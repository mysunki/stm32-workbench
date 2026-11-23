import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from stm32_workbench.desktop import Desktop
from stm32_workbench.models import Board, load_workspace, probe_selection, validate_boards, workspace_document


class ProbeSettingsTests(unittest.TestCase):
    def live(self, identity="one", kind="auto", uid="EXACT"):
        return Board(identity, identity, "pyocd", "not-opened.elf", uid, "stm32f103rc", probe_type=kind)

    def test_old_workspace_defaults_remain_compatible(self):
        board = Board.from_dict({"id": "old", "name": "Old", "backend": "pyocd", "firmware": "old.elf", "probe_uid": "EXACT", "target": "stm32f103rc"})
        self.assertEqual((board.probe_type, board.wire_protocol, board.debug_frequency_hz), ("auto", "swd", 1000000))

    def test_configuration_roundtrip(self):
        board = self.live(kind="jlink")
        board.wire_protocol, board.debug_frequency_hz = "jtag", 4000000
        with tempfile.TemporaryDirectory(prefix="workbench-test-") as folder:
            path = Path(folder) / "test.workspace.json"
            path.write_text(json.dumps(workspace_document([board])), encoding="utf-8")
            restored = load_workspace(path)[0]
        self.assertEqual((restored.probe_type, restored.wire_protocol, restored.debug_frequency_hz), ("jlink", "jtag", 4000000))

    def test_invalid_driver_protocol_and_frequency_are_refused(self):
        for key, value in (("probe_type", "unknown"), ("wire_protocol", "spi"), ("debug_frequency_hz", 0), ("debug_frequency_hz", True)):
            board = self.live()
            setattr(board, key, value)
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                board.validate()

    def test_uid_prefix_cannot_override_a_different_selected_driver(self):
        self.assertEqual(probe_selection("auto", "jlink:123"), ("jlink", "123"))
        with self.assertRaises(ValueError):
            probe_selection("stlink", "jlink:123")

    def test_auto_assignment_overlap_is_refused(self):
        with self.assertRaises(ValueError):
            validate_boards([self.live("one", "auto"), self.live("two", "stlink")])
        with self.assertRaises(ValueError):
            validate_boards([self.live("one", "auto", "stlink:EXACT"), self.live("two", "stlink")])
        validate_boards([self.live("one", "stlink"), self.live("two", "jlink")])

    def test_add_edit_and_snapshot_are_offline_and_preserve_selection(self):
        desktop = Desktop()
        desktop.dispatch({"op": "add_live", "board_config": self.live(kind="stlink").to_dict()})
        identity = desktop.selected
        self.assertIsNone(desktop.engine)
        desktop.dispatch({"op": "edit_live", "board": identity, "board_config": {"probe_type": "jlink", "wire_protocol": "jtag", "debug_frequency_hz": "200000"}})
        self.assertEqual(desktop.board().id, identity)
        info = next(b for b in desktop.snapshot()["boards"] if b["id"] == identity)
        self.assertEqual((info["probe_type"], info["wire_protocol"], info["debug_frequency_hz"]), ("jlink", "jtag", 200000))
        self.assertIsNone(desktop.engine)

    def test_probe_scan_passes_selected_type(self):
        desktop = Desktop()
        with patch("stm32_workbench.desktop.list_probes", return_value=[]) as scan:
            desktop.dispatch({"op": "probes", "probe_type": "cmsisdap", "request_id": "dialog"})
        scan.assert_called_once_with("cmsisdap")
        message = next(m for m in desktop.messages if m["kind"] == "probes")
        self.assertEqual(message["request_id"], "dialog")
