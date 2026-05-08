import { useEffect } from 'react';

// ── Strangle results data ─────────────────────────────────────────────────────
const BANKNIFTY_ROWS = [
  { label: 'VIX gate ON',  return_ann: '13.9%', sharpe: '1.15', wr: '80.6%', mc_dd: '7.5%',  trades: '36*' },
  { label: 'VIX gate OFF', return_ann: '-5.6%', sharpe: '-0.31', wr: '61.1%', mc_dd: '18.3%', trades: '59'  },
];

const NIFTY_ROWS = [
  { label: 'Weekly strangle (VIX-gated)', return_ann: '16.4%', sharpe: '0.556', wr: '78.2%', mc_dd: '~12%', trades: '55' },
];

function Divider() {
  return <hr className="border-gray-100 my-10" />;
}

function Callout({ children, type = 'neutral' }: { children: React.ReactNode; type?: 'warn' | 'neutral' | 'positive' }) {
  const styles = {
    warn:     'bg-amber-50 border-amber-200 text-amber-900',
    neutral:  'bg-gray-50 border-gray-200 text-gray-700',
    positive: 'bg-emerald-50 border-emerald-200 text-emerald-900',
  };
  return (
    <div className={`border rounded-xl px-5 py-4 my-6 text-sm leading-relaxed ${styles[type]}`}>
      {children}
    </div>
  );
}

export default function OptionsResearchPage() {
  useEffect(() => {
    document.title = 'Shadow Market Research — Options Selling on Indian Markets';
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
            <a href="/research/nifty-backtest" className="text-xs text-gray-400 hover:text-gray-600 transition-colors">← Piece 1</a>
            <span className="text-xs text-gray-400">Research</span>
            <a href="/login" className="text-xs font-medium text-trading-brand hover:text-trading-brand-light transition-colors">
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
          <span className="text-xs text-gray-400">10 min read</span>
        </div>

        {/* Title */}
        <h1 className="text-3xl font-bold text-gray-900 leading-tight mb-3">
          We found one options strategy with marginal validated edge on Indian markets. Here's the honest report.
        </h1>
        <p className="text-base text-gray-500 mb-10 leading-relaxed">
          Nifty weekly short strangles, VIX-gated. 55 trades. WF Sharpe 0.556.
          Not the home run. The only result that survived our validation discipline.
        </p>

        {/* ── Section 1 ── */}
        <div className="space-y-4 text-gray-700 leading-relaxed text-[17px]">
          <p>
            In{' '}
            <a href="/research/nifty-backtest" className="text-trading-brand hover:underline">
              our first research piece
            </a>
            , we tested seven popular technical analysis strategies on Nifty 100 equity daily
            data. All seven lost money. Walk-forward Sharpe values ranged from -0.25 to -63.79.
          </p>
          <p>
            Options selling is different enough from equity trend-following that it deserved
            its own test. A short strangle doesn't need to predict direction — it only needs
            the underlying to stay within a range. In theory, that's a lower bar. In practice,
            the risk profile is completely different: unlimited losses on sharp moves, gamma
            acceleration near expiry, and IV collapse eating into credit on adjustment.
          </p>
          <p>
            We ran the same pre-committed discipline: decision criteria committed before
            any data was observed, mechanical verdict, no adjustments after seeing results.
            Here's what we found.
          </p>
        </div>

        <Divider />

        {/* ── Section 2: What we tested ── */}
        <h2 className="text-xl font-bold text-gray-900 mb-4">What we tested</h2>
        <div className="space-y-4 text-gray-700 leading-relaxed text-[17px]">
          <p>
            <strong className="text-gray-900">Strategy:</strong> Short strangle on index weekly
            options. Sell one OTM call and one OTM put, both at approximately 0.15 delta at
            entry, 5–6 days before expiry.
          </p>
          <p>
            <strong className="text-gray-900">Exit rules:</strong> Take profit at 50% of initial
            credit collected. Stop at 2× initial credit. Time exit at market close on expiry day.
          </p>
          <p>
            <strong className="text-gray-900">VIX regime gate:</strong> Only enter when India VIX
            is between the 30th and 80th percentile of its trailing 252-day window. Skip entries
            when VIX is abnormally low (credit too thin) or abnormally high (directional gap risk
            too large).
          </p>
          <p>
            <strong className="text-gray-900">Universe:</strong> BankNifty weekly (discontinued
            November 2024, tested Jan 2023–Nov 2024), then Nifty weekly (surviving, tested
            Jan 2023–Apr 2026).
          </p>
          <p>
            <strong className="text-gray-900">Cost model:</strong> Full Zerodha rate stack —
            ₹20 flat brokerage per order, STT on exercise, exchange charges, GST, stamp duty.
            0.05–0.10% slippage on ATM/OTM strikes respectively.
          </p>
        </div>

        <Divider />

        {/* ── Section 3: BankNifty ── */}
        <h2 className="text-xl font-bold text-gray-900 mb-4">BankNifty: the VIX gate is load-bearing</h2>
        <div className="space-y-4 text-gray-700 leading-relaxed text-[17px]">
          <p>
            BankNifty weekly options were discontinued by SEBI in November 2024 as part of
            the expiry rationalization policy. We tested the full available window: Jan 2023 to
            Nov 2024, roughly 96 weeks.
          </p>
          <p>
            The single most important finding: <strong className="text-gray-900">with the VIX
            gate, the strategy made money. Without it, it lost.</strong>
          </p>
        </div>

        {/* BankNifty results table */}
        <div className="my-6 overflow-x-auto">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="border-b border-gray-200">
                <th className="text-left py-2 pr-4 text-gray-500 font-medium text-xs uppercase tracking-wide">Variant</th>
                <th className="text-right py-2 px-3 text-gray-500 font-medium text-xs uppercase tracking-wide">Ann. Return</th>
                <th className="text-right py-2 px-3 text-gray-500 font-medium text-xs uppercase tracking-wide">WF Sharpe</th>
                <th className="text-right py-2 px-3 text-gray-500 font-medium text-xs uppercase tracking-wide">Win Rate</th>
                <th className="text-right py-2 px-3 text-gray-500 font-medium text-xs uppercase tracking-wide">MC P95 DD</th>
                <th className="text-right py-2 pl-3 text-gray-500 font-medium text-xs uppercase tracking-wide">Trades</th>
              </tr>
            </thead>
            <tbody>
              {BANKNIFTY_ROWS.map((row) => (
                <tr key={row.label} className="border-b border-gray-100">
                  <td className="py-2.5 pr-4 font-medium text-gray-900 text-sm">{row.label}</td>
                  <td className={`py-2.5 px-3 text-right font-mono text-sm ${row.return_ann.startsWith('-') ? 'text-red-600' : 'text-emerald-600'}`}>{row.return_ann}</td>
                  <td className={`py-2.5 px-3 text-right font-mono text-sm ${row.sharpe.startsWith('-') ? 'text-red-600' : 'text-emerald-600'}`}>{row.sharpe}</td>
                  <td className="py-2.5 px-3 text-right font-mono text-sm text-gray-700">{row.wr}</td>
                  <td className="py-2.5 px-3 text-right font-mono text-sm text-gray-700">{row.mc_dd}</td>
                  <td className="py-2.5 pl-3 text-right font-mono text-sm text-gray-500">{row.trades}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-xs text-gray-400 mt-2">* 36 trades is below our 50-trade significance threshold — result recorded as OVERRIDE-inconclusive, not a clean Tier 1 pass.</p>
        </div>

        <div className="space-y-4 text-gray-700 leading-relaxed text-[17px]">
          <p>
            The VIX gate removes 39% of potential entries. The 19.5 percentage point swing
            in annualized return between gate-on and gate-off variants means the gate isn't
            refining a profitable strategy — it's turning a losing strategy into a profitable one.
            When VIX is at extremes, the strangle gets hurt by both sides: low VIX means thin
            credit that can't absorb adjustments; high VIX means the underlying makes the kind
            of directional moves that blow through the short strikes.
          </p>
          <p>
            The 80.6% win rate with VIX gate on looks impressive. The asterisk matters: 36
            qualifying trades is below the 50-trade threshold we set in our pre-committed
            criteria. The result is recorded as OVERRIDE-inconclusive — the direction is
            positive, but statistical certainty is missing. We carried the gate logic forward
            to Nifty because the 19.5pp delta is large enough to be signal, not noise.
          </p>
        </div>

        <Divider />

        {/* ── Section 4: Nifty ── */}
        <h2 className="text-xl font-bold text-gray-900 mb-4">Nifty weekly: marginal positive edge confirmed</h2>
        <div className="space-y-4 text-gray-700 leading-relaxed text-[17px]">
          <p>
            After SEBI discontinued BankNifty weekly, Nifty weekly became the only surviving
            weekly index derivative in India. We ran the same strategy — same VIX gate, same
            exit rules, same cost model — on 3 years of Nifty weekly data.
          </p>
        </div>

        {/* Nifty results table */}
        <div className="my-6 overflow-x-auto">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="border-b border-gray-200">
                <th className="text-left py-2 pr-4 text-gray-500 font-medium text-xs uppercase tracking-wide">Strategy</th>
                <th className="text-right py-2 px-3 text-gray-500 font-medium text-xs uppercase tracking-wide">Ann. Return</th>
                <th className="text-right py-2 px-3 text-gray-500 font-medium text-xs uppercase tracking-wide">WF Sharpe</th>
                <th className="text-right py-2 px-3 text-gray-500 font-medium text-xs uppercase tracking-wide">Win Rate</th>
                <th className="text-right py-2 px-3 text-gray-500 font-medium text-xs uppercase tracking-wide">MC P95 DD</th>
                <th className="text-right py-2 pl-3 text-gray-500 font-medium text-xs uppercase tracking-wide">Trades</th>
              </tr>
            </thead>
            <tbody>
              {NIFTY_ROWS.map((row) => (
                <tr key={row.label} className="border-b border-gray-100">
                  <td className="py-2.5 pr-4 font-medium text-gray-900 text-sm">{row.label}</td>
                  <td className="py-2.5 px-3 text-right font-mono text-sm text-emerald-600">{row.return_ann}</td>
                  <td className="py-2.5 px-3 text-right font-mono text-sm text-emerald-600">{row.sharpe}</td>
                  <td className="py-2.5 px-3 text-right font-mono text-sm text-gray-700">{row.wr}</td>
                  <td className="py-2.5 px-3 text-right font-mono text-sm text-gray-700">{row.mc_dd}</td>
                  <td className="py-2.5 pl-3 text-right font-mono text-sm text-gray-500">{row.trades}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <Callout type="positive">
          <strong>Tier 2 result.</strong> The strategy produced positive walk-forward Sharpe (0.556)
          and 78.2% win rate across 55 qualifying trades. This is the only strategy in 9 backtests
          across two asset classes that produced a positive out-of-sample Sharpe. It is not Tier 1
          — walk-forward confirmation with a clean OOS window still pending. We are calling it
          marginal positive edge with full transparency about what that means.
        </Callout>

        <div className="space-y-4 text-gray-700 leading-relaxed text-[17px]">
          <p>
            The VIX gate rejected 22% of potential entries on Nifty data — fewer rejections than
            BankNifty because Nifty's volatility profile is more stable than BankNifty's. The
            remaining entries trade in the regime where credit is meaningful without being a panic
            premium, and the underlying is range-bound enough for the short strikes to stay safe.
          </p>
          <p>
            The 12% estimated max drawdown (Monte Carlo P95) is the number to focus on for risk
            sizing. If you allocated ₹1,50,000 margin per strangle (the approximate SPAN margin
            for one lot), a P95 drawdown means a potential ₹18,000 peak-to-trough loss. That's
            the number to stress-test against your capital before considering this trade.
          </p>
        </div>

        <Divider />

        {/* ── Section 5: What it doesn't mean ── */}
        <h2 className="text-xl font-bold text-gray-900 mb-4">What "marginal validated edge" actually means</h2>
        <div className="space-y-4 text-gray-700 leading-relaxed text-[17px]">
          <p>
            <strong className="text-gray-900">It doesn't mean this always works.</strong> 55 trades
            across 3 years is statistically thin. The Sharpe of 0.556 is in range where overfitting
            is possible, even with walk-forward validation. A bad six-month stretch — a VIX regime
            that breaks historical patterns, a sharp directional move the gate doesn't catch — could
            eliminate most of the edge quickly.
          </p>
          <p>
            <strong className="text-gray-900">It doesn't mean the edge is stable going forward.</strong>{' '}
            SEBI's expiry rationalization changed the market structure significantly. Weekly options
            on a single index concentrate retail flow differently than when BankNifty, FinNifty, and
            MidCap weekly options all existed simultaneously. That structural change happened during
            our test window — we don't know whether it helped or hurt this specific strategy.
          </p>
          <p>
            <strong className="text-gray-900">It does mean the VIX gate is non-trivial.</strong>{' '}
            The 19.5pp delta on BankNifty is large. The Nifty positive Sharpe replicates the
            directional finding across a different underlying. A regime-aware premium selling
            approach appears to have some signal on Indian weekly index derivatives — even after
            realistic costs.
          </p>
          <p>
            <strong className="text-gray-900">It does mean the next step is more rigorous testing,
            not deployment.</strong> Before this graduates from Tier 2 to Tier 1, we need a clean
            walk-forward run with a hold-out test set, and earnings/FII event gate validation on
            the already-backtested window.
          </p>
        </div>

        <Divider />

        {/* ── Section 6: How we manage the signal ── */}
        <h2 className="text-xl font-bold text-gray-900 mb-4">How we're managing this in the platform</h2>
        <div className="space-y-4 text-gray-700 leading-relaxed text-[17px]">
          <p>
            The platform currently emits one Nifty weekly strangle signal per entry cycle —
            weekly, when entry conditions are met. Every signal card shows a{' '}
            <strong className="text-gray-900">T2 badge</strong>{' '}
            (Tier 2: marginal validated edge) and carries the full disclaimer.
          </p>
          <p>
            We are also testing two additional gates on the signal:
          </p>
          <ul className="list-disc ml-5 space-y-1 text-[16px]">
            <li>
              <strong>Earnings blackout:</strong> Skip entry if any Nifty 50 constituent reports
              earnings within the trade window. Earnings events cause the kind of gap risk that
              violates the strangle's range assumption.
            </li>
            <li>
              <strong>FII flow filter:</strong> Skip if FII net F&O flow has been strongly
              negative for five consecutive sessions. Large institutional outflows coincide with
              trending conditions that break the strategy's range-bound assumption.
            </li>
          </ul>
          <p>
            Both gates are being backtested against the original validated window with pre-committed
            criteria. If they improve the Sharpe without over-filtering, the signal upgrades to
            an improved Tier 2. If they don't, they're dropped.
          </p>
          <Callout type="warn">
            <strong>This signal is live but not fully validated.</strong> We send it because
            the evidence is strong enough to be directionally useful and we have no other
            way to accumulate out-of-sample data. Every signal is clearly labeled as Tier 2.
            Paper trade or allocate conservatively until walk-forward Tier 1 is confirmed.
          </Callout>
        </div>

        <Divider />

        {/* ── Subscribe ── */}
        <div className="border border-gray-200 rounded-2xl p-7 bg-gray-50 text-center">
          <p className="text-sm font-semibold text-gray-900 mb-1">Get the signal when it fires</p>
          <p className="text-sm text-gray-500 mb-5">
            Weekly Nifty strangle entry alerts, with VIX, strikes, and credit at the time of signal.
            Free Telegram channel.
          </p>
          <a
            href="https://t.me/shadowmarketai"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-block bg-trading-brand text-white text-sm font-semibold px-6 py-3 rounded-xl hover:opacity-90 transition-opacity"
          >
            Join on Telegram
          </a>
          <p className="text-xs text-gray-400 mt-4">No spam. Signals only.</p>
        </div>

        <Divider />

        {/* ── What's next ── */}
        <h2 className="text-xl font-bold text-gray-900 mb-4">What we're testing next</h2>
        <div className="space-y-4 text-gray-700 leading-relaxed text-[17px]">
          <ol className="list-decimal ml-5 space-y-3 text-[16px]">
            <li>
              <strong>Earnings/FII gate refinement</strong> — does adding the two event gates
              above push the Nifty strangle from Tier 2 to Tier 1?
            </li>
            <li>
              <strong>PSU-excluded equity signals</strong> — the pipeline test found 16 PSU stocks
              with 0% win rate across all trades. Wyckoff standalone on the remaining 74 tickers
              may have positive expectancy once government-linked stocks are removed.
            </li>
            <li>
              <strong>AI debate validator</strong> — a 6-agent adversarial debate system routes
              signals through bull/bear/judge analysis. Does it improve on the rule-based
              confluence filter (PF 0.43)?
            </li>
          </ol>
          <p>
            Every test follows the same discipline: decision criteria committed before any data
            is observed, mechanical verdict accepted regardless of outcome.
          </p>
        </div>

        <Divider />

        {/* ── Previous piece link ── */}
        <div className="border border-gray-100 rounded-xl p-5 flex items-center gap-4 hover:border-gray-200 transition-colors">
          <div className="flex-1 min-w-0">
            <p className="text-xs text-gray-400 mb-0.5">Previous research</p>
            <a href="/research/nifty-backtest" className="text-sm font-semibold text-gray-900 hover:text-trading-brand transition-colors">
              We backtested 7 popular trading strategies on Nifty 100. None had generalizable edge.
            </a>
          </div>
          <span className="text-gray-300 text-lg flex-shrink-0">→</span>
        </div>

        {/* ── Disclaimer ── */}
        <div className="mt-12 pt-8 border-t border-gray-100">
          <p className="text-xs text-gray-400 leading-relaxed">
            <strong className="text-gray-500">Research disclaimer:</strong> This article is for
            informational and educational purposes only. Past backtest results do not guarantee
            future returns. Options trading involves substantial risk of loss, including the
            potential to lose more than the initial investment. Shadow Market is not a SEBI-registered
            investment adviser. Nothing in this article constitutes investment advice. Consult a
            SEBI-registered adviser before making investment decisions.
          </p>
        </div>

      </article>
    </div>
  );
}
