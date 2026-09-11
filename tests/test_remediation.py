import asyncio
import importlib
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx

from app.models.schemas import Diagnosis, IncidentRequest
from app.services.curio import Curio
from app.services.github_service import (
    GitHubFinalizationError, GitHubService, GitHubWorkspaceError,
    PullRequestMetadata, WorkspaceMetadata,
)
from app.services.model_router import ModelRouter
from app.services.patch_service import PatchResult, PatchService
from app.services.reviewer import Reviewer, ReviewResult
from app.services.test_runner import TestResult as ExecutionResult, TestRunner as Runner


class RemediationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.incident = IncidentRequest(source="ci", repository="owner/repo", branch="dev", logs="stripe missing")

    def pipeline(self, stop=None):
        calls, workspaces = [], []
        router = Mock(spec=ModelRouter)
        github = Mock(spec=GitHubService)
        patcher = Mock(spec=PatchService)
        runner = Mock(spec=Runner)
        reviewer = Mock(spec=Reviewer)

        async def diagnose(request):
            calls.append("diagnose")
            if stop == "diagnosis_failed":
                raise RuntimeError("backend failed")
            return Diagnosis(
                error_type="missing_dependency", root_cause="stripe missing",
                affected_files=["requirements.txt"], proposed_fix="Install stripe",
                confidence=0.99, safe_to_autofix=stop != "unsafe",
            )

        def prepare(**kwargs):
            calls.append("prepare")
            self.assertEqual(kwargs["base_branch"], "dev")
            if stop == "workspace_failed":
                raise GitHubWorkspaceError("fetch failed")
            root = Path(tempfile.mkdtemp(prefix=f"curiora-{kwargs['incident_id']}-")).resolve()
            workspaces.append(root)
            self.addCleanup(shutil.rmtree, root, True)
            return WorkspaceMetadata("owner/repo", "dev", f"curio/fix-{kwargs['incident_id']}", root)

        def apply(diagnosis, workspace):
            calls.append("patch")
            if stop == "patch_exception":
                raise RuntimeError("unexpected patch failure")
            return PatchResult(stop != "patch_failed", ["requirements.txt"], "+stripe", "patch result")

        def run(workspace):
            calls.append("tests")
            return ExecutionResult(stop != "tests_failed", ["python", "-m", "pytest"],
                                   1 if stop == "tests_failed" else 0, "", "", 1, "test result")

        def review(diagnosis, patch_result, tests):
            calls.append("review")
            return ReviewResult(stop != "review_rejected", "low", [], "review result")

        def finalize(**kwargs):
            calls.append("finalize")
            self.assertTrue(kwargs["patch"].success)
            self.assertTrue(kwargs["tests"].passed)
            self.assertTrue(kwargs["review"].approved)
            if stop == "finalization_failed":
                raise GitHubFinalizationError("PR failed", commit_sha="a" * 40,
                                              pushed_branch=kwargs["workspace"].fix_branch)
            return PullRequestMetadata("a" * 40, kwargs["workspace"].fix_branch, 1,
                                       "https://github.com/owner/repo/pull/1", "Fix stripe", "dev")

        router.diagnose_text = AsyncMock(side_effect=diagnose)
        github.prepare_workspace.side_effect = prepare
        patcher.apply_patch.side_effect = apply
        runner.run.side_effect = run
        reviewer.review.side_effect = review
        github.finalize.side_effect = finalize
        curio = Curio(router, github_service=github, patch_service=patcher,
                      test_runner=runner, reviewer=reviewer)
        return curio, calls, workspaces

    async def test_service_order_short_circuiting_and_workspace_cleanup(self):
        stages = ["diagnose", "prepare", "patch", "tests", "review", "finalize"]
        cases = {
            None: ("completed", 6), "diagnosis_failed": ("diagnosis_failed", 1),
            "unsafe": ("unsafe", 1), "workspace_failed": ("workspace_failed", 2),
            "patch_failed": ("patch_failed", 3), "patch_exception": ("patch_failed", 3),
            "tests_failed": ("tests_failed", 4), "review_rejected": ("review_rejected", 5),
            "finalization_failed": ("finalization_failed", 6),
        }
        for stop, (status, count) in cases.items():
            with self.subTest(stop=stop):
                curio, calls, workspaces = self.pipeline(stop)
                result = await curio.remediate_incident(self.incident)
                self.assertEqual(calls, stages[:count])
                self.assertEqual(result.status, status)
                self.assertTrue(all(not path.exists() for path in workspaces))
                self.assertIsNone(result.cleanup_error)
                if count < 6:
                    curio.github_service.finalize.assert_not_called()
                if stop is None:
                    self.assertEqual(result.pull_request.base_branch, "dev")
                    self.assertEqual(result.pull_request.pushed_branch, f"curio/fix-{result.incident_id}")
                if stop == "finalization_failed":
                    self.assertEqual(result.commit_sha, "a" * 40)
                    self.assertEqual(result.pushed_branch, f"curio/fix-{result.incident_id}")
                if count < 4:
                    self.assertIsNone(result.tests)
                if count < 5:
                    self.assertIsNone(result.review)

    async def test_autofix_endpoint_and_existing_diagnosis_endpoint(self):
        curio, calls, workspaces = self.pipeline()
        module = importlib.import_module("app.routers.incidents")
        from app.main import app
        with patch.object(module, "curio", curio):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                payload = self.incident.model_dump()
                response = await client.post("/api/v1/incidents", json=payload | {"branch": "main"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["status"], "diagnosed")
                self.assertNotIn("pull_request", response.json())
                self.assertEqual(calls, ["diagnose"])
                calls.clear()
                response = await client.post("/api/v1/incidents/autofix", json=payload)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["status"], "completed")
                self.assertEqual(response.json()["pull_request"]["base_branch"], "dev")
                self.assertTrue(all(not path.exists() for path in workspaces))
                calls.clear()
                response = await client.post("/api/v1/incidents/autofix", json=payload | {"branch": "main"})
                self.assertEqual(response.json()["status"], "rejected_branch")
                self.assertEqual(calls, [])

    async def test_cancellation_finishes_current_stage_then_cleans_up(self):
        curio, calls, workspaces = self.pipeline()
        entered, release, cleaned = threading.Event(), threading.Event(), threading.Event()
        original_prepare = curio.github_service.prepare_workspace.side_effect
        original_cleanup = shutil.rmtree

        def blocked_prepare(**kwargs):
            workspace = original_prepare(**kwargs)
            entered.set()
            release.wait(timeout=5)
            return workspace

        def cleanup(path, *args, **kwargs):
            original_cleanup(path, *args, **kwargs)
            cleaned.set()

        curio.github_service.prepare_workspace.side_effect = blocked_prepare
        with patch("app.services.curio.shutil.rmtree", side_effect=cleanup):
            task = asyncio.create_task(curio.remediate_incident(self.incident))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            finally:
                release.set()
            self.assertTrue(await asyncio.to_thread(cleaned.wait, 2))
        self.assertEqual(calls, ["diagnose", "prepare"])
        self.assertTrue(all(not path.exists() for path in workspaces))


if __name__ == "__main__":
    unittest.main()
