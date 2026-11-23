"""Windows desktop using an independently authored .NET Framework UI host.

Only the GUI is C#; all application operations use the existing Python controller.
The host is compiled locally from the included source, without downloading tools.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time

from .desktop import Desktop
from .models import load_workspace


def build_host(cache: Path | None = None) -> Path:
    if os.name != "nt":
        raise RuntimeError("The Windows desktop host requires Windows")
    source = Path(__file__).with_name("WindowsDesktop.cs")
    windir = Path(os.environ.get("WINDIR", "C:/Windows"))
    compiler = next((p for p in (windir / "Microsoft.NET/Framework64/v4.0.30319/csc.exe",
                                 windir / "Microsoft.NET/Framework/v4.0.30319/csc.exe") if p.is_file()), None)
    if compiler is None:
        raise RuntimeError("Windows desktop requires .NET Framework 4.x with its C# compiler. No installer was started.")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:16]
    cache = cache or Path.cwd() / "local/native-ui"
    cache.mkdir(parents=True, exist_ok=True)
    output = cache.resolve() / f"workbench-ui-{digest}.exe"
    if not output.exists():
        result = subprocess.run([str(compiler), "/nologo", "/target:winexe", "/platform:anycpu", "/optimize+",
            "/out:" + str(output), "/r:System.Windows.Forms.dll", "/r:System.Drawing.dll",
            "/r:System.Web.Extensions.dll", "/r:System.Core.dll", str(source)], capture_output=True, text=True,
            timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise RuntimeError("Native desktop compilation failed:\n" + result.stdout + result.stderr)
    return output


def launch(workspace=None, *, verify_dir=None, verify_mode="full"):
    runtime = Desktop(load_workspace(workspace) if workspace else None)
    if verify_dir and any(board.backend != "demo" for board in runtime.boards):
        raise ValueError("Automated desktop verification accepts synthetic demo workspaces only; hardware is disabled")
    host = build_host()
    arguments = [str(host)]
    if verify_dir:
        verify_dir = Path(verify_dir).resolve()
        verify_dir.mkdir(parents=True, exist_ok=True)
        arguments.extend(["--verify", str(verify_dir), "--verify-mode", verify_mode])
    process = subprocess.Popen(arguments, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", bufsize=1, creationflags=subprocess.CREATE_NO_WINDOW)
    commands = queue.Queue()
    stderr_lines = []
    def read_commands():
        try:
            for line in process.stdout:
                try:
                    command = json.loads(line)
                    if not isinstance(command, dict):
                        raise ValueError("Expected command object")
                    commands.put(command)
                except ValueError as error:
                    commands.put({"op": "_protocol_error", "text": str(error)})
        finally:
            commands.put({"op": "_frontend_eof"})
    def read_errors():
        for line in process.stderr:
            stderr_lines.append(line)
    readers = [threading.Thread(target=read_commands, daemon=True), threading.Thread(target=read_errors, daemon=True)]
    for thread in readers:
        thread.start()
    def send(message):
        process.stdin.write(json.dumps(message, ensure_ascii=False, allow_nan=False) + "\n")
        process.stdin.flush()
    verification = None
    last_snapshot, revision = 0, -1
    eof = False
    started = time.monotonic()
    try:
        while True:
            while not commands.empty():
                command = commands.get_nowait()
                operation = command.get("op")
                if operation == "_frontend_eof":
                    eof = True
                    runtime.closing = True
                    runtime.stop()
                elif operation == "verification_result":
                    verification = command.get("result")
                    runtime.closing = True
                    runtime.stop()
                else:
                    try:
                        if operation == "_protocol_error":
                            raise ValueError(command["text"])
                        if verify_dir and operation == "start" and any(board.backend != "demo" for board in runtime.boards):
                            raise ValueError("Hardware is disabled during automated desktop verification")
                        runtime.dispatch(command)
                    except Exception as error:
                        if not eof:
                            send({"kind": "error", "text": f"{type(error).__name__}: {error}"})
                    last_snapshot = 0
            keep_running = runtime.poll()
            if not eof and process.poll() is None:
                while runtime.messages:
                    send(runtime.messages.pop(0))
                if runtime.firmware_revision != revision:
                    try:
                        send(runtime.firmware_view())
                    except Exception as error:
                        send({"kind": "error", "text": str(error)})
                    revision = runtime.firmware_revision
                if time.monotonic() - last_snapshot >= 0.12:
                    send(runtime.snapshot())
                    last_snapshot = time.monotonic()
            if not keep_running:
                if not eof and process.poll() is None:
                    send({"kind": "close"})
                break
            if verify_dir and time.monotonic() - started > 45:
                raise RuntimeError("Desktop verification timed out; no hardware was opened")
            time.sleep(0.02)
    finally:
        runtime.stop()
        if runtime.engine and not runtime.engine.join(5):
            raise RuntimeError("Waiting for owned board connection shutdown")
        runtime.poll()
        runtime.finish_recording()
        try:
            if process.poll() is None:
                send({"kind": "close"})
            process.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        exit_code = process.wait(timeout=10)
        for thread in readers:
            thread.join(timeout=1)
    if verify_dir:
        result = {"passed": bool(verification and verification.get("passed")),
                  "frontend_exit_code": exit_code, "frontend": verification,
                  "physical_hardware_opened": False, "application": "native Windows desktop + actual Python engine",
                  "stderr": "".join(stderr_lines)}
        (verify_dir / f"ui-result-{verify_mode}.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        if not result["passed"] or exit_code:
            raise RuntimeError("Desktop interaction verification failed: " + json.dumps(result))
    elif exit_code:
        raise RuntimeError("Windows desktop exited with error: " + "".join(stderr_lines))
    return 0
