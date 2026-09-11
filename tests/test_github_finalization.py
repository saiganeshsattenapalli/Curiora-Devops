import os
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx

from app.models.schemas import Diagnosis
from app.services.github_service import GitHubFinalizationError, GitHubService, WorkspaceMetadata
from app.services.patch_service import PatchService
from app.services.reviewer import Reviewer
from app.services.test_runner import TestResult as ExecutionResult


REAL_RUN = subprocess.run
RUN = "app.services.github_service.subprocess.run"
POST = "app.services.github_service.httpx.post"


class GitHubFinalizationTests(unittest.TestCase):
    def setUp(self):
        incident = uuid4()
        directory = tempfile.TemporaryDirectory(prefix=f"curiora-{incident}-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.workspace = WorkspaceMetadata("owner/repo", "dev", f"curio/fix-{incident}", self.root)
        self.service = GitHubService()
        self.git("init", "--template=", "--initial-branch=" + self.workspace.fix_branch)
        self.git("remote", "add", "origin", "https://github.com/owner/repo.git")
        (self.root / "requirements.txt").write_text("fastapi>=0.100\n")
        self.git("add", "requirements.txt")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "fixture")
        self.base = self.git("rev-parse", "HEAD").strip()
        self.git("update-ref", "refs/remotes/origin/dev", self.base)
        self.diagnosis = Diagnosis(
            error_type="missing_dependency", root_cause="ModuleNotFoundError: No module named 'stripe'",
            affected_files=["requirements.txt"], proposed_fix="Add stripe to requirements.txt",
            confidence=0.99, safe_to_autofix=True,
        )
        self.patch = PatchService().apply_patch(self.diagnosis, self.workspace)
        self.tests = ExecutionResult(True, ["python", "-m", "pytest"], 0, "1 passed", "", 10, "pytest passed")
        self.review = Reviewer().review(self.diagnosis, self.patch, self.tests)
        self.assertTrue(self.review.approved)
        self.calls = []

    def git(self, *args):
        return REAL_RUN(
            ["git", *args], cwd=self.root, env=self.service._git_environment(),
            capture_output=True, text=True, check=True,
        ).stdout

    def intercept_git(self, args, **kwargs):
        self.calls.append(args)
        self.assertIsInstance(args, list)
        self.assertFalse(kwargs["shell"])
        if args[1] == "push":
            return subprocess.CompletedProcess(args, 0, "mock push succeeded", "")
        return REAL_RUN(args, **kwargs)

    def create_pr(self, url, **kwargs):
        data = kwargs["json"]
        self.assertEqual(url, "https://api.github.com/repos/owner/repo/pulls")
        self.assertEqual(data["base"], "dev")
        self.assertEqual(data["head"], self.workspace.fix_branch)
        return httpx.Response(201, request=httpx.Request("POST", url), json={
            "number": 7, "html_url": "https://github.com/owner/repo/pull/7", "title": data["title"],
            "base": {"ref": "dev"},
            "head": {"ref": data["head"], "sha": self.git("rev-parse", "HEAD").strip()},
        })

    def finalize(self, **overrides):
        values = dict(workspace=self.workspace, diagnosis=self.diagnosis, patch=self.patch,
                      tests=self.tests, review=self.review)
        return self.service.finalize(**(values | overrides))

    def test_approved_review_commits_pushes_only_fix_and_creates_dev_pr(self):
        with patch.dict(os.environ, {"GITHUB_TOKEN": "test-only-token"}), patch(RUN, side_effect=self.intercept_git), patch(POST, side_effect=self.create_pr) as post:
            result = self.finalize()
        self.assertEqual(result.base_branch, "dev")
        self.assertEqual(result.pushed_branch, self.workspace.fix_branch)
        self.assertEqual(result.pr_number, 7)
        self.assertEqual(result.commit_sha, self.git("rev-parse", "HEAD").strip())
        self.assertEqual(self.git("rev-parse", "HEAD^").strip(), self.base)
        self.assertEqual(self.git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").strip(), "requirements.txt")
        self.assertTrue(result.pr_title.startswith("[CURIO] Fix incident " + self.workspace.fix_branch[10:] + ": "))
        pushes = [args for args in self.calls if args[1] == "push"]
        self.assertEqual(len(pushes), 1)
        self.assertEqual(pushes[0][-1], f"refs/heads/{self.workspace.fix_branch}:refs/heads/{self.workspace.fix_branch}")
        self.assertNotIn("--force", pushes[0])
        body = post.call_args.kwargs["json"]["body"]
        for text in (self.diagnosis.root_cause, "requirements.txt", "pytest passed", self.review.summary, "CURIO generated and validated"):
            self.assertIn(text, body)
        self.assertNotIn("test-only-token", (self.root / ".git/config").read_text())
        self.assertNotIn("Authorization", (self.root / ".git/config").read_text())
        self.assertNotIn("test-only-token", str(self.calls))

    def assert_refused(self, **overrides):
        with patch.dict(os.environ, {"GITHUB_TOKEN": "test-only-token"}), patch(RUN, side_effect=self.intercept_git), patch(POST) as post:
            with self.assertRaises(GitHubFinalizationError):
                self.finalize(**overrides)
            post.assert_not_called()
        self.assertFalse(any(args[1] in {"push", "add", "commit"} for args in self.calls))
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.base)

    def test_rejected_review_does_not_push_or_create_pr(self):
        self.assert_refused(review=replace(self.review, approved=False))

    def test_real_push_refspec_updates_only_the_fix_branch(self):
        with tempfile.TemporaryDirectory(prefix="curiora-remote-test-") as directory:
            bare = Path(directory) / "remote.git"
            env = self.service._git_environment()
            REAL_RUN(
                ["git", "init", "--bare", "--template=", "--initial-branch=dev", str(bare)],
                env=env, check=True, capture_output=True,
            )
            self.git("config", "push.followTags", "true")
            self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "tag", "-a", "extra-tag", "-m", "fixture")
            def local_push(args, **kwargs):
                if args[1] == "push":
                    args = ["git", "-c", "protocol.file.allow=always", *args[1:]]
                    args[args.index("https://github.com/owner/repo.git")] = str(bare)
                    return REAL_RUN(args, **kwargs)
                return self.intercept_git(args, **kwargs)
            with patch.dict(os.environ, {"GITHUB_TOKEN": "test-only-token"}), patch(RUN, side_effect=local_push), patch(POST, side_effect=self.create_pr):
                self.finalize()
            refs = REAL_RUN(
                ["git", "--git-dir=" + str(bare), "for-each-ref", "--format=%(refname)"],
                env=env, text=True, capture_output=True, check=True,
            ).stdout.splitlines()
            self.assertEqual(refs, ["refs/heads/" + self.workspace.fix_branch])

    def test_wrong_current_branch_rejects(self):
        self.git("checkout", "-b", "other-fix")
        self.assert_refused()

    def test_non_dev_base_rejects(self):
        self.assert_refused(workspace=replace(self.workspace, base_branch="main"))

    def test_absent_token_fails_before_git_or_http(self):
        with patch.dict(os.environ, {"GITHUB_TOKEN": "", "GH_TOKEN": ""}), patch(RUN) as run, patch(POST) as post:
            with self.assertRaises(GitHubFinalizationError):
                self.finalize()
            run.assert_not_called()
            post.assert_not_called()

    def test_no_tracked_changes_rejects(self):
        self.git("restore", "requirements.txt")
        self.assert_refused()

    def test_changes_after_review_reject(self):
        (self.root / "requirements.txt").write_text("fastapi>=0.100\nstripe\nrequests\n")
        self.assert_refused()

    def test_api_failure_preserves_commit_and_push_metadata_without_retry(self):
        with patch.dict(os.environ, {"GITHUB_TOKEN": "", "GH_TOKEN": "fallback-test-token"}), patch(RUN, side_effect=self.intercept_git), patch(POST, side_effect=httpx.ReadTimeout("timeout")) as post:
            with self.assertRaises(GitHubFinalizationError) as caught:
                self.finalize()
            post.assert_called_once()
        self.assertEqual(caught.exception.commit_sha, self.git("rev-parse", "HEAD").strip())
        self.assertEqual(caught.exception.pushed_branch, self.workspace.fix_branch)
        self.assertIn("PR creation", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
