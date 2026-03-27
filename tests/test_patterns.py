import numpy as np
import pandas as pd

from mcp_server.pattern_engine import PatternEngine


def test_pattern_engine_init():
    engine = PatternEngine()
    assert engine is not None


def test_detect_all_short_data():
    engine = PatternEngine()
    df = pd.DataFrame({
        "open": [100, 101],
        "high": [102, 103],
        "low": [99, 100],
        "close": [101, 102],
        "volume": [1000, 1100],
    })
    results = engine.detect_all(df)
    assert isinstance(results, list)


def test_detect_all_sufficient_data():
    np.random.seed(42)
    n = 120
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    df = pd.DataFrame({
        "open": close - np.random.rand(n) * 0.3,
        "high": close + np.random.rand(n) * 1.0,
        "low": close - np.random.rand(n) * 1.0,
        "close": close,
        "volume": np.random.randint(50000, 500000, n),
    })
    engine = PatternEngine()
    results = engine.detect_all(df)
    assert isinstance(results, list)
    # Each result should have required fields
    for r in results:
        assert hasattr(r, "name")
        assert hasattr(r, "direction")
        assert hasattr(r, "confidence")
