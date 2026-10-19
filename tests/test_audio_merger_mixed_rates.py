import shutil
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from src.audio_merger import AudioMerger


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")
def test_merge_preserves_duration_for_mixed_qwen_and_rvc_sample_rates(
    tmp_path: Path,
):
    qwen_path = tmp_path / "qwen-24k.wav"
    rvc_path = tmp_path / "rvc-48k.wav"
    output_path = tmp_path / "chapter.mp3"
    sf.write(qwen_path, np.zeros(24000, dtype=np.float32), 24000)
    sf.write(rvc_path, np.zeros(48000, dtype=np.float32), 48000)

    AudioMerger(crossfade_ms=0).merge_wav_files(
        [str(qwen_path), str(rvc_path)],
        str(output_path),
        format="mp3",
        cleanup_chunks=False,
    )

    assert output_path.is_file()
    assert AudioMerger().get_duration(str(output_path)) == pytest.approx(2.0, abs=0.08)
    assert not list(tmp_path.glob("*-normalized-*"))
