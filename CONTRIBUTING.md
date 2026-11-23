# Contributing

Start with `python -I -B run.py selftest`. Keep the default experience usable
without pip packages, USB drivers, a network connection, or target hardware.

Firmware import must stay offline. Do not add target programming, mass erase,
automatic reset/halt, or silent selection of the first probe. New target operations
need an explicit product design and separate controls.

Use independently authored code and synthetic fixtures. Do not submit employer or
customer firmware, private measurements, credentials, serial numbers, or vendor
SDK/driver binaries. Describe a hardware issue with a minimal public example and
the target/probe/software versions; mark physical tests separately from fake-memory
tests. Do not claim all STM32 devices are supported because one board was tested.

For changes, explain the observed problem, resulting behavior, verification, and
remaining limits. Add regression tests for parsers, data integrity, concurrency,
or connection behavior when those change.

Before publication on Windows, run
`python -I -B tools/verify_from_scratch.py --output local/my-new-verification`.
This exercises actual native controls and Python operations from a fresh source
copy and empty venv. Keep screenshots and distinguish synthetic from physical data.
`tools/ui_smoke.py` is a legacy Tk-only smoke check; it does not validate the default
Windows native frontend. Linux/macOS visual validation remains outstanding.
