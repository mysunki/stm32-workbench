"""Adapter contract checks using fake modules and fake memory. No USB access."""
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from stm32_workbench.backends import PyOCDBackend, pyocd_options
from stm32_workbench.firmware import Firmware, Segment
from stm32_workbench.models import Board, Symbol


class Region:
    def __init__(self, start, end, flash):
        self.start, self.end, self.is_flash, self.is_ram = start, end, flash, not flash
        self.is_readable = True


class HardwareContractTests(unittest.TestCase):
    def setUp(self):
        self.watch = Symbol("counter", 0x20000000, 4, "u32")
        self.board = Board("board", "Board", "pyocd", "generic.elf", "EXACT123", "stm32f103rc", watches=[self.watch])
        self.image = Firmware("generic.elf", "ELF32", "a" * 64, 4, [self.watch], [Segment(0x08000000, b"TEST")])
        self.reads, self.states, self.options = [], [], []
        self.flash = b"TEST"
        self.uid = "EXACT123"

    def fake_modules(self):
        test = self
        class Target:
            memory_map = SimpleNamespace(get_region_for_address=lambda address:
                Region(0x08000000, 0x0800FFFF, True) if 0x08000000 <= address <= 0x0800FFFF else
                Region(0x20000000, 0x20003FFF, False) if 0x20000000 <= address <= 0x20003FFF else None)
            def read_memory_block8(self, address, size):
                test.reads.append((address, size))
                return list(test.flash[:size] if address == 0x08000000 else bytes(size))
        class Session:
            def __init__(self, probe, options):
                test.options.append(options)
                self.board = SimpleNamespace(target=Target())
            def open(self): test.states.append("open")
            def close(self): test.states.append("close")
        helpers, session = ModuleType("pyocd.core.helpers"), ModuleType("pyocd.core.session")
        helpers.ConnectHelper = SimpleNamespace(get_all_connected_probes=lambda blocking: [SimpleNamespace(unique_id=test.uid)])
        session.Session = Session
        return {"pyocd": ModuleType("pyocd"), "pyocd.core": ModuleType("pyocd.core"),
                "pyocd.core.helpers": helpers, "pyocd.core.session": session}

    def test_exact_uid_verified_flash_and_scalar_read(self):
        with patch.dict(sys.modules, self.fake_modules()):
            backend = PyOCDBackend(self.board, self.image)
            backend.open()
            self.assertEqual(backend.read(self.watch), b"\0" * 4)
            backend.close()
        self.assertEqual(self.states, ["open", "close"])
        self.assertEqual(self.reads, [(0x08000000, 4), (0x20000000, 4)])

    def test_substring_probe_match_is_never_used(self):
        self.uid = "PREFIX-EXACT123-SUFFIX"
        with patch.dict(sys.modules, self.fake_modules()):
            with self.assertRaisesRegex(ValueError, "Exact probe UID"):
                PyOCDBackend(self.board, self.image).open()
        self.assertEqual(self.states, [])

    def test_mismatch_refuses_watch_and_closes_session(self):
        self.flash = b"FAIL"
        with patch.dict(sys.modules, self.fake_modules()):
            with self.assertRaisesRegex(ValueError, "Firmware mismatch"):
                PyOCDBackend(self.board, self.image).open()
        self.assertEqual(self.states, ["open", "close"])
        self.assertNotIn((0x20000000, 4), self.reads)

    def test_peripheral_and_cross_boundary_reads_refused(self):
        with patch.dict(sys.modules, self.fake_modules()):
            backend = PyOCDBackend(self.board, self.image)
            backend.open()
            try:
                for watch in (Symbol("mmio", 0x40000000, 4, "u32"), Symbol("cross", 0x20003FFE, 4, "u32")):
                    with self.assertRaises(ValueError):
                        backend.read(watch)
            finally:
                backend.close()

    def test_attach_no_unlock_no_memory_cache_and_no_default_script(self):
        options = pyocd_options(self.board)
        self.assertEqual(options["connect_mode"], "attach")
        self.assertFalse(options["auto_unlock"])
        self.assertFalse(options["resume_on_disconnect"])
        self.assertFalse(options["cache.enable_memory"])
        self.assertTrue(options["no_config"])
        self.assertTrue(options["user_script"].endswith("_pyocd_noop.py"))

    def test_wrong_symbol_table_refused_before_usb(self):
        self.board.watches = [Symbol("wrong", 0x20000004, 4, "u32")]
        with self.assertRaisesRegex(ValueError, "symbol table"):
            PyOCDBackend(self.board, self.image).open()
        self.assertEqual(self.states, [])
