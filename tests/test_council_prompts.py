"""Tests for council prompt construction and guardrails."""

import sys
from types import SimpleNamespace

if "dotenv" not in sys.modules:
    class _DotenvStub:
        @staticmethod
        def load_dotenv(*_, **__):
            return None

    sys.modules["dotenv"] = SimpleNamespace(load_dotenv=_DotenvStub.load_dotenv)

from backend import council


def test_stage1_system_prompt_discourages_cutoff_disclaimers() -> None:
    messages = council._build_stage1_messages("What is new in AI?", context_items=[])

    system_msg = messages[0]["content"]

    assert "do not claim" in system_msg.lower()
    assert "knowledge cutoff" in system_msg.lower()
    assert "lack browsing" in system_msg.lower()


def test_stage1_prompt_includes_context_block_when_available() -> None:
    context_items = [
        {
            "title": "Fresh News",
            "source": "NewsAPI",
            "summary": "Summary text",
            "content": "Full text",
            "published_at": "2024-12-01 00:00 UTC",
            "url": "https://example.com/fresh",
        }
    ]

    messages = council._build_stage1_messages("Tell me", context_items=context_items)

    assert "CONTEXT:" in messages[1]["content"]
    assert "Fresh News" in messages[1]["content"]
