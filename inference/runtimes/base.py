"""Compact adaptation of Campus's RuntimeAdapter and model-switch lifecycle."""

import gc
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class GenerationRequest:
    mode: Literal["text", "vision"]
    model_id: str
    messages: list[dict[str, str]]
    max_tokens: int = 1024
    temperature: float = 0.0
    response_prefix: str = ""
    image_path: str | None = None


class RuntimeAdapter(ABC):
    """The gateway serializes generation and release for this single model slot."""

    def __init__(self) -> None:
        self._resources: tuple[Any, Any, Any] | None = None
        self._key: tuple[str, str] | None = None
        self._failed_loads: set[tuple[str, str]] = set()

    def generate(self, request: GenerationRequest) -> str:
        key = (request.mode, request.model_id)
        if key in self._failed_loads:
            raise RuntimeError("Model loading previously failed; restart to retry")
        if self._key != key:
            self.release()
            try:
                self._resources = self._load(request)
            except Exception:
                self._failed_loads.add(key)
                self.release()
                raise
            self._key = key
        return self._generate(request)

    def release(self) -> None:
        self._resources = None
        self._key = None
        gc.collect()
        self._clear_cache()

    @abstractmethod
    def _load(self, request: GenerationRequest) -> tuple[Any, Any, Any]: ...

    @abstractmethod
    def _generate(self, request: GenerationRequest) -> str: ...

    def _clear_cache(self) -> None:
        pass


def text_prompt(tokenizer: Any, request: GenerationRequest) -> str:
    messages = list(request.messages)
    if request.response_prefix:
        messages.append({"role": "assistant", "content": request.response_prefix})
    return tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=not bool(request.response_prefix),
        continue_final_message=bool(request.response_prefix),
        reasoning_effort="low",
    )


def final_text(output: str, prefix: str) -> str:
    if prefix:
        return prefix + output
    # Campus's final-channel extraction, supporting both GPT-OSS token spellings.
    match = re.search(
        r"<\|(?:channel|meta_sep)\|>final<\|message\|>(.*?)"
        r"(?:<\|(?:end|start|return|fim_suffix)\|>|$)",
        output,
        re.DOTALL,
    )
    if not match:
        raise ValueError("GPT-OSS did not return a final channel")
    return match.group(1).strip()
