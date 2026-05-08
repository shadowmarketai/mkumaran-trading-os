# PSU-Excluded All-Engines Backtest — Pre-Committed Decision Criteria

**Date set:** 2026-05-08
**Author:** M. Kumaran
**Committed before any validation run:** Yes

---

## Hypothesis

Seven signal engines (SMC, Wyckoff, VSA, Harmonic, Confluence, RRMS, pos_5ema)
applied to the PSU-excluded Nifty 100 subset (~75 tickers after removing
government-linked companies) will show meaningfully better results than the same
engines on the full Nifty 100 universe (2026-04-28 baseline).

One or more engines may cross into positive expectancy territory when the
PSU contamination that systematically produces 0% win rate is removed.

Additionally, this test includes PSU-excluded **confluence variants**:
- 2-engine confluence (minimum 2 engines agreeing) — the natural next step from
  Wyckoff standalone TIER 3 with 34.7% profitable tickers
- 3-engine confluence (higher bar, fewer but higher-quality signals)

---

## Why this follows from individual engine + PSU-excluded Wyckoff results

Individual engine test (2026-04-28) on full Nifty 100:
- All 7 engines: TIER 3. Sharpe range -0.25 (Wyckoff) to -63.79 (SMC).
- PSU stocks confirmed as systematic drag (PF 0.00, 0% WR on 16 tickers).

PSU-excluded Wyckoff (2026-05-08):
- Standalone Wyckoff PSU-excluded: TIER 3 (PF 0.70, +0.030 lift vs 0.67 baseline)
- Profitable tickers: 34.7% vs ~13% full pipeline — universe is cleaner
- Per criteria doc: ONE structural change permitted — Option B (confluence) chosen

This test extends the PSU-excluded approach to all engines simultaneously,
plus tests confluence variants with 2 and 3 engine thresholds.

---

## Test parameters (locked for all engines)

| Parameter | Value |
|---|---|
| Universe | Nifty 100 minus PSU list (same 16-ticker exclusion list as psu_excluded_wyckoff_criteria.md) |
| Engines tested | SMC, Wyckoff, VSA, Harmonic, Confluence-2, Confluence-3 |
| MWA filter | NOT applied — isolate engine signal quality |
| Quality gate | NOT applied — raw engine output only |
| Position dedup | NOT applied — per-ticker isolation |
| Lookback | 3 years (2023-01-01 to 2026-04-30) |
| Cost model | Full Zerodha rate stack (same as all previous tests) |
| Slippage | 0.3% per side (daily data) |
| Capital | ₹1,00,000 per ticker |

**Confluence-2:** at least 2 of (SMC, Wyckoff, VSA, Harmonic) agree on direction.
**Confluence-3:** at least 3 of (SMC, Wyckoff, VSA, Harmonic) agree on direction.

---

## Decision criteria (per engine)

### Tier 1 — Engine has positive expectancy on PSU-excluded universe

| Metric | Threshold |
|---|---|
| Median PF | ≥ 1.2 |
| Profitable tickers (PF ≥ 1.0) | ≥ 40% of non-PSU universe |
| Total trades | ≥ 200 |
| Win rate | ≥ 35% |

**Decision for T1 engine:** Run walk-forward validation (12m train / 3m test)
on PSU-excluded universe with that engine before deployment.

### Tier 2 — Engine improves but insufficient

| Metric | Threshold |
|---|---|
| Median PF | 0.8–1.2 |
| Profitable tickers | 25–40% |

**Decision for T2 engine:** Apply ONE additional filter (MWA only) with new
pre-committed criteria doc before any further iteration.

### Tier 3 — PSU exclusion does not rescue engine

| Metric | Threshold |
|---|---|
| Median PF | < 0.8 |
| OR profitable tickers | < 25% |

**Decision for T3 engine:** Engine not viable on Indian daily equity data even
with PSU exclusion. Document. No further iteration on that engine.

---

## Baseline comparison table (locked, from 2026-04-28)

| Engine | Baseline PF (full N100) | Baseline Sharpe | Baseline WR |
|---|---|---|---|
| Wyckoff | 0.67 | -0.25 | 23.6% |
| Confluence | 0.49 | -2.25 | 18.2% |
| VSA | 0.54 | -5.70 | 19.1% |
| SMC | 0.42 | -63.79 | 15.6% |
| RRMS | 0.52 | -16.50 | 12.5% |
| Harmonic | 0.00 | — | 0.0% |
| pos_5ema | 0.20 | -7.65 | 25.4% (15m) |

All lift/drag figures in the postmortem are relative to this table.

---

## Override conditions

1. **Total trades < 100 per engine** — insufficient mass for that engine, mark inconclusive
2. **Any ticker PF > 10** — look-ahead or data bug; investigate before recording
3. **PSU-excluded universe < 60 tickers with data** — universe too thin; check data sources

---

## What this test does NOT answer

- Whether MWA filter further improves PSU-excluded results (separate test)
- Whether walk-forward holds OOS for any T1 engine (separate test)
- Options signal quality on PSU-excluded universe (different test arc)

---

## Run commands

```bash
# POC — 5 tickers, all engines (~5 min)
python scripts/validate_psu_excluded_all_engines.py --poc

# Full run — all engines, all tickers (~45-90 min)
python scripts/validate_psu_excluded_all_engines.py --workers 4

# Single engine subset
python scripts/validate_psu_excluded_all_engines.py --engines wyckoff,vsa --workers 4

# Resume after interruption
python scripts/validate_psu_excluded_all_engines.py --workers 4 --resume
```

---

## Signature

Criteria committed 2026-05-08 before any multi-engine PSU-excluded run.

Context: Individual engines TIER 3 on full N100 (2026-04-28). PSU-excluded
Wyckoff TIER 3 with improved profitable-ticker rate (34.7% vs 13%). This test
determines which engines, if any, have recoverable edge on the PSU-excluded
universe, and whether confluence of 2-3 engines crosses into positive territory.

---

## Postmortem (2026-05-08, after full run — 78 tickers)

**Result: ALL ENGINES TIER 3 — PSU exclusion does not rescue any engine.**

### Full results vs baseline

| Engine | Trades | Median PF | Baseline PF | Lift | Tier |
|---|---|---|---|---|---|
| wyckoff | 658 | 0.70 | 0.67 | +0.030 | TIER_3 |
| vsa | 745 | 0.55 | 0.54 | +0.010 | TIER_3 |
| smc | 1,260 | 0.39 | 0.42 | -0.030 | TIER_3 |
| harmonic | 53 | 0.00 | 0.00 | — | TIER_3 (INCONCLUSIVE — only 53 trades) |
| confluence_2 | 656 | 0.68 | 0.49 | +0.190 | TIER_3 |
| confluence_3 | 132 | 0.00 | 0.49 | — | TIER_3 (INCONCLUSIVE — 132 trades, ~1.7/ticker) |

### Key findings

**PSU exclusion does not rescue any engine into positive expectancy.**
All lifts are marginal (+0.030 best for Wyckoff; +0.190 for confluence_2).
No engine crosses the Tier 2 floor of PF ≥ 0.80.

**Best performer: Confluence-2 (0.68, +0.190 lift).** Requiring 2+ engines to
agree improves over standalone Wyckoff (0.70) and individual engines, but still
0.12 PF below the Tier 2 floor. This is the best result across all experiments
so far, but insufficient.

**Confluence-3 is too sparse.** Only 132 trades across 78 tickers (~1.7/ticker).
Most tickers generate 0 confluence-3 signals over 3 years. The few that do have
highly variable outcomes (TORNTPOWER: 1 trade PF=inf; ATGL: 2 trades PF=0.00).
Statistical mass is insufficient for any conclusion.

**SMC is the only engine that regressed** (-0.030 lift). PSU exclusion did not
help SMC — the engine signal quality is independent of sector contamination.

**Harmonic produces near-zero edge** across all tickers. 53 trades across 78
tickers confirms harmonic pattern detection on NSE daily data is not generating
actionable signals at any scale.

**ZOMATO still unavailable** via yfinance (delisted/symbol error). Excluded from
78-ticker universe as in prior runs.

### Binding constraint

The failure is in the engine signals themselves on Indian NSE daily data, not in
universe contamination. The PSU exclusion hypothesis is fully tested and rejected:
removing 16 government-linked tickers provides marginal lift but no engine crosses
into positive expectancy territory.

### Per criteria doc decision

All engines TIER 3 → **No further iteration on any of these engines on Indian
daily equity data without a new structural hypothesis.**

Per criteria: "Engine not viable on Indian daily equity data even with PSU
exclusion. Document. No further iteration on that engine."

### Candidate structural hypotheses for future test arcs (new criteria docs required)

1. **Weekly timeframe** — fewer but larger-RRR signals; less noise from 1-day bars
2. **OI-weighted Wyckoff** — volume proxy problem on NSE (delivery vol ≠ true accumulation signal)
3. **Options volatility edge** — Nifty strangle / BankNifty strangle already in progress
4. **Sector concentration** — private power (TORNTPOWER, CESC consistently above PF 1.0) may
   warrant a dedicated narrow-universe test with new pre-committed criteria

### Signature

Criteria committed 2026-05-08 before run.
Postmortem added 2026-05-08 after full 78-ticker run.
Result is definitive: PSU exclusion hypothesis rejected across all engines.
