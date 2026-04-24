"""Tests for multi-source data routing + scanner segregation by segment."""


# ── Scanner Segment Assignment Tests ─────────────────────────


class TestScannerSegments:
    """Verify every scanner has a segments field and the assignment rules are correct."""

    def test_all_scanners_have_segments(self):
        from mcp_server.mwa_scanner import SCANNERS
        for key, cfg in SCANNERS.items():
            assert "segments" in cfg, f"Scanner {key} missing 'segments' field"
            assert isinstance(cfg["segments"], list), f"Scanner {key} segments is not a list"
            assert len(cfg["segments"]) > 0, f"Scanner {key} has empty segments list"

    def test_chartink_scanners_nse_only(self):
        from mcp_server.mwa_scanner import SCANNERS
        for key, cfg in SCANNERS.items():
            if cfg["source"] == "Chartink":
                assert cfg["segments"] == ["NSE"], (
                    f"Chartink scanner {key} should only run on NSE, got {cfg['segments']}"
                )

    def test_cds_scanners_cds_only(self):
        from mcp_server.mwa_scanner import SCANNERS
        cds_keys = [k for k, v in SCANNERS.items() if v["layer"] == "Forex"]
        assert len(cds_keys) == 8, f"Expected 8 CDS scanners, got {len(cds_keys)}"
        for key in cds_keys:
            assert SCANNERS[key]["segments"] == ["CDS"], (
                f"Forex scanner {key} should only run on CDS, got {SCANNERS[key]['segments']}"
            )

    def test_mcx_scanners_mcx_only(self):
        from mcp_server.mwa_scanner import SCANNERS
        mcx_keys = [k for k, v in SCANNERS.items() if v["layer"] == "Commodity"]
        assert len(mcx_keys) == 8, f"Expected 8 MCX scanners, got {len(mcx_keys)}"
        for key in mcx_keys:
            assert SCANNERS[key]["segments"] == ["MCX"], (
                f"Commodity scanner {key} should only run on MCX, got {SCANNERS[key]['segments']}"
            )

    def test_smc_scanners_universal(self):
        from mcp_server.mwa_scanner import SCANNERS
        smc_keys = [k for k, v in SCANNERS.items()
                     if v["layer"] == "SMC" and v["source"] == "Python"
                     and v["type"] not in ("FILTER",)]
        for key in smc_keys:
            segs = SCANNERS[key]["segments"]
            for seg in ["NSE", "MCX", "CDS", "NFO"]:
                assert seg in segs, f"SMC scanner {key} missing segment {seg}"

    def test_wyckoff_scanners_universal(self):
        from mcp_server.mwa_scanner import SCANNERS
        wy_keys = [k for k, v in SCANNERS.items() if v["layer"] == "Wyckoff"]
        assert len(wy_keys) == 8
        for key in wy_keys:
            assert set(SCANNERS[key]["segments"]) == {"NSE", "MCX", "CDS", "NFO"}

    def test_vsa_scanners_universal(self):
        from mcp_server.mwa_scanner import SCANNERS
        vsa_keys = [k for k, v in SCANNERS.items() if v["layer"] == "VSA"]
        assert len(vsa_keys) == 8
        for key in vsa_keys:
            assert set(SCANNERS[key]["segments"]) == {"NSE", "MCX", "CDS", "NFO"}

    def test_filter_scanners_nse_only(self):
        from mcp_server.mwa_scanner import SCANNERS
        filter_names = ["large_cap_filter", "delivery_pct_filter",
                        "fii_dii_filter", "sector_rotation_filter"]
        for name in filter_names:
            assert name in SCANNERS, f"Filter scanner {name} not found"
            assert SCANNERS[name]["segments"] == ["NSE"], (
                f"Filter {name} should be NSE only, got {SCANNERS[name]['segments']}"
            )


class TestComputedSegmentDicts:
    """Verify NSE_SCANNERS, MCX_SCANNERS, etc. are correctly computed."""

    def test_nse_scanners_includes_chartink(self):
        from mcp_server.mwa_scanner import NSE_SCANNERS
        chartink_in_nse = [k for k, v in NSE_SCANNERS.items() if v["source"] == "Chartink"]
        assert len(chartink_in_nse) > 30, "NSE_SCANNERS should include all Chartink scanners"

    def test_mcx_scanners_no_chartink(self):
        from mcp_server.mwa_scanner import MCX_SCANNERS
        chartink_in_mcx = [k for k, v in MCX_SCANNERS.items() if v["source"] == "Chartink"]
        assert len(chartink_in_mcx) == 0, "MCX_SCANNERS should NOT include Chartink scanners"

    def test_cds_scanners_no_chartink(self):
        from mcp_server.mwa_scanner import CDS_SCANNERS
        chartink_in_cds = [k for k, v in CDS_SCANNERS.items() if v["source"] == "Chartink"]
        assert len(chartink_in_cds) == 0, "CDS_SCANNERS should NOT include Chartink scanners"

    def test_mcx_scanners_has_smc(self):
        from mcp_server.mwa_scanner import MCX_SCANNERS
        smc_in_mcx = [k for k in MCX_SCANNERS if k.startswith("smc_")]
        assert len(smc_in_mcx) > 20, f"MCX should have SMC scanners, got {len(smc_in_mcx)}"

    def test_cds_scanners_has_smc(self):
        from mcp_server.mwa_scanner import CDS_SCANNERS
        smc_in_cds = [k for k in CDS_SCANNERS if k.startswith("smc_")]
        assert len(smc_in_cds) > 20, f"CDS should have SMC scanners, got {len(smc_in_cds)}"

    def test_mcx_scanners_has_commodity_specific(self):
        from mcp_server.mwa_scanner import MCX_SCANNERS
        mcx_specific = [k for k in MCX_SCANNERS if k.startswith("mcx_")]
        assert len(mcx_specific) == 8

    def test_cds_scanners_has_forex_specific(self):
        from mcp_server.mwa_scanner import CDS_SCANNERS
        cds_specific = [k for k in CDS_SCANNERS if k.startswith("cds_")]
        assert len(cds_specific) == 8

    def test_nfo_scanners_no_chartink(self):
        from mcp_server.mwa_scanner import NFO_SCANNERS
        chartink_in_nfo = [k for k, v in NFO_SCANNERS.items() if v["source"] == "Chartink"]
        assert len(chartink_in_nfo) == 0


# ── Segment Routing Tests ────────────────────────────────────


class TestSegmentRouting:
    """Verify SEGMENT_ROUTING dict and data routing logic."""

    def test_segment_routing_has_all_segments(self):
        from mcp_server.data_provider import SEGMENT_ROUTING
        for seg in ["NSE", "BSE", "NFO", "MCX", "CDS"]:
            assert seg in SEGMENT_ROUTING, f"Missing segment {seg} in SEGMENT_ROUTING"

    def test_nse_routing_angel_first(self):
        from mcp_server.data_provider import SEGMENT_ROUTING
        assert SEGMENT_ROUTING["NSE"][0] == "angel"

    def test_mcx_routing_dhan_first(self):
        # Dhan is now the MCX primary (free API, native MCX_COMM segment);
        # gwc/angel/kite remain as fallbacks. yfinance intentionally excluded
        # — its MCX symbols (e.g. CRUDEOIL→CL=F) are USD-denominated global
        # proxies, not INR MCX FUTCOM contracts.
        from mcp_server.data_provider import SEGMENT_ROUTING
        assert SEGMENT_ROUTING["MCX"][0] == "dhan"
        assert "yfinance" not in SEGMENT_ROUTING["MCX"]

    def test_cds_routing_dhan_first(self):
        # Dhan is also primary for currency derivatives; yfinance is the
        # final fallback rather than the primary as it once was.
        from mcp_server.data_provider import SEGMENT_ROUTING
        assert SEGMENT_ROUTING["CDS"][0] == "dhan"

    def test_nfo_routing_angel_first(self):
        from mcp_server.data_provider import SEGMENT_ROUTING
        assert SEGMENT_ROUTING["NFO"][0] == "angel"


# ── run_all Backward Compatibility Tests ─────────────────────


class TestRunAllBackwardCompat:
    """Verify run_all(segment="ALL") still works as before."""

    def test_run_all_default_segment_is_all(self):
        """run_all() without segment param should default to 'ALL'."""
        import inspect
        from mcp_server.mwa_scanner import MWAScanner
        sig = inspect.signature(MWAScanner.run_all)
        assert sig.parameters["segment"].default == "ALL"

    def test_run_python_scanners_default_segment_is_all(self):
        import inspect
        from mcp_server.mwa_scanner import MWAScanner
        sig = inspect.signature(MWAScanner.run_python_scanners)
        assert sig.parameters["segment"].default == "ALL"


# ── Angel Auto-Refresh Tests ────────────────────────────────


class TestAngelAutoRefresh:
    """Verify force_refresh_angel_token exists and has correct behavior."""

    def test_force_refresh_function_exists(self):
        from mcp_server.angel_auth import force_refresh_angel_token
        assert callable(force_refresh_angel_token)

    def test_get_ohlcv_routed_method_exists(self):
        from mcp_server.data_provider import MarketDataProvider
        assert hasattr(MarketDataProvider, "get_ohlcv_routed")
        assert callable(getattr(MarketDataProvider, "get_ohlcv_routed"))

    def test_angel_fetch_with_refresh_method_exists(self):
        from mcp_server.data_provider import MarketDataProvider
        assert hasattr(MarketDataProvider, "_angel_fetch_with_refresh")
