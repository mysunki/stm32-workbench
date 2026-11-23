"""Create a small synthetic symbol-inspection example; not runnable MCU firmware."""
from pathlib import Path
import struct


def synthetic_elf() -> bytes:
    names = ("temperature_c", "supply_v", "motor_rpm", "tick")
    strings = bytearray(b"\0")
    offsets = []
    for name in names:
        offsets.append(len(strings))
        strings.extend(name.encode("ascii") + b"\0")
    raw = bytearray(0x110)
    raw[:16] = b"\x7fELF\x01\x01\x01" + b"\0" * 9
    raw[0x100:0x110] = struct.pack("<ffII", 25.0, 3.3, 1200, 0)
    symbols = bytearray(16)
    for index, offset in enumerate(offsets):
        symbols.extend(struct.pack("<IIIBBH", offset, 0x20000000 + index * 4, 4, 0x11, 0, 1))
    symbol_offset = len(raw)
    raw.extend(symbols)
    string_offset = len(raw)
    raw.extend(strings)
    raw.extend(b"\0" * (-len(raw) % 4))
    section_offset = len(raw)
    sections = [(0,) * 10, (0, 1, 3, 0x20000000, 0x100, 16, 0, 0, 4, 0),
                (0, 2, 0, 0, symbol_offset, len(symbols), 3, 1, 4, 16),
                (0, 3, 0, 0, string_offset, len(strings), 0, 0, 1, 0)]
    for section in sections:
        raw.extend(struct.pack("<IIIIIIIIII", *section))
    struct.pack_into("<HHIIIIIHHHHHH", raw, 16, 2, 40, 1, 0, 52, section_offset, 0, 52, 32, 1, 40, 4, 0)
    struct.pack_into("<IIIIIIII", raw, 52, 1, 0x100, 0x20000000, 0x08000000, 16, 16, 6, 4)
    return bytes(raw)


def write_synthetic_elf(path):
    path = Path(path)
    with path.open("xb") as output:
        output.write(synthetic_elf())
    return path
