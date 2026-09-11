"""Adapted from Campus: runtime selection, model routing, and serialized access."""

import asyncio
import os
import platform
from pathlib import Path
from threading import Lock
from typing import Literal

from inference.runtimes.base import GenerationRequest, RuntimeAdapter


class ModelGateway:
    def __init__(self) -> None:
        self._runtime: RuntimeAdapter | None = None
        self._kind = ""
        self._lock = Lock()

    def _select_runtime(self) -> RuntimeAdapter:
        if self._runtime is not None:
            return self._runtime
        # Preserve the existing setting; the default now detects the hardware.
        mode = os.getenv(
            "CURIORA_RUNTIME", os.getenv("CURIORA_TEXT_MODE", "auto")
        ).strip().lower()
        apple = (
            platform.system() == "Darwin"
            and platform.machine().lower() in {"arm64", "aarch64"}
        )
        if mode == "mock":
            from inference.runtimes.mock_runtime import MockRuntime

            self._runtime = MockRuntime()
            self._kind = "mock"
        elif mode == "mlx" or (mode == "auto" and apple):
            from inference.runtimes.mlx_runtime import MLXRuntime

            self._runtime = MLXRuntime()
            self._kind = "mlx"
        elif mode in {"auto", "torch"}:
            import torch
            from inference.runtimes.torch_runtime import TorchRuntime

            self._runtime = TorchRuntime("cuda" if torch.cuda.is_available() else "cpu")
            self._kind = "torch"
        else:
            raise ValueError("CURIORA_RUNTIME must be auto, mlx, torch, or mock")
        return self._runtime

    async def generate_text(
        self, *, messages: list[dict[str, str]], max_tokens: int = 1024,
        temperature: float = 0.0, response_prefix: str = "",
    ) -> str:
        return await asyncio.to_thread(
            self._generate, "text", messages, max_tokens, temperature, response_prefix, None
        )

    async def generate_vision(
        self, *, image_path: str, messages: list[dict[str, str]],
        max_tokens: int = 512, temperature: float = 0.0,
    ) -> str:
        if not Path(image_path).is_file():
            raise FileNotFoundError(image_path)
        if not any(m["role"] == "user" for m in messages):
            raise ValueError("Vision input requires a user message")
        return await asyncio.to_thread(
            self._generate, "vision", messages, max_tokens, temperature, "", image_path
        )

    def _generate(
        self, mode: Literal["text", "vision"], messages: list[dict[str, str]],
        max_tokens: int, temperature: float, response_prefix: str, image_path: str | None,
    ) -> str:
        # The worker owns the lock even if its awaiting request is cancelled.
        with self._lock:
            runtime = self._select_runtime()
            if mode == "text":
                default = (
                    "mlx-community/gpt-oss-20b-MXFP4-Q8"
                    if self._kind == "mlx" else "openai/gpt-oss-20b"
                )
                model_id = os.getenv("CURIORA_TEXT_MODEL", default)
            else:
                default = (
                    "mlx-community/Qwen3-VL-8B-Instruct-8bit"
                    if self._kind == "mlx" else "Qwen/Qwen3-VL-8B-Instruct"
                )
                model_id = os.getenv("CURIORA_VISION_MODEL", default)
            return runtime.generate(GenerationRequest(
                mode, model_id, messages, max_tokens, temperature, response_prefix, image_path
            ))

    async def release(self) -> None:
        await asyncio.to_thread(self._release)

    def _release(self) -> None:
        with self._lock:
            if self._runtime is not None:
                self._runtime.release()
            self._runtime = None
            self._kind = ""


# One default gateway/model slot per process, shared by text and vision callers.
model_gateway = ModelGateway()
