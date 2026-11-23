# Initial validation — 2026-11-23

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

## Not yet validated

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
publication sequencing/identity. **The complete local suite passes 38 tests.** These
are decision/contract tests; the real installation/login/upload flow is unverified.
