"""A local Tkinter desktop: no web server, telemetry, or automatic USB connection."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import replace
import json
from pathlib import Path
import time
import uuid

from .engine import Engine
from .firmware import inspect_firmware
from .models import Board, Symbol, TYPES, demo_boards, integer, load_workspace, workspace_document
from .recording import Recorder, Replay

BG, PANEL, INK, MUTED, TEAL, LINE = "#0c1524", "#162338", "#e6eef8", "#9badc6", "#58dfc1", "#2a3c55"


class Workbench:
    def __init__(self, root, boards: list[Board]):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk, self.root = tk, ttk, root
        self.boards = boards
        self.engine = self.recorder = self.replay = None
        self.images = {}
        self.samples = defaultdict(lambda: deque(maxlen=1200))
        self.rows, self.last_received, self.board_states = {}, {}, {}
        self.running, self.closing = False, False
        self.origin = self.replay_start = 0
        self.dropped_seen = 0
        self.root.title("STM32 Workbench · Multi-board observation")
        self.root.geometry("1280x820")
        self.root.minsize(960, 650)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._style()
        self._build()
        self._refresh_boards()
        self._refresh_watches()
        self._log("Ready. Demo signals are synthetic. Importing firmware never opens a probe.")
        self.root.after(80, self.tick)

    def _style(self):
        style = self.ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=INK, font=("Segoe UI", 10), bordercolor=LINE)
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=INK)
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Title.TLabel", font=("Segoe UI", 21, "bold"))
        style.configure("Accent.TLabel", foreground=TEAL, font=("Segoe UI", 10, "bold"))
        style.configure("TButton", background=PANEL, padding=(12, 8), borderwidth=1)
        style.map("TButton", background=[("active", "#29405b")], foreground=[("disabled", "#708198")])
        style.configure("Accent.TButton", background="#167d71", foreground="#ffffff")
        style.map("Accent.TButton", background=[("active", "#219c8d")])
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=INK, rowheight=30, borderwidth=0)
        style.configure("Treeview.Heading", background="#20314a", foreground=MUTED, padding=8)
        style.map("Treeview", background=[("selected", "#275c69")], foreground=[("selected", "#ffffff")])
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=PANEL, padding=(18, 10))
        style.map("TNotebook.Tab", background=[("selected", "#29405b")])
        style.configure("TEntry", fieldbackground=PANEL, foreground=INK, insertcolor=INK, padding=5)
        style.configure("TCombobox", fieldbackground=PANEL, background=PANEL, foreground=INK)

    def _build(self):
        tk, ttk = self.tk, self.ttk
        header = ttk.Frame(self.root, padding=(24, 20, 24, 10))
        header.pack(fill="x")
        ttk.Label(header, text="STM32 WORKBENCH", style="Title.TLabel").pack(side="left")
        self.mode = ttk.Label(header, text="DEMO / SYNTHETIC", style="Accent.TLabel")
        self.mode.pack(side="right")
        ttk.Label(self.root, text="Many boards. One workspace.  Firmware inspection · Variable watch · Session replay", style="Muted.TLabel").pack(anchor="w", padx=26)
        toolbar = ttk.Frame(self.root, padding=(24, 16))
        toolbar.pack(fill="x")
        self.start_button = ttk.Button(toolbar, text="Start watching", style="Accent.TButton", command=self.start)
        self.start_button.pack(side="left", padx=(0, 8))
        ttk.Button(toolbar, text="Stop sampling", command=self.stop).pack(side="left", padx=(0, 8))
        self.record_button = ttk.Button(toolbar, text="Record session", command=self.toggle_record)
        self.record_button.pack(side="left", padx=(0, 8))
        ttk.Button(toolbar, text="Open recording", command=self.open_replay).pack(side="left", padx=(0, 8))
        ttk.Button(toolbar, text="Load workspace", command=self.open_workspace).pack(side="right", padx=(8, 0))
        ttk.Button(toolbar, text="Save workspace", command=self.save_workspace).pack(side="right")
        panes = ttk.Panedwindow(self.root, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=24, pady=(0, 12))
        sidebar = ttk.Frame(panes, padding=(0, 0, 16, 0))
        panes.add(sidebar, weight=0)
        ttk.Label(sidebar, text="BOARDS", style="Accent.TLabel").pack(anchor="w", pady=(4, 10))
        self.board_tree = ttk.Treeview(sidebar, columns=("source", "state"), show="tree headings", height=10, selectmode="browse")
        self.board_tree.heading("#0", text="Board")
        self.board_tree.heading("source", text="Source")
        self.board_tree.heading("state", text="State")
        self.board_tree.column("#0", width=125, minwidth=95)
        self.board_tree.column("source", width=62, stretch=False)
        self.board_tree.column("state", width=85, stretch=False)
        self.board_tree.pack(fill="both", expand=True)
        self.board_tree.bind("<<TreeviewSelect>>", lambda _: self._show_firmware())
        for text, command in (("Add demo board", self.add_demo), ("Add live board", self.add_live),
                              ("Remove board", self.remove_board), ("Import firmware", self.import_firmware),
                              ("List USB probes", self.show_probes), ("Reset to 3-board demo", self.reset_demo)):
            ttk.Button(sidebar, text=text, command=command).pack(fill="x", pady=(8, 0))
        ttk.Label(sidebar, text="Import is offline.\nStart is always explicit.\nOne probe per live board.", style="Muted.TLabel").pack(anchor="w", pady=(16, 0))
        right = ttk.Frame(panes)
        panes.add(right, weight=1)
        notebook = ttk.Notebook(right)
        notebook.pack(fill="both", expand=True)
        watch_tab, firmware_tab, log_tab = (ttk.Frame(notebook, padding=12) for _ in range(3))
        notebook.add(watch_tab, text="Variable watch")
        notebook.add(firmware_tab, text="Firmware inspector")
        notebook.add(log_tab, text="Session log")
        self.watch_tree = self._tree(watch_tab, ("board", "symbol", "address", "type", "value", "status"),
                                     (100, 150, 100, 52, 120, 90), height=8)
        self.watch_tree.bind("<<TreeviewSelect>>", lambda _: self.draw_chart())
        actions = ttk.Frame(watch_tab, padding=(0, 10))
        actions.pack(fill="x")
        ttk.Button(actions, text="Add explicit watch", command=self.add_manual_watch).pack(side="left")
        ttk.Button(actions, text="Remove selected watch", command=self.remove_watch).pack(side="left", padx=8)
        ttk.Label(actions, text="Select a numeric row to plot", style="Muted.TLabel").pack(side="right")
        self.chart = tk.Canvas(watch_tab, bg="#101c2e", highlightthickness=1, highlightbackground=LINE, height=235)
        self.chart.pack(fill="both", expand=True)
        self.chart.bind("<Configure>", lambda _: self.draw_chart())
        ttk.Label(watch_tab, text="PC timestamps · Sequential reads · No cross-board synchronization · 1,200 points per series", style="Muted.TLabel").pack(anchor="w", pady=(8, 0))
        self.firmware_info = tk.StringVar(value="Choose a board, then import its firmware. No probe will be opened.")
        ttk.Label(firmware_tab, textvariable=self.firmware_info, wraplength=700, justify="left").pack(anchor="w", fill="x", pady=(0, 10))
        symbol_bar = ttk.Frame(firmware_tab)
        symbol_bar.pack(fill="x", pady=(0, 10))
        self.symbol_search = tk.StringVar()
        self.symbol_search.trace_add("write", lambda *_: self._show_firmware())
        ttk.Label(symbol_bar, text="Find symbol").pack(side="left", padx=(0, 8))
        ttk.Entry(symbol_bar, textvariable=self.symbol_search).pack(side="left", fill="x", expand=True)
        self.symbol_tree = self._tree(firmware_tab, ("symbol", "address", "size", "inferred"), (240, 120, 70, 100), height=10, multi=True)
        add_bar = ttk.Frame(firmware_tab, padding=(0, 10))
        add_bar.pack(fill="x")
        ttk.Label(add_bar, text="Interpret as").pack(side="left")
        self.watch_type = tk.StringVar(value="auto")
        ttk.Combobox(add_bar, textvariable=self.watch_type, values=("auto", *TYPES), width=9, state="readonly").pack(side="left", padx=8)
        ttk.Button(add_bar, text="Watch selected symbols", command=self.add_symbols).pack(side="left")
        self.log_text = tk.Text(log_tab, background=PANEL, foreground=INK, insertbackground=INK, relief="flat", wrap="word", font=("Consolas", 10), state="disabled")
        self.log_text.pack(fill="both", expand=True)
        self.status = tk.StringVar(value="Ready · No hardware connection")
        ttk.Label(self.root, textvariable=self.status, style="Muted.TLabel", padding=(24, 2, 24, 14)).pack(fill="x")

    def _tree(self, parent, columns, widths, height=10, multi=False):
        frame = self.ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        tree = self.ttk.Treeview(frame, columns=columns, show="headings", height=height, selectmode="extended" if multi else "browse")
        for name, width in zip(columns, widths):
            tree.heading(name, text=name.capitalize())
            tree.column(name, width=width, minwidth=45)
        scrollbar = self.ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)
        return tree

    def _log(self, message):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{time.strftime('%H:%M:%S')}  {message}\n")
        if int(self.log_text.index("end-1c").split(".")[0]) > 2000:
            self.log_text.delete("1.0", "200.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _error(self, error):
        from tkinter import messagebox
        self._log(str(error))
        messagebox.showerror("STM32 Workbench", str(error), parent=self.root)

    def _editable(self):
        if self.running or (self.engine and self.engine.alive) or self.recorder:
            self._error("Stop sampling and finish recording before changing the workspace.")
            return False
        if self.replay:
            self._error("This is a replay workspace. Load a workspace or reset the demo to edit it.")
            return False
        return True

    def _selected_board(self):
        selected = self.board_tree.selection()
        return next((b for b in self.boards if selected and b.id == selected[0]), self.boards[0])

    def _refresh_boards(self):
        selected = self.board_tree.selection()
        self.board_tree.delete(*self.board_tree.get_children())
        for board in self.boards:
            self.board_tree.insert("", "end", iid=board.id, text=board.name,
                                   values=("REPLAY" if self.replay else board.backend.upper(), self.board_states.get(board.id, "ready")))
        self.board_tree.selection_set(selected[0] if selected and any(b.id == selected[0] for b in self.boards) else self.boards[0].id)
        modes = {b.backend for b in self.boards}
        self.mode.configure(text="REPLAY / OFFLINE" if self.replay else "DEMO / SYNTHETIC" if modes == {"demo"} else "LIVE CONFIGURED / EXPLICIT START")

    def _refresh_watches(self):
        self.watch_tree.delete(*self.watch_tree.get_children())
        self.rows.clear()
        for board in self.boards:
            for symbol in board.watches:
                row = self.watch_tree.insert("", "end", values=(board.name, symbol.name, f"0x{symbol.address:08x}", symbol.dtype, "—", "ready"))
                self.rows[(board.id, symbol.name)] = row
        if self.watch_tree.get_children():
            self.watch_tree.selection_set(self.watch_tree.get_children()[0])
        self.draw_chart()

    def _show_firmware(self):
        board = self._selected_board()
        image = self.images.get(board.id)
        self.symbol_tree.delete(*self.symbol_tree.get_children())
        self.visible_symbols = {}
        if image is None:
            self.firmware_info.set("Recorded workspace; firmware files are not required for replay." if self.replay else
                                   f"{board.name}: no image inspected. Import an ELF/OUT/AXF, HEX, or BIN file.")
            return
        query = self.symbol_search.get().strip().lower()
        matches = [s for s in image.symbols if query in s.name.lower()]
        self.firmware_info.set(f"{Path(image.path).name} · {image.format} · {image.size:,} bytes\nSHA256 {image.sha256}\n{len(image.symbols):,} scalar symbols · showing up to 2,000 matches\n" + " ".join(image.notes))
        for index, symbol in enumerate(matches[:2000]):
            key = str(index)
            self.visible_symbols[key] = symbol
            self.symbol_tree.insert("", "end", iid=key, values=(symbol.name, f"0x{symbol.address:08x}", symbol.size, symbol.dtype))

    def _dialog(self, title, fields):
        tk, ttk = self.tk, self.ttk
        window = tk.Toplevel(self.root)
        window.title(title)
        window.configure(bg=BG)
        window.transient(self.root)
        window.grab_set()
        values, result = {}, {}
        panel = ttk.Frame(window, padding=22)
        panel.pack(fill="both", expand=True)
        for i, (key, label, default) in enumerate(fields):
            ttk.Label(panel, text=label).grid(row=i, column=0, sticky="w", padx=(0, 18), pady=7)
            value = tk.StringVar(value=default)
            values[key] = value
            entry = ttk.Combobox(panel, textvariable=value, values=TYPES, state="readonly", width=29) if key == "dtype" else ttk.Entry(panel, textvariable=value, width=32)
            entry.grid(row=i, column=1, sticky="ew")
            if i == 0:
                entry.focus_set()
        def submit():
            result.update({key: value.get().strip() for key, value in values.items()})
            window.destroy()
        ttk.Button(panel, text="Add", command=submit).grid(row=len(fields), column=1, sticky="e", pady=(16, 0))
        window.bind("<Return>", lambda _: submit())
        window.bind("<Escape>", lambda _: window.destroy())
        self.root.wait_window(window)
        return result

    def add_demo(self):
        if not self._editable():
            return
        if len(self.boards) >= 16:
            return self._error("At most 16 boards per workspace")
        board = demo_boards()[0]
        board.id, board.name = uuid.uuid4().hex[:12], f"Demo {len(self.boards) + 1}"
        self.boards.append(board)
        self._refresh_boards()
        self._refresh_watches()

    def add_live(self):
        if not self._editable():
            return
        if len(self.boards) >= 16:
            return self._error("At most 16 boards per workspace")
        values = self._dialog("Configure a live board (does not connect)", [
            ("name", "Board name", "My STM32"), ("probe_uid", "Exact probe UID", ""),
            ("target", "pyOCD target name", ""), ("interval", "Interval (ms)", "100")])
        if not values:
            return
        try:
            if not values["name"] or not values["probe_uid"] or not values["target"]:
                raise ValueError("Name, exact probe UID, and target are required")
            if any(b.backend == "pyocd" and b.probe_uid == values["probe_uid"] for b in self.boards):
                raise ValueError("This probe is already assigned to another board")
            interval = integer(values["interval"])
            if not 20 <= interval <= 10000:
                raise ValueError("Interval must be 20..10000 ms")
            board = Board(uuid.uuid4().hex[:12], values["name"], "pyocd", probe_uid=values["probe_uid"], target=values["target"], interval_ms=interval)
            self.boards.append(board)
            self._refresh_boards()
            self.board_tree.selection_set(board.id)
            self._log(f"Configured {board.name}; import its image and choose watches before starting.")
        except (ValueError, KeyError) as error:
            self._error(error)

    def remove_board(self):
        if not self._editable():
            return
        if len(self.boards) == 1:
            return self._error("Keep at least one board in the workspace")
        board = self._selected_board()
        self.boards.remove(board)
        self.images.pop(board.id, None)
        self._refresh_boards()
        self._refresh_watches()

    def import_firmware(self):
        if not self._editable():
            return
        from tkinter import filedialog, simpledialog
        path = filedialog.askopenfilename(parent=self.root, title="Inspect firmware offline", filetypes=[("Firmware", "*.elf *.out *.axf *.hex *.bin"), ("All files", "*")])
        if not path:
            return
        try:
            board = self._selected_board()
            base = None
            if Path(path).suffix.lower() == ".bin":
                value = simpledialog.askstring("BIN load address", "Base address for later Flash verification (e.g. 0x08000000).\nLeave blank for offline inspection only.", parent=self.root)
                if value:
                    base = integer(value)
            image = inspect_firmware(path, base)
            self.images[board.id] = image
            board.firmware, board.base_address = image.path, base
            board.watches = []
            self._show_firmware()
            self._refresh_watches()
            self._log(f"Offline import: {Path(path).name}. Choose watches in Firmware inspector; no probe opened.")
        except (OSError, ValueError) as error:
            self._error(error)

    def add_symbols(self):
        if not self._editable():
            return
        board = self._selected_board()
        try:
            additions = []
            for item in self.symbol_tree.selection():
                symbol = self.visible_symbols[item]
                dtype = self.watch_type.get()
                symbol = symbol if dtype == "auto" else replace(symbol, dtype=dtype)
                if all(s.name != symbol.name for s in board.watches):
                    additions.append(symbol)
            if len(board.watches) + len(additions) > 64:
                raise ValueError("At most 64 watches per board")
            board.watches.extend(additions)
            self._refresh_watches()
        except ValueError as error:
            self._error(error)

    def add_manual_watch(self):
        if not self._editable():
            return
        values = self._dialog("Add an explicit scalar watch", [("name", "Symbol name", "my_counter"), ("address", "Address", "0x20000000"),
                            ("size", "Size (bytes)", "4"), ("dtype", "Type", "u32")])
        if not values:
            return
        try:
            board = self._selected_board()
            if len(board.watches) >= 64 or any(s.name == values["name"] for s in board.watches):
                raise ValueError("Watch limit reached or name already present")
            symbol = Symbol(values["name"], integer(values["address"]), integer(values["size"]), values["dtype"])
            board.watches.append(symbol)
            self._refresh_watches()
        except ValueError as error:
            self._error(error)

    def remove_watch(self):
        if not self._editable():
            return
        selected = self.watch_tree.selection()
        for key, row in list(self.rows.items()):
            if row in selected:
                board = next(b for b in self.boards if b.id == key[0])
                board.watches = [s for s in board.watches if s.name != key[1]]
        self._refresh_watches()

    def show_probes(self):
        if self.running or (self.engine and self.engine.alive):
            return self._error("Stop sampling before USB enumeration")
        from tkinter import messagebox
        try:
            from .backends import list_probes
            probes = list_probes()
            text = "\n\n".join(f"{p['description']}\n{p['uid']}" for p in probes) or "No probes found."
            messagebox.showinfo("USB probes (no target session opened)", text, parent=self.root)
        except Exception as error:
            self._error(error)

    def start(self):
        if self.running or (self.engine and self.engine.alive) or self.closing:
            return
        try:
            if self.replay:
                self.replay.position = 0
                self.replay_start = time.monotonic()
            else:
                allow = any(b.backend == "pyocd" for b in self.boards)
                if allow:
                    from tkinter import messagebox
                    if not messagebox.askyesno("Start live observation?", "This will open the configured USB probes and attach to real hardware.\n\nThe app requests attach mode and disables auto-unlock. Target initialization can still have device-specific effects. Use an isolated test board.\n\nNo flashing, memory writes, halt, or reset commands are offered. Continue?", parent=self.root):
                        return
                self.engine = Engine(self.boards, allow_hardware=allow)
                self.dropped_seen = 0
                self.engine.start()
            self.samples.clear()
            self.last_received.clear()
            self.board_states.clear()
            self.origin = 0
            self._refresh_watches()
            self.running = True
            self.start_button.configure(state="disabled")
            self._log("Offline replay started." if self.replay else "Sampling started. Target CPUs are not paused by this button.")
        except Exception as error:
            self._error(error)

    def stop(self):
        if self.engine:
            self.engine.request_stop()
        if self.replay:
            self.running = False
            self.start_button.configure(state="normal")

    def toggle_record(self):
        if self.recorder:
            return self._finish_recording()
        if self.replay:
            return self._error("Replay is already a recording. Switch to a demo/live workspace to record.")
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(parent=self.root, title="New recording (existing files are never overwritten)", defaultextension=".jsonl", initialfile=time.strftime("session-%Y%m%d-%H%M%S.jsonl"))
        if path:
            try:
                self.recorder = Recorder(path, self.boards)
                self.record_button.configure(text="Finish recording")
                self._log(f"Recording to {Path(path).name}. Raw bytes and source provenance included.")
            except Exception as error:
                self._error(error)

    def _finish_recording(self):
        recorder, self.recorder = self.recorder, None
        if recorder:
            try:
                recorder.close()
                self._log(f"Recording flushed and closed: {recorder.path.name}")
            except OSError as error:
                self._error(f"Recording save failed; partial file preserved: {error}")
        self.record_button.configure(text="Record session")

    def _record(self, event):
        if self.recorder:
            try:
                self.recorder.write(event)
            except (OSError, ValueError) as error:
                self._finish_recording()
                self._error(f"Recording interrupted. Partial data preserved: {error}")

    def _idle_to_load(self):
        if self.running or (self.engine and self.engine.alive) or self.recorder:
            self._error("Stop sampling and finish recording before loading another session.")
            return False
        return True

    def _clear_session(self):
        self.images.clear()
        self.samples.clear()
        self.last_received.clear()
        self.board_states.clear()
        self.origin = 0
        self.engine = None
        self._refresh_boards()
        self._refresh_watches()
        self._show_firmware()

    def reset_demo(self):
        if self._idle_to_load():
            self.replay, self.boards = None, demo_boards()
            self._clear_session()

    def open_workspace(self):
        if not self._idle_to_load():
            return
        from tkinter import filedialog
        path = filedialog.askopenfilename(parent=self.root, filetypes=[("Workspace", "*.json")])
        if path:
            try:
                boards = load_workspace(path)
                self.replay, self.boards = None, boards
                self._clear_session()
                self._log("Workspace loaded offline. Press Start only when ready.")
            except Exception as error:
                self._error(error)

    def save_workspace(self):
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".workspace.json", initialfile="my.workspace.json")
        if path:
            try:
                document = workspace_document(self.boards)
                Path(path).write_text(json.dumps(document, indent=2), encoding="utf-8")
                self._log("Workspace saved locally. It may contain local paths and probe UIDs.")
            except (ValueError, OSError) as error:
                self._error(error)

    def open_replay(self):
        if not self._idle_to_load():
            return
        from tkinter import filedialog
        path = filedialog.askopenfilename(parent=self.root, filetypes=[("Session recording", "*.jsonl")])
        if path:
            try:
                replay = Replay(path)
                self.replay, self.boards = replay, replay.boards
                self._clear_session()
                self._log(f"Loaded {len(replay.events):,} offline events. Start replays from the beginning.")
            except Exception as error:
                self._error(error)

    def _event(self, event):
        if event["kind"] == "gap":
            self._log(f"Event gap: {event.get('dropped_total', '?')} total dropped. Recording is incomplete.")
            return
        board_id, kind = event["board"], event["kind"]
        if kind in ("state", "error"):
            state = "error" if kind == "error" else event["state"]
            self.board_states[board_id] = state
            self.board_tree.set(board_id, "state", state)
            self._log(f"{board_id}: {event.get('error', state)}")
            if state in ("error", "stopped", "connecting"):
                for (bid, _), row in self.rows.items():
                    if bid == board_id:
                        self.watch_tree.set(row, "value", "—")
                        self.watch_tree.set(row, "status", state)
        elif kind == "sample":
            key = (board_id, event["symbol"])
            if key not in self.rows:
                return
            value = event["value"]
            text = f"{value:.5g}" if isinstance(value, float) else str(value)
            self.watch_tree.set(self.rows[key], "value", text)
            source = "REPLAY" if self.replay else "DEMO" if event["synthetic"] else "LIVE"
            self.watch_tree.set(self.rows[key], "status", source)
            self.last_received[key] = time.monotonic()
            if not self.origin:
                self.origin = event["host_ns"]
            if isinstance(value, (int, float)):
                self.samples[key].append(((event["host_ns"] - self.origin) / 1e9, float(value)))

    def tick(self):
        try:
            if self.engine:
                events = self.engine.events.drain()
                if self.engine.events.dropped != self.dropped_seen:
                    self.dropped_seen = self.engine.events.dropped
                    gap = {"kind": "gap", "host_ns": time.monotonic_ns(), "dropped_total": self.dropped_seen}
                    self._event(gap)
                    self._record(gap)
                for event in events:
                    self._event(event)
                    self._record(event)
                if self.running and not self.engine.alive:
                    self.running = False
                    self.start_button.configure(state="normal")
            if self.replay and self.running:
                for event in self.replay.ready(time.monotonic() - self.replay_start):
                    self._event(event)
                if self.replay.finished:
                    self.running = False
                    self.start_button.configure(state="normal")
                    self._log("Replay finished. No hardware was accessed.")
            if self.running and not self.replay:
                for board in self.boards:
                    if self.board_states.get(board.id) == "watching":
                        for symbol in board.watches:
                            key = (board.id, symbol.name)
                            if key in self.last_received and time.monotonic() - self.last_received[key] > max(1.0, board.interval_ms / 250):
                                self.watch_tree.set(self.rows[key], "status", "STALE")
            count = sum(len(v) for v in self.samples.values())
            self.status.set(f"{'Replaying' if self.replay and self.running else 'Watching' if self.running else 'Idle'} · {len(self.boards)} boards · {count:,} numeric points buffered · {self.dropped_seen:,} events dropped" + (" · RECORDING" if self.recorder else ""))
            self.draw_chart()
        finally:
            if self.closing and not (self.engine and self.engine.alive):
                self._finish_recording()
                self.root.destroy()
            else:
                self.root.after(80, self.tick)

    def draw_chart(self):
        if not hasattr(self, "chart"):
            return
        canvas = self.chart
        canvas.delete("all")
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if width < 100 or height < 100:
            return
        selected = self.watch_tree.selection()
        key = next((k for k, row in self.rows.items() if selected and row == selected[0]), None)
        points = list(self.samples.get(key, []))
        if len(points) < 2:
            canvas.create_text(width / 2, height / 2, text="Start sampling and select a numeric watch.\nRaw bytes are never guessed as a numeric type.", fill=MUTED, font=("Segoe UI", 11), justify="center")
            return
        left, top, right, bottom = 72, 30, width - 22, height - 38
        xmin, xmax = points[0][0], points[-1][0]
        ymin, ymax = min(p[1] for p in points), max(p[1] for p in points)
        padding = max((ymax - ymin) * 0.12, abs(ymax) * 0.002, 0.001)
        ymin, ymax = ymin - padding, ymax + padding
        for i in range(5):
            y = top + (bottom - top) * i / 4
            canvas.create_line(left, y, right, y, fill=LINE)
            canvas.create_text(left - 10, y, text=f"{ymax - (ymax - ymin) * i / 4:.4g}", fill=MUTED, anchor="e", font=("Segoe UI", 9))
        canvas.create_text(left, 14, text=f"{key[0]} / {key[1]}", fill=INK, anchor="w", font=("Segoe UI", 10, "bold"))
        canvas.create_text(left, bottom + 18, text=f"{xmin:.2f} s", fill=MUTED, anchor="w")
        canvas.create_text(right, bottom + 18, text=f"{xmax:.2f} s", fill=MUTED, anchor="e")
        board = next(b for b in self.boards if b.id == key[0])
        path, previous = [], None
        for x, y in points:
            if previous is not None and x - previous > max(1.0, board.interval_ms / 250):
                if len(path) >= 4:
                    canvas.create_line(*path, fill=TEAL, width=2)
                path = []
            path.extend((left + (x - xmin) / max(xmax - xmin, 0.001) * (right - left),
                         bottom - (y - ymin) / (ymax - ymin) * (bottom - top)))
            previous = x
        if len(path) >= 4:
            canvas.create_line(*path, fill=TEAL, width=2)

    def close(self):
        self.closing = True
        self.stop()
        self.status.set("Closing owned connections normally. Waiting for pending reads…")


def launch(workspace: Path | None = None):
    try:
        import tkinter as tk
        root = tk.Tk()
    except Exception as error:
        raise RuntimeError("Desktop UI needs a working Python Tk installation. On Linux install your distribution's python3-tk package; on Windows repair Python's Tcl/Tk component. Headless inspect/record-demo/selftest still work. " + str(error)) from error
    try:
        boards = load_workspace(workspace) if workspace else demo_boards()
        Workbench(root, boards)
        root.mainloop()
    except BaseException:
        try:
            root.destroy()
        except tk.TclError:
            pass
        raise
    return 0
