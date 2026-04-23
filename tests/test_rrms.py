from decimal import Decimal

from mcp_server.rrms_engine import RRMSEngine


def test_rrms_long_valid():
    engine = RRMSEngine()
    # CMP must be within 2% of LTRP: ltrp=97, entry zone = 97*1.02 = 98.94
    # So CMP=98 is within zone
    result = engine.calculate("TEST", cmp=98, ltrp=97, pivot_high=115, direction="LONG")
    assert result.ticker == "TEST"
    assert result.direction == "LONG"
    assert result.target == Decimal("115")
    # Verify calculation runs without error


def test_rrms_long_invalid_far_from_ltrp():
    engine = RRMSEngine()
    # CMP far above LTRP -> not within 2% entry zone
    result = engine.calculate("TEST", cmp=120, ltrp=95, pivot_high=130, direction="LONG")
    # Entry zone check: (120 - 95) / 95 = 26.3% -> way above 2%
    assert result.ticker == "TEST"
    assert result.is_valid is False


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


def test_rrms_result_fields_are_decimal():
    # Money-shaped fields must be Decimal so downstream math stays exact.
    # qty is int, is_valid bool, ticker/direction/reason str.
    engine = RRMSEngine()
    result = engine.calculate("NSE:RELIANCE", cmp=98, ltrp=97, pivot_high=115)
    for field in (
        "cmp", "ltrp", "pivot_high", "entry_price", "stop_loss", "target",
        "risk_per_share", "reward_per_share", "rrr", "risk_amt", "potential_profit",
    ):
        assert isinstance(getattr(result, field), Decimal), (
            f"{field} must be Decimal, got {type(getattr(result, field)).__name__}"
        )
    assert isinstance(result.qty, int)
    assert isinstance(result.is_valid, bool)


def test_rrms_accepts_decimal_inputs():
    # Engine public API is Numeric — passing Decimals must not error.
    engine = RRMSEngine()
    result = engine.calculate(
        "NSE:RELIANCE",
        cmp=Decimal("98.00"),
        ltrp=Decimal("97.00"),
        pivot_high=Decimal("115.00"),
    )
    assert result.direction == "LONG"


def test_rrms_cds_preserves_4dp_precision():
    # Currency ticker (CDS) rounds to 4dp per money.quantum_for("CDS").
    engine = RRMSEngine()
    result = engine.calculate(
        "CDS:USDINR", cmp="83.1234", ltrp="82.9000", pivot_high="85.5000",
    )
    # stop_loss = 82.9000 * 0.995 = 82.4855 → rounds at 4dp, stays 82.4855
    assert result.stop_loss == Decimal("82.4855")


def test_rrms_capital_override_via_numeric():
    # Constructor accepts any Numeric for capital override; ensures config's
    # Decimal fallback isn't bypassed when a plain int is provided.
    engine = RRMSEngine(capital=200_000)
    assert isinstance(engine.capital, Decimal)
    assert engine.capital == Decimal("200000")
    # risk_amt = 200_000 * 0.02 = 4_000
    assert engine.risk_amt == Decimal("4000.00")
