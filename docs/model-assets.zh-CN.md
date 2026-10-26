# 模型与声线资产来源

> 完整模型盘点、下载地址、机器恢复步骤及本机模型清理记录见 [模型资产交接文档](./model-assets-handoff.zh-CN.md)。

另一台电脑不能只拉 Git 仓库后立刻生成。Git 只包含应用代码和本清单；模型权重及本机声线锁不会提交到仓库，也不会上传到 R2。按平台安装运行环境后，首次使用相应引擎时还需要联网下载模型。

`model-assets.json` 是安装脚本所需外部资产来源的机器可读清单。macOS 安装脚本从中读取 Ollama 模型及 IndexTTS 仓库地址；Windows 安装脚本从中读取 IndexTTS 仓库地址；可选 RVC 安装脚本从中读取模型文件地址。Qwen3-TTS 与 IndexTTS 权重的运行时仓库 ID 仍以 `config.json` 和引擎默认值为准，可由用户在设置中更改。

| 资产 | 来源与触发方式 | 本机位置 | 完整性说明 |
| --- | --- | --- | --- |
| Qwen3-TTS | `config.json` 的 `qwen3_custom_model_id`、`qwen3_clone_model_id`、`qwen3_voice_design_model_id`；引擎首次加载时经 Hugging Face Hub 下载 | `models/qwen3/` | Hub 提供仓库版本元数据；当前配置不固定仓库 commit 或项目级 SHA-256 |
| Ollama Qwen3 1.7B | `setup-macos-zero-cost.sh` 按 `config.json` 的 `llm_local_model`（缺省 `qwen3:1.7b`）执行 `ollama pull` | Ollama 管理 | 由 Ollama 管理下载；项目未固定模型 digest |
| IndexTTS-2 | 首次使用时由 IndexTTS worker 下载 `IndexTeam/IndexTTS-2`（约 5.5 GB） | `engines/index-tts/checkpoints/` | 运行时用 Hub 元数据；项目未固定仓库 commit 或 SHA-256 |
| 八重神子 RVC 社区模型（可选） | 手动运行 `scripts/setup-yae-rvc.sh`，从清单所列 Hugging Face 社区仓库下载 `.pth` 与 `.index` | `data/rvc/yae_miko/` | 清单未固定上游 SHA-256；安装脚本只做非空/最小体积检查。社区模型不代表官方授权 |

## 安装

- Apple Silicon Mac：运行 `./setup-macos-zero-cost.sh`，之后运行 `./run-macos-zero-cost.sh`。该安装步骤安装 Python、FFmpeg、Ollama 与 IndexTTS 代码环境，并拉取 Ollama 对话分析模型；Qwen3-TTS / IndexTTS 权重按首次使用下载。
- NVIDIA Windows：运行仓库已有的 `setup.bat`，完成后用 `run.bat` 启动。安装器会检测 NVIDIA GPU 并安装对应 PyTorch/CUDA；Qwen3/IndexTTS 权重仍在首次使用时从各自 Hugging Face Hub 下载。克隆仓库里的 macOS `mlx-community/*` Qwen 模型名会在非 Apple Silicon 运行时映射为对应 PyTorch 模型默认值，原 `config.json` 不会被启动过程改写。Windows 的 `setup.bat` 不安装 Ollama；若需要本地人物/对白分析，请从 [Ollama Windows 下载页](https://ollama.com/download/windows) 安装 Ollama，再运行 `ollama pull qwen3:1.7b`（或 `config.json` 中配置的 `llm_local_model`）。建议使用 NVIDIA GPU；CPU 可运行但长篇生成会很慢。
- RVC：只在确实需要旁白转换时额外运行对应脚本。它单独安装 Python 3.10 环境和社区声线模型，不是基础生成的必要条件。

下载量因平台、设置的模型和引擎而不同；Qwen3 权重、IndexTTS 权重与 Ollama 模型都可能占用数 GB。请先确认网络与可用磁盘空间，避免在空间不足的电脑上同时安装多个 TTS 引擎。

## 不随 Git 同步的本地资产

- `data/voice_locks/` 保存本机生成的 Qwen3 稳定声线锁；`.gitignore` 会排除它们。新电脑会使用本机模型和提示重新生成声线锁，声音不保证跨设备逐位一致。
- `data/voice_prompts/`、`data/rvc/`、`models/`、Hugging Face 缓存和 `static/audio/` 均为本机资产/输出，不纳入 Git。R2 社区库仅负责章节音频缓存，不存储或分发这些模型权重、提示音频或声线锁。
- 请勿把个人小说源文、生成章节音频、模型权重、`.env`、API token、私钥或本机配置密钥提交到 Git。
