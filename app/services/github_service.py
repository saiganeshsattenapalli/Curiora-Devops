from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from uuid import UUID

import httpx

if TYPE_CHECKING:
    from app.models.schemas import Diagnosis
    from app.services.patch_service import PatchResult
    from app.services.reviewer import ReviewResult
    from app.services.test_runner import TestResult


@dataclass(frozen=True)
class WorkspaceMetadata:
    repository: str
    base_branch: Literal["dev"]
    fix_branch: str
    workspace_path: Path


class GitHubWorkspaceError(RuntimeError):
    """Preparation failed; raw git output is intentionally not exposed."""


@dataclass(frozen=True)
class PullRequestMetadata:
    commit_sha: str
    pushed_branch: str
    pr_number: int
    pr_url: str
    pr_title: str
    base_branch: Literal["dev"]


class GitHubFinalizationError(RuntimeError):
    def __init__(
        self, message: str, *, commit_sha: str | None = None, pushed_branch: str | None = None
    ) -> None:
        super().__init__(message)
        self.commit_sha = commit_sha
        self.pushed_branch = pushed_branch


class GitHubService:
    """Prepare dev-based workspaces and finalize approved fixes as dev-targeted PRs.

    Authentication: GITHUB_TOKEN, falling back to GH_TOKEN. Public repositories
    can be fetched without a token. Successful workspaces belong to the caller,
    which must remove workspace_path when finished. Failed workspaces are removed.
    This is a blocking service; async callers can use asyncio.to_thread.
    """

    def prepare_workspace(
        self, *, repository: str, incident_id: UUID | str, base_branch: str = "dev"
    ) -> WorkspaceMetadata:
        if base_branch != "dev":
            raise ValueError("Only dev is permitted as the base/target branch")
        self._validate_repository(repository)
        incident = UUID(str(incident_id))
        fix_branch = f"curio/fix-{incident}"
        env = self._git_environment()
        workspace = Path(tempfile.mkdtemp(prefix=f"curiora-{incident}-"))
        try:
            # An explicit initial branch and refspec avoid even checking out a
            # remote default branch. Missing dev is an error, never a fallback.
            commands = [
                ["init", "--initial-branch=dev", "--template="],
                ["remote", "add", "-t", "dev", "origin", f"https://github.com/{repository}.git"],
                [
                    "fetch", "--depth=1", "--no-tags", "--no-recurse-submodules",
                    "origin", "refs/heads/dev:refs/remotes/origin/dev",
                ],
                ["checkout", "--no-track", "-B", "dev", "refs/remotes/origin/dev"],
                ["checkout", "--no-track", "-b", fix_branch, "dev"],
            ]
            for args in commands:
                self._run(args, workspace, env)
        except BaseException:
            shutil.rmtree(workspace)
            raise
        return WorkspaceMetadata(repository, "dev", fix_branch, workspace)

    def finalize(
        self, *, workspace: WorkspaceMetadata, diagnosis: Diagnosis,
        patch: PatchResult, tests: TestResult, review: ReviewResult,
    ) -> PullRequestMetadata:
        # Local import avoids a cycle through the services using WorkspaceMetadata.
        from app.services.reviewer import Reviewer

        if not review.approved or review.risk != "low" or review.issues:
            raise GitHubFinalizationError("An approved low-risk review is required")
        if workspace.base_branch != "dev":
            raise GitHubFinalizationError("Only dev is permitted as the PR base branch")
        if not Reviewer().review(diagnosis, patch, tests).approved:
            raise GitHubFinalizationError("The supplied patch and tests do not pass deterministic review")
        token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
        if not token or not token.strip():
            raise GitHubFinalizationError("GITHUB_TOKEN or GH_TOKEN is required for finalization")

        commit_sha = None
        pushed_branch = None
        stage = "workspace validation"
        try:
            self._validate_repository(workspace.repository)
            incident = UUID(workspace.fix_branch.removeprefix("curio/fix-"))
            root = workspace.workspace_path.resolve(strict=True)
            if (
                workspace.fix_branch != f"curio/fix-{incident}"
                or not root.is_relative_to(Path(tempfile.gettempdir()).resolve())
                or not root.name.startswith("curiora-")
                or workspace.workspace_path.is_symlink()
                or not (root / ".git").is_dir() or (root / ".git").is_symlink()
                or (root / "requirements.txt").is_symlink()
            ):
                raise ValueError("Invalid prepared workspace")
            env = self._git_environment()
            url = f"https://github.com/{workspace.repository}.git"
            if Path(self._execute(["rev-parse", "--show-toplevel"], root, env).stdout.strip()).resolve() != root:
                raise ValueError("Wrong repository root")
            if self._execute(["symbolic-ref", "--short", "HEAD"], root, env).stdout.strip() != workspace.fix_branch:
                raise ValueError("Wrong current branch")
            if self._execute(["remote", "get-url", "origin"], root, env).stdout.strip() != url:
                raise ValueError("Origin does not match the approved repository")
            # The prepared fix branch must not contain additional, unreviewed commits.
            if self._execute(["rev-parse", "HEAD"], root, env).stdout != self._execute(
                ["rev-parse", "refs/remotes/origin/dev"], root, env
            ).stdout:
                raise ValueError("Fix branch already contains commits beyond its prepared dev base")
            changed = self._execute(
                ["diff", "--name-only", "-z", "HEAD", "--"], root, env
            ).stdout.strip("\0").split("\0")
            if changed != patch.changed_files:
                raise ValueError("No tracked changes, or changed files differ from the approved patch")
            staged = self._execute(
                ["diff", "--cached", "--name-only", "-z", "--"], root, env
            ).stdout.strip("\0")
            if staged and staged.split("\0") != patch.changed_files:
                raise ValueError("Unreviewed files are staged")
            diff_args = [
                "--no-ext-diff", "--no-textconv", "--no-color", "--no-renames",
                "--no-relative", "--diff-algorithm=myers", "--unified=3",
                "--src-prefix=a/", "--dst-prefix=b/", "HEAD", "--", "requirements.txt",
            ]
            if self._execute(["diff", *diff_args], root, env).stdout != patch.diff:
                raise ValueError("Workspace changed after patch review")

            summary = " ".join(diagnosis.root_cause.split())[:80] or "missing dependency"
            title = f"[CURIO] Fix incident {incident}: {summary}"
            body = (
                f"## Root cause\n{diagnosis.root_cause}\n\n"
                "## Changed files\n" + "\n".join(f"- {name}" for name in patch.changed_files)
                + f"\n\n## Test result\n{tests.reason}; exit code {tests.return_code}; "
                f"duration {tests.duration_ms} ms.\n\n"
                f"## Review result\nApproved ({review.risk} risk): {review.summary}\n\n"
                "CURIO generated and validated this fix. This PR targets dev."
            )
            stage = "staging"
            self._execute(["add", "--update", "--", "requirements.txt"], root, env)
            if self._execute(["diff", "--cached", *diff_args], root, env).stdout != patch.diff:
                raise ValueError("Staged changes differ from the approved patch")
            stage = "commit"
            self._execute([
                "-c", "user.name=CURIO", "-c", "user.email=curio@users.noreply.github.com",
                "-c", "commit.gpgsign=false", "commit", "-m", title,
            ], root, env)
            commit_sha = self._execute(["rev-parse", "HEAD"], root, env).stdout.strip()
            if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit_sha):
                raise ValueError("Invalid commit SHA")
            stage = "push"
            self._execute([
                "push", "--porcelain", "--no-force", "--no-follow-tags", "--no-mirror", "--",
                url, f"refs/heads/{workspace.fix_branch}:refs/heads/{workspace.fix_branch}",
            ], root, env)
            pushed_branch = workspace.fix_branch
            stage = "PR creation"
            response = httpx.post(
                f"https://api.github.com/repos/{workspace.repository}/pulls",
                headers={
                    "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2026-03-10",
                },
                json={"title": title, "head": workspace.fix_branch, "base": "dev", "body": body},
                timeout=30, follow_redirects=False, trust_env=False,
            )
            response.raise_for_status()
            data = response.json()
            number = data["number"]
            if (
                response.status_code != 201 or type(number) is not int or number <= 0
                or data["base"]["ref"] != "dev" or data["head"]["ref"] != workspace.fix_branch
                or data["head"]["sha"] != commit_sha or data["title"] != title
                or data["html_url"].lower() != f"https://github.com/{workspace.repository}/pull/{number}".lower()
            ):
                raise ValueError("Unexpected PR metadata")
            return PullRequestMetadata(commit_sha, pushed_branch, number, data["html_url"], title, "dev")
        except (ValueError, TypeError, KeyError, AttributeError, OSError, GitHubWorkspaceError, httpx.HTTPError):
            # No automatic retry: a timed-out push/POST may have succeeded remotely.
            raise GitHubFinalizationError(
                f"Finalization failed during {stage}; inspect the workspace and GitHub before retrying.",
                commit_sha=commit_sha, pushed_branch=pushed_branch,
            ) from None

    @staticmethod
    def _validate_repository(repository: str) -> None:
        # Only GitHub owner/name identifiers, not URLs, paths, or git options.
        match = re.fullmatch(
            r"([A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?)/([A-Za-z0-9_.-]{1,100})",
            repository,
        )
        if not match or "--" in match[1] or match[2] in {".", ".."}:
            raise ValueError("Repository must be a GitHub owner/name identifier")

    @staticmethod
    def _git_environment() -> dict[str, str]:
        # Ignore inherited repository locations, config injection, tracing, and
        # credential helpers. No token is written to the remote URL or git config.
        env = {
            key: value for key, value in os.environ.items()
            if not key.startswith("GIT_") and key not in {"GITHUB_TOKEN", "GH_TOKEN"}
        }
        env.update({
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
        })
        config = [("core.hooksPath", os.devnull), ("protocol.allow", "never"),
                  ("protocol.https.allow", "always")]
        token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
        if token:
            credential = base64.b64encode(f"x-access-token:{token}".encode()).decode()
            config.append(("http.https://github.com/.extraHeader", f"Authorization: Basic {credential}"))
        env["GIT_CONFIG_COUNT"] = str(len(config))
        for index, (key, value) in enumerate(config):
            env[f"GIT_CONFIG_KEY_{index}"] = key
            env[f"GIT_CONFIG_VALUE_{index}"] = value
        return env

    @staticmethod
    def _run(args: list[str], workspace: Path, env: dict[str, str]) -> None:
        GitHubService._execute(args, workspace, env)

    @staticmethod
    def _execute(
        args: list[str], workspace: Path, env: dict[str, str]
    ) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                ["git", *args], cwd=workspace, env=env, shell=False,
                capture_output=True, text=True, check=True, timeout=120,
            )
            return result
        except (subprocess.SubprocessError, OSError):
            raise GitHubWorkspaceError(
                f"Workspace preparation failed during git {args[0]}; "
                "check repository access and that the dev branch exists."
            ) from None
