# smart_money_concepts.py
# MKUMARAN Trading OS — AMD + CRT + C4 Strategy Engine
# Detects institutional price delivery patterns on NSE stocks + F&O indices
#
# INTEGRATIONS:
#   → pattern_engine.py  : call detect_all_smc() alongside your 12 RRMS patterns
#   → fo_module.py       : call crt_fo_entry() for BankNifty/Nifty intraday entries
#   → validator.py       : smc_confidence_score() boosts Claude AI signal confidence
#   → mwa_scanner.py     : amd_zone_scanner() as Layer 1 extension
#   → Telegram alerts    : format_smc_card() appended to existing signal cards
#
# Usage:
#   from smart_money_concepts import SMCEngine
#   smc = SMCEngine()
#   result = smc.analyse(df, symbol="NSE:BANKNIFTY", timeframe="15minute")

import pandas as pd
import numpy as np
from typing import Optional

from mcp_server.market_calendar import now_ist
from dataclasses import dataclass


# ─── DATA CLASSES ─────────────────────────────────────────────────────────────

@dataclass
class AMDZone:
    """Accumulation-Manipulation-Distribution zone"""
    symbol:           str
    phase:            str        # ACCUMULATION / MANIPULATION / DISTRIBUTION
    direction:        str        # BULL / BEAR
    zone_high:        float
    zone_low:         float
    manipulation_low: float      # The sweep low (bull) or sweep high (bear)
    manipulation_high:float
    confirmed:        bool
    confidence:       float      # 0–100
    candle_index:     int

@dataclass
class CRTCandle:
    """Candle Range Theory analysis of a single candle"""
    symbol:           str
    timeframe:        str
    candle_type:      str        # BULLISH / BEARISH / DOJI / INDECISION
    crt_pattern:      str        # TYPE1_BULL / TYPE2_BEAR / TYPE3_MIXED / TYPE4_DOJI
    open:             float
    high:             float
    low:              float
    close:            float
    manipulation_side:str        # LOW_SWEEP / HIGH_SWEEP / BOTH / NONE
    manipulation_wick:float      # Size of the sweep wick
    true_direction:   str        # UP / DOWN / SIDEWAYS
    entry_zone_high:  float      # Return-to-open entry zone
    entry_zone_low:   float
    stop_loss:        float      # Below manipulation wick
    confidence:       float

@dataclass
class C4Setup:
    """C4 Strategy: Consolidation → Compression → Catalyst → Continuation"""
    symbol:           str
    timeframe:        str
    stage:            str        # CONSOLIDATION / COMPRESSION / CATALYST / CONTINUATION
    direction:        str        # BULL / BEAR
    consolidation_high: float
    consolidation_low:  float
    compression_range:  float    # Narrowing candle range (% of consolidation)
    catalyst_candle:    Optional[CRTCandle]
    entry_price:        float
    stop_loss:          float
    target_1:           float    # 1:2 RRR
    target_2:           float    # 1:3 RRR
    target_3:           float    # Opposing liquidity pool
    rrr:                float
    confidence:         float
    aligned_with_amd:   bool     # True if AMD confirms this C4 direction


# ══════════════════════════════════════════════════════════════════════════════
# AMD ENGINE — Accumulation, Manipulation, Distribution
# ══════════════════════════════════════════════════════════════════════════════

class AMDEngine:
    """
    Detects AMD phases in price data.
    Works on any timeframe — best on 1H, 4H, Daily for macro view.
    """

    def __init__(self,
                 consolidation_min_bars: int = 5,
                 consolidation_range_pct: float = 2.0,
                 manipulation_pct: float = 0.5):
        self.consol_min_bars   = consolidation_min_bars
        self.consol_range_pct  = consolidation_range_pct  # Max % range to qualify as consolidation
        self.manip_pct         = manipulation_pct          # Min % sweep beyond range

    def detect_consolidation_zones(self, df: pd.DataFrame) -> list:
        """
        Find consolidation zones (accumulation) where price is ranging.
        Returns list of (start_idx, end_idx, zone_high, zone_low)
        """
        zones = []
        i = 0
        while i < len(df) - self.consol_min_bars:
            window = df.iloc[i:i + self.consol_min_bars]
            w_high = window['high'].max()
            w_low  = window['low'].min()
            range_pct = ((w_high - w_low) / w_low) * 100

            if range_pct <= self.consol_range_pct:
                # Extend consolidation as long as price stays in range
                end = i + self.consol_min_bars
                while end < len(df):
                    candle = df.iloc[end]
                    if candle['high'] > w_high * 1.002 or candle['low'] < w_low * 0.998:
                        break
                    w_high = max(w_high, candle['high'])
                    w_low  = min(w_low, candle['low'])
                    end += 1

                if end - i >= self.consol_min_bars:
                    zones.append({
                        "start": i,
                        "end":   end - 1,
                        "high":  w_high,
                        "low":   w_low,
                        "bars":  end - i,
                        "range_pct": range_pct,
                    })
                i = end
            else:
                i += 1
        return zones

    def detect_manipulation(self, df: pd.DataFrame, zone: dict) -> dict:
        """
        After a consolidation zone, detect the manipulation sweep.
        Bull AMD: price dips BELOW zone low then recovers.
        Bear AMD: price spikes ABOVE zone high then reverses.
        """
        zone_end = zone["end"]
        zone_high = zone["high"]
        zone_low  = zone["low"]

        # Look at next 5 candles after consolidation
        lookahead = min(zone_end + 6, len(df))
        post_zone = df.iloc[zone_end:lookahead]

        if post_zone.empty:
            return {"found": False}

        # Bull manipulation: sweep below zone low
        min_low = post_zone['low'].min()
        sweep_below = zone_low - min_low
        sweep_below_pct = (sweep_below / zone_low) * 100

        # Bear manipulation: spike above zone high
        max_high = post_zone['high'].max()
        sweep_above = max_high - zone_high
        sweep_above_pct = (sweep_above / zone_high) * 100

        if sweep_below_pct >= self.manip_pct and sweep_below > sweep_above:
            # Bullish AMD — manipulated down to sweep sell stops
            sweep_idx = post_zone['low'].idxmin()
            return {
                "found":      True,
                "direction":  "BULL",
                "sweep_level": min_low,
                "sweep_pct":  round(sweep_below_pct, 2),
                "sweep_idx":  sweep_idx,
                "phase":      "MANIPULATION",
            }
        elif sweep_above_pct >= self.manip_pct and sweep_above > sweep_below:
            # Bearish AMD — manipulated up to sweep buy stops
            sweep_idx = post_zone['high'].idxmax()
            return {
                "found":      True,
                "direction":  "BEAR",
                "sweep_level": max_high,
                "sweep_pct":  round(sweep_above_pct, 2),
                "sweep_idx":  sweep_idx,
                "phase":      "MANIPULATION",
            }

        return {"found": False}

    def detect_distribution(self, df: pd.DataFrame,
                             zone: dict,
                             manipulation: dict) -> dict:
        """
        After manipulation, detect if price delivers in the true direction.
        Distribution = trend move away from zone in opposite direction of manipulation.
        """
        if not manipulation.get("found"):
            return {"found": False}

        manip_idx = manipulation.get("sweep_idx", zone["end"])
        direction = manipulation["direction"]

        # Look at 10 candles post manipulation
        try:
            idx_pos    = df.index.get_loc(manip_idx)
            post_manip = df.iloc[idx_pos:idx_pos + 10]
        except Exception:
            return {"found": False}

        if direction == "BULL":
            # Should close above zone high
            closes_above = (post_manip['close'] > zone["high"]).sum()
            move = post_manip['close'].max() - zone["high"]
            move_pct = (move / zone["high"]) * 100
            if closes_above >= 2 and move_pct >= 1.0:
                return {
                    "found":     True,
                    "direction": "BULL",
                    "move_pct":  round(move_pct, 2),
                    "phase":     "DISTRIBUTION",
                }
        elif direction == "BEAR":
            # Should close below zone low
            closes_below = (post_manip['close'] < zone["low"]).sum()
            move = zone["low"] - post_manip['close'].min()
            move_pct = (move / zone["low"]) * 100
            if closes_below >= 2 and move_pct >= 1.0:
                return {
                    "found":     True,
                    "direction": "BEAR",
                    "move_pct":  round(move_pct, 2),
                    "phase":     "DISTRIBUTION",
                }

        return {"found": False}

    def scan(self, df: pd.DataFrame, symbol: str = "") -> list:
        """
        Full AMD scan on a DataFrame.
        Returns list of AMDZone objects found.
        """
        results = []
        zones   = self.detect_consolidation_zones(df)

        for zone in zones:
            manip = self.detect_manipulation(df, zone)
            if not manip.get("found"):
                continue

            distrib = self.detect_distribution(df, zone, manip)

            # Confidence scoring
            confidence = 50.0
            if zone["bars"] >= 8:
                confidence += 10
            if zone["bars"] >= 12:
                confidence += 10
            if manip["sweep_pct"] >= 1.0:
                confidence += 10
            if distrib.get("found"):
                confidence += 20
            if distrib.get("move_pct", 0) >= 2.0:
                confidence += 10

            amd = AMDZone(
                symbol           = symbol,
                phase            = distrib["phase"] if distrib.get("found") else manip["phase"],
                direction        = manip["direction"],
                zone_high        = zone["high"],
                zone_low         = zone["low"],
                manipulation_low  = manip["sweep_level"] if manip["direction"] == "BULL" else zone["low"],
                manipulation_high = manip["sweep_level"] if manip["direction"] == "BEAR" else zone["high"],
                confirmed        = distrib.get("found", False),
                confidence       = min(confidence, 100),
                candle_index     = zone["start"],
            )
            results.append(amd)

        return results


# ══════════════════════════════════════════════════════════════════════════════
# CRT ENGINE — Candle Range Theory
# ══════════════════════════════════════════════════════════════════════════════

class CRTEngine:
    """
    Analyses individual candles for CRT manipulation patterns.
    Best timeframes: 5M, 15M, 1H.
    Key insight: manipulation sweep always happens BEFORE true delivery.
    """

    def __init__(self,
                 min_wick_body_ratio: float = 0.3,
                 min_sweep_pct: float = 0.1):
        self.min_wick_body_ratio = min_wick_body_ratio
        self.min_sweep_pct       = min_sweep_pct

    def analyse_candle(self, row: pd.Series,
                        symbol: str = "",
                        timeframe: str = "15minute") -> CRTCandle:
        """
        Analyse a single candle for CRT pattern.
        row: pandas Series with open, high, low, close columns.
        """
        o, h, lo, c = row['open'], row['high'], row['low'], row['close']

        body_size  = abs(c - o)
        full_range = h - lo
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - lo

        # Basic candle direction
        if c > o:
            candle_type = "BULLISH"
        elif c < o:
            candle_type = "BEARISH"
        else:
            candle_type = "DOJI"

        # CRT pattern classification
        # Type 1 Bull: sweeps low first, closes bullish near high
        # Type 2 Bear: sweeps high first, closes bearish near low
        # Type 3 Mixed: sweeps both sides
        # Type 4 Doji: no clear direction

        lower_wick_pct = (lower_wick / full_range * 100) if full_range > 0 else 0
        upper_wick_pct = (upper_wick / full_range * 100) if full_range > 0 else 0
        body_pct       = (body_size  / full_range * 100) if full_range > 0 else 0

        # Determine CRT pattern type
        if candle_type == "BULLISH" and lower_wick_pct >= 25:
            crt_pattern       = "TYPE1_BULL"
            manipulation_side = "LOW_SWEEP"
            true_direction    = "UP"
            manipulation_wick = lower_wick
        elif candle_type == "BEARISH" and upper_wick_pct >= 25:
            crt_pattern       = "TYPE2_BEAR"
            manipulation_side = "HIGH_SWEEP"
            true_direction    = "DOWN"
            manipulation_wick = upper_wick
        elif lower_wick_pct >= 20 and upper_wick_pct >= 20:
            # Both wicks significant — direction from body
            crt_pattern       = "TYPE3_MIXED"
            manipulation_side = "BOTH"
            true_direction    = "UP" if c > o else "DOWN"
            manipulation_wick = max(lower_wick, upper_wick)
        elif body_pct <= 20:
            crt_pattern       = "TYPE4_DOJI"
            manipulation_side = "NONE"
            true_direction    = "SIDEWAYS"
            manipulation_wick = 0
        else:
            crt_pattern       = "STANDARD"
            manipulation_side = "NONE"
            true_direction    = "UP" if c > o else "DOWN"
            manipulation_wick = 0

        # Entry zone: return to open (±0.3% of open)
        entry_zone_high = o * 1.003
        entry_zone_low  = o * 0.997

        # Stop loss: beyond manipulation wick
        if manipulation_side == "LOW_SWEEP":
            stop_loss = lo * 0.998   # Just below the wick low
        elif manipulation_side == "HIGH_SWEEP":
            stop_loss = h * 1.002   # Just above the wick high
        elif manipulation_side == "BOTH":
            stop_loss = lo * 0.998 if true_direction == "UP" else h * 1.002
        else:
            stop_loss = lo * 0.998 if true_direction == "UP" else h * 1.002

        # Confidence scoring
        confidence = 40.0
        if crt_pattern in ("TYPE1_BULL", "TYPE2_BEAR"):
            confidence += 30
        if crt_pattern == "TYPE3_MIXED":
            confidence += 20
        if lower_wick_pct >= 35 or upper_wick_pct >= 35:
            confidence += 15
        if body_pct >= 50:
            confidence += 15

        return CRTCandle(
            symbol           = symbol,
            timeframe        = timeframe,
            candle_type      = candle_type,
            crt_pattern      = crt_pattern,
            open             = round(o, 2),
            high             = round(h, 2),
            low              = round(lo, 2),
            close            = round(c, 2),
            manipulation_side= manipulation_side,
            manipulation_wick= round(manipulation_wick, 2),
            true_direction   = true_direction,
            entry_zone_high  = round(entry_zone_high, 2),
            entry_zone_low   = round(entry_zone_low, 2),
            stop_loss        = round(stop_loss, 2),
            confidence       = round(min(confidence, 100), 1),
        )

    def scan_candles(self, df: pd.DataFrame,
                      symbol: str = "",
                      timeframe: str = "15minute",
                      last_n: int = 10) -> list:
        """
        Scan last N candles for CRT patterns.
        Returns list of CRTCandle results with meaningful patterns.
        """
        results = []
        scan_df  = df.tail(last_n)

        for idx, row in scan_df.iterrows():
            crt = self.analyse_candle(row, symbol, timeframe)
            if crt.crt_pattern not in ("STANDARD", "TYPE4_DOJI"):
                results.append(crt)

        return results

    def detect_opening_crt(self, df: pd.DataFrame,
                            symbol: str = "BANKNIFTY",
                            timeframe: str = "5minute") -> Optional[CRTCandle]:
        """
        Special function for 9:15-9:30 AM opening candle CRT analysis.
        The opening candle on NSE almost always shows CRT manipulation.
        Called by fo_module.py at 9:30 AM.
        """
        if df.empty or len(df) < 2:
            return None

        # Get the 9:15 AM candle
        opening_candle = df.iloc[0]

        # Check if this is actually the opening candle (should be at market open)
        crt = self.analyse_candle(opening_candle, symbol, timeframe)

        # Opening candle CRT is only actionable if clear manipulation exists
        if crt.manipulation_side in ("LOW_SWEEP", "HIGH_SWEEP", "BOTH"):
            crt.confidence = min(crt.confidence + 20, 100)  # Boost for opening
            return crt

        return None


# ══════════════════════════════════════════════════════════════════════════════
# C4 ENGINE — Consolidation, Compression, Catalyst, Continuation
# ══════════════════════════════════════════════════════════════════════════════

class C4Engine:
    """
    Detects C4 setups: Consolidation → Compression → Catalyst → Continuation.
    Best timeframes: 5M, 15M for intraday. 1H, 4H for swing.
    """

    def __init__(self,
                 min_consol_bars:    int   = 4,
                 compression_ratio:  float = 0.6,  # Compression = 60% of consolidation range
                 catalyst_wick_pct:  float = 0.3): # Min wick as % of candle range for catalyst
        self.min_consol_bars   = min_consol_bars
        self.compression_ratio = compression_ratio
        self.catalyst_wick_pct = catalyst_wick_pct
        self.crt_engine        = CRTEngine()

    def detect_consolidation(self, df: pd.DataFrame,
                              lookback: int = 20) -> Optional[dict]:
        """Find the most recent clear consolidation in the last N candles."""
        scan = df.tail(lookback)
        best_zone = None

        for i in range(len(scan) - self.min_consol_bars):
            window   = scan.iloc[i:i + self.min_consol_bars]
            z_high   = window['high'].max()
            z_low    = window['low'].min()
            range_pct = ((z_high - z_low) / z_low) * 100

            if range_pct <= 2.5:  # Max 2.5% range = consolidation
                if best_zone is None or range_pct < best_zone["range_pct"]:
                    best_zone = {
                        "high":      z_high,
                        "low":       z_low,
                        "range_pct": range_pct,
                        "bars":      self.min_consol_bars,
                        "start_idx": i,
                    }

        return best_zone

    def detect_compression(self, df: pd.DataFrame,
                            consol: dict,
                            last_n: int = 5) -> Optional[dict]:
        """
        After consolidation, detect if candles are compressing (narrowing).
        Compression = candle ranges getting smaller within the consolidation.
        """
        recent = df.tail(last_n)
        ranges = [r['high'] - r['low'] for _, r in recent.iterrows()]

        if len(ranges) < 3:
            return None

        # Check if ranges are generally decreasing
        consol_range = consol["high"] - consol["low"]
        avg_recent   = np.mean(ranges[-3:])

        compression_ratio = avg_recent / max(consol_range, 0.001)

        if compression_ratio <= self.compression_ratio:
            return {
                "found":            True,
                "compression_ratio": round(compression_ratio, 3),
                "narrowing":        ranges[-1] < ranges[-2] < ranges[-3],
                "avg_range":        round(avg_recent, 2),
            }
        return None

    def detect_catalyst(self, df: pd.DataFrame,
                         consol: dict) -> Optional[CRTCandle]:
        """
        Detect the catalyst candle — the CRT manipulation sweep that signals
        the true direction. Must be a liquidity sweep beyond consolidation range.
        """
        # Look at the most recent 3 candles for the catalyst
        recent = df.tail(3)

        for idx, row in recent.iterrows():
            # Catalyst must sweep beyond consolidation zone
            swept_low  = row['low']  < consol["low"]  * 0.9985
            swept_high = row['high'] > consol["high"] * 1.0015

            if swept_low or swept_high:
                crt = self.crt_engine.analyse_candle(row)

                # Valid catalyst: swept zone AND reversed (body opposite to sweep)
                if swept_low and row['close'] > row['open']:
                    # Swept below, closed bullish = BULL catalyst
                    crt.true_direction    = "UP"
                    crt.manipulation_side = "LOW_SWEEP"
                    crt.confidence        = min(crt.confidence + 25, 100)
                    return crt
                elif swept_high and row['close'] < row['open']:
                    # Swept above, closed bearish = BEAR catalyst
                    crt.true_direction    = "DOWN"
                    crt.manipulation_side = "HIGH_SWEEP"
                    crt.confidence        = min(crt.confidence + 25, 100)
                    return crt

        return None

    def detect_setup(self, df: pd.DataFrame,
                      symbol: str = "",
                      timeframe: str = "15minute",
                      amd_zones: list = None) -> Optional[C4Setup]:
        """
        Full C4 detection on a DataFrame.
        Returns C4Setup if a valid setup is found, else None.
        """
        if len(df) < 15:
            return None

        # Step 1: Find consolidation
        consol = self.detect_consolidation(df)
        if not consol:
            return None

        # Step 2: Find compression within consolidation
        compress = self.detect_compression(df, consol)
        if not compress:
            # Still report CONSOLIDATION stage
            stage = "CONSOLIDATION"
        else:
            stage = "COMPRESSION"

        # Step 3: Find catalyst (CRT sweep candle)
        catalyst = self.detect_catalyst(df, consol)

        if catalyst:
            stage = "CATALYST"
            direction = catalyst.true_direction
        else:
            # Determine likely direction from AMD or trend
            direction = self._determine_direction(df, consol, amd_zones)

        # Step 4: Check if continuation has started
        is_continuation = self._check_continuation(df, consol, direction)
        if is_continuation and catalyst:
            stage = "CONTINUATION"

        # Calculate trade levels
        if direction == "UP":
            entry  = consol["high"] + (consol["high"] - consol["low"]) * 0.1
            sl     = catalyst.stop_loss if catalyst else consol["low"] * 0.998
            risk   = entry - sl
            t1     = entry + risk * 2
            t2     = entry + risk * 3
            t3     = self._find_liquidity_target(df, "UP")
        else:
            entry = consol["low"] - (consol["high"] - consol["low"]) * 0.1
            sl    = catalyst.stop_loss if catalyst else consol["high"] * 1.002
            risk  = sl - entry
            t1    = entry - risk * 2
            t2    = entry - risk * 3
            t3    = self._find_liquidity_target(df, "DOWN")

        rrr = round(abs(t2 - entry) / max(abs(entry - sl), 0.001), 2)

        # Confidence scoring
        confidence = 40.0
        if compress:
            confidence += 15
        if catalyst:
            confidence += 25
        if catalyst and catalyst.confidence >= 70:
            confidence += 10
        if is_continuation:
            confidence += 10
        # AMD alignment bonus
        aligned_with_amd = False
        if amd_zones:
            for amd in amd_zones:
                if amd.direction == direction and amd.confirmed:
                    confidence += 15
                    aligned_with_amd = True
                    break
        if rrr >= 3.0:
            confidence += 5

        if direction == "SIDEWAYS":
            return None

        return C4Setup(
            symbol             = symbol,
            timeframe          = timeframe,
            stage              = stage,
            direction          = direction,
            consolidation_high = round(consol["high"], 2),
            consolidation_low  = round(consol["low"],  2),
            compression_range  = compress["compression_ratio"] if compress else 1.0,
            catalyst_candle    = catalyst,
            entry_price        = round(entry, 2),
            stop_loss          = round(sl, 2),
            target_1           = round(t1, 2),
            target_2           = round(t2, 2),
            target_3           = round(t3, 2),
            rrr                = rrr,
            confidence         = round(min(confidence, 100), 1),
            aligned_with_amd   = aligned_with_amd,
        )

    def _determine_direction(self, df: pd.DataFrame,
                              consol: dict,
                              amd_zones: list = None) -> str:
        """Determine likely C4 direction from higher timeframe context."""
        if amd_zones:
            for amd in amd_zones:
                if amd.confirmed:
                    return "UP" if amd.direction == "BULL" else "DOWN"

        # Fallback: trend direction from last 20 candles
        if len(df) >= 20:
            recent = df.tail(20)
            ema20  = recent['close'].ewm(span=20).mean()
            if ema20.iloc[-1] > ema20.iloc[-10]:
                return "UP"
            else:
                return "DOWN"

        return "SIDEWAYS"

    def _check_continuation(self, df: pd.DataFrame,
                              consol: dict,
                              direction: str) -> bool:
        """Check if continuation move has started after the catalyst."""
        last_close = df['close'].iloc[-1]
        if direction == "UP":
            return last_close > consol["high"] * 1.002
        elif direction == "DOWN":
            return last_close < consol["low"] * 0.998
        return False

    def _find_liquidity_target(self, df: pd.DataFrame, direction: str) -> float:
        """Find the nearest liquidity pool (swing high/low) as Target 3."""
        if direction == "UP":
            # Find previous swing high (liquidity pool)
            highs  = df['high'].rolling(5).max()
            recent = highs.dropna()
            if len(recent) > 10:
                return round(recent.iloc[-10:].max() * 1.002, 2)
            return round(df['high'].max() * 1.002, 2)
        else:
            # Find previous swing low (liquidity pool)
            lows   = df['low'].rolling(5).min()
            recent = lows.dropna()
            if len(recent) > 10:
                return round(recent.iloc[-10:].min() * 0.998, 2)
            return round(df['low'].min() * 0.998, 2)


# ══════════════════════════════════════════════════════════════════════════════
# MASTER SMC ENGINE — Orchestrates all three
# ══════════════════════════════════════════════════════════════════════════════

class SMCEngine:
    """
    Master Smart Money Concepts engine.
    Runs AMD + CRT + C4 together and returns combined analysis.
    Designed to integrate with your MKUMARAN Trading OS.
    """

    def __init__(self):
        self.amd = AMDEngine()
        self.crt = CRTEngine()
        self.c4  = C4Engine()

    def analyse(self, df: pd.DataFrame,
                 symbol: str = "",
                 timeframe: str = "15minute") -> dict:
        """
        Full SMC analysis on a DataFrame.
        Returns combined AMD + CRT + C4 results.

        Args:
            df: DataFrame with open, high, low, close, volume columns
            symbol: e.g. "NSE:BANKNIFTY" or "NSE:RELIANCE"
            timeframe: "5minute", "15minute", "60minute", "day"

        Returns:
            dict with keys: amd_zones, crt_candles, c4_setup, confidence_boost,
                           trade_signal, telegram_summary
        """
        results = {
            "symbol":           symbol,
            "timeframe":        timeframe,
            "timestamp":        now_ist().isoformat(),
            "amd_zones":        [],
            "crt_candles":      [],
            "c4_setup":         None,
            "smc_direction":    "NEUTRAL",
            "confidence_boost": 0,
            "trade_signal":     None,
            "telegram_summary": "",
        }

        if df.empty or len(df) < 10:
            return results

        # 1. AMD analysis (higher timeframe context)
        amd_zones = self.amd.scan(df, symbol)
        results["amd_zones"] = amd_zones

        # 2. CRT analysis (recent candles)
        crt_candles = self.crt.scan_candles(df, symbol, timeframe, last_n=10)
        results["crt_candles"] = crt_candles

        # 3. C4 setup detection
        c4_setup = self.c4.detect_setup(df, symbol, timeframe, amd_zones)
        results["c4_setup"] = c4_setup

        # 4. Determine overall SMC direction
        direction = self._determine_overall_direction(amd_zones, crt_candles, c4_setup)
        results["smc_direction"] = direction

        # 5. Calculate confidence boost for validator.py
        boost = self._calculate_confidence_boost(amd_zones, crt_candles, c4_setup, direction)
        results["confidence_boost"] = boost

        # 6. Generate trade signal if all aligned
        if c4_setup and c4_setup.stage in ("CATALYST", "CONTINUATION") and boost >= 15:
            results["trade_signal"] = {
                "action":     "BUY"  if c4_setup.direction == "UP" else "SELL",
                "entry":      c4_setup.entry_price,
                "sl":         c4_setup.stop_loss,
                "target_1":   c4_setup.target_1,
                "target_2":   c4_setup.target_2,
                "target_3":   c4_setup.target_3,
                "rrr":        c4_setup.rrr,
                "confidence": c4_setup.confidence,
                "stage":      c4_setup.stage,
            }

        # 7. Format Telegram summary
        results["telegram_summary"] = self.format_smc_card(results)

        return results

    def _determine_overall_direction(self, amd_zones, crt_candles, c4_setup) -> str:
        bull_score = bear_score = 0

        for amd in amd_zones:
            if amd.confirmed:
                if amd.direction == "BULL":
                    bull_score += 2
                else:
                    bear_score += 2

        for crt in crt_candles[-3:]:  # Last 3 CRT candles
            if crt.true_direction == "UP":
                bull_score += 1
            elif crt.true_direction == "DOWN":
                bear_score += 1

        if c4_setup:
            if c4_setup.direction == "UP":
                bull_score += 2
            elif c4_setup.direction == "DOWN":
                bear_score += 2

        if bull_score > bear_score:
            return "BULL"
        elif bear_score > bull_score:
            return "BEAR"
        return "NEUTRAL"

    def _calculate_confidence_boost(self, amd_zones, crt_candles,
                                     c4_setup, direction) -> int:
        """
        Returns confidence boost % to add to existing RRMS signal confidence.
        Max +30%.
        """
        boost = 0

        # AMD alignment
        for amd in amd_zones:
            if amd.confirmed:
                amd_dir = "BULL" if amd.direction == "BULL" else "BEAR"
                if amd_dir == direction:
                    boost += 10
                    break

        # CRT catalyst present
        for crt in crt_candles[-3:]:
            crt_dir = "BULL" if crt.true_direction == "UP" else "BEAR"
            if crt_dir == direction and crt.crt_pattern in ("TYPE1_BULL", "TYPE2_BEAR"):
                boost += 8
                break

        # C4 setup active
        if c4_setup and c4_setup.stage in ("CATALYST", "CONTINUATION"):
            c4_dir = "BULL" if c4_setup.direction == "UP" else "BEAR"
            if c4_dir == direction:
                boost += 12

        return min(boost, 30)

    def format_smc_card(self, results: dict) -> str:
        """Format SMC analysis as Telegram message section."""
        direction = results["smc_direction"]
        emoji = {"BULL": "🟢", "BEAR": "🔴", "NEUTRAL": "⚪"}.get(direction, "⚪")
        boost = results["confidence_boost"]

        lines = [
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "[SMC ANALYSIS — ICT CONCEPTS]",
            f"Direction : {emoji} {direction} (+{boost}% confidence)",
        ]

        # AMD summary
        amd_zones = results.get("amd_zones", [])
        confirmed_amd = [a for a in amd_zones if a.confirmed]
        if confirmed_amd:
            latest = confirmed_amd[-1]
            lines.append(f"AMD Zone  : {latest.direction} — {latest.phase} ✅")
            lines.append(f"           Zone {latest.zone_low:.0f}–{latest.zone_high:.0f}")
        else:
            lines.append("AMD Zone  : No confirmed zone")

        # CRT summary
        crt_candles = results.get("crt_candles", [])
        if crt_candles:
            latest_crt = crt_candles[-1]
            lines.append(f"CRT       : {latest_crt.crt_pattern} — {latest_crt.manipulation_side}")
            lines.append(f"           Sweep → True dir: {latest_crt.true_direction}")
        else:
            lines.append("CRT       : No manipulation pattern")

        # C4 summary
        c4 = results.get("c4_setup")
        if c4:
            lines.append(f"C4 Setup  : Stage {c4.stage} — {c4.direction}")
            lines.append(f"           Consol {c4.consolidation_low:.0f}–{c4.consolidation_high:.0f}")
            if c4.catalyst_candle:
                lines.append(f"           Catalyst: {c4.catalyst_candle.crt_pattern} ✅")
            lines.append(f"           AMD aligned: {'YES ✅' if c4.aligned_with_amd else 'NO'}")
        else:
            lines.append("C4 Setup  : Not detected")

        # Trade signal
        signal = results.get("trade_signal")
        if signal:
            lines.append(f"SMC Entry : {signal['action']} @ ₹{signal['entry']}")
            lines.append(f"SMC SL    : ₹{signal['sl']}")
            lines.append(f"SMC Tgt 1 : ₹{signal['target_1']} (1:{round(signal['rrr']*0.67, 1)})")
            lines.append(f"SMC Tgt 2 : ₹{signal['target_2']} (1:{signal['rrr']})")

        return "\n".join(lines)


# ─── F&O SPECIFIC FUNCTIONS ───────────────────────────────────────────────────

def crt_fo_entry(df_5m: pd.DataFrame,
                  index: str = "BANKNIFTY") -> dict:
    """
    Special CRT-based F&O entry for BankNifty / Nifty intraday.
    Called by fo_module.py at 9:30 AM after the opening candle prints.

    Logic:
    - 9:15 AM opening candle almost always = CRT candle
    - Sweep one side first (manipulation)
    - Enter on return to open
    - Target: previous day's high/low (opposing liquidity)
    """
    engine = CRTEngine()
    crt    = engine.detect_opening_crt(df_5m, symbol=index, timeframe="5minute")

    if not crt:
        return {"signal": "WAIT", "reason": "No clear CRT opening candle"}

    risk     = abs(crt.entry_zone_low - crt.stop_loss)
    if risk <= 0:
        return {"signal": "WAIT", "reason": "Zero risk — invalid CRT"}

    target_1 = crt.entry_zone_low + risk * 2 if crt.true_direction == "UP" \
               else crt.entry_zone_high - risk * 2
    target_2 = crt.entry_zone_low + risk * 3 if crt.true_direction == "UP" \
               else crt.entry_zone_high - risk * 3

    return {
        "signal":           "BUY" if crt.true_direction == "UP" else "SELL",
        "index":            index,
        "timeframe":        "5minute",
        "crt_type":         crt.crt_pattern,
        "manipulation":     crt.manipulation_side,
        "entry_zone_high":  crt.entry_zone_high,
        "entry_zone_low":   crt.entry_zone_low,
        "stop_loss":        crt.stop_loss,
        "target_1":         round(target_1, 0),
        "target_2":         round(target_2, 0),
        "rrr":              round(abs(target_2 - crt.entry_zone_low) / max(risk, 1), 2),
        "confidence":       crt.confidence,
        "reasoning":        f"Opening candle {crt.crt_pattern}: swept {crt.manipulation_side} "
                            f"(wick: {crt.manipulation_wick:.0f} pts), "
                            f"true direction → {crt.true_direction}",
    }


def smc_confidence_boost(smc_result: dict,
                          rrms_direction: str) -> int:
    """
    Calculate confidence boost from SMC analysis for validator.py.
    Add this to existing Claude AI confidence score.

    Args:
        smc_result: output from SMCEngine.analyse()
        rrms_direction: "BULL" or "BEAR" from your RRMS signal

    Returns:
        int: confidence boost (0–30)
    """
    smc_direction = smc_result.get("smc_direction", "NEUTRAL")
    boost         = smc_result.get("confidence_boost", 0)

    # Only boost if SMC agrees with RRMS direction
    if smc_direction == rrms_direction:
        return boost
    elif smc_direction == "NEUTRAL":
        return boost // 2
    else:
        # SMC disagrees with RRMS — reduce boost
        return -5


# ─── INTEGRATION EXAMPLE ──────────────────────────────────────────────────────

if __name__ == "__main__":
    """
    Test with dummy data. In production, replace with provider.get_ohlcv()
    """
    print("SMC Engine — MKUMARAN Trading OS")
    print("=" * 50)

    # Create sample OHLCV data
    import random
    random.seed(42)
    dates  = pd.date_range("2025-03-01 09:15", periods=60, freq="15min")
    base   = 47000

    data = []
    for i, dt in enumerate(dates):
        o = base + random.randint(-100, 100)
        c = o + random.randint(-80, 80)
        h = max(o, c) + random.randint(5, 60)
        lo = min(o, c) - random.randint(5, 60)
        v = random.randint(50000, 200000)
        data.append({"date": dt, "open": o, "high": h, "low": lo, "close": c, "volume": v})
        base = c

    df = pd.DataFrame(data).set_index("date")

    smc    = SMCEngine()
    result = smc.analyse(df, symbol="NSE:BANKNIFTY", timeframe="15minute")

    print(f"SMC Direction : {result['smc_direction']}")
    print(f"Conf Boost    : +{result['confidence_boost']}%")
    print(f"AMD Zones     : {len(result['amd_zones'])} found")
    print(f"CRT Candles   : {len(result['crt_candles'])} patterns")
    print(f"C4 Stage      : {result['c4_setup'].stage if result['c4_setup'] else 'None'}")
    print()
    print("Telegram card preview:")
    print(result["telegram_summary"])
