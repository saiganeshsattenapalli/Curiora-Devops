import re
from dataclasses import dataclass
from typing import Literal

from app.models.schemas import Diagnosis
from app.services.patch_service import PatchResult, PatchService
from app.services.test_runner import TestResult


@dataclass(frozen=True)
class ReviewResult:
    approved: bool
    risk: Literal["low", "high"]
    issues: list[str]
    summary: str


class Reviewer:
    """Authoritative deterministic gates; no model calls or repository writes."""

    def review(self, diagnosis: Diagnosis, patch: PatchResult, tests: TestResult) -> ReviewResult:
        if not tests.passed or tests.return_code != 0:
            return self._reject("Test validation did not pass successfully")
        if not patch.success:
            return self._reject("Patch application was unsuccessful")
        if not patch.changed_files:
            return self._reject("No files changed")
        # An exact allowlist also excludes secrets, .git, and traversal paths.
        if patch.changed_files != ["requirements.txt"]:
            return self._reject("Protected or unsupported files changed; only requirements.txt is allowed")
        if not diagnosis.safe_to_autofix:
            return self._reject("Diagnosis is not safe to autofix")
        if diagnosis.error_type not in {"missing_dependency", "ModuleNotFoundError"}:
            return self._reject("Diagnosis is not a supported missing dependency")
        try:
            # Share the patcher's package interpretation rather than guessing again.
            expected = PatchService._package(diagnosis)
            added = self._single_addition(patch.diff)
            if added != expected:
                return self._reject("Added dependency does not match the diagnosis")
        except ValueError:
            return self._reject("Ambiguous diagnosis or diff is not one minimal dependency addition")
        return ReviewResult(
            True, "low", [],
            f"Approved one {expected} dependency addition to requirements.txt; supplied validation passed.",
        )

    @staticmethod
    def _reject(issue: str) -> ReviewResult:
        return ReviewResult(False, "high", [issue], "Rejected by deterministic safety checks.")

    @staticmethod
    def _single_addition(diff: str) -> str:
        """Accept one regular-file Git diff, one complete hunk, and one added line.

        Renames, mode changes, binary diffs, removals, and additional file sections
        are rejected even if changed_files claims that only requirements.txt changed.
        """
        lines = diff.splitlines()
        if (
            len(lines) < 6
            or lines[0] != "diff --git a/requirements.txt b/requirements.txt"
            or not re.fullmatch(r"index [0-9a-f]{7,64}\.\.[0-9a-f]{7,64} 100(?:644|755)", lines[1])
            or lines[2:4] != ["--- a/requirements.txt", "+++ b/requirements.txt"]
        ):
            raise ValueError("Unexpected diff headers")
        hunk = re.fullmatch(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?", lines[4])
        if not hunk:
            raise ValueError("Expected a unified diff hunk")
        old_count = int(hunk[2]) if hunk[2] is not None else 1
        new_count = int(hunk[4]) if hunk[4] is not None else 1
        additions = []
        context_count = 0
        for line in lines[5:]:
            if line.startswith("+"):
                additions.append(line[1:])
            elif line.startswith(" "):
                context_count += 1
            else:
                raise ValueError("Unexpected deletion, extra hunk, or file section")
        if len(additions) != 1 or old_count != context_count or new_count != context_count + 1:
            raise ValueError("Diff counts do not describe exactly one addition")
        if int(hunk[3]) != max(1, int(hunk[1])):
            raise ValueError("Inconsistent hunk positions")
        return additions[0]
