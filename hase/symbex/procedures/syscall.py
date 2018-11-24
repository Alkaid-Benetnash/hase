from __future__ import absolute_import, division, print_function

import claripy
from angr import SimProcedure
from angr.procedures import SIM_PROCEDURES
from angr.storage.file import Flags

from ...errors import HaseError
from .helper import errno_success, minmax, test_concrete_value
from .sym_struct import (
    linux_dirent,
    linux_dirent64,
    robust_list_head,
    sigaction,
    stat_t,
    statfs_t,
    sysinfo_t,
    timespec,
)


class rt_sigaction(SimProcedure):
    IS_SYSCALL = True

    def run(self, signum, act, oldact) -> claripy.BVV:
        # TODO: do real signal registery?
        if not test_concrete_value(self, oldact, 0):
            sigaction(oldact).store_all(self)
        return errno_success(self)


class rt_sigprocmask(SimProcedure):
    IS_SYSCALL = True

    def run(self, how, set, oldset) -> claripy.BVV:
        # TODO: do real signal registery?
        if not test_concrete_value(self, oldset, 0):
            self.state.memory.store(
                oldset,
                self.state.solver.Unconstrained("oldset", 128 * 8, uninitialized=False),
            )
        return errno_success(self)


class connect(SimProcedure):
    IS_SYSCALL = True

    def run(self, sockfd, addr, addrlen) -> claripy.BVV:
        # NOTE: recv from angr == read, so connect does nothing
        # FIXME: actually angr.posix has open_socket and socket_queue
        new_filename = "/tmp/angr_implicit_%d" % self.state.posix.autotmp_counter
        self.state.posix.autotmp_counter += 1
        self.state.posix.open(new_filename, Flags.O_RDWR, preferred_fd=sockfd)
        return errno_success(self)


class access(SimProcedure):
    IS_SYSCALL = True

    def run(self, pathname, mode) -> claripy.BVV:
        return self.state.solver.Unconstrained("access", 32, uninitialized=False)


class getgroups(SimProcedure):
    IS_SYSCALL = True

    def run(self, size, list) -> claripy.BVV:
        # TODO: actually read groups to state
        return self.state.solver.Unconstrained("getgroups", 32, uninitialized=False)


class setgroups(SimProcedure):
    IS_SYSCALL = True

    def run(self, size, list) -> claripy.BVV:
        # TODO: actually set groups to state
        return errno_success(self)


class getdents(SimProcedure):
    IS_SYSCALL = True

    def run(self, fd, dirp, count) -> claripy.BVV:
        linux_dirent(dirp).store_all(self)
        return errno_success(self)


class getdents64(SimProcedure):
    IS_SYSCALL = True

    def run(self, fd, dirp, count) -> claripy.BVV:
        linux_dirent64(dirp).store_all(self)
        return errno_success(self)


class getpriority(SimProcedure):
    IS_SYSCALL = True

    def run(self, which, who) -> claripy.BVV:
        """
        The value which is one of PRIO_PROCESS, PRIO_PGRP, or PRIO_USER, and
        who is interpreted relative to which (a process identifier for
        PRIO_PROCESS, process group identifier for PRIO_PGRP, and a user ID
        for PRIO_USER).  A zero value for who denotes (respectively) the
        calling process, the process group of the calling process, or the
        real user ID of the calling process.
        """
        return self.state.solver.Unconstrained("getpriority", 32, uninitialized=False)


class setpriority(SimProcedure):
    IS_SYSCALL = True

    def run(self, which, who, prio) -> claripy.BVV:
        # TODO: add priority to state
        return errno_success(self)


class arch_prctl(SimProcedure):
    IS_SYSCALL = True

    ARCH_SET_GS = 0x1001
    ARCH_SET_FS = 0x1002
    ARCH_GET_FS = 0x1003
    ARCH_GET_GS = 0x1004

    def run(self, code, addr) -> claripy.BVV:
        if self.state.solver.symbolic(code):
            raise HaseError("what to do here?")
        if test_concrete_value(self, code, self.ARCH_SET_GS):
            self.state.regs.gs = addr
        elif test_concrete_value(self, code, self.ARCH_SET_FS):
            self.state.regs.fs = addr
        elif test_concrete_value(self, code, self.ARCH_GET_GS):
            self.state.memory.store(addr, self.state.regs.gs)
        elif test_concrete_value(self, code, self.ARCH_GET_FS):
            self.state.memory.store(addr, self.state.regs.Fs)
        return errno_success(self)


class set_tid_address(SimProcedure):
    IS_SYSCALL = True

    def run(self, tidptr) -> claripy.BVV:
        # Currently we have no multiple process
        # so no set_child_tid or clear_child_tid
        return self.state.solver.Unconstrained(
            "set_tid_address", 32, uninitialized=False
        )


class kill(SimProcedure):
    IS_SYSCALL = True

    def run(self, pid, sig) -> claripy.BVV:
        # TODO: manager signal
        return errno_success(self)


class get_robust_list(SimProcedure):
    IS_SYSCALL = True

    def run(self, head, length) -> claripy.BVV:
        self.state.memory.store(head, self.state.robust_list_head)
        self.state.memory.store(length, self.state.robust_list_size)
        return errno_success(self)


class set_robust_list(SimProcedure):
    IS_SYSCALL = True

    def run(self, head, length) -> claripy.BVV:
        self.state.robust_list_head = head
        self.state.libc.max_robust_size = 0x20
        if self.state.solver.symbolic(length):
            length = minmax(self, length, self.state.libc.max_robust_size)
        else:
            length = self.state.solver.eval(length)
        self.state.robust_list_size = length
        size = robust_list_head.size  # type: ignore
        for i in range(length):
            robust_list_head(head + i * size).store_all(self)
        return errno_success(self)


class nanosleep(SimProcedure):
    IS_SYSCALL = True

    def run(self, req, rem) -> claripy.BVV:
        timespec(rem).store_all(self)
        return errno_success(self)


class sysinfo(SimProcedure):
    IS_SYSCALL = True

    def run(self, info) -> claripy.BVV:
        sysinfo_t(info).store_all(self)
        return errno_success(self)


class execve(SimProcedure):
    IS_SYSCALL = True

    def run(self, filename, argv, envp) -> claripy.BVV:
        # TODO: do nothing here
        return errno_success(self)


class exit_group(SimProcedure):
    IS_SYSCALL = True
    NO_RET = True

    def run(self, status) -> claripy.BVV:
        self.exit(status)


class futex(SimProcedure):
    IS_SYSCALL = True

    def run(self, uaddr, futex_op, val, timeout, uaddr2, val3) -> claripy.BVV:
        # do nothing
        return self.state.solver.Unconstrained("futex", 32, uninitialized=False)


class readlink(SimProcedure):
    IS_SYSCALL = True

    def run(self, path, buf, bufsize) -> claripy.BVV:
        self.state.memory.store(
            buf,
            self.state.solver.Unconstrained(
                "readlink", bufsize * 8, uninitialized=False
            ),
        )
        return errno_success(self)


class alarm(SimProcedure):
    IS_SYSCALL = True

    def run(self, seconds) -> claripy.BVV:
        return self.state.solver.Unconstrained("alarm", 32, uninitialized=False)


class getpid(SimProcedure):
    IS_SYSCALL = True

    def run(self) -> claripy.BVV:
        return self.state.solver.Unconstrained("getpid", 32, uninitialized=False)


class getppid(SimProcedure):
    IS_SYSCALL = True

    def run(self) -> claripy.BVV:
        return self.state.solver.Unconstrained("getppid", 32, uninitialized=False)


class getgid(SimProcedure):
    IS_SYSCALL = True

    def run(self) -> claripy.BVV:
        return self.state.solver.Unconstrained("getgid", 32, uninitialized=False)


class getpgid(SimProcedure):
    IS_SYSCALL = True

    def run(self) -> claripy.BVV:
        return self.state.solver.Unconstrained("getpgid", 32, uninitialized=False)


class getuid(SimProcedure):
    IS_SYSCALL = True

    def run(self) -> claripy.BVV:
        return self.state.solver.Unconstrained("getuid", 32, uninitialized=False)


class getgrp(SimProcedure):
    IS_SYSCALL = True

    def run(self) -> claripy.BVV:
        return self.state.solver.Unconstrained("getgrp", 32, uninitialized=False)


class getpgrp(SimProcedure):
    IS_SYSCALL = True

    def run(self) -> claripy.BVV:
        return self.state.solver.Unconstrained("getpgrp", 32, uninitialized=False)


class ioctl(SimProcedure):
    IS_SYSCALL = True
    ARGS_MISMATCH = True

    def run(self, fd, request) -> claripy.BVV:
        return errno_success(self)


class openat(SimProcedure):
    IS_SYSCALL = True

    def run(self, dirfd, pathname, flags, mode=0o644) -> claripy.BVV:
        xopen = SIM_PROCEDURES["posix"]["open"]
        # XXX: Actually name is useless, we just want to open a SimFile
        return self.inline_call(xopen, pathname, flags, mode).ret_expr


class stat(SimProcedure):
    IS_SYSCALL = True

    def run(self, file_path, stat_buf) -> claripy.BVV:
        # NOTE: make everything symbolic now
        stat_t(stat_buf).store_all(self)
        return errno_success(self)


class lstat(SimProcedure):
    IS_SYSCALL = True

    def run(self, file_path, stat_buf) -> claripy.BVV:
        ret_expr = self.inline_call(stat, file_path, stat_buf).ret_expr
        return ret_expr


class fstat(SimProcedure):
    IS_SYSCALL = True

    def run(self, fd, stat_buf) -> claripy.BVV:
        # NOTE: since file_path doesn't matter
        return self.inline_call(stat, fd, stat_buf).ret_expr


class fstatat(SimProcedure):
    IS_SYSCALL = True

    def run(self, dirfd, pathname, stat_buf, flags) -> claripy.BVV:
        return self.inline_call(stat, pathname, stat_buf).ret_expr


class newfstatat(SimProcedure):
    IS_SYSCALL = True

    def run(self, dirfd, pathname, stat_buf, flags) -> claripy.BVV:
        return self.inline_call(stat, pathname, stat_buf).ret_expr


class fcntl(SimProcedure):
    ARGS_MISMATCH = True
    IS_SYSCALL = True

    def run(self, fd, cmd) -> claripy.BVV:
        return self.state.solver.Unconstrained("fcntl", 32, uninitialized=False)


class fadvise64(SimProcedure):
    IS_SYSCALL = True

    def run(self, fd, offset, len, advise) -> claripy.BVV:
        return errno_success(self)


class statfs(SimProcedure):
    IS_SYSCALL = True

    def run(self, path, statfs_buf) -> claripy.BVV:
        statfs_t(statfs_buf).store_all(self)
        return errno_success(self)


class fstatfs(SimProcedure):
    IS_SYSCALL = True

    def run(self, fd, stat_buf) -> claripy.BVV:
        return self.inline_call(statfs, fd, stat_buf).ret_expr


class dup(SimProcedure):
    IS_SYSCALL = True

    def run(self, oldfd) -> claripy.BVV:
        return self.state.solver.Unconstrained("dup", 32, uninitialized=False)


class dup2(SimProcedure):
    IS_SYSCALL = True

    def run(self, oldfd, newfd) -> claripy.BVV:
        return self.state.solver.Unconstrained("dup2", 32, uninitialized=False)


class dup3(SimProcedure):
    IS_SYSCALL = True

    def run(self, oldfd, newfd, flags) -> claripy.BVV:
        return self.state.solver.Unconstrained("dup3", 32, uninitialized=False)
