# References

The implementation is newly authored. The following public primary references
were consulted for format/API behavior; their code is not copied or vendored.

- [GNU objcopy: raw binaries discard symbols and relocations](https://sourceware.org/binutils/docs/binutils/objcopy.html)
- [pyOCD Python API and probe selection](https://pyocd.io/docs/python_api.html)
- [pyOCD options: attach, auto_unlock, caching, resume_on_disconnect](https://pyocd.io/docs/options.html)
- [pyOCD debug probe support](https://pyocd.io/docs/debug_probes.html)
- [pyOCD Session API source](https://github.com/pyocd/pyOCD/blob/main/pyocd/core/session.py)
- [pyelftools DWARF API examples](https://github.com/eliben/pyelftools/tree/main/examples)
- [ARM ELF ABI specification](https://github.com/ARM-software/abi-aa/blob/main/aaelf32/aaelf32.rst)

The optional libraries have independent releases and licenses. Compatibility claims
must identify the versions tested rather than relying on these links remaining unchanged.
