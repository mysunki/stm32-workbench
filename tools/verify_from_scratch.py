"""Copy audited source, create an empty venv, and exercise the real Windows desktop.

No pip downloads, board connections, GitHub writes, or inherited build outputs.
File dialog paths are supplied by the verifier; actual buttons/controller/engine,
recording files, saved workspace, and rendered Windows controls are exercised.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import time
import venv

ROOT = Path(__file__).resolve().parents[1]


def source_module():
    spec = importlib.util.spec_from_file_location("public_source_audit", ROOT / "tools/package_source.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New verification directory; existing nonempty directories are refused")
    args = parser.parse_args(argv)
    if os.name != "nt":
        parser.exit(1, "The real desktop acceptance workflow currently requires Windows. Core tests remain cross-platform.\n")
    target = args.output.resolve()
    if target.exists() and any(target.iterdir()):
        parser.exit(1, "Choose a new or empty output directory to avoid mixing verification runs.\n")
    target.mkdir(parents=True, exist_ok=True)
    stage, environment = target / "source", target / "environment"
    stage.mkdir()
    artifacts = stage / "local/acceptance"
    artifacts.mkdir(parents=True)
    started, stages = time.monotonic(), []
    report = {"passed": False, "physical_hardware_opened": False, "network_used": False,
              "source_origin": "audited local source snapshot; not a GitHub download", "stages": stages}
    try:
        files = source_module().source_files()
        manifest = []
        for source in files:
            relative = source.relative_to(ROOT)
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            manifest.append({"path": relative.as_posix(), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
        report["source_files"] = len(manifest)
        report["source_fingerprint"] = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
        code_manifest = [item for item in manifest if Path(item["path"]).suffix in (".py", ".cs", ".toml", ".cmd", ".ps1")]
        report["tested_code_fingerprint"] = hashlib.sha256(json.dumps(code_manifest, sort_keys=True).encode()).hexdigest()
        report["code_fingerprint_scope"] = "Python/C#/TOML/CMD/PowerShell source; excludes generated reports and screenshots to avoid self-referential hashes"
        (target / "source-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        stages.append({"name": "fresh_source_copy", "passed": True, "inherited_executables": len(list(stage.rglob("*.exe")))})
        if stages[-1]["inherited_executables"]:
            raise RuntimeError("The fresh source unexpectedly contains prebuilt executables")
        venv.EnvBuilder(with_pip=True, system_site_packages=False, symlinks=False).create(environment)
        python = environment / "Scripts/python.exe"
        def command(name, arguments, timeout=60):
            result = subprocess.run([str(python), "-I", "-B", *map(str, arguments)], cwd=stage,
                                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
            (target / (name + ".stdout.log")).write_text(result.stdout, encoding="utf-8")
            (target / (name + ".stderr.log")).write_text(result.stderr, encoding="utf-8")
            stages.append({"name": name, "passed": result.returncode == 0, "exit_code": result.returncode})
            print(name + (": PASS" if result.returncode == 0 else ": FAIL"), flush=True)
            if result.returncode:
                raise RuntimeError(name + " failed: " + result.stderr[-3000:])
            return result.stdout
        details = json.loads(command("isolated_environment", ["-c", "import json,sys,site;print(json.dumps({'prefix':sys.prefix,'base_prefix':sys.base_prefix,'user_site_enabled':site.ENABLE_USER_SITE}))"]))
        if Path(details["prefix"]).resolve() != environment or details["prefix"] == details["base_prefix"] or details["user_site_enabled"]:
            raise RuntimeError("The verification interpreter is not an isolated virtual environment")
        packages = json.loads(command("installed_packages", ["-m", "pip", "list", "--format", "json", "--disable-pip-version-check"]))
        report["packages"] = packages
        if {p["name"].lower() for p in packages} - {"pip", "setuptools"}:
            raise RuntimeError("The fresh environment contains unexpected third-party packages")
        command("core_tests", ["run.py", "selftest"])
        test_summary = re.search(r"Ran (\d+) tests?", (target / "core_tests.stderr.log").read_text(encoding="utf-8"))
        if test_summary is None:
            raise RuntimeError("Core test runner did not return a test count")
        report["tests_passed"] = int(test_summary.group(1))
        command("make_synthetic_example", ["tools/make_example.py", artifacts / "synthetic-symbols.elf"])
        image = json.loads(command("firmware_inspection", ["run.py", "inspect", artifacts / "synthetic-symbols.elf", "--json"]))
        if len(image["symbols"]) != 4:
            raise RuntimeError("Synthetic image symbol discovery failed")
        command("record_cli_demo", ["run.py", "record-demo", "--duration", "1", "--output", artifacts / "cli-session.jsonl"])
        cli_replay = json.loads(command("validate_cli_recording", ["run.py", "replay-info", artifacts / "cli-session.jsonl"]))
        command("desktop_full", ["run.py", "gui", "--verify-dir", artifacts])
        command("desktop_restart", ["run.py", "gui", "--workspace", artifacts / "ui.workspace.json", "--verify-dir", artifacts, "--verify-mode", "restart"])
        ui_replay = json.loads(command("validate_ui_recording", ["run.py", "replay-info", artifacts / "ui-session.jsonl"]))
        full = json.loads((artifacts / "ui-result-full.json").read_text())
        restart = json.loads((artifacts / "ui-result-restart.json").read_text())
        if not full["passed"] or not restart["passed"]:
            raise RuntimeError("Actual desktop interaction verification did not pass")
        screenshots = full["frontend"]["screenshots"] + restart["frontend"]["screenshots"]
        for name in screenshots:
            source = artifacts / name
            if not source.is_file() or source.stat().st_size < 10000:
                raise RuntimeError("Missing or empty desktop screenshot: " + name)
            shutil.copy2(source, target / name)
        report.update({"passed": True, "python_version": sys.version.split()[0],
                       "environment": "new venv; no system/user packages; no downloads", "platform": sys.platform,
                       "ui": full["frontend"], "restart": restart["frontend"], "cli_recording": cli_replay,
                       "ui_recording": ui_replay, "screenshots": screenshots,
                       "native_compilation": "new executable compiled from included C# source inside fresh checkout",
                       "duration_seconds": round(time.monotonic() - started, 2)})
        print("FROM-SCRATCH DESKTOP ACCEPTANCE: PASS", flush=True)
        print("Evidence directory: " + str(target), flush=True)
        return 0
    except Exception as error:
        report["error"] = str(error)
        print("FROM-SCRATCH DESKTOP ACCEPTANCE: FAIL\n" + str(error), file=sys.stderr)
        return 1
    finally:
        (target / "acceptance.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
