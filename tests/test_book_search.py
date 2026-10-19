from __future__ import annotations

import base64
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask
import requests

from src.book_search import (
    BookSearchService,
    DirectHtmlAdapter,
    GoogleBooksAdapter,
    GutenbergOpdsAdapter,
    GutendexAdapter,
    ManualLoginRequired,
    OpenLibraryAdapter,
    SearxAdapter,
    SearchJob,
    SoushubaAdapter,
    SourceCircuitBreaker,
    create_book_search_blueprint,
    merge_results,
    normalize_isbn,
    normalize_offer,
    validate_public_url,
)
from src.cloud_bridge import CloudBridge, _path_contains_local_credentials


class FakeVault:
    def __init__(self) -> None:
        self.values: dict[str, dict[str, str]] = {}

    def has(self, source_id: str) -> bool:
        return source_id in self.values

    def read(self, source_id: str):
        return self.values.get(source_id)

    def write(self, source_id: str, username: str, password: str) -> None:
        if not username or not password:
            raise ValueError("账号和密码都不能为空。")
        self.values[source_id] = {"username": username, "password": password}

    def delete(self, source_id: str) -> None:
        self.values.pop(source_id, None)


class FakeResponse:
    def __init__(self, payload, *, status_code: int = 200, text: str = "", headers=None, url: str = "") -> None:
        self._payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 400
        self.text = text
        self.headers = dict(headers or {})
        self.url = url

    @property
    def is_redirect(self) -> bool:
        return self.status_code in {301, 302, 303, 307, 308} and "Location" in self.headers

    @property
    def is_permanent_redirect(self) -> bool:
        return self.status_code in {301, 308} and "Location" in self.headers

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        if not self.ok:
            response = requests.Response()
            response.status_code = self.status_code
            raise requests.HTTPError(response=response)


class FixtureSession:
    def __init__(self, responses: list[FakeResponse] | None = None) -> None:
        self.responses = list(responses or [])
        self.headers: dict[str, str] = {}
        self.calls: list[tuple[tuple, dict]] = []
        self.post_calls: list[tuple[tuple, dict]] = []

    def get(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if not self.responses:
            raise requests.ConnectionError("fixture exhausted")
        response = self.responses.pop(0)
        if not response.url and args:
            response.url = str(args[0])
        return response

    def post(self, *args, **kwargs):
        self.post_calls.append((args, kwargs))
        if not self.responses:
            raise requests.ConnectionError("fixture exhausted")
        response = self.responses.pop(0)
        if not response.url and args:
            response.url = str(args[0])
        return response


class FixtureAdapter:
    def search(self, query, page, source, credentials=None):
        if source["id"] == "open-library":
            raise requests.Timeout("fixture timeout")
        return [
            {
                "title": "三体",
                "authors": ["刘慈欣"],
                "description": f"{source['name']} 的公开书目信息",
                "url": f"https://example.com/{source['id']}/three-body",
                "isbns": ["9787536692930"],
                "access": "unknown",
                "rank": 1,
            }
        ]


class BookSearchTests(unittest.TestCase):
    @patch("src.book_search.socket.getaddrinfo")
    def test_import_public_text_revalidates_and_strips_gutenberg_wrapper(self, getaddrinfo) -> None:
        getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
        body = (
            "Project Gutenberg metadata\n"
            "*** START OF THE PROJECT GUTENBERG EBOOK ALICE ***\n"
            + ("Alice followed the white rabbit into Wonderland.\n" * 8)
            + "*** END OF THE PROJECT GUTENBERG EBOOK ALICE ***\nFooter"
        )
        session = FixtureSession([FakeResponse({}, text=body, headers={"Content-Type": "text/plain; charset=utf-8"})])
        with tempfile.TemporaryDirectory() as temp_dir:
            service = BookSearchService(Path(temp_dir), session=session, vault=FakeVault())
            source = service.store.get_source("project-gutenberg")
            offer = normalize_offer({
                "title": "Alice's Adventures in Wonderland",
                "authors": ["Lewis Carroll"],
                "url": "https://www.gutenberg.org/ebooks/11",
                "access": "public",
                "download_url": "https://www.gutenberg.org/ebooks/11.txt.utf-8",
                "download_format": "TXT",
                "importable": True,
                "license": "美国公版（请核对所在地版权）",
            }, source, "Alice")
            group = merge_results([offer], "Alice")[0]
            service.jobs["job-public"] = SearchJob(
                "job-public", "Alice", 1, True, "2026-08-04T00:00:00+00:00",
                "completed", {}, [offer], [group], "2026-08-04T00:00:01+00:00",
            )

            imported = service.import_public_text("job-public", group["id"])

        self.assertEqual("Alice's Adventures in Wonderland", imported["title"])
        self.assertIn("white rabbit", imported["text"])
        self.assertNotIn("START OF THE PROJECT", imported["text"])
        self.assertNotIn("Footer", imported["text"])

    def test_import_rejects_free_but_unlicensed_soushuba_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = BookSearchService(Path(temp_dir), session=FixtureSession(), vault=FakeVault())
            group = {
                "id": "protected-book",
                "title": "版权未知小说",
                "authors": [],
                "offers": [{
                    "source_id": "soushuba",
                    "source_name": "搜书吧",
                    "url": "https://example.com/thread/1",
                    "access": "public",
                    "download_url": "https://example.com/free.txt",
                    "download_format": "TXT",
                    "importable": True,
                    "license": "",
                }],
            }
            service.jobs["job-protected"] = SearchJob(
                "job-protected", "版权未知小说", 1, True, "2026-08-04T00:00:00+00:00",
                "completed", {}, [], [group], "2026-08-04T00:00:01+00:00",
            )

            with self.assertRaisesRegex(ValueError, "没有可自动导入"):
                service.import_public_text("job-protected", "protected-book")

    def test_searx_fixed_json_keeps_only_the_requested_domain(self) -> None:
        adapter = SearxAdapter(FixtureSession([FakeResponse({"results": [
            {"title": "庆余年", "url": "https://www.qidian.com/book/1010191960", "content": "猫腻作品"},
            {"title": "无关结果", "url": "https://unrelated.example/book/1"},
        ]})]), "http://127.0.0.1:8888")
        results = adapter.search("庆余年", 1, {"id": "qidian", "name": "起点中文网", "domain": "qidian.com"})

        self.assertEqual(1, len(results))
        self.assertEqual("庆余年", results[0]["title"])

    @patch("src.book_search.socket.getaddrinfo")
    def test_chinese_site_adapter_parses_fixed_html_without_scripts(self, getaddrinfo) -> None:
        getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
        html = """
        <article class="book-item">
          <a href="/book/1031940621" title="宿命之环">宿命之环</a>
          <span class="author">爱潜水的乌贼</span>
          <p class="intro">诡秘世界的全新故事。</p>
          <img data-src="/covers/circle.jpg">
        </article>
        """
        adapter = DirectHtmlAdapter(FixtureSession([FakeResponse({}, text=html)]))
        result = adapter.search("宿命之环", 1, {
            "id": "qidian",
            "search_url_template": "https://www.qidian.com/search?kw={query}",
        })[0]

        self.assertEqual("宿命之环", result["title"])
        self.assertEqual(["爱潜水的乌贼"], result["authors"])
        self.assertEqual("https://www.qidian.com/book/1031940621", result["url"])
        self.assertEqual("https://www.qidian.com/covers/circle.jpg", result["cover_url"])

    @patch("src.book_search.socket.getaddrinfo")
    def test_soushuba_adapter_uses_normal_login_and_parses_search_metadata(self, getaddrinfo) -> None:
        getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
        login_form = """
        <form id="lsform" action="member.php?mod=logging&amp;action=login&amp;loginsubmit=yes&amp;inajax=1">
          <input type="hidden" name="formhash" value="abc123">
          <input name="username"><input type="password" name="password">
        </form>
        """
        logged_in_home = '<a href="home.php?mod=space">reader</a><a href="member.php?action=logout">退出</a>'
        search_form = """
        <form id="scform" action="search.php?mod=forum" method="post">
          <input type="text" name="srchtxt"><input type="hidden" name="searchsubmit" value="yes">
        </form>
        """
        results_html = """
        <ul>
          <li class="pbw">
            <h3><a href="forum.php?mod=viewthread&amp;tid=326474&amp;highlight=x">我的堕落故事（01-43）作者：辣妈人妻/长腿辣妈</a></h3>
            <p>12 个回复 - 2883 次查看</p><p>仅保留搜索结果摘要。</p>
            <p>2020-9-30 00:00 - lance98765 - 2019-2020存档</p>
          </li>
          <li class="pbw">
            <h3><a href="forum.php?mod=viewthread&amp;tid=190866&amp;highlight=x">有声系列之《我的堕落经历》(第1集 共3集)小窈</a></h3>
            <p>9 个回复 - 642 次查看</p><p>请使用解压软件。</p>
            <p>2018-12-4 23:31 - kongkongja - 有声小说</p>
          </li>
        </ul>
        """
        broad_results_html = '<h2>找到 “堕落” 相关内容 400 个</h2>' + results_html
        session = FixtureSession([
            FakeResponse({}, text=login_form, url="https://books.example/"),
            FakeResponse({}, text="login ok", url="https://books.example/member.php?mod=logging"),
            FakeResponse({}, text=logged_in_home, url="https://books.example/"),
            FakeResponse({}, text=search_form, url="https://books.example/search.php?mod=forum"),
            FakeResponse({}, status_code=302, headers={"Location": "/search.php?mod=forum&searchid=1"}),
            FakeResponse({}, text=results_html, url="https://books.example/search.php?mod=forum&searchid=1"),
            FakeResponse({}, text=search_form, url="https://books.example/search.php?mod=forum"),
            FakeResponse({}, status_code=302, headers={"Location": "/search.php?mod=forum&searchid=2"}),
            FakeResponse({}, text=broad_results_html, url="https://books.example/search.php?mod=forum&searchid=2"),
        ])
        adapter = SoushubaAdapter(session)

        results = adapter.search(
            "我的堕落",
            1,
            {"confirmed_origin": "https://books.example"},
            {"username": "reader", "password": "secret"},
        )

        self.assertEqual(2, len(results))
        self.assertEqual(["辣妈人妻/长腿辣妈"], results[0]["authors"])
        self.assertEqual("login_required", results[0]["access"])
        self.assertFalse(results[0]["importable"])
        self.assertEqual("2020-9-30 00:00", results[0]["updated_at"])
        self.assertEqual("secret", session.post_calls[0][1]["data"]["password"])
        self.assertEqual("我的堕落".encode("gb18030"), session.post_calls[1][1]["data"]["srchtxt"])
        self.assertEqual("堕落".encode("gb18030"), session.post_calls[2][1]["data"]["srchtxt"])
        self.assertEqual(400, results[0]["source_total"])

    @patch("src.book_search.socket.getaddrinfo")
    def test_soushuba_adapter_never_posts_credentials_to_a_changed_origin(self, getaddrinfo) -> None:
        getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
        session = FixtureSession([FakeResponse({}, text="""
          <form id="lsform" action="https://evil.example/login">
            <input name="username"><input type="password" name="password">
          </form>
        """)])

        with self.assertRaisesRegex(ValueError, "离开了已确认域名"):
            SoushubaAdapter(session).search(
                "测试",
                1,
                {"confirmed_origin": "https://books.example"},
                {"username": "reader", "password": "secret"},
            )

        self.assertEqual([], session.post_calls)

    @patch("src.book_search.socket.getaddrinfo")
    def test_soushuba_adapter_requires_local_credentials(self, getaddrinfo) -> None:
        getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
        with self.assertRaisesRegex(ManualLoginRequired, "需要账号"):
            SoushubaAdapter(FixtureSession()).search(
                "测试", 1, {"confirmed_origin": "https://books.example"}, None
            )

    @patch("src.book_search.socket.getaddrinfo")
    def test_soushuba_release_page_discovers_https_mirror_without_credentials(self, getaddrinfo) -> None:
        getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
        release_html = """
        <h1>搜书吧</h1>
        <a href="https://books.example/">最新地址</a>
        <h2>永久地址</h2><p>www.soushu2030.com</p>
        """
        mirror_html = """
        <title>搜书吧-网络小说交流论坛</title>
        <h1>搜书吧</h1>
        <form action="search.php?mod=forum"><input name="srchtxt"></form>
        """
        session = FixtureSession([
            FakeResponse({}, status_code=404, text=release_html),
            FakeResponse({}, text=mirror_html),
        ])
        with tempfile.TemporaryDirectory() as temporary_root:
            service = BookSearchService(Path(temporary_root), session=session, vault=FakeVault())
            source = service.store.update_source("soushuba", {
                "release_url": "http://release.example:2228/o/?sigin=public-link",
            })

            candidates = service.discover_soushuba_candidates()

        self.assertEqual("http://release.example:2228/o/?sigin=public-link", source["release_url"])
        self.assertEqual("https://books.example", candidates[0]["origin"])
        self.assertTrue(candidates[0]["verified"])
        self.assertEqual("release_page", candidates[0]["discovered_via"])
        self.assertEqual([], session.post_calls)

    def test_google_books_and_open_library_parse_fixed_json(self) -> None:
        google = GoogleBooksAdapter(
            FixtureSession([FakeResponse({"items": [{
                "id": "g1",
                "volumeInfo": {
                    "title": "活着",
                    "subtitle": "一部长篇小说",
                    "authors": ["余华"],
                    "industryIdentifiers": [{"identifier": "9787506365437"}],
                    "infoLink": "https://books.google.com/books?id=g1",
                    "canonicalVolumeLink": "https://books.google.com/books/about/活着.html?id=g1",
                    "imageLinks": {"thumbnail": "http://books.google.com/cover?id=g1&edge=curl"},
                },
                "accessInfo": {"publicDomain": False},
                "saleInfo": {"saleability": "FOR_SALE"},
            }]})])
        )
        open_library = OpenLibraryAdapter(
            FixtureSession([FakeResponse({"docs": [{
                "key": "/works/OL1W",
                "title": "活着",
                "author_name": ["余华"],
                "isbn": ["9787506365437"],
                "public_scan_b": True,
            }]})])
        )

        google_result = google.search("活着", 1, {})[0]
        open_result = open_library.search("活着", 1, {})[0]
        self.assertEqual("paid", google_result["access"])
        self.assertEqual("活着: 一部长篇小说", google_result["title"])
        self.assertEqual("https://books.google.com/books/about/活着.html?id=g1", google_result["url"])
        self.assertEqual("https://books.google.com/cover?id=g1", google_result["cover_url"])
        self.assertEqual("public", open_result["access"])
        self.assertEqual("https://openlibrary.org/works/OL1W", open_result["url"])

    def test_google_books_exposes_only_confirmed_public_downloads(self) -> None:
        adapter = GoogleBooksAdapter(FixtureSession([FakeResponse({"items": [{
            "id": "public-1",
            "volumeInfo": {"title": "Public Book", "infoLink": "https://books.google.com/books?id=public-1"},
            "accessInfo": {
                "publicDomain": True,
                "epub": {"isAvailable": True, "downloadLink": "https://books.google.com/books/download?id=public-1"},
            },
            "saleInfo": {"saleability": "NOT_FOR_SALE"},
        }]} )]))

        result = adapter.search("Public Book", 1, {})[0]

        self.assertEqual("public", result["access"])
        self.assertEqual("https://books.google.com/books/download?id=public-1", result["download_url"])
        self.assertEqual("EPUB", result["download_format"])

    def test_open_library_uses_detailed_isbn_lookup(self) -> None:
        session = FixtureSession([FakeResponse({
            "ISBN:0553103547": {
                "title": "A Game of Thrones",
                "subtitle": "A Song of Ice and Fire",
                "authors": [{"name": "George R. R. Martin"}],
                "publish_date": "August 1996",
                "url": "https://openlibrary.org/books/OL123M/A_Game_of_Thrones",
                "cover": {"large": "https://covers.openlibrary.org/b/id/123-L.jpg"},
                "identifiers": {"isbn_10": ["0553103547"], "isbn_13": ["9780553103540"]},
                "subjects": [{"name": "Fantasy"}, {"name": "fantasy"}, {"name": "Kings and rulers"}],
            }
        })])
        adapter = OpenLibraryAdapter(session)

        result = adapter.search("0553103547", 1, {})[0]

        self.assertEqual("A Game of Thrones: A Song of Ice and Fire", result["title"])
        self.assertEqual(["George R. R. Martin"], result["authors"])
        self.assertEqual("Fantasy；Kings and rulers", result["description"])
        self.assertEqual("9780553103540", result["isbns"][0])
        self.assertEqual("ISBN:0553103547", session.calls[0][1]["params"]["bibkeys"])

    def test_gutendex_returns_only_confirmed_public_domain_books(self) -> None:
        adapter = GutendexAdapter(FixtureSession([FakeResponse({"results": [
            {
                "id": 11,
                "title": "Alice's Adventures in Wonderland\r\nA children's classic",
                "authors": [{"name": "Carroll, Lewis"}],
                "summaries": ["Alice follows a white rabbit."],
                "subjects": ["Fantasy fiction"],
                "copyright": False,
                "formats": {
                    "image/jpeg": "https://www.gutenberg.org/cache/epub/11/pg11.cover.medium.jpg",
                    "text/plain; charset=utf-8": "https://www.gutenberg.org/ebooks/11.txt.utf-8",
                },
            },
            {
                "id": 999,
                "title": "Still copyrighted",
                "authors": [],
                "copyright": True,
                "formats": {},
            },
        ]})]))

        results = adapter.search("alice", 1, {})

        self.assertEqual(1, len(results))
        self.assertEqual("public", results[0]["access"])
        self.assertTrue(results[0]["importable"])
        self.assertEqual(
            "Alice's Adventures in Wonderland: A children's classic",
            results[0]["title"],
        )
        self.assertEqual("https://www.gutenberg.org/ebooks/11", results[0]["url"])
        self.assertEqual("https://www.gutenberg.org/ebooks/11.txt.utf-8", results[0]["download_url"])
        self.assertEqual("TXT", results[0]["download_format"])
        self.assertIn("公版", results[0]["license"])

    def test_project_gutenberg_opds_fallback_skips_navigation_entries(self) -> None:
        xml = """<?xml version="1.0" encoding="utf-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <id>https://www.gutenberg.org/ebooks/subjects/search.opds/?query=alice</id>
            <title>Subjects</title>
            <content type="text">2 subject headings match your search.</content>
          </entry>
          <entry>
            <id>https://www.gutenberg.org/ebooks/11.opds</id>
            <updated>2026-08-04T00:00:00Z</updated>
            <title>Alice's Adventures in Wonderland</title>
            <content type="text">Lewis Carroll</content>
            <link rel="subsection" href="/ebooks/11.opds" />
          </entry>
        </feed>"""
        adapter = GutenbergOpdsAdapter(FixtureSession([FakeResponse({}, text=xml)]))

        results = adapter.search("alice", 1, {})

        self.assertEqual(1, len(results))
        self.assertEqual(["Lewis Carroll"], results[0]["authors"])
        self.assertEqual("https://www.gutenberg.org/ebooks/11", results[0]["url"])
        self.assertTrue(results[0]["importable"])
        self.assertEqual("https://www.gutenberg.org/cache/epub/11/pg11.txt", results[0]["download_url"])
        self.assertEqual("TXT", results[0]["download_format"])

    def test_protected_offer_cannot_smuggle_a_direct_download_link(self) -> None:
        source = {"id": "protected", "name": "受限站", "mature": False, "book_type": "网络小说"}
        offer = normalize_offer({
            "title": "受限作品",
            "url": "https://books.example/item/1",
            "download_url": "https://books.example/private.txt",
            "download_format": "TXT",
            "access": "login_required",
            "importable": True,
        }, source, "受限作品")

        self.assertIsNotNone(offer)
        self.assertEqual("", offer["download_url"])
        self.assertFalse(offer["importable"])

    def test_source_circuit_breaker_suspends_and_recovers(self) -> None:
        breaker = SourceCircuitBreaker(threshold=2, base_cooldown=10, max_cooldown=60)

        self.assertEqual(0, breaker.record_failure("gutendex", "timeout"))
        self.assertFalse(breaker.suspended("gutendex")[0])
        self.assertEqual(10, breaker.record_failure("gutendex", "timeout"))
        suspended, remaining, reason = breaker.suspended("gutendex")
        self.assertTrue(suspended)
        self.assertGreater(remaining, 0)
        self.assertEqual("timeout", reason)

        breaker.record_success("gutendex")
        self.assertFalse(breaker.suspended("gutendex")[0])

    def test_isbn_deduplication_merges_all_source_offers(self) -> None:
        source_a = {"id": "a", "name": "甲站", "mature": False, "book_type": "出版书"}
        source_b = {"id": "b", "name": "乙站", "mature": True, "book_type": "出版书"}
        raw = {
            "title": "三体",
            "authors": ["刘慈欣"],
            "url": "https://example.com/book",
            "isbns": ["9787536692930"],
            "rank": 1,
        }
        offers = [normalize_offer(raw, source_a, "三体"), normalize_offer({**raw, "url": "https://example.org/book"}, source_b, "三体")]
        groups = merge_results([item for item in offers if item], "三体")

        self.assertEqual(1, len(groups))
        self.assertEqual(2, groups[0]["source_count"])
        self.assertTrue(groups[0]["mature"])
        self.assertEqual({"a", "b"}, {offer["source_id"] for offer in groups[0]["offers"]})

    def test_isbn10_and_isbn13_forms_merge_as_the_same_edition(self) -> None:
        source_a = {"id": "a", "name": "甲站", "mature": False, "book_type": "出版书"}
        source_b = {"id": "b", "name": "乙站", "mature": False, "book_type": "出版书"}
        isbn10 = normalize_offer({
            "title": "A Game of Thrones",
            "authors": ["George R. R. Martin"],
            "url": "https://example.com/isbn10",
            "isbns": ["0553103547"],
        }, source_a, "0553103547")
        isbn13 = normalize_offer({
            "title": "A Game of Thrones",
            "authors": ["George R. R. Martin"],
            "url": "https://example.org/isbn13",
            "isbns": ["9780553103540"],
        }, source_b, "0553103547")

        groups = merge_results([item for item in (isbn10, isbn13) if item], "0553103547")

        self.assertEqual("9780553103540", normalize_isbn("ISBN: 978-0-553-10354-0"))
        self.assertEqual("9780553103540", normalize_isbn("urn:isbn:9780553103540"))
        self.assertEqual(1, len(groups))
        self.assertEqual(2, groups[0]["source_count"])

    def test_simplified_and_traditional_titles_merge_without_isbn(self) -> None:
        source_a = {"id": "a", "name": "甲站", "mature": False, "book_type": "出版书"}
        source_b = {"id": "b", "name": "乙站", "mature": False, "book_type": "出版书"}
        simplified = normalize_offer({"title": "三体", "authors": ["刘慈欣"], "url": "https://example.com/a"}, source_a, "三体")
        traditional = normalize_offer({"title": "三體", "authors": ["劉慈欣"], "url": "https://example.org/b"}, source_b, "三体")

        groups = merge_results([item for item in (simplified, traditional) if item], "三体")
        self.assertEqual(1, len(groups))
        self.assertEqual(2, groups[0]["source_count"])

    def test_job_returns_partial_results_when_one_source_times_out(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            service = BookSearchService(
                Path(temporary_root),
                session=FixtureSession(),
                vault=FakeVault(),
                adapter_factory=lambda _source: FixtureAdapter(),
            )
            started = service.start_job("三体", source_ids=["google-books", "open-library"])
            deadline = time.monotonic() + 3
            snapshot = started
            while snapshot["status"] in {"queued", "running"} and time.monotonic() < deadline:
                time.sleep(0.02)
                snapshot = service.job_snapshot(started["id"]) or snapshot

            self.assertEqual("completed", snapshot["status"])
            self.assertEqual(1, snapshot["result_count"])
            states = {state["id"]: state["status"] for state in snapshot["sources"]}
            self.assertEqual("success", states["google-books"])
            self.assertEqual("timeout", states["open-library"])

    def test_favorites_store_only_sanitized_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            service = BookSearchService(Path(temporary_root), session=FixtureSession(), vault=FakeVault())
            favorite = service.store.save_favorite({
                "id": "book-1",
                "title": "<b>围城</b>",
                "authors": ["钱钟书"],
                "offers": [{
                    "title": "围城",
                    "source_id": "demo",
                    "source_name": "示例站",
                    "url": "https://example.com/book",
                    "protected_text": "不应保存的正文",
                }],
                "protected_text": "不应保存的正文",
            })
            self.assertEqual("围城", favorite["title"])
            self.assertNotIn("protected_text", favorite)
            self.assertNotIn("protected_text", favorite["offers"][0])

    def test_recent_history_keeps_the_latest_copy_of_each_query(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            service = BookSearchService(Path(temporary_root), session=FixtureSession(), vault=FakeVault())
            service.store.add_history("三体", {"page": 1})
            service.store.add_history("三体", {"page": 2})

            history = service.store.list_history()
            self.assertEqual(1, len(history))
            self.assertEqual(2, history[0]["filters"]["page"])

    @patch("src.book_search.socket.getaddrinfo")
    def test_custom_source_url_validation_blocks_private_dns(self, getaddrinfo) -> None:
        getaddrinfo.return_value = [(2, 1, 6, "", ("127.0.0.1", 443))]
        with self.assertRaisesRegex(ValueError, "内网"):
            validate_public_url("https://books.example/", require_https=True)

    @patch("src.book_search.socket.getaddrinfo")
    def test_nonstandard_port_is_allowed_only_for_explicit_release_page(self, getaddrinfo) -> None:
        getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 2228))]
        release_url = "http://release.example:2228/o/"

        with self.assertRaisesRegex(ValueError, "非标准端口"):
            validate_public_url(release_url)
        self.assertEqual(
            release_url,
            validate_public_url(release_url, allow_nonstandard_port=True),
        )

    @patch("src.book_search.socket.getaddrinfo")
    def test_custom_public_http_source_is_allowed_but_cannot_store_credentials(self, getaddrinfo) -> None:
        getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 80))]
        with tempfile.TemporaryDirectory() as temporary_root:
            service = BookSearchService(Path(temporary_root), session=FixtureSession(), vault=FakeVault())
            source = service.store.create_source({
                "name": "公开书目站",
                "domain": "books.example",
                "search_url_template": "http://books.example/search?q={query}",
            })

            self.assertEqual("http://books.example/", source["homepage_url"])
            self.assertFalse(source["credential_supported"])

    def test_credentials_route_is_local_only_and_never_reads_passwords(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            vault = FakeVault()
            service = BookSearchService(Path(temporary_root), session=FixtureSession(), vault=vault)
            app = Flask(__name__)
            app.config.update(TESTING=True)
            app.register_blueprint(create_book_search_blueprint(service=service, name="book_search_tests"))
            client = app.test_client()
            url = "/api/book-search/sources/qidian/credentials"

            blocked = client.put(url, headers={"X-ShengYue-Bridge-Request": "1"}, json={"username": "u", "password": "secret"})
            cross_site = client.put(url, headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"}, json={"username": "u", "password": "secret"})
            saved = client.put(url, json={"username": "u", "password": "secret"})
            sources = client.get("/api/book-search/sources").get_json()["sources"]

            self.assertEqual(403, blocked.status_code)
            self.assertEqual(403, cross_site.status_code)
            self.assertEqual(200, saved.status_code)
            self.assertTrue(next(item for item in sources if item["id"] == "qidian")["credential_configured"])
            self.assertNotIn("secret", str(sources))

    def test_cloud_bridge_always_blocks_credential_endpoint(self) -> None:
        self.assertTrue(_path_contains_local_credentials("/api/book-search/sources/qidian/credentials"))
        self.assertFalse(_path_contains_local_credentials("/api/book-search/sources"))

    def test_malicious_result_urls_are_removed_before_the_frontend(self) -> None:
        source = {"id": "web", "name": "全网", "mature": False, "book_type": "图书"}
        self.assertIsNone(normalize_offer({"title": "坏结果", "url": "javascript:alert(1)"}, source, "坏结果"))
        self.assertIsNone(normalize_offer({"title": "内网结果", "url": "http://127.0.0.1/admin"}, source, "内网结果"))

    @patch("src.cloud_bridge.requests.request")
    def test_cloud_bridge_strips_spoofed_headers_and_marks_forwarded_requests(self, outbound) -> None:
        class RelayResponse:
            status_code = 200
            headers = {"Content-Type": "application/json"}

            @staticmethod
            def iter_content(chunk_size):
                return [b"{}"]

        outbound.return_value = RelayResponse()
        bridge = CloudBridge("https://relay.example", "secret", "http://127.0.0.1:7860")
        sent = []
        bridge.send = sent.append
        try:
            bridge._handle_request({
                "id": "request-1",
                "path": "/api/book-search/sources",
                "method": "GET",
                "body": base64.b64encode(b"").decode("ascii"),
                "headers": {
                    "Authorization": "Bearer should-not-forward",
                    "X-ShengYue-Bridge-Request": "0",
                },
            })
        finally:
            bridge.stop()

        forwarded_headers = outbound.call_args.kwargs["headers"]
        self.assertNotIn("Authorization", forwarded_headers)
        self.assertEqual("1", forwarded_headers["X-ShengYue-Bridge-Request"])
        self.assertEqual("response_start", sent[0]["type"])


if __name__ == "__main__":
    unittest.main()
