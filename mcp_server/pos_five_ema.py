"""
MKUMARAN Trading OS — POS 5 EMA Signal Generator

Subasish Pani's "Power of Stocks" 5 EMA setup. The setup candle is one
whose full range sits one side of the 5 EMA (no overlap). The trigger
fires when the next candle breaks the setup candle's opposite extreme,
giving a clean entry/SL pair with 1:2 minimum reward.

  • SHORT setup: setup-candle low > setup-EMA5
                 → entry = setup_low,  stop = setup_high
  • LONG  setup: setup-candle high < setup-EMA5
                 → entry = setup_high, stop = setup_low

Filters that turn this from coin-flip into edge:
  - Trend filter   — close vs 50-EMA must agree with direction
  - Volume filter  — setup volume > rolling-20 avg × 1.2
  - Trigger filter — current candle must actually break the setup level

Money math runs in Decimal at the boundary (signal dict construction);
the analysis zone (pandas EMA / ATR) stays float so the existing
backtester slippage math doesn't trip Decimal×float TypeErrors.

Designed to plug into:
  - `backtester.py` as a new strategy key (`pos_5ema`)
  - `debate_validator.py` as the 9th specialist agent (low weight)
  - real-time scan loops alongside existing intraday/MWA scanners
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pandas as pd

from mcp_server.money import Numeric, round_tick, to_money

logger = logging.getLogger(__name__)


# ── Defaults (tunable; lock final values via backtest) ──────
DEFAULT_EMA_PERIOD = 5
DEFAULT_TREND_EMA = 50
DEFAULT_ATR_PERIOD = 14
DEFAULT_MIN_VOLUME_RATIO = 1.2
DEFAULT_RISK_REWARD = 2.0
DEFAULT_VOL_AVG_WINDOW = 20


@dataclass
class FiveEMASignal:
    """A POS 5 EMA setup with trigger fired on the latest closed bar."""

    symbol: str
    bar_idx: int
    direction: str  # "LONG" | "SHORT"
    entry: Decimal
    stop_loss: Decimal
    target: Decimal
    target_2: Decimal
    risk_per_share: Decimal
    confidence: float
    filters_passed: dict[str, bool] = field(default_factory=dict)

    def to_signal_dict(
        self, qty: int = 1, exchange: str | None = None,
    ) -> dict[str, Any]:
        """Shape that backtester._simulate_trades and signal_cards.create accept.

        Money fields cross into the analysis zone here as float — the same
        boundary discipline _generate_rrms_signals enforces.
        """
        return {
            "bar_idx": self.bar_idx,
            "direction": self.direction,
            "entry": float(self.entry),
            "stop_loss": float(self.stop_loss),
            "target": float(self.target),
            "qty": qty,
            "risk_per_share": float(self.risk_per_share),
            "source": "pos_5ema",
            "pattern": "5ema_breakout",
            "confidence": int(round(self.confidence * 100)),
        }


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _atr(df: pd.DataFrame, period: int) -> pd.Series:
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift()
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period).mean()


class FiveEMAGenerator:
    """Detects setup-then-trigger 5 EMA entries on a closed-bar OHLCV frame."""

    def __init__(
        self,
        ema_period: int = DEFAULT_EMA_PERIOD,
        trend_ema: int = DEFAULT_TREND_EMA,
        atr_period: int = DEFAULT_ATR_PERIOD,
        min_volume_ratio: float = DEFAULT_MIN_VOLUME_RATIO,
        risk_reward: float = DEFAULT_RISK_REWARD,
        vol_avg_window: int = DEFAULT_VOL_AVG_WINDOW,
        exchange: str | None = None,
    ) -> None:
        self.ema_period = ema_period
        self.trend_ema = trend_ema
        self.atr_period = atr_period
        self.min_volume_ratio = min_volume_ratio
        self.rr = risk_reward
        self.vol_avg_window = vol_avg_window
        self.exchange = exchange

    # ── Public: scan one symbol's frame for the latest signal ──

    def detect_latest(
        self, df: pd.DataFrame, symbol: str,
    ) -> FiveEMASignal | None:
        """Return a signal if the latest bar triggered, else None.

        df must have OHLCV columns: open, high, low, close, volume.
        """
        if not self._frame_ok(df):
            return None

        feats = self._with_indicators(df)
        return self._detect_at(feats, symbol, idx=len(feats) - 1)

    # ── Public: backtester scan (every bar from window forward) ──

    def detect_all(
        self, df: pd.DataFrame, symbol: str,
    ) -> list[FiveEMASignal]:
        """Walk the frame and return every triggered setup. Used by backtester."""
        if not self._frame_ok(df):
            return []
        feats = self._with_indicators(df)
        signals: list[FiveEMASignal] = []
        # Need the rolling/EMA windows to be filled before any setup is real.
        warmup = max(self.trend_ema, self.atr_period, self.vol_avg_window) + 2
        for i in range(warmup, len(feats)):
            sig = self._detect_at(feats, symbol, idx=i)
            if sig:
                signals.append(sig)
        return signals

    # ── Internals ────────────────────────────────────────────

    def _frame_ok(self, df: pd.DataFrame) -> bool:
        required = {"open", "high", "low", "close", "volume"}
        if not required.issubset(df.columns):
            logger.debug("FiveEMA: missing OHLCV columns; got %s", list(df.columns))
            return False
        if len(df) < max(self.trend_ema, self.atr_period, self.vol_avg_window) + 2:
            return False
        return True

    def _with_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        feats = df.copy()
        feats["ema5"] = _ema(feats["close"], self.ema_period)
        feats["ema_trend"] = _ema(feats["close"], self.trend_ema)
        feats["atr"] = _atr(feats, self.atr_period)
        feats["vol_avg"] = feats["volume"].rolling(self.vol_avg_window).mean()
        return feats

    def _detect_at(
        self, feats: pd.DataFrame, symbol: str, idx: int,
    ) -> FiveEMASignal | None:
        if idx < 1:
            return None
        setup = feats.iloc[idx - 1]
        current = feats.iloc[idx]

        # Required indicators present (window must have warmed up)
        for col in ("ema5", "ema_trend", "atr", "vol_avg"):
            if pd.isna(setup[col]):
                return None

        # SHORT: setup candle's full range sits ABOVE 5 EMA, breakdown trigger
        if setup["low"] > setup["ema5"]:
            filters = {
                "range_above_ema5": True,
                "trend_filter": setup["close"] < setup["ema_trend"],
                "volume_filter": setup["volume"] > setup["vol_avg"] * self.min_volume_ratio,
                "trigger_fired": current["low"] < setup["low"],
            }
            if all(filters.values()):
                entry = setup["low"]
                stop = setup["high"]
                risk = stop - entry
                target_1 = entry - risk * self.rr
                target_2 = entry - risk * 3.0
                return self._build_signal(
                    symbol=symbol,
                    idx=idx,
                    direction="SHORT",
                    entry=entry,
                    stop=stop,
                    target_1=target_1,
                    target_2=target_2,
                    risk=risk,
                    setup_row=setup,
                    feats=feats,
                    filters=filters,
                )

        # LONG: setup candle's full range sits BELOW 5 EMA, breakout trigger
        if setup["high"] < setup["ema5"]:
            filters = {
                "range_below_ema5": True,
                "trend_filter": setup["close"] > setup["ema_trend"],
                "volume_filter": setup["volume"] > setup["vol_avg"] * self.min_volume_ratio,
                "trigger_fired": current["high"] > setup["high"],
            }
            if all(filters.values()):
                entry = setup["high"]
                stop = setup["low"]
                risk = entry - stop
                target_1 = entry + risk * self.rr
                target_2 = entry + risk * 3.0
                return self._build_signal(
                    symbol=symbol,
                    idx=idx,
                    direction="LONG",
                    entry=entry,
                    stop=stop,
                    target_1=target_1,
                    target_2=target_2,
                    risk=risk,
                    setup_row=setup,
                    feats=feats,
                    filters=filters,
                )

        return None

    def _build_signal(
        self,
        symbol: str,
        idx: int,
        direction: str,
        entry: float,
        stop: float,
        target_1: float,
        target_2: float,
        risk: float,
        setup_row: pd.Series,
        feats: pd.DataFrame,
        filters: dict[str, bool],
    ) -> FiveEMASignal:
        confidence = self._score_confidence(setup_row, feats, idx)
        return FiveEMASignal(
            symbol=symbol,
            bar_idx=idx,
            direction=direction,
            entry=round_tick(to_money(entry), self.exchange),
            stop_loss=round_tick(to_money(stop), self.exchange),
            target=round_tick(to_money(target_1), self.exchange),
            target_2=round_tick(to_money(target_2), self.exchange),
            risk_per_share=to_money(risk),
            confidence=confidence,
            filters_passed=filters,
        )

    def _score_confidence(
        self, setup_row: pd.Series, feats: pd.DataFrame, idx: int,
    ) -> float:
        """Base 0.5; +0.2 if setup is stretched > 1.5×ATR from 5 EMA;
        +0.15 if volume is more than 2× the rolling avg.
        """
        score = 0.5
        atr = float(setup_row["atr"]) or 1.0
        stretch = abs(float(setup_row["close"]) - float(setup_row["ema5"])) / atr
        if stretch > 1.5:
            score += 0.2
        # Use the prior-bar vol_avg snapshot — already lookback-only, no
        # leakage risk.
        vol_avg_prev = float(feats.iloc[idx - 1]["vol_avg"])
        if vol_avg_prev > 0 and float(setup_row["volume"]) > vol_avg_prev * 2.0:
            score += 0.15
        return min(score, 1.0)


# ── Backtester adapter ──────────────────────────────────────


def generate_signals_for_backtest(
    data: pd.DataFrame,
    ticker: str,
    capital: Numeric,
    regime_filter: bool = True,
) -> list[dict[str, Any]]:
    """Adapter consumed by mcp_server.backtester.run_backtest("pos_5ema").

    Sizes positions at 1% of capital risk, mirroring the architect's
    spec. The backtester then applies its own per-trade slippage and
    cost layers to the (entry, stop, target, qty) tuple — the same
    contract _generate_rrms_signals fulfils.

    regime_filter=True (default): signals generated on bars where the
    regime at that point in the walkthrough is RANGING or VOLATILE are
    suppressed. This lets the backtest reflect the same gate that the
    live system applies. Set to False to see unfiltered signal count.
    """
    from mcp_server.regime_detector import classify_from_df, STRATEGY_GATES

    gen = FiveEMAGenerator()
    cap = float(to_money(capital))
    risk_rupees = cap * 0.01
    allowed = STRATEGY_GATES["pos_5ema"]

    raw_signals = gen.detect_all(data, ticker)
    out: list[dict[str, Any]] = []
    for sig in raw_signals:
        risk_per_share = float(sig.risk_per_share)
        if risk_per_share <= 0:
            continue

        if regime_filter:
            # Classify regime using data up to (not including) the signal bar
            # to avoid lookahead — only use history available at signal time.
            historical_slice = data.iloc[: sig.bar_idx]
            if len(historical_slice) >= 16:  # need ≥ ADX period + 2 bars
                regime = classify_from_df(historical_slice)
                if regime.label not in allowed:
                    continue  # suppress in non-trending regime

        qty = max(int(risk_rupees / risk_per_share), 1)
        out.append(sig.to_signal_dict(qty=qty))
    return out
