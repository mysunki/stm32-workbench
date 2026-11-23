"""Versioned JSONL recordings; replay is offline and never creates an Engine."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import time

from .models import Board, validate_boards, workspace_document


class Recorder:
    def __init__(self, path: str | Path, boards: list[Board]):
        self.path = Path(path)
        self._file = self.path.open("x", encoding="utf-8", newline="\n")
        self._last_flush = time.monotonic()
        try:
            self.write({"kind": "header", "schema": 1, "application": "stm32-workbench",
                        "created_utc_ns": time.time_ns(), "workspace": workspace_document(boards),
                        "timing": "PC read timestamps; not atomic, MCU-timed, or synchronized across boards"})
            self._file.flush()
        except BaseException:
            self._file.close()
            raise

    def write(self, event: dict):
        self._file.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
        if time.monotonic() - self._last_flush >= 0.25:
            self._file.flush()
            self._last_flush = time.monotonic()

    def close(self):
        if not self._file.closed:
            try:
                self._file.flush()
                os.fsync(self._file.fileno())
            finally:
                self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class Replay:
    def __init__(self, path: str | Path):
        path = Path(path)
        if path.stat().st_size > 128 * 1024 * 1024:
            raise ValueError("Replay is limited to 128 MiB per file")
        self.events, self.boards, self.header = [], [], None
        with path.open(encoding="utf-8") as source:
            for number, line in enumerate(source, 1):
                if len(line) > 1024 * 1024:
                    raise ValueError(f"Recording line {number} is too large")
                if not line.strip():
                    continue
                try:
                    event = json.loads(line, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
                except (ValueError, TypeError) as error:
                    raise ValueError(f"Invalid recording at line {number}; keep partial data for recovery") from error
                if not isinstance(event, dict):
                    raise ValueError(f"Recording line {number} must be a JSON object")
                if self.header is None:
                    if (event.get("kind") != "header" or event.get("schema") != 1
                            or event.get("application") != "stm32-workbench"):
                        raise ValueError("Not a supported Workbench recording")
                    try:
                        if event["workspace"].get("schema") != 1:
                            raise ValueError("Unsupported workspace schema")
                        self.boards = [Board.from_dict(b) for b in event["workspace"]["boards"]]
                        validate_boards(self.boards)
                    except (KeyError, TypeError, AttributeError) as error:
                        raise ValueError("Invalid recording workspace") from error
                    self.header = event
                    continue
                if event.get("kind") not in ("sample", "state", "error", "gap"):
                    raise ValueError(f"Unknown event at line {number}")
                timestamp = event.get("host_ns")
                if type(timestamp) is not int or timestamp < 0:
                    raise ValueError("Recording timestamps must be non-negative integer nanoseconds")
                # Multiple board threads can enqueue out of timestamp order. Sort after loading.
                if event["kind"] != "gap":
                    board = next((b for b in self.boards if b.id == event.get("board")), None)
                    if board is None or event.get("mode") != board.backend or event.get("synthetic") is not (board.backend == "demo"):
                        raise ValueError("Recording source provenance does not match its workspace")
                    if event["kind"] == "sample":
                        symbol = next((s for s in board.watches if s.name == event.get("symbol")), None)
                        if symbol is None or event.get("dtype") != symbol.dtype or event.get("address") != symbol.address or event.get("size") != symbol.size:
                            raise ValueError("Recording sample does not match its symbol")
                        from .models import decode
                        raw = event.get("raw")
                        start, end = event.get("read_start_ns"), event.get("read_end_ns")
                        if not isinstance(raw, str) or len(raw) != symbol.size * 2:
                            raise ValueError("Invalid raw sample bytes")
                        if type(start) is not int or type(end) is not int or not 0 <= start <= end <= timestamp:
                            raise ValueError("Invalid sample timing brackets")
                        decoded = decode(symbol, bytes.fromhex(raw))
                        if type(decoded) is not type(event.get("value")) or decoded != event.get("value"):
                            raise ValueError("Recording decoded value disagrees with its raw bytes")
                    elif event["kind"] == "state" and event.get("state") not in ("connecting", "watching", "stopped", "error"):
                        raise ValueError("Invalid recorded board state")
                    elif event["kind"] == "error" and not isinstance(event.get("error"), str):
                        raise ValueError("Invalid recorded error")
                elif type(event.get("dropped_total")) is not int or event["dropped_total"] < 1:
                    raise ValueError("Invalid event-loss metadata")
                self.events.append(event)
                if len(self.events) > 500000:
                    raise ValueError("Replay exceeds 500,000 events")
        if self.header is None:
            raise ValueError("Empty recording")
        self.events.sort(key=lambda event: event["host_ns"])
        self.origin = self.events[0]["host_ns"] if self.events else 0
        self.position = 0

    def ready(self, elapsed_seconds: float) -> list[dict]:
        if not math.isfinite(elapsed_seconds) or elapsed_seconds < 0:
            raise ValueError("Replay time must be finite and non-negative")
        limit = self.origin + int(elapsed_seconds * 1e9)
        result = []
        while self.position < len(self.events) and self.events[self.position]["host_ns"] <= limit:
            event = dict(self.events[self.position])
            event["replay"] = True
            result.append(event)
            self.position += 1
        return result

    @property
    def finished(self):
        return self.position >= len(self.events)
