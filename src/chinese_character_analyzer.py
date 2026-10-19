"""Book-level Chinese character and protagonist analysis.

The streaming reader deliberately uses deterministic rules here.  A local LLM
may still be used by the editor, but audiobook generation must be restartable
and must never silently rewrite the source novel.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence


_HAN_RE = re.compile(r"[\u3400-\u9fff]")
_TAG_RE = re.compile(
    r"\[/?(?:emotion|[a-zA-Z0-9_\-]+)\]",
    flags=re.IGNORECASE,
)
_EMOTION_BLOCK_RE = re.compile(
    r"\[emotion\].*?\[/emotion\]\s*",
    flags=re.IGNORECASE | re.DOTALL,
)
_SPEECH_VERB = (
    r"(?:说道|说罢|说|问道|问|答道|回答|答|喊道|喊|叫道|叫|"
    r"笑道|冷笑道|喝道|嚷道|嘟囔道|喃喃道|回应|回道|"
    r"开口道|开口|低声道|轻声道|沉声道|朗声道|转口道|道)"
)
_COMMON_SURNAMES = set(
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华"
    "金魏陶姜戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方"
    "俞任袁柳酆鲍史唐费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅"
    "皮卞齐康伍余元卜顾孟平黄和穆萧尹姚邵湛汪祁毛禹狄米贝明臧"
    "计伏成戴谈宋茅庞熊纪舒屈项祝董梁杜阮蓝闵席季麻强贾路娄危"
    "江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍虞万支柯昝管卢莫"
    "经房裘缪干解应宗丁宣贲邓郁单杭洪包诸左石崔吉龚程嵇邢滑裴"
    "陆荣翁荀羊於惠甄曲家封芮羿储靳汲邴糜松井段富巫乌焦巴弓牧"
    "隗山谷车侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘钭厉戎祖武符刘景"
    "詹束龙叶幸司韶郜黎蓟薄印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙池"
    "乔阴郁胥能苍双闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍却璩桑桂濮"
    "牛寿通边扈燕冀郏浦尚农温别庄晏柴瞿阎充慕连茹习宦艾鱼容向"
    "古易慎戈廖庾终暨居衡步都耿满弘匡国文寇广禄阙东欧殳沃利蔚"
    "越夔隆师巩厍聂晁勾敖融冷訾辛阚那简饶空曾毋沙乜养鞠须丰巢"
    "关蒯相查后荆红游竺权逯盖益桓公"
)
_COMPOUND_SURNAMES = (
    "欧阳",
    "司马",
    "上官",
    "诸葛",
    "夏侯",
    "东方",
    "皇甫",
    "尉迟",
    "公孙",
    "慕容",
    "宇文",
    "司徒",
    "司空",
    "令狐",
    "长孙",
    "轩辕",
)
_NAME_STOPWORDS = {
    "自己",
    "什么",
    "怎么",
    "这个",
    "那个",
    "这里",
    "那里",
    "如此",
    "只是",
    "不是",
    "已经",
    "没有",
    "可以",
    "因为",
    "所以",
    "但是",
    "然后",
    "现在",
    "方才",
    "此时",
    "这时",
    "其中",
    "身旁",
    "周围",
    "众人",
    "有人",
    "对方",
    "二人",
    "几人",
    "一人",
    "师父",
    "师尊",
    "师兄",
    "师弟",
    "师姐",
    "师妹",
    "长老",
    "宗主",
    "掌柜",
    "男人",
    "女人",
    "男子",
    "女子",
    "少年",
    "少女",
    "老者",
    "声音",
    "陡然",
    "忽然",
    "随后",
    "接着",
    "闻言",
    "只见",
    "不由",
    "在这",
    "于此",
    "连忙",
    "那些",
    "看来",
    "想到",
    "听到",
    "看到",
    "感觉",
    "知道",
    "发现",
    "此刻",
    "片刻",
    "一旁",
    "宗门",
    "那么",
    "古怪",
    "万界",
    "终究",
    "周身",
    "应声",
    "解释",
    "那位",
    "古仙",
    "满脸",
    "应该",
    "冷静",
    "许多",
    "平静",
    "双眼",
    "温柔",
    "怀里",
    "诸多",
    "都不",
    "施展",
    "许久",
    "都要",
    "双眸",
    "关切",
    "都已",
    "余光",
    "怀中",
    "诸位",
    "明白",
    "时间",
    "时日",
    "后方",
    "冷淡",
    "莫名",
    "冷冷",
    "通红",
    "索性",
    "和笑",
    "万分",
    "冷声",
    "万千",
    "宫主",
    "宫宫主",
    "却见",
    "却不",
    "温家",
    "沙哑",
    "安抚",
    "满意",
    "冷冽",
    "白袍",
    "宫宫",
    "顾四周",
    "顾四",
    "温声",
}
_BAD_NAME_CHARACTERS = set("的是了着过在和与及而却也又便才都就把被让给向从对为于所其这那哪谁")
_BAD_NAME_SUFFIXES = (
    "低声",
    "轻声",
    "沉声",
    "笑道",
    "轻笑",
    "冷笑",
    "说道",
    "问道",
    "开口",
    "转口",
    "说",
    "问",
    "答",
    "道",
    "失笑",
    "笑呵",
    "宫主",
)
_TITLE_SUFFIXES = (
    "师弟",
    "师兄",
    "师姐",
    "师妹",
    "宗主",
    "掌门",
    "公子",
    "姑娘",
    "小姐",
    "先生",
    "长老",
    "道友",
    "前辈",
    "兄",
)
_MALE_TITLES = ("师弟", "师兄", "公子", "兄", "先生", "少爷", "父亲", "哥哥", "弟弟")
_FEMALE_TITLES = ("师姐", "师妹", "姑娘", "小姐", "夫人", "母亲", "姐姐", "妹妹")
_MALE_VOICES = (
    "rational_scribe",
    "moon_guard",
    "maple_swordsman",
    "cloud_general",
    "battle_friend",
    "gilded_gambler",
    "choir_priest",
    "scarred_blade",
    "wild_ranger",
    "ancient_gentleman",
    "chief_justice",
    "wind_bard",
    "silent_adeptus",
    "sharp_wanderer",
    "yanshu",
    "ash_prince",
)
_FEMALE_VOICES = (
    "frost_master",
    "songbird",
    "gentle_firefly",
    "rose_leader",
    "qingxia",
    "tangxing",
    "velvet_hunter",
    "void_walker",
    "cyber_girl",
    "cyber_ace",
    "sky_general",
    "dream_oracle",
    "genius_madam",
    "stage_queen",
    "mischief_director",
    "eternal_shogun",
    "hearth_father",
    "sun_chief",
    "forest_sage",
)


def strip_speaker_tags(text: str) -> str:
    """Return the source prose contained in speaker/emotion tags."""
    without_emotions = _EMOTION_BLOCK_RE.sub("", str(text or ""))
    return _TAG_RE.sub("", without_emotions)


def sampled_chapter_indices(chapter_count: int) -> List[int]:
    """Return stable first/middle/last-three indices without duplicates."""
    count = max(0, int(chapter_count))
    if not count:
        return []
    middle = count // 2
    candidates = [
        0,
        1,
        2,
        middle - 1,
        middle,
        middle + 1,
        count - 3,
        count - 2,
        count - 1,
    ]
    return sorted({index for index in candidates if 0 <= index < count})


def extract_synopsis(text: str, limit: int = 4000) -> str:
    """Return front matter before the first numbered chapter heading."""
    value = strip_speaker_tags(text)
    heading = re.search(
        r"(?m)^\s*第\s*[一二三四五六七八九十百千万零〇两0-9]+\s*章[^\n]*$",
        value,
    )
    front_matter = value[:heading.start()] if heading else ""
    return front_matter[:max(0, int(limit))]


def _looks_like_name(value: str) -> bool:
    name = str(value or "").strip()
    if len(name) not in {2, 3, 4} or name in _NAME_STOPWORDS:
        return False
    if not re.fullmatch(r"[\u3400-\u9fff]{2,4}", name):
        return False
    if any(name.endswith(suffix) for suffix in _BAD_NAME_SUFFIXES):
        return False
    if any(char in _BAD_NAME_CHARACTERS for char in name[1:]):
        return False
    if name[:2] in _COMPOUND_SURNAMES:
        return len(name) in {3, 4}
    return name[0] in _COMMON_SURNAMES


def looks_like_character_name(value: str) -> bool:
    """Public strict name guard shared by the scene dialogue tagger.

    It deliberately rejects arbitrary two-to-four character fragments such as
    “一位”“身旁”“天道”.  A fantasy name that does not use a common surname is
    still accepted once it has been discovered as a durable alias at book
    level; this guard is only for creating a *new* identity from raw prose.
    """
    return _looks_like_name(value)


def _candidate_names(sample_texts: Sequence[str]) -> List[str]:
    """Find likely names, favouring speech labels and repeated surname tokens."""
    candidates: Counter[str] = Counter()

    speech_pattern = re.compile(
        rf"(?P<label>[\u3400-\u9fff]{{2,4}})"
        rf"[^，。！？；：“”\n]{{0,10}}?{_SPEECH_VERB}\s*[：:]?[“「『]",
    )
    for text in sample_texts:
        for match in speech_pattern.finditer(text):
            label = match.group("label")
            # The regex can begin too early in a Chinese clause.  Prefer the
            # shortest surname-looking suffix nearest the speech action.
            suffixes = [
                label[-length:]
                for length in (2, 3, 4)
                if len(label) >= length and _looks_like_name(label[-length:])
            ]
            if suffixes:
                candidates[min(suffixes, key=len)] += 8

    # A protagonist can speak without an attribution.  Repeated surname-like
    # two/three-character tokens provide a conservative second source.
    for text in sample_texts:
        for index, char in enumerate(text):
            if char not in _COMMON_SURNAMES:
                continue
            for length in (2, 3):
                token = text[index:index + length]
                if _looks_like_name(token):
                    candidates[token] += 1
        for surname in _COMPOUND_SURNAMES:
            start = 0
            while True:
                start = text.find(surname, start)
                if start < 0:
                    break
                for length in (3, 4):
                    token = text[start:start + length]
                    if _looks_like_name(token):
                        candidates[token] += 1
                start += len(surname)

    # Suppress three-character spillovers such as “苏承被” when the two
    # character name accounts for most occurrences of the prefix.
    # Full books can produce tens of thousands of surname-shaped fragments.
    # Only the strongest few hundred could enter the final top 80, so avoid an
    # O(book_size × all_candidates) rescan that can exhaust a 16 GB Mac.
    shortlist = [
        name
        for name, weight in candidates.most_common(400)
        if weight >= 3
    ]
    actual_mentions: Counter[str] = Counter()
    for text in sample_texts:
        for name in shortlist:
            count = text.count(name)
            if count:
                actual_mentions[name] += count
    names = []
    shortlist_set = set(shortlist)
    for name, weight in candidates.most_common(400):
        if name not in shortlist_set:
            continue
        if len(name) == 3:
            prefix_weight = candidates.get(name[:2], 0)
            if prefix_weight >= max(5, int(weight * 1.35)):
                continue
        if len(name) == 2:
            longer = [
                other
                for other in shortlist
                if len(other) == 3
                and (other.startswith(name) or other.endswith(name))
                and actual_mentions.get(other, 0)
                >= actual_mentions.get(name, 0) * 0.75
            ]
            if longer:
                continue
        if weight >= 3:
            names.append(name)
    return names[:80]


def _count_speech_attributions(name: str, text: str) -> int:
    before = re.compile(
        rf"{re.escape(name)}[^，。！？；：“”\n]{{0,12}}?{_SPEECH_VERB}\s*[：:]?[“「『]"
    )
    after = re.compile(
        rf"[”」』][，,、]?\s*{re.escape(name)}"
        rf"[^，。！？；：“”\n]{{0,12}}?{_SPEECH_VERB}"
    )
    return len(before.findall(text)) + len(after.findall(text))


def _infer_gender(name: str, sample_text: str) -> tuple[str, float]:
    escaped = re.escape(name)
    male = len(
        re.findall(
            rf"{escaped}[^。！？\n]{{0,40}}[。！？]\s*他",
            sample_text,
        )
    )
    female = len(
        re.findall(
            rf"{escaped}[^。！？\n]{{0,40}}[。！？]\s*她",
            sample_text,
        )
    )
    male += 5 * sum(sample_text.count(f"{name}{title}") for title in _MALE_TITLES)
    female += 5 * sum(sample_text.count(f"{name}{title}") for title in _FEMALE_TITLES)
    male += 4 * len(
        re.findall(
            rf"(?:少年|男子|男人|男修|青年)(?:名叫|唤作)?{escaped}|"
            rf"{escaped}(?:这个|这名|乃是|是个)?(?:少年|男子|男人|男修|青年)",
            sample_text,
        )
    )
    female += 4 * len(
        re.findall(
            rf"(?:少女|女子|女人|女修)(?:名叫|唤作)?{escaped}|"
            rf"{escaped}(?:这个|这名|乃是|是个)?(?:少女|女子|女人|女修)",
            sample_text,
        )
    )
    if male >= max(2, female * 2):
        return "male", min(0.99, 0.72 + (male / max(20, male + female)) * 0.25)
    if female >= max(2, male * 2):
        return "female", min(0.99, 0.72 + (female / max(20, male + female)) * 0.25)
    return "neutral", 0.45


def _discover_aliases(name: str, sample_text: str, all_names: Sequence[str]) -> List[str]:
    aliases = [name]
    surname = name[:2] if name[:2] in _COMPOUND_SURNAMES else name[0]
    unique_surname = sum(
        1
        for other in all_names
        if other != name and other.startswith(surname)
    ) == 0
    for suffix in _TITLE_SUFFIXES:
        alias = f"{surname}{suffix}"
        if alias not in sample_text:
            continue
        co_reference = re.search(
            rf"(?:{re.escape(name)}.{{0,120}}{re.escape(alias)}|"
            rf"{re.escape(alias)}.{{0,120}}{re.escape(name)})",
            sample_text,
            flags=re.DOTALL,
        )
        if co_reference or (
            unique_surname and _count_speech_attributions(alias, sample_text) > 0
        ):
            aliases.append(alias)
    return aliases


def _character_id(name: str, gender: str) -> str:
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:10]
    # Gender is editable.  Keeping it out of the durable identifier prevents a
    # later correction from changing every segment foreign key.
    return f"character-{digest}"


def analyze_book_characters(
    chapters: Iterable[Dict[str, Any]],
    *,
    synopsis: str = "",
    allow_multiple_protagonists: bool = True,
    max_protagonists: Optional[int] = None,
    scan_all_chapters: bool = True,
) -> List[Dict[str, Any]]:
    """Analyze the complete book and return a durable cast table.

    ``scan_all_chapters`` exists only for backwards-compatible lightweight
    callers.  Streaming V3 always scans every chapter so a heroine introduced
    in the middle of a long book cannot be missed by a nine-chapter sample.
    """
    chapter_list = list(chapters)
    indices = (
        list(range(len(chapter_list)))
        if scan_all_chapters
        else sampled_chapter_indices(len(chapter_list))
    )
    samples = [
        strip_speaker_tags(str(chapter_list[index].get("content") or ""))
        for index in indices
    ]
    if not samples:
        return []

    candidates = _candidate_names(samples)
    combined = "\n".join(samples)
    chapter_count = len(chapter_list)
    first_cut = max(1, chapter_count // 3)
    second_cut = max(first_cut + 1, (chapter_count * 2) // 3)
    regions = {
        "start": set(range(0, min(first_cut, chapter_count))),
        "middle": set(range(first_cut, min(second_cut, chapter_count))),
        "end": set(range(second_cut, chapter_count)),
    }
    scored: List[Dict[str, Any]] = []
    for name in candidates:
        mentions_by_sample = [sample.count(name) for sample in samples]
        mentions = sum(mentions_by_sample)
        if mentions < 3:
            continue
        speech = sum(_count_speech_attributions(name, sample) for sample in samples)
        covered_indices = {
            indices[position]
            for position, count in enumerate(mentions_by_sample)
            if count > 0
        }
        covered_regions = [
            region
            for region, region_indices in regions.items()
            if covered_indices & region_indices
        ]
        synopsis_mentions = strip_speaker_tags(synopsis).count(name)
        if speech <= 0 and not (
            synopsis_mentions > 0 and len(covered_regions) >= 2
        ):
            continue
        score = (
            float(mentions)
            + float(speech * 8)
            + float(len(covered_regions) * 30)
            + float(synopsis_mentions * 24)
        )
        gender, gender_confidence = _infer_gender(name, combined)
        scored.append(
            {
                "name": name,
                "mention_count": mentions,
                "speech_count": speech,
                "sample_chapter_count": len(covered_indices),
                "coverage_regions": covered_regions,
                "coverage_count": len(covered_regions),
                "synopsis_mentions": synopsis_mentions,
                "score": round(score, 3),
                "gender": gender,
                "gender_confidence": round(gender_confidence, 3),
            }
        )

    scored.sort(
        key=lambda item: (
            float(item["score"]),
            int(item["coverage_count"]),
            int(item["mention_count"]),
        ),
        reverse=True,
    )
    canonical_scored: List[Dict[str, Any]] = []
    for item in scored:
        name = str(item["name"])
        if any(
            name.startswith(str(existing["name"]))
            and len(name) > len(str(existing["name"]))
            for existing in canonical_scored
        ):
            continue
        canonical_scored.append(item)
    scored = canonical_scored
    if not scored:
        return []

    top_score = max(1.0, float(scored[0]["score"]))
    protagonist_names = {scored[0]["name"]}
    if allow_multiple_protagonists:
        for item in scored[1:]:
            if (
                max_protagonists is not None
                and len(protagonist_names) >= max(1, int(max_protagonists))
            ):
                break
            if (
                float(item["score"]) >= top_score * 0.55
                and int(item["coverage_count"]) >= 2
            ):
                protagonist_names.add(item["name"])

    all_names = [item["name"] for item in scored]
    profiles: List[Dict[str, Any]] = []
    for rank, item in enumerate(scored[:120], start=1):
        is_protagonist = item["name"] in protagonist_names
        gender = str(item["gender"])
        recurring = (
            int(item["sample_chapter_count"]) >= 3
            and int(item["speech_count"]) >= 8
        )
        prominent = (
            float(item["score"]) >= top_score * 0.35
            and int(item["coverage_count"]) >= 2
        )
        role_tier = (
            "lead"
            if is_protagonist or prominent or int(item["synopsis_mentions"]) > 0
            else ("recurring" if recurring else "extra")
        )
        confidence = min(
            0.995,
            0.5
            + 0.22 * min(1.0, float(item["score"]) / top_score)
            + 0.08 * int(item["coverage_count"])
            + 0.08 * min(1.0, int(item["speech_count"]) / 12),
        )
        aliases = _discover_aliases(item["name"], combined, all_names)
        profiles.append(
            {
                "character_id": _character_id(item["name"], gender),
                "name": item["name"],
                "aliases": aliases,
                "gender": gender,
                "voice": "",
                "is_protagonist": is_protagonist,
                "role_tier": role_tier,
                "voice_locked": role_tier in {"lead", "recurring"},
                "rank": rank,
                "confidence": round(confidence, 3),
                "score": item["score"],
                "mention_count": item["mention_count"],
                "speech_count": item["speech_count"],
                "sample_chapter_count": item["sample_chapter_count"],
                "appearance_chapter_count": item["sample_chapter_count"],
                "coverage_regions": item["coverage_regions"],
                "coverage_count": item["coverage_count"],
                "synopsis_mentions": item["synopsis_mentions"],
                "evidence": {
                    "sampling": "full_book" if scan_all_chapters else "first_middle_last",
                    "scan_scope": "full_book" if scan_all_chapters else "sampled",
                    "scanned_chapter_count": len(indices),
                    "sample_indices": (
                        sampled_chapter_indices(chapter_count)
                        if scan_all_chapters
                        else indices
                    ),
                    "gender_confidence": item["gender_confidence"],
                },
            }
        )
    return assign_character_voices(profiles)


def assign_character_voices(
    characters: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Allocate stable, gender-safe voices without a four-person cap."""
    profiles = [dict(character) for character in characters]
    used: Dict[str, set[str]] = {"male": set(), "female": set()}
    slots = {"male": 0, "female": 0}

    # The highest-ranked male lead is the established young male lead voice.
    lead_male = next(
        (
            item
            for item in sorted(profiles, key=lambda row: int(row.get("rank") or 9999))
            if str(item.get("gender") or "") == "male"
            and bool(item.get("is_protagonist"))
        ),
        None,
    )
    if lead_male:
        lead_male["voice"] = "rational_scribe"
        used["male"].add("rational_scribe")

    for profile in sorted(profiles, key=lambda row: int(row.get("rank") or 9999)):
        gender = str(profile.get("gender") or "neutral").lower()
        selected = str(profile.get("voice") or "")
        if profile is lead_male:
            continue
        pool = _MALE_VOICES if gender == "male" else _FEMALE_VOICES if gender == "female" else ()
        if not pool:
            profile["voice"] = ""
            continue
        if selected in pool and selected not in used[gender]:
            used[gender].add(selected)
            continue
        available = [voice for voice in pool if voice not in used[gender]]
        if available:
            selected = available[0]
        else:
            # More named roles than prepared locks: retain deterministic
            # identity for now. Cast audit exposes the collision so a derived
            # VoiceDesign lock can be created before synthesis.
            selected = pool[slots[gender] % len(pool)]
        slots[gender] += 1
        profile["voice"] = selected
        if str(profile.get("role_tier") or "extra") in {"lead", "recurring"}:
            used[gender].add(selected)
    return profiles


def _character_excerpts(
    chapters: Sequence[Dict[str, Any]],
    name: str,
    *,
    limit: int = 3,
) -> List[str]:
    excerpts: List[str] = []
    for chapter in chapters:
        text = strip_speaker_tags(str(chapter.get("content") or ""))
        start = 0
        while len(excerpts) < limit:
            position = text.find(name, start)
            if position < 0:
                break
            left = max(0, position - 90)
            right = min(len(text), position + len(name) + 130)
            excerpt = re.sub(r"\s+", " ", text[left:right]).strip()
            if excerpt and excerpt not in excerpts:
                excerpts.append(excerpt)
            start = position + len(name)
        if len(excerpts) >= limit:
            break
    return excerpts


def _extract_json_array(value: str) -> List[Dict[str, Any]]:
    raw = str(value or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", raw, re.DOTALL)
    candidate = fenced.group(1) if fenced else raw
    if not candidate.startswith("["):
        match = re.search(r"\[.*\]", candidate, re.DOTALL)
        candidate = match.group(0) if match else ""
    try:
        decoded = json.loads(candidate)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return [item for item in decoded if isinstance(item, dict)] if isinstance(decoded, list) else []


def refine_characters_with_llm(
    characters: Iterable[Dict[str, Any]],
    chapters: Iterable[Dict[str, Any]],
    generate: Callable[[str], str],
    *,
    batch_size: int = 8,
) -> List[Dict[str, Any]]:
    """Use Ollama only to review cast facts; source prose is never rewritten."""
    profiles = [dict(character) for character in characters]
    chapter_list = list(chapters)
    combined = "\n".join(
        strip_speaker_tags(str(chapter.get("content") or ""))
        for chapter in chapter_list
    )
    by_name = {str(item.get("name") or ""): item for item in profiles}
    reviewable = [
        item
        for item in profiles
        if item.get("role_tier") in {"lead", "recurring"}
        or str(item.get("gender") or "neutral") == "neutral"
    ][:48]

    for offset in range(0, len(reviewable), max(1, int(batch_size))):
        batch = reviewable[offset:offset + max(1, int(batch_size))]
        evidence = [
            {
                "name": item.get("name"),
                "current_gender": item.get("gender"),
                "mentions": item.get("mention_count"),
                "speeches": item.get("speech_count"),
                "chapters": item.get("appearance_chapter_count"),
                "excerpts": _character_excerpts(
                    chapter_list,
                    str(item.get("name") or ""),
                ),
            }
            for item in batch
        ]
        prompt = (
            "你是中文小说人物表校对器。只根据证据判断，不续写正文。"
            "返回严格 JSON 数组，每项字段为 name、gender（male/female/neutral）、"
            "aliases（数组）、role_tier（lead/recurring/extra）、confidence（0到1）、reason。"
            "姓名只是书名或普通短语时增加 invalid:true。性别证据不足必须 neutral。\n"
            + json.dumps(evidence, ensure_ascii=False)
        )
        try:
            reviews = _extract_json_array(generate(prompt))
        except Exception:
            continue
        for review in reviews:
            name = str(review.get("name") or "").strip()
            profile = by_name.get(name)
            if not profile:
                continue
            confidence = max(0.0, min(float(review.get("confidence") or 0), 1.0))
            if review.get("invalid") and confidence >= 0.75:
                profile["invalid"] = True
                profile.setdefault("evidence", {})["llm_reason"] = str(review.get("reason") or "")
                continue
            gender = str(review.get("gender") or "neutral").lower()
            if gender in {"male", "female"} and confidence >= 0.62:
                profile["gender"] = gender
                profile.setdefault("evidence", {})["gender_confidence"] = confidence
                profile["gender_confidence"] = confidence
            role_tier = str(review.get("role_tier") or "").lower()
            if role_tier in {"lead", "recurring", "extra"} and confidence >= 0.62:
                if role_tier in {"lead", "recurring"} or profile.get("role_tier") == "extra":
                    profile["role_tier"] = role_tier
            aliases = [str(alias or "").strip() for alias in review.get("aliases") or []]
            for alias in aliases:
                if (
                    alias
                    and len(alias) <= 12
                    and alias in combined
                    and alias not in profile.get("aliases", [])
                ):
                    profile.setdefault("aliases", []).append(alias)
            profile["voice_locked"] = profile.get("role_tier") in {"lead", "recurring"}
            profile.setdefault("evidence", {})["llm_reason"] = str(review.get("reason") or "")

    return assign_character_voices(
        profile for profile in profiles if not profile.get("invalid")
    )


__all__ = [
    "analyze_book_characters",
    "assign_character_voices",
    "extract_synopsis",
    "looks_like_character_name",
    "refine_characters_with_llm",
    "sampled_chapter_indices",
    "strip_speaker_tags",
]
