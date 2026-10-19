"""Durable state for chapter-first audiobook generation.

The regular job table stores coarse queue state.  These tables deliberately keep
chapter and segment state separate so a browser can start playing finalized
segments while the worker continues rendering later material.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


CHAPTER_STATES = {
    "pending",
    "analyzing",
    "synthesizing",
    "converting",
    "streamable",
    "ready",
    "failed",
}

SEGMENT_STATES = {
    "pending",
    "synthesizing",
    "converting",
    "ready",
    "failed",
}


def can_release_streaming_audio(
    *,
    ready_segments: int,
    playable_seconds: float,
    render_seconds: float,
    playback_rate: float,
    minimum_buffer_seconds: float = 90,
) -> bool:
    """Whether a partial chapter has enough measured headroom to start."""
    if ready_segments < 3 or playable_seconds < minimum_buffer_seconds:
        return False
    if render_seconds <= 0:
        return False
    production_ratio = playable_seconds / render_seconds
    return production_ratio >= max(0.25, playback_rate) * 1.25


def _now() -> str:
    return datetime.now().isoformat()


class StreamingStore:
    """Small SQLite repository used by the streaming worker and HTTP routes."""

    def __init__(self, database_path: Path | str):
        self.database_path = str(database_path)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS job_chapters (
                    job_id TEXT NOT NULL,
                    chapter_index INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending',
                    total_segments INTEGER NOT NULL DEFAULT 0,
                    ready_segments INTEGER NOT NULL DEFAULT 0,
                    playable_seconds REAL NOT NULL DEFAULT 0,
                    duration_seconds REAL NOT NULL DEFAULT 0,
                    render_seconds REAL NOT NULL DEFAULT 0,
                    production_ratio REAL NOT NULL DEFAULT 0,
                    qwen_seconds REAL NOT NULL DEFAULT 0,
                    rvc_seconds REAL NOT NULL DEFAULT 0,
                    overlap_seconds REAL NOT NULL DEFAULT 0,
                    peak_memory_mb REAL NOT NULL DEFAULT 0,
                    current_batch_size INTEGER NOT NULL DEFAULT 1,
                    relative_path TEXT,
                    legacy_relative_path TEXT,
                    generation_version INTEGER NOT NULL DEFAULT 2,
                    recast_state TEXT,
                    error TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    priority INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (job_id, chapter_index)
                );

                CREATE TABLE IF NOT EXISTS job_segments (
                    job_id TEXT NOT NULL,
                    chapter_index INTEGER NOT NULL,
                    segment_index INTEGER NOT NULL,
                    speaker TEXT NOT NULL,
                    character_id TEXT,
                    gender TEXT NOT NULL DEFAULT 'neutral',
                    emotion TEXT,
                    state TEXT NOT NULL DEFAULT 'pending',
                    text TEXT NOT NULL,
                    relative_path TEXT,
                    duration_seconds REAL NOT NULL DEFAULT 0,
                    render_seconds REAL NOT NULL DEFAULT 0,
                    qwen_seconds REAL NOT NULL DEFAULT 0,
                    rvc_seconds REAL NOT NULL DEFAULT 0,
                    batch_size INTEGER NOT NULL DEFAULT 1,
                    peak_memory_mb REAL NOT NULL DEFAULT 0,
                    source_start INTEGER,
                    source_end INTEGER,
                    attribution_label TEXT,
                    attribution_source TEXT,
                    attribution_confidence REAL NOT NULL DEFAULT 0,
                    scene_id TEXT,
                    speaker_role TEXT,
                    content_hash TEXT,
                    generation_version INTEGER NOT NULL DEFAULT 2,
                    inference_evidence TEXT NOT NULL DEFAULT '{}',
                    legacy_relative_path TEXT,
                    converted INTEGER NOT NULL DEFAULT 0,
                    warning TEXT,
                    error TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (job_id, chapter_index, segment_index)
                );

                CREATE TABLE IF NOT EXISTS job_characters (
                    job_id TEXT NOT NULL,
                    character_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    aliases TEXT NOT NULL DEFAULT '[]',
                    gender TEXT NOT NULL DEFAULT 'neutral',
                    voice TEXT,
                    is_protagonist INTEGER NOT NULL DEFAULT 0,
                    rank INTEGER NOT NULL DEFAULT 0,
                    confidence REAL NOT NULL DEFAULT 0,
                    score REAL NOT NULL DEFAULT 0,
                    mention_count INTEGER NOT NULL DEFAULT 0,
                    speech_count INTEGER NOT NULL DEFAULT 0,
                    sample_chapter_count INTEGER NOT NULL DEFAULT 0,
                    coverage_regions TEXT NOT NULL DEFAULT '[]',
                    evidence TEXT NOT NULL DEFAULT '{}',
                    role_tier TEXT NOT NULL DEFAULT 'extra',
                    voice_locked INTEGER NOT NULL DEFAULT 0,
                    appearance_chapter_count INTEGER NOT NULL DEFAULT 0,
                    gender_confidence REAL NOT NULL DEFAULT 0,
                    gender_evidence TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (job_id, character_id)
                );

                CREATE TABLE IF NOT EXISTS job_playback (
                    job_id TEXT PRIMARY KEY,
                    chapter_index INTEGER NOT NULL DEFAULT 0,
                    current_time REAL NOT NULL DEFAULT 0,
                    duration REAL NOT NULL DEFAULT 0,
                    playback_rate REAL NOT NULL DEFAULT 1,
                    state TEXT NOT NULL DEFAULT 'idle',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS job_cast_audits (
                    job_id TEXT NOT NULL,
                    pipeline_version INTEGER NOT NULL DEFAULT 3,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (job_id, pipeline_version)
                );

                CREATE INDEX IF NOT EXISTS idx_job_chapters_state
                    ON job_chapters(job_id, state, priority, chapter_index);
                CREATE INDEX IF NOT EXISTS idx_job_segments_state
                    ON job_segments(job_id, chapter_index, state, segment_index);
                CREATE INDEX IF NOT EXISTS idx_job_characters_rank
                    ON job_characters(job_id, is_protagonist DESC, rank ASC);
                """
            )
            # Keep schema upgrades local and non-destructive for existing jobs.
            segment_columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(job_segments)").fetchall()
            }
            segment_upgrades = {
                "attempts": "INTEGER NOT NULL DEFAULT 0",
                "character_id": "TEXT",
                "qwen_seconds": "REAL NOT NULL DEFAULT 0",
                "rvc_seconds": "REAL NOT NULL DEFAULT 0",
                "batch_size": "INTEGER NOT NULL DEFAULT 1",
                "peak_memory_mb": "REAL NOT NULL DEFAULT 0",
                "source_start": "INTEGER",
                "source_end": "INTEGER",
                "attribution_label": "TEXT",
                "attribution_source": "TEXT",
                "attribution_confidence": "REAL NOT NULL DEFAULT 0",
                "scene_id": "TEXT",
                "speaker_role": "TEXT",
                "content_hash": "TEXT",
                "generation_version": "INTEGER NOT NULL DEFAULT 2",
                "inference_evidence": "TEXT NOT NULL DEFAULT '{}'",
                "legacy_relative_path": "TEXT",
            }
            for column, declaration in segment_upgrades.items():
                if column not in segment_columns:
                    conn.execute(
                        f"ALTER TABLE job_segments ADD COLUMN {column} {declaration}"
                    )
            chapter_columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(job_chapters)").fetchall()
            }
            chapter_upgrades = {
                "qwen_seconds": "REAL NOT NULL DEFAULT 0",
                "rvc_seconds": "REAL NOT NULL DEFAULT 0",
                "overlap_seconds": "REAL NOT NULL DEFAULT 0",
                "peak_memory_mb": "REAL NOT NULL DEFAULT 0",
                "current_batch_size": "INTEGER NOT NULL DEFAULT 1",
                "legacy_relative_path": "TEXT",
                "generation_version": "INTEGER NOT NULL DEFAULT 2",
                "recast_state": "TEXT",
            }
            for column, declaration in chapter_upgrades.items():
                if column not in chapter_columns:
                    conn.execute(
                        f"ALTER TABLE job_chapters ADD COLUMN {column} {declaration}"
                    )
            character_columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(job_characters)").fetchall()
            }
            character_upgrades = {
                "role_tier": "TEXT NOT NULL DEFAULT 'extra'",
                "voice_locked": "INTEGER NOT NULL DEFAULT 0",
                "appearance_chapter_count": "INTEGER NOT NULL DEFAULT 0",
                "gender_confidence": "REAL NOT NULL DEFAULT 0",
                "gender_evidence": "TEXT NOT NULL DEFAULT '{}'",
            }
            for column, declaration in character_upgrades.items():
                if column not in character_columns:
                    conn.execute(
                        f"ALTER TABLE job_characters ADD COLUMN {column} {declaration}"
                    )
            conn.commit()

    def recover_interrupted(self) -> None:
        """Return in-flight rows to a resumable state after a process restart."""
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE job_segments
                SET state='pending', error=NULL, updated_at=?
                WHERE state IN ('synthesizing', 'converting')
                """,
                (_now(),),
            )
            conn.execute(
                """
                UPDATE job_chapters
                SET state=CASE
                        WHEN ready_segments >= 3
                             AND playable_seconds >= 90
                             AND production_ratio >= (
                                 1.25 * MAX(
                                     0.25,
                                     COALESCE(
                                         (
                                             SELECT playback_rate
                                             FROM job_playback
                                             WHERE job_playback.job_id = job_chapters.job_id
                                         ),
                                         1
                                     )
                                 )
                             )
                        THEN 'streamable'
                        ELSE 'pending'
                    END,
                    error=NULL, updated_at=?
                WHERE state IN ('analyzing', 'synthesizing', 'converting')
                """,
                (_now(),),
            )
            conn.commit()

    def prepare_recast(
        self,
        job_id: str,
        chapters: Iterable[Dict[str, Any]],
        chapter_segments: Dict[int, Iterable[Dict[str, Any]]],
        *,
        generation_version: int = 3,
    ) -> None:
        """Replace active DB plans while preserving legacy file references."""
        chapter_rows = list(chapters)
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE job_chapters
                SET legacy_relative_path=COALESCE(
                        legacy_relative_path,
                        relative_path
                    ),
                    relative_path=NULL,
                    state='pending',
                    ready_segments=0,
                    playable_seconds=0,
                    duration_seconds=0,
                    render_seconds=0,
                    production_ratio=0,
                    qwen_seconds=0,
                    rvc_seconds=0,
                    overlap_seconds=0,
                    generation_version=?,
                    recast_state='pending',
                    error=NULL,
                    updated_at=?
                WHERE job_id=?
                """,
                (int(generation_version), _now(), job_id),
            )
            # Audio files are deliberately untouched.  The manifest written by
            # the caller retains every legacy row for rollback.
            conn.execute("DELETE FROM job_segments WHERE job_id=?", (job_id,))
            conn.commit()
        self.ensure_chapters(job_id, chapter_rows)
        for chapter in chapter_rows:
            chapter_index = int(chapter["index"])
            self.ensure_segments(
                job_id,
                chapter_index,
                chapter_segments.get(chapter_index) or [],
            )
            self.update_chapter(
                job_id,
                chapter_index,
                generation_version=int(generation_version),
                recast_state="pending",
            )

    def ensure_chapters(self, job_id: str, chapters: Iterable[Dict[str, Any]]) -> None:
        now = _now()
        with self.connect() as conn:
            for chapter in chapters:
                conn.execute(
                    """
                    INSERT INTO job_chapters (
                        job_id, chapter_index, title, state, updated_at
                    ) VALUES (?, ?, ?, 'pending', ?)
                    ON CONFLICT(job_id, chapter_index) DO UPDATE SET
                        title=excluded.title,
                        updated_at=excluded.updated_at
                    """,
                    (
                        job_id,
                        int(chapter["index"]),
                        str(chapter.get("title") or f"第 {int(chapter['index']) + 1} 章"),
                        now,
                    ),
                )
            conn.execute(
                """
                INSERT INTO job_playback (
                    job_id, chapter_index, current_time, duration,
                    playback_rate, state, updated_at
                ) VALUES (?, 0, 0, 0, 1, 'idle', ?)
                ON CONFLICT(job_id) DO NOTHING
                """,
                (job_id, now),
            )
            conn.commit()

    def ensure_segments(
        self,
        job_id: str,
        chapter_index: int,
        segments: Iterable[Dict[str, Any]],
    ) -> None:
        rows = list(segments)
        now = _now()
        with self.connect() as conn:
            for segment in rows:
                conn.execute(
                    """
                    INSERT INTO job_segments (
                        job_id, chapter_index, segment_index, speaker, character_id,
                        gender, emotion, state, text, source_start, source_end,
                        attribution_label, attribution_source,
                        attribution_confidence, scene_id, speaker_role,
                        content_hash, generation_version, inference_evidence,
                        legacy_relative_path, updated_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, 'pending',
                        ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?
                    )
                    ON CONFLICT(job_id, chapter_index, segment_index) DO UPDATE SET
                        speaker=excluded.speaker,
                        character_id=excluded.character_id,
                        gender=excluded.gender,
                        emotion=excluded.emotion,
                        text=excluded.text,
                        source_start=excluded.source_start,
                        source_end=excluded.source_end,
                        attribution_label=excluded.attribution_label,
                        attribution_source=excluded.attribution_source,
                        attribution_confidence=excluded.attribution_confidence,
                        scene_id=excluded.scene_id,
                        speaker_role=excluded.speaker_role,
                        content_hash=excluded.content_hash,
                        generation_version=excluded.generation_version,
                        inference_evidence=excluded.inference_evidence,
                        legacy_relative_path=COALESCE(
                            job_segments.legacy_relative_path,
                            excluded.legacy_relative_path
                        ),
                        updated_at=excluded.updated_at
                    WHERE job_segments.state != 'ready'
                    """,
                    (
                        job_id,
                        chapter_index,
                        int(segment["segment_index"]),
                        str(segment.get("speaker") or "default"),
                        segment.get("character_id"),
                        str(segment.get("gender") or "neutral"),
                        segment.get("emotion"),
                        str(segment.get("text") or ""),
                        segment.get("source_start"),
                        segment.get("source_end"),
                        segment.get("attribution_label"),
                        segment.get("attribution_source"),
                        float(segment.get("attribution_confidence") or 0),
                        segment.get("scene_id"),
                        segment.get("speaker_role"),
                        segment.get("content_hash"),
                        int(segment.get("generation_version") or 2),
                        json.dumps(
                            segment.get("inference_evidence")
                            or segment.get("evidence")
                            or {},
                            ensure_ascii=False,
                        ),
                        segment.get("legacy_relative_path"),
                        now,
                    ),
                )
            conn.execute(
                """
                UPDATE job_chapters
                SET total_segments=?, updated_at=?
                WHERE job_id=? AND chapter_index=?
                """,
                (len(rows), now, job_id, chapter_index),
            )
            conn.commit()

    def update_chapter(self, job_id: str, chapter_index: int, **fields: Any) -> None:
        if "state" in fields and fields["state"] not in CHAPTER_STATES:
            raise ValueError(f"Unsupported chapter state: {fields['state']}")
        allowed = {
            "title",
            "state",
            "total_segments",
            "ready_segments",
            "playable_seconds",
            "duration_seconds",
            "render_seconds",
            "production_ratio",
            "qwen_seconds",
            "rvc_seconds",
            "overlap_seconds",
            "peak_memory_mb",
            "current_batch_size",
            "relative_path",
            "legacy_relative_path",
            "generation_version",
            "recast_state",
            "error",
            "attempts",
            "priority",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return
        updates["updated_at"] = _now()
        clause = ", ".join(f"{key}=?" for key in updates)
        values = list(updates.values()) + [job_id, chapter_index]
        with self.connect() as conn:
            conn.execute(
                f"UPDATE job_chapters SET {clause} WHERE job_id=? AND chapter_index=?",
                values,
            )
            conn.commit()

    def update_segment(
        self,
        job_id: str,
        chapter_index: int,
        segment_index: int,
        **fields: Any,
    ) -> None:
        if "state" in fields and fields["state"] not in SEGMENT_STATES:
            raise ValueError(f"Unsupported segment state: {fields['state']}")
        allowed = {
            "speaker",
            "character_id",
            "gender",
            "emotion",
            "state",
            "text",
            "relative_path",
            "duration_seconds",
            "render_seconds",
            "qwen_seconds",
            "rvc_seconds",
            "batch_size",
            "peak_memory_mb",
            "source_start",
            "source_end",
            "attribution_label",
            "attribution_source",
            "attribution_confidence",
            "scene_id",
            "speaker_role",
            "content_hash",
            "generation_version",
            "inference_evidence",
            "legacy_relative_path",
            "converted",
            "warning",
            "error",
            "attempts",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if "inference_evidence" in updates and not isinstance(
            updates["inference_evidence"], str
        ):
            updates["inference_evidence"] = json.dumps(
                updates["inference_evidence"] or {},
                ensure_ascii=False,
            )
        if not updates:
            return
        updates["updated_at"] = _now()
        clause = ", ".join(f"{key}=?" for key in updates)
        values = list(updates.values()) + [job_id, chapter_index, segment_index]
        with self.connect() as conn:
            conn.execute(
                f"""
                UPDATE job_segments SET {clause}
                WHERE job_id=? AND chapter_index=? AND segment_index=?
                """,
                values,
            )
            conn.commit()

    def ensure_characters(
        self,
        job_id: str,
        characters: Iterable[Dict[str, Any]],
    ) -> None:
        now = _now()
        with self.connect() as conn:
            for character in characters:
                character_id = str(character.get("character_id") or "").strip()
                name = str(character.get("name") or "").strip()
                if not character_id or not name:
                    continue
                conn.execute(
                    """
                    INSERT INTO job_characters (
                        job_id, character_id, name, aliases, gender, voice,
                        is_protagonist, rank, confidence, score, mention_count,
                        speech_count, sample_chapter_count, coverage_regions,
                        evidence, role_tier, voice_locked,
                        appearance_chapter_count, gender_confidence,
                        gender_evidence, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(job_id, character_id) DO NOTHING
                    """,
                    (
                        job_id,
                        character_id,
                        name,
                        json.dumps(character.get("aliases") or [name], ensure_ascii=False),
                        str(character.get("gender") or "neutral"),
                        str(character.get("voice") or ""),
                        int(bool(character.get("is_protagonist"))),
                        int(character.get("rank") or 0),
                        float(character.get("confidence") or 0),
                        float(character.get("score") or 0),
                        int(character.get("mention_count") or 0),
                        int(character.get("speech_count") or 0),
                        int(character.get("sample_chapter_count") or 0),
                        json.dumps(
                            character.get("coverage_regions") or [],
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            character.get("evidence") or {},
                            ensure_ascii=False,
                        ),
                        str(character.get("role_tier") or "extra"),
                        int(bool(character.get("voice_locked"))),
                        int(
                            character.get("appearance_chapter_count")
                            or character.get("sample_chapter_count")
                            or 0
                        ),
                        float(character.get("gender_confidence") or 0),
                        json.dumps(
                            character.get("gender_evidence") or {},
                            ensure_ascii=False,
                        ),
                        now,
                    ),
                )
            conn.commit()

    @staticmethod
    def _decode_character_row(row: sqlite3.Row | Dict[str, Any]) -> Dict[str, Any]:
        item = dict(row)
        for key, fallback in (
            ("aliases", []),
            ("coverage_regions", []),
            ("evidence", {}),
            ("gender_evidence", {}),
        ):
            try:
                item[key] = json.loads(item.get(key) or json.dumps(fallback))
            except (TypeError, ValueError, json.JSONDecodeError):
                item[key] = fallback
        item["is_protagonist"] = bool(item.get("is_protagonist"))
        item["voice_locked"] = bool(item.get("voice_locked"))
        return item

    def replace_characters(
        self,
        job_id: str,
        characters: Iterable[Dict[str, Any]],
    ) -> None:
        """Atomically replace analysis rows without touching any audio file."""
        rows = list(characters)
        with self.connect() as conn:
            conn.execute("DELETE FROM job_characters WHERE job_id=?", (job_id,))
            conn.commit()
        self.ensure_characters(job_id, rows)

    def list_characters(self, job_id: str) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM job_characters
                WHERE job_id=?
                ORDER BY is_protagonist DESC, rank ASC, name ASC
                """,
                (job_id,),
            ).fetchall()
        return [self._decode_character_row(row) for row in rows]

    def get_character(
        self,
        job_id: str,
        character_id: str,
    ) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM job_characters
                WHERE job_id=? AND character_id=?
                """,
                (job_id, character_id),
            ).fetchone()
        return self._decode_character_row(row) if row else None

    def update_character(
        self,
        job_id: str,
        character_id: str,
        **fields: Any,
    ) -> Optional[Dict[str, Any]]:
        allowed = {
            "name",
            "aliases",
            "gender",
            "voice",
            "role_tier",
            "voice_locked",
            "gender_confidence",
            "gender_evidence",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if "aliases" in updates:
            updates["aliases"] = json.dumps(
                updates["aliases"] or [],
                ensure_ascii=False,
            )
        if "gender_evidence" in updates and not isinstance(
            updates["gender_evidence"], str
        ):
            updates["gender_evidence"] = json.dumps(
                updates["gender_evidence"] or {},
                ensure_ascii=False,
            )
        if "voice_locked" in updates:
            updates["voice_locked"] = int(bool(updates["voice_locked"]))
        if not updates:
            return self.get_character(job_id, character_id)
        updates["updated_at"] = _now()
        clause = ", ".join(f"{key}=?" for key in updates)
        values = list(updates.values()) + [job_id, character_id]
        with self.connect() as conn:
            conn.execute(
                f"""
                UPDATE job_characters SET {clause}
                WHERE job_id=? AND character_id=?
                """,
                values,
            )
            updated = conn.execute(
                """
                SELECT name, aliases, gender FROM job_characters
                WHERE job_id=? AND character_id=?
                """,
                (job_id, character_id),
            ).fetchone()
            if updated:
                aliases = json.loads(updated["aliases"] or "[]")
                labels = {
                    str(updated["name"] or "").strip(),
                    *[str(alias or "").strip() for alias in aliases],
                }
                labels.discard("")
                conn.execute(
                    """
                    UPDATE job_segments
                    SET speaker=?, character_id=?, gender=?, updated_at=?
                    WHERE job_id=? AND state='pending'
                      AND (
                        character_id=?
                        OR attribution_label IN (
                            SELECT value FROM json_each(?)
                        )
                      )
                    """,
                    (
                        character_id,
                        character_id,
                        str(updated["gender"] or "neutral"),
                        _now(),
                        job_id,
                        character_id,
                        json.dumps(sorted(labels), ensure_ascii=False),
                    ),
                )
            conn.commit()
        return self.get_character(job_id, character_id)

    def save_cast_audit(
        self,
        job_id: str,
        payload: Dict[str, Any],
        *,
        pipeline_version: int = 3,
    ) -> Dict[str, Any]:
        now = _now()
        status = str(payload.get("status") or (
            "ready" if payload.get("ready") else "review_required"
        ))
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO job_cast_audits (
                    job_id, pipeline_version, status, payload, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(job_id, pipeline_version) DO UPDATE SET
                    status=excluded.status,
                    payload=excluded.payload,
                    updated_at=excluded.updated_at
                """,
                (
                    job_id,
                    int(pipeline_version),
                    status,
                    json.dumps(payload, ensure_ascii=False),
                    now,
                ),
            )
            conn.commit()
        return self.get_cast_audit(job_id, pipeline_version=pipeline_version) or payload

    def get_cast_audit(
        self,
        job_id: str,
        *,
        pipeline_version: int = 3,
    ) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM job_cast_audits
                WHERE job_id=? AND pipeline_version=?
                """,
                (job_id, int(pipeline_version)),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        try:
            payload = json.loads(item.get("payload") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        payload.setdefault("status", item.get("status"))
        payload.setdefault("pipeline_version", int(item.get("pipeline_version") or 3))
        payload["updated_at"] = item.get("updated_at")
        return payload

    def update_playback(self, job_id: str, **fields: Any) -> Dict[str, Any]:
        allowed = {
            "chapter_index",
            "current_time",
            "duration",
            "playback_rate",
            "state",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        now = _now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO job_playback (
                    job_id, chapter_index, current_time, duration,
                    playback_rate, state, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    chapter_index=excluded.chapter_index,
                    current_time=excluded.current_time,
                    duration=excluded.duration,
                    playback_rate=excluded.playback_rate,
                    state=excluded.state,
                    updated_at=excluded.updated_at
                """,
                (
                    job_id,
                    int(updates.get("chapter_index", 0) or 0),
                    float(updates.get("current_time", 0) or 0),
                    float(updates.get("duration", 0) or 0),
                    max(0.25, min(float(updates.get("playback_rate", 1) or 1), 4)),
                    str(updates.get("state") or "idle"),
                    now,
                ),
            )
            conn.commit()
        return self.get_playback(job_id)

    def get_playback(self, job_id: str) -> Dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM job_playback WHERE job_id=?",
                (job_id,),
            ).fetchone()
        return dict(row) if row else {
            "job_id": job_id,
            "chapter_index": 0,
            "current_time": 0.0,
            "duration": 0.0,
            "playback_rate": 1.0,
            "state": "idle",
            "updated_at": None,
        }

    def prioritize(self, job_id: str, chapter_index: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE job_chapters SET priority=0 WHERE job_id=?",
                (job_id,),
            )
            conn.execute(
                """
                UPDATE job_chapters
                SET priority=100,
                    state=CASE WHEN state='failed' THEN 'pending' ELSE state END,
                    attempts=CASE WHEN state='failed' THEN 0 ELSE attempts END,
                    error=CASE WHEN state='failed' THEN NULL ELSE error END,
                    updated_at=?
                WHERE job_id=? AND chapter_index=? AND state != 'ready'
                """,
                (_now(), job_id, chapter_index),
            )
            conn.execute(
                """
                UPDATE job_segments
                SET state='pending', error=NULL, updated_at=?
                WHERE job_id=? AND chapter_index=? AND state='failed'
                """,
                (_now(), job_id, chapter_index),
            )
            conn.commit()

    def requeue_failed_segments(self, job_id: str) -> List[int]:
        """Make failed segment rows retryable when a user resumes a job.

        Ready rows are intentionally untouched. This is used after a code or
        voice-profile correction so a long-running book can continue from its
        first failed line rather than silently skipping it or restarting.
        """
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT chapter_index
                FROM job_segments
                WHERE job_id=? AND state='failed'
                ORDER BY chapter_index
                """,
                (job_id,),
            ).fetchall()
            chapter_indices = [int(row["chapter_index"]) for row in rows]
            if not chapter_indices:
                return []
            conn.execute(
                """
                UPDATE job_segments
                SET state='pending', error=NULL, updated_at=?
                WHERE job_id=? AND state='failed'
                """,
                (_now(), job_id),
            )
            placeholders = ",".join("?" for _ in chapter_indices)
            conn.execute(
                f"""
                UPDATE job_chapters
                SET state='pending', error=NULL, updated_at=?
                WHERE job_id=? AND chapter_index IN ({placeholders})
                    AND state != 'ready'
                """,
                (_now(), job_id, *chapter_indices),
            )
            conn.commit()
        return chapter_indices

    def next_chapter(
        self,
        job_id: str,
        *,
        target_index: int,
        continue_full_book: bool,
    ) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            priority = conn.execute(
                """
                SELECT * FROM job_chapters
                WHERE job_id=? AND state != 'ready' AND priority > 0
                ORDER BY priority DESC, chapter_index ASC LIMIT 1
                """,
                (job_id,),
            ).fetchone()
            if priority:
                return dict(priority)
            if continue_full_book:
                row = conn.execute(
                    """
                    SELECT * FROM job_chapters
                    WHERE job_id=? AND state != 'ready'
                    ORDER BY chapter_index ASC LIMIT 1
                    """,
                    (job_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT * FROM job_chapters
                    WHERE job_id=? AND state != 'ready' AND chapter_index <= ?
                    ORDER BY chapter_index ASC LIMIT 1
                    """,
                    (job_id, target_index),
                ).fetchone()
        return dict(row) if row else None

    def list_segments(self, job_id: str, chapter_index: int) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM job_segments
                WHERE job_id=? AND chapter_index=?
                ORDER BY segment_index ASC
                """,
                (job_id, chapter_index),
            ).fetchall()
        return [self._decode_segment_row(row) for row in rows]

    @staticmethod
    def _decode_segment_row(row: sqlite3.Row | Dict[str, Any]) -> Dict[str, Any]:
        item = dict(row)
        try:
            item["inference_evidence"] = json.loads(
                item.get("inference_evidence") or "{}"
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            item["inference_evidence"] = {}
        return item

    def list_chapters(
        self,
        job_id: str,
        *,
        include_segments: bool = True,
    ) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            chapter_rows = conn.execute(
                """
                SELECT * FROM job_chapters
                WHERE job_id=? ORDER BY chapter_index ASC
                """,
                (job_id,),
            ).fetchall()
            segment_rows = []
            if include_segments:
                segment_rows = conn.execute(
                    """
                    SELECT * FROM job_segments
                    WHERE job_id=? ORDER BY chapter_index ASC, segment_index ASC
                    """,
                    (job_id,),
                ).fetchall()

        grouped: Dict[int, List[Dict[str, Any]]] = {}
        for row in segment_rows:
            item = self._decode_segment_row(row)
            grouped.setdefault(int(item["chapter_index"]), []).append(item)

        chapters = []
        for row in chapter_rows:
            chapter = dict(row)
            chapter["segments"] = grouped.get(int(chapter["chapter_index"]), [])
            chapters.append(chapter)
        return chapters

    def summary(self, job_id: str) -> Dict[str, Any]:
        chapters = self.list_chapters(job_id, include_segments=False)
        playback = self.get_playback(job_id)
        ready = [chapter for chapter in chapters if chapter["state"] == "ready"]
        streamable = [
            chapter
            for chapter in chapters
            if chapter["state"] in {"streamable", "ready"}
        ]
        legacy_playable = [
            chapter
            for chapter in chapters
            if chapter.get("legacy_relative_path")
            and chapter.get("state") != "ready"
        ]
        playable = [
            chapter
            for chapter in chapters
            if chapter.get("state") in {"streamable", "ready"}
            or chapter.get("legacy_relative_path")
        ]
        current_index = int(playback.get("chapter_index") or 0)
        highest_ready = max(
            (int(chapter["chapter_index"]) for chapter in ready),
            default=-1,
        )
        highest_playable = max(
            (int(chapter["chapter_index"]) for chapter in playable),
            default=-1,
        )
        active = next(
            (
                chapter
                for chapter in chapters
                if chapter.get("state")
                in {"analyzing", "synthesizing", "converting", "streamable"}
            ),
            None,
        )
        if active is None:
            active = next(
                (
                    chapter
                    for chapter in chapters
                    if chapter.get("state") not in {"ready", "failed"}
                ),
                None,
            )
        active_total = int((active or {}).get("total_segments") or 0)
        active_ready = int((active or {}).get("ready_segments") or 0)
        return {
            "chapter_count": len(chapters),
            "ready_chapters": len(ready),
            "streamable_chapters": len(streamable),
            "playable_chapters": len(playable),
            "legacy_playable_chapters": len(legacy_playable),
            "current_chapter_index": current_index,
            "active_chapter_index": (
                int(active["chapter_index"]) if active is not None else None
            ),
            "active_chapter_progress": (
                int((active_ready / active_total) * 100)
                if active_total
                else 0
            ),
            "highest_ready_chapter": highest_ready,
            "highest_playable_chapter": highest_playable,
            "buffered_chapters": max(0, highest_playable - current_index),
            "playback": playback,
        }

    def snapshot_token(self, job_id: str) -> str:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COALESCE(MAX(updated_at), '') AS chapter_updated,
                    COALESCE(SUM(ready_segments), 0) AS ready_segments,
                    COALESCE(SUM(CASE WHEN state='ready' THEN 1 ELSE 0 END), 0) AS ready_chapters
                FROM job_chapters WHERE job_id=?
                """,
                (job_id,),
            ).fetchone()
            playback = conn.execute(
                "SELECT updated_at FROM job_playback WHERE job_id=?",
                (job_id,),
            ).fetchone()
            characters = conn.execute(
                """
                SELECT COALESCE(MAX(updated_at), '') AS updated_at
                FROM job_characters WHERE job_id=?
                """,
                (job_id,),
            ).fetchone()
        return json.dumps(
            {
                "chapter_updated": row["chapter_updated"] if row else "",
                "ready_segments": row["ready_segments"] if row else 0,
                "ready_chapters": row["ready_chapters"] if row else 0,
                "playback_updated": playback["updated_at"] if playback else "",
                "characters_updated": (
                    characters["updated_at"] if characters else ""
                ),
            },
            sort_keys=True,
        )

    def delete_job(self, job_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM job_characters WHERE job_id=?", (job_id,))
            conn.execute("DELETE FROM job_segments WHERE job_id=?", (job_id,))
            conn.execute("DELETE FROM job_chapters WHERE job_id=?", (job_id,))
            conn.execute("DELETE FROM job_playback WHERE job_id=?", (job_id,))
            conn.commit()
