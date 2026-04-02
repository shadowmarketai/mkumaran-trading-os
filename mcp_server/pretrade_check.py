"""
Pre-Trade Checklist — 10 automated checks before placing a trade.

Run all checks against a signal and return PASS/WARN/FAIL per check
with an overall verdict: GO / CAUTION / BLOCK.
"""

import logging

from sqlalchemy.orm import Session
from sqlalchemy import desc

from mcp_server.models import Signal, MWAScore, ActiveTrade

logger = logging.getLogger(__name__)


def _check(name: str, status: str, detail: str) -> dict:
    return {"name": name, "status": status, "detail": detail}


def check_market_hours(signal: Signal) -> dict:
    """Check 1: Is the exchange currently open?"""
    try:
        from mcp_server.market_calendar import get_market_status
        ms = get_market_status(signal.exchange or "NSE")
        if ms.get("is_open"):
            return _check("Market Hours", "PASS", f"{signal.exchange} market is OPEN")
        reason = ms.get("reason", "closed")
        return _check("Market Hours", "FAIL", f"{signal.exchange} market {reason}")
    except Exception as e:
        return _check("Market Hours", "WARN", f"Could not check: {e}")


def check_active_positions(db: Session) -> dict:
    """Check 2: Are we under the max open positions limit?"""
    from mcp_server.order_manager import MAX_OPEN_POSITIONS
    count = db.query(ActiveTrade).count()
    if count < MAX_OPEN_POSITIONS:
        return _check("Active Positions", "PASS", f"{count}/{MAX_OPEN_POSITIONS} positions open")
    return _check("Active Positions", "FAIL", f"{count}/{MAX_OPEN_POSITIONS} — at max capacity")


def check_rrr(signal: Signal) -> dict:
    """Check 3: Does RRR meet the minimum for this asset class?"""
    rrr = float(signal.rrr or 0)
    min_rrr = 3.0
    exchange = signal.exchange or "NSE"
    if exchange in ("MCX", "NFO", "CDS"):
        min_rrr = 2.0
    if rrr >= min_rrr:
        return _check("RRR Minimum", "PASS", f"RRR {rrr:.1f} >= {min_rrr:.1f}")
    if rrr >= min_rrr * 0.8:
        return _check("RRR Minimum", "WARN", f"RRR {rrr:.1f} slightly below {min_rrr:.1f}")
    return _check("RRR Minimum", "FAIL", f"RRR {rrr:.1f} < minimum {min_rrr:.1f}")


def check_mwa_direction(signal: Signal, db: Session) -> dict:
    """Check 4: Does latest MWA direction align with signal direction?"""
    mwa = db.query(MWAScore).order_by(desc(MWAScore.id)).first()
    if not mwa:
        return _check("MWA Direction", "WARN", "No MWA score available")
    mwa_dir = (mwa.direction or "").upper()
    sig_dir = (signal.direction or "").upper()
    aligned = (
        (sig_dir == "LONG" and mwa_dir in ("BULL", "MILD_BULL"))
        or (sig_dir == "SHORT" and mwa_dir in ("BEAR", "MILD_BEAR"))
    )
    if aligned:
        return _check("MWA Direction", "PASS", f"Signal {sig_dir} aligns with MWA {mwa_dir}")
    if mwa_dir == "SIDEWAYS":
        return _check("MWA Direction", "WARN", f"MWA is SIDEWAYS — {sig_dir} signal has no tailwind")
    return _check("MWA Direction", "FAIL", f"Signal {sig_dir} opposes MWA {mwa_dir}")


def check_ai_confidence(signal: Signal) -> dict:
    """Check 5: Is AI confidence above 50%?"""
    conf = int(signal.ai_confidence or 0)
    if conf >= 50:
        return _check("AI Confidence", "PASS", f"Confidence {conf}% >= 50%")
    if conf >= 35:
        return _check("AI Confidence", "WARN", f"Confidence {conf}% — borderline")
    return _check("AI Confidence", "FAIL", f"Confidence {conf}% < 50%")


def check_price_zone(signal: Signal) -> dict:
    """Check 6: Is current price within 2% of the entry price?"""
    try:
        from mcp_server.data_provider import get_stock_data
        ticker = signal.ticker or ""
        exchange = signal.exchange or "NSE"
        fetch_ticker = ticker if ":" in ticker else f"{exchange}:{ticker}"
        df = get_stock_data(fetch_ticker, period="1d", interval="1d", force_refresh=True)
        if df is None or df.empty:
            return _check("Price Zone", "WARN", "Could not fetch live price")
        current = float(df["close"].iloc[-1])
        entry = float(signal.entry_price or 0)
        if entry <= 0:
            return _check("Price Zone", "WARN", "No entry price set")
        gap_pct = abs(current - entry) / entry
        if gap_pct <= 0.02:
            return _check("Price Zone", "PASS", f"CMP {current:.2f} within {gap_pct:.1%} of entry {entry:.2f}")
        if gap_pct <= 0.05:
            return _check("Price Zone", "WARN", f"CMP {current:.2f} is {gap_pct:.1%} from entry {entry:.2f}")
        return _check("Price Zone", "FAIL", f"CMP {current:.2f} is {gap_pct:.1%} away from entry {entry:.2f}")
    except Exception as e:
        return _check("Price Zone", "WARN", f"Price check failed: {e}")


def check_fii_flow(signal: Signal, db: Session) -> dict:
    """Check 7: FII not selling > 2000 Cr for long signals?"""
    mwa = db.query(MWAScore).order_by(desc(MWAScore.id)).first()
    if not mwa or mwa.fii_net is None:
        return _check("FII Flow", "WARN", "No FII data available")
    fii = float(mwa.fii_net)
    direction = (signal.direction or "").upper()
    if direction == "LONG" and fii < -2000:
        return _check("FII Flow", "FAIL", f"FII selling {fii:.0f} Cr (threshold -2000 Cr for longs)")
    if direction == "LONG" and fii < -1000:
        return _check("FII Flow", "WARN", f"FII selling {fii:.0f} Cr — cautious for longs")
    return _check("FII Flow", "PASS", f"FII net: {fii:+.0f} Cr")


def check_news_impact(signal: Signal) -> dict:
    """Check 8: No HIGH impact news in last 2 hours?"""
    try:
        from mcp_server.news_monitor import get_latest_news
        news = get_latest_news(hours=2, min_impact="HIGH")
        if not news:
            return _check("News Impact", "PASS", "No HIGH impact news in last 2 hours")
        titles = [n.title for n in news[:3]]
        return _check("News Impact", "WARN", f"{len(news)} HIGH-impact news: {'; '.join(titles)}")
    except Exception as e:
        return _check("News Impact", "WARN", f"News check unavailable: {e}")


def check_delivery_pct(signal: Signal) -> dict:
    """Check 9: Delivery % > 40% for NSE equity?"""
    exchange = (signal.exchange or "NSE").upper()
    asset_class = (signal.asset_class or "EQUITY").upper()
    if exchange != "NSE" or asset_class != "EQUITY":
        return _check("Delivery %", "PASS", f"Not applicable for {exchange}/{asset_class}")
    try:
        from mcp_server.delivery_filter import get_delivery_data
        data = get_delivery_data()
        ticker = (signal.ticker or "").replace("NSE:", "")
        pct = data.get(ticker)
        if pct is None:
            return _check("Delivery %", "WARN", f"No delivery data for {ticker}")
        if pct >= 40:
            return _check("Delivery %", "PASS", f"Delivery {pct:.1f}% >= 40%")
        return _check("Delivery %", "WARN", f"Delivery {pct:.1f}% < 40% — weak conviction")
    except Exception as e:
        return _check("Delivery %", "WARN", f"Delivery check failed: {e}")


def check_sector_strength(signal: Signal, db: Session) -> dict:
    """Check 10: Sector not opposing signal direction?"""
    mwa = db.query(MWAScore).order_by(desc(MWAScore.id)).first()
    if not mwa or not mwa.sector_strength:
        return _check("Sector Strength", "WARN", "No sector data available")
    sector_data = mwa.sector_strength
    if not isinstance(sector_data, dict):
        return _check("Sector Strength", "WARN", "Sector data format unexpected")

    direction = (signal.direction or "").upper()

    # sector_strength is {sector_name: "STRONG"/"NEUTRAL"/"WEAK"}
    # We don't have a ticker-to-sector map here, so check if any sector is opposing
    weak_sectors = [s for s, v in sector_data.items() if v == "WEAK"]
    strong_sectors = [s for s, v in sector_data.items() if v == "STRONG"]

    if direction == "LONG" and len(weak_sectors) > len(strong_sectors):
        return _check("Sector Strength", "WARN", f"More WEAK ({len(weak_sectors)}) than STRONG ({len(strong_sectors)}) sectors")
    if direction == "SHORT" and len(strong_sectors) > len(weak_sectors):
        return _check("Sector Strength", "WARN", f"More STRONG ({len(strong_sectors)}) than WEAK ({len(weak_sectors)}) sectors")
    return _check("Sector Strength", "PASS", f"Sectors: {len(strong_sectors)} strong, {len(weak_sectors)} weak")


def run_pretrade_checks(signal_id: int, db: Session) -> dict:
    """
    Run all 10 pre-trade checks for a signal.

    Returns dict with: signal_id, ticker, verdict, checks[], pass/warn/fail counts.
    """
    signal = db.query(Signal).filter(Signal.id == signal_id).first()
    if not signal:
        return {"error": f"Signal {signal_id} not found", "verdict": "BLOCK", "checks": []}

    checks = [
        check_market_hours(signal),
        check_active_positions(db),
        check_rrr(signal),
        check_mwa_direction(signal, db),
        check_ai_confidence(signal),
        check_price_zone(signal),
        check_fii_flow(signal, db),
        check_news_impact(signal),
        check_delivery_pct(signal),
        check_sector_strength(signal, db),
    ]

    pass_count = sum(1 for c in checks if c["status"] == "PASS")
    warn_count = sum(1 for c in checks if c["status"] == "WARN")
    fail_count = sum(1 for c in checks if c["status"] == "FAIL")

    if fail_count > 0:
        verdict = "BLOCK"
    elif warn_count > 0:
        verdict = "CAUTION"
    else:
        verdict = "GO"

    return {
        "signal_id": signal.id,
        "ticker": signal.ticker,
        "direction": signal.direction,
        "verdict": verdict,
        "checks": checks,
        "pass_count": pass_count,
        "warn_count": warn_count,
        "fail_count": fail_count,
    }
