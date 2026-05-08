# We backtested 7 popular trading strategies on Nifty 100. None had generalizable edge.

*Including SMC, the most-taught methodology in Indian retail finance.*

---

The walk-forward Sharpe for SMC strategies on Nifty 100 was -63.79.

Walk-forward Sharpe is calculated on data the strategy has never seen — not the training period, not the calibration window. Out-of-sample, across five test windows spanning three years. A negative number means the strategy's average risk-adjusted return across out-of-sample windows was negative — not just below benchmark, but losing money on a volatility-adjusted basis. At -63.79, SMC didn't underperform. It lost money in every single out-of-sample window we tested.

If you've spent any time in Indian trading YouTube over the last three years, you've encountered SMC. Order blocks. Fair value gaps. Liquidity sweeps. Institutional footprints. The methodology dominates paid course content in Indian retail finance. Hundreds of thousands of retail traders are building trading systems around its concepts right now.

We tested it. On 90 Nifty 100 stocks. Three years of data. Realistic Indian costs — every Zerodha charge, modeled slippage, no idealized assumptions about execution quality. Walk-forward validation across out-of-sample windows the strategy never saw during development.

The result was -63.79. Not "didn't beat the index." Not "marginally negative." Destroying capital, consistently, in every test window.

We also tested six other strategies that retail traders use and teach. None of them produced positive expectancy either. This piece covers what we found, how we tested it, and where we made mistakes.

Here's what we tested.

---

## What We Tested

Seven trading strategies, 90 Nifty 100 stocks, three years.

The seven engines:

- **SMC (Smart Money Concepts)**: Identifies institutional order blocks, fair value gaps, and liquidity sweeps. The most-taught retail trading methodology in Indian finance YouTube and paid course content.
- **Wyckoff**: Reads supply and demand through accumulation and distribution phases. Older methodology, fewer retail practitioners, stronger conceptual foundation.
- **VSA (Volume Spread Analysis)**: Analyses the relationship between price spread and volume to infer institutional activity.
- **Confluence**: Requires two or more of the above engines to agree before generating a signal. A filter on top of other strategies, not a strategy in itself.
- **Harmonic patterns**: Geometric price patterns based on Fibonacci ratios. High precision entry requirements, low signal frequency.
- **pos_5ema**: Five-EMA momentum on 15-minute intraday data. The closest to a standard retail approach — buy on pullback to rising EMA, sell on breakdown.
- **RRMS**: An internal risk management and position sizing system that uses support and resistance levels to set stops and risk gates. We initially included it in the entry validation harness — a category error we caught and corrected during the run, as discussed below.

The universe was 90 of the 100 stocks in the Nifty 100 index. The other 10 had IPOs, index additions, suspensions, or data gaps during our three-year window. Including them would have introduced survivorship bias.

The validation window was January 2023 through April 2026 — over three years of daily OHLCV data for six engines, plus 15-minute intraday data for pos_5ema.

**Costs** — every charge Zerodha actually bills:
- Brokerage: ₹20 flat per order
- STT: 0.025% on delivery sell-side; 0.0125% on intraday sell-side
- GST: 18% on brokerage and exchange charges
- Stamp duty: 0.015% on buy-side
- Exchange charges: NSE turnover + SEBI charges
- Slippage (modeled execution gap, not a billed fee): 0.3% per side on daily data, 0.1% per side on 15-minute. Slippage is the gap between the price you intend to enter at and what you actually fill at. We modeled this as a cost rather than assuming perfect execution.

Most retail backtests use a simplified flat cost assumption like ₹20 flat brokerage with no slippage. The full Indian cost structure is meaningfully higher. For pos_5ema, which executes intraday trades at ₹1,00,000 per position, the full cost stack — brokerage, STT, GST, stamp duty, exchange charges, and modeled slippage — totals 28 basis points per round-trip. A backtest that models only ₹20 flat brokerage with no slippage costs 4 basis points. That 24-basis-point gap across 8,722 trades is real money, not a rounding error.

**Validation methodology** — three tools, not one:
- Walk-forward (5 windows): trained on past data, tested on the next unseen period, repeated 5 times. The numbers in the results table come from these out-of-sample windows.
- Monte Carlo permutation: trade outcomes randomly resequenced 10,000 times. Tests whether the observed return is statistically distinguishable from a random ordering of the same trades.
- Bootstrap Sharpe CI: 5,000 resamples to produce a 95% confidence interval on the Sharpe ratio.

Walk-forward is the methodological choice that separates most retail backtests from what we did here. Without it, you measure how well a strategy memorised past data. With it, you measure whether it generalised to data it never saw. The difference is everything.

---

## What We Found

All 7 engines lost money. Here's what 3 years of out-of-sample validation across 90 Nifty 100 stocks looked like.

| Engine | Timeframe | WF Sharpe | Profit Factor | Win Rate | Trades |
|---|---|---|---|---|---|
| Harmonic | Daily | — | 0.00 | 0.0% | 63 |
| Wyckoff | Daily | -0.25 | 0.67 | 23.6% | 770 |
| Confluence | Daily | -2.25 | 0.49 | 18.2% | 803 |
| VSA | Daily | -5.70 | 0.54 | 19.1% | 892 |
| pos_5ema | 15-minute | -7.65 | 0.20 | 25.4% | 8,722 |
| RRMS | Daily | -16.50 | 0.52 | 12.5% | 837 |
| SMC | Daily | -63.79 | 0.42 | 15.6% | 1,506 |

A negative walk-forward Sharpe means the strategy's average risk-adjusted return across out-of-sample test windows was negative. These aren't in-sample numbers dressed up as validation. The strategy's training data was deliberately excluded.

Here is what each result actually means.

**Wyckoff — closest to viable**

Wyckoff was the best-performing engine — WF Sharpe -0.25, profit factor 0.67, meaning for every ₹1 of gross profit, ₹1.50 of gross loss. The win rate was 23.6%. At Wyckoff's average reward-to-risk ratio, you need 25% win rate to break even. Wyckoff came in 1.4 percentage points short. That gap sounds small. Closing it requires fundamental changes to how the engine identifies entries — different filters, different timing logic, different setups. Not parameter tuning.

**VSA — second closest, same conclusion**

VSA had a similar profile: PF 0.54, WR 19.1%, WF Sharpe -5.70. VSA's larger negative Sharpe doesn't mean it's a worse strategy concept — it likely means VSA's volume-based filtering produces more concentrated bad bets when wrong. Same category, different failure mode.

**Confluence — gate, not strategy**

The confluence engine requires two or more other engines to agree before generating a signal. We expected it to outperform individual engines because of the filtering effect. It didn't. WF Sharpe -2.25, PF 0.49. It works as a filter on top of strategies that already have edge. It does not generate edge on its own.

**pos_5ema — consistently wrong, not randomly wrong**

pos_5ema ran on 15-minute intraday data — 8,722 trades across 90 stocks. More trades means a cleaner statistical picture. The picture was clear: PF 0.20, WF Sharpe -7.65. The bootstrap robustness test re-samples the trade sequence randomly thousands of times, asking: would different orderings of these trades have produced a different outcome? In 89% of resampled sequences, pos_5ema still lost money. This isn't noise that more data would resolve. The 5-EMA momentum approach, as implemented, loses money with high consistency.

**Harmonic patterns — statistically unusable**

63 total trades across 90 tickers over 3 years. That is 0.7 signals per ticker per year. At this frequency, no statistical conclusion is possible — confidence intervals span from deeply negative to deeply positive. Harmonic patterns didn't fail the test. They couldn't be tested.

**RRMS — category error caught mid-run**

RRMS is a position sizing and risk management system that calculates trade size using support and resistance levels and applies a risk gate before any trade is executed. Testing it as a standalone entry engine was a category error — it was never designed to generate entry signals. We caught this during the run, reclassified it, removed it from the entry validation harness. Its -16.50 WF Sharpe reflects testing a position sizer as if it were a strategy, not the quality of the risk management itself.

**SMC — no good period existed**

WF Sharpe -63.79. The P75 — the best 25% of all out-of-sample windows — was -8.07. There was no regime, no period, no subset of the data where SMC produced positive expectancy. Not "underperforming." Losing money in every test window, consistently, over three years.

---

## Why This Matters More Than the Numbers

There's an obvious question hanging over the table above: if these strategies don't work, why is the entire Indian retail trading ecosystem teaching them?

The strategies that get published, taught, and sold are the ones that look convincing — not the ones that test well. This is a selection problem, and it's structural.

Visual pattern recognition feels like insight. Order blocks and fair value gaps are easy to draw on a chart after the fact — once you know where price went, you can draw the lines that "predicted" it. Geometric Fibonacci patterns are visually compelling. The visual conviction these methodologies create is unrelated to whether they generate positive expectancy on data the practitioner hasn't seen yet.

**The walk-forward gap**

These engines don't look hopeless in-sample. In the training windows, several produce plausible Sharpe ratios. The out-of-sample collapse is what the walk-forward reveals. A strategy that memorised Nifty 100 patterns over three years can produce acceptable-looking in-sample metrics. Whether that memorisation generalised to the next period is the only question that matters for trading it.

**The cost gap**

Realistic costs change which strategies look viable. Indian equity trading has more cost layers than most retail backtests account for — STT asymmetry between buy and sell sides, GST stacking on top of exchange charges, stamp duty on buy-side. For pos_5ema, the full cost stack totals 28 basis points per round-trip against a common simplified assumption of 4 basis points. That gap, multiplied across thousands of trades, is the difference between a strategy that looks marginal and one whose losses are structural.

**The publication gap**

The universe of trading content that gets published is heavily selected for positive results. This isn't dishonesty — it's incentive structure. A creator who publishes "I tested this and it lost money" has less to sell than one who publishes "here's a setup that works." Over time, the content ecosystem fills up with strategies that look profitable and empties out the ones that don't — regardless of whether the look-profitable ones actually test well.

Seven strategies genuinely popular in Indian retail trading. Three years of data, 90 stocks, realistic Indian costs, out-of-sample validation. None had positive expectancy.

That finding tells you where not to look. That's worth something.

---

## What We Did Wrong, and What We Got Right

Three bugs surfaced during the validation run. We're publishing them.

**Bug 1: The equity floor**

The pos_5ema simulation didn't stop when an account hit zero capital. It kept running with negative balances. Percentage returns on negative equity inflate apparent losses — the backtester was modelling trading with money that didn't exist, applying percentage-based returns to negative equity, which inverts P&L signs and compounds the appearance of losses. When we fixed the simulation to halt at zero equity, the WF Sharpe moved from approximately -15 to -7.65. The strategy is still deeply negative. The bug made it look worse than it was.

**Bug 2: Intraday slippage**

For pos_5ema's 15-minute data, we initially applied the daily slippage rate of 0.3% per side. The correct rate for 15-minute data on liquid large-caps is 0.1% per side. The fix went in pos_5ema's favor — less slippage means better backtest performance. The conclusion didn't change. PF stayed at 0.20, WF Sharpe at -7.65. A strategy that loses money even with corrected, more favorable cost assumptions isn't a strategy that needs better cost modeling. It needs different entry logic.

**Bug 3: Tick-wide stops**

On daily data, some bars have open equal to close — no intraday movement. When RRMS calculated position size from these bars, it produced stop distances of 0%. Position sizing logic divides total risk budget by per-share risk; when per-share risk approaches zero, position size approaches infinity. We added a minimum stop floor of 0.5% of entry price to bring sizing in line with what would actually happen in live trading.

Publishing these bugs is risky. Any reader can use them to argue that our entire validation is suspect. We're publishing them anyway. The alternative — quietly fixing them without telling readers — is what makes most retail backtest content untrustworthy. Here's what we got right alongside the bugs:

**Pre-committed verdicts**

Before running any engine, we committed the decision criteria in a document with a date stamp: WF Sharpe ≥ 1.0 = deploy, ≥ 0.5 = viable with a regime filter, below that = kill or rebuild. Those thresholds didn't move after we saw results. When SMC came in at -63.79, the verdict was Kill standalone. We didn't lower the bar.

**No iteration after negative results**

When an engine failed, we documented the verdict and moved on. RRMS was reclassified as a position sizer — not retested with different parameters until it passed. Harmonic was declared statistically unusable — not retested on a narrower universe where it might produce 80 trades instead of 63. The discipline that produced these negative results is the same discipline that makes any positive result credible. The two are inseparable.

**Walk-forward by construction**

Every WF Sharpe in the table above is out-of-sample. The training window is excluded from performance measurement. An engine that memorised three years of Nifty 100 patterns would show a plausible in-sample Sharpe. The out-of-sample windows are what tell you whether that memorisation generalised to new data. It didn't, for any of these engines.

---

## What's Next

After the equity validation, we shifted to a different strategy class: systematic options selling on Indian index derivatives.

We tested four variants using the same methodology — pre-committed decision criteria documented before any run, walk-forward testing, Monte Carlo, mechanical verdicts. BankNifty weekly strangles, BankNifty monthly strangles, Nifty weekly strangles, Nifty monthly strangles.

One produced a positive result.

The strategy: short Nifty 50 weekly strangles at 0.15-delta, entered five days before expiry, with a VIX regime gate filtering when premium is rich enough to sell. The numbers: walk-forward return 16.4% on margin, Sharpe 0.556, win rate 78.2% across 55 trades.

It isn't deployed. We pre-commit deployment thresholds before any test runs — for this strategy, Tier 1 required walk-forward return above 20% and Sharpe above 1.0. This result is marginal — meaningful enough to park as a candidate, not strong enough to trade capital against.

The finding we didn't anticipate: removing the VIX regime gate collapsed BankNifty strangle returns by 19.5 percentage points. Walk-forward return went from +13.9% to -5.6%. The gate isn't a refinement. On the data we have, it's the difference between a positive result and a losing one. Understanding why that filter is load-bearing is most of what the next piece covers.

We publish findings as they complete validation. No tipping service. No newsletters about market moods. Just the next piece of research, when it's done.

Subscribe for the next piece — [Telegram] or [email]. No tips, no calls, no daily newsletters. Just research as it completes validation.

---

## Disclaimer

This content is for educational purposes only. Nothing published here constitutes investment advice, a buy or sell recommendation, or a solicitation to trade any security.

Shadow Market is not registered with SEBI as a Research Analyst or Investment Adviser, and does not provide personalized research or advisory services to any client or subscriber. Past backtest performance does not predict future results. All figures are derived from historical backtests using modeled costs and slippage — actual trading results will differ.

Before making any investment decision, consult a SEBI-registered Research Analyst or Investment Adviser.
