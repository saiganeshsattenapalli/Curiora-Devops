import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from app.services.github_service import WorkspaceMetadata
from app.services.test_runner import TestRunner as Runner


class TestRunnerTests(unittest.TestCase):
    def setUp(self):
        incident = UUID("12345678-1234-5678-1234-567812345678")
        directory = tempfile.TemporaryDirectory(prefix=f"curiora-{incident}-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.workspace = WorkspaceMetadata("owner/repo", "dev", f"curio/fix-{incident}", self.root)
        subprocess.run(
            ["git", "init", "--template=", "--initial-branch=" + self.workspace.fix_branch],
            cwd=self.root, env=Runner._environment(self.root),
            capture_output=True, check=True,
        )
        self.runner = Runner()

    def test_successful_pytest_run(self):
        (self.root / "test_example.py").write_text("def test_ok(): assert True\n")
        with patch.dict(os.environ, {"GITHUB_TOKEN": "secret", "PYTEST_ADDOPTS": "--collect-only"}):
            # No pytest installation is needed to verify strategy/result handling.
            with patch.object(self.runner, "_execute", return_value=(0, "1 passed\n", "", False)) as execute:
                result = self.runner.run(self.workspace)
        self.assertTrue(result.passed, result.reason)
        self.assertEqual(result.return_code, 0)
        self.assertEqual(result.stdout, "1 passed\n")
        self.assertEqual(result.command[4:6], ["-m", "pytest"])
        self.assertIn("./test_example.py", result.command)
        self.assertEqual(execute.call_args.args[1], self.root)
        env = execute.call_args.args[2]
        self.assertNotIn("GITHUB_TOKEN", env)
        self.assertNotIn("PYTEST_ADDOPTS", env)
        self.assertTrue(Path(env["HOME"]).is_relative_to(self.root))
        self.assertEqual(env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"], "1")
        self.assertGreaterEqual(result.duration_ms, 0)

    def test_failing_pytest_run(self):
        (self.root / "test_example.py").write_text("def test_bad(): assert False\n")
        with patch.object(self.runner, "_execute", return_value=(1, "1 failed\n", "failure detail", False)):
            result = self.runner.run(self.workspace)
        self.assertFalse(result.passed)
        self.assertEqual(result.return_code, 1)
        self.assertEqual(result.stderr, "failure detail")
        self.assertEqual(result.reason, "pytest failed")

    def test_compileall_fallback_runs_without_executing_source(self):
        (self.root / "module.py").write_text("raise RuntimeError('must not execute')\n")
        result = self.runner.run(self.workspace)
        self.assertTrue(result.passed, result.stderr or result.reason)
        self.assertIn("compileall", result.command)
        self.assertEqual(result.return_code, 0)
        self.assertIn("syntax check only", result.reason)
        self.assertFalse(list(self.root.rglob("*.pyc")))
        self.assertFalse(list(self.root.glob(".curio-test-*")))

    def test_compileall_reports_syntax_errors(self):
        (self.root / "module.py").write_text("def broken(:\n")
        result = self.runner.run(self.workspace)
        self.assertFalse(result.passed)
        self.assertNotEqual(result.return_code, 0)
        self.assertIn("SyntaxError", result.stdout)

    def test_timeout_handling_preserves_partial_logs(self):
        (self.root / "module.py").write_text("value = 1\n")
        runner = Runner(timeout_seconds=0.3)
        original_execute = runner._execute
        def slow_process(command, root, env):
            return original_execute([
                sys.executable, "-I", "-u", "-c",
                "import time; print('started', flush=True); time.sleep(10)",
            ], root, env)
        with patch.object(runner, "_execute", side_effect=slow_process):
            result = runner.run(self.workspace)
        self.assertFalse(result.passed)
        self.assertLess(result.return_code, 0)
        self.assertIn("Timed out", result.reason)
        self.assertIn("started", result.stdout)
        self.assertGreaterEqual(result.duration_ms, 300)
        self.assertLess(result.duration_ms, 5000)
        self.assertFalse(list(self.root.glob(".curio-test-*")))

    def test_large_logs_are_bounded_and_decoded_safely(self):
        runner = Runner(max_log_bytes=16)
        code, stdout, stderr, timed_out = runner._execute([
            sys.executable, "-I", "-u", "-c",
            "import sys; sys.stdout.buffer.write(('€' * 100000).encode()); "
            "sys.stderr.buffer.write(b'x' * 100000)",
        ], self.root, Runner._environment(self.root))
        self.assertEqual(code, 0)
        self.assertFalse(timed_out)
        self.assertIn("[output truncated]", stdout)
        self.assertIn("[output truncated]", stderr)
        self.assertLess(len(stdout), 40)
        self.assertLess(len(stderr), 40)

    def test_workspace_isolation_rejects_wrong_paths_branches_and_links(self):
        (self.root / "module.py").write_text("value = 1\n")
        with tempfile.TemporaryDirectory() as outside:
            external = Path(outside) / "external.py"
            external.write_text("raise RuntimeError('outside')\n")
            with patch.object(self.runner, "_execute") as execute:
                for workspace in (
                    replace(self.workspace, workspace_path=Path(outside)),
                    replace(self.workspace, base_branch="main"),
                    replace(self.workspace, fix_branch="curio/fix-00000000-0000-0000-0000-000000000000"),
                ):
                    with self.subTest(workspace=workspace):
                        self.assertFalse(self.runner.run(workspace).passed)
                (self.root / "linked.py").symlink_to(external)
                self.assertFalse(self.runner.run(self.workspace).passed)
                execute.assert_not_called()
            self.assertEqual(external.read_text(), "raise RuntimeError('outside')\n")


if __name__ == "__main__":
    unittest.main()
