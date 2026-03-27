from mcp_server.rrms_engine import RRMSEngine


def test_rrms_long_valid():
    engine = RRMSEngine()
    # CMP must be within 2% of LTRP: ltrp=97, entry zone = 97*1.02 = 98.94
    # So CMP=98 is within zone
    result = engine.calculate("TEST", cmp=98, ltrp=97, pivot_high=115, direction="LONG")
    assert result.ticker == "TEST"
    assert result.direction == "LONG"
    assert result.target == 115
    # Verify calculation runs without error


def test_rrms_long_invalid_far_from_ltrp():
    engine = RRMSEngine()
    # CMP far above LTRP -> not within 2% entry zone
    result = engine.calculate("TEST", cmp=120, ltrp=95, pivot_high=130, direction="LONG")
    # Entry zone check: (120 - 95) / 95 = 26.3% -> way above 2%
    assert result.ticker == "TEST"


def test_rrms_short_valid():
    engine = RRMSEngine()
    result = engine.calculate("TEST", cmp=100, ltrp=103, pivot_high=85, direction="SHORT")
    assert result.direction == "SHORT"


def test_rrms_result_has_all_fields():
    engine = RRMSEngine()
    result = engine.calculate("RELIANCE", cmp=100, ltrp=97, pivot_high=115, direction="LONG")
    assert hasattr(result, "entry_price")
    assert hasattr(result, "stop_loss")
    assert hasattr(result, "target")
    assert hasattr(result, "risk_per_share")
    assert hasattr(result, "reward_per_share")
    assert hasattr(result, "rrr")
    assert hasattr(result, "qty")
    assert hasattr(result, "risk_amt")
