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


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI on a price series."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("inf"))
    return 100 - 100 / (1 + rs)


def compute_bollinger_bands(
    series: pd.Series, period: int = 20, num_std: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (upper, middle, lower) Bollinger Bands."""
    middle = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    return middle + num_std * std, middle, middle - num_std * std


def compute_pivot_points(df: pd.DataFrame) -> pd.DataFrame:
    """
    Standard daily pivot points computed from the PREVIOUS day's H/L/C.
    Returns df with columns: pivot, r1, r2, s1, s2 (today's values).
    """
    prev_high  = df["high"].shift(1)
    prev_low   = df["low"].shift(1)
    prev_close = df["close"].shift(1)
    pivot = (prev_high + prev_low + prev_close) / 3
    r1 = 2 * pivot - prev_low
    s1 = 2 * pivot - prev_high
    r2 = pivot + (prev_high - prev_low)
    s2 = pivot - (prev_high - prev_low)
    result = df.copy()
    result["pivot"] = pivot
    result["r1"] = r1
    result["r2"] = r2
    result["s1"] = s1
    result["s2"] = s2
    return result


def scan_bb_breakout_bull(
    stock_data: dict[str, pd.DataFrame],
    st_period: int = 7,
    st_mult: float = 3.0,
    rsi_period: int = 14,
    rsi_threshold: float = 70.0,
    bb_period: int = 20,
    bb_std: float = 2.0,
) -> dict:
    """
    BB Breakout — Bullish (all 4 must fire on today's daily close):
    1. Close > SuperTrend (direction = +1)
    2. RSI(14) > 70
    3. Close > R1 daily pivot (previous day's resistance broken)
    4. Close > Upper Bollinger Band(20, 2)
    """
    hits: list[str] = []

    for ticker, df in stock_data.items():
        if df is None or len(df) < max(bb_period, 252) + 5:
            continue
        try:
            # Normalise column names
            df = df.copy()
            df.columns = [c.lower() for c in df.columns]
            if "close" not in df.columns:
                continue

            close = df["close"]
            high  = df["high"]  if "high"  in df.columns else close
            low   = df["low"]   if "low"   in df.columns else close

            # Condition 1: SuperTrend direction = +1
            st_df = compute_supertrend(
                df.rename(columns={"close": "close", "high": "high", "low": "low"}),
                period=st_period, multiplier=st_mult,
            )
            if st_df["st_direction"].iloc[-1] != 1:
                continue

            # Condition 2: RSI > rsi_threshold
            rsi = compute_rsi(close, rsi_period)
            if rsi.iloc[-1] <= rsi_threshold:
                continue

            # Condition 3: Close > R1 pivot
            tmp = pd.DataFrame({"close": close, "high": high, "low": low})
            piv = compute_pivot_points(tmp)
            if close.iloc[-1] <= piv["r1"].iloc[-1]:
                continue

            # Condition 4: Close > Upper BB
            upper_bb, _, _ = compute_bollinger_bands(close, bb_period, bb_std)
            if close.iloc[-1] <= upper_bb.iloc[-1]:
                continue

            hits.append(ticker)
        except Exception as e:
            logger.debug("BB breakout bull check failed for %s: %s", ticker, e)

    logger.info("[BB_BREAKOUT_BULL] %d stocks passed all 4 conditions", len(hits))
    return {
        "name": "BB Breakout Bullish",
        "group": "G_BB_BREAKOUT",
        "direction": "BULL",
        "weight": 4.0,
        "stocks": hits,
        "count": len(hits),
    }


def scan_bb_breakout_bear(
    stock_data: dict[str, pd.DataFrame],
    st_period: int = 7,
    st_mult: float = 3.0,
    rsi_period: int = 14,
    rsi_threshold: float = 30.0,
    bb_period: int = 20,
    bb_std: float = 2.0,
) -> dict:
    """
    BB Breakout — Bearish (all 4 must fire on today's daily close):
    1. Close < SuperTrend (direction = -1)
    2. RSI(14) < 30
    3. Close < S1 daily pivot (support broken)
    4. Close < Lower Bollinger Band(20, 2)
    """
    hits: list[str] = []

    for ticker, df in stock_data.items():
        if df is None or len(df) < max(bb_period, 252) + 5:
            continue
        try:
            df = df.copy()
            df.columns = [c.lower() for c in df.columns]
            if "close" not in df.columns:
                continue

            close = df["close"]
            high  = df["high"]  if "high"  in df.columns else close
            low   = df["low"]   if "low"   in df.columns else close

            st_df = compute_supertrend(
                df.rename(columns={"close": "close", "high": "high", "low": "low"}),
                period=st_period, multiplier=st_mult,
            )
            if st_df["st_direction"].iloc[-1] != -1:
                continue

            rsi = compute_rsi(close, rsi_period)
            if rsi.iloc[-1] >= rsi_threshold:
                continue

            tmp = pd.DataFrame({"close": close, "high": high, "low": low})
            piv = compute_pivot_points(tmp)
            if close.iloc[-1] >= piv["s1"].iloc[-1]:
                continue

            _, _, lower_bb = compute_bollinger_bands(close, bb_period, bb_std)
            if close.iloc[-1] >= lower_bb.iloc[-1]:
                continue

            hits.append(ticker)
        except Exception as e:
            logger.debug("BB breakout bear check failed for %s: %s", ticker, e)

    logger.info("[BB_BREAKOUT_BEAR] %d stocks passed all 4 conditions", len(hits))
    return {
        "name": "BB Breakout Bearish",
        "group": "G_BB_BREAKOUT",
        "direction": "BEAR",
        "weight": 4.0,
        "stocks": hits,
        "count": len(hits),
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
    results["bb_breakout_bull"] = scan_bb_breakout_bull(stock_data)
    results["bb_breakout_bear"] = scan_bb_breakout_bear(stock_data)

    logger.info("Technical scanners complete: %d scanners run", len(results))
    return results
