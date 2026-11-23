"""One connection owner per board; bounded UI events and isolated board failures."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import threading
import time

from .backends import create_backend
from .firmware import inspect_firmware
from .models import Board, decode, validate_boards


@dataclass
class EventBuffer:
    capacity: int = 4096
    _events: deque = field(default_factory=deque)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    dropped: int = 0

    def __post_init__(self):
        if type(self.capacity) is not int or not 1 <= self.capacity <= 500000:
            raise ValueError("Event capacity must be 1..500000")

    def put(self, event: dict):
        with self._lock:
            if len(self._events) >= self.capacity:
                self._events.popleft()
                self.dropped += 1
            self._events.append(event)

    def drain(self) -> list[dict]:
        with self._lock:
            events = list(self._events)
            self._events.clear()
            return events


class Engine:
    def __init__(self, boards: list[Board], *, allow_hardware: bool = False,
                 backend_factory=create_backend, event_capacity: int = 4096):
        validate_boards(boards)
        if any(b.backend == "pyocd" for b in boards) and not allow_hardware:
            raise ValueError("Hardware access is disabled. Explicitly allow live observation first.")
        self.boards = boards
        self.events = EventBuffer(event_capacity)
        self._stop = threading.Event()
        self._threads = []
        self._factory = backend_factory
        self._started = False

    @property
    def alive(self) -> bool:
        return any(t.is_alive() for t in self._threads)

    def start(self):
        if self._started:
            raise RuntimeError("Create a new engine for a new session")
        self._started = True
        for board in self.boards:
            thread = threading.Thread(target=self._run, args=(board,), name=f"board-{board.id}", daemon=False)
            self._threads.append(thread)
            thread.start()

    def request_stop(self):
        self._stop.set()

    def join(self, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        for thread in self._threads:
            thread.join(max(0, deadline - time.monotonic()))
        return not self.alive

    def _emit(self, board: Board, kind: str, **values):
        self.events.put({"kind": kind, "board": board.id, "mode": board.backend,
                         "synthetic": board.backend == "demo", "host_ns": time.monotonic_ns(),
                         "utc_ns": time.time_ns(), **values})

    def _run(self, board: Board):
        backend = None
        failed = False
        try:
            self._emit(board, "state", state="connecting")
            image = inspect_firmware(board.firmware, board.base_address) if board.firmware else None
            if self._stop.is_set():
                return
            backend = self._factory(board, image)
            backend.open()
            self._emit(board, "state", state="watching", firmware_sha256=image.sha256 if image else None)
            sequence = 0
            while not self._stop.is_set():
                cycle_start = time.monotonic()
                for symbol in board.watches:
                    if self._stop.is_set():
                        break
                    start = time.monotonic_ns()
                    raw = backend.read(symbol)
                    finish = time.monotonic_ns()
                    value = decode(symbol, raw)
                    self._emit(board, "sample", symbol=symbol.name, address=symbol.address,
                               size=symbol.size, dtype=symbol.dtype, raw=raw.hex(), value=value,
                               read_start_ns=start, read_end_ns=finish, sequence=sequence)
                sequence += 1
                remaining = board.interval_ms / 1000 - (time.monotonic() - cycle_start)
                self._stop.wait(max(0, remaining))
        except Exception as error:
            failed = True
            self._emit(board, "error", error=f"{type(error).__name__}: {error}")
        finally:
            if backend is not None:
                try:
                    backend.close()
                except Exception as error:
                    failed = True
                    self._emit(board, "error", error=f"Disconnect failed: {error}")
            self._emit(board, "state", state="error" if failed else "stopped")
