# Optional hardware setup

No hardware was connected during this project's initial automated verification.
The pyOCD adapter is implemented and fake-session tested; physical compatibility is
not yet established. A probe/backend feature should not be advertised as physically
validated until a reproducible test is recorded here.

## Requirements

- A board whose MCU has a working pyOCD target definition.
- One uniquely identified debug probe per board, supported by your pyOCD installation.
- Locally configured OS drivers/permissions and any target packs your device requires.
- The image currently programmed on the board; preferably a linked ELF/OUT with symbols.
- A separate, appropriately configured test setup that is safe to attach to.

Install optional dependencies in your own virtual environment:

```console
python -m pip install -e ".[all]"
pyocd list --targets
python -I -B run.py probes
python -I -B run.py probes --type stlink
python -I -B run.py probes --type jlink
```

The app does not install drivers or target packs automatically. `probes` explicitly
enumerates attached debug probes; it does not create target sessions. The full UID
must be assigned to exactly one live board. Substring matches and first-device
fallbacks are not used.

Use **Configure live board**, choose its debugger type, SWD/JTAG and requested clock,
then supply the full UID, MCU target and image path. **Scan USB** enumerates only the
chosen driver. **Edit selected connection** changes an existing board after stopping
sampling and recording. No target session opens while saving configuration.

| Selection | pyOCD driver | Additional setup |
| --- | --- | --- |
| Auto | All available drivers, exact UID required | Ambiguous matching IDs are refused |
| ST-Link V2/V3 | `stlink` | OS USB access/driver support |
| SEGGER J-Link | `jlink` | SEGGER driver package/DLL; decimal serial without leading zeroes |
| CMSIS-DAP / DAPLink | `cmsisdap` | OS USB/HID access and probe firmware support |
| Raspberry Pi Debug Probe | `picoprobe` | Compatible debug probe firmware and USB access |

The selected driver is passed as pyOCD's type-prefixed selector. The app also checks
the actual returned driver class and full UID. A missing driver or a wrong-kind
match does not fall back to a different driver. J-Link target power is not enabled
by the app. Requested clock rates may be quantized or rejected by the device/driver.
Changing the UI selection does not install packages, drivers or MCU target packs.

Import the board image and choose watches. A BIN additionally
requires its actual load address and manual variable definitions. Save the workspace
locally; it contains paths and UIDs and is ignored by Git by default.

## What attachment means

pyOCD is asked to attach without halting and not automatically unlock a protected
target. The app does not offer Flash erase/programming, reset, halt, stepping, or
arbitrary writes. This limits the application interface, but debug initialization
itself can affect a target. Device-specific startup sequences, access protection,
security states, low-power modes, caches, probe firmware, and drivers need testing.

The image check covers imported load bytes that fall in declared Flash regions.
A mismatch, unknown target range, duplicate probe assignment, invalid scalar type,
or missing load image stops that board's observation.

If a connection fails, check the target name, image build, exact UID, OS access,
probe ownership by another debugger, and pyOCD's own device support. Do not add
automatic mass erase or reset as a workaround.

## Validation matrix

| Setup | Initial status |
| --- | --- |
| Synthetic byte sources, 3 boards | Automated demo/record/replay verified |
| Fake pyOCD session and RAM/Flash | Adapter contract verified |
| Driver dropdown, SWD/JTAG, clock and workspace restore | Actual Windows UI verified offline |
| Type/UID filtering and requested protocol/clock | Fake driver/session contract verified |
| Physical ST-Link / STM32 | Not tested |
| Physical J-Link / STM32 | Not tested |
| Physical CMSIS-DAP / STM32 | Not tested |
| Physical Raspberry Pi Debug Probe / STM32 | Not tested |
| More than 3 simultaneous physical boards | Not tested |

Report exact versions and target/probe combinations when contributing physical results.
