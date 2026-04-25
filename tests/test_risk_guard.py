"""Tests for mcp_server.risk_guard — weekly loss, margin, heartbeat, spot/spread sanity."""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from mcp_server.risk_guard import (
    BROKER_HEARTBEAT_TIMEOUT_S,
    MARGIN_HALT_PCT,
    MARGIN_WARN_PCT,
    SPOT_SANITY_MAX_DEV_PCT,
    SPREAD_SANITY_MAX_PCT,
    WEEKLY_LOSS_LIMIT_PCT,
    RiskGuard,
    _iso_week_start,
    validate_spot_sanity,
    validate_spread_acceptable,
)


# ── Weekly loss ─────────────────────────────────────────────


def test_weekly_loss_does_not_trigger_below_limit():
    g = RiskGuard()
    cap = Decimal("100000")
    g.record_pnl(Decimal("-2000"), cap)  # -2% — below the 5% halt
    halt, reason = g.check_weekly_loss(cap)
    assert halt is False
    assert reason is None


def test_weekly_loss_triggers_at_limit():
    g = RiskGuard()
    cap = Decimal("100000")
    # Drive below the -5% threshold
    g.record_pnl(Decimal("-5500"), cap)
    halt, reason = g.check_weekly_loss(cap)
    assert halt is True
    assert "Weekly loss" in reason
    assert g.state.is_weekly_halted is True


def test_weekly_loss_resets_on_new_week(monkeypatch):
    # Initialise the guard "last week" then move the clock to this week.
    g = RiskGuard()
    last_week = _iso_week_start(date.today()) - timedelta(days=7)
    g.state.week_start = last_week
    g.state.weekly_starting_capital = Decimal("100000")
    g.state.weekly_realized_pnl = Decimal("-9000")  # -9% — would normally halt
    g.state.is_weekly_halted = True

    halt, _ = g.check_weekly_loss(Decimal("100000"))
    assert halt is False, "New ISO week must reset the weekly halt"
    assert g.state.weekly_realized_pnl == Decimal("0")
    assert g.state.week_start == _iso_week_start(date.today())


def test_weekly_loss_constant_is_negative_5pct():
    # Defensive: catch accidental sign flip on a refactor.
    assert WEEKLY_LOSS_LIMIT_PCT == -0.05


# ── Margin utilisation ──────────────────────────────────────


def test_margin_below_warn_passes():
    g = RiskGuard()
    halt, _ = g.check_margin(capital=Decimal("100000"), deployed=Decimal("50000"))
    assert halt is False


def test_margin_at_halt_threshold_blocks():
    g = RiskGuard()
    halt, reason = g.check_margin(
        capital=Decimal("100000"),
        deployed=Decimal("85000"),  # exactly 85%
    )
    assert halt is True
    assert "Margin utilisation" in reason


def test_margin_warn_threshold_logs_but_passes(caplog):
    g = RiskGuard()
    with caplog.at_level("WARNING"):
        halt, _ = g.check_margin(
            capital=Decimal("100000"),
            deployed=Decimal("75000"),  # 75% — between warn and halt
        )
    assert halt is False
    assert any("margin utilisation" in m.lower() for m in caplog.messages), (
        "Margin warn threshold must log a warning"
    )


def test_margin_zero_capital_does_not_explode():
    g = RiskGuard()
    halt, _ = g.check_margin(capital=Decimal("0"), deployed=Decimal("0"))
    assert halt is False


def test_margin_thresholds_ordered():
    assert MARGIN_WARN_PCT < MARGIN_HALT_PCT


# ── Broker heartbeat ────────────────────────────────────────


def test_heartbeat_never_recorded_is_permissive():
    g = RiskGuard()
    halt, _ = g.check_broker_heartbeat()
    assert halt is False, "First-boot must not block trading before any broker call"


def test_heartbeat_fresh_passes():
    g = RiskGuard()
    g.record_broker_heartbeat()
    halt, _ = g.check_broker_heartbeat()
    assert halt is False


def test_heartbeat_stale_blocks():
    g = RiskGuard()
    # Backdate the heartbeat past the timeout
    g.record_broker_heartbeat(when=datetime.utcnow() - timedelta(seconds=BROKER_HEARTBEAT_TIMEOUT_S + 5))
    halt, reason = g.check_broker_heartbeat()
    assert halt is True
    assert "stale" in reason.lower()


# ── Composite check ─────────────────────────────────────────


def test_composite_check_returns_first_failing_gate():
    g = RiskGuard()
    cap = Decimal("100000")
    # Trip weekly loss + margin simultaneously; weekly is the first listed gate.
    g.record_pnl(Decimal("-6000"), cap)
    halt, reason = g.check(capital=cap, deployed=Decimal("90000"))
    assert halt is True
    assert reason.startswith("weekly_loss")


def test_composite_check_passes_when_clean():
    g = RiskGuard()
    g.record_broker_heartbeat()
    halt, reason = g.check(capital=Decimal("100000"), deployed=Decimal("10000"))
    assert halt is False
    assert reason is None


# ── Spot-price sanity ──────────────────────────────────────


def test_spot_sanity_accepts_close_price():
    ok, err = validate_spot_sanity(intended_price=100, last_traded_price=101)
    assert ok is True
    assert err is None


def test_spot_sanity_rejects_5pct_off():
    ok, err = validate_spot_sanity(intended_price=100, last_traded_price=110)
    assert ok is False
    assert "Spot sanity" in err


def test_spot_sanity_zero_ltp_is_permissive():
    ok, _ = validate_spot_sanity(intended_price=100, last_traded_price=0)
    assert ok is True, "Zero LTP means no quote yet — let broker reject the order"


def test_spot_sanity_constant_is_5pct():
    assert SPOT_SANITY_MAX_DEV_PCT == 0.05


# ── Spread sanity ──────────────────────────────────────────


def test_spread_acceptable_tight():
    ok, _ = validate_spread_acceptable(bid=Decimal("100.00"), ask=Decimal("100.10"))
    assert ok is True


def test_spread_rejected_wide():
    ok, err = validate_spread_acceptable(bid=Decimal("100.00"), ask=Decimal("101.00"))  # 1% spread
    assert ok is False
    assert "Spread sanity" in err


def test_spread_rejects_crossed_book():
    ok, err = validate_spread_acceptable(bid=Decimal("101"), ask=Decimal("100"))
    assert ok is False
    assert "crossed" in err.lower() or "invalid" in err.lower()


def test_spread_constant_is_50bps():
    assert SPREAD_SANITY_MAX_PCT == 0.005


# ── Helper ─────────────────────────────────────────────────


def test_iso_week_start_is_monday():
    # 2026-04-25 is a Saturday; Monday of that ISO week is 2026-04-20.
    assert _iso_week_start(date(2026, 4, 25)) == date(2026, 4, 20)
    # Already Monday — returns same date.
    assert _iso_week_start(date(2026, 4, 20)) == date(2026, 4, 20)


# ── Integration with order_manager (smoke) ────────────────


def test_record_pnl_updates_weekly_tally():
    g = RiskGuard()
    cap = Decimal("100000")
    g.record_pnl(Decimal("-1000"), cap)
    g.record_pnl(Decimal("-2000"), cap)
    assert g.state.weekly_realized_pnl == Decimal("-3000")
    halt, _ = g.check_weekly_loss(cap)
    assert halt is False  # -3% still below the -5% halt


def test_record_pnl_accumulates_to_halt():
    g = RiskGuard()
    cap = Decimal("100000")
    for _ in range(6):
        g.record_pnl(Decimal("-1000"), cap)
    # -6% cumulative — must be halted by the auto re-eval inside record_pnl
    assert g.state.is_weekly_halted is True


@pytest.mark.parametrize("intended,ltp,want_ok", [
    (100, 100, True),    # exact match
    (100, 96, True),     # |100-96|/96 = 4.17% — within
    (100, 95, False),    # |100-95|/95 = 5.26% — over
    (100, 90, False),    # 11% — clear reject
    (100, 105, True),    # |100-105|/105 = 4.76% — within
    (100, 106, False),   # |100-106|/106 = 5.66% — over
])
def test_spot_sanity_threshold_bands(intended, ltp, want_ok):
    ok, _ = validate_spot_sanity(intended, ltp)
    assert ok is want_ok
