import json
from pathlib import Path
import struct
import tempfile
import threading
import time
import unittest

from stm32_workbench.engine import Engine, EventBuffer
from stm32_workbench.models import Board, Symbol, decode, demo_boards, load_workspace, validate_boards, workspace_document
from stm32_workbench.recording import Recorder, Replay


class ModelsTests(unittest.TestCase):
    def test_explicit_types_and_bad_reads(self):
        self.assertEqual(decode(Symbol("a", 0x20000000, 4, "f32"), struct.pack("<f", 1.25)), 1.25)
        self.assertEqual(decode(Symbol("a", 0x20000000, 4), b"\x01\x02\x03\x04"), "01 02 03 04")
        with self.assertRaises(OSError):
            decode(Symbol("a", 1, 4), b"x")
        with self.assertRaises(ValueError):
            decode(Symbol("a", 1, 4, "f32"), struct.pack("<f", float("nan")))

    def test_invalid_symbol_shapes(self):
        for values in (("", 0, 1, "u8"), ("a", 0, 8, "f32"), ("a", 0, 0, "raw"),
                       ("a", 2**32 - 1, 4, "u32"), ("a", True, 4, "u32")):
            with self.assertRaises(ValueError):
                Symbol(*values)

    def test_duplicate_probes_and_board_ids_refused(self):
        a = Board("a", "A", "pyocd", firmware="user.elf", probe_uid="exact-uid", target="stm32f103rc")
        b = Board("b", "B", "pyocd", firmware="user.elf", probe_uid="exact-uid", target="stm32f103rc")
        with self.assertRaises(ValueError):
            validate_boards([a, b])
        boards = demo_boards()
        boards[1].id = boards[0].id
        with self.assertRaises(ValueError):
            validate_boards(boards)

    def test_workspace_roundtrip_and_relative_firmware(self):
        with tempfile.TemporaryDirectory(prefix="workbench-test-") as folder:
            path = Path(folder) / "demo.workspace.json"
            boards = demo_boards()
            boards[0].firmware = "local/example.elf"
            path.write_text(json.dumps(workspace_document(boards)), encoding="utf-8")
            actual = load_workspace(path)
            self.assertEqual(actual[0].watches, boards[0].watches)
            self.assertEqual(actual[0].firmware, str((Path(folder) / "local/example.elf").resolve()))


class EngineTests(unittest.TestCase):
    def test_hardware_gate_before_backend_construction(self):
        board = Board("a", "A", "pyocd", firmware="user.elf", probe_uid="uid", target="stm32f103rc")
        with self.assertRaisesRegex(ValueError, "Hardware access is disabled"):
            Engine([board], backend_factory=lambda *_: self.fail("Must not create a backend"))

    def test_bounded_events_report_loss(self):
        buffer = EventBuffer(2)
        for i in range(4):
            buffer.put({"i": i})
        self.assertEqual(buffer.dropped, 2)
        self.assertEqual(buffer.drain(), [{"i": 2}, {"i": 3}])
        self.assertEqual(buffer.drain(), [])

    def test_invalid_event_capacity_refused(self):
        with self.assertRaises(ValueError):
            EventBuffer(0)

    def test_independent_failures_and_connection_thread_ownership(self):
        owners, reads = {}, threading.Event()
        boards = demo_boards()[:2]
        class Backend:
            def __init__(self, board): self.board = board
            def open(self): owners[self.board.id] = [threading.get_ident()]
            def read(self, symbol):
                if self.board.id == boards[0].id: raise OSError("simulated disconnected probe")
                reads.set()
                return bytes(symbol.size)
            def close(self): owners[self.board.id].append(threading.get_ident())
        engine = Engine(boards, backend_factory=lambda board, _: Backend(board))
        engine.start()
        try:
            self.assertTrue(reads.wait(2))
        finally:
            engine.request_stop()
            self.assertTrue(engine.join())
        events = engine.events.drain()
        self.assertTrue(any(e["kind"] == "error" and e["board"] == boards[0].id for e in events))
        self.assertTrue(any(e["kind"] == "sample" and e["board"] == boards[1].id for e in events))
        for owner in owners.values():
            self.assertEqual(owner[0], owner[1])
            self.assertNotEqual(owner[0], threading.get_ident())

    def test_demo_recording_and_offline_replay_roundtrip(self):
        with tempfile.TemporaryDirectory(prefix="workbench-test-") as folder:
            path = Path(folder) / "demo.jsonl"
            boards = demo_boards()
            engine = Engine(boards)
            engine.start()
            collected = []
            try:
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    collected.extend(engine.events.drain())
                    if len({e["board"] for e in collected if e["kind"] == "sample"}) == 3:
                        break
                    time.sleep(0.01)
            finally:
                engine.request_stop()
                self.assertTrue(engine.join())
                collected.extend(engine.events.drain())
            with Recorder(path, boards) as recorder:
                for event in collected: recorder.write(event)
            replay = Replay(path)
            self.assertEqual(len(replay.boards), 3)
            samples = [e for e in replay.events if e["kind"] == "sample"]
            self.assertTrue(samples)
            self.assertTrue(all(e["synthetic"] and e["read_end_ns"] >= e["read_start_ns"] for e in samples))
            events = replay.ready(1e6)
            self.assertTrue(all(e["replay"] for e in events))
            self.assertTrue(replay.finished)
            self.assertEqual(replay.ready(1e6), [])


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="workbench-test-")
        self.path = Path(self.temp.name) / "session.jsonl"
        self.boards = demo_boards()

    def tearDown(self):
        self.temp.cleanup()

    def sample(self):
        symbol = self.boards[0].watches[0]
        return {"kind": "sample", "host_ns": 100, "board": self.boards[0].id, "mode": "demo", "synthetic": True,
                "symbol": symbol.name, "address": symbol.address, "size": 4, "dtype": "f32", "raw": struct.pack("<f", 1.5).hex(), "value": 1.5,
                "read_start_ns": 80, "read_end_ns": 90}

    def test_existing_recording_never_overwritten(self):
        self.path.write_text("do not change", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            Recorder(self.path, self.boards)
        self.assertEqual(self.path.read_text(), "do not change")

    def test_corrupt_sample_and_false_provenance_refused(self):
        for change in ({"value": 4.5}, {"synthetic": False}, {"mode": "pyocd"}, {"symbol": "not-watched"}):
            event = {**self.sample(), **change}
            with Recorder(self.path, self.boards) as recorder:
                recorder.write(event)
            with self.assertRaises(ValueError):
                Replay(self.path)
            self.path.unlink()

    def test_truncated_recording_is_not_silently_accepted(self):
        with Recorder(self.path, self.boards) as recorder:
            recorder.write(self.sample())
        with self.path.open("a") as out:
            out.write('{"kind": "sample"')
        with self.assertRaisesRegex(ValueError, "partial data"):
            Replay(self.path)

    def test_multithread_event_order_is_sorted_for_replay(self):
        with Recorder(self.path, self.boards) as recorder:
            recorder.write({**self.sample(), "host_ns": 200})
            recorder.write(self.sample())
        replay = Replay(self.path)
        self.assertEqual([e["host_ns"] for e in replay.events], [100, 200])

    def test_hardware_recording_replay_needs_no_image_or_probe(self):
        self.boards[0].backend = "pyocd"
        self.boards[0].firmware = "does-not-exist.elf"
        self.boards[0].probe_uid, self.boards[0].target = "offline-only", "stm32f103rc"
        with Recorder(self.path, self.boards) as recorder:
            recorder.write({**self.sample(), "mode": "pyocd", "synthetic": False})
        replay = Replay(self.path)
        self.assertEqual(replay.boards[0].backend, "pyocd")
        self.assertFalse(replay.ready(0)[0]["synthetic"])

    def test_malformed_event_objects_states_and_timing_refused(self):
        for event in ([1, 2], {**self.sample(), "read_end_ns": 101},
                      {**self.sample(), "kind": "state", "state": "invented"},
                      {"kind": "gap", "host_ns": 100, "dropped_total": "unknown"}):
            with Recorder(self.path, self.boards) as recorder:
                recorder.write(event)
            with self.assertRaises(ValueError):
                Replay(self.path)
            self.path.unlink()
