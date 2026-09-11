import base64
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID


@dataclass(frozen=True)
class WorkspaceMetadata:
    repository: str
    base_branch: Literal["dev"]
    fix_branch: str
    workspace_path: Path


class GitHubWorkspaceError(RuntimeError):
    """Preparation failed; raw git output is intentionally not exposed."""


class GitHubService:
    """Prepare local workspaces only; this service never pushes.

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
        try:
            subprocess.run(
                ["git", *args], cwd=workspace, env=env, shell=False,
                capture_output=True, text=True, check=True, timeout=120,
            )
        except (subprocess.SubprocessError, OSError):
            raise GitHubWorkspaceError(
                f"Workspace preparation failed during git {args[0]}; "
                "check repository access and that the dev branch exists."
            ) from None
