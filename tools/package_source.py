"""Audit and package only explicitly selected public source, never the parent tree."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {"AGENTS.md", ".gitignore", "pyproject.toml", "run.py", "Start-Workbench.cmd", "Verify-Workbench.cmd",
              "Publish-GitHub.ps1", "Publish-Start.cmd", "README.md", "README.ko.md", "LICENSE", "CONTRIBUTING.md", "SECURITY.md"}
DIRECTORIES = {"src": {".py", ".cs"}, "tests": {".py"}, "docs": {".md"}, "tools": {".py"}, ".github": {".yml", ".yaml"}}
EXAMPLES = {"examples/demo.workspace.json"}
PUBLIC_EVIDENCE = {"docs/acceptance.json", "docs/screenshots/demo-watch.png", "docs/screenshots/firmware-inspector.png",
                   "docs/screenshots/offline-replay.png", "docs/screenshots/workspace-restart.png", "docs/screenshots/debugger-selection.png"}
SECRET_PATTERNS = [
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{30,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)[a-z]:[\\/](?:Users|Documents and Settings)[\\/][^\s\"']+"),
]


def source_files(root=ROOT) -> list[Path]:
    root = root.resolve()
    candidates = [root / name for name in sorted(ROOT_FILES | EXAMPLES)]
    candidates.extend(root / name for name in sorted(PUBLIC_EVIDENCE) if (root / name).is_file())
    for folder, extensions in DIRECTORIES.items():
        directory = root / folder
        if directory.is_symlink():
            raise ValueError(f"Source directory is a symlink: {folder}")
        for path in sorted(directory.rglob("*")):
            if "__pycache__" not in path.parts and path.suffix in extensions and path.is_file():
                candidates.append(path)
    result = []
    for path in candidates:
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError(f"Source path escapes the project or is a symlink: {path.name}")
        if not path.is_file():
            raise ValueError(f"Missing source file: {path.relative_to(root)}")
        if path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError(f"Unexpectedly large source: {path.name}")
        raw = path.read_bytes()
        if path.relative_to(root).as_posix() in PUBLIC_EVIDENCE and path.suffix == ".png":
            if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("Screenshot evidence must be a PNG")
            result.append(path)
            continue
        text = raw.decode("utf-8")
        if b"\0" in raw:
            raise ValueError(f"Unexpected binary source: {path.name}")
        if any(pattern.search(text) for pattern in SECRET_PATTERNS):
            raise ValueError(f"Potential credential/private path in {path.relative_to(root)}; review before publication")
        result.append(path)
    return sorted(set(result))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--list", action="store_true", help="Print allowlisted relative paths as a JSON array")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        files = source_files()
        if args.list:
            print(json.dumps([path.relative_to(ROOT).as_posix() for path in files]))
            return 0
        manifest = [{"path": p.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                     "bytes": p.stat().st_size} for p in files]
        if args.output:
            output = args.output.resolve()
            if output.exists():
                raise ValueError("Archive already exists; choose a new output name")
            with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
                for path in files:
                    archive.write(path, "stm32-workbench/" + path.relative_to(ROOT).as_posix())
                archive.writestr("stm32-workbench/SOURCE-MANIFEST.json", json.dumps({"schema": 1, "files": manifest}, indent=2))
            print(f"Created {output.name}: {len(files)} audited source files + SHA256 manifest")
        else:
            print(f"Source audit passed: {len(files)} allowlisted UTF-8 files; no runtime firmware or captures included")
        return 0
    except (ValueError, OSError, UnicodeError) as error:
        print(f"Source audit failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
