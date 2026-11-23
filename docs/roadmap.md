# Roadmap

## Present in 0.1.0

- Independent generic source, desktop UI, headless demo, and offline firmware inspection.
- Per-board observation workers, optional pyOCD adapter, and explicit scalar types.
- Versioned recordings and offline replay with synthetic/live provenance.
- Automated core tests, source packaging, and a GitHub publication helper.
- Native Windows frontend without Tk, cross-board variable overlays, and a tested
  fresh-source/empty-environment desktop acceptance workflow with screenshots.

## Next: validate the foundation

- Validate the original Tk UI on Linux/macOS; broaden Windows scaling and keyboard testing.
- Test one public STM32 development board with a documented ST-Link setup.
- Confirm attach/disconnect behavior and error recovery for that exact target.
- Add real-board results and reproducible public demo firmware.
- Verify optional DWARF paths with GCC and IAR-produced ELF/OUT samples.
- Build a manual QA checklist for recording save failures, disconnects, and large inputs.

## Later, after measured demand

- Selected-series CSV export; extend overlays to the original Tk frontend.
- Source/line view and structured variable browsing.
- GDB-server adapters with explicit ownership semantics.
- Target-specific J-Link integration if pyOCD support is insufficient.
- Multi-device synchronized acquisition where hardware supports it.
- Installable desktop releases and signed distribution.
- A separately scoped instruction/peripheral emulator adapter.

These are planned items, not available features or completed validation.
