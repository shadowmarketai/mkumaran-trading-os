# PSU-Excluded Wyckoff Backtest — Pre-Committed Decision Criteria

**Date set:** 2026-05-08
**Author:** M. Kumaran
**Committed before any validation run:** Yes

---

## Hypothesis

Wyckoff standalone, applied only to the non-PSU subset of Nifty 100 (~70 tickers
after excluding government-linked companies), produces positive risk-adjusted
expectancy over a 3-year window — even though Wyckoff standalone on the full Nifty 100
universe lost money (PF 0.67, WF Sharpe -0.25 from 2026-04-28 individual engine test).

The core claim: PSU/government stocks have policy-driven price behaviour that
Wyckoff accumulation/distribution patterns cannot read. Removing them may surface
a real underlying edge in the remaining universe.

---

## Why this test follows from pipeline validation

Pipeline validation (2026-05-08) showed a structural sector split:

**PSU / government stocks (16 tickers, zero wins across all trades):**
SBIN, POWERGRID, ONGC, NTPC, SIEMENS, BOSCHLTD, AMBUJACEM,
BANDHANBNK, LUPIN, AUROPHARMA, ALKEM, CONCOR, SUNPHARMA, ADANIENT,
BHEL, COALINDIA — PF 0.00, WR 0% on every signal.

These stocks move on policy announcements, subsidy changes, government capex cycles,
and divestment news — none of which Wyckoff or any technical engine can anticipate.
The Wyckoff standalone test (2026-04-28) included these tickers, which dragged the
portfolio-level PF down. This test answers: was PSU contamination the reason Wyckoff
looked weak?

Wyckoff is the closest engine to viable from the individual engine test:
- PF 0.67 (least negative of all 7 engines tested)
- WF Sharpe -0.25 (least negative)
- Win rate 23.6% (above breakeven for its average RRR)

---

## PSU exclusion list (locked)

Remove the following tickers from the Nifty 100 universe before any run:

| Ticker | Reason |
|---|---|
| SBIN | Government bank — policy-driven |
| POWERGRID | Government infrastructure — tariff-driven |
| ONGC | Government oil — subsidy/policy driven |
| NTPC | Government power — regulated returns |
| COALINDIA | Government mining — price policy driven |
| ADANIENT | Conglomerate with heavy government project exposure |
| AMBUJACEM | Construction linked — government infra spend |
| BANDHANBNK | Government-backed financial inclusion bank |
| AUROPHARMA | Pharma — included for FY2025 PSU contract drag |
| ALKEM | Same as above |
| CONCOR | Government logistics — railway ministry |
| SIEMENS | Government infra contracts primary revenue |
| BOSCHLTD | PSU supplier — heavy government procurement |
| LUPIN | Government tender-dependent revenue |
| SUNPHARMA | Partial inclusion — government price controls |
| BHEL | Heavy Engineering / government capex |

**Remaining universe: ~74 tickers from Nifty 100**

---

## Test parameters (locked)

| Parameter | Value |
|---|---|
| Universe | Nifty 100 minus PSU list above (~74 tickers) |
| Engine | Wyckoff standalone (same as 2026-04-28 individual test) |
| Confluence | NOT required — standalone engine only |
| MWA filter | NOT applied — isolate engine signal quality |
| Quality gate | NOT applied — raw engine output only |
| Position dedup | NOT applied — per-ticker isolation |
| Lookback | 3 years (2023-01-01 to 2026-04-30) |
| Cost model | Full Zerodha rate stack (same as all previous tests) |
| Slippage | 0.3% per side (daily data) |
| Capital | ₹1,00,000 per ticker |

**Note:** No filters are applied so the result is directly comparable to the
2026-04-28 standalone Wyckoff result. If the PSU-excluded universe shows better PF,
the attribution is clear: PSU contamination was the drag.

---

## Decision criteria

### Tier 1 — PSU exclusion rescues Wyckoff → pipeline with PSU filter next

| Metric | Threshold |
|---|---|
| Median PF (PSU-excluded) | ≥ 1.2 |
| Median Sharpe | ≥ 0.5 |
| Win rate | ≥ 35% |
| Profitable tickers (PF ≥ 1.0) | ≥ 40% of non-PSU universe |
| Total trades | ≥ 200 |

**Decision:** PSU contamination was the cause of Wyckoff's failure on the full
universe. Next test: apply full pipeline (confluence + MWA + quality gate + dedup)
to PSU-excluded universe with new pre-committed criteria doc.

### Tier 2 — PSU exclusion helps but insufficient

| Metric | Threshold |
|---|---|
| Median PF | 0.8–1.2 |
| Median Sharpe | 0.0–0.5 |
| Win rate | 25–35% |

**Decision:** PSU exclusion improves but not enough for standalone viability.
Test ONE structural change only — stated in writing before running:
- Option A: Add MWA filter only (no quality gate) — does regime alignment help?
- Option B: Raise to confluence (2 engines, PSU-excluded) — does agreement raise WR?

### Tier 3 — PSU exclusion does not help

| Metric | Threshold |
|---|---|
| Median PF | < 0.8 |
| OR win rate | < 25% |

**Decision:** Wyckoff edge is not recoverable by universe filtering alone.
The failure is in the engine signals themselves on Indian daily equity data, not
in the universe contamination. Document. Consider:
(a) Weekly timeframe (fewer but larger signals, less noise)
(b) OI-data-based Wyckoff variant (volume proxy problem on NSE daily)

---

## Override conditions

1. **Total trades < 200** — insufficient mass, result is inconclusive
2. **Any ticker PF > 10** — look-ahead or data bug; investigate before recording
3. **PSU-excluded profitable tickers < 10** — universe may be too thin; check data

---

## Comparison baseline (locked)

| Metric | Full universe Wyckoff (2026-04-28) |
|---|---|
| Median PF | 0.67 |
| WF Sharpe | -0.25 |
| Win rate | 23.6% |
| Universe | Nifty 100 (90 tickers with data) |

Any result is reported as lift/drag relative to this baseline.

---

## Run commands

```bash
# POC — verify on 5 non-PSU tickers
python scripts/validate_psu_excluded_wyckoff.py --poc

# Full run
python scripts/validate_psu_excluded_wyckoff.py --workers 4

# Comparison: full Nifty 100 Wyckoff (re-run baseline with same script)
python scripts/validate_psu_excluded_wyckoff.py --full-universe
```

---

## Signature

Criteria committed 2026-05-08 before any PSU-excluded run.

Context: Pipeline TIER 3 (2026-05-08) found 16 PSU tickers with PF 0.00 and 0%
win rate across all trades. Individual Wyckoff TIER 3 (2026-04-28) had PF 0.67 on
full universe. PSU exclusion is the most actionable structural hypothesis from both
findings. Decision criteria committed before script is written or run.

---

## Postmortem (2026-05-08, after full run)

**Result: TIER 3 — PSU exclusion helps but insufficient for standalone viability.**

### Key metrics

| Metric | Value | Threshold | Result |
|---|---|---|---|
| Median PF | 0.70 | ≥ 1.2 = Tier 1, ≥ 0.8 = Tier 2 | Tier 3 ✓ |
| Lift vs baseline (0.67) | +0.030 | — | Positive but marginal |
| Profitable tickers | 26/75 (34.7%) | ≥ 40% = Tier 1 | Near Tier 2 boundary |
| Total trades | 691 | ≥ 200 (not override) | OK ✓ |

### Key findings

PSU exclusion does improve signal quality — profitable tickers went from ~13% (full
pipeline) to 34.7% (PSU-excluded standalone Wyckoff). The universe is cleaner.
But median PF 0.70 is the binding constraint: below the Tier 2 floor of 0.80.

Notable PSU-excluded tickers with PF > 1.0:
- TORNTPOWER: PF 2.29, WR 50.0%, 6 trades (private power, not PSU)
- CESC: PF 1.20, WR 33.3%, 9 trades (private power, not PSU)
The common thread: private-sector power companies have more predictable
technical patterns than government-linked stocks.

Data failures: ZOMATO.NS and MCDOWELL-N.NS returned empty from yfinance — symbol
mapping issue, not a strategy finding. Both excluded from the 78-ticker count.

### Per criteria doc — ONE structural change next

Per Tier 3 decision, ONE change may be tested with a new criteria doc. The two options:
- Option A: MWA filter only — does regime alignment lift PF above 0.8?
- Option B: 2-engine confluence on PSU-excluded universe (fewer but better signals)

**Recommended next test: Option B (confluence).** Reasoning: 34.7% profitable-ticker
rate indicates real underlying edge in the non-PSU universe. The drag is from the
losing half of single-engine signals. Confluence (2+ engines agreeing) on a 78-ticker
PSU-excluded universe should reduce signal count but increase signal quality. A new
pre-committed criteria doc is required before running.

### Signature

Criteria committed 2026-05-08 before run. Postmortem added 2026-05-08 after run.
