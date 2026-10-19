#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"
rvc_dir="$project_dir/data/rvc"
venv_dir="$rvc_dir/venv"
model_dir="$rvc_dir/yae_miko"
asset_manifest="$project_dir/model-assets.json"
asset_file_url() {
    python3 - "$asset_manifest" "$1" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
asset = next(item for item in manifest["assets"] if item["id"] == "yae_miko_rvc_community_model")
file_info = next(item for item in asset["files"] if item["name"] == sys.argv[2])
print(file_info["url"])
PY
}
model_url="$(asset_file_url Yae_MikoJP.pth)"
index_url="$(asset_file_url Yae_MikoJP.index)"

mkdir -p "$model_dir"

if [[ ! -x "$venv_dir/bin/python" ]]; then
    if command -v python3.10 >/dev/null 2>&1; then
        python3.10 -m venv "$venv_dir"
    elif command -v conda >/dev/null 2>&1; then
        conda create --yes --prefix "$venv_dir" python=3.10 pip
    else
        echo "需要 Python 3.10。请先安装 Python 3.10 或 Miniforge/Conda，再重新运行此脚本。" >&2
        exit 1
    fi
fi

"$venv_dir/bin/python" -m pip install "pip<24.1" "setuptools<81"
"$venv_dir/bin/python" -m pip install "rvc-python==0.1.5"
if [[ "$(uname -s)" == "Darwin" ]]; then
    "$venv_dir/bin/python" -m pip install "torch==2.1.1" "torchaudio==2.1.1"
fi

download_model_file() {
    local source_url="$1"
    local target_path="$2"
    if [[ -s "$target_path" ]]; then
        echo "保留已下载模型：$target_path"
        return
    fi
    local partial_path="${target_path}.partial"
    curl --fail --location --retry 3 "$source_url" --output "$partial_path"
    mv "$partial_path" "$target_path"
}

download_model_file "$model_url" "$model_dir/Yae_MikoJP.pth"
download_model_file "$index_url" "$model_dir/Yae_MikoJP.index"

"$venv_dir/bin/python" - <<'PY'
from pathlib import Path
from rvc_python.infer import RVCInference

root = Path.cwd() / "data" / "rvc" / "yae_miko"
assert (root / "Yae_MikoJP.pth").stat().st_size > 1_000_000
assert (root / "Yae_MikoJP.index").stat().st_size > 1_000_000
print("RVC 运行环境与八重神子社区模型已安装。重启应用后自动生效。")
print("提醒：社区模型的声音权利与商用授权需由使用者另行确认。")
PY
