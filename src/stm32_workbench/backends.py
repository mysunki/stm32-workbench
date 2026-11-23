"""Synthetic demo and optional pyOCD memory-observation adapters."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import struct
import time

from .firmware import Firmware
from .models import Board, FORMATS, PROBE_TYPES, Symbol, probe_selection


class DemoBackend:
    synthetic = True

    def __init__(self, board: Board, image: Firmware | None = None):
        self.board = board
        self.phase = int.from_bytes(hashlib.sha256(board.id.encode()).digest()[:2], "little") / 1000
        self.start = 0.0

    def open(self):
        self.start = time.monotonic()

    def read(self, symbol: Symbol) -> bytes:
        t = time.monotonic() - self.start
        phase = t + self.phase + symbol.address / 4096
        if symbol.dtype in ("f32", "f64"):
            value = (3.3 + 0.1 * math.sin(phase)) if "supply" in symbol.name else 26 + 4 * math.sin(phase / 3)
        elif symbol.dtype == "bool":
            value = int(t) % 2 == 0
        elif "tick" in symbol.name:
            value = int(t * 1000)
        else:
            value = int(1200 + 250 * math.sin(phase))
        if symbol.dtype == "raw":
            return (int(value) % (1 << (8 * symbol.size))).to_bytes(symbol.size, "little")
        if symbol.dtype[0] in ("u", "i"):
            bits = symbol.size * 8
            value %= 1 << bits
            if symbol.dtype[0] == "i" and value >= 1 << (bits - 1):
                value -= 1 << bits
        return struct.pack("<" + FORMATS[symbol.dtype], value)

    def close(self):
        pass


def pyocd_options(board: Board) -> dict:
    return {
        "target_override": board.target,
        "connect_mode": "attach",
        "auto_unlock": False,
        "resume_on_disconnect": False,
        "cache.enable_memory": False,
        "cache.enable_register": False,
        "cache.read_code_from_elf": False,
        "no_config": True,
        "user_script": str(Path(__file__).with_name("_pyocd_noop.py")),
        "frequency": board.debug_frequency_hz,
        "dap_protocol": board.wire_protocol,
        "jlink.power": False,
    }


def discover_probes(probe_type="auto", uid=""):
    probe_type, uid = probe_selection(probe_type, uid)
    try:
        from pyocd.core.helpers import ConnectHelper
        from pyocd.probe.aggregator import PROBE_CLASSES
    except ImportError as error:
        raise RuntimeError("Live support is optional. Install: python -m pip install -e '.[hardware]'") from error
    classes = {name.lower(): klass for name, klass in PROBE_CLASSES.items()}
    if probe_type != "auto" and probe_type not in classes:
        hint = " Install the SEGGER J-Link driver package and ensure its DLL is available." if probe_type == "jlink" else " Check the pyOCD installation and platform USB driver support."
        raise RuntimeError(PROBE_TYPES[probe_type] + " driver is not available." + hint)
    selector = (probe_type + ":" + uid) if probe_type != "auto" else uid or None
    try:
        probes = ConnectHelper.get_all_connected_probes(blocking=False, unique_id=selector)
    except Exception as error:
        raise RuntimeError("Probe discovery failed for " + PROBE_TYPES[probe_type] + ": " + str(error)) from error
    result = []
    for probe in probes:
        kinds = [name for name, klass in classes.items() if isinstance(probe, klass)]
        kind = kinds[0] if len(kinds) == 1 else "unknown"
        # Check both kind and the complete UID, even though pyOCD itself also filters.
        if probe_type != "auto" and kind != probe_type:
            continue
        if uid and probe.unique_id != uid:
            continue
        result.append((probe, kind))
    return result


def list_probes(probe_type="auto") -> list[dict]:
    return [{"uid": probe.unique_id, "description": probe.description, "probe_type": kind,
             "label": PROBE_TYPES.get(kind, kind)} for probe, kind in discover_probes(probe_type)]


class PyOCDBackend:
    """No flash/halt/reset/write command surface. Attach itself is not zero-impact."""
    synthetic = False

    def __init__(self, board: Board, image: Firmware | None):
        self.board, self.image = board, image
        self.session = self.target = None

    def _memory_region(self, address: int, size: int, flash_only: bool = False):
        region = self.target.memory_map.get_region_for_address(address)
        if (region is None or size <= 0 or address + size - 1 > region.end
                or not region.is_readable
                or not (region.is_flash if flash_only else (region.is_flash or region.is_ram))):
            raise ValueError(f"Access outside target-declared {'Flash' if flash_only else 'RAM/Flash'}: 0x{address:08x}+{size}")
        return region

    def open(self):
        self.board.validate()
        if self.image is None or not self.image.segments:
            raise ValueError("Live observation requires a verifiable image; BIN also needs a load address")
        if not self.board.watches:
            raise ValueError("Select at least one scalar watch before connecting")
        # Validate known ELF symbols before touching USB. Manual watches are allowed only
        # for images with no scalar symbol table (BIN/HEX/stripped ELF).
        if self.image.symbols:
            known = {(s.name, s.address, s.size) for s in self.image.symbols}
            if any((s.name, s.address, s.size) not in known for s in self.board.watches):
                raise ValueError("A watch does not match this firmware's symbol table")
        try:
            from pyocd.core.session import Session
        except ImportError as error:
            raise RuntimeError("Install the optional hardware extra to use pyOCD") from error
        # pyOCD's helper accepts substring matches. Enforce the full UID ourselves.
        probes = discover_probes(self.board.probe_type, self.board.probe_uid)
        if len(probes) != 1:
            raise ValueError("Exact probe UID not found or not unique; no fallback probe is selected")
        self.session = Session(probes[0][0], options=pyocd_options(self.board))
        try:
            self.session.open()
            self.target = self.session.board.target
            verified = 0
            for segment in self.image.segments:
                region = self.target.memory_map.get_region_for_address(segment.address)
                if region is None or not region.is_flash:
                    continue
                self._memory_region(segment.address, len(segment.data), flash_only=True)
                for offset in range(0, len(segment.data), 1024):
                    expected = segment.data[offset:offset + 1024]
                    actual = bytes(self.target.read_memory_block8(segment.address + offset, len(expected)))
                    if actual != expected:
                        raise ValueError(f"Firmware mismatch at 0x{segment.address + offset:08x}; watching refused")
                    verified += len(expected)
            if not verified:
                raise ValueError("No load bytes fall in target-declared Flash; firmware cannot be verified")
            for symbol in self.board.watches:
                self._memory_region(symbol.address, symbol.size)
        except BaseException:
            self.close()
            raise

    def read(self, symbol: Symbol) -> bytes:
        if self.target is None:
            raise RuntimeError("Probe is not connected")
        self._memory_region(symbol.address, symbol.size)
        return bytes(self.target.read_memory_block8(symbol.address, symbol.size))

    def close(self):
        session, self.session, self.target = self.session, None, None
        if session is not None:
            session.close()


def create_backend(board: Board, image: Firmware | None):
    return DemoBackend(board, image) if board.backend == "demo" else PyOCDBackend(board, image)
