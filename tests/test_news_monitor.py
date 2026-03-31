"""Tests for news_monitor.py — keyword classification, RSS parsing, dedup."""

from unittest.mock import patch, MagicMock

from mcp_server.news_monitor import (
    classify_impact,
    fetch_rss_feeds,
    fetch_newsapi,
    get_latest_news,
    NewsItem,
    _clean_html,
)
from mcp_server.config import settings


# ── Impact Classification ──────────────────────────────────


class TestClassifyImpact:
    def test_high_rbi_policy(self):
        impact, category, kw = classify_impact("RBI policy rate cut of 25 bps announced")
        assert impact == "HIGH"

    def test_high_war(self):
        impact, category, kw = classify_impact("India Pakistan war tensions escalate")
        assert impact == "HIGH"
        assert category == "GEOPOLITICAL"

    def test_high_trump_tariff(self):
        impact, category, kw = classify_impact("Trump tariff on Indian goods raises concerns")
        assert impact == "HIGH"
        assert category == "GEOPOLITICAL"

    def test_high_market_crash(self):
        impact, category, kw = classify_impact("Circuit breaker triggered after massive selloff")
        assert impact == "HIGH"

    def test_medium_fii(self):
        impact, category, kw = classify_impact("FII buying boosts market sentiment")
        assert impact == "MEDIUM"

    def test_medium_earnings(self):
        impact, category, kw = classify_impact("TCS quarterly results beat estimates, earnings up")
        assert impact == "MEDIUM"

    def test_low_generic(self):
        impact, category, kw = classify_impact("Local restaurant opens new branch")
        assert impact == "LOW"
        assert category == "GENERAL"
        assert kw == []

    def test_category_policy(self):
        _, category, _ = classify_impact("RBI announces new repo rate changes")
        assert category == "POLICY"

    def test_category_regulatory(self):
        _, category, _ = classify_impact("SEBI regulation on algo trading tightened")
        assert category == "REGULATORY"

    def test_category_macro(self):
        _, category, _ = classify_impact("India GDP growth at 6.5%")
        assert category == "MACRO"

    def test_category_market(self):
        _, category, _ = classify_impact("Nifty hits all-time high today")
        assert category == "MARKET"

    def test_case_insensitive(self):
        impact, _, _ = classify_impact("rbi policy decision tomorrow")
        assert impact == "HIGH"

    def test_budget_high(self):
        impact, _, _ = classify_impact("Union budget 2026 key highlights")
        assert impact == "HIGH"

    def test_crude_oil_crash(self):
        impact, _, _ = classify_impact("Crude oil crash sends markets reeling")
        assert impact == "HIGH"

    def test_political_modi(self):
        impact, _, _ = classify_impact("Modi announces new economic package")
        assert impact == "MEDIUM"


# ── RSS Parsing ────────────────────────────────────────────

SAMPLE_RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>RBI policy rate cut announced</title>
      <link>https://example.com/rbi</link>
      <pubDate>Fri, 28 Mar 2026 10:00:00 GMT</pubDate>
      <description>&lt;p&gt;RBI cuts repo rate by 25 bps&lt;/p&gt;</description>
    </item>
    <item>
      <title>New movie releases this week</title>
      <link>https://example.com/movie</link>
      <pubDate>Fri, 28 Mar 2026 09:00:00 GMT</pubDate>
      <description>Bollywood update</description>
    </item>
  </channel>
</rss>"""


class TestRSSParsing:
    def test_parse_rss_items(self):
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_RSS_XML
        mock_resp.raise_for_status = MagicMock()

        with patch("mcp_server.news_monitor.requests.get", return_value=mock_resp):
            items = fetch_rss_feeds()

        assert len(items) >= 2
        rbi_item = next((i for i in items if "RBI" in i.title), None)
        assert rbi_item is not None
        assert rbi_item.impact == "HIGH"
        assert rbi_item.url == "https://example.com/rbi"

    def test_rss_network_failure_graceful(self):
        with patch("mcp_server.news_monitor.requests.get", side_effect=Exception("timeout")):
            items = fetch_rss_feeds()
        assert items == []


# ── NewsAPI ────────────────────────────────────────────────


class TestNewsAPI:
    def test_no_key_returns_empty(self, monkeypatch):
        monkeypatch.setattr(settings, "NEWSAPI_KEY", "")
        items = fetch_newsapi()
        assert items == []

    def test_newsapi_parses_response(self, monkeypatch):
        monkeypatch.setattr(settings, "NEWSAPI_KEY", "test-key")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "articles": [
                {
                    "title": "RBI rate hike shocks markets",
                    "source": {"name": "Reuters"},
                    "url": "https://reuters.com/rbi",
                    "publishedAt": "2026-03-28T10:00:00Z",
                    "description": "RBI surprised with 50bps hike",
                },
                {
                    "title": "[Removed]",
                    "source": {"name": "Unknown"},
                    "url": "",
                    "publishedAt": "",
                    "description": "",
                },
            ]
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("mcp_server.news_monitor.requests.get", return_value=mock_resp):
            items = fetch_newsapi()

        assert len(items) == 1
        assert items[0].impact == "HIGH"
        assert "Reuters" in items[0].source


# ── Deduplication ──────────────────────────────────────────


class TestDeduplication:
    def test_dedup_by_url(self):
        items = [
            NewsItem("Title A", "src1", "https://x.com/1", "2026-03-28", "HIGH", "POLICY"),
            NewsItem("Title A dupe", "src2", "https://x.com/1", "2026-03-28", "HIGH", "POLICY"),
            NewsItem("Title B", "src1", "https://x.com/2", "2026-03-28", "MEDIUM", "MACRO"),
        ]

        with patch("mcp_server.news_monitor.fetch_rss_feeds", return_value=items), \
             patch("mcp_server.news_monitor.fetch_newsapi", return_value=[]):
            result = get_latest_news(hours=24, min_impact="LOW")

        urls = [i.url for i in result]
        assert len(urls) == len(set(urls))

    def test_min_impact_filter(self):
        items = [
            NewsItem("High", "src", "https://x.com/h", "", "HIGH", "POLICY"),
            NewsItem("Med", "src", "https://x.com/m", "", "MEDIUM", "MACRO"),
            NewsItem("Low", "src", "https://x.com/l", "", "LOW", "GENERAL"),
        ]

        with patch("mcp_server.news_monitor.fetch_rss_feeds", return_value=items), \
             patch("mcp_server.news_monitor.fetch_newsapi", return_value=[]):
            result = get_latest_news(hours=24, min_impact="HIGH")

        assert len(result) == 1
        assert result[0].impact == "HIGH"


# ── Helpers ────────────────────────────────────────────────


class TestHelpers:
    def test_clean_html(self):
        assert _clean_html("<p>Hello <b>world</b></p>") == "Hello world"
        assert _clean_html("No tags here") == "No tags here"
