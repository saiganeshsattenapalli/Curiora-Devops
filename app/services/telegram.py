"""Fire-and-forget Telegram notifications for the remediation pipeline.

Every public method swallows all exceptions so that Telegram outages,
misconfiguration, or network errors never break the pipeline.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from uuid import UUID

    from app.models.schemas import Diagnosis
    from app.services.github_service import PullRequestMetadata
    from app.services.patch_service import PatchResult
    from app.services.reviewer import ReviewResult
    from app.services.test_runner import TestResult

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(connect=10, read=10, write=10, pool=10)


class TelegramNotifier:
    """Synchronous Telegram notifier; safe to call from ``run_stages`` threads.

    Reads ``TELEGRAM_BOT_TOKEN`` and ``TELEGRAM_CHAT_ID`` from the environment
    at construction time.  When either is missing the notifier becomes a silent
    no-op.  All public ``notify_*`` methods catch every exception internally.
    """

    def __init__(self) -> None:
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        if token and chat_id:
            self._url = f"https://api.telegram.org/bot{token}/sendMessage"
            self._chat_id = chat_id
            self.enabled = True
        else:
            self._url = ""
            self._chat_id = ""
            self.enabled = False

    # ------------------------------------------------------------------
    # Low-level sender
    # ------------------------------------------------------------------

    def _send(self, text: str) -> None:
        """POST a message to the Telegram Bot API.  Never raises."""
        if not self.enabled:
            return
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                client.post(
                    self._url,
                    json={
                        "chat_id": self._chat_id,
                        "text": text,
                        "parse_mode": "HTML",
                    },
                )
        except Exception:
            logger.debug("Telegram notification failed", exc_info=True)

    # ------------------------------------------------------------------
    # Stage helpers — each wraps _send so failures never propagate
    # ------------------------------------------------------------------

    def notify_incident_detected(
        self, incident_id: UUID, repository: str, source: str,
    ) -> None:
        try:
            self._send(
                f"🚨 <b>Incident Detected</b>\n"
                f"ID: <code>{incident_id}</code>\n"
                f"Repo: <code>{repository}</code>\n"
                f"Source: {_esc(source)}"
            )
        except Exception:
            pass

    def notify_diagnosis_completed(
        self, incident_id: UUID, diagnosis: Diagnosis,
    ) -> None:
        try:
            self._send(
                f"🔍 <b>Diagnosis Completed</b>\n"
                f"ID: <code>{incident_id}</code>\n"
                f"Error: <code>{_esc(diagnosis.error_type)}</code>\n"
                f"Root cause: {_esc(diagnosis.root_cause)}\n"
                f"Confidence: {diagnosis.confidence:.0%}\n"
                f"Safe to autofix: {diagnosis.safe_to_autofix}"
            )
        except Exception:
            pass

    def notify_autofix_started(
        self, incident_id: UUID, repository: str,
    ) -> None:
        try:
            self._send(
                f"🔧 <b>Autofix Started</b>\n"
                f"ID: <code>{incident_id}</code>\n"
                f"Repo: <code>{repository}</code>"
            )
        except Exception:
            pass

    def notify_patch_validated(
        self, incident_id: UUID, patch: PatchResult,
    ) -> None:
        try:
            files = ", ".join(patch.changed_files) or "none"
            self._send(
                f"✅ <b>Patch Validated</b>\n"
                f"ID: <code>{incident_id}</code>\n"
                f"Changed: <code>{_esc(files)}</code>\n"
                f"Result: {_esc(patch.reason)}"
            )
        except Exception:
            pass

    def notify_review_result(
        self, incident_id: UUID, review: ReviewResult,
    ) -> None:
        try:
            status = "✅ Approved" if review.approved else "❌ Rejected"
            self._send(
                f"📋 <b>Automated Review {status}</b>\n"
                f"ID: <code>{incident_id}</code>\n"
                f"Risk: {review.risk}\n"
                f"Summary: {_esc(review.summary)}"
            )
        except Exception:
            pass

    def notify_pr_created(
        self, incident_id: UUID, pr: PullRequestMetadata,
    ) -> None:
        try:
            self._send(
                f"🔀 <b>Pull Request Created</b>\n"
                f"ID: <code>{incident_id}</code>\n"
                f"PR #{pr.pr_number}: {_esc(pr.pr_title)}\n"
                f"URL: {pr.pr_url}\n"
                f"Branch: <code>{pr.pushed_branch}</code> → <code>{pr.base_branch}</code>"
            )
        except Exception:
            pass

    def notify_final_success(
        self,
        incident_id: UUID,
        repository: str,
        diagnosis: Diagnosis,
        patch: PatchResult,
        tests: TestResult,
        review: ReviewResult,
        pr: PullRequestMetadata,
    ) -> None:
        try:
            files = ", ".join(patch.changed_files) or "none"
            self._send(
                f"🎉 <b>Remediation Complete</b>\n\n"
                f"<b>Repository:</b> <code>{_esc(repository)}</code>\n"
                f"<b>Root cause:</b> {_esc(diagnosis.root_cause)}\n"
                f"<b>Changed files:</b> <code>{_esc(files)}</code>\n"
                f"<b>Validation:</b> {_esc(tests.reason)} (exit {tests.return_code})\n"
                f"<b>Review:</b> {'Approved' if review.approved else 'Rejected'}"
                f" ({review.risk} risk) — {_esc(review.summary)}\n"
                f"<b>PR:</b> #{pr.pr_number} — {pr.pr_url}\n"
                f"<b>Merge:</b> <code>{pr.pushed_branch}</code> → <code>{pr.base_branch}</code>"
            )
        except Exception:
            pass


def _esc(text: str) -> str:
    """Minimal HTML escaping for Telegram's HTML parse mode."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
