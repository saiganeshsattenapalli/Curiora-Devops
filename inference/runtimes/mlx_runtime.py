from typing import Any

from inference.runtimes.base import (
    GenerationRequest,
    RuntimeAdapter,
    final_text,
    text_prompt,
)


class MLXRuntime(RuntimeAdapter):
    """Campus's MLX text/vision split, with lazy imports and shared eviction."""

    def _load(self, request: GenerationRequest) -> tuple[Any, Any, Any]:
        if request.mode == "text":
            from mlx_lm import load

            model, tokenizer = load(request.model_id)
            return model, tokenizer, None

        from mlx_vlm import load
        from mlx_vlm.utils import load_config

        config = load_config(request.model_id)
        model, processor = load(request.model_id)
        return model, processor, config

    def _generate(self, request: GenerationRequest) -> str:
        assert self._resources is not None
        model, processor, config = self._resources
        if request.mode == "text":
            from mlx_lm import generate
            from mlx_lm.sample_utils import make_sampler

            output = generate(
                model, processor, prompt=text_prompt(processor, request),
                max_tokens=request.max_tokens,
                sampler=make_sampler(temp=request.temperature), verbose=False,
            )
            return final_text(output, request.response_prefix)

        from mlx_vlm import generate
        from mlx_vlm.prompt_utils import apply_chat_template

        prompt = apply_chat_template(processor, config, request.messages, num_images=1)
        result = generate(
            model, processor, prompt, [request.image_path],
            max_tokens=request.max_tokens, temperature=request.temperature,
            verbose=False,
        )
        return result if isinstance(result, str) else result.text

    def _clear_cache(self) -> None:
        import mlx.core as mx

        mx.synchronize()
        mx.clear_cache()
