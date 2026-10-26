import json
from pathlib import Path


def test_model_manifest_covers_setup_and_runtime_assets():
    project = Path(__file__).resolve().parents[1]
    manifest = json.loads((project / "model-assets.json").read_text(encoding="utf-8"))
    assets = {asset["id"]: asset for asset in manifest["assets"]}

    assert manifest["bootstrap"]["ollama"]["config_key"] == "llm_local_model"
    assert manifest["bootstrap"]["index_tts_repository"].startswith("https://github.com/")
    assert {
        "qwen3_tts",
        "ollama_character_analysis",
        "index_tts2",
        "yae_miko_rvc_community_model",
    } <= set(assets)
    assert "qwen3_custom_model_id" in assets["qwen3_tts"]["config_keys"]
    assert assets["index_tts2"]["repository"] == "IndexTeam/IndexTTS-2"
    assert all(item["sha256"] is None for item in assets["yae_miko_rvc_community_model"]["files"])
    qwen_models = {item["model_id"]: item for item in assets["qwen3_tts"]["models"]}
    assert "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-8bit" in qwen_models
    assert "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit" in qwen_models
    index_aux = {item["model_id"] for item in assets["index_tts2_auxiliary_models"]["models"]}
    assert {"facebook/w2v-bert-2.0", "amphion/MaskGCT", "nvidia/bigvgan_v2_22khz_80band_256x"} <= index_aux
    assert len(assets["rvc_helper_models"]["models"]) == 3
    assert assets["rvc_helper_models"]["download_source_code"] == "https://github.com/daswer123/rvc-python"
    assert "models--<owner>--<model>" in assets["qwen3_tts"]["local_path"]
    assert "kitten-tts-micro-0.8" in assets["kitten_tts_optional"]["model_id"]
    assert "kitten-tts-mini-0.8" in assets["kitten_tts_optional"]["setup_prefetch_model_id"]
    assert {
        "chatterbox_turbo_optional",
        "omnivoice_optional",
        "voxcpm_optional",
        "dots_tts_optional",
        "kitten_tts_optional",
        "pocket_tts_optional",
        "kokoro_optional",
    } <= set(assets)
    assert manifest["online_services_without_local_model_weights"]


def test_install_scripts_read_third_party_sources_from_manifest():
    project = Path(__file__).resolve().parents[1]
    macos = (project / "setup-macos-zero-cost.sh").read_text(encoding="utf-8")
    rvc = (project / "scripts/setup-yae-rvc.sh").read_text(encoding="utf-8")
    windows = (project / "setup.bat").read_text(encoding="utf-8")

    assert 'asset_manifest="$project_dir/model-assets.json"' in macos
    assert 'asset_manifest="$project_dir/model-assets.json"' in rvc
    assert "ollama pull \"$ollama_model\"" in macos
    assert "ConvertFrom-Json" in windows
    assert "$m.bootstrap.index_tts_repository" in windows
    assert 'git clone "!INDEX_TTS_REPO!"' in windows
