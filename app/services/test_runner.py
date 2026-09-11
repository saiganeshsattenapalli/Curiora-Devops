import math
import os
import selectors
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from app.services.github_service import WorkspaceMetadata


@dataclass(frozen=True)
class TestResult:
    passed: bool
    command: list[str]
    return_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    reason: str


class TestRunner:
    """Blocking POSIX runner for trusted repository tests, not an OS sandbox.

    Uses the current Python environment without installing dependencies. Project
    pytest config and auto-loaded plugins are disabled for deterministic discovery.
    """

    _SKIP = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache"}

    def __init__(self, timeout_seconds: float = 120, max_log_bytes: int = 64 * 1024) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0 or max_log_bytes <= 0:
            raise ValueError("Timeout and log limit must be positive")
        self.timeout_seconds = timeout_seconds
        self.max_log_bytes = max_log_bytes

    def run(self, workspace: WorkspaceMetadata) -> TestResult:
        command: list[str] = []
        started = time.monotonic()
        try:
            if os.name != "posix":
                raise ValueError("This runner requires POSIX process groups")
            root = self._validate_workspace(workspace)
            sources = self._python_files(root)
            tests = [p for p in sources if Path(p).name.startswith("test_") or p.endswith("_test.py")]
            if not sources and not any((root / p).is_file() for p in (
                "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt"
            )):
                raise ValueError("No supported Python project or tests found")

            with tempfile.TemporaryDirectory(prefix=".curio-test-", dir=root) as temporary:
                scratch = Path(temporary)
                (scratch / "tmp").mkdir()
                env = self._environment(scratch)
                if tests:
                    config = scratch / "pytest.ini"
                    config.write_text("[pytest]\n", encoding="utf-8")
                    command = [
                        sys.executable, "-I", "-B", "-u", "-m", "pytest",
                        "-c", str(config), "--rootdir=.", "--confcutdir=.",
                        "-o", "pythonpath=.", "--basetemp=" + str(scratch / "pytest"),
                        "-p", "no:cacheprovider", "--color=no", "--", *tests,
                    ]
                    strategy = "pytest"
                else:
                    command = [
                        sys.executable, "-I", "-u", "-X", "pycache_prefix=" + str(scratch / "bytecode"),
                        "-m", "compileall", "-q", "-l", *(sources or ["."]),
                    ]
                    strategy = "compileall (syntax check only; no tests detected)"
                code, stdout, stderr, timed_out = self._execute(command, root, env)
            return TestResult(
                code == 0 and not timed_out, command, code, stdout, stderr,
                round((time.monotonic() - started) * 1000),
                f"Timed out after {self.timeout_seconds:g}s" if timed_out else
                f"{strategy} {'passed' if code == 0 else 'failed'}",
            )
        except ValueError as exc:
            reason = str(exc)
        except (OSError, subprocess.SubprocessError):
            reason = "Workspace validation or process launch failed"
        return TestResult(False, command, None, "", "", round((time.monotonic() - started) * 1000), reason)

    @staticmethod
    def _validate_workspace(workspace: WorkspaceMetadata) -> Path:
        root = workspace.workspace_path.resolve(strict=True)
        incident = UUID(workspace.fix_branch.removeprefix("curio/fix-"))
        if (
            workspace.base_branch != "dev"
            or workspace.fix_branch != f"curio/fix-{incident}"
            or not root.is_relative_to(Path(tempfile.gettempdir()).resolve())
            or not root.name.startswith("curiora-")
            or workspace.workspace_path.is_symlink()
            or not (root / ".git").is_dir()
            or (root / ".git").is_symlink()
        ):
            raise ValueError("Expected a prepared temporary dev/fix workspace")
        env = TestRunner._environment(root)
        for args, expected in (
            (["rev-parse", "--show-toplevel"], str(root)),
            (["symbolic-ref", "--short", "HEAD"], workspace.fix_branch),
        ):
            result = subprocess.run(
                ["git", *args], cwd=root, env=env, capture_output=True, text=True,
                check=True, shell=False, timeout=5,
            )
            if result.stdout.strip() != expected:
                raise ValueError("Repository root or checked-out fix branch does not match metadata")
        return root

    @classmethod
    def _python_files(cls, root: Path) -> list[str]:
        sources = []
        for directory, directories, files in os.walk(root, followlinks=False):
            # Reject links instead of letting discovery or Python follow them.
            for name in directories + files:
                path = Path(directory) / name
                if path.is_symlink():
                    raise ValueError("Workspace contains a symlink")
                if path.is_file() and path.stat().st_nlink != 1:
                    raise ValueError("Workspace contains a hard-linked file")
            directories[:] = sorted(d for d in directories if d not in cls._SKIP and not d.startswith(".curio-test-"))
            sources.extend("./" + str((Path(directory) / name).relative_to(root)) for name in files if name.endswith(".py"))
        return sorted(sources)

    @staticmethod
    def _environment(scratch: Path) -> dict[str, str]:
        # An allowlist prevents tokens, PYTHONPATH, and PYTEST_ADDOPTS inheritance.
        return {
            "PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath,
            "HOME": str(scratch), "TMPDIR": str(scratch / "tmp"), "LC_ALL": "C",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0",
        }

    def _execute(self, command: list[str], root: Path, env: dict[str, str]) -> tuple[int, str, str, bool]:
        logs = {"stdout": bytearray(), "stderr": bytearray()}
        timed_out = False
        with subprocess.Popen(
            command, cwd=root, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
            start_new_session=True,
        ) as process:
            deadline = time.monotonic() + self.timeout_seconds
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
                    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
                    while selector.get_map():
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise subprocess.TimeoutExpired(command, self.timeout_seconds)
                        for key, _ in selector.select(min(remaining, 0.1)):
                            chunk = os.read(key.fd, 8192)
                            if not chunk:
                                selector.unregister(key.fileobj)
                            else:
                                buffer = logs[key.data]
                                buffer.extend(chunk[:max(0, self.max_log_bytes + 1 - len(buffer))])
                    process.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                timed_out = True
            finally:
                # Terminate descendants too, including children left after a pass.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
        def decode(data: bytearray) -> str:
            text = data[:self.max_log_bytes].decode("utf-8", errors="replace")
            return text + ("\n[output truncated]" if len(data) > self.max_log_bytes else "")
        return process.returncode, decode(logs["stdout"]), decode(logs["stderr"]), timed_out
