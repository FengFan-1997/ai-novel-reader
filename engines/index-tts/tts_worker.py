"""
IndexTTS worker script — runs inside the IndexTTS isolated venv.

Called by the TTS-Story engine adapter via subprocess. Reads a JSON job
from stdin (or --job-file), synthesises all chunks, writes WAV files, and
prints a JSON result to stdout.

Usage:
    python tts_worker.py --job-file /path/to/job.json

Job JSON schema:
{
    "model_dir":   "checkpoints",          # path to IndexTTS checkpoints dir
    "cfg_path":    "checkpoints/config.yaml",
    "use_fp16":    false,
    "use_deepspeed": false,
    "device":      null,                   # null = auto
    "chunks": [
        {
            "text":             "Hello world.",
            "spk_audio_prompt": "/abs/path/to/voice.wav",
            "emo_vector":       [0, 0.8, 0, 0, 0.2, 0, 0, 0],
            "emo_alpha":        0.6,
            "use_random":       false,
            "output_path":      "/abs/path/to/chunk_0000.wav"
        },
        ...
    ]
}

Result JSON (written to stdout):
{
    "success": true,
    "files": ["/abs/path/to/chunk_0000.wav", ...]
}
or on error:
{
    "success": false,
    "error": "traceback string"
}
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import traceback

# Redirect stdout to stderr so that all print() calls from IndexTTS internals
# (infer_v2.py, etc.) go to stderr. The final JSON result is written directly
# to the real stdout via _stdout below.
_stdout = sys.stdout
sys.stdout = sys.stderr

_MODEL_REPO_MAP = {
    "IndexTTS-2":   "IndexTeam/IndexTTS-2",
    "IndexTTS-1.5": "IndexTeam/IndexTTS-1.5",
    "IndexTTS":     "IndexTeam/IndexTTS",
}
_EMOTION_VECTOR_KEYS = (
    "happy",
    "angry",
    "sad",
    "afraid",
    "disgusted",
    "melancholic",
    "surprised",
    "calm",
)

# The bundled semantic classifier only knows eight basic emotions. Composite
# audiobook directions such as shy, cold, dangerous, gentle and whisper are
# performance states rather than classifier labels. For those states the
# context-aware director vector must remain the stronger signal, otherwise
# "dangerous restraint" and "shy hesitation" are often misread as sadness.
_SEMANTIC_BLEND_BY_STATE = {
    "neutral": 0.70,
    "bright": 0.75,
    "angry": 0.75,
    "gentle": 0.35,
    "shy": 0.10,
    "cold": 0.20,
    "dangerous": 0.15,
    "whisper": 0.15,
}


def _flash_attn_available() -> bool:
    return importlib.util.find_spec("flash_attn") is not None


def _flash_attn_error(error: str) -> bool:
    lowered = error.lower()
    return "flash_attn" in lowered or "flash-attention" in lowered


def _torch_compile_available() -> bool:
    if os.environ.get("INDEXTTS_ALLOW_TORCH_COMPILE") == "1":
        return importlib.util.find_spec("triton") is not None
    if os.name == "nt":
        return False
    return importlib.util.find_spec("triton") is not None


def _torch_compile_error(error: str) -> bool:
    lowered = error.lower()
    return "tritonmissing" in lowered or "working triton installation" in lowered


def _unused_model_kwargs(error: str) -> list[str]:
    match = re.search(r"model_kwargs.*?\[(.*?)\]", error, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return []
    return re.findall(r"['\"]([^'\"]+)['\"]", match.group(1))


def _infer_with_compatible_kwargs(tts, *, spk_audio_prompt: str, text: str, output_path: str, kwargs: dict) -> None:
    try:
        tts.infer(
            spk_audio_prompt=spk_audio_prompt,
            text=text,
            output_path=output_path,
            verbose=False,
            **kwargs,
        )
        return
    except Exception:
        error = traceback.format_exc()
        unused = [key for key in _unused_model_kwargs(error) if key in kwargs]
        if not unused:
            raise
        for key in unused:
            kwargs.pop(key, None)
        print(
            f"[worker] IndexTTS ignored unsupported generation args {unused}; retrying without them.",
            file=sys.stderr,
            flush=True,
        )
        tts.infer(
            spk_audio_prompt=spk_audio_prompt,
            text=text,
            output_path=output_path,
            verbose=False,
            **kwargs,
        )


def _build_generation_kwargs(
    chunk: dict,
    *,
    num_beams: int,
    diffusion_steps: int,
    temperature: float,
    top_p: float,
    top_k: int,
    repetition_penalty: float,
    max_mel_tokens: int,
    max_text_tokens_per_segment: int,
) -> dict:
    """Build one deterministic IndexTTS2 request, including real emotion input."""
    generation_kwargs = {
        "num_beams": num_beams,
        "diffusion_steps": diffusion_steps,
        "temperature": temperature,
        "top_p": top_p,
        "top_k": top_k,
        "repetition_penalty": repetition_penalty,
        "max_mel_tokens": max_mel_tokens,
        "max_text_tokens_per_segment": max_text_tokens_per_segment,
    }
    use_emotion_text = bool(chunk.get("use_emo_text"))
    emotion_text = str(chunk.get("emo_text") or "").strip()
    if use_emotion_text and emotion_text:
        director_vector = chunk.get("emo_vector")
        generation_kwargs.update(
            {
                "use_emo_text": True,
                "emo_text": emotion_text,
                "director_state": str(chunk.get("state") or "neutral"),
                "director_vector": (
                    [
                        max(0.0, min(1.0, float(value)))
                        for value in director_vector
                    ]
                    if isinstance(director_vector, list)
                    and len(director_vector) == 8
                    else None
                ),
                "emo_alpha": max(
                    0.0,
                    min(0.6, float(chunk.get("emo_alpha", 0.5))),
                ),
                "use_random": False,
            }
        )
    else:
        emotion_vector = chunk.get("emo_vector")
        if not isinstance(emotion_vector, list) or len(emotion_vector) != 8:
            return generation_kwargs
        generation_kwargs.update(
            {
                "emo_vector": [
                    max(0.0, min(1.0, float(value)))
                    for value in emotion_vector
                ],
                "emo_alpha": max(
                    0.0,
                    min(0.6, float(chunk.get("emo_alpha", 0.5))),
                ),
                "use_random": bool(chunk.get("use_random", False)),
            }
        )
    return generation_kwargs


def _materialize_semantic_emotion(
    tts,
    generation_kwargs: dict,
    *,
    previous_vector: list[float] | None = None,
    smoothing: float = 0.18,
) -> tuple[dict, list[float] | None, dict | None]:
    """Convert semantic emotion text to a vector and smooth same-speaker turns."""
    if not generation_kwargs.get("use_emo_text"):
        vector = generation_kwargs.get("emo_vector")
        return (
            generation_kwargs,
            list(vector) if isinstance(vector, list) and len(vector) == 8 else None,
            None,
        )

    emotion_text = str(generation_kwargs.pop("emo_text", "") or "").strip()
    generation_kwargs.pop("use_emo_text", None)
    director_state = str(generation_kwargs.pop("director_state", "neutral"))
    director_vector = generation_kwargs.pop("director_vector", None)
    if not emotion_text:
        return generation_kwargs, None, None

    detected = tts.qwen_emo.inference(emotion_text)
    current = [
        max(0.0, min(1.2, float(detected.get(key, 0.0))))
        for key in _EMOTION_VECTOR_KEYS
    ]
    if isinstance(director_vector, list) and len(director_vector) == 8:
        semantic_mix = _SEMANTIC_BLEND_BY_STATE.get(director_state, 0.50)
        current = [
            round(
                semantic_mix * semantic
                + (1.0 - semantic_mix) * max(0.0, min(1.0, float(directed))),
                4,
            )
            for semantic, directed in zip(current, director_vector)
        ]
    if previous_vector and len(previous_vector) == 8:
        mix = max(0.0, min(0.35, float(smoothing)))
        current = [
            round((1.0 - mix) * now + mix * before, 4)
            for now, before in zip(current, previous_vector)
        ]

    # The bundled classifier normally returns a distribution, but malformed or
    # ambiguous output can contain several full-strength emotions.  IndexTTS2
    # subtracts the emotion-vector sum from the original speaker embedding, so
    # a sum above 1 can invert that identity contribution and sound like a
    # different actor. Preserve the mix while keeping a safe unit budget; the
    # subsequent emo_alpha (capped at 0.6) controls performance intensity.
    vector_sum = sum(current)
    if vector_sum > 1.0:
        current = [round(value / vector_sum, 4) for value in current]

    generation_kwargs["emo_vector"] = current
    generation_kwargs["use_random"] = False
    return generation_kwargs, current, detected


def _ensure_model(model_dir: str, model_version: str) -> None:
    """Download model weights from HuggingFace if not already present."""
    required_paths = (
        os.path.join(model_dir, "config.yaml"),
        os.path.join(model_dir, "gpt.pth"),
        os.path.join(model_dir, "s2mel.pth"),
        os.path.join(model_dir, "qwen0.6bemo4-merge", "model.safetensors"),
    )
    if all(os.path.isfile(path) for path in required_paths):
        return

    repo_id = _MODEL_REPO_MAP.get(model_version, "IndexTeam/IndexTTS-2")
    print(
        f"[worker] Model weights not found. Downloading {repo_id} to {model_dir} ...",
        file=sys.stderr, flush=True,
    )
    print(
        f"[worker] This is a one-time download (~5.5 GB for IndexTTS2). Please wait.",
        file=sys.stderr, flush=True,
    )

    try:
        # The official helper detects restricted Hugging Face connectivity and
        # switches to ModelScope when appropriate.
        from indextts.utils.model_download import snapshot_download  # type: ignore
        snapshot_download(
            repo_id=repo_id,
            local_dir=model_dir,
            ignore_patterns=["*.md", "*.txt", "examples/*"],
        )
        print(f"[worker] Model download complete.", file=sys.stderr, flush=True)
    except Exception:
        raise RuntimeError(
            f"Failed to download IndexTTS model '{repo_id}'.\n"
            f"Check your internet connection or download manually:\n"
            f"  huggingface-cli download {repo_id} --local-dir {model_dir}\n\n"
            + traceback.format_exc()
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="IndexTTS batch worker")
    parser.add_argument("--job-file", required=True, help="Path to JSON job file")
    args = parser.parse_args()

    with open(args.job_file, "r", encoding="utf-8") as fh:
        job = json.load(fh)

    model_dir = job.get("model_dir", "checkpoints")
    model_version = job.get("model_version", "IndexTTS-2")
    cfg_path = job.get("cfg_path", os.path.join(model_dir, "config.yaml"))
    use_fp16 = bool(job.get("use_fp16", False))
    use_deepspeed = bool(job.get("use_deepspeed", False))
    use_torch_compile = bool(job.get("use_torch_compile", False))
    use_accel = bool(job.get("use_accel", False))
    num_beams = int(job.get("num_beams", 3))
    diffusion_steps = int(job.get("diffusion_steps", 25))
    temperature = float(job.get("temperature", 0.8))
    top_p = float(job.get("top_p", 0.8))
    top_k = int(job.get("top_k", 30))
    repetition_penalty = float(job.get("repetition_penalty", 10.0))
    max_mel_tokens = int(job.get("max_mel_tokens", 1500))
    max_text_tokens_per_segment = int(job.get("max_text_tokens_per_segment", 120))
    device = job.get("device") or None
    chunks = job.get("chunks", [])

    if not _flash_attn_available() and (use_fp16 or use_deepspeed or use_accel):
        print(
            "[worker] flash_attn is not installed; disabling IndexTTS fp16, "
            "DeepSpeed, and acceleration for compatibility.",
            file=sys.stderr,
            flush=True,
        )
        use_fp16 = False
        use_deepspeed = False
        use_accel = False

    if use_torch_compile and not _torch_compile_available():
        print(
            "[worker] Triton is not available; disabling IndexTTS torch_compile "
            "for compatibility.",
            file=sys.stderr,
            flush=True,
        )
        use_torch_compile = False

    try:
        _ensure_model(model_dir, model_version)
    except Exception:
        _fail(traceback.format_exc())
        return

    try:
        from indextts.infer_v2 import IndexTTS2  # type: ignore

        try:
            tts = IndexTTS2(
                cfg_path=cfg_path,
                model_dir=model_dir,
                use_fp16=use_fp16,
                use_deepspeed=use_deepspeed,
                use_torch_compile=use_torch_compile,
                use_accel=use_accel,
                device=device,
                use_cuda_kernel=None,
            )
        except Exception:
            error = traceback.format_exc()
            if _flash_attn_error(error) and (use_fp16 or use_deepspeed or use_accel):
                print(
                    "[worker] IndexTTS requested flash_attn. Retrying with "
                    "fp16, DeepSpeed, and acceleration disabled.",
                    file=sys.stderr,
                    flush=True,
                )
                tts = IndexTTS2(
                    cfg_path=cfg_path,
                    model_dir=model_dir,
                    use_fp16=False,
                    use_deepspeed=False,
                    use_torch_compile=use_torch_compile,
                    use_accel=False,
                    device=device,
                    use_cuda_kernel=False,
                )
            elif _torch_compile_error(error) and use_torch_compile:
                print(
                    "[worker] IndexTTS torch_compile failed because Triton is "
                    "unavailable. Retrying with torch_compile disabled.",
                    file=sys.stderr,
                    flush=True,
                )
                use_torch_compile = False
                tts = IndexTTS2(
                    cfg_path=cfg_path,
                    model_dir=model_dir,
                    use_fp16=use_fp16,
                    use_deepspeed=use_deepspeed,
                    use_torch_compile=False,
                    use_accel=use_accel,
                    device=device,
                    use_cuda_kernel=False,
                )
            else:
                raise
    except Exception:
        _fail(traceback.format_exc())
        return

    files: list[str] = []
    previous_emotion_by_prompt: dict[str, list[float]] = {}
    for chunk in chunks:
        text = chunk.get("text", "")
        spk_audio_prompt = chunk.get("spk_audio_prompt", "")
        output_path = chunk.get("output_path", "")

        if not text.strip():
            print(f"[worker] Skipping empty chunk -> {output_path}", file=sys.stderr)
            continue

        try:
            generation_kwargs = _build_generation_kwargs(
                chunk,
                num_beams=num_beams,
                diffusion_steps=diffusion_steps,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                repetition_penalty=repetition_penalty,
                max_mel_tokens=max_mel_tokens,
                max_text_tokens_per_segment=max_text_tokens_per_segment,
            )
            previous_vector = (
                previous_emotion_by_prompt.get(spk_audio_prompt)
                if bool(chunk.get("smooth_emotion"))
                else None
            )
            generation_kwargs, resolved_vector, detected = (
                _materialize_semantic_emotion(
                    tts,
                    generation_kwargs,
                    previous_vector=previous_vector,
                )
            )
            if resolved_vector is not None:
                previous_emotion_by_prompt[spk_audio_prompt] = resolved_vector
            if detected is not None:
                print(
                    "[EMOTION_DETECTED] "
                    + json.dumps(
                        {
                            "scores": detected,
                            "smoothed": bool(previous_vector),
                        },
                        ensure_ascii=False,
                    ),
                    file=sys.stderr,
                    flush=True,
                )
            _infer_with_compatible_kwargs(
                tts,
                spk_audio_prompt=spk_audio_prompt,
                text=text,
                output_path=output_path,
                kwargs=generation_kwargs,
            )
            files.append(output_path)
            print(f"[CHUNK_DONE] {output_path}", file=sys.stderr, flush=True)
        except Exception:
            _fail(traceback.format_exc())
            return

    result = {"success": True, "files": files}
    print(json.dumps(result), file=_stdout, flush=True)


def _fail(error: str) -> None:
    result = {"success": False, "error": error}
    print(json.dumps(result), file=_stdout, flush=True)
    sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        _fail(traceback.format_exc())
