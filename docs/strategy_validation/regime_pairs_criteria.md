# Regime-Filtered Pairs Trading — Pre-committed Decision Criteria

**Date set:** 2026-05-12
**Committed before any validation run:** Yes
**Prior attempts:** `pairs_trading_criteria.md` (OVERRIDE) + `screener_pairs_criteria.md` (OVERRIDE)

---

## Why this attempt exists

Both prior runs OVERRODE. Root cause analysis:
- Sector pairs failed: no statistical cointegration (8/10 pairs p > 0.05)
- Screener pairs failed: full-period cointegration held but 2021-2026 was a persistent bull
  trend — rolling 12-month windows showed 0-2/17 passing cointegration. Spread kept trending
  instead of reverting. z=2.0 was NOT the problem.

User insight: "The spread kept trending instead of reverting — why not fix that?"

**This attempt adds a regime filter** that only allows entries when:
1. The recent 60-day window is cointegrated (rolling coint check)
2. The broader market (Nifty 50) is NOT in a strong directional trend

If this attempt OVERRIDES: **pairs trading chapter is permanently closed.** No further iterations.

---

## Pairs under test

| Pair | Full-period coint p | Source |
|---|---|---|
| RELIANCE / IOC | 0.0015 | Screener (both oil refiners) |
| AXISBANK / COALINDIA | 0.0007 | Screener (strongest coint signal) |

Only 2 pairs tested (not 6) — this is a focused regime-filter proof-of-concept.

---

## Strategy Parameters (do not change after committing)

| Parameter | Value | Change vs prior |
|---|---|---|
| Cointegration test | Engle-Granger | Same |
| Z-score signal | OLS hedge ratio on train window | Same |
| Entry threshold | \|z\| > 1.5 | Relaxed from 2.0 |
| Exit threshold | \|z\| < 0.5 | Same |
| Stop threshold | \|z\| > 4.0 (skip 30 days) | Same |
| Walk-forward | 12m train / 3m test | Same |
| **Regime filter 1** | Rolling 60-day EG coint p < 0.10 at entry | NEW |
| **Regime filter 2** | Nifty 50 60-day directional move ≤ 15% | NEW |
| Costs | Same as prior criteria | Same |

### Regime filter detail

**Filter 1 — Rolling cointegration check (entry gate):**
At each potential entry signal (|z| > 1.5), compute Engle-Granger cointegration p-value
on the most recent 60 trading days of prices for both legs. Entry is only allowed when
p < 0.10 (cointegration holds in the recent window).

**Filter 2 — Nifty slope filter (entry gate):**
At each potential entry, compute the linear regression slope of Nifty 50 over the last
60 trading days. Normalize: |slope × 60 / current_price|. If this exceeds 0.15 (i.e.,
Nifty is trending more than 15% directionally over 60 days), block entry — pairs
mean-reversion doesn't work in trending markets.

Both filters must pass simultaneously for an entry to execute.

---

## Decision criteria

### Tier 1 — PROCEED: extend regime filter to all top-6 screener pairs

Per pair:
- WF Sharpe > 0.8
- Max drawdown < 20%
- Trade count ≥ 15 (lowered from 30 — regime filter legitimately reduces frequency)
- Win rate (profitable trades / total trades) > 55%

Universe verdict: **≥ 1 pair TIER 1**

### Tier 2 — PROCEED WITH CAUTION: paper trade 3 months

Per pair:
- WF Sharpe 0.4 – 0.8
- Max drawdown < 30%
- Trade count ≥ 10
- Win rate > 50%

Universe verdict: **≥ 1 pair TIER 2 AND 0 pairs TIER 1**

### OVERRIDE — HYPOTHESIS DISPROVEN (FINAL — PAIRS CHAPTER CLOSED)

Either pair:
- Trade count < 10, OR
- WF Sharpe < 0.4, OR
- Max drawdown > 30%

**No further pairs iterations permitted after this run under any framing.**
If both pairs OVERRIDE: close pairs chapter, proceed with momentum + RSI strategies.

---

## Permitted post-result change (Tier 2 only, one iteration)

If Tier 2: may extend from 2 pairs to all 6 screener pairs (same filter, same z=1.5).
No parameter changes to filters or thresholds.

---

_Criteria committed 2026-05-12, before any validation run._
