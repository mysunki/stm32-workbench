"""UI-neutral application operations used by the Windows desktop host.

The native frontend sends JSON over private stdio pipes. No network listener and
no automatic hardware attachment are involved. Desktop verification uses this same
controller and the real Engine/Recorder/Replay, not a second fake implementation.
"""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import threading
import time
import uuid

from .backends import DemoBackend, create_backend, list_probes
from .engine import Engine
from .firmware import inspect_firmware
from .models import Board, Symbol, demo_boards, integer, load_workspace, validate_boards, workspace_document
from .recording import Recorder, Replay


class Desktop:
    def __init__(self, boards=None):
        self.boards = boards or demo_boards()
        validate_boards(self.boards)
        self.selected = self.boards[0].id
        self.engine = self.recorder = self.replay = None
        self.running = self.closing = False
        self.latest, self.states, self.images = {}, {}, {}
        self.total_samples = self.origin_ns = self.dropped = 0
        self.replay_start = 0.0
        self.faults = set()
        self.fault_lock = threading.Lock()
        self.messages = []
        self.firmware_revision = 0
        self.symbol_query = ""

    def board(self, identity=None):
        board = next((b for b in self.boards if b.id == (identity or self.selected)), None)
        if board is None:
            raise ValueError("Board not found")
        return board

    def log(self, text):
        self.messages.append({"kind": "log", "text": str(text)})

    def editable(self):
        if self.running or (self.engine and self.engine.alive) or self.recorder:
            raise ValueError("Stop sampling and finish recording before editing the workspace")
        if self.replay:
            raise ValueError("Replay is read-only. Load a workspace or reset the demo before editing")

    def idle(self):
        if self.running or (self.engine and self.engine.alive) or self.recorder:
            raise ValueError("Stop sampling and finish recording before loading a session")

    def backend(self, board, image):
        if board.backend != "demo":
            return create_backend(board, image)
        desktop = self
        class FaultableDemo(DemoBackend):
            def read(self, symbol):
                with desktop.fault_lock:
                    fault = board.id in desktop.faults
                if fault:
                    raise OSError("Injected DEMO connection fault; no physical device involved")
                return super().read(symbol)
        return FaultableDemo(board, image)

    def start(self, allow_hardware=False):
        if self.running or (self.engine and self.engine.alive):
            raise ValueError("Sampling is already active")
        if not all(b.watches for b in self.boards):
            raise ValueError("Choose at least one watch for every configured board")
        if self.replay:
            self.replay.position = 0
            self.replay_start = time.monotonic()
        else:
            with self.fault_lock:
                self.faults.clear()
            self.engine = Engine(self.boards, allow_hardware=allow_hardware, backend_factory=self.backend)
            self.engine.start()
        self.latest.clear()
        self.states.clear()
        self.total_samples = self.origin_ns = self.dropped = 0
        self.running = True
        self.messages.append({"kind": "reset_chart"})
        self.log("Offline replay started" if self.replay else "Sampling started; demo sources are synthetic")

    def stop(self):
        if self.engine:
            self.engine.request_stop()
        if self.replay:
            self.running = False

    def finish_recording(self):
        recorder, self.recorder = self.recorder, None
        if recorder:
            recorder.close()
            self.log("Recording saved: " + recorder.path.name)

    def write_event(self, event):
        if self.recorder:
            try:
                self.recorder.write(event)
            except (OSError, ValueError) as error:
                try:
                    self.finish_recording()
                finally:
                    self.log("Recording failed; partial file preserved: " + str(error))
                    self.messages.append({"kind": "error", "text": str(error)})

    def event(self, event):
        kind = event["kind"]
        if kind == "sample":
            self.latest[(event["board"], event["symbol"])] = (event, time.monotonic())
            self.total_samples += 1
            if not self.origin_ns:
                self.origin_ns = event["host_ns"]
        elif kind == "state":
            self.states[event["board"]] = event["state"]
            self.log(event["board"] + ": " + event["state"])
        elif kind == "error":
            self.states[event["board"]] = "error"
            self.log(event["board"] + ": " + event["error"])
        elif kind == "gap":
            self.log("Event loss: " + str(event["dropped_total"]))

    def poll(self):
        if self.engine:
            for event in self.engine.events.drain():
                self.event(event)
                self.write_event(event)
            if self.engine.events.dropped != self.dropped:
                self.dropped = self.engine.events.dropped
                event = {"kind": "gap", "host_ns": time.monotonic_ns(), "dropped_total": self.dropped}
                self.event(event)
                self.write_event(event)
            if self.running and not self.engine.alive:
                self.running = False
        if self.replay and self.running:
            for event in self.replay.ready(time.monotonic() - self.replay_start):
                self.event(event)
            if self.replay.finished:
                self.running = False
                self.log("Replay completed; no hardware was opened")
        if self.closing and not (self.engine and self.engine.alive):
            self.finish_recording()
            return False
        return True

    def reset(self, boards, replay=None):
        self.boards, self.replay, self.engine = boards, replay, None
        self.selected = self.boards[0].id
        self.images.clear()
        self.latest.clear()
        self.states.clear()
        self.total_samples = self.origin_ns = self.dropped = 0
        self.firmware_revision += 1
        self.messages.append({"kind": "reset_chart"})

    def dispatch(self, command):
        operation = command.get("op")
        if operation == "start":
            self.start(allow_hardware=command.get("allow_hardware") is True)
        elif operation == "stop":
            self.stop()
        elif operation == "select":
            self.selected = self.board(command["board"]).id
            self.firmware_revision += 1
        elif operation == "filter_symbols":
            self.symbol_query = str(command.get("query", ""))[:256].lower()
            self.firmware_revision += 1
        elif operation == "import":
            self.editable()
            board = self.board(command.get("board"))
            base = command.get("base")
            image = inspect_firmware(command["path"], integer(base) if base not in (None, "") else None)
            self.images[board.id] = image
            board.firmware, board.base_address = image.path, integer(base) if base not in (None, "") else None
            board.watches = []
            self.latest = {key: value for key, value in self.latest.items() if key[0] != board.id}
            self.firmware_revision += 1
            self.log("Offline image loaded: " + Path(image.path).name)
        elif operation == "add_symbols":
            self.editable()
            board = self.board()
            image = self.get_image(board)
            if image is None:
                raise ValueError("Import an image first")
            names = command.get("symbols", [])
            if not isinstance(names, list) or not names:
                raise ValueError("Select symbols to watch")
            lookup = {s.name: s for s in image.symbols}
            new = []
            for name in dict.fromkeys(names):
                if name not in lookup:
                    raise ValueError("Symbol is not in the selected image")
                symbol = lookup[name]
                dtype = command.get("dtype", "auto")
                if dtype != "auto":
                    symbol = replace(symbol, dtype=dtype)
                if all(s.name != symbol.name for s in board.watches):
                    new.append(symbol)
            if len(board.watches) + len(new) > 64:
                raise ValueError("At most 64 watches per board")
            board.watches.extend(new)
        elif operation == "add_watch":
            self.editable()
            board = self.board()
            symbol = Symbol.from_dict(command["symbol"])
            if len(board.watches) >= 64 or any(s.name == symbol.name for s in board.watches):
                raise ValueError("Watch limit reached or name already exists")
            board.watches.append(symbol)
        elif operation == "remove_watch":
            self.editable()
            board = self.board(command["board"])
            board.watches = [s for s in board.watches if s.name != command["symbol"]]
        elif operation == "add_demo":
            self.editable()
            if len(self.boards) >= 16:
                raise ValueError("At most 16 boards per workspace")
            board = demo_boards()[0]
            board.id, board.name = uuid.uuid4().hex[:12], "Demo " + str(len(self.boards) + 1)
            self.boards.append(board)
            self.selected = board.id
            self.firmware_revision += 1
        elif operation == "add_live":
            self.editable()
            board = Board.from_dict({**command["board_config"], "id": uuid.uuid4().hex[:12], "backend": "pyocd"})
            validate_boards([*self.boards, board])
            self.boards.append(board)
            self.selected = board.id
            self.firmware_revision += 1
            self.log("Live board configured offline. Import its image and choose watches before starting")
        elif operation == "remove_board":
            self.editable()
            if len(self.boards) <= 1:
                raise ValueError("Keep at least one board")
            board = self.board()
            self.boards.remove(board)
            self.selected = self.boards[0].id
            self.firmware_revision += 1
        elif operation == "demo_fault":
            if not self.running or self.replay or self.board().backend != "demo":
                raise ValueError("A synthetic fault requires an active demo board")
            with self.fault_lock:
                self.faults.add(self.selected)
            self.log("DEMO fault requested for " + self.selected + "; other boards continue independently")
        elif operation == "record":
            if self.replay:
                raise ValueError("Replay cannot be recorded as a new live session")
            if self.recorder:
                self.finish_recording()
            else:
                self.recorder = Recorder(command["path"], self.boards)
                self.log("Recording started: " + Path(command["path"]).name)
        elif operation == "save_workspace":
            document = workspace_document(self.boards)
            Path(command["path"]).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
            self.log("Workspace saved")
        elif operation == "load_workspace":
            self.idle()
            self.reset(load_workspace(command["path"]))
            self.log("Workspace restored offline; no probes opened")
        elif operation == "open_replay":
            self.idle()
            replay = Replay(command["path"])
            self.reset(replay.boards, replay)
            self.log("Recording loaded for offline replay")
        elif operation == "reset_demo":
            self.idle()
            self.reset(demo_boards())
        elif operation == "probes":
            self.idle()
            self.messages.append({"kind": "probes", "probes": list_probes()})
        elif operation == "close":
            self.closing = True
            self.stop()
        else:
            raise ValueError("Unknown desktop operation")

    def get_image(self, board):
        if board.id not in self.images and board.firmware and not self.replay:
            self.images[board.id] = inspect_firmware(board.firmware, board.base_address)
        return self.images.get(board.id)

    def firmware_view(self):
        board = self.board()
        image = self.get_image(board)
        if image is None:
            return {"kind": "firmware", "board": board.id, "title": "Select a board and import its image. Import is offline.", "symbols": []}
        symbols = [s for s in image.symbols if self.symbol_query in s.name.lower()]
        return {"kind": "firmware", "board": board.id,
                "title": f"{Path(image.path).name} | {image.format} | {image.size:,} bytes | {len(image.symbols)} scalar symbols\nSHA256 {image.sha256}\n" + " ".join(image.notes),
                "symbols": [{"name": s.name, "address": f"0x{s.address:08x}", "size": s.size, "dtype": s.dtype} for s in symbols[:2000]]}

    def snapshot(self):
        watches = []
        for board in self.boards:
            for symbol in board.watches:
                entry = self.latest.get((board.id, symbol.name))
                event, received = entry if entry else (None, 0)
                state = self.states.get(board.id, "ready")
                valid = event is not None and state not in ("error", "connecting")
                stale = self.running and not self.replay and event is not None and time.monotonic() - received > max(1, board.interval_ms / 250)
                watches.append({"board": board.id, "board_name": board.name, "symbol": symbol.name,
                    "address": f"0x{symbol.address:08x}", "size": symbol.size, "dtype": symbol.dtype,
                    "value": event["value"] if valid else None,
                    "sample_time": (event["host_ns"] - self.origin_ns) / 1e9 if event and self.origin_ns else None,
                    "sample_id": str(event["host_ns"]) if event else "",
                    "status": "STALE" if stale else ("REPLAY" if self.replay else "DEMO" if board.backend == "demo" else "LIVE") if valid else state})
        return {"kind": "snapshot", "running": self.running, "busy": bool(self.engine and self.engine.alive),
                "replay": self.replay is not None, "replay_finished": bool(self.replay and self.replay.finished),
                "recording": self.recorder.path.name if self.recorder else "", "selected": self.selected,
                "source": "REPLAY / OFFLINE" if self.replay else "DEMO / SYNTHETIC" if all(b.backend == "demo" for b in self.boards) else "LIVE CONFIGURED / EXPLICIT ATTACH",
                "total_samples": self.total_samples, "dropped": self.dropped,
                "boards": [{"id": b.id, "name": b.name, "backend": b.backend, "state": self.states.get(b.id, "ready"),
                            "firmware": Path(b.firmware).name if b.firmware else "No firmware required for demo",
                            "watches": len(b.watches), "interval_ms": b.interval_ms} for b in self.boards], "watches": watches}
