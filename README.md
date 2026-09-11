# Curiora-DevOps inference

The existing incident API uses:

`Curio → ModelRouter → TextDiagnosisProvider → CurioTextProvider → ModelGateway → RuntimeAdapter`

`CurioTextProvider` builds the diagnosis prompt and validates the returned JSON.
The shared gateway selects GPT-OSS 20B for text/code and Qwen3-VL 8B for vision.
Vision is available through `await model_gateway.generate_vision(image_path=...,
messages=...)`; the incident HTTP request schema is unchanged.

## Configuration

Install `requirements.txt` on Apple Silicon. Automatic runtime selection uses
MLX on Apple Silicon, otherwise Torch with CUDA when available or CPU.
Install `requirements-torch.txt` for the optional Torch backend.

| Variable | Default | Purpose |
| --- | --- | --- |
| `CURIORA_RUNTIME` | `auto` | `auto`, `mlx`, `torch`, or `mock` |
| `CURIORA_TEXT_MODEL` | Backend default below | Local model directory or model repository |
| `CURIORA_VISION_MODEL` | Backend default below | Local model directory or model repository |

`CURIORA_TEXT_MODE` remains a compatibility alias when `CURIORA_RUNTIME` is unset.
Use checkpoints matching the selected backend when overriding model paths.

- MLX text: `mlx-community/gpt-oss-20b-MXFP4-Q8`
- MLX vision: `mlx-community/Qwen3-VL-8B-Instruct-8bit`
- Torch text: `openai/gpt-oss-20b`
- Torch vision: `Qwen/Qwen3-VL-8B-Instruct`

The first generation downloads/loads its checkpoint as needed. Switching between
text and vision releases the old model and clears the backend cache before loading
the next model. The default gateway shares one model slot **per process**; use one
Uvicorn worker to avoid loading separate copies. Generation and release run off the
event loop under the same lock, including when the awaiting request is cancelled.
Torch dequantizes GPT-OSS to avoid requiring specialized MXFP4 kernels, so it needs
substantially more memory than the MLX quantized checkpoint.

Invalid output or inference errors produce an unknown diagnosis with confidence
zero and `safe_to_autofix=false`. `CURIORA_RUNTIME=mock` uses a safe canned diagnosis
without importing MLX or Torch; mock output never approves an autofix. Failed
model loads are remembered until the gateway is released or the process restarts.
`await model_gateway.release()` unloads the current model and resets runtime selection.

## Campus adaptation

Adapted from Campus's `app/services/model_gateway.py`, `app/core/runtime.py`, and
`app/runtimes/{base,mlx_runtime,torch_runtime}.py`: backend detection, the text/vision
model mapping, serialized gateway access, adapter boundaries, and model eviction.
The common adapter uses one typed generation request to keep lifecycle handling
shared. DevOps retains its own prompt, final-channel JSON prefill, strict validation,
and async API. Campus chat/session features, debug output, memory telemetry, and
other application functionality were not copied.
