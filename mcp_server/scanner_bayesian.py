"""
Bayesian Scanner Self-Learning

For every scanner in the SCANNERS dict, we maintain a Beta(α, β) posterior
over its "signal → win" rate using historical closed signals where that
scanner fired. From this we derive:

  - posterior mean        = α / (α + β)   (point estimate of win rate)
  - credible interval     = Beta.ppf(0.05, 0.95)
  - Thompson sample       = Beta.rvs(α, β)   (for bandit-style routing)
  - confidence adjustment = sigmoid-scaled prior-to-posterior delta

This gives each scanner a dynamic, evidence-based quality score that we
can use to:
  - boost / discount confidence on new signals
  - surface under-performers for review in the EOD digest
  - automatically retire scanners whose lower-bound win rate falls below
    a threshold (non-destructive — just flagged, never deleted)

Pure Python. Uses only numpy (already a dep). Results are persisted as a
JSON file at `data/scanner_bayesian.json` with atomic writes.
"""

from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from mcp_server.db import SessionLocal
from mcp_server.models import Outcome, Signal

logger = logging.getLogger(__name__)


STATE_DIR = Path(os.getenv("BAYESIAN_STATE_DIR", "data"))
STATE_FILE = STATE_DIR / "scanner_bayesian.json"

# Prior: Beta(2, 2) = weakly informative, mean 0.5
PRIOR_ALPHA = 2.0
PRIOR_BETA = 2.0

# A scanner is considered "under-performing" if upper bound of 90% credible
# interval for win rate is below this threshold.
RETIREMENT_THRESHOLD = 0.35

# Minimum samples before we trust the posterior enough to use it
MIN_SAMPLES = 10


def _beta_quantile(alpha: float, beta: float, q: float) -> float:
    """
    Approximate Beta quantile using numpy (avoids scipy dep).

    We use the fact that Beta.ppf ≈ inverse-CDF numerically via bisection.
    Good enough for reporting purposes.
    """
    if alpha <= 0 or beta <= 0:
        return 0.5

    def cdf(x: float) -> float:
        # Incomplete beta via simple series — works well for moderate params.
        # For robustness we use numpy's random sampling as a Monte Carlo estimator
        # when alpha/beta aren't too large.
        return float(np.mean(np.random.beta(alpha, beta, size=4000) <= x))

    lo, hi = 0.0, 1.0
    for _ in range(30):
        mid = (lo + hi) / 2
        if cdf(mid) < q:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _beta_mean(alpha: float, beta: float) -> float:
    if alpha + beta <= 0:
        return 0.5
    return alpha / (alpha + beta)


def _beta_std(alpha: float, beta: float) -> float:
    s = alpha + beta
    if s <= 0:
        return 0.0
    return math.sqrt((alpha * beta) / ((s * s) * (s + 1)))


def _load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {"updated_at": None, "scanners": {}}
    try:
        with STATE_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Bayesian state load failed: %s", e)
        return {"updated_at": None, "scanners": {}}


def _save_state(state: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, default=str)
    tmp.replace(STATE_FILE)


def update_bayesian_stats() -> dict[str, Any]:
    """
    Walk all closed signals, aggregate wins/losses per scanner name, and
    update the Beta posterior for each. Safe to run repeatedly.
    """
    session = SessionLocal()
    try:
        rows = (
            session.query(Signal, Outcome)
            .join(Outcome, Outcome.signal_id == Signal.id)
            .filter(Signal.scanner_list.isnot(None))
            .all()
        )
    finally:
        session.close()

    # counts[scanner] = {"wins": int, "losses": int, "tickers": set}
    counts: dict[str, dict[str, Any]] = {}
    for sig, out in rows:
        scanners = sig.scanner_list
        if not scanners or not isinstance(scanners, list):
            continue
        label = (out.outcome or "").upper()
        for key in scanners:
            if not isinstance(key, str):
                continue
            slot = counts.setdefault(
                key,
                {"wins": 0, "losses": 0, "tickers": set()},
            )
            if label == "WIN":
                slot["wins"] += 1
            elif label == "LOSS":
                slot["losses"] += 1
            if sig.ticker:
                slot["tickers"].add(sig.ticker)

    if not counts:
        return {
            "status": "no_data",
            "reason": "no closed signals with scanner attribution",
        }

    scanners_out: dict[str, Any] = {}
    for key, slot in counts.items():
        wins = int(slot["wins"])
        losses = int(slot["losses"])
        total = wins + losses
        alpha = PRIOR_ALPHA + wins
        beta = PRIOR_BETA + losses

        mean = _beta_mean(alpha, beta)
        std = _beta_std(alpha, beta)
        low = _beta_quantile(alpha, beta, 0.05) if total >= MIN_SAMPLES else 0.0
        high = _beta_quantile(alpha, beta, 0.95) if total >= MIN_SAMPLES else 1.0

        under = total >= MIN_SAMPLES and high < RETIREMENT_THRESHOLD

        scanners_out[key] = {
            "wins": wins,
            "losses": losses,
            "samples": total,
            "alpha": round(alpha, 3),
            "beta": round(beta, 3),
            "posterior_mean": round(mean, 4),
            "posterior_std": round(std, 4),
            "ci90_low": round(low, 4),
            "ci90_high": round(high, 4),
            "underperforming": bool(under),
            "unique_tickers": len(slot["tickers"]),
        }

    state = {
        "updated_at": datetime.utcnow().isoformat(),
        "prior": {"alpha": PRIOR_ALPHA, "beta": PRIOR_BETA},
        "retirement_threshold": RETIREMENT_THRESHOLD,
        "min_samples": MIN_SAMPLES,
        "scanners": scanners_out,
    }

    try:
        _save_state(state)
    except Exception as e:
        logger.warning("Bayesian state save failed: %s", e)

    return {
        "status": "ok",
        "scanners_tracked": len(scanners_out),
        "underperforming_count": sum(1 for v in scanners_out.values() if v["underperforming"]),
        "updated_at": state["updated_at"],
    }


def get_scanner_stats(scanner_key: str) -> dict[str, Any] | None:
    state = _load_state()
    return (state.get("scanners") or {}).get(scanner_key)


def get_all_stats() -> dict[str, Any]:
    return _load_state()


def get_underperforming_scanners() -> list[dict[str, Any]]:
    state = _load_state()
    scanners = state.get("scanners") or {}
    out = []
    for key, val in scanners.items():
        if val.get("underperforming"):
            out.append({"key": key, **val})
    out.sort(key=lambda r: r["ci90_high"])
    return out


# ── Runtime auto-disable set ───────────────────────────────────
# Scanners disabled by the self-dev pipeline based on Bayesian stats.
# Persisted to data/disabled_scanners.json so it survives restarts.
# Re-evaluated daily: a scanner can be re-enabled if new data improves
# its stats above the threshold.

_DISABLED_FILE = STATE_DIR / "disabled_scanners.json"


def _load_disabled() -> dict[str, Any]:
    if _DISABLED_FILE.exists():
        try:
            return json.loads(_DISABLED_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"scanners": {}, "updated_at": None}


def _save_disabled(data: dict) -> None:
    _DISABLED_FILE.parent.mkdir(parents=True, exist_ok=True)
    _DISABLED_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def get_disabled_scanners() -> set[str]:
    """Return the set of currently auto-disabled scanner names."""
    data = _load_disabled()
    return set(data.get("scanners", {}).keys())


def auto_disable_underperformers() -> dict[str, Any]:
    """Evaluate all scanners and auto-disable/re-enable based on stats.

    Disable: scanner has ≥10 samples AND 90% CI upper < 35% win rate
    Re-enable: scanner was disabled but new data pushed CI above threshold
    """
    state = _load_state()
    scanners = state.get("scanners") or {}
    disabled = _load_disabled()
    currently_disabled = disabled.get("scanners", {})

    newly_disabled: list[dict] = []
    re_enabled: list[dict] = []

    for key, stats in scanners.items():
        is_under = stats.get("underperforming", False)
        was_disabled = key in currently_disabled

        if is_under and not was_disabled:
            # Disable: consistently losing
            currently_disabled[key] = {
                "reason": (
                    f"Win rate CI90: {stats['ci90_low']:.0%}-{stats['ci90_high']:.0%} "
                    f"(below {RETIREMENT_THRESHOLD:.0%} threshold). "
                    f"Record: {stats['wins']}W/{stats['losses']}L "
                    f"over {stats['samples']} trades."
                ),
                "disabled_at": datetime.utcnow().isoformat(),
                "stats": {
                    "wins": stats["wins"],
                    "losses": stats["losses"],
                    "posterior_mean": stats["posterior_mean"],
                    "ci90_high": stats["ci90_high"],
                },
            }
            newly_disabled.append({"key": key, **stats})
            logger.info(
                "Scanner AUTO-DISABLED: %s (WR: %d/%d = %.0f%%, CI90 upper: %.0f%%)",
                key, stats["wins"], stats["losses"],
                stats["posterior_mean"] * 100, stats["ci90_high"] * 100,
            )

        elif was_disabled and not is_under and stats.get("samples", 0) >= MIN_SAMPLES:
            # Re-enable: new data improved performance
            reason = currently_disabled.pop(key)
            re_enabled.append({"key": key, "old_reason": reason, **stats})
            logger.info(
                "Scanner RE-ENABLED: %s (new WR: %.0f%%, CI90: %.0f%%)",
                key, stats["posterior_mean"] * 100, stats["ci90_high"] * 100,
            )

    disabled["scanners"] = currently_disabled
    disabled["updated_at"] = datetime.utcnow().isoformat()
    _save_disabled(disabled)

    return {
        "total_tracked": len(scanners),
        "total_disabled": len(currently_disabled),
        "newly_disabled": len(newly_disabled),
        "re_enabled": len(re_enabled),
        "newly_disabled_list": [
            {"key": d["key"], "wins": d["wins"], "losses": d["losses"],
             "wr": f"{d['posterior_mean']:.0%}"} for d in newly_disabled
        ],
        "re_enabled_list": [
            {"key": r["key"], "wins": r["wins"], "losses": r["losses"],
             "wr": f"{r['posterior_mean']:.0%}"} for r in re_enabled
        ],
    }


def compute_confidence_adjustment(scanner_list: list[str]) -> int:
    """
    Given the list of scanners firing on a new signal, return an integer
    confidence delta (-20..+20) to apply on top of the baseline AI confidence.

    Logic:
      - average posterior mean across the scanners
      - shift relative to the prior (0.5)
      - scale to ±20 range, clipped
      - only counts scanners with enough samples
    """
    if not scanner_list:
        return 0

    state = _load_state()
    scanners = state.get("scanners") or {}

    means: list[float] = []
    for key in scanner_list:
        stat = scanners.get(key)
        if not stat:
            continue
        if stat.get("samples", 0) < MIN_SAMPLES:
            continue
        means.append(float(stat.get("posterior_mean", 0.5)))

    if not means:
        return 0

    avg = sum(means) / len(means)
    # shift relative to baseline 0.5 → ±0.5 → scale to ±20
    delta = int(round((avg - 0.5) * 40))
    return max(-20, min(20, delta))


def thompson_sample(scanner_key: str, rng: np.random.Generator | None = None) -> float:
    """
    Draw a Thompson sample from the scanner's posterior. Used if we want
    bandit-style routing (pick the scanner with the highest sampled win rate).
    """
    stat = get_scanner_stats(scanner_key)
    if not stat:
        # Unknown scanner → draw from the prior
        alpha, beta = PRIOR_ALPHA, PRIOR_BETA
    else:
        alpha = float(stat.get("alpha", PRIOR_ALPHA))
        beta = float(stat.get("beta", PRIOR_BETA))
    generator = rng or np.random.default_rng()
    return float(generator.beta(alpha, beta))
