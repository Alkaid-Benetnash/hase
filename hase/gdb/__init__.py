from __future__ import absolute_import, division, print_function

import pty
import os
import os.path
import logging
import tty
import threading
import resource
import termios
import struct
import xml.etree.ElementTree as ET
from pygdbmi.gdbcontroller import GdbController
from typing import Tuple, IO, Any, Optional

from ..symbex.state import State

logging.basicConfig()
l = logging.getLogger(__name__)


class GdbRegSpace(object):
    def __init__(self, active_state):
        # https://github.com/radare/radare2/blob/fe6372339da335bd08a8b568d95bb0bd29f24406/shlr/gdb/src/arch.c#L5
        self.names = [
            "rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rbp", "rsp", "r8", "r9",
            "r10", "r11", "r12", "r13", "r14", "r15", "rip", "eflags", "cs",
            "ss", "ds", "es", "fs", "gs"
        ]
        self.active_state = active_state

    def __getitem__(self, name):
        # type: (str) -> str
        if name in ["cs", "ss", "ds", "es"]:
            return "xx"
        reg = self.active_state.registers[name]
        if reg.size == 32:
            fmt = "<I"
        elif reg.size == 64:
            fmt = "<Q"
        else:
            raise Exception("Unsupported bit width %d" % reg.size)
        return struct.pack(fmt, reg.value).encode("hex")

    def __setitem__(self, name, value):
        # type: (str, int) -> None
        # TODO: affect simstate registers
        return

    def read_all(self):
        # type: () -> str
        values = ""
        for r in self.names:
            values += self.__getitem__(r)
        return values

    def write_all(self, values):
        # type: (str) -> None
        # TODO: affect simstate registers
        # TODO: exception handling
        return


class GdbMemSpace(object):
    def __init__(self, active_state, cda):
        self.active_state = active_state
        self.cda = cda
        self.stack_offset = self.cda.registers['rsp'] - self.active_state.registers['rsp'].value
        self.stack_start = self.cda.stack_start - self.stack_offset
        self.stack_stop = self.cda.stack_stop - self.stack_offset

    def __getitem__(self, addr):
        # type: (int) -> str
        # TODO: good idea to directly use coredump stack?
        value = self.active_state.memory[addr]
        if value is None:
            try:
                value = ord(
                    self.active_state.simstate.project.loader.memory[addr])
            except:
                value = None
            if value is None:
                # FIXME: weird, this works for rsp index accessing
                sec = self.active_state.simstate.memory.load(addr, 0x1)
                try:
                    value = self.active_state.eval(sec)
                except:
                    value = None
        if value is None:
            return "ff"
        return "%.2x" % value

    def __setitem__(self, addr, value):
        # type: (int, int) -> None
        # TODO: affect simstate memory
        return

    def read(self, addr, length):
        # type: (int, int) -> str
        values = ""
        for offset in range(length):
            values += self.__getitem__(addr + offset)
        return values

    def write(self, addr, length, value):
        # type: (int, int, str) -> None
        # TODO: affect simstate memory
        return


class GdbSharedLibrary():
    def __init__(self, active_state, pksize):
        self.active_state = active_state
        self.libs = []
        self.pksize = pksize
        self.tls_object = self.active_state.simstate.project.loader.tls_object
        loader = self.active_state.simstate.project.loader
        for lib in loader.shared_objects.values():
            if lib != loader.main_object:
                self.libs.append(lib)
        self.xml = None

    def make_xml(self, update=False):
        # type: (Optional[bool]) -> str
        if not update and self.xml:
            return self.xml
        header = '<?xml version="1.0"?>'
        root = ET.Element('library-list-svr4', {'version': '1.0'})
        for lib in self.libs:
            h_ld = 0  # value of memory address of PT_DYNAMIC for current lib
            # TODO: Find a way to solve linked_map address. Maybe some solutions below
            # REF: https://reverseengineering.stackexchange.com/questions/6525/elf-link-map-when-linked-as-relro
            #    : https://code.woboq.org/userspace/glibc/elf/link.h.html
            a_lm = 0 # address of linked_map

            for sec in lib.sections:
                if sec.name == '.dynamic':
                    h_ld = sec.vaddr

            # h_lm = active_state.simstate.memory.load(a_lm + 8, 0x8) # header address of link_map chain
            h_lm = 0
            # h_addr = active_state.simstate.memory.load(h_lm + 8, 0x8)
            h_addr = 0
            
            ET.SubElement(
                root, 'library', {
                    'name': '/' + '/'.join(lib.binary.split('/')[4:]),
                    'lm': hex(h_lm),
                    'l_addr': hex(h_addr),
                    'l_ld': hex(h_ld),
                })
        self.xml = header + ET.tostring(root)
        return self.xml

    def validate_xml(self, xml):
        # type: (str) -> Tuple[bool, str]
        from lxml import etree
        root = etree.XML(xml)
        dtd = etree.DTD(open("./library-list-svr4.dtd"))
        return dtd.validate(root), dtd.error_log.filter_from_errors()

    def read_xml(self, offset, size):
        # type: (int, int) -> str
        prefix = 'm'
        xml = self.make_xml()
        if offset > len(xml):
            return ''
        if size > self.pksize - 4:
            size = self.pksize - 4
        if size > len(xml) - offset:
            prefix = 'l'
            size = len(xml) - offset
        return prefix + xml[offset:offset + size]


def create_pty():
    # type: () -> Tuple[IO[Any], str]
    master_fd, slave_fd = pty.openpty()
    # disable echoing
    tty.setraw(master_fd, termios.TCSANOW)
    tty.setraw(slave_fd, termios.TCSANOW)
    ptsname = os.ttyname(slave_fd)
    os.close(slave_fd)
    # make i/o unbuffered
    return os.fdopen(master_fd, "rw+", 0), ptsname


PAGESIZE = resource.getpagesize()


def compute_checksum(data):
    # type: (str) -> int
    return sum((ord(c) for c in data)) % 256


class GdbServer(object):
    def __init__(self, active_state, binary, cda):
        # type: (State, str, Any) -> None
        master, ptsname = create_pty()
        self.master = master
        self.COMMANDS = {
            'q': self.handle_query,
            'g': self.read_register_all,
            'G': self.write_register_all,
            'H': self.set_thread,
            'm': self.read_memory,
            'M': self.write_memory,
            'p': self.read_register,
            'P': self.write_register,
            'v': self.handle_long_commands,
            'X': self.write_memory_bin,
            'Z': self.insert_breakpoint,
            'z': self.remove_breakpoint,
            '?': self.stop_reason,
            '!': self.extend_mode,
        }
        self.active_state = active_state
        self.regs = GdbRegSpace(self.active_state)
        self.mem = GdbMemSpace(self.active_state, cda)
        self.packet_size = PAGESIZE
        self.libs = GdbSharedLibrary(self.active_state, self.packet_size)
        self.gdb = GdbController()
        self.gdb.write("-target-select remote %s" % ptsname, timeout_sec=10)
        self.thread = threading.Thread(target=self.run)
        self.thread.start()

        self.gdb.write("-file-exec-and-symbols %s" % binary, timeout_sec=10)

    def eval_expression(self, expr):
        # type: (str) -> None
        res = self.gdb.write(
            "-data-evaluate-expression %s" % expr, timeout_sec=99999)
        print(res)

    def write_request(self, req, **kwargs):
        timeout_sec = kwargs.pop('timeout_sec', 10)
        kwargs['read_response'] = False
        self.gdb.write(req, timeout_sec=timeout_sec, **kwargs)
        resp = []
        while True:
            try:
                resp += self.gdb.get_gdb_response()
            except:
                break
        return resp

    def run(self):
        # () -> None
        l.info("start server gdb server")
        buf = []
        while True:
            try:
                data = os.read(self.master.fileno(), PAGESIZE)
            except OSError as e:
                l.info("gdb connection was closed: %s", e)
                return

            if len(data) == 0:
                l.debug("gdb connection was closed")
            buf += data
            buf = self.process_data(buf)

    @property
    def active_state(self):
        # type: () -> State
        return self.state

    @active_state.setter
    def active_state(self, state):
        # type: (State) -> None
        self.state = state

    def process_data(self, buf):
        # type: (str) -> str
        while len(buf):
            if buf[0] == "+" or buf[0] == "-":
                buf = buf[1:]
                if len(buf) == 0:
                    return buf

            begin = buf.index("$") + 1
            end = buf.index("#")
            if begin >= 0 and end < len(buf):
                packet = buf[begin:end]
                checksum = int(buf[end + 2], 16)
                checksum += int(buf[end + 1], 16) << 4
                assert checksum == compute_checksum(packet)

                self.process_packet(packet)
                buf = buf[end + 3:]
        return buf

    def write_ack(self):
        # type: () -> None
        self.master.write("+")
        self.master.flush()

    def process_packet(self, packet):
        # type: (str) -> None
        handler = self.COMMANDS.get(packet[0], None)

        request = "".join(packet[1:])
        l.warning("<-- %s%s" % (packet[0], request))

        if handler is None:
            l.warning("unknown command %s%s received" % (packet[0], request))
            response = ""
        else:
            response = handler(request)
        self.write_response(response)

    def write_response(self, response):
        # type: (str) -> None
        # Each packet should be acknowledged with a single character.
        # '+' to indicate satisfactory receipt
        l.warning("--> %s" % response)
        self.master.write("+$%s#%.2x" % (response, compute_checksum(response)))
        self.master.flush()

    def extend_mode(self, packet):
        # type: (str) -> str
        """
        !
        """
        return "OK"

    def read_register_all(self, packet):
        # type: (str) -> str
        """
        g
        """
        return self.regs.read_all()

    def write_register_all(self, packet):
        # type: (str) -> str
        """
        G XX...
        """
        self.regs.write_all(packet)
        return "OK"

    def read_register(self, packet):
        # type: (str) -> str
        """
        p n
        """
        n = int(packet, 16)
        # FIXME: gdb request out of range while gdb info frame
        if n < len(self.regs.names):
            return self.regs[self.regs.names[n]]
        return "ffffffff"

    def write_register(self, packet):
        # type: (str) -> str
        """
        P n...=r...
        """
        n_, r_ = packet.split('=')
        n = int(n_, 16)
        r = int(r_, 16)
        if n < len(self.regs.names):
            self.regs[self.regs.names[n]] = r
        return "OK"

    def set_thread(self, packet):
        # type: (str) -> str
        """
        H op thread-id
        """
        return 'OK'

    def read_memory(self, packet):
        # type: (str) -> str
        """
        m addr,length
        """
        addr_, length_ = packet.split(',')
        addr = int(addr_, 16)
        length = int(length_, 16)
        return self.mem.read(addr, length)

    def write_memory(self, packet):
        # type: (str) -> str
        """
        M addr,length:XX
        """
        l = packet.split(',')
        addr_ = l[0]
        length_, value = l[1].split(':')
        addr = int(addr_, 16)
        length = int(length_, 16)
        self.mem.write(addr, length, value)
        return "OK"

    def write_memory_bin(self, packet):
        # type: (str) -> str
        """
        X addr,length:XX(bin)
        """
        pass

    def insert_breakpoint(self, packet):
        # type: (str) -> str
        """
        Z type,addr,kind
        type:   0 software (0xcc)
                1 hardware (drx)
                2 write watchpoint
                3 read watchpoint
        """
        return "OK"

    def remove_breakpoint(self, packet):
        # type: (str) -> str
        """
        z type,addr,kind
        """
        return "OK"

    def stop_reason(self, packet):
        # type: (str) -> str
        GDB_SIGNAL_TRAP = 5
        return "S%.2x" % GDB_SIGNAL_TRAP

    def handle_long_commands(self, packet):
        # type: (str) -> str

        def handle_cont(action, tid=None):
            # type: (str, Optional[int]) -> str
            # TODO: for a continue/step/stop operation
            self.write_response("T05library:r;")
            return "S05"

        if packet.startswith('Cont'):
            supported_action = ['', 'c', 's',
                                't']  # TODO: C sig/S sig/r start,end
            packet = packet[4:]
            if packet == '?':
                return ';'.join(supported_action)
            action = packet.split(';')[1]
            action = action.split(':')[0]
            if action in supported_action:
                return handle_cont(action)
            l.warning("unknown command: v%s", 'Cont' + packet)
            return ""

        if packet.startswith('CtrlC'):
            return "OK"

        if packet.startswith('MustReplyEmpty'):
            return ""
        else:
            l.warning("unknown command: v%s", packet)
            return ""

    def handle_query(self, packet):
        # type: (str) -> str
        """
        qSupported|qAttached|qC
        qXfer:...:read:annex:offset,size
        """

        if packet.startswith('Supported'):
            features = [
                'qXfer:libraries-svr4:read+',
                # 'qXfer:memory-map:read+'
            ]
            features.append('PacketSize=%x' % self.packet_size)
            return ';'.join(features)
        elif packet.startswith('Xfer'):
            reqs = packet.split(':')
            # FIXME: not working now
            if reqs[1] == 'libraries-svr4' and reqs[2] == 'read':
                data = reqs[4].split(',')
                return self.libs.read_xml(int(data[0], 16), int(data[1], 16))
            if reqs[1] == 'memory-map' and reqs[2] == 'read':
                # TODO: add memory-map, (do we really need it now?)
                return ""
            return ''
        elif packet.startswith('Attached'):
            return '1'
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
        elif packet.startswith('Symbol'):
            if packet == 'Symbol::':
                return "OK"
            _, sym_value, sym_name = packet.split(':')
            return "OK"
        else:
            l.warning("unknown query: %s", packet)
            return ""
