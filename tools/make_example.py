"""Generate a public synthetic ELF inspection fixture, never a board firmware."""
from pathlib import Path
import argparse
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from stm32_workbench.examples import write_synthetic_elf

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        write_synthetic_elf(args.output)
        print("Created a SYNTHETIC symbol-inspection fixture. Do not program it to a board.")
    except OSError as error:
        parser.exit(1, str(error) + "\n")
