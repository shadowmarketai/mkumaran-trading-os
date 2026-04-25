"""
MKUMARAN Trading OS — Risk Guard

Pre-trade halt gates that complement the in-process kill switch
(`order_manager.KillSwitchState`) and the per-order portfolio checks
(`portfolio_risk.validate_portfolio_risk`).

Adds five checks the prior layers don't:

  1. Weekly loss limit  — halt for the ISO-week if cumulative realised
                          P&L drops below -5% of the week's starting
                          capital. Resets every Monday.
  2. Margin utilisation — warn at 70% capital deployed, halt new orders
                          at 85%.
  3. Broker heartbeat   — halt all orders if the last successful broker
                          round-trip is older than 30s (dead-man switch).
  4. Spot-price sanity  — reject orders whose intended price differs
                          from last-traded-price by more than 5%.
  5. Spread sanity      — reject orders when bid-ask spread exceeds
                          0.5% of mid (illiquid/stale book).

Money math runs in Decimal; thresholds stay float because they're
dimensionless ratios compared against Decimal fractions.

Designed so OrderManager can consult a singleton instance:

    from mcp_server.risk_guard import RiskGuard

    guard = RiskGuard()
    guard.record_broker_heartbeat()              # on every successful call
    halt, reason = guard.check(capital, exposure)
    if halt: return error(reason)

Each check is also exposed as a stateless function so they can be
called from elsewhere (n8n workers, scanner cron, etc.) without
sharing state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from mcp_server.money import Numeric, to_money

logger = logging.getLogger(__name__)


# ── Halt thresholds ──────────────────────────────────────────
WEEKLY_LOSS_LIMIT_PCT = -0.05       # -5% of week's starting capital
MARGIN_WARN_PCT = 0.70              # warn at 70% deployed
MARGIN_HALT_PCT = 0.85              # halt new orders at 85% deployed
BROKER_HEARTBEAT_TIMEOUT_S = 30     # dead-man switch after 30s silence
SPOT_SANITY_MAX_DEV_PCT = 0.05      # reject orders > 5% off LTP
SPREAD_SANITY_MAX_PCT = 0.005       # reject when spread > 0.5% of mid


def _iso_week_start(d: date) -> date:
    """Monday of the ISO week containing `d`."""
    return d - timedelta(days=d.weekday())


@dataclass
class RiskGuardState:
    """Tracks weekly P&L + broker heartbeat for halt gates."""

    week_start: date = field(default_factory=lambda: _iso_week_start(date.today()))
    weekly_starting_capital: Decimal = field(default_factory=lambda: Decimal("0"))
    weekly_realized_pnl: Decimal = field(default_factory=lambda: Decimal("0"))
    last_broker_heartbeat: datetime | None = None

    is_weekly_halted: bool = False
    weekly_halt_reason: str = ""

    def _roll_week_if_needed(self, capital: Decimal) -> None:
        today = date.today()
        current_week_start = _iso_week_start(today)
        if current_week_start != self.week_start:
            self.week_start = current_week_start
            self.weekly_starting_capital = capital
            self.weekly_realized_pnl = Decimal("0")
            self.is_weekly_halted = False
            self.weekly_halt_reason = ""
            logger.info("RiskGuard: new ISO week, resetting weekly P&L")

        if self.weekly_starting_capital <= 0:
            self.weekly_starting_capital = capital


class RiskGuard:
    """Stateful risk gate. One per OrderManager."""

    def __init__(self) -> None:
        self.state = RiskGuardState()

    # ── Recording ─────────────────────────────────────────────

    def record_broker_heartbeat(self, when: datetime | None = None) -> None:
        """Call after every successful broker round-trip."""
        self.state.last_broker_heartbeat = when or datetime.utcnow()

    def record_pnl(self, pnl: Numeric, capital: Numeric) -> None:
        """Add a realised-P&L delta to the weekly tally."""
        cap_dec = to_money(capital)
        self.state._roll_week_if_needed(cap_dec)
        self.state.weekly_realized_pnl += to_money(pnl)
        # Re-evaluate weekly halt after pnl moves
        self.check_weekly_loss(cap_dec)

    # ── Individual checks (each returns (halt, reason)) ─────

    def check_weekly_loss(self, capital: Numeric) -> tuple[bool, str | None]:
        cap_dec = to_money(capital)
        self.state._roll_week_if_needed(cap_dec)

        if self.state.weekly_starting_capital <= 0:
            return False, None

        weekly_pct = self.state.weekly_realized_pnl / self.state.weekly_starting_capital
        if weekly_pct <= Decimal(str(WEEKLY_LOSS_LIMIT_PCT)):
            self.state.is_weekly_halted = True
            self.state.weekly_halt_reason = (
                f"Weekly loss limit hit: {weekly_pct:.1%} "
                f"(limit: {WEEKLY_LOSS_LIMIT_PCT:.1%})"
            )
            logger.warning("RISK GUARD WEEKLY HALT: %s", self.state.weekly_halt_reason)
            return True, self.state.weekly_halt_reason
        return False, None

    def check_margin(
        self, capital: Numeric, deployed: Numeric,
    ) -> tuple[bool, str | None]:
        """Halt new orders when deployed/capital > MARGIN_HALT_PCT."""
        cap_dec = to_money(capital)
        dep_dec = to_money(deployed)
        if cap_dec <= 0:
            return False, None
        ratio = dep_dec / cap_dec
        if ratio >= Decimal(str(MARGIN_HALT_PCT)):
            return True, f"Margin utilisation {ratio:.1%} >= halt threshold {MARGIN_HALT_PCT:.0%}"
        if ratio >= Decimal(str(MARGIN_WARN_PCT)):
            logger.warning(
                "RISK GUARD WARN: margin utilisation %.1f%% (warn %.0f%%, halt %.0f%%)",
                float(ratio) * 100, MARGIN_WARN_PCT * 100, MARGIN_HALT_PCT * 100,
            )
        return False, None

    def check_broker_heartbeat(
        self, now: datetime | None = None,
    ) -> tuple[bool, str | None]:
        """Halt if the last broker round-trip is older than the timeout."""
        if self.state.last_broker_heartbeat is None:
            # Never recorded — be permissive on first boot. Caller is expected
            # to record a heartbeat after `_validate_broker` succeeds.
            return False, None
        now = now or datetime.utcnow()
        age = (now - self.state.last_broker_heartbeat).total_seconds()
        if age > BROKER_HEARTBEAT_TIMEOUT_S:
            return True, (
                f"Broker heartbeat stale: {age:.0f}s > {BROKER_HEARTBEAT_TIMEOUT_S}s "
                f"(dead-man switch)"
            )
        return False, None

    # ── Composite gate ────────────────────────────────────────

    def check(
        self,
        capital: Numeric,
        deployed: Numeric = Decimal("0"),
        now: datetime | None = None,
    ) -> tuple[bool, str | None]:
        """Run all halt gates. First trip wins."""
        for name, fn in (
            ("weekly_loss", lambda: self.check_weekly_loss(capital)),
            ("margin", lambda: self.check_margin(capital, deployed)),
            ("heartbeat", lambda: self.check_broker_heartbeat(now)),
        ):
            halt, reason = fn()
            if halt:
                return True, f"{name}: {reason}"
        return False, None


# ── Stateless per-order checks ──────────────────────────────


def validate_spot_sanity(
    intended_price: Numeric,
    last_traded_price: Numeric,
    max_dev_pct: float = SPOT_SANITY_MAX_DEV_PCT,
) -> tuple[bool, str | None]:
    """Reject orders whose limit/market-implied price strays > max_dev from LTP.

    Catches fat-finger entries (off-by-decimal) and stale signals against
    a fast-moved market.
    """
    intended = to_money(intended_price)
    ltp = to_money(last_traded_price)
    if ltp <= 0:
        return True, None  # No LTP yet — let the order through; broker will reject if invalid.
    dev = abs(intended - ltp) / ltp
    if dev > Decimal(str(max_dev_pct)):
        return False, (
            f"Spot sanity: order price {intended} differs from LTP {ltp} "
            f"by {dev:.1%} (max {max_dev_pct:.0%})"
        )
    return True, None


def validate_spread_acceptable(
    bid: Numeric,
    ask: Numeric,
    max_spread_pct: float = SPREAD_SANITY_MAX_PCT,
) -> tuple[bool, str | None]:
    """Reject when bid-ask spread is wider than `max_spread_pct` of mid.

    Wide spreads usually mean the book is illiquid or stale; market orders
    in that state are how slippage anomalies happen.
    """
    bid_dec = to_money(bid)
    ask_dec = to_money(ask)
    if bid_dec <= 0 or ask_dec <= 0 or ask_dec < bid_dec:
        return False, "Spread sanity: invalid quote (bid/ask <= 0 or crossed)"
    mid = (bid_dec + ask_dec) / 2
    if mid <= 0:
        return False, None
    spread_pct = (ask_dec - bid_dec) / mid
    if spread_pct > Decimal(str(max_spread_pct)):
        return False, (
            f"Spread sanity: bid-ask {bid_dec}/{ask_dec} = {spread_pct:.2%} "
            f"of mid (max {max_spread_pct:.1%})"
        )
    return True, None
