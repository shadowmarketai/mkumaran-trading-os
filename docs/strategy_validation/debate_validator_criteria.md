# Debate Validator Backtest — Pre-Committed Decision Criteria

**Date set:** 2026-05-08
**Author:** M. Kumaran
**Committed before any validation run:** Yes

---

## Hypothesis

The 6-agent debate validator (Bull → Bear → Bull rebuttal → Bear rebuttal → Judge → Risk)
produces a higher-quality signal filter than simple rule-based confluence (2+ engine agreement)
on the same Nifty 100 signal universe, as measured by profit factor improvement over the
TIER 3 pipeline baseline (PF 0.43, 2026-05-08).

This test answers: does LLM-assisted adversarial reasoning extract edge that deterministic
rule-based confluence misses on Indian equity daily data?

---

## Why this test follows from pipeline validation

Pipeline validation (2026-05-08) showed:
- Rule-based confluence (2+ engines) + MWA + quality gate: median PF 0.43 (TIER 3)
- The debate validator was explicitly called out as untested in the pipeline criteria doc
- The pipeline produced 50 broadcast signals from 2,711 raw signals (1.8% retention)
- Debate validator was designed for the uncertain zone (40–75 pre-confidence), not as a
  blanket replacement for the rule-based filter

The question: on the subset of signals where pre-confidence is 40–75, does running the
debate validator improve PF above the rule-based baseline?

---

## Test design

### Signal universe
- Same as pipeline validation: Nifty 100 tickers, 3-year window (2023-01-01 to 2026-04-30)
- Same cost model: full Zerodha rate stack, 0.3% slippage
- Same capital: ₹1,00,000 per ticker

### What changes vs pipeline test
- Instead of rule-based quality gate (RRR ≥ 1.5, confidence ≥ 55), signals in the
  uncertain zone (40–75 pre-confidence) are routed through the debate validator
- Signals with pre-confidence > 75: single-pass validation (ALERT path, kept)
- Signals with pre-confidence < 40: SKIP (unchanged from baseline)
- Debate output: ALERT → trade, WATCHLIST → trade at half-size proxy, SKIP → no trade

### LLM cost structure
| Debate path | API calls per signal |
|---|---|
| Full debate (40–75 pre-conf) | 6 calls (Bull + Bear + 2 rebuttals + Judge + Risk) |
| Single-pass (> 75 pre-conf) | 1 call |
| SKIP (< 40 pre-conf) | 0 calls |

**Estimated signals in uncertain zone:** 30–50% of 2,711 raw signals = ~800–1,350 signals
**Estimated API calls:** 800 × 6 + 450 × 1 ≈ 5,250 calls
**API:** Free tier in use — no monetary cost but rate-limit throttle required

### Throttling requirement
- Max 20 calls/minute (free tier conservative estimate)
- Expected runtime: 5,250 calls ÷ 20/min = ~4.4 hours
- Script must use `asyncio.Semaphore(3)` to stay within burst limits
- Log per-signal LLM latency and retry count for observability

---

## Decision criteria

### Tier 1 — Debate adds meaningful signal quality improvement

| Metric | Threshold |
|---|---|
| Median PF (debate-routed signals) | ≥ 1.2 |
| Lift over baseline PF 0.43 | ≥ +0.4 absolute |
| Profitable tickers | ≥ 40% of universe |
| Total trades with debate routing | ≥ 100 |

**Decision:** Integrate debate validator into live pipeline. Replace rule-based quality gate
with debate routing for uncertain-zone signals. Commit criteria doc for live A/B test
(debate vs rule-based) before enabling in production.

### Tier 2 — Debate helps but marginal improvement

| Metric | Threshold |
|---|---|
| Median PF | 0.8–1.2 |
| Lift over baseline | +0.1 to +0.4 |
| Profitable tickers | 25–40% |

**Decision:** Debate validator improves signal quality but insufficient for live routing.
Test ONE structural change only, committed in writing before running:
- Option A: Raise debate threshold (only pre-conf 50–70, not 40–75)
- Option B: Require ALERT (not WATCHLIST) for trade entry

### Tier 3 — Debate does not improve on rule-based baseline

| Metric | Threshold |
|---|---|
| Median PF | < 0.8 |
| Lift over baseline | < +0.1 (or negative) |
| Profitable tickers | < 25% |

**Decision:** LLM adversarial reasoning does not add statistically meaningful edge on
Nifty 100 daily equity signals. Document. No further debate validator iteration on this
universe. Consider: different universe (PSU-excluded), different timeframe (weekly signals),
or different debate prompt framing.

---

## Override conditions

1. **Total trades < 100** — insufficient mass, result is inconclusive (not failed)
2. **Any ticker PF > 10** — likely look-ahead or data bug; investigate before recording
3. **API failure rate > 20%** — unreliable LLM routing; result is inconclusive
4. **Rate limit hits > 5%** of calls — reduce concurrency and re-run

---

## What this test does NOT answer

- Whether debate validator improves options signal quality (separate test)
- Whether live LLM latency (2–4s per signal) affects trading execution (real-time test)
- Whether specific agent prompts are optimal (prompt engineering is a separate arc)
- PSU-excluded universe performance (needs new criteria doc)

---

## Comparison baseline (locked, from 2026-05-08 pipeline run)

| Metric | Baseline (rule-based confluence) |
|---|---|
| Median PF | 0.43 |
| Profitable tickers | 12/90 (13.3%) |
| Total trades | 744 |
| Retention rate | 1.8% (50 / 2,711 signals) |

Any result reported in this test is a lift/drag RELATIVE to this baseline.

---

## Run commands

```bash
# POC — verify script runs on 5 signals (cost: ~30 API calls)
python scripts/validate_debate_pipeline.py --poc --tickers HDFCBANK,TCS,INFY,FEDERALBNK,SBIN

# Full run (overnight, ~4–6 hours with rate limiting)
python scripts/validate_debate_pipeline.py --workers 3 --resume

# Comparison variant: ALERT-only entry (Tier 2 option)
python scripts/validate_debate_pipeline.py --alert-only --workers 3
```

---

## Postmortem (2026-05-08, after full run)

**Result: TIER 3 — debate routing does not meaningfully improve on rule-based baseline.**

### Key metrics

| Metric | Value | Threshold | Result |
|---|---|---|---|
| Median PF | 0.485 | < 0.8 = Tier 3 | Tier 3 ✓ |
| Lift over baseline (0.43) | +0.055 | ≥ +0.4 for Tier 1 | Tier 3 ✓ |
| Profitable tickers | 18/90 (20.0%) | ≥ 40% for Tier 1 | Tier 3 ✓ |
| Total trades | 650 | ≥ 100 (not override) | OK ✓ |

### Routing distribution

| Verdict | Count |
|---|---|
| ALERT | 0 |
| WATCHLIST | 1,821 |
| SKIP | 990 |
| pre_skip (< 40 conf or no MWA) | 251 |

**Critical finding: skill agents returned ALERT 0 times.** Every signal that passed
the pre-confidence gate (>40) was routed to WATCHLIST. The skill-based debate system
has no calibration that produces ALERT-level conviction on confluence signals from this
universe. The effective result was: all signals above the pre-confidence floor were
traded — which is weaker filtering than the rule-based quality gate (RRR ≥ 1.5, conf ≥ 55).

### Why PF improved slightly (+0.055) despite ALERT=0

The pre-confidence gate (threshold 40) filters out low-conviction signals before debate.
This alone removes ~251 signals that the rule-based pipeline would have kept.
The slight PF improvement is attributable to the pre-confidence pre-filter, not to the
debate verdict itself.

### Structural findings

- Profitable tickers: 18/90 (20.0%) vs 12/90 (13.3%) baseline — marginal improvement
- PSU sector still PF ≈ 0 (same structural failure as pipeline test)
- The WATCHLIST-only recommendation is a skill_agents calibration issue:
  agents are scoring all confluence signals in the 40–75 confidence zone
  as "worth watching but not ALERT" — which is the expected conservative behaviour
  but means the debate adds no filtering beyond the pre-confidence gate

### Conclusion

Skill-based debate routing produces PF 0.485 vs rule-based PF 0.43 on Nifty 100 daily
equity signals. The lift (+0.055) is present but insufficient for Tier 2 (needs ≥ 0.8).
The ALERT=0 finding suggests the debate system is correctly conservative but needs
recalibration before it can function as a signal quality gate (not just a signal watch).

### Actions per criteria doc

- Result is TIER 3 — no further debate pipeline iteration without new criteria doc
- Next investigation before any new run: examine why skill agents return WATCHLIST=100%
  (threshold calibration in skill_agents.py vs. expected confluence signal confidence range)
- PSU-excluded universe test still pending — may recover Wyckoff edge without debate routing

### Future direction

The pre-confidence gate alone (+0.055 lift) warrants a standalone test: does applying
ONLY the pre-confidence filter (drop signals < 40) to the original rule-based pipeline
produce the same or better improvement? If yes, the debate routing adds nothing.

---

## Signature

Criteria committed 2026-05-08 before any debate validator run.

Context: Pipeline test (2026-05-08) produced TIER 3 result with rule-based confluence.
Debate validator has never been backtested. This test determines if LLM reasoning
recovers the edge that deterministic rules miss.
