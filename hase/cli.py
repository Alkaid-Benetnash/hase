import argparse
from typing import List, Any

from .record import DEFAULT_LOG_DIR, record_command


def parse_arguments(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=argv[0], description="process crashes")
    parser.add_argument(
        "--debug", action="store_true", help="jump into ipdb post mortem debugger"
    )
    subparsers = parser.add_subparsers(
        title="subcommands", description="valid subcommands", help="additional help"
    )

    record = subparsers.add_parser("record")
    record.set_defaults(func=record_command)
    record.add_argument(
        "--log-dir",
        default=str(DEFAULT_LOG_DIR),
        type=str,
        help="where to store crash reports",
    )

    record.add_argument(
        "--pid-file",
        default=str(DEFAULT_LOG_DIR.joinpath("hase-record.pid")),
        help="pid file to be created when recording is started",
    )

    record.add_argument(
        "--limit",
        default=0,
        type=int,
        help="Maximum crashes to record (0 for unlimited crashes)",
    )

    record.add_argument(
        "--rusage-file",
        help="the file to output resource usage result (for benchmarking)",
    )

    record.add_argument(
        "args", nargs="*", help="Executable and arguments for perf tracing"
    )

    replay = subparsers.add_parser("replay")
    replay.add_argument("report")

    unpack = subparsers.add_parser("unpack")
    unpack.add_argument("report")

    def lazy_import_replay_command(args: argparse.Namespace) -> Any:
        from .replay import replay_command

        return replay_command(args)

    replay.set_defaults(func=lazy_import_replay_command)

    def lazy_import_unpack_command(args: argparse.Namespace) -> Any:
        from .replay import unpack_command

        return unpack_command(args)

    unpack.set_defaults(func=lazy_import_unpack_command)

    args, unknown = parser.parse_known_args(argv[1:])
    args.args += unknown
    return args
