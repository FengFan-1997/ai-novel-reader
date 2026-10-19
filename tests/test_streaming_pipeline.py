from pathlib import Path
from types import SimpleNamespace
import shutil
import time

import numpy as np
import pytest
import soundfile as sf

from src.chinese_dialogue_tagger import (
    tag_chinese_dialogue,
    tag_chinese_dialogue_detailed,
)
from src.chinese_character_analyzer import (
    analyze_book_characters,
    sampled_chapter_indices,
    strip_speaker_tags,
)
from src.chinese_voice_director import (
    VOICE_PRESETS,
    audit_streaming_cast,
    build_streaming_voice_assignments,
)
from src.rvc_service import project_conversion_seconds
from src.streaming_store import StreamingStore, can_release_streaming_audio
from src.engines.qwen3_custom_voice_engine import Qwen3CustomVoiceEngine


def test_adaptive_release_requires_three_segments_ninety_seconds_and_headroom():
    assert not can_release_streaming_audio(
        ready_segments=2,
        playable_seconds=120,
        render_seconds=40,
        playback_rate=1,
    )
    assert not can_release_streaming_audio(
        ready_segments=3,
        playable_seconds=89,
        render_seconds=30,
        playback_rate=1,
    )
    assert can_release_streaming_audio(
        ready_segments=3,
        playable_seconds=90,
        render_seconds=60,
        playback_rate=1,
    )
    assert not can_release_streaming_audio(
        ready_segments=3,
        playable_seconds=90,
        render_seconds=60,
        playback_rate=1.5,
    )


@pytest.mark.parametrize(
    ("playback_rate", "render_seconds"),
    [(1.0, 72.0), (1.5, 48.0), (2.0, 36.0)],
)
def test_adaptive_release_tracks_supported_playback_rates(
    playback_rate,
    render_seconds,
):
    assert can_release_streaming_audio(
        ready_segments=3,
        playable_seconds=90,
        render_seconds=render_seconds,
        playback_rate=playback_rate,
    )
    assert not can_release_streaming_audio(
        ready_segments=3,
        playable_seconds=90,
        render_seconds=render_seconds + 0.1,
        playback_rate=playback_rate,
    )


def test_rvc_projection_counts_cold_start_once_and_uses_warm_median():
    assert project_conversion_seconds([120, 5], 80) == 0
    assert project_conversion_seconds([120, 4, 6], 80) == 515


def test_streaming_retry_classifier_is_narrow():
    import app as app_module

    assert app_module._is_retryable_streaming_error(
        RuntimeError("Qwen3 automatic voice lock returned no audio.")
    )
    assert not app_module._is_retryable_streaming_error(
        RuntimeError("Unsupported output format")
    )


def test_rvc_safety_fallback_is_persisted_with_the_job_payload():
    import app as app_module

    payload = app_module._serialize_job_payload(
        {
            "job_payload": {},
            "rvc_auto_disabled": True,
            "streaming_warning": "using fast narrator",
        }
    )

    assert payload["rvc_auto_disabled"] is True
    assert payload["streaming_warning"] == "using fast narrator"


def test_streaming_job_reports_qwen_engine_not_global_default_engine():
    import app as app_module

    payload = app_module._build_job_payload(
        "streaming-job",
        "测试",
        {
            "engine": "index_tts",
            "streaming_mode": True,
            "job_type": "streaming_audio",
            "config_snapshot": {"tts_engine": "index_tts"},
        },
    )

    assert payload["engine"] == "qwen3_custom"
    assert payload["streaming_mode"] is True


def test_non_apple_runtime_maps_checked_in_mlx_model_ids_without_rewriting_config(
    monkeypatch,
    tmp_path: Path,
):
    import json
    import app as app_module

    config_path = tmp_path / "config.json"
    source_config = {
        "qwen3_custom_model_id": "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-8bit",
        "qwen3_custom_clone_model_id": "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit",
        "qwen3_clone_model_id": "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit",
        "qwen3_voice_design_model_id": "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-8bit",
    }
    config_path.write_text(json.dumps(source_config), encoding="utf-8")
    defaults = app_module.DEFAULT_CONFIG.copy()
    defaults.update({
        "qwen3_custom_model_id": "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
        "qwen3_custom_clone_model_id": "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
        "qwen3_clone_model_id": "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
        "qwen3_voice_design_model_id": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
    })
    monkeypatch.setattr(app_module, "DEFAULT_CONFIG", defaults)
    monkeypatch.setattr(app_module, "CONFIG_FILE", str(config_path))
    monkeypatch.setattr(app_module, "IS_APPLE_SILICON", False)

    loaded = app_module.load_config()

    assert loaded["qwen3_custom_model_id"] == "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
    assert loaded["qwen3_custom_clone_model_id"] == "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
    assert loaded["qwen3_clone_model_id"] == "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
    assert loaded["qwen3_voice_design_model_id"] == "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
    assert json.loads(config_path.read_text(encoding="utf-8")) == source_config


def test_unknown_dialogue_uses_scene_scoped_participants():
    source = "\n".join(f"“第{i}句话。”" for i in range(30))
    tagged = tag_chinese_dialogue(source)
    assert tagged
    assert "unknown-neutral-" not in tagged
    assert "extra-chapter-0-s001-p01-male" in tagged
    assert "extra-chapter-0-s001-p02-male" in tagged


def test_first_middle_last_sampling_is_stable_and_unique():
    assert sampled_chapter_indices(2) == [0, 1]
    assert sampled_chapter_indices(9) == [0, 1, 2, 3, 4, 5, 6, 7, 8]
    assert sampled_chapter_indices(20) == [0, 1, 2, 9, 10, 11, 17, 18, 19]


def test_recovering_raw_source_drops_editor_emotion_instructions():
    tagged = (
        "[emotion]愤怒地大喊[/emotion]"
        "[hero-male]“住手！”[/hero-male]"
        "[narrator]众人回头。[/narrator]"
    )
    assert strip_speaker_tags(tagged) == "“住手！”众人回头。"


def test_book_level_cast_fixes_protagonist_and_pronoun_to_one_male_voice():
    chapters = []
    for index in range(12):
        text = (
            "苏承走入大殿。苏承环顾四周。苏承低声道：“先等等。”"
            "众人安静下来。苏承点头。他问：“都准备好了吗？”"
        )
        chapters.append({"index": index, "content": text})

    characters = analyze_book_characters(chapters, synopsis="苏承穿越后建立宗门。")
    protagonist = characters[0]
    assert protagonist["name"] == "苏承"
    assert protagonist["gender"] == "male"
    assert protagonist["voice"] == "rational_scribe"
    assert protagonist["is_protagonist"] is True

    tagged = tag_chinese_dialogue(chapters[0]["content"], characters)
    speaker = protagonist["character_id"]
    assert tagged.count(f"[{speaker}]") == 2
    casting = build_streaming_voice_assignments(
        tagged,
        {speaker: {"voice": protagonist["voice"]}},
    )
    assert VOICE_PRESETS[casting[speaker]["voice"]]["gender"] == "Male"


def test_book_level_cast_can_select_multiple_leads_without_forcing_ambiguous_pronoun():
    chapters = []
    for index in range(12):
        chapters.append(
            {
                "index": index,
                "content": (
                    "苏承说道：“向东。”林雪问道：“为什么？”"
                    "苏承看向林雪，林雪也看向苏承。旁边还有王林和赵海。"
                    "他道：“照计划做。”"
                )
                * 3,
            }
        )
    characters = analyze_book_characters(
        chapters,
        synopsis="苏承与林雪共同踏上旅途。",
        allow_multiple_protagonists=True,
    )
    protagonists = [
        item["name"] for item in characters if item["is_protagonist"]
    ]
    assert "苏承" in protagonists
    assert "林雪" in protagonists
    assert len(protagonists) >= 2


def test_streaming_cast_never_crosses_explicit_gender():
    text = (
        "[narrator]夜色降临。[/narrator]"
        "[hero-male]走吧。[/hero-male]"
        "[heroine-female]好。[/heroine-female]"
    )
    supplied = {
        "hero-male": {"voice": "qingxia"},
        "heroine-female": {"voice": "yanshu"},
    }
    casting = build_streaming_voice_assignments(text, supplied)
    assert casting["narrator"]["voice"] == "fox_lady"
    assert VOICE_PRESETS[casting["hero-male"]["voice"]]["gender"] == "Male"
    assert VOICE_PRESETS[casting["heroine-female"]["voice"]]["gender"] == "Female"


def test_unnamed_crowd_uses_multiple_non_protagonist_male_library_voices():
    text = (
        "[unknown-neutral-1]别傻站着。[/unknown-neutral-1]"
        "[unknown-neutral-2]快跟上。[/unknown-neutral-2]"
        "[cn-u4e61-u4eb2-neutral]俺也去看看。[/cn-u4e61-u4eb2-neutral]"
        "[hero-male]我知道了。[/hero-male]"
    )
    casting = build_streaming_voice_assignments(
        text,
        {"hero-male": {"voice": "rational_scribe"}},
    )

    crowd_voices = []
    for speaker in (
        "unknown-neutral-1",
        "unknown-neutral-2",
        "cn-u4e61-u4eb2-neutral",
    ):
        assert VOICE_PRESETS[casting[speaker]["voice"]]["gender"] == "Male"
        assert casting[speaker]["voice"] != casting["hero-male"]["voice"]
        crowd_voices.append(casting[speaker]["voice"])
    assert len(set(crowd_voices)) == 3


def test_real_first_chapter_exchange_alternates_su_and_strong_man():
    characters = [{
        "character_id": "character-su",
        "name": "苏承",
        "aliases": ["苏承"],
        "gender": "male",
    }]
    source = (
        "苏承看向壮汉，问道：“哥们，你是谁？”"
        "壮汉挠了挠头：“啊？”"
        "“山上的？”"
        "“浣星宗。”"
    )
    detail = tag_chinese_dialogue_detailed(
        source,
        characters,
        scene_key="chapter-1",
    )
    assert detail is not None
    speakers = [item["speaker"] for item in detail.attributions]
    assert speakers[0] == speakers[2] == "character-su"
    assert speakers[1] == speakers[3]
    assert speakers[1] != "character-su"


def test_real_chapter_opening_vocative_assigns_warning_to_bystander_then_su_asks():
    characters = [{
        "character_id": "character-su",
        "name": "苏承",
        "aliases": ["苏承"],
        "gender": "male",
    }]
    source = (
        "苏承被撞了个踉跄。方才撞他的男人朝自己尴尬笑笑。"
        "周围嘈杂，苏承扶着额头。背后又有人推搡两下。"
        "“兄弟，别傻站着。”"
        "苏承被推挤着踏上台阶，回头看向那男人。"
        "“哥们，这山上的……是什么？”"
        "“啊？”"
        "“山上的，叫什么！”"
        "“浣星宗！”"
        "虬髯汉子扯着嗓子说道：“浣星宗三年大开仙门！”"
        "苏承问道：“人人都能上去？”"
        "壮汉笑道：“你上了山，仙长们一瞧便知。”"
    )
    detail = tag_chinese_dialogue_detailed(
        source,
        characters,
        scene_key="chapter-1",
    )
    assert detail is not None
    speakers = [item["speaker"] for item in detail.attributions]
    bystander = speakers[0]
    assert bystander.startswith("extra-chapter-1-s001-")
    assert speakers[:5] == [
        bystander,
        "character-su",
        bystander,
        "character-su",
        bystander,
    ]
    assert speakers[5] == bystander
    assert speakers[6] == "character-su"
    assert speakers[7] == bystander


def test_postposed_agreement_after_adjacent_quote_belongs_to_named_responder():
    characters = [
        {
            "character_id": "character-su",
            "name": "苏承",
            "aliases": ["苏承"],
            "gender": "male",
        },
        {
            "character_id": "character-lin",
            "name": "林雪",
            "aliases": ["林雪"],
            "gender": "female",
        },
    ]
    detail = tag_chinese_dialogue_detailed(
        '苏承说道：“先这样。” “我也这么觉得。”林雪也跟着附和。',
        characters,
        scene_key="agreement",
    )

    assert detail is not None
    second = detail.attributions[1]
    assert second["speaker"] == "character-lin"
    assert second["gender"] == "female"
    assert second["source"] == "explicit_after"
    assert second["evidence"]["after"] == "林雪"


@pytest.mark.parametrize(
    "attribution",
    [
        "林雪附和道",
        "林雪接话道",
        "林雪应声道",
        "林雪应和道",
        "林雪也跟着附和",
        "林雪接着附和了一句",
    ],
)
def test_preposed_agreement_and_response_cues_bind_the_speaker(attribution):
    characters = [{
        "character_id": "character-lin",
        "name": "林雪",
        "aliases": ["林雪"],
        "gender": "female",
    }]
    detail = tag_chinese_dialogue_detailed(
        f'{attribution}：“我同意。”',
        characters,
        scene_key="agreement",
    )

    assert detail is not None
    assert detail.attributions[0]["speaker"] == "character-lin"
    assert detail.attributions[0]["source"] == "explicit_before"


def test_ambiguous_bare_quote_in_crowded_scene_does_not_reuse_previous_named_speaker():
    characters = [
        {"character_id": "character-su", "name": "苏承", "aliases": ["苏承"], "gender": "male"},
        {"character_id": "character-lin", "name": "林雪", "aliases": ["林雪"], "gender": "female"},
        {"character_id": "character-wang", "name": "王林", "aliases": ["王林"], "gender": "male"},
    ]
    detail = tag_chinese_dialogue_detailed(
        '苏承说道：“向左。”林雪说道：“不行。”王林点了点头。 “照原计划。”',
        characters,
        scene_key="crowded",
    )

    assert detail is not None
    final = detail.attributions[-1]
    assert final["speaker"] not in {"character-su", "character-lin", "character-wang"}
    assert final["source"] == "scene_extra"


def test_inner_monologue_keeps_one_known_speaker_without_creating_a_scene_partner():
    characters = [{
        "character_id": "character-su",
        "name": "苏承",
        "aliases": ["苏承"],
        "gender": "male",
    }]
    detail = tag_chinese_dialogue_detailed(
        '苏承心中暗道：“先等等。”苏承心中又想：“还不能暴露。”',
        characters,
        scene_key="monologue",
    )

    assert detail is not None
    assert [item["speaker"] for item in detail.attributions] == [
        "character-su",
        "character-su",
    ]


def test_scene_extras_never_borrow_any_named_character_voice_lock():
    text = (
        "[character-hero]主角[/character-hero]"
        "[character-rival]对手[/character-rival]"
        "[extra-chapter-1-s001-p01-male]路人甲[/extra-chapter-1-s001-p01-male]"
        "[extra-chapter-1-s001-p02-male]路人乙[/extra-chapter-1-s001-p02-male]"
    )
    casting = build_streaming_voice_assignments(
        text,
        {
            "character-hero": {"voice": "rational_scribe"},
            "character-rival": {"voice": "moon_guard"},
        },
        speaker_genders={
            "character-hero": "male",
            "character-rival": "male",
            "extra-chapter-1-s001-p01-male": "male",
            "extra-chapter-1-s001-p02-male": "male",
        },
    )
    extra_voices = {
        casting["extra-chapter-1-s001-p01-male"]["voice"],
        casting["extra-chapter-1-s001-p02-male"]["voice"],
    }
    assert not extra_voices & {"rational_scribe", "moon_guard"}


def test_two_male_and_ten_female_leads_receive_unique_gender_safe_voices():
    genders = {
        **{f"character-m{i}": "male" for i in range(2)},
        **{f"character-f{i}": "female" for i in range(10)},
    }
    text = "".join(f"[{speaker}]测试[/{speaker}]" for speaker in genders)
    casting = build_streaming_voice_assignments(text, speaker_genders=genders)
    male_voices = [casting[f"character-m{i}"]["voice"] for i in range(2)]
    female_voices = [casting[f"character-f{i}"]["voice"] for i in range(10)]
    assert len(set(male_voices)) == 2
    assert len(set(female_voices)) == 10
    assert all(VOICE_PRESETS[voice]["gender"] == "Male" for voice in male_voices)
    assert all(VOICE_PRESETS[voice]["gender"] == "Female" for voice in female_voices)


def test_five_extras_in_one_scene_use_five_distinct_voices():
    speakers = [f"extra-chapter-2-s001-p{i:02d}-male" for i in range(1, 6)]
    text = "".join(f"[{speaker}]测试[/{speaker}]" for speaker in speakers)
    casting = build_streaming_voice_assignments(
        text,
        speaker_genders={speaker: "male" for speaker in speakers},
    )
    assert len({casting[speaker]["voice"] for speaker in speakers}) == 5


def test_extra_voice_does_not_repeat_inside_ten_chapter_cooldown():
    speakers = [f"extra-chapter-{chapter}-s001-p01-male" for chapter in range(15)]
    text = "".join(f"[{speaker}]测试[/{speaker}]" for speaker in speakers)
    casting = build_streaming_voice_assignments(
        text,
        speaker_genders={speaker: "male" for speaker in speakers},
    )
    uses = {}
    for chapter, speaker in enumerate(speakers):
        voice = casting[speaker]["voice"]
        if voice in uses:
            assert chapter - uses[voice] >= 10
        uses[voice] = chapter


def test_false_character_fragments_are_not_created_as_speakers():
    tagged = tag_chinese_dialogue(
        "一位修士站在身旁，仰望天道。他说道：“快走。”"
    )
    assert "[一位]" not in tagged
    assert "[身旁]" not in tagged
    assert "[天道]" not in tagged


def test_empty_audio_fallback_only_changes_unnamed_minor_roles():
    import app as app_module

    neutral_voice = app_module._fallback_voice_for_unnamed_streaming_speaker(
        {"speaker": "unknown-neutral-1", "gender": "neutral"}
    )
    male_voice = app_module._fallback_voice_for_unnamed_streaming_speaker(
        {"speaker": "cn-u4e2d-u5e74-male", "gender": "male"}
    )
    female_voice = app_module._fallback_voice_for_unnamed_streaming_speaker(
        {"speaker": "extra-chapter-2-s001-role-abc-female", "gender": "female"}
    )
    assert VOICE_PRESETS[neutral_voice]["gender"] == "Male"
    assert VOICE_PRESETS[male_voice]["gender"] == "Male"
    assert VOICE_PRESETS[female_voice]["gender"] == "Female"
    assert "rational_scribe" not in {neutral_voice, male_voice, female_voice}
    assert "fox_lady" not in {neutral_voice, male_voice, female_voice}
    assert male_voice == app_module._fallback_voice_for_unnamed_streaming_speaker(
        {"speaker": "cn-u4e2d-u5e74-male", "gender": "male"}
    )
    assert app_module._fallback_voice_for_unnamed_streaming_speaker(
        {"speaker": "character-444e0b8bce", "gender": "male"}
    ) is None
    assert app_module._fallback_voice_for_unnamed_streaming_speaker(
        {"speaker": "narrator", "gender": "narrator"}
    ) is None


def test_explicit_gender_label_is_not_contaminated_by_nearby_speaker():
    tagged = tag_chinese_dialogue('男人说道：“停下。”女人回答：“不。”')

    assert "-male]“停下。”" in tagged
    assert "-female]“不。”" in tagged


def test_store_schedules_only_through_one_chapter_ahead(tmp_path: Path):
    store = StreamingStore(tmp_path / "jobs.db")
    store.init_schema()
    store.ensure_chapters(
        "job",
        [{"index": index, "title": f"第 {index + 1} 章"} for index in range(4)],
    )
    for index in range(4):
        store.ensure_segments(
            "job",
            index,
            [
                {
                    "segment_index": 0,
                    "speaker": "narrator",
                    "gender": "narrator",
                    "text": "正文",
                }
            ],
        )

    assert store.next_chapter(
        "job",
        target_index=1,
        continue_full_book=False,
    )["chapter_index"] == 0
    store.update_chapter("job", 0, state="ready")
    assert store.next_chapter(
        "job",
        target_index=1,
        continue_full_book=False,
    )["chapter_index"] == 1
    store.update_chapter("job", 1, state="ready")
    assert store.next_chapter(
        "job",
        target_index=1,
        continue_full_book=False,
    ) is None

    store.update_playback("job", chapter_index=1, playback_rate=2, state="playing")
    assert store.next_chapter(
        "job",
        target_index=2,
        continue_full_book=False,
    )["chapter_index"] == 2


def test_store_recovers_inflight_rows_without_touching_ready_audio(tmp_path: Path):
    store = StreamingStore(tmp_path / "jobs.db")
    store.init_schema()
    store.ensure_chapters("job", [{"index": 0, "title": "第一章"}])
    store.ensure_segments(
        "job",
        0,
        [
            {
                "segment_index": 0,
                "speaker": "narrator",
                "gender": "narrator",
                "text": "片段一",
            },
            {
                "segment_index": 1,
                "speaker": "hero-male",
                "gender": "male",
                "text": "片段二",
            },
        ],
    )
    store.update_segment("job", 0, 0, state="ready", relative_path="one.wav")
    store.update_segment("job", 0, 1, state="converting")
    store.update_chapter("job", 0, state="converting", ready_segments=1)
    store.recover_interrupted()
    rows = store.list_segments("job", 0)
    assert rows[0]["state"] == "ready"
    assert rows[1]["state"] == "pending"
    assert store.list_chapters("job", include_segments=False)[0]["state"] == "pending"


def test_resuming_requeues_failed_segments_without_touching_ready_audio(tmp_path: Path):
    store = StreamingStore(tmp_path / "jobs.db")
    store.init_schema()
    store.ensure_chapters("job", [{"index": 0, "title": "第一章"}])
    store.ensure_segments(
        "job",
        0,
        [
            {"segment_index": 0, "speaker": "narrator", "text": "完成"},
            {"segment_index": 1, "speaker": "unknown-neutral-1", "text": "重试"},
        ],
    )
    store.update_segment("job", 0, 0, state="ready", relative_path="one.wav")
    store.update_segment("job", 0, 1, state="failed", error="no audio")
    store.update_chapter("job", 0, state="failed")

    assert store.requeue_failed_segments("job") == [0]
    rows = store.list_segments("job", 0)
    assert rows[0]["state"] == "ready"
    assert rows[1]["state"] == "pending"
    assert store.list_chapters("job", include_segments=False)[0]["state"] == "pending"


def test_startup_auto_resume_requeues_only_interrupted_streaming_work(monkeypatch):
    import app as app_module

    class FakeQueue:
        def __init__(self):
            self.items = []

        def put(self, item):
            self.items.append(item)

    fake_queue = FakeQueue()
    recovered_entry = {
        "status": "interrupted",
        "streaming_mode": True,
        "job_payload": {"streaming_mode": True},
        "config_snapshot": {},
    }
    paused_entry = {
        "status": "paused",
        "streaming_mode": True,
        "job_payload": {"streaming_mode": True},
        "config_snapshot": {},
    }
    monkeypatch.setattr(
        app_module,
        "jobs",
        {"recover-me": recovered_entry, "leave-paused": paused_entry},
    )
    monkeypatch.setattr(app_module, "job_queue", fake_queue)
    monkeypatch.setattr(
        app_module,
        "load_config",
        lambda: {"streaming_auto_resume_after_restart": True},
    )
    monkeypatch.setattr(app_module, "start_worker_thread", lambda: None)
    monkeypatch.setattr(app_module, "_persist_job_state", lambda *_args, **_kwargs: None)

    assert app_module._auto_resume_streaming_jobs_after_restart() == 1
    assert recovered_entry["status"] == "queued"
    assert recovered_entry["streaming_phase"] == "recovering"
    assert paused_entry["status"] == "paused"
    assert len(fake_queue.items) == 1
    assert fake_queue.items[0]["job_id"] == "recover-me"


def test_character_edits_only_recast_pending_segments(tmp_path: Path):
    store = StreamingStore(tmp_path / "jobs.db")
    store.init_schema()
    character = {
        "character_id": "character-su",
        "name": "苏承",
        "aliases": ["苏承"],
        "gender": "male",
        "voice": "rational_scribe",
        "is_protagonist": True,
        "rank": 1,
    }
    store.ensure_characters("job", [character])
    store.ensure_chapters("job", [{"index": 0, "title": "第一章"}])
    store.ensure_segments(
        "job",
        0,
        [
            {
                "segment_index": 0,
                "speaker": "character-su",
                "character_id": "character-su",
                "gender": "male",
                "text": "已经完成",
                "attribution_label": "苏承",
            },
            {
                "segment_index": 1,
                "speaker": "unknown-neutral-1",
                "gender": "neutral",
                "text": "尚未生成",
                "attribution_label": "苏师弟",
            },
        ],
    )
    store.update_segment("job", 0, 0, state="ready", relative_path="done.wav")

    store.update_character(
        "job",
        "character-su",
        aliases=["苏承", "苏师弟"],
        voice="moon_guard",
    )

    rows = store.list_segments("job", 0)
    assert rows[0]["speaker"] == "character-su"
    assert rows[0]["state"] == "ready"
    assert rows[1]["speaker"] == "character-su"
    assert rows[1]["gender"] == "male"
    assert store.get_character("job", "character-su")["voice"] == "moon_guard"


def test_character_api_exposes_cast_and_updates_pending_voice(
    monkeypatch,
    tmp_path: Path,
):
    import app as app_module

    store = StreamingStore(tmp_path / "jobs.db")
    store.init_schema()
    monkeypatch.setattr(app_module, "streaming_store", store)
    monkeypatch.setattr(app_module, "_persist_job_state", lambda *_args, **_kwargs: None)
    character = {
        "character_id": "character-su",
        "name": "苏承",
        "aliases": ["苏承", "苏公子"],
        "gender": "male",
        "voice": "rational_scribe",
        "is_protagonist": True,
        "rank": 1,
        "confidence": 0.99,
    }
    store.ensure_characters("character-api-job", [character])
    app_module.jobs["character-api-job"] = {
        "status": "buffered",
        "streaming_mode": True,
        "voice_assignments": {
            "character-su": {"voice": "rational_scribe"},
        },
        "config_snapshot": {},
    }
    client = app_module.app.test_client()

    response = client.get("/api/jobs/character-api-job/characters")
    assert response.status_code == 200
    assert response.get_json()["protagonists"][0]["name"] == "苏承"

    response = client.patch(
        "/api/jobs/character-api-job/characters/character-su",
        json={"voice": "moon_guard", "aliases": ["苏承", "苏师弟"]},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["applies_to"] == "pending_segments_only"
    assert payload["character"]["voice"] == "moon_guard"
    assert app_module.jobs["character-api-job"]["voice_assignments"][
        "character-su"
    ]["voice"] == "moon_guard"
    app_module.jobs.pop("character-api-job", None)


def test_generate_api_marks_only_new_streaming_jobs_as_v3(
    monkeypatch,
    tmp_path: Path,
):
    import app as app_module

    class FakeQueue:
        def __init__(self):
            self.items = []

        def put(self, item):
            self.items.append(item)

        def qsize(self):
            return len(self.items)

    store = StreamingStore(tmp_path / "jobs.db")
    store.init_schema()
    fake_queue = FakeQueue()
    monkeypatch.setattr(app_module, "streaming_store", store)
    monkeypatch.setattr(app_module, "JOBS_DATA_DIR", tmp_path / "jobs")
    monkeypatch.setattr(app_module, "OUTPUT_DIR", tmp_path / "audio")
    monkeypatch.setattr(app_module, "job_queue", fake_queue)
    monkeypatch.setattr(app_module, "start_worker_thread", lambda: None)
    monkeypatch.setattr(app_module, "_persist_job_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(app_module, "_archive_old_jobs", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        app_module,
        "_validate_voice_assignments_for_engine",
        lambda *_args, **_kwargs: None,
    )
    source = "\n".join(
        f"第{index + 1}章 测试\n苏承走入殿内。"
        f"苏承点头。他环顾四周。苏承说道：“开始第{index + 1}章。”"
        for index in range(12)
    )
    response = app_module.app.test_client().post(
        "/api/generate",
        json={
            "text": source,
            "streaming_mode": True,
            "output_format": "wav",
        },
    )
    assert response.status_code == 200
    payload = response.get_json()
    job_id = payload["job_id"]
    queued = fake_queue.items[0]
    assert queued["streaming_pipeline_version"] == 3
    assert queued["batch_strategy"] == "adaptive_window"
    assert queued["batch_window_segments"] == 12
    assert queued["max_batch_size"] == 4
    assert Path(queued["source_text_path"]).read_text(encoding="utf-8") == source
    protagonist = store.list_characters(job_id)[0]
    assert protagonist["name"] == "苏承"
    assert protagonist["voice"] == "rational_scribe"
    assert payload["characters_url"].endswith("/characters")
    app_module.jobs.pop(job_id, None)


def test_adaptive_batch_keeps_earliest_and_only_matches_inside_window():
    import app as app_module

    rows = [
        {
            "segment_index": index,
            "speaker": "hero" if index in {0, 3, 7, 13} else "narrator",
            "gender": "male" if index in {0, 3, 7, 13} else "narrator",
            "emotion": "calm",
        }
        for index in range(14)
    ]
    assignments = {
        "hero": {"voice": "rational_scribe", "extra": {"language": "Chinese"}},
        "narrator": {"voice": "fox_lady", "extra": {"language": "Chinese"}},
    }
    selected = app_module._select_adaptive_streaming_batch(
        rows,
        assignments,
        window_segments=12,
        batch_size=4,
    )
    assert [row["segment_index"] for row in selected] == [0, 3, 7]


def test_native_qwen_batch_maps_out_of_order_results_by_sequence():
    class FakeModel:
        sample_rate = 24000

        def batch_generate(self, **_kwargs):
            return iter(
                [
                    SimpleNamespace(
                        sequence_idx=1,
                        audio=np.ones(12, dtype=np.float32),
                        sample_rate=24000,
                        peak_memory_usage=0.75,
                    ),
                    SimpleNamespace(
                        sequence_idx=0,
                        audio=np.zeros(8, dtype=np.float32),
                        sample_rate=24000,
                        peak_memory_usage=0.5,
                    ),
                ]
            )

    engine = object.__new__(Qwen3CustomVoiceEngine)
    engine.model = FakeModel()
    engine.stability_seed = 20260727
    lock = {
        "speaker": "rational_scribe",
        "instruction": "冷静",
        "audio_path": "voice.wav",
        "reference_text": "参考文本",
    }
    generated, elapsed, peak = engine._synthesize_locked_native_batch(
        [
            {"text": "第一句", "language": "Chinese", "voice_lock": lock},
            {"text": "第二句", "language": "Chinese", "voice_lock": lock},
        ]
    )

    assert list(generated) == [1, 0]
    assert generated[0][0].shape == (8,)
    assert generated[1][0].shape == (12,)
    assert elapsed > 0
    assert peak == 750


def test_prioritizing_failed_chapter_resets_its_retry_budget(tmp_path: Path):
    store = StreamingStore(tmp_path / "jobs.db")
    store.init_schema()
    store.ensure_chapters("job", [{"index": 0, "title": "第一章"}])
    store.ensure_segments(
        "job",
        0,
        [
            {
                "segment_index": 0,
                "speaker": "narrator",
                "gender": "narrator",
                "text": "正文",
            }
        ],
    )
    store.update_chapter(
        "job",
        0,
        state="failed",
        attempts=3,
        error="temporary failure",
    )

    store.prioritize("job", 0)

    chapter = store.list_chapters("job", include_segments=False)[0]
    assert chapter["state"] == "pending"
    assert chapter["attempts"] == 0
    assert chapter["error"] is None
    assert chapter["priority"] == 100


def test_store_recovery_respects_two_x_playback_headroom(tmp_path: Path):
    store = StreamingStore(tmp_path / "jobs.db")
    store.init_schema()
    store.ensure_chapters("job", [{"index": 0, "title": "第一章"}])
    store.update_playback("job", playback_rate=2, state="playing")
    store.update_chapter(
        "job",
        0,
        state="converting",
        ready_segments=3,
        playable_seconds=90,
        production_ratio=1.5,
    )

    store.recover_interrupted()

    assert store.list_chapters("job", include_segments=False)[0]["state"] == "pending"


def test_streaming_worker_publishes_two_chapters_then_parks(monkeypatch, tmp_path: Path):
    import app as app_module

    database_path = tmp_path / "jobs.db"
    output_path = tmp_path / "audio"
    output_path.mkdir()
    store = StreamingStore(database_path)
    monkeypatch.setattr(app_module, "JOBS_DB_PATH", database_path)
    monkeypatch.setattr(app_module, "OUTPUT_DIR", output_path)
    monkeypatch.setattr(app_module, "streaming_store", store)
    app_module._init_jobs_db()

    class FakeEngine:
        def generate_batch(
            self,
            *,
            segments,
            output_dir,
            chunk_cb,
            **_kwargs,
        ):
            files = []
            output_dir = Path(output_dir)
            for index, segment in enumerate(segments):
                path = output_dir / f"chunk_{index:04d}.wav"
                sf.write(path, np.zeros(800, dtype=np.float32), 8000)
                files.append(str(path))
                chunk_cb(
                    0,
                    {
                        "speaker": segment["speaker"],
                        "text": segment["text"],
                        "emotion": segment.get("emotion"),
                    },
                    str(path),
                )
            return files

    class FakeMerger:
        def __init__(self, **_kwargs):
            pass

        def merge_wav_files(self, *, input_files, output_path, **_kwargs):
            audio, sample_rate = sf.read(input_files[0], dtype="float32")
            sf.write(output_path, audio, sample_rate, format="WAV")

    class FakeRVC:
        def convert(self, *_args, **_kwargs):
            return False, "RVC test fallback"

    monkeypatch.setattr(app_module, "get_tts_engine", lambda *_args, **_kwargs: FakeEngine())
    monkeypatch.setattr(app_module, "AudioMerger", FakeMerger)
    monkeypatch.setattr(app_module, "rvc_service", FakeRVC())
    monkeypatch.setattr(
        app_module,
        "_streaming_section_layout",
        lambda *_args, **_kwargs: [
            {"index": 0, "title": "第一章", "content": "[narrator]一。[/narrator]"},
            {"index": 1, "title": "第二章", "content": "[hero-male]二。[/hero-male]"},
            {"index": 2, "title": "第三章", "content": "[heroine-female]三。[/heroine-female]"},
        ],
    )
    job_id = "stream-test"
    app_module.jobs[job_id] = {
        "status": "processing",
        "created_at": "2026-01-01T00:00:00",
        "text_path": None,
        "text_length": 3,
        "chapter_mode": True,
        "streaming_mode": True,
        "job_type": "streaming_audio",
        "config_snapshot": {},
        "voice_assignments": {},
        "job_dir": str(output_path / job_id),
        "merge_options": {},
        "chunks": [],
    }
    app_module.process_streaming_audio_job(
        {
            "job_id": job_id,
            "text": "测试",
            "voice_assignments": {},
            "config": {
                "tts_engine": "qwen3_custom",
                "chunk_size": 500,
                "output_format": "wav",
                "sample_rate": 8000,
                "speed": 1,
            },
            "buffer_chapters": 1,
            "continue_full_book": False,
            "narrator_conversion": "yae_rvc",
            "generate_full_story": False,
        }
    )

    chapters = store.list_chapters(job_id, include_segments=False)
    assert [chapter["state"] for chapter in chapters] == ["ready", "ready", "pending"]
    assert app_module.jobs[job_id]["status"] == "buffered"
    assert Path(output_path / job_id / chapters[0]["relative_path"]).is_file()
    assert not any(output_path.rglob("*.partial"))
    assert not any(output_path.rglob(".work"))


def test_v2_worker_adapts_from_two_to_four_and_records_metrics(
    monkeypatch,
    tmp_path: Path,
):
    import app as app_module

    database_path = tmp_path / "jobs.db"
    output_path = tmp_path / "audio"
    output_path.mkdir()
    store = StreamingStore(database_path)
    monkeypatch.setattr(app_module, "JOBS_DB_PATH", database_path)
    monkeypatch.setattr(app_module, "OUTPUT_DIR", output_path)
    monkeypatch.setattr(app_module, "streaming_store", store)
    app_module._init_jobs_db()
    observed_batch_sizes = []

    class FakeEngine:
        def generate_batch(
            self,
            *,
            segments,
            output_dir,
            chunk_cb,
            **_kwargs,
        ):
            observed_batch_sizes.append(len(segments))
            output_dir = Path(output_dir)
            files = []
            for index, segment in enumerate(segments):
                path = output_dir / f"chunk_{index:04d}.wav"
                sf.write(path, np.zeros(800, dtype=np.float32), 8000)
                files.append(str(path))
                chunk_cb(
                    0,
                    {
                        "speaker": segment["speaker"],
                        "text": segment["text"],
                        "segment_index": index,
                        "chunk_index": 0,
                        "batch_size": len(segments),
                        "qwen_seconds": 0.1,
                        "batch_peak_memory_mb": 512,
                    },
                    str(path),
                )
            return files

    class FakeMerger:
        def __init__(self, **_kwargs):
            pass

        def merge_wav_files(self, *, input_files, output_path, **_kwargs):
            audio, sample_rate = sf.read(input_files[0], dtype="float32")
            sf.write(output_path, audio, sample_rate, format="WAV")

    monkeypatch.setattr(
        app_module,
        "get_tts_engine",
        lambda *_args, **_kwargs: FakeEngine(),
    )
    monkeypatch.setattr(app_module, "AudioMerger", FakeMerger)
    monkeypatch.setattr(
        app_module,
        "_streaming_section_layout",
        lambda *_args, **_kwargs: [
            {
                "index": 0,
                "title": "第一章",
                "content": "第一章正文",
                "source_start": 0,
            },
            {
                "index": 1,
                "title": "第二章",
                "content": "第二章正文",
                "source_start": 5,
            },
            {
                "index": 2,
                "title": "第三章",
                "content": "第三章正文",
                "source_start": 10,
            },
        ],
    )
    monkeypatch.setattr(
        app_module,
        "_flatten_streaming_segments",
        lambda *_args, **_kwargs: [
            {
                "segment_index": index,
                "speaker": "narrator",
                "gender": "narrator",
                "emotion": None,
                "text": f"旁白 {index}",
                "attribution_source": "narration",
                "attribution_confidence": 1,
            }
            for index in range(8)
        ],
    )
    job_id = "stream-v2-test"
    app_module.jobs[job_id] = {
        "status": "processing",
        "created_at": "2026-01-01T00:00:00",
        "text_path": None,
        "text_length": 15,
        "chapter_mode": True,
        "streaming_mode": True,
        "streaming_pipeline_version": 2,
        "job_type": "streaming_audio",
        "config_snapshot": {},
        "voice_assignments": {},
        "job_dir": str(output_path / job_id),
        "merge_options": {},
        "chunks": [],
    }
    app_module.process_streaming_audio_job(
        {
            "job_id": job_id,
            "text": "第一章正文第二章正文第三章正文",
            "source_text": "第一章正文第二章正文第三章正文",
            "voice_assignments": {},
            "config": {
                "tts_engine": "qwen3_custom",
                "chunk_size": 500,
                "output_format": "wav",
                "sample_rate": 8000,
                "speed": 1,
            },
            "streaming_pipeline_version": 2,
            "batch_strategy": "adaptive_window",
            "batch_window_segments": 12,
            "max_batch_size": 4,
            "buffer_chapters": 1,
            "continue_full_book": False,
            "narrator_conversion": "none",
            "generate_full_story": False,
        }
    )

    chapters = store.list_chapters(job_id, include_segments=True)
    assert [chapter["state"] for chapter in chapters] == [
        "ready",
        "ready",
        "pending",
    ]
    assert observed_batch_sizes[:3] == [2, 2, 4]
    assert max(observed_batch_sizes) == 4
    assert chapters[0]["qwen_seconds"] > 0
    assert chapters[0]["peak_memory_mb"] == 512
    assert {row["batch_size"] for row in chapters[0]["segments"]} == {2, 4}
    assert app_module.jobs[job_id]["status"] == "buffered"
    assert not any(output_path.rglob("*.partial"))
    assert not any(output_path.rglob(".work"))


def test_v2_qwen_and_rvc_work_overlap_without_converting_character_lines(
    monkeypatch,
    tmp_path: Path,
):
    import app as app_module

    store = StreamingStore(tmp_path / "jobs.db")
    output_path = tmp_path / "audio"
    output_path.mkdir()
    monkeypatch.setattr(app_module, "streaming_store", store)
    monkeypatch.setattr(app_module, "OUTPUT_DIR", output_path)
    monkeypatch.setattr(app_module, "jobs", {})
    monkeypatch.setattr(app_module, "_persist_job_state", lambda *_args, **_kwargs: None)
    store.init_schema()

    class FakeEngine:
        def generate_batch(self, *, segments, output_dir, chunk_cb, **_kwargs):
            output_dir = Path(output_dir)
            for index, segment in enumerate(segments):
                path = output_dir / f"chunk_{index:04d}.wav"
                sf.write(path, np.zeros(800, dtype=np.float32), 8000)
                chunk_cb(
                    0,
                    {
                        "speaker": segment["speaker"],
                        "text": segment["text"],
                        "segment_index": index,
                        "chunk_index": 0,
                        "batch_size": len(segments),
                        "qwen_seconds": 0.04,
                        "batch_peak_memory_mb": 400,
                    },
                    str(path),
                )
            time.sleep(0.08)
            return []

    class FakeRVC:
        calls = 0

        def convert(self, source, target, _config):
            self.calls += 1
            time.sleep(0.06)
            shutil.copyfile(source, target)
            return True, None

    class FakeMerger:
        def __init__(self, **_kwargs):
            pass

        def merge_wav_files(self, *, input_files, output_path, **_kwargs):
            audio, sample_rate = sf.read(input_files[0], dtype="float32")
            sf.write(output_path, audio, sample_rate, format="WAV")

    fake_rvc = FakeRVC()
    monkeypatch.setattr(app_module, "rvc_service", fake_rvc)
    monkeypatch.setattr(
        app_module,
        "get_tts_engine",
        lambda *_args, **_kwargs: FakeEngine(),
    )
    monkeypatch.setattr(app_module, "AudioMerger", FakeMerger)
    monkeypatch.setattr(
        app_module,
        "_streaming_section_layout",
        lambda *_args, **_kwargs: [
            {
                "index": 0,
                "title": "第一章",
                "content": "正文",
                "source_start": 0,
            }
        ],
    )
    monkeypatch.setattr(
        app_module,
        "_flatten_streaming_segments",
        lambda *_args, **_kwargs: [
            {
                "segment_index": index,
                "speaker": "narrator" if index != 2 else "hero",
                "gender": "narrator" if index != 2 else "male",
                "emotion": None,
                "text": f"片段 {index}",
                "attribution_source": "narration",
                "attribution_confidence": 1,
            }
            for index in range(6)
        ],
    )
    job_id = "stream-overlap-test"
    app_module.jobs[job_id] = {
        "status": "processing",
        "created_at": "2026-01-01T00:00:00",
        "streaming_mode": True,
        "streaming_pipeline_version": 2,
        "job_type": "streaming_audio",
        "config_snapshot": {},
        "voice_assignments": {
            "narrator": {"voice": "fox_lady"},
            "hero": {"voice": "rational_scribe"},
        },
        "job_dir": str(output_path / job_id),
        "chunks": [],
    }
    app_module.process_streaming_audio_job(
        {
            "job_id": job_id,
            "text": "正文",
            "source_text": "正文",
            "voice_assignments": app_module.jobs[job_id]["voice_assignments"],
            "config": {
                "tts_engine": "qwen3_custom",
                "chunk_size": 500,
                "output_format": "wav",
                "sample_rate": 8000,
                "speed": 1,
            },
            "streaming_pipeline_version": 2,
            "batch_strategy": "adaptive_window",
            "batch_window_segments": 12,
            "max_batch_size": 4,
            "buffer_chapters": 1,
            "continue_full_book": False,
            "narrator_conversion": "yae_rvc",
            "generate_full_story": False,
        }
    )
    chapter = store.list_chapters(job_id, include_segments=True)[0]
    assert chapter["state"] == "ready"
    assert chapter["overlap_seconds"] > 0
    narrator_rows = [
        row for row in chapter["segments"] if row["gender"] == "narrator"
    ]
    hero_rows = [row for row in chapter["segments"] if row["gender"] == "male"]
    assert fake_rvc.calls == len(narrator_rows)
    assert all(row["converted"] == 1 for row in narrator_rows)
    assert all(row["converted"] == 0 for row in hero_rows)
