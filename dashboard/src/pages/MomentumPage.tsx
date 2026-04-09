import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Rocket,
  RefreshCw,
  Loader2,
  AlertCircle,
  TrendingUp,
  Minus,
  ArrowUpRight,
  ArrowDownRight,
  ShoppingCart,
  XCircle,
  Clock,
} from 'lucide-react';
import GlassCard from '../components/ui/GlassCard';
import { cn } from '../lib/utils';
import { useMomentum } from '../hooks/useMomentum';
import type { MomentumStock, RebalanceSignal } from '../types';

function RankChange({ current, prev }: { current: number; prev: number | null }) {
  if (prev === null) {
    return <span className="text-[10px] text-trading-ai font-mono font-bold">NEW</span>;
  }
  const diff = prev - current; // positive means improved
  if (diff > 0) {
    return (
      <span className="flex items-center gap-0.5 text-trading-bull text-xs font-mono tabular-nums">
        <ArrowUpRight size={12} />
        {diff}
      </span>
    );
  }
  if (diff < 0) {
    return (
      <span className="flex items-center gap-0.5 text-trading-bear text-xs font-mono tabular-nums">
        <ArrowDownRight size={12} />
        {Math.abs(diff)}
      </span>
    );
  }
  return <Minus size={12} className="text-slate-500" />;
}

function ScoreBar({ score }: { score: number }) {
  const pct = Math.min(score * 100, 100);
  return (
    <div className="w-20 h-1.5 bg-trading-card rounded-full overflow-hidden">
      <div
        className="h-full rounded-full bg-gradient-to-r from-trading-ai to-trading-ai-light"
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

function ReturnCell({ value }: { value: number }) {
  const positive = value >= 0;
  return (
    <span
      className={cn(
        'font-mono text-xs tabular-nums',
        positive ? 'text-trading-bull' : 'text-trading-bear',
      )}
    >
      {positive ? '+' : ''}
      {value.toFixed(1)}%
    </span>
  );
}

function RankingsTable({ rankings }: { rankings: MomentumStock[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-[9px] uppercase tracking-[0.12em] text-slate-500 border-b border-trading-border/15">
            <th className="py-2.5 px-2 md:px-3 text-left">#</th>
            <th className="py-2.5 px-2 text-center w-12"></th>
            <th className="py-2.5 px-2 md:px-3 text-left">Symbol</th>
            <th className="py-2.5 px-3 text-left hidden md:table-cell">Sector</th>
            <th className="py-2.5 px-2 md:px-3 text-left">Score</th>
            <th className="py-2.5 px-2 md:px-3 text-right">3M</th>
            <th className="py-2.5 px-3 text-right hidden md:table-cell">6M</th>
            <th className="py-2.5 px-2 md:px-3 text-right">12M</th>
            <th className="py-2.5 px-3 text-right hidden md:table-cell">Vol</th>
          </tr>
        </thead>
        <tbody>
          <AnimatePresence>
            {rankings.map((stock) => (
              <motion.tr
                key={stock.ticker}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0 }}
                className="border-b border-trading-border/15 hover:bg-white/[0.015] transition-colors"
              >
                <td className="py-2.5 px-2 md:px-3 font-mono font-bold text-white tabular-nums">{stock.rank}</td>
                <td className="py-2.5 px-2 text-center">
                  <RankChange current={stock.rank} prev={stock.prev_rank} />
                </td>
                <td className="py-2.5 px-2 md:px-3 font-medium text-white">{stock.ticker}</td>
                <td className="py-2.5 px-3 hidden md:table-cell">
                  <span className="text-xs text-slate-400 bg-trading-card/50 px-2 py-0.5 rounded">
                    {stock.sector}
                  </span>
                </td>
                <td className="py-2.5 px-2 md:px-3">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs text-white tabular-nums">{stock.score.toFixed(3)}</span>
                    <ScoreBar score={stock.score} />
                  </div>
                </td>
                <td className="py-2.5 px-2 md:px-3 text-right"><ReturnCell value={stock.ret_3m} /></td>
                <td className="py-2.5 px-3 text-right hidden md:table-cell"><ReturnCell value={stock.ret_6m} /></td>
                <td className="py-2.5 px-2 md:px-3 text-right"><ReturnCell value={stock.ret_12m} /></td>
                <td className="py-2.5 px-3 text-right hidden md:table-cell">
                  <span className="font-mono text-xs text-slate-400 tabular-nums">{stock.volatility.toFixed(1)}%</span>
                </td>
              </motion.tr>
            ))}
          </AnimatePresence>
        </tbody>
      </table>
    </div>
  );
}

function SignalCard({ signal }: { signal: RebalanceSignal }) {
  const isBuy = signal.action === 'BUY';
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ ease: [0.16, 1, 0.3, 1] }}
      className={cn(
        'glass-card p-4 border-l-2',
        isBuy ? 'border-l-trading-bull' : 'border-l-trading-bear',
      )}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          {isBuy ? (
            <ShoppingCart size={14} className="text-trading-bull" />
          ) : (
            <XCircle size={14} className="text-trading-bear" />
          )}
          <span className="font-medium text-white">{signal.ticker}</span>
        </div>
        <span
          className={cn(
            'px-2 py-0.5 rounded-xl text-[10px] font-mono font-bold border',
            isBuy
              ? 'bg-trading-bull/10 text-trading-bull border-trading-bull/30'
              : 'bg-trading-bear/10 text-trading-bear border-trading-bear/30',
          )}
        >
          {signal.action}
        </span>
      </div>
      <p className="text-xs text-slate-400">{signal.reason}</p>
      <div className="flex items-center gap-2 mt-1.5">
        <span className="text-[10px] text-slate-500 bg-trading-card/50 px-1.5 py-0.5 rounded">
          {signal.sector}
        </span>
        {signal.score > 0 && (
          <span className="text-[10px] text-slate-500 font-mono tabular-nums">
            Score: {signal.score.toFixed(3)}
          </span>
        )}
      </div>
    </motion.div>
  );
}

function formatRankedAt(dateStr: string | null): string {
  if (!dateStr) return 'Never';
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return dateStr;
    const now = new Date();
    const diffMs = now.getTime() - d.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHrs = Math.floor(diffMins / 60);
    if (diffHrs < 24) return `${diffHrs}h ago`;
    const diffDays = Math.floor(diffHrs / 24);
    return `${diffDays}d ago`;
  } catch {
    return dateStr;
  }
}

export default function MomentumPage() {
  const [topN, setTopN] = useState(10);
  const { data, loading, rebalancing, error, refresh, triggerRebalance } = useMomentum();

  const rankings = data?.rankings || [];
  const signals = data?.signals || [];
  const holdings = data?.holdings || [];
  const buySignals = signals.filter((s) => s.action === 'BUY');
  const sellSignals = signals.filter((s) => s.action === 'SELL');

  if (loading && !data) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <div className="w-12 h-12 rounded-2xl bg-trading-ai/10 flex items-center justify-center mb-4">
          <Loader2 size={24} className="text-trading-ai animate-spin" />
        </div>
        <p className="text-slate-400 text-sm">Loading momentum data...</p>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <div className="w-12 h-12 rounded-2xl bg-slate-800/50 flex items-center justify-center mb-4">
          <AlertCircle size={24} className="text-trading-alert" />
        </div>
        <p className="text-slate-400 text-sm">Failed to load: {error}</p>
        <button onClick={refresh} className="mt-4 text-trading-ai text-sm hover:underline">
          Retry
        </button>
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      className="space-y-5"
    >
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Rocket size={20} className="text-trading-ai" />
          <h2 className="text-lg font-semibold text-white">Momentum Ranking</h2>
          {data?.ranked_at && (
            <span className="flex items-center gap-1 text-[10px] text-slate-500 font-mono">
              <Clock size={10} />
              {formatRankedAt(data.ranked_at)}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {/* Top N selector */}
          <div className="flex items-center gap-1">
            {[5, 10, 15, 20].map((n) => (
              <button
                key={n}
                onClick={() => setTopN(n)}
                className={cn(
                  'px-2 py-1 rounded-xl text-xs font-mono transition-colors',
                  topN === n
                    ? 'bg-trading-card text-white border border-trading-ai/30'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-trading-bg-secondary/50',
                )}
              >
                Top {n}
              </button>
            ))}
          </div>

          <div className="w-px h-5 bg-trading-border/30 hidden sm:block" />

          <button
            onClick={() => triggerRebalance(topN)}
            disabled={rebalancing}
            className={cn(
              'flex items-center gap-1.5 px-4 py-1.5 rounded-xl text-xs font-medium transition-all',
              rebalancing
                ? 'bg-trading-ai/20 text-trading-ai-light cursor-wait'
                : 'bg-trading-ai/8 text-trading-ai-light hover:bg-trading-ai/12 border border-trading-ai/15',
            )}
          >
            {rebalancing ? (
              <>
                <Loader2 size={14} className="animate-spin" />
                Scanning (~60s)...
              </>
            ) : (
              <>
                <RefreshCw size={14} />
                Trigger Rebalance
              </>
            )}
          </button>
        </div>
      </div>

      {/* Stats row */}
      {rankings.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <GlassCard className="!p-3 text-center">
            <p className="stat-label">Ranked</p>
            <p className="text-xl font-mono font-bold text-white tabular-nums">{rankings.length}</p>
          </GlassCard>
          <GlassCard className="!p-3 text-center">
            <p className="stat-label">Holdings</p>
            <p className="text-xl font-mono font-bold text-white tabular-nums">{holdings.length}</p>
          </GlassCard>
          <GlassCard className="!p-3 text-center" glowColor="bull">
            <p className="stat-label">Buy Signals</p>
            <p className="text-xl font-mono font-bold text-trading-bull tabular-nums">{buySignals.length}</p>
          </GlassCard>
          <GlassCard className="!p-3 text-center" glowColor="bear">
            <p className="stat-label">Sell Signals</p>
            <p className="text-xl font-mono font-bold text-trading-bear tabular-nums">{sellSignals.length}</p>
          </GlassCard>
        </div>
      )}

      {/* Rankings Table */}
      {rankings.length > 0 ? (
        <GlassCard className="!p-0 overflow-hidden">
          <div className="px-4 py-3 border-b border-trading-border/30 flex items-center gap-2">
            <TrendingUp size={14} className="text-trading-ai" />
            <span className="text-sm font-medium text-white">Top {rankings.length} by Momentum Score</span>
          </div>
          <RankingsTable rankings={rankings} />
        </GlassCard>
      ) : (
        <GlassCard className="text-center py-12">
          <div className="w-12 h-12 rounded-2xl bg-slate-800/50 flex items-center justify-center mx-auto mb-3">
            <Rocket size={24} className="text-slate-600" />
          </div>
          <p className="text-slate-400 text-sm mb-1">No momentum rankings yet</p>
          <p className="text-slate-500 text-xs">
            Click "Trigger Rebalance" to scan the NSE universe and generate rankings.
          </p>
        </GlassCard>
      )}

      {/* Rebalance Signals */}
      {signals.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-white">Rebalance Signals</span>
            <span className="text-[10px] text-slate-500 font-mono tabular-nums">
              {buySignals.length} BUY / {sellSignals.length} SELL
            </span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {signals.map((signal) => (
              <SignalCard key={`${signal.action}-${signal.ticker}`} signal={signal} />
            ))}
          </div>
        </div>
      )}

      {/* Current Holdings */}
      {holdings.length > 0 && (
        <GlassCard className="!p-4">
          <p className="stat-label mb-2">Current Portfolio</p>
          <div className="flex flex-wrap gap-2">
            {holdings.map((ticker) => (
              <span
                key={ticker}
                className="px-2.5 py-1 rounded-xl text-xs font-medium text-white bg-trading-card border border-trading-border/20"
              >
                {ticker}
              </span>
            ))}
          </div>
        </GlassCard>
      )}

      {/* Error display */}
      {error && (
        <div className="flex items-center gap-2 px-4 py-2 rounded-lg bg-trading-bear/10 border border-trading-bear/20">
          <AlertCircle size={14} className="text-trading-bear" />
          <span className="text-xs text-trading-bear">{error}</span>
        </div>
      )}

      {/* Footer */}
      <p className="text-center text-[10px] text-slate-600">
        Score = 0.4 x 12M + 0.3 x 6M + 0.2 x 3M + 0.1 x InvVol | Min-max normalized | Rebalance monthly
      </p>
    </motion.div>
  );
}
