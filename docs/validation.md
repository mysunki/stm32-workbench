# Validation — 2026-11-23

## Current result: actual Windows desktop verified from fresh source

`python -I -B tools/verify_from_scratch.py --output local/<new-directory>` passed
on Windows with CPython 3.14.7. The verifier copied only audited source into a new
folder, inherited **zero executables**, created a new virtual environment with no
system/user packages, and used the bundled pip without downloading dependencies.
It compiled the native Windows UI from included C# source and launched actual forms.

| Step | Result |
| --- | --- |
| New source folder and isolated venv | Passed; no prebuilt UI or third-party packages reused |
| Core and publication-contract tests | 55 tests passed |
| Driver selection and connection settings | Actual dropdown, SWD/JTAG, clock, offline save and workspace restore passed |
| Driver-kind/UID filtering | ST-Link/J-Link/CMSIS-DAP/Picoprobe contract checks with fake drivers passed |
| Synthetic ELF generation and 4-variable inspection | Passed |
| Three-board CLI recording and replay validation | Passed |
| Actual window, 3 boards, 12 scalar watches and charts | Passed |
| Demo link fault | Selected board stopped; other 2 boards continued |
| Record / stop / finish | Real JSONL created and validated |
| Firmware import and explicit float watch | Passed through actual UI command paths |
| Board add / remove; workspace save / load | Passed |
| Offline replay in actual table and chart | Passed |
| Exit and fresh process restoring the workspace | Passed; 3 boards / 9 saved watches |
| Rendered desktop evidence | 6 actual-control PNG captures generated |

The UI verifier invokes `PerformClick` on real Windows controls. It supplies file
dialog paths rather than driving a physical mouse. UI messages reach the normal
Python controller, Engine, Recorder, Replay, and workspace code. Those operations
are not mocked. Signals remain synthetic; this does not execute MCU instructions.

See [machine-readable acceptance](acceptance.json),
[debugger selection](screenshots/debugger-selection.png),
[watch screen](screenshots/demo-watch.png),
[firmware screen](screenshots/firmware-inspector.png),
[replay screen](screenshots/offline-replay.png), and
[fresh-process restore](screenshots/workspace-restart.png).

The machine-readable report records a fingerprint of tested executable source;
generated report/screenshot files are excluded from that fingerprint to avoid a
self-referential hash. Run the verifier again to check a modified checkout.

### Remaining boundaries

- This run uses an audited **local source snapshot**, not a direct GitHub download.
  A user-run updater separately recorded verified remote commit
  `fff8656e5717f3c73e006ea0b3fa145aefd5083b` for the preceding version. That receipt
  does not establish that these newer driver-selection changes have been pushed.
- Physical probes/STM32 boards were not connected. The optional pyOCD adapter has
  fake-memory contract tests; physical compatibility and real DWARF inference remain
  unverified. Full stepping/breakpoints/Flash programming are not implemented.
- Linux/macOS Tk rendering, other Windows setups, and the GitHub-hosted CI jobs have
  not been run here. CI configuration is not a claim of CI success.
- The original Tcl/Tk failure is resolved for the default Windows path by using a
  native .NET UI. The original Tk implementation remains available and unverified.
- Publication/update entry points require desktop acceptance. The new debugger-type
  settings were only exercised offline; no real probe was scanned or connected in
  this acceptance run. Fake adapter checks do not establish physical compatibility.

## Historical initial validation (before the native desktop was added)

Environment: Windows, CPython 3.14.7. No packages or drivers were installed.
No physical probes, boards, target outputs, resets, or Flash operations were used.

## Passed locally

- `python -I -B run.py selftest`: **31 tests passed**.
- Linked ARM ELF32 fixture inspection, malformed ELF refusal, raw BIN metadata,
  Intel HEX checksum/EOF/address/overlap checks.
- Explicit scalar decoding, duplicate board/probe refusal, workspace round-trip.
- Independent board failure handling and worker-owned open/read/close operations.
- Bounded event buffering and detected-loss count.
- Synthetic capture → JSONL → offline replay with raw-value/provenance validation.
- Fake pyOCD session: exact UID selection, Flash comparison, mismatch refusal,
  RAM/Flash range checks, attach/no-unlock/no-cache options.
- Python source syntax and TOML package metadata parsing.
- PowerShell publication script syntax parsing (no publication performed).
- Allowlisted public source audit.

## Observed demo run

```console
python -I -B run.py record-demo --duration 1 --output ../stm32-workbench-demo-20261123.jsonl
Recorded 120 SYNTHETIC samples from 3 demo boards

python -I -B run.py replay-info ../stm32-workbench-demo-20261123.jsonl
{
  "schema": 1,
  "boards": 3,
  "events": 129,
  "source_modes": ["demo"],
  "samples": 120,
  "hardware_opened": false
}
```

Counts vary with scheduling; these values describe this run, not a throughput claim.
The recording stays outside the public source package.

## Limits at that initial stage (superseded where stated above)

- The installed Python cannot initialize Tk because its Tcl `init.tcl` is missing.
  Desktop rendering, widget behavior, and the real UI smoke check are unverified.
  The desktop source is implemented; this is not a screenshot-verified release.
- Optional pyOCD and pyelftools packages are absent. Physical target compatibility
  and real DWARF inference were not exercised. Adapter checks use fake modules.
- Only Windows/Python 3.14 was run locally. The GitHub Actions matrix is configured
  but has not run, and does not imply cross-platform validation has passed.
- Git/GitHub CLI and an exposed repository-write connector are unavailable in the
  preparation environment. No remote repository or initial push was created.
  The publication helper is prepared and syntax-checked, not end-to-end tested.
- Binary installation/build distribution has not been validated. Running directly
  from the checkout with the documented commands is the tested headless path.

Do not promote fake-memory tests or synthetic data into hardware validation results.

## Publication launcher follow-up — 2026-11-23

The user requested handling all commands and leaving only human confirmation.
An attempt to execute `winget --version` was denied by the current agent execution
environment. No installer ran, and no authentication or remote write was performed.

`Publish-Start.cmd` now runs a Python helper for a user to launch from a normal
Windows console. It uses standard WinGet installers and browser authentication,
checks the account, tests and audits source, creates a fresh allowlisted checkout,
and requests a new public repository. It does not modify security/execution policies,
retry denied installs by another route, force-push, or overwrite an existing repository.

Seven additional tests use fake subprocess results for account mismatch, destination
existence, network failure, confirmed 404, denied installation, path escape, and
publication sequencing/identity. **At that stage, the local suite passed 38 tests.** These
are decision/contract tests; the real installation/login/upload flow is unverified.
