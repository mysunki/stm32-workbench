# STM32 Workbench

This is a new, independent public-source project. Do not copy code, firmware,
measurements, product names, authentication material, or configuration from sibling
directories. Synthetic test fixtures and generic example data are the only samples.

Use Python 3.11+ and the standard library for the default demo, parsers, CLI, and
Tkinter UI. Optional hardware support uses pyOCD; optional DWARF decoding uses
pyelftools. Keep these imports lazy so the demo works without USB drivers.

Run `python -I -B run.py selftest` after changes. Never connect to hardware while
testing this project. Hardware operations must be explicitly requested by the user.
Keep demo/replay/live visibly distinct; do not call synthetic signal generation an
STM32 instruction emulator. Firmware import must not connect, flash, reset, or halt.

Keep publishable source inside this directory. The parent project and its portfolio
are local-only and must never be included in the publication archive. Do not add
external licenses to copied company work: write new generic implementation instead.
