# Weekly Timeframe Backtest — Pre-Committed Decision Criteria

**Date set:** 2026-05-08
**Author:** M. Kumaran
**Committed before any validation run:** Yes

---

## Hypothesis

Wyckoff and Confluence-2 applied to **weekly bars** (instead of daily bars) on the
PSU-excluded Nifty 100 universe will show meaningfully better results than the same
engines on daily bars, because:

1. Weekly bars average out intraday noise and short-term FII volatility
2. Each weekly signal represents a full 5-session structural conviction — higher RRR
3. Wyckoff accumulation/distribution patterns are classically described on weekly timeframes
4. Fewer but higher-quality signals → better signal-to-noise ratio

This is the secondary arc alongside the options/strangle primary arc.

---

## Why only Wyckoff and Confluence-2

From the PSU-excluded all-engines result (2026-05-08):
- Wyckoff: best individual engine (PF 0.70, +0.030 lift) — closest to viable
- Confluence-2: best overall (PF 0.68, +0.190 lift) — largest improvement from PSU exclusion
- SMC, VSA, Harmonic: TIER 3 on both full and PSU-excluded universe — not worth weekly test
- Confluence-3: insufficient signal mass (1.7 trades/ticker) — not viable on weekly either

Testing all engines on weekly would be redundant. Wyckoff and Confluence-2 are the
only candidates with evidence of underlying edge.

---

## Test parameters (locked)

| Parameter | Value |
|---|---|
| Universe | Nifty 100 minus PSU list (same 16-ticker exclusion from psu_excluded_wyckoff_criteria.md) |
| Engines | Wyckoff standalone + Confluence-2 (2+ engines: Wyckoff, VSA, SMC, Harmonic) |
| Bar interval | Weekly (5-day) — **only change vs PSU-excluded daily tests** |
| MWA filter | NOT applied — isolate timeframe change |
| Quality gate | NOT applied — raw engine output only |
| Position dedup | NOT applied — per-ticker isolation |
| Lookback | 3 years of weekly data (≈ 156 weekly bars, 2023-01-01 to 2026-04-30) |
| Cost model | Full Zerodha rate stack (same as all previous tests) |
| Slippage | 0.5% per side (weekly data — larger gap risk) |
| Capital | ₹1,00,000 per ticker |

**Note:** Slippage raised from 0.3% (daily) to 0.5% (weekly) to account for
larger bid-ask spread at weekly open entries. This is the only parameter difference.

---

## Decision criteria (per engine)

### Tier 1 — Weekly timeframe rescues the engine

| Metric | Threshold |
|---|---|
| Median PF | ≥ 1.2 |
| Profitable tickers (PF ≥ 1.0) | ≥ 40% of non-PSU universe |
| Total trades | ≥ 100 (fewer expected on weekly — lower threshold than daily) |
| Win rate | ≥ 35% |

**Decision for T1:** Run walk-forward on weekly bars before deployment.

### Tier 2 — Weekly helps but insufficient

| Metric | Threshold |
|---|---|
| Median PF | 0.8–1.2 |
| Profitable tickers | 25–40% |

**Decision for T2:** Apply MWA filter on weekly bars with new criteria doc.

### Tier 3 — Weekly timeframe does not rescue

| Metric | Threshold |
|---|---|
| Median PF | < 0.8 |
| OR profitable tickers | < 25% |

**Decision for T3:** Engine is not viable on NSE data at any standard timeframe
(daily or weekly). Document. Consider OI-based or fundamentals-driven approaches
outside the current engine set.

---

## Override conditions

1. **Total trades < 50 per engine** — too few weekly signals, result inconclusive
2. **Any ticker PF > 10** — look-ahead or data bug; investigate
3. **PSU-excluded universe < 60 tickers with data** — too thin; check data sources

---

## Baseline comparison (from daily PSU-excluded run, 2026-05-08)

| Engine | Daily PF | Daily profitable% | Daily trades |
|---|---|---|---|
| Wyckoff | 0.70 | 34.7% | 658 |
| Confluence-2 | 0.68 | — | 656 |

Any weekly result is reported as lift/drag relative to these daily baselines.

---

## Run commands

```bash
# POC — 5 tickers, both engines
python scripts/validate_weekly_timeframe.py --poc

# Full run
python scripts/validate_weekly_timeframe.py --workers 4

# Single engine
python scripts/validate_weekly_timeframe.py --engines wyckoff
```

---

## Signature

Criteria committed 2026-05-08 before any weekly-timeframe run.

Context: All daily-bar engines TIER 3 on both full and PSU-excluded Nifty 100
(2026-04-28 through 2026-05-08). Weekly timeframe is the remaining structural
hypothesis for equity engines. Options/strangle is the parallel primary arc.
If weekly also TIER 3, the equity signal engine arc is closed.
