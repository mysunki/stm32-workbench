"""Run from a checkout, including with Python's isolated-mode switch."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

if __name__ == "__main__":
    from stm32_workbench.cli import main
    raise SystemExit(main())
