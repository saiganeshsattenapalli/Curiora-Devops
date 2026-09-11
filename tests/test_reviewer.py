import unittest
from dataclasses import replace

from app.models.schemas import Diagnosis
from app.services.patch_service import PatchResult
from app.services.reviewer import Reviewer
from app.services.test_runner import TestResult as ExecutionResult


DIFF = """diff --git a/requirements.txt b/requirements.txt
index 1234567..abcdef0 100644
--- a/requirements.txt
+++ b/requirements.txt
@@ -1 +1,2 @@
 fastapi>=0.100
+stripe
"""


class ReviewerTests(unittest.TestCase):
    def setUp(self):
        self.diagnosis = Diagnosis(
            error_type="missing_dependency",
            root_cause="ModuleNotFoundError: No module named 'stripe'",
            affected_files=["requirements.txt"],
            proposed_fix="Add stripe to requirements.txt",
            confidence=0.99,
            safe_to_autofix=True,
        )
        self.patch = PatchResult(True, ["requirements.txt"], DIFF, "Added stripe")
        self.tests = ExecutionResult(True, ["python", "-m", "pytest"], 0, "1 passed", "", 20, "pytest passed")
        self.reviewer = Reviewer()

    def test_tests_failed_rejects_immediately(self):
        result = self.reviewer.review(self.diagnosis, self.patch, replace(self.tests, passed=False, return_code=1))
        self.assertFalse(result.approved)
        self.assertIn("Test validation", result.issues[0])

    def test_patch_failed_rejects(self):
        result = self.reviewer.review(self.diagnosis, replace(self.patch, success=False), self.tests)
        self.assertFalse(result.approved)

    def test_unsafe_diagnosis_rejects(self):
        result = self.reviewer.review(self.diagnosis.model_copy(update={"safe_to_autofix": False}), self.patch, self.tests)
        self.assertFalse(result.approved)

    def test_protected_file_change_rejects(self):
        for path in (".git/config", ".env", "secrets.json", ".github/workflows/ci.yml", "../requirements.txt"):
            with self.subTest(path=path):
                result = self.reviewer.review(self.diagnosis, replace(self.patch, changed_files=[path]), self.tests)
                self.assertFalse(result.approved)
                self.assertEqual(result.risk, "high")

    def test_valid_requirements_fix_approves_as_low_risk(self):
        result = self.reviewer.review(self.diagnosis, self.patch, self.tests)
        self.assertTrue(result.approved)
        self.assertEqual(result.risk, "low")
        self.assertEqual(result.issues, [])

    def test_no_files_changed_rejects(self):
        result = self.reviewer.review(self.diagnosis, replace(self.patch, changed_files=[], diff=""), self.tests)
        self.assertFalse(result.approved)

    def test_diff_must_match_metadata_and_one_minimal_addition(self):
        for diff in (
            "", "not a diff",
            DIFF.replace("requirements.txt", ".env"),
            DIFF + DIFF.replace("requirements.txt", ".env"),
            DIFF.replace("+stripe\n", "+requests\n"),
            DIFF.replace("+stripe\n", "+stripe\n+requests\n").replace("+1,2", "+1,3"),
            DIFF.replace(" fastapi>=0.100", "-fastapi>=0.100"),
            DIFF.replace("+1,2", "+1,99"),
            DIFF.replace(" 100644", " 120000"),
        ):
            with self.subTest(diff=diff):
                result = self.reviewer.review(self.diagnosis, replace(self.patch, diff=diff), self.tests)
                self.assertFalse(result.approved)

    def test_inconsistent_test_success_rejects(self):
        result = self.reviewer.review(self.diagnosis, self.patch, replace(self.tests, return_code=1))
        self.assertFalse(result.approved)


if __name__ == "__main__":
    unittest.main()
