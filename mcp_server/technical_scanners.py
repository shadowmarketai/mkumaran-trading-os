import logging
import pandas as pd

logger = logging.getLogger(__name__)


def compute_ema(series: pd.Series, period: int) -> pd.Series:
    """Compute EMA for a given period."""
    return series.ewm(span=period, adjust=False).mean()


def detect_ema_crossover(
    df: pd.DataFrame,
    fast_period: int,
    slow_period: int,
    column: str = "close",
) -> str:
    """
    Detect EMA crossover signal.

    Returns: "BUY" if fast EMA crosses above slow, "SELL" if below, "HOLD" otherwise
    """
    fast_ema = compute_ema(df[column], fast_period)
    slow_ema = compute_ema(df[column], slow_period)

    if len(fast_ema) < 2:
        return "HOLD"

    # Current and previous relationship
    curr_above = fast_ema.iloc[-1] > slow_ema.iloc[-1]
    prev_above = fast_ema.iloc[-2] > slow_ema.iloc[-2]

    if curr_above and not prev_above:
        return "BUY"
    elif not curr_above and prev_above:
        return "SELL"
    return "HOLD"


def scan_nifty_ema(nifty_df: pd.DataFrame) -> dict:
    """
    Scanner 16b: Nifty 5/10 EMA crossover on 15-min.

    Args:
        nifty_df: Nifty 50 15-minute OHLCV data
    """
    signal = detect_ema_crossover(nifty_df, fast_period=5, slow_period=10)

    fast_ema = compute_ema(nifty_df["close"], 5).iloc[-1]
    slow_ema = compute_ema(nifty_df["close"], 10).iloc[-1]

    return {
        "name": "Nifty 5/10 EMA",
        "group": "G7_EMA",
        "direction": "BULL" if signal == "BUY" else ("BEAR" if signal == "SELL" else "NEUTRAL"),
        "weight": 1.0,
        "signal": signal,
        "fast_ema": round(float(fast_ema), 2),
        "slow_ema": round(float(slow_ema), 2),
        "stocks": [],
        "count": 1 if signal != "HOLD" else 0,
    }


def scan_stock_ema_crossover(
    stock_data: dict[str, pd.DataFrame],
) -> dict:
    """
    Scanner 16c: Stock 9/21 EMA daily crossover.
    Returns stocks where 9 EMA crossed above 21 EMA today.
    """
    bullish_crosses: list[str] = []

    for ticker, df in stock_data.items():
        if len(df) < 25:
            continue
        signal = detect_ema_crossover(df, fast_period=9, slow_period=21)
        if signal == "BUY":
            bullish_crosses.append(ticker)

    return {
        "name": "Stock 9/21 EMA Cross",
        "group": "G7_EMA",
        "direction": "BULL",
        "weight": 1.0,
        "signal": "BUY" if bullish_crosses else "HOLD",
        "stocks": bullish_crosses,
        "count": len(bullish_crosses),
    }


def compute_supertrend(
    df: pd.DataFrame,
    period: int = 10,
    multiplier: float = 3.0,
) -> pd.DataFrame:
    """Compute Supertrend indicator."""
    hl2 = (df['high'] + df['low']) / 2

    # ATR
    tr1 = df['high'] - df['low']
    tr2 = abs(df['high'] - df['close'].shift(1))
    tr3 = abs(df['low'] - df['close'].shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()

    upper_band = hl2 + (multiplier * atr)
    lower_band = hl2 - (multiplier * atr)

    supertrend = pd.Series(index=df.index, dtype=float)
    direction = pd.Series(index=df.index, dtype=int)

    for i in range(period, len(df)):
        if i == period:
            supertrend.iloc[i] = upper_band.iloc[i]
            direction.iloc[i] = -1
            continue

        if df['close'].iloc[i] > supertrend.iloc[i-1]:
            supertrend.iloc[i] = max(lower_band.iloc[i], supertrend.iloc[i-1]) if direction.iloc[i-1] == 1 else lower_band.iloc[i]
            direction.iloc[i] = 1
        else:
            supertrend.iloc[i] = min(upper_band.iloc[i], supertrend.iloc[i-1]) if direction.iloc[i-1] == -1 else upper_band.iloc[i]
            direction.iloc[i] = -1

    result = df.copy()
    result['supertrend'] = supertrend
    result['st_direction'] = direction
    return result


def scan_supertrend(stock_data: dict[str, pd.DataFrame]) -> dict:
    """
    Scanner 17: Supertrend Buy signal.
    Stocks where Supertrend just flipped to BUY (direction changed from -1 to 1).
    """
    buy_signals: list[str] = []

    for ticker, df in stock_data.items():
        if len(df) < 20:
            continue
        try:
            st_df = compute_supertrend(df)
            if len(st_df) < 2:
                continue
            curr_dir = st_df['st_direction'].iloc[-1]
            prev_dir = st_df['st_direction'].iloc[-2]
            if curr_dir == 1 and prev_dir == -1:
                buy_signals.append(ticker)
        except Exception as e:
            logger.error("Supertrend calc failed for %s: %s", ticker, e)

    return {
        "name": "Supertrend Buy",
        "group": "G8_Priority",
        "direction": "BULL",
        "weight": 2.0,
        "stocks": buy_signals,
        "count": len(buy_signals),
    }


def compute_macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Compute MACD, Signal, and Histogram."""
    fast_ema = compute_ema(df['close'], fast)
    slow_ema = compute_ema(df['close'], slow)
    macd_line = fast_ema - slow_ema
    signal_line = compute_ema(macd_line, signal_period)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def scan_macd_crossover(stock_data: dict[str, pd.DataFrame]) -> dict:
    """
    Scanner 18: MACD Bullish Crossover.
    Stocks where MACD line just crossed above signal line.
    """
    bullish: list[str] = []

    for ticker, df in stock_data.items():
        if len(df) < 35:
            continue
        try:
            macd_line, signal_line, _ = compute_macd(df)
            if len(macd_line) < 2:
                continue
            curr_above = macd_line.iloc[-1] > signal_line.iloc[-1]
            prev_above = macd_line.iloc[-2] > signal_line.iloc[-2]
            if curr_above and not prev_above:
                bullish.append(ticker)
        except Exception as e:
            logger.error("MACD calc failed for %s: %s", ticker, e)

    return {
        "name": "MACD Bullish Crossover",
        "group": "G8_Priority",
        "direction": "BULL",
        "weight": 1.5,
        "stocks": bullish,
        "count": len(bullish),
    }


def scan_52week_high(stock_data: dict[str, pd.DataFrame]) -> dict:
    """
    Scanner 19: 52-Week High Breakout.
    Stocks making new 52-week highs today.
    """
    breakouts: list[str] = []

    for ticker, df in stock_data.items():
        if len(df) < 252:
            continue
        try:
            high_52w = df['high'].tail(252).max()
            today_high = df['high'].iloc[-1]
            if today_high >= high_52w * 0.995:  # Within 0.5% of 52-wk high
                breakouts.append(ticker)
        except Exception as e:
            logger.error("52-wk high check failed for %s: %s", ticker, e)

    return {
        "name": "52-Week High Breakout",
        "group": "G8_Priority",
        "direction": "BULL",
        "weight": 2.5,
        "stocks": breakouts,
        "count": len(breakouts),
    }


def run_all_technical_scanners(
    stock_data: dict[str, pd.DataFrame],
    nifty_df: pd.DataFrame | None = None,
) -> dict[str, dict]:
    """Run all 4 Python-computed scanners."""
    results: dict[str, dict] = {}

    if nifty_df is not None:
        results["16b_nifty_ema"] = scan_nifty_ema(nifty_df)

    results["16c_stock_ema"] = scan_stock_ema_crossover(stock_data)
    results["17_supertrend"] = scan_supertrend(stock_data)
    results["18_macd"] = scan_macd_crossover(stock_data)
    results["19_52week_high"] = scan_52week_high(stock_data)

    logger.info("Technical scanners complete: %d scanners run", len(results))
    return results
