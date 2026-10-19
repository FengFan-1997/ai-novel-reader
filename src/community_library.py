"""Local client for the ShengYue public audiobook library.

The generator owns all heavyweight work.  This client only fingerprints the
already finished chapter, transcodes its final file to a compact Opus seed and
uses the cloud control-plane for dedupe and resumable contribution state.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from src.system_tools import find_system_tool

logger = logging.getLogger(__name__)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def normalize_text(value: str) -> str:
    """Keep content identity stable across CRLF/spacing-only imports."""
    return "\n".join(" ".join(line.split()) for line in str(value or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")).strip()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class CommunityLibraryClient:
    def __init__(self, data_dir: Path | str):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.database_path = self.data_dir / "community_library.db"
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS community_contributions (
                    job_id TEXT NOT NULL,
                    chapter_index INTEGER NOT NULL,
                    artifact_key TEXT NOT NULL,
                    audio_path TEXT NOT NULL,
                    state TEXT NOT NULL,
                    contribution_id TEXT,
                    artifact_id TEXT,
                    error TEXT,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(job_id, chapter_index)
                );
                CREATE TABLE IF NOT EXISTS community_cache_matches (
                    edition_hash TEXT NOT NULL,
                    recipe_hash TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    checked_at REAL NOT NULL,
                    PRIMARY KEY(edition_hash, recipe_hash)
                );
                """
            )

    @staticmethod
    def enabled(config: Dict[str, Any]) -> bool:
        return bool(config.get("community_shared_enabled") and config.get("community_auto_contribute") and config.get("community_api_url") and config.get("community_device_token"))

    @staticmethod
    def recipe(job_entry: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
        snapshot = dict(job_entry.get("config_snapshot") or config or {})
        voices = job_entry.get("voice_assignments") or {}
        voice_manifest = {
            str(key): {
                "voice": value.get("voice") if isinstance(value, dict) else value,
                "extra": (value.get("extra") or {}) if isinstance(value, dict) else {},
            }
            for key, value in voices.items()
        }
        settings = {
            "engine": job_entry.get("engine") or snapshot.get("tts_engine") or "qwen3_custom",
            "model": snapshot.get("qwen3_custom_model") or snapshot.get("qwen3_model") or "qwen3-tts",
            "segmenter": "streaming-v2",
            "emotion_driver": snapshot.get("emotion_driver") or "contextual-v1",
            "narrator_conversion": snapshot.get("narrator_conversion") or "none",
            "rvc_model": snapshot.get("rvc_model") or "",
            "sample_rate": 24000,
            "codec": "opus-48k-mono",
        }
        recipe_hash = _sha256_text(_canonical_json({"voice_manifest": voice_manifest, "settings": settings}))
        return {"recipeHash": recipe_hash, "modelVersion": str(settings["model"]), "voiceManifest": voice_manifest, "settings": settings}

    @staticmethod
    def edition(chapters: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        normalized = []
        for chapter in chapters:
            content = "".join(str(segment.get("text") or "") for segment in chapter.get("segments") or [])
            normalized.append({
                "index": int(chapter["chapter_index"]),
                "title": str(chapter.get("title") or f"第 {int(chapter['chapter_index']) + 1} 章"),
                "textHash": _sha256_text(normalize_text(content)),
            })
        normalized.sort(key=lambda item: item["index"])
        manifest_hash = _sha256_text(_canonical_json(normalized))
        return {"manifestHash": manifest_hash, "chapters": normalized}

    def _request(self, base_url: str, token: str, path: str, *, method: str = "GET", payload: Optional[Dict[str, Any]] = None, raw: Optional[bytes] = None, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        url = base_url.rstrip("/") + path
        request_headers = {"Accept": "application/json", **(headers or {})}
        if token:
            request_headers["Authorization"] = f"Bearer {token}"
        data = raw
        if payload is not None:
            data = _canonical_json(payload).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, method=method, headers=request_headers)
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                body = response.read()
                if not body:
                    return {"success": response.status < 300}
                return json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                message = json.loads(body).get("error") or body
            except Exception:
                message = body
            raise RuntimeError(f"云端返回 {exc.code}：{message}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"无法连接公共书库：{exc.reason}") from exc

    def enroll(self, config: Dict[str, Any], *, display_name: str, public_key: str = "") -> Dict[str, Any]:
        base_url = str(config.get("community_api_url") or "").strip()
        if not base_url:
            raise ValueError("请先设置公共书库地址")
        result = self._request(base_url, "", "/v1/auth/devices", method="POST", payload={"accepted": True, "consentVersion": "community-v1", "displayName": display_name, "publicKey": public_key})
        if not result.get("success") or not result.get("token"):
            raise RuntimeError(result.get("error") or "无法启用共享书库")
        return {"community_shared_enabled": True, "community_auto_contribute": True, "community_device_id": result["deviceId"], "community_device_token": result["token"]}

    def resolve(self, config: Dict[str, Any], edition: Dict[str, Any], recipe: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        result = self._request(str(config["community_api_url"]), str(config.get("community_device_token") or ""), "/v1/artifacts/resolve", method="POST", payload={"manifestHash": edition["manifestHash"], "recipeHash": recipe["recipeHash"]})
        match = result.get("match")
        if match:
            with self._connect() as conn:
                conn.execute("INSERT OR REPLACE INTO community_cache_matches VALUES (?, ?, ?, ?)", (edition["manifestHash"], recipe["recipeHash"], _canonical_json(match), time.time()))
        return match

    def transcode_opus(self, source: Path, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and destination.stat().st_size > 1024:
            return destination
        ffmpeg = find_system_tool("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("未找到 FFmpeg，无法生成公共书库所需的 Opus 音频。")
        partial = destination.with_suffix(destination.suffix + ".partial")
        if partial.exists():
            partial.unlink()
        command = [str(ffmpeg), "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "24000", "-c:a", "libopus", "-b:a", "48k", "-vbr", "on", str(partial)]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=30 * 60)
        if completed.returncode != 0 or not partial.exists() or partial.stat().st_size < 1024:
            raise RuntimeError(f"Opus 转码失败：{completed.stderr[-500:]}")
        partial.replace(destination)
        return destination

    def _duration(self, path: Path) -> float:
        ffprobe = find_system_tool("ffprobe")
        if not ffprobe:
            return 0.0
        result = subprocess.run([str(ffprobe), "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)], capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            return 0.0
        try:
            return max(0.0, float(json.loads(result.stdout).get("format", {}).get("duration") or 0))
        except Exception:
            return 0.0

    def _mark(self, job_id: str, chapter_index: int, artifact_key: str, audio_path: Path, state: str, *, contribution_id: str = "", artifact_id: str = "", error: str = "") -> None:
        with self._connect() as conn:
            conn.execute("""INSERT INTO community_contributions (job_id, chapter_index, artifact_key, audio_path, state, contribution_id, artifact_id, error, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(job_id, chapter_index) DO UPDATE SET artifact_key=excluded.artifact_key, audio_path=excluded.audio_path, state=excluded.state, contribution_id=excluded.contribution_id, artifact_id=excluded.artifact_id, error=excluded.error, updated_at=excluded.updated_at""",
                         (job_id, chapter_index, artifact_key, str(audio_path), state, contribution_id, artifact_id, error, time.time()))

    def contribute_chapter(self, *, config: Dict[str, Any], job_id: str, job_entry: Dict[str, Any], job_dir: Path, chapter: Dict[str, Any], all_chapters: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not self.enabled(config):
            return {"skipped": True, "reason": "共享书库未启用"}
        with self._connect() as conn:
            previous = conn.execute(
                "SELECT state, artifact_id FROM community_contributions WHERE job_id=? AND chapter_index=?",
                (job_id, int(chapter["chapter_index"])),
            ).fetchone()
        if previous and previous["state"] == "complete":
            return {"skipped": True, "reason": "该章节已贡献", "artifactId": previous["artifact_id"]}
        relative_path = str(chapter.get("relative_path") or "")
        source = job_dir / relative_path
        if not relative_path or not source.exists():
            return {"skipped": True, "reason": "章节文件尚未完成"}
        edition = self.edition(all_chapters)
        target_chapter = next(item for item in edition["chapters"] if item["index"] == int(chapter["chapter_index"]))
        recipe = self.recipe(job_entry, config)
        artifact_key = _sha256_text(f"{target_chapter['textHash']}:{recipe['recipeHash']}")
        opus_path = job_dir / "community" / f"chapter_{int(chapter['chapter_index']) + 1:04d}.{artifact_key[:12]}.opus"
        try:
            opus_path = self.transcode_opus(source, opus_path)
            duration = self._duration(opus_path) or float(chapter.get("duration_seconds") or 0)
            if duration <= 0:
                raise RuntimeError("无法验证 Opus 时长")
            audio = {"sha256": _file_sha256(opus_path), "byteSize": opus_path.stat().st_size, "durationSeconds": duration}
            title = str(job_entry.get("audiobook_title") or job_entry.get("title") or job_entry.get("filename") or "未命名作品")
            payload = {"work": {"title": title}, "edition": edition, "chapters": edition["chapters"], "chapter": target_chapter, "recipe": recipe, "audio": audio, "validation": {"decoder": "ffmpeg", "sourceFormat": source.suffix.lstrip(".")}}
            initiated = self._request(str(config["community_api_url"]), str(config["community_device_token"]), "/v1/contributions/initiate", method="POST", payload=payload)
            if not initiated.get("success"):
                raise RuntimeError(initiated.get("error") or "云端拒绝了贡献")
            contribution_id = initiated["contributionId"]
            artifact_id = initiated["artifactId"]
            self._mark(job_id, int(chapter["chapter_index"]), artifact_key, opus_path, "uploading", contribution_id=contribution_id, artifact_id=artifact_id)
            cached = False
            object_key = initiated.get("objectKey")
            upload = initiated.get("upload") or {}
            if upload.get("url"):
                self._request("", "", str(upload["url"]), method="PUT", raw=opus_path.read_bytes(), headers={"Content-Type": str(upload.get("contentType") or "audio/ogg")})
                cached = True
            completed = self._request(str(config["community_api_url"]), str(config["community_device_token"]), f"/v1/contributions/{contribution_id}/complete", method="POST", payload={"artifactId": artifact_id, "cached": cached, "objectKey": object_key, "byteSize": audio["byteSize"], "durationSeconds": audio["durationSeconds"], "validation": payload["validation"]})
            if not completed.get("success"):
                raise RuntimeError(completed.get("error") or "云端未确认贡献")
            self._mark(job_id, int(chapter["chapter_index"]), artifact_key, opus_path, "complete", contribution_id=contribution_id, artifact_id=artifact_id)
            return {"success": True, "artifactId": artifact_id, "cached": cached, "opusPath": str(opus_path)}
        except Exception as exc:
            logger.warning("Community contribution failed for %s/%s: %s", job_id, chapter.get("chapter_index"), exc)
            self._mark(job_id, int(chapter["chapter_index"]), artifact_key, opus_path, "failed", error=str(exc))
            return {"success": False, "error": str(exc)}

    def contribute_async(self, **kwargs: Any) -> threading.Thread:
        thread = threading.Thread(target=self.contribute_chapter, kwargs=kwargs, daemon=True, name=f"community-contribution-{kwargs.get('job_id', 'job')}")
        thread.start()
        return thread

    def status(self, job_id: Optional[str] = None) -> List[Dict[str, Any]]:
        query = "SELECT * FROM community_contributions"
        params: tuple[Any, ...] = ()
        if job_id:
            query += " WHERE job_id=?"
            params = (job_id,)
        query += " ORDER BY updated_at DESC"
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(query, params).fetchall()]
