# AI Novel Reader 模型资产交接

审计日期：2026-10-26
项目仓库：<https://github.com/FengFan-1997/ai-novel-reader>
机器可读地址清单：[model-assets.json](../model-assets.json)

## 结论

当前工作配置使用 **Qwen3-TTS 1.7B** 生成语音、**Ollama Qwen3 1.7B** 做本地文本分析；旁白的八重神子 RVC 转换也有本地权重。IndexTTS 和其他 TTS 是项目支持的可选引擎，并非当前主引擎。

本次盘点找到约 **19.79 GiB** 可重新下载的模型权重与模型缓存。清理后保留了代码、运行环境、人物声线锁、声音提示、小说/任务数据和已生成章节音频。删掉权重不会删已生成的音频，但**本机在重新下载相应模型前不能继续用这些模型生成新语音**。

这里说的是磁盘空间。删除模型文件会腾出磁盘，不会自动释放已经驻留在其他进程里的 RAM；本次检查时没有活动中的语音生成进程。

## 本机实际使用的模型

| 用途 | 模型 / 来源 | 清理前本机占用 | 恢复方式 |
| --- | --- | ---: | --- |
| 当前 Qwen3 语音设计 | [`mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-8bit`](https://huggingface.co/mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-8bit) | 约 2.9 GiB | 首次使用自动从 Hugging Face 下载；也可运行 `hf download mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-8bit` |
| 当前 Qwen3 克隆/稳定声线锁 | [`mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit`](https://huggingface.co/mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit) | 约 2.9 GiB | 首次需要克隆/声线锁时自动下载；也可运行 `hf download mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit` |
| 本地文本分析 | [`qwen3:1.7b`](https://ollama.com/library/qwen3) | **0**；`ollama list` 为空 | 安装 Ollama 后运行 `ollama pull qwen3:1.7b` |
| 八重神子旁白转换 | 社区 RVC [`iroaK/RVC2_YaeMiko_GenshinImpact`](https://huggingface.co/iroaK/RVC2_YaeMiko_GenshinImpact) 的 `.pth` + `.index` | 约 177 MiB | 运行 `./scripts/setup-yae-rvc.sh`；下载地址和文件名在 `model-assets.json` |
| RVC 转换辅助权重 | `hubert_base.pt`、`rmvpe.pt`、`rmvpe.onnx`；下载源由 `rvc-python==0.1.5` 的 `download_model.py` 指定 | 约 698 MiB | RVC 初始化时会自动补下载；源地址在 `model-assets.json` |

当前 `config.json` 的 `tts_engine` 是 `qwen3_custom`，使用上表中的 Qwen3 VoiceDesign 和 Base。RVC 开关未在此配置文件里设置，应用默认值为开启；默认模型路径就是上表的 Yae RVC 文件。Yae 社区模型没有可核验的上游 SHA-256，仓库也没有模型卡，声音/数据授权需要使用者单独确认。

Qwen3 的官方原始模型和代码：[`Qwen/Qwen3-TTS`](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign)、[Qwen3-TTS GitHub](https://github.com/QwenLM/Qwen3-TTS)。Mac 当前用的是 MLX 社区提供的 8-bit 转换版本；Windows/CUDA 配置一般使用 Qwen 官方 PyTorch 版本，不能把 MLX 权重当成 CUDA 权重直接用。

## 本机缓存但不是当前主配置

| 模型 | 来源 | 清理前占用 | 说明 |
| --- | --- | ---: | --- |
| Qwen3 1.7B CustomVoice 8-bit | [`mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit`](https://huggingface.co/mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit) | 约 2.9 GiB | 有缓存，当前配置没有选择它 |
| Qwen3 0.6B CustomVoice 8-bit | [`mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit`](https://huggingface.co/mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit) | 约 1.9 GiB | 有缓存，较小的可选/回退模型，不是当前配置 |
| Whisper Tiny MLX | [`mlx-community/whisper-tiny-mlx`](https://huggingface.co/mlx-community/whisper-tiny-mlx) | 约 71 MiB | 本次在项目源码中没有找到对它的引用，是本机缓存残留，不是当前生成所需 |

## IndexTTS 权重和内部子模型

IndexTTS 代码来自 [IndexTTS GitHub](https://github.com/index-tts/index-tts)，主模型为 [IndexTeam/IndexTTS-2](https://huggingface.co/IndexTeam/IndexTTS-2)，另有 [ModelScope 镜像](https://modelscope.cn/models/IndexTeam/IndexTTS-2)。本机 `engines/index-tts/checkpoints/` 总计约 **8.3 GiB**；上游 worker 打印的约 5.5 GB 是主模型估算，不含本机实际存在的全部辅助权重。

其中核实到：

- `gpt.pth` 约 3.2 GiB、`s2mel.pth` 约 1.1 GiB、`qwen0.6bemo4-merge/model.safetensors` 约 1.1 GiB，随主模型仓库下载。
- `facebook/w2v-bert-2.0` 约 2.2 GiB；[Hugging Face](https://huggingface.co/facebook/w2v-bert-2.0) / [ModelScope 映射](https://modelscope.cn/models/AI-ModelScope/w2v-bert-2.0)。
- `amphion/MaskGCT` 的语义 codec 约 169 MiB；[模型页](https://huggingface.co/amphion/MaskGCT)。
- `funasr/campplus` 约 27 MiB；[Hugging Face](https://huggingface.co/funasr/campplus) / [ModelScope 映射](https://modelscope.cn/models/iic/speech_campplus_sv_zh-cn_16k-common)。
- NVIDIA BigVGAN 声码器约 428 MiB；[模型页](https://huggingface.co/nvidia/bigvgan_v2_22khz_80band_256x)。

这些地址和 ModelScope 回退映射均按当前本机 IndexTTS 下载代码核对。选用 IndexTTS 时，worker 会自动重新下载缺失权重；本次清理只移除忽略目录 `engines/index-tts/checkpoints/`，保留其余项目代码和 IndexTTS 虚拟环境。

## 项目支持的其他本地 TTS 地址

下面是源码中可选引擎的模型来源，不代表这些模型曾经在本机下载。本次盘点没有在本机找到它们的权重：

| 可选引擎 | 模型来源 | 备注 |
| --- | --- | --- |
| Chatterbox Turbo | [ResembleAI/chatterbox-turbo](https://huggingface.co/ResembleAI/chatterbox-turbo) | 首次选用本地 Chatterbox 时下载 |
| OmniVoice Clone / Design | [k2-fsa/OmniVoice](https://huggingface.co/k2-fsa/OmniVoice) | 两种模式共用该模型；安装脚本可选择预下载 |
| VoxCPM 1.5 | [openbmb/VoxCPM1.5](https://huggingface.co/openbmb/VoxCPM1.5) | 首次选用时下载 |
| Dot.TTS | [`rednote-hilab/dots.tts-soar`](https://huggingface.co/rednote-hilab/dots.tts-soar) | 当前 HF 地址会跳转到 [`dots-studio/dots.tts-soar`](https://huggingface.co/dots-studio/dots.tts-soar) |
| KittenTTS | 配置文件选 [micro-0.8](https://huggingface.co/KittenML/kitten-tts-micro-0.8)；引擎默认值和 Windows 安装预取却是 [mini-0.8](https://huggingface.co/KittenML/kitten-tts-mini-0.8) | 这是仓库当前的配置不一致；若使用 KittenTTS，需先统一模型 ID。运行包：[GitHub Release](https://github.com/KittenML/KittenTTS/releases/download/0.8/kittentts-0.8.0-py3-none-any.whl)；`PREFETCH_KITTEN_TTS_MODEL=0` 可跳过预取 |
| Pocket TTS | [kyutai/pocket-tts](https://huggingface.co/kyutai/pocket-tts) | 下载前需要接受模型仓库条款；预置提示音在 [kyutai/tts-voices](https://huggingface.co/kyutai/tts-voices) |
| Kokoro | [hexgrad/Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) | 项目：[hexgrad/kokoro](https://github.com/hexgrad/kokoro) |

可选参考音频转写模型 [iic/SenseVoiceSmall](https://modelscope.cn/models/iic/SenseVoiceSmall) 由 FunASR 在 Qwen3 Clone、VoxCPM 或 Dot.TTS 需要自动转写提示音频时按需下载。本次没有在项目本地缓存中找到它。

## 在线服务（不下载本地模型权重）

| 服务 | 官方目录/说明 | 本地存储情况 |
| --- | --- | --- |
| Ollama Qwen3 | [模型库](https://ollama.com/library/qwen3) | 本地模型；本机目前没有下载，未来 `ollama pull` 后会占空间 |
| Gemini | [Gemini API 模型目录](https://ai.google.dev/gemini-api/docs/models) | 云端 API，不下载权重 |
| Azure Speech | [Azure Text-to-Speech](https://learn.microsoft.com/azure/ai-services/speech-service/text-to-speech) | 云端语音服务，不下载权重 |
| ElevenLabs | [模型目录](https://elevenlabs.io/docs/models) | 云端 API，不下载权重 |
| Replicate | [Replicate](https://replicate.com/) | 由托管服务运行模型，不在本机保存权重 |
| Edge TTS | [edge-tts 客户端](https://github.com/rany2/edge-tts) | 连接在线语音服务，不下载本地 TTS 权重 |
| OpenRouter | [模型目录](https://openrouter.ai/models) | 云端 LLM API，不下载权重 |

## 本次释放空间的范围

清理前通过 `du` 逐项检查，以下模型和缓存合计约 **19.79 GiB**：

1. `~/.cache/huggingface/hub/` 下四个 Qwen3 模型仓库缓存，以及无项目引用的 `whisper-tiny-mlx` 缓存，共约 10.7 GiB。
2. `engines/index-tts/checkpoints/`，约 8.3 GiB。IndexTTS worker 会在下次使用时从上表来源重建。
3. `data/rvc/yae_miko/Yae_MikoJP.pth` 与 `.index`，约 177 MiB。要再次使用八重神子 RVC 旁白需重新运行安装脚本。
4. `data/rvc/venv/lib/python3.10/site-packages/rvc_python/base_model/` 的 HuBERT/RMVPE 权重，约 698 MiB；RVC 初始化时会从 `rvc-python` 下载代码指定的地址。
5. `data/rvc/venv/lib/python3.10/site-packages/torchcrepe/assets/` 的两个可选 CREPE 权重，约 87 MiB。当前默认音高提取使用 RMVPE；只有选择 CREPE 时才需要。若将来需要但包没有自动恢复，可在 RVC 环境中重装 `torchcrepe`。

本次**不删除** `data/voice_locks/`、`data/voice_prompts/`、`static/audio/`、`data/jobs/`、SQLite 任务记录、小说源文件、代码或 Python 虚拟环境。清理前 `static/audio/` 约 140 MiB、声线锁约 84 MiB、提示音约 3.7 MiB；这些资产与模型权重分开保存。

## 在另一台电脑恢复

先安装运行环境和代码。Mac Apple Silicon：

```bash
git clone --branch codex/zero-cost-cn https://github.com/FengFan-1997/ai-novel-reader.git
cd ai-novel-reader
./setup-macos-zero-cost.sh
./run-macos-zero-cost.sh
```

`setup-macos-zero-cost.sh` 会安装基础 Python/FFmpeg/Ollama 环境并拉取配置中的 Ollama 模型。若主界面选择 Qwen3，首次生成时会按 `config.json` 下载 VoiceDesign 权重；首次创建或调用稳定声线锁时还会下载 Base 权重。也可用上表 `hf download <model-id>` 命令提前下载。

若需要恢复旁白的 Yae RVC 转换：

```bash
./scripts/setup-yae-rvc.sh
```

若改用 IndexTTS、VoxCPM、OmniVoice、Dot.TTS、KittenTTS、Pocket TTS 或 Kokoro，只在设置中选用对应引擎并按其安装步骤运行；它们会从上表所列源下载自己的权重。首次下载前应确认足够磁盘空间和网络可用。

NVIDIA Windows 可从同一仓库运行 `setup.bat`，随后运行 `run.bat`。Windows 需要 Ollama 做本地文本分析时，先从 [Ollama Windows 下载页](https://ollama.com/download/windows) 安装，再运行 `ollama pull qwen3:1.7b`。MLX 格式只用于 Apple Silicon；Windows/CUDA 会使用 Qwen 官方 PyTorch 模型版本。

## Git 与安全边界

推到 GitHub 的只有本交接文档、机器可读来源清单和代码。**不上传模型权重、`.env`、API 密钥、声线锁、提示录音、小说正文、生成音频或本机任务数据库。**不同模型仓库的许可各不相同；第三方声线模型尤其需要单独核对授权。Hugging Face 源未锁定 revision 或 SHA-256 时，未来重新下载的文件可能与这次审计时不同。

若 GitHub 版本的交接记录与代码不一致，以当前仓库中的 `config.json`、`src/engines/`、安装脚本和 [model-assets.json](../model-assets.json) 为准；不要把本机的整个 `config.json` 当作模型备份上传，因为配置里可能包含服务密钥。
