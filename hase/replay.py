from __future__ import absolute_import, division, print_function

import argparse
import subprocess
import json
import shutil
from typing import List, Any, Dict

from .symbex.tracer import Tracer, State
from .mapping import Mapping
from .path import Tempdir


class Replay():
    def __init__(self, report):
        # type: (str) -> None
        self.report = report
        self.tempdir = Tempdir()

    def __enter__(self):
        # type: () -> Replay
        self.prepare_tracer()
        return self

    def __exit__(self, type, value, traceback):
        self.cleanup()

    def prepare_tracer(self):
        # type: () -> None
        subprocess.check_call(
            ["tar", "-xzf", self.report, "-C",
             str(self.tempdir)])

        manifest = self.load_manifest()

        coredump = manifest["coredump"]

        self.tracer = Tracer(
            coredump["executable"],
            coredump["global_tid"],
            manifest["perf_data"],
            coredump["file"],
            manifest["mappings"],
            executable_root=str(self.tempdir.join("binaries")))

    def run(self):
        # type: () -> List[State]
        if not self.tracer:
            self.prepare_tracer()
        return self.tracer.run()

    def cleanup(self):
        # type: () -> None
        shutil.rmtree(str(self.tempdir))

    @property
    def tracer(self):
        # type: () -> Tracer
        return self.tracer

    @property
    def executable(self):
        # type: () -> str
        return self.executable

    @executable.setter
    def executable(self, value):
        # type: (str) -> None
        self.executable = value

    def load_manifest(self):
        # type: () -> Dict[str, Any]
        archive_root = self.tempdir
        manifest_path = archive_root.join("manifest.json")
        with open(str(manifest_path)) as f:
            manifest = json.load(f)

        mappings = []
        for m in manifest["mappings"]:
            if m["path"] != "":
                path = archive_root.join(m["path"])
                if path.exists():
                    m["path"] = str(path)
            m = Mapping(**m)
            mappings.append(m)
        manifest["mappings"] = mappings
        manifest["perf_data"] = str(archive_root.join(manifest["perf_data"]))

        coredump = manifest["coredump"]
        self.executable = '/' + coredump['executable'].partition('/')[2]
        coredump["executable"] = str(archive_root.join(coredump["executable"]))
        coredump["file"] = str(archive_root.join(coredump["file"]))

        return manifest


def replay_trace(report):
    # type: (str) -> Replay
    return Replay(report)


def replay_command(args):
    # type: (argparse.Namespace) -> List[State]
    with replay_trace(args.report) as rt:
        return rt.run()
