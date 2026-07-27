"""Deterministic Chinese dialogue tagging fallback.

Small local language models occasionally rewrite or omit source text even when
asked not to.  This module only inserts speaker tags around Chinese quotation
marks, so it can never change the novel itself.  It is intentionally
conservative: uncertain speakers receive a neutral role instead of a guessed
identity or gender.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Optional


_CHINESE_RE = re.compile(r"[\u3400-\u9fff]")
_DIALOGUE_RE = re.compile(r"“[^”]*”|「[^」]*」|『[^』]*』")
_CLAUSE_BREAK_RE = re.compile(r"[。！？；\n]")

_SPEECH_VERB = (
    r"(?:低声|轻声|沉声|朗声|冷冷地|笑着|哭着|忽然|缓缓)?"
    r"(?:说道|说|问道|问|答道|回答|答|喊道|喊|叫道|叫|"
    r"笑道|喝道|嚷道|嘟囔道|喃喃道|回应|回道|开口道|开口)"
)

_PRONOUNS = {"他", "她"}
_FEMALE_HINTS = ("她", "女人", "女子", "少女", "姑娘", "女孩", "夫人", "小姐", "母亲", "姐姐", "妹妹", "女王")
_MALE_HINTS = ("他", "男人", "男子", "少年", "男孩", "先生", "父亲", "哥哥", "弟弟", "将军", "公子", "老者")
_ROLE_LABELS = (
    "男人|女人|男子|女子|少年|少女|男孩|女孩|老人|老者|小姑娘|"
    "先生|小姐|夫人|将军|掌柜|店主|老板|师父|师尊|母亲|父亲|"
    "哥哥|姐姐|弟弟|妹妹|侍卫|守卫|士兵|医生|护士|老师|同学|"
    "女王|国王|皇帝|皇后|声音"
)
_SPEAKER_LABEL = rf"(?:他|她|{_ROLE_LABELS}|[\u3400-\u9fff]{{2,4}}?)"


def _last_clause(value: str) -> str:
    return _CLAUSE_BREAK_RE.split(value)[-1].strip()


def _first_clause(value: str) -> str:
    return _CLAUSE_BREAK_RE.split(value, maxsplit=1)[0].strip()


def _speaker_before_quote(prefix: str) -> Optional[str]:
    clause = _last_clause(prefix)
    if not clause:
        return None
    match = re.search(
        rf"^(?:这时|此时|忽然|只见|随后|接着)?"
        rf"(?P<label>{_SPEAKER_LABEL})"
        rf"[^，。！？；]{{0,24}}?(?:，|,)?{_SPEECH_VERB}[：:]?\s*$",
        clause,
    )
    return match.group("label") if match else None


def _speaker_after_quote(suffix: str) -> Optional[str]:
    clause = _first_clause(suffix)
    if not clause:
        return None
    match = re.match(
        rf"^[，,、]?\s*(?P<label>{_SPEAKER_LABEL})"
        rf"[^，。！？；]{{0,24}}?(?:，|,)?{_SPEECH_VERB}",
        clause,
    )
    return match.group("label") if match else None


def _infer_gender(label: str) -> str:
    if any(hint in label for hint in _FEMALE_HINTS):
        return "female"
    if any(hint in label for hint in _MALE_HINTS):
        return "male"
    return "neutral"


def _unicode_slug(label: str, gender: str) -> str:
    encoded = "-".join(f"u{ord(char):x}" for char in label if _CHINESE_RE.match(char))
    return f"cn-{encoded or 'role'}-{gender}"


@dataclass
class _SpeakerState:
    by_label: Dict[str, str] = field(default_factory=dict)
    last_by_gender: Dict[str, str] = field(default_factory=dict)
    anonymous_count: int = 0

    def resolve(self, label: Optional[str]) -> str:
        if label in _PRONOUNS:
            gender = _infer_gender(label or "")
            existing = self.last_by_gender.get(gender)
            if existing:
                return existing

        if label:
            existing = self.by_label.get(label)
            if existing:
                return existing
            gender = _infer_gender(label)
            tag = _unicode_slug(label, gender)
            self.by_label[label] = tag
            self.last_by_gender[gender] = tag
            return tag

        self.anonymous_count += 1
        tag = f"character-{self.anonymous_count}-neutral"
        self.last_by_gender["neutral"] = tag
        return tag


def tag_chinese_dialogue(source_text: str) -> Optional[str]:
    """Insert balanced narrator/speaker tags without changing source text.

    Returns ``None`` when the input is not Chinese or contains no supported
    Chinese quotation marks, allowing callers to keep their original error.
    """
    text = source_text or ""
    if not _CHINESE_RE.search(text) or not _DIALOGUE_RE.search(text):
        return None

    state = _SpeakerState()
    output = []
    cursor = 0

    for match in _DIALOGUE_RE.finditer(text):
        narration = text[cursor:match.start()]
        if narration.strip():
            output.append(f"[narrator]{narration.strip()}[/narrator]")

        prefix = text[max(0, match.start() - 90):match.start()]
        suffix = text[match.end():match.end() + 90]
        label = _speaker_before_quote(prefix) or _speaker_after_quote(suffix)
        speaker = state.resolve(label)
        output.append(f"[{speaker}]{match.group(0)}[/{speaker}]")
        cursor = match.end()

    trailing = text[cursor:]
    if trailing.strip():
        output.append(f"[narrator]{trailing.strip()}[/narrator]")

    return "\n".join(output) if output else None
