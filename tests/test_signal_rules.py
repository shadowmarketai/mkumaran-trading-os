"""Tests for Signal Rules Engine."""

from mcp_server.signal_rules import (
    check_auto_reject,
    validate_entry_rules,
    apply_confidence_boosts,
)


# ── check_auto_reject ────────────────────────────────────────

def test_reject_low_rrr():
    rejected, reason = check_auto_reject(
        rrr=2.5, sector_strength="STRONG", direction="LONG",
        fii_net=500, volume_scanners=["6_vol_above_avg"], cmp=100, ltrp=100,
    )
    assert rejected is True
    assert "RRR" in reason


def test_reject_weak_sector_long():
    rejected, reason = check_auto_reject(
        rrr=4.0, sector_strength="WEAK", direction="LONG",
        fii_net=500, volume_scanners=["6_vol_above_avg"], cmp=100, ltrp=100,
    )
    assert rejected is True
    assert "WEAK" in reason


def test_reject_strong_sector_short():
    rejected, reason = check_auto_reject(
        rrr=4.0, sector_strength="STRONG", direction="SHORT",
        fii_net=-500, volume_scanners=["6_vol_above_avg"], cmp=100, ltrp=100,
    )
    assert rejected is True
    assert "STRONG" in reason


def test_reject_fii_selling_long():
    rejected, reason = check_auto_reject(
        rrr=4.0, sector_strength="NEUTRAL", direction="LONG",
        fii_net=-3000, volume_scanners=["6_vol_above_avg"], cmp=100, ltrp=100,
    )
    assert rejected is True
    assert "FII" in reason


def test_reject_no_volume():
    rejected, reason = check_auto_reject(
        rrr=4.0, sector_strength="NEUTRAL", direction="LONG",
        fii_net=500, volume_scanners=[], cmp=100, ltrp=100,
    )
    assert rejected is True
    assert "volume" in reason.lower()


def test_reject_missed_entry_zone():
    rejected, reason = check_auto_reject(
        rrr=4.0, sector_strength="NEUTRAL", direction="LONG",
        fii_net=500, volume_scanners=["6_vol_above_avg"], cmp=110, ltrp=100,
    )
    assert rejected is True
    assert "LTRP" in reason


def test_accept_valid_signal():
    rejected, reason = check_auto_reject(
        rrr=4.0, sector_strength="NEUTRAL", direction="LONG",
        fii_net=500, volume_scanners=["6_vol_above_avg"], cmp=100, ltrp=100,
    )
    assert rejected is False
    assert reason == ""


def test_accept_short_with_weak_sector():
    """Shorts are allowed in weak sectors."""
    rejected, _ = check_auto_reject(
        rrr=4.0, sector_strength="WEAK", direction="SHORT",
        fii_net=-500, volume_scanners=["7_vol_2x"], cmp=100, ltrp=100,
    )
    assert rejected is False


# ── validate_entry_rules ──────────────────────────────────────

def _make_scanners(**active_keys):
    """Helper to build scanner_results dict."""
    result = {}
    for key in active_keys:
        result[key] = {"count": 1, "stocks": ["TEST"]}
    return result


def test_valid_long_entry():
    scanners = _make_scanners(**{k: True for k in [
        "1_swing_low", "2_upswing", "6_vol_above_avg",
    ]})
    valid, msg = validate_entry_rules("LONG", scanners, "BULL", "STRONG")
    assert valid is True


def test_long_missing_trend():
    scanners = _make_scanners(**{k: True for k in ["2_upswing", "6_vol_above_avg"]})
    valid, msg = validate_entry_rules("LONG", scanners, "BULL", "STRONG")
    assert valid is False
    assert "trend" in msg.lower()


def test_long_wrong_mwa():
    scanners = _make_scanners(**{k: True for k in [
        "1_swing_low", "2_upswing", "6_vol_above_avg",
    ]})
    valid, msg = validate_entry_rules("LONG", scanners, "BEAR", "STRONG")
    assert valid is False
    assert "MWA" in msg


def test_valid_short_entry():
    scanners = _make_scanners(**{k: True for k in [
        "3_swing_high", "4_downswing", "6_vol_above_avg",
    ]})
    valid, msg = validate_entry_rules("SHORT", scanners, "BEAR", "WEAK")
    assert valid is True


def test_invalid_direction():
    valid, msg = validate_entry_rules("HOLD", {}, "BULL", "NEUTRAL")
    assert valid is False
    assert "Invalid" in msg


# ── apply_confidence_boosts ───────────────────────────────────

def test_boosts_supertrend():
    scanners = {"17_supertrend": {"count": 1, "stocks": ["TEST"]}}
    conf, boosts = apply_confidence_boosts(50, scanners, False, 40, 0, "NEUTRAL", "LONG")
    assert conf >= 65
    assert any("Supertrend" in b for b in boosts)


def test_boosts_tv_confirmed():
    conf, boosts = apply_confidence_boosts(50, {}, True, 40, 0, "NEUTRAL", "LONG")
    assert conf == 60
    assert any("TV" in b for b in boosts)


def test_boosts_delivery():
    conf, boosts = apply_confidence_boosts(50, {}, False, 75, 0, "NEUTRAL", "LONG")
    assert conf == 60
    assert any("Delivery" in b for b in boosts)


def test_boosts_fii_buying_long():
    conf, boosts = apply_confidence_boosts(50, {}, False, 40, 1000, "NEUTRAL", "LONG")
    assert conf == 60
    assert any("FII" in b for b in boosts)


def test_boosts_cap_at_100():
    scanners = {
        "17_supertrend": {"count": 1, "stocks": []},
        "19_52week_high": {"count": 1, "stocks": []},
        "7_vol_2x": {"count": 1, "stocks": []},
        "18_macd": {"count": 1, "stocks": []},
        "1_swing_low": {"count": 1, "stocks": []},
        "2_upswing": {"count": 1, "stocks": []},
        "6_vol_above_avg": {"count": 1, "stocks": []},
    }
    conf, _ = apply_confidence_boosts(80, scanners, True, 80, 1000, "STRONG", "LONG")
    assert conf == 100


def test_boosts_no_boosts():
    conf, boosts = apply_confidence_boosts(50, {}, False, 40, -500, "NEUTRAL", "LONG")
    assert conf == 50
    assert len(boosts) == 0
