# Options Greeks & Payoff Calculator — User Guide

Complete step-by-step guide for using MKUMARAN Trading OS Options Greeks (Black-Scholes) and Multi-Leg Payoff calculator.

**Base URL**: `https://money.shadowmarket.ai`
**Auth**: All `/api/options/*` endpoints require login token. `/api/fno/*` are public.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Greeks Calculator (single option)](#1-greeks-calculator-single-option)
3. [Option Chain with Greeks (all strikes)](#2-option-chain-with-greeks-all-strikes)
4. [Implied Volatility from Market Price](#3-implied-volatility-from-market-price)
5. [IV Rank & Volatility Setup](#4-iv-rank--volatility-setup)
6. [Multi-Leg Payoff Calculator](#5-multi-leg-payoff-calculator)
7. [Strategy Recipes](#6-strategy-recipes)
8. [Worked Example: NIFTY Iron Condor](#7-worked-example-nifty-iron-condor)
9. [Glossary](#glossary)

---

## Quick Start

You need 4 numbers to compute Greeks:

| Input | What it is | Example |
|-------|-----------|---------|
| **spot** | Current underlying price | `22500` (NIFTY spot) |
| **strike** | Option strike price | `22500` (ATM) |
| **expiry_days** | Calendar days to expiry | `7` (weekly) |
| **volatility** | Annualised IV (decimal) | `0.15` = 15% |

Optional:
- `rate` = risk-free rate (default `0.065` = 6.5%)
- `option_type` = `CE` (call) or `PE` (put)

---

## 1. Greeks Calculator (single option)

### Endpoint
```
POST /api/options/greeks
```

### Request Body
```json
{
  "spot": 22500,
  "strike": 22500,
  "expiry_days": 7,
  "rate": 0.065,
  "volatility": 0.15,
  "option_type": "CE"
}
```

### Response
```json
{
  "status": "ok",
  "price": 112.45,
  "delta": 0.5446,
  "gamma": 0.001500,
  "theta": -9.65,
  "vega": 12.35,
  "rho": 2.33,
  "iv": 0.0
}
```

### How to read each Greek

| Greek | Meaning | Trading use |
|-------|---------|-------------|
| **price** | Black-Scholes fair value | Compare with market LTP — buy if undervalued |
| **delta** | ₹ change in premium per ₹1 spot move | Call: 0→1, Put: -1→0. ATM ≈ ±0.5 |
| **gamma** | Change in delta per ₹1 spot move | Highest at ATM. High gamma = unstable hedge |
| **theta** | ₹ premium decay per day | Always negative for buyers, positive for sellers |
| **vega** | ₹ change in premium per 1% IV move | Long options gain when IV rises |
| **rho** | ₹ change per 1% interest-rate move | Usually negligible for short-DTE |

### Step-by-step usage

1. Get current spot from your terminal (e.g. NIFTY = 22500)
2. Pick the strike you want to analyse (ATM, ±100, ±200, …)
3. Count days to expiry (weekly = 0–7, monthly = 8–30)
4. Estimate IV — either use `/api/fno/iv_rank/{symbol}` or assume 12–18% for indices
5. POST the JSON body — get back all 6 Greeks

### cURL example
```bash
curl -X POST https://money.shadowmarket.ai/api/options/greeks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "spot": 22500,
    "strike": 22500,
    "expiry_days": 7,
    "volatility": 0.12,
    "option_type": "CE"
  }'
```

---

## 2. Option Chain with Greeks (all strikes)

When you want Greeks for **every strike** in one call (build an option chain UI):

### Endpoint
```
GET /api/options/chain?spot=22500&expiry_days=7&strike_step=50
```

### Query parameters

| Param | Default | Description |
|-------|---------|-------------|
| `spot` | required | Current underlying price |
| `expiry_days` | `30` | Days to expiry |
| `strike_start` | `spot * 0.90` | Lower strike bound |
| `strike_end` | `spot * 1.10` | Upper strike bound |
| `strike_step` | `50` | Strike spacing (NIFTY=50, BANKNIFTY=100) |
| `rate` | `0.065` | Risk-free rate |

### Response
```json
{
  "status": "ok",
  "spot": 22500,
  "expiry_days": 7,
  "atm_strike": 22500,
  "strikes_count": 41,
  "chain": [
    {
      "strike": 22250,
      "ce": { "price": 285.10, "delta": 0.78, "gamma": 0.0012, "theta": -8.20, "vega": 9.40, "rho": 1.85 },
      "pe": { "price": 35.40, "delta": -0.22, "gamma": 0.0012, "theta": -8.20, "vega": 9.40, "rho": -0.45 }
    },
    ...
  ]
}
```

### When to use
- Building an option-chain dashboard
- Spotting where gamma peaks
- Finding the strike with highest vega for IV plays

---

## 3. Implied Volatility from Market Price

If you know the **market price** of an option and want the IV the market is pricing in:

### Endpoint (no auth — pure math)
```
GET /api/fno/option_greeks?symbol=NIFTY&strike=22500&expiry_days=7&market_price=120&spot=22500&option_type=CE
```

### Response
```json
{
  "symbol": "NIFTY",
  "strike": 22500,
  "expiry_days": 7,
  "spot": 22500,
  "market_price": 120,
  "option_type": "CE",
  "iv_pct": 8.48,
  "delta": 0.5446,
  "gamma": 0.001500,
  "theta": -9.65,
  "vega": 12.35,
  "rho": 2.33,
  "fair_price": 120.00
}
```

### How it works
- Newton-Raphson IV solver finds the volatility that makes BS price = market price
- Falls back to bisection if Newton-Raphson doesn't converge
- Then computes all 6 Greeks at that IV

### Use cases
- "What IV is the market pricing for tomorrow's expiry?"
- Hunting overpriced options to **sell**, underpriced to **buy**
- Pre-event positioning (RBI policy, FOMC, earnings)

---

## 4. IV Rank & Volatility Setup

### Get current IV rank for a symbol
```
GET /api/fno/iv_rank/NIFTY
```

Response:
```json
{
  "symbol": "NIFTY",
  "current_iv_pct": 12.4,
  "iv_rank": 35,
  "iv_percentile": 42,
  "samples": 60,
  "lookback_days": 60,
  "bias": "NEUTRAL"
}
```

| `iv_rank` | What it means | Strategy |
|-----------|--------------|----------|
| 0–20 | IV is at the lowest 20% of last 60 days | **Buy straddle/strangle** (vol expansion play) |
| 20–80 | Normal range | Direction trades, theta selling at edges |
| 80–100 | IV is at the highest 20% of last 60 days | **Sell straddle / iron condor** (vol crush play) |

### Auto-suggest a setup
```
GET /api/fno/volatility_setup/NIFTY
```

Returns:
```json
{
  "symbol": "NIFTY",
  "iv_rank": 18,
  "current_iv_pct": 11.2,
  "setup": "LONG_STRADDLE",
  "rationale": "IV at 18 percentile — vol expansion likely",
  "suggested_strikes": { "atm": 22500 }
}
```

The system suggests:
- **LONG_STRADDLE** when IV rank < 20 (cheap vol)
- **SHORT_STRADDLE** when IV rank > 80 (expensive vol)
- **DIRECTIONAL** otherwise

---

## 5. Multi-Leg Payoff Calculator

Calculate combined P&L curve for any options strategy (1–10 legs).

### Endpoint
```
POST /api/options/payoff
```

### Request structure
```json
{
  "legs": [
    { "strike": 22500, "premium": 120, "qty": 50, "option_type": "CE", "action": "BUY" },
    { "strike": 22700, "premium":  60, "qty": 50, "option_type": "CE", "action": "SELL" }
  ],
  "spot_min": 0,
  "spot_max": 0,
  "num_points": 200
}
```

### Field reference

| Field | Type | Description |
|-------|------|-------------|
| `legs[].strike` | float | Option strike |
| `legs[].premium` | float | Per-share premium (LTP) |
| `legs[].qty` | int | Lot size × number of lots (NIFTY lot = 50) |
| `legs[].option_type` | string | `CE` or `PE` |
| `legs[].action` | string | `BUY` or `SELL` |
| `spot_min` | float | Lower bound of payoff curve (auto if 0) |
| `spot_max` | float | Upper bound (auto if 0) |
| `num_points` | int | Resolution of curve (default 200) |

### Response
```json
{
  "status": "ok",
  "points": [
    { "spot": 22300, "pnl": -3000 },
    { "spot": 22400, "pnl": -3000 },
    { "spot": 22500, "pnl": -3000 },
    { "spot": 22560, "pnl":     0 },
    { "spot": 22700, "pnl":  7000 },
    { "spot": 22800, "pnl":  7000 }
  ],
  "breakevens": [22560.00],
  "max_profit": 7000,
  "max_loss": -3000,
  "net_premium": -3000
}
```

### How to read it

- **breakevens** — spot prices where P&L crosses zero
- **max_profit** — best case (capped for spreads, infinite for naked longs)
- **max_loss** — worst case (capped for spreads, infinite for naked shorts)
- **net_premium** — net debit (negative) or credit (positive) at entry
- **points** — list of `{spot, pnl}` for plotting the curve

### Step-by-step

1. Build your `legs` array — one entry per option you want in the strategy
2. Each leg = `{strike, premium, qty, option_type, action}`
3. POST it
4. Plot `points` on a chart with spot on X-axis, pnl on Y-axis
5. Mark `breakevens` as vertical lines, `max_profit` and `max_loss` as horizontal lines

---

## 6. Strategy Recipes

The 6 most common strategies and how to encode them as `legs`.

### A. Long Call (bullish, unlimited upside)
```json
[{ "strike": 22500, "premium": 120, "qty": 50, "option_type": "CE", "action": "BUY" }]
```

### B. Long Put (bearish)
```json
[{ "strike": 22500, "premium": 100, "qty": 50, "option_type": "PE", "action": "BUY" }]
```

### C. Bull Call Spread (capped bullish, lower cost)
```json
[
  { "strike": 22500, "premium": 120, "qty": 50, "option_type": "CE", "action": "BUY"  },
  { "strike": 22700, "premium":  60, "qty": 50, "option_type": "CE", "action": "SELL" }
]
```
Max loss = net debit (₹3 000), max profit = (200 − 60) × 50 = ₹7 000.

### D. Bear Put Spread (capped bearish)
```json
[
  { "strike": 22500, "premium": 100, "qty": 50, "option_type": "PE", "action": "BUY"  },
  { "strike": 22300, "premium":  40, "qty": 50, "option_type": "PE", "action": "SELL" }
]
```

### E. Long Straddle (volatility expansion, direction-agnostic)
```json
[
  { "strike": 22500, "premium": 120, "qty": 50, "option_type": "CE", "action": "BUY" },
  { "strike": 22500, "premium": 100, "qty": 50, "option_type": "PE", "action": "BUY" }
]
```
Use when IV rank < 20.

### F. Iron Condor (range-bound, volatility crush)
```json
[
  { "strike": 22200, "premium":  20, "qty": 50, "option_type": "PE", "action": "BUY"  },
  { "strike": 22400, "premium":  60, "qty": 50, "option_type": "PE", "action": "SELL" },
  { "strike": 22600, "premium":  60, "qty": 50, "option_type": "CE", "action": "SELL" },
  { "strike": 22800, "premium":  20, "qty": 50, "option_type": "CE", "action": "BUY"  }
]
```
Use when IV rank > 80 and spot expected to stay in 22 400–22 600 range.

---

## 7. Worked Example: NIFTY Iron Condor

**Setup**: NIFTY at 22 500, 7 DTE, IV rank = 85 (expensive vol). You expect NIFTY to stay in 22 400–22 600 until expiry.

### Step 1 — Check IV rank
```bash
curl https://money.shadowmarket.ai/api/fno/iv_rank/NIFTY
```
→ `iv_rank: 85` ✓ (vol crush setup confirmed)

### Step 2 — Get suggested setup
```bash
curl https://money.shadowmarket.ai/api/fno/volatility_setup/NIFTY
```
→ `setup: SHORT_STRADDLE`. Iron condor is the same idea but with risk-defined wings.

### Step 3 — Get current option premiums (use chain endpoint or your terminal)
```bash
curl "https://money.shadowmarket.ai/api/options/chain?spot=22500&expiry_days=7&strike_step=100"
```

### Step 4 — Build the iron condor
```bash
curl -X POST https://money.shadowmarket.ai/api/options/payoff \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "legs": [
      { "strike": 22200, "premium":  20, "qty": 50, "option_type": "PE", "action": "BUY"  },
      { "strike": 22400, "premium":  60, "qty": 50, "option_type": "PE", "action": "SELL" },
      { "strike": 22600, "premium":  60, "qty": 50, "option_type": "CE", "action": "SELL" },
      { "strike": 22800, "premium":  20, "qty": 50, "option_type": "CE", "action": "BUY"  }
    ]
  }'
```

### Step 5 — Read the response
```json
{
  "max_profit": 4000,
  "max_loss": -6000,
  "breakevens": [22320, 22680],
  "net_premium": 4000
}
```

**Interpretation**:
- You collect ₹4 000 net credit upfront
- If NIFTY stays between 22 320 and 22 680 at expiry → keep the full ₹4 000
- If NIFTY ends below 22 200 or above 22 800 → max loss ₹6 000
- Risk:reward = 6 000 : 4 000 = 1.5 : 1

### Step 6 — Monitor with Greeks
After entry, check the **net delta** of your position daily:
```bash
# For each leg, call /api/options/greeks and sum delta * qty * sign(action)
```
If net delta drifts > ±50, consider adjusting (rolling a leg).

---

## Glossary

| Term | Definition |
|------|-----------|
| **ATM** | At-the-money — strike closest to spot |
| **ITM** | In-the-money — call: strike < spot, put: strike > spot |
| **OTM** | Out-of-the-money — call: strike > spot, put: strike < spot |
| **DTE** | Days to expiry |
| **IV** | Implied volatility — market's expectation of future move |
| **IV rank** | Where current IV sits in the 60-day range (0=lowest, 100=highest) |
| **IV percentile** | % of past 60 days where IV was ≤ current IV |
| **Breakeven** | Spot price at which P&L = 0 |
| **Max profit** | Best-case P&L of the strategy |
| **Max loss** | Worst-case P&L of the strategy |
| **Net premium** | Total premium paid (debit, negative) or received (credit, positive) |
| **Lot size** | Minimum tradeable quantity (NIFTY=50, BANKNIFTY=15, FINNIFTY=40) |

---

## Endpoint Cheat Sheet

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/api/options/greeks` | POST | yes | Greeks for one option (you supply IV) |
| `/api/options/chain` | GET | yes | Greeks for all strikes |
| `/api/options/payoff` | POST | yes | Multi-leg P&L curve |
| `/api/fno/option_greeks` | GET | no | IV solver + Greeks (you supply market price) |
| `/api/fno/iv_rank/{symbol}` | GET | no | Current IV rank/percentile |
| `/api/fno/volatility_setup/{symbol}` | GET | no | Auto-suggest long/short straddle |
| `/api/fno/snapshot/{symbol}` | GET | no | OI + chain + IV + buildup combined |
| `/api/fno/expiry/{symbol}` | GET | no | Is today an expiry day? |
| `/api/fno/oi_buildup` | GET | no | OI buildup scan across F&O universe |
| `/tools/scan_oi_buildup` | POST | no | Same scan, n8n compatible |

---

## Notes & Constants

- **Risk-free rate**: defaults to 6.5% (RBI repo rate proxy)
- **Pricing model**: Black-Scholes-Merton (European exercise — fine for index options)
- **Normal CDF**: Abramowitz & Stegun approximation (5-decimal accuracy, no scipy)
- **IV solver**: Newton-Raphson with bisection fallback (5-decimal IV precision)
- **Theta** is reported per **calendar day** (already divided by 365)
- **Vega** is per **1% IV move** (already divided by 100)
- **Rho** is per **1% rate move** (already divided by 100)
- All Greeks rounded: delta=4dp, gamma=6dp, theta/vega/rho=2dp, price=2dp
