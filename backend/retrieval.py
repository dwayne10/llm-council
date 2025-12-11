"""Fetch up-to-date context snippets from multiple external sources."""

from __future__ import annotations

import asyncio
import calendar
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import feedparser
import httpx

from .config import (
    ARXIV_API_URL,
    GITHUB_API_URL,
    GITHUB_TOKEN,
    NEWSAPI_BASE_URL,
    NEWSAPI_KEY,
    TECH_RSS_FEEDS,
)

ContextItem = Dict[str, Any]

RSS_REQUEST_HEADERS = {
    "User-Agent": "llm-council/1.0 (+https://github.com/varbhar/llm-council)",
    "Accept": "application/rss+xml, application/atom+xml;q=0.9, application/xml;q=0.8, */*;q=0.7",
}

PROCEEDINGS_FEEDS = [
    {"provider": "neurips", "url": "https://papers.nips.cc/paper_files/paper/2024/rss"},
    {"provider": "iclr", "url": "https://iclr.cc/virtual/2025/overview/rss"},
    {"provider": "icml", "url": "https://proceedings.mlr.press/rss.xml"},
]

async def fetch_context_items(query: str, limit: int = 8) -> List[ContextItem]:
    """
    Aggregate context snippets from news, arXiv, GitHub, scholarly APIs, and RSS feeds.
    """
    tasks = [
        fetch_news_articles(query, max_results=min(4, limit)),
        fetch_arxiv_papers(query, max_results=3),
        fetch_github_releases(query, max_repos=2),
        fetch_rss_articles(query, max_articles=3),
        fetch_semantic_scholar_papers(query, max_results=3),
        fetch_crossref_works(query, max_results=3),
        fetch_conference_proceedings(max_items=3),
    ]

    chunks = await asyncio.gather(*tasks, return_exceptions=True)

    results: List[ContextItem] = []
    for chunk in chunks:
        if isinstance(chunk, Exception):
            print(f"Context fetch error: {chunk}")
            continue
        results.extend(chunk)

    # Deduplicate by URL while keeping latest timestamps
    deduped: Dict[str, ContextItem] = {}
    for item in results:
        key = item.get("url") or f"{item.get('title')}::{item.get('source')}"
        existing = deduped.get(key)
        if not existing:
            deduped[key] = item
            continue
        if _parse_datetime(item.get("published_at")) > _parse_datetime(
            existing.get("published_at")
        ):
            deduped[key] = item

    sorted_items = sorted(
        deduped.values(),
        key=lambda x: _parse_datetime(x.get("published_at")),
        reverse=True,
    )

    return sorted_items[:limit]


async def fetch_news_articles(
    query: str,
    max_results: int = 3,
    language: str = "en",
) -> List[ContextItem]:
    """Retrieve news articles via NewsAPI."""
    if not NEWSAPI_KEY:
        return []

    params = {
        "q": query,
        "language": language,
        "sortBy": "publishedAt",
        "pageSize": max_results,
    }
    headers = {"X-Api-Key": NEWSAPI_KEY}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{NEWSAPI_BASE_URL}/everything",
                params=params,
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:  # noqa: BLE001
        print(f"News retrieval failed: {exc}")
        return []

    articles = payload.get("articles") or []
    results: List[ContextItem] = []
    for article in articles:
        published_at = _format_timestamp(article.get("publishedAt"))
        results.append(
            _build_context_item(
                provider="newsapi",
                source=(_safe_get(article, "source", "name") or "News article"),
                title=article.get("title"),
                summary=article.get("description"),
                url=article.get("url"),
                published_at=published_at,
                content=article.get("content"),
                extra={"author": article.get("author")},
            )
        )

    return results


async def fetch_arxiv_papers(
    query: str,
    max_results: int = 3,
) -> List[ContextItem]:
    """Fetch recent arXiv papers related to the query."""
    if not query:
        return []

    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    query_string = "&".join(f"{k}={quote_plus(str(v))}" for k, v in params.items())
    url = f"{ARXIV_API_URL}?{query_string}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            feed_xml = response.text
    except Exception as exc:  # noqa: BLE001
        print(f"arXiv retrieval failed: {exc}")
        return []

    return _parse_arxiv_feed(feed_xml)


async def fetch_semantic_scholar_papers(
    query: str,
    max_results: int = 3,
    max_age_days: int = 365,
) -> List[ContextItem]:
    """Search Semantic Scholar for recent Computer Science papers."""
    if not query:
        return []

    params = {
        "query": query,
        "fieldsOfStudy": "Computer Science",
        "sort": "publicationDate:desc",
        "limit": max_results * 2,
        "offset": 0,
        "fields": "title,abstract,url,venue,publicationDate,year,authors",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                params=params,
            )
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:  # noqa: BLE001
        print(f"Semantic Scholar retrieval failed: {exc}")
        return []

    return _parse_semantic_scholar_payload(payload, max_results, max_age_days)


async def fetch_crossref_works(
    query: str,
    max_results: int = 3,
    max_age_days: int = 365,
) -> List[ContextItem]:
    """Fetch recent works metadata from Crossref."""
    if not query:
        return []

    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).date()
    params = {
        "query": query,
        "filter": f"from-pub-date:{cutoff.isoformat()}",
        "sort": "published",
        "order": "desc",
        "rows": max_results * 2,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get("https://api.crossref.org/works", params=params)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:  # noqa: BLE001
        print(f"Crossref retrieval failed: {exc}")
        return []

    return _parse_crossref_payload(payload, max_results, max_age_days)


async def fetch_conference_proceedings(
    max_items: int = 3,
    max_age_days: int = 365,
) -> List[ContextItem]:
    """Fetch the latest NeurIPS/ICLR/ICML proceedings via RSS/JSON endpoints."""
    if not PROCEEDINGS_FEEDS:
        return []

    async with httpx.AsyncClient(timeout=10.0) as client:
        fetch_tasks = [
            client.get(feed["url"], headers=RSS_REQUEST_HEADERS)
            for feed in PROCEEDINGS_FEEDS
        ]
        responses = await asyncio.gather(*fetch_tasks, return_exceptions=True)

    items: List[ContextItem] = []
    for feed_meta, resp in zip(PROCEEDINGS_FEEDS, responses):
        if isinstance(resp, Exception):
            print(f"Proceedings fetch failed for {feed_meta['provider']}: {resp}")
            continue

        try:
            parsed_items = _parse_proceedings_feed(
                resp.content,
                feed_meta["url"],
                feed_meta["provider"],
                max_age_days,
            )
            items.extend(parsed_items)
        except Exception as exc:  # noqa: BLE001
            print(f"Proceedings parse failed for {feed_meta['provider']}: {exc}")
            continue

    sorted_items = sorted(
        items,
        key=lambda x: _parse_datetime(x.get("published_at")),
        reverse=True,
    )
    return sorted_items[:max_items]


async def fetch_github_releases(
    query: str,
    max_repos: int = 2,
) -> List[ContextItem]:
    """Retrieve latest GitHub releases for repositories related to the query."""
    if not query:
        return []

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "llm-council",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    params = {
        "q": query,
        "sort": "updated",
        "order": "desc",
        "per_page": max_repos,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            search_resp = await client.get(
                f"{GITHUB_API_URL}/search/repositories",
                params=params,
                headers=headers,
            )
            search_resp.raise_for_status()
            repos = (search_resp.json().get("items") or [])[:max_repos]

            releases: List[ContextItem] = []
            for repo in repos:
                owner = repo["owner"]["login"]
                name = repo["name"]
                release_url = f"{GITHUB_API_URL}/repos/{owner}/{name}/releases/latest"
                try:
                    release_resp = await client.get(release_url, headers=headers)
                    if release_resp.status_code == 404:
                        continue
                    release_resp.raise_for_status()
                except Exception as release_exc:  # noqa: BLE001
                    print(f"Release fetch failed for {owner}/{name}: {release_exc}")
                    continue

                release = release_resp.json()
                published_at = _format_timestamp(
                    release.get("published_at") or release.get("created_at")
                )
                releases.append(
                    _build_context_item(
                        provider="github",
                        source=f"{owner}/{name}",
                        title=release.get("name") or repo.get("full_name"),
                        summary=release.get("body") or repo.get("description"),
                        url=release.get("html_url") or repo.get("html_url"),
                        published_at=published_at,
                        content=release.get("body"),
                        extra={"tag_name": release.get("tag_name")},
                    )
                )

    except Exception as exc:  # noqa: BLE001
        print(f"GitHub retrieval failed: {exc}")
        return []

    return releases


async def fetch_rss_articles(
    query: str,
    max_articles: int = 3,
) -> List[ContextItem]:
    """Search predefined RSS feeds for posts matching the query."""
    if not TECH_RSS_FEEDS or not query:
        return []

    async with httpx.AsyncClient(timeout=10.0) as client:
        fetch_tasks = [
            client.get(url, headers=RSS_REQUEST_HEADERS) for url in TECH_RSS_FEEDS
        ]
        responses = await asyncio.gather(*fetch_tasks, return_exceptions=True)

    matched_items: List[ContextItem] = []
    query_lower = query.lower()

    for feed_url, resp in zip(TECH_RSS_FEEDS, responses):
        if isinstance(resp, Exception):
            print(f"RSS fetch failed for {feed_url}: {resp}")
            continue

        try:
            items = _parse_rss_feed(resp.content, feed_url)
        except Exception as exc:  # noqa: BLE001
            print(f"RSS parse failed for {feed_url}: {exc}")
            continue

        for item in items:
            haystack = f"{item.get('title', '')} {item.get('summary', '')}".lower()
            if query_lower not in haystack:
                continue
            matched_items.append(item)
            if len(matched_items) >= max_articles:
                break

        if len(matched_items) >= max_articles:
            break

    return matched_items


def _parse_arxiv_feed(feed_xml: str) -> List[ContextItem]:
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(feed_xml)
    entries = root.findall("atom:entry", ns)
    results: List[ContextItem] = []

    for entry in entries:
        title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
        summary = (
            entry.findtext("atom:summary", default="", namespaces=ns) or ""
        ).strip()
        published = entry.findtext("atom:published", default="", namespaces=ns) or ""
        updated = entry.findtext("atom:updated", default="", namespaces=ns) or ""
        link = ""
        for link_el in entry.findall("atom:link", ns):
            if link_el.attrib.get("type") == "text/html":
                link = link_el.attrib.get("href", "")
                break
        authors = [
            (author.findtext("atom:name", default="", namespaces=ns) or "").strip()
            for author in entry.findall("atom:author", ns)
        ]

        published_at = _format_timestamp(updated or published)
        results.append(
            _build_context_item(
                provider="arxiv",
                source="arXiv",
                title=title,
                summary=summary,
                url=link,
                published_at=published_at,
                content=summary,
                extra={"authors": authors},
            )
        )

    return results


def _parse_semantic_scholar_payload(
    payload: Dict[str, Any], max_results: int, max_age_days: int
) -> List[ContextItem]:
    results: List[ContextItem] = []
    now = datetime.now(timezone.utc)
    for paper in payload.get("data") or []:
        raw_date = paper.get("publicationDate") or paper.get("year")
        published_dt = _coerce_datetime(raw_date)
        if published_dt and published_dt < now - timedelta(days=max_age_days):
            continue

        published_at = _format_timestamp(
            published_dt.isoformat() if published_dt else None
        )
        authors = [
            author.get("name")
            for author in paper.get("authors") or []
            if isinstance(author, dict) and author.get("name")
        ]

        results.append(
            _build_context_item(
                provider="semantic_scholar",
                source=paper.get("venue") or "Semantic Scholar",
                title=paper.get("title"),
                summary=paper.get("abstract"),
                url=paper.get("url"),
                published_at=published_at,
                content=paper.get("abstract"),
                extra={"authors": authors} if authors else None,
            )
        )
        if len(results) >= max_results:
            break

    return results


def _parse_crossref_payload(
    payload: Dict[str, Any], max_results: int, max_age_days: int
) -> List[ContextItem]:
    results: List[ContextItem] = []
    now = datetime.now(timezone.utc)
    items = payload.get("message", {}).get("items") or []
    for item in items:
        published_dt = _extract_crossref_date(item)
        if published_dt and published_dt < now - timedelta(days=max_age_days):
            continue

        published_at = _format_timestamp(
            published_dt.isoformat() if published_dt else None
        )
        title = item.get("title", [])
        title_text = title[0] if title else None
        summary = _strip_html(item.get("abstract")) if item.get("abstract") else ""
        container_titles = item.get("container-title") or []

        results.append(
            _build_context_item(
                provider="crossref",
                source=container_titles[0] if container_titles else "Crossref",
                title=title_text,
                summary=summary,
                url=item.get("URL"),
                published_at=published_at,
                content=summary,
                extra={"doi": item.get("DOI")},
            )
        )
        if len(results) >= max_results:
            break

    return results


def _parse_proceedings_feed(
    feed_bytes: bytes, feed_url: str, provider: str, max_age_days: int
) -> List[ContextItem]:
    parsed = feedparser.parse(feed_bytes)
    if getattr(parsed, "bozo", False):
        exc = getattr(parsed, "bozo_exception", None)
        if exc and not getattr(parsed, "entries", None):
            raise ValueError(f"{exc}")
        if exc:
            print(
                f"Proceedings feed had parsing issues but will proceed for {feed_url}: {exc}"
            )

    feed_title = (parsed.feed.get("title") if parsed.feed else None) or provider.upper()
    results: List[ContextItem] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)

    for entry in parsed.entries or []:
        title = entry.get("title") or "Untitled"
        summary = entry.get("summary") or ""
        link = entry.get("link")
        published = (
            entry.get("published")
            or entry.get("updated")
            or _struct_time_to_iso(entry.get("published_parsed"))
            or _struct_time_to_iso(entry.get("updated_parsed"))
        )
        published_dt = _coerce_datetime(published)
        if published_dt and published_dt < cutoff:
            continue

        results.append(
            _build_context_item(
                provider=provider,
                source=feed_title,
                title=title,
                summary=_strip_html(summary),
                url=link,
                published_at=_format_timestamp(published),
                content=_strip_html(summary),
            )
        )

    return results


def _parse_rss_feed(feed_bytes: bytes, feed_url: str) -> List[ContextItem]:
    parsed = feedparser.parse(feed_bytes)
    if getattr(parsed, "bozo", False):
        exc = getattr(parsed, "bozo_exception", None)
        if exc and not getattr(parsed, "entries", None):
            raise ValueError(f"{exc}")  # propagate so caller logs failure
        if exc:
            print(f"RSS feed had parsing issues but will proceed for {feed_url}: {exc}")

    feed_title = (parsed.feed.get("title") if parsed.feed else None) or "RSS Feed"
    results: List[ContextItem] = []

    for entry in parsed.entries or []:
        title = entry.get("title") or "Untitled"
        summary = entry.get("summary")
        if not summary:
            contents = entry.get("content") or []
            if contents and isinstance(contents, list):
                summary = contents[0].get("value")
        summary = summary or ""

        link = entry.get("link")

        published = (
            entry.get("published")
            or entry.get("updated")
            or _struct_time_to_iso(entry.get("published_parsed"))
            or _struct_time_to_iso(entry.get("updated_parsed"))
        )

        results.append(
            _build_context_item(
                provider="rss",
                source=feed_title,
                title=title,
                summary=_strip_html(summary),
                url=link,
                published_at=_format_timestamp(published),
                content=_strip_html(summary),
            )
        )

    return results


def _build_context_item(
    provider: str,
    source: Optional[str],
    title: Optional[str],
    summary: Optional[str],
    url: Optional[str],
    published_at: Optional[str],
    content: Optional[str],
    extra: Optional[Dict[str, Any]] = None,
) -> ContextItem:
    item: ContextItem = {
        "provider": provider,
        "source": source or provider,
        "title": title or "Untitled",
        "summary": summary or "",
        "url": url,
        "published_at": published_at or "Unknown date",
        "content": content or summary or "",
    }
    if extra:
        item["metadata"] = extra
    return item


def _strip_html(text: Optional[str]) -> str:
    if not text:
        return ""
    # Very light HTML removal
    return (
        text.replace("<p>", " ")
        .replace("</p>", " ")
        .replace("<br>", " ")
        .replace("<br/>", " ")
        .replace("<br />", " ")
        .strip()
    )


def _format_timestamp(timestamp: Optional[str]) -> str:
    if not timestamp:
        return "Unknown date"
    try:
        ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return ts.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        try:
            ts = datetime.strptime(timestamp, "%a, %d %b %Y %H:%M:%S %Z")
            return ts.strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            return timestamp


def _parse_datetime(timestamp: Optional[str]) -> datetime:
    if not timestamp or timestamp == "Unknown date":
        return datetime.min
    for fmt in ("%Y-%m-%d %H:%M UTC", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(timestamp, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except Exception:
        return datetime.min


def _coerce_datetime(raw: Optional[Any]) -> Optional[datetime]:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)

    candidates = [str(raw), f"{raw}-01-01"] if isinstance(raw, int) else [str(raw)]
    for candidate in candidates:
        try:
            return datetime.fromisoformat(candidate.replace("Z", "+00:00")).astimezone(
                timezone.utc
            )
        except Exception:
            continue

    try:
        return datetime.strptime(str(raw), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        try:
            return parsedate_to_datetime(str(raw)).astimezone(timezone.utc)
        except Exception:
            return None


def _extract_crossref_date(item: Dict[str, Any]) -> Optional[datetime]:
    for key in ("published-online", "published-print", "issued", "created"):
        date_info = item.get(key)
        if not isinstance(date_info, dict):
            continue
        parts = date_info.get("date-parts")
        if not parts or not isinstance(parts, list):
            continue
        part = parts[0]
        if not part:
            continue
        year = part[0]
        month = part[1] if len(part) > 1 else 1
        day = part[2] if len(part) > 2 else 1
        try:
            return datetime(year, month, day, tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def _safe_get(data: Dict[str, Any], *keys: str) -> Any:
    obj = data
    for key in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def _struct_time_to_iso(struct: Optional[time.struct_time]) -> Optional[str]:
    if not struct:
        return None
    try:
        return (
            datetime.fromtimestamp(calendar.timegm(struct), tz=timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ")
        )
    except Exception:
        return None
