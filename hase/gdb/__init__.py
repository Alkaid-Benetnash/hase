import binascii
import logging
import os
import os.path
import pty
import resource
import struct
import termios
import threading
import tty
import xml.etree.ElementTree as ET
from typing import IO, Any, Dict, List, Optional, Tuple, Union

from cle import ELF
from pygdbmi.gdbcontroller import GdbController

from ..errors import HaseError
from ..path import APP_ROOT
from ..symbex.state import State, StateManager
from ..symbex.cdanalyzer import CoredumpAnalyzer

l = logging.getLogger(__name__)


class GdbRegSpace:
    def __init__(self, active_state: State) -> None:
        # https://github.com/radare/radare2/blob/fe6372339da335bd08a8b568d95bb0bd29f24406/shlr/gdb/src/arch.c#L5
        self.names = [
            "rax",
            "rbx",
            "rcx",
            "rdx",
            "rsi",
            "rdi",
            "rbp",
            "rsp",
            "r8",
            "r9",
            "r10",
            "r11",
            "r12",
            "r13",
            "r14",
            "r15",
            "rip",
            "eflags",
            "cs",
            "ss",
            "ds",
            "es",
            "fs",
            "gs",
        ]
        self.active_state = active_state

    def __getitem__(self, name: str) -> str:
        if name in ["cs", "ss", "ds", "es"]:
            return "xx"
        try:
            reg = self.active_state.registers[name]
            if reg.size == 32:
                fmt = "<I"
            elif reg.size == 64:
                fmt = "<Q"
            else:
                raise HaseError("Unsupported bit width %d" % reg.size)
            packed = struct.pack(fmt, reg.value)
            return binascii.hexlify(packed).decode("ascii")
        except Exception:
            return "xx" * 8

    def __setitem__(self, name: str, value: int) -> None:
        return

    def read_all(self) -> str:
        values = ""
        for r in self.names:
            values += self.__getitem__(r)
        return values

    def write_all(self, values: str) -> None:
        return


class GdbMemSpace:
    def __init__(self, active_state: State, cda: CoredumpAnalyzer) -> None:
        self.active_state = active_state
        self.cda = cda

    def __getitem__(self, addr: int) -> str:
        # TODO: good idea to directly use coredump stack?
        value = self.active_state.memory[addr]
        if value is None:
            try:
                value = ord(self.active_state.simstate.project.loader.memory[addr])
            except Exception:
                value = None
            if value is None:
                # FIXME: weird, this works for rsp index accessing
                sec = self.active_state.simstate.memory.load(addr, 0x1)
                try:
                    value = self.active_state.eval(sec)
                except Exception:
                    value = None
        if value is None:
            return "xx"
        return "%.2x" % value

    def __setitem__(self, addr: int, value: int) -> None:
        # TODO: affect simstate memory
        return

    def read(self, addr: int, length: int) -> str:
        values = ""
        for offset in range(length):
            values += self.__getitem__(addr + offset)
        return values

    def write(self, addr: int, length: int, value: str) -> None:
        # TODO: affect simstate memory
        return


class GdbSharedLibrary:
    def __init__(self, active_state: State, pksize: int) -> None:
        self.active_state = active_state
        self.libs = []  # type: List[ELF]
        self.pksize = pksize
        self.tls_object = self.active_state.simstate.project.loader.tls_object
        loader = self.active_state.simstate.project.loader
        for lib in loader.shared_objects.values():
            if lib != loader.main_object:
                self.libs.append(lib)
        self.xml = None  # type: Optional[str]

    def make_xml(self, update: Optional[bool] = False) -> str:
        if not update and self.xml:
            return self.xml
        header = '<?xml version="1.0"?>'
        root = ET.Element("library-list-svr4", {"version": "1.0"})
        for lib in self.libs:
            h_ld = 0  # value of memory address of PT_DYNAMIC for current lib
            # TODO: Find a way to solve linked_map address. Maybe some solutions below
            # REF: https://reverseengineering.stackexchange.com/questions/6525/elf-link-map-when-linked-as-relro
            #    : https://code.woboq.org/userspace/glibc/elf/link.h.html
            # a_lm = 0  # address of linked_map

            for sec in lib.sections:
                if sec.name == ".dynamic":
                    h_ld = sec.vaddr

            # h_lm = active_state.simstate.memory.load(a_lm + 8, 0x8) # header address of link_map chain
            h_lm = 0
            # h_addr = active_state.simstate.memory.load(h_lm + 8, 0x8)
            h_addr = 0

            ET.SubElement(
                root,
                "library",
                {
                    "name": "/" + "/".join(lib.binary.split("/")[4:]),
                    "lm": hex(h_lm),
                    "l_addr": hex(h_addr),
                    "l_ld": hex(h_ld),
                },
            )
        body = ET.tostring(root)
        assert body is not None
        self.xml = header + str(body)
        return self.xml

    def validate_xml(self, xml: str) -> Tuple[bool, str]:
        from lxml import etree

        root = etree.XML(xml)
        dtd = etree.DTD(open("./library-list-svr4.dtd"))
        return dtd.validate(root), dtd.error_log.filter_from_errors()

    def read_xml(self, offset: int, size: int) -> str:
        prefix = "m"
        xml = self.make_xml()
        if offset > len(xml):
            return ""
        if size > self.pksize - 4:
            size = self.pksize - 4
        if size > len(xml) - offset:
            prefix = "l"
            size = len(xml) - offset
        return prefix + xml[offset : offset + size]


def create_pty() -> Tuple[IO[Any], str]:
    master_fd, slave_fd = pty.openpty()
    # disable echoing
    tty.setraw(master_fd, termios.TCSANOW)
    tty.setraw(slave_fd, termios.TCSANOW)
    ptsname = os.ttyname(slave_fd)
    os.close(slave_fd)
    # make i/o unbuffered
    return os.fdopen(master_fd, "wb+", 0), ptsname


PAGESIZE = resource.getpagesize()


def compute_checksum(data: str) -> int:
    return sum((ord(c) for c in data)) % 256


class GdbServer:
    def __init__(
        self,
        states: StateManager,
        binary: str,
        cda: CoredumpAnalyzer,
        active_state: Optional[State] = None,
    ) -> None:
        # FIXME: this binary is original path
        master, ptsname = create_pty()
        self.master = master
        self.COMMANDS = {
            "q": self.handle_query,
            "g": self.read_register_all,
            "G": self.write_register_all,
            "H": self.set_thread,
            "m": self.read_memory,
            "M": self.write_memory,
            "p": self.read_register,
            "P": self.write_register,
            "v": self.handle_long_commands,
            "X": self.write_memory_bin,
            "Z": self.insert_breakpoint,
            "z": self.remove_breakpoint,
            "?": self.stop_reason,
            "!": self.extend_mode,
        }
        self.states = states
        self.active_state = active_state if active_state else states.get_major(-1)
        self.regs = GdbRegSpace(self.active_state)
        self.mem = GdbMemSpace(self.active_state, cda)
        self.packet_size = PAGESIZE
        self.libs = GdbSharedLibrary(self.active_state, self.packet_size)
        self.gdb = GdbController(gdb_args=["--quiet", "--nx", "--interpreter=mi2"])
        self.gdb.write("-target-select remote %s" % ptsname, timeout_sec=10)
        self.thread = threading.Thread(target=self.run)
        self.thread.start()

        self.gdb.write("-file-exec-and-symbols %s" % binary, timeout_sec=100)
        self.gdb.write("set stack-cache off", timeout_sec=100)

    def update_active(self) -> None:
        self.regs.active_state = self.active_state
        self.mem.active_state = self.active_state
        self.libs.active_state = self.active_state
        self.write_request("c")

    def read_variables(self) -> List[Dict[str, Any]]:
        py_file = APP_ROOT.joinpath("gdb/gdb_get_locals.py")
        resp = self.write_request('python execfile ("{}")'.format(py_file))
        res = []
        for r in resp:
            if (
                "payload" in r.keys()
                and isinstance(r["payload"], str)
                and r["payload"].startswith("ARGS:")
            ):
                l = r["payload"].split(" ")
                name = l[1]
                tystr = l[2].replace("%", " ")
                idr = int(l[3])
                addr_comment = l[4].strip().replace("\\n", "")
                if "&" in addr_comment:
                    if idr == 1:
                        ll = addr_comment.partition("&")
                        addr = int(ll[0], 16)  # type: Union[str, int]
                        comment = ll[2]
                else:
                    if idr == 1:
                        addr = int(addr_comment, 16)
                        comment = ""
                    else:
                        addr = addr_comment
                        comment = ""
                size = int(l[5].strip().replace("\\n", ""))
                res.append(
                    {
                        "name": name,
                        "type": tystr,
                        "loc": idr,
                        "addr": addr,
                        "size": size,
                        "comment": comment,
                    }
                )
        return res

    def eval_expression(self, expr: str) -> None:
        res = self.gdb.write("-data-evaluate-expression %s" % expr, timeout_sec=99999)
        print(res)

    def write_request(self, req: str, **kwargs: Any) -> List[Dict[str, Any]]:
        timeout_sec = kwargs.pop("timeout_sec", 10)
        kwargs["read_response"] = False
        self.gdb.write(req, timeout_sec=timeout_sec, **kwargs)
        resp = []  # type: List[Dict[str, Any]]
        while True:
            try:
                resp += self.gdb.get_gdb_response()
            except Exception:
                break
        return resp

    def run(self) -> None:
        l.info("start server gdb server")
        buf = ""
        while True:
            try:
                data = os.read(self.master.fileno(), PAGESIZE)
            except OSError as e:
                l.info("gdb connection was closed: %s", e)
                return

            if len(data) == 0:
                l.debug("gdb connection was closed")
            buf += data.decode("utf-8")
            buf = self.process_data(buf)

    def process_data(self, buf: str) -> str:
        while len(buf):
            if buf[0] == "+" or buf[0] == "-":
                buf = buf[1:]
                if len(buf) == 0:
                    return buf
            if "$" not in buf:
                return buf
            begin = buf.index("$") + 1
            end = buf.index("#")
            if begin >= 0 and end < len(buf):
                packet = buf[begin:end]
                checksum = int(buf[end + 2], 16)
                checksum += int(buf[end + 1], 16) << 4
                assert checksum == compute_checksum(packet)

                self.process_packet(packet)
                buf = buf[end + 3 :]
        return buf

    def write_ack(self) -> None:
        self.master.write("+")
        self.master.flush()

    def process_packet(self, packet: str) -> None:
        handler = self.COMMANDS.get(packet[0], None)

        request = "".join(packet[1:])
        l.warning("<-- %s%s" % (packet[0], request))

        if handler is None:
            l.warning("unknown command %s%s received" % (packet[0], request))
            response = ""
        else:
            response = handler(request)
        self.write_response(response)

    def write_response(self, response: str) -> None:
        # Each packet should be acknowledged with a single character.
        # '+' to indicate satisfactory receipt
        l.warning("--> %s" % response)
        s = "+$%s#%.2x" % (response, compute_checksum(response))
        self.master.write(s.encode("utf-8"))
        self.master.flush()

    def extend_mode(self, packet: str) -> str:
        """
        !
        """
        return "OK"

    def read_register_all(self, packet: str) -> str:
        """
        g
        """
        return self.regs.read_all()

    def write_register_all(self, packet: str) -> str:
        """
        G XX...
        """
        self.regs.write_all(packet)
        return "OK"

    def read_register(self, packet: str) -> str:
        """
        p n
        """
        n = int(packet, 16)
        # FIXME: gdb request out of range while gdb info frame
        if n < len(self.regs.names):
            return self.regs[self.regs.names[n]]
        return "ffffffff"

    def write_register(self, packet: str) -> str:
        """
        P n...=r...
        """
        n_, r_ = packet.split("=")
        n = int(n_, 16)
        r = int(r_, 16)
        if n < len(self.regs.names):
            self.regs[self.regs.names[n]] = r
        return "OK"

    def set_thread(self, packet: str) -> str:
        """
        H op thread-id
        """
        return "OK"

    def read_memory(self, packet: str) -> str:
        """
        m addr,length
        """
        addr_, length_ = packet.split(",")
        addr = int(addr_, 16)
        length = int(length_, 16)
        return self.mem.read(addr, length)

    def write_memory(self, packet: str) -> str:
        """
        M addr,length:XX
        """
        l = packet.split(",")
        addr_ = l[0]
        length_, value = l[1].split(":")
        addr = int(addr_, 16)
        length = int(length_, 16)
        self.mem.write(addr, length, value)
        return "OK"

    def write_memory_bin(self, packet: str) -> str:
        """
        X addr,length:XX(bin)
        """
        pass

    def insert_breakpoint(self, packet: str) -> str:
        """
        Z type,addr,kind
        type:   0 software (0xcc)
                1 hardware (drx)
                2 write watchpoint
                3 read watchpoint
        """
        return "OK"

    def remove_breakpoint(self, packet: str) -> str:
        """
        z type,addr,kind
        """
        return "OK"

    def stop_reason(self, packet: str) -> str:
        GDB_SIGNAL_TRAP = 5
        return "S%.2x" % GDB_SIGNAL_TRAP

    def handle_long_commands(self, packet: str) -> str:
        def handle_cont(action: str, tid: Optional[int] = None) -> str:
            # TODO: for a continue/step/stop operation
            self.write_response("T05library:r;")
            return "S05"

        if packet.startswith("Cont"):
            supported_action = ["", "c", "s", "t"]  # TODO: C sig/S sig/r start,end
            packet = packet[4:]
            if packet == "?":
                return ";".join(supported_action)
            action = packet.split(";")[1]
            action = action.split(":")[0]
            if action in supported_action:
                return handle_cont(action)
            l.warning("unknown command: v%s", "Cont" + packet)
            return ""

        if packet.startswith("CtrlC"):
            return "OK"

        if packet.startswith("MustReplyEmpty"):
            return ""
        else:
            l.warning("unknown command: v%s", packet)
            return ""

    def handle_query(self, packet: str) -> str:
        """
        qSupported|qAttached|qC
        qXfer:...:read:annex:offset,size
        """

        if packet.startswith("Supported"):
            features = [
                "qXfer:libraries-svr4:read+",
                # 'qXfer:memory-map:read+'
            ]
            features.append("PacketSize=%x" % self.packet_size)
            return ";".join(features)
        elif packet.startswith("Xfer"):
            reqs = packet.split(":")
            # FIXME: not working now
            if reqs[1] == "libraries-svr4" and reqs[2] == "read":
                data = reqs[4].split(",")
                return self.libs.read_xml(int(data[0], 16), int(data[1], 16))
            if reqs[1] == "memory-map" and reqs[2] == "read":
                # TODO: add memory-map, (do we really need it now?)
                return ""
            return ""
        elif packet.startswith("Attached"):
            return "1"
        elif packet.startswith("C"):
            # FIXME real thread id
            return ""  # empty means no threads
        elif packet.startswith("fThreadInfo"):
            return "m0"
        elif packet.startswith("sThreadInfo"):
            return "l"
        elif packet.startswith("TStatus"):
            # catch all for all commands we know and don't want to implement
            return ""
        elif packet.startswith("Symbol"):
            if packet == "Symbol::":
                return "OK"
            _, sym_value, sym_name = packet.split(":")
            return "OK"
        else:
            l.warning("unknown query: %s", packet)
            return ""
