"""Tests for Multi-Asset Support: asset_registry, symbol resolution, filter applicability."""

from mcp_server.asset_registry import (
    Exchange,
    AssetClass,
    EXCHANGE_CONFIG,
    MCX_YF_PROXY,
    MCX_UNIVERSE,
    CDS_UNIVERSE,
    NFO_INDEX_UNIVERSE,
    parse_ticker,
    resolve_yf_symbol,
    get_exchange,
    get_asset_class,
    get_applicable_filters,
    filter_applies,
    get_universe,
    format_ticker,
    get_supported_exchanges,
)


# ── Exchange / AssetClass Enums ──────────────────────────────

def test_exchange_enum_values():
    assert Exchange.NSE == "NSE"
    assert Exchange.BSE == "BSE"
    assert Exchange.MCX == "MCX"
    assert Exchange.CDS == "CDS"
    assert Exchange.NFO == "NFO"


def test_asset_class_enum_values():
    assert AssetClass.EQUITY == "EQUITY"
    assert AssetClass.COMMODITY == "COMMODITY"
    assert AssetClass.CURRENCY == "CURRENCY"
    assert AssetClass.FNO == "FNO"


def test_exchange_config_has_all_exchanges():
    for ex in Exchange:
        assert ex in EXCHANGE_CONFIG, f"{ex} missing from EXCHANGE_CONFIG"


def test_exchange_config_required_keys():
    required = {"asset_class", "yf_suffix", "kite_exchange", "filters", "scanners", "description"}
    for ex, cfg in EXCHANGE_CONFIG.items():
        missing = required - set(cfg.keys())
        assert not missing, f"{ex} missing keys: {missing}"


# ── parse_ticker ─────────────────────────────────────────────

def test_parse_ticker_with_prefix():
    assert parse_ticker("NSE:RELIANCE") == ("NSE", "RELIANCE")
    assert parse_ticker("MCX:GOLD") == ("MCX", "GOLD")
    assert parse_ticker("CDS:USDINR") == ("CDS", "USDINR")
    assert parse_ticker("NFO:NIFTY") == ("NFO", "NIFTY")
    assert parse_ticker("BSE:TCS") == ("BSE", "TCS")


def test_parse_ticker_without_prefix():
    assert parse_ticker("RELIANCE") == ("NSE", "RELIANCE")
    assert parse_ticker("SBIN") == ("NSE", "SBIN")


def test_parse_ticker_lowercase():
    assert parse_ticker("nse:reliance") == ("NSE", "RELIANCE")
    assert parse_ticker("mcx:gold") == ("MCX", "GOLD")


# ── resolve_yf_symbol ────────────────────────────────────────

def test_resolve_yf_nse():
    assert resolve_yf_symbol("NSE:RELIANCE") == "RELIANCE.NS"
    assert resolve_yf_symbol("NSE:SBIN") == "SBIN.NS"


def test_resolve_yf_bse():
    assert resolve_yf_symbol("BSE:RELIANCE") == "RELIANCE.BO"


def test_resolve_yf_mcx():
    assert resolve_yf_symbol("MCX:GOLD") == "GC=F"
    assert resolve_yf_symbol("MCX:SILVER") == "SI=F"
    assert resolve_yf_symbol("MCX:CRUDEOIL") == "CL=F"
    assert resolve_yf_symbol("MCX:NATURALGAS") == "NG=F"
    assert resolve_yf_symbol("MCX:COPPER") == "HG=F"


def test_resolve_yf_mcx_no_proxy():
    assert resolve_yf_symbol("MCX:MENTHAOIL") is None


def test_resolve_yf_cds():
    assert resolve_yf_symbol("CDS:USDINR") == "USDINR=X"
    assert resolve_yf_symbol("CDS:EURINR") == "EURINR=X"


def test_resolve_yf_nfo_none():
    assert resolve_yf_symbol("NFO:NIFTY") is None


def test_resolve_yf_default_nse():
    assert resolve_yf_symbol("RELIANCE") == "RELIANCE.NS"


# ── get_exchange / get_asset_class ───────────────────────────

def test_get_exchange():
    assert get_exchange("NSE:RELIANCE") == Exchange.NSE
    assert get_exchange("MCX:GOLD") == Exchange.MCX
    assert get_exchange("CDS:USDINR") == Exchange.CDS
    assert get_exchange("NFO:NIFTY") == Exchange.NFO
    assert get_exchange("RELIANCE") == Exchange.NSE  # default


def test_get_asset_class():
    assert get_asset_class("NSE:RELIANCE") == AssetClass.EQUITY
    assert get_asset_class("BSE:TCS") == AssetClass.EQUITY
    assert get_asset_class("MCX:GOLD") == AssetClass.COMMODITY
    assert get_asset_class("CDS:USDINR") == AssetClass.CURRENCY
    assert get_asset_class("NFO:NIFTY") == AssetClass.FNO


# ── Filter Applicability ─────────────────────────────────────

def test_equity_filters():
    filters = get_applicable_filters("NSE:RELIANCE")
    assert "delivery" in filters
    assert "fii_dii" in filters
    assert "sector" in filters
    assert "earnings" in filters


def test_commodity_filters():
    filters = get_applicable_filters("MCX:GOLD")
    assert "delivery" not in filters
    assert "fii_dii" not in filters
    assert "sector" not in filters
    assert "oi_buildup" in filters


def test_currency_filters():
    filters = get_applicable_filters("CDS:USDINR")
    assert len(filters) == 0  # No specific filters for CDS


def test_fno_filters():
    filters = get_applicable_filters("NFO:NIFTY")
    assert "oi_buildup" in filters
    assert "delivery" not in filters


def test_filter_applies_delivery():
    assert filter_applies("NSE:RELIANCE", "delivery") is True
    assert filter_applies("MCX:GOLD", "delivery") is False
    assert filter_applies("CDS:USDINR", "delivery") is False


def test_filter_applies_fii_dii():
    assert filter_applies("NSE:SBIN", "fii_dii") is True
    assert filter_applies("MCX:SILVER", "fii_dii") is False


def test_filter_applies_sector():
    assert filter_applies("NSE:TATASTEEL", "sector") is True
    assert filter_applies("MCX:COPPER", "sector") is False


# ── Universe Lists ───────────────────────────────────────────

def test_mcx_universe():
    assert len(MCX_UNIVERSE) >= 10
    assert "GOLD" in MCX_UNIVERSE
    assert "SILVER" in MCX_UNIVERSE
    assert "CRUDEOIL" in MCX_UNIVERSE


def test_cds_universe():
    assert len(CDS_UNIVERSE) >= 4
    assert "USDINR" in CDS_UNIVERSE


def test_nfo_index_universe():
    assert "NIFTY" in NFO_INDEX_UNIVERSE
    assert "BANKNIFTY" in NFO_INDEX_UNIVERSE


def test_get_universe_nse():
    universe = get_universe("NSE")
    assert len(universe) >= 50
    assert "RELIANCE" in universe


def test_get_universe_mcx():
    universe = get_universe("MCX")
    assert "GOLD" in universe
    assert "CRUDEOIL" in universe


def test_get_universe_cds():
    universe = get_universe("CDS")
    assert "USDINR" in universe


def test_get_universe_nfo():
    universe = get_universe("NFO")
    assert "NIFTY" in universe


def test_get_universe_invalid():
    universe = get_universe("INVALID")
    assert universe == []


# ── format_ticker ────────────────────────────────────────────

def test_format_ticker():
    assert format_ticker("NSE", "RELIANCE") == "NSE:RELIANCE"
    assert format_ticker(Exchange.MCX, "GOLD") == "MCX:GOLD"
    assert format_ticker("CDS", "USDINR") == "CDS:USDINR"


# ── MCX yfinance Proxy Map ──────────────────────────────────

def test_mcx_yf_proxy_coverage():
    assert len(MCX_YF_PROXY) >= 10
    assert MCX_YF_PROXY["GOLD"] == "GC=F"
    assert MCX_YF_PROXY["SILVER"] == "SI=F"
    assert MCX_YF_PROXY["CRUDEOIL"] == "CL=F"


# ── get_supported_exchanges ──────────────────────────────────

def test_supported_exchanges():
    exchanges = get_supported_exchanges()
    assert len(exchanges) == 5
    names = [e["exchange"] for e in exchanges]
    assert "NSE" in names
    assert "MCX" in names
    assert "CDS" in names


def test_supported_exchanges_structure():
    for ex in get_supported_exchanges():
        assert "exchange" in ex
        assert "asset_class" in ex
        assert "description" in ex
        assert "filters" in ex
        assert "scanners" in ex
        assert "universe_size" in ex


# ── Backward Compatibility ───────────────────────────────────

def test_nse_scanner_backward_compat():
    """Existing NSE code should still work with bare tickers."""
    from mcp_server.nse_scanner import _get_nse_universe

    universe = _get_nse_universe()
    assert len(universe) >= 50
    assert "RELIANCE" in universe


def test_filter_backward_compat_delivery():
    """Delivery filter should auto-pass non-equity tickers."""
    from mcp_server.delivery_filter import apply_delivery_filter

    result = apply_delivery_filter(
        ["MCX:GOLD", "MCX:SILVER"],
        delivery_data={},
    )
    assert result["MCX:GOLD"]["passed"] is True
    assert result["MCX:GOLD"].get("skipped") is True
    assert result["MCX:SILVER"]["passed"] is True


def test_filter_backward_compat_fii():
    """FII filter should auto-pass non-equity tickers."""
    from mcp_server.fii_dii_filter import fii_allows_long

    # Commodity should always pass regardless of FII data
    assert fii_allows_long(-5000, ticker="MCX:GOLD") is True
    # Equity should respect the FII threshold
    assert fii_allows_long(-5000, ticker="NSE:RELIANCE") is False
    assert fii_allows_long(100, ticker="NSE:RELIANCE") is True


def test_filter_backward_compat_sector():
    """Sector filter should auto-pass non-equity tickers."""
    from mcp_server.sector_filter import sector_allows_trade

    # Commodity should always pass
    assert sector_allows_trade("MCX:GOLD", "LONG", {"Metal": "WEAK"}) is True
    # Currency should always pass
    assert sector_allows_trade("CDS:USDINR", "LONG", {}) is True


# ── Model Exchange Column ────────────────────────────────────

def test_watchlist_model_has_exchange():
    from mcp_server.models import Watchlist
    assert hasattr(Watchlist, "exchange")
    assert hasattr(Watchlist, "asset_class")


def test_signal_model_has_exchange():
    from mcp_server.models import Signal
    assert hasattr(Signal, "exchange")
    assert hasattr(Signal, "asset_class")


def test_active_trade_model_has_exchange():
    from mcp_server.models import ActiveTrade
    assert hasattr(ActiveTrade, "exchange")
    assert hasattr(ActiveTrade, "asset_class")
