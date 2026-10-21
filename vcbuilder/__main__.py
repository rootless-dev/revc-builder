"""Command-line front end: ``python -m vcbuilder <game-folder>`` (spec section 4)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from vcbuilder.errors import BuildError
from vcbuilder.events import Event, LogLine, Progress, StageFailed, StageFinished, StageStarted
from vcbuilder.pipeline import STAGE_IDS
from vcbuilder.renderers import DEFAULT_RENDERER, RENDERERS
from vcbuilder.session import BuildSession


def render_event(event: Event, verbose: bool = False) -> str | None:
    if isinstance(event, StageStarted):
        return f"==> {event.title}"
    if isinstance(event, Progress):
        if event.fraction is None:
            return f"    {event.message}" if event.message else None
        return f"    {event.fraction:.0%} {event.message}".rstrip()
    if isinstance(event, LogLine):
        return f"    {event.text}" if verbose else None
    if isinstance(event, StageFailed):
        if event.cancelled:
            return "Cancelled."
        if event.error is None:
            return "ERROR: the stage failed."
        detail = f"\n       {event.error.detail}" if verbose and event.error.detail else ""
        return f"ERROR: {event.error.user_message}{detail}"
    if isinstance(event, StageFinished):
        return None
    return None


class _Printer:
    """Prints rendered events; in quiet mode, only every 10 % step of a stage's progress."""

    def __init__(self, verbose: bool) -> None:
        self.verbose = verbose
        self._last_step: dict[str, int] = {}
        self._last_message: dict[str, str] = {}

    def __call__(self, event: Event) -> None:
        if isinstance(event, Progress) and not self.verbose and event.fraction is not None:
            step = int(event.fraction * 10)
            if step == self._last_step.get(event.stage) and event.message in ("", self._last_message.get(event.stage)):
                return
            self._last_step[event.stage] = step
            if event.message:
                self._last_message[event.stage] = event.message
        if isinstance(event, Progress) and self.verbose:
            return  # the log lines already show what is happening
        text = render_event(event, self.verbose)
        if text is None:
            return
        stream = sys.stderr if isinstance(event, StageFailed) else sys.stdout
        print(text, file=stream, flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m vcbuilder",
        description="Build and install a native macOS reVC app from a GTA Vice City (PC) game folder you own.",
    )
    parser.add_argument("game_folder", type=Path, help="the folder that contains the game's data and models folders")
    parser.add_argument("-v", "--verbose", action="store_true", help="print every line of compiler output")
    parser.add_argument("--from-stage", choices=STAGE_IDS, default="validate", help="start at this stage")
    parser.add_argument("--stop-after", choices=STAGE_IDS, help="stop after this stage")
    parser.add_argument(
        "--home",
        type=Path,
        help="use this folder instead of your home folder for everything the Builder and reVC "
        "read and write (cache, logs, game data, reVC.ini); the app then goes to HOME/Applications "
        "unless --applications is given (for experiments)",
    )
    parser.add_argument(
        "--applications",
        type=Path,
        help="install the app in this folder (default: the platform's applications folder; on macOS "
        "/Applications, or ~/Applications when it is not writable)",
    )
    parser.add_argument(
        "--renderer",
        choices=sorted(RENDERERS),
        default=DEFAULT_RENDERER,
        help=f"the renderer to build reVC with (default: {DEFAULT_RENDERER}); wgpu is the Rust/wgpu renderer",
    )
    parser.add_argument(
        "--rwgpu-dir",
        type=Path,
        help="development: use the rwgpu library in this folder (lib/librwgpu.a, lib/link-libs.txt, "
        "include/rwgpu.h, as renderer/build-universal.sh makes) instead of the pinned download; "
        "the environment variable VCBUILDER_RWGPU_DIR does the same",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    printer = _Printer(args.verbose)
    app_destination = args.applications
    if app_destination is None and args.home is not None:
        app_destination = args.home / "Applications"
    rwgpu_dir = args.rwgpu_dir
    if rwgpu_dir is None and os.environ.get("VCBUILDER_RWGPU_DIR"):
        rwgpu_dir = Path(os.environ["VCBUILDER_RWGPU_DIR"])
    if rwgpu_dir is not None:
        rwgpu_dir = rwgpu_dir.expanduser().resolve()
    try:
        session = BuildSession(home=args.home, emit=printer, app_destination=app_destination,
                               renderer=args.renderer, rwgpu_dir=rwgpu_dir)
    except BuildError as error:
        print(f"ERROR: {error.user_message}", file=sys.stderr)
        return 1
    print(f"Log: {session.log_path}", flush=True)
    try:
        result = session.build(args.game_folder.expanduser(), start=args.from_stage, stop_after=args.stop_after)
    except KeyboardInterrupt:
        session.log.note("Interrupted from the keyboard.")
        print("Cancelled.", file=sys.stderr)
        return 130
    finally:
        session.close()
    if result.succeeded:
        if session.installed_app:
            print(f"Done. The game is installed at {session.installed_app}")
        else:
            print(f"Done (stopped after the {args.stop_after} stage).")
        return 0
    if not result.cancelled:
        print(f"The full log is at {session.log_path}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
