from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from decimal import Decimal

import pandas as pd

from mcp_server.config import settings
from mcp_server.money import Numeric, round_tick, to_money

logger = logging.getLogger(__name__)


@dataclass
class RRMSResult:
    """Result of an RRMS calculation.

    Money-shaped fields are Decimal (rounded to exchange tick via
    mcp_server.money.round_tick). `rrr` is dimensionless but kept as
    Decimal so a single exact-arithmetic chain runs from inputs to
    output. Integer position size, boolean validity flag, and string
    ticker/direction/reason stay in their natural types.
    """
    ticker: str
    direction: str
    cmp: Decimal
    ltrp: Decimal
    pivot_high: Decimal
    entry_price: Decimal
    stop_loss: Decimal
    target: Decimal
    risk_per_share: Decimal
    reward_per_share: Decimal
    rrr: Decimal
    qty: int
    risk_amt: Decimal
    potential_profit: Decimal
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
        capital: Numeric = 0,
        risk_pct: Numeric = 0,
        min_rrr: float = 0,
    ):
        # `or` semantics: a zero-valued override falls back to settings.
        self.capital: Decimal = to_money(capital) if capital else settings.RRMS_CAPITAL
        self.risk_pct: Decimal = to_money(risk_pct) if risk_pct else settings.RRMS_RISK_PCT
        self.min_rrr: float = min_rrr or settings.RRMS_MIN_RRR
        self.risk_amt: Decimal = self.capital * self.risk_pct

    def calculate(
        self,
        ticker: str,
        cmp: Numeric,
        ltrp: Numeric,
        pivot_high: Numeric,
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
        cmp_d = to_money(cmp)
        ltrp_d = to_money(ltrp)
        pivot_d = to_money(pivot_high)
        if direction == "LONG":
            return self._calculate_long(ticker, cmp_d, ltrp_d, pivot_d)
        else:
            return self._calculate_short(ticker, cmp_d, ltrp_d, pivot_d)

    def _calculate_long(
        self,
        ticker: str,
        cmp: Decimal,
        ltrp: Decimal,
        pivot_high: Decimal,
    ) -> RRMSResult:
        """Calculate for LONG position."""
        # Entry trigger: CMP must be within 2% of LTRP
        entry_zone_upper = ltrp * Decimal("1.02")
        zero = Decimal("0")

        if cmp > entry_zone_upper:
            return RRMSResult(
                ticker=ticker, direction="LONG", cmp=cmp,
                ltrp=ltrp, pivot_high=pivot_high,
                entry_price=cmp, stop_loss=zero, target=pivot_high,
                risk_per_share=zero, reward_per_share=zero, rrr=zero,
                qty=0, risk_amt=self.risk_amt, potential_profit=zero,
                is_valid=False,
                rejection_reason=f"CMP {cmp:.2f} > entry zone {entry_zone_upper:.2f} (LTRP*1.02)",
            )

        # Stop loss: 0.5% below LTRP
        stop_loss = ltrp * Decimal("0.995")

        # Risk and reward
        risk_per_share = cmp - stop_loss
        reward_per_share = pivot_high - cmp

        if risk_per_share <= 0:
            return RRMSResult(
                ticker=ticker, direction="LONG", cmp=cmp,
                ltrp=ltrp, pivot_high=pivot_high,
                entry_price=cmp, stop_loss=stop_loss, target=pivot_high,
                risk_per_share=zero, reward_per_share=reward_per_share, rrr=zero,
                qty=0, risk_amt=self.risk_amt, potential_profit=zero,
                is_valid=False,
                rejection_reason="CMP below stop loss -- no valid entry",
            )

        rrr = reward_per_share / risk_per_share

        # Position sizing — both operands are Decimal, math.floor truncates to int.
        qty = math.floor(self.risk_amt / risk_per_share)
        potential_profit = qty * reward_per_share

        # Validate minimum RRR (Decimal vs float comparison is supported)
        is_valid = rrr >= self.min_rrr and qty > 0
        rejection_reason = ""
        if rrr < self.min_rrr:
            rejection_reason = f"RRR {rrr:.2f} < minimum {self.min_rrr}"
        elif qty <= 0:
            rejection_reason = "Position size is 0 -- risk per share too large"

        result = RRMSResult(
            ticker=ticker, direction="LONG", cmp=cmp,
            ltrp=ltrp, pivot_high=pivot_high,
            entry_price=cmp, stop_loss=round_tick(stop_loss, ticker), target=pivot_high,
            risk_per_share=round_tick(risk_per_share, ticker),
            reward_per_share=round_tick(reward_per_share, ticker),
            rrr=round_tick(rrr, "NSE"),  # dimensionless ratio, 2dp
            qty=qty,
            risk_amt=round_tick(self.risk_amt, ticker),
            potential_profit=round_tick(potential_profit, ticker),
            is_valid=is_valid,
            rejection_reason=rejection_reason,
        )

        logger.info(
            "RRMS %s: %s @ %.2f | SL: %.2f | Target: %.2f | RRR: %.2f | Qty: %d | Valid: %s",
            ticker, "LONG", cmp, stop_loss, pivot_high, rrr, qty, is_valid,
        )

        return result

    def _calculate_short(
        self,
        ticker: str,
        cmp: Decimal,
        ltrp: Decimal,
        pivot_high: Decimal,
    ) -> RRMSResult:
        """Calculate for SHORT position (reversed logic)."""
        zero = Decimal("0")
        # For shorts: entry near pivot_high, target at ltrp, SL above pivot_high
        entry_zone_lower = pivot_high * Decimal("0.98")

        if cmp < entry_zone_lower:
            return RRMSResult(
                ticker=ticker, direction="SHORT", cmp=cmp,
                ltrp=ltrp, pivot_high=pivot_high,
                entry_price=cmp, stop_loss=zero, target=ltrp,
                risk_per_share=zero, reward_per_share=zero, rrr=zero,
                qty=0, risk_amt=self.risk_amt, potential_profit=zero,
                is_valid=False,
                rejection_reason=f"CMP {cmp:.2f} < entry zone {entry_zone_lower:.2f} (pivot*0.98)",
            )

        stop_loss = pivot_high * Decimal("1.005")
        risk_per_share = stop_loss - cmp
        reward_per_share = cmp - ltrp

        if risk_per_share <= 0:
            return RRMSResult(
                ticker=ticker, direction="SHORT", cmp=cmp,
                ltrp=ltrp, pivot_high=pivot_high,
                entry_price=cmp, stop_loss=stop_loss, target=ltrp,
                risk_per_share=zero, reward_per_share=reward_per_share, rrr=zero,
                qty=0, risk_amt=self.risk_amt, potential_profit=zero,
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
            entry_price=cmp, stop_loss=round_tick(stop_loss, ticker), target=ltrp,
            risk_per_share=round_tick(risk_per_share, ticker),
            reward_per_share=round_tick(reward_per_share, ticker),
            rrr=round_tick(rrr, "NSE"),
            qty=qty,
            risk_amt=round_tick(self.risk_amt, ticker),
            potential_profit=round_tick(potential_profit, ticker),
            is_valid=is_valid,
            rejection_reason=rejection_reason,
        )

    def auto_calculate(
        self,
        ticker: str,
        cmp: Numeric,
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
