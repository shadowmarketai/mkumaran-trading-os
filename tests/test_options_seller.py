"""Tests for mcp_server.options_seller — IV engine, strike selector, adjustment engine."""

import numpy as np

from mcp_server.options_seller.iv_engine import (
    DELTA_TARGET,
    PERCENTILE_CRUSHED,
    PERCENTILE_ELEVATED,
    PERCENTILE_EXTREME,
    PERCENTILE_LOW,
    SUGGESTED_DTE,
    IVRegime,
    _percentile_rank,
    classify_iv,
)
from mcp_server.options_seller.adjustment_engine import (
    AdjustmentAction,
    LivePositionSnapshot,
    evaluate,
)
from mcp_server.options_seller.strike_selector import (
    LOT_SIZES,
    StranglePosition,
    _lot_size,
    _nearest_strike,
)


# ── IV Engine ────────────────────────────────────────────────

def _history(low: float, high: float, n: int = 252) -> np.ndarray:
    """Uniform history from low to high — predictable percentile ranks."""
    return np.linspace(low, high, n)


def test_percentile_rank_below_all():
    hist = _history(15.0, 25.0)
    assert _percentile_rank(hist, 10.0) == 0.0


def test_percentile_rank_above_all():
    hist = _history(15.0, 25.0)
    assert _percentile_rank(hist, 30.0) == 100.0


def test_percentile_rank_midpoint():
    hist = _history(0.0, 100.0)
    rank = _percentile_rank(hist, 50.0)
    assert 48.0 < rank < 52.0


def test_percentile_rank_empty_history():
    assert _percentile_rank(np.array([]), 20.0) == 50.0


def test_classify_crushed():
    hist = _history(10.0, 40.0)   # 10th VIX = 10.0
    # VIX=10 → 0th percentile → CRUSHED
    regime = classify_iv("BANKNIFTY", 10.0, hist[-90:], hist)
    assert regime.label == "CRUSHED"
    assert regime.sell_premium_ok is False
    assert regime.suggested_dte == 0
    assert regime.delta_target == 0.0


def test_classify_low():
    hist = _history(10.0, 40.0)
    # VIX=16 → ~20th percentile → LOW
    regime = classify_iv("NIFTY", 16.0, hist[-90:], hist)
    assert regime.label == "LOW"
    assert regime.sell_premium_ok is True
    assert regime.suggested_dte == SUGGESTED_DTE["LOW"]


def test_classify_normal():
    hist = _history(10.0, 40.0)
    # VIX=25 → ~50th percentile → NORMAL
    regime = classify_iv("NIFTY", 25.0, hist[-90:], hist)
    assert regime.label == "NORMAL"
    assert regime.sell_premium_ok is True
    assert regime.suggested_dte == SUGGESTED_DTE["NORMAL"]


def test_classify_elevated():
    hist = _history(10.0, 40.0)
    # VIX=33 → ~77th percentile → ELEVATED
    regime = classify_iv("NIFTY", 33.0, hist[-90:], hist)
    assert regime.label == "ELEVATED"
    assert regime.sell_premium_ok is True


def test_classify_extreme():
    hist = _history(10.0, 40.0)
    # VIX=39 → ~97th percentile → EXTREME
    regime = classify_iv("NIFTY", 39.0, hist[-90:], hist)
    assert regime.label == "EXTREME"
    assert regime.sell_premium_ok is False
    assert regime.suggested_dte == 0


def test_classify_populates_all_fields():
    hist = _history(12.0, 30.0)
    regime = classify_iv("BANKNIFTY", 21.0, hist[-90:], hist, atm_iv=0.18)
    assert isinstance(regime, IVRegime)
    assert regime.instrument == "BANKNIFTY"
    assert regime.vix_current == 21.0
    assert regime.atm_iv == 0.18
    assert 0.0 <= regime.vix_percentile_90d <= 100.0
    assert 0.0 <= regime.vix_percentile_1y <= 100.0


def test_as_dict_keys():
    hist = _history(10.0, 30.0)
    regime = classify_iv("NIFTY", 20.0, hist[-90:], hist)
    d = regime.as_dict()
    for k in ("instrument", "regime", "vix_current", "vix_percentile_90d",
              "vix_percentile_1y", "atm_iv", "sell_premium_ok",
              "suggested_dte", "delta_target", "reason"):
        assert k in d


def test_thresholds_ordered():
    assert PERCENTILE_CRUSHED < PERCENTILE_LOW < PERCENTILE_ELEVATED < PERCENTILE_EXTREME


def test_crushed_and_extreme_have_zero_delta_target():
    assert DELTA_TARGET["CRUSHED"] == 0.0
    assert DELTA_TARGET["EXTREME"] == 0.0


# ── Strike Selector ──────────────────────────────────────────


def test_lot_sizes_all_6_instruments():
    for inst in ("BANKNIFTY", "NIFTY", "MIDCPNIFTY", "FINNIFTY", "SENSEX", "BANKEX"):
        assert _lot_size(inst) > 0


def test_lot_size_unknown_fallback():
    from mcp_server.options_seller.strike_selector import DEFAULT_LOT_SIZE
    assert _lot_size("UNKNOWN") == DEFAULT_LOT_SIZE


def test_nearest_strike():
    strikes = [44800.0, 44900.0, 45000.0, 45100.0, 45200.0]
    assert _nearest_strike(strikes, 44950.0) in (44900.0, 45000.0)
    assert _nearest_strike(strikes, 45250.0) == 45200.0


def test_build_strangle_iron_condor():
    """Smoke test with a synthetic chain — verify structure is returned."""
    from mcp_server.options_seller.strike_selector import build_strangle
    from mcp_server.options_greeks import calculate_greeks

    spot = 45000.0
    dte  = 5

    # Build synthetic chain around spot
    chain: dict = {}
    for strike in range(43000, 47200, 100):
        ce = calculate_greeks(spot, float(strike), dte, volatility=0.18, option_type="CE")
        pe = calculate_greeks(spot, float(strike), dte, volatility=0.18, option_type="PE")
        chain[float(strike)] = {
            "CE": {"ltp": max(ce.price, 0.5), "iv": 0.18},
            "PE": {"ltp": max(pe.price, 0.5), "iv": 0.18},
        }

    pos = build_strangle(
        instrument="BANKNIFTY",
        spot=spot,
        chain=chain,
        dte=dte,
        target_delta=0.15,
        min_premium=10.0,  # low threshold for test
        structure="IRON_CONDOR",
    )
    assert pos is not None
    assert isinstance(pos, StranglePosition)
    assert pos.structure == "IRON_CONDOR"
    assert len(pos.legs) == 4               # 2 short + 2 long
    assert pos.net_credit > 0
    assert pos.short_call_strike > pos.short_put_strike   # call above put
    assert pos.breakeven_upper > pos.short_call_strike
    assert pos.breakeven_lower < pos.short_put_strike


def test_build_strangle_naked():
    from mcp_server.options_seller.strike_selector import build_strangle
    from mcp_server.options_greeks import calculate_greeks

    spot = 20000.0
    chain = {}
    for strike in range(18000, 22100, 100):
        ce = calculate_greeks(spot, float(strike), 5, volatility=0.16, option_type="CE")
        pe = calculate_greeks(spot, float(strike), 5, volatility=0.16, option_type="PE")
        chain[float(strike)] = {
            "CE": {"ltp": max(ce.price, 0.5), "iv": 0.16},
            "PE": {"ltp": max(pe.price, 0.5), "iv": 0.16},
        }

    pos = build_strangle(
        instrument="NIFTY",
        spot=spot,
        chain=chain,
        dte=5,
        target_delta=0.15,
        min_premium=5.0,
        structure="NAKED_STRANGLE",
    )
    assert pos is not None
    assert pos.structure == "NAKED_STRANGLE"
    assert len(pos.legs) == 2   # only short legs


def test_build_strangle_sparse_chain_returns_none():
    from mcp_server.options_seller.strike_selector import build_strangle
    pos = build_strangle("NIFTY", 20000, chain={}, dte=5)
    assert pos is None


def test_strangle_as_dict_keys():
    from mcp_server.options_seller.strike_selector import build_strangle
    from mcp_server.options_greeks import calculate_greeks

    spot = 45000.0
    chain = {}
    for strike in range(43000, 47200, 100):
        ce = calculate_greeks(spot, float(strike), 5, volatility=0.18, option_type="CE")
        pe = calculate_greeks(spot, float(strike), 5, volatility=0.18, option_type="PE")
        chain[float(strike)] = {
            "CE": {"ltp": max(ce.price, 0.5), "iv": 0.18},
            "PE": {"ltp": max(pe.price, 0.5), "iv": 0.18},
        }
    pos = build_strangle("BANKNIFTY", spot, chain, dte=5, min_premium=5.0)
    assert pos is not None
    d = pos.as_dict()
    for k in ("instrument", "structure", "net_credit", "max_loss",
              "breakeven_upper", "breakeven_lower", "legs"):
        assert k in d


# ── Adjustment Engine ────────────────────────────────────────


def _snap(
    spot: float = 45000,
    sc_strike: float = 45800,
    sp_strike: float = 44200,
    sc_delta: float = 0.14,
    sp_delta: float = -0.14,
    sc_entry: float = 80,
    sp_entry: float = 75,
    sc_current: float = 60,
    sp_current: float = 55,
    credit: float = 155,
    pnl: float = 40,
    dte_remaining: float = 4,
) -> LivePositionSnapshot:
    return LivePositionSnapshot(
        instrument="BANKNIFTY",
        spot=spot,
        short_call_strike=sc_strike,
        short_put_strike=sp_strike,
        short_call_delta=sc_delta,
        short_put_delta=sp_delta,
        short_call_entry_premium=sc_entry,
        short_put_entry_premium=sp_entry,
        short_call_current_premium=sc_current,
        short_put_current_premium=sp_current,
        credit_received=credit,
        current_pnl=pnl,
        dte_remaining=dte_remaining,
    )


def test_hold_when_all_parameters_ok():
    decision = evaluate(_snap(), event_horizon_hours=0)   # disable event check
    assert decision.action == AdjustmentAction.HOLD
    assert decision.rule == "default"


def test_rule_2_strike_imminent():
    # Spot very close to call strike
    s = _snap(spot=45780, sc_strike=45800)
    decision = evaluate(s, event_horizon_hours=0)
    assert decision.action == AdjustmentAction.CLOSE_TESTED_LEG
    assert decision.rule == "rule_2"


def test_rule_3_delta_breach():
    # Call delta crept to 0.35 (>0.30 threshold)
    s = _snap(sc_delta=0.35, spot=45500, sc_strike=45800)
    decision = evaluate(s, event_horizon_hours=0)
    assert decision.action == AdjustmentAction.ROLL_TESTED
    assert decision.rule == "rule_3"


def test_rule_4_premium_decay_reload():
    # Untested side decayed to 5% of entry
    s = _snap(
        sp_current=3.75,   # 5% of sp_entry=75
        sp_delta=-0.04,    # very small — far OTM, nearly worthless
        dte_remaining=3,
    )
    decision = evaluate(s, event_horizon_hours=0)
    assert decision.action == AdjustmentAction.ROLL_UNTESTED
    assert decision.rule == "rule_4"


def test_rule_4_not_fired_when_dte_too_low():
    s = _snap(sp_current=3.75, dte_remaining=1)
    decision = evaluate(s, event_horizon_hours=0)
    # Rule 4 requires dte >= 2 — should not fire
    assert decision.rule != "rule_4"


def test_rule_5_max_loss_breach():
    s = _snap(credit=100, pnl=-220)   # -2.2× credit
    decision = evaluate(s, event_horizon_hours=0)
    assert decision.action == AdjustmentAction.CLOSE_ALL
    assert decision.rule == "rule_5"


def test_rule_priority_imminent_beats_delta_breach():
    # Both rule 2 and rule 3 conditions are true — rule 2 must win (lower number)
    s = _snap(spot=45790, sc_strike=45800, sc_delta=0.40)
    decision = evaluate(s, event_horizon_hours=0)
    assert decision.rule == "rule_2"


def test_decision_as_dict_keys():
    d = evaluate(_snap(), event_horizon_hours=0).as_dict()
    for k in ("action", "rule", "reason", "tested_leg", "untested_leg"):
        assert k in d


def test_adjustment_action_values_are_strings():
    for action in AdjustmentAction:
        assert isinstance(action.value, str)


# ── LOT_SIZES coverage ────────────────────────────────────────


def test_lot_sizes_dict_has_all_6_instruments():
    required = {"BANKNIFTY", "NIFTY", "MIDCPNIFTY", "FINNIFTY", "SENSEX", "BANKEX"}
    assert required.issubset(LOT_SIZES.keys())


def test_banknifty_lot_size_is_15():
    assert LOT_SIZES["BANKNIFTY"] == 15


def test_nifty_lot_size_is_25():
    assert LOT_SIZES["NIFTY"] == 25
