import asyncio
import shutil
from threading import Event
from uuid import uuid4

from app.models.model_requests import TextDiagnosisRequest
from app.models.remediation import RemediationResponse
from app.models.schemas import Diagnosis, IncidentRequest, IncidentResponse
from app.services.github_service import GitHubFinalizationError, GitHubService
from app.services.model_router import ModelRouter
from app.services.patch_service import PatchService
from app.services.reviewer import Reviewer
from app.services.test_runner import TestRunner


class Curio:
    def __init__(
        self, model_router: ModelRouter | None = None, *,
        github_service: GitHubService | None = None,
        patch_service: PatchService | None = None,
        test_runner: TestRunner | None = None,
        reviewer: Reviewer | None = None,
    ) -> None:
        self.model_router = model_router if model_router is not None else ModelRouter()
        self.github_service = github_service if github_service is not None else GitHubService()
        self.patch_service = patch_service if patch_service is not None else PatchService()
        self.test_runner = test_runner if test_runner is not None else TestRunner()
        self.reviewer = reviewer if reviewer is not None else Reviewer()

    async def diagnose_incident(self, incident: IncidentRequest) -> IncidentResponse:
        request = TextDiagnosisRequest(
            source=incident.source,
            repository=incident.repository,
            branch=incident.branch,
            logs=incident.logs,
        )
        diagnosis = await self.model_router.diagnose_text(request)
        return IncidentResponse(
            incident_id=uuid4(),
            **diagnosis.model_dump(),
        )

    async def remediate_incident(self, incident: IncidentRequest) -> RemediationResponse:
        result = RemediationResponse(incident_id=uuid4(), status="diagnosis_failed")
        if incident.branch != "dev":
            result.status = "rejected_branch"
            result.error = "Autonomous remediation only accepts incidents on dev."
            return result
        try:
            diagnosed = await self.diagnose_incident(incident)
        except Exception:
            result.error = "Diagnosis failed; no remediation was attempted."
            return result
        result.incident_id = diagnosed.incident_id
        diagnosis = Diagnosis.model_validate(diagnosed.model_dump())
        result.diagnosis = diagnosis
        if not diagnosis.safe_to_autofix:
            result.status = "unsafe"
            return result

        cancelled = Event()

        def run_stages() -> RemediationResponse:
            workspace = None

            def should_stop() -> bool:
                if cancelled.is_set():
                    result.status = "cancelled"
                    return True
                return False

            try:
                if should_stop():
                    return result
                result.status = "workspace_failed"
                workspace = self.github_service.prepare_workspace(
                    repository=incident.repository, incident_id=result.incident_id, base_branch="dev"
                )
                if should_stop():
                    return result
                result.status = "patch_failed"
                result.patch = self.patch_service.apply_patch(diagnosis, workspace)
                if not result.patch.success or should_stop():
                    return result
                result.status = "tests_failed"
                result.tests = self.test_runner.run(workspace)
                if not result.tests.passed or result.tests.return_code != 0 or should_stop():
                    return result
                result.status = "review_rejected"
                result.review = self.reviewer.review(diagnosis, result.patch, result.tests)
                if not result.review.approved or should_stop():
                    return result
                result.status = "finalization_failed"
                result.pull_request = self.github_service.finalize(
                    workspace=workspace, diagnosis=diagnosis, patch=result.patch,
                    tests=result.tests, review=result.review,
                )
                result.status = "completed"
            except GitHubFinalizationError as exc:
                result.error = str(exc)
                result.commit_sha = exc.commit_sha
                result.pushed_branch = exc.pushed_branch
            except Exception:
                # Preserve completed stage results without exposing raw logs/secrets.
                result.error = f"Remediation stopped at {result.status}."
            finally:
                if workspace is not None:
                    try:
                        shutil.rmtree(workspace.workspace_path)
                    except FileNotFoundError:
                        pass
                    except OSError:
                        result.status = "cleanup_failed"
                        result.cleanup_error = f"Could not remove temporary workspace {workspace.workspace_path}."
            return result

        try:
            # Cleanup remains in this worker even if the awaiting request is cancelled.
            return await asyncio.to_thread(run_stages)
        except asyncio.CancelledError:
            cancelled.set()
            raise
