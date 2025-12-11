"""Unit tests for retrieval helpers and aggregation."""

import asyncio
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase, mock

if "feedparser" not in sys.modules:
    class _FeedParserStub:
        @staticmethod
        def parse(data: bytes):
            root = ET.fromstring(data)
            channel = root.find("channel")
            feed_title = channel.findtext("title") if channel is not None else None
            entries = []
            for item in root.findall("channel/item"):
                entry = {
                    "title": item.findtext("title"),
                    "summary": item.findtext("description"),
                    "link": item.findtext("link"),
                    "published": item.findtext("pubDate"),
                }
                entries.append(entry)
            return SimpleNamespace(feed={"title": feed_title}, entries=entries, bozo=False)

    sys.modules["feedparser"] = _FeedParserStub()

if "httpx" not in sys.modules:
    class _DummyResponse:
        def __init__(self):
            self.status_code = 200
            self.content = b""
            self.text = ""

        def json(self):
            return {}

        def raise_for_status(self):
            return None

    class _AsyncClient:
        def __init__(self, *_, **__):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *_, **__):
            return _DummyResponse()

    sys.modules["httpx"] = SimpleNamespace(AsyncClient=_AsyncClient)

if "dotenv" not in sys.modules:
    class _DotenvStub:
        @staticmethod
        def load_dotenv(*_, **__):
            return None

    sys.modules["dotenv"] = SimpleNamespace(load_dotenv=_DotenvStub.load_dotenv)

from backend import retrieval


class SemanticScholarParsingTests(TestCase):
    def test_filters_and_formats_semantic_scholar_results(self) -> None:
        recent_date = (datetime.now(timezone.utc) - timedelta(days=5)).date().isoformat()
        old_date = "2010-01-01"
        payload = {
            "data": [
                {
                    "title": "Recent Paper",
                    "abstract": "A modern discovery",
                    "url": "https://example.org/recent",
                    "venue": "ICLR",
                    "publicationDate": recent_date,
                    "authors": [{"name": "Alice"}],
                },
                {
                    "title": "Old Paper",
                    "url": "https://example.org/old",
                    "publicationDate": old_date,
                },
            ]
        }

        results = retrieval._parse_semantic_scholar_payload(payload, 5, 365)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["provider"], "semantic_scholar")
        self.assertEqual(results[0]["source"], "ICLR")
        self.assertEqual(results[0]["metadata"]["authors"], ["Alice"])
        self.assertIn("UTC", results[0]["published_at"])


class CrossrefParsingTests(TestCase):
    def test_crossref_parsing_respects_date_filter(self) -> None:
        today = datetime.now(timezone.utc).date()
        payload = {
            "message": {
                "items": [
                    {
                        "title": ["Graph Advances"],
                        "abstract": "<p>Concise summary</p>",
                        "URL": "https://doi.org/10.1000/xyz",
                        "DOI": "10.1000/xyz",
                        "container-title": ["JMLR"],
                        "published-online": {
                            "date-parts": [[today.year, today.month, today.day]]
                        },
                    },
                    {
                        "title": ["Outdated Work"],
                        "URL": "https://doi.org/10.1000/old",
                        "DOI": "10.1000/old",
                        "published-print": {"date-parts": [[2005, 1, 1]]},
                    },
                ]
            }
        }

        results = retrieval._parse_crossref_payload(payload, 5, 365)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["provider"], "crossref")
        self.assertEqual(results[0]["source"], "JMLR")
        self.assertEqual(results[0]["metadata"]["doi"], "10.1000/xyz")
        self.assertEqual(results[0]["content"], "Concise summary")


class ProceedingsParsingTests(TestCase):
    def test_proceedings_feed_parsing_filters_stale_items(self) -> None:
        recent_pubdate = (
            datetime.now(timezone.utc) - timedelta(days=30)
        ).strftime("%a, %d %b %Y %H:%M:%S GMT")
        feed = f"""
            <rss version="2.0">
              <channel>
                <title>NeurIPS</title>
                <item>
                  <title>Fresh Paper</title>
                  <link>https://neurips.cc/fresh</link>
                  <pubDate>{recent_pubdate}</pubDate>
                  <description>Recent findings</description>
                </item>
                <item>
                  <title>Archive</title>
                  <link>https://neurips.cc/old</link>
                  <pubDate>Mon, 01 Jan 2010 00:00:00 GMT</pubDate>
                  <description>Old news</description>
                </item>
              </channel>
            </rss>
        """.encode()

        results = retrieval._parse_proceedings_feed(
            feed, "https://neurips.cc/rss", "neurips", 400
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["provider"], "neurips")
        self.assertEqual(results[0]["source"], "NeurIPS")
        self.assertEqual(results[0]["title"], "Fresh Paper")


class AggregationTests(IsolatedAsyncioTestCase):
    async def test_fetch_context_items_aggregates_new_sources(self) -> None:
        base_item = retrieval._build_context_item(
            provider="rss",
            source="Feed",
            title="Duplicate",
            summary="same link",
            url="https://example.org/dup",
            published_at="2024-01-01 00:00 UTC",
            content="",
        )
        newer_item = retrieval._build_context_item(
            provider="semantic_scholar",
            source="ICLR",
            title="Duplicate",
            summary="newer",
            url="https://example.org/dup",
            published_at="2024-02-01 00:00 UTC",
            content="",
        )

        with mock.patch(
            "backend.retrieval.fetch_news_articles",
            new_callable=mock.AsyncMock,
            return_value=[base_item],
        ):
            with mock.patch(
                "backend.retrieval.fetch_arxiv_papers",
                new_callable=mock.AsyncMock,
                return_value=[],
            ):
                with mock.patch(
                    "backend.retrieval.fetch_github_releases",
                    new_callable=mock.AsyncMock,
                    return_value=[],
                ):
                    with mock.patch(
                        "backend.retrieval.fetch_rss_articles",
                        new_callable=mock.AsyncMock,
                        return_value=[],
                    ):
                        with mock.patch(
                            "backend.retrieval.fetch_semantic_scholar_papers",
                            new_callable=mock.AsyncMock,
                            return_value=[newer_item],
                        ):
                            with mock.patch(
                                "backend.retrieval.fetch_crossref_works",
                                new_callable=mock.AsyncMock,
                                return_value=[],
                            ):
                                with mock.patch(
                                    "backend.retrieval.fetch_conference_proceedings",
                                    new_callable=mock.AsyncMock,
                                    return_value=[],
                                ):
                                    results = await retrieval.fetch_context_items("test", limit=5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["provider"], "semantic_scholar")
        self.assertEqual(results[0]["url"], "https://example.org/dup")
