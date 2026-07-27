import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_zero_cost_config_uses_local_models():
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    assert config["llm_provider"] == "local"
    assert config["llm_local_provider"] == "ollama"
    assert config["llm_local_model"] == "qwen3:1.7b"
    assert config["tts_engine"] == "qwen3_custom"
    assert config["qwen3_custom_model_id"].startswith("mlx-community/")
    assert config["qwen3_custom_default_language"].lower() == "chinese"
    assert config["qwen3_custom_auto_voice_lock"] is True
    assert config["qwen3_custom_clone_model_id"].endswith("Base-8bit")
    assert config["qwen3_custom_stability_temperature"] <= 0.4
    assert config["qwen3_custom_stability_seed"] == 20260727
    assert config["qwen3_clone_model_id"].startswith("mlx-community/")
    assert config["qwen3_voice_design_model_id"].startswith("mlx-community/")
    assert "中文有声书选角导演" in config["gemini_speaker_profile_prompt"]
    assert "母语者自然语流" in config["gemini_speaker_profile_prompt"]
    assert "lin-ning" not in config["llm_prompt"]
    assert "没有说话的角色不能获得标签" in config["llm_prompt"]
    assert "[unknown-neutral]" in config["llm_prompt"]
    assert config["llm_local_temperature"] == 0.1


def test_example_story_covers_chinese_structure_and_dialogue():
    story = (ROOT / "example_story_zh.txt").read_text(encoding="utf-8")
    assert "第一卷" in story
    assert story.count("章 ") >= 2
    assert "尾声" in story
    assert "“" in story and "”" in story


def test_chinese_volume_and_chapters_are_detected():
    import app

    story = (ROOT / "example_story_zh.txt").read_text(encoding="utf-8")
    books = [match.group(1) for match in app.BOOK_HEADING_PATTERN.finditer(story)]
    sections = [
        match.group(1)
        for match in app._build_section_heading_pattern().finditer(story)
    ]
    assert books == ["第一卷 雨夜"]
    assert sections == ["第一章 旧书店", "第二章 没有书名的书", "尾声"]
    assert app.slugify_filename("第一章 旧书店") == "第一章-旧书店"


def test_tag_wrapped_chinese_headings_and_nested_book_structure():
    import app

    story = """[narrator]第一卷 雨夜[/narrator]

[narrator]第一章 旧书店[/narrator]
[narrator]雨落下来。[/narrator]

[narrator]第二章 来客[/narrator]
[narrator]门开了。[/narrator]"""
    assert [m.group(1) for m in app.BOOK_HEADING_PATTERN.finditer(story)] == ["第一卷 雨夜"]
    assert [
        m.group(1) for m in app._build_section_heading_pattern().finditer(story)
    ] == ["第一章 旧书店", "第二章 来客"]

    hierarchy = app.split_text_into_book_sections(story)
    assert hierarchy["kind"] == "book"
    assert [chapter["title"] for chapter in hierarchy["books"][0]["chapters"]] == [
        "第一章 旧书店",
        "第二章 来客",
    ]


def test_classic_chinese_volume_and_short_story_headings():
    import app

    story = "卷一\n\n〈考城隍〉\n\n正文。\n\n〈耳中人〉\n\n正文。"
    assert [m.group(1) for m in app.BOOK_HEADING_PATTERN.finditer(story)] == ["卷一"]
    hierarchy = app.split_text_into_book_sections(story)
    assert [chapter["title"] for chapter in hierarchy["books"][0]["chapters"]] == [
        "〈考城隍〉",
        "〈耳中人〉",
    ]


def test_cjk_llm_chunking_uses_characters_and_preserves_text():
    import app

    text = "".join(f"第{i}句，雨落在长街上。" for i in range(180))
    chunks = app._chunk_text_by_paragraph_words(text, 120)
    assert len(chunks) > 10
    assert "".join(chunks) == text
    assert all(app._count_reading_units(chunk) <= 120 for chunk in chunks)


def test_llm_fidelity_guard_rejects_naked_or_changed_text():
    import app

    source = "他说：“你好。”她点了点头。"
    valid = "[narrator]他说：[/narrator]\n[li-male]“你好。”[/li-male]\n[narrator]她点了点头。[/narrator]"
    assert app._validate_llm_text_fidelity(source, valid) == (True, "")
    assert app._validate_llm_text_fidelity(source, valid + "\n解释") == (
        False,
        "LLM output contains text outside speaker tags",
    )
    changed = valid.replace("点了点头", "微笑")
    assert app._validate_llm_text_fidelity(source, changed)[0] is False


def test_chinese_dialogue_fallback_preserves_text_and_detects_speakers():
    import app
    from src.chinese_dialogue_tagger import tag_chinese_dialogue
    from src.text_processor import TextProcessor

    source = (
        "第一章 雨夜\n"
        "雨敲着窗。林夏推门进来，说：“你还没睡？”\n"
        "老周放下茶杯，答道：“我在等你。”"
    )
    tagged = tag_chinese_dialogue(source)

    assert tagged is not None
    assert app._validate_llm_text_fidelity(source, tagged) == (True, "")
    assert "第一章 雨夜" in tagged
    assert "“你还没睡？”" in tagged
    assert "“我在等你。”" in tagged
    speakers = TextProcessor().extract_speakers(tagged)
    assert "narrator" in speakers
    assert len(speakers) == 3
    assert any("u6797-u590f" in speaker for speaker in speakers)
    assert any("u8001-u5468" in speaker for speaker in speakers)


def test_invalid_local_llm_output_uses_safe_chinese_fallback():
    import app

    source = "林夏说：“别怕。”"
    altered = "[narrator]林夏说：[/narrator]\n[wrong-female]“快走。”[/wrong-female]"
    recovered, reason, used_fallback = app._recover_chinese_speaker_tags(
        source,
        altered,
    )

    assert used_fallback is True
    assert "changed, omitted, duplicated, or reordered" in reason
    assert recovered is not None
    assert app._validate_llm_text_fidelity(source, recovered) == (True, "")
    assert "“别怕。”" in recovered
    assert "“快走。”" not in recovered


def test_chinese_sentence_chunking_prefers_sentence_boundaries():
    from src.text_processor import TextProcessor

    processor = TextProcessor(
        chunk_strategy="characters",
        char_soft_limit=12,
        char_hard_limit=16,
    )
    chunks = processor.chunk_text("雨停了。林宁推开门。有人问：“你找谁？”她没有回答。")
    assert chunks
    assert "".join(chunks).replace(" ", "") == "雨停了。林宁推开门。有人问：“你找谁？”她没有回答。"
    assert all(chunk[-1] in "。！？？”" for chunk in chunks)


def test_mlx_adapter_concatenates_generated_audio():
    import numpy as np
    from src.engines.qwen3_custom_voice_engine import Qwen3CustomVoiceEngine

    class Result:
        sample_rate = 24000

        def __init__(self, audio):
            self.audio = audio

    class Model:
        sample_rate = 24000

        def generate_custom_voice(self, **kwargs):
            assert kwargs["speaker"] == "vivian"
            assert kwargs["language"] == "chinese"
            yield Result(np.array([0.1, 0.2], dtype=np.float32))
            yield Result(np.array([0.3], dtype=np.float32))

    engine = Qwen3CustomVoiceEngine.__new__(Qwen3CustomVoiceEngine)
    engine.backend = "mlx"
    engine.model = Model()
    audio, sample_rate = engine._synthesize("你好", "vivian", "Chinese", "自然")
    assert sample_rate == 24000
    assert np.allclose(audio, [0.1, 0.2, 0.3])


def test_main_qwen_engine_routes_character_presets_to_voice_design():
    import numpy as np
    from src.engines.qwen3_custom_voice_engine import Qwen3CustomVoiceEngine

    class Config:
        tts_model_type = "voice_design"

    class Result:
        sample_rate = 24000

        def __init__(self, audio):
            self.audio = audio

    class Model:
        sample_rate = 24000
        config = Config()

        def generate(self, **kwargs):
            assert kwargs["lang_code"] == "chinese"
            assert "清冷" in kwargs["instruct"]
            assert "禁止升高基础音调" in kwargs["instruct"]
            yield Result(np.array([0.1, 0.2], dtype=np.float32))

    engine = Qwen3CustomVoiceEngine.__new__(Qwen3CustomVoiceEngine)
    engine.backend = "mlx"
    engine.model = Model()
    engine.model_id = "mlx-community/Qwen3-TTS-VoiceDesign-8bit"
    audio, sample_rate = engine._synthesize(
        "她低声说：“我没有在等你。”",
        "frost_master",
        "Chinese",
        "她有些娇羞，但仍保持师长的克制。",
    )
    assert sample_rate == 24000
    assert np.allclose(audio, [0.1, 0.2])


def test_voice_lock_identity_is_stable_and_persona_specific(tmp_path):
    from src.engines.qwen3_custom_voice_engine import Qwen3CustomVoiceEngine

    engine = Qwen3CustomVoiceEngine.__new__(Qwen3CustomVoiceEngine)
    engine.model_id = "mlx-community/Qwen3-TTS-VoiceDesign-8bit"
    engine.design_model_id = engine.model_id
    engine.clone_model_id = "mlx-community/Qwen3-TTS-Base-8bit"
    engine.stability_temperature = 0.35
    engine.stability_top_k = 20
    engine.stability_top_p = 0.9
    engine.stability_seed = 20260727
    engine.voice_lock_cache_dir = tmp_path

    first = engine._voice_lock_spec(
        speaker="qingxia",
        language="Chinese",
        instruct=None,
    )
    repeated = engine._voice_lock_spec(
        speaker="qingxia",
        language="Chinese",
        instruct=None,
    )
    other = engine._voice_lock_spec(
        speaker="yanshu",
        language="Chinese",
        instruct=None,
    )

    assert first["key"] == repeated["key"]
    assert first["audio_path"] == repeated["audio_path"]
    assert first["key"] != other["key"]


def test_mlx_voice_design_automatically_locks_then_clones_without_preview(tmp_path):
    import numpy as np
    from src.engines.qwen3_custom_voice_engine import Qwen3CustomVoiceEngine

    class DesignConfig:
        tts_model_type = "voice_design"

    class CloneConfig:
        tts_model_type = "base"

    class Result:
        sample_rate = 24000

        def __init__(self, audio):
            self.audio = np.asarray(audio, dtype=np.float32)

    class DesignModel:
        config = DesignConfig()
        sample_rate = 24000

        def __init__(self):
            self.calls = []

        def generate(self, **kwargs):
            self.calls.append(kwargs)
            assert kwargs["temperature"] == 0.5
            assert kwargs["top_k"] == 30
            assert kwargs["top_p"] == 0.92
            assert "instruct" in kwargs
            yield Result([0.1, 0.2, 0.3])

    class CloneModel:
        config = CloneConfig()
        sample_rate = 24000

        def __init__(self):
            self.calls = []

        def generate(self, **kwargs):
            self.calls.append(kwargs)
            assert Path(kwargs["ref_audio"]).is_file()
            assert "快跟上" in kwargs["ref_text"]
            assert "instruct" not in kwargs
            yield Result([0.4, 0.5])

    class PostProcessor:
        @staticmethod
        def apply_post_pipeline(audio, _sample_rate, _fx):
            return audio

    design_model = DesignModel()
    clone_model = CloneModel()
    engine = Qwen3CustomVoiceEngine.__new__(Qwen3CustomVoiceEngine)
    engine.backend = "mlx"
    engine.model = design_model
    engine.model_id = "mlx-community/Qwen3-TTS-VoiceDesign-8bit"
    engine.design_model_id = engine.model_id
    engine.clone_model_id = "mlx-community/Qwen3-TTS-Base-8bit"
    engine.default_language = "Chinese"
    engine.default_instruct = None
    engine.auto_voice_lock = True
    engine.stability_temperature = 0.35
    engine.stability_top_k = 20
    engine.stability_top_p = 0.9
    engine.stability_seed = 20260727
    engine.voice_lock_cache_dir = tmp_path / "locks"
    engine._using_voice_lock_clone = False
    engine._voice_locks = {}
    engine._sample_rate = 24000
    engine._supported_speakers = []
    engine.post_processor = PostProcessor()

    def replace_model(model_id):
        engine.model = (
            clone_model if model_id == engine.clone_model_id else design_model
        )

    engine._replace_mlx_model = replace_model
    voice_config = {
        "heroine": {
            "voice": "qingxia",
            "extra": {"language": "Chinese"},
        },
    }
    output_dir = tmp_path / "audio"
    files = engine.generate_batch(
        segments=[
            {
                "speaker": "heroine",
                "chunks": ["“快跟上，我们出发啦！”"],
            },
        ],
        voice_config=voice_config,
        output_dir=output_dir,
    )

    assert len(design_model.calls) == 2
    assert len(clone_model.calls) == 1
    assert len(files) == 1
    assert Path(files[0]).is_file()
    assert len(list((tmp_path / "locks").glob("*.wav"))) == 2
    assert len(list((tmp_path / "locks").glob("*.json"))) == 2
    assert any("情绪明亮兴奋" in call["instruct"] for call in design_model.calls)
    assert any("情绪克制自然" in call["instruct"] for call in design_model.calls)


def test_chinese_voice_director_has_distinct_original_archetypes():
    from src.chinese_voice_director import (
        CHINESE_SAMPLE_TEXT,
        compose_voice_instruction,
        emotion_reference_text,
        list_voice_presets,
    )

    presets = list_voice_presets()
    preset_ids = {preset["id"] for preset in presets}
    assert {
        "qingxia",
        "yanshu",
        "ash_prince",
        "frost_master",
        "fox_lady",
        "tangxing",
    }.issubset(preset_ids)
    assert len(presets) >= 30
    assert {preset["source"] for preset in presets} >= {
        "崩坏：星穹铁道",
        "原神",
        "通用有声书",
    }
    assert all("reference_characters" in preset for preset in presets)
    assert all("match_keywords" in preset for preset in presets)
    assert "你愿意和我一起去看看吗" in CHINESE_SAMPLE_TEXT
    cold = compose_voice_instruction("frost_master", acting_state="cold")
    shy = compose_voice_instruction("frost_master", acting_state="shy")
    assert "标准的中国大陆普通话" in cold
    assert "不逐字朗读" in cold
    assert "疏离克制" in cold
    assert "娇羞" not in cold
    assert "藏不住的笑意" in shy
    assert "保持同一个人的年龄感" in cold
    assert emotion_reference_text("qingxia", "bright") != emotion_reference_text(
        "tangxing",
        "bright",
    )


def test_chinese_emotion_director_recognizes_all_acting_states():
    from src.chinese_voice_director import infer_acting_state

    examples = {
        "bright": "太好了！快看，我们终于找到宝藏了！",
        "gentle": "别担心，我就在这里。慢慢来，我会听着。",
        "shy": "我才没有一直等你……不许笑。",
        "cold": "收剑。此事到此为止。",
        "dangerous": "我只提醒你最后一次，后果由你承担。",
        "angry": "够了！闭嘴，马上把手放开！",
        "whisper": "嘘，别出声，门外有人。",
    }
    for expected, text in examples.items():
        decision = infer_acting_state(text, default_state="neutral")
        assert decision["state"] == expected
        assert decision["source"] == "automatic"

    neutral = infer_acting_state("我知道了，我们先回去吧。")
    assert neutral["state"] == "neutral"
    assert neutral["source"] == "persona"


def test_chinese_emotion_director_honors_override_and_continuity():
    from src.chinese_voice_director import infer_acting_state

    override = infer_acting_state(
        "这句话没有明显的线索。",
        explicit_instruction="娇羞",
        default_state="cold",
    )
    assert override["state"] == "shy"
    assert override["source"] == "manual"

    continued = infer_acting_state(
        "你跟紧我。",
        default_state="neutral",
        previous_state="dangerous",
    )
    assert continued["state"] == "dangerous"
    assert continued["source"] == "continuity"

    from_narration = infer_acting_state(
        "你现在就给我出去。",
        context_before="她猛地拍案，厉声喝道：",
    )
    assert from_narration["state"] == "angry"
    assert from_narration["source"] == "automatic"
    assert "上下文" in from_narration["reason"]


def test_shy_body_language_outweighs_generic_low_voice_cue():
    from src.chinese_voice_director import infer_acting_state

    decision = infer_acting_state(
        "师父……你别这样看着我。",
        context_before="她别过脸，耳尖微红，小声说道。",
    )

    assert decision["state"] == "shy"
    assert "耳尖" in decision["reason"]


def test_index_tts_uses_bounded_disentangled_emotion_vectors():
    from src.engines.index_tts_engine import index_tts_emotion_profile

    angry = index_tts_emotion_profile("angry", strength=1.0)
    gentle = index_tts_emotion_profile("gentle", strength=0.5)

    assert angry["state"] == "angry"
    assert angry["emo_vector"][1] == 0.82
    assert angry["emo_alpha"] == 0.6
    assert gentle["state"] == "gentle"
    assert gentle["emo_alpha"] == 0.22
    assert len(gentle["emo_vector"]) == 8
    assert sum(gentle["emo_vector"]) == pytest.approx(1.0)
    assert angry["use_random"] is False


def test_index_tts_allows_emotion_strength_to_be_disabled():
    import app

    normalized = app._normalize_index_tts_options(
        {"index_tts_emotion_strength": 0}
    )
    assert normalized["index_tts_emotion_strength"] == 0.0


def test_index_tts_worker_passes_real_emotion_vector_and_caps_alpha():
    import importlib.util

    worker_path = ROOT / "engines" / "index-tts" / "tts_worker.py"
    spec = importlib.util.spec_from_file_location("index_tts_worker_test", worker_path)
    assert spec and spec.loader
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)

    kwargs = worker._build_generation_kwargs(
        {
            "emo_vector": [-1, 0.8, 0, 0, 0.3, 0, 0, 2],
            "emo_alpha": 0.95,
            "use_random": False,
        },
        num_beams=1,
        diffusion_steps=12,
        temperature=0.8,
        top_p=0.8,
        top_k=30,
        repetition_penalty=10.0,
        max_mel_tokens=1500,
        max_text_tokens_per_segment=120,
    )

    assert kwargs["emo_vector"] == [0.0, 0.8, 0.0, 0.0, 0.3, 0.0, 0.0, 1.0]
    assert kwargs["emo_alpha"] == pytest.approx(0.6)
    assert kwargs["use_random"] is False

    semantic_kwargs = worker._build_generation_kwargs(
        {
            "use_emo_text": True,
            "emo_text": "前文旁白：她猛地拍案。\n当前对白：你现在就给我出去。",
            "emo_vector": [0, 1, 0, 0, 0, 0, 0, 0],
            "emo_alpha": 0.54,
        },
        num_beams=1,
        diffusion_steps=12,
        temperature=0.8,
        top_p=0.8,
        top_k=30,
        repetition_penalty=10.0,
        max_mel_tokens=1500,
        max_text_tokens_per_segment=120,
    )
    assert semantic_kwargs["use_emo_text"] is True
    assert "当前对白" in semantic_kwargs["emo_text"]
    assert "emo_vector" not in semantic_kwargs
    assert semantic_kwargs["director_vector"] == [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    assert semantic_kwargs["emo_alpha"] == pytest.approx(0.54)

    class FakeEmotion:
        @staticmethod
        def inference(_text):
            return {
                "happy": 0.0,
                "angry": 1.0,
                "sad": 0.0,
                "afraid": 0.0,
                "disgusted": 0.0,
                "melancholic": 0.0,
                "surprised": 0.0,
                "calm": 0.0,
            }

    class FakeTTS:
        qwen_emo = FakeEmotion()

    materialized, vector, detected = worker._materialize_semantic_emotion(
        FakeTTS(),
        semantic_kwargs,
        previous_vector=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    )
    assert "use_emo_text" not in materialized
    assert materialized["emo_vector"] == vector
    assert vector[:2] == [0.18, 0.82]
    assert detected["angry"] == 1.0

    class OverloadedEmotion:
        @staticmethod
        def inference(_text):
            return {key: 1.0 for key in worker._EMOTION_VECTOR_KEYS}

    class OverloadedTTS:
        qwen_emo = OverloadedEmotion()

    overloaded_kwargs = dict(semantic_kwargs)
    overloaded_kwargs.update(
        {
            "use_emo_text": True,
            "emo_text": "多种强烈情绪混合",
        }
    )
    overloaded, overloaded_vector, _ = worker._materialize_semantic_emotion(
        OverloadedTTS(),
        overloaded_kwargs,
    )
    assert overloaded["emo_vector"] == overloaded_vector
    assert sum(overloaded_vector) == pytest.approx(1.0, abs=0.001)

    class MisreadDangerEmotion:
        @staticmethod
        def inference(_text):
            return {
                "happy": 0.0,
                "angry": 0.1,
                "sad": 0.5,
                "afraid": 0.2,
                "disgusted": 0.05,
                "melancholic": 0.1,
                "surprised": 0.0,
                "calm": 0.05,
            }

    class MisreadDangerTTS:
        qwen_emo = MisreadDangerEmotion()

    dangerous_kwargs = worker._build_generation_kwargs(
        {
            "use_emo_text": True,
            "emo_text": "我只说最后一次。再往前一步，你就别想活着离开。",
            "state": "dangerous",
            "emo_vector": [0.0, 0.2, 0.0, 0.1, 0.22, 0.18, 0.0, 0.3],
            "emo_alpha": 0.56,
        },
        num_beams=1,
        diffusion_steps=12,
        temperature=0.8,
        top_p=0.8,
        top_k=30,
        repetition_penalty=10.0,
        max_mel_tokens=1500,
        max_text_tokens_per_segment=120,
    )
    _, dangerous_vector, _ = worker._materialize_semantic_emotion(
        MisreadDangerTTS(),
        dangerous_kwargs,
    )
    assert dangerous_vector[2] < 0.1
    assert dangerous_vector[4] > dangerous_vector[2]
    assert dangerous_vector[7] > dangerous_vector[2]


def test_index_tts_emotion_plan_reads_narration_and_preserves_continuity():
    from src.engines.base import VoiceAssignment
    from src.engines.index_tts_engine import IndexTTSEngine

    engine = IndexTTSEngine.__new__(IndexTTSEngine)
    engine._auto_emotion = True
    engine._emotion_strength = 1.0
    narrator_assignment = VoiceAssignment(voice="ink_narrator")
    heroine_assignment = VoiceAssignment(voice="frost_master")
    worker_chunks = [
        {"text": "她猛地拍案，厉声喝道：", "spk_audio_prompt": "narrator.wav"},
        {"text": "你现在就给我出去。", "spk_audio_prompt": "heroine.wav"},
        {"text": "现在。", "spk_audio_prompt": "heroine.wav"},
    ]
    chunk_meta = [
        {
            "speaker": "narrator",
            "text": worker_chunks[0]["text"],
            "segment_index": 0,
            "chunk_index": 0,
            "assignment": narrator_assignment,
        },
        {
            "speaker": "heroine-female",
            "text": worker_chunks[1]["text"],
            "segment_index": 1,
            "chunk_index": 0,
            "assignment": heroine_assignment,
        },
        {
            "speaker": "heroine-female",
            "text": worker_chunks[2]["text"],
            "segment_index": 2,
            "chunk_index": 0,
            "assignment": heroine_assignment,
        },
    ]

    enriched, metadata = engine.enrich_worker_chunks(worker_chunks, chunk_meta)

    assert metadata[1]["emotion"] == "angry"
    assert metadata[1]["emotion_source"] == "automatic"
    assert metadata[2]["emotion"] == "angry"
    assert metadata[2]["emotion_source"] == "continuity"
    assert metadata[1]["emotion_driver"] == "semantic_text"
    assert enriched[1]["use_emo_text"] is True
    assert "前文旁白" in enriched[1]["emo_text"]
    assert "连续表演参考：愤怒" in enriched[1]["emo_text"]
    assert enriched[1]["emo_vector"][1] == 0.82
    assert enriched[1]["emo_alpha"] == 0.6


def test_index_tts_ignores_unrelated_following_narration_for_dialogue_emotion():
    from src.engines.base import VoiceAssignment
    from src.engines.index_tts_engine import IndexTTSEngine

    engine = IndexTTSEngine.__new__(IndexTTSEngine)
    engine._auto_emotion = True
    engine._emotion_strength = 1.0
    assignment = VoiceAssignment(voice="frost_master")
    workers = [
        {"text": "我会在这里等你。", "spk_audio_prompt": "heroine.wav"},
        {"text": "另一边，女孩兴奋地跑进花园。", "spk_audio_prompt": "narrator.wav"},
    ]
    metadata = [
        {
            "speaker": "heroine-female",
            "text": workers[0]["text"],
            "segment_index": 0,
            "chunk_index": 0,
            "assignment": assignment,
        },
        {
            "speaker": "narrator",
            "text": workers[1]["text"],
            "segment_index": 1,
            "chunk_index": 0,
            "assignment": VoiceAssignment(voice="ink_narrator"),
        },
    ]

    enriched, _ = engine.enrich_worker_chunks(workers, metadata)

    assert "后文旁白" not in enriched[0]["emo_text"]


def test_index_tts_can_reuse_qwen_persona_identity_cache(tmp_path):
    from src.engines.index_tts_engine import IndexTTSEngine

    engine_root = tmp_path / "engines" / "index-tts"
    engine_root.mkdir(parents=True)
    voice_locks = tmp_path / "data" / "voice_locks"
    voice_locks.mkdir(parents=True)
    neutral = voice_locks / "frost_master-neutral-test.wav"
    neutral.write_bytes(b"RIFF")

    engine = IndexTTSEngine.__new__(IndexTTSEngine)
    engine._engine_root = engine_root
    resolved = engine._resolve_persona_voice_lock("frost_master")

    assert resolved == neutral.resolve()


def test_index_tts_bootstraps_only_missing_neutral_persona(monkeypatch):
    import src.engines.qwen3_custom_voice_engine as qwen_module
    from src.engines.index_tts_engine import IndexTTSEngine

    created = set()
    calls = {}

    class FakeBootstrap:
        def __init__(self, **kwargs):
            calls["init"] = kwargs

        def _prepare_voice_locks(self, requested, **kwargs):
            calls["requested"] = requested
            calls["prepare"] = kwargs
            created.update(requested)

        def cleanup(self):
            calls["cleaned"] = True

    monkeypatch.setattr(qwen_module, "Qwen3CustomVoiceEngine", FakeBootstrap)

    engine = IndexTTSEngine.__new__(IndexTTSEngine)
    engine._persona_design_model_id = "voice-design"
    engine._persona_clone_model_id = "base"
    engine._persona_stability_temperature = 0.35
    engine._persona_stability_top_k = 20
    engine._persona_stability_top_p = 0.9
    engine._persona_stability_seed = 20260727
    monkeypatch.setattr(
        engine,
        "_resolve_persona_voice_lock",
        lambda voice_name: Path("/tmp/ready.wav")
        if voice_name in created or voice_name == "qingxia"
        else None,
    )

    engine.ensure_persona_voice_locks(
        {
            "heroine": {"voice": "frost_master", "extra": {"language": "Chinese"}},
            "friend": {"voice": "qingxia"},
        }
    )

    assert set(calls["requested"]) == {"frost_master"}
    assert calls["prepare"]["required_states_by_voice"] == {
        "frost_master": {"neutral"}
    }
    assert calls["prepare"]["include_preset_default"] is False
    assert calls["prepare"]["switch_to_clone"] is False
    assert calls["cleaned"] is True


def test_emotion_voice_locks_share_identity_seed_but_keep_distinct_cache_keys(tmp_path):
    from src.chinese_voice_director import VOICE_IDENTITY_CONSISTENCY
    from src.engines.qwen3_custom_voice_engine import Qwen3CustomVoiceEngine

    engine = Qwen3CustomVoiceEngine.__new__(Qwen3CustomVoiceEngine)
    engine.model_id = "mlx-community/Qwen3-TTS-VoiceDesign-8bit"
    engine.design_model_id = engine.model_id
    engine.clone_model_id = "mlx-community/Qwen3-TTS-Base-8bit"
    engine.stability_temperature = 0.35
    engine.stability_top_k = 20
    engine.stability_top_p = 0.9
    engine.stability_seed = 20260727
    engine.voice_lock_cache_dir = tmp_path

    cold = engine._voice_lock_spec(
        speaker="frost_master",
        language="Chinese",
        instruct=None,
        acting_state="cold",
    )
    shy = engine._voice_lock_spec(
        speaker="frost_master",
        language="Chinese",
        instruct=None,
        acting_state="shy",
    )

    assert cold["key"] != shy["key"]
    assert cold["audio_path"] != shy["audio_path"]
    assert VOICE_IDENTITY_CONSISTENCY in cold["instruction"]
    assert VOICE_IDENTITY_CONSISTENCY in shy["instruction"]
    assert engine._seed_generation(
        "frost_master",
        cold["instruction"],
        cold["reference_text"],
        preserve_voice_identity=True,
    ) == engine._seed_generation(
        "frost_master",
        shy["instruction"],
        shy["reference_text"],
        preserve_voice_identity=True,
    )


def test_qwen_emotion_plan_tracks_automatic_manual_and_adjacent_states():
    from src.engines.qwen3_custom_voice_engine import Qwen3CustomVoiceEngine

    engine = Qwen3CustomVoiceEngine.__new__(Qwen3CustomVoiceEngine)
    engine.default_language = "Chinese"
    engine._supported_speakers = []
    voice_config = {
        "master": {
            "voice": "frost_master",
            "extra": {"language": "Chinese"},
        },
    }
    plan, required = engine._plan_chunk_emotions(
        [
            {
                "speaker": "master",
                "chunks": [
                    "够了！闭嘴！",
                    "你跟紧我。",
                ],
            },
            {
                "speaker": "master",
                "emotion": "娇羞",
                "chunks": ["我没有在等你。"],
            },
        ],
        voice_config,
    )

    assert plan[(0, 0)]["state"] == "angry"
    assert plan[(0, 0)]["source"] == "automatic"
    assert plan[(0, 1)]["state"] == "angry"
    assert plan[(0, 1)]["source"] == "continuity"
    assert plan[(1, 0)]["state"] == "shy"
    assert plan[(1, 0)]["source"] == "manual"
    assert {"neutral", "cold", "angry", "shy"}.issubset(
        required["frost_master"]
    )


def test_qwen_metadata_switches_to_chinese_character_presets():
    import app

    response = app.app.test_client().get("/api/qwen3/metadata")
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["mode"] == "voice_design"
    assert payload["speakers"][:6] == [
        "qingxia",
        "yanshu",
        "ash_prince",
        "frost_master",
        "fox_lady",
        "tangxing",
    ]
    assert len(payload["speakers"]) >= 30
    assert len(payload["presets"]) == len(payload["speakers"])
    assert payload["speaker_labels"]["frost_master"].startswith("霜月师尊")


def test_voice_design_presets_api_is_chinese_first():
    import app

    response = app.app.test_client().get("/api/qwen3/voice-design/presets")
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["success"] is True
    assert len(payload["presets"]) >= 30
    assert payload["default_text"].startswith("雨刚停")
    assert any(state["id"] == "shy" for state in payload["acting_states"])


def test_character_persona_recommender_matches_reference_and_traits():
    from src.chinese_voice_director import recommend_voice_presets

    direct = recommend_voice_presets("砂金一样优雅又危险的笑面赌徒", limit=2)
    assert direct[0]["id"] == "gilded_gambler"
    assert direct[0]["confidence"] >= 0.95

    persona = recommend_voice_presets(
        "俏皮机灵的少女堂主，喜欢开玩笑但坦然面对生死",
        gender="Female",
        limit=3,
    )
    assert persona[0]["id"] == "mischief_director"
    assert persona[0]["score"] > persona[1]["score"]

    narrator = recommend_voice_presets("自然耐听的男旁白 narrator", limit=1)
    assert narrator[0]["id"] == "ink_narrator"


def test_character_persona_recommendation_api():
    import app

    response = app.app.test_client().post(
        "/api/qwen3/voice-design/recommend",
        json={"profile": "低沉儒雅、博古通今的成熟先生", "gender": "Male"},
    )
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["recommendations"][0]["id"] == "ancient_gentleman"


def test_mandarin_pacing_gate_only_flags_grossly_slow_takes():
    from src.chinese_voice_director import has_abnormally_slow_delivery

    text = "她推开门，看见长街上的灯一盏接一盏亮了起来。"
    assert has_abnormally_slow_delivery(text, 24_000 * 20, 24_000) is True
    assert has_abnormally_slow_delivery(text, 24_000 * 6, 24_000) is False
    assert has_abnormally_slow_delivery("你好。", 24_000 * 8, 24_000) is False


def test_main_voice_design_retries_grossly_slow_mandarin():
    import numpy as np
    from src.engines.qwen3_custom_voice_engine import Qwen3CustomVoiceEngine

    class Config:
        tts_model_type = "voice_design"

    class Result:
        sample_rate = 24000

        def __init__(self, sample_count):
            self.audio = np.zeros(sample_count, dtype=np.float32)

    class Model:
        sample_rate = 24000
        config = Config()

        def __init__(self):
            self.calls = []

        def generate(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                yield Result(24_000 * 20)
            else:
                assert "上一版语速和停顿过慢" in kwargs["instruct"]
                yield Result(24_000 * 6)

    engine = Qwen3CustomVoiceEngine.__new__(Qwen3CustomVoiceEngine)
    engine.backend = "mlx"
    engine.model = Model()
    engine.model_id = "mlx-community/Qwen3-TTS-VoiceDesign-8bit"
    audio, sample_rate = engine._synthesize(
        "她推开门，看见长街上的灯一盏接一盏亮了起来。",
        "velvet_hunter",
        "Chinese",
        None,
    )
    assert sample_rate == 24000
    assert len(audio) == 24_000 * 6
    assert len(engine.model.calls) == 2


def test_mlx_voice_design_preview_uses_preset_and_concatenates(monkeypatch):
    import numpy as np
    import app

    class Result:
        sample_rate = 24000

        def __init__(self, audio):
            self.audio = audio

    class Model:
        sample_rate = 24000

        def generate(self, **kwargs):
            assert kwargs["lang_code"] == "chinese"
            assert "中国大陆普通话" in kwargs["instruct"]
            assert "强势青年男性" in kwargs["instruct"]
            yield Result(np.array([0.1, 0.2], dtype=np.float32))
            yield Result(np.array([0.3], dtype=np.float32))

    monkeypatch.setattr(app, "_get_qwen3_voice_design_model", lambda _config: Model())
    monkeypatch.setattr(app, "qwen3_voice_design_backend", "mlx")
    monkeypatch.setattr(app, "_apply_voice_design_cleanup", lambda audio, _sr: audio)

    result = app._generate_voice_design_preview(
        {
            "text": "你终于来了。",
            "language": "Chinese",
            "preset_id": "ash_prince",
            "acting_state": "dangerous",
        },
        {},
    )
    assert result["mime_type"] == "audio/wav"
    assert result["audio_base64"]


def test_mlx_voice_clone_requires_transcript_and_concatenates():
    import numpy as np
    import pytest
    from src.engines.qwen3_voice_clone_engine import Qwen3VoiceCloneEngine

    class Result:
        sample_rate = 24000

        def __init__(self, audio):
            self.audio = audio

    class Model:
        sample_rate = 24000

        def generate(self, **kwargs):
            assert kwargs["lang_code"] == "chinese"
            assert kwargs["ref_audio"] == "/tmp/reference.wav"
            assert kwargs["ref_text"] == "这是参考文本。"
            yield Result(np.array([0.1], dtype=np.float32))
            yield Result(np.array([0.2, 0.3], dtype=np.float32))

    engine = Qwen3VoiceCloneEngine.__new__(Qwen3VoiceCloneEngine)
    engine.backend = "mlx"
    engine.model = Model()
    with pytest.raises(ValueError, match="exact transcript"):
        engine._synthesize_clone(
            text="新的中文句子。",
            language="Chinese",
            prompt_path="/tmp/reference.wav",
            prompt_text="",
        )
    audio, sample_rate = engine._synthesize_clone(
        text="新的中文句子。",
        language="Chinese",
        prompt_path="/tmp/reference.wav",
        prompt_text="这是参考文本。",
    )
    assert sample_rate == 24000
    assert np.allclose(audio, [0.1, 0.2, 0.3])
