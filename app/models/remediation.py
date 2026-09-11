from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.models.schemas import Diagnosis
from app.services.github_service import PullRequestMetadata
from app.services.patch_service import PatchResult
from app.services.reviewer import ReviewResult
from app.services.test_runner import TestResult


class RemediationResponse(BaseModel):
    incident_id: UUID
    status: Literal[
        "rejected_branch", "diagnosis_failed", "unsafe", "workspace_failed",
        "patch_failed", "tests_failed", "review_rejected", "finalization_failed",
        "completed", "cancelled", "cleanup_failed",
    ]
    diagnosis: Diagnosis | None = None
    patch: PatchResult | None = None
    tests: TestResult | None = None
    review: ReviewResult | None = None
    pull_request: PullRequestMetadata | None = None
    error: str | None = None
    # Preserve known remote progress if finalization fails after committing/pushing.
    commit_sha: str | None = None
    pushed_branch: str | None = None
    cleanup_error: str | None = None
