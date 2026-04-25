"""Tests for mcp_server.broker_reconciler — normalisation + comparison logic."""


from mcp_server.broker_reconciler import (
    BrokerPosition,
    DBPosition,
    ReconcileResult,
    _compare,
    _norm_ticker,
    _normalise_angel,
    _normalise_dhan,
    _normalise_gwc,
)


# ── _norm_ticker ─────────────────────────────────────────────


def test_norm_ticker_adds_exchange_prefix():
    assert _norm_ticker("RELIANCE") == "NSE:RELIANCE"


def test_norm_ticker_preserves_existing_prefix():
    assert _norm_ticker("BSE:SENSEX") == "BSE:SENSEX"


def test_norm_ticker_uppercases():
    assert _norm_ticker("reliance") == "NSE:RELIANCE"


def test_norm_ticker_custom_exchange():
    assert _norm_ticker("BANKNIFTY", "NFO") == "NFO:BANKNIFTY"


def test_norm_ticker_strips_whitespace():
    assert _norm_ticker("  RELIANCE  ") == "NSE:RELIANCE"


# ── _normalise_dhan ──────────────────────────────────────────


def test_dhan_long_position():
    raw = [{"tradingSymbol": "RELIANCE", "exchangeSegment": "NSE_EQ",
            "netQty": 10, "ltp": 2500}]
    result = _normalise_dhan(raw)
    assert len(result) == 1
    p = result[0]
    assert p.ticker == "NSE:RELIANCE"
    assert p.qty == 10
    assert p.direction == "LONG"
    assert p.ltp == 2500.0
    assert p.source == "dhan"


def test_dhan_short_position():
    raw = [{"tradingSymbol": "SBIN", "exchangeSegment": "NSE_EQ",
            "netQty": -5, "ltp": 800}]
    result = _normalise_dhan(raw)
    assert len(result) == 1
    assert result[0].direction == "SHORT"
    assert result[0].qty == 5  # absolute


def test_dhan_flat_position_excluded():
    raw = [{"tradingSymbol": "WIPRO", "exchangeSegment": "NSE_EQ",
            "netQty": 0, "ltp": 400}]
    result = _normalise_dhan(raw)
    assert result == []


def test_dhan_missing_fields_skipped():
    raw = [{"tradingSymbol": None, "exchangeSegment": "NSE_EQ", "netQty": "bad"}]
    # Should not raise; bad row silently dropped
    result = _normalise_dhan(raw)
    assert result == []


def test_dhan_uses_security_id_fallback():
    raw = [{"securityId": "1234", "exchangeSegment": "NSE_EQ", "netQty": 3}]
    result = _normalise_dhan(raw)
    assert len(result) == 1
    assert "1234" in result[0].ticker


# ── _normalise_angel ─────────────────────────────────────────


def test_angel_dict_with_net_key():
    raw = {"data": {"net": [
        {"tradingsymbol": "TCS", "exchange": "NSE", "netqty": "20", "ltp": "3800"},
    ]}}
    result = _normalise_angel(raw)
    assert len(result) == 1
    assert result[0].ticker == "NSE:TCS"
    assert result[0].qty == 20


def test_angel_list_form():
    raw = [{"tradingsymbol": "INFY", "exchange": "NSE", "netqty": "15", "ltp": "1500"}]
    result = _normalise_angel(raw)
    assert len(result) == 1
    assert result[0].source == "angel"


def test_angel_flat_excluded():
    raw = [{"tradingsymbol": "HDFC", "exchange": "NSE", "netqty": "0"}]
    result = _normalise_angel(raw)
    assert result == []


# ── _normalise_gwc ───────────────────────────────────────────


def test_gwc_basic():
    raw = [{"symbol": "AXISBANK", "exchange": "NSE", "netQty": 8}]
    result = _normalise_gwc(raw)
    assert len(result) == 1
    assert result[0].ticker == "NSE:AXISBANK"
    assert result[0].source == "gwc"


def test_gwc_flat_excluded():
    raw = [{"symbol": "ITC", "exchange": "NSE", "netQty": 0}]
    assert _normalise_gwc(raw) == []


# ── _compare ─────────────────────────────────────────────────


def _b(ticker, qty=10, direction="LONG", source="dhan") -> BrokerPosition:
    return BrokerPosition(ticker=ticker, qty=qty, direction=direction, source=source)


def _d(ticker, qty=10, direction="LONG", id_=1) -> DBPosition:
    return DBPosition(id=id_, ticker=ticker, qty=qty, direction=direction, entry_price=100.0)


def test_compare_clean():
    broker = [_b("NSE:RELIANCE"), _b("NSE:SBIN")]
    db = [_d("NSE:RELIANCE"), _d("NSE:SBIN", id_=2)]
    ghosts, phantoms, drifts = _compare(broker, db)
    assert ghosts == []
    assert phantoms == []
    assert drifts == []


def test_compare_ghost_detected():
    broker = []
    db = [_d("NSE:RELIANCE")]
    ghosts, phantoms, drifts = _compare(broker, db)
    assert len(ghosts) == 1
    assert ghosts[0].ticker == "NSE:RELIANCE"


def test_compare_phantom_detected():
    broker = [_b("NSE:WIPRO")]
    db = []
    ghosts, phantoms, drifts = _compare(broker, db)
    assert len(phantoms) == 1
    assert phantoms[0].ticker == "NSE:WIPRO"


def test_compare_qty_drift_detected():
    broker = [_b("NSE:TCS", qty=20)]
    db = [_d("NSE:TCS", qty=10)]
    ghosts, phantoms, drifts = _compare(broker, db)
    assert len(drifts) == 1
    assert drifts[0]["broker_qty"] == 20
    assert drifts[0]["db_qty"] == 10
    assert drifts[0]["delta"] == 10


def test_compare_qty_within_tolerance_not_flagged():
    broker = [_b("NSE:TCS", qty=11)]
    db = [_d("NSE:TCS", qty=10)]
    ghosts, phantoms, drifts = _compare(broker, db, qty_tolerance=2)
    assert drifts == []


def test_compare_direction_mismatch_is_phantom_and_ghost():
    # Same ticker but different direction → separate keys → one ghost + one phantom
    broker = [_b("NSE:SBIN", direction="SHORT")]
    db = [_d("NSE:SBIN", direction="LONG")]
    ghosts, phantoms, drifts = _compare(broker, db)
    assert len(ghosts) == 1
    assert len(phantoms) == 1
    assert drifts == []


# ── ReconcileResult helpers ───────────────────────────────────


def test_has_drift_false_when_clean():
    r = ReconcileResult()
    assert r.has_drift() is False


def test_has_drift_true_with_ghost():
    r = ReconcileResult(ghosts=[_d("NSE:X")])
    assert r.has_drift() is True


def test_summary_clean():
    r = ReconcileResult(
        broker_positions=[_b("NSE:X")],
        db_positions=[_d("NSE:X")],
    )
    s = r.summary()
    assert "CLEAN" in s


def test_summary_drift_contains_type_labels():
    r = ReconcileResult(
        ghosts=[_d("NSE:GHOST")],
        phantoms=[_b("NSE:PHANTOM")],
        qty_drifts=[{"ticker": "NSE:DRIFT", "broker_qty": 5, "db_qty": 3,
                     "direction": "LONG", "delta": 2}],
    )
    s = r.summary()
    assert "GHOST" in s
    assert "PHANTOM" in s
    assert "QTY_DRIFT" in s


# ── run_reconciliation (paper-mode — no live broker) ─────────


def test_run_reconciliation_returns_result_type():
    from mcp_server.broker_reconciler import run_reconciliation
    result = run_reconciliation(alert_on_drift=False)
    # In test environment, no broker is live — result is always returned,
    # never raises.
    from mcp_server.broker_reconciler import ReconcileResult
    assert isinstance(result, ReconcileResult)
