import struct
import tempfile
import unittest
from pathlib import Path

from stm32_workbench.firmware import inspect_firmware


def arm_elf():
    """A synthetic ELF container, not an executable vendor/MCU firmware."""
    raw = bytearray(0x108)
    raw[:16] = b"\x7fELF\x01\x01\x01" + b"\0" * 9
    names = b"\0temperature_c\0counter\0"
    symbols = b"\0" * 16 + struct.pack("<IIIBBH", 1, 0x20000000, 4, 0x11, 0, 1)
    symbols += struct.pack("<IIIBBH", 15, 0x20000004, 4, 0x11, 0, 1)
    symoffset = len(raw)
    raw.extend(symbols)
    stroffset = len(raw)
    raw.extend(names)
    raw.extend(b"\0" * (-len(raw) % 4))
    shoffset = len(raw)
    sections = [(0,) * 10, (0, 1, 3, 0x20000000, 0x100, 8, 0, 0, 4, 0),
                (0, 2, 0, 0, symoffset, len(symbols), 3, 1, 4, 16),
                (0, 3, 0, 0, stroffset, len(names), 0, 0, 1, 0)]
    for section in sections:
        raw.extend(struct.pack("<IIIIIIIIII", *section))
    struct.pack_into("<HHIIIIIHHHHHH", raw, 16, 2, 40, 1, 0x08000001, 52, shoffset, 0, 52, 32, 1, 40, 4, 0)
    struct.pack_into("<IIIIIIII", raw, 52, 1, 0x100, 0x20000000, 0x08000000, 8, 8, 6, 4)
    raw[0x100:0x108] = struct.pack("<fI", 23.5, 42)
    return bytes(raw)


def hex_record(address, kind, payload=b""):
    data = bytes([len(payload)]) + address.to_bytes(2, "big") + bytes([kind]) + payload
    return ":" + (data + bytes([(-sum(data)) & 255])).hex().upper()


class FirmwareTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="workbench-test-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def image(self, name, data, **kwargs):
        path = self.root / name
        path.write_bytes(data)
        return inspect_firmware(path, **kwargs)

    def test_elf_object_symbols_and_load_address(self):
        image = self.image("synthetic.out", arm_elf())
        byname = {s.name: s for s in image.symbols}
        self.assertEqual(set(byname), {"counter", "temperature_c"})
        self.assertEqual(byname["temperature_c"].address, 0x20000000)
        self.assertEqual(byname["temperature_c"].dtype, "raw")
        self.assertEqual(image.segments[0].address, 0x08000000)
        self.assertEqual(image.segments[0].data, struct.pack("<fI", 23.5, 42))
        self.assertEqual(len(image.sha256), 64)

    def test_truncation_refused(self):
        with self.assertRaises(ValueError):
            self.image("broken.elf", arm_elf()[:100])

    def test_non_arm_and_relocatable_elf_refused(self):
        for offset, value in ((16, 1), (18, 62)):
            raw = bytearray(arm_elf())
            struct.pack_into("<H", raw, offset, value)
            with self.assertRaises(ValueError):
                self.image("unsupported.elf", raw)

    def test_unknown_size_is_not_guessed_as_float(self):
        image = self.image("synthetic.elf", arm_elf())
        self.assertTrue(all(s.dtype == "raw" for s in image.symbols))

    def test_binary_has_no_symbols_or_assumed_address(self):
        image = self.image("generic.bin", b"abcd")
        self.assertEqual(image.symbols, [])
        self.assertEqual(image.segments, [])
        image = self.image("generic.bin", b"abcd", base_address=0x08000000)
        self.assertEqual(image.segments[0].address, 0x08000000)

    def test_binary_address_overflow_refused(self):
        with self.assertRaises(ValueError):
            self.image("generic.bin", b"abcd", base_address=0xFFFFFFFE)

    def test_hex_sparse_addresses_preserved_without_zero_filling(self):
        lines = [hex_record(0, 4, b"\x08\x00"), hex_record(0, 0, b"abc"),
                 hex_record(0x1000, 0, b"xyz"), hex_record(0, 1)]
        image = self.image("generic.hex", "\n".join(lines).encode())
        self.assertEqual([(s.address, s.data) for s in image.segments], [(0x08000000, b"abc"), (0x08001000, b"xyz")])

    def test_hex_bad_checksum_and_missing_eof_refused(self):
        for text in (":010000000100", hex_record(0, 0, b"x")):
            with self.assertRaises(ValueError):
                self.image("invalid.hex", text.encode())

    def test_hex_conflicting_overlap_and_trailing_record_refused(self):
        for lines in ([hex_record(0, 0, b"a"), hex_record(0, 0, b"b"), hex_record(0, 1)],
                      [hex_record(0, 0, b"a"), hex_record(0, 1), hex_record(1, 0, b"b")]):
            with self.assertRaises(ValueError):
                self.image("invalid.hex", "\n".join(lines).encode())

    def test_unknown_map_dialect_refused(self):
        with self.assertRaises(ValueError):
            self.image("unknown.map", b"var 0x20000000")
