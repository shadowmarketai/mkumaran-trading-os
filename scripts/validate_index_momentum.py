"""
validate_index_momentum.py
Walk-forward backtest of index momentum / range-breakout triggers for
NIFTY and BANKNIFTY.

Strategy logic (daily bars):
  - 5-day range breakout: close > max of prior 5 days → BULLISH (buy CE)
  - 5-day range breakdown: close < min of prior 5 days → BEARISH (buy PE)
  - Confluence filters tested:
      baseline:      breakout only
      ema_confirm:   breakout + EMA9 > EMA21 (bull) or EMA9 < EMA21 (bear)
      rsi_confirm:   breakout + RSI(14) > 55 (bull) or RSI(14) < 45 (bear)
      full_confirm:  breakout + EMA confirm + RSI confirm
      vix_filter:    full_confirm + VIX rising (bear) or VIX stable (bull)

Exit model (simulates buying ATM option premium):
  - Entry: index close at signal bar (simulated premium ~ 1% of spot)
  - Win: index moves +0.5% more in breakout direction within 3 days
         (premium roughly doubles → ~100% gain on option)
  - Loss: index reverses through breakout level (option expires worthless → -100%)
  - Note: we track *index direction* wins, not option P&L directly.
          Options power-law: 40% WR × 2.5x avg winner > 60% loser at 1x
          Break-even WR for RRR=2.5 is 28.6%. TIER_2 target: WR >= 40%.

Usage:
    python scripts/validate_index_momentum.py
    python scripts/validate_index_momentum.py --days 365 --forward 3 5
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SYMBOLS = {
    "NIFTY": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "VIX": "^INDIAVIX",
}

TIER1_WR, TIER1_TRADES, TIER1_SHARPE = 0.50, 20, 0.6
TIER2_WR, TIER2_TRADES, TIER2_SHARPE = 0.40, 12, 0.3


# ── Indicators ────────────────────────────────────────────────────────────────

def _ema(arr: np.ndarray, p: int) -> np.ndarray:
    out = np.full(len(arr), np.nan)
    if len(arr) < p:
        return out
    out[p - 1] = arr[:p].mean()
    k = 2.0 / (p + 1)
    for i in range(p, len(arr)):
        out[i] = arr[i] * k + out[i - 1] * (1 - k)
    return out


def _rsi(c: np.ndarray, p: int = 14) -> np.ndarray:
    out = np.full(len(c), np.nan)
    if len(c) < p + 1:
        return out
    for i in range(p, len(c)):
        window = c[i - p: i + 1]
        d = np.diff(window)
        gains = d[d > 0].mean() if (d > 0).any() else 0.0
        losses = -d[d < 0].mean() if (d < 0).any() else 0.0
        out[i] = 100 - 100 / (1 + gains / losses) if losses > 0 else 100.0
    return out


# ── Data ─────────────────────────────────────────────────────────────────────

def _fetch(yf_sym: str, days: int) -> pd.DataFrame | None:
    try:
        import yfinance as yf
        lookback = min(days + 90, 730)
        df = yf.download(yf_sym, period=f"{lookback}d", interval="1d",
                         progress=False, auto_adjust=True)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        df.columns = [c.lower() for c in df.columns]
        return df.dropna(subset=["close", "high", "low", "open"])
    except Exception as e:
        logger.warning("Fetch failed %s: %s", yf_sym, e)
        return None


# ── Scanner ──────────────────────────────────────────────────────────────────

def _scan_bar(
    df_idx: pd.DataFrame,
    df_vix: pd.DataFrame | None,
    i: int,
    n_range: int = 5,
    ema_confirm: bool = False,
    rsi_confirm: bool = False,
    vix_filter: bool = False,
) -> str | None:
    """Return 'BULL', 'BEAR', or None for bar at index i."""
    if i < max(n_range + 1, 22):
        return None

    c   = df_idx["close"].values.astype(float)
    # 5-day range: compare today's close vs prior N bars' high/low
    prior_high = c[i - n_range: i].max()
    prior_low  = c[i - n_range: i].min()

    is_bull = c[i] > prior_high
    is_bear = c[i] < prior_low

    if not is_bull and not is_bear:
        return None

    direction = "BULL" if is_bull else "BEAR"

    if ema_confirm or rsi_confirm:
        e9  = _ema(c[:i + 1], 9)
        e21 = _ema(c[:i + 1], 21)

        if ema_confirm:
            if np.isnan(e9[-1]) or np.isnan(e21[-1]):
                return None
            if is_bull and e9[-1] <= e21[-1]:
                return None
            if is_bear and e9[-1] >= e21[-1]:
                return None

        if rsi_confirm:
            rsi = _rsi(c[:i + 1], 14)
            if np.isnan(rsi[-1]):
                return None
            if is_bull and rsi[-1] < 55:
                return None
            if is_bear and rsi[-1] > 45:
                return None

    if vix_filter and df_vix is not None and len(df_vix) > 1:
        # Align VIX to signal date
        sig_date = df_idx.index[i]
        vix_before = df_vix[df_vix.index <= sig_date]
        if len(vix_before) >= 2:
            vix_now  = float(vix_before["close"].iloc[-1])
            vix_prev = float(vix_before["close"].iloc[-2])
            vix_rising = vix_now > vix_prev
            # Bear signals confirmed by rising VIX; bull by stable/falling
            if is_bear and not vix_rising:
                return None
            if is_bull and vix_rising and vix_now > 18:
                return None  # skip bull when VIX spike — fear trumps momentum

    return direction


# ── Simulation ────────────────────────────────────────────────────────────────

def _simulate(
    df: pd.DataFrame, df_vix: pd.DataFrame | None,
    lookback: int, forward: int,
    ema_confirm: bool, rsi_confirm: bool, vix_filter: bool,
) -> list[dict]:
    cutoff = date.today() - timedelta(days=lookback)
    c = df["close"].values.astype(float)
    trades = []
    last_signal_i = -5  # cooldown: skip if signal within 3 bars of last one

    for i in range(22, len(df) - forward):
        sig_date = df.index[i].date()
        if sig_date < cutoff:
            continue
        if i - last_signal_i < 3:
            continue  # cooldown

        direction = _scan_bar(df, df_vix, i, n_range=5,
                              ema_confirm=ema_confirm,
                              rsi_confirm=rsi_confirm,
                              vix_filter=vix_filter)
        if not direction:
            continue

        last_signal_i = i
        entry_price = c[i]

        # Win condition: index moves 0.5%+ in breakout direction within `forward` days
        win = False
        max_forward_move = 0.0
        for j in range(i + 1, min(i + 1 + forward, len(df))):
            move = (c[j] - entry_price) / entry_price * 100
            if direction == "BULL":
                max_forward_move = max(max_forward_move, move)
                if move >= 0.5:
                    win = True
                    break
            else:
                max_forward_move = max(max_forward_move, -move)
                if move <= -0.5:
                    win = True
                    break

        # Simulate approximate option P&L
        # Win: +100% on premium (premium doubled)  Loss: -100% (expired)
        opt_ret = 100.0 if win else -100.0

        trades.append({
            "date": sig_date,
            "direction": direction,
            "win": win,
            "ret": opt_ret,
            "max_move": round(max_forward_move, 2),
        })

    return trades


def _metrics(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0, "wr": 0, "sharpe": 0, "pnl": 0,
                "verdict": "OVERRIDE", "bull": 0, "bear": 0}
    rets = [t["ret"] for t in trades]
    wins = [r for r in rets if r > 0]
    n, wr = len(rets), len(wins) / len(rets)
    pnl = sum(rets)  # % return sum (each trade 1 unit)
    std = np.std(rets, ddof=1) if n > 1 else 1.0
    sharpe = np.mean(rets) / std * (252 ** 0.5) if std > 0 else 0
    bull = sum(1 for t in trades if t["direction"] == "BULL")
    bear = sum(1 for t in trades if t["direction"] == "BEAR")

    if wr >= TIER1_WR and n >= TIER1_TRADES and sharpe >= TIER1_SHARPE:
        verdict = "TIER_1"
    elif wr >= TIER2_WR and n >= TIER2_TRADES and sharpe >= TIER2_SHARPE:
        verdict = "TIER_2"
    else:
        verdict = "OVERRIDE"
    return {"n": n, "wr": round(wr * 100, 1), "sharpe": round(sharpe, 3),
            "pnl": round(pnl, 0), "verdict": verdict, "bull": bull, "bear": bear}


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=730)
    parser.add_argument("--forward", type=int, nargs="+", default=[3, 5])
    args = parser.parse_args()

    logger.info("Fetching data (%dd lookback)...", args.days)
    data = {}
    for name, yf_sym in SYMBOLS.items():
        df = _fetch(yf_sym, args.days)
        if df is not None and len(df) >= 30:
            data[name] = df
            logger.info("  %s: %d bars", name, len(df))
        else:
            logger.warning("  %s: fetch failed", name)

    if "NIFTY" not in data and "BANKNIFTY" not in data:
        logger.error("No index data — aborting")
        return

    df_vix = data.get("VIX")

    variants = [
        ("baseline",     False, False, False),
        ("ema_confirm",  True,  False, False),
        ("rsi_confirm",  False, True,  False),
        ("full_confirm", True,  True,  False),
        ("vix_filter",   True,  True,  True),
    ]

    best_overall = {}

    for idx_name in ("NIFTY", "BANKNIFTY"):
        if idx_name not in data:
            continue
        df = data[idx_name]
        logger.info("\n══ %s ══", idx_name)

        for fwd in args.forward:
            logger.info("  -- forward=%dd --", fwd)
            for vname, ema_c, rsi_c, vix_f in variants:
                trades = _simulate(df, df_vix, args.days, fwd, ema_c, rsi_c, vix_f)
                m = _metrics(trades)
                logger.info(
                    "  %-14s | n=%3d (B:%d/E:%d) | WR=%-5.1f%% | "
                    "Sharpe=%-6.3f | PnL=%+.0f%% → %s",
                    vname, m["n"], m["bull"], m["bear"],
                    m["wr"], m["sharpe"], m["pnl"], m["verdict"],
                )
                key = f"{idx_name}_{vname}_fwd{fwd}"
                best_overall[key] = m

    # Summary
    logger.info("\n── SUMMARY ──")
    tier1 = [(k, v) for k, v in best_overall.items() if v["verdict"] == "TIER_1"]
    tier2 = [(k, v) for k, v in best_overall.items() if v["verdict"] == "TIER_2"]
    override = [(k, v) for k, v in best_overall.items() if v["verdict"] == "OVERRIDE"]
    logger.info("TIER_1: %d variants", len(tier1))
    for k, v in tier1:
        logger.info("  %s: WR=%.1f%% n=%d Sharpe=%.3f", k, v["wr"], v["n"], v["sharpe"])
    logger.info("TIER_2: %d variants", len(tier2))
    for k, v in tier2:
        logger.info("  %s: WR=%.1f%% n=%d Sharpe=%.3f", k, v["wr"], v["n"], v["sharpe"])
    logger.info("OVERRIDE: %d variants", len(override))
    logger.info("\nDecision threshold: TIER_2+ → build live scanner | OVERRIDE → do not build")


if __name__ == "__main__":
    main()
