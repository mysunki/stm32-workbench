"""Bounded ARM ELF32, Intel HEX and raw BIN inspection. No probe access."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import hashlib
import io
from pathlib import Path
import struct

from .models import Symbol

MAX_FILE = 64 * 1024 * 1024
MAX_IMAGE = 16 * 1024 * 1024


@dataclass(frozen=True)
class Segment:
    address: int
    data: bytes


@dataclass
class Firmware:
    path: str
    format: str
    sha256: str
    size: int
    symbols: list[Symbol] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def summary(self):
        return {"file": Path(self.path).name, "format": self.format, "sha256": self.sha256,
                "size": self.size, "symbols": [asdict(s) for s in self.symbols],
                "segments": [{"address": hex(s.address), "size": len(s.data)} for s in self.segments],
                "notes": self.notes}


def _slice(data: bytes, offset: int, size: int) -> bytes:
    if offset < 0 or size < 0 or offset + size > len(data):
        raise ValueError("Truncated or out-of-bounds firmware structure")
    return data[offset:offset + size]


def _cstring(data: bytes, offset: int) -> str:
    if not 0 <= offset < len(data):
        raise ValueError("Invalid string-table offset")
    end = data.find(b"\0", offset)
    if end < 0:
        raise ValueError("Unterminated symbol name")
    return data[offset:end].decode("utf-8", errors="replace")


def _elf(image: Firmware, raw: bytes):
    if len(raw) < 52 or raw[:7] != b"\x7fELF\x01\x01\x01":
        raise ValueError("Expected a 32-bit, little-endian ELF version 1")
    fields = struct.unpack_from("<HHIIIIIHHHHHH", raw, 16)
    kind, machine, version, _, phoff, shoff, _, ehsize, phsize, phnum, shsize, shnum, _ = fields
    if kind != 2 or machine != 40 or version != 1 or ehsize < 52:
        raise ValueError("Only linked ARM ELF32 executables are supported (not relocatable objects)")
    if phnum > 1024 or shnum > 10000 or (phnum and phsize < 32) or (shnum and shsize < 40):
        raise ValueError("Invalid or unsupported ELF table layout")
    total = 0
    for i in range(phnum):
        entry = _slice(raw, phoff + i * phsize, 32)
        ptype, offset, _, physical, filesz, memsz, _, _ = struct.unpack("<IIIIIIII", entry)
        if ptype != 1 or not filesz:
            continue
        if filesz > memsz or physical + memsz > 2**32:
            raise ValueError("Invalid ELF load segment")
        chunk = _slice(raw, offset, filesz)
        total += filesz
        if total > MAX_IMAGE:
            raise ValueError("ELF load image exceeds 16 MiB")
        # Keep all load segments: the live adapter verifies only target-declared Flash.
        image.segments.append(Segment(physical, chunk))
    sections = [struct.unpack("<IIIIIIIIII", _slice(raw, shoff + i * shsize, 40)) for i in range(shnum)]
    found = {}
    for section in sections:
        _, stype, _, _, offset, size, link, _, _, entsize = section
        if stype not in (2, 11):
            continue
        if link >= len(sections) or entsize < 16 or size % entsize:
            raise ValueError("Invalid ELF symbol table")
        strings = sections[link]
        if strings[1] != 3:
            raise ValueError("Symbol table does not reference a string table")
        names = _slice(raw, strings[4], strings[5])
        _slice(raw, offset, size)
        if size // entsize > 200000:
            raise ValueError("ELF symbol table is too large")
        for pos in range(offset, offset + size, entsize):
            nameidx, address, nbytes, info, _, sectionidx = struct.unpack("<IIIBBH", _slice(raw, pos, 16))
            if info & 15 != 1 or not 0 < sectionidx < len(sections) or not 1 <= nbytes <= 8:
                continue
            name = _cstring(names, nameidx)
            if not name or len(name) > 256:
                continue
            symbol = Symbol(name, address, nbytes)
            found[(name, address)] = symbol
    duplicates = {}
    for name, address in found:
        duplicates[name] = duplicates.get(name, 0) + 1
    image.symbols = sorted((replace(s, name=f"{s.name}@{s.address:08x}") if duplicates[s.name] > 1 else s
                            for s in found.values()), key=lambda s: (s.name.lower(), s.address))
    image.notes.append("Scalar object symbols only. Unknown C types remain raw bytes; sizes do not imply a type.")
    _dwarf_types(image, raw)
    if not image.symbols:
        image.notes.append("No scalar object symbols found. Rebuild with symbols or configure explicit addresses/types.")


def _dwarf_types(image: Firmware, raw: bytes):
    try:
        from elftools.elf.elffile import ELFFile
    except ImportError:
        image.notes.append("Optional DWARF type inference: install the dwarf extra. Manual type selection is available.")
        return
    try:
        elf = ELFFile(io.BytesIO(raw))
        if not elf.has_dwarf_info():
            return
        typed = {}
        for cu in elf.get_dwarf_info().iter_CUs():
            for die in cu.iter_DIEs():
                if die.tag != "DW_TAG_variable" or "DW_AT_type" not in die.attributes:
                    continue
                loc = die.attributes.get("DW_AT_location")
                if loc is None or not isinstance(loc.value, (list, bytes)) or len(loc.value) != 5 or loc.value[0] != 3:
                    continue  # Only fixed DW_OP_addr globals; never guess register/stack locations.
                address = int.from_bytes(bytes(loc.value[1:]), "little")
                dtype_die = die.get_DIE_from_attribute("DW_AT_type")
                seen = set()
                while dtype_die and dtype_die.tag in ("DW_TAG_typedef", "DW_TAG_const_type", "DW_TAG_volatile_type", "DW_TAG_restrict_type"):
                    if dtype_die.offset in seen or "DW_AT_type" not in dtype_die.attributes:
                        dtype_die = None
                        break
                    seen.add(dtype_die.offset)
                    dtype_die = dtype_die.get_DIE_from_attribute("DW_AT_type")
                if dtype_die is None or dtype_die.tag != "DW_TAG_base_type":
                    continue
                size = dtype_die.attributes.get("DW_AT_byte_size")
                encoding = dtype_die.attributes.get("DW_AT_encoding")
                if not size or not encoding:
                    continue
                prefix = {2: "bool", 4: "f", 5: "i", 6: "i", 7: "u", 8: "u"}.get(encoding.value)
                if not prefix:
                    continue
                dtype = "bool" if prefix == "bool" and size.value == 1 else f"{prefix}{size.value * 8}"
                nameattr = die.attributes.get("DW_AT_linkage_name") or die.attributes.get("DW_AT_name")
                if nameattr:
                    typed[(nameattr.value.decode("utf-8", errors="replace"), address)] = dtype
        from .models import TYPES
        for i, symbol in enumerate(image.symbols):
            dtype = typed.get((symbol.name.split("@")[0], symbol.address))
            if dtype in TYPES:
                image.symbols[i] = replace(symbol, dtype=dtype)
    except Exception as error:
        image.notes.append(f"DWARF type inference unavailable: {type(error).__name__}; symbols remain usable as raw bytes.")


def _hex(image: Firmware, raw: bytes):
    memory = {}
    base, eof = 0, False
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as error:
        raise ValueError("Intel HEX must be ASCII") from error
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if eof or not line.startswith(":"):
            raise ValueError("Invalid HEX record or content after EOF")
        try:
            record = bytes.fromhex(line[1:])
        except ValueError as error:
            raise ValueError("Invalid HEX encoding") from error
        if len(record) < 5 or len(record) != record[0] + 5 or sum(record) & 255:
            raise ValueError("HEX length or checksum mismatch")
        size, address, kind = record[0], int.from_bytes(record[1:3], "big"), record[3]
        payload = record[4:-1]
        if kind == 0:
            start = base + address
            if address + size > 0x10000 or start + size > 2**32:
                raise ValueError("HEX address overflow")
            for i, value in enumerate(payload):
                pos = start + i
                if pos in memory and memory[pos] != value:
                    raise ValueError("Conflicting overlapping HEX records")
                memory[pos] = value
            if len(memory) > MAX_IMAGE:
                raise ValueError("HEX data exceeds 16 MiB")
        elif kind == 1 and not size and not address:
            eof = True
        elif kind in (2, 4) and size == 2 and not address:
            base = int.from_bytes(payload, "big") << (4 if kind == 2 else 16)
        elif kind in (3, 5) and size == 4 and not address:
            pass  # Start address is metadata, not a memory load record.
        else:
            raise ValueError("Unsupported or malformed HEX record")
    if not eof or not memory:
        raise ValueError("HEX must contain data and an EOF record")
    start, previous, chunk = None, None, bytearray()
    for address in sorted(memory):
        if previous is not None and address != previous + 1:
            image.segments.append(Segment(start, bytes(chunk)))
            chunk = bytearray()
            start = None
        if start is None:
            start = address
        chunk.append(memory[address])
        previous = address
    image.segments.append(Segment(start, bytes(chunk)))
    image.notes.append("HEX stores load addresses and bytes, not C variable names or types.")


def inspect_firmware(path: str | Path, base_address: int | None = None) -> Firmware:
    path = Path(path)
    if not 0 < path.stat().st_size <= MAX_FILE:
        raise ValueError("Firmware must be non-empty and at most 64 MiB")
    raw = path.read_bytes()
    if len(raw) > MAX_FILE:
        raise ValueError("Firmware changed while reading or exceeds 64 MiB")
    suffix = path.suffix.lower()
    kind = "ELF32" if raw.startswith(b"\x7fELF") else "Intel HEX" if suffix == ".hex" else "BIN" if suffix == ".bin" else "unknown"
    image = Firmware(str(path.resolve()), kind, hashlib.sha256(raw).hexdigest(), len(raw))
    if kind == "ELF32":
        _elf(image, raw)
    elif kind == "Intel HEX":
        _hex(image, raw)
    elif kind == "BIN":
        if len(raw) > MAX_IMAGE:
            raise ValueError("BIN load image exceeds 16 MiB")
        if base_address is not None:
            if type(base_address) is not int or not 0 <= base_address < base_address + len(raw) <= 2**32:
                raise ValueError("Invalid BIN load address")
            image.segments.append(Segment(base_address, raw))
        image.notes.append("BIN has no symbol names, types, or load address. Supply a base address and explicit watches for live use.")
    else:
        raise ValueError("Use a linked ARM ELF/OUT/AXF file, Intel HEX, or .bin file. MAP dialects are not auto-guessed.")
    return image
