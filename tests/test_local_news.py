"""The local_news vendor serves imported files inside the window and yields to the next vendor otherwise."""
import json

import pytest

from tradingagents.dataflows import config as df_config
from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.dataflows.vendors.local_news import get_news_local


def _article(i, when, body="body text"):
    return {"id": str(i), "published_at": when, "title": f"T{i}", "body": body,
            "url": f"https://x/{i}", "author": {"name": "Src"}}


@pytest.fixture
def news_dir(tmp_path, monkeypatch):
    folder = tmp_path / "TSLA" / "longbridge"
    folder.mkdir(parents=True)
    (folder / "raw.json").write_text(json.dumps([
        _article(1, "2026-11-05T10:00:00Z"),
        _article(2, "2026-11-07T00:00:00Z"),          # after the window
        _article(3, "2026-10-01T00:00:00Z"),          # before the window
        _article(1, "2026-11-05T10:00:00Z"),          # duplicate
        _article(4, "2026-11-06T23:59:00Z", "x" * 5000),
    ]))
    (folder / "digest.md").write_text("# not json")
    monkeypatch.setattr(df_config, "get_config", lambda: {"news_dir": str(tmp_path), "news_article_limit": 20})
    monkeypatch.setattr("tradingagents.dataflows.vendors.local_news.get_config", df_config.get_config)
    return tmp_path


@pytest.mark.unit
def test_window_dedupe_order_and_truncation(news_dir):
    out = get_news_local("tsla", "2026-11-01", "2026-11-06")
    assert out.index("### T4") < out.index("### T1")      # newest first
    assert out.count("### T1") == 1
    assert "### T2" not in out and "### T3" not in out     # no look-ahead
    assert "x" * 1600 not in out


@pytest.mark.unit
def test_unknown_ticker_or_empty_window_yields_to_next_vendor(news_dir):
    with pytest.raises(VendorUnavailableError):
        get_news_local("NVDA", "2026-11-01", "2026-11-06")
    with pytest.raises(VendorUnavailableError):
        get_news_local("TSLA", "2026-01-01", "2026-01-05")
