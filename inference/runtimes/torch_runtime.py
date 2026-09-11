from typing import Any

from inference.runtimes.base import (
    GenerationRequest,
    RuntimeAdapter,
    final_text,
    text_prompt,
)


class TorchRuntime(RuntimeAdapter):
    """Campus's optional CUDA/CPU adapter; never imported on the MLX path."""

    def __init__(self, device: str) -> None:
        super().__init__()
        self.device = device

    def _load(self, request: GenerationRequest) -> tuple[Any, Any, Any]:
        import torch
        from transformers import AutoProcessor, AutoTokenizer

        kwargs: dict[str, Any] = {
            "device_map": self.device,
            "dtype": torch.bfloat16 if self.device == "cuda" else torch.float32,
        }
        if request.mode == "text":
            from transformers import AutoModelForCausalLM, Mxfp4Config

            # Avoid requiring hardware-specific MXFP4 kernels on the Torch path.
            # Dequantized GPT-OSS needs substantially more memory than MLX MXFP4.
            kwargs["quantization_config"] = Mxfp4Config(dequantize=True)
            processor = AutoTokenizer.from_pretrained(request.model_id)
            model = AutoModelForCausalLM.from_pretrained(request.model_id, **kwargs)
        else:
            from transformers import Qwen3VLForConditionalGeneration

            processor = AutoProcessor.from_pretrained(request.model_id)
            model = Qwen3VLForConditionalGeneration.from_pretrained(
                request.model_id, **kwargs
            )
        model.eval()
        return model, processor, None

    def _generate(self, request: GenerationRequest) -> str:
        import torch

        assert self._resources is not None
        model, processor, _ = self._resources
        if request.mode == "text":
            inputs = processor(
                text_prompt(processor, request), return_tensors="pt",
                add_special_tokens=False,
            )
        else:
            from PIL import Image

            messages: list[dict[str, Any]] = [
                {"role": m["role"], "content": [{"type": "text", "text": m["content"]}]}
                for m in request.messages
            ]
            user = next(m for m in reversed(messages) if m["role"] == "user")
            user["content"].insert(0, {"type": "image"})
            prompt = processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            with Image.open(request.image_path) as image:
                inputs = processor(
                    text=[prompt], images=[image.convert("RGB")], return_tensors="pt"
                )

        inputs = {key: value.to(model.device) for key, value in inputs.items()}
        options: dict[str, Any] = {"do_sample": request.temperature > 0}
        if request.temperature > 0:
            options["temperature"] = request.temperature
        with torch.inference_mode():
            output = model.generate(**inputs, max_new_tokens=request.max_tokens, **options)
        generated = output[0, inputs["input_ids"].shape[-1]:]
        # Keep Harmony markers when extracting a non-prefilled text response.
        answer = processor.decode(
            generated,
            skip_special_tokens=request.mode == "vision" or bool(request.response_prefix),
        )
        return final_text(answer, request.response_prefix) if request.mode == "text" else answer

    def _clear_cache(self) -> None:
        if self.device == "cuda":
            import torch

            torch.cuda.empty_cache()
