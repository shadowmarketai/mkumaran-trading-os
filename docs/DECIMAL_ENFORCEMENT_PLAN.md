# Decimal Enforcement Plan

> Plan only — no code changes. Approve before execution.
>
> **Goal:** honour CLAUDE.md invariant #2 ("all P&L, stop-loss, target computations use `Decimal`, not `float`") without breaking the numpy/pandas-heavy analysis paths.
>
> **Status:** DRAFT
> **Author:** `onboarder`
> **Last updated:** 2026-04-22

---

## 1. The reality today

| Layer | Current type | What I found |
|---|---|---|
| Postgres | `Numeric(10,2)`, `Numeric(14,4)`, etc. | ✅ correct — exact arbitrary-precision |
| SQLAlchemy models (`models.py`) | `Column(Numeric(...))` | ✅ returns `Decimal` at the boundary |
| Python arithmetic past the boundary | `float` | ❌ cast-to-float everywhere, 70+ declarations in `rrms_engine`, `signal_cards`, `mwa_signal_generator`, `options_greeks` alone |
| `config.py` risk primitives | `RRMS_CAPITAL: float`, `RRMS_RISK_PCT: float`, `RRMS_MIN_RRR: float` | ❌ float at config level → float propagates |
| Broker API responses (Kite, Dhan, Angel) | `float` from JSON | ❌ JSON numbers → float by default |
| Zero files import `Decimal` | — | grep `from decimal` in `mcp_server/` returns nothing |

So the invariant is aspirational. The DB stores precise values; the Python code rounds them.

**Worst-offenders** (files most sensitive to rounding error):
- `mcp_server/rrms_engine.py` — position sizing, risk $ per share, RRR
- `mcp_server/signal_cards.py` — SL/TGT display + broadcast
- `mcp_server/options_greeks.py` — Black-Scholes, float is academically correct but premium × lot_size × contracts needs precision
- `mcp_server/portfolio_risk.py` — aggregate exposure across positions
- `mcp_server/signal_monitor.py` — P&L at close time → written to `outcomes.pnl_amount` (which IS Numeric, so precision lost on the way in)

**Not worth touching** (performance or library-required):
- `mcp_server/pattern_engine.py`, `smc_engine.py`, `wyckoff_engine.py`, `vsa_engine.py`, `harmonic_engine.py` — run np.array math over OHLCV bars. Conversion would be 100× slower with no precision benefit (technical analysis is inherently statistical).
- `mcp_server/mwa_scoring.py`, `mwa_scanner.py` — scoring/ranking, not money.
- `mcp_server/ohlcv_cache.py` — OHLCV bars stored as `Numeric(14,4)` but loaded into pandas for TA. Keep float past the cache boundary.
- `mcp_server/signal_features.py` — ML feature vectors → sklearn wants float64.

---

## 2. Target state

Two zones, with explicit conversion at the border:

```
┌────────────────────────────────────────────────────────────────┐
│  MONEY ZONE — Decimal                                          │
│  entries: broker response parsers, form inputs, DB reads       │
│  operations: P&L, position sizing, RRR, SL/TGT display         │
│  persist: directly to Numeric columns (no cast)                │
│                                                                 │
│  Files: rrms_engine, signal_cards, signal_monitor,              │
│         portfolio_risk, order_manager, options_selector         │
│         (premium × lot × contracts math only, Greeks stay float)│
└───────────────┬────────────────────────────────────────────────┘
                │ explicit .to_float() at boundary
                ▼
┌────────────────────────────────────────────────────────────────┐
│  ANALYSIS ZONE — float / numpy / pandas                        │
│  entries: OHLCV cache, pandas frames, scikit-learn             │
│  operations: TA (SMA/RSI/ATR/etc), Greeks, ML inference        │
│  files: pattern_engine, smc_engine, mwa_scanner, signal_features│
└────────────────────────────────────────────────────────────────┘
```

Boundary discipline: crossing money → analysis requires `float(dec_value)`, and crossing analysis → money requires `Decimal(str(float_value))` (never `Decimal(float_value)` directly — that preserves the binary artefact).

---

## 3. Mechanics

### 3.1 A `Money` helper module — opt-in, not mandatory

```python
# mcp_server/money.py  (new)
from decimal import Decimal, ROUND_HALF_UP
from typing import Union

Numeric = Union[int, float, str, Decimal]

def to_money(x: Numeric) -> Decimal:
    """Construct a Decimal with the broker precision (2dp for INR)."""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, float):
        return Decimal(str(x))  # avoid binary-float artefact
    return Decimal(x)

def round_paise(x: Decimal) -> Decimal:
    """Round half-up to 2dp (NSE tick-size aware rounding — 2dp for equity)."""
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def pnl(entry: Decimal, exit_price: Decimal, qty: int) -> Decimal:
    return round_paise((exit_price - entry) * Decimal(qty))
```

Thin layer. No behaviour change — purely a namespace to keep the pattern consistent.

### 3.2 Config layer first

`mcp_server/config.py` — `RRMS_CAPITAL`, `RRMS_RISK_PCT`, `RRMS_MIN_RRR`, `PREDICTOR_BLOCK_THRESHOLD`, etc. are read as `float(os.getenv(...))`. Change the money-shaped ones (`RRMS_CAPITAL`, `RRMS_RISK_PCT`) to Decimal via `to_money`. Keep ratio-shaped ones (`RRMS_MIN_RRR`, thresholds) as float — they're dimensionless and arithmetic on them doesn't touch paise.

### 3.3 RRMS engine — the big one

`rrms_engine.py` is where position sizing happens. Current shape:

```python
risk_per_share = entry_price - stop_loss     # float - float
risk_amt = capital * risk_pct                # float * float
qty = int(risk_amt / risk_per_share)         # float ÷ float → floor
```

Rounding errors here translate to wrong share counts. Proposed:

```python
risk_per_share = entry_price - stop_loss     # Decimal - Decimal
risk_amt = round_paise(capital * risk_pct)
qty = int(risk_amt / risk_per_share)         # Decimal ÷ Decimal → int
```

Type change cascades through the `RRMSDecision` dataclass. Small blast radius — ~20 declarations in one file.

### 3.4 Signal cards — the SL/TGT display layer

`signal_cards.py` formats Decimals for Telegram. Currently casts through `float(sig.entry_price)` to do arithmetic (trailing SL, % move). Replace with Decimal math + `str()` at the format step.

### 3.5 Monitor → outcomes

`signal_monitor.py` computes P&L at close-time and writes to `outcomes.pnl_amount` (Numeric). Currently:

```python
pnl_amt = (exit_price - entry_price) * qty   # float
outcome.pnl_amount = pnl_amt                 # SQLAlchemy coerces to Decimal
```

The coercion does a `Decimal(float(x))` which preserves the rounding error. Fix: keep the whole chain in Decimal from the broker response forward.

### 3.6 Boundary converters

Wherever a broker response or pandas cell feeds into the money path, wrap:

```python
# Before
entry = float(ltp_from_broker)

# After
entry = to_money(ltp_from_broker)  # if broker returned str or Decimal-able
```

One helper in `data_provider.py` can centralise this.

---

## 4. Phased execution

Three PRs. Each independently mergeable. No PR changes behaviour; only types.

### Phase 1 — Landing zone

- Add `mcp_server/money.py` with `to_money`, `round_paise`, `pnl`.
- Unit tests for the 3 helpers (pytest, no DB).
- **Nothing else changes.** Purely adds the tool.
- PR risk: zero.

### Phase 2 — RRMS + config + order sizing

- `config.py`: migrate money-shaped settings to Decimal (via `to_money` at load time).
- `rrms_engine.py`: replace `float` annotations + arithmetic with Decimal.
- `pretrade_check.py`, `order_manager.py`: accept Decimal at the interface; cast to float only at broker-API boundary (Kite/Dhan SDKs want floats in their JSON payloads).
- Tests: existing `tests/test_rrms.py` covers 15 cases; update float literals to pass through `to_money(...)`.
- PR risk: medium. This is the core sizing path. Needs the existing test suite to keep passing + a round-trip integration test on paper-mode.

### Phase 3 — Monitor + outcomes + portfolio aggregate

- `signal_monitor.py`: P&L computation in Decimal.
- `portfolio_risk.py`: aggregate exposure in Decimal.
- `signal_cards.py`: Decimal all the way to the format call.
- Tests: `test_signal_monitor.py`, `test_portfolio_risk.py` updated similarly.
- PR risk: medium-low. Monitor is the reactive side, not the decision side.

### Not done

- Options Greeks math (`options_greeks.py`) stays float — Black-Scholes is inherently an approximation; Decimal buys nothing and costs perf.
- Premium × lot × contracts aggregation IS money; that stays in the Decimal zone at a higher layer (`options_selector.py` exit code, `signal_monitor.py` outcome P&L).
- Technical analysis engines (SMC, VSA, Wyckoff, Harmonic, Patterns) — stay float, pandas/numpy-native.

---

## 5. Testing story

New invariants to add to the test suite:

1. **Boundary tests** — `test_money.py`: `to_money(0.1 + 0.2) == Decimal("0.30")` (i.e., boundary conversion prevents the classic 0.30000000000000004).
2. **Round-trip tests** — `test_rrms.py`: signal in Decimal → persist to DB (Numeric) → load back → compare equality with original Decimal (not with `== ±ε`).
3. **Forbidden patterns test** — a meta-test that greps the money-zone files and fails if they import `float` for P&L variables. Optional; strict version of the CLAUDE.md rule.

---

## 6. What this unlocks

- The CLAUDE.md invariant stops being aspirational.
- Rounding-error class of bugs becomes structurally impossible in the money zone.
- Audit/compliance: regulatory reports that need paise-accurate totals stop drifting.

## 7. What this does NOT fix

- OHLCV cache precision (already Numeric(14,4), already lossless on DB side — the downstream loss happens when pandas reads it).
- AI signal confidence scores (0–100 ints, no money involved).
- Scanner scoring / ranking (dimensionless).
- Historical `outcomes.pnl_amount` rows already written with float-through-Decimal coercion. A one-shot re-computation migration could back-fix them using historical broker prices, but that's out of scope.

---

## 8. Ballpark sizing

| Phase | LOC changed | Test work | Calendar |
|---|---|---|---|
| 1 — `money.py` + tests | +50 | +40 | 1 hr |
| 2 — RRMS + config + order | ~200 | ~60 | 3 hr |
| 3 — Monitor + portfolio + cards | ~250 | ~80 | 3 hr |

~7 hours dev work, 3 PRs. Stage-testable in paper-mode.

---

## 9. Open questions for the operator

1. **Precision target.** 2dp for INR equity, but MCX commodities trade in fractional paise (e.g., Natural Gas on MCX quotes 4dp). A single `round_paise` may not fit every segment. Proposal: `round_tick(value, exchange)` that dispatches per segment. Agree or keep 2dp everywhere as a simplification?
2. **Paper mode semantics.** Paper mode uses yfinance which returns floats. When we convert to Decimal at the boundary, do we preserve the 4-6dp yfinance returns, or immediately truncate to 2dp? (I'd keep the full precision until the sizing step, truncate at display.)
3. **Legacy `outcomes` rows.** Back-fix via a re-computation migration, or accept existing rows as historical and only enforce going forward?
4. **Broker SDK float requirement.** Kite / Dhan / Angel SDKs accept floats. The fix-up layer casts Decimal → float right before the API call. Confirm that's acceptable (versus forking an SDK wrapper).
5. **Go / no-go / phase pick.** Phase 1 is zero-risk and unblocks the others; Phase 2 is the meaningful one; Phase 3 is clean-up. Ship all three? Stop after Phase 2?

Answer inline on the PR that adopts this plan, or reply with numbered responses.
