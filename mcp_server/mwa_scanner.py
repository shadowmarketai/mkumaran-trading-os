"""
MKUMARAN Trading OS — 156-Scanner MWA System

CURRENT COUNT (source of truth — README/TRADING/CLAUDE reconciled to this):
  156 scanners across 15 layers:
    Trend(16) / Volume(8) / Breakout(13) / RSI(8) / Gap(6) / MA(6) /
    Filter(5) / SMC(32) / Wyckoff(8) / VSA(8) / Harmonic(6) / RL(8) /
    Forex(8) / Commodity(8) / FnO(16)
  Mix: ~34 Chartink slugs + ~122 Python implementations
  28+ signal chains (Original / SMC / Cross-engine / RL / Forex /
  Commodity / FnO)
"""

import logging
import os
import re
import time
import json
import requests

from mcp_server.market_calendar import now_ist

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# 156 SCANNERS — 15 LAYERS
# Trend(16) Volume(8) Breakout(13) RSI(8) Gap(6) MA(6) Filter(5)
# SMC(32) Wyckoff(8) VSA(8) Harmonic(6) RL(8) Forex(8) Commodity(8) FnO(16)
# Source of truth — README/TRADING/CLAUDE docs are reconciled to these
# numbers. If you add or retire scanners, update this header AND the
# 156/15 references in the three docs.
# ══════════════════════════════════════════════════════════════

SCANNERS = {

    # ── LAYER 1 — TREND DIRECTION (8 scanners) ──────────────

    "swing_low": {
        "no": 1, "slug": "copy-swing-low-daily-100",
        "type": "BULL", "weight": 2.5, "layer": "Trend", "source": "Chartink",
        "desc": "Personal swing low. Stock at swing low = at LTRP zone. Core RRMS long entry trigger.",
        "pairs_with": ["upswing", "volume_avg", "rsi_above_30", "llbb_bounce"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest low <= min( 20 , latest low ) and latest close > latest open and latest volume > 10000 ) )",
    },
    "upswing": {
        "no": 2, "slug": "copy-upswing-daily-82",
        "type": "BULL", "weight": 2.5, "layer": "Trend", "source": "Chartink",
        "desc": "Personal upswing. Higher highs + higher lows. Rule 3 enforcer for longs.",
        "pairs_with": ["swing_low", "bandwalk_highs", "breakout_200dma"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest high > 1 day ago high and latest low > 1 day ago low and 1 day ago high > 2 days ago high and 1 day ago low > 2 days ago low ) )",
    },
    "swing_high": {
        "no": 3, "slug": "copy-swing-high-daily-192",
        "type": "BEAR", "weight": 2.5, "layer": "Trend", "source": "Chartink",
        "desc": "Personal swing high. Near Pivot High / short zone.",
        "pairs_with": ["downswing", "failure_swing_bearish", "macd_sell_weekly"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest high >= max( 20 , latest high ) and latest close < latest open and latest volume > 10000 ) )",
    },
    "downswing": {
        "no": 4, "slug": "copy-downswing-daily-177",
        "type": "BEAR", "weight": 2.5, "layer": "Trend", "source": "Chartink",
        "desc": "Personal downswing. Lower highs + lower lows. Rule 3 for shorts.",
        "pairs_with": ["swing_high", "bearish_divergence", "macd_sell_weekly"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest high < 1 day ago high and latest low < 1 day ago low and 1 day ago high < 2 days ago high and 1 day ago low < 2 days ago low ) )",
    },
    "bandwalk_highs": {
        "no": 5, "slug": "copy-bandwalk-with-highs-green-candle-daily-150",
        "type": "BULL", "weight": 2.5, "layer": "Trend", "source": "Chartink",
        "desc": "Bandwalk: hugging upper BB making new highs with green candle.",
        "pairs_with": ["upswing", "breakout_200dma", "volume_spike"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest high >= max( 5 , latest high ) and latest close > latest open and latest high >= latest upper bollinger band( 20 , 2 ) ) )",
    },
    "llbb_bounce": {
        "no": 6, "slug": "copy-todays-low-bounced-off-llbb-and-green-candle-close-184",
        "type": "BULL", "weight": 2.5, "layer": "Trend", "source": "Chartink",
        "desc": "Low touched Lower BB + green candle close. RRMS LTRP bounce confirmation.",
        "pairs_with": ["swing_low", "rsi_above_30", "failure_swing_bullish", "near_200ma_v2"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest low <= latest lower bollinger band( 20 , 2 ) and latest close > latest open ) )",
    },
    "macd_sell_weekly": {
        "no": 7, "slug": "copy-macd-sell-call-weekly-chart-170",
        "type": "BEAR", "weight": 2.5, "layer": "Trend", "source": "Chartink",
        "desc": "MACD sell on weekly chart. Higher timeframe bearish conviction.",
        "pairs_with": ["swing_high", "downswing", "failure_swing_bearish", "bearish_divergence"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest macd line( 26 , 12 , 9 ) < latest macd signal( 26 , 12 , 9 ) and 1 day ago macd line( 26 , 12 , 9 ) > 1 day ago macd signal( 26 , 12 , 9 ) ) )",
    },
    "supertrend_buy": {
        "no": 8, "slug": "python:scan_supertrend",
        "type": "BULL", "weight": 2.0, "layer": "Trend", "source": "Python",
        "desc": "Supertrend(7,3) flips to buy. Runs on live OHLCV.",
        "pairs_with": ["swing_low", "upswing", "breakout_200dma"],
        "status": "ACTIVE",
    },

    # ── LAYER 2 — VOLUME & MOMENTUM (6 scanners) ────────────

    "volume_avg": {
        "no": 9, "slug": "copy-volume-previous-50-days-average-volume-194",
        "type": "BULL", "weight": 2.0, "layer": "Volume", "source": "Chartink",
        "desc": "Volume above 50-day average. Mandatory cross-reference for every breakout.",
        "pairs_with": ["swing_low", "breakout_50day", "breakout_200dma"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest volume > latest sma( volume , 50 ) ) )",
    },
    "volume_spike": {
        "no": 10, "slug": "copy-volume-previous-50-days-average-volume-10-173",
        "type": "BULL", "weight": 3.0, "layer": "Volume", "source": "Chartink",
        "desc": "Volume spike 2x+ 50-day average. STRONG institutional move.",
        "pairs_with": ["breakout_200dma", "breakout_50day", "richie_rich_breakout"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest volume > latest sma( volume , 50 ) * 2 ) )",
    },
    "daily_pct_change": {
        "no": 11, "slug": "python:daily_pct_change",
        "type": "BULL", "weight": 1.0, "layer": "Volume", "source": "Python",
        "desc": "Daily % change > 3%. Python formula replaces broken Chartink scanner.",
        "pairs_with": ["volume_avg", "breakout_200dma"],
        "status": "ACTIVE",
    },
    "macd_buy_hourly": {
        "no": 12, "slug": "copy-macd-buy-call-hourly-chart-189",
        "type": "BULL", "weight": 2.0, "layer": "Volume", "source": "Chartink",
        "desc": "MACD buy on hourly chart. Intraday momentum confirmation.",
        "pairs_with": ["buy_morning_9_30", "gap_up", "ema_crossover_bn"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest macd line( 26 , 12 , 9 ) > latest macd signal( 26 , 12 , 9 ) and latest macd line( 26 , 12 , 9 ) > 0 ) )",
    },
    "macd_buy_daily": {
        "no": 13, "slug": "mk-macd-buy-call-daily",
        "type": "BULL", "weight": 2.5, "layer": "Volume", "source": "Chartink",
        "desc": "MACD buy on daily chart. Swing trade momentum entry.",
        "pairs_with": ["swing_low", "upswing", "breakout_200dma"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest macd line( 26 , 12 , 9 ) crossed above latest macd signal( 26 , 12 , 9 ) ) )",
    },
    "buy_morning_9_30": {
        "no": 14, "slug": "copy-buy-100-accuracy-morning-scanner-scan-at-9-30-20985",
        "type": "BULL", "weight": 2.5, "layer": "Volume", "source": "Chartink",
        "desc": "High-accuracy morning buy scanner. Multi-condition entry for 9:30 AM.",
        "pairs_with": ["gap_up", "volume_spike", "macd_buy_hourly", "ema_crossover_bn"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest close > latest open and latest close > latest ema( close , 9 ) and latest close > latest ema( close , 21 ) and latest volume > latest sma( volume , 20 ) and latest rsi( 14 ) > 50 ) )",
    },

    # ── LAYER 3 — BREAKOUT & BREAKDOWN (6 scanners) ─────────

    "breakout_50day": {
        "no": 15, "slug": "copy-todays-close-surpassing-the-50-days-high-range-179",
        "type": "BULL", "weight": 2.0, "layer": "Breakout", "source": "Chartink",
        "desc": "Breaks above 50-day high. Bullish continuation pattern trigger.",
        "pairs_with": ["volume_spike", "volume_avg", "breakout_200dma"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest close > max( 50 , 1 day ago high ) ) )",
    },
    "breakout_200dma": {
        "no": 16, "slug": "copy-surpassing-the-high-with-regime-filter-of-200-dma-and-green-candle-only-181",
        "type": "BULL", "weight": 3.0, "layer": "Breakout", "source": "Chartink",
        "desc": "Breakout + 200 DMA regime filter + green candle. Highest quality breakout scanner.",
        "pairs_with": ["volume_spike", "volume_avg", "upswing", "bandwalk_highs"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest close > max( 20 , 1 day ago high ) and latest close > latest sma( close , 200 ) and latest close > latest open ) )",
    },
    "breakdown_20day": {
        "no": 17, "slug": "copy-todays-low-surpassing-the-20-day-low-range-181",
        "type": "BEAR", "weight": 2.0, "layer": "Breakout", "source": "Chartink",
        "desc": "Breaks below 20-day low. Bearish continuation pattern trigger.",
        "pairs_with": ["downswing", "bearish_divergence", "macd_sell_weekly"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest low < min( 20 , 1 day ago low ) ) )",
    },
    "52week_high": {
        "no": 18, "slug": "mk-52-week-high-breakout",
        "type": "BULL", "weight": 3.0, "layer": "Breakout", "source": "Chartink",
        "desc": "52-week high breakout. Strongest momentum — no overhead resistance.",
        "pairs_with": ["volume_spike", "richie_rich_breakout", "breakout_200dma"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest high >= max( 250 , latest high ) ) )",
    },
    "richie_rich_breakout": {
        "no": 19, "slug": "copy-ffa-richie-rich-breakout-system-2204",
        "type": "BULL", "weight": 3.0, "layer": "Breakout", "source": "Chartink",
        "desc": "FFA Richie Rich Breakout System. Multi-condition: price + volume + momentum + trend.",
        "pairs_with": ["volume_spike", "breakout_200dma", "bandwalk_highs", "richie_rich_tracker"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest close > max( 20 , 1 day ago high ) and latest volume > latest sma( volume , 20 ) * 2 and latest close > latest ema( close , 20 ) and latest rsi( 14 ) > 60 ) )",
    },
    "richie_rich_tracker": {
        "no": 20, "slug": "rich-rich-breakout-tracker-3",
        "type": "BULL", "weight": 2.5, "layer": "Breakout", "source": "Chartink",
        "desc": "Richie Rich Tracker. Follows stocks that broke out and are continuing.",
        "pairs_with": ["richie_rich_breakout", "upswing", "bandwalk_highs"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest close > 5 days ago close and latest close > latest ema( close , 20 ) and latest volume > latest sma( volume , 20 ) ) )",
    },

    # ── LAYER 4 — RSI DIVERGENCE LADDER (6 scanners) ────────

    "bullish_divergence": {
        "no": 21, "slug": "copy-bullish-divergence-occurring-today-205",
        "type": "BULL", "weight": 2.5, "layer": "RSI", "source": "Chartink",
        "desc": "STAGE 1 BULL: Bullish RSI divergence — price lower low + RSI higher low.",
        "pairs_with": ["failure_swing_bullish", "swing_low", "llbb_bounce"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest low < min( 14 , 1 day ago low ) and latest rsi( 14 ) > min( 14 , 1 day ago rsi( 14 ) ) and latest rsi( 14 ) < 40 ) )",
    },
    "bearish_divergence": {
        "no": 22, "slug": "copy-bearish-divergence-occurring-today-189",
        "type": "BEAR", "weight": 2.5, "layer": "RSI", "source": "Chartink",
        "desc": "STAGE 1 BEAR: Bearish RSI divergence — price higher high + RSI lower high.",
        "pairs_with": ["failure_swing_bearish", "swing_high", "macd_sell_weekly"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest high > max( 14 , 1 day ago high ) and latest rsi( 14 ) < max( 14 , 1 day ago rsi( 14 ) ) and latest rsi( 14 ) > 60 ) )",
    },
    "failure_swing_bullish": {
        "no": 23, "slug": "copy-failure-swing-bullish-divergence-occurring-today-185",
        "type": "BULL", "weight": 2.5, "layer": "RSI", "source": "Chartink",
        "desc": "STAGE 2 BULL: RSI failure swing confirmation.",
        "pairs_with": ["bullish_divergence", "swing_low", "upswing", "llbb_bounce"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest rsi( 14 ) > 30 and 1 day ago rsi( 14 ) < 30 and latest close > latest open ) )",
    },
    "failure_swing_bearish": {
        "no": 24, "slug": "copy-failure-swing-bearish-divergence-occurring-today-177",
        "type": "BEAR", "weight": 2.5, "layer": "RSI", "source": "Chartink",
        "desc": "STAGE 2 BEAR: RSI failure swing confirmation.",
        "pairs_with": ["bearish_divergence", "swing_high", "downswing", "macd_sell_weekly"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest rsi( 14 ) < 70 and 1 day ago rsi( 14 ) > 70 and latest close < latest open ) )",
    },
    "rsi_above_30": {
        "no": 25, "slug": "copy-rsi-crossed-above-30-zones-188",
        "type": "BULL", "weight": 2.0, "layer": "RSI", "source": "Chartink",
        "desc": "STAGE 3 BULL: RSI crosses above 30. Momentum confirmed after divergence.",
        "pairs_with": ["swing_low", "llbb_bounce", "failure_swing_bullish"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest rsi( 14 ) > 30 and 1 day ago rsi( 14 ) <= 30 ) )",
    },
    "rsi_below_70": {
        "no": 26, "slug": "copy-rsi-crossed-below-70-zones-180",
        "type": "BEAR", "weight": 2.0, "layer": "RSI", "source": "Chartink",
        "desc": "STAGE 3 BEAR: RSI crosses below 70. Momentum confirmed after divergence.",
        "pairs_with": ["swing_high", "failure_swing_bearish", "bearish_divergence"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest rsi( 14 ) < 70 and 1 day ago rsi( 14 ) >= 70 ) )",
    },

    # ── LAYER 5 — GAP & INTRADAY EMA (4 scanners) ───────────

    "gap_up": {
        "no": 27, "slug": "copy-gap-up-daily-199",
        "type": "BULL", "weight": 1.5, "layer": "Gap", "source": "Chartink",
        "desc": "Personal gap up. Opens above yesterday's high.",
        "pairs_with": ["upswing", "macd_buy_hourly", "buy_morning_9_30"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest open > 1 day ago high ) )",
    },
    "gap_down": {
        "no": 28, "slug": "copy-gap-down-daily-171",
        "type": "BEAR", "weight": 1.5, "layer": "Gap", "source": "Chartink",
        "desc": "Personal gap down. Opens below yesterday's low.",
        "pairs_with": ["downswing", "bearish_divergence"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest open < 1 day ago low ) )",
    },
    "ema_crossover_bn": {
        "no": 29, "slug": "copy-5-and-10-crossover-hourly-196",
        "type": "BULL", "weight": 1.5, "layer": "Gap", "source": "Chartink",
        "desc": "BankNifty 5/10 EMA crossover hourly. F&O intraday trigger.",
        "pairs_with": ["macd_buy_hourly", "buy_morning_9_30", "gap_up"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest ema( close , 5 ) > latest ema( close , 10 ) and 1 day ago ema( close , 5 ) <= 1 day ago ema( close , 10 ) ) )",
    },
    "ema_crossover_nifty": {
        "no": 30, "slug": "mk-nifty-5-10-ema-crossover-hourly",
        "type": "BULL", "weight": 1.5, "layer": "Gap", "source": "Chartink",
        "desc": "Nifty 50 5/10 EMA crossover hourly. F&O trigger for Nifty.",
        "pairs_with": ["ema_crossover_bn", "macd_buy_hourly", "buy_morning_9_30"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest ema( close , 5 ) > latest ema( close , 10 ) and 1 day ago ema( close , 5 ) <= 1 day ago ema( close , 10 ) ) )",
    },

    # ── LAYER 6 — MA SUPPORT ZONES (5 scanners) ─────────────

    "near_100ma": {
        "no": 31, "slug": "copy-moving-average-100-goldmine-futures-170",
        "type": "BULL", "weight": 1.5, "layer": "MA", "source": "Chartink",
        "desc": "Near 100-day MA. Medium-term support zone.",
        "pairs_with": ["swing_low", "rsi_above_30", "llbb_bounce"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest close > latest sma( close , 100 ) * 0.97 and latest close < latest sma( close , 100 ) * 1.03 ) )",
    },
    "near_200ma": {
        "no": 32, "slug": "copy-moving-average-200-goldmine-futures-172",
        "type": "BULL", "weight": 2.0, "layer": "MA", "source": "Chartink",
        "desc": "Near 200-day MA v1. Long-term support zone.",
        "pairs_with": ["swing_low", "near_200ma_v2", "llbb_bounce"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest close > latest sma( close , 200 ) * 0.97 and latest close < latest sma( close , 200 ) * 1.03 ) )",
    },
    "near_200ma_v2": {
        "no": 33, "slug": "copy-moving-average-200-goldmine-futures-304",
        "type": "BULL", "weight": 2.0, "layer": "MA", "source": "Chartink",
        "desc": "Near 200-day MA v2 (newer). Double institutional support confirm.",
        "pairs_with": ["near_200ma", "swing_low", "llbb_bounce"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest close > latest sma( close , 200 ) * 0.95 and latest close < latest sma( close , 200 ) * 1.05 and latest volume > latest sma( volume , 20 ) ) )",
    },
    "muthukumaran_a": {
        "no": 34, "slug": "muthukumaran-3",
        "type": "BULL", "weight": 2.0, "layer": "RSI", "source": "Chartink",
        "desc": "RSI recovery + upswing: Close>prev, HH, HL, RSI(14) crossed above 30.",
        "pairs_with": ["swing_low", "rsi_above_30", "failure_swing_bullish"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest close > 1 day ago close and latest high > 1 day ago high and latest low > 1 day ago low and latest rsi( 14 ) > 30 and 1 day ago rsi( 14 ) <= 30 ) )",
    },
    "muthukumaran_b": {
        "no": 35, "slug": "muthukumaran-2",
        "type": "BULL", "weight": 2.0, "layer": "Trend", "source": "Chartink",
        "desc": "Parabolic SAR buy: Close > SAR(0.02, 0.02, 0.2). Trend-following confirmation.",
        "pairs_with": ["supertrend_buy", "upswing", "breakout_200dma"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest close > latest sar( 0.02 , 0.02 , 0.2 ) and latest close > latest open ) )",
    },

    # ── LAYER 7 — PYTHON PRE-FILTERS (5 items — NOT scored) ─

    "large_cap_filter": {
        "no": 36, "slug": "large-cap-100250",
        "type": "FILTER", "weight": 0.0, "layer": "Filter", "source": "Chartink",
        "desc": "Large cap universe. Cross-reference Tier 1 results against large cap list.",
        "pairs_with": [],
        "status": "ACTIVE",
    },
    "delivery_pct_filter": {
        "no": 37, "slug": "python:apply_delivery_filter",
        "type": "FILTER", "weight": 0.0, "layer": "Filter", "source": "Python",
        "desc": "NSE Delivery % > 60%. Institutional holding confirmation.",
        "pairs_with": [],
        "status": "ACTIVE",
    },
    "fii_dii_filter": {
        "no": 38, "slug": "python:fii_allows_long",
        "type": "FILTER", "weight": 0.0, "layer": "Filter", "source": "Python",
        "desc": "FII/DII net buy day check. Only take new longs when FII net buying.",
        "pairs_with": [],
        "status": "ACTIVE",
    },
    "sector_rotation_filter": {
        "no": 39, "slug": "python:sector_allows_trade",
        "type": "FILTER", "weight": 0.0, "layer": "Filter", "source": "Python",
        "desc": "Sector rotation weekly pre-filter. Blocks long entries in WEAK sectors.",
        "pairs_with": [],
        "status": "ACTIVE",
    },
    "daily_pct_change_py": {
        "no": 40, "slug": "python:daily_pct_change",
        "type": "BULL", "weight": 1.0, "layer": "Filter", "source": "Python",
        "desc": "Daily % change > 3%. Correct Python formula replaces broken Chartink scanner.",
        "pairs_with": ["volume_avg", "breakout_200dma"],
        "status": "ACTIVE",
    },

    # ── LAYER 15 — INSTITUTIONAL / SMART MONEY CHARTINK (20 scanners) ──

    "high_delivery_rise": {
        "no": 175, "slug": "python:chartink",
        "type": "BULL", "weight": 3.0, "layer": "Volume", "source": "Chartink",
        "desc": "Delivery % > 60% AND price rose > 2%. Smart money accumulation signal.",
        "pairs_with": ["volume_spike", "breakout_200dma"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest delivery percentage > 60 and latest close > 1 day ago close * 1.02 and latest volume > 50000 ) )",
    },
    "bulk_deal_breakout": {
        "no": 176, "slug": "python:chartink",
        "type": "BULL", "weight": 3.5, "layer": "Volume", "source": "Chartink",
        "desc": "Stocks with bulk/block deals + price above 20 SMA. Institutional accumulation.",
        "pairs_with": ["high_delivery_rise", "breakout_200dma"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest close > latest sma( close , 20 ) and latest volume > 5 * latest sma( volume , 20 ) and latest close > latest open ) )",
    },
    "ma_stack_bullish": {
        "no": 177, "slug": "python:chartink",
        "type": "BULL", "weight": 3.0, "layer": "MA", "source": "Chartink",
        "desc": "Perfect MA stack: 5>10>20>50>100>200 SMA. Strongest trend confirmation.",
        "pairs_with": ["upswing", "bandwalk_highs"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest sma( close , 5 ) > latest sma( close , 10 ) and latest sma( close , 10 ) > latest sma( close , 20 ) and latest sma( close , 20 ) > latest sma( close , 50 ) and latest sma( close , 50 ) > latest sma( close , 100 ) and latest sma( close , 100 ) > latest sma( close , 200 ) ) )",
    },
    "ma_stack_bearish": {
        "no": 178, "slug": "python:chartink",
        "type": "BEAR", "weight": 3.0, "layer": "MA", "source": "Chartink",
        "desc": "Bearish MA stack: 5<10<20<50<100<200. Perfect downtrend.",
        "pairs_with": ["downswing", "swing_high"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest sma( close , 5 ) < latest sma( close , 10 ) and latest sma( close , 10 ) < latest sma( close , 20 ) and latest sma( close , 20 ) < latest sma( close , 50 ) and latest sma( close , 50 ) < latest sma( close , 100 ) and latest sma( close , 100 ) < latest sma( close , 200 ) ) )",
    },
    "darvas_box_breakout": {
        "no": 179, "slug": "python:chartink",
        "type": "BULL", "weight": 3.5, "layer": "Breakout", "source": "Chartink",
        "desc": "Darvas box breakout: new 52-week high with volume surge. Classic momentum.",
        "pairs_with": ["52week_high", "volume_spike"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest high = max( 252 , latest high ) and latest volume > 2 * latest sma( volume , 20 ) and latest close > latest open ) )",
    },
    "hammer_reversal": {
        "no": 180, "slug": "python:chartink",
        "type": "BULL", "weight": 2.5, "layer": "Trend", "source": "Chartink",
        "desc": "Hammer candlestick at support: long lower wick + small body near highs.",
        "pairs_with": ["swing_low", "rsi_above_30", "llbb_bounce"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( ( latest low - latest min( close , open ) ) > 2 * abs( latest close - latest open ) and ( latest high - latest max( close , open ) ) < 0.3 * abs( latest close - latest open ) and latest close > latest open and latest low <= min( 20 , latest low ) ) )",
    },
    "bearish_engulfing": {
        "no": 181, "slug": "python:chartink",
        "type": "BEAR", "weight": 2.5, "layer": "Trend", "source": "Chartink",
        "desc": "Bearish engulfing at resistance: today's red candle engulfs yesterday's green.",
        "pairs_with": ["swing_high", "rsi_below_70"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest close < latest open and 1 day ago close > 1 day ago open and latest open > 1 day ago close and latest close < 1 day ago open and latest volume > 50000 ) )",
    },
    "bullish_engulfing": {
        "no": 182, "slug": "python:chartink",
        "type": "BULL", "weight": 2.5, "layer": "Trend", "source": "Chartink",
        "desc": "Bullish engulfing at support: today's green candle engulfs yesterday's red.",
        "pairs_with": ["swing_low", "rsi_above_30"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest close > latest open and 1 day ago close < 1 day ago open and latest open < 1 day ago close and latest close > 1 day ago open and latest volume > 50000 ) )",
    },
    "supertrend_buy_daily": {
        "no": 183, "slug": "python:chartink",
        "type": "BULL", "weight": 2.5, "layer": "Trend", "source": "Chartink",
        "desc": "Supertrend buy signal on daily chart. Popular Indian trader setup.",
        "pairs_with": ["upswing", "volume_avg"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest supertrend( 10 , 3 , 1 ) = 1 and 1 day ago supertrend( 10 , 3 , 1 ) = -1 and latest volume > 50000 ) )",
    },
    "supertrend_sell_daily": {
        "no": 184, "slug": "python:chartink",
        "type": "BEAR", "weight": 2.5, "layer": "Trend", "source": "Chartink",
        "desc": "Supertrend sell signal on daily chart.",
        "pairs_with": ["downswing", "swing_high"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest supertrend( 10 , 3 , 1 ) = -1 and 1 day ago supertrend( 10 , 3 , 1 ) = 1 and latest volume > 50000 ) )",
    },
    "gap_up_high_volume": {
        "no": 185, "slug": "python:chartink",
        "type": "BULL", "weight": 2.0, "layer": "Gap", "source": "Chartink",
        "desc": "Gap up > 2% with volume > 2x average. Institutional opening interest.",
        "pairs_with": ["volume_spike", "breakout_50day"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest open > 1 day ago close * 1.02 and latest volume > 2 * latest sma( volume , 20 ) and latest close > latest open ) )",
    },
    "gap_down_high_volume": {
        "no": 186, "slug": "python:chartink",
        "type": "BEAR", "weight": 2.0, "layer": "Gap", "source": "Chartink",
        "desc": "Gap down > 2% with volume > 2x average. Institutional distribution.",
        "pairs_with": ["volume_spike", "breakdown_20day"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest open < 1 day ago close * 0.98 and latest volume > 2 * latest sma( volume , 20 ) and latest close < latest open ) )",
    },
    "rsi_bullish_divergence": {
        "no": 187, "slug": "python:chartink",
        "type": "BULL", "weight": 3.0, "layer": "RSI", "source": "Chartink",
        "desc": "RSI making higher low while price makes lower low. Classic bullish divergence.",
        "pairs_with": ["swing_low", "llbb_bounce"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest rsi( 14 ) > 1 day ago min( 5 , rsi( 14 ) ) and latest low < 1 day ago min( 5 , low ) and latest rsi( 14 ) > 30 and latest rsi( 14 ) < 50 and latest volume > 50000 ) )",
    },
    "narrow_range_7": {
        "no": 188, "slug": "python:chartink",
        "type": "BULL", "weight": 2.0, "layer": "Breakout", "source": "Chartink",
        "desc": "NR7: Today's range is the narrowest in 7 days. Compression before expansion.",
        "pairs_with": ["volume_avg", "breakout_200dma"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( ( latest high - latest low ) < min( 7 , ( latest high - latest low ) ) and latest volume > 50000 ) )",
    },
    "inside_bar_breakout": {
        "no": 189, "slug": "python:chartink",
        "type": "BULL", "weight": 2.5, "layer": "Breakout", "source": "Chartink",
        "desc": "Inside bar (today's range inside yesterday's) broken upward. Consolidation breakout.",
        "pairs_with": ["narrow_range_7", "volume_spike"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( 1 day ago high > 2 days ago high and 1 day ago low < 2 days ago low and latest close > 1 day ago high and latest volume > 50000 ) )",
    },
    "ema_ribbon_bull": {
        "no": 190, "slug": "python:chartink",
        "type": "BULL", "weight": 2.5, "layer": "MA", "source": "Chartink",
        "desc": "EMA ribbon expansion: 8>13>21>55 EMA with price above all. Strong uptrend.",
        "pairs_with": ["ma_stack_bullish", "upswing"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest ema( close , 8 ) > latest ema( close , 13 ) and latest ema( close , 13 ) > latest ema( close , 21 ) and latest ema( close , 21 ) > latest ema( close , 55 ) and latest close > latest ema( close , 8 ) ) )",
    },
    "high_volume_breakout_consolidation": {
        "no": 191, "slug": "python:chartink",
        "type": "BULL", "weight": 3.5, "layer": "Breakout", "source": "Chartink",
        "desc": "Price breaks 20-day high after 10 days of <3% range. Compression breakout.",
        "pairs_with": ["narrow_range_7", "darvas_box_breakout"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest close > max( 20 , latest high ) and max( 10 , latest high ) - min( 10 , latest low ) < 0.03 * latest close and latest volume > 2 * latest sma( volume , 20 ) ) )",
    },
    "weekly_breakout": {
        "no": 192, "slug": "python:chartink",
        "type": "BULL", "weight": 3.0, "layer": "Breakout", "source": "Chartink",
        "desc": "Weekly chart: close above 10-week high. Positional breakout.",
        "pairs_with": ["52week_high", "ma_stack_bullish"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( weekly latest close > weekly max( 10 , latest high ) and latest volume > latest sma( volume , 20 ) ) )",
    },
    "adx_strong_trend": {
        "no": 193, "slug": "python:chartink",
        "type": "BULL", "weight": 2.5, "layer": "Trend", "source": "Chartink",
        "desc": "ADX > 30 + +DI > -DI + close above 20 SMA. Strong confirmed uptrend.",
        "pairs_with": ["upswing", "ma_stack_bullish", "ema_ribbon_bull"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest adx( 14 ) > 30 and latest plus di( 14 ) > latest minus di( 14 ) and latest close > latest sma( close , 20 ) and latest volume > 50000 ) )",
    },
    "adx_strong_downtrend": {
        "no": 194, "slug": "python:chartink",
        "type": "BEAR", "weight": 2.5, "layer": "Trend", "source": "Chartink",
        "desc": "ADX > 30 + -DI > +DI + close below 20 SMA. Strong confirmed downtrend.",
        "pairs_with": ["downswing", "ma_stack_bearish"],
        "status": "ACTIVE",
        "scan_clause": "( {57960} ( latest adx( 14 ) > 30 and latest minus di( 14 ) > latest plus di( 14 ) and latest close < latest sma( close , 20 ) and latest volume > 50000 ) )",
    },
    "intraday_momentum_bull": {
        "no": 119, "slug": "python:intraday_momentum_bull",
        "type": "BULL", "weight": 3.0, "layer": "Breakout", "source": "Python",
        "desc": "Intraday momentum: close > open by 3%+ AND above previous close. Catches strong gap-up + sustained moves.",
        "pairs_with": ["volume_spike", "gap_up", "breakout_200dma"],
        "status": "ACTIVE",
    },
    "intraday_momentum_bear": {
        "no": 120, "slug": "python:intraday_momentum_bear",
        "type": "BEAR", "weight": 3.0, "layer": "Breakout", "source": "Python",
        "desc": "Intraday momentum: close < open by 3%+ AND below previous close. Catches strong sell-off moves.",
        "pairs_with": ["volume_spike", "gap_down"],
        "status": "ACTIVE",
    },

    # ── LAYER 8 — SMART MONEY CONCEPTS (12 scanners) ─────────

    "smc_bos_bull": {
        "no": 41, "slug": "python:scan_bos_bull",
        "type": "BULL", "weight": 2.5, "layer": "SMC", "source": "Python",
        "desc": "SMC Break of Structure bullish. Continuation HH confirmed.",
        "pairs_with": ["upswing", "smc_demand_ob", "volume_spike"],
        "status": "ACTIVE",
    },
    "smc_bos_bear": {
        "no": 42, "slug": "python:scan_bos_bear",
        "type": "BEAR", "weight": 2.5, "layer": "SMC", "source": "Python",
        "desc": "SMC Break of Structure bearish. Continuation LL confirmed.",
        "pairs_with": ["downswing", "smc_supply_ob", "volume_spike"],
        "status": "ACTIVE",
    },
    "smc_choch_bull": {
        "no": 43, "slug": "python:scan_choch_bull",
        "type": "BULL", "weight": 3.0, "layer": "SMC", "source": "Python",
        "desc": "SMC Change of Character bullish. Reversal from downtrend.",
        "pairs_with": ["smc_demand_ob", "smc_liq_sweep_bull", "smc_bullish_fvg"],
        "status": "ACTIVE",
    },
    "smc_choch_bear": {
        "no": 44, "slug": "python:scan_choch_bear",
        "type": "BEAR", "weight": 3.0, "layer": "SMC", "source": "Python",
        "desc": "SMC Change of Character bearish. Reversal from uptrend.",
        "pairs_with": ["smc_supply_ob", "smc_liq_sweep_bear", "smc_bearish_fvg"],
        "status": "ACTIVE",
    },
    "smc_demand_ob": {
        "no": 45, "slug": "python:scan_bullish_ob",
        "type": "BULL", "weight": 2.0, "layer": "SMC", "source": "Python",
        "desc": "SMC Demand Order Block. Institutional buy zone (unmitigated).",
        "pairs_with": ["smc_choch_bull", "smc_bos_bull", "smc_discount"],
        "status": "ACTIVE",
    },
    "smc_supply_ob": {
        "no": 46, "slug": "python:scan_bearish_ob",
        "type": "BEAR", "weight": 2.0, "layer": "SMC", "source": "Python",
        "desc": "SMC Supply Order Block. Institutional sell zone (unmitigated).",
        "pairs_with": ["smc_choch_bear", "smc_bos_bear", "smc_premium"],
        "status": "ACTIVE",
    },
    "smc_bullish_fvg": {
        "no": 47, "slug": "python:scan_bullish_fvg",
        "type": "BULL", "weight": 1.5, "layer": "SMC", "source": "Python",
        "desc": "SMC Bullish Fair Value Gap. Imbalance to be filled (demand).",
        "pairs_with": ["smc_demand_ob", "smc_choch_bull", "smc_discount"],
        "status": "ACTIVE",
    },
    "smc_bearish_fvg": {
        "no": 48, "slug": "python:scan_bearish_fvg",
        "type": "BEAR", "weight": 1.5, "layer": "SMC", "source": "Python",
        "desc": "SMC Bearish Fair Value Gap. Imbalance to be filled (supply).",
        "pairs_with": ["smc_supply_ob", "smc_choch_bear", "smc_premium"],
        "status": "ACTIVE",
    },
    "smc_liq_sweep_bull": {
        "no": 49, "slug": "python:scan_liquidity_sweep_bull",
        "type": "BULL", "weight": 3.0, "layer": "SMC", "source": "Python",
        "desc": "SMC Liquidity Sweep bullish. Stop hunt below equal lows then reversal.",
        "pairs_with": ["smc_choch_bull", "smc_demand_ob", "smc_bullish_fvg"],
        "status": "ACTIVE",
    },
    "smc_liq_sweep_bear": {
        "no": 50, "slug": "python:scan_liquidity_sweep_bear",
        "type": "BEAR", "weight": 3.0, "layer": "SMC", "source": "Python",
        "desc": "SMC Liquidity Sweep bearish. Stop hunt above equal highs then reversal.",
        "pairs_with": ["smc_choch_bear", "smc_supply_ob", "smc_bearish_fvg"],
        "status": "ACTIVE",
    },
    "smc_discount": {
        "no": 51, "slug": "python:scan_discount_zone",
        "type": "FILTER", "weight": 0.0, "layer": "SMC", "source": "Python",
        "desc": "SMC Discount Zone. Price below equilibrium of dealing range.",
        "pairs_with": [],
        "status": "ACTIVE",
    },
    "smc_premium": {
        "no": 52, "slug": "python:scan_premium_zone",
        "type": "FILTER", "weight": 0.0, "layer": "SMC", "source": "Python",
        "desc": "SMC Premium Zone. Price above equilibrium of dealing range.",
        "pairs_with": [],
        "status": "ACTIVE",
    },

    # ── LAYER 8b — SMC ADVANCED (20 scanners) ────────────────

    "smc_breaker_bull": {
        "no": 99, "slug": "python:scan_breaker_block_bull",
        "type": "BULL", "weight": 2.5, "layer": "SMC", "source": "Python",
        "desc": "SMC Breaker Block bullish. Failed supply OB flips to demand.",
        "pairs_with": ["smc_choch_bull", "smc_liq_sweep_bull", "smc_discount"],
        "status": "ACTIVE",
    },
    "smc_breaker_bear": {
        "no": 100, "slug": "python:scan_breaker_block_bear",
        "type": "BEAR", "weight": 2.5, "layer": "SMC", "source": "Python",
        "desc": "SMC Breaker Block bearish. Failed demand OB flips to supply.",
        "pairs_with": ["smc_choch_bear", "smc_liq_sweep_bear", "smc_premium"],
        "status": "ACTIVE",
    },
    "smc_mitigation_bull": {
        "no": 101, "slug": "python:scan_mitigation_block_bull",
        "type": "BULL", "weight": 2.0, "layer": "SMC", "source": "Python",
        "desc": "SMC Mitigation Block bullish. Demand OB mitigated but held.",
        "pairs_with": ["smc_demand_ob", "smc_bullish_fvg", "smc_discount"],
        "status": "ACTIVE",
    },
    "smc_mitigation_bear": {
        "no": 102, "slug": "python:scan_mitigation_block_bear",
        "type": "BEAR", "weight": 2.0, "layer": "SMC", "source": "Python",
        "desc": "SMC Mitigation Block bearish. Supply OB mitigated but held.",
        "pairs_with": ["smc_supply_ob", "smc_bearish_fvg", "smc_premium"],
        "status": "ACTIVE",
    },
    "smc_ifvg_bull": {
        "no": 103, "slug": "python:scan_ifvg_bull",
        "type": "BULL", "weight": 1.5, "layer": "SMC", "source": "Python",
        "desc": "SMC Inversion FVG bullish. Filled bearish FVG now acts as support.",
        "pairs_with": ["smc_demand_ob", "smc_discount", "smc_breaker_bull"],
        "status": "ACTIVE",
    },
    "smc_ifvg_bear": {
        "no": 104, "slug": "python:scan_ifvg_bear",
        "type": "BEAR", "weight": 1.5, "layer": "SMC", "source": "Python",
        "desc": "SMC Inversion FVG bearish. Filled bullish FVG now acts as resistance.",
        "pairs_with": ["smc_supply_ob", "smc_premium", "smc_breaker_bear"],
        "status": "ACTIVE",
    },
    "smc_mss_bull": {
        "no": 105, "slug": "python:scan_mss_bull",
        "type": "BULL", "weight": 3.0, "layer": "SMC", "source": "Python",
        "desc": "SMC Market Structure Shift bullish. Liquidity sweep + structure break.",
        "pairs_with": ["smc_liq_sweep_bull", "smc_choch_bull", "smc_demand_ob"],
        "status": "ACTIVE",
    },
    "smc_mss_bear": {
        "no": 106, "slug": "python:scan_mss_bear",
        "type": "BEAR", "weight": 3.0, "layer": "SMC", "source": "Python",
        "desc": "SMC Market Structure Shift bearish. Liquidity sweep + structure break.",
        "pairs_with": ["smc_liq_sweep_bear", "smc_choch_bear", "smc_supply_ob"],
        "status": "ACTIVE",
    },
    "smc_ote_bull": {
        "no": 107, "slug": "python:scan_ote_bull",
        "type": "BULL", "weight": 2.5, "layer": "SMC", "source": "Python",
        "desc": "SMC Optimal Trade Entry bullish. Price at Fib 62-79% retracement.",
        "pairs_with": ["smc_demand_ob", "smc_bullish_fvg", "smc_discount"],
        "status": "ACTIVE",
    },
    "smc_ote_bear": {
        "no": 108, "slug": "python:scan_ote_bear",
        "type": "BEAR", "weight": 2.5, "layer": "SMC", "source": "Python",
        "desc": "SMC Optimal Trade Entry bearish. Price at Fib 62-79% retracement.",
        "pairs_with": ["smc_supply_ob", "smc_bearish_fvg", "smc_premium"],
        "status": "ACTIVE",
    },
    "smc_idm_bull": {
        "no": 109, "slug": "python:scan_inducement_bull",
        "type": "BULL", "weight": 2.0, "layer": "SMC", "source": "Python",
        "desc": "SMC Inducement bullish. Minor low swept, major low held.",
        "pairs_with": ["smc_liq_sweep_bull", "smc_mss_bull", "smc_demand_ob"],
        "status": "ACTIVE",
    },
    "smc_idm_bear": {
        "no": 110, "slug": "python:scan_inducement_bear",
        "type": "BEAR", "weight": 2.0, "layer": "SMC", "source": "Python",
        "desc": "SMC Inducement bearish. Minor high swept, major high held.",
        "pairs_with": ["smc_liq_sweep_bear", "smc_mss_bear", "smc_supply_ob"],
        "status": "ACTIVE",
    },
    "smc_ce_bull": {
        "no": 111, "slug": "python:scan_ce_bull",
        "type": "FILTER", "weight": 0.0, "layer": "SMC", "source": "Python",
        "desc": "SMC Consequent Encroachment bullish. Price at 50% of bullish FVG.",
        "pairs_with": ["smc_bullish_fvg", "smc_demand_ob"],
        "status": "ACTIVE",
    },
    "smc_ce_bear": {
        "no": 112, "slug": "python:scan_ce_bear",
        "type": "FILTER", "weight": 0.0, "layer": "SMC", "source": "Python",
        "desc": "SMC Consequent Encroachment bearish. Price at 50% of bearish FVG.",
        "pairs_with": ["smc_bearish_fvg", "smc_supply_ob"],
        "status": "ACTIVE",
    },
    "smc_erl_bull": {
        "no": 113, "slug": "python:scan_erl_bull",
        "type": "BULL", "weight": 1.5, "layer": "SMC", "source": "Python",
        "desc": "SMC External Range Liquidity bullish. Buy-side liquidity draw above.",
        "pairs_with": ["smc_discount", "smc_demand_ob", "smc_ote_bull"],
        "status": "ACTIVE",
    },
    "smc_erl_bear": {
        "no": 114, "slug": "python:scan_erl_bear",
        "type": "BEAR", "weight": 1.5, "layer": "SMC", "source": "Python",
        "desc": "SMC External Range Liquidity bearish. Sell-side liquidity draw below.",
        "pairs_with": ["smc_premium", "smc_supply_ob", "smc_ote_bear"],
        "status": "ACTIVE",
    },
    "smc_fake_bo_bull": {
        "no": 115, "slug": "python:scan_fake_breakout_bull",
        "type": "BULL", "weight": 2.5, "layer": "SMC", "source": "Python",
        "desc": "SMC Fake Breakout bullish. Bear trap — broke support then reversed.",
        "pairs_with": ["smc_liq_sweep_bull", "smc_mss_bull", "smc_idm_bull"],
        "status": "ACTIVE",
    },
    "smc_fake_bo_bear": {
        "no": 116, "slug": "python:scan_fake_breakout_bear",
        "type": "BEAR", "weight": 2.5, "layer": "SMC", "source": "Python",
        "desc": "SMC Fake Breakout bearish. Bull trap — broke resistance then reversed.",
        "pairs_with": ["smc_liq_sweep_bear", "smc_mss_bear", "smc_idm_bear"],
        "status": "ACTIVE",
    },
    "smc_ema_pullback_bull": {
        "no": 117, "slug": "python:scan_ema_pullback_bull",
        "type": "BULL", "weight": 2.0, "layer": "SMC", "source": "Python",
        "desc": "9/21 EMA pullback buy. Price between EMAs in uptrend, bullish candle.",
        "pairs_with": ["upswing", "smc_bos_bull", "smc_demand_ob"],
        "status": "ACTIVE",
    },
    "smc_ema_pullback_bear": {
        "no": 118, "slug": "python:scan_ema_pullback_bear",
        "type": "BEAR", "weight": 2.0, "layer": "SMC", "source": "Python",
        "desc": "9/21 EMA pullback sell. Price between EMAs in downtrend, bearish candle.",
        "pairs_with": ["downswing", "smc_bos_bear", "smc_supply_ob"],
        "status": "ACTIVE",
    },

    # ── LAYER 9 — WYCKOFF METHOD (8 scanners) ────────────────

    "wyckoff_accumulation": {
        "no": 53, "slug": "python:scan_accumulation",
        "type": "BULL", "weight": 2.5, "layer": "Wyckoff", "source": "Python",
        "desc": "Wyckoff Accumulation phase. Institutional buying at range lows.",
        "pairs_with": ["wyckoff_spring", "wyckoff_sos", "smc_demand_ob"],
        "status": "ACTIVE",
    },
    "wyckoff_distribution": {
        "no": 54, "slug": "python:scan_distribution",
        "type": "BEAR", "weight": 2.5, "layer": "Wyckoff", "source": "Python",
        "desc": "Wyckoff Distribution phase. Institutional selling at range highs.",
        "pairs_with": ["wyckoff_upthrust", "wyckoff_sow", "smc_supply_ob"],
        "status": "ACTIVE",
    },
    "wyckoff_spring": {
        "no": 55, "slug": "python:scan_spring",
        "type": "BULL", "weight": 3.0, "layer": "Wyckoff", "source": "Python",
        "desc": "Wyckoff Spring. False breakdown shaking out weak longs.",
        "pairs_with": ["wyckoff_accumulation", "smc_liq_sweep_bull", "vsa_selling_climax"],
        "status": "ACTIVE",
    },
    "wyckoff_upthrust": {
        "no": 56, "slug": "python:scan_upthrust",
        "type": "BEAR", "weight": 3.0, "layer": "Wyckoff", "source": "Python",
        "desc": "Wyckoff Upthrust. False breakout trapping breakout buyers.",
        "pairs_with": ["wyckoff_distribution", "smc_liq_sweep_bear", "vsa_buying_climax"],
        "status": "ACTIVE",
    },
    "wyckoff_sos": {
        "no": 57, "slug": "python:scan_sos",
        "type": "BULL", "weight": 2.0, "layer": "Wyckoff", "source": "Python",
        "desc": "Wyckoff Sign of Strength. Strong up move on volume in range.",
        "pairs_with": ["wyckoff_accumulation", "wyckoff_spring", "volume_spike"],
        "status": "ACTIVE",
    },
    "wyckoff_sow": {
        "no": 58, "slug": "python:scan_sow",
        "type": "BEAR", "weight": 2.0, "layer": "Wyckoff", "source": "Python",
        "desc": "Wyckoff Sign of Weakness. Strong down move on volume in range.",
        "pairs_with": ["wyckoff_distribution", "wyckoff_upthrust", "volume_spike"],
        "status": "ACTIVE",
    },
    "wyckoff_test_bull": {
        "no": 59, "slug": "python:scan_test_bull",
        "type": "BULL", "weight": 2.5, "layer": "Wyckoff", "source": "Python",
        "desc": "Wyckoff Bullish Test. Low-volume retest confirming accumulation.",
        "pairs_with": ["wyckoff_spring", "wyckoff_accumulation", "vsa_stopping_bull"],
        "status": "ACTIVE",
    },
    "wyckoff_test_bear": {
        "no": 60, "slug": "python:scan_test_bear",
        "type": "BEAR", "weight": 2.5, "layer": "Wyckoff", "source": "Python",
        "desc": "Wyckoff Bearish Test. Low-volume retest confirming distribution.",
        "pairs_with": ["wyckoff_upthrust", "wyckoff_distribution", "vsa_stopping_bear"],
        "status": "ACTIVE",
    },

    # ── LAYER 10 — VOLUME SPREAD ANALYSIS (8 scanners) ───────

    "vsa_no_supply": {
        "no": 61, "slug": "python:scan_no_supply",
        "type": "BULL", "weight": 1.5, "layer": "VSA", "source": "Python",
        "desc": "VSA No Supply. Down bar, narrow spread, low volume — no sellers.",
        "pairs_with": ["wyckoff_accumulation", "smc_discount", "wyckoff_test_bull"],
        "status": "ACTIVE",
    },
    "vsa_no_demand": {
        "no": 62, "slug": "python:scan_no_demand",
        "type": "BEAR", "weight": 1.5, "layer": "VSA", "source": "Python",
        "desc": "VSA No Demand. Up bar, narrow spread, low volume — no buyers.",
        "pairs_with": ["wyckoff_distribution", "smc_premium", "wyckoff_test_bear"],
        "status": "ACTIVE",
    },
    "vsa_stopping_bull": {
        "no": 63, "slug": "python:scan_stopping_vol_bull",
        "type": "BULL", "weight": 2.5, "layer": "VSA", "source": "Python",
        "desc": "VSA Stopping Volume Bull. High volume absorbing selling.",
        "pairs_with": ["wyckoff_accumulation", "smc_demand_ob", "vsa_selling_climax"],
        "status": "ACTIVE",
    },
    "vsa_stopping_bear": {
        "no": 64, "slug": "python:scan_stopping_vol_bear",
        "type": "BEAR", "weight": 2.5, "layer": "VSA", "source": "Python",
        "desc": "VSA Stopping Volume Bear. High volume absorbing buying.",
        "pairs_with": ["wyckoff_distribution", "smc_supply_ob", "vsa_buying_climax"],
        "status": "ACTIVE",
    },
    "vsa_selling_climax": {
        "no": 65, "slug": "python:scan_selling_climax",
        "type": "BULL", "weight": 3.0, "layer": "VSA", "source": "Python",
        "desc": "VSA Selling Climax. Capitulation — ultra high vol down bar.",
        "pairs_with": ["wyckoff_spring", "smc_liq_sweep_bull", "vsa_stopping_bull"],
        "status": "ACTIVE",
    },
    "vsa_buying_climax": {
        "no": 66, "slug": "python:scan_buying_climax",
        "type": "BEAR", "weight": 3.0, "layer": "VSA", "source": "Python",
        "desc": "VSA Buying Climax. Euphoria top — ultra high vol up bar.",
        "pairs_with": ["wyckoff_upthrust", "smc_liq_sweep_bear", "vsa_stopping_bear"],
        "status": "ACTIVE",
    },
    "vsa_effort_bull": {
        "no": 67, "slug": "python:scan_effort_bull",
        "type": "BULL", "weight": 2.0, "layer": "VSA", "source": "Python",
        "desc": "VSA Effort vs Result Bull. High vol, narrow down spread — absorbed.",
        "pairs_with": ["vsa_no_supply", "wyckoff_accumulation", "smc_demand_ob"],
        "status": "ACTIVE",
    },
    "vsa_effort_bear": {
        "no": 68, "slug": "python:scan_effort_bear",
        "type": "BEAR", "weight": 2.0, "layer": "VSA", "source": "Python",
        "desc": "VSA Effort vs Result Bear. High vol, narrow up spread — absorbed.",
        "pairs_with": ["vsa_no_demand", "wyckoff_distribution", "smc_supply_ob"],
        "status": "ACTIVE",
    },

    # ── LAYER 11 — HARMONIC PATTERNS (6 scanners) ────────────

    "harmonic_gartley_bull": {
        "no": 69, "slug": "python:scan_harmonic_gartley_bull",
        "type": "BULL", "weight": 2.5, "layer": "Harmonic", "source": "Python",
        "desc": "Harmonic Gartley Bullish. Most reliable harmonic at 78.6% XA.",
        "pairs_with": ["smc_discount", "wyckoff_accumulation", "harmonic_any_bull"],
        "status": "ACTIVE",
    },
    "harmonic_gartley_bear": {
        "no": 70, "slug": "python:scan_harmonic_gartley_bear",
        "type": "BEAR", "weight": 2.5, "layer": "Harmonic", "source": "Python",
        "desc": "Harmonic Gartley Bearish. Most reliable harmonic at 78.6% XA.",
        "pairs_with": ["smc_premium", "wyckoff_distribution", "harmonic_any_bear"],
        "status": "ACTIVE",
    },
    "harmonic_bat_bull": {
        "no": 71, "slug": "python:scan_harmonic_bat_bull",
        "type": "BULL", "weight": 2.0, "layer": "Harmonic", "source": "Python",
        "desc": "Harmonic Bat Bullish. Deep retracement at 88.6% XA.",
        "pairs_with": ["smc_discount", "smc_demand_ob", "harmonic_any_bull"],
        "status": "ACTIVE",
    },
    "harmonic_bat_bear": {
        "no": 72, "slug": "python:scan_harmonic_bat_bear",
        "type": "BEAR", "weight": 2.0, "layer": "Harmonic", "source": "Python",
        "desc": "Harmonic Bat Bearish. Deep retracement at 88.6% XA.",
        "pairs_with": ["smc_premium", "smc_supply_ob", "harmonic_any_bear"],
        "status": "ACTIVE",
    },
    "harmonic_any_bull": {
        "no": 73, "slug": "python:scan_harmonic_any_bull",
        "type": "BULL", "weight": 2.0, "layer": "Harmonic", "source": "Python",
        "desc": "Any bullish harmonic (Gartley/Butterfly/Bat/Crab/Cypher).",
        "pairs_with": ["smc_discount", "wyckoff_accumulation", "vsa_stopping_bull"],
        "status": "ACTIVE",
    },
    "harmonic_any_bear": {
        "no": 74, "slug": "python:scan_harmonic_any_bear",
        "type": "BEAR", "weight": 2.0, "layer": "Harmonic", "source": "Python",
        "desc": "Any bearish harmonic (Gartley/Butterfly/Bat/Crab/Cypher).",
        "pairs_with": ["smc_premium", "wyckoff_distribution", "vsa_stopping_bear"],
        "status": "ACTIVE",
    },

    # ── LAYER 12 — RL-INSPIRED (8 scanners) ────────────────────

    "rl_trend_bull": {
        "no": 75, "slug": "python:scan_rl_trend_bull",
        "type": "BULL", "weight": 2.0, "layer": "RL", "source": "Python",
        "desc": "RL regime trend bullish. Volatility + trend strength classification.",
        "pairs_with": ["upswing", "rl_momentum_bull", "rl_optimal_entry_bull"],
        "status": "ACTIVE",
    },
    "rl_trend_bear": {
        "no": 76, "slug": "python:scan_rl_trend_bear",
        "type": "BEAR", "weight": 2.0, "layer": "RL", "source": "Python",
        "desc": "RL regime trend bearish. Volatility + trend strength classification.",
        "pairs_with": ["downswing", "rl_momentum_bear", "rl_optimal_entry_bear"],
        "status": "ACTIVE",
    },
    "rl_vwap_bull": {
        "no": 77, "slug": "python:scan_rl_vwap_bull",
        "type": "BULL", "weight": 1.5, "layer": "RL", "source": "Python",
        "desc": "RL VWAP deviation bullish. Price below VWAP mean-reversion signal.",
        "pairs_with": ["swing_low", "rl_trend_bull", "smc_discount"],
        "status": "ACTIVE",
    },
    "rl_vwap_bear": {
        "no": 78, "slug": "python:scan_rl_vwap_bear",
        "type": "BEAR", "weight": 1.5, "layer": "RL", "source": "Python",
        "desc": "RL VWAP deviation bearish. Price above VWAP mean-reversion signal.",
        "pairs_with": ["swing_high", "rl_trend_bear", "smc_premium"],
        "status": "ACTIVE",
    },
    "rl_momentum_bull": {
        "no": 79, "slug": "python:scan_rl_momentum_bull",
        "type": "BULL", "weight": 2.5, "layer": "RL", "source": "Python",
        "desc": "RL momentum score bullish. Composite returns + RSI + volume ratio.",
        "pairs_with": ["rl_trend_bull", "volume_spike", "upswing"],
        "status": "ACTIVE",
    },
    "rl_momentum_bear": {
        "no": 80, "slug": "python:scan_rl_momentum_bear",
        "type": "BEAR", "weight": 2.5, "layer": "RL", "source": "Python",
        "desc": "RL momentum score bearish. Composite returns + RSI + volume ratio.",
        "pairs_with": ["rl_trend_bear", "volume_spike", "downswing"],
        "status": "ACTIVE",
    },
    "rl_optimal_entry_bull": {
        "no": 81, "slug": "python:scan_rl_optimal_entry_bull",
        "type": "BULL", "weight": 3.0, "layer": "RL", "source": "Python",
        "desc": "RL optimal entry bullish. Multi-factor confluence: regime + VWAP + momentum.",
        "pairs_with": ["rl_trend_bull", "rl_vwap_bull", "rl_momentum_bull"],
        "status": "ACTIVE",
    },
    "rl_optimal_entry_bear": {
        "no": 82, "slug": "python:scan_rl_optimal_entry_bear",
        "type": "BEAR", "weight": 3.0, "layer": "RL", "source": "Python",
        "desc": "RL optimal entry bearish. Multi-factor confluence: regime + VWAP + momentum.",
        "pairs_with": ["rl_trend_bear", "rl_vwap_bear", "rl_momentum_bear"],
        "status": "ACTIVE",
    },

    # ── LAYER 13 — FOREX / CDS (8 scanners) ─────────────────────

    "cds_ema_crossover": {
        "no": 83, "slug": "python:scan_cds_ema_crossover",
        "type": "BULL", "weight": 1.5, "layer": "Forex", "source": "Python",
        "desc": "CDS 9/21 EMA bullish crossover on currency pairs.",
        "pairs_with": ["cds_ema_crossover_bear", "cds_rsi_oversold", "cds_bb_squeeze"],
        "status": "ACTIVE",
    },
    "cds_ema_crossover_bear": {
        "no": 84, "slug": "python:scan_cds_ema_crossover_bear",
        "type": "BEAR", "weight": 1.5, "layer": "Forex", "source": "Python",
        "desc": "CDS 9/21 EMA bearish crossover on currency pairs.",
        "pairs_with": ["cds_ema_crossover", "cds_rsi_overbought", "cds_bb_squeeze_bear"],
        "status": "ACTIVE",
    },
    "cds_rsi_oversold": {
        "no": 85, "slug": "python:scan_cds_rsi_oversold",
        "type": "BULL", "weight": 1.0, "layer": "Forex", "source": "Python",
        "desc": "CDS RSI(14) < 30 oversold on currency pairs.",
        "pairs_with": ["cds_ema_crossover", "cds_bb_squeeze"],
        "status": "ACTIVE",
    },
    "cds_rsi_overbought": {
        "no": 86, "slug": "python:scan_cds_rsi_overbought",
        "type": "BEAR", "weight": 1.0, "layer": "Forex", "source": "Python",
        "desc": "CDS RSI(14) > 70 overbought on currency pairs.",
        "pairs_with": ["cds_ema_crossover_bear", "cds_bb_squeeze_bear"],
        "status": "ACTIVE",
    },
    "cds_bb_squeeze": {
        "no": 87, "slug": "python:scan_cds_bb_squeeze",
        "type": "BULL", "weight": 1.5, "layer": "Forex", "source": "Python",
        "desc": "CDS Bollinger Band squeeze (bandwidth < 20-period low) with price above middle.",
        "pairs_with": ["cds_ema_crossover", "cds_rsi_oversold"],
        "status": "ACTIVE",
    },
    "cds_bb_squeeze_bear": {
        "no": 88, "slug": "python:scan_cds_bb_squeeze_bear",
        "type": "BEAR", "weight": 1.5, "layer": "Forex", "source": "Python",
        "desc": "CDS BB squeeze with price below middle band — bearish.",
        "pairs_with": ["cds_ema_crossover_bear", "cds_rsi_overbought"],
        "status": "ACTIVE",
    },
    "cds_carry_trade": {
        "no": 89, "slug": "python:scan_cds_carry_trade",
        "type": "BULL", "weight": 2.0, "layer": "Forex", "source": "Python",
        "desc": "USDINR trending with positive carry differential.",
        "pairs_with": ["cds_ema_crossover", "cds_bb_squeeze"],
        "status": "ACTIVE",
    },
    "cds_dxy_divergence": {
        "no": 90, "slug": "python:scan_cds_dxy_divergence",
        "type": "BEAR", "weight": 2.0, "layer": "Forex", "source": "Python",
        "desc": "INR pairs diverging from DXY correlation — bearish.",
        "pairs_with": ["cds_ema_crossover_bear", "cds_rsi_overbought"],
        "status": "ACTIVE",
    },

    # ── LAYER 14 — COMMODITY / MCX (8 scanners) ─────────────────

    "mcx_ema_crossover": {
        "no": 91, "slug": "python:scan_mcx_ema_crossover",
        "type": "BULL", "weight": 1.5, "layer": "Commodity", "source": "Python",
        "desc": "MCX 9/21 EMA bullish crossover on metals/energy.",
        "pairs_with": ["mcx_ema_crossover_bear", "mcx_rsi_oversold", "mcx_crude_momentum"],
        "status": "ACTIVE",
    },
    "mcx_ema_crossover_bear": {
        "no": 92, "slug": "python:scan_mcx_ema_crossover_bear",
        "type": "BEAR", "weight": 1.5, "layer": "Commodity", "source": "Python",
        "desc": "MCX 9/21 EMA bearish crossover.",
        "pairs_with": ["mcx_ema_crossover", "mcx_rsi_overbought"],
        "status": "ACTIVE",
    },
    "mcx_rsi_oversold": {
        "no": 93, "slug": "python:scan_mcx_rsi_oversold",
        "type": "BULL", "weight": 1.0, "layer": "Commodity", "source": "Python",
        "desc": "MCX RSI(14) < 30 oversold commodities.",
        "pairs_with": ["mcx_ema_crossover", "mcx_gold_silver_ratio"],
        "status": "ACTIVE",
    },
    "mcx_rsi_overbought": {
        "no": 94, "slug": "python:scan_mcx_rsi_overbought",
        "type": "BEAR", "weight": 1.0, "layer": "Commodity", "source": "Python",
        "desc": "MCX RSI(14) > 70 overbought commodities.",
        "pairs_with": ["mcx_ema_crossover_bear", "mcx_gold_silver_ratio_bear"],
        "status": "ACTIVE",
    },
    "mcx_gold_silver_ratio": {
        "no": 95, "slug": "python:scan_mcx_gold_silver_ratio",
        "type": "BULL", "weight": 2.0, "layer": "Commodity", "source": "Python",
        "desc": "Gold/Silver ratio mean-reversion signal — bullish for metals.",
        "pairs_with": ["mcx_metal_strength", "mcx_ema_crossover"],
        "status": "ACTIVE",
    },
    "mcx_gold_silver_ratio_bear": {
        "no": 96, "slug": "python:scan_mcx_gold_silver_ratio_bear",
        "type": "BEAR", "weight": 2.0, "layer": "Commodity", "source": "Python",
        "desc": "Gold/Silver ratio expansion — bearish for silver.",
        "pairs_with": ["mcx_rsi_overbought", "mcx_ema_crossover_bear"],
        "status": "ACTIVE",
    },
    "mcx_crude_momentum": {
        "no": 97, "slug": "python:scan_mcx_crude_momentum",
        "type": "BULL", "weight": 2.5, "layer": "Commodity", "source": "Python",
        "desc": "Crude oil MACD + volume breakout.",
        "pairs_with": ["mcx_ema_crossover", "mcx_rsi_oversold"],
        "status": "ACTIVE",
    },
    "mcx_metal_strength": {
        "no": 98, "slug": "python:scan_mcx_metal_strength",
        "type": "BULL", "weight": 1.5, "layer": "Commodity", "source": "Python",
        "desc": "Multi-metal relative strength index — outperforming 20-day avg.",
        "pairs_with": ["mcx_gold_silver_ratio", "mcx_ema_crossover"],
        "status": "ACTIVE",
    },

    # ── LAYER 15 — F&O / NFO (8 scanners) ────────────────────

    "nfo_ema_crossover": {
        "no": 121, "slug": "python:scan_nfo_ema_crossover",
        "type": "BULL", "weight": 1.5, "layer": "FnO", "source": "Python",
        "desc": "NFO 9/21 EMA bullish crossover on index futures.",
        "pairs_with": ["nfo_rsi_oversold", "nfo_vol_squeeze_bull", "nfo_range_breakout_bull"],
        "status": "ACTIVE",
    },
    "nfo_ema_crossover_bear": {
        "no": 122, "slug": "python:scan_nfo_ema_crossover_bear",
        "type": "BEAR", "weight": 1.5, "layer": "FnO", "source": "Python",
        "desc": "NFO 9/21 EMA bearish crossover on index futures.",
        "pairs_with": ["nfo_rsi_overbought", "nfo_vol_squeeze_bear", "nfo_range_breakdown_bear"],
        "status": "ACTIVE",
    },
    "nfo_rsi_oversold": {
        "no": 123, "slug": "python:scan_nfo_rsi_oversold",
        "type": "BULL", "weight": 1.0, "layer": "FnO", "source": "Python",
        "desc": "NFO index RSI(14) < 30 oversold — potential long entry for calls/bull spreads.",
        "pairs_with": ["nfo_ema_crossover", "nfo_vol_squeeze_bull"],
        "status": "ACTIVE",
    },
    "nfo_rsi_overbought": {
        "no": 124, "slug": "python:scan_nfo_rsi_overbought",
        "type": "BEAR", "weight": 1.0, "layer": "FnO", "source": "Python",
        "desc": "NFO index RSI(14) > 70 overbought — potential short entry for puts/bear spreads.",
        "pairs_with": ["nfo_ema_crossover_bear", "nfo_vol_squeeze_bear"],
        "status": "ACTIVE",
    },
    "nfo_vol_squeeze_bull": {
        "no": 125, "slug": "python:scan_nfo_vol_squeeze_bull",
        "type": "BULL", "weight": 1.5, "layer": "FnO", "source": "Python",
        "desc": "NFO BB squeeze with price above middle band — bullish breakout setup.",
        "pairs_with": ["nfo_ema_crossover", "nfo_range_breakout_bull"],
        "status": "ACTIVE",
    },
    "nfo_vol_squeeze_bear": {
        "no": 126, "slug": "python:scan_nfo_vol_squeeze_bear",
        "type": "BEAR", "weight": 1.5, "layer": "FnO", "source": "Python",
        "desc": "NFO BB squeeze with price below middle band — bearish breakdown setup.",
        "pairs_with": ["nfo_ema_crossover_bear", "nfo_range_breakdown_bear"],
        "status": "ACTIVE",
    },
    "nfo_range_breakout_bull": {
        "no": 127, "slug": "python:scan_nfo_range_breakout_bull",
        "type": "BULL", "weight": 2.5, "layer": "FnO", "source": "Python",
        "desc": "NFO index breakout above 20-day high with volume — highest conviction F&O long.",
        "pairs_with": ["nfo_ema_crossover", "nfo_vol_squeeze_bull"],
        "status": "ACTIVE",
    },
    "nfo_range_breakdown_bear": {
        "no": 128, "slug": "python:scan_nfo_range_breakdown_bear",
        "type": "BEAR", "weight": 2.5, "layer": "FnO", "source": "Python",
        "desc": "NFO index breakdown below 20-day low with volume — highest conviction F&O short.",
        "pairs_with": ["nfo_ema_crossover_bear", "nfo_vol_squeeze_bear"],
        "status": "ACTIVE",
    },

    # ── F&O Stock scanners (129-136) — RELIANCE, TCS, INFY, HDFCBANK, ... ──
    "nfo_stk_ema_crossover": {
        "no": 129, "slug": "python:scan_nfo_stk_ema_crossover",
        "type": "BULL", "weight": 2.0, "layer": "FnO", "source": "Python",
        "desc": "F&O stock 9/21 EMA bullish crossover (~190 stocks).",
        "pairs_with": ["nfo_stk_rsi_oversold", "nfo_stk_vol_squeeze_bull", "nfo_stk_range_breakout_bull"],
        "status": "ACTIVE",
    },
    "nfo_stk_ema_crossover_bear": {
        "no": 130, "slug": "python:scan_nfo_stk_ema_crossover_bear",
        "type": "BEAR", "weight": 2.0, "layer": "FnO", "source": "Python",
        "desc": "F&O stock 9/21 EMA bearish crossover.",
        "pairs_with": ["nfo_stk_rsi_overbought", "nfo_stk_vol_squeeze_bear", "nfo_stk_range_breakdown_bear"],
        "status": "ACTIVE",
    },
    "nfo_stk_rsi_oversold": {
        "no": 131, "slug": "python:scan_nfo_stk_rsi_oversold",
        "type": "BULL", "weight": 1.5, "layer": "FnO", "source": "Python",
        "desc": "F&O stock RSI(14) < 30 — oversold long entry candidate.",
        "pairs_with": ["nfo_stk_ema_crossover", "nfo_stk_vol_squeeze_bull"],
        "status": "ACTIVE",
    },
    "nfo_stk_rsi_overbought": {
        "no": 132, "slug": "python:scan_nfo_stk_rsi_overbought",
        "type": "BEAR", "weight": 1.5, "layer": "FnO", "source": "Python",
        "desc": "F&O stock RSI(14) > 70 — overbought short entry candidate.",
        "pairs_with": ["nfo_stk_ema_crossover_bear", "nfo_stk_vol_squeeze_bear"],
        "status": "ACTIVE",
    },
    "nfo_stk_vol_squeeze_bull": {
        "no": 133, "slug": "python:scan_nfo_stk_vol_squeeze_bull",
        "type": "BULL", "weight": 2.0, "layer": "FnO", "source": "Python",
        "desc": "F&O stock BB squeeze with price ≥ middle band — bullish breakout setup.",
        "pairs_with": ["nfo_stk_ema_crossover", "nfo_stk_range_breakout_bull"],
        "status": "ACTIVE",
    },
    "nfo_stk_vol_squeeze_bear": {
        "no": 134, "slug": "python:scan_nfo_stk_vol_squeeze_bear",
        "type": "BEAR", "weight": 2.0, "layer": "FnO", "source": "Python",
        "desc": "F&O stock BB squeeze with price < middle band — bearish breakdown setup.",
        "pairs_with": ["nfo_stk_ema_crossover_bear", "nfo_stk_range_breakdown_bear"],
        "status": "ACTIVE",
    },
    "nfo_stk_range_breakout_bull": {
        "no": 135, "slug": "python:scan_nfo_stk_range_breakout_bull",
        "type": "BULL", "weight": 2.5, "layer": "FnO", "source": "Python",
        "desc": "F&O stock 20-day breakout with volume — high-conviction F&O stock long.",
        "pairs_with": ["nfo_stk_ema_crossover", "nfo_stk_vol_squeeze_bull"],
        "status": "ACTIVE",
    },
    "nfo_stk_range_breakdown_bear": {
        "no": 136, "slug": "python:scan_nfo_stk_range_breakdown_bear",
        "type": "BEAR", "weight": 2.5, "layer": "FnO", "source": "Python",
        "desc": "F&O stock 20-day breakdown with volume — high-conviction F&O stock short.",
        "pairs_with": ["nfo_stk_ema_crossover_bear", "nfo_stk_vol_squeeze_bear"],
        "status": "ACTIVE",
    },
}


# ── SEGMENT ASSIGNMENT ──────────────────────────────────────
# Assign each scanner to the market segments where it should run.
# Rules:
#   - Chartink scanners → NSE only (Chartink is NSE-exclusive)
#   - Filters (delivery, fii_dii, sector, large_cap) → NSE only
#   - CDS-specific (layer=Forex) → CDS only
#   - MCX-specific (layer=Commodity) → MCX only
#   - All other Python scanners (SMC/Wyckoff/VSA/Harmonic/RL/supertrend/volume)
#     are pure OHLCV and work universally → NSE, MCX, CDS, NFO

_ALL_SEGMENTS = ["NSE", "MCX", "CDS", "NFO"]
_NSE_ONLY_FILTERS = {
    "large_cap_filter", "delivery_pct_filter", "fii_dii_filter",
    "sector_rotation_filter",
}

for _key, _cfg in SCANNERS.items():
    if "segments" in _cfg:
        continue  # already set
    if _cfg["source"] == "Chartink":
        _cfg["segments"] = ["NSE"]
    elif _cfg["layer"] == "Forex":
        _cfg["segments"] = ["CDS"]
    elif _cfg["layer"] == "Commodity":
        _cfg["segments"] = ["MCX"]
    elif _cfg["layer"] == "FnO":
        _cfg["segments"] = ["NFO"]
    elif _key in _NSE_ONLY_FILTERS:
        _cfg["segments"] = ["NSE"]
    else:
        _cfg["segments"] = list(_ALL_SEGMENTS)

# Computed segment dicts — scanners relevant to each segment
NSE_SCANNERS = {k: v for k, v in SCANNERS.items() if "NSE" in v["segments"]}
MCX_SCANNERS = {k: v for k, v in SCANNERS.items() if "MCX" in v["segments"]}
CDS_SCANNERS = {k: v for k, v in SCANNERS.items() if "CDS" in v["segments"]}
NFO_SCANNERS = {k: v for k, v in SCANNERS.items() if "NFO" in v["segments"]}


# ── SIGNAL CHAINS ────────────────────────────────────────────

SIGNAL_CHAINS = {
    "strongest_long": {
        "scanners": ["swing_low", "upswing", "llbb_bounce", "bullish_divergence",
                     "failure_swing_bullish", "volume_spike"],
        "desc": "Bottom reversal + trend + bounce + dual divergence + volume",
        "boost": 25, "best_for": "Double Bottom, Rounded Bottom, IH&S",
    },
    "quality_breakout": {
        "scanners": ["breakout_200dma", "volume_spike", "upswing",
                     "bandwalk_highs", "richie_rich_breakout"],
        "desc": "Regime breakout + volume + trend + bandwalk + Richie Rich",
        "boost": 25, "best_for": "Bullish Flag, Triangle, Rectangle above 200MA",
    },
    "52week_momentum": {
        "scanners": ["52week_high", "richie_rich_breakout", "volume_spike", "breakout_200dma"],
        "desc": "52-week high + Richie Rich + volume spike + 200DMA regime",
        "boost": 30, "best_for": "Highest conviction momentum entries",
    },
    "richie_rich_full": {
        "scanners": ["richie_rich_breakout", "richie_rich_tracker", "breakout_200dma", "volume_spike"],
        "desc": "Both Richie Rich scanners + regime breakout + volume",
        "boost": 20, "best_for": "Highest conviction breakout entries",
    },
    "divergence_bull": {
        "scanners": ["bullish_divergence", "failure_swing_bullish", "rsi_above_30"],
        "desc": "Full bullish divergence ladder: early warning -> confirm -> momentum",
        "boost": 20, "best_for": "Catching bottom reversals early",
    },
    "divergence_bear": {
        "scanners": ["bearish_divergence", "failure_swing_bearish", "rsi_below_70"],
        "desc": "Full bearish divergence ladder: early warning -> confirm -> momentum",
        "boost": 20, "best_for": "Catching top reversals early",
    },
    "strongest_short": {
        "scanners": ["swing_high", "downswing", "bearish_divergence",
                     "failure_swing_bearish", "macd_sell_weekly"],
        "desc": "Top reversal + trend + dual divergence + weekly MACD",
        "boost": 25, "best_for": "H&S, Double Top, Rising Wedge shorts",
    },
    "intraday_long": {
        "scanners": ["gap_up", "buy_morning_9_30", "macd_buy_hourly", "ema_crossover_bn"],
        "desc": "Gap up + morning scanner + hourly MACD + EMA crossover",
        "boost": 15, "best_for": "9:15-10:30 AM intraday entries",
    },
    "fo_confirmed": {
        "scanners": ["ema_crossover_bn", "ema_crossover_nifty", "macd_buy_hourly"],
        "desc": "BankNifty + Nifty EMA both firing + hourly MACD",
        "boost": 15, "best_for": "Full F&O long confirmation signal",
    },
    "positional_200ma": {
        "scanners": ["near_200ma_v2", "swing_low", "llbb_bounce",
                     "failure_swing_bullish", "supertrend_buy"],
        "desc": "200MA support + swing low + bounce + divergence + supertrend flip",
        "boost": 20, "best_for": "Highest RRR positional trades at 200MA",
    },
    "smc_reversal_long": {
        "scanners": ["smc_choch_bull", "smc_demand_ob", "smc_liq_sweep_bull",
                     "smc_bullish_fvg", "volume_spike"],
        "desc": "SMC reversal long: CHoCH + demand OB + liquidity sweep + FVG + volume",
        "boost": 25, "best_for": "Institutional reversal longs with SMC confluence",
    },
    "smc_reversal_short": {
        "scanners": ["smc_choch_bear", "smc_supply_ob", "smc_liq_sweep_bear",
                     "smc_bearish_fvg", "volume_spike"],
        "desc": "SMC reversal short: CHoCH + supply OB + liquidity sweep + FVG + volume",
        "boost": 25, "best_for": "Institutional reversal shorts with SMC confluence",
    },
    "smc_continuation": {
        "scanners": ["smc_bos_bull", "smc_demand_ob", "upswing", "volume_avg"],
        "desc": "SMC continuation: BOS + demand OB + upswing + volume",
        "boost": 20, "best_for": "Trend continuation entries with smart money confirmation",
    },
    # Wyckoff chains
    "wyckoff_spring_setup": {
        "scanners": ["wyckoff_accumulation", "wyckoff_spring", "wyckoff_test_bull",
                     "wyckoff_sos", "volume_spike"],
        "desc": "Full Wyckoff spring: accumulation + spring + test + SOS + volume",
        "boost": 30, "best_for": "Highest conviction institutional accumulation longs",
    },
    "wyckoff_distribution_setup": {
        "scanners": ["wyckoff_distribution", "wyckoff_upthrust", "wyckoff_test_bear",
                     "wyckoff_sow"],
        "desc": "Wyckoff distribution: distribution + upthrust + test + SOW",
        "boost": 25, "best_for": "Institutional distribution shorts",
    },
    # VSA chains
    "vsa_capitulation_long": {
        "scanners": ["vsa_selling_climax", "vsa_stopping_bull", "vsa_no_supply",
                     "vsa_effort_bull"],
        "desc": "VSA capitulation: selling climax + stopping vol + no supply + effort absorbed",
        "boost": 25, "best_for": "Bottom fishing after capitulation with VSA confirmation",
    },
    "vsa_euphoria_short": {
        "scanners": ["vsa_buying_climax", "vsa_stopping_bear", "vsa_no_demand",
                     "vsa_effort_bear"],
        "desc": "VSA euphoria: buying climax + stopping vol + no demand + effort absorbed",
        "boost": 25, "best_for": "Top shorting after euphoria with VSA confirmation",
    },
    # Cross-engine confluence chains
    "institutional_reversal_long": {
        "scanners": ["wyckoff_spring", "smc_liq_sweep_bull", "vsa_selling_climax",
                     "smc_choch_bull", "volume_spike"],
        "desc": "Triple confluence: Wyckoff Spring + SMC Sweep + VSA Climax + CHoCH + volume",
        "boost": 35, "best_for": "Maximum conviction reversal longs (3 engines agree)",
    },
    "institutional_reversal_short": {
        "scanners": ["wyckoff_upthrust", "smc_liq_sweep_bear", "vsa_buying_climax",
                     "smc_choch_bear", "volume_spike"],
        "desc": "Triple confluence: Wyckoff Upthrust + SMC Sweep + VSA Climax + CHoCH + volume",
        "boost": 35, "best_for": "Maximum conviction reversal shorts (3 engines agree)",
    },
    "harmonic_confluence_long": {
        "scanners": ["harmonic_any_bull", "smc_discount", "wyckoff_accumulation",
                     "vsa_stopping_bull"],
        "desc": "Harmonic + SMC discount + Wyckoff accumulation + VSA stopping volume",
        "boost": 25, "best_for": "Fibonacci reversal with institutional confirmation",
    },
    # RL chains
    "rl_regime_momentum_long": {
        "scanners": ["rl_trend_bull", "rl_momentum_bull", "volume_spike", "upswing"],
        "desc": "RL regime trend + momentum + volume spike + upswing confirmation",
        "boost": 25, "best_for": "Trend-following entries with RL momentum confirmation",
    },
    "rl_regime_momentum_short": {
        "scanners": ["rl_trend_bear", "rl_momentum_bear", "volume_spike", "downswing"],
        "desc": "RL regime trend bear + momentum bear + volume spike + downswing",
        "boost": 25, "best_for": "Trend-following shorts with RL momentum confirmation",
    },
    "rl_optimal_confluence": {
        "scanners": ["rl_optimal_entry_bull", "rl_vwap_bull", "smc_demand_ob",
                     "wyckoff_accumulation"],
        "desc": "RL optimal entry + VWAP + SMC demand OB + Wyckoff accumulation",
        "boost": 30, "best_for": "Maximum conviction RL + institutional confluence longs",
    },
    # Forex chains
    "forex_momentum": {
        "scanners": ["cds_ema_crossover", "cds_rsi_oversold", "cds_bb_squeeze"],
        "desc": "CDS EMA crossover + RSI oversold + BB squeeze — forex momentum long",
        "boost": 20, "best_for": "Forex momentum entries on currency pairs",
    },
    "forex_reversal": {
        "scanners": ["cds_rsi_overbought", "cds_dxy_divergence", "cds_bb_squeeze_bear"],
        "desc": "CDS RSI overbought + DXY divergence + BB squeeze bear — forex reversal",
        "boost": 20, "best_for": "Forex reversal shorts on INR pairs",
    },
    # Commodity chains
    "commodity_momentum": {
        "scanners": ["mcx_ema_crossover", "mcx_crude_momentum", "mcx_rsi_oversold"],
        "desc": "MCX EMA crossover + crude momentum + RSI oversold — commodity momentum",
        "boost": 20, "best_for": "Commodity momentum entries on MCX",
    },
    "commodity_reversal": {
        "scanners": ["mcx_rsi_overbought", "mcx_ema_crossover_bear", "mcx_gold_silver_ratio_bear"],
        "desc": "MCX RSI overbought + EMA bear + gold/silver ratio expansion — reversal",
        "boost": 20, "best_for": "Commodity reversal shorts on MCX",
    },
    "gold_silver_mean_reversion": {
        "scanners": ["mcx_gold_silver_ratio", "mcx_metal_strength"],
        "desc": "Gold/silver ratio mean-reversion + multi-metal relative strength",
        "boost": 15, "best_for": "Precious metals mean-reversion trades",
    },
    # Advanced SMC chains
    "smc_breaker_reversal_long": {
        "scanners": ["smc_breaker_bull", "smc_liq_sweep_bull", "smc_mss_bull",
                     "smc_ote_bull"],
        "desc": "Breaker Block + liquidity sweep + MSS + OTE — advanced SMC reversal long",
        "boost": 30, "best_for": "Advanced SMC reversal longs with breaker block confluence",
    },
    "smc_breaker_reversal_short": {
        "scanners": ["smc_breaker_bear", "smc_liq_sweep_bear", "smc_mss_bear",
                     "smc_ote_bear"],
        "desc": "Breaker Block + liquidity sweep + MSS + OTE — advanced SMC reversal short",
        "boost": 30, "best_for": "Advanced SMC reversal shorts with breaker block confluence",
    },
    "smc_ote_entry_long": {
        "scanners": ["smc_ote_bull", "smc_demand_ob", "smc_discount",
                     "smc_bullish_fvg"],
        "desc": "OTE retracement + demand OB + discount zone + FVG — precision long entry",
        "boost": 25, "best_for": "High-precision institutional long entries at OTE",
    },
    "smc_ote_entry_short": {
        "scanners": ["smc_ote_bear", "smc_supply_ob", "smc_premium",
                     "smc_bearish_fvg"],
        "desc": "OTE retracement + supply OB + premium zone + FVG — precision short entry",
        "boost": 25, "best_for": "High-precision institutional short entries at OTE",
    },
    "smc_fake_bo_reversal": {
        "scanners": ["smc_fake_bo_bull", "smc_idm_bull", "smc_mss_bull",
                     "volume_spike"],
        "desc": "Fake breakout + inducement + MSS + volume — bear trap reversal",
        "boost": 25, "best_for": "Fake breakout reversal longs with smart money confirmation",
    },
    "smc_ema_trend_long": {
        "scanners": ["smc_ema_pullback_bull", "smc_bos_bull", "smc_demand_ob",
                     "volume_avg"],
        "desc": "9/21 EMA pullback + BOS + demand OB + volume — trend continuation",
        "boost": 20, "best_for": "EMA pullback continuation longs with SMC confluence",
    },
    # F&O / NFO chains
    "nfo_breakout_long": {
        "scanners": ["nfo_range_breakout_bull", "nfo_ema_crossover", "nfo_vol_squeeze_bull"],
        "desc": "NFO range breakout + EMA crossover + vol squeeze — index futures long",
        "boost": 25, "best_for": "High-conviction index call buying / bull spreads",
    },
    "nfo_breakdown_short": {
        "scanners": ["nfo_range_breakdown_bear", "nfo_ema_crossover_bear", "nfo_vol_squeeze_bear"],
        "desc": "NFO range breakdown + EMA bear cross + vol squeeze — index futures short",
        "boost": 25, "best_for": "High-conviction index put buying / bear spreads",
    },
    "nfo_reversal_long": {
        "scanners": ["nfo_rsi_oversold", "nfo_ema_crossover", "nfo_vol_squeeze_bull"],
        "desc": "NFO RSI oversold + EMA bullish crossover + vol squeeze — reversal long",
        "boost": 20, "best_for": "Index reversal longs after oversold conditions",
    },
    "nfo_reversal_short": {
        "scanners": ["nfo_rsi_overbought", "nfo_ema_crossover_bear", "nfo_vol_squeeze_bear"],
        "desc": "NFO RSI overbought + EMA bearish crossover + vol squeeze — reversal short",
        "boost": 20, "best_for": "Index reversal shorts after overbought conditions",
    },
}


# ── MWA SCANNER CLASS ────────────────────────────────────────

class MWAScanner:
    """Full 118-scanner MWA breadth scanner with Chartink + Python + SMC integration."""

    BASE = "https://chartink.com"
    PROCESS_URL = "https://chartink.com/screener/process"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://chartink.com/",
    }

    def __init__(self, delay: float = 1.5):
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self.logged_in = False
        self.delay = delay
        self._csrf = ""
        self._diag_logged = False  # log diagnostics only once per scan

    def login(self) -> bool:
        """Establish Chartink session and cache CSRF token.

        Public screeners don't need login — we just need a valid session
        with a CSRF token.  If CHARTINK_EMAIL is set we also attempt a
        cookie-based login so that private screeners become available.
        """
        try:
            # ── Step 1: hit the main screener page to establish session ──
            from bs4 import BeautifulSoup
            from urllib.parse import unquote

            r = self.session.get(f"{self.BASE}/screener/", timeout=15)
            logger.info("[CHARTINK] Session init: status=%d, len=%d, cookies=%s",
                        r.status_code, len(r.text),
                        list(self.session.cookies.keys()))

            # ── Step 2: extract CSRF token ──
            # Method A: meta tag (traditional Laravel)
            soup = BeautifulSoup(r.text, "html.parser")
            meta = soup.select_one('meta[name="csrf-token"]')
            if meta and meta.get("content"):
                self._csrf = meta["content"]
                logger.info("[CHARTINK] CSRF from meta tag (%d chars)", len(self._csrf))
            else:
                # Method B: XSRF-TOKEN cookie (Laravel SPA / Sanctum)
                xsrf = self.session.cookies.get("XSRF-TOKEN", "")
                if xsrf:
                    self._csrf = unquote(xsrf)
                    logger.info("[CHARTINK] CSRF from XSRF cookie (%d chars)", len(self._csrf))
                else:
                    logger.error("[CHARTINK] No CSRF token found (no meta tag, no XSRF cookie)")
                    # Log first 500 chars for diagnostics
                    logger.error("[CHARTINK] Page head: %.500s", r.text[:500])
                    return False

            # ── Step 3: optional login for private screeners ──
            email = os.environ.get("CHARTINK_EMAIL", "")
            password = os.environ.get("CHARTINK_PASSWORD", "")
            if email and password:
                logger.info("[CHARTINK] Attempting login as %s...", email[:5] + "***")
                try:
                    login_r = self.session.post(
                        f"{self.BASE}/login",
                        headers={
                            "x-csrf-token": self._csrf,
                            "Content-Type": "application/x-www-form-urlencoded",
                            "Referer": f"{self.BASE}/login",
                        },
                        data={
                            "_token": self._csrf,
                            "email": email,
                            "password": password,
                        },
                        allow_redirects=True,
                        timeout=15,
                    )

                    # After login, re-fetch screener page to get fresh CSRF
                    # (Laravel rotates CSRF on login)
                    check = self.session.get(f"{self.BASE}/screener/", timeout=15)
                    soup2 = BeautifulSoup(check.text, "html.parser")
                    meta2 = soup2.select_one('meta[name="csrf-token"]')
                    if meta2 and meta2.get("content"):
                        self._csrf = meta2["content"]
                        logger.info("[CHARTINK] Refreshed CSRF from meta tag (%d chars)", len(self._csrf))

                    uid_m = re.search(r'userId:\s*(\d+)', check.text)
                    if uid_m and uid_m.group(1) != "0":
                        self.logged_in = True
                        logger.info("[CHARTINK] Login OK (userId=%s, status=%d)",
                                    uid_m.group(1), login_r.status_code)
                    else:
                        logger.warning("[CHARTINK] Login returned %d but userId=0 — "
                                       "continuing without login (public screeners still work)",
                                       login_r.status_code)
                except Exception as e:
                    logger.warning("[CHARTINK] Login failed: %s — continuing without login", e)

            self.logged_in = self.logged_in or bool(self._csrf)
            logger.info("[CHARTINK] Ready: csrf=%d chars, authenticated=%s",
                        len(self._csrf), self.logged_in)
            return bool(self._csrf)
        except Exception as e:
            logger.error("[CHARTINK] Session init error: %s", e)
            return False

    def _ensure_csrf(self) -> str:
        """Return cached CSRF or re-fetch it."""
        if self._csrf:
            return self._csrf
        self.login()
        return self._csrf

    def _extract_scan_clause(self, html: str) -> str:
        """Extract scan_clause from Chartink page HTML.

        Tries multiple strategies:
        1. Inertia.js data-page attribute (modern SPA)
        2. JSON page props embedded in script tags
        3. Traditional form elements / JS variables
        """
        import html as htmlmod

        # ── Strategy 1: Inertia.js data-page attribute ──
        # Inertia.js embeds all page props as JSON in data-page="..."
        m = re.search(r'data-page="([^"]*(?:scan_clause|scan)[^"]*)"', html)
        if not m:
            # Try broader match — data-page can be very large
            m = re.search(r'data-page="({.*?})"', html)
        if not m:
            m = re.search(r"data-page='({.*?})'", html)
        if m:
            try:
                raw = htmlmod.unescape(m.group(1))
                page_data = json.loads(raw)
                props = page_data.get("props", {})
                clause = props.get("scan_clause", "")
                if not clause:
                    for key in ("screener", "scanner", "screen"):
                        sub = props.get(key, {})
                        if isinstance(sub, dict):
                            clause = sub.get("scan_clause", sub.get("scanClause", ""))
                            if clause:
                                break
                if clause:
                    return clause.replace("\\n", "\n").replace('\\"', '"')
            except (json.JSONDecodeError, ValueError):
                pass

        # ── Strategy 2: JSON blob in script tag or inline JS ──
        patterns = [
            r'"scan_clause"\s*:\s*"((?:[^"\\]|\\.)*)"',
            r'"scanClause"\s*:\s*"((?:[^"\\]|\\.)*)"',
            r"'scan_clause'\s*:\s*'((?:[^'\\]|\\.)*)'",
            r'var\s+scan_clause\s*=\s*["\'](.+?)["\']',
            r'scan_clause["\s:=]+["\'](.+?)["\']',
        ]
        for pat in patterns:
            found = re.search(pat, html, re.DOTALL)
            if found:
                clause = (found.group(1) or "").strip()
                if clause and len(clause) > 10:
                    return clause.replace("\\n", "\n").replace('\\"', '"')

        # ── Strategy 3: Traditional form elements ──
        patterns_form = [
            r'<textarea[^>]*id=["\']scan_clause["\'][^>]*>(.*?)</textarea>',
            r'name=["\']scan_clause["\'][^>]*value=["\']([^"\']*)["\']',
            r'data-scan-clause=["\']([^"\']+)["\']',
        ]
        for pat in patterns_form:
            found = re.search(pat, html, re.DOTALL)
            if found:
                clause = (found.group(1) or "").strip()
                if clause:
                    return htmlmod.unescape(clause)

        return ""

    def fetch_chartink(self, slug: str, hardcoded_clause: str = "") -> list[str]:
        """Fetch stock list from a Chartink screener.

        Flow:
        1. Use hardcoded scan_clause if available (preferred — no page fetch needed)
        2. Otherwise GET screener page → try to extract scan_clause from HTML
        3. POST scan_clause to /screener/process with CSRF header
        """
        try:
            csrf = self._ensure_csrf()
            if not csrf:
                return []

            # ── Priority 1: hardcoded scan_clause ──
            scan_clause = hardcoded_clause

            # ── Priority 2: extract from page HTML ──
            if not scan_clause:
                page = self.session.get(f"{self.BASE}/screener/{slug}", timeout=15)
                if page.status_code != 200:
                    logger.warning("[CHARTINK] %s returned status %d", slug, page.status_code)
                    return []
                scan_clause = self._extract_scan_clause(page.text)

            # Fallback: try X-Inertia JSON request
            if not scan_clause:
                try:
                    inertia_r = self.session.get(
                        f"{self.BASE}/screener/{slug}",
                        headers={
                            "X-Inertia": "true",
                            "X-Inertia-Version": "",
                            "X-Requested-With": "XMLHttpRequest",
                            "Accept": "text/html, application/xhtml+xml",
                        },
                        timeout=10,
                    )
                    if inertia_r.status_code == 200:
                        try:
                            idata = inertia_r.json()
                            props = idata.get("props", {})
                            scan_clause = props.get("scan_clause", "")
                            if not scan_clause:
                                for key in ("screener", "scanner", "screen"):
                                    sub = props.get(key, {})
                                    if isinstance(sub, dict):
                                        scan_clause = sub.get("scan_clause", sub.get("scanClause", ""))
                                        if scan_clause:
                                            break
                            if scan_clause:
                                logger.info("[CHARTINK] Got scan_clause via X-Inertia for %s", slug)
                        except (ValueError, KeyError):
                            pass
                except Exception:
                    pass

            # Fallback: try /screener/data/{slug} API endpoint
            if not scan_clause:
                try:
                    api_r = self.session.get(
                        f"{self.BASE}/screener/data/{slug}",
                        headers={
                            "X-Requested-With": "XMLHttpRequest",
                            "Accept": "application/json",
                        },
                        timeout=10,
                    )
                    if api_r.status_code == 200:
                        api_data = api_r.json()
                        scan_clause = api_data.get("scan_clause", api_data.get("scanClause", ""))
                        if scan_clause:
                            logger.info("[CHARTINK] Got scan_clause via API for %s", slug)
                except Exception:
                    pass

            if not scan_clause:
                # Log diagnostics once per scan session
                if not self._diag_logged:
                    has_data_page = "data-page" in page.text
                    has_app_div = 'id="app"' in page.text
                    has_inertia = "inertia" in page.text.lower()
                    logger.warning(
                        "[CHARTINK] No scan_clause for %s — page diagnostics: "
                        "len=%d, data-page=%s, #app=%s, inertia=%s, "
                        "first_300=%.300s",
                        slug, len(page.text), has_data_page, has_app_div,
                        has_inertia, page.text[:300],
                    )
                    self._diag_logged = True
                else:
                    logger.warning("[CHARTINK] No scan_clause for %s", slug)
                return []

            # ── POST to /screener/process ──
            r = self.session.post(
                self.PROCESS_URL,
                timeout=15,
                headers={
                    "x-csrf-token": csrf,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"scan_clause": scan_clause},
            )

            if r.status_code != 200:
                logger.warning("[CHARTINK] /screener/process returned %d for %s (body=%.200s)",
                               r.status_code, slug, r.text[:200])
                return []

            stocks = [
                i.get("nsecode", i.get("symbol", ""))
                for i in r.json().get("data", [])
            ]
            return [s for s in stocks if s]
        except Exception as e:
            logger.error("[CHARTINK] Fetch failed for %s: %s", slug, e)
            return []

    def run_python_scanners(self, stock_data: dict | None = None, segment: str = "ALL") -> dict[str, list[str]]:
        """Run Python-based scanners that replace/supplement Chartink.

        Args:
            stock_data: Dict of {ticker: DataFrame} for Python scanners
            segment: "ALL" runs every Python scanner, or "NSE"/"MCX"/"CDS"/"NFO"
                     runs only scanners whose segments list includes that value.
        """
        results: dict[str, list[str]] = {}

        def _should_run(scanner_key: str) -> bool:
            """Check if scanner should run for the given segment."""
            if segment == "ALL":
                return True
            cfg = SCANNERS.get(scanner_key, {})
            return segment in cfg.get("segments", [])

        try:
            from mcp_server.technical_scanners import scan_supertrend
            if stock_data and _should_run("supertrend_buy"):
                st_result = scan_supertrend(stock_data)
                results["supertrend_buy"] = st_result.get("stocks", [])
            else:
                results["supertrend_buy"] = []
        except ImportError:
            logger.warning("technical_scanners.scan_supertrend not available")
            results["supertrend_buy"] = []

        # Intraday momentum scanner (catches top gainers/losers)
        if stock_data:
            for mom_key, mom_dir, mom_pct in [
                ("intraday_momentum_bull", "bull", 3.0),
                ("intraday_momentum_bear", "bear", -3.0),
            ]:
                if not _should_run(mom_key):
                    results[mom_key] = []
                    continue
                try:
                    hits: list[str] = []
                    for ticker, df in stock_data.items():
                        if df is None or df.empty or len(df) < 2:
                            continue
                        curr = df.iloc[-1]
                        prev = df.iloc[-2]
                        c = float(curr.get("Close", curr.get("close", 0)))
                        o = float(curr.get("Open", curr.get("open", 0)))
                        pc = float(prev.get("Close", prev.get("close", 0)))
                        if o == 0 or pc == 0:
                            continue
                        intraday_pct = ((c - o) / o) * 100
                        vs_prev_pct = ((c - pc) / pc) * 100
                        if mom_dir == "bull" and intraday_pct >= mom_pct and vs_prev_pct > 0:
                            hits.append(ticker.replace("NSE:", ""))
                        elif mom_dir == "bear" and intraday_pct <= mom_pct and vs_prev_pct < 0:
                            hits.append(ticker.replace("NSE:", ""))
                    results[mom_key] = hits
                    if hits:
                        logger.info("[MOMENTUM] %s: %d stocks: %s", mom_key, len(hits), hits[:5])
                except Exception as e:
                    logger.error("Intraday momentum scanner %s failed: %s", mom_key, e)
                    results[mom_key] = []

            # daily_pct_change_py scanner (was defined but never executed)
            if _should_run("daily_pct_change_py"):
                try:
                    hits = []
                    for ticker, df in stock_data.items():
                        if df is None or df.empty or len(df) < 2:
                            continue
                        curr = df.iloc[-1]
                        prev = df.iloc[-2]
                        c = float(curr.get("Close", curr.get("close", 0)))
                        pc = float(prev.get("Close", prev.get("close", 0)))
                        if pc > 0 and ((c - pc) / pc) * 100 > 3.0:
                            hits.append(ticker.replace("NSE:", ""))
                    results["daily_pct_change_py"] = hits
                except Exception as e:
                    logger.error("daily_pct_change_py failed: %s", e)
                    results["daily_pct_change_py"] = []
        else:
            results["intraday_momentum_bull"] = []
            results["intraday_momentum_bear"] = []
            results["daily_pct_change_py"] = []

        # macd_buy_daily and 52week_high are now Chartink-sourced (no Python fallback needed)

        # SMC scanners (require stock_data with OHLCV DataFrames)
        try:
            from mcp_server.smc_engine import (
                scan_bos_bull, scan_bos_bear,
                scan_choch_bull, scan_choch_bear,
                scan_bullish_ob, scan_bearish_ob,
                scan_bullish_fvg, scan_bearish_fvg,
                scan_liquidity_sweep_bull, scan_liquidity_sweep_bear,
                scan_discount_zone, scan_premium_zone,
                scan_breaker_block_bull, scan_breaker_block_bear,
                scan_mitigation_block_bull, scan_mitigation_block_bear,
                scan_ifvg_bull, scan_ifvg_bear,
                scan_mss_bull, scan_mss_bear,
                scan_ote_bull, scan_ote_bear,
                scan_inducement_bull, scan_inducement_bear,
                scan_ce_bull, scan_ce_bear,
                scan_erl_bull, scan_erl_bear,
                scan_fake_breakout_bull, scan_fake_breakout_bear,
                scan_ema_pullback_bull, scan_ema_pullback_bear,
            )
            if stock_data:
                smc_scanners = {
                    "smc_bos_bull": scan_bos_bull,
                    "smc_bos_bear": scan_bos_bear,
                    "smc_choch_bull": scan_choch_bull,
                    "smc_choch_bear": scan_choch_bear,
                    "smc_demand_ob": scan_bullish_ob,
                    "smc_supply_ob": scan_bearish_ob,
                    "smc_bullish_fvg": scan_bullish_fvg,
                    "smc_bearish_fvg": scan_bearish_fvg,
                    "smc_liq_sweep_bull": scan_liquidity_sweep_bull,
                    "smc_liq_sweep_bear": scan_liquidity_sweep_bear,
                    "smc_discount": scan_discount_zone,
                    "smc_premium": scan_premium_zone,
                    "smc_breaker_bull": scan_breaker_block_bull,
                    "smc_breaker_bear": scan_breaker_block_bear,
                    "smc_mitigation_bull": scan_mitigation_block_bull,
                    "smc_mitigation_bear": scan_mitigation_block_bear,
                    "smc_ifvg_bull": scan_ifvg_bull,
                    "smc_ifvg_bear": scan_ifvg_bear,
                    "smc_mss_bull": scan_mss_bull,
                    "smc_mss_bear": scan_mss_bear,
                    "smc_ote_bull": scan_ote_bull,
                    "smc_ote_bear": scan_ote_bear,
                    "smc_idm_bull": scan_inducement_bull,
                    "smc_idm_bear": scan_inducement_bear,
                    "smc_ce_bull": scan_ce_bull,
                    "smc_ce_bear": scan_ce_bear,
                    "smc_erl_bull": scan_erl_bull,
                    "smc_erl_bear": scan_erl_bear,
                    "smc_fake_bo_bull": scan_fake_breakout_bull,
                    "smc_fake_bo_bear": scan_fake_breakout_bear,
                    "smc_ema_pullback_bull": scan_ema_pullback_bull,
                    "smc_ema_pullback_bear": scan_ema_pullback_bear,
                }
                for key, scanner_fn in smc_scanners.items():
                    if not _should_run(key):
                        continue
                    try:
                        results[key] = scanner_fn(stock_data)
                    except Exception as e:
                        logger.error("SMC scanner %s failed: %s", key, e)
                        results[key] = []
            else:
                for key in [
                    "smc_bos_bull", "smc_bos_bear", "smc_choch_bull", "smc_choch_bear",
                    "smc_demand_ob", "smc_supply_ob", "smc_bullish_fvg", "smc_bearish_fvg",
                    "smc_liq_sweep_bull", "smc_liq_sweep_bear", "smc_discount", "smc_premium",
                    "smc_breaker_bull", "smc_breaker_bear", "smc_mitigation_bull", "smc_mitigation_bear",
                    "smc_ifvg_bull", "smc_ifvg_bear", "smc_mss_bull", "smc_mss_bear",
                    "smc_ote_bull", "smc_ote_bear", "smc_idm_bull", "smc_idm_bear",
                    "smc_ce_bull", "smc_ce_bear", "smc_erl_bull", "smc_erl_bear",
                    "smc_fake_bo_bull", "smc_fake_bo_bear",
                    "smc_ema_pullback_bull", "smc_ema_pullback_bear",
                ]:
                    results[key] = []
        except ImportError:
            logger.warning("smc_engine not available — skipping SMC scanners")

        # Wyckoff scanners
        try:
            from mcp_server.wyckoff_engine import (
                scan_accumulation, scan_distribution, scan_spring, scan_upthrust,
                scan_sos, scan_sow, scan_test_bull, scan_test_bear,
            )
            if stock_data:
                wyckoff_scanners = {
                    "wyckoff_accumulation": scan_accumulation,
                    "wyckoff_distribution": scan_distribution,
                    "wyckoff_spring": scan_spring,
                    "wyckoff_upthrust": scan_upthrust,
                    "wyckoff_sos": scan_sos,
                    "wyckoff_sow": scan_sow,
                    "wyckoff_test_bull": scan_test_bull,
                    "wyckoff_test_bear": scan_test_bear,
                }
                for key, scanner_fn in wyckoff_scanners.items():
                    if not _should_run(key):
                        continue
                    try:
                        results[key] = scanner_fn(stock_data)
                    except Exception as e:
                        logger.error("Wyckoff scanner %s failed: %s", key, e)
                        results[key] = []
            else:
                for key in [
                    "wyckoff_accumulation", "wyckoff_distribution", "wyckoff_spring",
                    "wyckoff_upthrust", "wyckoff_sos", "wyckoff_sow",
                    "wyckoff_test_bull", "wyckoff_test_bear",
                ]:
                    results[key] = []
        except ImportError:
            logger.warning("wyckoff_engine not available — skipping Wyckoff scanners")

        # VSA scanners
        try:
            from mcp_server.vsa_engine import (
                scan_no_supply, scan_no_demand,
                scan_stopping_vol_bull, scan_stopping_vol_bear,
                scan_selling_climax, scan_buying_climax,
                scan_effort_bull, scan_effort_bear,
            )
            if stock_data:
                vsa_scanners = {
                    "vsa_no_supply": scan_no_supply,
                    "vsa_no_demand": scan_no_demand,
                    "vsa_stopping_bull": scan_stopping_vol_bull,
                    "vsa_stopping_bear": scan_stopping_vol_bear,
                    "vsa_selling_climax": scan_selling_climax,
                    "vsa_buying_climax": scan_buying_climax,
                    "vsa_effort_bull": scan_effort_bull,
                    "vsa_effort_bear": scan_effort_bear,
                }
                for key, scanner_fn in vsa_scanners.items():
                    if not _should_run(key):
                        continue
                    try:
                        results[key] = scanner_fn(stock_data)
                    except Exception as e:
                        logger.error("VSA scanner %s failed: %s", key, e)
                        results[key] = []
            else:
                for key in [
                    "vsa_no_supply", "vsa_no_demand", "vsa_stopping_bull",
                    "vsa_stopping_bear", "vsa_selling_climax", "vsa_buying_climax",
                    "vsa_effort_bull", "vsa_effort_bear",
                ]:
                    results[key] = []
        except ImportError:
            logger.warning("vsa_engine not available — skipping VSA scanners")

        # Harmonic scanners
        try:
            from mcp_server.harmonic_engine import (
                scan_harmonic_gartley_bull, scan_harmonic_gartley_bear,
                scan_harmonic_bat_bull, scan_harmonic_bat_bear,
                scan_harmonic_any_bull, scan_harmonic_any_bear,
            )
            if stock_data:
                harmonic_scanners = {
                    "harmonic_gartley_bull": scan_harmonic_gartley_bull,
                    "harmonic_gartley_bear": scan_harmonic_gartley_bear,
                    "harmonic_bat_bull": scan_harmonic_bat_bull,
                    "harmonic_bat_bear": scan_harmonic_bat_bear,
                    "harmonic_any_bull": scan_harmonic_any_bull,
                    "harmonic_any_bear": scan_harmonic_any_bear,
                }
                for key, scanner_fn in harmonic_scanners.items():
                    if not _should_run(key):
                        continue
                    try:
                        results[key] = scanner_fn(stock_data)
                    except Exception as e:
                        logger.error("Harmonic scanner %s failed: %s", key, e)
                        results[key] = []
            else:
                for key in [
                    "harmonic_gartley_bull", "harmonic_gartley_bear",
                    "harmonic_bat_bull", "harmonic_bat_bear",
                    "harmonic_any_bull", "harmonic_any_bear",
                ]:
                    results[key] = []
        except ImportError:
            logger.warning("harmonic_engine not available — skipping Harmonic scanners")

        # Forex (CDS) scanners
        try:
            from mcp_server.forex_scanners import (
                scan_cds_ema_crossover, scan_cds_ema_crossover_bear,
                scan_cds_rsi_oversold, scan_cds_rsi_overbought,
                scan_cds_bb_squeeze, scan_cds_bb_squeeze_bear,
                scan_cds_carry_trade, scan_cds_dxy_divergence,
            )
            if stock_data:
                forex_scanners = {
                    "cds_ema_crossover": scan_cds_ema_crossover,
                    "cds_ema_crossover_bear": scan_cds_ema_crossover_bear,
                    "cds_rsi_oversold": scan_cds_rsi_oversold,
                    "cds_rsi_overbought": scan_cds_rsi_overbought,
                    "cds_bb_squeeze": scan_cds_bb_squeeze,
                    "cds_bb_squeeze_bear": scan_cds_bb_squeeze_bear,
                    "cds_carry_trade": scan_cds_carry_trade,
                    "cds_dxy_divergence": scan_cds_dxy_divergence,
                }
                for key, scanner_fn in forex_scanners.items():
                    if not _should_run(key):
                        continue
                    try:
                        results[key] = scanner_fn(stock_data)
                    except Exception as e:
                        logger.error("Forex scanner %s failed: %s", key, e)
                        results[key] = []
            else:
                for key in [
                    "cds_ema_crossover", "cds_ema_crossover_bear",
                    "cds_rsi_oversold", "cds_rsi_overbought",
                    "cds_bb_squeeze", "cds_bb_squeeze_bear",
                    "cds_carry_trade", "cds_dxy_divergence",
                ]:
                    results[key] = []
        except ImportError:
            logger.warning("forex_scanners not available — skipping Forex scanners")

        # Commodity (MCX) scanners
        try:
            from mcp_server.commodity_scanners import (
                scan_mcx_ema_crossover, scan_mcx_ema_crossover_bear,
                scan_mcx_rsi_oversold, scan_mcx_rsi_overbought,
                scan_mcx_gold_silver_ratio, scan_mcx_gold_silver_ratio_bear,
                scan_mcx_crude_momentum, scan_mcx_metal_strength,
            )
            if stock_data:
                commodity_scanners = {
                    "mcx_ema_crossover": scan_mcx_ema_crossover,
                    "mcx_ema_crossover_bear": scan_mcx_ema_crossover_bear,
                    "mcx_rsi_oversold": scan_mcx_rsi_oversold,
                    "mcx_rsi_overbought": scan_mcx_rsi_overbought,
                    "mcx_gold_silver_ratio": scan_mcx_gold_silver_ratio,
                    "mcx_gold_silver_ratio_bear": scan_mcx_gold_silver_ratio_bear,
                    "mcx_crude_momentum": scan_mcx_crude_momentum,
                    "mcx_metal_strength": scan_mcx_metal_strength,
                }
                for key, scanner_fn in commodity_scanners.items():
                    if not _should_run(key):
                        continue
                    try:
                        results[key] = scanner_fn(stock_data)
                    except Exception as e:
                        logger.error("Commodity scanner %s failed: %s", key, e)
                        results[key] = []
            else:
                for key in [
                    "mcx_ema_crossover", "mcx_ema_crossover_bear",
                    "mcx_rsi_oversold", "mcx_rsi_overbought",
                    "mcx_gold_silver_ratio", "mcx_gold_silver_ratio_bear",
                    "mcx_crude_momentum", "mcx_metal_strength",
                ]:
                    results[key] = []
        except ImportError:
            logger.warning("commodity_scanners not available — skipping Commodity scanners")

        # F&O (NFO) scanners — indices (121-128) + F&O stocks (129-136)
        try:
            from mcp_server.nfo_scanners import (
                scan_nfo_ema_crossover, scan_nfo_ema_crossover_bear,
                scan_nfo_rsi_oversold, scan_nfo_rsi_overbought,
                scan_nfo_vol_squeeze_bull, scan_nfo_vol_squeeze_bear,
                scan_nfo_range_breakout_bull, scan_nfo_range_breakdown_bear,
                scan_nfo_stk_ema_crossover, scan_nfo_stk_ema_crossover_bear,
                scan_nfo_stk_rsi_oversold, scan_nfo_stk_rsi_overbought,
                scan_nfo_stk_vol_squeeze_bull, scan_nfo_stk_vol_squeeze_bear,
                scan_nfo_stk_range_breakout_bull, scan_nfo_stk_range_breakdown_bear,
            )
            if stock_data:
                nfo_scanners = {
                    "nfo_ema_crossover": scan_nfo_ema_crossover,
                    "nfo_ema_crossover_bear": scan_nfo_ema_crossover_bear,
                    "nfo_rsi_oversold": scan_nfo_rsi_oversold,
                    "nfo_rsi_overbought": scan_nfo_rsi_overbought,
                    "nfo_vol_squeeze_bull": scan_nfo_vol_squeeze_bull,
                    "nfo_vol_squeeze_bear": scan_nfo_vol_squeeze_bear,
                    "nfo_range_breakout_bull": scan_nfo_range_breakout_bull,
                    "nfo_range_breakdown_bear": scan_nfo_range_breakdown_bear,
                    # F&O stock variants (RELIANCE, TCS, HDFCBANK, ...)
                    "nfo_stk_ema_crossover": scan_nfo_stk_ema_crossover,
                    "nfo_stk_ema_crossover_bear": scan_nfo_stk_ema_crossover_bear,
                    "nfo_stk_rsi_oversold": scan_nfo_stk_rsi_oversold,
                    "nfo_stk_rsi_overbought": scan_nfo_stk_rsi_overbought,
                    "nfo_stk_vol_squeeze_bull": scan_nfo_stk_vol_squeeze_bull,
                    "nfo_stk_vol_squeeze_bear": scan_nfo_stk_vol_squeeze_bear,
                    "nfo_stk_range_breakout_bull": scan_nfo_stk_range_breakout_bull,
                    "nfo_stk_range_breakdown_bear": scan_nfo_stk_range_breakdown_bear,
                }
                for key, scanner_fn in nfo_scanners.items():
                    if not _should_run(key):
                        continue
                    try:
                        results[key] = scanner_fn(stock_data)
                    except Exception as e:
                        logger.error("NFO scanner %s failed: %s", key, e)
                        results[key] = []
            else:
                for key in [
                    "nfo_ema_crossover", "nfo_ema_crossover_bear",
                    "nfo_rsi_oversold", "nfo_rsi_overbought",
                    "nfo_vol_squeeze_bull", "nfo_vol_squeeze_bear",
                    "nfo_range_breakout_bull", "nfo_range_breakdown_bear",
                    "nfo_stk_ema_crossover", "nfo_stk_ema_crossover_bear",
                    "nfo_stk_rsi_oversold", "nfo_stk_rsi_overbought",
                    "nfo_stk_vol_squeeze_bull", "nfo_stk_vol_squeeze_bear",
                    "nfo_stk_range_breakout_bull", "nfo_stk_range_breakdown_bear",
                ]:
                    results[key] = []
        except ImportError:
            logger.warning("nfo_scanners not available — skipping F&O scanners")

        # RL scanners
        try:
            from mcp_server.rl_engine import (
                scan_rl_trend_bull, scan_rl_trend_bear,
                scan_rl_vwap_bull, scan_rl_vwap_bear,
                scan_rl_momentum_bull, scan_rl_momentum_bear,
                scan_rl_optimal_entry_bull, scan_rl_optimal_entry_bear,
            )
            if stock_data:
                rl_scanners = {
                    "rl_trend_bull": scan_rl_trend_bull,
                    "rl_trend_bear": scan_rl_trend_bear,
                    "rl_vwap_bull": scan_rl_vwap_bull,
                    "rl_vwap_bear": scan_rl_vwap_bear,
                    "rl_momentum_bull": scan_rl_momentum_bull,
                    "rl_momentum_bear": scan_rl_momentum_bear,
                    "rl_optimal_entry_bull": scan_rl_optimal_entry_bull,
                    "rl_optimal_entry_bear": scan_rl_optimal_entry_bear,
                }
                for key, scanner_fn in rl_scanners.items():
                    if not _should_run(key):
                        continue
                    try:
                        results[key] = scanner_fn(stock_data)
                    except Exception as e:
                        logger.error("RL scanner %s failed: %s", key, e)
                        results[key] = []
            else:
                for key in [
                    "rl_trend_bull", "rl_trend_bear",
                    "rl_vwap_bull", "rl_vwap_bear",
                    "rl_momentum_bull", "rl_momentum_bear",
                    "rl_optimal_entry_bull", "rl_optimal_entry_bear",
                ]:
                    results[key] = []
        except ImportError:
            logger.warning("rl_engine not available — skipping RL scanners")

        return results

    def run_all(self, stock_data: dict | None = None, save: bool = True, segment: str = "ALL") -> dict[str, list[str]]:
        """
        Run scanners and return results.

        Args:
            stock_data: Dict of {ticker: DataFrame} for Python scanners
            save: Whether to save results to JSON file
            segment: "ALL" runs everything (backward compatible),
                     "NSE" runs Chartink + NSE-tagged Python scanners,
                     "MCX"/"CDS"/"NFO" runs only segment-tagged Python scanners (no Chartink).
        """
        if not self._csrf:
            self.login()

        results: dict[str, list[str]] = {}
        self._diag_logged = False  # reset diagnostics flag per scan run
        skip_types = {"FILTER", "UNKNOWN"}
        layers = ["Trend", "Volume", "Breakout", "RSI", "Gap", "MA"]

        run_chartink = segment in ("ALL", "NSE")

        logger.info("MWA Scan started at %s (segment=%s, csrf=%d chars)",
                     now_ist().strftime("%d %b %Y %H:%M"), segment, len(self._csrf))

        # Chartink scanners by layer — only for NSE/ALL
        if run_chartink:
            for layer in layers:
                items = {
                    k: v for k, v in SCANNERS.items()
                    if v["layer"] == layer
                    and v["type"] not in skip_types
                    and v["source"] == "Chartink"
                    and "CREATE" not in v.get("slug", "")
                    and "python:" not in v.get("slug", "")
                }
                if not items:
                    continue
                # Skip auto-disabled scanners (Bayesian underperformers)
                try:
                    from mcp_server.scanner_bayesian import get_disabled_scanners
                    _auto_disabled = get_disabled_scanners()
                except Exception:
                    _auto_disabled = set()

                logger.info("[CHARTINK] Scanning layer: %s (%d scanners)", layer, len(items))
                for key, cfg in items.items():
                    if key in _auto_disabled:
                        logger.info("[CHARTINK] %s: SKIPPED (auto-disabled by Bayesian stats)", key)
                        results[key] = []
                        continue
                    try:
                        stocks = self.fetch_chartink(cfg["slug"], cfg.get("scan_clause", ""))
                        results[key] = stocks
                        logger.info(
                            "[CHARTINK] %s: %d stocks (%s)", key, len(stocks), cfg["type"]
                        )
                        time.sleep(self.delay)
                    except Exception as e:
                        results[key] = []
                        logger.error("[CHARTINK] Scanner %s failed: %s", key, e)

            # Chartink summary
            chartink_active = sum(1 for k, v in results.items() if v)
            chartink_total = len(results)
            logger.info("[CHARTINK] Done: %d/%d scanners found stocks (logged_in=%s)",
                         chartink_active, chartink_total, self.logged_in)

        # Python scanners (segment-filtered)
        logger.info("Running Python scanners (segment=%s)...", segment)
        py_results = self.run_python_scanners(stock_data, segment=segment)
        for key, stocks in py_results.items():
            results[key] = [s.replace("NSE:", "") for s in stocks]
            logger.info("[PYTHON] %s: %d stocks", key, len(results[key]))

        # TradingView scanners — union into existing keys for NSE/ALL only.
        # Gated behind TRADINGVIEW_SCANNER_ENABLED; no-op when flag is off
        # or tradingview-screener isn't installed.
        if segment in ("ALL", "NSE"):
            try:
                from mcp_server import tradingview_scanner as tv_scanner

                if tv_scanner.is_available():
                    tv_results = tv_scanner.run_all()
                    added_total = 0
                    for key, tv_symbols in tv_results.items():
                        existing = results.get(key, [])
                        seen = set(existing)
                        additions = [s for s in tv_symbols if s and s not in seen]
                        if additions:
                            results[key] = existing + additions
                            added_total += len(additions)
                            logger.info(
                                "[TRADINGVIEW] %s: +%d symbols (total now %d)",
                                key, len(additions), len(results[key]),
                            )
                    logger.info(
                        "[TRADINGVIEW] Done: %d scanners queried, %d net new symbols unioned",
                        len(tv_results), added_total,
                    )
            except Exception as e:
                logger.warning("[TRADINGVIEW] scanner pass failed: %s", e)

        if save:
            try:
                data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
                os.makedirs(data_dir, exist_ok=True)
                with open(os.path.join(data_dir, "mwa_results.json"), "w") as f:
                    json.dump(
                        {
                            "timestamp": now_ist().isoformat(),
                            "counts": {k: len(v) for k, v in results.items()},
                            "stocks": results,
                        },
                        f,
                        indent=2,
                    )
            except Exception as e:
                logger.warning("Failed to save MWA results: %s", e)

        return results

    def apply_python_filters(
        self, candidates: list[dict], fii_check: bool = True
    ) -> list[dict]:
        """Apply all Python pre-filters before signals reach Claude AI."""
        try:
            from mcp_server.delivery_filter import apply_delivery_filter
            candidates = apply_delivery_filter(candidates, min_delivery_pct=60)
            logger.info("After delivery filter: %d candidates", len(candidates))
        except ImportError:
            logger.warning("delivery_filter not available — skipping")

        if fii_check:
            try:
                from mcp_server.fii_dii_filter import get_fii_dii_data, fii_allows_long
                fii_data = get_fii_dii_data()
                fii_net = fii_data.get("fii_net", 0)
                if not fii_allows_long(fii_net):
                    candidates = [c for c in candidates if c.get("direction") != "LONG"]
                    logger.info(
                        "FII selling today — %d candidates after FII filter", len(candidates)
                    )
            except ImportError:
                logger.warning("fii_dii_filter not available — skipping")

        try:
            from mcp_server.sector_filter import get_sector_strength, sector_allows_trade
            sector_strength = get_sector_strength()
            candidates = [
                c for c in candidates
                if sector_allows_trade(
                    c.get("ticker", ""), c.get("direction", "LONG"), sector_strength
                )
            ]
            logger.info("After sector filter: %d candidates", len(candidates))
        except ImportError:
            logger.warning("sector_filter not available — skipping")

        return candidates


# ── BACKWARD-COMPATIBLE FUNCTIONS ────────────────────────────
# These wrap the class for callers expecting the old API.


def fetch_chartink(url: str, timeout: int = 30) -> list[str]:
    """Legacy: Fetch stock list from a Chartink screener URL."""
    try:
        session = requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        page = session.get(url, timeout=timeout)
        page.raise_for_status()

        csrf_match = re.search(
            r'meta name="csrf-token" content="([^"]+)"', page.text
        )
        if not csrf_match:
            logger.warning("Could not extract CSRF from %s", url)
            return []

        # Extract scan_clause from page
        scan_clause = ""
        sc_match = re.search(r'"scan_clause"\s*:\s*"(.*?)"', page.text)
        if sc_match:
            scan_clause = sc_match.group(1).replace("\\n", "\n").replace('\\"', '"')

        result = session.post(
            "https://chartink.com/screener/process",
            data={"scan_clause": scan_clause},
            headers={
                "X-CSRF-Token": csrf_match.group(1),
                "X-Requested-With": "XMLHttpRequest",
                "Referer": url,
            },
            timeout=timeout,
        )
        stocks = [item.get("nsecode", "") for item in result.json().get("data", [])]
        return [s for s in stocks if s]
    except Exception as e:
        logger.error("Chartink fetch failed for %s: %s", url, e)
        return []


def run_all_chartink_scanners() -> dict[str, dict]:
    """
    Legacy: Run all Chartink scanners and return results in old format.

    Returns dict keyed by scanner_id with:
        name, group, direction, weight, stocks (list), count
    """
    scanner = MWAScanner()
    raw_results = scanner.run_all(save=False)

    results: dict[str, dict] = {}
    for key, stocks in raw_results.items():
        cfg = SCANNERS.get(key, {})
        results[key] = {
            "name": key,
            "group": cfg.get("layer", ""),
            "direction": cfg.get("type", "NEUTRAL"),
            "weight": cfg.get("weight", 1.0),
            "stocks": stocks,
            "count": len(stocks),
        }

    total = sum(r["count"] for r in results.values())
    logger.info(
        "All scanners complete: %d total hits across %d scanners", total, len(results)
    )
    return results
