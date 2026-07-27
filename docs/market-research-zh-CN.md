# AI 中文小说有声化：第一轮 GitHub 调研

更新日期：2026-07-27

## 结论

“本地、零 API 费用、中文、多角色、多声线”可以做，但零成本指的是不付 API
费用，不代表零下载、零磁盘或零计算时间。当前最合适的产品骨架仍是 TTS-Story，
在 Apple Silicon 上使用 MLX 版 Qwen3-TTS；短期的产品差异化不应只是“能发声”，
而应是：

1. 中文原文绝不被 LLM 偷改；
2. 角色跨章节保持一致；
3. 每段音频可复听、重生成、替换声线；
4. 后续加入 ASR 回听，自动发现漏字、重复和结巴。

## 对标项目

| 项目 | 许可 | 可借鉴点 | 不直接采用的原因 |
|---|---|---|---|
| [TTS-Story](https://github.com/Xerophayze/TTS-Story) | Apache-2.0（仓库 LICENSE） | Web UI、角色管理、分块重生成、队列和音频库 | 原版偏英文/CUDA，需要补中文与 Apple MLX |
| [tts-audiobook-tool](https://github.com/zeropointnine/tts-audiobook-tool) | MIT | 多种分句策略、生成失败重试、工程化项目保存 | 不是中文多角色优先；产品形态偏终端 |
| [Pandrator](https://github.com/lukaszliniewicz/Pandrator) | AGPL-3.0 | EPUB/PDF、翻译、克隆声线、一体化安装体验 | AGPL 约束更强，只学习产品设计，不复制代码 |
| [VoxNovel](https://github.com/DrewThomasson/VoxNovel) | MIT | 角色—声线映射、人工校正角色归属 | BookNLP 管线以英文为主，不适合作为中文主解析器 |
| [AudioBookGenerator](https://github.com/JiaruiHu0102/AudioBookGenerator) | MIT | 中文标点分句、GPT-SoVITS、多角色桌面流程 | 依赖较重，Apple Silicon 零门槛不足 |
| [qwen3-tts-audiobook](https://github.com/bluefermion/qwen3-tts-audiobook) | MIT | Qwen3-TTS、多角色脚本、ASR 回听与自动重试 | 默认 CUDA，验证模型会额外占磁盘和算力 |
| [novel_reader](https://github.com/lpsandrea02/novel_reader) | 未标许可 | 中文学习、MLX Qwen-TTS/Qwen-ASR 方向相同 | 无明确许可证，因此不复制代码 |
| [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) | Apache-2.0 | 中文、表达控制、克隆/设计声线 | 只是模型层，不是完整小说产品 |
| [mlx-audio](https://github.com/Blaizzy/mlx-audio) | MIT | Apple Silicon 本地推理 | 只是推理基础设施 |

## 本轮已经吸收的设计

- 从中文项目的做法中确认：中文必须按字符预算并优先在 `。！？；` 处分句，不能按
  空格统计“单词”。
- 从 VoxNovel 确认：自动角色归属一定会错，界面必须保留逐段人工校正和固定
  “角色—声线”映射。
- 从 qwen3-tts-audiobook 和 tts-audiobook-tool 确认：高质量产品需要生成后验证和
  自动重试。当前分支先加入原文保真闸门；ASR 回听列为下一阶段。
- 不从无许可证仓库或 AGPL 仓库复制实现。

## 公版小说测试集

可复现脚本：`python scripts/test_public_domain_novels.py`

- [《三國志演義》Project Gutenberg #23950](https://www.gutenberg.org/ebooks/23950)
- [《聊齋志異》Project Gutenberg #51828](https://www.gutenberg.org/ebooks/51828)
- [《儒林外史》Project Gutenberg #24032](https://www.gutenberg.org/ebooks/24032)

测试会下载到被 Git 忽略的 `.cache/public-domain-novels/`，检查章节识别、长文本
切块上限，以及去除空白后原文是否逐字保留。它不会把整本小说提交进仓库。

## 尚未被证明的部分

- Qwen 文本模型和 Qwen3-TTS 权重尚未完整下载，因此真实整章的角色判断和最终
  音质仍未完成验收。
- 0.6B/8-bit TTS 的优势是本地成本低；它是否达到“像正常人”的主观标准，只能靠
  真实试听 AB 测试判断。
- ASR 自动回听会提升可靠性，但要再下载一个识别模型；应作为可选质量模式，避免
  破坏“低门槛”。

## 第二轮：为什么“识别出情绪”仍然听不出情绪

这一轮找到的是模型与接线问题，不只是提示词问题：

- [Qwen3-TTS 官方模型表](https://github.com/QwenLM/Qwen3-TTS/blob/main/README.md)
  明确区分了 Base、VoiceDesign 和 CustomVoice：Base 可以克隆声纹，但没有
  Instruction Control。官方
  [Discussion #231](https://github.com/QwenLM/Qwen3-TTS/discussions/231)
  也复现了“先设计声音，再用 Base 克隆时情绪指令无效”的同类问题。
- 上游 TTS-Story 文档写到 IndexTTS2 情绪控制，但当时的适配器把它标为
  `supports_emotion_tags=False`，worker 调用也没有传任何情绪参数。也就是说，
  前端即使判断出“愤怒”，合成器实际上仍收到普通朗读请求。
- [IndexTTS2 官方实现](https://github.com/index-tts/index-tts)把说话人身份与情绪
  分成独立条件，支持八维情绪向量。这比“为每种情绪重新生成一条参考音频”更适合
  保持同一人物。

论文侧也支持用户的听感判断：

- [跨模态情绪研究](https://aclanthology.org/2026.findings-eacl.136/)发现，文字与
  音频情绪并不总是一一对应，只有效价维度呈现较强相关；单句文字标签不能代替
  真实语音表演。
- [上下文情绪 TTS 研究](https://aclanthology.org/2026.findings-acl.940/)指出，
  单句级情绪标签会漏掉细腻变化；对话上下文和开放式情绪描述能改善自然度与情绪
  准确性。
- [有声书表达研究](https://aclanthology.org/2026.findings-acl.308/)表明，小说里
  “低声说、厉声喝道”等说话动词和副词，是提升对白表达力和可懂度的重要线索。

因此产品改成五层：

`当前对白 + 相邻旁白 + 上一句状态 → 上下文表演导演 → 本地 0.6B 基础情绪分析 → 两路向量按表演类别融合 → 固定人物声纹 + 连续状态平滑`

真文本验证还发现了语义分类器的边界：自然、兴奋、愤怒识别准确，但“危险的克制”和
“娇羞的犹豫”容易被八分类模型当成悲伤。产品因此不让分类器覆盖导演结果，而是对
自然、兴奋、愤怒给予较高语义权重，对娇羞、冷峻、危险、温柔、低声给予较高导演权重。
这一步直接针对“文字判断对了一半，但声音演错方向”的问题。

情绪向量不会无限加大。IndexTTS 社区问题记录显示，强度过高会出现“有情绪就不像
原来的人”或表演不自然；产品把模型混合强度限制在 0.6 以内，并允许用户整体降低。
