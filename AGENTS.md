# STM32 Workbench

This is a new, independent public-source project. Do not copy code, firmware,
measurements, product names, authentication material, or configuration from sibling
directories. Synthetic test fixtures and generic example data are the only samples.

Use Python 3.11+ and the standard library for the default demo, parsers, CLI, and
the Tkinter UI on non-Windows systems. Windows defaults to the included C# WinForms
host, compiled locally with .NET Framework; its controller/engine remain Python.
Optional hardware support uses pyOCD; optional DWARF decoding uses
pyelftools. Keep these imports lazy so the demo works without USB drivers.

Run `python -I -B run.py selftest` after changes. Never connect to hardware while
testing this project. Hardware operations must be explicitly requested by the user.
Keep demo/replay/live visibly distinct; do not call synthetic signal generation an
STM32 instruction emulator. Firmware import must not connect, flash, reset, or halt.

Before publication, run `python -I -B tools/verify_from_scratch.py --output local/<new-run-name>`
on Windows. Unit tests alone are insufficient: the actual UI, import, recording,
replay, and fresh-process restore must pass. Keep evidence and distinguish a local
source snapshot from an actual GitHub clone/download. Do not call a mocked publish
test or fake-memory probe check an actual remote write or physical hardware test.

Keep publishable source inside this directory. The parent project and its portfolio
are local-only and must never be included in the publication archive. Do not add
external licenses to copied company work: write new generic implementation instead.
