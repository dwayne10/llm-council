"""Pytest configuration for test helpers."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET

# Ensure project root is available for imports when running tests directly or via pytest
PROJECT_ROOT = Path(__file__).resolve().parent.parent
project_root_str = str(PROJECT_ROOT)
if project_root_str not in sys.path:
    sys.path.insert(0, project_root_str)

# Lightweight stubs for optional dependencies during tests
if "dotenv" not in sys.modules:
    class _DotenvStub:
        @staticmethod
        def load_dotenv(*_, **__):
            return None

    sys.modules["dotenv"] = SimpleNamespace(load_dotenv=_DotenvStub.load_dotenv)

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

        async def post(self, *_, **__):
            return _DummyResponse()

    sys.modules["httpx"] = SimpleNamespace(AsyncClient=_AsyncClient)

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
