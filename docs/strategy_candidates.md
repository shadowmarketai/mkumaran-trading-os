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
- Monthly Nifty test validates at Tier 1 → deploy as combined weekly+monthly book

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

*Last updated: 2026-05-07*
