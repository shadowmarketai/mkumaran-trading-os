"""Tests for portfolio risk management — sector concentration, asset class limits."""

from mcp_server.portfolio_risk import (
    get_sector,
    check_sector_concentration,
    check_asset_class_concentration,
    validate_portfolio_risk,
    get_portfolio_exposure,
    MAX_SECTOR_PCT,
    MAX_ASSET_CLASS_PCT,
)


# ── Sector Mapping Tests ─────────────────────────────────────

class TestSectorMapping:
    def test_known_stock(self):
        assert get_sector("RELIANCE") == "ENERGY"
        assert get_sector("TCS") == "IT"
        assert get_sector("HDFCBANK") == "FINANCIALS"

    def test_exchange_prefix_stripped(self):
        assert get_sector("NSE:RELIANCE") == "ENERGY"
        assert get_sector("BSE:INFY") == "IT"

    def test_mcx_maps_to_commodity(self):
        assert get_sector("MCX:GOLD") == "COMMODITY"
        assert get_sector("MCX:CRUDEOIL") == "COMMODITY"

    def test_cds_maps_to_currency(self):
        assert get_sector("CDS:USDINR") == "CURRENCY"

    def test_nfo_maps_to_fno(self):
        assert get_sector("NFO:NIFTY") == "FNO_DERIVATIVES"

    def test_unknown_stock(self):
        assert get_sector("UNKNOWNSTOCK") == "UNKNOWN"

    def test_case_insensitive_lookup(self):
        # get_sector uses .upper() so lowercase works
        assert get_sector("reliance") == "ENERGY"
        assert get_sector("NSE:reliance") == "ENERGY"


# ── Sector Concentration Tests ───────────────────────────────

class TestSectorConcentration:
    def test_no_breach_with_empty_portfolio(self):
        error = check_sector_concentration([], "NSE:RELIANCE", 40000, 500000)
        assert error is None

    def test_no_breach_under_limit(self):
        positions = [
            {"ticker": "NSE:RELIANCE", "entry_price": 2500, "qty": 10},  # 25000 ENERGY
        ]
        # Adding another ENERGY stock: 40000 + 25000 = 65000 = 13% of 500k
        error = check_sector_concentration(positions, "NSE:ONGC", 40000, 500000)
        assert error is None

    def test_breach_over_limit(self):
        positions = [
            {"ticker": "NSE:RELIANCE", "entry_price": 2500, "qty": 20},  # 50000 ENERGY
            {"ticker": "NSE:BPCL", "entry_price": 500, "qty": 100},     # 50000 ENERGY
        ]
        # Already 100000 ENERGY (20%). Adding 30000 more = 130000 = 26% > 25%
        error = check_sector_concentration(positions, "NSE:ONGC", 30000, 500000)
        assert error is not None
        assert "SECTOR LIMIT" in error
        assert "ENERGY" in error

    def test_different_sectors_ok(self):
        positions = [
            {"ticker": "NSE:HDFCBANK", "entry_price": 1700, "qty": 30},  # 51000 FINANCIALS
        ]
        # Adding IT stock — different sector
        error = check_sector_concentration(positions, "NSE:TCS", 45000, 500000)
        assert error is None

    def test_zero_capital_skips(self):
        error = check_sector_concentration([], "NSE:RELIANCE", 40000, 0)
        assert error is None


# ── Asset Class Concentration Tests ──────────────────────────

class TestAssetClassConcentration:
    def test_equity_under_limit(self):
        positions = [
            {"ticker": "NSE:RELIANCE", "entry_price": 2500, "qty": 40},  # 100000 EQUITY
        ]
        # Adding 100000 more EQUITY: 200000 = 40% of 500k, under 50%
        error = check_asset_class_concentration(positions, "NSE:TCS", 100000, 500000)
        assert error is None

    def test_equity_over_limit(self):
        positions = [
            {"ticker": "NSE:RELIANCE", "entry_price": 2500, "qty": 40},  # 100000
            {"ticker": "NSE:TCS", "entry_price": 3800, "qty": 30},       # 114000
        ]
        # Already 214000 EQUITY (42.8%). Adding 50000 more = 264000 = 52.8% > 50%
        error = check_asset_class_concentration(positions, "NSE:INFY", 50000, 500000)
        assert error is not None
        assert "ASSET CLASS" in error

    def test_cross_asset_ok(self):
        positions = [
            {"ticker": "NSE:RELIANCE", "entry_price": 2500, "qty": 40},  # 100000 EQUITY
        ]
        # Adding MCX commodity — different asset class
        error = check_asset_class_concentration(positions, "MCX:GOLD", 100000, 500000)
        assert error is None


# ── Validate Portfolio Risk (Combined) Tests ─────────────────

class TestValidatePortfolioRisk:
    def test_clean_portfolio_passes(self):
        error = validate_portfolio_risk([], "NSE:RELIANCE", 40000, 500000)
        assert error is None

    def test_sector_breach_caught(self):
        positions = [
            {"ticker": "NSE:HDFCBANK", "entry_price": 1700, "qty": 40},
            {"ticker": "NSE:ICICIBANK", "entry_price": 1050, "qty": 50},
        ]
        # FINANCIALS: 68000 + 52500 = 120500. Adding 20000 more = 140500/500000 = 28% > 25%
        error = validate_portfolio_risk(positions, "NSE:SBIN", 20000, 500000)
        assert error is not None
        assert "SECTOR" in error

    def test_asset_class_breach_caught(self):
        positions = [
            {"ticker": "NSE:RELIANCE", "entry_price": 2500, "qty": 80},  # 200000 EQUITY
        ]
        error = validate_portfolio_risk(positions, "NSE:TCS", 60000, 500000)
        # 200000 + 60000 = 260000 = 52% > 50%
        assert error is not None
        assert "ASSET CLASS" in error


# ── Portfolio Exposure Tests ─────────────────────────────────

class TestPortfolioExposure:
    def test_empty_portfolio(self):
        exp = get_portfolio_exposure([], 500000)
        assert exp["total_deployed"] == 0
        assert exp["deployed_pct"] == 0
        assert exp["sector_breakdown"] == {}

    def test_mixed_portfolio(self):
        positions = [
            {"ticker": "NSE:RELIANCE", "entry_price": 2500, "qty": 10},  # 25000 ENERGY
            {"ticker": "NSE:TCS", "entry_price": 3800, "qty": 5},        # 19000 IT
            {"ticker": "MCX:GOLD", "entry_price": 58000, "qty": 1},      # 58000 COMMODITY
        ]
        exp = get_portfolio_exposure(positions, 500000)
        assert exp["total_deployed"] == 102000
        assert exp["deployed_pct"] == 20.4
        assert "ENERGY" in exp["sector_breakdown"]
        assert "IT" in exp["sector_breakdown"]
        assert "COMMODITY" in exp["sector_breakdown"]
        assert "EQUITY" in exp["asset_class_breakdown"]
        assert "COMMODITY" in exp["asset_class_breakdown"]

    def test_limits_present(self):
        exp = get_portfolio_exposure([], 500000)
        assert exp["limits"]["max_sector_pct"] == MAX_SECTOR_PCT * 100
        assert exp["limits"]["max_asset_class_pct"] == MAX_ASSET_CLASS_PCT * 100
