"""Local-first multi-source book discovery for ShengYue.

The module deliberately separates discovery metadata from book content.  It
never downloads protected text, bypasses authentication, or forwards stored
credentials to an unconfirmed origin.  Network adapters only return public
metadata and outbound source links.
"""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import html
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import unicodedata
import xml.etree.ElementTree as ElementTree
from typing import Any, Callable, Iterable, Mapping, Protocol
from urllib.parse import quote, urljoin, urlparse
import uuid

from bs4 import BeautifulSoup
from flask import Blueprint, jsonify, request
import requests
from src.upstream_book_algorithms import (
    fix_subtitles as upstream_fix_subtitles,
    normalize_isbn as upstream_normalize_isbn,
    pick_preferred_isbn,
    to_isbn13,
    unique_casefolded,
)

try:
    from opencc import OpenCC
except ImportError:  # pragma: no cover - dependency is installed by setup
    OpenCC = None  # type: ignore[assignment,misc]


LOGGER = logging.getLogger(__name__)
DEFAULT_SEARXNG_URL = os.environ.get("SHENGYUE_SEARXNG_URL", "http://127.0.0.1:8888")
DEFAULT_GOOGLE_BOOKS_API_KEY = os.environ.get("SHENGYUE_GOOGLE_BOOKS_API_KEY", "").strip()
DEFAULT_SOUSHUBA_RELEASE_URL = os.environ.get("SHENGYUE_SOUSHUBA_RELEASE_URL", "").strip()
MACOS_SYSTEM_CA_BUNDLE = Path("/etc/ssl/cert.pem")
SEARCH_SOURCE_TIMEOUT_SECONDS = 8
SEARCH_JOB_TIMEOUT_SECONDS = 15
SEARCH_RESULT_LIMIT = 20
HISTORY_LIMIT = 100
MAX_PUBLIC_TEXT_BYTES = 12 * 1024 * 1024
PUBLIC_TEXT_IMPORT_SOURCES = {"project-gutenberg"}
SOURCE_FAILURE_THRESHOLD = 2
SOURCE_COOLDOWN_SECONDS = 30
SOURCE_MAX_COOLDOWN_SECONDS = 10 * 60
_SAFE_SOURCE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
_TEXT_SPACES = re.compile(r"\s+")
_TRADITIONAL_TO_SIMPLIFIED = OpenCC("t2s") if OpenCC else None
_GUTENBERG_START_RE = re.compile(
    r"\*{3}\s*START OF (?:THIS|THE) PROJECT GUTENBERG EBOOK.*?\*{3}",
    re.IGNORECASE,
)
_GUTENBERG_END_RE = re.compile(
    r"\*{3}\s*END OF (?:THIS|THE) PROJECT GUTENBERG EBOOK.*?\*{3}",
    re.IGNORECASE,
)


DEFAULT_SOURCES: tuple[dict[str, Any], ...] = (
    {
        "id": "google-books",
        "name": "Google Books",
        "kind": "google_books",
        "domain": "books.google.com",
        "homepage_url": "https://books.google.com/",
        "search_url_template": "https://books.google.com/books?q={query}",
        "book_type": "出版书",
        "mature": False,
        "credential_supported": False,
        "sort_order": 10,
    },
    {
        "id": "open-library",
        "name": "Open Library",
        "kind": "open_library",
        "domain": "openlibrary.org",
        "homepage_url": "https://openlibrary.org/",
        "search_url_template": "https://openlibrary.org/search?q={query}",
        "book_type": "开放图书",
        "mature": False,
        "credential_supported": False,
        "sort_order": 20,
    },
    {
        "id": "project-gutenberg",
        "name": "Project Gutenberg",
        "kind": "gutendex",
        "domain": "gutenberg.org",
        "homepage_url": "https://www.gutenberg.org/",
        "search_url_template": "https://www.gutenberg.org/ebooks/search/?query={query}",
        "book_type": "公版电子书",
        "mature": False,
        "credential_supported": False,
        "sort_order": 25,
    },
    {
        "id": "qidian",
        "name": "起点中文网",
        "kind": "html_domain",
        "domain": "qidian.com",
        "homepage_url": "https://www.qidian.com/",
        "search_url_template": "https://www.qidian.com/search?kw={query}",
        "book_type": "网络小说",
        "mature": False,
        "credential_supported": True,
        "sort_order": 30,
    },
    {
        "id": "fanqie",
        "name": "番茄小说",
        "kind": "html_domain",
        "domain": "fanqienovel.com",
        "homepage_url": "https://fanqienovel.com/",
        "search_url_template": "https://fanqienovel.com/search/{query}",
        "book_type": "网络小说",
        "mature": False,
        "credential_supported": True,
        "sort_order": 40,
    },
    {
        "id": "jjwxc",
        "name": "晋江文学城",
        "kind": "html_domain",
        "domain": "jjwxc.net",
        "homepage_url": "https://www.jjwxc.net/",
        "search_url_template": "https://www.jjwxc.net/search.php?kw={query}",
        "book_type": "网络小说",
        "mature": False,
        "credential_supported": True,
        "sort_order": 50,
    },
    {
        "id": "weread",
        "name": "微信读书",
        "kind": "html_domain",
        "domain": "weread.qq.com",
        "homepage_url": "https://weread.qq.com/",
        "search_url_template": "https://weread.qq.com/web/search/books?keyword={query}",
        "book_type": "出版书",
        "mature": False,
        "credential_supported": True,
        "sort_order": 60,
    },
    {
        "id": "soushuba",
        "name": "搜书吧",
        "kind": "soushuba",
        "domain": "",
        "homepage_url": "https://soushu2030.com/",
        "release_url": DEFAULT_SOUSHUBA_RELEASE_URL,
        "search_url_template": "",
        "book_type": "网络小说",
        "mature": True,
        "credential_supported": True,
        "sort_order": 70,
    },
    {
        "id": "web",
        "name": "全网发现",
        "kind": "searx_web",
        "domain": "",
        "homepage_url": "",
        "search_url_template": "",
        "book_type": "全网结果",
        "mature": False,
        "credential_supported": False,
        "sort_order": 90,
    },
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_text(value: Any, limit: int = 1200) -> str:
    if value is None:
        return ""
    raw = str(value)
    text = BeautifulSoup(raw, "html.parser").get_text(" ", strip=True) if "<" in raw else html.unescape(raw)
    return _TEXT_SPACES.sub(" ", text).strip()[:limit]


def response_markup(response: requests.Response) -> str:
    """Prefer valid UTF-8 bytes when a rotating host omits its charset header."""
    content = getattr(response, "content", b"")
    if isinstance(content, bytes) and content:
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            pass
    return str(getattr(response, "text", "") or "")


def safe_result_url(value: Any) -> str:
    normalized = str(value or "").strip()
    try:
        parsed = urlparse(normalized)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    if parsed.username or parsed.password:
        return ""
    hostname = parsed.hostname.casefold().rstrip(".")
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return ""
    try:
        if not _is_public_ip(hostname):
            return ""
    except ValueError:
        pass
    return normalized[:3000]


def normalize_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", clean_text(value, 300)).casefold()
    if _TRADITIONAL_TO_SIMPLIFIED:
        normalized = _TRADITIONAL_TO_SIMPLIFIED.convert(normalized)
    return "".join(character for character in normalized if character.isalnum())


def normalize_isbn(value: Any) -> str:
    return upstream_normalize_isbn(str(value or "")) or ""


def result_group_key(result: Mapping[str, Any]) -> str:
    isbns = [to_isbn13(str(item)) for item in result.get("isbns") or []]
    valid_isbn = next((item for item in isbns if item), "")
    if valid_isbn:
        return f"isbn:{valid_isbn}"
    title = normalize_title(str(result.get("title") or ""))
    authors = result.get("authors") or []
    author = normalize_title(str(authors[0])) if authors else ""
    return f"book:{title}:{author}" if author else f"title:{title}"


def result_score(result: Mapping[str, Any], query: str) -> float:
    normalized_query = normalize_title(query)
    query_parts = [
        normalize_title(part)
        for part in re.split(r"[\s,，、/|]+", clean_text(query, 300))
        if normalize_title(part)
    ]
    title = normalize_title(str(result.get("title") or ""))
    authors = "".join(normalize_title(str(item)) for item in result.get("authors") or [])
    score = max(0.0, 20.0 - float(result.get("rank") or 20))
    query_isbn = to_isbn13(query)
    result_isbns = {to_isbn13(str(item)) for item in result.get("isbns") or []}
    if query_isbn and query_isbn in result_isbns:
        score += 120
    if normalized_query and title == normalized_query:
        score += 100
    elif normalized_query and normalized_query in title:
        score += 65
    elif title and title in normalized_query:
        score += 45
    elif any(part in title for part in query_parts):
        score += 38
    if normalized_query and normalized_query in authors:
        score += 35
    elif any(part in authors for part in query_parts):
        score += 28
    if result.get("cover_url"):
        score += 6
    if result.get("description"):
        score += 4
    if result.get("isbns"):
        score += 3
    return score


def normalize_offer(raw: Mapping[str, Any], source: Mapping[str, Any], query: str) -> dict[str, Any] | None:
    title = clean_text(raw.get("title"), 300)
    url = safe_result_url(raw.get("url"))
    if not title or not url:
        return None
    authors_value = raw.get("authors") or []
    if isinstance(authors_value, str):
        authors_value = [authors_value]
    authors = [clean_text(item, 120) for item in authors_value if clean_text(item, 120)][:8]
    source_name = clean_text(raw.get("source_name") or source.get("name"), 100)
    access = (
        str(raw.get("access") or "unknown")
        if str(raw.get("access") or "unknown") in {"public", "login_required", "paid", "unknown"}
        else "unknown"
    )
    download_url = safe_result_url(raw.get("download_url")) if access == "public" else ""
    download_format = clean_text(raw.get("download_format"), 20).upper()
    if download_format not in {"TXT", "EPUB", "PDF"}:
        download_format = ""
    normalized = {
        "title": title,
        "authors": authors,
        "cover_url": safe_result_url(raw.get("cover_url")),
        "description": clean_text(raw.get("description"), 1200),
        "source_id": str(source.get("id")),
        "source_name": source_name,
        "url": url,
        "updated_at": clean_text(raw.get("updated_at"), 80),
        "book_type": clean_text(raw.get("book_type") or source.get("book_type"), 80),
        "mature": bool(raw.get("mature", source.get("mature", False))),
        "access": access,
        "download_url": download_url,
        "download_format": download_format,
        "importable": bool(raw.get("importable", False) and download_url and download_format == "TXT"),
        "license": clean_text(raw.get("license"), 120),
        "isbns": [isbn for isbn in (normalize_isbn(item) for item in raw.get("isbns") or []) if isbn],
        "rank": int(raw.get("rank") or 0),
    }
    normalized["score"] = result_score(normalized, query)
    return normalized


def merge_results(results: Iterable[Mapping[str, Any]], query: str) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for result in results:
        key = result_group_key(result)
        if key.endswith(":") or key == "title:":
            continue
        group = groups.get(key)
        if group is None:
            group = {
                "id": hashlib.sha256(key.encode("utf-8")).hexdigest()[:20],
                "title": result.get("title") or "未命名作品",
                "authors": list(result.get("authors") or []),
                "cover_url": result.get("cover_url") or "",
                "description": result.get("description") or "",
                "book_type": result.get("book_type") or "图书",
                "mature": bool(result.get("mature")),
                "score": float(result.get("score") or 0),
                "offers": [],
            }
            groups[key] = group
        group["offers"].append(dict(result))
        group["mature"] = bool(group["mature"] or result.get("mature"))
        group["score"] = max(float(group["score"]), float(result.get("score") or 0))
        if not group["cover_url"] and result.get("cover_url"):
            group["cover_url"] = result["cover_url"]
        if len(str(result.get("description") or "")) > len(str(group["description"])):
            group["description"] = result.get("description") or ""
        if not group["authors"] and result.get("authors"):
            group["authors"] = list(result.get("authors") or [])
    merged = list(groups.values())
    for group in merged:
        group["offers"].sort(key=lambda item: (-float(item.get("score") or 0), item.get("source_name") or ""))
        group["source_count"] = len({item.get("source_id") for item in group["offers"]})
        group["access"] = (
            "public"
            if any(item.get("access") == "public" for item in group["offers"])
            else "paid"
            if any(item.get("access") == "paid" for item in group["offers"])
            else "login_required"
            if any(item.get("access") == "login_required" for item in group["offers"])
            else "unknown"
        )
        group["importable"] = any(bool(item.get("importable")) for item in group["offers"])
    merged.sort(key=lambda item: (-float(item.get("score") or 0), str(item.get("title") or "")))
    return merged


def _is_public_ip(address: str) -> bool:
    parsed = ipaddress.ip_address(address)
    return not (
        parsed.is_private
        or parsed.is_loopback
        or parsed.is_link_local
        or parsed.is_multicast
        or parsed.is_reserved
        or parsed.is_unspecified
    )


def validate_public_url(
    value: str,
    *,
    require_https: bool = False,
    allow_nonstandard_port: bool = False,
) -> str:
    normalized = safe_result_url(value)
    if not normalized:
        raise ValueError("请输入有效的 HTTP 或 HTTPS 地址。")
    parsed = urlparse(normalized)
    if require_https and parsed.scheme != "https":
        raise ValueError("该地址必须使用 HTTPS。")
    if not allow_nonstandard_port and parsed.port not in {None, 80, 443}:
        raise ValueError("不允许使用非标准端口。")
    try:
        addresses = {
            entry[4][0]
            for entry in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
        }
    except socket.gaierror as exc:
        raise ValueError("域名当前无法解析。") from exc
    if not addresses or any(not _is_public_ip(address) for address in addresses):
        raise ValueError("不允许访问本机、内网或保留地址。")
    return normalized


class CredentialVault(Protocol):
    def has(self, source_id: str) -> bool: ...
    def read(self, source_id: str) -> dict[str, str] | None: ...
    def write(self, source_id: str, username: str, password: str) -> None: ...
    def delete(self, source_id: str) -> None: ...


class KeychainCredentialVault:
    """Store both the account and password as secrets in the OS keychain."""

    def __init__(self, service_prefix: str = "ShengYue Book Source") -> None:
        self.service_prefix = service_prefix

    def _service(self, source_id: str) -> str:
        if not _SAFE_SOURCE_ID.fullmatch(source_id):
            raise ValueError("无效的来源编号。")
        return f"{self.service_prefix}:{source_id}"

    @staticmethod
    def _uses_macos_security() -> bool:
        return sys.platform == "darwin" and Path("/usr/bin/security").is_file()

    @staticmethod
    def _security_call(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        try:
            completed = subprocess.run(
                ["/usr/bin/security", *arguments],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError("macOS Keychain 暂时不可用。") from exc
        if check and completed.returncode != 0:
            raise RuntimeError("macOS Keychain 操作失败。")
        return completed

    def _macos_get(self, service: str, account: str) -> str:
        completed = self._security_call(
            "find-generic-password", "-s", service, "-a", account, "-w", check=False
        )
        return completed.stdout.rstrip("\r\n") if completed.returncode == 0 else ""

    @staticmethod
    def _keyring():
        try:
            import keyring
        except ImportError as exc:  # pragma: no cover - setup error
            raise RuntimeError("本机钥匙串组件尚未安装。") from exc
        return keyring

    def has(self, source_id: str) -> bool:
        try:
            service = self._service(source_id)
            if self._uses_macos_security():
                return bool(self._macos_get(service, "username") and self._macos_get(service, "password"))
            keyring = self._keyring()
            return bool(keyring.get_password(service, "username") and keyring.get_password(service, "password"))
        except Exception:
            return False

    def read(self, source_id: str) -> dict[str, str] | None:
        service = self._service(source_id)
        if self._uses_macos_security():
            username = self._macos_get(service, "username")
            password = self._macos_get(service, "password")
        else:
            keyring = self._keyring()
            username = keyring.get_password(service, "username") or ""
            password = keyring.get_password(service, "password") or ""
        return {"username": username, "password": password} if username and password else None

    def write(self, source_id: str, username: str, password: str) -> None:
        if not username.strip() or not password:
            raise ValueError("账号和密码都不能为空。")
        service = self._service(source_id)
        if self._uses_macos_security():
            self._security_call(
                "add-generic-password", "-U", "-s", service, "-a", "username", "-w", username.strip()
            )
            self._security_call(
                "add-generic-password", "-U", "-s", service, "-a", "password", "-w", password
            )
        else:
            keyring = self._keyring()
            keyring.set_password(service, "username", username.strip())
            keyring.set_password(service, "password", password)

    def delete(self, source_id: str) -> None:
        service = self._service(source_id)
        if self._uses_macos_security():
            for account in ("username", "password"):
                self._security_call(
                    "delete-generic-password", "-s", service, "-a", account, check=False
                )
            return
        keyring = self._keyring()
        for account in ("username", "password"):
            try:
                keyring.delete_password(service, account)
            except keyring.errors.PasswordDeleteError:
                pass


class BookSearchStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS book_search_sources (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    domain TEXT NOT NULL DEFAULT '',
                    homepage_url TEXT NOT NULL DEFAULT '',
                    release_url TEXT NOT NULL DEFAULT '',
                    search_url_template TEXT NOT NULL DEFAULT '',
                    confirmed_origin TEXT NOT NULL DEFAULT '',
                    book_type TEXT NOT NULL DEFAULT '图书',
                    mature INTEGER NOT NULL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    builtin INTEGER NOT NULL DEFAULT 0,
                    credential_supported INTEGER NOT NULL DEFAULT 0,
                    sort_order INTEGER NOT NULL DEFAULT 100,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS book_search_history (
                    id TEXT PRIMARY KEY,
                    query TEXT NOT NULL,
                    filters_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_book_search_history_created
                    ON book_search_history(created_at DESC);
                CREATE TABLE IF NOT EXISTS book_search_favorites (
                    id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(book_search_sources)")
            }
            if "release_url" not in columns:
                connection.execute(
                    "ALTER TABLE book_search_sources ADD COLUMN release_url TEXT NOT NULL DEFAULT ''"
                )
            now = utc_now()
            for source in DEFAULT_SOURCES:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO book_search_sources (
                        id, name, kind, domain, homepage_url, release_url, search_url_template,
                        book_type, mature, enabled, builtin, credential_supported,
                        sort_order, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?, ?, ?)
                    """,
                    (
                        source["id"], source["name"], source["kind"], source["domain"],
                        source["homepage_url"], source.get("release_url", ""),
                        source["search_url_template"], source["book_type"],
                        int(source["mature"]), int(source["credential_supported"]),
                        int(source["sort_order"]), now, now,
                    ),
                )
                connection.execute(
                    """
                    UPDATE book_search_sources SET
                        name = ?, kind = ?, homepage_url = ?, book_type = ?,
                        mature = ?, credential_supported = ?, sort_order = ?, updated_at = ?
                    WHERE id = ? AND builtin = 1
                    """,
                    (
                        source["name"], source["kind"], source["homepage_url"], source["book_type"],
                        int(source["mature"]), int(source["credential_supported"]),
                        int(source["sort_order"]), now, source["id"],
                    ),
                )

    @staticmethod
    def _source_from_row(row: sqlite3.Row) -> dict[str, Any]:
        source = dict(row)
        for key in ("mature", "enabled", "builtin", "credential_supported"):
            source[key] = bool(source[key])
        return source

    def list_sources(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM book_search_sources"
        parameters: tuple[Any, ...] = ()
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY sort_order, name"
        with self._connect() as connection:
            return [self._source_from_row(row) for row in connection.execute(query, parameters)]

    def get_source(self, source_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM book_search_sources WHERE id = ?", (source_id,)).fetchone()
        return self._source_from_row(row) if row else None

    def create_source(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        name = clean_text(payload.get("name"), 80)
        domain = str(payload.get("domain") or "").strip().lower().removeprefix("www.")
        search_template = str(payload.get("search_url_template") or "").strip()
        if not name or not domain or "{query}" not in search_template:
            raise ValueError("请填写来源名称、域名和包含 {query} 的搜索地址。")
        probe_url = search_template.replace("{query}", quote("测试", safe=""))
        validated_template_url = validate_public_url(probe_url)
        template_scheme = urlparse(validated_template_url).scheme
        homepage_url = validate_public_url(f"{template_scheme}://{domain}/")
        template_host = (urlparse(validated_template_url).hostname or "").removeprefix("www.")
        if template_host != domain and not template_host.endswith(f".{domain}"):
            raise ValueError("搜索地址必须属于所填写的域名。")
        source_id = f"custom-{hashlib.sha256(f'{domain}:{name}'.encode()).hexdigest()[:12]}"
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO book_search_sources (
                    id, name, kind, domain, homepage_url, search_url_template,
                    book_type, mature, enabled, builtin, credential_supported,
                    sort_order, created_at, updated_at
                ) VALUES (?, ?, 'searx_domain', ?, ?, ?, ?, ?, 1, 0, 0, 80, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name, domain=excluded.domain,
                    homepage_url=excluded.homepage_url,
                    search_url_template=excluded.search_url_template,
                    book_type=excluded.book_type, mature=excluded.mature,
                    enabled=1, updated_at=excluded.updated_at
                """,
                (
                    source_id, name, domain, homepage_url, search_template,
                    clean_text(payload.get("book_type") or "自定义来源", 60),
                    int(bool(payload.get("mature"))), now, now,
                ),
            )
        return self.get_source(source_id) or {}

    def update_source(self, source_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        source = self.get_source(source_id)
        if not source:
            raise KeyError(source_id)
        updates: list[str] = []
        values: list[Any] = []
        if "enabled" in payload:
            updates.append("enabled = ?")
            values.append(int(bool(payload.get("enabled"))))
        if "confirmed_origin" in payload:
            confirmed = str(payload.get("confirmed_origin") or "").strip().rstrip("/")
            if confirmed:
                confirmed = validate_public_url(confirmed, require_https=True)
                parsed = urlparse(confirmed)
                confirmed = f"{parsed.scheme}://{parsed.netloc}"
            updates.append("confirmed_origin = ?")
            values.append(confirmed)
            if source_id == "soushuba" and confirmed:
                updates.extend(("domain = ?", "search_url_template = ?"))
                hostname = (urlparse(confirmed).hostname or "").removeprefix("www.")
                values.extend((hostname, f"{confirmed}/search.php?mod=forum"))
        if "release_url" in payload:
            if source_id != "soushuba":
                raise ValueError("只有搜书吧使用独立发布页地址。")
            release_url = str(payload.get("release_url") or "").strip()
            if release_url:
                release_url = validate_public_url(
                    release_url,
                    allow_nonstandard_port=True,
                )
            updates.append("release_url = ?")
            values.append(release_url)
        if not source["builtin"]:
            if "name" in payload:
                updates.append("name = ?")
                values.append(clean_text(payload.get("name"), 80) or source["name"])
            if "mature" in payload:
                updates.append("mature = ?")
                values.append(int(bool(payload.get("mature"))))
        if updates:
            updates.append("updated_at = ?")
            values.append(utc_now())
            values.append(source_id)
            with self._connect() as connection:
                connection.execute(f"UPDATE book_search_sources SET {', '.join(updates)} WHERE id = ?", values)
        return self.get_source(source_id) or {}

    def delete_source(self, source_id: str) -> bool:
        source = self.get_source(source_id)
        if not source:
            return False
        if source["builtin"]:
            raise ValueError("内置来源不能删除，可以将它停用。")
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM book_search_sources WHERE id = ?", (source_id,))
        return cursor.rowcount > 0

    def add_history(self, query: str, filters: Mapping[str, Any]) -> dict[str, Any]:
        entry = {"id": str(uuid.uuid4()), "query": clean_text(query, 240), "filters": dict(filters), "created_at": utc_now()}
        with self._connect() as connection:
            connection.execute("DELETE FROM book_search_history WHERE query = ?", (entry["query"],))
            connection.execute(
                "INSERT INTO book_search_history(id, query, filters_json, created_at) VALUES (?, ?, ?, ?)",
                (entry["id"], entry["query"], json.dumps(entry["filters"], ensure_ascii=False), entry["created_at"]),
            )
            connection.execute(
                """DELETE FROM book_search_history WHERE id NOT IN (
                       SELECT id FROM book_search_history ORDER BY created_at DESC LIMIT ?
                   )""",
                (HISTORY_LIMIT,),
            )
        return entry

    def list_history(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM book_search_history ORDER BY created_at DESC LIMIT ?", (HISTORY_LIMIT,)
            ).fetchall()
        return [
            {"id": row["id"], "query": row["query"], "filters": json.loads(row["filters_json"]), "created_at": row["created_at"]}
            for row in rows
        ]

    def delete_history(self, entry_id: str | None = None) -> int:
        with self._connect() as connection:
            if entry_id:
                cursor = connection.execute("DELETE FROM book_search_history WHERE id = ?", (entry_id,))
            else:
                cursor = connection.execute("DELETE FROM book_search_history")
        return cursor.rowcount

    def save_favorite(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        favorite_id = clean_text(payload.get("id"), 80)
        if not favorite_id or not isinstance(payload.get("offers"), list):
            raise ValueError("收藏内容不完整。")
        safe_payload = sanitize_group(payload)
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO book_search_favorites(id, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET payload_json=excluded.payload_json, updated_at=excluded.updated_at
                """,
                (favorite_id, json.dumps(safe_payload, ensure_ascii=False), now, now),
            )
        return {**safe_payload, "saved_at": now}

    def list_favorites(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM book_search_favorites ORDER BY updated_at DESC").fetchall()
        return [{**json.loads(row["payload_json"]), "saved_at": row["updated_at"]} for row in rows]

    def delete_favorite(self, favorite_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM book_search_favorites WHERE id = ?", (favorite_id,))
        return cursor.rowcount > 0


def sanitize_group(payload: Mapping[str, Any]) -> dict[str, Any]:
    offers = []
    for raw in list(payload.get("offers") or [])[:30]:
        if not isinstance(raw, Mapping):
            continue
        url = safe_result_url(raw.get("url"))
        if not url:
            continue
        offers.append(
            {
                "title": clean_text(raw.get("title"), 300),
                "authors": [clean_text(item, 120) for item in list(raw.get("authors") or [])[:8]],
                "source_id": clean_text(raw.get("source_id"), 80),
                "source_name": clean_text(raw.get("source_name"), 100),
                "url": url,
                "download_url": safe_result_url(raw.get("download_url")) if raw.get("access") == "public" else "",
                "download_format": clean_text(raw.get("download_format"), 20).upper(),
                "access": clean_text(raw.get("access") or "unknown", 30),
                "mature": bool(raw.get("mature")),
                "importable": bool(raw.get("importable")),
                "book_type": clean_text(raw.get("book_type"), 80),
                "updated_at": clean_text(raw.get("updated_at"), 80),
                "license": clean_text(raw.get("license"), 120),
            }
        )
    return {
        "id": clean_text(payload.get("id"), 80),
        "title": clean_text(payload.get("title"), 300),
        "authors": [clean_text(item, 120) for item in list(payload.get("authors") or [])[:8]],
        "cover_url": safe_result_url(payload.get("cover_url")),
        "description": clean_text(payload.get("description"), 1200),
        "book_type": clean_text(payload.get("book_type") or "图书", 80),
        "mature": bool(payload.get("mature")),
        "access": clean_text(payload.get("access") or "unknown", 30),
        "importable": bool(payload.get("importable")),
        "source_count": len({item["source_id"] for item in offers}),
        "offers": offers,
    }


class SearchAdapter(Protocol):
    def search(self, query: str, page: int, source: Mapping[str, Any], credentials: Mapping[str, str] | None = None) -> list[dict[str, Any]]: ...


class GoogleBooksAdapter:
    """Google Books mapping ported from Obsidian Book Search Plugin (MIT)."""

    endpoint = "https://www.googleapis.com/books/v1/volumes"

    def __init__(
        self,
        session: requests.Session,
        timeout: int = SEARCH_SOURCE_TIMEOUT_SECONDS,
        api_key: str = DEFAULT_GOOGLE_BOOKS_API_KEY,
    ) -> None:
        self.session = session
        self.timeout = timeout
        self.api_key = api_key

    def search(self, query: str, page: int, source: Mapping[str, Any], credentials: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
        isbn = normalize_isbn(query)
        params: dict[str, Any] = {
            "q": f"isbn:{isbn}" if isbn else query,
            "startIndex": (page - 1) * SEARCH_RESULT_LIMIT,
            "maxResults": SEARCH_RESULT_LIMIT,
            "printType": "books",
        }
        if self.api_key:
            params["key"] = self.api_key
        response = self.session.get(
            self.endpoint,
            params=params,
            timeout=self.timeout,
        )
        response.raise_for_status()
        results = []
        for rank, item in enumerate(response.json().get("items") or [], start=1):
            info = item.get("volumeInfo") or {}
            sale = item.get("saleInfo") or {}
            access_info = item.get("accessInfo") or {}
            identifiers = [entry.get("identifier") for entry in info.get("industryIdentifiers") or []]
            access = "public" if access_info.get("publicDomain") or access_info.get("viewability") == "ALL_PAGES" else "paid" if sale.get("saleability") == "FOR_SALE" else "unknown"
            thumbnail = ((info.get("imageLinks") or {}).get("thumbnail") or "").replace("&edge=curl", "")
            epub = access_info.get("epub") if isinstance(access_info.get("epub"), Mapping) else {}
            pdf = access_info.get("pdf") if isinstance(access_info.get("pdf"), Mapping) else {}
            download_url = ""
            download_format = ""
            if access == "public" and epub.get("isAvailable"):
                download_url = safe_result_url(epub.get("downloadLink"))
                download_format = "EPUB" if download_url else ""
            if access == "public" and not download_url and pdf.get("isAvailable"):
                download_url = safe_result_url(pdf.get("downloadLink"))
                download_format = "PDF" if download_url else ""
            title = str(info.get("title") or "")
            if info.get("subtitle"):
                title = f"{title}: {info['subtitle']}"
            results.append(
                {
                    "title": title,
                    "authors": info.get("authors") or [],
                    "description": info.get("description") or "",
                    "cover_url": str(thumbnail).replace("http://", "https://", 1),
                    "url": info.get("canonicalVolumeLink") or info.get("infoLink") or f"https://books.google.com/books?id={item.get('id', '')}",
                    "updated_at": info.get("publishedDate") or "",
                    "isbns": identifiers,
                    "access": access,
                    "download_url": download_url,
                    "download_format": download_format,
                    "rank": rank,
                }
            )
        return results


class OpenLibraryAdapter:
    """Open Library ISBN/free-text mapping ported from Citadel (MIT)."""

    endpoint = "https://openlibrary.org/search.json"
    isbn_endpoint = "https://openlibrary.org/api/books"

    def __init__(self, session: requests.Session, timeout: int = SEARCH_SOURCE_TIMEOUT_SECONDS) -> None:
        self.session = session
        self.timeout = timeout

    def search(self, query: str, page: int, source: Mapping[str, Any], credentials: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
        isbn = normalize_isbn(query)
        if isbn:
            response = self.session.get(
                self.isbn_endpoint,
                params={"bibkeys": f"ISBN:{isbn}", "format": "json", "jscmd": "data"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            values = list(response.json().values())
            return [self._map_isbn_book(values[0], isbn)] if values else []
        # Open Library currently rejects two-character full-text queries with
        # HTTP 422, while its title/author fields accept Chinese names.
        common_params = {
            "page": page,
            "limit": SEARCH_RESULT_LIMIT,
            "fields": "key,title,subtitle,author_name,cover_i,first_publish_year,isbn,public_scan_b,ebook_access,publisher,subject",
        }
        query_params = {"q": query} if len(query.strip()) >= 3 else {"title": query}
        request_timeout = max(1.0, self.timeout / 2) if len(query.strip()) < 3 else self.timeout
        response = self.session.get(
            self.endpoint,
            params={**query_params, **common_params},
            timeout=request_timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if len(query.strip()) < 3 and not payload.get("docs"):
            response = self.session.get(
                self.endpoint,
                params={"author": query, **common_params},
                timeout=request_timeout,
            )
            response.raise_for_status()
            payload = response.json()
        results = []
        for rank, item in enumerate(payload.get("docs") or [], start=1):
            key = str(item.get("key") or "")
            cover_id = item.get("cover_i")
            public = bool(item.get("public_scan_b")) or item.get("ebook_access") == "public"
            title = str(item.get("title") or "")
            if item.get("subtitle"):
                title = f"{title}: {item['subtitle']}"
            subjects = unique_casefolded(item.get("subject") or [], limit=6)
            results.append(
                {
                    "title": title,
                    "authors": item.get("author_name") or [],
                    "description": "；".join(subjects),
                    "cover_url": f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg" if cover_id else "",
                    "url": f"https://openlibrary.org{key}" if key.startswith("/") else "https://openlibrary.org/",
                    "updated_at": str(item.get("first_publish_year") or ""),
                    "isbns": item.get("isbn") or [],
                    "access": "public" if public else "unknown",
                    "rank": rank,
                }
            )
        return results

    @staticmethod
    def _map_isbn_book(item: Mapping[str, Any], queried_isbn: str) -> dict[str, Any]:
        identifiers = item.get("identifiers") if isinstance(item.get("identifiers"), Mapping) else {}
        identifier_values = list(identifiers.get("isbn_13") or []) + list(identifiers.get("isbn_10") or [])
        preferred_isbn = pick_preferred_isbn([str(value) for value in identifier_values]) or queried_isbn
        cover = item.get("cover") if isinstance(item.get("cover"), Mapping) else {}
        authors = [
            clean_text(author.get("name"), 120)
            for author in item.get("authors") or []
            if isinstance(author, Mapping) and clean_text(author.get("name"), 120)
        ]
        subjects = unique_casefolded(
            [subject.get("name") for subject in item.get("subjects") or [] if isinstance(subject, Mapping)],
            limit=6,
        )
        title = str(item.get("title") or "")
        if item.get("subtitle"):
            title = f"{title}: {item['subtitle']}"
        item_url = safe_result_url(item.get("url"))
        key = str(item.get("key") or "")
        if not item_url and key:
            item_url = f"https://openlibrary.org{key}" if key.startswith("/") else ""
        return {
            "title": title,
            "authors": authors,
            "description": "；".join(subjects),
            "cover_url": cover.get("large") or cover.get("medium") or cover.get("small") or "",
            "url": item_url or f"https://openlibrary.org/isbn/{queried_isbn}",
            "updated_at": item.get("publish_date") or "",
            "isbns": [preferred_isbn, *identifier_values],
            "access": "unknown",
            "rank": 1,
        }


class GutendexAdapter:
    """Search Project Gutenberg's public-domain catalogue through Gutendex.

    Gutendex exposes catalogue metadata and format links without an API key.
    We explicitly request records marked out of copyright in the United States;
    users still need to check the copyright rules where they live.
    """

    endpoint = "https://gutendex.com/books/"

    def __init__(self, session: requests.Session, timeout: int = SEARCH_SOURCE_TIMEOUT_SECONDS) -> None:
        self.session = session
        self.timeout = timeout

    def search(self, query: str, page: int, source: Mapping[str, Any], credentials: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
        response = self.session.get(
            self.endpoint,
            params={"search": query, "page": page, "copyright": "false"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        results = []
        for rank, item in enumerate(response.json().get("results") or [], start=1):
            if item.get("copyright") is not False:
                continue
            formats = item.get("formats") if isinstance(item.get("formats"), Mapping) else {}
            cover_url = formats.get("image/jpeg") or ""
            plain_text_url = next(
                (
                    safe_result_url(url)
                    for mime_type, url in formats.items()
                    if str(mime_type).casefold().startswith("text/plain") and safe_result_url(url)
                ),
                "",
            )
            epub_url = safe_result_url(formats.get("application/epub+zip"))
            download_url = plain_text_url or epub_url
            download_format = "TXT" if plain_text_url else "EPUB" if epub_url else ""
            authors = [
                clean_text(person.get("name"), 120)
                for person in item.get("authors") or []
                if isinstance(person, Mapping) and clean_text(person.get("name"), 120)
            ]
            summaries = [clean_text(summary, 700) for summary in item.get("summaries") or [] if clean_text(summary, 700)]
            subjects = [clean_text(subject, 160) for subject in item.get("subjects") or [] if clean_text(subject, 160)]
            description = summaries[0] if summaries else "；".join(subjects[:4])
            gutenberg_id = item.get("id")
            if not isinstance(gutenberg_id, int) or gutenberg_id <= 0:
                continue
            results.append(
                {
                    "title": upstream_fix_subtitles(str(item.get("title") or "")),
                    "authors": authors,
                    "description": description,
                    "cover_url": cover_url,
                    "url": f"https://www.gutenberg.org/ebooks/{gutenberg_id}",
                    "access": "public",
                    "download_url": download_url,
                    "download_format": download_format,
                    "importable": bool(plain_text_url),
                    "license": "美国公版（请核对所在地版权）",
                    "rank": rank,
                }
            )
        return results


class GutenbergOpdsAdapter:
    """Fallback to Project Gutenberg's official, no-key OPDS catalogue."""

    endpoint = "https://www.gutenberg.org/ebooks/search.opds/"
    namespaces = {"atom": "http://www.w3.org/2005/Atom"}

    def __init__(self, session: requests.Session, timeout: int = SEARCH_SOURCE_TIMEOUT_SECONDS) -> None:
        self.session = session
        self.timeout = timeout

    def search(self, query: str, page: int, source: Mapping[str, Any], credentials: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
        response = self.session.get(
            self.endpoint,
            params={"query": query, "start_index": ((page - 1) * 25) + 1},
            timeout=self.timeout,
        )
        response.raise_for_status()
        root = ElementTree.fromstring(response.text[:2_000_000])
        results = []
        for entry in root.findall("atom:entry", self.namespaces):
            entry_id = str(entry.findtext("atom:id", default="", namespaces=self.namespaces) or "").strip()[:300]
            match = re.search(r"/ebooks/(\d+)(?:\.opds)?$", entry_id)
            if not match:
                continue
            gutenberg_id = int(match.group(1))
            content = clean_text(entry.findtext("atom:content", default="", namespaces=self.namespaces), 300)
            authors = [] if re.search(r"\bdownloads?$", content, re.IGNORECASE) else [content] if content else []
            thumbnail = ""
            for link in entry.findall("atom:link", self.namespaces):
                relation = str(link.get("rel") or "")
                candidate = str(link.get("href") or "")
                if relation.endswith("/image/thumbnail") and safe_result_url(candidate):
                    thumbnail = candidate
                    break
            results.append(
                {
                    "title": upstream_fix_subtitles(
                        str(entry.findtext("atom:title", default="", namespaces=self.namespaces) or "")
                    ),
                    "authors": authors,
                    "cover_url": thumbnail,
                    "url": f"https://www.gutenberg.org/ebooks/{gutenberg_id}",
                    "updated_at": entry.findtext("atom:updated", default="", namespaces=self.namespaces),
                    "access": "public",
                    # Project Gutenberg's official HTTPS cache URL stays on the
                    # validated source domain and avoids the legacy TXT route's
                    # downgrade redirect to plain HTTP.
                    "download_url": f"https://www.gutenberg.org/cache/epub/{gutenberg_id}/pg{gutenberg_id}.txt",
                    "download_format": "TXT",
                    "importable": True,
                    "license": "Project Gutenberg License（请核对所在地版权）",
                    "rank": len(results) + 1,
                }
            )
            if len(results) >= SEARCH_RESULT_LIMIT:
                break
        return results


class ManualLoginRequired(RuntimeError):
    """A public search page now requires an interactive site login."""


class DirectHtmlAdapter:
    """Parse public search pages without executing page scripts.

    The parser intentionally uses a small allowlisted set of ordinary book
    link patterns. It does not accept user-provided selectors or scripts.
    """

    LINK_SELECTORS: dict[str, tuple[str, ...]] = {
        "qidian": ('a[href*="/book/"]',),
        "fanqie": ('a[href*="/page/"]', 'a[href*="/reader/"]'),
        "jjwxc": ('a[href*="onebook.php"]',),
        "weread": ('a[href*="/web/bookDetail/"]',),
        "soushuba": ('a[href*="thread-"]', 'a[href*="viewthread"]'),
    }
    LOGIN_MARKERS = ("验证码", "安全验证", "请先登录", "人机验证", "captcha", "verify you are human")

    def __init__(self, session: requests.Session, timeout: int = SEARCH_SOURCE_TIMEOUT_SECONDS) -> None:
        self.session = session
        self.timeout = timeout

    @staticmethod
    def _json_ld_books(soup: BeautifulSoup, base_url: str) -> list[dict[str, Any]]:
        books: list[dict[str, Any]] = []

        def visit(value: Any) -> None:
            if isinstance(value, list):
                for item in value:
                    visit(item)
                return
            if not isinstance(value, Mapping):
                return
            graph = value.get("@graph")
            if graph:
                visit(graph)
            types = value.get("@type") or []
            if isinstance(types, str):
                types = [types]
            if not any(str(item).casefold() == "book" for item in types):
                return
            author_value = value.get("author") or []
            if not isinstance(author_value, list):
                author_value = [author_value]
            authors = [
                clean_text(item.get("name") if isinstance(item, Mapping) else item, 120)
                for item in author_value
            ]
            image_value = value.get("image") or ""
            if isinstance(image_value, Mapping):
                image_value = image_value.get("url") or image_value.get("contentUrl") or ""
            url_value = value.get("url") or value.get("mainEntityOfPage") or ""
            if isinstance(url_value, Mapping):
                url_value = url_value.get("@id") or url_value.get("url") or ""
            books.append({
                "title": value.get("name") or value.get("headline"),
                "authors": [item for item in authors if item],
                "description": value.get("description") or "",
                "cover_url": urljoin(base_url, str(image_value)),
                "url": urljoin(base_url, str(url_value)),
                "isbns": [value.get("isbn")] if value.get("isbn") else [],
                "updated_at": value.get("datePublished") or value.get("dateModified") or "",
            })

        for script in soup.select('script[type="application/ld+json"]'):
            try:
                visit(json.loads(script.string or script.get_text() or "{}"))
            except (json.JSONDecodeError, TypeError):
                continue
        return books

    @staticmethod
    def _nearby_text(anchor: Any, selectors: tuple[str, ...]) -> str:
        container = anchor.find_parent(["article", "li", "div", "tr"]) or anchor.parent
        if not container:
            return ""
        for selector in selectors:
            match = container.select_one(selector)
            if match:
                value = clean_text(match.get("alt") if match.name == "img" else match.get_text(" ", strip=True), 300)
                if value:
                    return value
        return ""

    def search(self, query: str, page: int, source: Mapping[str, Any], credentials: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
        template = str(source.get("search_url_template") or "")
        if not template or "{query}" not in template:
            return []
        target_url = template.replace("{query}", quote(query, safe=""))
        validate_public_url(target_url, require_https=True)
        response = self.session.get(target_url, timeout=self.timeout, allow_redirects=False)
        response.raise_for_status()
        page_text = clean_text(response.text, 20000).casefold()
        if any(marker in page_text for marker in self.LOGIN_MARKERS):
            raise ManualLoginRequired("来源需要在原站手动登录或完成验证")
        soup = BeautifulSoup(response.text, "html.parser")
        raw_results = self._json_ld_books(soup, target_url)
        selectors = self.LINK_SELECTORS.get(str(source.get("id")), ())
        seen_urls = {safe_result_url(item.get("url")) for item in raw_results}
        for selector in selectors:
            for anchor in soup.select(selector):
                title = clean_text(anchor.get("title") or anchor.get_text(" ", strip=True), 300)
                item_url = safe_result_url(urljoin(target_url, str(anchor.get("href") or "")))
                if not title or len(title) < 2 or not item_url or item_url in seen_urls:
                    continue
                seen_urls.add(item_url)
                container = anchor.find_parent(["article", "li", "div", "tr"]) or anchor.parent
                image = container.select_one("img") if container else None
                raw_results.append({
                    "title": title,
                    "authors": [self._nearby_text(anchor, (".author", '[class*="author"]', '[data-author]'))],
                    "description": self._nearby_text(anchor, (".intro", ".desc", '[class*="intro"]', '[class*="desc"]')),
                    "cover_url": urljoin(target_url, str(image.get("src") or image.get("data-src") or "")) if image else "",
                    "url": item_url,
                })
                if len(raw_results) >= SEARCH_RESULT_LIMIT:
                    break
            if len(raw_results) >= SEARCH_RESULT_LIMIT:
                break
        return [{**item, "rank": rank} for rank, item in enumerate(raw_results[:SEARCH_RESULT_LIMIT], start=1)]


class SoushubaAdapter:
    """Search a confirmed Discuz forum through its normal account flow.

    Credentials are posted only to the user-confirmed HTTPS origin.  The
    adapter keeps its cookies in a dedicated session, never handles CAPTCHA
    challenges, and returns search-result metadata rather than protected post
    bodies.
    """

    LOGIN_MARKERS = ("验证码", "安全验证", "人机验证", "captcha")
    BROAD_QUERY_PREFIXES = ("我的", "一个", "一部", "这本", "那本")

    def __init__(self, session: requests.Session, timeout: int = SEARCH_SOURCE_TIMEOUT_SECONDS) -> None:
        self.session = session
        self.timeout = timeout

    @staticmethod
    def _confirmed_origin(source: Mapping[str, Any]) -> str:
        configured = str(source.get("confirmed_origin") or "").strip().rstrip("/")
        if not configured:
            raise ManualLoginRequired("请先确认搜书吧当前域名")
        validated = validate_public_url(configured, require_https=True)
        parsed = urlparse(validated)
        return f"{parsed.scheme}://{parsed.netloc}"

    @staticmethod
    def _same_origin_url(origin: str, candidate: str, *, purpose: str) -> str:
        target = urljoin(origin + "/", candidate)
        expected = urlparse(origin)
        parsed = urlparse(target)
        if parsed.scheme != "https" or parsed.netloc.casefold() != expected.netloc.casefold():
            raise ValueError(f"搜书吧{purpose}地址离开了已确认域名，已停止发送账号或会话。")
        return validate_public_url(target, require_https=True)

    def _get(self, target: str) -> requests.Response:
        response = self.session.get(target, timeout=self.timeout, allow_redirects=False)
        response.raise_for_status()
        return response

    def _follow_same_origin_redirect(self, response: requests.Response, origin: str) -> requests.Response:
        current = response
        for _ in range(3):
            if not current.is_redirect and not current.is_permanent_redirect:
                return current
            location = str(current.headers.get("Location") or "")
            if not location:
                break
            target = self._same_origin_url(origin, location, purpose="跳转")
            current = self._get(target)
        return current

    @staticmethod
    def _form_payload(form: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for field in form.select("input[name]"):
            field_type = str(field.get("type") or "text").casefold()
            if field_type in {"submit", "button", "file"}:
                continue
            if field_type in {"checkbox", "radio"} and not field.has_attr("checked"):
                continue
            payload[str(field.get("name"))] = str(field.get("value") or "")
        return payload

    def _login(self, origin: str, credentials: Mapping[str, str]) -> None:
        username = str(credentials.get("username") or "").strip()
        password = str(credentials.get("password") or "")
        if not username or not password:
            raise ManualLoginRequired("搜书吧账号尚未配置完整")

        home = self._get(origin + "/")
        soup = BeautifulSoup(home.text, "html.parser")
        form = soup.select_one('form#lsform, form[action*="logging"]')
        if not form:
            raise ManualLoginRequired("搜书吧登录入口已变化，需要手动登录")
        action = self._same_origin_url(origin, str(form.get("action") or ""), purpose="登录")
        payload = self._form_payload(form)
        payload.update({"username": username, "password": password, "cookietime": "2592000"})
        login_response = self.session.post(
            action,
            data=payload,
            timeout=self.timeout,
            allow_redirects=False,
            headers={"Referer": origin + "/"},
        )
        login_response.raise_for_status()
        login_text = clean_text(login_response.text, 20000).casefold()
        if any(marker.casefold() in login_text for marker in self.LOGIN_MARKERS):
            raise ManualLoginRequired("搜书吧要求验证码或安全验证，请在原站手动登录")

        # Discuz commonly returns an in-ajax response while setting the session
        # cookie.  Re-read the home page to verify the resulting authenticated
        # state instead of trusting a success string from the POST response.
        verified_home = self._get(origin + "/")
        verified_text = clean_text(verified_home.text, 30000)
        if username not in verified_text or "退出" not in verified_text:
            raise ManualLoginRequired("搜书吧账号登录失败或需要额外验证")

    @staticmethod
    def _result_authors(title: str) -> list[str]:
        match = re.search(r"作者\s*[:：]\s*([^\[【（(]+)", title)
        return [clean_text(match.group(1), 120)] if match else []

    @classmethod
    def _broader_query(cls, query: str) -> str:
        compact = re.sub(r"\s+", "", clean_text(query, 120))
        if len(compact) < 4 or not all("\u3400" <= character <= "\u9fff" for character in compact):
            return ""
        for prefix in cls.BROAD_QUERY_PREFIXES:
            if compact.startswith(prefix) and len(compact) - len(prefix) >= 2:
                return compact[len(prefix):]
        return ""

    def _search_once(self, origin: str, query: str, page: int) -> list[dict[str, Any]]:
        search_page = self._get(origin + "/search.php?mod=forum")
        search_markup = response_markup(search_page)
        search_text = clean_text(search_markup, 20000)
        if "游客" in search_text and "无法进行此操作" in search_text:
            raise ManualLoginRequired("搜书吧登录状态已失效，请在原站手动登录")
        soup = BeautifulSoup(search_markup, "html.parser")
        form = soup.select_one("form#scform") or soup.select_one('form[action*="search.php"]')
        if not form:
            raise RuntimeError("搜书吧搜索入口已变化")
        action = self._same_origin_url(origin, str(form.get("action") or "search.php?mod=forum"), purpose="搜索")
        payload = self._form_payload(form)
        payload.update({"srchtxt": query.encode("gb18030"), "searchsubmit": "yes"})
        response = self.session.post(
            action,
            data=payload,
            timeout=self.timeout,
            allow_redirects=False,
            headers={"Referer": origin + "/search.php?mod=forum"},
        )
        response.raise_for_status()
        response = self._follow_same_origin_redirect(response, origin)
        if page > 1:
            page_url = self._same_origin_url(origin, response.url, purpose="分页")
            separator = "&" if "?" in page_url else "?"
            response = self._get(f"{page_url}{separator}page={page}")

        result_markup = response_markup(response)
        result_soup = BeautifulSoup(result_markup, "html.parser")
        result_text = clean_text(result_markup, 30000)
        total_match = re.search(r"相关内容\s*(\d+)\s*个", result_text)
        source_total = int(total_match.group(1)) if total_match else 0
        results: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for anchor in result_soup.select('h3 a[href*="viewthread"], a[href*="viewthread"][href*="highlight"]'):
            title = clean_text(anchor.get_text(" ", strip=True), 300)
            item_url = safe_result_url(urljoin(origin + "/", str(anchor.get("href") or "")))
            if not title or not item_url or item_url in seen_urls:
                continue
            seen_urls.add(item_url)
            container = anchor.find_parent("li") or anchor.find_parent(["article", "div"])
            container_text = clean_text(container.get_text(" ", strip=True) if container else "", 1600)
            paragraphs = [clean_text(item.get_text(" ", strip=True), 800) for item in container.select("p")] if container else []
            description = next(
                (
                    item for item in paragraphs
                    if item and not re.search(r"\d+\s*个回复|\d+\s*次查看|^\d{4}-\d{1,2}-\d{1,2}", item)
                ),
                "",
            )
            updated_match = re.search(r"\b(20\d{2}-\d{1,2}-\d{1,2}(?:\s+\d{1,2}:\d{2})?)\b", container_text)
            results.append(
                {
                    "title": title,
                    "authors": self._result_authors(title),
                    "description": description,
                    "url": item_url,
                    "updated_at": updated_match.group(1) if updated_match else "",
                    "access": "login_required",
                    "importable": False,
                    "rank": len(results) + 1,
                    "source_total": source_total,
                    "matched_query": query,
                }
            )
            if len(results) >= SEARCH_RESULT_LIMIT:
                break
        return results

    def search(
        self,
        query: str,
        page: int,
        source: Mapping[str, Any],
        credentials: Mapping[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        origin = self._confirmed_origin(source)
        if not credentials:
            raise ManualLoginRequired("搜书吧站内搜索需要账号")
        self._login(origin, credentials)
        broader_query = self._broader_query(query)
        exact_results = self._search_once(origin, query, 1) if page == 1 else []
        broad_results = self._search_once(origin, broader_query, page) if broader_query else []
        if not broader_query:
            return self._search_once(origin, query, page) if page > 1 else exact_results

        combined: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        source_total = max(
            (int(item.get("source_total") or 0) for item in [*exact_results, *broad_results]),
            default=0,
        )
        for item in [*exact_results, *broad_results]:
            item_url = str(item.get("url") or "")
            if not item_url or item_url in seen_urls:
                continue
            seen_urls.add(item_url)
            combined.append({**item, "rank": len(combined) + 1, "source_total": source_total})
        return combined


class FallbackAdapter:
    def __init__(self, primary: SearchAdapter, fallback: SearchAdapter) -> None:
        self.primary = primary
        self.fallback = fallback

    def search(self, query: str, page: int, source: Mapping[str, Any], credentials: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
        primary_error: Exception | None = None
        try:
            results = self.primary.search(query, page, source, credentials)
            if results:
                return results
        except Exception as exc:  # The site search is best effort; SearXNG is the documented fallback.
            primary_error = exc
        try:
            return self.fallback.search(query, page, source, credentials)
        except Exception:
            if primary_error:
                raise primary_error
            return []


class SearxAdapter:
    def __init__(self, session: requests.Session, searxng_url: str, timeout: int = SEARCH_SOURCE_TIMEOUT_SECONDS) -> None:
        self.session = session
        self.endpoint = searxng_url.rstrip("/") + "/search"
        self.timeout = timeout

    def search(self, query: str, page: int, source: Mapping[str, Any], credentials: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
        domain = str(source.get("domain") or "").strip()
        search_query = f"{query} site:{domain}" if domain else query
        if source.get("id") == "soushuba" and not domain:
            search_query = f"{query} 搜书吧 soushu2030"
        response = self.session.get(
            self.endpoint,
            params={"q": search_query, "format": "json", "pageno": page, "language": "zh-CN", "safesearch": 0, "categories": "general"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        results = []
        for rank, item in enumerate(response.json().get("results") or [], start=1):
            item_url = safe_result_url(item.get("url"))
            host = (urlparse(item_url).hostname or "").removeprefix("www.") if item_url else ""
            normalized_domain = domain.removeprefix("www.")
            if normalized_domain and host != normalized_domain and not host.endswith(f".{normalized_domain}"):
                continue
            source_name = source.get("name") if source.get("id") != "web" else host or "全网发现"
            results.append(
                {
                    "title": item.get("title"),
                    "description": item.get("content") or item.get("snippet") or "",
                    "cover_url": item.get("thumbnail") or item.get("img_src") or "",
                    "url": item_url,
                    "updated_at": item.get("publishedDate") or "",
                    "source_name": source_name,
                    "access": "unknown",
                    "rank": rank,
                }
            )
        return results


@dataclass
class SearchJob:
    id: str
    query: str
    page: int
    include_mature: bool
    created_at: str
    status: str
    source_states: dict[str, dict[str, Any]]
    raw_results: list[dict[str, Any]]
    results: list[dict[str, Any]]
    completed_at: str | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "query": self.query,
            "page": self.page,
            "include_mature": self.include_mature,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "status": self.status,
            "sources": list(self.source_states.values()),
            "results": list(self.results),
            "result_count": len(self.results),
            "has_next_page": any(
                state.get("status") == "success"
                and (
                    int(state.get("available_count") or 0) > self.page * SEARCH_RESULT_LIMIT
                    or int(state.get("result_count") or 0) >= SEARCH_RESULT_LIMIT
                )
                for state in self.source_states.values()
            ),
        }


AdapterFactory = Callable[[Mapping[str, Any]], SearchAdapter]


@dataclass
class SourceFailureState:
    failures: int = 0
    suspended_until: float = 0.0
    reason: str = ""


class SourceCircuitBreaker:
    """Temporarily stop calling repeatedly failing upstreams.

    This mirrors the failure-isolation pattern used by mature metasearch
    services: one unhealthy source must not slow down every new search job.
    State is intentionally process-local and contains no search results.
    """

    def __init__(
        self,
        *,
        threshold: int = SOURCE_FAILURE_THRESHOLD,
        base_cooldown: int = SOURCE_COOLDOWN_SECONDS,
        max_cooldown: int = SOURCE_MAX_COOLDOWN_SECONDS,
    ) -> None:
        self.threshold = max(1, threshold)
        self.base_cooldown = max(1, base_cooldown)
        self.max_cooldown = max(self.base_cooldown, max_cooldown)
        self.states: dict[str, SourceFailureState] = {}
        self.lock = threading.Lock()

    def suspended(self, source_id: str) -> tuple[bool, int, str]:
        with self.lock:
            state = self.states.get(source_id)
            if not state:
                return False, 0, ""
            remaining = max(0, int(state.suspended_until - time.monotonic() + 0.999))
            if remaining <= 0:
                state.suspended_until = 0.0
                return False, 0, state.reason
            return True, remaining, state.reason

    def record_success(self, source_id: str) -> None:
        with self.lock:
            self.states.pop(source_id, None)

    def record_failure(self, source_id: str, reason: str, *, retry_after: int | None = None) -> int:
        with self.lock:
            state = self.states.setdefault(source_id, SourceFailureState())
            state.failures += 1
            state.reason = clean_text(reason, 120)
            if retry_after is not None:
                cooldown = max(1, min(int(retry_after), self.max_cooldown))
            elif state.failures >= self.threshold:
                cooldown = min(
                    self.base_cooldown * (2 ** (state.failures - self.threshold)),
                    self.max_cooldown,
                )
            else:
                return 0
            state.suspended_until = max(state.suspended_until, time.monotonic() + cooldown)
            return cooldown


def response_retry_after_seconds(response: requests.Response | None, default: int = 60) -> int:
    if response is None:
        return default
    value = str(response.headers.get("Retry-After") or "").strip()
    if value.isdigit():
        return max(1, min(int(value), SOURCE_MAX_COOLDOWN_SECONDS))
    return default


class BookSearchService:
    def __init__(
        self,
        data_dir: Path,
        *,
        searxng_url: str = DEFAULT_SEARXNG_URL,
        session: requests.Session | None = None,
        vault: CredentialVault | None = None,
        adapter_factory: AdapterFactory | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.store = BookSearchStore(self.data_dir / "book_search.db")
        self.session = session or requests.Session()
        if session is None and sys.platform == "darwin" and MACOS_SYSTEM_CA_BUNDLE.is_file():
            # Homebrew Python's certifi bundle can lag macOS trust roots.  Use
            # the system CA bundle while keeping certificate verification on.
            self.session.verify = str(MACOS_SYSTEM_CA_BUNDLE)
        self.session.headers.update({"User-Agent": "ShengYue-BookDiscovery/1.0 (+local personal search)"})
        self.searxng_url = searxng_url.rstrip("/")
        self.vault = vault or KeychainCredentialVault()
        self.adapter_factory = adapter_factory
        self.jobs: dict[str, SearchJob] = {}
        self.lock = threading.RLock()
        self._health_cache: tuple[float, bool] = (0.0, False)
        self.source_breaker = SourceCircuitBreaker()

    def _adapter_for(self, source: Mapping[str, Any]) -> SearchAdapter:
        if self.adapter_factory:
            return self.adapter_factory(source)
        if source.get("kind") == "google_books":
            return GoogleBooksAdapter(self.session)
        if source.get("kind") == "open_library":
            return OpenLibraryAdapter(self.session)
        if source.get("kind") == "gutendex":
            return FallbackAdapter(
                GutendexAdapter(self.session, timeout=max(1, SEARCH_SOURCE_TIMEOUT_SECONDS // 2)),
                GutenbergOpdsAdapter(self.session, timeout=max(1, SEARCH_SOURCE_TIMEOUT_SECONDS // 2)),
            )
        if source.get("kind") == "soushuba" and source.get("confirmed_origin"):
            dedicated_session = requests.Session()
            dedicated_session.headers.update(self.session.headers)
            dedicated_session.verify = getattr(self.session, "verify", True)
            return FallbackAdapter(
                SoushubaAdapter(dedicated_session, timeout=SEARCH_SOURCE_TIMEOUT_SECONDS),
                SearxAdapter(self.session, self.searxng_url, timeout=max(1, SEARCH_SOURCE_TIMEOUT_SECONDS // 2)),
            )
        if source.get("kind") == "html_domain":
            return FallbackAdapter(
                DirectHtmlAdapter(self.session, timeout=max(1, SEARCH_SOURCE_TIMEOUT_SECONDS // 2)),
                SearxAdapter(self.session, self.searxng_url, timeout=max(1, SEARCH_SOURCE_TIMEOUT_SECONDS // 2)),
            )
        return SearxAdapter(self.session, self.searxng_url)

    def searxng_available(self, *, refresh: bool = False) -> bool:
        checked_at, cached = self._health_cache
        if not refresh and time.monotonic() - checked_at < 10:
            return cached
        try:
            response = self.session.get(
                self.searxng_url + "/search",
                params={"q": "声阅", "format": "json", "categories": "general"},
                timeout=1.5,
            )
            available = response.ok and isinstance(response.json(), dict)
        except Exception:
            available = False
        self._health_cache = (time.monotonic(), available)
        return available

    def public_sources(self) -> list[dict[str, Any]]:
        searx_up = self.searxng_available()
        sources = []
        for source in self.store.list_sources():
            state = "ready"
            message = "可直接搜索"
            suspended, remaining, reason = self.source_breaker.suspended(source["id"])
            if source["kind"].startswith("searx") or source["kind"] == "soushuba":
                state = "ready" if searx_up else "degraded"
                message = "SearXNG 已连接" if searx_up else "SearXNG 未运行，将跳过此来源"
            if source["kind"] == "html_domain":
                message = "公开搜索页直连；异常时由 SearXNG 补充" if searx_up else "公开搜索页直连；SearXNG 备用通道未运行"
            if source["id"] == "soushuba" and source.get("confirmed_origin"):
                state = "ready"
                if self.vault.has(source["id"]):
                    message = "已确认域名和本机账号，可进行站内搜索"
                else:
                    state = "login_required"
                    message = "已确认域名；配置本机账号后可进行站内搜索"
            if source["id"] == "soushuba" and not source.get("confirmed_origin"):
                state = "needs_origin" if searx_up else "degraded"
                message = "尚未确认当前域名；先用全网线索搜索" if searx_up else "需要启动 SearXNG 并确认最新地址"
            if suspended:
                state = "degraded"
                message = f"连续失败，暂停 {remaining} 秒" + (f"（{reason}）" if reason else "")
            sources.append(
                {
                    **{key: value for key, value in source.items() if key not in {"created_at", "updated_at"}},
                    "credential_configured": self.vault.has(source["id"]) if source["credential_supported"] else False,
                    "health": state,
                    "health_message": message,
                }
            )
        return sources

    def start_job(self, query: str, *, page: int = 1, source_ids: Iterable[str] | None = None, include_mature: bool = True) -> dict[str, Any]:
        query = clean_text(query, 240)
        if not query:
            raise ValueError("请输入书名、作者或 ISBN。")
        if len(query) < 2:
            raise ValueError("搜索词至少需要两个字符。")
        page = max(1, min(int(page or 1), 20))
        requested = {str(item) for item in source_ids or [] if str(item)}
        sources = [source for source in self.store.list_sources(enabled_only=True) if not requested or source["id"] in requested]
        if not include_mature:
            sources = [source for source in sources if not source["mature"]]
        if not sources:
            raise ValueError("没有可用的搜索来源。")
        job_id = str(uuid.uuid4())
        states = {
            source["id"]: {
                "id": source["id"],
                "name": source["name"],
                "mature": source["mature"],
                "status": "queued",
                "result_count": 0,
                "available_count": 0,
                "message": "等待搜索",
            }
            for source in sources
        }
        searx_up = self.searxng_available()
        runnable_sources = []
        for source in sources:
            suspended, remaining, _reason = self.source_breaker.suspended(source["id"])
            if suspended:
                states[source["id"]].update(status="failed", message=f"来源连续失败，暂停 {remaining} 秒后重试")
                continue
            requires_searx = source["kind"].startswith("searx") or (
                source["kind"] == "soushuba" and not source.get("confirmed_origin")
            )
            if requires_searx and not searx_up:
                states[source["id"]].update(status="failed", message="SearXNG 未运行，已跳过此来源")
            else:
                runnable_sources.append(source)
        job = SearchJob(job_id, query, page, include_mature, utc_now(), "queued", states, [], [])
        with self.lock:
            self._prune_jobs()
            self.jobs[job_id] = job
        self.store.add_history(query, {"page": page, "source_ids": sorted(requested), "include_mature": include_mature})
        threading.Thread(target=self._run_job, args=(job_id, runnable_sources), daemon=True, name=f"book-search-{job_id[:8]}").start()
        return job.snapshot()

    def _prune_jobs(self) -> None:
        cutoff = time.time() - 3600
        stale = []
        for job_id, job in self.jobs.items():
            try:
                timestamp = datetime.fromisoformat(job.created_at).timestamp()
            except ValueError:
                timestamp = time.time()
            if timestamp < cutoff:
                stale.append(job_id)
        for job_id in stale:
            self.jobs.pop(job_id, None)

    def _search_source(self, job_id: str, source: Mapping[str, Any]) -> list[dict[str, Any]]:
        with self.lock:
            job = self.jobs[job_id]
            state = job.source_states[str(source["id"])]
            state.update(status="running", message="正在搜索")
        credentials = self.vault.read(str(source["id"])) if source.get("credential_supported") and self.vault.has(str(source["id"])) else None
        adapter = self._adapter_for(source)
        raw_items = adapter.search(job.query, job.page, source, credentials)
        available_count = max((int(item.get("source_total") or 0) for item in raw_items), default=0)
        source_limit = SEARCH_RESULT_LIMIT * 2 if source.get("id") == "soushuba" else SEARCH_RESULT_LIMIT
        normalized = []
        for raw in raw_items[:source_limit]:
            offer = normalize_offer(raw, source, job.query)
            if offer:
                normalized.append(offer)
        with self.lock:
            state = self.jobs[job_id].source_states[str(source["id"])]
            if self.jobs[job_id].status != "running" or state.get("status") != "running":
                return normalized
            self.source_breaker.record_success(str(source["id"]))
            message = (
                f"本页展示 {len(normalized)} 条 · 原站匹配约 {available_count} 条"
                if available_count > len(normalized)
                else f"找到 {len(normalized)} 条"
            )
            state.update(
                status="success",
                result_count=len(normalized),
                available_count=available_count,
                message=message,
            )
            self.jobs[job_id].raw_results.extend(normalized)
            self.jobs[job_id].results = merge_results(self.jobs[job_id].raw_results, self.jobs[job_id].query)
        return normalized

    def _run_job(self, job_id: str, sources: list[dict[str, Any]]) -> None:
        with self.lock:
            self.jobs[job_id].status = "running"
        if not sources:
            with self.lock:
                job = self.jobs[job_id]
                job.status = "failed"
                job.completed_at = utc_now()
            return
        executor = ThreadPoolExecutor(max_workers=min(8, len(sources)), thread_name_prefix="book-source")
        futures: dict[Future[list[dict[str, Any]]], dict[str, Any]] = {
            executor.submit(self._search_source, job_id, source): source for source in sources
        }
        done, pending = wait(futures, timeout=SEARCH_JOB_TIMEOUT_SECONDS)
        for future in done:
            source = futures[future]
            try:
                future.result()
            except requests.HTTPError as exc:
                status_code = exc.response.status_code if exc.response is not None else 0
                if status_code in {401, 403}:
                    message = "来源要求登录"
                    status = "login_required"
                elif status_code == 429:
                    cooldown = self.source_breaker.record_failure(
                        str(source["id"]),
                        "请求过于频繁",
                        retry_after=response_retry_after_seconds(exc.response),
                    )
                    message = f"请求过于频繁，暂停 {cooldown} 秒"
                    status = "failed"
                else:
                    if status_code >= 500 or not status_code:
                        self.source_breaker.record_failure(str(source["id"]), f"HTTP {status_code or '错误'}")
                    message = f"来源返回 HTTP {status_code or '错误'}"
                    status = "failed"
                self._mark_source(job_id, source, status, message)
            except requests.Timeout:
                self.source_breaker.record_failure(str(source["id"]), "响应超时")
                self._mark_source(job_id, source, "timeout", "来源响应超时")
            except ManualLoginRequired:
                self._mark_source(job_id, source, "login_required", "需要在原站手动登录或完成验证")
            except Exception as exc:
                LOGGER.info("Book source %s failed: %s", source.get("id"), exc)
                self.source_breaker.record_failure(str(source["id"]), "来源暂时不可用")
                self._mark_source(job_id, source, "failed", "来源暂时不可用")
        for future in pending:
            source = futures[future]
            future.cancel()
            self.source_breaker.record_failure(str(source["id"]), "超过整次搜索时限")
            self._mark_source(job_id, source, "timeout", "超过整次搜索时限")
        executor.shutdown(wait=False, cancel_futures=True)
        with self.lock:
            job = self.jobs[job_id]
            job.results = merge_results(job.raw_results, job.query)
            job.status = "completed" if job.results else "failed"
            job.completed_at = utc_now()

    def _mark_source(self, job_id: str, source: Mapping[str, Any], status: str, message: str) -> None:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return
            state = job.source_states[str(source["id"])]
            if state.get("status") != "success":
                state.update(status=status, message=message, result_count=0, available_count=0)

    def job_snapshot(self, job_id: str) -> dict[str, Any] | None:
        with self.lock:
            job = self.jobs.get(job_id)
            return job.snapshot() if job else None

    def import_public_text(self, job_id: str, group_id: str) -> dict[str, Any]:
        """Fetch one search result only when its adapter proved it importable.

        The client cannot submit a URL.  It references an in-memory result from
        this service, and the source id, license, format, DNS and every redirect
        are revalidated before any bytes are read.
        """
        with self.lock:
            job = self.jobs.get(str(job_id))
            group = next(
                (dict(item) for item in (job.results if job else []) if str(item.get("id")) == str(group_id)),
                None,
            )
        if not job or not group:
            raise ValueError("搜索结果不存在或已经过期，请重新找书。")
        offer = next(
            (
                dict(item)
                for item in group.get("offers") or []
                if item.get("source_id") in PUBLIC_TEXT_IMPORT_SOURCES
                and item.get("access") == "public"
                and item.get("importable") is True
                and item.get("download_format") == "TXT"
                and item.get("download_url")
                and item.get("license")
            ),
            None,
        )
        if not offer:
            raise ValueError("这个结果没有可自动导入的公版或开放授权纯文本。")

        source = self.store.get_source(str(offer["source_id"])) or {}
        source_domain = str(source.get("domain") or "").casefold().rstrip(".")
        target_url = str(offer["download_url"])
        response: requests.Response | None = None
        for _redirect in range(4):
            target_url = validate_public_url(target_url, require_https=True)
            hostname = str(urlparse(target_url).hostname or "").casefold().rstrip(".")
            if not source_domain or not (hostname == source_domain or hostname.endswith(f".{source_domain}")):
                raise ValueError("公开文本地址离开了已确认的来源域名，已停止导入。")
            response = self.session.get(target_url, timeout=20, allow_redirects=False)
            if response.status_code in {301, 302, 303, 307, 308}:
                location = str(response.headers.get("Location") or "").strip()
                if not location:
                    raise ValueError("公开文本来源返回了无效跳转。")
                target_url = urljoin(target_url, location)
                continue
            response.raise_for_status()
            break
        else:
            raise ValueError("公开文本来源跳转次数过多。")
        if response is None:
            raise ValueError("公开文本暂时无法读取。")

        declared_length = str(response.headers.get("Content-Length") or "").strip()
        if declared_length.isdigit() and int(declared_length) > MAX_PUBLIC_TEXT_BYTES:
            raise ValueError("公开文本超过 12MB，请下载后手动导入。")
        content = bytes(getattr(response, "content", b"") or b"")
        if not content:
            content = str(getattr(response, "text", "") or "").encode("utf-8")
        if len(content) > MAX_PUBLIC_TEXT_BYTES:
            raise ValueError("公开文本超过 12MB，请下载后手动导入。")

        decoded = ""
        preferred_encoding = str(getattr(response, "encoding", "") or "").strip()
        for encoding in ("utf-8-sig", preferred_encoding, "gb18030", "latin-1"):
            if not encoding:
                continue
            try:
                decoded = content.decode(encoding)
                break
            except (LookupError, UnicodeDecodeError):
                continue
        text = decoded.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n").strip()
        start = _GUTENBERG_START_RE.search(text)
        if start:
            text = text[start.end():].lstrip("\n ")
        end = _GUTENBERG_END_RE.search(text)
        if end:
            text = text[:end.start()].rstrip()
        if len(text) < 100:
            raise ValueError("公开文本内容过短或格式异常，请下载后手动检查。")
        return {
            "group_id": str(group["id"]),
            "title": clean_text(group.get("title"), 300),
            "authors": [clean_text(item, 120) for item in group.get("authors") or [] if clean_text(item, 120)],
            "text": text,
            "char_count": len(text),
            "source_id": str(offer["source_id"]),
            "source_name": clean_text(offer.get("source_name"), 100),
            "source_url": str(offer["url"]),
            "download_url": target_url,
            "license": clean_text(offer.get("license"), 160),
        }

    def _verify_soushuba_origin(
        self,
        origin: str,
        *,
        title: str,
        discovered_via: str,
    ) -> dict[str, Any]:
        verified = False
        try:
            validate_public_url(origin, require_https=True)
            response = self.session.get(origin, timeout=5, allow_redirects=False)
            markup = response_markup(response) if response.ok else ""
            text = clean_text(markup, 20000)
            page = BeautifulSoup(markup, "html.parser") if markup else None
            has_search = bool(
                page
                and (
                    page.select_one('form[action*="search.php"], a[href*="search.php"]')
                    or page.find("input", attrs={"type": "search"})
                    or page.find("form")
                )
            )
            verified = response.ok and "搜书吧" in text and has_search
        except Exception:
            verified = False
        return {
            "origin": origin,
            "verified": verified,
            "title": clean_text(title, 160),
            "discovered_via": discovered_via,
        }

    def _discover_soushuba_from_release_page(
        self,
        source: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        release_url = str(source.get("release_url") or "").strip()
        if not release_url:
            return []
        try:
            release_url = validate_public_url(
                release_url,
                allow_nonstandard_port=True,
            )
            response = self.session.get(release_url, timeout=5, allow_redirects=False)
            # Some rotating publication hosts intentionally serve a complete
            # directory document with a 404 status.  Treat the branded page
            # content as the signal; never submit data to this HTTP endpoint.
            if response.status_code >= 500:
                return []
            markup = response_markup(response)
            page = BeautifulSoup(markup, "html.parser")
            page_text = clean_text(markup, 20000)
            if "搜书吧" not in page_text or not (
                "soushu2030.com" in page_text.casefold() or "永久地址" in page_text
            ):
                return []
        except Exception:
            return []

        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()
        for anchor in page.select("a[href]"):
            href = safe_result_url(urljoin(release_url, str(anchor.get("href") or "")))
            parsed = urlparse(href)
            if parsed.scheme != "https" or not parsed.hostname:
                continue
            origin = f"https://{parsed.netloc}"
            if origin in seen or parsed.hostname in {"soushu2030.com", "www.soushu2030.com"}:
                continue
            seen.add(origin)
            candidates.append(
                self._verify_soushuba_origin(
                    origin,
                    title=anchor.get_text(" ", strip=True) or "发布页最新地址",
                    discovered_via="release_page",
                )
            )
        return sorted(candidates, key=lambda item: (not item["verified"], item["origin"]))[:6]

    def discover_soushuba_candidates(self) -> list[dict[str, Any]]:
        source = self.store.get_source("soushuba") or {}
        release_candidates = self._discover_soushuba_from_release_page(source)
        if any(candidate["verified"] for candidate in release_candidates):
            return release_candidates

        adapter = SearxAdapter(self.session, self.searxng_url, timeout=5)
        try:
            raw_results = adapter.search("搜书吧 soushu2030 最新网址", 1, {**source, "id": "web", "domain": ""})
        except requests.RequestException:
            return release_candidates
        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()
        for result in raw_results[:12]:
            result_url = safe_result_url(result.get("url"))
            parsed = urlparse(result_url)
            if parsed.scheme != "https" or not parsed.hostname:
                continue
            origin = f"https://{parsed.netloc}"
            if origin in seen or parsed.hostname in {"soushu2030.com", "www.soushu2030.com"}:
                continue
            seen.add(origin)
            candidates.append(
                self._verify_soushuba_origin(
                    origin,
                    title=str(result.get("title") or ""),
                    discovered_via="searxng",
                )
            )
        combined = [*release_candidates, *candidates]
        unique = {candidate["origin"]: candidate for candidate in combined}
        return sorted(unique.values(), key=lambda item: (not item["verified"], item["origin"]))[:6]


def _json_error(message: str, status: int):
    return jsonify({"success": False, "error": message}), status


def _is_local_credential_request() -> bool:
    if request.headers.get("X-ShengYue-Bridge-Request") == "1":
        return False
    if request.remote_addr not in {"127.0.0.1", "::1", None}:
        return False
    if request.headers.get("Sec-Fetch-Site", "").casefold() == "cross-site":
        return False
    origin = request.headers.get("Origin") or request.headers.get("Referer") or ""
    if origin:
        try:
            hostname = (urlparse(origin).hostname or "").casefold()
        except ValueError:
            return False
        if hostname not in {"localhost", "127.0.0.1", "::1"}:
            return False
    return True


def create_book_search_blueprint(
    data_dir: Path | None = None,
    *,
    service: BookSearchService | None = None,
    name: str = "book_search",
) -> Blueprint:
    search_service = service or BookSearchService(data_dir or Path("data"))
    blueprint = Blueprint(name, __name__)
    blueprint.book_search_service = search_service  # type: ignore[attr-defined]

    @blueprint.get("/api/book-search/sources")
    def list_sources_route():
        return jsonify({"success": True, "sources": search_service.public_sources(), "searxng_url": search_service.searxng_url})

    @blueprint.post("/api/book-search/jobs")
    def create_job_route():
        payload = request.get_json(silent=True) or {}
        try:
            job = search_service.start_job(
                str(payload.get("query") or ""),
                page=int(payload.get("page") or 1),
                source_ids=payload.get("source_ids") if isinstance(payload.get("source_ids"), list) else None,
                include_mature=payload.get("include_mature") is not False,
            )
            return jsonify({"success": True, "job": job, "job_id": job["id"]}), 202
        except (TypeError, ValueError) as exc:
            return _json_error(str(exc), 400)

    @blueprint.get("/api/book-search/jobs/<job_id>")
    def get_job_route(job_id: str):
        job = search_service.job_snapshot(job_id)
        if not job:
            return _json_error("搜索任务不存在或已过期。", 404)
        return jsonify({"success": True, "job": job})

    @blueprint.post("/api/book-search/jobs/<job_id>/import")
    def import_public_text_route(job_id: str):
        payload = request.get_json(silent=True) or {}
        group_id = str(payload.get("group_id") or "").strip()
        if not group_id:
            return _json_error("缺少书目编号。", 400)
        try:
            imported = search_service.import_public_text(job_id, group_id)
            return jsonify({"success": True, "book": imported})
        except ValueError as exc:
            return _json_error(str(exc), 409)
        except requests.Timeout:
            return _json_error("公开文本下载超时，请稍后重试。", 504)
        except requests.RequestException:
            return _json_error("公开文本来源暂时无法下载。", 502)

    @blueprint.route("/api/book-search/history", methods=["GET", "DELETE"])
    def history_route():
        if request.method == "GET":
            return jsonify({"success": True, "history": search_service.store.list_history()})
        payload = request.get_json(silent=True) or {}
        deleted = search_service.store.delete_history(str(payload.get("id") or request.args.get("id") or "") or None)
        return jsonify({"success": True, "deleted": deleted})

    @blueprint.route("/api/book-search/favorites", methods=["GET", "POST", "DELETE"])
    def favorites_route():
        if request.method == "GET":
            return jsonify({"success": True, "favorites": search_service.store.list_favorites()})
        payload = request.get_json(silent=True) or {}
        if request.method == "DELETE":
            favorite_id = str(payload.get("id") or request.args.get("id") or "")
            if not favorite_id:
                return _json_error("缺少收藏编号。", 400)
            return jsonify({"success": True, "deleted": search_service.store.delete_favorite(favorite_id)})
        try:
            favorite = search_service.store.save_favorite(payload)
            return jsonify({"success": True, "favorite": favorite})
        except ValueError as exc:
            return _json_error(str(exc), 400)

    @blueprint.route("/api/book-search/sources", methods=["POST", "PUT", "DELETE"])
    def mutate_sources_route():
        payload = request.get_json(silent=True) or {}
        try:
            if request.method == "POST":
                source = search_service.store.create_source(payload)
                return jsonify({"success": True, "source": source}), 201
            source_id = str(payload.get("id") or "")
            if not source_id:
                return _json_error("缺少来源编号。", 400)
            if request.method == "DELETE":
                deleted = search_service.store.delete_source(source_id)
                if deleted:
                    search_service.vault.delete(source_id)
                return jsonify({"success": True, "deleted": deleted})
            previous = search_service.store.get_source(source_id)
            updated = search_service.store.update_source(source_id, payload)
            if (
                "confirmed_origin" in payload
                and previous
                and previous.get("confirmed_origin") != updated.get("confirmed_origin")
            ):
                search_service.vault.delete(source_id)
            return jsonify({"success": True, "source": updated})
        except KeyError:
            return _json_error("来源不存在。", 404)
        except ValueError as exc:
            return _json_error(str(exc), 400)

    @blueprint.post("/api/book-search/sources/soushuba/discover")
    def discover_soushuba_route():
        try:
            return jsonify({"success": True, "candidates": search_service.discover_soushuba_candidates()})
        except Exception:
            return _json_error("暂时无法查找最新地址，请检查发布页或确认 SearXNG 已运行。", 503)

    @blueprint.route("/api/book-search/sources/<source_id>/credentials", methods=["PUT", "DELETE"])
    def source_credentials_route(source_id: str):
        if not _is_local_credential_request():
            return _json_error("账号只能在运行声阅的本机上配置。", 403)
        source = search_service.store.get_source(source_id)
        if not source:
            return _json_error("来源不存在。", 404)
        if not source["credential_supported"]:
            return _json_error("该来源不使用账号登录。", 409)
        try:
            if request.method == "DELETE":
                search_service.vault.delete(source_id)
                return jsonify({"success": True, "credential_configured": False})
            payload = request.get_json(silent=True) or {}
            search_service.vault.write(source_id, str(payload.get("username") or ""), str(payload.get("password") or ""))
            return jsonify({"success": True, "credential_configured": True})
        except (RuntimeError, ValueError) as exc:
            return _json_error(str(exc), 400)

    return blueprint
