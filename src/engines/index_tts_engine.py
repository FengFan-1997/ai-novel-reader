"""IndexTTS engine adapter (subprocess-isolated).

IndexTTS runs in its own isolated venv under engines/index-tts/ to avoid
dependency conflicts with the main project (torch version, numpy, etc.).
This adapter communicates with the IndexTTS worker via subprocess.

Setup:
    1. Run setup.bat (clones repo + runs uv sync automatically)
    Model weights are downloaded automatically on first use via huggingface_hub.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import soundfile as sf

from .base import EngineCapabilities, TtsEngineBase, VoiceAssignment
from ..audio_effects import AudioPostProcessor, VoiceFXSettings
from ..chinese_voice_director import (
    ACTING_STATES,
    VOICE_PRESETS,
    infer_acting_state,
    resolve_acting_state,
)

logger = logging.getLogger(__name__)

INDEX_TTS_SAMPLE_RATE = 22050
INDEX_TTS_DEFAULT_MODEL_VERSION = "IndexTTS-2"

_ENGINE_ROOT = Path(__file__).resolve().parent.parent.parent / "engines" / "index-tts"

# IndexTTS2 vector order from the official implementation:
# happy, angry, sad, afraid, disgusted, melancholic, surprised, calm.
# Vectors describe the direction; `alpha` controls the amount mixed into the
# cloned speaker. Community testing and the official README both recommend
# keeping text/vector emotion strength around 0.6 or lower to preserve identity.
INDEX_TTS_EMOTION_PROFILES: Dict[str, Dict[str, object]] = {
    "neutral": {
        "vector": [0.0, 0.0, 0.0, 0.0, 0.0, 0.05, 0.0, 0.95],
        "alpha": 0.32,
    },
    "bright": {
        "vector": [0.72, 0.0, 0.0, 0.0, 0.0, 0.03, 0.25, 0.0],
        "alpha": 0.56,
    },
    "gentle": {
        "vector": [0.12, 0.0, 0.0, 0.0, 0.0, 0.18, 0.0, 0.70],
        "alpha": 0.44,
    },
    "shy": {
        "vector": [0.22, 0.0, 0.0, 0.15, 0.0, 0.18, 0.0, 0.45],
        "alpha": 0.48,
    },
    "cold": {
        "vector": [0.0, 0.0, 0.0, 0.0, 0.10, 0.20, 0.0, 0.70],
        "alpha": 0.46,
    },
    "dangerous": {
        "vector": [0.0, 0.20, 0.0, 0.10, 0.22, 0.18, 0.0, 0.30],
        "alpha": 0.56,
    },
    "angry": {
        "vector": [0.0, 0.82, 0.0, 0.0, 0.18, 0.0, 0.0, 0.0],
        "alpha": 0.60,
    },
    "whisper": {
        "vector": [0.0, 0.0, 0.0, 0.16, 0.0, 0.20, 0.0, 0.64],
        "alpha": 0.44,
    },
}


def index_tts_emotion_profile(
    acting_state: Optional[str],
    *,
    strength: float = 1.0,
) -> Dict[str, object]:
    """Return a safe IndexTTS2 emotion vector for one acting state."""
    state_id = (
        str(acting_state or "neutral")
        if str(acting_state or "neutral") in ACTING_STATES
        else "neutral"
    )
    profile = INDEX_TTS_EMOTION_PROFILES[state_id]
    bounded_strength = max(0.0, min(1.0, float(strength)))
    return {
        "state": state_id,
        "label": ACTING_STATES[state_id]["label"],
        "emo_vector": list(profile["vector"]),
        "emo_alpha": round(float(profile["alpha"]) * bounded_strength, 4),
        "use_random": False,
    }


def _find_venv_python(engine_root: Path) -> Optional[Path]:
    """Locate the Python executable inside the IndexTTS uv venv."""
    candidates = [
        engine_root / ".venv" / "Scripts" / "python.exe",   # Windows
        engine_root / ".venv" / "bin" / "python",            # Linux/macOS
        engine_root / ".venv" / "bin" / "python3",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def _check_index_tts_available(engine_root: Path) -> tuple[bool, str]:
    """Return (available, reason) for the IndexTTS isolated environment."""
    if not engine_root.exists():
        return False, f"IndexTTS directory not found: {engine_root}. Run setup.bat to install."
    worker = engine_root / "tts_worker.py"
    if not worker.is_file():
        return False, f"IndexTTS worker not found: {worker}. Run setup.bat to repair the IndexTTS install."
    python = _find_venv_python(engine_root)
    if python is None:
        return False, f"IndexTTS venv not found under {engine_root}. Run setup.bat to install."
    return True, ""


INDEX_TTS_AVAILABLE, INDEX_TTS_UNAVAILABLE_REASON = _check_index_tts_available(_ENGINE_ROOT)


class IndexTTSEngine(TtsEngineBase):
    """IndexTTS engine adapter — zero-shot voice cloning via isolated subprocess."""

    name = "index_tts"
    capabilities = EngineCapabilities(
        supports_voice_cloning=True,
        supports_emotion_tags=True,
        supported_languages=["en", "zh"],
    )

    def __init__(
        self,
        *,
        engine_root: Optional[str] = None,
        model_version: str = INDEX_TTS_DEFAULT_MODEL_VERSION,
        use_fp16: bool = False,
        use_deepspeed: bool = False,
        use_torch_compile: bool = False,
        use_accel: bool = False,
        num_beams: int = 3,
        diffusion_steps: int = 25,
        temperature: float = 0.8,
        top_p: float = 0.8,
        top_k: int = 30,
        repetition_penalty: float = 10.0,
        max_mel_tokens: int = 1500,
        max_text_tokens_per_segment: int = 120,
        device: Optional[str] = None,
        default_prompt: Optional[str] = None,
        auto_emotion: bool = True,
        emotion_strength: float = 1.0,
        persona_design_model_id: str = "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-8bit",
        persona_clone_model_id: str = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit",
        persona_stability_temperature: float = 0.35,
        persona_stability_top_k: int = 20,
        persona_stability_top_p: float = 0.9,
        persona_stability_seed: int = 20260727,
        **_kwargs,
    ) -> None:
        self._engine_root = Path(engine_root) if engine_root else _ENGINE_ROOT
        available, reason = _check_index_tts_available(self._engine_root)
        if not available:
            raise ImportError(f"IndexTTS is not available: {reason}")

        self._python = _find_venv_python(self._engine_root)
        self._worker = self._engine_root / "tts_worker.py"
        self._model_dir = str(self._engine_root / "checkpoints")
        self._cfg_path = str(self._engine_root / "checkpoints" / "config.yaml")
        self._model_version = model_version
        self._use_fp16 = use_fp16
        self._use_deepspeed = use_deepspeed
        self._use_torch_compile = use_torch_compile
        self._use_accel = use_accel
        self._num_beams = max(1, int(num_beams))
        self._diffusion_steps = max(1, int(diffusion_steps))
        self._temperature = float(temperature)
        self._top_p = float(top_p)
        self._top_k = max(1, int(top_k))
        self._repetition_penalty = float(repetition_penalty)
        self._max_mel_tokens = max(100, int(max_mel_tokens))
        self._max_text_tokens_per_segment = max(20, int(max_text_tokens_per_segment))
        self._device = device or None
        self._default_prompt = (default_prompt or "").strip() or None
        self._auto_emotion = bool(auto_emotion)
        self._emotion_strength = max(0.0, min(1.0, float(emotion_strength)))
        self._persona_design_model_id = persona_design_model_id
        self._persona_clone_model_id = persona_clone_model_id
        self._persona_stability_temperature = persona_stability_temperature
        self._persona_stability_top_k = persona_stability_top_k
        self._persona_stability_top_p = persona_stability_top_p
        self._persona_stability_seed = persona_stability_seed
        self.post_processor = AudioPostProcessor()

        logger.info(
            "IndexTTSEngine ready (model=%s, fp16=%s, deepspeed=%s, torch_compile=%s, accel=%s, num_beams=%d, diffusion_steps=%d, device=%s)",
            model_version, use_fp16, use_deepspeed, use_torch_compile, use_accel,
            self._num_beams, self._diffusion_steps, device or "auto",
        )

    @property
    def sample_rate(self) -> int:
        return INDEX_TTS_SAMPLE_RATE

    @staticmethod
    def _is_narrator(meta: Dict) -> bool:
        return str(meta.get("speaker") or "").strip().lower() in {
            "narrator",
            "旁白",
        }

    @staticmethod
    def _is_following_attribution(text: object) -> bool:
        """Keep post-dialogue context only when it looks like delivery/action attribution."""
        return bool(
            re.search(
                r"说|道|问|答|喊|叫|喝|嚷|嘟囔|喃喃|开口|"
                r"声音|语气|口吻|笑|哭|叹|低声|轻声|沉声|冷声",
                str(text or ""),
            )
        )

    @staticmethod
    def _callback_payload(meta: Dict) -> Dict[str, object]:
        payload: Dict[str, object] = {
            "speaker": meta.get("speaker"),
            "text": meta.get("text"),
            "segment_index": meta.get("segment_index"),
            "chunk_index": meta.get("chunk_index"),
        }
        if "chapter_index" in meta:
            payload["chapter_index"] = meta.get("chapter_index", 0)
        for key in (
            "emotion",
            "emotion_label",
            "emotion_source",
            "emotion_confidence",
            "emotion_reason",
            "emotion_driver",
        ):
            if meta.get(key) is not None:
                payload[key] = meta.get(key)
        return payload

    def enrich_worker_chunks(
        self,
        worker_chunks: List[Dict],
        chunk_meta: List[Dict],
    ) -> tuple[List[Dict], List[Dict]]:
        """Attach context-aware IndexTTS2 emotion controls to flat chunks."""
        previous_identity: Optional[str] = None
        previous_state: Optional[str] = None

        for index, (worker_chunk, meta) in enumerate(
            zip(worker_chunks, chunk_meta)
        ):
            assignment = meta.get("assignment")
            if not isinstance(assignment, VoiceAssignment):
                assignment = VoiceAssignment()
            extra = assignment.extra or {}
            explicit_emotion = meta.get("emotion")
            manual_instruction = extra.get("instruct")
            manual_state = resolve_acting_state(manual_instruction)
            identity = str(
                worker_chunk.get("spk_audio_prompt")
                or assignment.voice
                or meta.get("speaker")
                or "default"
            )

            context_before = ""
            context_after = ""
            if index > 0 and self._is_narrator(chunk_meta[index - 1]):
                context_before = str(chunk_meta[index - 1].get("text") or "")
            if (
                index + 1 < len(chunk_meta)
                and self._is_narrator(chunk_meta[index + 1])
                and self._is_following_attribution(
                    chunk_meta[index + 1].get("text")
                )
            ):
                context_after = str(chunk_meta[index + 1].get("text") or "")

            adjacent_state = (
                previous_state if previous_identity == identity else None
            )
            worker_chunk["smooth_emotion"] = adjacent_state is not None
            if not self._auto_emotion and not explicit_emotion and not manual_state:
                decision = infer_acting_state(
                    meta.get("text"),
                    explicit_instruction="自然",
                )
            else:
                decision = infer_acting_state(
                    meta.get("text"),
                    explicit_instruction=(
                        explicit_emotion
                        or (manual_instruction if manual_state else None)
                    ),
                    default_state="neutral",
                    previous_state=adjacent_state,
                    context_before=context_before,
                    context_after=context_after,
                )

            profile = index_tts_emotion_profile(
                str(decision["state"]),
                strength=self._emotion_strength,
            )
            worker_chunk.update(profile)
            # IndexTTS2 ships a small Chinese semantic emotion model. For
            # automatically directed dialogue, let it produce the nuanced
            # eight-dimensional mix from the spoken line and nearby narration.
            # Explicit story labels and manual role settings remain deterministic
            # vectors so the author's/user's choice always wins.
            use_semantic_emotion = (
                self._auto_emotion
                and not explicit_emotion
                and not manual_state
                and not self._is_narrator(meta)
            )
            if use_semantic_emotion:
                emotion_text_parts: List[str] = []
                if context_before:
                    emotion_text_parts.append(f"前文旁白：{context_before[-160:]}")
                emotion_text_parts.append(f"当前对白：{str(meta.get('text') or '')}")
                if context_after:
                    emotion_text_parts.append(f"后文旁白：{context_after[:120]}")
                if decision.get("source") in {"automatic", "continuity"}:
                    emotion_text_parts.append(
                        f"连续表演参考：{decision.get('label') or '自然'}"
                    )
                worker_chunk.update(
                    {
                        "use_emo_text": True,
                        "emo_text": "\n".join(emotion_text_parts),
                        "emo_alpha": round(
                            min(
                                0.6,
                                max(
                                    float(worker_chunk.get("emo_alpha", 0.0)),
                                    0.54 * self._emotion_strength,
                                ),
                            ),
                            4,
                        ),
                    }
                )
            meta.update(
                {
                    "emotion": decision.get("state"),
                    "emotion_label": decision.get("label"),
                    "emotion_source": decision.get("source"),
                    "emotion_confidence": decision.get("confidence"),
                    "emotion_reason": decision.get("reason"),
                    "emotion_driver": (
                        "semantic_text" if use_semantic_emotion else "vector"
                    ),
                }
            )
            if not self._is_narrator(meta):
                previous_identity = identity
                previous_state = str(decision["state"])

        return worker_chunks, chunk_meta

    def generate_batch(
        self,
        segments: List[Dict],
        voice_config: Dict[str, Dict],
        output_dir: Path,
        speed: float = 1.0,
        sample_rate: Optional[int] = None,
        progress_cb=None,
        chunk_cb=None,
        parallel_workers: int = 1,
        pause_cb=None,
        cancel_cb=None,
        group_by_speaker: bool = False,
    ) -> List[str]:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        self.ensure_persona_voice_locks(voice_config)

        # Build flat list of chunks for the worker
        worker_chunks: List[Dict] = []
        chunk_meta: List[Dict] = []
        chunk_index = 0

        for seg_idx, segment in enumerate(segments):
            speaker = segment.get("speaker")
            chunks = segment.get("chunks") or []
            assignment = self._voice_assignment_for(voice_config, speaker)
            spk_prompt = self._resolve_prompt(assignment)

            for local_idx, chunk_text in enumerate(chunks):
                output_path = output_dir / f"chunk_{chunk_index:04d}.wav"
                worker_chunks.append({
                    "text": chunk_text,
                    "spk_audio_prompt": spk_prompt,
                    "output_path": str(output_path),
                    "_order_index": chunk_index,
                })
                chunk_meta.append({
                    "speaker": speaker,
                    "text": chunk_text,
                    "segment_index": seg_idx,
                    "chunk_index": local_idx,
                    "emotion": segment.get("emotion"),
                    "output_path": str(output_path),
                    "assignment": assignment,
                    "_order_index": chunk_index,
                })
                chunk_index += 1

        if not worker_chunks:
            return []

        worker_chunks, chunk_meta = self.enrich_worker_chunks(
            worker_chunks,
            chunk_meta,
        )

        # Group by speaker so the model's internal voice-prompt cache stays hot.
        # Chunks with the same spk_audio_prompt run back-to-back; the worker
        # skips re-encoding the reference audio for consecutive same-voice chunks.
        # Output files keep their original chunk_NNNN.wav names so merge order
        # is unaffected.
        if group_by_speaker and len(worker_chunks) > 1:
            seen_prompts: List[str] = []
            by_prompt: Dict[str, List[Dict]] = {}
            for item in worker_chunks:
                p = item["spk_audio_prompt"] or ""
                if p not in by_prompt:
                    seen_prompts.append(p)
                    by_prompt[p] = []
                by_prompt[p].append(item)
            grouped_worker: List[Dict] = []
            grouped_meta: List[Dict] = []
            meta_by_order = {m["_order_index"]: m for m in chunk_meta}
            for p in seen_prompts:
                for item in by_prompt[p]:
                    grouped_worker.append(item)
                    grouped_meta.append(meta_by_order[item["_order_index"]])
            worker_chunks = grouped_worker
            chunk_meta = grouped_meta

        # Write job file and call worker
        job = {
            "model_dir": self._model_dir,
            "cfg_path": self._cfg_path,
            "model_version": self._model_version,
            "use_fp16": self._use_fp16,
            "use_deepspeed": self._use_deepspeed,
            "use_torch_compile": self._use_torch_compile,
            "use_accel": self._use_accel,
            "num_beams": self._num_beams,
            "diffusion_steps": self._diffusion_steps,
            "temperature": self._temperature,
            "top_p": self._top_p,
            "top_k": self._top_k,
            "repetition_penalty": self._repetition_penalty,
            "max_mel_tokens": self._max_mel_tokens,
            "max_text_tokens_per_segment": self._max_text_tokens_per_segment,
            "device": self._device,
            "chunks": worker_chunks,
        }

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as tf:
            json.dump(job, tf)
            job_file = tf.name

        files: List[str] = []
        import threading
        paused_early = threading.Event()
        cancelled_early = threading.Event()
        try:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(self._engine_root)
            env.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            env.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
            env.setdefault("MODELSCOPE_DOWNLOAD_PARALLELS", "4")

            proc = subprocess.Popen(
                [str(self._python), str(self._worker), "--job-file", job_file],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(self._engine_root),
                env=env,
            )

            stderr_lines: List[str] = []
            stdout_chunks: List[str] = []
            completed_paths: List[str] = []

            def _stream_stderr() -> None:
                assert proc.stderr is not None
                for line in proc.stderr:
                    line = line.rstrip()
                    stderr_lines.append(line)
                    logger.info("[index-tts worker] %s", line)
                    if line.startswith("[CHUNK_DONE] "):
                        done_path = line[len("[CHUNK_DONE] "):]
                        completed_paths.append(done_path)
                        idx = len(completed_paths) - 1
                        if idx < len(chunk_meta):
                            meta = chunk_meta[idx]
                            if callable(cancel_cb) and cancel_cb():
                                cancelled_early.set()
                                proc.terminate()
                                return
                            if callable(pause_cb) and pause_cb():
                                paused_early.set()
                                proc.terminate()
                                return
                            if callable(progress_cb):
                                try:
                                    progress_cb()
                                except Exception:
                                    # JobPaused or other cancellation exception - signal to stop
                                    paused_early.set()
                                    proc.terminate()
                                    return
                            if callable(chunk_cb):
                                chunk_cb(
                                    meta["chunk_index"],
                                    self._callback_payload(meta),
                                    done_path,
                                )

            def _poll_cancel() -> None:
                """Poll cancel/pause between chunks in case no [CHUNK_DONE] arrives quickly."""
                while proc.poll() is None:
                    if callable(cancel_cb) and cancel_cb():
                        cancelled_early.set()
                        proc.terminate()
                        return
                    if callable(pause_cb) and pause_cb():
                        paused_early.set()
                        proc.terminate()
                        return
                    threading.Event().wait(0.5)

            def _read_stdout() -> None:
                assert proc.stdout is not None
                stdout_chunks.append(proc.stdout.read())

            stderr_thread = threading.Thread(target=_stream_stderr, daemon=True)
            stdout_thread = threading.Thread(target=_read_stdout, daemon=True)
            poll_thread = threading.Thread(target=_poll_cancel, daemon=True)
            stderr_thread.start()
            stdout_thread.start()
            poll_thread.start()

            proc.wait()
            stderr_thread.join(timeout=5)
            stdout_thread.join(timeout=5)
            returncode = proc.returncode
            stdout_data = "".join(stdout_chunks)

            if cancelled_early.is_set():
                logger.info("IndexTTS worker terminated early due to cancel — %d chunks completed", len(completed_paths))
                files = [p for p in completed_paths if Path(p).exists()]
            elif paused_early.is_set():
                logger.info("IndexTTS worker terminated early due to pause — %d chunks completed", len(completed_paths))
                files = [p for p in completed_paths if Path(p).exists()]
            elif not stdout_data.strip():
                raise RuntimeError(
                    f"IndexTTS worker produced no output (exit code {returncode}).\n"
                    f"stderr:\n{chr(10).join(stderr_lines) or '(empty)'}"
                )
            else:
                response = json.loads(stdout_data.strip())
                if not response.get("success"):
                    raise RuntimeError(
                        f"IndexTTS worker failed:\n{response.get('error', 'unknown error')}"
                    )
                files = response.get("files", [])

        finally:
            try:
                os.unlink(job_file)
            except OSError:
                pass

        if cancelled_early.is_set():
            return [p for p in files if Path(p).exists()]

        if paused_early.is_set():
            return [p for p in files if Path(p).exists()]

        # Apply FX post-processing only — callbacks were already fired per-chunk
        # in real-time by _stream_stderr as each [CHUNK_DONE] marker arrived.
        processed_files: List[str] = []
        already_reported = set(completed_paths)
        for i, file_path in enumerate(files):
            meta = chunk_meta[i]
            assignment: VoiceAssignment = meta["assignment"]
            fx_settings = VoiceFXSettings.from_payload(assignment.fx_payload)

            if fx_settings and not fx_settings.is_identity():
                try:
                    audio, sr = sf.read(file_path, dtype="float32")
                    audio = self.post_processor.apply_post_pipeline(audio, sr, fx_settings)
                    sf.write(file_path, audio, sr)
                except Exception as exc:
                    logger.warning("FX post-processing failed for %s: %s", file_path, exc)

            processed_files.append(file_path)

            if callable(pause_cb) and pause_cb():
                return processed_files

            # Only fire callbacks if this chunk wasn't already reported live
            if file_path not in already_reported:
                if callable(progress_cb):
                    try:
                        progress_cb()
                    except Exception:
                        # JobPaused or other cancellation exception - re-raise so caller handles it
                        raise
                if callable(chunk_cb):
                    chunk_cb(
                        meta["chunk_index"],
                        self._callback_payload(meta),
                        file_path,
                    )

        # Return in original chunk_NNNN order regardless of group_by_speaker processing order
        processed_files.sort(key=lambda p: p)
        return processed_files

    def generate_batch_prebuilt(
        self,
        worker_chunks: List[Dict],
        chunk_meta: List[Dict],
        progress_cb=None,
        chunk_cb=None,
        pause_cb=None,
        cancel_cb=None,
        group_by_speaker: bool = False,
    ) -> List[str]:
        """Run one subprocess for a pre-built list of chunks with explicit output paths.

        Each entry in worker_chunks must have: text, spk_audio_prompt, output_path.
        Each entry in chunk_meta must have: speaker, text, segment_index, chunk_index,
        output_path, assignment, _order_index.

        This is used by app.py to batch ALL chapters of a job into a single subprocess
        call, eliminating per-chapter model-reload overhead (~30-60s each).
        """
        if not worker_chunks:
            return []

        worker_chunks, chunk_meta = self.enrich_worker_chunks(
            worker_chunks,
            chunk_meta,
        )

        if group_by_speaker and len(worker_chunks) > 1:
            seen_prompts: List[str] = []
            by_prompt: Dict[str, List[Dict]] = {}
            for item in worker_chunks:
                p = item.get("spk_audio_prompt") or ""
                if p not in by_prompt:
                    seen_prompts.append(p)
                    by_prompt[p] = []
                by_prompt[p].append(item)
            grouped_worker: List[Dict] = []
            grouped_meta: List[Dict] = []
            meta_by_order = {m["_order_index"]: m for m in chunk_meta}
            for p in seen_prompts:
                for item in by_prompt[p]:
                    grouped_worker.append(item)
                    grouped_meta.append(meta_by_order[item["_order_index"]])
            worker_chunks = grouped_worker
            chunk_meta = grouped_meta

        job = {
            "model_dir": self._model_dir,
            "cfg_path": self._cfg_path,
            "model_version": self._model_version,
            "use_fp16": self._use_fp16,
            "use_deepspeed": self._use_deepspeed,
            "use_torch_compile": self._use_torch_compile,
            "use_accel": self._use_accel,
            "num_beams": self._num_beams,
            "diffusion_steps": self._diffusion_steps,
            "temperature": self._temperature,
            "top_p": self._top_p,
            "top_k": self._top_k,
            "repetition_penalty": self._repetition_penalty,
            "max_mel_tokens": self._max_mel_tokens,
            "max_text_tokens_per_segment": self._max_text_tokens_per_segment,
            "device": self._device,
            "chunks": [{k: v for k, v in c.items() if not k.startswith("_")} for c in worker_chunks],
        }

        import threading
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tf:
            json.dump(job, tf)
            job_file = tf.name

        files: List[str] = []
        paused_early = threading.Event()
        cancelled_early = threading.Event()
        try:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(self._engine_root)
            env.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            env.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
            env.setdefault("MODELSCOPE_DOWNLOAD_PARALLELS", "4")

            proc = subprocess.Popen(
                [str(self._python), str(self._worker), "--job-file", job_file],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(self._engine_root),
                env=env,
            )

            stderr_lines: List[str] = []
            stdout_chunks: List[str] = []
            completed_paths: List[str] = []

            def _stream_stderr() -> None:
                assert proc.stderr is not None
                for line in proc.stderr:
                    line = line.rstrip()
                    stderr_lines.append(line)
                    logger.info("[index-tts worker] %s", line)
                    if line.startswith("[CHUNK_DONE] "):
                        done_path = line[len("[CHUNK_DONE] "):]
                        completed_paths.append(done_path)
                        idx = len(completed_paths) - 1
                        if idx < len(chunk_meta):
                            meta = chunk_meta[idx]
                            if callable(cancel_cb) and cancel_cb():
                                cancelled_early.set()
                                proc.terminate()
                                return
                            if callable(pause_cb) and pause_cb():
                                paused_early.set()
                                proc.terminate()
                                return
                            if callable(progress_cb):
                                try:
                                    progress_cb()
                                except Exception:
                                    # JobPaused or other cancellation exception - signal to stop
                                    paused_early.set()
                                    proc.terminate()
                                    return
                            if callable(chunk_cb):
                                chunk_cb(
                                    meta["chunk_index"],
                                    self._callback_payload(meta),
                                    done_path,
                                )

            def _poll_cancel() -> None:
                """Poll cancel/pause between chunks in case no [CHUNK_DONE] arrives quickly."""
                while proc.poll() is None:
                    if callable(cancel_cb) and cancel_cb():
                        cancelled_early.set()
                        proc.terminate()
                        return
                    if callable(pause_cb) and pause_cb():
                        paused_early.set()
                        proc.terminate()
                        return
                    threading.Event().wait(0.5)

            def _read_stdout() -> None:
                assert proc.stdout is not None
                stdout_chunks.append(proc.stdout.read())

            stderr_thread = threading.Thread(target=_stream_stderr, daemon=True)
            stdout_thread = threading.Thread(target=_read_stdout, daemon=True)
            poll_thread = threading.Thread(target=_poll_cancel, daemon=True)
            stderr_thread.start()
            stdout_thread.start()
            poll_thread.start()
            proc.wait()
            stderr_thread.join(timeout=5)
            stdout_thread.join(timeout=5)
            stdout_data = "".join(stdout_chunks)

            if cancelled_early.is_set():
                logger.info("IndexTTS worker terminated early due to cancel — %d chunks completed", len(completed_paths))
                files = [p for p in completed_paths if Path(p).exists()]
            elif paused_early.is_set():
                logger.info("IndexTTS worker terminated early due to pause — %d chunks completed", len(completed_paths))
                files = [p for p in completed_paths if Path(p).exists()]
            elif not stdout_data.strip():
                raise RuntimeError(
                    f"IndexTTS worker produced no output (exit code {proc.returncode}).\n"
                    f"stderr:\n{chr(10).join(stderr_lines) or '(empty)'}"
                )
            else:
                response = json.loads(stdout_data.strip())
                if not response.get("success"):
                    raise RuntimeError(f"IndexTTS worker failed:\n{response.get('error', 'unknown error')}")
                files = response.get("files", [])
        finally:
            try:
                os.unlink(job_file)
            except OSError:
                pass

        if cancelled_early.is_set() or paused_early.is_set():
            return files

        already_reported = set(completed_paths)
        for i, file_path in enumerate(files):
            meta = chunk_meta[i]
            assignment: VoiceAssignment = meta["assignment"]
            fx_settings = VoiceFXSettings.from_payload(assignment.fx_payload)
            if fx_settings and not fx_settings.is_identity():
                try:
                    audio, sr = sf.read(file_path, dtype="float32")
                    audio = self.post_processor.apply_post_pipeline(audio, sr, fx_settings)
                    sf.write(file_path, audio, sr)
                except Exception as exc:
                    logger.warning("FX post-processing failed for %s: %s", file_path, exc)

            if callable(pause_cb) and pause_cb():
                return files

            if file_path not in already_reported:
                if callable(progress_cb):
                    try:
                        progress_cb()
                    except Exception:
                        # JobPaused or other cancellation exception - re-raise so caller handles it
                        raise
                if callable(chunk_cb):
                    chunk_cb(
                        meta["chunk_index"],
                        self._callback_payload(meta),
                        file_path,
                    )

        return files

    def generate_audio(
        self,
        *,
        text: str,
        voice: str = "",
        lang_code: Optional[str] = None,
        speed: float = 1.0,
        sample_rate: Optional[int] = None,
        fx_settings: Optional[VoiceFXSettings] = None,
        spk_audio_prompt: Optional[str] = None,
    ) -> np.ndarray:
        """Generate audio for a single text string (used for previews)."""
        prompt = spk_audio_prompt or self._default_prompt
        if not prompt:
            raise ValueError("IndexTTS requires a reference audio prompt for voice cloning.")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            output_path = tf.name

        job = {
            "model_dir": self._model_dir,
            "cfg_path": self._cfg_path,
            "model_version": self._model_version,
            "use_fp16": self._use_fp16,
            "use_deepspeed": self._use_deepspeed,
            "device": self._device,
            "chunks": [{"text": text, "spk_audio_prompt": prompt, "output_path": output_path}],
        }

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as tf:
            json.dump(job, tf)
            job_file = tf.name

        try:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(self._engine_root)
            env.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
            env.setdefault("MODELSCOPE_DOWNLOAD_PARALLELS", "4")
            result = subprocess.run(
                [str(self._python), str(self._worker), "--job-file", job_file],
                capture_output=True,
                text=True,
                cwd=str(self._engine_root),
                env=env,
            )
            response = json.loads(result.stdout.strip())
            if not response.get("success"):
                raise RuntimeError(f"IndexTTS worker failed:\n{response.get('error', '')}")
        finally:
            try:
                os.unlink(job_file)
            except OSError:
                pass

        audio, sr = sf.read(output_path, dtype="float32")
        try:
            os.unlink(output_path)
        except OSError:
            pass

        if fx_settings and not fx_settings.is_identity():
            audio = self.post_processor.apply_post_pipeline(audio, sr, fx_settings)
        return audio

    def cleanup(self) -> None:
        logger.info("IndexTTSEngine cleanup (subprocess-based, nothing to unload)")

    def _resolve_prompt_path(self, path_str: str) -> Path:
        """Resolve a prompt filename or path to an absolute Path."""
        candidate = Path(path_str)
        if candidate.is_absolute() and candidate.is_file():
            return candidate
        # Try relative to CWD first (handles absolute-looking relative paths)
        if candidate.is_file():
            return candidate.resolve()
        # Try relative to project root (engines/index-tts/../../ = TTS-Story/)
        project_root = self._engine_root.parent.parent
        fallback = project_root / "data" / "voice_prompts" / path_str
        if fallback.is_file():
            return fallback.resolve()
        raise FileNotFoundError(
            f"IndexTTS reference audio not found: {path_str}. "
            f"Checked: {candidate}, {fallback}"
        )

    def _resolve_persona_voice_lock(self, voice_name: Optional[str]) -> Optional[Path]:
        """Reuse a Qwen-designed persona as IndexTTS2's timbre-only prompt."""
        normalized = str(voice_name or "").strip()
        if normalized not in VOICE_PRESETS:
            return None
        project_root = self._engine_root.parent.parent
        cache_dir = project_root / "data" / "voice_locks"
        patterns = (
            f"{normalized}-neutral-*.wav",
            f"{normalized}-{VOICE_PRESETS[normalized].get('default_state', 'neutral')}-*.wav",
            f"{normalized}-*.wav",
        )
        for pattern in patterns:
            candidates = sorted(
                cache_dir.glob(pattern),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            if candidates:
                return candidates[0].resolve()
        return None

    def ensure_persona_voice_locks(self, voice_config: Dict[str, Dict]) -> None:
        """Create missing neutral persona anchors before the PyTorch worker loads."""
        requested: Dict[str, Dict] = {}
        for speaker_key in voice_config or {}:
            assignment = self._voice_assignment_for(voice_config, speaker_key)
            voice_name = str(assignment.voice or "").strip()
            if (
                voice_name in VOICE_PRESETS
                and self._resolve_persona_voice_lock(voice_name) is None
            ):
                requested[voice_name] = {
                    "voice": voice_name,
                    "extra": {
                        "language": (assignment.extra or {}).get("language")
                        or "Chinese",
                    },
                }
        if not requested:
            return

        logger.info(
            "[index-tts] creating %d missing neutral persona anchor(s): %s",
            len(requested),
            ", ".join(sorted(requested)),
        )
        from .qwen3_custom_voice_engine import Qwen3CustomVoiceEngine

        bootstrap = Qwen3CustomVoiceEngine(
            model_id=self._persona_design_model_id,
            clone_model_id=self._persona_clone_model_id,
            default_language="Chinese",
            auto_voice_lock=True,
            stability_temperature=self._persona_stability_temperature,
            stability_top_k=self._persona_stability_top_k,
            stability_top_p=self._persona_stability_top_p,
            stability_seed=self._persona_stability_seed,
        )
        try:
            bootstrap._prepare_voice_locks(
                requested,
                required_states_by_voice={
                    voice_name: {"neutral"} for voice_name in requested
                },
                include_preset_default=False,
                switch_to_clone=False,
            )
        finally:
            bootstrap.cleanup()
            try:
                import mlx.core as mx

                mx.clear_cache()
            except Exception:
                logger.debug("Unable to clear MLX cache after persona bootstrap", exc_info=True)

        still_missing = [
            voice_name
            for voice_name in requested
            if self._resolve_persona_voice_lock(voice_name) is None
        ]
        if still_missing:
            raise RuntimeError(
                "Could not create persona identity anchors for: "
                + ", ".join(still_missing)
            )

    def _resolve_prompt(self, assignment: VoiceAssignment) -> str:
        """Return the best available audio prompt path for this assignment."""
        logger.info("[index-tts] _resolve_prompt: audio_prompt_path=%r default=%r cwd=%s",
                    assignment.audio_prompt_path, self._default_prompt, os.getcwd())
        if assignment.audio_prompt_path:
            try:
                resolved = str(self._resolve_prompt_path(assignment.audio_prompt_path))
                from ..audio_effects import convert_mp3_to_wav_if_needed
                resolved, temp_mp3_conv = convert_mp3_to_wav_if_needed(resolved)
                logger.info("[index-tts] resolved prompt: %s", resolved)
                return resolved
            except FileNotFoundError as e:
                logger.warning("[index-tts] prompt path failed: %s", e)
        persona_prompt = self._resolve_persona_voice_lock(assignment.voice)
        if persona_prompt:
            logger.info(
                "[index-tts] using Qwen persona identity prompt: %s",
                persona_prompt,
            )
            return str(persona_prompt)
        if self._default_prompt:
            try:
                resolved = str(self._resolve_prompt_path(self._default_prompt))
                from ..audio_effects import convert_mp3_to_wav_if_needed
                resolved, temp_mp3_conv = convert_mp3_to_wav_if_needed(resolved)
                logger.info("[index-tts] resolved default prompt: %s", resolved)
                return resolved
            except FileNotFoundError as e:
                logger.warning("[index-tts] default prompt failed: %s", e)
        raise ValueError(
            "IndexTTS requires a reference audio prompt. "
            "Assign a voice prompt, or first generate the selected Chinese "
            "persona once so its local identity cache exists."
        )

    def _voice_assignment_for(
        self, voice_config: Dict[str, Dict], speaker: Optional[str]
    ) -> VoiceAssignment:
        speaker_key = (speaker or "").strip().lower()
        payload = (
            voice_config.get(speaker)
            or voice_config.get(speaker_key)
            or voice_config.get("default")
            or {}
        )
        return VoiceAssignment(
            voice=payload.get("voice"),
            lang_code=payload.get("lang_code"),
            audio_prompt_path=payload.get("audio_prompt_path"),
            fx_payload=payload.get("fx"),
            speed_override=payload.get("speed"),
            extra=payload.get("extra") or {},
        )


__all__ = [
    "IndexTTSEngine",
    "INDEX_TTS_AVAILABLE",
    "INDEX_TTS_UNAVAILABLE_REASON",
    "INDEX_TTS_SAMPLE_RATE",
    "INDEX_TTS_EMOTION_PROFILES",
    "index_tts_emotion_profile",
]
