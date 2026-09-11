import os
import re
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from uuid import UUID

from app.models.schemas import Diagnosis
from app.services.github_service import WorkspaceMetadata


@dataclass(frozen=True)
class PatchResult:
    success: bool
    changed_files: list[str]
    diff: str
    reason: str


_NAME = r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?"
_VERSION = r"(?:===|==|~=|!=|<=|>=|<|>)\s*[A-Za-z0-9.*+!_-]+"
_REQUIREMENT = re.compile(
    rf"({_NAME})(?:\[[A-Za-z0-9_., -]+\])?"
    rf"(?:\s*{_VERSION}(?:\s*,\s*{_VERSION})*)?"
    r"(?:\s*;\s*[^#\r\n]+)?\s*(?:#.*)?"
)


class PatchService:
    """Blocking, deterministic requirements.txt edits; no commands from the LLM."""

    def apply_patch(self, diagnosis: Diagnosis, workspace: WorkspaceMetadata) -> PatchResult:
        try:
            if not diagnosis.safe_to_autofix or diagnosis.error_type not in {
                "missing_dependency", "ModuleNotFoundError"
            }:
                raise ValueError("Diagnosis is unsafe or is not a supported missing dependency")
            package = self._package(diagnosis)
            root = workspace.workspace_path.resolve(strict=True)
            if (
                not root.is_relative_to(Path(tempfile.gettempdir()).resolve())
                or not root.name.startswith("curiora-")
                or workspace.workspace_path.is_symlink()
                or workspace.base_branch != "dev"
                or not workspace.fix_branch.startswith("curio/fix-")
            ):
                raise ValueError("Expected a prepared temporary dev/fix workspace")
            incident = UUID(workspace.fix_branch.removeprefix("curio/fix-"))
            if workspace.fix_branch != f"curio/fix-{incident}":
                raise ValueError("Invalid fix branch")
            for name in diagnosis.affected_files:
                self._safe_path(root, name)
            target = self._safe_path(root, "requirements.txt")
            if not (root / ".git").is_dir() or (root / ".git").is_symlink():
                raise ValueError("Expected an isolated repository, not a linked worktree")
            if Path(self._git(root, "rev-parse", "--show-toplevel").strip()).resolve() != root:
                raise ValueError("Repository root does not match workspace")
            if self._git(root, "symbolic-ref", "--short", "HEAD").strip() != workspace.fix_branch:
                raise ValueError("Workspace is not on its CURIO fix branch")
            self._git(root, "ls-files", "--error-unmatch", "--", "requirements.txt")

            # Do not follow a symlink or alter a hard-linked file outside this repo.
            with os.fdopen(os.open(target, os.O_RDWR | os.O_NOFOLLOW), "r+b") as handle:
                info = os.fstat(handle.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError("Requirements must be a regular, unlinked file")
                original = handle.read()
                text = original.decode("utf-8")
                if "\x00" in text or "\\" in text or "://" in text:
                    raise ValueError("Unsupported requirements syntax; manual review required")
                names = set()
                for line in text.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    match = _REQUIREMENT.fullmatch(line)
                    if not match:
                        raise ValueError("Only simple named requirements are supported")
                    names.add(self._normalize(match[1]))
                if self._normalize(package) in names:
                    return PatchResult(True, [], "", f"{package} is already declared; no change needed")
                if self._git(root, "status", "--porcelain=v1", "--untracked-files=all"):
                    raise ValueError("Workspace has existing changes; refusing to mix patches")

                newline = b"\r\n" if b"\r\n" in original else b"\n"
                addition = (b"" if not original or original.endswith(b"\n") else newline)
                addition += package.encode("ascii") + newline
                try:
                    handle.seek(0, os.SEEK_END)
                    handle.write(addition)
                    handle.flush()
                    diff = self._git(
                        root, "diff", "--no-ext-diff", "--no-textconv", "--no-color",
                        "--no-renames", "--no-relative", "--diff-algorithm=myers",
                        "--unified=3", "--src-prefix=a/", "--dst-prefix=b/",
                        "HEAD", "--", "requirements.txt",
                    )
                    if not diff:
                        raise ValueError("Git did not produce a patch")
                except BaseException:
                    handle.seek(0)
                    handle.write(original)
                    handle.truncate()
                    handle.flush()
                    raise
            return PatchResult(True, ["requirements.txt"], diff, f"Added missing dependency {package}")
        except UnicodeError:
            return PatchResult(False, [], "", "Requirements must be UTF-8 text")
        except ValueError as exc:
            return PatchResult(False, [], "", str(exc))
        except (OSError, subprocess.SubprocessError):
            # Avoid exposing repository contents, credentials, or raw git errors.
            return PatchResult(False, [], "", "Workspace file access or Git failed; no patch applied")

    @staticmethod
    def _package(diagnosis: Diagnosis) -> str:
        # Require an explicit distribution name, not a guessed import-to-package mapping.
        proposal = diagnosis.proposed_fix.strip()
        match = re.fullmatch(
            rf"Add\s+[`'\"]?({_NAME})[`'\"]?\s+to\s+"
            r"(?:(?:the|your|project's)\s+)*(?:requirements\.txt|dependency manifest|dependencies)"
            r"(?: and install the dependencies in the environment running the application)?\.?",
            proposal, re.IGNORECASE,
        ) or re.fullmatch(rf"Install\s+[`'\"]?({_NAME})[`'\"]?\.?", proposal, re.IGNORECASE)
        if not match:
            raise ValueError("Expected a single explicit package addition or installation")
        package = PatchService._normalize(match[1])
        modules = re.findall(r"No module named ['\"]([^'\"]+)['\"]", diagnosis.root_cause)
        modules += re.findall(
            rf"cannot import (?:the\s+)?[`'\"]?({_NAME})", diagnosis.root_cause, re.IGNORECASE
        )
        if any(PatchService._normalize(module) != package for module in modules):
            raise ValueError("Package proposal conflicts with the missing module")
        return package

    @staticmethod
    def _normalize(name: str) -> str:
        return re.sub(r"[-_.]+", "-", name).lower()

    @staticmethod
    def _safe_path(root: Path, name: str) -> Path:
        path = PurePosixPath(name)
        if not name or path.is_absolute() or "\\" in name or ":" in name or ".." in path.parts:
            raise ValueError("Unsafe repository path")
        current = root
        for part in path.parts:
            lower = part.lower()
            if (
                lower.startswith((".git", ".env"))
                or "secret" in lower or "credential" in lower
                or lower in {".ssh", ".aws", ".netrc", ".npmrc", ".pypirc", "id_rsa", "id_ed25519"}
                or lower.endswith((".pem", ".key", ".p12"))
            ):
                raise ValueError("Protected path")
            current = current / part
            if current.is_symlink():
                raise ValueError("Symlink paths are not supported")
        resolved = current.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError("Path escapes workspace")
        return resolved

    @staticmethod
    def _git(root: Path, *args: str) -> str:
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update({
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C",
        })
        return subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=" + os.devnull, *args],
            cwd=root, env=env, capture_output=True, text=True, check=True, shell=False, timeout=30,
        ).stdout
