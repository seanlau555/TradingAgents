"""News read from a folder of files you imported yourself.

Layout: ``<news_dir>/<TICKER>/**/*.json``. A file holds a JSON list of articles,
each with ``published_at`` (ISO 8601), ``title``, ``body`` (or ``description``),
``url`` and ``author.name``. This is the shape ``longbridge news`` exports, so a
``longbridge_raw_*.json`` dropped under ``news/TSLA/`` works as it is. Files that
are not such a list (the generated ``.md`` digests, READMEs) are ignored.

Select it with ``data_vendors["news_data"] = "local_news,yfinance"`` (or
``TRADINGAGENTS_NEWS_VENDOR``): when the folder has nothing for the symbol or the
window, the next vendor in the chain serves the call.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.date_window import in_window
from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.dataflows.symbols import normalize_symbol, safe_ticker_component

logger = logging.getLogger(__name__)

# Bound what one article may cost the analyst's context.
_MAX_BODY_CHARS = 1500


def _ticker_dir(news_dir: Path, ticker: str) -> Path | None:
    """The folder for ``ticker`` under ``news_dir``, matched case-insensitively."""
    safe = safe_ticker_component(normalize_symbol(ticker))
    if not news_dir.is_dir():
        return None
    for child in news_dir.iterdir():
        if child.is_dir() and child.name.upper() == safe.upper():
            return child
    return None


def _parse_time(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _load_articles(folder: Path) -> list[dict]:
    """Every article in the folder's JSON files, once each, newest first."""
    seen: set[str] = set()
    articles: list[dict] = []
    for path in sorted(folder.rglob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("Skipping unreadable news file %s: %s", path, exc)
            continue
        if not isinstance(raw, list):
            continue
        for item in raw:
            if not isinstance(item, dict):
                continue
            pub = _parse_time(item.get("published_at"))
            body = (item.get("body") or item.get("description") or "").strip()
            title = (item.get("title") or "").strip() or body[:100] or "No title"
            key = str(item.get("id") or item.get("url") or title)
            if key in seen:
                continue
            seen.add(key)
            author = item.get("author")
            articles.append({
                "title": title,
                "body": body,
                "publisher": (author.get("name") if isinstance(author, dict) else author) or "Unknown",
                "link": item.get("url") or "",
                "pub_date": pub,
            })
    epoch = datetime.min.replace(tzinfo=None)
    articles.sort(key=lambda a: a["pub_date"].replace(tzinfo=None) if a["pub_date"] else epoch, reverse=True)
    return articles


def get_news_local(ticker: str, start_date: str, end_date: str) -> str:
    """News about ``ticker`` published in the window, from the local news folder."""
    config = get_config()
    news_dir = config.get("news_dir")
    if not news_dir:
        raise VendorUnavailableError("news_dir is not configured")
    folder = _ticker_dir(Path(news_dir).expanduser(), ticker)
    if folder is None:
        raise VendorUnavailableError(f"no local news folder for {ticker} under {news_dir}")

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    # Undated articles are dropped: in_window keeps them only for a present-day window,
    # and a file cannot prove an undated article is not from after the run's date.
    in_range = [
        a for a in _load_articles(folder)
        if a["pub_date"] is not None and in_window(a["pub_date"], start_dt, end_dt)
    ]
    if not in_range:
        raise VendorUnavailableError(
            f"local news for {ticker} has no articles from {start_date} to {end_date}"
        )

    limit = config.get("news_article_limit") or len(in_range)
    out = f"## {ticker} News, from {start_date} to {end_date} (local files):\n\n"
    for a in in_range[:limit]:
        out += f"### {a['title']} (source: {a['publisher']})\n"
        out += f"Published: {a['pub_date'].isoformat()}\n"
        if a["body"]:
            body = a["body"]
            if len(body) > _MAX_BODY_CHARS:
                body = body[:_MAX_BODY_CHARS].rstrip() + " …"
            out += f"{body}\n"
        if a["link"]:
            out += f"Link: {a['link']}\n"
        out += "\n"
    if len(in_range) > limit:
        out += f"({len(in_range) - limit} older articles in the window omitted)\n"
    return out


def get_global_news_local(
    as_of_date: str, look_back_days: int | None = None, limit: int | None = None
) -> str:
    """Global news is not kept in the local folder, which is organised per ticker."""
    raise VendorUnavailableError("the local news folder holds company news only, not global news")
