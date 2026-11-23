# Firmware support

The dependency-free inspector is intentionally strict.

| Input | Supported | Not inferred |
| --- | --- | --- |
| ELF32 | Linked executable, machine ARM, little endian, normal section/program tables | MCU identity, C types from symbol size, relocated stack/register locations |
| `.out` / `.axf` | Same as ELF32 when the magic/header match | Proprietary non-ELF formats |
| Intel HEX | Checksummed data, extended segment/linear address, EOF; sparse ranges preserved | C symbol names/types |
| BIN | Raw bytes, SHA256, explicit optional load address | Address, C symbol names/types |
| MAP | Not parsed in v0.1.0 | Vendor/toolchain-specific heuristic guesses |

Bounds: file size 64 MiB, load-image data 16 MiB, ELF symbol entries 200,000,
1–8-byte scalar object symbols. The HEX implementation accumulates sparse byte
addresses and can use more memory than the input's payload size. Use trusted,
appropriately sized firmware files for desktop inspection.

Duplicate static symbol names at different addresses receive `@address` suffixes.
Undefined, absolute, function, oversized object, and unsupported special-section
symbols are not turned into scalar watches.

Without optional DWARF support, symbols are raw bytes. Install `.[dwarf]` to infer
supported fixed-address global base types from DWARF. Typedef/const/volatile wrappers
are resolved; pointers, structs, arrays, location lists, register expressions, and
stack-relative locations remain unsupported. Inference failure leaves raw symbols
available and adds a note. Manually selecting a type requires the correct byte size.

For live use, load segments are checked against the target's declared Flash. RAM
initializers use ELF physical load addresses. Only target-declared readable RAM or
Flash can be watched; peripheral registers are not accepted because some reads have
side effects. Different devices and external memories need explicit testing.

Always use the same build's image and symbols. Compiler optimization can remove or
merge variables; symbol discovery cannot restore optimized-away state.
