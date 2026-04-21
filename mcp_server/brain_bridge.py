"""
Brain Bridge — connects Trading OS to NeuroLinked brain.

Sends observations (signals, outcomes, market state) to the shared
brain at brain.shadowmarket.ai so it learns patterns across trades.

Non-blocking, fire-and-forget. Never crashes the trading pipeline.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)

BRAIN_URL = os.environ.get("NEUROLINKED_URL", "https://brain.shadowmarket.ai")
BRAIN_TOKEN = os.environ.get("NEUROLINKED_TOKEN", "nlkd_8wPJ3KKdw71R9MKsnWXsQ2QFTN2PdZn0")
BRAIN_ENABLED = os.environ.get("NEUROLINKED_ENABLED", "true").lower() == "true"

_SESSION = requests.Session()
_SESSION.headers.update({
    "Content-Type": "application/json",
    "Authorization": f"Bearer {BRAIN_TOKEN}",
})


def observe(text: str, tags: list[str] | None = None) -> bool:
    """Send an observation to the brain. Fire-and-forget."""
    if not BRAIN_ENABLED:
        return False
    try:
        resp = _SESSION.post(
            f"{BRAIN_URL}/api/claude/observe",
            json={"text": text, "tags": tags or []},
            timeout=5,
        )
        return resp.status_code == 200
    except Exception as e:
        logger.debug("Brain observe failed: %s", e)
        return False


def observe_signal(sig: dict[str, Any], confidence: int = 0, recommendation: str = "") -> bool:
    """Send a generated signal to the brain."""
    text = (
        f"Signal: {sig.get('ticker', '?')} {sig.get('direction', '?')} "
        f"entry={sig.get('entry', 0):.1f} sl={sig.get('sl', 0):.1f} "
        f"target={sig.get('target', 0):.1f} rrr={sig.get('rrr', 0):.1f} "
        f"confidence={confidence}% recommendation={recommendation} "
        f"scanners={sig.get('scanner_count', 0)} "
        f"exchange={sig.get('exchange', 'NSE')} "
        f"pattern={sig.get('pattern', '?')}"
    )
    tags = [
        "signal", sig.get("ticker", ""), sig.get("direction", ""),
        sig.get("exchange", "NSE"), sig.get("pattern", ""),
    ]
    return observe(text, tags)


def observe_outcome(
    ticker: str, direction: str, outcome: str,
    entry: float, exit_price: float, pnl_pct: float,
    days_held: int = 0, reason: str = "",
) -> bool:
    """Send a trade outcome (WIN/LOSS) to the brain."""
    text = (
        f"Outcome: {ticker} {direction} → {outcome} "
        f"entry={entry:.1f} exit={exit_price:.1f} pnl={pnl_pct:.2f}% "
        f"held={days_held}d reason={reason}"
    )
    tags = ["outcome", ticker, direction, outcome.lower(), reason]
    return observe(text, tags)


def observe_scan_summary(
    direction: str, bull_pct: float, bear_pct: float,
    signals_count: int, suppressed: int,
) -> bool:
    """Send scan cycle summary to the brain."""
    text = (
        f"Scan: direction={direction} bull={bull_pct:.0f}% bear={bear_pct:.0f}% "
        f"signals={signals_count} suppressed={suppressed}"
    )
    return observe(text, ["scan", direction])


def observe_postmortem(ticker: str, outcome: str, narrative: str) -> bool:
    """Send postmortem analysis to the brain."""
    text = f"Postmortem: {ticker} {outcome} — {narrative}"
    return observe(text, ["postmortem", ticker, outcome.lower()])


def recall(query: str) -> list[dict]:
    """Query the brain's memory. Returns matching observations."""
    if not BRAIN_ENABLED:
        return []
    try:
        resp = _SESSION.get(
            f"{BRAIN_URL}/api/claude/learned",
            timeout=5,
        )
        if resp.status_code == 200:
            return resp.json().get("associations", [])
    except Exception:
        pass
    return []


def get_insights() -> list[str]:
    """Get overnight consolidation insights from the brain."""
    if not BRAIN_ENABLED:
        return []
    try:
        resp = _SESSION.get(
            f"{BRAIN_URL}/api/claude/summary",
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("insights", [])
    except Exception:
        pass
    return []
