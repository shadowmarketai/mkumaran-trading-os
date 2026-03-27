"""Tests for Delivery, FII/DII, and Sector Filters."""

from mcp_server.delivery_filter import apply_delivery_filter
from mcp_server.fii_dii_filter import classify_fii_sentiment, fii_allows_long
from mcp_server.sector_filter import (
    SECTOR_INDICES,
    STOCK_SECTORS,
    get_stock_sector,
    sector_allows_trade,
)


# ── Delivery Filter ───────────────────────────────────────────

def test_delivery_filter_passes():
    delivery_data = {"RELIANCE": 75.5, "SBIN": 62.0, "TCS": 45.0}
    result = apply_delivery_filter(["RELIANCE", "SBIN", "TCS"], delivery_data, min_delivery_pct=60)
    assert result["RELIANCE"]["passed"] is True
    assert result["SBIN"]["passed"] is True
    assert result["TCS"]["passed"] is False


def test_delivery_filter_nse_prefix():
    delivery_data = {"RELIANCE": 80.0}
    result = apply_delivery_filter(["NSE:RELIANCE"], delivery_data)
    assert result["NSE:RELIANCE"]["passed"] is True
    assert result["NSE:RELIANCE"]["delivery_pct"] == 80.0


def test_delivery_filter_missing_stock():
    result = apply_delivery_filter(["UNKNOWN"], {})
    assert result["UNKNOWN"]["delivery_pct"] == 0.0
    assert result["UNKNOWN"]["passed"] is False


def test_delivery_filter_empty():
    result = apply_delivery_filter([], {})
    assert result == {}


def test_delivery_filter_custom_threshold():
    delivery_data = {"TEST": 50.0}
    result = apply_delivery_filter(["TEST"], delivery_data, min_delivery_pct=40)
    assert result["TEST"]["passed"] is True


# ── FII/DII Classifier ───────────────────────────────────────

def test_fii_strong_buy():
    assert classify_fii_sentiment(1000) == "STRONG_BUY"


def test_fii_buy():
    assert classify_fii_sentiment(200) == "BUY"


def test_fii_sell():
    assert classify_fii_sentiment(-500) == "SELL"


def test_fii_strong_sell():
    assert classify_fii_sentiment(-3000) == "STRONG_SELL"


def test_fii_allows_long_positive():
    assert fii_allows_long(500) is True


def test_fii_allows_long_mild_sell():
    assert fii_allows_long(-1000) is True


def test_fii_blocks_long_heavy_sell():
    assert fii_allows_long(-2500) is False


def test_fii_boundary():
    assert fii_allows_long(-2000) is False
    assert fii_allows_long(-1999) is True


# ── Sector Filter ─────────────────────────────────────────────

def test_sector_indices_defined():
    assert len(SECTOR_INDICES) >= 10
    assert "IT" in SECTOR_INDICES
    assert "Banking" in SECTOR_INDICES
    assert "Metal" in SECTOR_INDICES


def test_stock_sectors_mapping():
    assert STOCK_SECTORS["RELIANCE"] == "Energy"
    assert STOCK_SECTORS["SBIN"] == "Banking"
    assert STOCK_SECTORS["TCS"] == "IT"
    assert STOCK_SECTORS["TATASTEEL"] == "Metal"


def test_get_stock_sector():
    assert get_stock_sector("RELIANCE") == "Energy"
    assert get_stock_sector("NSE:SBIN") == "Banking"
    assert get_stock_sector("UNKNOWN") == "Unknown"


def test_sector_allows_long_strong():
    strength = {"Energy": "STRONG"}
    assert sector_allows_trade("RELIANCE", "LONG", strength) is True


def test_sector_blocks_long_weak():
    strength = {"Energy": "WEAK"}
    assert sector_allows_trade("RELIANCE", "LONG", strength) is False


def test_sector_blocks_short_strong():
    strength = {"Banking": "STRONG"}
    assert sector_allows_trade("SBIN", "SHORT", strength) is False


def test_sector_allows_short_weak():
    strength = {"Banking": "WEAK"}
    assert sector_allows_trade("SBIN", "SHORT", strength) is True


def test_sector_neutral_allows_both():
    strength = {"IT": "NEUTRAL"}
    assert sector_allows_trade("TCS", "LONG", strength) is True
    assert sector_allows_trade("TCS", "SHORT", strength) is True


def test_sector_unknown_stock():
    assert sector_allows_trade("UNKNOWN_STOCK", "LONG", {}) is True
