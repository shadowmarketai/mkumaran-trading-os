"""
MWA Scoring Engine — aligned with 40-scanner system.

Calculates weighted MWA score from scanner results,
detects signal chains, and auto-promotes stocks.
"""

import logging
from datetime import date

from mcp_server.mwa_scanner import SCANNERS, SIGNAL_CHAINS

logger = logging.getLogger(__name__)

# Calculate max weights dynamically from SCANNERS dict
MAX_BULL_WEIGHT = sum(
    v["weight"] for v in SCANNERS.values()
    if v["type"] == "BULL" and v.get("status") not in ("VERIFY_NEEDED",)
)

MAX_BEAR_WEIGHT = sum(
    v["weight"] for v in SCANNERS.values()
    if v["type"] == "BEAR"
)


def calculate_mwa_score(
    scanner_results: dict, symbol: str = "", segments_run: list[str] | None = None,
) -> dict:
    """
    Calculate weighted MWA score from scanner results.

    Args:
        scanner_results: Dict keyed by scanner name (e.g. "swing_low")
            with value either:
            - list of stocks (new format from MWAScanner.run_all)
            - dict with "stocks"/"count" keys (old format)
        segments_run: List of market segments that were active for this scan
            (e.g. ["MCX", "CDS"]).  None = all segments (backward compat).

    Returns:
        Dict with direction, bull_score, bear_score, bull_pct, bear_pct,
        fired_bull, fired_bear, active_chains, etc.
    """
    bull_score = 0.0
    bear_score = 0.0
    max_bull = 0.0
    max_bear = 0.0
    fired = {"bull": [], "bear": []}

    for key, cfg in SCANNERS.items():
        if cfg["type"] in ("FILTER", "UNKNOWN"):
            continue

        # Skip scanners that couldn't have run for the active segments
        if segments_run is not None:
            scanner_segs = cfg.get("segments", [])
            if not any(s in scanner_segs for s in segments_run):
                continue

        w = cfg["weight"]
        result = scanner_results.get(key)

        # Determine if scanner fired (support both new and old format)
        if result is None:
            hit = False
        elif isinstance(result, list):
            hit = len(result) > 0
        elif isinstance(result, dict):
            hit = result.get("count", len(result.get("stocks", []))) > 0
        else:
            hit = False

        if cfg["type"] == "BULL":
            max_bull += w
            if hit:
                bull_score += w
                fired["bull"].append(key)
        elif cfg["type"] == "BEAR":
            max_bear += w
            if hit:
                bear_score += w
                fired["bear"].append(key)

    bull_pct = round(bull_score / max(max_bull, 1) * 100, 1)
    bear_pct = round(bear_score / max(max_bear, 1) * 100, 1)

    # Classification
    if bull_pct >= 65:
        direction = "BULL"
    elif bull_pct >= 50:
        direction = "MILD_BULL"
    elif bear_pct >= 65:
        direction = "BEAR"
    elif bear_pct >= 50:
        direction = "MILD_BEAR"
    else:
        direction = "SIDEWAYS"

    # Signal chain detection
    active_chains = detect_signal_chains(fired, segments_run=segments_run)

    chain_boost = sum(
        c["boost"] for c in active_chains if c["complete"]
    )
    chain_boost = min(chain_boost, 35)  # Cap at 35

    # News sentiment modifier (optional layer — only for specific symbol)
    news_sentiment = None
    if symbol:
        try:
            from .news_monitor import calculate_news_sentiment

            sentiment = calculate_news_sentiment(symbol)
            news_score = sentiment.get("score", 0)
            if abs(news_score) > 30:  # Only apply for strong sentiment
                modifier = news_score / 100 * 5  # Max +/-5% adjustment
                bull_pct = min(100, max(0, bull_pct + modifier))
                bear_pct = min(100, max(0, bear_pct - modifier))
            news_sentiment = sentiment
        except Exception:
            pass  # News sentiment is optional, never block MWA

    logger.info(
        "MWA Score: %s | Bull: %.1f (%.1f%%) | Bear: %.1f (%.1f%%) | Chains: %d",
        direction, bull_score, bull_pct, bear_score, bear_pct, len(active_chains),
    )

    return {
        "score_date": str(date.today()),
        "direction": direction,
        "bull_score": round(bull_score, 1),
        "bear_score": round(bear_score, 1),
        "bull_pct": round(bull_pct, 1),
        "bear_pct": round(bear_pct, 1),
        "fired_bull": fired["bull"],
        "fired_bear": fired["bear"],
        "allow_longs": direction in ("BULL", "MILD_BULL"),
        "allow_shorts": direction in ("BEAR", "MILD_BEAR"),
        "active_chains": active_chains,
        "chain_boost": chain_boost,
        "news_sentiment": news_sentiment,
        "scanner_results": scanner_results,
    }


def detect_signal_chains(
    fired: dict[str, list[str]], segments_run: list[str] | None = None,
) -> list[dict]:
    """
    Detect which signal chains are active (75%+ match).

    Args:
        fired: Dict with "bull" and "bear" lists of fired scanner keys
        segments_run: List of active market segments.  None = all.

    Returns:
        List of active chain dicts with name, boost, complete flag, etc.
    """
    all_fired = set(fired["bull"] + fired["bear"])
    active_chains = []

    for name, chain in SIGNAL_CHAINS.items():
        needed = set(chain["scanners"])

        # Filter needed to only include scanners available for active segments
        if segments_run is not None:
            available = {
                k for k in needed
                if any(s in SCANNERS.get(k, {}).get("segments", [])
                       for s in segments_run)
            }
            if not available:
                continue  # Skip chain entirely if no scanners available
            needed = available

        matched = needed & all_fired
        if len(matched) >= len(needed) * 0.75:
            complete = matched == needed
            active_chains.append({
                "name": name,
                "desc": chain["desc"],
                "matched": sorted(matched),
                "missing": sorted(needed - all_fired),
                "boost": chain["boost"],
                "best_for": chain["best_for"],
                "complete": complete,
            })

    return active_chains


def get_promoted_stocks(
    scanner_results: dict, min_scanners: int = 3
) -> list[str]:
    """
    Auto-promote stocks that appear in 3+ bull scanners to Tier 2 watchlist.
    MCX/CDS/NFO tickers use a lower threshold (1 scanner) since they have
    fewer scanners available compared to NSE equities.

    Args:
        scanner_results: Dict keyed by scanner name with stock lists or dicts
        min_scanners: Minimum scanner appearances to promote (default 3)
    """
    # Key bull scanners for auto-promotion
    promotion_scanners = [
        "swing_low", "upswing", "volume_avg", "volume_spike",
        "breakout_50day", "breakout_200dma", "richie_rich_breakout",
        "supertrend_buy", "macd_buy_daily", "52week_high",
        "bandwalk_highs", "bullish_divergence", "failure_swing_bullish",
        "smc_bos_bull", "smc_choch_bull", "smc_demand_ob", "smc_liq_sweep_bull",
        "smc_breaker_bull", "smc_mitigation_bull", "smc_ifvg_bull",
        "smc_mss_bull", "smc_ote_bull", "smc_idm_bull",
        "smc_erl_bull", "smc_fake_bo_bull", "smc_ema_pullback_bull",
        "wyckoff_accumulation", "wyckoff_spring", "wyckoff_sos", "wyckoff_test_bull",
        "vsa_selling_climax", "vsa_stopping_bull", "vsa_effort_bull",
        "harmonic_gartley_bull", "harmonic_any_bull",
        "rl_trend_bull", "rl_momentum_bull", "rl_optimal_entry_bull",
        "cds_ema_crossover", "cds_rsi_oversold", "cds_bb_squeeze",
        "cds_carry_trade", "cds_dxy_divergence",
        "mcx_ema_crossover", "mcx_rsi_oversold", "mcx_crude_momentum",
        "mcx_gold_silver_ratio", "mcx_metal_strength",
        "intraday_momentum_bull", "daily_pct_change_py",
        "nfo_ema_crossover", "nfo_rsi_oversold", "nfo_vol_squeeze_bull",
        "nfo_range_breakout_bull",
        "nfo_stk_ema_crossover", "nfo_stk_rsi_oversold", "nfo_stk_vol_squeeze_bull",
        "nfo_stk_range_breakout_bull",
    ]

    stock_counts: dict[str, int] = {}

    for scanner_id in promotion_scanners:
        result = scanner_results.get(scanner_id)
        if result is None:
            continue

        # Support both new format (list) and old format (dict with "stocks")
        if isinstance(result, list):
            stocks = result
        elif isinstance(result, dict):
            stocks = result.get("stocks", [])
        else:
            continue

        for stock in stocks:
            stock_counts[stock] = stock_counts.get(stock, 0) + 1

    from mcp_server.asset_registry import MCX_UNIVERSE, CDS_UNIVERSE, NFO_INDEX_UNIVERSE
    multi_asset_tickers = set(MCX_UNIVERSE + CDS_UNIVERSE + NFO_INDEX_UNIVERSE)

    promoted = []
    for s, c in stock_counts.items():
        # MCX/CDS/NFO tickers need only 1 scanner (they have fewer scanners)
        threshold = 1 if s in multi_asset_tickers else min_scanners
        if c >= threshold:
            promoted.append(s)

    if promoted:
        logger.info(
            "Auto-promoting %d stocks to Tier 2: %s", len(promoted), promoted[:10]
        )

    return promoted


def format_morning_brief(score: dict) -> str:
    """Format MWA score as a Telegram-style morning brief."""
    em = {
        "BULL": "GREEN", "MILD_BULL": "YELLOW", "SIDEWAYS": "NEUTRAL",
        "MILD_BEAR": "ORANGE", "BEAR": "RED",
    }
    d = score["direction"]
    lines = [
        f"MWA BRIEF — {score.get('score_date', date.today())}",
        "-" * 33,
        f"Market : {d} ({em.get(d, 'NEUTRAL')}) | Bull {score['bull_pct']}% | Bear {score['bear_pct']}%",
        f"Longs  : {'ALLOWED' if score.get('allow_longs') else 'BLOCKED'}",
        f"Shorts : {'ALLOWED' if score.get('allow_shorts') else 'BLOCKED'}",
        "-" * 33,
    ]

    active_chains = score.get("active_chains", [])
    complete = [c for c in active_chains if c["complete"]]
    partial = [c for c in active_chains if not c["complete"]]

    if complete:
        lines.append("Complete signal chains:")
        for c in complete:
            lines.append(f"  * {c['name']:22}: +{c['boost']}% confidence")
            lines.append(f"    -> {c['best_for']}")

    if partial:
        lines.append("Near-complete (75%+):")
        for c in partial:
            lines.append(f"  ~ {c['name']:22}: missing {', '.join(c['missing'])}")

    fired_bull = score.get("fired_bull", [])
    fired_bear = score.get("fired_bear", [])

    if fired_bull:
        lines.append("-" * 33)
        lines.append(f"Bull ({len(fired_bull)}):")
        for k in fired_bull[:8]:
            layer = SCANNERS.get(k, {}).get("layer", "")
            lines.append(f"  {k:28} [{layer}]")

    if fired_bear:
        lines.append("-" * 33)
        lines.append(f"Bear ({len(fired_bear)}):")
        for k in fired_bear:
            lines.append(f"  {k}")

    lines.append("-" * 33)
    return "\n".join(lines)
