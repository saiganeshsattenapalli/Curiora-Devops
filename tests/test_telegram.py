import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.services.github_service import PullRequestMetadata
from app.services.patch_service import PatchResult
from app.services.reviewer import ReviewResult
from app.services.telegram import TelegramNotifier, _esc
from app.services.test_runner import TestResult


def _diagnosis():
    from app.models.schemas import Diagnosis
    return Diagnosis(
        error_type="missing_dependency",
        root_cause="No module named 'stripe'",
        affected_files=["requirements.txt"],
        proposed_fix="Install stripe",
        confidence=0.95,
        safe_to_autofix=True,
    )


def _patch():
    return PatchResult(True, ["requirements.txt"], "+stripe\n", "Added missing dependency stripe")


def _tests():
    return TestResult(True, ["python", "-m", "pytest"], 0, "", "", 123, "pytest passed")


def _review():
    return ReviewResult(True, "low", [], "Approved one stripe dependency addition to requirements.txt; supplied validation passed.")


def _pr():
    return PullRequestMetadata(
        "a" * 40, "curio/fix-00000000-0000-0000-0000-000000000001", 42,
        "https://github.com/owner/repo/pull/42", "[CURIO] Fix incident: stripe missing", "dev",
    )


class TestTelegramDisabledWhenEnvMissing(unittest.TestCase):
    """Notifier must be a silent no-op when env vars are absent."""

    def test_disabled_without_token(self):
        with patch.dict("os.environ", {"TELEGRAM_CHAT_ID": "123"}, clear=True):
            notifier = TelegramNotifier()
        self.assertFalse(notifier.enabled)

    def test_disabled_without_chat_id(self):
        with patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "tok"}, clear=True):
            notifier = TelegramNotifier()
        self.assertFalse(notifier.enabled)

    def test_disabled_with_empty_values(self):
        with patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": " ", "TELEGRAM_CHAT_ID": ""}, clear=True):
            notifier = TelegramNotifier()
        self.assertFalse(notifier.enabled)

    def test_enabled_with_both_set(self):
        with patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "123"}, clear=True):
            notifier = TelegramNotifier()
        self.assertTrue(notifier.enabled)
        self.assertIn("tok", notifier._url)
        self.assertEqual(notifier._chat_id, "123")


class TestTelegramSend(unittest.TestCase):
    """Verify HTTP payload and error resilience."""

    def _notifier(self):
        with patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "test-token", "TELEGRAM_CHAT_ID": "42"}, clear=True):
            return TelegramNotifier()

    @patch("app.services.telegram.httpx.Client")
    def test_send_posts_correct_payload(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        notifier = self._notifier()
        notifier._send("hello <b>world</b>")
        mock_client.post.assert_called_once()
        args, kwargs = mock_client.post.call_args
        self.assertIn("test-token", args[0])
        self.assertEqual(kwargs["json"]["chat_id"], "42")
        self.assertEqual(kwargs["json"]["text"], "hello <b>world</b>")
        self.assertEqual(kwargs["json"]["parse_mode"], "HTML")

    @patch("app.services.telegram.httpx.Client")
    def test_send_swallows_network_errors(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.post.side_effect = Exception("connection refused")
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        notifier = self._notifier()
        # Must not raise
        notifier._send("test message")

    def test_send_noop_when_disabled(self):
        with patch.dict("os.environ", {}, clear=True):
            notifier = TelegramNotifier()
        with patch("app.services.telegram.httpx.Client") as mock_client_cls:
            notifier._send("test")
            mock_client_cls.assert_not_called()


class TestStageHelpers(unittest.TestCase):
    """Each helper must produce a non-empty message and never raise."""

    def setUp(self):
        with patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "1"}, clear=True):
            self.notifier = TelegramNotifier()
        self.notifier._send = MagicMock()
        self.incident_id = uuid4()

    def test_notify_incident_detected(self):
        self.notifier.notify_incident_detected(self.incident_id, "owner/repo", "ci")
        self.notifier._send.assert_called_once()
        msg = self.notifier._send.call_args[0][0]
        self.assertIn("Incident Detected", msg)
        self.assertIn("owner/repo", msg)

    def test_notify_diagnosis_completed(self):
        self.notifier.notify_diagnosis_completed(self.incident_id, _diagnosis())
        msg = self.notifier._send.call_args[0][0]
        self.assertIn("Diagnosis Completed", msg)
        self.assertIn("missing_dependency", msg)

    def test_notify_autofix_started(self):
        self.notifier.notify_autofix_started(self.incident_id, "owner/repo")
        msg = self.notifier._send.call_args[0][0]
        self.assertIn("Autofix Started", msg)

    def test_notify_patch_validated(self):
        self.notifier.notify_patch_validated(self.incident_id, _patch())
        msg = self.notifier._send.call_args[0][0]
        self.assertIn("Patch Validated", msg)
        self.assertIn("requirements.txt", msg)

    def test_notify_review_result_approved(self):
        self.notifier.notify_review_result(self.incident_id, _review())
        msg = self.notifier._send.call_args[0][0]
        self.assertIn("Approved", msg)
        self.assertIn("low", msg)

    def test_notify_review_result_rejected(self):
        rejected = ReviewResult(False, "high", ["bad patch"], "Rejected by deterministic safety checks.")
        self.notifier.notify_review_result(self.incident_id, rejected)
        msg = self.notifier._send.call_args[0][0]
        self.assertIn("Rejected", msg)

    def test_notify_pr_created(self):
        self.notifier.notify_pr_created(self.incident_id, _pr())
        msg = self.notifier._send.call_args[0][0]
        self.assertIn("Pull Request Created", msg)
        self.assertIn("#42", msg)
        self.assertIn("https://github.com/owner/repo/pull/42", msg)

    def test_notify_final_success_includes_all_fields(self):
        self.notifier.notify_final_success(
            self.incident_id, "owner/repo", _diagnosis(), _patch(), _tests(), _review(), _pr(),
        )
        msg = self.notifier._send.call_args[0][0]
        # All required fields per the spec
        self.assertIn("owner/repo", msg)                       # repository
        self.assertIn("No module named", msg)                  # root cause
        self.assertIn("requirements.txt", msg)                 # changed files
        self.assertIn("pytest passed", msg)                    # validation result
        self.assertIn("low", msg)                              # review risk
        self.assertIn("Approved", msg)                         # review status
        self.assertIn("#42", msg)                              # PR number
        self.assertIn("https://github.com/owner/repo/pull/42", msg)  # PR URL
        self.assertIn("curio/fix-", msg)                       # curio/fix-* → dev
        self.assertIn("dev", msg)                              # → dev


class TestHelperExceptionSafety(unittest.TestCase):
    """Every notify_* must swallow internal errors."""

    def test_all_helpers_swallow_exceptions(self):
        with patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "1"}, clear=True):
            notifier = TelegramNotifier()
        notifier._send = MagicMock(side_effect=RuntimeError("boom"))
        iid = uuid4()
        # None of these may raise
        notifier.notify_incident_detected(iid, "o/r", "ci")
        notifier.notify_diagnosis_completed(iid, _diagnosis())
        notifier.notify_autofix_started(iid, "o/r")
        notifier.notify_patch_validated(iid, _patch())
        notifier.notify_review_result(iid, _review())
        notifier.notify_pr_created(iid, _pr())
        notifier.notify_final_success(iid, "o/r", _diagnosis(), _patch(), _tests(), _review(), _pr())


class TestEscaping(unittest.TestCase):
    def test_html_entities(self):
        self.assertEqual(_esc("a<b>c&d"), "a&lt;b&gt;c&amp;d")

    def test_plain_text_unchanged(self):
        self.assertEqual(_esc("hello world"), "hello world")


if __name__ == "__main__":
    unittest.main()
