# IndexTTS

TTS-Story uses IndexTTS2 as a local English-and-Chinese zero-shot cloning and
emotional-reading engine. It runs in its own environment and uses either a
reference from the shared Voice Prompts library or a Qwen-designed Chinese
persona anchor.

## Best for

- Local English or Chinese reference cloning
- Same-speaker emotional dialogue: natural, bright, gentle, shy, cold,
  dangerous, angry, and whisper
- Chinese fiction where nearby narration such as “she whispered” or “he
  shouted angrily” should affect the following line
- Users with an NVIDIA GPU who want detailed speed/quality controls
- Apple Silicon users who accept slower local generation for stronger
  expression
- Rebuilding individual chunks with the same reference identity

The adapter keeps emotion independent from the speaker prompt. Automatically
directed dialogue uses IndexTTS2's local 0.6B semantic emotion analyser on the
line, nearby narration, and continuity hint. Because that classifier only
contains eight basic emotions, its result is blended with the context
director's vector: semantic scores lead for neutral, bright, and angry, while
the director leads for compound performance states such as shy, cold,
dangerous, gentle, and whisper. Consecutive turns from the same speaker blend
a small amount of the preceding vector to avoid abrupt jumps.
Explicit story labels and manual
role choices use deterministic vectors instead. The vector order is `happy,
angry, sad, afraid, disgusted, melancholic, surprised, calm`; both paths cap
upstream `emo_alpha` at 0.6 to reduce identity drift.

## Requirements and setup

![Voice Prompts library used to store cloning references](../../../static/help/screenshots/voice-prompts.png)

*Store the clean reference in Voice Prompts, then select it for IndexTTS in the speaker or engine settings.*

The normal setup clones the official IndexTTS repository into
`engines/index-tts`, creates its isolated environment with `uv`, and installs
dependencies. Model weights are downloaded automatically on first use and are
approximately 5.5 GB for IndexTTS2; its speaker encoder, semantic model,
vocoder, and isolated environment require additional space. Reserve roughly
12 GB for this engine in total.

A CUDA GPU is strongly recommended. Apple Silicon uses MPS with PyTorch's CPU
fallback enabled for unsupported operations. CPU is selectable but large jobs
can be very slow. The Windows setup deliberately skips the optional DeepSpeed
extra because it usually cannot build without specialized CUDA tooling.

Assign a clean prompt for each speaker or configure a Default Prompt under [Settings → Engine Settings](app:settings/index-tts). See [Reference Voice Prompts](help:voice-prompts).

## Controls TTS-Story exposes

- **Model Version:** IndexTTS-2, 1.5, or legacy 1.0
- **Device**, **Default Prompt**, and **Chunk Size** (400 by default)
- **Automatic emotion:** analyse each line plus adjacent narration and preserve
  short same-speaker continuity
- **Emotion performance strength:** scales performance from 0 to 1 while the
  worker still caps the actual model mix at 0.6
- **Beam Search Width:** 1 is fastest; wider search adds GPT-stage work
- **Diffusion Steps:** TTS-Story starts at 12; more steps increase the slow synthesis stage
- **Temperature, top-p, and top-k:** sampling variation
- **Repetition Penalty:** raise cautiously if audio stutters or loops
- **Max Mel Tokens:** output-length safety cap; 1500 is roughly 68 seconds according to the UI estimate
- **Max Text Tokens per Segment:** internal splitting limit
- **FP16, DeepSpeed, torch.compile, and Accel:** optional performance paths whose support depends on the isolated runtime and GPU

Saved application defaults leave DeepSpeed, torch.compile, and Accel off. FP16 can reduce memory on supported GPUs, but make a baseline before enabling several acceleration paths together.

## Effective-use tips

1. Start with one beam, 12 diffusion steps, and the supplied sampling defaults.
2. Use a clean 10–15 second single-speaker prompt. A noisy or already
   over-acted reference is usually a larger quality problem than a sampling
   value.
3. If output loops, shorten the chunk first, then test a small repetition-penalty increase.
4. If a chunk is cut short, check Max Mel Tokens and sentence length before raising every limit.
5. `torch.compile` can make the first compiled request much slower while later requests improve. Benchmark after warm-up.
6. Treat DeepSpeed as unsupported unless you intentionally installed and
   verified it inside the IndexTTS environment.
7. If emotion is obvious but the voice begins to sound like another person,
   lower Emotion Performance Strength before changing pitch or post-processing.

## Time, privacy, and limitations

The first job includes model download, weight loading, and possibly compilation. Later speed varies with diffusion steps, beams, precision, text length, and GPU. Changing model versions can trigger another download.

After assets are cached, synthesis is local and has no provider usage charge. The isolated environment occupies additional disk space by design.

IndexTTS2 weights use the repository's bilibili Model Use License rather than
Apache or MIT. Local use is royalty-free under its terms, but distribution and
very-large-scale commercial use require a fresh license review.

This adapter supports English and Chinese and sends vector emotion control to
the worker. Emotion-reference, free-form emotion-text, and duration control are
not currently exposed. Automatic text emotion is intentionally conservative:
text alone cannot reveal every performance cue, so explicit story labels and
manual role settings take priority.

## Authoritative reference

- [IndexTTS official repository](https://github.com/index-tts/index-tts)
