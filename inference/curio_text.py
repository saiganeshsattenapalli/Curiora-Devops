import re

from app.models.model_requests import TextDiagnosisRequest
from app.models.schemas import Diagnosis


class CurioTextProvider:
    """Deterministic mock; performs no inference or repository changes."""

    async def diagnose(self, request: TextDiagnosisRequest) -> Diagnosis:
        if re.search(
            r"ModuleNotFoundError: No module named (['\"])stripe\1",
            request.logs,
        ):
            return Diagnosis(
                error_type="missing_dependency",
                root_cause="The Python environment cannot import the stripe package.",
                affected_files=[],
                proposed_fix=(
                    "Add stripe to the project's dependency manifest and install "
                    "the dependencies in the environment running the application."
                ),
                confidence=0.99,
                safe_to_autofix=True,
            )

        return Diagnosis(
            error_type="unknown",
            root_cause="The mock provider does not recognize an error in these logs.",
            affected_files=[],
            proposed_fix="Review the logs and dependency configuration manually.",
            confidence=0.0,
            safe_to_autofix=False,
        )
