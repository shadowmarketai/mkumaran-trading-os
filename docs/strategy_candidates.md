# Strategy Candidates — Validated Edge, Not Yet Deployed

Strategies that passed pre-committed validation criteria at Tier 2 (marginal),
or produced encouraging signals before hitting a sample-size or structural limit.

Not dead. Not deployed. Parked with honest accounting of where they stand.

---

## 1. Nifty Weekly Short Strangle

**Status:** Tier 2 — Marginal validation
**Validated:** 2026-05-07
**Criteria doc:** `docs/strategy_validation/nifty_weekly_strangle_criteria.md`
**Validation script:** `scripts/validate_nifty_weekly_strangle.py`

### Results (net of all costs)

| Metric | Value |
|---|---|
| Trade count | 55 (3.4 years) |
| Win rate | 78.2% |
| WF return (OOS) | 16.4% |
| WF Sharpe (chronological OOS) | 0.556 |
| WF consistency | 75% (3/4 windows positive) |
| MC P95 max drawdown | 28.7% |

### Why parked and not deployed

- WF Sharpe (0.556) and WF return (16.4%) are below Tier 1 thresholds (1.0 / 20%)
- Binding constraint: VIX gate selects only 42% of weeks → 55 trades over 3+ years
- 4 OOS windows is statistically thin — one breakeven window (-₹26 total) drags
  the chronological Sharpe below 1.0
- No exit parameter flaw identified; iteration declined as parameter fishing

### Conditions for promotion

- Combined with a complementary Tier 2+ strategy improving portfolio-level Sharpe
- Successful OOS confirmation on a different time period (e.g., 2019–2022)
- Monthly Nifty OVERRIDE resolved (bhavcopy backfill to 2021) → if monthly validates
  at Tier 1, deploy as combined weekly+monthly book

### What not to do

- Do not deploy as standalone strategy at current confidence level
- Do not iterate on exit parameters without a new structural hypothesis
- Do not combine with BankNifty results to inflate a composite metric

---

## 2. BankNifty Weekly Short Strangle

**Status:** OVERRIDE — Positive signals, sample size insufficient
**Validated:** 2026-04-29
**Criteria doc:** `docs/strategy_validation/banknifty_strangle_criteria.md`

### Results

| Metric | Value |
|---|---|
| Trade count | 36 (Jan 2023 – Nov 2024, discontinued) |
| Win rate | 80.6% |
| WF return (OOS) | 13.9% |
| WF Sharpe | 1.15 |
| MC P95 max drawdown | 7.5% |
| VIX gate delta | 19.5pp (confirmed load-bearing) |

### Why parked

- BankNifty weekly discontinued November 2024 (NSE expiry consolidation)
- 36 trades < 50 minimum threshold → OVERRIDE, not Tier 1
- Cannot collect more data; instrument no longer exists

### Notes

- VIX gate proven load-bearing (19.5pp delta between gated and ungated returns)
- This result is the structural basis for the VIX gate in all subsequent option
  selling tests
- Cannot be revisited; instrument discontinued

---

## 3. Nifty Monthly Short Strangle

**Status:** OVERRIDE — Sample-size-limited. Inconclusive, not failed.
**Validated:** 2026-05-08
**Criteria doc:** `docs/strategy_validation/nifty_monthly_strangle_criteria.md`
**Validation script:** `scripts/validate_nifty_monthly_strangle.py`

### Results (net of all costs, 13 trades — below 30-trade minimum)

| Metric | Value | Note |
|---|---|---|
| Trade count | 13 (2023-01 → 2026-04) | OVERRIDE threshold: < 30 |
| Win rate | 84.6% | Suggestive, not conclusive |
| WF return (OOS) | 6.8% | Meaningless at n=13 |
| WF Sharpe (OOS) | 0.334 | CI: [-0.97, 15.71] — too wide |
| WF consistency | 83% (5/6 windows) | Would satisfy T1 if sample sufficient |
| MC P95 max drawdown | 25.0% | Would satisfy T1 (<30%) if sample sufficient |

### Why OVERRIDE and not a tier verdict

- 41 monthly expiries in window; VIX gate rejected 27 (66%) — most selective gate seen
- 13 live trades < 30 minimum → OVERRIDE, not failed
- Extended to 2021-01-01 (permitted): still 13 trades — options chain DB only covers
  2023 onwards; no pre-2023 backfill available

### Why not failed

- OVERRIDE ≠ TIER 3 or TIER 4. The Nifty options-selling arc is not exhausted.
- Observable signals on 13 trades are directionally consistent with the weekly result
- Binding constraint is data availability + VIX gate selectivity, not strategy edge

### Conditions for a future test

- Both OVERRIDE-permitted actions are exhausted. This test is closed.
- Any future test on Nifty monthly (e.g., with 2021-2026 data if backfill becomes
  available) requires a new pre-committed criteria document before any data is run.
- The OVERRIDE extension clause was a one-time action within these criteria, not
  standing permission for future reruns under this document.

### What not to do

- Do not loosen the VIX gate to increase trade count
- Do not change delta target to generate more trades
- Do not treat OVERRIDE as equivalent to a negative tier result

---

*Last updated: 2026-05-08*
