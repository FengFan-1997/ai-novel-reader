"""Local Qwen3-TTS CustomVoice engine adapter."""
from __future__ import annotations

import gc
import hashlib
import json
import logging
import os
import platform
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import soundfile as sf
try:
    import torch
except ImportError:  # pragma: no cover - optional on Apple Silicon/MLX
    torch = None  # type: ignore[assignment]

from .base import EngineCapabilities, TtsEngineBase, VoiceAssignment
from ..audio_effects import AudioPostProcessor, VoiceFXSettings
from ..chinese_voice_director import (
    ACTING_STATES,
    PACING_RETRY_INSTRUCTION,
    VOICE_PRESETS,
    compose_voice_instruction,
    emotion_reference_text,
    has_abnormally_slow_delivery,
    infer_acting_state,
    resolve_acting_state,
)

logger = logging.getLogger(__name__)

# Disable HuggingFace Hub symlinks warning on Windows
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

try:
    from huggingface_hub import snapshot_download
    from qwen_tts import Qwen3TTSModel  # type: ignore

    QWEN3_PYTORCH_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    Qwen3TTSModel = None  # type: ignore[assignment]
    snapshot_download = None  # type: ignore[assignment]
    QWEN3_PYTORCH_AVAILABLE = False

try:
    from mlx_audio.tts.utils import load_model as load_mlx_model  # type: ignore
    QWEN3_MLX_AVAILABLE = (
        platform.system() == "Darwin" and platform.machine().lower() == "arm64"
    )
except ImportError:  # pragma: no cover - optional Apple Silicon dependency
    load_mlx_model = None  # type: ignore[assignment]
    QWEN3_MLX_AVAILABLE = False

QWEN3_AVAILABLE = QWEN3_PYTORCH_AVAILABLE or QWEN3_MLX_AVAILABLE

VOICE_LOCK_CACHE_VERSION = 2
DEFAULT_MLX_CLONE_MODEL = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit"


class Qwen3CustomVoiceEngine(TtsEngineBase):
    """Offline Qwen3-TTS CustomVoice engine."""

    name = "qwen3_custom"
    capabilities = EngineCapabilities(
        supports_voice_cloning=False,
        supports_emotion_tags=True,
    )

    def __init__(
        self,
        *,
        device: str = "auto",
        model_id: str = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
        dtype: str = "bfloat16",
        attn_implementation: str = "flash_attention_2",
        default_language: str = "Auto",
        default_instruct: Optional[str] = None,
        auto_voice_lock: bool = True,
        clone_model_id: str = DEFAULT_MLX_CLONE_MODEL,
        stability_temperature: float = 0.35,
        stability_top_k: int = 20,
        stability_top_p: float = 0.9,
        stability_seed: int = 20260727,
        voice_lock_cache_dir: Optional[str] = None,
    ):
        if not QWEN3_AVAILABLE:
            raise ImportError(
                "Qwen3-TTS is unavailable. Install mlx-audio on Apple Silicon "
                "or qwen-tts on a CUDA machine."
            )

        self.design_model_id = model_id
        self.clone_model_id = clone_model_id or DEFAULT_MLX_CLONE_MODEL
        self.auto_voice_lock = bool(auto_voice_lock)
        self.stability_temperature = max(0.05, min(float(stability_temperature), 1.5))
        self.stability_top_k = max(1, int(stability_top_k))
        self.stability_top_p = max(0.05, min(float(stability_top_p), 1.0))
        self.stability_seed = int(stability_seed)
        self.voice_lock_cache_dir = Path(
            voice_lock_cache_dir
            or Path(__file__).resolve().parents[2] / "data" / "voice_locks"
        )
        self._using_voice_lock_clone = False
        self._voice_locks: Dict[str, Dict[str, str]] = {}

        wants_mlx = str(model_id).lower().startswith("mlx-community/")
        apple_silicon = platform.system() == "Darwin" and platform.machine().lower() == "arm64"
        self.backend = "mlx" if (wants_mlx or (apple_silicon and QWEN3_MLX_AVAILABLE)) else "pytorch"
        if self.backend == "mlx":
            if not QWEN3_MLX_AVAILABLE or load_mlx_model is None:
                raise ImportError(
                    "This MLX Qwen3 model requires Apple Silicon and mlx-audio. "
                    "Install the zero-cost macOS requirements first."
                )
            if not wants_mlx:
                model_id = "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit"
            logger.info("Loading Qwen3 CustomVoice MLX model=%s", model_id)
            self.model = load_mlx_model(model_id)
            self.device = "mps"
            self.model_id = model_id
            self.default_language = default_language or "Chinese"
            self.default_instruct = default_instruct
            self.post_processor = AudioPostProcessor()
            self._sample_rate = int(getattr(self.model, "sample_rate", 24000))
            self._supported_speakers = self._safe_supported_list("speakers")
            self._supported_languages = self._safe_supported_list("languages")
            return

        if not QWEN3_PYTORCH_AVAILABLE or torch is None:
            raise ImportError("qwen-tts and PyTorch are required for the CUDA Qwen3 backend.")

        resolved_device = self._resolve_device(device)
        if resolved_device.startswith("cuda") and torch.cuda.is_available():
            torch.backends.cudnn.benchmark = True
            logger.info("Enabled cuDNN benchmark mode for faster inference")
        resolved_dtype = self._resolve_dtype(dtype)
        resolved_attn = self._resolve_attn_implementation(attn_implementation)
        logger.info(
            "Loading Qwen3 CustomVoice model=%s device=%s dtype=%s attn=%s",
            model_id,
            resolved_device,
            resolved_dtype,
            resolved_attn or "auto",
        )
        logger.warning(
            "Qwen3 attention debug: device=%s dtype=%s attn=%s",
            resolved_device,
            resolved_dtype,
            resolved_attn or "auto",
        )

        model_path = self._ensure_model(model_id)

        self.model = Qwen3TTSModel.from_pretrained(
            str(model_path),
            device_map=resolved_device,
            dtype=resolved_dtype,
            attn_implementation=resolved_attn or None,
        )
        self._log_attention_backend(resolved_attn)

        self.device = resolved_device
        self.model_id = model_id
        self.default_language = default_language or "Auto"
        self.default_instruct = default_instruct
        self.post_processor = AudioPostProcessor()

        self._sample_rate = None
        self._supported_speakers = self._safe_supported_list("speakers")
        self._supported_languages = self._safe_supported_list("languages")

    @property
    def sample_rate(self) -> int:
        return self._sample_rate or 24000

    @property
    def supported_speakers(self) -> List[str]:
        return list(self._supported_speakers or [])

    @property
    def supported_languages(self) -> List[str]:
        return list(self._supported_languages or [])

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
    ) -> List[str]:
        if sample_rate and sample_rate != self.sample_rate:
            logger.warning(
                "Qwen3 outputs at %s Hz. Requested sample rate %s will be resampled during merge.",
                self.sample_rate,
                sample_rate,
            )

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        files: List[str] = []
        chunk_index = 0
        voice_locks = None
        emotion_plan: Dict[tuple[int, int], Dict[str, object]] = {}
        if self._should_use_auto_voice_lock():
            emotion_plan, required_states = self._plan_chunk_emotions(
                segments,
                voice_config,
            )
            voice_locks = self._prepare_voice_locks(
                voice_config,
                required_states_by_voice=required_states,
            )

        for seg_idx, segment in enumerate(segments):
            speaker = segment["speaker"]
            chunks = segment["chunks"]
            assignment = self._voice_assignment_for(voice_config, speaker)
            fx_settings = VoiceFXSettings.from_payload(assignment.fx_payload)
            voice_name = assignment.voice or self._fallback_speaker()
            language = (assignment.extra.get("language") if assignment.extra else None) or self.default_language
            # Emotion from segment takes priority, then user-provided instruct, then default
            segment_emotion = segment.get("emotion")
            user_instruct = (assignment.extra.get("instruct") if assignment.extra else None)
            if segment_emotion:
                # If both emotion and user instruct exist, combine them
                instruct = f"{segment_emotion}; {user_instruct}" if user_instruct else segment_emotion
            else:
                instruct = user_instruct or self.default_instruct

            if not voice_name:
                raise ValueError("Qwen3 CustomVoice requires a speaker selection.")

            logger.info(
                "Qwen3 CustomVoice segment %s/%s speaker=%s language=%s instruct=%s",
                seg_idx + 1,
                len(segments),
                voice_name,
                language,
                instruct[:50] + "..." if instruct and len(instruct) > 50 else instruct,
            )

            for chunk_idx, chunk_text in enumerate(chunks):
                output_path = output_dir / f"chunk_{chunk_index:04d}.wav"
                emotion_decision = emotion_plan.get((seg_idx, chunk_idx))
                if voice_locks is not None:
                    acting_state = str(
                        (emotion_decision or {}).get("state") or "neutral"
                    )
                    voice_lock = self._voice_lock_for(
                        speaker=voice_name,
                        language=language,
                        instruct=user_instruct,
                        acting_state=acting_state,
                    )
                    audio, sr = self._synthesize_locked(
                        text=chunk_text,
                        language=language,
                        voice_lock=voice_lock,
                    )
                else:
                    audio, sr = self._synthesize(chunk_text, voice_name, language, instruct)
                self._sample_rate = sr
                audio = self.post_processor.apply_post_pipeline(audio, int(sr), fx_settings)
                sf.write(str(output_path), audio, sr)
                files.append(str(output_path))
                chunk_index += 1
                if callable(progress_cb):
                    try:
                        progress_cb()
                    except Exception:
                        # JobPaused or other cancellation exception - re-raise so caller handles it
                        raise
                if callable(chunk_cb):
                    chunk_meta = {
                        "speaker": speaker,
                        "text": chunk_text,
                        "segment_index": seg_idx,
                        "chunk_index": chunk_idx,
                    }
                    if emotion_decision:
                        chunk_meta.update({
                            "emotion": emotion_decision.get("state"),
                            "emotion_label": emotion_decision.get("label"),
                            "emotion_source": emotion_decision.get("source"),
                            "emotion_confidence": emotion_decision.get("confidence"),
                            "emotion_reason": emotion_decision.get("reason"),
                        })
                    chunk_cb(chunk_idx, chunk_meta, str(output_path))

        return files

    def cleanup(self) -> None:  # pragma: no cover
        logger.info("Cleaning up Qwen3 CustomVoice engine resources")
        try:
            if hasattr(self, "model") and self.model is not None:
                del self.model
                self.model = None
        except Exception:
            pass
        gc.collect()
        if torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()

    def generate_audio(
        self,
        *,
        text: str,
        voice: str,
        lang_code: Optional[str] = None,
        speed: float = 1.0,
        sample_rate: Optional[int] = None,
        fx_settings: Optional[VoiceFXSettings] = None,
    ) -> np.ndarray:
        """Generate a single preview clip for the /api/preview endpoint."""
        language = lang_code or self.default_language
        if self._should_use_auto_voice_lock():
            voice_config = {
                "preview": {
                    "voice": voice,
                    "extra": {
                        "language": language,
                        "instruct": self.default_instruct,
                    },
                },
            }
            preview_state = (
                resolve_acting_state(self.default_instruct)
                or str(
                    (VOICE_PRESETS.get(voice) or {}).get("default_state")
                    or "neutral"
                )
            )
            self._prepare_voice_locks(
                voice_config,
                required_states_by_voice={voice: {preview_state}},
            )
            wav, sr = self._synthesize_locked(
                text=text,
                language=language,
                voice_lock=self._voice_lock_for(
                    speaker=voice,
                    language=language,
                    instruct=self.default_instruct,
                    acting_state=preview_state,
                ),
            )
        else:
            wav, sr = self._synthesize(text, voice, language, self.default_instruct)
        self._sample_rate = sr
        return self.post_processor.apply_post_pipeline(wav, int(sr), fx_settings)

    def _voice_assignment_for(self, voice_config: Dict[str, Dict], speaker: str) -> VoiceAssignment:
        payload = voice_config.get(speaker) or voice_config.get("default") or {}
        return VoiceAssignment(
            voice=payload.get("voice"),
            lang_code=payload.get("lang_code"),
            audio_prompt_path=payload.get("audio_prompt_path"),
            fx_payload=payload.get("fx"),
            speed_override=payload.get("speed"),
            extra=payload.get("extra") or {},
        )

    def _synthesize(
        self,
        text: str,
        speaker: str,
        language: str,
        instruct: Optional[str],
    ) -> tuple[np.ndarray, int]:
        if self.backend == "mlx":
            if self._is_voice_design_model():
                voice_instruction = compose_voice_instruction(
                    speaker if speaker in VOICE_PRESETS else None,
                    acting_state=resolve_acting_state(instruct),
                    custom_instruction=instruct,
                )
                self._seed_generation(speaker, voice_instruction, text)
                results = list(self.model.generate(
                    text=text,
                    lang_code=(language or "chinese").lower(),
                    instruct=voice_instruction,
                    **self._design_sampling_kwargs(),
                    verbose=False,
                ))
                if not results:
                    raise RuntimeError("Qwen3 VoiceDesign MLX returned no audio.")
                parts = [
                    np.asarray(result.audio, dtype=np.float32).reshape(-1)
                    for result in results
                ]
                audio = np.concatenate(parts) if len(parts) > 1 else parts[0]
                sample_rate = int(
                    getattr(results[0], "sample_rate", None)
                    or getattr(self.model, "sample_rate", 24000)
                )
                if has_abnormally_slow_delivery(text, len(audio), sample_rate):
                    logger.warning(
                        "Qwen3 VoiceDesign delivery was abnormally slow; retrying speaker=%s",
                        speaker,
                    )
                    self._seed_generation(speaker, voice_instruction, text, retry=True)
                    retry_results = list(self.model.generate(
                        text=text,
                        lang_code=(language or "chinese").lower(),
                        instruct=voice_instruction + PACING_RETRY_INSTRUCTION,
                        **self._design_sampling_kwargs(),
                        verbose=False,
                    ))
                    if retry_results:
                        retry_parts = [
                            np.asarray(result.audio, dtype=np.float32).reshape(-1)
                            for result in retry_results
                        ]
                        retry_audio = (
                            np.concatenate(retry_parts)
                            if len(retry_parts) > 1
                            else retry_parts[0]
                        )
                        if len(retry_audio) < len(audio):
                            audio = retry_audio
                            sample_rate = int(
                                getattr(retry_results[0], "sample_rate", None)
                                or getattr(self.model, "sample_rate", sample_rate)
                            )
                return audio, sample_rate
            results = list(self.model.generate_custom_voice(
                text=text,
                language=(language or "auto").lower(),
                speaker=speaker,
                instruct=instruct or None,
            ))
            if not results:
                raise RuntimeError("Qwen3 MLX returned no audio.")
            parts = [np.asarray(result.audio, dtype=np.float32).reshape(-1) for result in results]
            audio = np.concatenate(parts) if len(parts) > 1 else parts[0]
            sample_rate = int(
                getattr(results[0], "sample_rate", None)
                or getattr(self.model, "sample_rate", 24000)
            )
            return audio, sample_rate

        if self._is_voice_design_model():
            wavs, sr = self.model.generate_voice_design(
                text=text,
                instruct=compose_voice_instruction(
                    speaker if speaker in VOICE_PRESETS else None,
                    acting_state=resolve_acting_state(instruct),
                    custom_instruction=instruct,
                ),
                language=language or "Chinese",
                non_streaming_mode=True,
            )
            return np.asarray(wavs[0], dtype=np.float32), int(sr)

        wavs, sr = self.model.generate_custom_voice(
            text=text,
            language=(language or "auto").lower(),
            speaker=speaker,
            instruct=instruct or "",
        )
        audio = np.asarray(wavs[0], dtype=np.float32)
        return audio, int(sr)

    def _plan_chunk_emotions(
        self,
        segments: List[Dict],
        voice_config: Dict[str, Dict],
    ) -> tuple[
        Dict[tuple[int, int], Dict[str, object]],
        Dict[str, set[str]],
    ]:
        plan: Dict[tuple[int, int], Dict[str, object]] = {}
        required_states: Dict[str, set[str]] = {}
        previous_voice: Optional[str] = None
        previous_state: Optional[str] = None

        for seg_idx, segment in enumerate(segments):
            speaker = segment.get("speaker") or "default"
            assignment = self._voice_assignment_for(voice_config, speaker)
            voice_name = assignment.voice or self._fallback_speaker()
            if not voice_name:
                continue
            extra = assignment.extra or {}
            user_instruct = extra.get("instruct")
            manual_state = resolve_acting_state(user_instruct)
            explicit_emotion = segment.get("emotion")
            preset = VOICE_PRESETS.get(voice_name) or {}
            default_state = str(preset.get("default_state") or "neutral")
            context_before = ""
            context_after = ""
            if seg_idx > 0:
                previous_segment = segments[seg_idx - 1]
                if str(previous_segment.get("speaker") or "").lower() in {
                    "narrator",
                    "旁白",
                }:
                    context_before = " ".join(
                        previous_segment.get("chunks") or []
                    )
            if seg_idx + 1 < len(segments):
                next_segment = segments[seg_idx + 1]
                if str(next_segment.get("speaker") or "").lower() in {
                    "narrator",
                    "旁白",
                }:
                    context_after = " ".join(next_segment.get("chunks") or [])

            for chunk_idx, chunk_text in enumerate(segment.get("chunks") or []):
                adjacent_previous = (
                    previous_state if previous_voice == voice_name else None
                )
                decision = infer_acting_state(
                    chunk_text,
                    explicit_instruction=(
                        explicit_emotion
                        or (user_instruct if manual_state else None)
                    ),
                    default_state=default_state,
                    previous_state=adjacent_previous,
                    context_before=context_before if chunk_idx == 0 else None,
                    context_after=(
                        context_after
                        if chunk_idx == len(segment.get("chunks") or []) - 1
                        else None
                    ),
                )
                plan[(seg_idx, chunk_idx)] = decision
                state_id = str(decision["state"])
                required_states.setdefault(voice_name, set()).add(state_id)
                previous_voice = voice_name
                previous_state = state_id

        # Every selected persona keeps a neutral identity reference plus its
        # natural default. Additional states are created lazily as the novel
        # actually uses them, so the bank grows without an eightfold startup.
        for voice_name in list(required_states):
            required_states[voice_name].add("neutral")
            preset_default = str(
                (VOICE_PRESETS.get(voice_name) or {}).get("default_state")
                or "neutral"
            )
            required_states[voice_name].add(preset_default)
        return plan, required_states

    def _should_use_auto_voice_lock(self) -> bool:
        return bool(
            getattr(self, "auto_voice_lock", False)
            and getattr(self, "backend", None) == "mlx"
            and (
                getattr(self, "_using_voice_lock_clone", False)
                or self._is_voice_design_model()
            )
        )

    def _sampling_kwargs(self) -> Dict[str, object]:
        return {
            "temperature": float(getattr(self, "stability_temperature", 0.35)),
            "top_k": int(getattr(self, "stability_top_k", 20)),
            "top_p": float(getattr(self, "stability_top_p", 0.9)),
            "repetition_penalty": 1.05,
        }

    def _design_sampling_kwargs(self) -> Dict[str, object]:
        """Allow enough VoiceDesign diversity, then let cloning lock the result."""
        return {
            "temperature": max(
                0.5,
                float(getattr(self, "stability_temperature", 0.35)),
            ),
            "top_k": max(30, int(getattr(self, "stability_top_k", 20))),
            "top_p": max(0.92, float(getattr(self, "stability_top_p", 0.9))),
            "repetition_penalty": 1.05,
        }

    def _seed_generation(
        self,
        speaker: str,
        instruction: str,
        text: str,
        *,
        retry: bool = False,
        preserve_voice_identity: bool = False,
    ) -> int:
        if preserve_voice_identity:
            # Every emotional reference for one persona starts from the same
            # deterministic sampling stream. The acting prompt and transcript
            # can change the performance, while the speaker's latent identity
            # is less likely to wander between independently designed clips.
            payload = "\0".join(
                (
                    "voice-identity",
                    speaker or "",
                    str(
                        (VOICE_PRESETS.get(speaker) or {}).get("instruction")
                        or ""
                    ),
                )
            )
        else:
            payload = "\0".join((speaker or "", instruction or "", text or ""))
        digest = hashlib.sha256(payload.encode("utf-8")).digest()
        seed = (
            int(getattr(self, "stability_seed", 20260727))
            + int.from_bytes(digest[:4], "big")
            + (1 if retry else 0)
        ) % (2**31 - 1)
        try:
            import mlx.core as mx

            mx.random.seed(seed)
        except Exception:
            logger.debug("Unable to seed MLX generation", exc_info=True)
        return seed

    def _voice_lock_spec(
        self,
        *,
        speaker: str,
        language: str,
        instruct: Optional[str],
        acting_state: str = "neutral",
    ) -> Dict[str, str]:
        state_id = (
            acting_state if acting_state in ACTING_STATES else "neutral"
        )
        instruction = compose_voice_instruction(
            speaker if speaker in VOICE_PRESETS else None,
            acting_state=state_id,
            custom_instruction=instruct,
        )
        reference_text = emotion_reference_text(speaker, state_id)
        identity = {
            "version": VOICE_LOCK_CACHE_VERSION,
            "design_model_id": str(
                getattr(self, "design_model_id", getattr(self, "model_id", ""))
            ),
            "clone_model_id": str(getattr(self, "clone_model_id", DEFAULT_MLX_CLONE_MODEL)),
            "speaker": speaker,
            "language": (language or "Chinese").lower(),
            "acting_state": state_id,
            "instruction": instruction,
            "reference_text": reference_text,
            "sampling": self._design_sampling_kwargs(),
            "seed": int(getattr(self, "stability_seed", 20260727)),
        }
        encoded = json.dumps(
            identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        cache_key = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        safe_speaker = "".join(
            character if character.isalnum() or character in {"-", "_"} else "_"
            for character in (speaker or "voice")
        ).strip("_") or "voice"
        cache_dir = Path(
            getattr(
                self,
                "voice_lock_cache_dir",
                Path(__file__).resolve().parents[2] / "data" / "voice_locks",
            )
        )
        return {
            "key": cache_key,
            "speaker": speaker,
            "language": language or "Chinese",
            "acting_state": state_id,
            "emotion_label": ACTING_STATES[state_id]["label"],
            "instruction": instruction,
            "reference_text": reference_text,
            "audio_path": str(
                cache_dir / f"{safe_speaker}-{state_id}-{cache_key[:12]}.wav"
            ),
            "metadata_path": str(
                cache_dir / f"{safe_speaker}-{state_id}-{cache_key[:12]}.json"
            ),
        }

    def _voice_lock_for(
        self,
        *,
        speaker: str,
        language: str,
        instruct: Optional[str],
        acting_state: str = "neutral",
    ) -> Dict[str, str]:
        spec = self._voice_lock_spec(
            speaker=speaker,
            language=language,
            instruct=instruct,
            acting_state=acting_state,
        )
        voice_lock = getattr(self, "_voice_locks", {}).get(spec["key"], spec)
        if not Path(voice_lock["audio_path"]).is_file():
            raise RuntimeError(f"Automatic voice lock is missing for speaker '{speaker}'.")
        return voice_lock

    def _prepare_voice_locks(
        self,
        voice_config: Dict[str, Dict],
        *,
        required_states_by_voice: Optional[Dict[str, set[str]]] = None,
        include_preset_default: bool = True,
        switch_to_clone: bool = True,
    ) -> Dict[str, Dict[str, str]]:
        requested: Dict[str, Dict[str, str]] = {}
        required_states_by_voice = required_states_by_voice or {}
        for speaker_key in voice_config or {"default": {}}:
            assignment = self._voice_assignment_for(voice_config, speaker_key)
            voice_name = assignment.voice or self._fallback_speaker()
            if not voice_name:
                continue
            extra = assignment.extra or {}
            states = set(required_states_by_voice.get(voice_name) or {"neutral"})
            states.add("neutral")
            if include_preset_default:
                preset_default = str(
                    (VOICE_PRESETS.get(voice_name) or {}).get("default_state")
                    or "neutral"
                )
                states.add(preset_default)
            for state_id in sorted(states):
                spec = self._voice_lock_spec(
                    speaker=voice_name,
                    language=extra.get("language") or self.default_language,
                    instruct=extra.get("instruct"),
                    acting_state=state_id,
                )
                requested[spec["key"]] = spec

        missing = [
            spec for spec in requested.values()
            if not Path(spec["audio_path"]).is_file()
        ]
        if missing and getattr(self, "_using_voice_lock_clone", False):
            self._replace_mlx_model(self.design_model_id)
            self._using_voice_lock_clone = False

        if missing:
            cache_dir = Path(missing[0]["audio_path"]).parent
            cache_dir.mkdir(parents=True, exist_ok=True)
            for spec in missing:
                logger.info(
                    "Creating automatic emotion voice lock speaker=%s state=%s",
                    spec["speaker"],
                    spec["acting_state"],
                )
                self._seed_generation(
                    spec["speaker"],
                    spec["instruction"],
                    spec["reference_text"],
                    preserve_voice_identity=True,
                )
                results = list(self.model.generate(
                    text=spec["reference_text"],
                    lang_code=(spec["language"] or "chinese").lower(),
                    instruct=spec["instruction"],
                    **self._design_sampling_kwargs(),
                    verbose=False,
                ))
                if not results:
                    raise RuntimeError(
                        f"Qwen3 VoiceDesign could not create a voice lock for "
                        f"'{spec['speaker']}'."
                    )
                parts = [
                    np.asarray(result.audio, dtype=np.float32).reshape(-1)
                    for result in results
                ]
                audio = np.concatenate(parts) if len(parts) > 1 else parts[0]
                sample_rate = int(
                    getattr(results[0], "sample_rate", None)
                    or getattr(self.model, "sample_rate", 24000)
                )
                audio_path = Path(spec["audio_path"])
                temporary_audio = audio_path.with_suffix(".tmp.wav")
                sf.write(str(temporary_audio), audio, sample_rate)
                temporary_audio.replace(audio_path)
                metadata = {
                    "version": VOICE_LOCK_CACHE_VERSION,
                    "speaker": spec["speaker"],
                    "language": spec["language"],
                    "acting_state": spec["acting_state"],
                    "emotion_label": spec["emotion_label"],
                    "reference_text": spec["reference_text"],
                    "instruction": spec["instruction"],
                    "sample_rate": sample_rate,
                }
                metadata_path = Path(spec["metadata_path"])
                temporary_metadata = metadata_path.with_suffix(".tmp.json")
                temporary_metadata.write_text(
                    json.dumps(metadata, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                temporary_metadata.replace(metadata_path)

        self._voice_locks.update(requested)
        if switch_to_clone and not getattr(self, "_using_voice_lock_clone", False):
            self._replace_mlx_model(self.clone_model_id)
            self._using_voice_lock_clone = True
        return requested

    def _replace_mlx_model(self, model_id: str) -> None:
        if load_mlx_model is None:
            raise RuntimeError("MLX model loader is unavailable.")
        old_model = getattr(self, "model", None)
        self.model = None
        if old_model is not None:
            del old_model
        gc.collect()
        try:
            import mlx.core as mx

            mx.clear_cache()
        except Exception:
            logger.debug("Unable to clear the MLX cache during model switch", exc_info=True)
        logger.info("Loading Qwen3 automatic voice-lock model=%s", model_id)
        self.model = load_mlx_model(model_id)
        self._sample_rate = int(getattr(self.model, "sample_rate", 24000))

    def _synthesize_locked(
        self,
        *,
        text: str,
        language: str,
        voice_lock: Dict[str, str],
    ) -> tuple[np.ndarray, int]:
        self._seed_generation(
            voice_lock["speaker"],
            voice_lock["instruction"],
            text,
        )
        results = list(self.model.generate(
            text=text,
            lang_code=(language or "chinese").lower(),
            ref_audio=voice_lock["audio_path"],
            ref_text=voice_lock["reference_text"],
            **self._sampling_kwargs(),
            verbose=False,
        ))
        if not results:
            raise RuntimeError("Qwen3 automatic voice lock returned no audio.")
        parts = [
            np.asarray(result.audio, dtype=np.float32).reshape(-1)
            for result in results
        ]
        audio = np.concatenate(parts) if len(parts) > 1 else parts[0]
        sample_rate = int(
            getattr(results[0], "sample_rate", None)
            or getattr(self.model, "sample_rate", 24000)
        )
        return audio, sample_rate

    def _is_voice_design_model(self) -> bool:
        config = getattr(self.model, "config", None)
        model_type = getattr(config, "tts_model_type", None)
        if model_type:
            return model_type == "voice_design"
        return "voicedesign" in str(
            getattr(self, "model_id", "")
        ).replace("-", "").lower()

    def _ensure_model(self, model_id: str) -> Path:
        local_model_dir = Path(__file__).parent.parent.parent / "models" / "qwen3"
        local_model_dir.mkdir(parents=True, exist_ok=True)
        model_path = local_model_dir / model_id.replace("/", "_")

        if not model_path.exists() or not any(model_path.iterdir()):
            logger.info("Downloading Qwen3 model to %s (this may take a few minutes)...", model_path)
            snapshot_download(
                repo_id=model_id,
                local_dir=str(model_path),
                local_dir_use_symlinks=False,
            )
        return model_path

    def _fallback_speaker(self) -> Optional[str]:
        if self._supported_speakers:
            return self._supported_speakers[0]
        return None

    def _safe_supported_list(self, list_type: str) -> List[str]:
        getter = None
        if list_type == "speakers":
            getter = getattr(self.model, "get_supported_speakers", None)
        if list_type == "languages":
            getter = getattr(self.model, "get_supported_languages", None)
        if callable(getter):
            try:
                return list(getter())
            except Exception:
                logger.warning("Failed to load Qwen3 supported %s", list_type, exc_info=True)
        attribute = getattr(self.model, f"supported_{list_type}", None)
        if attribute:
            try:
                return list(attribute)
            except TypeError:
                logger.warning("Invalid Qwen3 supported_%s metadata", list_type)
        return []

    def _log_attention_backend(self, requested_attn: Optional[str]) -> None:
        try:
            candidates = [
                self.model,
                getattr(self.model, "model", None),
                getattr(self.model, "tts_model", None),
                getattr(self.model, "tts", None),
                getattr(self.model, "inner_model", None),
            ]
            target_model = next(
                (candidate for candidate in candidates if hasattr(candidate, "modules")), None
            )
            config = getattr(target_model or self.model, "config", None)
            config_attn = None
            if config is not None:
                config_attn = getattr(config, "attn_implementation", None) or getattr(
                    config, "_attn_implementation", None
                )
            # Check if flash_attention_2 is registered in transformers dispatch
            dispatch_available = "unknown"
            try:
                from transformers.modeling_utils import ALL_ATTENTION_FUNCTIONS
                dispatch_available = "flash_attention_2" in ALL_ATTENTION_FUNCTIONS
            except Exception:
                pass
            logger.warning(
                "Qwen3 attention audit: requested=%s config=%s dispatch_available=%s model=%s",
                requested_attn or "auto",
                config_attn or "unknown",
                dispatch_available,
                type(target_model or self.model).__name__,
            )
        except Exception:
            logger.warning("Qwen3 attention audit failed", exc_info=True)

    @staticmethod
    def _resolve_device(device: str) -> str:
        if torch is None:
            raise RuntimeError("PyTorch is not installed.")
        candidate = (device or "auto").strip().lower()
        if candidate == "auto":
            return "cuda" if torch.cuda.is_available() else "cpu"
        if candidate.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError("CUDA device requested but no GPU is available.")
        return candidate

    @staticmethod
    def _resolve_dtype(dtype_value: str):
        if torch is None:
            raise RuntimeError("PyTorch is not installed.")
        normalized = (dtype_value or "").strip().lower()
        if normalized in {"bf16", "bfloat16"}:
            return torch.bfloat16
        if normalized in {"fp16", "float16"}:
            return torch.float16
        return torch.float32

    @staticmethod
    def _resolve_attn_implementation(attn_value: Optional[str]) -> Optional[str]:
        normalized = (attn_value or "").strip().lower().replace("-", "_")
        if normalized in {"", "auto"}:
            return None
        if normalized in {"flash_attention_2", "flash_attention2", "flash"}:
            try:
                import flash_attn  # type: ignore
                logger.warning(
                    "flash-attn available (version=%s)",
                    getattr(flash_attn, "__version__", "unknown"),
                )
            except Exception:
                logger.warning(
                    "flash-attn not installed; falling back to eager attention for Qwen3"
                )
                return "eager"
            return "flash_attention_2"
        return normalized


__all__ = [
    "Qwen3CustomVoiceEngine",
    "QWEN3_AVAILABLE",
    "QWEN3_MLX_AVAILABLE",
    "QWEN3_PYTORCH_AVAILABLE",
]
