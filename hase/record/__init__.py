from __future__ import absolute_import, division, print_function

import argparse
import errno
import fcntl
import json
import logging
import os
import resource
import shutil
import subprocess
from queue import Queue
from signal import SIGUSR2
from tempfile import NamedTemporaryFile
from threading import Condition, Thread
from types import FrameType
from typing import IO, Any, Dict, List, Optional, Tuple, Union

from . import coredumps
from .. import pwn_wrapper
from ..errors import HaseError
from ..path import APP_ROOT, Path, Tempdir
from ..perf import IncreasePerfBuffer, Perf, Trace
from .ptrace import ptrace_detach, ptrace_me
from .signal_handler import SignalHandler

l = logging.getLogger(__name__)

DEFAULT_LOG_DIR = Path("/var/lib/hase")

PROT_EXEC = 4


class Recording:
    def __init__(
        self, coredump: Optional[coredumps.Coredump], trace: Trace, exit_status: int
    ) -> None:
        self.coredump = coredump
        self.trace = trace
        self.exit_status = exit_status
        # set by the report_worker atm, should be refactored
        self.report_path: Optional[str] = None


def record_process(
    process: subprocess.Popen,
    record_paths: "RecordPaths",
    timeout: Optional[int] = None,
) -> Recording:
    handler = coredumps.Handler(
        str(record_paths.coredump),
        str(record_paths.fifo),
        str(record_paths.manifest),
        log_path=str(record_paths.log_path.join("coredump.log")),
    )

    # work around missing nonlocal keyword in python2 with a list
    got_coredump = [False]

    def received_coredump(signum, frame_type):
        # type: (int, FrameType) -> None
        got_coredump[0] = True

    with IncreasePerfBuffer(100 * 1024), Perf(
        process.pid
    ) as perf, handler as _coredump, SignalHandler(SIGUSR2, received_coredump):
        write_pid_file(record_paths.pid_file)

        ptrace_detach(process.pid)
        exit_code = process.wait(timeout)

        if not got_coredump[0]:
            coredump = None
        else:
            coredump = _coredump

        record_paths.perf_directory.mkdir_p()
        trace = perf.write(str(record_paths.perf_directory))

        return Recording(coredump, trace, exit_code)


def record(
    record_paths: "RecordPaths",
    command: Optional[List[str]] = None,
    stdin: Optional[IO[Any]] = None,
    timeout: Optional[int] = None,
) -> Recording:

    if command is None:
        raise HaseError("recording without command is not supported at the moment")

    proc = subprocess.Popen(command, preexec_fn=ptrace_me, stdin=stdin)
    return record_process(proc, record_paths, timeout)


def write_pid_file(pid_file):
    # type: (Optional[str]) -> None
    if pid_file is not None:
        with open(pid_file, "w") as f:
            f.write(str(os.getpid()))


class ExitEvent(object):
    pass


class Job(object):
    def __init__(self, recording: Recording, record_paths: "RecordPaths") -> None:
        self.recording = recording
        self.record_paths = record_paths

    def core_file(self) -> Optional[str]:
        if self.recording.coredump is None:
            return None
        else:
            return self.recording.coredump.get()

    def remove(self) -> None:
        try:
            if self.recording.coredump is not None:
                self.recording.coredump.remove()
        except OSError:
            pass

        shutil.rmtree(str(self.record_paths.perf_directory), ignore_errors=True)


class RecordPaths(object):
    def __init__(self, path, id, log_path, pid_file):
        # type: (Path, int, Path, Optional[str]) -> None
        self.path = path
        self.log_path = log_path
        self.pid_file = pid_file
        self.id = id

        self.state_dir = self.path
        self.perf_directory = self.path.join("traces-%d" % self.id)
        self.coredump = self.path.join("core.%d" % self.id)

        self.fifo = self.path.join("fifo.%d" % self.id)
        self.manifest = self.path.join("manifest.json")

    def report_archive(self, executable, timestamp):
        # type: (str, str) -> Path
        return self.log_path.join(
            "%s-%s.tar.gz" % (os.path.basename(executable), timestamp)
        )


def serialize_trace(trace, state_dir):
    # type: (Trace, Path) -> Dict[str, Any]
    cpus = []
    for cpu in trace.cpus:
        event_path = str(state_dir.relpath(cpu.event_path))
        trace_path = str(state_dir.relpath(cpu.trace_path))

        c = dict(
            idx=cpu.idx,
            event_path=event_path,
            trace_path=trace_path,
            start_time=cpu.start_time,
            start_pid=cpu.start_pid,
            start_tid=cpu.start_tid,
        )
        cpus.append(c)

    return dict(
        cpus=cpus,
        time_mult=trace.time_mult,
        time_shift=trace.time_shift,
        time_zero=trace.time_zero,
        sample_type=trace.sample_type,
        cpu_family=trace.cpu_family,
        cpu_model=trace.cpu_model,
        cpu_stepping=trace.cpu_stepping,
        cpuid_0x15_eax=trace.cpuid_0x15_eax,
        cpuid_0x15_ebx=trace.cpuid_0x15_ebx,
    )


def store_report(job: Job) -> str:
    core_file = job.core_file()
    record_paths = job.record_paths
    state_dir = record_paths.state_dir
    manifest_path = str(record_paths.manifest)

    with NamedTemporaryFile() as template:

        def append(path):
            # type: (str) -> None
            template.write(str(state_dir.relpath(path)).encode("utf-8"))
            template.write(b"\0")

        append(manifest_path)

        manifest = json.load(open(manifest_path))
        binaries = manifest["binaries"] = []

        paths = set()
        for obj in pwn_wrapper.Coredump(str(core_file)).mappings:
            if (
                (obj.flags & PROT_EXEC)
                and obj.path.startswith("/")
                and os.path.exists(obj.path)
            ):
                paths.add(obj.path)

        for path in paths:
            # FIXME check if elf, only create parent directory once
            archive_path = state_dir.join("binaries", path[1:])
            archive_path.dirname().mkdir_p()

            shutil.copyfile(path, str(archive_path))

            binaries.append(str(state_dir.relpath(str(archive_path))))
            append(str(archive_path))

        if core_file is not None:
            coredump = manifest["coredump"]
            coredump["executable"] = os.path.join("binaries", coredump["executable"])
            coredump["file"] = str(state_dir.relpath(core_file))
            append(core_file)

        trace = serialize_trace(job.recording.trace, state_dir)

        for cpu in trace["cpus"]:
            append(str(state_dir.join(cpu["event_path"])))
            append(str(state_dir.join(cpu["trace_path"])))

        manifest["trace"] = trace

        with open(manifest_path, "w") as manifest_file:
            json.dump(manifest, manifest_file, indent=4)

        template.flush()

        archive_path = record_paths.report_archive(
            coredump["executable"], coredump["time"]
        )

        l.info("creating archive %s", archive_path)
        subprocess.check_call(
            [
                "tar",
                "--null",
                "-C",
                str(record_paths.state_dir),
                "-T",
                str(template.name),
                "-czf",
                str(archive_path),
            ]
        )
        l.info("built archive %s", archive_path)
        os.unlink(manifest_path)
        return archive_path


def report_worker(queue):
    # type: (Queue) -> None
    l.info("start worker")
    while True:
        job = queue.get()  # type: Union[Job, ExitEvent]
        if isinstance(job, ExitEvent):
            return

        try:
            report_path = store_report(job)
            job.recording.report_path = report_path
            l.info("processed job")
        except OSError:
            l.exception("Error while creating report")
        finally:
            l.info("remove job")
            job.remove()

# XXX since global recording is probably not coming back we can remove this background worker + loop
def record_loop(
    record_path: Path,
    log_path: Path,
    pid_file: Optional[str] = None,
    limit: int = 0,
    command: Optional[List[str]] = None,
    stdin: Optional[IO[Any]] = None,
    timeout: Optional[int] = None,
) -> Optional[Recording]:
    job_queue: Queue[Union[Job, ExitEvent]] = Queue()
    post_process_thread = Thread(target=report_worker, args=(job_queue,))
    post_process_thread.start()

    try:
        i = 0
        while limit == 0 or limit > i:
            i += 1
            # TODO ratelimit
            record_paths = RecordPaths(record_path, i, log_path, pid_file)
            recording = record(record_paths, command, stdin=stdin, timeout=timeout)
            if recording.coredump is None:
                return recording
            job_queue.put(Job(recording, record_paths))
            if command is not None:
                # if we record a single command we do not go into a loop
                return recording
    except KeyboardInterrupt:
        pass
    finally:
        job_queue.put(ExitEvent())
        l.info("Wait for child")
        post_process_thread.join()

    return None


def record_command(args):
    # type: (argparse.Namespace) -> None

    log_path = Path(args.log_dir)
    log_path.mkdir_p()

    logging.basicConfig(filename=str(log_path.join("hase.log")), level=logging.INFO)

    command = None if len(args.args) == 0 else args.args

    with Tempdir() as tempdir:
        record_loop(
            tempdir, log_path, pid_file=args.pid_file, limit=args.limit, command=command
        )

    if args.rusage_file is not None:
        usage = tuple(resource.getrusage(resource.RUSAGE_CHILDREN))
        with open(args.rusage_file, "w") as usage_file:
            usage_file.write(", ".join([str(x) for x in usage]))
            usage_file.write("\n")
