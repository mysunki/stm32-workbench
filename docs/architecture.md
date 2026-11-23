# Architecture and design decisions

## Why this shape?

A firmware file, a physical target, and a debug probe are different identities.
They are deliberately separate in the workspace. An ELF identifies named objects;
a probe UID selects a cable/device; the pyOCD target declares the memory map and
connection behavior. None is inferred from a company-specific product profile.

| Module | Responsibility |
| --- | --- |
| `models.py` | Scalar symbols, explicit decoding, workspace validation |
| `firmware.py` | Offline file parsing, image SHA256, symbols and load ranges |
| `backends.py` | Synthetic byte source; optional pyOCD connection and reads |
| `engine.py` | Connection ownership, per-board workers, typed timestamped events |
| `recording.py` | JSONL source provenance, durability, validation, offline playback |
| `ui.py` | Tk main-thread event rendering and selected-series visualization |
| `cli.py` | Inspection, synthetic capture, replay inspection, test entry points |

## Connection ownership

Each board has one worker. That worker opens, uses, and closes its backend. It does
not share a target object with the Tk thread or other boards. Duplicate probe UIDs
are rejected before any worker starts. A read failure stops that board and emits an
error; other board workers remain independent.

Stopping requests cooperative shutdown. The application waits for owned connections
to close and does not terminate external debug servers or other processes. A backend
read can still block in a driver; the UI waits rather than pretending the connection
has closed. Driver-level timeout behavior needs physical testing.

## Observation policy

The application exposes RAM/Flash reads, not a full target-control interface.
The live adapter uses exact UID matching, attach mode, `auto_unlock=False`, and
`resume_on_disconnect=False`. Working-directory configuration and default user
scripts are bypassed. Memory/code caching is disabled to avoid presenting cached
data as live observations.

Flash load bytes within the declared target Flash region are compared before watch
reads. This detects image mismatches; it is not cryptographic device attestation,
an MCU behavior test, or a check of all unused Flash. A target/driver may still
perform debug initialization writes. Attaching is not a zero-impact operation.

## Timing and bounded memory

Events carry host monotonic nanoseconds, UTC nanoseconds, raw bytes, the selected
type, decoded value, and read start/end brackets. Reads are sequential and separate
boards are not synchronized. The configured interval is a scheduling target.

The engine retains at most 4,096 pending UI events; loss increments a counter.
Recorders/UI emit gap metadata when detected. This bounds memory but makes the
recording incomplete if a consumer falls behind. Charts retain 1,200 points per
series and do not connect long observation gaps.

## Data durability and provenance

A recording starts with schema, application, timing disclaimer, and a workspace
snapshot. Demo/live source labels are repeated in events and validated during replay.
Replay never constructs an Engine or imports a hardware session to obtain values.
Raw bytes and typed values must agree. Data flushes at least during writes separated
by 250ms; normal close additionally calls fsync. There is no hard power-loss durability
guarantee. Malformed or truncated tails are reported; partial files are preserved.

## Why no MCU emulator?

File inspection and synthetic traces are useful without claiming peripheral or CPU
emulation. Faithful firmware execution needs a supported MCU/peripheral model,
interrupts, clocks, external circuits, and I/O. Future instruction-level emulation
would be a separate adapter with an explicit device compatibility matrix.
