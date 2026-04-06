from mcp_server.mwa_scoring import (
    calculate_mwa_score,
    get_promoted_stocks,
    detect_signal_chains,
)


def test_calculate_mwa_score_empty():
    result = calculate_mwa_score({})
    assert "direction" in result
    assert "bull_score" in result
    assert "bear_score" in result
    assert "bull_pct" in result
    assert "bear_pct" in result
    assert result["direction"] == "SIDEWAYS"
    assert result["bull_score"] == 0
    assert result["bear_score"] == 0


def test_calculate_mwa_score_bullish():
    """Many bull scanners firing should produce a BULL or MILD_BULL direction."""
    scanners = {
        "swing_low": ["RELIANCE", "SBIN"],
        "upswing": ["RELIANCE", "TCS"],
        "bandwalk_highs": ["RELIANCE"],
        "llbb_bounce": ["SBIN"],
        "volume_avg": ["RELIANCE", "TCS", "SBIN"],
        "volume_spike": ["RELIANCE"],
        "breakout_50day": ["RELIANCE", "TCS"],
        "breakout_200dma": ["RELIANCE"],
        "richie_rich_breakout": ["RELIANCE"],
        "bullish_divergence": ["SBIN"],
        "failure_swing_bullish": ["SBIN"],
        "rsi_above_30": ["RELIANCE", "SBIN"],
        "near_100ma": ["TCS"],
        "near_200ma": ["SBIN"],
        # SMC bull scanners
        "smc_bos_bull": ["RELIANCE"],
        "smc_choch_bull": ["SBIN"],
        "smc_demand_ob": ["RELIANCE"],
        "smc_bullish_fvg": ["RELIANCE"],
        "smc_liq_sweep_bull": ["SBIN"],
        # Wyckoff + VSA + Harmonic bull scanners
        "wyckoff_accumulation": ["RELIANCE"],
        "wyckoff_spring": ["SBIN"],
        "wyckoff_sos": ["RELIANCE"],
        "wyckoff_test_bull": ["SBIN"],
        "vsa_selling_climax": ["RELIANCE"],
        "vsa_stopping_bull": ["SBIN"],
        "vsa_effort_bull": ["RELIANCE"],
        "harmonic_any_bull": ["RELIANCE"],
        "harmonic_gartley_bull": ["SBIN"],
        # Advanced SMC bull scanners
        "smc_breaker_bull": ["RELIANCE"],
        "smc_mitigation_bull": ["SBIN"],
        "smc_ifvg_bull": ["RELIANCE"],
        "smc_mss_bull": ["SBIN"],
        "smc_ote_bull": ["RELIANCE"],
        "smc_idm_bull": ["SBIN"],
        "smc_erl_bull": ["RELIANCE"],
        "smc_fake_bo_bull": ["SBIN"],
        "smc_ema_pullback_bull": ["RELIANCE"],
    }
    result = calculate_mwa_score(scanners)
    assert result["bull_pct"] > result["bear_pct"]
    assert result["direction"] in ("BULL", "MILD_BULL")
    assert result["allow_longs"] is True
    assert len(result["fired_bull"]) > 0


def test_calculate_mwa_score_bearish():
    """Many bear scanners firing should produce BEAR or MILD_BEAR."""
    scanners = {
        "swing_high": ["TATASTEEL"],
        "downswing": ["TATASTEEL", "SBIN"],
        "macd_sell_weekly": ["TATASTEEL"],
        "bearish_divergence": ["SBIN"],
        "failure_swing_bearish": ["SBIN"],
        "rsi_below_70": ["TATASTEEL", "SBIN"],
        "breakdown_20day": ["TATASTEEL"],
        "gap_down": ["SBIN"],
        # SMC + Wyckoff + VSA bear scanners
        "smc_bos_bear": ["TATASTEEL"],
        "smc_choch_bear": ["SBIN"],
        "smc_supply_ob": ["TATASTEEL"],
        "smc_liq_sweep_bear": ["SBIN"],
        "wyckoff_distribution": ["TATASTEEL"],
        "wyckoff_upthrust": ["SBIN"],
        "wyckoff_sow": ["TATASTEEL"],
        "vsa_buying_climax": ["SBIN"],
        "vsa_stopping_bear": ["TATASTEEL"],
        "harmonic_any_bear": ["SBIN"],
        # Advanced SMC bear scanners
        "smc_breaker_bear": ["TATASTEEL"],
        "smc_mitigation_bear": ["SBIN"],
        "smc_ifvg_bear": ["TATASTEEL"],
        "smc_mss_bear": ["SBIN"],
        "smc_ote_bear": ["TATASTEEL"],
        "smc_idm_bear": ["SBIN"],
        "smc_erl_bear": ["TATASTEEL"],
        "smc_fake_bo_bear": ["SBIN"],
        "smc_ema_pullback_bear": ["TATASTEEL"],
    }
    result = calculate_mwa_score(scanners)
    assert result["bear_pct"] > result["bull_pct"]
    assert result["direction"] in ("BEAR", "MILD_BEAR")
    assert result["allow_shorts"] is True


def test_calculate_mwa_score_old_format():
    """Support old format with dict values containing 'count' and 'stocks'."""
    scanners = {
        "swing_low": {"stocks": ["RELIANCE"], "count": 1, "weight": 2.5},
        "upswing": {"stocks": ["RELIANCE"], "count": 1, "weight": 2.5},
    }
    result = calculate_mwa_score(scanners)
    assert result["bull_score"] > 0
    assert "swing_low" in result["fired_bull"]


def test_get_promoted_stocks_threshold():
    """Stocks in 3+ bull scanners get promoted."""
    scanners = {
        "swing_low": ["RELIANCE", "SBIN"],
        "upswing": ["RELIANCE", "TCS"],
        "volume_avg": ["RELIANCE", "SBIN"],
        "supertrend_buy": ["SBIN"],
    }
    promoted = get_promoted_stocks(scanners, min_scanners=3)
    assert "RELIANCE" in promoted  # appears in 3 scanners
    assert "SBIN" in promoted      # appears in 3 scanners
    assert "TCS" not in promoted   # only in 1


def test_get_promoted_stocks_old_format():
    """Support old dict format in get_promoted_stocks."""
    scanners = {
        "swing_low": {"stocks": ["RELIANCE", "SBIN"]},
        "upswing": {"stocks": ["RELIANCE", "TCS"]},
        "volume_avg": {"stocks": ["RELIANCE", "SBIN"]},
    }
    promoted = get_promoted_stocks(scanners, min_scanners=3)
    assert "RELIANCE" in promoted


def test_detect_signal_chains_divergence_bull():
    """Full bullish divergence ladder should be detected."""
    fired = {
        "bull": ["bullish_divergence", "failure_swing_bullish", "rsi_above_30"],
        "bear": [],
    }
    chains = detect_signal_chains(fired)
    names = [c["name"] for c in chains]
    assert "divergence_bull" in names
    chain = next(c for c in chains if c["name"] == "divergence_bull")
    assert chain["complete"] is True
    assert chain["boost"] == 20


def test_detect_signal_chains_partial():
    """75%+ match should be detected as partial chain."""
    fired = {
        "bull": ["bullish_divergence", "failure_swing_bullish"],  # 2/3 = 67% — NOT enough
        "bear": [],
    }
    chains = detect_signal_chains(fired)
    # 2/3 < 75%, so divergence_bull should NOT appear
    names = [c["name"] for c in chains]
    assert "divergence_bull" not in names


def test_detect_signal_chains_strongest_short():
    """Full strongest_short chain detection."""
    fired = {
        "bull": [],
        "bear": ["swing_high", "downswing", "bearish_divergence",
                 "failure_swing_bearish", "macd_sell_weekly"],
    }
    chains = detect_signal_chains(fired)
    names = [c["name"] for c in chains]
    assert "strongest_short" in names
    chain = next(c for c in chains if c["name"] == "strongest_short")
    assert chain["complete"] is True
    assert chain["boost"] == 25


def test_detect_signal_chains_empty():
    """No fired scanners = no chains."""
    chains = detect_signal_chains({"bull": [], "bear": []})
    assert chains == []
