# 52-Week Breakout (Nifty 500) — Pre-committed Decision Criteria

**Date set:** 2026-05-12
**Committed before any validation run:** Yes

---

## Hypothesis

Nifty 500 stocks that break above their 52-week high (252-day high) for the first time
continue to trend higher over the next 1-3 months (momentum continuation). Buying
fresh 52-week breakouts and holding with a trailing stop generates positive alpha over
the Nifty 50, net of costs.

Rationale: 52-week highs are strong psychological resistance levels. When a stock
breaks above that level on meaningful volume, institutional buying is often confirmed.
This is the purest momentum signal — the stock just proved it can make new highs.

---

## Strategy Parameters

| Parameter | Value |
|---|---|
| Universe | Nifty 500 (data/nifty500.json) |
| Signal | Close > 252-day rolling high (first time in last 10 days) |
| Entry | Close of breakout day |
| Exit rule 1 | Trailing stop: close < 20-day rolling low |
| Exit rule 2 | Hard stop: -10% from entry |
| Exit rule 3 | Max hold: 63 trading days (~3 months) |
| Max concurrent | 10 positions |
| Position size | ₹1,00,000 per trade |
| Long-only | Yes |
| Period | 2021-01-01 → today |
| Benchmark | Nifty 50 (^NSEI, buy-and-hold) |

### Signal detail

"First time in last 10 days" prevents entering on the same breakout multiple days in a row.
A breakout is only counted on day T if:
  - close[T] > max(close[T-252 : T])  (new 52-week high)
  - close[T-1] ≤ max(close[T-252 : T-1])  (was NOT a 52-week high yesterday)

### Exit rule 1 — Trailing stop detail

At each daily close, check: is today's close < the lowest close of the last 20 trading days?
If yes, exit. This allows the stock to "breathe" while locking in gains on a sustained move.

---

## Cost Model

Same as other Nifty 500 strategies:
| Brokerage | ₹20 flat per order |
| STT | 0.1% on sell side |
| Exchange | 0.00345% per side |
| GST | 18% on brokerage + exchange |
| Stamp duty | 0.015% on buy side |
| Slippage | 0.05% per side |

---

## Decision Criteria

### Tier 1 — PROCEED: build live 52-week breakout scanner

- Total trades ≥ 50
- CAGR ≥ 15% net
- Sharpe ≥ 0.8
- Max drawdown ≤ 30%
- Win rate ≥ 50% (breakout strategies tend to have moderate win rates but large winners)

### Tier 2 — PROCEED WITH CAUTION: paper trade 3 months

- Total trades ≥ 30
- CAGR ≥ 8%
- Sharpe ≥ 0.5
- Max drawdown ≤ 40%
- Win rate ≥ 40%

### OVERRIDE — HYPOTHESIS DISPROVEN

- Trades < 30, OR CAGR < 8%, OR Sharpe < 0.5, OR Max drawdown > 40%

---

_Criteria committed 2026-05-12, before any validation run._
