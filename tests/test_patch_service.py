import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from app.models.schemas import Diagnosis
from app.services.github_service import WorkspaceMetadata
from app.services.patch_service import PatchService


class PatchServiceTests(unittest.TestCase):
    def setUp(self):
        incident = UUID("12345678-1234-5678-1234-567812345678")
        directory = tempfile.TemporaryDirectory(prefix=f"curiora-{incident}-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.workspace = WorkspaceMetadata("owner/repo", "dev", f"curio/fix-{incident}", self.root)
        self.manifest = self.root / "requirements.txt"
        self.manifest.write_text("fastapi>=0.100\n")
        self.git("init", "--initial-branch=" + self.workspace.fix_branch, "--template=")
        self.git("add", "requirements.txt")
        self.commit()
        self.service = PatchService()

    def git(self, *args):
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull})
        return subprocess.run(
            ["git", "-c", "core.hooksPath=" + os.devnull, *args],
            cwd=self.root, env=env, capture_output=True, text=True, check=True,
        ).stdout

    def commit(self):
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "fixture")

    def diagnosis(self, **overrides):
        values = dict(
            error_type="missing_dependency",
            root_cause="ModuleNotFoundError: No module named 'stripe'",
            affected_files=["requirements.txt"],
            proposed_fix="Add stripe to requirements.txt",
            confidence=0.99,
            safe_to_autofix=True,
        )
        return Diagnosis(**(values | overrides))

    def test_missing_dependency_added_once_with_git_diff(self):
        git_before = {p.relative_to(self.root): p.read_bytes() for p in (self.root / ".git").rglob("*") if p.is_file()}
        result = self.service.apply_patch(self.diagnosis(), self.workspace)
        self.assertTrue(result.success, result.reason)
        self.assertEqual(result.changed_files, ["requirements.txt"])
        self.assertEqual(self.manifest.read_text(), "fastapi>=0.100\nstripe\n")
        self.assertIn("diff --git a/requirements.txt b/requirements.txt", result.diff)
        self.assertIn("+stripe\n", result.diff)
        git_after = {p.relative_to(self.root): p.read_bytes() for p in (self.root / ".git").rglob("*") if p.is_file()}
        self.assertEqual(git_before, git_after)
        repeated = self.service.apply_patch(self.diagnosis(
            root_cause="The Python environment cannot import the stripe package.",
            proposed_fix=("Add stripe to the project's dependency manifest and install "
                          "the dependencies in the environment running the application."),
        ), self.workspace)
        self.assertTrue(repeated.success)
        self.assertEqual(repeated.changed_files, [])
        self.assertEqual(repeated.diff, "")
        self.assertEqual(self.manifest.read_text().splitlines().count("stripe"), 1)

    def test_duplicate_dependency_not_added(self):
        self.manifest.write_text("Stripe[async]>=10; python_version >= '3.10' # existing\n")
        before = self.manifest.read_bytes()
        result = self.service.apply_patch(self.diagnosis(), self.workspace)
        self.assertTrue(result.success)
        self.assertEqual(result.changed_files, [])
        self.assertEqual(result.diff, "")
        self.assertEqual(self.manifest.read_bytes(), before)

    def test_unsafe_or_ambiguous_diagnosis_rejected(self):
        before = self.manifest.read_bytes()
        for diagnosis in (
            self.diagnosis(safe_to_autofix=False),
            self.diagnosis(error_type="unknown"),
            self.diagnosis(proposed_fix="Install whatever is missing"),
            self.diagnosis(proposed_fix="Install requests"),
            self.diagnosis(proposed_fix="Do not add stripe to requirements.txt"),
            self.diagnosis(root_cause="The environment cannot import requests", proposed_fix="Install stripe"),
            self.diagnosis(proposed_fix="Add stripe to requirements.txt and add requests to requirements.txt"),
        ):
            with self.subTest(diagnosis=diagnosis):
                result = self.service.apply_patch(diagnosis, self.workspace)
                self.assertFalse(result.success)
                self.assertEqual(result.changed_files, [])
                self.assertEqual(self.manifest.read_bytes(), before)

    def test_traversal_and_protected_paths_rejected(self):
        before = self.manifest.read_bytes()
        for name in ("../outside.txt", "app/../../outside.txt", "/etc/passwd", "..\\outside", ".git/config", ".env", "secrets/token", ".github/workflows/ci.yml"):
            with self.subTest(path=name):
                result = self.service.apply_patch(self.diagnosis(affected_files=[name]), self.workspace)
                self.assertFalse(result.success)
                self.assertEqual(self.manifest.read_bytes(), before)

    def test_symlink_and_hardlink_targets_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "requirements.txt"
            target.write_text("outside content\n")
            self.manifest.unlink()
            self.manifest.symlink_to(target)
            self.assertFalse(self.service.apply_patch(self.diagnosis(), self.workspace).success)
            self.manifest.unlink()
            os.link(target, self.manifest)
            self.assertFalse(self.service.apply_patch(self.diagnosis(), self.workspace).success)
            self.assertEqual(target.read_text(), "outside content\n")

    def test_git_failure_restores_original_file(self):
        original_git = self.service._git
        before = self.manifest.read_bytes()
        def fail_diff(root, *args):
            if args[0] == "diff":
                raise subprocess.CalledProcessError(1, ["git", "diff"])
            return original_git(root, *args)
        with patch.object(self.service, "_git", side_effect=fail_diff):
            result = self.service.apply_patch(self.diagnosis(), self.workspace)
        self.assertFalse(result.success)
        self.assertEqual(self.manifest.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
