"""Controller regressions; the separate acceptance tool exercises actual Windows UI."""
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from stm32_workbench.desktop import Desktop
from stm32_workbench.examples import write_synthetic_elf
from stm32_workbench.recording import Replay


class DesktopTests(unittest.TestCase):
    def wait_for(self, desktop, condition):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            desktop.poll()
            if condition():
                return
            time.sleep(0.01)
        self.fail("Timed out waiting for controller state")

    def shutdown(self, desktop):
        desktop.stop()
        if desktop.engine:
            self.assertTrue(desktop.engine.join())
        desktop.poll()
        desktop.finish_recording()

    def test_demo_fault_isolation_reaches_snapshot(self):
        desktop = Desktop()
        desktop.dispatch({"op": "start"})
        try:
            self.wait_for(desktop, lambda: len(desktop.latest) == 12)
            desktop.dispatch({"op": "demo_fault"})
            self.wait_for(desktop, lambda: desktop.states.get(desktop.selected) == "error")
            before = desktop.total_samples
            self.wait_for(desktop, lambda: desktop.total_samples > before)
            snapshot = desktop.snapshot()
            self.assertEqual(sum(b["state"] == "watching" for b in snapshot["boards"]), 2)
            self.assertTrue(all(w["value"] is None for w in snapshot["watches"] if w["board"] == desktop.selected))
        finally:
            self.shutdown(desktop)

    def test_image_selection_workspace_persistence_and_replay(self):
        with tempfile.TemporaryDirectory(prefix="workbench-test-") as folder:
            folder = Path(folder)
            image = write_synthetic_elf(folder / "synthetic.elf")
            desktop = Desktop()
            desktop.dispatch({"op": "import", "path": str(image)})
            self.assertEqual(len(desktop.firmware_view()["symbols"]), 4)
            desktop.dispatch({"op": "add_symbols", "symbols": ["temperature_c"], "dtype": "f32"})
            workspace, recording = folder / "settings.workspace.json", folder / "session.jsonl"
            desktop.dispatch({"op": "save_workspace", "path": str(workspace)})
            desktop.dispatch({"op": "record", "path": str(recording)})
            desktop.dispatch({"op": "start"})
            try:
                self.wait_for(desktop, lambda: desktop.total_samples >= 9)
            finally:
                self.shutdown(desktop)
            desktop.dispatch({"op": "add_demo"})
            desktop.dispatch({"op": "remove_board"})
            self.assertEqual(len(desktop.boards), 3)
            desktop.dispatch({"op": "load_workspace", "path": str(workspace)})
            self.assertEqual(sum(len(b.watches) for b in desktop.boards), 9)
            self.assertEqual(desktop.boards[0].watches[0].dtype, "f32")
            expected = sum(e["kind"] == "sample" for e in Replay(recording).events)
            desktop.dispatch({"op": "open_replay", "path": str(recording)})
            desktop.dispatch({"op": "start"})
            self.wait_for(desktop, lambda: not desktop.running)
            self.assertEqual(desktop.total_samples, expected)
            self.assertTrue(desktop.snapshot()["replay"])

    def test_edit_lock_and_hardware_attachment_gate(self):
        desktop = Desktop()
        desktop.dispatch({"op": "add_live", "board_config": {"name": "Public test board", "probe_uid": "EXACT", "target": "stm32f103rc", "firmware": "user.elf", "watches": [{"name": "counter", "address": "0x20000000", "size": 4, "dtype": "u32"}]}})
        self.assertIsNone(desktop.engine)
        with self.assertRaisesRegex(ValueError, "Hardware access is disabled"):
            desktop.dispatch({"op": "start"})
        self.assertIsNone(desktop.engine)
        desktop = Desktop()
        desktop.start()
        try:
            with self.assertRaisesRegex(ValueError, "Stop sampling"):
                desktop.dispatch({"op": "import", "path": "not-opened.elf"})
        finally:
            self.shutdown(desktop)

    def test_bad_type_selection_does_not_partially_add_watches(self):
        with tempfile.TemporaryDirectory(prefix="workbench-test-") as folder:
            image = write_synthetic_elf(Path(folder) / "synthetic.elf")
            desktop = Desktop()
            desktop.dispatch({"op": "import", "path": str(image)})
            with self.assertRaises(ValueError):
                desktop.dispatch({"op": "add_symbols", "symbols": ["temperature_c"], "dtype": "f64"})
            self.assertEqual(desktop.board().watches, [])

    def test_desktop_verifier_refuses_live_workspace_before_starting_ui(self):
        from stm32_workbench.windows import launch
        with tempfile.TemporaryDirectory(prefix="workbench-test-") as folder:
            desktop = Desktop()
            desktop.dispatch({"op": "add_live", "board_config": {"name": "Unopened board", "probe_uid": "EXACT", "target": "stm32f103rc", "firmware": "not-opened.elf"}})
            workspace = Path(folder) / "live.workspace.json"
            desktop.dispatch({"op": "save_workspace", "path": str(workspace)})
            with patch("stm32_workbench.windows.build_host") as build, patch("stm32_workbench.windows.subprocess.Popen") as process:
                with self.assertRaisesRegex(ValueError, "hardware is disabled"):
                    launch(workspace, verify_dir=Path(folder) / "verification")
            build.assert_not_called()
            process.assert_not_called()
