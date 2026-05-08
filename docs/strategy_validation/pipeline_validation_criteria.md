# Production Pipeline Validation — Pre-Committed Decision Criteria

**Date set:** 2026-05-08
**Author:** M. Kumaran
**Committed before any pipeline validation run:** Yes

---

## Hypothesis

The production signal pipeline — engine confluence (2+ of SMC/Wyckoff/VSA/Harmonic)
→ MWA proxy (Nifty 200 EMA) → quality gate (RRR ≥ 1.5, confidence ≥ 55) →
position dedup (max 5 open, 30d cooldown) — produces positive expectancy on
Nifty 100 equity signals after realistic costs over a 3-year window, even though
no individual engine has positive expectancy in isolation.

This test answers the specific question: does the combination of filters add
enough signal-to-noise improvement to compensate for individual engine losses?

---

## Why this test follows from the individual engine validation

Individual engine validation (2026-04-28) showed:
- All 7 standalone engines lost money (WF Sharpe range: -0.25 to -63.79)
- Wyckoff closest to viable: PF 0.67, WF Sharpe -0.25, win rate 23.6%
- Confluence engine: PF 0.49 standalone, but designed as a filter not a strategy
- The pipeline was explicitly identified as untested in portfolio_v1_2026_04_28.md

The pipeline test is the logical next step. Individual engines are raw signal
sources; the pipeline is the product. The question is whether the debate
validator, MWA filter, and dedup together rescue the signal quality.

---

## Test parameters (locked)

| Parameter | Value |
|---|---|
| Universe | Nifty 100 (same as individual engine test) |
| Confluence threshold | 2+ engines agreeing on direction |
| Engines in confluence | SMC, Wyckoff, VSA, Harmonic |
| MWA filter | Nifty 50 > 200 EMA → LONG signals only |
| Quality gate | RRR ≥ 1.5, confidence ≥ 55 |
| Position dedup | Max 5 open positions, 30-day per-ticker cooldown |
| Lookback | 3 years (same as individual engine test) |
| Cost model | Full Zerodha rate stack (same as individual engine test) |
| Slippage | 0.3% per side (daily data) |
| Capital | ₹1,00,000 per ticker |

**Note on walk-forward:** This first pass is in-sample only (no train/test split).
Results are directional, not definitive. A Tier 1 result requires a follow-up
walk-forward run before deployment. Results are noted as "in-sample" throughout.

---

## Decision criteria

### Tier 1 — Pipeline has positive expectancy → walk-forward validation next

| Metric | Threshold |
|---|---|
| Median profit factor (across profitable tickers) | ≥ 1.2 |
| Median Sharpe (across tickers with trades) | ≥ 0.3 |
| Profitable tickers (PF ≥ 1.0) | ≥ 40% of universe |
| Total trades across all tickers | ≥ 200 |

**Decision:** Run walk-forward validation with 12-month train / 3-month test
windows on the full universe. Do not assign signal weights or deploy until
walk-forward confirms positive OOS expectancy.

### Tier 2 — Combination helps but insufficient → identify which filter adds most

| Metric | Threshold |
|---|---|
| Median profit factor | 0.8–1.2 |
| Median Sharpe | -0.3 to 0.3 |
| Profitable tickers | 20–40% |

**Decision:** Run diagnostic variants:
- Remove MWA filter → does PF improve? (MWA may be removing good signals)
- Raise confluence to 3 engines → does PF improve? (higher bar, fewer but better signals)
- ONE structural change only, stated in writing before running.

### Tier 3 — Combination does not help → fundamental engine review

| Metric | Threshold |
|---|---|
| Median profit factor | < 0.8 |
| Profitable tickers | < 20% |

**Decision:** The confluence + filtering approach does not rescue individual
engine losses on Indian equity daily data. Document. No further pipeline
iteration. Consider: (a) different signal sources (OI, delivery %, FII flow),
(b) different timeframe (weekly signals), (c) different universe.

---

## Override conditions

1. **Total trades < 200** — insufficient statistical mass, result is inconclusive
2. **Any single ticker shows PF > 10** — likely a data or look-ahead bug; investigate before recording
3. **Filter retention > 30%** — if pipeline retains > 30% of raw signals, the filters are too weak; the quality gate thresholds need tightening, not the engines

---

## What this test does NOT answer

- Whether the debate validator (6-agent AI system) adds value — the pipeline
  script uses rule-based confluence, not the AI debate validator. A separate
  test is required for that.
- Options signal quality (separate research arc)
- Commodity or forex signal quality (not yet validated)

---

## Run commands

```bash
# POC — verify script runs correctly on 3 tickers
python scripts/validate_production_pipeline.py --poc

# Full run (overnight, ~45-90 minutes)
python scripts/validate_production_pipeline.py --workers 4 --resume

# Variant A: without MWA filter
python scripts/validate_production_pipeline.py --no-mwa --workers 4

# Variant B: 3-engine confluence (higher bar)
python scripts/validate_production_pipeline.py --min-engines 3 --workers 4
```

---

## Postmortem template (to be completed after run)

- Final tier verdict (mechanical, per criteria above)
- Median PF, Sharpe, profitable ticker count, total trades
- Filter retention rate (raw → broadcast signals)
- Whether any bugs were found (PF > 10 on any ticker)
- Confirmation that no parameters were changed after seeing results
- Walk-forward result if Tier 1

---

## Signature

Criteria committed 2026-05-08 before any pipeline validation run.

Context: 7 individual engines validated standalone — all lost money.
Pipeline test is the next logical step per portfolio_v1_2026_04_28.md.
Same discipline: commit criteria before running, accept mechanical verdict.
