import { useEffect } from 'react';

// ── Engine results table data ─────────────────────────────────────────────
const ENGINE_RESULTS = [
  { engine: 'Harmonic',   tf: 'Daily',     sharpe: '—',      pf: '0.00', wr: '0.0%',  trades: '63' },
  { engine: 'Wyckoff',    tf: 'Daily',     sharpe: '-0.25',  pf: '0.67', wr: '23.6%', trades: '770' },
  { engine: 'Confluence', tf: 'Daily',     sharpe: '-2.25',  pf: '0.49', wr: '18.2%', trades: '803' },
  { engine: 'VSA',        tf: 'Daily',     sharpe: '-5.70',  pf: '0.54', wr: '19.1%', trades: '892' },
  { engine: 'pos_5ema',   tf: '15-minute', sharpe: '-7.65',  pf: '0.20', wr: '25.4%', trades: '8,722' },
  { engine: 'RRMS',       tf: 'Daily',     sharpe: '-16.50', pf: '0.52', wr: '12.5%', trades: '837' },
  { engine: 'SMC',        tf: 'Daily',     sharpe: '-63.79', pf: '0.42', wr: '15.6%', trades: '1,506' },
];

// ── Sub-section heading ───────────────────────────────────────────────────
function SubHeading({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-base font-semibold text-gray-900 mt-8 mb-2">
      {children}
    </h3>
  );
}

// ── Section divider ───────────────────────────────────────────────────────
function Divider() {
  return <hr className="border-gray-100 my-10" />;
}

export default function ResearchPage() {
  useEffect(() => {
    document.title = 'Shadow Market Research — Nifty 100 Backtest';
    window.scrollTo(0, 0);
  }, []);

  return (
    <div className="min-h-screen bg-white">
      {/* ── Top bar ── */}
      <div className="border-b border-gray-100 sticky top-0 bg-white/95 backdrop-blur-sm z-10">
        <div className="max-w-2xl mx-auto px-6 py-4 flex items-center justify-between">
          <a href="/" className="flex items-center gap-2 group">
            <div className="w-7 h-7 rounded-lg bg-trading-brand flex items-center justify-center">
              <span className="text-white text-xs font-bold">SM</span>
            </div>
            <span className="font-semibold text-gray-900 text-sm group-hover:text-trading-brand transition-colors">
              Shadow Market
            </span>
          </a>
          <div className="flex items-center gap-3">
            <span className="text-xs text-gray-400">Research</span>
            <a
              href="/login"
              className="text-xs font-medium text-trading-brand hover:text-trading-brand-light transition-colors"
            >
              Platform →
            </a>
          </div>
        </div>
      </div>

      {/* ── Article ── */}
      <article className="max-w-2xl mx-auto px-6 py-14">

        {/* Meta */}
        <div className="flex items-center gap-3 mb-6">
          <span className="text-xs font-medium text-trading-brand bg-trading-brand-bg px-2.5 py-1 rounded-full">
            Strategy Research
          </span>
          <span className="text-xs text-gray-400">May 8, 2026</span>
          <span className="text-xs text-gray-400">·</span>
          <span className="text-xs text-gray-400">12 min read</span>
        </div>

        {/* Title */}
        <h1 className="text-3xl font-bold text-gray-900 leading-tight mb-3">
          We backtested 7 popular trading strategies on Nifty 100. None had generalizable edge.
        </h1>
        <p className="text-base text-gray-500 mb-10 leading-relaxed">
          Including SMC, the most-taught methodology in Indian retail finance.
        </p>

        {/* ── Hook ── */}
        <div className="space-y-4 text-gray-700 leading-relaxed text-[17px]">
          <p>
            The walk-forward Sharpe for SMC strategies on Nifty 100 was{' '}
            <strong className="text-gray-900">-63.79</strong>.
          </p>
          <p>
            Walk-forward Sharpe is calculated on data the strategy has never seen — not
            the training period, not the calibration window. Out-of-sample, across five
            test windows spanning three years. A negative number means the strategy's
            average risk-adjusted return across out-of-sample windows was negative — not
            just below benchmark, but losing money on a volatility-adjusted basis. At
            -63.79, SMC didn't underperform. It lost money in every single out-of-sample
            window we tested.
          </p>
          <p>
            If you've spent any time in Indian trading YouTube over the last three years,
            you've encountered SMC. Order blocks. Fair value gaps. Liquidity sweeps.
            Institutional footprints. The methodology dominates paid course content in
            Indian retail finance. Hundreds of thousands of retail traders are building
            trading systems around its concepts right now.
          </p>
          <p>
            We tested it. On 90 Nifty 100 stocks. Three years of data. Realistic Indian
            costs — every Zerodha charge, modeled slippage, no idealized assumptions about
            execution quality. Walk-forward validation across out-of-sample windows the
            strategy never saw during development.
          </p>
          <p>
            The result was -63.79. Not "didn't beat the index." Not "marginally negative."
            Destroying capital, consistently, in every test window.
          </p>
          <p>
            We also tested six other strategies that retail traders use and teach. None
            of them produced positive expectancy either. This piece covers what we found,
            how we tested it, and where we made mistakes.
          </p>
          <p className="font-medium text-gray-900">Here's what we tested.</p>
        </div>

        <Divider />

        {/* ── What We Tested ── */}
        <h2 className="text-xl font-bold text-gray-900 mb-5">What We Tested</h2>
        <div className="space-y-4 text-gray-700 leading-relaxed text-[17px]">
          <p>Seven trading strategies, 90 Nifty 100 stocks, three years.</p>
          <p>The seven engines:</p>
        </div>

        <ul className="mt-4 space-y-3 text-[16px] text-gray-700">
          {[
            { name: 'SMC (Smart Money Concepts)', desc: 'Identifies institutional order blocks, fair value gaps, and liquidity sweeps. The most-taught retail trading methodology in Indian finance YouTube and paid course content.' },
            { name: 'Wyckoff', desc: 'Reads supply and demand through accumulation and distribution phases. Older methodology, fewer retail practitioners, stronger conceptual foundation.' },
            { name: 'VSA (Volume Spread Analysis)', desc: 'Analyses the relationship between price spread and volume to infer institutional activity.' },
            { name: 'Confluence', desc: 'Requires two or more of the above engines to agree before generating a signal. A filter on top of other strategies, not a strategy in itself.' },
            { name: 'Harmonic patterns', desc: 'Geometric price patterns based on Fibonacci ratios. High precision entry requirements, low signal frequency.' },
            { name: 'pos_5ema', desc: 'Five-EMA momentum on 15-minute intraday data. The closest to a standard retail approach — buy on pullback to rising EMA, sell on breakdown.' },
            { name: 'RRMS', desc: 'An internal risk management and position sizing system that uses support and resistance levels to set stops and risk gates. We initially included it in the entry validation harness — a category error we caught and corrected during the run, as discussed below.' },
          ].map(({ name, desc }) => (
            <li key={name} className="flex gap-3">
              <span className="mt-1 flex-shrink-0 w-1.5 h-1.5 rounded-full bg-trading-brand mt-2" />
              <span><strong className="text-gray-900">{name}:</strong> {desc}</span>
            </li>
          ))}
        </ul>

        <div className="mt-6 space-y-4 text-gray-700 leading-relaxed text-[17px]">
          <p>
            The universe was 90 of the 100 stocks in the Nifty 100 index. The other 10
            had IPOs, index additions, suspensions, or data gaps during our three-year
            window. Including them would have introduced survivorship bias.
          </p>
          <p>
            The validation window was January 2023 through April 2026 — over three years
            of daily OHLCV data for six engines, plus 15-minute intraday data for pos_5ema.
          </p>
        </div>

        {/* Cost box */}
        <div className="mt-6 rounded-xl border border-gray-100 bg-trading-bg p-5 text-[15px] text-gray-700">
          <p className="font-semibold text-gray-900 mb-3">Costs — every charge Zerodha actually bills:</p>
          <ul className="space-y-1.5">
            {[
              'Brokerage: ₹20 flat per order',
              'STT: 0.025% on delivery sell-side; 0.0125% on intraday sell-side',
              'GST: 18% on brokerage and exchange charges',
              'Stamp duty: 0.015% on buy-side',
              'Exchange charges: NSE turnover + SEBI charges',
              'Slippage (modeled): 0.3% per side on daily data, 0.1% per side on 15-minute',
            ].map((item) => (
              <li key={item} className="flex gap-2">
                <span className="text-trading-brand flex-shrink-0">·</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
          <p className="mt-4 text-[15px] text-gray-600 leading-relaxed">
            Most retail backtests use a simplified flat cost assumption like ₹20 flat
            brokerage with no slippage. For pos_5ema, the full cost stack totals 28 basis
            points per round-trip. A backtest using only ₹20 flat brokerage with no
            slippage costs 4 basis points. That 24-basis-point gap across 8,722 trades
            is real money, not a rounding error.
          </p>
        </div>

        <div className="mt-6 space-y-4 text-gray-700 leading-relaxed text-[17px]">
          <p className="font-semibold text-gray-900">Validation methodology — three tools, not one:</p>
          <ul className="space-y-2">
            {[
              'Walk-forward (5 windows): trained on past data, tested on the next unseen period, repeated 5 times. The numbers in the results table come from these out-of-sample windows.',
              'Monte Carlo permutation: trade outcomes randomly resequenced 10,000 times. Tests whether the observed return is statistically distinguishable from a random ordering of the same trades.',
              'Bootstrap Sharpe CI: 5,000 resamples to produce a 95% confidence interval on the Sharpe ratio.',
            ].map((item) => (
              <li key={item} className="flex gap-3">
                <span className="flex-shrink-0 w-1.5 h-1.5 rounded-full bg-trading-brand mt-2.5" />
                <span>{item}</span>
              </li>
            ))}
          </ul>
          <p>
            Walk-forward is the methodological choice that separates most retail backtests
            from what we did here. Without it, you measure how well a strategy memorised
            past data. With it, you measure whether it generalised to data it never saw.{' '}
            <strong className="text-gray-900">The difference is everything.</strong>
          </p>
        </div>

        <Divider />

        {/* ── What We Found ── */}
        <h2 className="text-xl font-bold text-gray-900 mb-5">What We Found</h2>
        <p className="text-[17px] text-gray-700 mb-6 leading-relaxed">
          All 7 engines lost money. Here's what 3 years of out-of-sample validation
          across 90 Nifty 100 stocks looked like.
        </p>

        {/* Results table */}
        <div className="overflow-x-auto rounded-xl border border-gray-100 mb-6">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-trading-bg border-b border-gray-100">
                {['Engine', 'Timeframe', 'WF Sharpe', 'Profit Factor', 'Win Rate', 'Trades'].map((h) => (
                  <th key={h} className="text-left px-4 py-3 font-semibold text-gray-700 text-xs uppercase tracking-wider whitespace-nowrap">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {ENGINE_RESULTS.map((row, i) => (
                <tr
                  key={row.engine}
                  className={`${i % 2 === 0 ? 'bg-white' : 'bg-trading-bg/30'} hover:bg-trading-ai-dim/20 transition-colors`}
                >
                  <td className="px-4 py-3 font-medium text-gray-900 whitespace-nowrap">{row.engine}</td>
                  <td className="px-4 py-3 text-gray-500 text-xs">{row.tf}</td>
                  <td className={`px-4 py-3 font-mono font-semibold ${row.sharpe === '—' ? 'text-gray-400' : 'text-trading-bear'}`}>
                    {row.sharpe}
                  </td>
                  <td className={`px-4 py-3 font-mono ${parseFloat(row.pf) >= 1 ? 'text-trading-bull font-semibold' : 'text-gray-600'}`}>
                    {row.pf}
                  </td>
                  <td className="px-4 py-3 text-gray-600 font-mono">{row.wr}</td>
                  <td className="px-4 py-3 text-gray-500 text-right font-mono">{row.trades}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p className="text-sm text-gray-500 mb-8 leading-relaxed">
          A negative walk-forward Sharpe means the strategy's average risk-adjusted return
          across out-of-sample test windows was negative. These aren't in-sample numbers
          dressed up as validation. The strategy's training data was deliberately excluded.
        </p>

        <div className="space-y-6 text-gray-700 leading-relaxed text-[17px]">
          <SubHeading>Wyckoff — closest to viable</SubHeading>
          <p>
            Wyckoff was the best-performing engine — WF Sharpe -0.25, profit factor 0.67,
            meaning for every ₹1 of gross profit, ₹1.50 of gross loss. The win rate was
            23.6%. At Wyckoff's average reward-to-risk ratio, you need 25% win rate to
            break even. Wyckoff came in 1.4 percentage points short. That gap sounds small.
            Closing it requires fundamental changes to how the engine identifies entries —
            different filters, different timing logic, different setups. Not parameter tuning.
          </p>

          <SubHeading>VSA — second closest, same conclusion</SubHeading>
          <p>
            VSA had a similar profile: PF 0.54, WR 19.1%, WF Sharpe -5.70. VSA's larger
            negative Sharpe doesn't mean it's a worse strategy concept — it likely means
            VSA's volume-based filtering produces more concentrated bad bets when wrong.
            Same category, different failure mode.
          </p>

          <SubHeading>Confluence — gate, not strategy</SubHeading>
          <p>
            The confluence engine requires two or more other engines to agree before
            generating a signal. We expected it to outperform individual engines because
            of the filtering effect. It didn't. WF Sharpe -2.25, PF 0.49. It works as
            a filter on top of strategies that already have edge. It does not generate
            edge on its own.
          </p>

          <SubHeading>pos_5ema — consistently wrong, not randomly wrong</SubHeading>
          <p>
            pos_5ema ran on 15-minute intraday data — 8,722 trades across 90 stocks.
            More trades means a cleaner statistical picture. The picture was clear: PF 0.20,
            WF Sharpe -7.65. The bootstrap robustness test re-samples the trade sequence
            randomly thousands of times, asking: would different orderings of these trades
            have produced a different outcome? In 89% of resampled sequences, pos_5ema
            still lost money. This isn't noise that more data would resolve. The 5-EMA
            momentum approach, as implemented, loses money with high consistency.
          </p>

          <SubHeading>Harmonic patterns — statistically unusable</SubHeading>
          <p>
            63 total trades across 90 tickers over 3 years. That is 0.7 signals per
            ticker per year. At this frequency, no statistical conclusion is possible —
            confidence intervals span from deeply negative to deeply positive. Harmonic
            patterns didn't fail the test. They couldn't be tested.
          </p>

          <SubHeading>RRMS — category error caught mid-run</SubHeading>
          <p>
            RRMS is a position sizing and risk management system that calculates trade
            size using support and resistance levels and applies a risk gate before any
            trade is executed. Testing it as a standalone entry engine was a category
            error — it was never designed to generate entry signals. We caught this during
            the run, reclassified it, removed it from the entry validation harness. Its
            -16.50 WF Sharpe reflects testing a position sizer as if it were a strategy,
            not the quality of the risk management itself.
          </p>

          <SubHeading>SMC — no good period existed</SubHeading>
          <p>
            WF Sharpe -63.79. The P75 — the best 25% of all out-of-sample windows —
            was -8.07. There was no regime, no period, no subset of the data where SMC
            produced positive expectancy. Not "underperforming." Losing money in every
            test window, consistently, over three years.
          </p>
        </div>

        <Divider />

        {/* ── Why This Matters ── */}
        <h2 className="text-xl font-bold text-gray-900 mb-5">Why This Matters More Than the Numbers</h2>
        <div className="space-y-5 text-gray-700 leading-relaxed text-[17px]">
          <p>
            There's an obvious question hanging over the table above: if these strategies
            don't work, why is the entire Indian retail trading ecosystem teaching them?
          </p>
          <p>
            The strategies that get published, taught, and sold are the ones that look
            convincing — not the ones that test well. This is a selection problem, and
            it's structural.
          </p>
          <p>
            Visual pattern recognition feels like insight. Order blocks and fair value
            gaps are easy to draw on a chart after the fact — once you know where price
            went, you can draw the lines that "predicted" it. Geometric Fibonacci patterns
            are visually compelling. The visual conviction these methodologies create is
            unrelated to whether they generate positive expectancy on data the practitioner
            hasn't seen yet.
          </p>

          <SubHeading>The walk-forward gap</SubHeading>
          <p>
            These engines don't look hopeless in-sample. In the training windows, several
            produce plausible Sharpe ratios. The out-of-sample collapse is what the
            walk-forward reveals. A strategy that memorised Nifty 100 patterns over three
            years can produce acceptable-looking in-sample metrics. Whether that
            memorisation generalised to the next period is the only question that matters
            for trading it.
          </p>

          <SubHeading>The cost gap</SubHeading>
          <p>
            Realistic costs change which strategies look viable. Indian equity trading has
            more cost layers than most retail backtests account for — STT asymmetry
            between buy and sell sides, GST stacking on top of exchange charges, stamp
            duty on buy-side. For pos_5ema, the full cost stack totals 28 basis points
            per round-trip against a common simplified assumption of 4 basis points. That
            gap, multiplied across thousands of trades, is the difference between a
            strategy that looks marginal and one whose losses are structural.
          </p>

          <SubHeading>The publication gap</SubHeading>
          <p>
            The universe of trading content that gets published is heavily selected for
            positive results. This isn't dishonesty — it's incentive structure. A creator
            who publishes "I tested this and it lost money" has less to sell than one who
            publishes "here's a setup that works." Over time, the content ecosystem fills
            up with strategies that look profitable and empties out the ones that don't —
            regardless of whether the look-profitable ones actually test well.
          </p>
          <p>
            Seven strategies genuinely popular in Indian retail trading. Three years of
            data, 90 stocks, realistic Indian costs, out-of-sample validation. None had
            positive expectancy.
          </p>
          <p className="font-semibold text-gray-900">
            That finding tells you where not to look. That's worth something.
          </p>
        </div>

        <Divider />

        {/* ── What We Did Wrong ── */}
        <h2 className="text-xl font-bold text-gray-900 mb-5">What We Did Wrong, and What We Got Right</h2>
        <p className="text-[17px] text-gray-700 mb-6">
          Three bugs surfaced during the validation run. We're publishing them.
        </p>

        <div className="space-y-6">
          {[
            {
              title: 'Bug 1: The equity floor',
              body: "The pos_5ema simulation didn't stop when an account hit zero capital. It kept running with negative balances. Percentage returns on negative equity inflate apparent losses — the backtester was modelling trading with money that didn't exist, applying percentage-based returns to negative equity, which inverts P&L signs and compounds the appearance of losses. When we fixed the simulation to halt at zero equity, the WF Sharpe moved from approximately -15 to -7.65. The strategy is still deeply negative. The bug made it look worse than it was.",
            },
            {
              title: 'Bug 2: Intraday slippage',
              body: "For pos_5ema's 15-minute data, we initially applied the daily slippage rate of 0.3% per side. The correct rate for 15-minute data on liquid large-caps is 0.1% per side. The fix went in pos_5ema's favor — less slippage means better backtest performance. The conclusion didn't change. PF stayed at 0.20, WF Sharpe at -7.65. A strategy that loses money even with corrected, more favorable cost assumptions isn't a strategy that needs better cost modeling. It needs different entry logic.",
            },
            {
              title: 'Bug 3: Tick-wide stops',
              body: 'On daily data, some bars have open equal to close — no intraday movement. When RRMS calculated position size from these bars, it produced stop distances of 0%. Position sizing logic divides total risk budget by per-share risk; when per-share risk approaches zero, position size approaches infinity. We added a minimum stop floor of 0.5% of entry price to bring sizing in line with what would actually happen in live trading.',
            },
          ].map(({ title, body }) => (
            <div key={title} className="rounded-xl border border-gray-100 p-5 bg-trading-bg/50">
              <h3 className="font-semibold text-gray-900 mb-2">{title}</h3>
              <p className="text-[16px] text-gray-700 leading-relaxed">{body}</p>
            </div>
          ))}
        </div>

        <p className="mt-6 text-[17px] text-gray-700 leading-relaxed">
          Publishing these bugs is risky. Any reader can use them to argue that our entire
          validation is suspect. We're publishing them anyway. The alternative — quietly
          fixing them without telling readers — is what makes most retail backtest content
          untrustworthy. Here's what we got right alongside the bugs:
        </p>

        <div className="mt-6 space-y-5 text-gray-700 leading-relaxed text-[17px]">
          <SubHeading>Pre-committed verdicts</SubHeading>
          <p>
            Before running any engine, we committed the decision criteria in a document
            with a date stamp: WF Sharpe ≥ 1.0 = deploy, ≥ 0.5 = viable with a regime
            filter, below that = kill or rebuild. Those thresholds didn't move after we
            saw results. When SMC came in at -63.79, the verdict was Kill standalone.
            We didn't lower the bar.
          </p>

          <SubHeading>No iteration after negative results</SubHeading>
          <p>
            When an engine failed, we documented the verdict and moved on. RRMS was
            reclassified as a position sizer — not retested with different parameters
            until it passed. Harmonic was declared statistically unusable — not retested
            on a narrower universe where it might produce 80 trades instead of 63. The
            discipline that produced these negative results is the same discipline that
            makes any positive result credible. The two are inseparable.
          </p>

          <SubHeading>Walk-forward by construction</SubHeading>
          <p>
            Every WF Sharpe in the table above is out-of-sample. The training window is
            excluded from performance measurement. An engine that memorised three years
            of Nifty 100 patterns would show a plausible in-sample Sharpe. The
            out-of-sample windows are what tell you whether that memorisation generalised
            to new data. It didn't, for any of these engines.
          </p>
        </div>

        <Divider />

        {/* ── What's Next ── */}
        <h2 className="text-xl font-bold text-gray-900 mb-5">What's Next</h2>
        <div className="space-y-5 text-gray-700 leading-relaxed text-[17px]">
          <p>
            After the equity validation, we shifted to a different strategy class:
            systematic options selling on Indian index derivatives.
          </p>
          <p>
            We tested four variants using the same methodology — pre-committed decision
            criteria documented before any run, walk-forward testing, Monte Carlo,
            mechanical verdicts. BankNifty weekly strangles, BankNifty monthly strangles,
            Nifty weekly strangles, Nifty monthly strangles.
          </p>
          <p className="font-semibold text-gray-900">One produced a positive result.</p>
          <p>
            The strategy: short Nifty 50 weekly strangles at 0.15-delta, entered five
            days before expiry, with a VIX regime gate filtering when premium is rich
            enough to sell. The numbers: walk-forward return 16.4% on margin, Sharpe
            0.556, win rate 78.2% across 55 trades.
          </p>
          <p>
            It isn't deployed. We pre-commit deployment thresholds before any test runs
            — for this strategy, Tier 1 required walk-forward return above 20% and Sharpe
            above 1.0. This result is marginal — meaningful enough to park as a candidate,
            not strong enough to trade capital against.
          </p>
          <p>
            The finding we didn't anticipate: removing the VIX regime gate collapsed
            BankNifty strangle returns by 19.5 percentage points. Walk-forward return
            went from +13.9% to -5.6%. The gate isn't a refinement. On the data we have,
            it's the difference between a positive result and a losing one. Understanding
            why that filter is load-bearing is most of what the next piece covers.
          </p>
        </div>

        {/* Subscribe CTA */}
        <div className="mt-10 rounded-2xl bg-trading-brand-bg border border-trading-brand/20 p-7 text-center">
          <p className="text-sm font-semibold text-trading-brand uppercase tracking-wider mb-2">
            Shadow Market Research
          </p>
          <p className="text-[17px] font-semibold text-gray-900 mb-1">
            We publish findings as they complete validation.
          </p>
          <p className="text-[15px] text-gray-600 mb-5">
            No tipping service. No market mood newsletters. Just research, when it's done.
          </p>
          <div className="flex flex-col sm:flex-row gap-3 justify-center">
            <a
              href="https://t.me/shadowmarketai"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-lg bg-trading-brand text-white text-sm font-medium hover:bg-trading-brand-light transition-colors shadow-brand"
            >
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.562 8.248l-2.025 9.54c-.148.658-.537.818-1.084.508l-3-2.21-1.447 1.394c-.16.16-.295.295-.605.295l.213-3.053 5.56-5.023c.242-.213-.054-.333-.373-.12L7.09 14.408l-2.95-.924c-.64-.203-.654-.64.136-.948l11.527-4.443c.532-.194 1 .13.76.155z"/>
              </svg>
              Telegram
            </a>
            <a
              href="/login"
              className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-lg border border-trading-brand text-trading-brand text-sm font-medium hover:bg-trading-brand-bg transition-colors"
            >
              Platform Access
            </a>
          </div>
          <p className="text-xs text-gray-400 mt-4">
            No tips, no calls, no daily newsletters. Just research as it completes validation.
          </p>
        </div>

        <Divider />

        {/* ── Disclaimer ── */}
        <div className="text-[13px] text-gray-400 leading-relaxed space-y-2">
          <p className="font-medium text-gray-500">Disclaimer</p>
          <p>
            This content is for educational purposes only. Nothing published here
            constitutes investment advice, a buy or sell recommendation, or a solicitation
            to trade any security.
          </p>
          <p>
            Shadow Market is not registered with SEBI as a Research Analyst or Investment
            Adviser, and does not provide personalized research or advisory services to
            any client or subscriber. Past backtest performance does not predict future
            results. All figures are derived from historical backtests using modeled costs
            and slippage — actual trading results will differ.
          </p>
          <p>
            Before making any investment decision, consult a SEBI-registered Research
            Analyst or Investment Adviser.
          </p>
        </div>

        {/* Footer */}
        <div className="mt-12 pt-8 border-t border-gray-100 flex items-center justify-between">
          <a href="/" className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-md bg-trading-brand flex items-center justify-center">
              <span className="text-white text-xs font-bold">SM</span>
            </div>
            <span className="text-sm font-semibold text-gray-700">Shadow Market</span>
          </a>
          <a
            href="/research"
            className="text-xs text-trading-brand hover:underline"
          >
            More research →
          </a>
        </div>

      </article>
    </div>
  );
}
