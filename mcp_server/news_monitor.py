"""
MKUMARAN Trading OS — News & Macro Event Monitor

Monitors RSS feeds and optional NewsAPI for market-moving events.
Classifies impact (HIGH/MEDIUM/LOW) and sends Telegram alerts for HIGH items.

No new dependencies — uses stdlib xml.etree.ElementTree + existing requests.
Optional: NEWSAPI_KEY env var for NewsAPI.org integration (free tier, 100 req/day).
"""

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta

import requests

from mcp_server.config import settings

logger = logging.getLogger(__name__)

# ── Data Model ─────────────────────────────────────────────


@dataclass
class NewsItem:
    title: str
    source: str
    url: str
    published: str
    impact: str  # HIGH, MEDIUM, LOW
    category: str  # POLICY, MACRO, GEOPOLITICAL, REGULATORY, MARKET, GENERAL
    matched_keywords: list[str] = field(default_factory=list)
    summary: str = ""


# ── RSS Feed Sources ───────────────────────────────────────

RSS_FEEDS: dict[str, str] = {
    "moneycontrol": "https://www.moneycontrol.com/rss/MCtopnews.xml",
    "economic_times": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "livemint": "https://www.livemint.com/rss/markets",
}

# ── Keyword Classification ─────────────────────────────────

HIGH_KEYWORDS: list[str] = [
    "RBI policy", "repo rate", "rate cut", "rate hike",
    "SEBI ban", "SEBI regulation", "SEBI order",
    "war", "airstrike", "military",
    "Trump tariff", "trade war", "trade ban",
    "union budget", "budget 2026", "budget 2027",
    "crude oil crash", "oil crash",
    "rupee crash", "rupee fall",
    "FII pullout", "FII outflow",
    "circuit breaker", "market crash", "flash crash",
    "export ban", "import ban",
    "election result", "government formation",
    "lockdown", "pandemic",
    "nuclear", "sanctions",
]

MEDIUM_KEYWORDS: list[str] = [
    "RBI", "SEBI", "inflation", "CPI", "WPI", "GDP",
    "Trump", "Modi", "Fed", "Powell", "Yellen",
    "tariff", "duty", "customs",
    "crude oil", "brent", "gold", "silver",
    "FII", "DII", "FPI",
    "Nifty", "Sensex", "Bank Nifty",
    "semiconductor", "AI", "artificial intelligence",
    "earnings", "quarterly results",
    "IPO", "listing",
    "merger", "acquisition", "takeover",
    "interest rate", "bond yield",
    "dollar", "forex", "currency",
]

# Category detection patterns (checked in order — first match wins)
CATEGORY_PATTERNS: list[tuple[str, list[str]]] = [
    ("POLICY", ["RBI", "repo rate", "rate cut", "rate hike", "monetary policy", "fiscal policy"]),
    ("REGULATORY", ["SEBI", "regulation", "ban", "compliance", "circular"]),
    ("GEOPOLITICAL", ["war", "airstrike", "military", "Trump", "sanctions", "nuclear", "trade war", "tariff"]),
    ("MACRO", ["inflation", "CPI", "GDP", "WPI", "budget", "fiscal deficit", "employment", "PMI"]),
    ("MARKET", ["Nifty", "Sensex", "FII", "DII", "circuit breaker", "crash", "rally", "IPO", "earnings"]),
]

# ── Seen URLs tracker (in-memory dedup) ────────────────────
_seen_urls: set[str] = set()


def classify_impact(title: str) -> tuple[str, str, list[str]]:
    """
    Classify a news headline by impact level and category.

    Returns: (impact, category, matched_keywords)
    """
    title_lower = title.lower()
    matched_high = [kw for kw in HIGH_KEYWORDS if kw.lower() in title_lower]
    matched_medium = [kw for kw in MEDIUM_KEYWORDS if kw.lower() in title_lower]

    # Determine impact
    if matched_high:
        impact = "HIGH"
    elif matched_medium:
        impact = "MEDIUM"
    else:
        impact = "LOW"

    # Determine category
    category = "GENERAL"
    all_matched = matched_high + matched_medium
    for cat_name, cat_keywords in CATEGORY_PATTERNS:
        for kw in cat_keywords:
            if kw.lower() in title_lower:
                category = cat_name
                break
        if category != "GENERAL":
            break

    return impact, category, all_matched


# ── RSS Fetcher ────────────────────────────────────────────


def fetch_rss_feeds(timeout: int = 15) -> list[NewsItem]:
    """Fetch and parse all configured RSS feeds."""
    items: list[NewsItem] = []

    for source_name, feed_url in RSS_FEEDS.items():
        try:
            resp = requests.get(feed_url, timeout=timeout, headers={
                "User-Agent": "MKUMARAN-TradingOS/1.0",
            })
            resp.raise_for_status()

            root = ET.fromstring(resp.text)

            # Standard RSS 2.0 structure
            for item_el in root.findall(".//item"):
                title = (item_el.findtext("title") or "").strip()
                link = (item_el.findtext("link") or "").strip()
                pub_date = (item_el.findtext("pubDate") or "").strip()
                description = (item_el.findtext("description") or "").strip()

                if not title:
                    continue

                impact, category, keywords = classify_impact(title)

                items.append(NewsItem(
                    title=title,
                    source=source_name,
                    url=link,
                    published=pub_date,
                    impact=impact,
                    category=category,
                    matched_keywords=keywords,
                    summary=_clean_html(description)[:200] if description else "",
                ))

        except Exception as e:
            logger.warning("RSS fetch failed for %s: %s", source_name, e)

    return items


def _clean_html(text: str) -> str:
    """Remove HTML tags from text."""
    return re.sub(r"<[^>]+>", "", text).strip()


# ── NewsAPI Fetcher (Optional) ─────────────────────────────


def fetch_newsapi(
    query: str = "India market OR RBI OR SEBI OR Nifty",
    hours: int = 24,
) -> list[NewsItem]:
    """Fetch news from NewsAPI.org. Requires NEWSAPI_KEY env var."""
    api_key = getattr(settings, "NEWSAPI_KEY", "")
    if not api_key:
        logger.debug("NEWSAPI_KEY not set — skipping NewsAPI fetch")
        return []

    try:
        from_date = (datetime.utcnow() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
        resp = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": query,
                "from": from_date,
                "sortBy": "publishedAt",
                "language": "en",
                "pageSize": 50,
                "apiKey": api_key,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        items: list[NewsItem] = []
        for article in data.get("articles", []):
            title = article.get("title", "")
            if not title or title == "[Removed]":
                continue

            impact, category, keywords = classify_impact(title)
            items.append(NewsItem(
                title=title,
                source=f"newsapi:{article.get('source', {}).get('name', 'unknown')}",
                url=article.get("url", ""),
                published=article.get("publishedAt", ""),
                impact=impact,
                category=category,
                matched_keywords=keywords,
                summary=(article.get("description") or "")[:200],
            ))

        return items

    except Exception as e:
        logger.warning("NewsAPI fetch failed: %s", e)
        return []


# ── Combined Fetcher ───────────────────────────────────────


def get_latest_news(
    hours: int = 24,
    min_impact: str = "LOW",
) -> list[NewsItem]:
    """
    Get combined news from all sources, deduplicated and sorted by impact.

    Args:
        hours: How far back to look (for NewsAPI; RSS returns latest items).
        min_impact: Minimum impact level to include (LOW, MEDIUM, HIGH).
    """
    impact_order = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
    min_level = impact_order.get(min_impact.upper(), 1)

    # Fetch from all sources
    all_items = fetch_rss_feeds()
    all_items.extend(fetch_newsapi(hours=hours))

    # Deduplicate by URL
    seen: set[str] = set()
    unique: list[NewsItem] = []
    for item in all_items:
        key = item.url or item.title
        if key not in seen:
            seen.add(key)
            if impact_order.get(item.impact, 0) >= min_level:
                unique.append(item)

    # Sort: HIGH first, then MEDIUM, then LOW
    unique.sort(key=lambda x: impact_order.get(x.impact, 0), reverse=True)

    return unique


# ── News Sentiment Scoring ────────────────────────────────

_sentiment_cache: dict[str, dict] = {}
_sentiment_cache_time: dict[str, float] = {}


def calculate_news_sentiment(symbol: str) -> dict:
    """Score news sentiment for a symbol using AI. Cached for 30 minutes.

    Returns: {"score": -100..100, "bias": "bullish/bearish/neutral",
              "count": int, "key_headline": str}
    """
    import time

    now = time.time()
    if symbol in _sentiment_cache and (now - _sentiment_cache_time.get(symbol, 0)) < 1800:
        return _sentiment_cache[symbol]

    # Try symbol-specific NewsAPI query first, fall back to general RSS filtered
    news = fetch_newsapi(query=f"{symbol} stock India", hours=6)
    if not news:
        # Filter RSS headlines that mention the symbol
        all_rss = fetch_rss_feeds()
        news = [n for n in all_rss if symbol.upper() in n.title.upper()]

    if not news:
        return {"score": 0, "count": 0, "bias": "neutral", "key_headline": ""}

    headlines = [f"- {n.title} ({n.source})" for n in news[:10]]
    from .wallstreet_tools import _call_claude, _parse_json

    prompt = (
        f"Score these headlines for {symbol} stock sentiment.\n"
        f"Headlines:\n"
        + "\n".join(headlines)
        + "\n\n"
        'Respond JSON: {"score": <-100 to 100>, "bias": "<bullish/bearish/neutral>", '
        '"key_headline": "<most impactful>"}'
    )

    raw = _call_claude(prompt, max_tokens=200)
    result = _parse_json(raw)
    if "raw_response" in result:
        result = {"score": 0, "bias": "neutral", "key_headline": ""}
    result["count"] = len(news)

    _sentiment_cache[symbol] = result
    _sentiment_cache_time[symbol] = now
    return result


# ── Alert Checker (Telegram) ──────────────────────────────


async def check_and_alert() -> dict:
    """
    Check for new HIGH-impact news and send Telegram alerts.

    Tracks seen URLs to avoid duplicate alerts.
    Returns summary of what was found and alerted.
    """
    global _seen_urls

    all_news = get_latest_news(hours=6, min_impact="HIGH")
    high_items = [n for n in all_news if n.impact == "HIGH"]

    new_alerts: list[NewsItem] = []
    for item in high_items:
        key = item.url or item.title
        if key not in _seen_urls:
            _seen_urls.add(key)
            new_alerts.append(item)

    # Send Telegram for new HIGH items
    if new_alerts:
        try:
            from mcp_server.telegram_bot import send_telegram_message

            for item in new_alerts[:5]:  # Max 5 alerts per check
                msg = (
                    f"\U0001f6a8 HIGH IMPACT NEWS\n"
                    f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
                    f"{item.title}\n\n"
                    f"Category: {item.category}\n"
                    f"Source: {item.source}\n"
                    f"Keywords: {', '.join(item.matched_keywords[:5])}\n"
                    f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
                    f"{item.url}"
                )
                # News alerts should go through even outside hours (force=True)
                await send_telegram_message(msg, force=True)

        except Exception as e:
            logger.error("News alert Telegram send failed: %s", e)

    return {
        "total_high": len(high_items),
        "new_alerts_sent": len(new_alerts),
        "seen_urls_count": len(_seen_urls),
        "alerts": [asdict(a) for a in new_alerts[:5]],
    }
