"""User-launched Windows setup and publication. Uses normal installers and browser auth.

Run from a normal console using Publish-Start.cmd. Never use this helper to work
around an agent sandbox, execution policy, or a denied installation. It does not
alter security policies, request administrator elevation itself, or accept tokens.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
OWNER, NAME = "mysunki", "stm32-workbench"


def run(args, *, cwd=ROOT, capture=False, check=True):
    result = subprocess.run([str(arg) for arg in args], cwd=cwd, text=True,
                            capture_output=capture, encoding="utf-8" if capture else None,
                            errors="replace" if capture else None)
    if check and result.returncode:
        if capture and result.stderr:
            print(result.stderr.strip(), file=sys.stderr)
        raise RuntimeError(f"Command failed ({result.returncode}): {Path(str(args[0])).name} {args[1]}")
    return result


def find_tool(name):
    executable = shutil.which(name)
    if executable:
        return executable
    # Newly installed tools do not update this already-running process's PATH.
    roots = [os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", ""),
             str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs")]
    relative = "Git/cmd/git.exe" if name == "git" else "GitHub CLI/gh.exe"
    for root in roots:
        candidate = Path(root) / relative
        if root and candidate.is_file():
            return str(candidate)
    if os.name == "nt":
        import winreg
        new_paths = []
        for hive, key in ((winreg.HKEY_CURRENT_USER, r"Environment"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
            try:
                with winreg.OpenKey(hive, key) as handle:
                    new_paths.append(os.path.expandvars(winreg.QueryValueEx(handle, "Path")[0]))
            except OSError:
                pass
        os.environ["PATH"] = os.pathsep.join([*new_paths, os.environ.get("PATH", "")])
    return shutil.which(name)


def ensure_tool(name, package):
    executable = find_tool(name)
    if executable:
        return executable
    winget = shutil.which("winget")
    if not winget:
        raise RuntimeError("Windows Package Manager is unavailable. Install Git and GitHub CLI from their official installers, then open Publish-Start.cmd again.")
    print(f"Installing {package} using Windows Package Manager. Confirm any normal installer prompt.", flush=True)
    run([winget, "install", "--id", package, "--exact", "--source", "winget", "--silent",
         "--accept-source-agreements", "--accept-package-agreements", "--disable-interactivity"])
    executable = find_tool(name)
    if not executable:
        raise RuntimeError(f"{name} is not available yet. Restart Publish-Start.cmd after the installation completes.")
    return executable


def authenticated_user(gh):
    result = run([gh, "api", "user"], capture=True)
    user = json.loads(result.stdout)
    if user.get("login", "").casefold() != OWNER.casefold():
        raise RuntimeError(f"Signed in as {user.get('login', '(unknown)')}; expected {OWNER}. No repository was created. Select the correct GitHub account and run again.")
    if type(user.get("id")) is not int or user["id"] <= 0:
        raise RuntimeError("Could not confirm the authenticated GitHub user ID")
    return user


def require_new_repository(gh):
    result = run([gh, "api", f"repos/{OWNER}/{NAME}"], capture=True, check=False)
    if result.returncode == 0:
        raise RuntimeError(f"{OWNER}/{NAME} already exists. Stopped without pushing or replacing anything. Check whether an earlier publication already succeeded.")
    try:
        response = json.loads(result.stdout)
    except ValueError:
        response = {}
    if response.get("message") != "Not Found" or "404" not in result.stderr:
        raise RuntimeError("Could not confirm that the destination repository is absent. Check network access and GitHub login, then retry.")


def publish(git, gh, user, source_root=ROOT):
    source_root = Path(source_root).resolve()
    require_new_repository(gh)
    run([sys.executable, "-I", "-B", source_root / "run.py", "selftest"])
    # This audit returns an allowlist, not a recursive copy of the workspace.
    result = run([sys.executable, "-I", "-B", source_root / "tools/package_source.py", "--list"], capture=True)
    names = json.loads(result.stdout)
    if not isinstance(names, list) or len(names) < 10 or not all(isinstance(name, str) for name in names):
        raise RuntimeError("Invalid source audit manifest")
    staging = Path(tempfile.mkdtemp(prefix="stm32-workbench-publish-"))
    print(f"Publication checkout: {staging}", flush=True)
    for name in names:
        source, destination = (source_root / name).resolve(), (staging / name).resolve()
        if not source.is_relative_to(source_root) or not destination.is_relative_to(staging):
            raise RuntimeError("Source manifest path escapes the selected project")
        if (source_root / name).is_symlink() or not source.is_file():
            raise RuntimeError("Source manifest contains a missing file or symlink")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    run([sys.executable, "-I", "-B", "tools/package_source.py", "--check"], cwd=staging)
    run([git, "init", "-b", "main"], cwd=staging)
    run([git, "config", "user.name", user["login"]], cwd=staging)
    run([git, "config", "user.email", f"{user['id']}+{user['login']}@users.noreply.github.com"], cwd=staging)
    # Only explicit audited source paths are staged; no parent files or old Git history.
    run([git, "add", "--", *names], cwd=staging)
    run([git, "commit", "-m", "Build independent multi-board STM32 observation workbench"], cwd=staging)
    result = run([gh, "repo", "create", f"{OWNER}/{NAME}", "--public", "--source", staging,
                  "--remote", "origin", "--push", "--description",
                  "Multi-board STM32 variable observation, firmware inspection, and offline session replay."],
                 cwd=staging, check=False)
    if result.returncode:
        raise RuntimeError(f"Publication did not complete. Checkout preserved at {staging}. Check GitHub for partial repository creation before retrying; this helper never overwrites an existing repository.")
    result = run([gh, "repo", "view", f"{OWNER}/{NAME}", "--json", "url", "--jq", ".url"], capture=True)
    url = result.stdout.strip()
    if url != f"https://github.com/{OWNER}/{NAME}":
        raise RuntimeError("Upload command finished, but the returned repository URL was unexpected. Check GitHub before retrying.")
    print(f"\nPublished: {url}\nKeep this checkout for future commits: {staging}", flush=True)
    try:
        webbrowser.open(url)
    except Exception:
        pass  # Browser handoff does not change the verified publication result.


def main():
    if os.name != "nt":
        print("This installation launcher is for Windows. Use the documented Git/CLI workflow on other systems.", file=sys.stderr)
        return 1
    try:
        print(f"STM32 Workbench: publish the audited source to PUBLIC repository {OWNER}/{NAME}.", flush=True)
        print("Browser login and normal Windows installer confirmation may require your input.\n", flush=True)
        verification = ROOT / "local" / ("before-publication-" + time.strftime("%Y%m%d-%H%M%S"))
        print("First: verify a fresh source copy and empty environment, including the actual Windows UI.", flush=True)
        run([sys.executable, "-I", "-B", ROOT / "tools/verify_from_scratch.py", "--output", verification], cwd=ROOT)
        proof = json.loads((verification / "acceptance.json").read_text(encoding="utf-8"))
        if proof.get("passed") is not True:
            raise RuntimeError("Desktop acceptance failed; publication is disabled")
        print("Verification passed. Screenshots and results: " + str(verification), flush=True)
        try:
            os.startfile(str(verification))
        except OSError:
            pass
        input("Review the screenshots. Press Enter to continue with PUBLIC GitHub publication, or Ctrl+C to stop: ")
        git = ensure_tool("git", "Git.Git")
        gh = ensure_tool("gh", "GitHub.cli")
        # Make the resolved Git available to gh in this process and its children.
        os.environ["PATH"] = str(Path(git).parent) + os.pathsep + os.environ.get("PATH", "")
        print("Authenticate in your browser using the mysunki account.", flush=True)
        run([gh, "auth", "login", "--hostname", "github.com", "--git-protocol", "https", "--web", "--scopes", "workflow"])
        user = authenticated_user(gh)
        run([gh, "auth", "setup-git", "--hostname", "github.com"])
        # Publish the immutable source copy that passed the acceptance workflow.
        publish(git, gh, user, source_root=verification / "source")
        return 0
    except KeyboardInterrupt:
        print("Stopped by the user. Check GitHub for partial creation before retrying.", file=sys.stderr)
        return 130
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        print(f"\nPublication stopped: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
