"""Generate local Chinese casting samples with Qwen3 VoiceDesign on MLX.

This is an audition tool, not a training or character-impersonation script.
It generates the original archetypes defined in ``chinese_voice_director``.

Examples:
    ./.venv/bin/python scripts/generate_chinese_character_samples.py --preset qingxia
    ./.venv/bin/python scripts/generate_chinese_character_samples.py --preset all
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.chinese_voice_director import (  # noqa: E402
    CHINESE_NOVEL_TEST_TEXTS,
    CHINESE_SAMPLE_TEXT,
    PACING_RETRY_INSTRUCTION,
    VOICE_PRESETS,
    compose_voice_instruction,
    has_abnormally_slow_delivery,
)


DEFAULT_MODEL = "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-8bit"
DEFAULT_OUTPUT_DIR = ROOT / "static" / "samples" / "chinese-characters"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Chinese-first original character voice samples."
    )
    parser.add_argument(
        "--preset",
        action="append",
        choices=["all", *VOICE_PRESETS.keys()],
        default=[],
        help="Preset to generate; repeat for several presets or use all.",
    )
    parser.add_argument(
        "--state",
        default=None,
        help="Override the preset's default acting state.",
    )
    parser.add_argument("--text", default=CHINESE_SAMPLE_TEXT)
    parser.add_argument(
        "--novel-test",
        action="store_true",
        help="Use a different in-character Chinese novel line for each preset.",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def selected_preset_ids(values: list[str]) -> list[str]:
    if not values or "all" in values:
        return list(VOICE_PRESETS)
    return list(dict.fromkeys(values))


def generate_one(model, preset_id: str, state: str, text: str) -> tuple[np.ndarray, int]:
    instruct = compose_voice_instruction(preset_id, acting_state=state)
    def run(instruction: str):
        return list(model.generate(
            text=text,
            instruct=instruction,
            lang_code="chinese",
            verbose=False,
        ))

    results = run(instruct)
    if not results:
        raise RuntimeError(f"No audio generated for {preset_id}.")
    parts = [
        np.asarray(result.audio, dtype=np.float32).reshape(-1)
        for result in results
    ]
    audio = np.concatenate(parts) if len(parts) > 1 else parts[0]
    sample_rate = int(
        getattr(results[0], "sample_rate", None)
        or getattr(model, "sample_rate", 24000)
    )
    if has_abnormally_slow_delivery(text, len(audio), sample_rate):
        print(f"Retrying {preset_id}: first take was abnormally slow...")
        retry_results = run(instruct + PACING_RETRY_INSTRUCTION)
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
                    or getattr(model, "sample_rate", sample_rate)
                )
    return audio, sample_rate


def main() -> int:
    args = parse_args()
    try:
        from mlx_audio.tts.utils import load_model
    except ImportError as exc:
        raise SystemExit(
            "mlx-audio is required. Run ./setup-macos-zero-cost.sh first."
        ) from exc

    preset_ids = selected_preset_ids(args.preset)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output_dir / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest = {
                key: value
                for key, value in manifest.items()
                if ":" in key and isinstance(value, dict)
            }
        except (json.JSONDecodeError, OSError):
            manifest = {}
    else:
        manifest = {}

    model = None
    for preset_id in preset_ids:
        preset = VOICE_PRESETS[preset_id]
        state = args.state or str(preset["default_state"])
        text = (
            CHINESE_NOVEL_TEST_TEXTS.get(preset_id, CHINESE_SAMPLE_TEXT)
            if args.novel_test
            else args.text
        )
        suffix = "-novel-test" if args.novel_test else ""
        output_path = args.output_dir / f"{preset_id}-{state}{suffix}.wav"
        manifest_key = f"{preset_id}:{state}{':novel-test' if args.novel_test else ''}"
        if output_path.exists() and not args.overwrite:
            print(f"Skipping existing sample: {output_path.name}")
            info = sf.info(output_path)
            sample_rate = int(info.samplerate)
            duration_seconds = round(float(info.duration), 3)
        else:
            if model is None:
                print(f"Loading {args.model}...")
                model = load_model(args.model)
            print(f"Generating {preset['label']} / {state}...")
            audio, sample_rate = generate_one(model, preset_id, state, text)
            sf.write(output_path, audio, sample_rate)
            duration_seconds = round(len(audio) / sample_rate, 3)
        manifest[manifest_key] = {
            "preset_id": preset_id,
            "name": preset["name"],
            "label": preset["label"],
            "state": state,
            "file": f"/static/samples/chinese-characters/{output_path.name}",
            "sample_rate": sample_rate,
            "duration_seconds": duration_seconds,
            "text": text,
            "model": args.model,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            f"Saved {output_path.name} "
            f"({manifest[manifest_key]['duration_seconds']} seconds)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
