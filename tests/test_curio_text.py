import json
import unittest
from unittest.mock import AsyncMock, Mock

from app.models.model_requests import TextDiagnosisRequest
from app.models.schemas import Diagnosis
from app.services.patch_service import PatchService
from inference.curio_text import CurioTextProvider
from inference.model_gateway import ModelGateway


class CurioTextNormalizationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.diagnosis = Diagnosis(
            error_type="ModuleNotFoundError",
            root_cause="The application cannot import stripe because it is missing.",
            affected_files=["app.py"],
            proposed_fix="Check the environment before installing dependencies.",
            confidence=0.95,
            safe_to_autofix=False,
        )

    async def diagnose(self, logs, diagnosis=None):
        gateway = Mock(spec=ModelGateway)
        gateway.generate_text = AsyncMock(return_value=(diagnosis or self.diagnosis).model_dump_json())
        return await CurioTextProvider(gateway).diagnose(
            TextDiagnosisRequest(source="ci", repository="owner/repo", branch="dev", logs=logs)
        )

    async def test_exact_missing_module_with_high_confidence_is_normalized(self):
        for error_type in ("ModuleNotFoundError", "missing_dependency"):
            for confidence in (0.8, 0.95):
                with self.subTest(error_type=error_type, confidence=confidence):
                    original = self.diagnosis.model_copy(update={
                        "error_type": error_type, "confidence": confidence,
                        "proposed_fix": "pip install some_other_package",
                    })
                    result = await self.diagnose(
                        "Traceback (most recent call last):\n"
                        "  File 'app.py', line 1, in <module>\n"
                        "    import stripe\nModuleNotFoundError: No module named 'stripe'\n",
                        original,
                    )
                    self.assertEqual(result, original.model_copy(update={
                        "error_type": "missing_dependency", "affected_files": [],
                        "proposed_fix": "Add stripe to requirements.txt.", "safe_to_autofix": True,
                    }))
                    self.assertEqual(PatchService._package(result), "stripe")

    async def test_low_confidence_is_not_upgraded(self):
        original = self.diagnosis.model_copy(update={"confidence": 0.79})
        self.assertEqual(await self.diagnose("ModuleNotFoundError: No module named 'stripe'", original), original)

    async def test_malformed_or_non_simple_module_is_not_upgraded(self):
        for module in ("../stripe", "stripe;echo x", "stripe.api", "stripe-extra", "", "1stripe", "_stripe", "stripe_", "class"):
            with self.subTest(module=module):
                self.assertEqual(
                    await self.diagnose(f"ModuleNotFoundError: No module named '{module}'"), self.diagnosis
                )

    async def test_unrelated_or_ambiguous_errors_are_not_upgraded(self):
        exact = "ModuleNotFoundError: No module named 'stripe'"
        for logs in ("ValueError: invalid value", f"Example: {exact}", f"{exact} extra text",
                     f"{exact}\nModuleNotFoundError: No module named 'requests'", f"{exact}\n{exact}"):
            with self.subTest(logs=logs):
                self.assertEqual(await self.diagnose(logs), self.diagnosis)
        original = self.diagnosis.model_copy(update={"error_type": "unknown"})
        self.assertEqual(await self.diagnose(exact, original), original)

    async def test_invalid_model_output_is_not_normalized(self):
        gateway = Mock(spec=ModelGateway)
        gateway.generate_text = AsyncMock(return_value=json.dumps({"confidence": 0.99}))
        result = await CurioTextProvider(gateway).diagnose(TextDiagnosisRequest(
            source="ci", repository="owner/repo", branch="dev",
            logs="ModuleNotFoundError: No module named 'stripe'",
        ))
        self.assertFalse(result.safe_to_autofix)
        self.assertEqual(result.error_type, "unknown")


if __name__ == "__main__":
    unittest.main()
