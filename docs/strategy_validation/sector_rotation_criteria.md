# NSE Sector Rotation — Pre-committed Decision Criteria

**Date set:** 2026-05-12
**Committed before any validation run:** Yes

---

## Hypothesis

NSE sectoral indices trend in cycles. Buying the top 3 sectors by 3-month trailing
momentum and rebalancing monthly captures sector rotation alpha over Nifty 50.

---

## Strategy Parameters

| Parameter | Value |
|---|---|
| Universe | 10 NSE sectoral indices (see below) |
| Ranking signal | 3-month (63 trading day) total return |
| Portfolio | Top 3 sectors by ranking |
| Weighting | Equal weight (1/3 each) |
| Rebalance | Monthly (first trading day of each month) |
| Benchmark | Nifty 50 (^NSEI) buy-and-hold |
| Period | 2021-01-01 → today |

### Sectoral index universe (yfinance tickers)

| Sector | Ticker |
|---|---|
| Bank | ^CNXBANK |
| IT | ^CNXIT |
| Pharma | ^CNXPHARMA |
| Auto | ^CNXAUTO |
| FMCG | ^CNXFMCG |
| Metal | ^CNXMETAL |
| Realty | ^CNXREALTY |
| Energy | ^CNXENERGY |
| Finance | ^CNXFINANCE |
| Infrastructure | ^CNXINFRA |

---

## Cost Model (index ETF proxy, delivery)

| Cost | Rate |
|---|---|
| Brokerage | ₹20 flat per order |
| STT | 0.1% on sell |
| Exchange | 0.00345% per side |
| GST | 18% on brokerage + exchange |
| Stamp | 0.015% on buy |
| Slippage | 0.05% per side |

Practical note: sector rotation is implemented via sector ETFs (Nifty Bank ETF, IT ETF,
etc.) — all liquid, delivery-based. Cost model is identical to equity delivery.

---

## Decision Criteria

### Tier 1 — PROCEED: automate monthly sector rotation signal

- Alpha vs Nifty 50 (CAGR) ≥ 5%
- Sharpe ≥ 0.8
- Max drawdown ≤ 35%
- Win rate (months portfolio > Nifty 50) ≥ 55%

### Tier 2 — PROCEED WITH CAUTION: manual rotation signal only

- Alpha ≥ 2%
- Sharpe ≥ 0.5
- Max drawdown ≤ 45%
- Win rate ≥ 50%

### OVERRIDE

- Alpha < 2%, OR Sharpe < 0.5, OR Max drawdown > 45%

---

_Criteria committed 2026-05-12, before any validation run._
