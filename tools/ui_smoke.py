"""Exercise the real desktop widgets with synthetic data only. Needs working Tk."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import tkinter as tk
from stm32_workbench.models import demo_boards
from stm32_workbench.ui import Workbench


def main():
    root = tk.Tk()
    root.withdraw()
    app = Workbench(root, demo_boards())
    errors = []
    root.report_callback_exception = lambda kind, value, trace: (errors.append(str(value)), app.close())
    app.start()
    def check():
        try:
            assert len(app.board_tree.get_children()) == 3
            assert len(app.watch_tree.get_children()) == 12
            assert len(app.samples) == 12
            assert all(app.watch_tree.set(row, "status") == "DEMO" for row in app.rows.values())
        except Exception as error:
            errors.append(str(error))
        finally:
            app.close()
    root.after(1000, check)
    root.mainloop()
    if errors:
        raise RuntimeError("UI smoke failed: " + "; ".join(errors))
    print("Desktop smoke passed: 3 synthetic boards, 12 watched signals; no hardware opened")


if __name__ == "__main__":
    main()
