"""Tests for Sector Picker: NSE_SECTOR_MAP and SectorPicker helpers."""

from mcp_server.sector_picker import (
    NSE_SECTOR_MAP,
    fetch_stock_fundamentals,
    SectorPicker,
    BAIN_PROMPT,
)


# ── NSE_SECTOR_MAP ──────────────────────────────────────────

def test_sector_map_has_entries():
    assert len(NSE_SECTOR_MAP) >= 25


def test_sector_map_required_keys():
    for ticker, data in NSE_SECTOR_MAP.items():
        assert "sector" in data, f"{ticker} missing 'sector'"
        assert "peers" in data, f"{ticker} missing 'peers'"
        assert isinstance(data["peers"], list)
        assert len(data["peers"]) >= 3, f"{ticker} has fewer than 3 peers"


def test_sector_map_tickers_have_nse_prefix():
    for ticker in NSE_SECTOR_MAP:
        assert ticker.startswith("NSE:"), f"{ticker} missing NSE: prefix"


def test_sector_map_key_stocks():
    """Verify key stocks from the 29-stock seed are mapped."""
    expected = [
        "NSE:RELIANCE", "NSE:SBIN", "NSE:TATASTEEL",
        "NSE:BEL", "NSE:ACC", "NSE:LICI",
    ]
    for ticker in expected:
        assert ticker in NSE_SECTOR_MAP, f"{ticker} not in sector map"


def test_sector_map_sectors_diverse():
    sectors = {data["sector"] for data in NSE_SECTOR_MAP.values()}
    assert len(sectors) >= 10


def test_sector_map_no_self_peer():
    """A stock should not list itself as a peer."""
    for ticker, data in NSE_SECTOR_MAP.items():
        assert ticker not in data["peers"], f"{ticker} lists itself as peer"


# ── SectorPicker.get_sector_peers ────────────────────────────

def test_get_sector_peers_found():
    # SectorPicker requires kite, but get_sector_peers only uses NSE_SECTOR_MAP
    picker = SectorPicker.__new__(SectorPicker)
    result = picker.get_sector_peers("NSE:TATASTEEL")
    assert result is not None
    assert result["sector"] == "Steel/Metal"
    assert "NSE:JSWSTEEL" in result["peers"]


def test_get_sector_peers_not_found():
    picker = SectorPicker.__new__(SectorPicker)
    result = picker.get_sector_peers("NSE:UNKNOWN")
    assert result is None


def test_get_sector_peers_banking():
    picker = SectorPicker.__new__(SectorPicker)
    result = picker.get_sector_peers("NSE:SBIN")
    assert result is not None
    assert "Bank" in result["sector"]


# ── BAIN_PROMPT Template ─────────────────────────────────────

def test_bain_prompt_is_string():
    assert isinstance(BAIN_PROMPT, str)
    assert len(BAIN_PROMPT) > 200


def test_bain_prompt_placeholders():
    result = BAIN_PROMPT.format(
        ticker="NSE:TATASTEEL", company_name="Tata Steel",
        sector="Steel/Metal",
        comparison_table="<table>",
        rrms_table="<rrms>",
        alternative="NSE:JSWSTEEL",
    )
    assert "TATASTEEL" in result
    assert "Steel/Metal" in result
    assert "JSWSTEEL" in result


def test_bain_prompt_mentions_moat():
    assert "moat" in BAIN_PROMPT.lower()
    assert "ROCE" in BAIN_PROMPT
    assert "ADD" in BAIN_PROMPT
    assert "CONSIDER" in BAIN_PROMPT


# ── fetch_stock_fundamentals error handling ──────────────────

def test_fetch_fundamentals_returns_dict():
    """Should return dict even when API fails (no network in test)."""
    result = fetch_stock_fundamentals("NONEXISTENT_TICKER_XYZ")
    assert isinstance(result, dict)
    assert "ticker" in result


# ── add_to_sector_map ────────────────────────────────────────

def test_add_to_sector_map():
    picker = SectorPicker.__new__(SectorPicker)
    picker.add_to_sector_map("NSE:TESTSTOCK", "Testing", ["NSE:A", "NSE:B", "NSE:C"])
    assert "NSE:TESTSTOCK" in NSE_SECTOR_MAP
    assert NSE_SECTOR_MAP["NSE:TESTSTOCK"]["sector"] == "Testing"
    # Cleanup
    del NSE_SECTOR_MAP["NSE:TESTSTOCK"]
