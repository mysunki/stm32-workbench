// Independently authored Windows UI. Python owns all board connections and files.
using System;
using System.IO;
using System.Linq;
using System.Text;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Collections;
using System.Collections.Generic;
using System.Threading;
using System.Windows.Forms;
using System.Web.Script.Serialization;

namespace STM32Workbench {
    class ActionControl : Button {
        protected override void OnPaint(PaintEventArgs args) {
            using (var brush = new SolidBrush(BackColor)) args.Graphics.FillRectangle(brush, ClientRectangle);
            ControlPaint.DrawBorder(args.Graphics, ClientRectangle, Color.FromArgb(53, 76, 102), ButtonBorderStyle.Solid);
            TextRenderer.DrawText(args.Graphics, Text, Font, ClientRectangle,
                Enabled ? ForeColor : Color.FromArgb(124, 145, 170),
                TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis);
            if (Focused && Enabled) ControlPaint.DrawFocusRectangle(args.Graphics, Rectangle.Inflate(ClientRectangle, -4, -4));
        }
    }
    static class Data {
        public static Dictionary<string, object> Obj(params object[] pairs) {
            var value = new Dictionary<string, object>();
            for (int i = 0; i < pairs.Length; i += 2) value[(string)pairs[i]] = pairs[i + 1];
            return value;
        }
        public static object Get(Dictionary<string, object> item, string key) { object value; return item.TryGetValue(key, out value) ? value : null; }
        public static string S(Dictionary<string, object> item, string key) { var value = Get(item, key); return value == null ? "" : Convert.ToString(value, System.Globalization.CultureInfo.InvariantCulture); }
        public static bool B(Dictionary<string, object> item, string key) { return Get(item, key) is bool && (bool)item[key]; }
        public static double N(Dictionary<string, object> item, string key) { var value = Get(item, key); return value == null ? 0 : Convert.ToDouble(value, System.Globalization.CultureInfo.InvariantCulture); }
        public static List<Dictionary<string, object>> Rows(Dictionary<string, object> item, string key) {
            var result = new List<Dictionary<string, object>>();
            var sequence = Get(item, key) as IEnumerable;
            if (sequence != null) foreach (var value in sequence) { var row = value as Dictionary<string, object>; if (row != null) result.Add(row); }
            return result;
        }
    }

    class TracePlot : Control {
        public Dictionary<string, List<PointF>> Traces = new Dictionary<string, List<PointF>>();
        public Dictionary<string, string> Names = new Dictionary<string, string>();
        public string Selected = "";
        public bool Overlay = true;
        public int PointCount { get { return Traces.Values.Sum(points => points.Count); } }
        readonly Color[] colors = { Color.FromArgb(77, 220, 187), Color.FromArgb(102, 168, 255), Color.FromArgb(255, 184, 105), Color.FromArgb(218, 146, 248) };
        public TracePlot() { DoubleBuffered = true; BackColor = Color.FromArgb(15, 29, 46); ForeColor = Color.FromArgb(220, 230, 243); }
        public void ClearTraces() { Traces.Clear(); Names.Clear(); Invalidate(); }
        public void Add(Dictionary<string, object> item) {
            object raw = Data.Get(item, "value");
            if (raw == null || raw is string) return;
            string key = Data.S(item, "board") + "|" + Data.S(item, "symbol");
            double value = raw is bool ? ((bool)raw ? 1 : 0) : Convert.ToDouble(raw);
            if (double.IsNaN(value) || double.IsInfinity(value)) return;
            float x = (float)Data.N(item, "sample_time");
            List<PointF> points;
            if (!Traces.TryGetValue(key, out points)) { points = new List<PointF>(); Traces[key] = points; }
            if (points.Count == 0 || x > points[points.Count - 1].X) points.Add(new PointF(x, (float)value));
            if (points.Count > 1200) points.RemoveRange(0, points.Count - 1200);
            Names[key] = Data.S(item, "board_name");
        }
        protected override void OnPaint(PaintEventArgs args) {
            base.OnPaint(args);
            var g = args.Graphics; g.SmoothingMode = SmoothingMode.AntiAlias;
            if (Width < 180 || Height < 120) return;
            string symbol = Selected.Contains("|") ? Selected.Substring(Selected.IndexOf('|') + 1) : "";
            var keys = Traces.Keys.Where(key => key == Selected || (Overlay && key.EndsWith("|" + symbol))).Where(key => Traces[key].Count > 1).ToList();
            if (keys.Count == 0) {
                using (var brush = new SolidBrush(Color.FromArgb(150, 170, 193))) g.DrawString("Start watching, then select a numeric variable.\nRaw bytes are never guessed as a numeric type.", Font, brush, 25, 55);
                return;
            }
            var all = keys.SelectMany(key => Traces[key]).ToList();
            float xmin = all.Min(p => p.X), xmax = all.Max(p => p.X), ymin = all.Min(p => p.Y), ymax = all.Max(p => p.Y);
            float padding = Math.Max((ymax - ymin) * 0.12f, Math.Max(Math.Abs(ymax) * 0.002f, 0.001f));
            ymin -= padding; ymax += padding;
            var area = new RectangleF(80, 46, Width - 104, Height - 86);
            using (var text = new SolidBrush(ForeColor)) g.DrawString(symbol + "   |   PC observation time", new Font(Font, FontStyle.Bold), text, 16, 11);
            using (var pen = new Pen(Color.FromArgb(40, 60, 82))) using (var text = new SolidBrush(Color.FromArgb(151, 172, 195))) {
                for (int i = 0; i <= 4; ++i) { float y = area.Top + area.Height * i / 4; g.DrawLine(pen, area.Left, y, area.Right, y); g.DrawString((ymax - (ymax - ymin) * i / 4).ToString("G4"), Font, text, 8, y - 7); }
                g.DrawString(xmin.ToString("F2") + " s", Font, text, area.Left, area.Bottom + 10);
                g.DrawString(xmax.ToString("F2") + " s", Font, text, area.Right - 65, area.Bottom + 10);
            }
            int colorIndex = 0;
            foreach (string key in keys) {
                var color = colors[colorIndex++ % colors.Length];
                using (var pen = new Pen(color, 2f)) using (var text = new SolidBrush(color)) {
                    var points = Traces[key];
                    for (int i = 1; i < points.Count; ++i) {
                        if (points[i].X - points[i - 1].X > 1.0f) continue;
                        PointF a = new PointF(area.Left + (points[i - 1].X - xmin) / Math.Max(xmax - xmin, 0.001f) * area.Width, area.Bottom - (points[i - 1].Y - ymin) / (ymax - ymin) * area.Height);
                        PointF b = new PointF(area.Left + (points[i].X - xmin) / Math.Max(xmax - xmin, 0.001f) * area.Width, area.Bottom - (points[i].Y - ymin) / (ymax - ymin) * area.Height);
                        g.DrawLine(pen, a, b);
                    }
                    g.DrawString(Names[key], Font, text, Math.Max(360, Width - 440) + (colorIndex - 1) * 135, 11);
                }
            }
        }
    }

    class DesktopForm : Form {
        readonly Color bg = Color.FromArgb(11, 23, 38), panel = Color.FromArgb(23, 39, 59), ink = Color.FromArgb(229, 237, 247), muted = Color.FromArgb(157, 177, 198), accent = Color.FromArgb(83, 222, 190);
        readonly Dictionary<string, Button> buttons = new Dictionary<string, Button>();
        readonly JavaScriptSerializer serializer = new JavaScriptSerializer { MaxJsonLength = 8 * 1024 * 1024 };
        readonly List<string> verificationSteps = new List<string>(), verificationErrors = new List<string>(), screenshots = new List<string>();
        Dictionary<string, object> snapshot;
        List<Dictionary<string, object>> boardRows = new List<Dictionary<string, object>>();
        ListView boards;
        DataGridView watches, symbols;
        TracePlot plot;
        TabControl tabs;
        TextBox log, firmwareInfo, query;
        Label sourceLabel, summaryLabel, statusLabel;
        ComboBox type;
        CheckBox overlay;
        bool updating, allowClose;
        string selected = "", verificationDir, verificationMode;
        System.Windows.Forms.Timer verificationTimer;
        int phase, ticks;
        double recordedAt, faultAt;
        bool uiShown;

        public DesktopForm(string verifyDirectory, string verifyMode) {
            verificationDir = verifyDirectory; verificationMode = verifyMode;
            Text = "STM32 Workbench | Multi-board observation"; ClientSize = new Size(1340, 860); MinimumSize = new Size(1100, 740);
            StartPosition = FormStartPosition.CenterScreen; BackColor = bg; ForeColor = ink; Font = new Font("Segoe UI", 10f);
            Build();
            FormClosing += delegate(object sender, FormClosingEventArgs e) { if (!allowClose) { e.Cancel = true; Send("close"); statusLabel.Text = "Closing owned connections normally..."; } };
            Shown += delegate {
                uiShown = true;
                var reader = new Thread(ReadMessages) { IsBackground = true }; reader.Start();
                if (verificationDir != null) { verificationTimer = new System.Windows.Forms.Timer { Interval = 160 }; verificationTimer.Tick += VerifyTick; verificationTimer.Start(); }
            };
        }

        Button ActionButton(string key, string text, Action action, bool primary = false) {
            var button = new ActionControl { Text = text, AutoSize = true, Height = 34, MinimumSize = new Size(50, 34), FlatStyle = FlatStyle.Flat,
                BackColor = primary ? Color.FromArgb(17, 112, 100) : panel, ForeColor = ink, Margin = new Padding(0, 0, 8, 0), Padding = new Padding(8, 3, 8, 3), UseVisualStyleBackColor = false };
            button.FlatAppearance.BorderColor = Color.FromArgb(51, 74, 98); button.Click += delegate { action(); }; buttons[key] = button; return button;
        }
        DataGridView Grid(string[] columns) {
            var grid = new DataGridView { Dock = DockStyle.Fill, ReadOnly = true, AllowUserToAddRows = false, AllowUserToDeleteRows = false, RowHeadersVisible = false,
                SelectionMode = DataGridViewSelectionMode.FullRowSelect, MultiSelect = false, BackgroundColor = panel, BorderStyle = BorderStyle.None,
                AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill, EnableHeadersVisualStyles = false, ColumnHeadersHeight = 34, RowTemplate = { Height = 28 } };
            grid.DefaultCellStyle = new DataGridViewCellStyle { BackColor = panel, ForeColor = ink, SelectionBackColor = Color.FromArgb(37, 85, 101), SelectionForeColor = Color.White, Padding = new Padding(5, 2, 5, 2) };
            grid.ColumnHeadersDefaultCellStyle = new DataGridViewCellStyle { BackColor = Color.FromArgb(31, 51, 74), ForeColor = muted, Padding = new Padding(5) };
            grid.GridColor = Color.FromArgb(38, 57, 78);
            foreach (string name in columns) grid.Columns.Add(name, name);
            return grid;
        }
        void Build() {
            var layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 5, Padding = new Padding(22, 16, 22, 12), BackColor = bg };
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 64)); layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 46)); layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 36)); layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100)); layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 28)); Controls.Add(layout);
            var header = new Panel { Dock = DockStyle.Fill };
            header.Controls.Add(new Label { Text = "STM32 WORKBENCH", Font = new Font("Segoe UI", 23, FontStyle.Bold), ForeColor = ink, AutoSize = true, Location = new Point(0, 0) });
            header.Controls.Add(new Label { Text = "Many boards. One workspace.   Firmware inspection / variable watch / session replay", ForeColor = muted, AutoSize = true, Location = new Point(2, 42) });
            sourceLabel = new Label { Text = "DEMO / SYNTHETIC", Font = new Font("Segoe UI", 10, FontStyle.Bold), ForeColor = accent, AutoSize = false, TextAlign = ContentAlignment.MiddleRight, Dock = DockStyle.Right, Width = 335 }; header.Controls.Add(sourceLabel); layout.Controls.Add(header, 0, 0);
            var actions = new FlowLayoutPanel { Dock = DockStyle.Fill, WrapContents = false };
            actions.Controls.Add(ActionButton("start", "Start watching", StartWatching, true));
            actions.Controls.Add(ActionButton("stop", "Stop sampling", delegate { Send("stop"); }));
            actions.Controls.Add(ActionButton("record", "Record session", ToggleRecording));
            actions.Controls.Add(ActionButton("open_replay", "Open recording", delegate { string path = PickFile("open_replay"); if (path != null) Send("open_replay", "path", path); }));
            actions.Controls.Add(ActionButton("save", "Save workspace", delegate { string path = PickFile("save"); if (path != null) Send("save_workspace", "path", path); }));
            actions.Controls.Add(ActionButton("load", "Load workspace", delegate { string path = PickFile("load"); if (path != null) Send("load_workspace", "path", path); })); layout.Controls.Add(actions, 0, 1);
            summaryLabel = new Label { Dock = DockStyle.Fill, Text = "3 demo boards | 12 scalar signals | No probe opened", ForeColor = muted, TextAlign = ContentAlignment.MiddleLeft }; layout.Controls.Add(summaryLabel, 0, 2);
            var split = new SplitContainer { Dock = DockStyle.Fill, FixedPanel = FixedPanel.Panel1, SplitterWidth = 16, BackColor = bg };
            split.Size = new Size(1296, 650); split.SplitterDistance = 252; split.Panel1MinSize = 225; split.Panel2MinSize = 650; layout.Controls.Add(split, 0, 3);
            var side = new TableLayoutPanel { Dock = DockStyle.Fill, RowCount = 10, ColumnCount = 1 };
            side.RowStyles.Add(new RowStyle(SizeType.Absolute, 30)); side.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            for (int i = 0; i < 7; i++) side.RowStyles.Add(new RowStyle(SizeType.Absolute, 42));
            side.RowStyles.Add(new RowStyle(SizeType.Absolute, 48)); split.Panel1.Controls.Add(side);
            side.Controls.Add(new Label { Text = "BOARDS", ForeColor = accent, Font = new Font(Font, FontStyle.Bold), Dock = DockStyle.Fill }, 0, 0);
            boards = new ListView { Dock = DockStyle.Fill, View = View.Details, FullRowSelect = true, HideSelection = false, MultiSelect = false, BackColor = panel, ForeColor = ink, BorderStyle = BorderStyle.None, HeaderStyle = ColumnHeaderStyle.Nonclickable };
            boards.Columns.Add("Board", 116); boards.Columns.Add("State", 95); boards.SelectedIndexChanged += BoardSelected; side.Controls.Add(boards, 0, 1);
            var sideButtons = new[] {
                ActionButton("add_demo", "Add demo board", delegate { Send("add_demo"); }),
                ActionButton("add_live", "Configure live board", AddLive),
                ActionButton("remove_board", "Remove selected board", delegate { Send("remove_board"); }),
                ActionButton("import", "Import firmware", ImportFirmware),
                ActionButton("fault", "Inject DEMO link fault", delegate { Send("demo_fault"); }),
                ActionButton("probes", "List USB probes", delegate { Send("probes"); }),
                ActionButton("reset", "Reset to three-board demo", delegate { Send("reset_demo"); }) };
            for (int i = 0; i < sideButtons.Length; i++) { sideButtons[i].Dock = DockStyle.Fill; sideButtons[i].Margin = new Padding(0, 5, 0, 2); side.Controls.Add(sideButtons[i], 0, i + 2); }
            side.Controls.Add(new Label { Text = "Import is offline. Start is explicit.\nDEMO is a signal source, not MCU emulation.", ForeColor = muted, Dock = DockStyle.Fill, Font = new Font("Segoe UI", 8.5f), Padding = new Padding(0, 7, 0, 0) }, 0, 9);
            tabs = new TabControl { Dock = DockStyle.Fill, Font = Font }; split.Panel2.Controls.Add(tabs);
            var watchTab = new TabPage("Variable watch") { BackColor = bg, Padding = new Padding(12) };
            var imageTab = new TabPage("Firmware inspector") { BackColor = bg, Padding = new Padding(12) };
            var logTab = new TabPage("Session log") { BackColor = bg, Padding = new Padding(12) }; tabs.TabPages.AddRange(new[] { watchTab, imageTab, logTab });
            var watchLayout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 4 };
            watchLayout.RowStyles.Add(new RowStyle(SizeType.Percent, 70)); watchLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 42)); watchLayout.RowStyles.Add(new RowStyle(SizeType.Percent, 30)); watchLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 24)); watchTab.Controls.Add(watchLayout);
            watches = Grid(new[] { "Board", "Variable", "Address", "Type", "Value", "Source / state" });
            watches.Columns[1].FillWeight = 145; watches.Columns[3].FillWeight = 45; watches.SelectionChanged += delegate { if (!updating) SelectPlot(); }; watchLayout.Controls.Add(watches, 0, 0);
            var watchActions = new FlowLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(0, 5, 0, 0), WrapContents = false };
            watchActions.Controls.Add(ActionButton("add_watch", "Add explicit watch", AddWatch));
            watchActions.Controls.Add(ActionButton("remove_watch", "Remove selected watch", RemoveWatch));
            overlay = new CheckBox { Text = "Overlay same variable", Checked = true, ForeColor = muted, AutoSize = true, Padding = new Padding(6, 7, 0, 0) };
            overlay.CheckedChanged += delegate { plot.Overlay = overlay.Checked; plot.Invalidate(); }; watchActions.Controls.Add(overlay); watchLayout.Controls.Add(watchActions, 0, 1);
            plot = new TracePlot { Dock = DockStyle.Fill, Font = new Font("Segoe UI", 9) }; watchLayout.Controls.Add(plot, 0, 2);
            watchLayout.Controls.Add(new Label { Text = "PC timestamps | sequential reads | no cross-board synchronization | 1,200 points per trace", ForeColor = muted, Dock = DockStyle.Fill, Font = new Font("Segoe UI", 8.5f), TextAlign = ContentAlignment.MiddleLeft }, 0, 3);
            var imageLayout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 4 };
            imageLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 112)); imageLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 38)); imageLayout.RowStyles.Add(new RowStyle(SizeType.Percent, 100)); imageLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 45)); imageTab.Controls.Add(imageLayout);
            firmwareInfo = new TextBox { Dock = DockStyle.Fill, Multiline = true, ReadOnly = true, BorderStyle = BorderStyle.None, BackColor = bg, ForeColor = muted, Font = new Font("Segoe UI", 9.5f) }; imageLayout.Controls.Add(firmwareInfo, 0, 0);
            var filterBar = new FlowLayoutPanel { Dock = DockStyle.Fill, WrapContents = false }; filterBar.Controls.Add(new Label { Text = "Find symbol", ForeColor = muted, AutoSize = true, Padding = new Padding(0, 6, 10, 0) });
            query = new TextBox { Width = 350, BackColor = panel, ForeColor = ink }; query.TextChanged += delegate { if (!updating) Send("filter_symbols", "query", query.Text); }; filterBar.Controls.Add(query); imageLayout.Controls.Add(filterBar, 0, 1);
            symbols = Grid(new[] { "Symbol", "Address", "Bytes", "Inferred type" }); symbols.MultiSelect = true; symbols.Columns[0].FillWeight = 180; imageLayout.Controls.Add(symbols, 0, 2);
            var symbolActions = new FlowLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(0, 7, 0, 0), WrapContents = false };
            symbolActions.Controls.Add(new Label { Text = "Interpret as", AutoSize = true, ForeColor = muted, Padding = new Padding(0, 6, 8, 0) });
            type = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList, Width = 90 }; type.Items.AddRange(new object[] { "auto", "raw", "u8", "i8", "u16", "i16", "u32", "i32", "u64", "i64", "f32", "f64", "bool" }); type.SelectedIndex = 0; symbolActions.Controls.Add(type);
            symbolActions.Controls.Add(ActionButton("add_symbols", "Watch selected symbols", AddSymbols)); imageLayout.Controls.Add(symbolActions, 0, 3);
            log = new TextBox { Dock = DockStyle.Fill, Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Vertical, BackColor = panel, ForeColor = ink, BorderStyle = BorderStyle.None, Font = new Font("Consolas", 10f) }; logTab.Controls.Add(log);
            statusLabel = new Label { Dock = DockStyle.Fill, Text = "Ready | no hardware connection", ForeColor = muted, TextAlign = ContentAlignment.BottomLeft }; layout.Controls.Add(statusLabel, 0, 4);
        }

        void Send(string operation, params object[] pairs) {
            var message = Data.Obj(pairs); message["op"] = operation;
            Console.Out.WriteLine(serializer.Serialize(message)); Console.Out.Flush();
        }
        void ReadMessages() {
            try {
                string line; var parser = new JavaScriptSerializer { MaxJsonLength = 8 * 1024 * 1024 };
                while ((line = Console.In.ReadLine()) != null) {
                    var message = parser.DeserializeObject(line) as Dictionary<string, object>;
                    if (message != null && !IsDisposed) BeginInvoke(new Action(delegate { Receive(message); }));
                }
                if (!IsDisposed) BeginInvoke(new Action(delegate { allowClose = true; Close(); }));
            } catch (Exception error) { Console.Error.WriteLine(error); if (!IsDisposed) try { BeginInvoke(new Action(delegate { allowClose = true; Close(); })); } catch { } }
        }
        void Receive(Dictionary<string, object> message) {
            string kind = Data.S(message, "kind");
            if (kind == "close") { allowClose = true; Close(); return; }
            if (kind == "log") { AppendLog(Data.S(message, "text")); return; }
            if (kind == "error") {
                string text = Data.S(message, "text"); AppendLog("ERROR: " + text);
                if (verificationDir != null) { verificationErrors.Add(text); FinishVerification(false); }
                else MessageBox.Show(this, text, "STM32 Workbench", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
            if (kind == "probes") { var rows = Data.Rows(message, "probes"); MessageBox.Show(this, rows.Count == 0 ? "No USB probes found" : String.Join("\n\n", rows.Select(p => Data.S(p, "description") + "\n" + Data.S(p, "uid"))), "USB probes; no target session opened"); return; }
            if (kind == "reset_chart") { plot.ClearTraces(); return; }
            if (kind == "firmware") {
                firmwareInfo.Text = Data.S(message, "title").Replace("\n", Environment.NewLine); symbols.Rows.Clear();
                foreach (var item in Data.Rows(message, "symbols")) { int row = symbols.Rows.Add(Data.S(item, "name"), Data.S(item, "address"), Data.S(item, "size"), Data.S(item, "dtype")); symbols.Rows[row].Tag = item; }
                return;
            }
            if (kind != "snapshot") return;
            snapshot = message; updating = true;
            try {
                boardRows = Data.Rows(message, "boards"); selected = Data.S(message, "selected"); boards.BeginUpdate(); boards.Items.Clear();
                foreach (var item in boardRows) { var row = new ListViewItem(Data.S(item, "name")); row.SubItems.Add(Data.S(item, "state")); row.Tag = Data.S(item, "id"); row.ForeColor = Data.S(item, "state") == "error" ? Color.Salmon : ink; boards.Items.Add(row); if ((string)row.Tag == selected) row.Selected = true; }
                boards.EndUpdate();
                var watchRows = Data.Rows(message, "watches"); string selectedWatch = watches.CurrentRow == null ? "" : Convert.ToString(watches.CurrentRow.Tag);
                bool rebuild = watches.Rows.Count != watchRows.Count || watches.Rows.Cast<DataGridViewRow>().Select(row => Convert.ToString(row.Tag)).SequenceEqual(watchRows.Select(row => Data.S(row, "board") + "|" + Data.S(row, "symbol"))) == false;
                if (rebuild) watches.Rows.Clear();
                for (int i = 0; i < watchRows.Count; ++i) {
                    var item = watchRows[i]; string key = Data.S(item, "board") + "|" + Data.S(item, "symbol"); object value = Data.Get(item, "value");
                    string display = value == null ? "—" : value is double || value is decimal || value is float ? Convert.ToDouble(value).ToString("G6") : Convert.ToString(value);
                    object[] cells = { Data.S(item, "board_name"), Data.S(item, "symbol"), Data.S(item, "address"), Data.S(item, "dtype"), display, Data.S(item, "status") };
                    if (rebuild) watches.Rows.Add(cells); else for (int j = 0; j < cells.Length; ++j) watches.Rows[i].Cells[j].Value = cells[j];
                    watches.Rows[i].Tag = key;
                    watches.Rows[i].DefaultCellStyle.ForeColor = Data.S(item, "status") == "error" ? Color.Salmon : ink;
                    if (rebuild && key == selectedWatch) watches.CurrentCell = watches.Rows[i].Cells[0];
                    plot.Add(item);
                }
                bool running = Data.B(message, "running"), busy = Data.B(message, "busy"), replay = Data.B(message, "replay");
                bool recording = Data.S(message, "recording") != "", editable = !running && !busy && !recording && !replay;
                sourceLabel.Text = Data.S(message, "source"); summaryLabel.Text = String.Format("{0} boards  |  {1} watched scalars  |  {2:N0} samples received  |  {3:N0} events dropped", boardRows.Count, watchRows.Count, Data.N(message, "total_samples"), Data.N(message, "dropped"));
                buttons["start"].Enabled = !running && !busy; buttons["start"].Text = replay ? "Start replay" : "Start watching";
                buttons["record"].Enabled = !replay; buttons["record"].Text = recording ? "Finish recording" : "Record session";
                foreach (string key in new[] { "add_demo", "add_live", "remove_board", "import", "add_watch", "remove_watch", "add_symbols" }) buttons[key].Enabled = editable;
                foreach (string key in new[] { "load", "open_replay", "reset", "probes" }) buttons[key].Enabled = !running && !busy && !recording;
                buttons["fault"].Enabled = running && !replay && boardRows.Any(row => Data.S(row, "id") == selected && Data.S(row, "backend") == "demo");
                statusLabel.Text = (running ? replay ? "Replaying" : "Watching" : "Idle") + " | " + (recording ? "RECORDING " + Data.S(message, "recording") : "PC timestamps; source data preserved") + " | target CPUs are not paused by Stop sampling";
            } finally { updating = false; }
            SelectPlot();
        }
        void SelectPlot() { if (watches.CurrentRow != null) plot.Selected = Convert.ToString(watches.CurrentRow.Tag); plot.Invalidate(); }
        void AppendLog(string text) { if (log.TextLength > 100000) log.Text = log.Text.Substring(50000); log.AppendText(DateTime.Now.ToString("HH:mm:ss") + "  " + text + Environment.NewLine); }
        void BoardSelected(object sender, EventArgs e) { if (!updating && boards.SelectedItems.Count == 1) { selected = (string)boards.SelectedItems[0].Tag; Send("select", "board", selected); } }
        string PickFile(string action) {
            if (verificationDir != null) {
                if (action == "record" || action == "open_replay") return Path.Combine(verificationDir, "ui-session.jsonl");
                if (action == "save" || action == "load") return Path.Combine(verificationDir, "ui.workspace.json");
                if (action == "import") return Path.Combine(verificationDir, "synthetic-symbols.elf");
            }
            if (action == "record" || action == "save") {
                using (var dialog = new SaveFileDialog { Title = action == "record" ? "New recording; existing files are not overwritten" : "Save workspace", Filter = action == "record" ? "Session recording|*.jsonl" : "Workspace|*.workspace.json", FileName = action == "record" ? "session-" + DateTime.Now.ToString("yyyyMMdd-HHmmss") + ".jsonl" : "my.workspace.json" }) return dialog.ShowDialog(this) == DialogResult.OK ? dialog.FileName : null;
            }
            using (var dialog = new OpenFileDialog { Title = action == "import" ? "Inspect firmware offline" : "Open saved file", Filter = action == "import" ? "Firmware|*.elf;*.out;*.axf;*.hex;*.bin|All files|*.*" : action == "open_replay" ? "Session recording|*.jsonl" : "Workspace|*.json" }) return dialog.ShowDialog(this) == DialogResult.OK ? dialog.FileName : null;
        }
        Dictionary<string, string> Ask(string title, string[] labels, string[] defaults) {
            using (var dialog = new Form { Text = title, StartPosition = FormStartPosition.CenterParent, FormBorderStyle = FormBorderStyle.FixedDialog, MaximizeBox = false, MinimizeBox = false, ClientSize = new Size(540, labels.Length * 43 + 70), BackColor = bg, ForeColor = ink, Font = Font }) {
                var fields = new Dictionary<string, TextBox>();
                for (int i = 0; i < labels.Length; ++i) { dialog.Controls.Add(new Label { Text = labels[i], Location = new Point(18, 18 + i * 43), Size = new Size(185, 30) }); var input = new TextBox { Text = defaults[i], Location = new Point(205, 15 + i * 43), Width = 310, BackColor = panel, ForeColor = ink }; fields[labels[i]] = input; dialog.Controls.Add(input); }
                var ok = new Button { Text = "Confirm", DialogResult = DialogResult.OK, Location = new Point(405, labels.Length * 43 + 18), Width = 110 }; dialog.Controls.Add(ok); dialog.AcceptButton = ok;
                if (dialog.ShowDialog(this) != DialogResult.OK) return null;
                return fields.ToDictionary(pair => pair.Key, pair => pair.Value.Text.Trim());
            }
        }
        void StartWatching() {
            bool live = snapshot != null && !Data.B(snapshot, "replay") && boardRows.Any(row => Data.S(row, "backend") == "pyocd");
            if (live && MessageBox.Show(this, "Open the configured physical probes and attach to the boards?\n\nAttach mode and no automatic unlock are requested. Target initialization can still affect hardware. Use an isolated test setup.\n\nNo flash, halt, reset or arbitrary write commands are offered.", "Confirm physical connection", MessageBoxButtons.YesNo, MessageBoxIcon.Warning) != DialogResult.Yes) return;
            Send("start", "allow_hardware", live);
        }
        void ToggleRecording() { if (snapshot != null && Data.S(snapshot, "recording") != "") Send("record"); else { string path = PickFile("record"); if (path != null) Send("record", "path", path); } }
        void ImportFirmware() {
            string path = PickFile("import"); if (path == null) return; string address = null;
            if (Path.GetExtension(path).Equals(".bin", StringComparison.OrdinalIgnoreCase)) { var answer = Ask("Binary load address; blank for offline inspection", new[] { "Base address" }, new[] { "0x08000000" }); if (answer == null) return; address = answer["Base address"]; }
            Send("import", "board", selected, "path", path, "base", address); tabs.SelectedIndex = 1;
        }
        void AddSymbols() {
            var names = symbols.SelectedRows.Cast<DataGridViewRow>().Select(row => Convert.ToString(row.Cells[0].Value)).ToArray();
            Send("add_symbols", "symbols", names, "dtype", Convert.ToString(type.SelectedItem));
        }
        void AddWatch() {
            var answer = Ask("Add an explicitly typed scalar", new[] { "Name", "Address", "Bytes", "Type" }, new[] { "my_counter", "0x20000000", "4", "u32" });
            if (answer != null) Send("add_watch", "symbol", Data.Obj("name", answer["Name"], "address", answer["Address"], "size", answer["Bytes"], "dtype", answer["Type"]));
        }
        void RemoveWatch() {
            if (watches.CurrentRow == null) return; string key = Convert.ToString(watches.CurrentRow.Tag); int split = key.IndexOf('|');
            Send("remove_watch", "board", key.Substring(0, split), "symbol", key.Substring(split + 1));
        }
        void AddLive() {
            var answer = Ask("Configure live board offline; does not connect", new[] { "Board name", "Exact probe UID", "pyOCD target", "Firmware path", "BIN base (optional)" }, new[] { "My STM32", "", "", "", "" });
            if (answer != null) Send("add_live", "board_config", Data.Obj("name", answer["Board name"], "probe_uid", answer["Exact probe UID"], "target", answer["pyOCD target"], "firmware", answer["Firmware path"], "base_address", answer["BIN base (optional)"] == "" ? null : answer["BIN base (optional)"]));
        }
        void Capture(string filename) {
            string path = Path.Combine(verificationDir, filename); Refresh();
            using (var bitmap = new Bitmap(Width, Height)) { DrawToBitmap(bitmap, new Rectangle(0, 0, Width, Height)); bitmap.Save(path, System.Drawing.Imaging.ImageFormat.Png); }
            screenshots.Add(filename);
        }
        void Check(bool condition, string text) { if (!condition) throw new InvalidOperationException(text); verificationSteps.Add(text); }
        void VerifyTick(object sender, EventArgs args) {
            if (++ticks > 220) { verificationErrors.Add("Interaction verification timed out at phase " + phase); FinishVerification(false); return; }
            if (snapshot == null) return;
            try {
                if (verificationMode == "restart") { VerifyRestart(); return; }
                switch (phase) {
                    case 0:
                        Check(uiShown && Visible && IsHandleCreated, "Real Windows form shown"); Check(boardRows.Count == 3 && watches.Rows.Count == 12, "Three demo boards and twelve watches displayed"); buttons["start"].PerformClick(); phase++; break;
                    case 1:
                        if (!Data.B(snapshot, "running") || Data.N(snapshot, "total_samples") < 240) return;
                        Check(plot.PointCount > 0, "Real engine samples reached numeric chart"); Capture("01-demo-watch.png"); recordedAt = Data.N(snapshot, "total_samples"); buttons["record"].PerformClick(); phase++; break;
                    case 2:
                        if (Data.S(snapshot, "recording") == "" || Data.N(snapshot, "total_samples") < recordedAt + 40) return;
                        faultAt = Data.N(snapshot, "total_samples"); buttons["fault"].PerformClick(); phase++; break;
                    case 3:
                        if (!boardRows.Any(row => Data.S(row, "state") == "error") || Data.N(snapshot, "total_samples") < faultAt + 24) return;
                        Check(boardRows.Count(row => Data.S(row, "state") == "watching") == 2, "Injected demo fault isolated while other two boards continued"); Capture("02-demo-fault-isolation.png"); buttons["stop"].PerformClick(); phase++; break;
                    case 4:
                        if (Data.B(snapshot, "running") || Data.B(snapshot, "busy")) return;
                        buttons["record"].PerformClick(); phase++; break;
                    case 5:
                        if (Data.S(snapshot, "recording") != "") return;
                        Check(File.Exists(Path.Combine(verificationDir, "ui-session.jsonl")), "Recording written by actual recorder"); buttons["import"].PerformClick(); phase++; break;
                    case 6:
                        if (symbols.Rows.Count != 4) return;
                        Check(watches.Rows.Count == 8, "Firmware import replaced only selected board watches"); Capture("03-firmware-inspector.png"); symbols.ClearSelection();
                        foreach (DataGridViewRow row in symbols.Rows) if (Convert.ToString(row.Cells[0].Value) == "temperature_c") { row.Selected = true; symbols.CurrentCell = row.Cells[0]; }
                        type.SelectedItem = "f32"; buttons["add_symbols"].PerformClick(); phase++; break;
                    case 7:
                        if (watches.Rows.Count != 9) return; Check(watches.Rows.Cast<DataGridViewRow>().Any(row => Convert.ToString(row.Cells[3].Value) == "f32"), "Imported scalar added with explicit float type"); buttons["save"].PerformClick(); phase++; break;
                    case 8:
                        if (!File.Exists(Path.Combine(verificationDir, "ui.workspace.json"))) return; buttons["add_demo"].PerformClick(); phase++; break;
                    case 9:
                        if (boardRows.Count != 4) return; Check(true, "Fourth demo board added using the actual UI command"); buttons["remove_board"].PerformClick(); phase++; break;
                    case 10:
                        if (boardRows.Count != 3) return; buttons["load"].PerformClick(); phase++; break;
                    case 11:
                        if (boardRows.Count != 3 || watches.Rows.Count != 9) return; Check(true, "Saved workspace loaded with original board and typed watch definitions"); buttons["open_replay"].PerformClick(); phase++; break;
                    case 12:
                        if (!Data.B(snapshot, "replay") || watches.Rows.Count != 12) return; buttons["start"].PerformClick(); phase++; break;
                    case 13:
                        if (!Data.B(snapshot, "replay_finished") || Data.B(snapshot, "running")) return;
                        Check(Data.N(snapshot, "total_samples") > 20 && plot.PointCount > 0, "Recorded samples replayed through the same table and chart"); tabs.SelectedIndex = 0; Capture("04-offline-replay.png"); FinishVerification(true); break;
                }
            } catch (Exception error) { verificationErrors.Add(error.ToString()); FinishVerification(false); }
        }
        void VerifyRestart() {
            if (phase == 0) { Check(boardRows.Count == 3 && watches.Rows.Count == 9, "Fresh process restored three boards and nine saved watches"); buttons["start"].PerformClick(); phase = 1; }
            else if (phase == 1 && Data.N(snapshot, "total_samples") >= 30) { Check(plot.PointCount > 0 && sourceLabel.Text == "DEMO / SYNTHETIC", "Restored workspace collected new synthetic values in a fresh process"); Capture("05-workspace-restart.png"); buttons["stop"].PerformClick(); phase = 2; }
            else if (phase == 2 && !Data.B(snapshot, "running") && !Data.B(snapshot, "busy")) FinishVerification(true);
        }
        void FinishVerification(bool passed) {
            if (verificationTimer != null) verificationTimer.Stop();
            Send("verification_result", "result", Data.Obj("passed", passed, "mode", verificationMode, "steps", verificationSteps.ToArray(), "errors", verificationErrors.ToArray(),
                "screenshots", screenshots.ToArray(), "form_shown", uiShown && Visible, "chart_points", plot.PointCount, "samples_displayed", snapshot == null ? 0 : Data.N(snapshot, "total_samples"),
                "interaction_method", "PerformClick on actual UI controls; only file dialog paths are supplied by the verifier", "physical_hardware_opened", false));
        }
    }

    static class Program {
        [STAThread] static int Main(string[] args) {
            try {
                // A GUI process has redirected pipes but no console input buffer.
                // Set explicit UTF-8 readers/writers without changing console modes.
                Console.SetIn(new StreamReader(Console.OpenStandardInput(), new UTF8Encoding(false)));
                Console.SetOut(new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false)) { AutoFlush = true });
                Console.SetError(new StreamWriter(Console.OpenStandardError(), new UTF8Encoding(false)) { AutoFlush = true });
                string directory = null, mode = "full";
                for (int i = 0; i < args.Length - 1; ++i) { if (args[i] == "--verify") directory = args[i + 1]; if (args[i] == "--verify-mode") mode = args[i + 1]; }
                Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false); Application.Run(new DesktopForm(directory, mode)); return 0;
            } catch (Exception error) { Console.Error.WriteLine(error.ToString()); return 1; }
        }
    }
}
