import ctypes
import gc
import logging
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

import angr
import archinfo
from angr import SimState
from angr import sim_options as so
from capstone import x86_const

from ..errors import HaseError
from ..pt.events import Instruction, InstructionClass
from ..pwn_wrapper import ELF, Coredump, Mapping
from .cdanalyzer import CoredumpAnalyzer
from .filter import FilterTrace
from .hook import setup_project_hook
from .rspsolver import solve_rsp
from .state import State, StateManager

l = logging.getLogger(__name__)


class Tracer:
    def __init__(
        self,
        executable: str,
        trace: List[Instruction],
        coredump: Coredump,
        load_options: Dict[str, Any],
    ) -> None:
        self.executable = executable
        self.project = angr.Project(executable, **load_options)

        self.coredump = coredump
        self.debug_unsat: Optional[SimState] = None

        self.trace = trace

        assert self.project.loader.main_object.os.startswith("UNIX")

        self.elf = ELF(executable)

        start = self.elf.symbols.get("_start")
        main = self.elf.symbols.get("main")

        self.cdanalyzer = CoredumpAnalyzer(
            self.elf, self.coredump, load_options["lib_opts"]
        )

        for (idx, event) in enumerate(self.trace):
            if event.ip == start or event.ip == main:
                self.trace = trace[idx:]

        add_options = {
            so.TRACK_JMP_ACTIONS,
            so.CONSERVATIVE_READ_STRATEGY,
            so.CONSERVATIVE_WRITE_STRATEGY,
            so.BYPASS_UNSUPPORTED_IRCCALL,
            so.BYPASS_UNSUPPORTED_IRDIRTY,
            so.CONSTRAINT_TRACKING_IN_SOLVER,
            # so.DOWNSIZE_Z3,
        }

        remove_simplications = {
            so.LAZY_SOLVES,
            so.EFFICIENT_STATE_MERGING,
            so.TRACK_CONSTRAINT_ACTIONS,
            # so.ALL_FILES_EXIST, # the problem is, when having this, simfd either None or exist, no If
        } | so.simplification

        self.use_hook = True
        hooked_symbols, omitted_section = setup_project_hook(
            self.project, self.cdanalyzer.gdb
        )

        self.filter = FilterTrace(
            self.project,
            self.trace,
            hooked_symbols,
            self.cdanalyzer.gdb,
            omitted_section,
            self.elf.statically_linked,
        )

        self.old_trace = self.trace
        self.trace, self.trace_idx, self.hook_target = self.filter.filtered_trace()
        self.hook_plt_idx = list(self.hook_target.keys())
        self.hook_plt_idx.sort()
        self.filter.entry_check()

        start_address = self.trace[0].ip

        args = [self.coredump.argc]
        args += [self.coredump.string(argv) for argv in self.coredump.argv]
        self.start_state = self.project.factory.call_state(
            start_address,
            *args,
            add_options=add_options,
            remove_options=remove_simplications,
        )
        rsp, _ = solve_rsp(self.start_state, self.cdanalyzer)
        self.start_state.regs.rsp = rsp

        l.info(
            "Trace length: {} | OldTrace length: {}".format(
                len(self.trace), len(self.old_trace)
            )
        )

        self.setup_argv()

    def desc_trace(self, start, end=None, filt=None):
        for i, inst in enumerate(self.trace[start:end]):
            if not filt or filt(inst.ip):
                print(
                    i + start,
                    self.trace_idx[i + start],
                    hex(inst.ip),
                    self.project.loader.describe_addr(inst.ip),
                )

    def desc_old_trace(self, start, end=None, filt=None):
        for i, inst in enumerate(self.old_trace[start:end]):
            if not filt or filt(inst.ip):
                print(
                    i + start, hex(inst.ip), self.project.loader.describe_addr(inst.ip)
                )

    def desc_addr(self, addr):
        return self.project.loader.describe_addr(addr)

    def desc_callstack(self):
        callstack = self.debug_state[-1].callstack
        for i, c in enumerate(callstack):
            print(
                "Frame {}: {} => {}, sp = {}".format(
                    i,
                    self.desc_addr(c.call_site_addr),
                    self.desc_addr(c.func_addr),
                    hex(c.stack_ptr),
                )
            )

    def setup_argv(self) -> None:
        # argv follows argc
        argv_addr = self.coredump.argc_address + ctypes.sizeof(ctypes.c_int)
        # TODO: if argv is modified by users, this won't help
        for i in range(len(self.coredump.argv)):
            self.start_state.memory.store(
                argv_addr + i * 8, self.coredump.argv[i], endness=archinfo.Endness.LE
            )
            self.start_state.memory.store(
                self.coredump.argv[i],
                self.coredump.string(self.coredump.argv[i])[::-1],
                endness=archinfo.Endness.LE,
            )

    def repair_exit_handler(self, state: SimState, step: SimState) -> SimState:
        artifacts = getattr(step, "artifacts", None)
        if (
            artifacts
            and "procedure" in artifacts.keys()
            and artifacts["name"] == "exit"
        ):
            if len(state.libc.exit_handler):
                addr = state.libc.exit_handler[0]
                step = self.project.factory.successors(
                    state, num_inst=1, force_addr=addr
                )
        return step

    def repair_alloca_ins(self, state: SimState) -> None:
        # NOTE: alloca problem, focus on sub rsp, rax
        # Typical usage: alloca(strlen(x))
        capstone = state.block().capstone
        first_ins = capstone.insns[0].insn
        if first_ins.mnemonic == "sub":
            if (
                first_ins.operands[0].reg
                in (x86_const.X86_REG_RSP, x86_const.X86_REG_RBP)
                and first_ins.operands[1].type == 1
            ):
                reg_name = first_ins.reg_name(first_ins.operands[1].reg)
                reg_v = getattr(state.regs, reg_name)
                if state.solver.symbolic(reg_v):
                    setattr(state.regs, reg_name, state.libc.max_str_len)

    def repair_jump_ins(
        self,
        state: SimState,
        previous_instruction: Instruction,
        instruction: Instruction,
    ) -> Tuple[bool, str]:
        # NOTE: typical case: switch(getchar())

        if previous_instruction.iclass == InstructionClass.ptic_other:
            return False, ""
        jump_ins = ["jmp", "call"]  # currently not deal with jcc regs
        capstone = state.block().capstone
        first_ins = capstone.insns[0].insn
        ins_repr = first_ins.mnemonic
        if ins_repr.startswith("ret"):
            if not state.solver.symbolic(state.regs.rsp):
                mem = state.memory.load(state.regs.rsp, 8)
                jump_target = 0
                if not state.solver.symbolic(mem):
                    jump_target = state.solver.eval(mem)
                if jump_target != instruction.ip:
                    return True, "ret"
                else:
                    return True, "ok"
            else:
                return True, "ret"

        for ins in jump_ins:
            if ins_repr.startswith(ins):
                # call rax
                if first_ins.operands[0].type == 1:
                    reg_name = first_ins.op_str
                    reg_v = getattr(state.regs, reg_name)
                    if (
                        state.solver.symbolic(reg_v)
                        or state.solver.eval(reg_v) != instruction.ip
                    ):
                        setattr(state.regs, reg_name, instruction.ip)
                        return True, ins

                # jmp 0xaabb
                if first_ins.operands[0].type == 2:
                    return True, ins

                # jmp [base + index*scale + disp]
                if first_ins.operands[0].type == 3:
                    self.last_jump_table = state
                    mem = first_ins.operands[0].value.mem
                    target = mem.disp
                    if mem.index:
                        reg_index_name = first_ins.reg_name(mem.index)
                        reg_index = getattr(state.regs, reg_index_name)
                        if state.solver.symbolic(reg_index):
                            return True, ins
                        else:
                            target += state.solver.eval(reg_index) * mem.scale
                    if mem.base:
                        reg_base_name = first_ins.reg_name(mem.base)
                        reg_base = getattr(state.regs, reg_base_name)
                        if state.solver.symbolic(reg_base):
                            return True, ins
                        else:
                            target += state.solver.eval(reg_base)
                    ip_mem = state.memory.load(target, 8, endness="Iend_LE")
                    if not state.solver.symbolic(ip_mem):
                        jump_target = state.solver.eval(ip_mem)
                        if jump_target != instruction.ip:
                            return True, ins
                        else:
                            return True, "ok"
                    else:
                        return True, ins
        return False, "ok"

    def repair_ip(self, state: SimState) -> int:
        try:
            addr = state.solver.eval(state._ip)
            # NOTE: repair IFuncResolver
            if (
                self.project.loader.find_object_containing(addr)
                == self.project.loader.extern_object
            ):
                func = self.project._sim_procedures.get(addr, None)
                if func:
                    funcname = func.kwargs["funcname"]
                    libf = self.project.loader.find_symbol(funcname)
                    if libf:
                        addr = libf.rebased_addr
        except Exception:
            logging.exception("Error while repairing ip")
            # NOTE: currently just try to repair ip for syscall
            addr = self.debug_state[-2].addr
        return addr

    def repair_func_resolver(self, state: SimState, step: SimState) -> SimState:
        artifacts = getattr(step, "artifacts", None)
        if (
            artifacts
            and "procedure" in artifacts.keys()
            and artifacts["name"] == "IFuncResolver"
        ):
            func = self.filter.find_function(self.debug_state[-2].addr)
            if func:
                addr = self.project.loader.find_symbol(func.name).rebased_addr
                step = self.project.factory.successors(
                    state, num_inst=1, force_addr=addr
                )
            else:
                raise HaseError("Cannot resolve function")
        return step

    def last_match(self, choice: SimState, instruction: Instruction) -> bool:
        # if last trace is A -> A
        if (
            instruction == self.trace[-1]
            and len(self.trace) > 2
            and self.trace[-1].ip == self.trace[-2].ip
        ):
            if choice.addr == instruction.ip:
                l.debug("jump 0%x -> 0%x", choice.addr, choice.addr)
                return True
        return False

    def jump_match(
        self,
        old_state: SimState,
        choice: SimState,
        previous_instruction: Instruction,
        instruction: Instruction,
    ) -> bool:
        if choice.addr == instruction.ip:
            l.debug("jump 0%x -> 0%x", previous_instruction.ip, choice.addr)
            return True
        return False

    def repair_satness(self, old_state: SimState, new_state: SimState) -> None:
        if not new_state.solver.satisfiable():
            new_state.solver._stored_solver = old_state.solver._solver.branch()

            if not self.debug_unsat:
                self.debug_sat = old_state
                self.debug_unsat = new_state

    def repair_ip_at_syscall(self, old_state: SimState, new_state: SimState) -> None:
        capstone = old_state.block().capstone
        first_ins = capstone.insns[0].insn
        ins_repr = first_ins.mnemonic
        if ins_repr.startswith("syscall"):
            new_state.regs.ip_at_syscall = new_state.ip

    def post_execute(self, old_state: SimState, state: SimState) -> None:
        self.repair_satness(old_state, state)
        self.repair_ip_at_syscall(old_state, state)

    def repair_syscall_jump(self, old_state: SimState, step: SimState) -> SimState:
        capstone = old_state.block().capstone
        first_ins = capstone.insns[0].insn
        ins_repr = first_ins.mnemonic
        # manually syscall will have no entry and just execute it.
        if (
            ins_repr.startswith("syscall")
            and 0x3000000 <= step.successors[0].reg_concrete("rip") < 0x3002000
        ):
            return step.successors[0].step(num_inst=1)
        return step

    def execute(
        self,
        state: SimState,
        previous_instruction: Instruction,
        instruction: Instruction,
        index: int,
    ) -> Tuple[SimState, SimState]:
        self.debug_state.append(state)
        force_jump, force_type = self.repair_jump_ins(
            state, previous_instruction, instruction
        )
        self.repair_alloca_ins(state)

        try:
            step = self.project.factory.successors(
                state, num_inst=1  # , force_addr=addr
            )
            step = self.repair_syscall_jump(state, step)
            step = self.repair_func_resolver(state, step)
            step = self.repair_exit_handler(state, step)
        except Exception:
            logging.exception(
                "Error while finding successor on instruction "
                + repr(previous_instruction)
                + " "
                + self.project.loader.describe_addr(previous_instruction.ip))
            raise
            new_state = state.copy()
            new_state.regs.ip = instruction.ip
            self.post_execute(state, new_state)
            return state, new_state

        if force_jump:
            new_state = state.copy()
            if force_type == "call":
                if not self.project.is_hooked(instruction.ip):
                    new_state.regs.rsp -= 8
                    ret_addr = state.addr + state.block().capstone.insns[0].size
                    new_state.memory.store(
                        new_state.regs.rsp, ret_addr, endness="Iend_LE"
                    )
            elif force_type == "ret":
                new_state.regs.rsp += 8
            new_state.regs.ip = instruction.ip
            all_choices = {"sat": [new_state], "unsat": [], "unconstrained": []}
            choices = [new_state]
        else:
            all_choices = {
                "sat": step.successors,
                "unsat": step.unsat_successors,
                "unconstrained": step.unconstrained_successors,
            }
            choices = []
            choices += all_choices["sat"]
            choices += all_choices["unsat"]

        old_state = state
        l.info(
            repr(state)
            + " "
            + repr(previous_instruction)
            + " "
            + repr(instruction)
            + "\n"
        )
        for choice in choices:
            # HACKS: if ip is symbolic
            try:
                if self.last_match(choice, instruction):
                    return choice, choice
                if self.jump_match(
                    old_state, choice, previous_instruction, instruction
                ):
                    self.post_execute(old_state, choice)
                    return old_state, choice
            except angr.SimValueError:
                logging.exception("Error while jumping")
                pass
        new_state = state.copy()
        new_state.regs.ip = instruction.ip
        return state, new_state

    def valid_address(self, address: int) -> bool:
        return self.project.loader.find_object_containing(address)

    def constrain_registers(self, state: State) -> bool:
        # FIXME: if exception caught is omitted by hook?
        # If same address, then give registers
        if state.registers["rip"].value == self.coredump.registers["rip"]:
            # don't give rbp, rsp
            assert state.registers["rsp"].value == self.coredump.registers["rsp"]
            registers = [
                "gs",
                "rip",
                "rdx",
                "r15",
                "rax",
                "rsi",
                "rcx",
                "r14",
                "fs",
                "r12",
                "r13",
                "r10",
                "r11",
                "rbx",
                "r8",
                "r9",
                "eflags",
                "rdi",
            ]
            for name in registers:
                state.registers[name] = self.coredump.registers[name]
            return True
        else:
            l.warning("RIP mismatch.")
            coredump = self.coredump
            arip = state.simstate.regs.rip
            crip = hex(coredump.registers["rip"])
            arsp = state.simstate.regs.rsp
            crsp = hex(coredump.registers["rsp"])
            l.warning(f"{arip} {crip} {arsp} {crsp}")
        return False

    def run(self) -> StateManager:
        simstate = self.start_state
        states = StateManager(self, len(self.trace) + 1)
        states.add_major(State(0, None, self.trace[0], None, simstate))
        self.debug_unsat: Optional[SimState] = None
        self.debug_state: deque = deque(maxlen=10)
        self.skip_addr: Dict[int, int] = {}
        cnt = -1
        interval = max(1, len(self.trace) // 200)
        length = len(self.trace) - 1
        trace = self.trace[0:]
        trace.append(trace[-1])

        # prev_instr.ip == state.ip
        for previous_idx in range(len(trace) - 1):
            previous_instruction = trace[previous_idx]
            instruction = trace[previous_idx + 1]
            cnt += 1
            if not cnt % 500:
                gc.collect()
            l.debug(
                "look for jump: 0x%x -> 0x%x"
                % (previous_instruction.ip, instruction.ip)
            )
            assert self.valid_address(previous_instruction.ip) and self.valid_address(
                instruction.ip
            )
            try:
                old_simstate, new_simstate = self.execute(
                    simstate, previous_instruction, instruction, cnt
                )
            except:
                import ipdb; ipdb.set_trace()
            simstate = new_simstate
            if cnt % interval == 0 or length - cnt < 15:
                states.add_major(
                    State(
                        cnt,
                        previous_instruction,
                        instruction,
                        old_simstate,
                        new_simstate,
                    )
                )
            if (
                self.project.loader.find_object_containing(instruction.ip)
                == self.project.loader.main_object
            ):
                states.last_main_state = State(
                    cnt, previous_instruction, instruction, old_simstate, new_simstate
                )

        self.constrain_registers(states.major_states[-1])

        return states
