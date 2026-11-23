"""Explicit symbol types and portable workspace validation."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import math
from pathlib import Path
import struct

FORMATS = {
    "u8": "B", "i8": "b", "u16": "H", "i16": "h", "u32": "I",
    "i32": "i", "u64": "Q", "i64": "q", "f32": "f", "f64": "d", "bool": "?",
}
TYPES = ("raw", *FORMATS)


def integer(value: int | str) -> int:
    if isinstance(value, bool):
        raise ValueError("Boolean is not an address or size")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value, 0)
    raise ValueError("Expected an integer or an integer string")


@dataclass(frozen=True)
class Symbol:
    name: str
    address: int
    size: int
    dtype: str = "raw"

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name or len(self.name) > 256:
            raise ValueError("A symbol needs a name of 1..256 characters")
        if type(self.address) is not int or type(self.size) is not int:
            raise ValueError("Symbol address and size must be integers")
        if not 0 <= self.address < self.address + self.size <= 2**32 or not 1 <= self.size <= 8:
            raise ValueError("Only scalar objects of 1..8 bytes in 32-bit address space are supported")
        if self.dtype not in TYPES:
            raise ValueError(f"Unsupported type: {self.dtype}")
        if self.dtype != "raw" and struct.calcsize(FORMATS[self.dtype]) != self.size:
            raise ValueError(f"{self.dtype} does not match {self.size} bytes")

    @classmethod
    def from_dict(cls, item: dict) -> Symbol:
        return cls(str(item["name"]), integer(item["address"]), integer(item["size"]), item.get("dtype", "raw"))


def decode(symbol: Symbol, raw: bytes):
    if len(raw) != symbol.size:
        raise OSError(f"Short read for {symbol.name}: {len(raw)}/{symbol.size}")
    if symbol.dtype == "raw":
        return raw.hex(" ")
    value = struct.unpack("<" + FORMATS[symbol.dtype], raw)[0]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{symbol.name} is not a finite number (check the selected type)")
    return value


@dataclass
class Board:
    id: str
    name: str
    backend: str = "demo"
    firmware: str = ""
    probe_uid: str = ""
    target: str = ""
    base_address: int | None = None
    interval_ms: int = 100
    watches: list[Symbol] = field(default_factory=list)

    def validate(self):
        if not isinstance(self.id, str) or not self.id or len(self.id) > 80 or not self.name:
            raise ValueError("Every board needs a stable ID and name")
        if self.backend not in ("demo", "pyocd"):
            raise ValueError("Backend must be demo or pyocd")
        if type(self.interval_ms) is not int or not 20 <= self.interval_ms <= 10000:
            raise ValueError("Sampling interval must be 20..10000 ms")
        if len(self.watches) > 64:
            raise ValueError("At most 64 scalar watches per board")
        if len({s.name for s in self.watches}) != len(self.watches):
            raise ValueError("Watch names must be unique within a board")
        if self.base_address is not None and (type(self.base_address) is not int or not 0 <= self.base_address < 2**32):
            raise ValueError("Invalid binary base address")
        if self.backend == "pyocd" and not all((self.probe_uid.strip(), self.target.strip(), self.firmware)):
            raise ValueError("Live boards need an exact probe UID, target name, and firmware")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, item: dict, root: Path | None = None) -> Board:
        values = {k: v for k, v in item.items() if k in cls.__dataclass_fields__}
        values["watches"] = [Symbol.from_dict(s) for s in item.get("watches", [])]
        if values.get("base_address") is not None:
            values["base_address"] = integer(values["base_address"])
        if values.get("firmware") and root is not None:
            path = Path(values["firmware"])
            values["firmware"] = str(path if path.is_absolute() else (root / path).resolve())
        board = cls(**values)
        board.validate()
        return board


def validate_boards(boards: list[Board]):
    if not 1 <= len(boards) <= 16:
        raise ValueError("A workspace must contain 1..16 boards")
    for board in boards:
        board.validate()
    if len({b.id for b in boards}) != len(boards):
        raise ValueError("Duplicate board ID")
    probes = [b.probe_uid for b in boards if b.backend == "pyocd"]
    if len(probes) != len(set(probes)):
        raise ValueError("A probe UID cannot be assigned to multiple boards")


def load_workspace(path: str | Path) -> list[Board]:
    path = Path(path)
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("Workspace exceeds 1 MiB")
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema") != 1:
        raise ValueError("Unsupported workspace schema")
    boards = [Board.from_dict(b, path.resolve().parent) for b in document["boards"]]
    validate_boards(boards)
    return boards


def workspace_document(boards: list[Board]) -> dict:
    validate_boards(boards)
    return {"schema": 1, "boards": [b.to_dict() for b in boards]}


def demo_boards() -> list[Board]:
    signals = [Symbol("temperature_c", 0x20000000, 4, "f32"),
               Symbol("supply_v", 0x20000004, 4, "f32"),
               Symbol("motor_rpm", 0x20000008, 4, "u32"),
               Symbol("tick", 0x2000000C, 4, "u32")]
    return [Board(f"demo-{i}", name, watches=list(signals)) for i, name in
            enumerate(("Acquisition", "Controller", "Drive"), 1)]
