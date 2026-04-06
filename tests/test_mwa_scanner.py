"""Tests for MWA Scanner: SCANNERS dict, SIGNAL_CHAINS dict, and scanner logic."""

import numpy as np
import pandas as pd

from mcp_server.mwa_scanner import SCANNERS, SIGNAL_CHAINS, MWAScanner


def _make_df(closes, volume=100000):
    n = len(closes)
    arr = np.array(closes, dtype=float)
    return pd.DataFrame({
        "open": arr - 0.5,
        "high": arr + 1.0,
        "low": arr - 1.0,
        "close": arr,
        "volume": [volume] * n,
    })


# ── SCANNERS Dict Structure ─────────────────────────────────

def test_scanners_count():
    assert len(SCANNERS) == 118


def test_scanners_required_keys():
    required = {"no", "slug", "type", "weight", "layer", "source", "desc", "pairs_with", "status"}
    for key, cfg in SCANNERS.items():
        missing = required - set(cfg.keys())
        assert not missing, f"Scanner '{key}' missing keys: {missing}"


def test_scanners_unique_numbers():
    numbers = [cfg["no"] for cfg in SCANNERS.values()]
    assert len(numbers) == len(set(numbers)), "Duplicate scanner numbers found"


def test_scanners_valid_types():
    valid = {"BULL", "BEAR", "FILTER"}
    for key, cfg in SCANNERS.items():
        assert cfg["type"] in valid, f"Scanner '{key}' has invalid type: {cfg['type']}"


def test_scanners_valid_layers():
    valid = {"Trend", "Volume", "Breakout", "RSI", "Gap", "MA", "Filter",
             "SMC", "Wyckoff", "VSA", "Harmonic", "RL", "Forex", "Commodity"}
    for key, cfg in SCANNERS.items():
        assert cfg["layer"] in valid, f"Scanner '{key}' has invalid layer: {cfg['layer']}"


def test_scanners_valid_sources():
    for key, cfg in SCANNERS.items():
        assert cfg["source"] in {"Chartink", "Python"}, f"'{key}' invalid source"


def test_scanners_weights_non_negative():
    for key, cfg in SCANNERS.items():
        assert cfg["weight"] >= 0, f"Scanner '{key}' has negative weight"


def test_scanners_filters_have_zero_weight():
    for key, cfg in SCANNERS.items():
        if cfg["type"] == "FILTER":
            assert cfg["weight"] == 0.0, f"Filter '{key}' should have weight 0"


def test_scanners_type_counts():
    counts = {"BULL": 0, "BEAR": 0, "FILTER": 0}
    for cfg in SCANNERS.values():
        counts[cfg["type"]] += 1
    assert counts["BULL"] >= 52
    assert counts["BEAR"] >= 30
    assert counts["FILTER"] >= 4


def test_scanners_layer_coverage():
    layers = {cfg["layer"] for cfg in SCANNERS.values()}
    assert len(layers) >= 14


def test_scanners_pairs_with_valid():
    """All pairs_with references should be valid scanner keys."""
    all_keys = set(SCANNERS.keys())
    for key, cfg in SCANNERS.items():
        for pair in cfg["pairs_with"]:
            assert pair in all_keys, f"Scanner '{key}' pairs_with '{pair}' not in SCANNERS"


# ── SIGNAL_CHAINS Dict ──────────────────────────────────────

def test_signal_chains_count():
    assert len(SIGNAL_CHAINS) >= 25


def test_signal_chains_required_keys():
    required = {"scanners", "desc", "boost", "best_for"}
    for key, chain in SIGNAL_CHAINS.items():
        missing = required - set(chain.keys())
        assert not missing, f"Chain '{key}' missing keys: {missing}"


def test_signal_chains_scanners_valid():
    """All scanner references in chains should exist in SCANNERS."""
    all_keys = set(SCANNERS.keys())
    for chain_key, chain in SIGNAL_CHAINS.items():
        for scanner in chain["scanners"]:
            assert scanner in all_keys, f"Chain '{chain_key}' references unknown scanner '{scanner}'"


def test_signal_chains_boost_positive():
    for key, chain in SIGNAL_CHAINS.items():
        assert chain["boost"] > 0, f"Chain '{key}' has non-positive boost"


def test_signal_chains_have_descriptions():
    for key, chain in SIGNAL_CHAINS.items():
        assert len(chain["desc"]) > 10, f"Chain '{key}' has short/empty description"


def test_signal_chains_have_best_for():
    for key, chain in SIGNAL_CHAINS.items():
        assert len(chain["best_for"]) > 5, f"Chain '{key}' has short/empty best_for"


# ── Specific Signal Chains ───────────────────────────────────

def test_institutional_reversal_long_chain():
    chain = SIGNAL_CHAINS["institutional_reversal_long"]
    assert "wyckoff_spring" in chain["scanners"]
    assert "smc_liq_sweep_bull" in chain["scanners"]
    assert "vsa_selling_climax" in chain["scanners"]
    assert chain["boost"] == 35  # highest boost


def test_institutional_reversal_short_chain():
    chain = SIGNAL_CHAINS["institutional_reversal_short"]
    assert "wyckoff_upthrust" in chain["scanners"]
    assert "smc_liq_sweep_bear" in chain["scanners"]
    assert chain["boost"] == 35


def test_harmonic_confluence_chain():
    chain = SIGNAL_CHAINS["harmonic_confluence_long"]
    assert "harmonic_any_bull" in chain["scanners"]
    assert "smc_discount" in chain["scanners"]


# ── MWAScanner Class ────────────────────────────────────────

def test_mwa_scanner_init():
    scanner = MWAScanner(delay=0.1)
    assert scanner.delay == 0.1
    assert scanner.logged_in is False


def test_run_python_scanners_no_data():
    scanner = MWAScanner()
    results = scanner.run_python_scanners(stock_data=None)
    assert isinstance(results, dict)
    assert results.get("supertrend_buy") == []


def test_run_python_scanners_with_data():
    stock_data = {"TEST": _make_df(list(range(100, 200)))}
    scanner = MWAScanner()
    results = scanner.run_python_scanners(stock_data=stock_data)
    assert isinstance(results, dict)
    # SMC scanners should have results (even if empty lists)
    assert "smc_bos_bull" in results
    assert "smc_choch_bear" in results
    # Wyckoff
    assert "wyckoff_spring" in results
    assert "wyckoff_upthrust" in results
    # VSA
    assert "vsa_selling_climax" in results
    assert "vsa_no_supply" in results
    # Harmonic
    assert "harmonic_gartley_bull" in results
    assert "harmonic_any_bear" in results
    # Forex
    assert "cds_ema_crossover" in results
    assert "cds_dxy_divergence" in results
    # Commodity
    assert "mcx_ema_crossover" in results
    assert "mcx_crude_momentum" in results


def test_run_python_scanners_returns_lists():
    stock_data = {"RELIANCE": _make_df(list(range(100, 200)))}
    scanner = MWAScanner()
    results = scanner.run_python_scanners(stock_data=stock_data)
    for key, val in results.items():
        assert isinstance(val, list), f"Scanner '{key}' should return list, got {type(val)}"


# ── Backward Compatible Functions ───────────────────────────

def test_run_all_chartink_scanners_import():
    from mcp_server.mwa_scanner import run_all_chartink_scanners
    assert callable(run_all_chartink_scanners)


def test_fetch_chartink_import():
    from mcp_server.mwa_scanner import fetch_chartink
    assert callable(fetch_chartink)
