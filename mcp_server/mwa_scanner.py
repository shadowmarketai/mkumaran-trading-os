"""
MKUMARAN Trading OS — 98-Scanner MWA System

FINAL COUNT:
  98 total = 60 BULL + 30 BEAR + 4 FILTER + 4 BEAR(CDS/MCX)
  34 Chartink + 64 Python
  14 layers: Trend / Volume / Breakout / RSI / Gap / MA / Filter / SMC / Wyckoff / VSA / Harmonic / RL / Forex / Commodity
  28 signal chains (10 original + 3 SMC + 8 cross-engine + 3 RL + 5 Forex/Commodity)
"""

import logging
import os
import re
import time
import json
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# 40 SCANNERS — 7 LAYERS
# ══════════════════════════════════════════════════════════════

SCANNERS = {

    # ── LAYER 1 — TREND DIRECTION (8 scanners) ──────────────

    "swing_low": {
        "no": 1, "slug": "copy-swing-low-daily-100",
        "type": "BULL", "weight": 2.5, "layer": "Trend", "source": "Chartink",
        "desc": "Personal swing low. Stock at swing low = at LTRP zone. Core RRMS long entry trigger.",
        "pairs_with": ["upswing", "volume_avg", "rsi_above_30", "llbb_bounce"],
        "status": "ACTIVE",
    },
    "upswing": {
        "no": 2, "slug": "copy-upswing-daily-82",
        "type": "BULL", "weight": 2.5, "layer": "Trend", "source": "Chartink",
        "desc": "Personal upswing. Higher highs + higher lows. Rule 3 enforcer for longs.",
        "pairs_with": ["swing_low", "bandwalk_highs", "breakout_200dma"],
        "status": "ACTIVE",
    },
    "swing_high": {
        "no": 3, "slug": "copy-swing-high-daily-192",
        "type": "BEAR", "weight": 2.5, "layer": "Trend", "source": "Chartink",
        "desc": "Personal swing high. Near Pivot High / short zone.",
        "pairs_with": ["downswing", "failure_swing_bearish", "macd_sell_weekly"],
        "status": "ACTIVE",
    },
    "downswing": {
        "no": 4, "slug": "copy-downswing-daily-177",
        "type": "BEAR", "weight": 2.5, "layer": "Trend", "source": "Chartink",
        "desc": "Personal downswing. Lower highs + lower lows. Rule 3 for shorts.",
        "pairs_with": ["swing_high", "bearish_divergence", "macd_sell_weekly"],
        "status": "ACTIVE",
    },
    "bandwalk_highs": {
        "no": 5, "slug": "copy-bandwalk-with-highs-green-candle-daily-150",
        "type": "BULL", "weight": 2.5, "layer": "Trend", "source": "Chartink",
        "desc": "Bandwalk: hugging upper BB making new highs with green candle.",
        "pairs_with": ["upswing", "breakout_200dma", "volume_spike"],
        "status": "ACTIVE",
    },
    "llbb_bounce": {
        "no": 6, "slug": "copy-todays-low-bounced-off-llbb-and-green-candle-close-184",
        "type": "BULL", "weight": 2.5, "layer": "Trend", "source": "Chartink",
        "desc": "Low touched Lower BB + green candle close. RRMS LTRP bounce confirmation.",
        "pairs_with": ["swing_low", "rsi_above_30", "failure_swing_bullish", "near_200ma_v2"],
        "status": "ACTIVE",
    },
    "macd_sell_weekly": {
        "no": 7, "slug": "copy-macd-sell-call-weekly-chart-170",
        "type": "BEAR", "weight": 2.5, "layer": "Trend", "source": "Chartink",
        "desc": "MACD sell on weekly chart. Higher timeframe bearish conviction.",
        "pairs_with": ["swing_high", "downswing", "failure_swing_bearish", "bearish_divergence"],
        "status": "ACTIVE",
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
    },
    "volume_spike": {
        "no": 10, "slug": "copy-volume-previous-50-days-average-volume-10-173",
        "type": "BULL", "weight": 3.0, "layer": "Volume", "source": "Chartink",
        "desc": "Volume spike 2x+ 50-day average. STRONG institutional move.",
        "pairs_with": ["breakout_200dma", "breakout_50day", "richie_rich_breakout"],
        "status": "ACTIVE",
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
    },
    "macd_buy_daily": {
        "no": 13, "slug": "mk-macd-buy-call-daily",
        "type": "BULL", "weight": 2.5, "layer": "Volume", "source": "Chartink",
        "desc": "MACD buy on daily chart. Swing trade momentum entry.",
        "pairs_with": ["swing_low", "upswing", "breakout_200dma"],
        "status": "ACTIVE",
    },
    "buy_morning_9_30": {
        "no": 14, "slug": "copy-buy-100-accuracy-morning-scanner-scan-at-9-30-20985",
        "type": "BULL", "weight": 2.5, "layer": "Volume", "source": "Chartink",
        "desc": "High-accuracy morning buy scanner. Multi-condition entry for 9:30 AM.",
        "pairs_with": ["gap_up", "volume_spike", "macd_buy_hourly", "ema_crossover_bn"],
        "status": "ACTIVE",
    },

    # ── LAYER 3 — BREAKOUT & BREAKDOWN (6 scanners) ─────────

    "breakout_50day": {
        "no": 15, "slug": "copy-todays-close-surpassing-the-50-days-high-range-179",
        "type": "BULL", "weight": 2.0, "layer": "Breakout", "source": "Chartink",
        "desc": "Breaks above 50-day high. Bullish continuation pattern trigger.",
        "pairs_with": ["volume_spike", "volume_avg", "breakout_200dma"],
        "status": "ACTIVE",
    },
    "breakout_200dma": {
        "no": 16, "slug": "copy-surpassing-the-high-with-regime-filter-of-200-dma-and-green-candle-only-181",
        "type": "BULL", "weight": 3.0, "layer": "Breakout", "source": "Chartink",
        "desc": "Breakout + 200 DMA regime filter + green candle. Highest quality breakout scanner.",
        "pairs_with": ["volume_spike", "volume_avg", "upswing", "bandwalk_highs"],
        "status": "ACTIVE",
    },
    "breakdown_20day": {
        "no": 17, "slug": "copy-todays-low-surpassing-the-20-day-low-range-181",
        "type": "BEAR", "weight": 2.0, "layer": "Breakout", "source": "Chartink",
        "desc": "Breaks below 20-day low. Bearish continuation pattern trigger.",
        "pairs_with": ["downswing", "bearish_divergence", "macd_sell_weekly"],
        "status": "ACTIVE",
    },
    "52week_high": {
        "no": 18, "slug": "mk-52-week-high-breakout",
        "type": "BULL", "weight": 3.0, "layer": "Breakout", "source": "Chartink",
        "desc": "52-week high breakout. Strongest momentum — no overhead resistance.",
        "pairs_with": ["volume_spike", "richie_rich_breakout", "breakout_200dma"],
        "status": "ACTIVE",
    },
    "richie_rich_breakout": {
        "no": 19, "slug": "copy-ffa-richie-rich-breakout-system-2204",
        "type": "BULL", "weight": 3.0, "layer": "Breakout", "source": "Chartink",
        "desc": "FFA Richie Rich Breakout System. Multi-condition: price + volume + momentum + trend.",
        "pairs_with": ["volume_spike", "breakout_200dma", "bandwalk_highs", "richie_rich_tracker"],
        "status": "ACTIVE",
    },
    "richie_rich_tracker": {
        "no": 20, "slug": "rich-rich-breakout-tracker-3",
        "type": "BULL", "weight": 2.5, "layer": "Breakout", "source": "Chartink",
        "desc": "Richie Rich Tracker. Follows stocks that broke out and are continuing.",
        "pairs_with": ["richie_rich_breakout", "upswing", "bandwalk_highs"],
        "status": "ACTIVE",
    },

    # ── LAYER 4 — RSI DIVERGENCE LADDER (6 scanners) ────────

    "bullish_divergence": {
        "no": 21, "slug": "copy-bullish-divergence-occurring-today-205",
        "type": "BULL", "weight": 2.5, "layer": "RSI", "source": "Chartink",
        "desc": "STAGE 1 BULL: Bullish RSI divergence — price lower low + RSI higher low.",
        "pairs_with": ["failure_swing_bullish", "swing_low", "llbb_bounce"],
        "status": "ACTIVE",
    },
    "bearish_divergence": {
        "no": 22, "slug": "copy-bearish-divergence-occurring-today-189",
        "type": "BEAR", "weight": 2.5, "layer": "RSI", "source": "Chartink",
        "desc": "STAGE 1 BEAR: Bearish RSI divergence — price higher high + RSI lower high.",
        "pairs_with": ["failure_swing_bearish", "swing_high", "macd_sell_weekly"],
        "status": "ACTIVE",
    },
    "failure_swing_bullish": {
        "no": 23, "slug": "copy-failure-swing-bullish-divergence-occurring-today-185",
        "type": "BULL", "weight": 2.5, "layer": "RSI", "source": "Chartink",
        "desc": "STAGE 2 BULL: RSI failure swing confirmation.",
        "pairs_with": ["bullish_divergence", "swing_low", "upswing", "llbb_bounce"],
        "status": "ACTIVE",
    },
    "failure_swing_bearish": {
        "no": 24, "slug": "copy-failure-swing-bearish-divergence-occurring-today-177",
        "type": "BEAR", "weight": 2.5, "layer": "RSI", "source": "Chartink",
        "desc": "STAGE 2 BEAR: RSI failure swing confirmation.",
        "pairs_with": ["bearish_divergence", "swing_high", "downswing", "macd_sell_weekly"],
        "status": "ACTIVE",
    },
    "rsi_above_30": {
        "no": 25, "slug": "copy-rsi-crossed-above-30-zones-188",
        "type": "BULL", "weight": 2.0, "layer": "RSI", "source": "Chartink",
        "desc": "STAGE 3 BULL: RSI crosses above 30. Momentum confirmed after divergence.",
        "pairs_with": ["swing_low", "llbb_bounce", "failure_swing_bullish"],
        "status": "ACTIVE",
    },
    "rsi_below_70": {
        "no": 26, "slug": "copy-rsi-crossed-below-70-zones-180",
        "type": "BEAR", "weight": 2.0, "layer": "RSI", "source": "Chartink",
        "desc": "STAGE 3 BEAR: RSI crosses below 70. Momentum confirmed after divergence.",
        "pairs_with": ["swing_high", "failure_swing_bearish", "bearish_divergence"],
        "status": "ACTIVE",
    },

    # ── LAYER 5 — GAP & INTRADAY EMA (4 scanners) ───────────

    "gap_up": {
        "no": 27, "slug": "copy-gap-up-daily-199",
        "type": "BULL", "weight": 1.5, "layer": "Gap", "source": "Chartink",
        "desc": "Personal gap up. Opens above yesterday's high.",
        "pairs_with": ["upswing", "macd_buy_hourly", "buy_morning_9_30"],
        "status": "ACTIVE",
    },
    "gap_down": {
        "no": 28, "slug": "copy-gap-down-daily-171",
        "type": "BEAR", "weight": 1.5, "layer": "Gap", "source": "Chartink",
        "desc": "Personal gap down. Opens below yesterday's low.",
        "pairs_with": ["downswing", "bearish_divergence"],
        "status": "ACTIVE",
    },
    "ema_crossover_bn": {
        "no": 29, "slug": "copy-5-and-10-crossover-hourly-196",
        "type": "BULL", "weight": 1.5, "layer": "Gap", "source": "Chartink",
        "desc": "BankNifty 5/10 EMA crossover hourly. F&O intraday trigger.",
        "pairs_with": ["macd_buy_hourly", "buy_morning_9_30", "gap_up"],
        "status": "ACTIVE",
    },
    "ema_crossover_nifty": {
        "no": 30, "slug": "mk-nifty-5-10-ema-crossover-hourly",
        "type": "BULL", "weight": 1.5, "layer": "Gap", "source": "Chartink",
        "desc": "Nifty 50 5/10 EMA crossover hourly. F&O trigger for Nifty.",
        "pairs_with": ["ema_crossover_bn", "macd_buy_hourly", "buy_morning_9_30"],
        "status": "ACTIVE",
    },

    # ── LAYER 6 — MA SUPPORT ZONES (5 scanners) ─────────────

    "near_100ma": {
        "no": 31, "slug": "copy-moving-average-100-goldmine-futures-170",
        "type": "BULL", "weight": 1.5, "layer": "MA", "source": "Chartink",
        "desc": "Near 100-day MA. Medium-term support zone.",
        "pairs_with": ["swing_low", "rsi_above_30", "llbb_bounce"],
        "status": "ACTIVE",
    },
    "near_200ma": {
        "no": 32, "slug": "copy-moving-average-200-goldmine-futures-172",
        "type": "BULL", "weight": 2.0, "layer": "MA", "source": "Chartink",
        "desc": "Near 200-day MA v1. Long-term support zone.",
        "pairs_with": ["swing_low", "near_200ma_v2", "llbb_bounce"],
        "status": "ACTIVE",
    },
    "near_200ma_v2": {
        "no": 33, "slug": "copy-moving-average-200-goldmine-futures-304",
        "type": "BULL", "weight": 2.0, "layer": "MA", "source": "Chartink",
        "desc": "Near 200-day MA v2 (newer). Double institutional support confirm.",
        "pairs_with": ["near_200ma", "swing_low", "llbb_bounce"],
        "status": "ACTIVE",
    },
    "muthukumaran_a": {
        "no": 34, "slug": "muthukumaran-3",
        "type": "BULL", "weight": 2.0, "layer": "RSI", "source": "Chartink",
        "desc": "RSI recovery + upswing: Close>prev, HH, HL, RSI(14) crossed above 30.",
        "pairs_with": ["swing_low", "rsi_above_30", "failure_swing_bullish"],
        "status": "ACTIVE",
    },
    "muthukumaran_b": {
        "no": 35, "slug": "muthukumaran-2",
        "type": "BULL", "weight": 2.0, "layer": "Trend", "source": "Chartink",
        "desc": "Parabolic SAR buy: Close > SAR(0.02, 0.02, 0.2). Trend-following confirmation.",
        "pairs_with": ["supertrend_buy", "upswing", "breakout_200dma"],
        "status": "ACTIVE",
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
}

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
}


# ── MWA SCANNER CLASS ────────────────────────────────────────

class MWAScanner:
    """Full 52-scanner MWA breadth scanner with Chartink + Python + SMC integration."""

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

    def login(self) -> bool:
        """Login to Chartink with credentials from environment."""
        email = os.environ.get("CHARTINK_EMAIL", "")
        password = os.environ.get("CHARTINK_PASSWORD", "")
        if not email:
            logger.warning("Set CHARTINK_EMAIL + CHARTINK_PASSWORD in .env")
            return False
        page = self.session.get(f"{self.BASE}/login")
        csrf = re.search(r'meta name="csrf-token" content="([^"]+)"', page.text)
        if not csrf:
            return False
        r = self.session.post(
            f"{self.BASE}/login",
            headers={"X-CSRF-Token": csrf.group(1), "Referer": f"{self.BASE}/login"},
            data={"_token": csrf.group(1), "email": email, "password": password},
            allow_redirects=True,
        )
        self.logged_in = "logout" in r.text.lower()
        if self.logged_in:
            logger.info("Chartink login successful")
        else:
            logger.error("Chartink login failed")
        return self.logged_in

    def fetch_chartink(self, slug: str) -> list[str]:
        """Fetch stock list from a Chartink screener by slug."""
        try:
            page = self.session.get(f"{self.BASE}/screener/{slug}", timeout=15)
            csrf = re.search(r'meta name="csrf-token" content="([^"]+)"', page.text)
            if not csrf:
                logger.warning("Chartink: no CSRF token for %s", slug)
                return []

            # Extract scan_clause from the screener page JS
            scan_clause = ""
            sc_match = re.search(r'"scan_clause"\s*:\s*"(.*?)"', page.text)
            if sc_match:
                scan_clause = sc_match.group(1).replace("\\n", "\n").replace('\\"', '"')
            else:
                # Alternative: look for scan_clause in textarea or hidden input
                sc_match2 = re.search(
                    r'id="scan_clause"[^>]*>([^<]+)<|'
                    r'name="scan_clause"[^>]*value="([^"]*)"',
                    page.text,
                )
                if sc_match2:
                    scan_clause = (sc_match2.group(1) or sc_match2.group(2) or "").strip()

            if not scan_clause:
                logger.warning("Chartink: no scan_clause found for %s", slug)
                return []

            r = self.session.post(
                self.PROCESS_URL,
                timeout=15,
                headers={
                    "X-CSRF-Token": csrf.group(1),
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": f"{self.BASE}/screener/{slug}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"scan_clause": scan_clause},
            )
            stocks = [
                i.get("nsecode", i.get("symbol", ""))
                for i in r.json().get("data", [])
            ]
            return [s for s in stocks if s]
        except Exception as e:
            logger.error("Chartink fetch failed for %s: %s", slug, e)
            return []

    def run_python_scanners(self, stock_data: dict | None = None) -> dict[str, list[str]]:
        """Run Python-based scanners that replace/supplement Chartink."""
        results: dict[str, list[str]] = {}
        try:
            from mcp_server.technical_scanners import scan_supertrend
            if stock_data:
                st_result = scan_supertrend(stock_data)
                results["supertrend_buy"] = st_result.get("stocks", [])
            else:
                results["supertrend_buy"] = []
        except ImportError:
            logger.warning("technical_scanners.scan_supertrend not available")
            results["supertrend_buy"] = []

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
                }
                for key, scanner_fn in smc_scanners.items():
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

    def run_all(self, stock_data: dict | None = None, save: bool = True) -> dict[str, list[str]]:
        """
        Run all 40 scanners (Chartink + Python) and return results.

        Args:
            stock_data: Dict of {ticker: DataFrame} for Python scanners
            save: Whether to save results to JSON file
        """
        if not self.logged_in:
            self.login()

        results: dict[str, list[str]] = {}
        skip_types = {"FILTER", "UNKNOWN"}
        layers = ["Trend", "Volume", "Breakout", "RSI", "Gap", "MA"]

        logger.info("MWA Scan started at %s", datetime.now().strftime("%d %b %Y %H:%M"))

        # Chartink scanners by layer
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
            logger.info("Scanning layer: %s (%d scanners)", layer, len(items))
            for key, cfg in items.items():
                try:
                    stocks = self.fetch_chartink(cfg["slug"])
                    results[key] = stocks
                    logger.info(
                        "[%s] %s: %d stocks", cfg["type"], key, len(stocks)
                    )
                    time.sleep(self.delay)
                except Exception as e:
                    results[key] = []
                    logger.error("Scanner %s failed: %s", key, e)

        # Python scanners
        logger.info("Running Python scanners...")
        py_results = self.run_python_scanners(stock_data)
        for key, stocks in py_results.items():
            results[key] = [s.replace("NSE:", "") for s in stocks]
            logger.info("[PYTHON] %s: %d stocks", key, len(results[key]))

        if save:
            try:
                data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
                os.makedirs(data_dir, exist_ok=True)
                with open(os.path.join(data_dir, "mwa_results.json"), "w") as f:
                    json.dump(
                        {
                            "timestamp": datetime.now().isoformat(),
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
