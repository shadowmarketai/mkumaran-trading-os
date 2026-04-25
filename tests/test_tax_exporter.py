"""Tests for mcp_server.tax_exporter — classification, costs, summary, CSV."""

from datetime import date
from decimal import Decimal

import pytest

from mcp_server.tax_exporter import (
    LTCG_DAYS,
    LTCG_EXEMPTION,
    LTCG_RATE,
    STCG_RATE,
    STT_DELIVERY,
    STT_INTRADAY,
    TaxSummary,
    TaxTrade,
    _classify,
    _costs,
    _fy_date_range,
    _tax_on_trade,
)


# ── _fy_date_range ────────────────────────────────────────────


def test_fy_date_range_2025_26():
    fd, td = _fy_date_range("2025-26")
    assert fd == date(2025, 4, 1)
    assert td == date(2026, 3, 31)


def test_fy_date_range_2026_27():
    fd, td = _fy_date_range("2026-27")
    assert fd == date(2026, 4, 1)
    assert td == date(2027, 3, 31)


def test_fy_date_range_invalid_raises():
    with pytest.raises(ValueError):
        _fy_date_range("bad-input")


# ── _classify ─────────────────────────────────────────────────


def test_classify_intraday_by_days():
    assert _classify("EQUITY", "1D", 0) == "INTRADAY_EQUITY"


def test_classify_intraday_by_timeframe():
    assert _classify("EQUITY", "5M", 1) == "INTRADAY_EQUITY"
    assert _classify("EQUITY", "15M", 2) == "INTRADAY_EQUITY"


def test_classify_stcg():
    assert _classify("EQUITY", "1D", 100) == "STCG_EQUITY"
    assert _classify("EQUITY", "1D", LTCG_DAYS - 1) == "STCG_EQUITY"


def test_classify_ltcg():
    assert _classify("EQUITY", "1D", LTCG_DAYS) == "LTCG_EQUITY"
    assert _classify("EQUITY", "1D", 400) == "LTCG_EQUITY"


def test_classify_fno():
    for ac in ("NFO", "FNO", "MCX", "CDS", "FOREX", "FX", "COMMODITY"):
        assert _classify(ac, "1D", 5) == "FNO"


def test_classify_fno_regardless_of_days():
    assert _classify("NFO", "1D", 0) == "FNO"
    assert _classify("NFO", "1D", 400) == "FNO"


# ── _costs ────────────────────────────────────────────────────


def _d(x: str) -> Decimal:
    return Decimal(x)


def test_costs_delivery_includes_stt_at_correct_rate():
    c = _costs(_d("1000"), _d("1100"), 10, "NSE", "STCG_EQUITY")
    # STT = exit_turnover × STT_DELIVERY = 11000 × 0.00025 = 2.75
    assert abs(float(c["stt"]) - 2.75) < 0.01


def test_costs_intraday_stt_half_of_delivery():
    delivery = _costs(_d("1000"), _d("1000"), 10, "NSE", "STCG_EQUITY")
    intraday = _costs(_d("1000"), _d("1000"), 10, "NSE", "INTRADAY_EQUITY")
    # Intraday STT = 0.0125%; delivery STT = 0.025% → ratio 0.5
    assert float(intraday["stt"]) == pytest.approx(float(delivery["stt"]) * 0.5, rel=1e-3)


def test_costs_brokerage_capped_at_20():
    # Small order (turnover < ₹6,666): brokerage = turnover × 0.03%
    c_small = _costs(_d("100"), _d("100"), 1, "NSE", "STCG_EQUITY")
    assert float(c_small["brokerage"]) < 40   # below 2 × ₹20

    # Large order (turnover >> ₹6,666): brokerage capped at ₹20/side = ₹40 round-trip
    c_large = _costs(_d("100000"), _d("100000"), 1, "NSE", "STCG_EQUITY")
    assert abs(float(c_large["brokerage"]) - 40.0) < 0.01


def test_costs_total_positive():
    c = _costs(_d("500"), _d("550"), 20, "BSE", "STCG_EQUITY")
    assert float(c["total_charges"]) > 0


def test_costs_stamp_duty_on_buy_only():
    # Stamp duty = entry_turnover × 0.00015
    c = _costs(_d("1000"), _d("1000"), 10, "NSE", "STCG_EQUITY")
    expected_stamp = 1000 * 10 * 0.00015
    assert abs(float(c["stamp_duty"]) - expected_stamp) < 0.01


def test_costs_dict_has_all_keys():
    c = _costs(_d("1000"), _d("1000"), 5, "NSE", "FNO")
    for k in ("brokerage", "stt", "exchange", "sebi", "gst", "stamp_duty", "total_charges"):
        assert k in c


# ── _tax_on_trade ─────────────────────────────────────────────


def test_tax_on_loss_is_zero():
    assert _tax_on_trade(Decimal("-500"), "STCG_EQUITY") == Decimal("0")


def test_tax_stcg_rate():
    tax = _tax_on_trade(Decimal("10000"), "STCG_EQUITY")
    assert tax == round(Decimal("10000") * STCG_RATE, 2)


def test_tax_ltcg_with_exemption():
    # Net gain = 200,000; exemption = 125,000; taxable = 75,000
    tax = _tax_on_trade(Decimal("200000"), "LTCG_EQUITY")
    expected = round((Decimal("200000") - LTCG_EXEMPTION) * LTCG_RATE, 2)
    assert tax == expected


def test_tax_ltcg_under_exemption_is_zero():
    tax = _tax_on_trade(Decimal("100000"), "LTCG_EQUITY")
    assert tax == Decimal("0")


def test_tax_fno_at_30pct():
    tax = _tax_on_trade(Decimal("50000"), "FNO")
    assert tax == round(Decimal("50000") * Decimal("0.30"), 2)


def test_tax_intraday_at_30pct():
    tax = _tax_on_trade(Decimal("20000"), "INTRADAY_EQUITY")
    assert tax == round(Decimal("20000") * Decimal("0.30"), 2)


# ── TaxTrade ──────────────────────────────────────────────────


def _sample_trade(category: str = "STCG_EQUITY") -> TaxTrade:
    charges = _costs(Decimal("1000"), Decimal("1100"), 10, "NSE", category)
    gross = Decimal("1000")
    net = gross - charges["total_charges"]
    return TaxTrade(
        signal_id=1,
        ticker="RELIANCE",
        exchange="NSE",
        asset_class="EQUITY",
        direction="LONG",
        entry_date=date(2025, 6, 1),
        exit_date=date(2025, 9, 1),
        days_held=92,
        qty=10,
        entry_price=Decimal("1000"),
        exit_price=Decimal("1100"),
        gross_pnl=gross,
        charges=charges,
        net_pnl=net,
        tax_category=category,
        indicative_tax=_tax_on_trade(net, category),
    )


def test_trade_to_dict_keys():
    t = _sample_trade()
    d = t.to_dict()
    for k in ("signal_id", "ticker", "exchange", "entry_date", "exit_date",
              "gross_pnl", "net_pnl", "total_charges", "tax_category",
              "indicative_tax", "brokerage", "stt"):
        assert k in d


def test_trade_net_pnl_less_than_gross():
    t = _sample_trade()
    assert t.net_pnl < t.gross_pnl


# ── TaxSummary ────────────────────────────────────────────────


def _make_summary(trades: list) -> TaxSummary:
    return TaxSummary(
        fy="2025-26",
        from_date=date(2025, 4, 1),
        to_date=date(2026, 3, 31),
        trades=trades,
    )


def test_summary_filters_by_category():
    s = _make_summary([
        _sample_trade("STCG_EQUITY"),
        _sample_trade("FNO"),
        _sample_trade("STCG_EQUITY"),
    ])
    assert len(s.stcg) == 2
    assert len(s.fno) == 1
    assert len(s.intraday) == 0
    assert len(s.ltcg) == 0


def test_summary_as_dict_keys():
    s = _make_summary([_sample_trade()])
    d = s.as_dict()
    for k in ("fy", "from_date", "to_date", "total_trades", "summary", "trades", "disclaimer"):
        assert k in d
    for cat in ("intraday_equity", "stcg_equity", "ltcg_equity", "fno", "overall"):
        assert cat in d["summary"]


def test_summary_overall_net_pnl_is_sum():
    trades = [_sample_trade("STCG_EQUITY"), _sample_trade("FNO")]
    s = _make_summary(trades)
    d = s.as_dict()
    expected_net = sum(t.net_pnl for t in trades)
    assert abs(d["summary"]["overall"]["net_pnl"] - float(expected_net)) < 0.01


def test_summary_csv_is_bytes():
    s = _make_summary([_sample_trade()])
    csv_bytes = s.as_csv()
    assert isinstance(csv_bytes, bytes)
    assert len(csv_bytes) > 0


def test_summary_csv_has_header():
    s = _make_summary([_sample_trade()])
    csv_text = s.as_csv().decode("utf-8")
    assert "ticker" in csv_text
    assert "tax_category" in csv_text
    assert "net_pnl" in csv_text


def test_summary_csv_empty_trades_returns_empty_bytes():
    s = _make_summary([])
    assert s.as_csv() == b""


# ── Constants sanity ──────────────────────────────────────────


def test_stt_delivery_is_25bps():
    assert STT_DELIVERY == Decimal("0.00025")


def test_stt_intraday_is_12_5bps():
    assert STT_INTRADAY == Decimal("0.000125")


def test_ltcg_rate_is_12_5pct():
    assert LTCG_RATE == Decimal("0.125")


def test_stcg_rate_is_20pct():
    assert STCG_RATE == Decimal("0.20")


def test_ltcg_exemption_is_1_25_lakh():
    assert LTCG_EXEMPTION == Decimal("125000")


def test_ltcg_days_is_365():
    assert LTCG_DAYS == 365
