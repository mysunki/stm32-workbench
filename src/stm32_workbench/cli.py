"""Offline inspection, demo recording, and an optional desktop UI."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import time

from . import __version__


def parser():
    result = argparse.ArgumentParser(prog="stm32-workbench", description="Multi-board variable observation and offline session replay")
    result.add_argument("--version", action="version", version=__version__)
    commands = result.add_subparsers(dest="command")
    gui = commands.add_parser("gui", help="Start the desktop UI with three synthetic demo boards")
    gui.add_argument("--workspace", type=Path)
    inspect = commands.add_parser("inspect", help="Inspect a firmware file without USB access")
    inspect.add_argument("file", type=Path)
    inspect.add_argument("--base", type=lambda s: int(s, 0))
    inspect.add_argument("--json", action="store_true")
    commands.add_parser("probes", help="Explicit USB probe enumeration; does not open a target session")
    demo = commands.add_parser("record-demo", help="Record three synthetic boards without a GUI or drivers")
    demo.add_argument("--duration", type=float, default=5)
    demo.add_argument("--output", type=Path, required=True)
    replay = commands.add_parser("replay-info", help="Validate a recording and report its provenance")
    replay.add_argument("file", type=Path)
    commands.add_parser("selftest", help="Run checkout tests; hardware is never accessed")
    return result


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    command = args.command or "gui"
    try:
        if command == "gui":
            from .ui import launch
            return launch(getattr(args, "workspace", None))
        if command == "inspect":
            from .firmware import inspect_firmware
            image = inspect_firmware(args.file, args.base)
            if args.json:
                print(json.dumps(image.summary(), indent=2, ensure_ascii=False))
            else:
                print(f"{Path(image.path).name} | {image.format} | {image.size} bytes")
                print(f"SHA256 {image.sha256}")
                print(f"{len(image.symbols)} scalar symbols, {len(image.segments)} load segments")
                for symbol in image.symbols[:50]:
                    print(f"0x{symbol.address:08x}  {symbol.size:>2}  {symbol.dtype:>4}  {symbol.name}")
                for note in image.notes:
                    print(f"Note: {note}")
        elif command == "probes":
            from .backends import list_probes
            print(json.dumps(list_probes(), indent=2))
        elif command == "record-demo":
            if not math.isfinite(args.duration) or not 0.1 <= args.duration <= 3600:
                raise ValueError("Duration must be 0.1..3600 seconds")
            from .engine import Engine
            from .models import demo_boards
            from .recording import Recorder
            boards = demo_boards()
            engine = Engine(boards)
            samples, dropped = 0, 0
            with Recorder(args.output, boards) as recorder:
                engine.start()
                try:
                    deadline = time.monotonic() + args.duration
                    while time.monotonic() < deadline:
                        for event in engine.events.drain():
                            recorder.write(event)
                            samples += event["kind"] == "sample"
                        if engine.events.dropped != dropped:
                            dropped = engine.events.dropped
                            recorder.write({"kind": "gap", "host_ns": time.monotonic_ns(), "dropped_total": dropped})
                        time.sleep(0.02)
                finally:
                    engine.request_stop()
                    if not engine.join():
                        raise RuntimeError("Demo workers did not stop")
                    for event in engine.events.drain():
                        recorder.write(event)
                        samples += event["kind"] == "sample"
            print(f"Recorded {samples} SYNTHETIC samples from {len(boards)} demo boards: {args.output}")
        elif command == "replay-info":
            from .recording import Replay
            replay = Replay(args.file)
            print(json.dumps({"schema": 1, "boards": len(replay.boards), "events": len(replay.events),
                              "source_modes": sorted({b.backend for b in replay.boards}),
                              "samples": sum(e["kind"] == "sample" for e in replay.events),
                              "hardware_opened": False}, indent=2))
        elif command == "selftest":
            import unittest
            tests = Path(__file__).resolve().parents[2] / "tests"
            if not tests.is_dir():
                raise ValueError("selftest is available in the source checkout")
            suite = unittest.defaultTestLoader.discover(str(tests))
            return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
        return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
