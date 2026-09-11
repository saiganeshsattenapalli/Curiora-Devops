import base64
import shutil
import subprocess
import unittest
from unittest.mock import patch
from uuid import UUID

from app.services.github_service import GitHubService, GitHubWorkspaceError


INCIDENT_ID = UUID("12345678-1234-5678-1234-567812345678")
RUN = "app.services.github_service.subprocess.run"


class GitHubServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = GitHubService()

    def prepare(self, **kwargs):
        return self.service.prepare_workspace(
            repository="curiora/example", incident_id=INCIDENT_ID, **kwargs
        )

    def test_rejects_every_non_dev_base_before_git_runs(self):
        with patch(RUN) as run:
            for branch in ("main", "master", "DEV", "dev; echo bad", "refs/heads/dev", ""):
                with self.subTest(branch=branch), self.assertRaises(ValueError):
                    self.prepare(base_branch=branch)
            run.assert_not_called()

    def test_rejects_repository_fragments_and_invalid_incident_ids(self):
        with patch(RUN) as run:
            for repository in ("https://github.com/owner/repo", "../repo", "owner/..",
                               "owner/repo;echo bad", "--upload-pack=x/repo", "owner/repo\n"):
                with self.subTest(repository=repository), self.assertRaises(ValueError):
                    self.service.prepare_workspace(repository=repository, incident_id=INCIDENT_ID)
            with self.assertRaises(ValueError):
                self.service.prepare_workspace(repository="owner/repo", incident_id="../main")
            run.assert_not_called()

    def test_fetches_only_dev_and_creates_local_fix_branch(self):
        with patch(RUN) as run:
            workspace = self.prepare()
        self.addCleanup(shutil.rmtree, workspace.workspace_path)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(workspace.base_branch, "dev")
        self.assertEqual(workspace.repository, "curiora/example")
        self.assertEqual(workspace.fix_branch, f"curio/fix-{INCIDENT_ID}")
        self.assertEqual(commands[2], [
            "git", "fetch", "--depth=1", "--no-tags", "--no-recurse-submodules",
            "origin", "refs/heads/dev:refs/remotes/origin/dev",
        ])
        self.assertEqual(commands[3], [
            "git", "checkout", "--no-track", "-B", "dev", "refs/remotes/origin/dev",
        ])
        self.assertEqual(commands[4], [
            "git", "checkout", "--no-track", "-b", workspace.fix_branch, "dev",
        ])
        for call in run.call_args_list:
            self.assertNotIn("push", call.args[0])
            self.assertNotIn("main", call.args[0])
            self.assertFalse(call.kwargs["shell"])
            self.assertTrue(call.kwargs["capture_output"])
            self.assertEqual(call.kwargs["cwd"], workspace.workspace_path)

    def test_missing_dev_aborts_and_removes_workspace(self):
        with patch(RUN) as run:
            run.side_effect = [None, None, subprocess.CalledProcessError(128, ["git", "fetch"])]
            with self.assertRaises(GitHubWorkspaceError):
                self.prepare()
            workspace = run.call_args_list[0].kwargs["cwd"]
            self.assertFalse(workspace.exists())
            self.assertEqual(run.call_count, 3)

    def test_environment_auth_does_not_enter_commands_or_metadata(self):
        token = "test-only-token"
        with patch.dict("os.environ", {"GITHUB_TOKEN": token, "GIT_DIR": "/unrelated", "GIT_TRACE": "1"}), patch(RUN) as run:
            workspace = self.prepare()
        self.addCleanup(shutil.rmtree, workspace.workspace_path)
        env = run.call_args.kwargs["env"]
        self.assertNotIn("GIT_DIR", env)
        self.assertNotIn("GIT_TRACE", env)
        self.assertNotIn("GITHUB_TOKEN", env)
        header = "Authorization: Basic " + base64.b64encode(f"x-access-token:{token}".encode()).decode()
        self.assertIn(header, env.values())
        self.assertNotIn(token, str(workspace))
        for call in run.call_args_list:
            self.assertNotIn(token, str(call.args))
            self.assertNotIn(header, str(call.args))

    def test_each_call_uses_an_isolated_workspace(self):
        with patch(RUN):
            first, second = self.prepare(), self.prepare()
        self.addCleanup(shutil.rmtree, first.workspace_path)
        self.addCleanup(shutil.rmtree, second.workspace_path)
        self.assertNotEqual(first.workspace_path, second.workspace_path)


if __name__ == "__main__":
    unittest.main()
