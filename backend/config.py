"""Configuration for the LLM Council."""

import os

from dotenv import load_dotenv

load_dotenv()

# OpenRouter API key
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# Council members - list of OpenRouter model identifiers
COUNCIL_MODELS = [
    "openai/gpt-5.1",
    "google/gemini-3-pro-preview",
    "anthropic/claude-sonnet-4.5",
    "x-ai/grok-4",
]

# Chairman model - synthesizes final response
CHAIRMAN_MODEL = "google/gemini-3-pro-preview"

# OpenRouter API endpoint
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Data directory for conversation storage
DATA_DIR = "data/conversations"

# External news retrieval configuration
NEWSAPI_KEY = "43418ecd27254838878dab5887155323"
NEWSAPI_BASE_URL = "https://newsapi.org/v2"

# Scholarly + technical retrieval configuration
ARXIV_API_URL = "https://export.arxiv.org/api/query"

# GitHub releases (token optional but improves rate limits)
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_API_URL = "https://api.github.com"

# Company/industry RSS feeds (comma-separated env override)
_default_feeds = [
    "https://openai.com/blog/rss/",
    "https://deepmind.google/discover/rss.xml",
    "https://huggingface.co/blog/feed",
]
TECH_RSS_FEEDS = [
    feed.strip()
    for feed in os.getenv("TECH_RSS_FEEDS", ",".join(_default_feeds)).split(",")
    if feed.strip()
]
