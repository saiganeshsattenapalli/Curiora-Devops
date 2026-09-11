import json
from typing import Any

from inference.runtimes.base import GenerationRequest, RuntimeAdapter


class MockRuntime(RuntimeAdapter):
    """Development fixture: never approves automatic changes."""

    def _load(self, request: GenerationRequest) -> tuple[Any, Any, Any]:
        return None, None, None

    def _generate(self, request: GenerationRequest) -> str:
        return json.dumps({
            "error_type": "unknown",
            "root_cause": "Mock inference mode; no model diagnosis was performed.",
            "affected_files": [],
            "proposed_fix": "Review the incident manually.",
            "confidence": 0.0,
            "safe_to_autofix": False,
        })
