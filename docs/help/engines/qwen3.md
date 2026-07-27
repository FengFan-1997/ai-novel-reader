# Qwen3-TTS: Custom Voice, Clone, and Design

TTS-Story uses three distinct Qwen3-TTS model modes. **CustomVoice** and **Voice Clone** are selectable job engines. In the Chinese-first Apple Silicon setup, the main Qwen job engine combines VoiceDesign and Base cloning automatically. It builds an adaptive emotion bank for each selected archetype and reuses those local references throughout the manuscript.

## Choose the correct mode

![Voice Creation workspace for designing and previewing Qwen3 voices](../../../static/help/screenshots/voice-creation.png)

*Voice Creation lets you describe, preview, and save a Qwen3 VoiceDesign result for later use.*

- **Qwen3 CustomVoice:** choose one of the speakers reported by the installed CustomVoice model and optionally describe delivery with an instruction such as “calm, warm narration.” This directs an existing identity; it does not invent a new speaker.
- **Qwen3 Voice Clone:** condition the Base model with reference audio. TTS-Story can transcribe the prompt automatically with SenseVoice when no transcript is supplied.
- **Qwen3 VoiceDesign:** describe a voice in [Voice Creation](help:voice-creation), or select one of the 37 original Chinese presets in the main job workflow. For Chinese MLX jobs, the selected design is turned into a reusable local reference automatically; previewing and manual saving are optional.

## Requirements and setup

The normal setup installs the Qwen TTS runtime. Each mode uses a separate 1.7B model by default, so selecting a new mode can trigger another multi-gigabyte download. Apple Silicon uses the local MLX 8-bit builds; other platforms use the PyTorch models. A supported NVIDIA GPU is strongly recommended for the PyTorch path. CPU is selectable but can be impractically slow for long work.

The defaults are:

- Chinese-first Apple Silicon job engine and Voice Creation: `mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-8bit`
- Optional built-in-speaker mode: `mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit`
- Apple Silicon clone: `mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit`
- CUDA/PyTorch uses the corresponding `Qwen/Qwen3-TTS-12Hz-1.7B-*` models.

Open [Settings → Engine Settings](app:settings/qwen3), leave Device at `auto`, and use the default model IDs unless deliberately testing a compatible replacement.

## Controls TTS-Story exposes

Both job modes share a 500-character chunk target and expose **Device**, **DType**, **Attention**, and **Default Language**.

- **bfloat16** is the initial dtype and is appropriate on supported recent GPUs. Try float16 if the GPU lacks good bfloat16 support. Float32 uses substantially more memory.
- **Flash Attention 2** can reduce memory use and improve speed, but it requires a compatible GPU, half-precision dtype, and a successful optional installation. If initialization reports a FlashAttention error, select **eager** rather than repeatedly retrying the job.
- **Auto language** lets the model infer or use its normal behavior. An explicit language can improve consistency when the manuscript is known to be monolingual.
- **Default Instruction** applies to CustomVoice. Per-speaker instructions can describe pace, emotion, or delivery.
- **Default Prompt** and **Prompt Transcript** apply to Clone. A per-speaker prompt takes priority.

The speaker and language choices shown by TTS-Story are built-in compatibility lists. The metadata endpoint deliberately does not load the large model, so a custom replacement model may support a different set of choices than the interface displays.

## Effective-use tips

1. Use CustomVoice when a built-in identity is acceptable and consistent instruction control matters.
2. Keep instructions short and non-conflicting. “Calm, intimate narration” is more reliable than a paragraph of competing traits.
3. For Clone, use clean single-speaker audio and verify the automatic transcript. A transcript mismatch can reduce similarity or intelligibility.
4. Start with 500-character chunks. Reduce the target if long sentences cause drift or memory pressure.
5. Test dtype and attention changes with the same passage. A successful first sample is more important than the theoretically fastest setting.
6. Chinese MLX jobs automatically classify each line as neutral, bright, gentle, shy, cold, dangerous, angry, or whisper. Explicit emotion tags and per-character manual choices override automatic classification.
7. Every emotional reference for a character shares the same identity seed and persona constraints. Emotion is directed through breath, emphasis, intensity, and rhythm rather than a different age, pitch base, or resonance. Weak adjacent lines inherit the previous state to avoid rapid switching.
8. The bank is adaptive: neutral and the persona's default state are prepared first, while other states are generated only when the manuscript uses them. The first use of a new state is slower; later chunks and jobs reuse its cached reference.

For Chinese novels, Voice Creation also provides 37 original casting
archetypes and eight acting states. The presets are grouped by Honkai:
Star Rail persona references, Genshin Impact persona references, and general
audiobook narrators. Persona references help casting only: the instructions do
not request an official character voice or clone a performer.

Speaker profiles can be matched to these archetypes automatically. The matcher
uses personality, age/gender direction, occupation, emotional contrast, and
explicit persona references. Native Mandarin pacing is enforced across all
presets. Direct VoiceDesign generation retries a grossly slow take once; the
automatic identity-lock path uses the matching cached emotional reference for
each manuscript chunk instead of redesigning a speaker on every chunk. The
library's chunk review shows the chosen acting state, whether it was manual,
automatic, inherited from the adjacent line, or the persona default, plus the
decision confidence and cue.

## Time, privacy, and limitations

The first Chinese identity-lock job downloads and loads both the VoiceDesign and Base 8-bit models. Creating a new persona adds reference-generation passes for neutral and its default state. Other acting states are added only when needed. Later chunks and later jobs using the same persona and state are a better speed measurement.

After model downloads, synthesis, design, and automatic prompt transcription run locally. There is no provider usage fee and manuscript text is not submitted to a cloud TTS service.

The automatic emotion bank is a generated local cache, not a trained multi-style speaker model. Shared identity seeds and persona constraints reduce within-book drift, but independently generated emotional references can still vary slightly and do not guarantee an exact official character or performer likeness. Exact real-person cloning still requires authorized source audio. Supported languages and speakers depend on the installed model, and output quality can vary across languages.

## Authoritative reference

- [Qwen3-TTS official repository](https://github.com/QwenLM/Qwen3-TTS)
