"""Publication decisions tested with fake subprocesses; no installers or GitHub writes."""
import importlib.util
import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


def load_publisher():
    path = Path(__file__).resolve().parents[1] / "tools/publish_interactive.py"
    spec = importlib.util.spec_from_file_location("publication_test_subject", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.publisher = load_publisher()
        # Fake installers/publication must not print success messages as if real.
        self.output = io.StringIO()
        redirect = contextlib.redirect_stdout(self.output)
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)

    def test_wrong_account_refuses_publication(self):
        result = SimpleNamespace(returncode=0, stdout=json.dumps({"login": "other-user", "id": 123}))
        with patch.object(self.publisher, "run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "expected mysunki"):
                self.publisher.authenticated_user("gh")

    def test_existing_repository_is_never_overwritten(self):
        result = SimpleNamespace(returncode=0, stdout="{}")
        with patch.object(self.publisher, "run", return_value=result) as runner:
            with self.assertRaisesRegex(RuntimeError, "already exists"):
                self.publisher.publish("git", "gh", {"login": "mysunki", "id": 123})
        self.assertEqual(runner.call_count, 1)

    def test_network_error_is_not_treated_as_a_missing_repository(self):
        result = SimpleNamespace(returncode=1, stdout="", stderr="network inaccessible")
        with patch.object(self.publisher, "run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "Could not confirm"):
                self.publisher.require_new_repository("gh")

    def test_only_confirmed_404_allows_new_repository_path(self):
        result = SimpleNamespace(returncode=1, stdout='{"message":"Not Found"}', stderr="gh: Not Found (HTTP 404)")
        with patch.object(self.publisher, "run", return_value=result):
            self.publisher.require_new_repository("gh")

    def test_install_failure_is_not_bypassed(self):
        with patch.object(self.publisher, "find_tool", return_value=None), \
             patch.object(self.publisher.shutil, "which", return_value="winget"), \
             patch.object(self.publisher, "run", side_effect=RuntimeError("installation denied")) as runner:
            with self.assertRaisesRegex(RuntimeError, "installation denied"):
                self.publisher.ensure_tool("git", "Git.Git")
        self.assertEqual(runner.call_count, 1)

    def test_manifest_escape_is_refused_before_git_initialization(self):
        results = [SimpleNamespace(returncode=1, stdout='{"message":"Not Found"}', stderr="HTTP 404"),
                   SimpleNamespace(returncode=0),
                   SimpleNamespace(returncode=0, stdout=json.dumps(["../outside"] * 10))]
        with tempfile.TemporaryDirectory(prefix="workbench-test-") as folder:
            with patch.object(self.publisher, "run", side_effect=results) as runner, \
                 patch.object(self.publisher.tempfile, "mkdtemp", return_value=folder):
                with self.assertRaisesRegex(RuntimeError, "escapes"):
                    self.publisher.publish("git", "gh", {"login": "mysunki", "id": 123})
            self.assertEqual(list(Path(folder).iterdir()), [])
            self.assertEqual(runner.call_count, 3)

    def test_publication_uses_fresh_audited_checkout_and_verified_identity(self):
        files = ["README.md", "README.ko.md", "LICENSE", "CONTRIBUTING.md", "SECURITY.md",
                 "AGENTS.md", ".gitignore", "pyproject.toml", "run.py", "Publish-Start.cmd"]
        calls = []
        def fake_run(args, **kwargs):
            args = list(map(str, args))
            calls.append((args, kwargs))
            if args[:2] == ["gh", "api"]:
                return SimpleNamespace(returncode=1, stdout='{"message":"Not Found"}', stderr="HTTP 404")
            if args[-1] == "--list":
                return SimpleNamespace(returncode=0, stdout=json.dumps(files))
            if args[:3] == ["gh", "repo", "view"]:
                return SimpleNamespace(returncode=0, stdout="https://github.com/mysunki/stm32-workbench\n")
            return SimpleNamespace(returncode=0)
        with tempfile.TemporaryDirectory(prefix="workbench-test-") as folder:
            with patch.object(self.publisher, "run", side_effect=fake_run), \
                 patch.object(self.publisher.tempfile, "mkdtemp", return_value=folder), \
                 patch.object(self.publisher.webbrowser, "open") as browser:
                self.publisher.publish("git", "gh", {"login": "mysunki", "id": 123})
            self.assertTrue(all((Path(folder) / name).is_file() for name in files))
            self.assertEqual(len(list(Path(folder).iterdir())), len(files))
            self.assertTrue(any(args == ["git", "config", "user.email", "123+mysunki@users.noreply.github.com"] for args, _ in calls))
            create = next(args for args, _ in calls if args[:3] == ["gh", "repo", "create"])
            self.assertIn("--public", create)
            self.assertIn("--push", create)
            self.assertNotIn("--force", create)
            browser.assert_called_once_with("https://github.com/mysunki/stm32-workbench")
