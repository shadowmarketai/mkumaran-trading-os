from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import pandas as pd

from mcp_server.config import settings

logger = logging.getLogger(__name__)


@dataclass
class RRMSResult:
    """Result of RRMS calculation."""
    ticker: str
    direction: str
    cmp: float
    ltrp: float
    pivot_high: float
    entry_price: float
    stop_loss: float
    target: float
    risk_per_share: float
    reward_per_share: float
    rrr: float
    qty: int
    risk_amt: float
    potential_profit: float
    is_valid: bool
    rejection_reason: str


class RRMSEngine:
    """
    MKUMARAN RRMS Position Sizing Engine.

    Rules:
    - Capital: configurable (default 1,00,000)
    - Risk per trade: 2% of capital (2,000)
    - Minimum RRR: 3:1
    - Entry trigger: CMP <= LTRP * 1.02 (within 2%)
    - Stop loss: LTRP * 0.995 (0.5% below LTRP)
    - Target: pivot_high
    """

    def __init__(
        self,
        capital: float = 0,
        risk_pct: float = 0,
        min_rrr: float = 0,
    ):
        self.capital = capital or settings.RRMS_CAPITAL
        self.risk_pct = risk_pct or settings.RRMS_RISK_PCT
        self.min_rrr = min_rrr or settings.RRMS_MIN_RRR
        self.risk_amt = self.capital * self.risk_pct

    def calculate(
        self,
        ticker: str,
        cmp: float,
        ltrp: float,
        pivot_high: float,
        direction: str = "LONG",
    ) -> RRMSResult:
        """
        Calculate RRMS position sizing for a stock.

        Args:
            ticker: Stock symbol (e.g. "NSE:RELIANCE")
            cmp: Current Market Price
            ltrp: Long Term Reference Point (swing low)
            pivot_high: Pivot High (swing high / target)
            direction: "LONG" or "SHORT"

        Returns:
            RRMSResult with all position sizing details
        """
        if direction == "LONG":
            return self._calculate_long(ticker, cmp, ltrp, pivot_high)
        else:
            return self._calculate_short(ticker, cmp, ltrp, pivot_high)

    def _calculate_long(
        self, ticker: str, cmp: float, ltrp: float, pivot_high: float
    ) -> RRMSResult:
        """Calculate for LONG position."""
        # Entry trigger: CMP must be within 2% of LTRP
        entry_zone_upper = ltrp * 1.02

        if cmp > entry_zone_upper:
            return RRMSResult(
                ticker=ticker, direction="LONG", cmp=cmp,
                ltrp=ltrp, pivot_high=pivot_high,
                entry_price=cmp, stop_loss=0, target=pivot_high,
                risk_per_share=0, reward_per_share=0, rrr=0,
                qty=0, risk_amt=self.risk_amt, potential_profit=0,
                is_valid=False,
                rejection_reason=f"CMP {cmp:.2f} > entry zone {entry_zone_upper:.2f} (LTRP*1.02)",
            )

        # Stop loss: 0.5% below LTRP
        stop_loss = ltrp * 0.995

        # Risk and reward
        risk_per_share = cmp - stop_loss
        reward_per_share = pivot_high - cmp

        if risk_per_share <= 0:
            return RRMSResult(
                ticker=ticker, direction="LONG", cmp=cmp,
                ltrp=ltrp, pivot_high=pivot_high,
                entry_price=cmp, stop_loss=stop_loss, target=pivot_high,
                risk_per_share=0, reward_per_share=reward_per_share, rrr=0,
                qty=0, risk_amt=self.risk_amt, potential_profit=0,
                is_valid=False,
                rejection_reason="CMP below stop loss -- no valid entry",
            )

        rrr = reward_per_share / risk_per_share

        # Position sizing
        qty = math.floor(self.risk_amt / risk_per_share)
        potential_profit = qty * reward_per_share

        # Validate minimum RRR
        is_valid = rrr >= self.min_rrr and qty > 0
        rejection_reason = ""
        if rrr < self.min_rrr:
            rejection_reason = f"RRR {rrr:.2f} < minimum {self.min_rrr}"
        elif qty <= 0:
            rejection_reason = "Position size is 0 -- risk per share too large"

        result = RRMSResult(
            ticker=ticker, direction="LONG", cmp=cmp,
            ltrp=ltrp, pivot_high=pivot_high,
            entry_price=cmp, stop_loss=stop_loss, target=pivot_high,
            risk_per_share=round(risk_per_share, 2),
            reward_per_share=round(reward_per_share, 2),
            rrr=round(rrr, 2),
            qty=qty,
            risk_amt=round(self.risk_amt, 2),
            potential_profit=round(potential_profit, 2),
            is_valid=is_valid,
            rejection_reason=rejection_reason,
        )

        logger.info(
            "RRMS %s: %s @ %.2f | SL: %.2f | Target: %.2f | RRR: %.2f | Qty: %d | Valid: %s",
            ticker, "LONG", cmp, stop_loss, pivot_high, rrr, qty, is_valid,
        )

        return result

    def _calculate_short(
        self, ticker: str, cmp: float, ltrp: float, pivot_high: float
    ) -> RRMSResult:
        """Calculate for SHORT position (reversed logic)."""
        # For shorts: entry near pivot_high, target at ltrp, SL above pivot_high
        entry_zone_lower = pivot_high * 0.98

        if cmp < entry_zone_lower:
            return RRMSResult(
                ticker=ticker, direction="SHORT", cmp=cmp,
                ltrp=ltrp, pivot_high=pivot_high,
                entry_price=cmp, stop_loss=0, target=ltrp,
                risk_per_share=0, reward_per_share=0, rrr=0,
                qty=0, risk_amt=self.risk_amt, potential_profit=0,
                is_valid=False,
                rejection_reason=f"CMP {cmp:.2f} < entry zone {entry_zone_lower:.2f} (pivot*0.98)",
            )

        stop_loss = pivot_high * 1.005
        risk_per_share = stop_loss - cmp
        reward_per_share = cmp - ltrp

        if risk_per_share <= 0:
            return RRMSResult(
                ticker=ticker, direction="SHORT", cmp=cmp,
                ltrp=ltrp, pivot_high=pivot_high,
                entry_price=cmp, stop_loss=stop_loss, target=ltrp,
                risk_per_share=0, reward_per_share=reward_per_share, rrr=0,
                qty=0, risk_amt=self.risk_amt, potential_profit=0,
                is_valid=False,
                rejection_reason="CMP above stop loss -- no valid short entry",
            )

        rrr = reward_per_share / risk_per_share
        qty = math.floor(self.risk_amt / risk_per_share)
        potential_profit = qty * reward_per_share

        is_valid = rrr >= self.min_rrr and qty > 0
        rejection_reason = ""
        if rrr < self.min_rrr:
            rejection_reason = f"RRR {rrr:.2f} < minimum {self.min_rrr}"
        elif qty <= 0:
            rejection_reason = "Position size is 0"

        return RRMSResult(
            ticker=ticker, direction="SHORT", cmp=cmp,
            ltrp=ltrp, pivot_high=pivot_high,
            entry_price=cmp, stop_loss=round(stop_loss, 2), target=ltrp,
            risk_per_share=round(risk_per_share, 2),
            reward_per_share=round(reward_per_share, 2),
            rrr=round(rrr, 2),
            qty=qty,
            risk_amt=round(self.risk_amt, 2),
            potential_profit=round(potential_profit, 2),
            is_valid=is_valid,
            rejection_reason=rejection_reason,
        )

    def auto_calculate(
        self,
        ticker: str,
        cmp: float,
        df: pd.DataFrame,
        direction: str = "LONG",
        lookback: int = 20,
    ) -> RRMSResult:
        """
        Auto-calculate RRMS by detecting LTRP and Pivot High from OHLCV data.
        """
        from mcp_server.swing_detector import auto_detect_levels

        levels = auto_detect_levels(df, lookback)
        return self.calculate(ticker, cmp, levels["ltrp"], levels["pivot_high"], direction)
