import imp
import logging
import os
import os.path
import sys
from pathlib import Path
from shlex import split as shsplit
from types import ModuleType
from typing import Any, Callable

from IPython import get_ipython
from IPython.core.interactiveshell import InteractiveShell
from IPython.core.magic import Magics, line_magic, magics_class
from PyQt5 import QtWidgets

from . import MainWindow
from .. import annotate, gdb
from ..path import find_in_path
from ..record import DEFAULT_LOG_DIR
from ..replay import replay_trace

l = logging.getLogger("hase")


class HaseFrontEndException(Exception):
    pass


def op_restrict(low: int = 0, high: int = 65536) -> Callable[[int, int], bool]:
    def comp(actual: int, given: int) -> bool:
        return low <= actual <= high

    return comp


def op_eq(actual: Any, given: Any) -> bool:
    return actual == given


# only for function in Magics class
# FIXME: inherit documentation (maybe by functools.wraps)
# TODO: is there same way to get line_magic name instead of manually setting?
def args(*param_names: str, **kwargs: Any) -> Callable:
    def func_wrapper(func: Callable) -> Callable:
        name = kwargs.pop("name", func.__name__)
        comp = kwargs.pop("comp", op_eq)
        info = kwargs.pop("usage", None)

        def recv_args(inst: str, query: str) -> None:
            param = shsplit(query)
            if not comp(len(param), len(param_names)):
                if not info:
                    print("USAGE: {} {}".format(name, "".join(param_names)))
                else:
                    print("USAGE: {}".format(info))
                return
            func(inst, query)

        # __wrapped__ is coming from functools
        recv_args.__name__ = func.__wrapped__.__name__  # type: ignore
        recv_args.__doc__ = func.__wrapped__.__doc__  # type: ignore
        return recv_args

    return func_wrapper


@magics_class
class HaseMagics(Magics):
    def __init__(self, shell: InteractiveShell) -> None:
        if shell is not None:
            self.user_ns = shell.user_ns
        else:
            # happens during initialisation of ipython
            self.user_ns = None
        self.shell = shell
        super(HaseMagics, self).__init__(shell)

    @property
    def app(self) -> QtWidgets.QApplication:
        return self.user_ns["app"]

    @property
    def window(self) -> MainWindow:
        return self.user_ns["window"]

    @args("<source_code>", name="show")
    @line_magic("show")
    def show_source(self, query: str) -> None:
        self.window.set_location(query, 0)

    @args()
    @line_magic("refresh")
    def refresh(self, query: str) -> None:
        self.window.time_slider.setValue(0)
        self.window.clear_viewer()
        self.window.append_archive()

    @args()
    @line_magic("reload_hase")
    def reload_hase(self, query: str) -> None:
        module_path = os.path.dirname(os.path.dirname(__file__))
        for name, m in sys.modules.items():
            if isinstance(m, ModuleType) and hasattr(m, "__file__"):
                if m.__file__ is not None and m.__file__.startswith(module_path):
                    print("reload %s" % name)
                    try:
                        imp.reload(m)
                    except Exception as e:
                        print("error while loading %s" % e)
        self.shell.extension_manager.reload_extension(__name__)

    @args("<report_archive>")
    @line_magic("load")
    def load(self, query: str) -> None:
        self.window.clear_cache()
        user_ns = self.shell.user_ns
        if not Path(query).exists():
            query = str(DEFAULT_LOG_DIR.joinpath(query))
        if not Path(query).exists():
            raise HaseFrontEndException("Report archive not exist")
        with replay_trace(query) as rep:
            user_ns["tracer"] = rep.tracer
            executable = rep.executable
            states, _ = rep.run()
            addr2line = annotate.Addr2line()
            # NOTE: we calculate all trace instead of state
            for instr in rep.tracer.trace:
                obj = rep.tracer.project.loader.find_object_containing(instr.ip)
                if obj in rep.tracer.project.loader.all_elf_objects:
                    addr2line.add_addr(obj, instr.ip)
            addr_map = addr2line.compute()

        self.active_state = states.major_states[-1]

        user_ns["addr_map"] = addr_map
        user_ns["states"] = states
        user_ns["executable"] = executable
        user_ns["coredump"] = user_ns["tracer"].coredump
        user_ns["active_state"] = self.active_state

        for k, v in addr_map.items():
            if not Path(v[0]).exists():
                origin_f = v[0]
                print("\nCannot resolve filename: {} at {}".format(origin_f, hex(k)))
                d = input(
                    "Try to manually set file path for {}: ".format(
                        os.path.basename(origin_f)
                    )
                )
                if d == "pass-all" or d == "":
                    break
                new_f = find_in_path(origin_f, [d])

                for i, p in addr_map.items():
                    if not Path(p[0]).exists():
                        if p[0] == origin_f and i != k:
                            addr_map[i] = (new_f, p[1])
                addr_map[k] = (new_f, v[1])

        l.info("Caching tokens")
        self.window.cache_tokens(addr_map)
        l.info("Add states")
        # self.window.add_states(user_ns["states"], user_ns["tracer"])
        self.window.enable_buttons()
        self.window.set_slider(user_ns["addr_map"], user_ns["states"])
        self.window.set_location(*addr_map[self.active_state.address()])
        self.window.cache_coredump_constraints()
        self.gdb_init("")

    @args(info="USAGE: info")
    @line_magic("info")
    def gdb_information(self, query: str) -> None:
        self.gdb_update("")
        user_ns = self.shell.user_ns
        addr_map = user_ns["addr_map"]
        active_state = user_ns["active_state"]
        self.window.set_regs()
        if addr_map[active_state.address()][0] != "??":
            user_ns["gdbs"].write_request("bt")
            self.window.set_variable()
        else:
            print("Cannot retrieve variables on unresolvable source code")

    @args(info="USAGE: init")
    @line_magic("init")
    def gdb_init(self, query: str) -> None:
        user_ns = self.shell.user_ns
        if "gdbs" in user_ns.keys():
            user_ns["gdbs"].gdb.exit()
        states = user_ns["states"]
        active_state = user_ns["active_state"]
        addr_map = user_ns["addr_map"]
        executable = user_ns["executable"]
        user_ns["gdbs"] = gdb.GdbServer(
            states, executable, user_ns["tracer"].cdanalyzer, active_state
        )
        user_ns["gdbs"].write_request(
            "dir {}".format(
                ":".join([os.path.dirname(str(p)) for p, _ in addr_map.values()])
            )
        )
        user_ns["gdbs"].write_request("info sharedlibrary")
        user_ns["gdbs"].write_request("info sharedlibrary")
        for lib in user_ns["gdbs"].libs.libs:
            libname = os.path.basename(lib.binary)
            print("Loading: {}".format(libname))
            user_ns["gdbs"].write_request("sharedlibrary {}".format(libname))

    @args(info="USAGE: update")
    @line_magic("update")
    def gdb_update(self, query: str) -> None:
        user_ns = self.shell.user_ns
        user_ns["gdbs"].active_state = user_ns["active_state"]
        user_ns["gdbs"].update_active()

    @line_magic("p")
    def print_value(self, query: str) -> int:
        """
        open current breakpoint in editor.
        """
        return 10

    @line_magic("backtrace")
    def backtrace(self, query: str) -> None:
        """
        open current breakpoint in editor.
        """
        print(self.active_state.simstate.callstack)

    @args(comp=op_restrict(1), info="USAGE: gdb ...")
    @line_magic("gdb")
    def gdb_angr(self, query: str) -> None:
        try:
            resp = self.shell.user_ns["gdbs"].write_request(query)
            for r in resp:
                if r["payload"]:
                    print(r["payload"].replace("\\n", "\n").replace("\\t", "\t"))
        except Exception:
            pass

    @args(comp=op_restrict(1), info="USAGE: gdb-core ...")
    @line_magic("gdb-core")
    def gdb_core(self, query: str) -> None:
        try:
            resp = self.shell.user_ns["tracer"].cdanalyzer.gdb.write_request(query)
            for r in resp:
                if r["payload"]:
                    print(r["payload"].replace("\\n", "\n").replace("\\t", "\t"))
        except Exception:
            pass


# get_ipython will be magically set by ipython
ip = get_ipython()
hase_magics = HaseMagics(ip)
ip.register_magics(hase_magics)
