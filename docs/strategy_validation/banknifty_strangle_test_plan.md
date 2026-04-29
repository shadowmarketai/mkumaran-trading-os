# BankNifty Short Strangle — Test Plan

**Created:** 2026-04-29  
**Status:** Weekend 1 — data backfill  
**Strategy under test:** Short strangle (15-delta CE + 15-delta PE) on BankNifty weekly expiry  
**Hypothesis:** Premium decay on weekly options, managed with delta/P&L rules, produces consistent positive expectancy after all costs  

---

## Prerequisites (verify before Weekend 1)

### 1. Dhan v2 F&O historical coverage

The `intraday_minute_data` API supports `instrument_type="OPTIDX"` for NSE_FNO.  
Key risk: each option contract needs a unique `security_id`. The Dhan scrip master  
is updated daily — **expired contracts from > ~6 months ago may not appear in the  
current scrip master**, limiting the backfill window to 12–18 months rather than 3 years.

**Check before building:** Pull `https://images.dhan.co/api-data/api-scrip-master.csv`  
and verify how many BANKNIFTY OPTIDX rows exist with `SEM_EXPIRY_DATE < 2025-01-01`.  
If the count is near zero, adjust the test window to 2024-01 → 2026-04 (2 years) or  
supplement with NSE bhavcopy reconstruction for older data.

### 2. BankNifty weekly expiry schedule

NSE changed weekly expiry assignments in 2024. Verify:
- Current BankNifty weekly expiry day (historically Thursday, reportedly changed to Wednesday in 2024)
- Whether BankNifty weekly is still active in 2026 (or if SEBI has restricted it)
- Check: nseindia.com → Derivatives → Weekly Options Contracts

If BankNifty weekly has been discontinued, pivot to Nifty weekly (Thursday) with the same methodology.

---

## Test design

| Parameter | Value | Rationale |
|---|---|---|
| Underlying | BankNifty | Highest options liquidity on NSE after Nifty |
| Structure | Short strangle (naked) | Simplest premium-sell structure; iron condor tested later if this validates |
| Target delta | 0.15 per leg (15-delta) | Standard retail options selling delta — enough premium, manageable gamma |
| Entry day/time | Monday 10:00 IST | After morning volatility settles; avoids first 45-min noise |
| Exit — profit | 50% of initial credit | Industry standard for short option premium collection |
| Exit — stop loss | 2× initial credit (net debit) | Limits catastrophic loss |
| Exit — time | Thursday 15:00 IST | Forced exit before expiry gamma risk |
| Adjustment rule | Roll untested side when tested side 2× credit or delta > 0.30 | From adjustment_engine.py existing rules |
| IV gate | Skip if VIX percentile < 30 or > 80 | Too little premium or structural event risk |
| Event gate | Skip if RBI/Fed/Budget within blackout | From event_calendar.py |
| Lot size | 1 lot (BankNifty = 15 shares) | Standard minimum |
| Capital per trade | Margin per lot (estimate ₹1,20,000 SPAN + exposure) | Use actual SPAN at each entry date |

---

## Data required

- **options_chain_cache** — new table, 15-min OHLCV per option contract
- **Nifty VIX** — for IV percentile gate (already in data_provider via yfinance `^INDIAVIX`)
- **BankNifty spot** — intraday 15-min (already in ohlcv_cache from Dhan backfill)
- **Event calendar** — already in `events/calendar.yaml`

---

## Build sequence

| Weekend | Task | Script | Output |
|---|---|---|---|
| 1 | Options chain backfill | `scripts/backfill_dhan_banknifty_options.py` | `options_chain_cache` table populated |
| 2 | Validation harness | `scripts/validate_banknifty_strangle.py` | `reports/banknifty_strangle_validation_<date>.md` |
| 3 | Read + decide | — | Decision per pre-committed criteria |

---

## Data quality gates (check Sunday of Weekend 1)

```sql
-- Minimum acceptable before running validation:
SELECT COUNT(DISTINCT expiry_date) FROM options_chain_cache 
WHERE underlying = 'BANKNIFTY';
-- Must be >= 40 (roughly 1 year of weekly expiries)
-- Prefer >= 80 (2 years); 3-year target = 130+ expiries

SELECT expiry_date, COUNT(DISTINCT strike), COUNT(DISTINCT option_type)
FROM options_chain_cache WHERE underlying = 'BANKNIFTY'
GROUP BY expiry_date ORDER BY expiry_date
LIMIT 5;
-- Each expiry must have >= 20 strikes per side (CE + PE)

SELECT MIN(bar_time), MAX(bar_time), COUNT(*) 
FROM options_chain_cache 
WHERE underlying = 'BANKNIFTY' AND expiry_date = '2024-01-25'
  AND strike = <ATM_STRIKE> AND option_type = 'CE';
-- Must have 15-min bars covering Monday 9:15 to Thursday 15:30
-- ~25 bars/day × 4 days = ~100 bars per contract per expiry
```

If any gate fails, fix data before Weekend 2. Do not validate on incomplete data.

---

## What this test will NOT tell us

- Whether the strategy works on Nifty (different liquidity, different gamma profile) — separate test
- Whether 10-delta or 20-delta is better — separate test after this verdict
- Whether monthly expiry is better than weekly — separate test
- Whether iron condor outperforms naked strangle — separate test

One hypothesis. One test. One verdict.

---

## Cost model

All P&L computed net of:
- Brokerage: ₹20/order (Zerodha F&O flat)
- STT: 0.0125% on sell side (intraday F&O)
- Exchange charges: 0.05% (NSE F&O)
- GST: 18% on brokerage + exchange charges
- Stamp duty: 0.003% on buy side
- Slippage: 0.5% per leg (options mid-price vs fill — conservative for BankNifty)

Reference: `mcp_server/backtester.py` cost model for actual rates.
