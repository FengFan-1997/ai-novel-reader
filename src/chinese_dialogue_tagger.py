"""Deterministic Chinese dialogue tagging fallback.

Small local language models occasionally rewrite or omit source text even when
asked not to.  This module only inserts speaker tags around Chinese quotation
marks, so it can never change the novel itself.  It is intentionally
conservative: uncertain speakers receive a neutral role instead of a guessed
identity or gender.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .chinese_character_analyzer import looks_like_character_name


_CHINESE_RE = re.compile(r"[\u3400-\u9fff]")
_DIALOGUE_RE = re.compile(r"“[^”]*”|「[^」]*」|『[^』]*』")
_CLAUSE_BREAK_RE = re.compile(r"[。！？；\n]")

_SPEECH_VERB = (
    r"(?:低声|轻声|沉声|朗声|冷冷地|笑着|哭着|忽然|缓缓)?"
    r"(?:(?:随声|跟着|接着)?附和(?:了一句|道)?|接话(?:道|说)?|应声(?:道|说)?|应和(?:道|说)?|"
    r"说道|说|问道|问|答道|回答|答|喊道|喊|叫道|叫|"
    r"笑道|冷笑道|喝道|嚷道|嘟囔道|喃喃道|回应|回道|"
    r"开口道|开口|转口道|道)"
)

_PRONOUNS = {"他", "她"}
_FEMALE_HINTS = ("她", "女人", "女子", "少女", "姑娘", "女孩", "夫人", "小姐", "母亲", "姐姐", "妹妹", "女王", "女修")
_MALE_HINTS = ("他", "男人", "男子", "少年", "男孩", "先生", "父亲", "哥哥", "弟弟", "将军", "公子", "老者", "壮汉", "汉子", "男修")
_ROLE_LABELS = (
    "男人|女人|男子|女子|少年|少女|男孩|女孩|老人|老者|壮汉|虬髯汉子|汉子|青年|小姑娘|"
    "先生|小姐|夫人|将军|掌柜|店主|老板|师父|师尊|母亲|父亲|"
    "哥哥|姐姐|弟弟|妹妹|侍卫|守卫|士兵|医生|护士|老师|同学|"
    "女王|国王|皇帝|皇后|反派|敌人|男修士|女修士|年轻修士|修士|弟子|众人|声音"
)
_SPEAKER_LABEL = rf"(?:他|她|{_ROLE_LABELS})"
_POTENTIAL_NAME = r"[\u3400-\u9fff]{2,4}"
_SCENE_BREAK_RE = re.compile(
    r"(?:\n\s*\n|^\s*(?:——+|\*{3,})\s*$|"
    r"(?:翌日|次日|第二天|与此同时|另一边|数日后|多年后|夜幕降临|清晨时分)[，。])",
    flags=re.MULTILINE,
)
_CONTINUATION_RE = re.compile(
    r"(?:顿了顿|停顿片刻|继续(?:说道|说|问|道)|接着(?:说道|说|问|道)|"
    r"又(?:说道|说|问|道)|补充道|话锋一转|没有停下|紧接着)"
)
_INNER_MONOLOGUE_RE = re.compile(
    r"(?:心中|心里|脑海|暗自|暗暗|默默|思忖|沉吟|念头|自言自语|喃喃自语)"
)
_COLON_ACTION_RE = re.compile(r"[：:]\s*$")
_GENERIC_VOCATIVES = {
    "你", "你们", "兄弟", "哥们", "兄台", "老兄", "小兄弟", "大哥", "大姐",
    "姑娘", "小姐", "公子", "道友", "前辈", "师父", "师尊", "师兄", "师弟",
    "师姐", "师妹",
}
_CROWD_VOCATIVES = {"乡亲们", "诸位", "各位", "大家"}
_NON_FOCUS_ROLE_LABELS = {
    "众人", "声音", "修士", "男修士", "女修士", "年轻修士", "弟子", "士兵", "同学",
}
_REACTION_AFTER_QUOTE_RE = re.compile(
    r"(?:闻言|听罢|听后|听见|听到|一怔|愣住|愣了|错愕|诧异|惊讶)"
)
_ACTOR_ACTION_RE = re.compile(
    r"(?:随声附和|跟着附和|附和|接话|应声|应和|笑|哭|皱眉|点头|摇头|抬手|抬眼|垂眸|抓|搓手|激动|扯着|"
    r"转身|上前|后退|开口|低声|沉声|轻声|大声|嚷|喊|说道|笑道|问道|答道|问|答)"
)


def _last_clause(value: str) -> str:
    return _CLAUSE_BREAK_RE.split(value)[-1].strip().lstrip("”」』\"'，, ")


def _first_clause(value: str) -> str:
    return _CLAUSE_BREAK_RE.split(value, maxsplit=1)[0].strip().lstrip("”」』\"'，, ")


def _known_alias_near_speech(
    clause: str,
    alias_lookup: Optional[Dict[str, Dict[str, Any]]],
) -> Optional[str]:
    if not alias_lookup or not re.search(rf"{_SPEECH_VERB}[：:]?\s*$", clause):
        return None
    speech_match = re.search(rf"{_SPEECH_VERB}[：:]?\s*$", clause)
    if not speech_match:
        return None
    before_verb = clause[:speech_match.start()]
    matches = [
        (before_verb.rfind(alias), alias)
        for alias in alias_lookup
        if before_verb.rfind(alias) >= 0
    ]
    if not matches:
        return None
    position, alias = max(matches)
    return alias if len(before_verb) - position <= 48 else None


def _speaker_before_quote(
    prefix: str,
    alias_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Optional[str]:
    clause = _last_clause(prefix)
    if not clause:
        return None
    known = _known_alias_near_speech(clause, alias_lookup)
    if known:
        return known
    match = re.search(
        rf"^(?:这时|此时|忽然|只见|随后|接着)?"
        rf"(?P<label>{_SPEAKER_LABEL})"
        rf"[^，。！？；]{{0,24}}?(?:，|,)?{_SPEECH_VERB}[：:]?\s*$",
        clause,
    )
    if match:
        return match.group("label")

    # A known character may speak after an action ending in a colon without a
    # literal “说道”, e.g. “苏承笑了笑：‘……’”. Prefer the nearest known alias;
    # never manufacture an arbitrary two-character label here.
    if alias_lookup and _COLON_ACTION_RE.search(clause):
        matches = [
            (clause.rfind(alias), alias)
            for alias in alias_lookup
            if clause.rfind(alias) >= 0
        ]
        if matches:
            position, alias = max(matches)
            if len(clause) - position <= 64:
                return alias

    if _COLON_ACTION_RE.search(clause):
        role_actor = re.match(
            rf"^(?:身旁|旁边|对面|身后|前方|那名|这名)?"
            rf"(?P<label>{_SPEAKER_LABEL})",
            clause,
        )
        if role_actor:
            label = role_actor.group("label")
            actor_tail = clause[role_actor.end():]
            if (
                not _REACTION_AFTER_QUOTE_RE.search(actor_tail)
                and _ACTOR_ACTION_RE.search(actor_tail)
            ):
                return label

    # Unknown but syntactically explicit Chinese names are admitted only when
    # the strict surname/name guard accepts them and they directly own a speech
    # action. This blocks fragments such as “一位”“身旁”“天道”.
    potential = re.search(
        rf"(?P<label>{_POTENTIAL_NAME})"
        rf"[^，。！？；：“”\n]{{0,8}}?{_SPEECH_VERB}[：:]?\s*$",
        clause,
    )
    if potential and looks_like_character_name(potential.group("label")):
        return potential.group("label")
    return None


def _speaker_after_quote(
    suffix: str,
    alias_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Optional[str]:
    clause = _first_clause(suffix)
    if clause:
        if alias_lookup:
            speech_match = re.search(_SPEECH_VERB, clause)
            if speech_match:
                before_verb = clause[:speech_match.start()]
                matches = [
                    (before_verb.rfind(alias), alias)
                    for alias in alias_lookup
                    if before_verb.rfind(alias) >= 0
                ]
                if matches:
                    position, alias = max(matches)
                    if position <= 12:
                        return alias
        match = re.match(
            rf"^[，,、]?\s*(?P<label>{_SPEAKER_LABEL})"
            rf"[^，。！？；]{{0,24}}?(?:，|,)?{_SPEECH_VERB}",
            clause,
        )
        if match:
            return match.group("label")
        potential = re.match(
            rf"^[，,、]?\s*(?P<label>{_POTENTIAL_NAME})"
            rf"[^，。！？；：“”\n]{{0,8}}?{_SPEECH_VERB}",
            clause,
        )
        if potential and looks_like_character_name(potential.group("label")):
            return potential.group("label")

    # A quote may be followed by its speaker's action rather than “某某说”,
    # e.g. “呼……” 身旁壮汉激动地搓手.  Accept only concrete actors with an
    # action cue and reject listener-reaction prose such as “苏承闻言一怔”.
    action_clause = str(suffix or "").lstrip()
    if action_clause and action_clause[0] not in "“「『":
        action_clause = re.split(r"[。！？\n]", action_clause, maxsplit=1)[0]
        actor_label = None
        if alias_lookup:
            matches = [
                (action_clause.find(alias), alias)
                for alias in alias_lookup
                if 0 <= action_clause.find(alias) <= 6
            ]
            if matches:
                actor_label = min(matches)[1]
        if actor_label is None:
            role_match = re.match(
                rf"^(?:身旁|旁边|对面|身后|前方|那名|这名)?"
                rf"(?P<label>{_SPEAKER_LABEL})",
                action_clause,
            )
            if role_match:
                actor_label = role_match.group("label")
        if actor_label:
            actor_tail = action_clause[action_clause.find(actor_label) + len(actor_label):]
            if (
                not _REACTION_AFTER_QUOTE_RE.search(actor_tail)
                and _ACTOR_ACTION_RE.search(actor_tail)
            ):
                return actor_label
    return None


def _infer_gender(label: str) -> str:
    if any(hint in label for hint in _FEMALE_HINTS):
        return "female"
    if any(hint in label for hint in _MALE_HINTS):
        return "male"
    name = str(label or "")[:4]
    if any(char in name for char in "婉晚雪月兰娜莉瑶柔妍婷倩琳萱薇晴"):
        return "female"
    if any(char in name for char in "强刚勇军伟峰舟杰豪雄"):
        return "male"
    return "neutral"


def _unicode_slug(label: str, gender: str) -> str:
    encoded = "-".join(f"u{ord(char):x}" for char in label if _CHINESE_RE.match(char))
    return f"cn-{encoded or 'role'}-{gender}"


@dataclass
class _SpeakerState:
    by_label: Dict[str, str] = field(default_factory=dict)
    last_by_gender: Dict[str, str] = field(default_factory=dict)
    gender_by_speaker: Dict[str, str] = field(default_factory=dict)
    alias_lookup: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    scene_characters: List[str] = field(default_factory=list)
    scene_label_speakers: Dict[str, str] = field(default_factory=dict)
    last_speaker: Optional[str] = None
    last_mentioned_character: Optional[str] = None
    context_focus_speaker: Optional[str] = None
    context_focus_distance: int = 10_000
    monologue_speaker: Optional[str] = None
    scene_key: str = "chapter-0"
    scene_index: int = 1
    scene_extra_count: int = 0

    @classmethod
    def from_characters(
        cls,
        characters: Optional[List[Dict[str, Any]]] = None,
        *,
        scene_key: str = "chapter-0",
    ) -> "_SpeakerState":
        state = cls(scene_key=re.sub(r"[^a-zA-Z0-9_-]+", "-", scene_key or "chapter-0"))
        for character in characters or []:
            character_id = str(character.get("character_id") or "").strip().lower()
            if not character_id:
                continue
            gender = str(character.get("gender") or "neutral").lower()
            state.gender_by_speaker[character_id] = gender
            labels = [
                str(character.get("name") or "").strip(),
                *[
                    str(alias or "").strip()
                    for alias in (character.get("aliases") or [])
                ],
            ]
            for label in labels:
                if not label:
                    continue
                state.by_label[label] = character_id
                state.alias_lookup[label] = character
        return state

    def _remember(self, speaker: str) -> None:
        if speaker in self.scene_characters:
            self.scene_characters.remove(speaker)
        self.scene_characters.append(speaker)
        self.scene_characters = self.scene_characters[-12:]
        gender = self.gender_by_speaker.get(speaker, "neutral")
        if gender in {"male", "female"}:
            self.last_by_gender[gender] = speaker

    def new_scene(self) -> None:
        self.scene_index += 1
        self.scene_characters = []
        self.scene_label_speakers = {}
        self.last_speaker = None
        self.last_mentioned_character = None
        self.context_focus_speaker = None
        self.context_focus_distance = 10_000
        self.monologue_speaker = None
        self.scene_extra_count = 0

    def _scene_speaker_for_label(
        self,
        label: str,
        gender: str,
        *,
        mentioned_only: bool = False,
    ) -> str:
        existing = self.scene_label_speakers.get(label)
        if existing:
            return existing
        safe_gender = gender if gender in {"male", "female"} else "male"
        # “男人 / 汉子 / 虬髯汉子 / 壮汉” often describe the same unnamed
        # person in successive narration.  When this scene has exactly one
        # unnamed person of that gender, bind the new role noun as an alias
        # instead of inventing a second character and voice.
        if re.fullmatch(rf"(?:{_ROLE_LABELS})", label):
            compatible_extras = [
                speaker
                for speaker in self.scene_characters
                if speaker.startswith("extra-")
                and self.gender_by_speaker.get(speaker) == safe_gender
            ]
            if len(compatible_extras) == 1:
                speaker = compatible_extras[0]
                self.scene_label_speakers[label] = speaker
                self.by_label[label] = speaker
                if not mentioned_only:
                    self._remember(speaker)
                return speaker
        digest = hashlib.sha1(label.encode("utf-8")).hexdigest()[:8]
        speaker = (
            f"extra-{self.scene_key}-s{self.scene_index:03d}-"
            f"role-{digest}-{safe_gender}"
        )
        self.scene_label_speakers[label] = speaker
        self.by_label[label] = speaker
        self.gender_by_speaker[speaker] = safe_gender
        if mentioned_only:
            if speaker not in self.scene_characters:
                self.scene_characters.append(speaker)
        else:
            self._remember(speaker)
        return speaker

    def _new_scene_extra(self, gender: str = "male") -> str:
        safe_gender = gender if gender in {"male", "female"} else "male"
        self.scene_extra_count += 1
        speaker = (
            f"extra-{self.scene_key}-s{self.scene_index:03d}-"
            f"p{self.scene_extra_count:02d}-{safe_gender}"
        )
        self.gender_by_speaker[speaker] = safe_gender
        self._remember(speaker)
        return speaker

    def observe_context(self, context: str) -> None:
        value = str(context or "")
        if _SCENE_BREAK_RE.search(value):
            self.new_scene()
        self.context_focus_speaker = None
        self.context_focus_distance = 10_000
        occurrences: List[Tuple[int, str, bool, str]] = []
        for alias, character in self.alias_lookup.items():
            position = value.rfind(alias)
            if position >= 0:
                occurrences.append((
                    position,
                    str(character["character_id"]).lower(),
                    True,
                    alias,
                ))

        # Track concrete role nouns mentioned in the current scene. They may
        # describe the same person under several names (男人/汉子/壮汉).
        # Collective nouns remain scene context but never become the focus of
        # a following singular reply.
        for role_match in re.finditer(rf"(?:{_ROLE_LABELS})", value):
            label = role_match.group(0)
            if label in {"声音"}:
                continue
            gender = _infer_gender(label)
            speaker = self._scene_speaker_for_label(
                label,
                gender,
                mentioned_only=True,
            )
            occurrences.append((
                role_match.start(),
                speaker,
                label not in _NON_FOCUS_ROLE_LABELS,
                label,
            ))

        for position, speaker, can_focus, label in sorted(occurrences):
            self._remember(speaker)
            if can_focus:
                self.last_mentioned_character = speaker
                self.context_focus_speaker = speaker
                self.context_focus_distance = max(
                    0,
                    len(value) - position - len(label),
                )

        inner_matches = list(_INNER_MONOLOGUE_RE.finditer(value))
        if value.strip() and not inner_matches:
            self.monologue_speaker = None
        if (
            inner_matches
            and len(value) - inner_matches[-1].end() <= 80
            and self.last_mentioned_character
        ):
            self.monologue_speaker = self.last_mentioned_character

    def resolve(
        self,
        label: Optional[str],
        context: str = "",
        *,
        narration: str = "",
        dialogue: str = "",
        trailing_previous_action: bool = False,
    ) -> Tuple[str, str, float]:
        if label in _PRONOUNS:
            gender = _infer_gender(label or "")
            existing = self.last_by_gender.get(gender)
            if existing:
                self.last_speaker = existing
                return existing, "pronoun_context", 0.82

        if label:
            existing = self.by_label.get(label)
            if existing:
                gender = self.gender_by_speaker.get(existing, "neutral")
                if gender in {"male", "female"}:
                    self.last_by_gender[gender] = existing
                self._remember(existing)
                self.last_speaker = existing
                self.monologue_speaker = None
                return existing, "explicit_character", 0.98
            # An explicit label such as “男人” or “她” is stronger evidence
            # than nearby prose. Only consult context when the label itself is
            # neutral, otherwise a following “女人回答” can flip a male line.
            gender = _infer_gender(label)
            if gender == "neutral":
                gender = _infer_gender(context)
            tag = self._scene_speaker_for_label(label, gender)
            self.last_speaker = tag
            self.monologue_speaker = None
            return tag, "explicit_label", 0.86

        if _CONTINUATION_RE.search(narration) and self.last_speaker:
            return self.last_speaker, "speaker_continuation", 0.88

        if self.monologue_speaker and (
            not narration.strip() or _INNER_MONOLOGUE_RE.search(narration)
        ):
            self.last_speaker = self.monologue_speaker
            self._remember(self.monologue_speaker)
            return self.monologue_speaker, "inner_monologue", 0.86

        # In a scene containing exactly two known characters, an unattributed
        # reply can alternate to the other participant.  More crowded scenes
        # stay unknown rather than assigning the protagonist by convenience.
        known_scene = list(dict.fromkeys(self.scene_characters))
        dialogue_body = str(dialogue or "").strip().lstrip("“「『\"'").strip()
        addressed_speaker = None
        for alias in sorted(self.by_label, key=len, reverse=True):
            if re.match(rf"^{re.escape(alias)}\s*[，,！!]", dialogue_body):
                addressed_speaker = self.by_label[alias]
                break
        generic_vocative = any(
            re.match(rf"^{re.escape(vocative)}\s*[，,！!]", dialogue_body)
            for vocative in _GENERIC_VOCATIVES
        )
        crowd_vocative = any(
            re.match(rf"^{re.escape(vocative)}\s*[，,！!]", dialogue_body)
            for vocative in _CROWD_VOCATIVES
        )
        if crowd_vocative:
            speaker = self._new_scene_extra("male")
            self.last_speaker = speaker
            return speaker, "crowd_address", 0.72
        if (
            len(known_scene) == 2
            and (addressed_speaker or generic_vocative)
        ):
            addressee = (
                addressed_speaker
                if addressed_speaker in known_scene
                else (
                    self.context_focus_speaker
                    if self.context_focus_speaker in known_scene
                    else (
                        self.last_speaker
                        if self.last_speaker in known_scene
                        else self.last_mentioned_character
                    )
                )
            )
            if addressee in known_scene:
                speaker = next(item for item in known_scene if item != addressee)
                self.last_speaker = speaker
                self._remember(speaker)
                gender = self.gender_by_speaker.get(speaker, "neutral")
                if gender in {"male", "female"}:
                    self.last_by_gender[gender] = speaker
                return speaker, "direct_address_turn", 0.78
        if (
            narration.strip()
            and not trailing_previous_action
            and self.context_focus_speaker in known_scene
            and self.context_focus_distance <= 48
        ):
            speaker = str(self.context_focus_speaker)
            self.last_speaker = speaker
            self._remember(speaker)
            gender = self.gender_by_speaker.get(speaker, "neutral")
            if gender in {"male", "female"}:
                self.last_by_gender[gender] = speaker
            return speaker, "narrative_focus", 0.74
        if self.last_speaker is None and self.last_mentioned_character:
            speaker = self.last_mentioned_character
            self.last_speaker = speaker
            self._remember(speaker)
            return speaker, "scene_focus", 0.64
        if len(known_scene) == 2 and self.last_speaker in known_scene:
            speaker = next(
                item for item in known_scene if item != self.last_speaker
            )
            self.last_speaker = speaker
            gender = self.gender_by_speaker.get(speaker, "neutral")
            if gender in {"male", "female"}:
                self.last_by_gender[gender] = speaker
            return speaker, "two_person_turn", 0.68

        if len(known_scene) == 1 and self.last_speaker == known_scene[0]:
            tag = self._new_scene_extra("male")
            self.last_speaker = tag
            return tag, "scene_partner", 0.52

        # Unknown participants are scoped to this scene.  They are not four
        # global fake people shared by a 550-chapter book. In a crowded scene,
        # an unattributed line is not assigned to the last non-speaker: that
        # low-confidence guess is exactly what makes an agreeing reply sound
        # like the preceding character.
        tag = self._new_scene_extra("male")
        self.last_speaker = tag
        return tag, "scene_extra", 0.25


@dataclass(frozen=True)
class DialogueTaggingResult:
    tagged_text: str
    attributions: List[Dict[str, Any]]


def tag_chinese_dialogue_detailed(
    source_text: str,
    characters: Optional[List[Dict[str, Any]]] = None,
    *,
    scene_key: str = "chapter-0",
) -> Optional[DialogueTaggingResult]:
    """Tag Chinese dialogue and retain source/provenance metadata."""
    text = source_text or ""
    if not _CHINESE_RE.search(text) or not _DIALOGUE_RE.search(text):
        return None

    state = _SpeakerState.from_characters(characters, scene_key=scene_key)
    output: List[str] = []
    attributions: List[Dict[str, Any]] = []
    cursor = 0

    for match in _DIALOGUE_RE.finditer(text):
        narration = text[cursor:match.start()]
        if narration.strip():
            output.append(f"[narrator]{narration.strip()}[/narrator]")
        state.observe_context(narration)

        prefix = text[max(0, match.start() - 120):match.start()]
        suffix = text[match.end():match.end() + 120]
        before = _speaker_before_quote(prefix, state.alias_lookup)
        after = _speaker_after_quote(suffix, state.alias_lookup)
        label = before or after
        speaker, source, confidence = state.resolve(
            label,
            f"{prefix}{suffix}",
            narration=narration,
            dialogue=match.group(0),
            trailing_previous_action=(
                cursor > 0
                and bool(narration)
                and not narration[0].isspace()
            ),
        )
        if source.startswith("explicit"):
            source = "explicit_before" if before else "explicit_after"
        output.append(f"[{speaker}]{match.group(0)}[/{speaker}]")
        attributions.append(
            {
                "source_start": match.start(),
                "source_end": match.end(),
                "speaker": speaker,
                "character_id": speaker if speaker.startswith("character-") else None,
                "gender": state.gender_by_speaker.get(
                    speaker,
                    _infer_gender(label or ""),
                ),
                "label": label,
                "source": source,
                "confidence": confidence,
                "scene_id": f"{state.scene_key}-s{state.scene_index:03d}",
                "speaker_role": (
                    "named"
                    if speaker.startswith("character-")
                    else "extra"
                ),
                "evidence": {
                    "before": before,
                    "after": after,
                    "scene_characters": list(state.scene_characters),
                },
                "text": match.group(0),
            }
        )
        cursor = match.end()

    trailing = text[cursor:]
    if trailing.strip():
        output.append(f"[narrator]{trailing.strip()}[/narrator]")

    return DialogueTaggingResult(
        tagged_text="\n".join(output),
        attributions=attributions,
    )


def tag_chinese_dialogue(
    source_text: str,
    characters: Optional[List[Dict[str, Any]]] = None,
    *,
    scene_key: str = "chapter-0",
) -> Optional[str]:
    """Insert balanced narrator/speaker tags without changing source text.

    Returns ``None`` when the input is not Chinese or contains no supported
    Chinese quotation marks, allowing callers to keep their original error.
    """
    result = tag_chinese_dialogue_detailed(
        source_text,
        characters,
        scene_key=scene_key,
    )
    return result.tagged_text if result else None


__all__ = [
    "DialogueTaggingResult",
    "tag_chinese_dialogue",
    "tag_chinese_dialogue_detailed",
]
