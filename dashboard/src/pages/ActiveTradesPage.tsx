import { useState, useMemo } from 'react';
import { motion } from 'framer-motion';
import {
  TrendingUp,
  TrendingDown,
  ArrowUpRight,
  ArrowDownRight,
  BarChart3,
  DollarSign,
  Layers,
  Loader2,
  AlertCircle,
} from 'lucide-react';
import GlassCard from '../components/ui/GlassCard';
import MetricCard from '../components/ui/MetricCard';
import StatusBadge from '../components/ui/StatusBadge';
import ProgressBar from '../components/ui/ProgressBar';
import { cn } from '../lib/utils';
import { useTrades } from '../hooks/useTrades';
import type { ActiveTrade } from '../types';

const SEGMENT_TABS = [
  { key: 'ALL', label: 'All' },
  { key: 'NSE', label: 'NSE' },
  { key: 'NFO', label: 'F&O' },
  { key: 'MCX', label: 'MCX' },
  { key: 'CDS', label: 'CDS' },
] as const;

function getProgressValues(trade: ActiveTrade): { current: number; min: number; max: number } {
  if (trade.direction === 'LONG' || trade.direction === 'BUY') {
    return { current: trade.current_price, min: trade.stop_loss, max: trade.target };
  }
  return { current: trade.current_price, min: trade.target, max: trade.stop_loss };
}

export default function ActiveTradesPage() {
  const { trades, loading, error } = useTrades();
  const [activeSegment, setActiveSegment] = useState<string>('ALL');

  const filteredTrades = useMemo(() => {
    if (activeSegment === 'ALL') return trades;
    return trades.filter((t) => (t.exchange || 'NSE') === activeSegment);
  }, [trades, activeSegment]);

  const segmentCounts = useMemo(() => {
    const counts: Record<string, number> = { ALL: trades.length };
    for (const t of trades) {
      const ex = t.exchange || 'NSE';
      counts[ex] = (counts[ex] || 0) + 1;
    }
    return counts;
  }, [trades]);

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <div className="w-12 h-12 rounded-2xl bg-violet-50 text-trading-ai flex items-center justify-center">
          <Loader2 size={24} className="text-trading-ai animate-spin" />
        </div>
        <p className="text-slate-500 text-xs mt-4 font-mono">Loading active trades...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <div className="w-12 h-12 rounded-2xl bg-amber-50 flex items-center justify-center mb-4">
          <AlertCircle size={24} className="text-trading-alert" />
        </div>
        <p className="text-slate-500 text-xs">{error}</p>
      </div>
    );
  }

  if (trades.length === 0) {
    return (
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-5">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <MetricCard title="Total Positions" value={0} icon={Layers} color="info" />
          <MetricCard title="Avg RRR" value="--" icon={BarChart3} color="ai" />
          <MetricCard title="Unrealized P&L" value="--" icon={DollarSign} color="info" />
        </div>
        <GlassCard className="flex flex-col items-center justify-center py-16">
          <div className="w-12 h-12 rounded-2xl bg-slate-100 flex items-center justify-center mb-4">
            <Layers size={24} className="text-slate-400" />
          </div>
          <p className="text-slate-500 text-xs">No active trades</p>
          <p className="text-slate-500 text-[10px] mt-1">Trades will appear here when signals are executed</p>
        </GlassCard>
      </motion.div>
    );
  }

  const totalPositions = filteredTrades.length;
  const avgRRR = totalPositions > 0 ? filteredTrades.reduce((sum, t) => sum + t.prrr, 0) / totalPositions : 0;
  const totalPnlPct = filteredTrades.reduce((sum, t) => sum + t.pnl_pct, 0);

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.4 }}
      className="space-y-5"
    >
      {/* Segment Filter */}
      <div className="flex items-center gap-1.5">
        {SEGMENT_TABS.map(({ key, label }) => {
          const count = segmentCounts[key] || 0;
          const isActive = activeSegment === key;
          return (
            <button
              key={key}
              onClick={() => setActiveSegment(key)}
              className={cn(
                'flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium transition-all duration-200',
                isActive
                  ? 'bg-violet-50 text-trading-ai-light border border-violet-200'
                  : 'text-slate-600 hover:text-slate-900 hover:bg-slate-50'
              )}
            >
              {label}
              {count > 0 && (
                <span className={cn(
                  'text-[9px] font-mono px-1.5 py-0.5 rounded-md',
                  isActive ? 'bg-trading-ai/15 text-trading-ai-light' : 'bg-slate-50 text-slate-600'
                )}>
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <MetricCard title="Total Positions" value={totalPositions} icon={Layers} color="info" />
        <MetricCard title="Avg RRR" value={avgRRR.toFixed(2)} icon={BarChart3} color="ai" />
        <MetricCard
          title="Unrealized P&L"
          value={`${totalPnlPct >= 0 ? '+' : ''}${totalPnlPct.toFixed(2)}%`}
          change={totalPnlPct}
          icon={DollarSign}
          color={totalPnlPct >= 0 ? 'bull' : 'bear'}
        />
      </div>

      {/* Trades Table */}
      <GlassCard className="!p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[9px] text-slate-500 uppercase tracking-[0.12em] border-b border-slate-200">
                <th className="text-left py-3.5 px-3 md:px-4">Ticker</th>
                <th className="text-center py-3.5 px-2 hidden md:table-cell">Exch</th>
                <th className="text-center py-3.5 px-2 hidden lg:table-cell">TF</th>
                <th className="text-center py-3.5 px-2">Dir</th>
                <th className="text-right py-3.5 px-2 font-mono">Entry</th>
                <th className="text-right py-3.5 px-2 font-mono hidden lg:table-cell">SL</th>
                <th className="text-right py-3.5 px-2 font-mono hidden lg:table-cell">Target</th>
                <th className="text-center py-3.5 px-2 font-mono hidden lg:table-cell">PRRR</th>
                <th className="text-right py-3.5 px-2 font-mono hidden md:table-cell">Current</th>
                <th className="text-center py-3.5 px-2 font-mono hidden lg:table-cell">CRRR</th>
                <th className="text-right py-3.5 px-2 font-mono">P&L%</th>
                <th className="text-center py-3.5 px-2 w-32 hidden md:table-cell">Progress</th>
              </tr>
            </thead>
            <tbody>
              {filteredTrades.map((trade, idx) => {
                const isProfit = trade.pnl_pct >= 0;
                const progressValues = getProgressValues(trade);

                return (
                  <motion.tr
                    key={trade.id}
                    initial={{ opacity: 0, x: -8 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ duration: 0.25, delay: idx * 0.03 }}
                    className={cn(
                      'border-b border-slate-200 hover:bg-slate-50 transition-colors',
                      trade.alert_sent && 'bg-trading-alert/[0.03]'
                    )}
                  >
                    <td className="py-3 px-3 md:px-4">
                      <div className="flex items-center gap-2">
                        <span className="font-mono font-bold text-slate-900 text-sm">{trade.ticker}</span>
                        {trade.alert_sent && (
                          <span className="w-1.5 h-1.5 rounded-full bg-trading-alert animate-pulse-live" />
                        )}
                      </div>
                    </td>
                    <td className="py-3 px-2 text-center hidden md:table-cell">
                      <span className={cn(
                        'text-[9px] font-mono font-bold px-1.5 py-0.5 rounded-md border',
                        trade.exchange === 'MCX' ? 'bg-amber-500/8 text-amber-400 border-amber-500/15' :
                        trade.exchange === 'NFO' ? 'bg-purple-500/8 text-purple-400 border-purple-500/15' :
                        trade.exchange === 'CDS' ? 'bg-emerald-500/8 text-emerald-400 border-emerald-500/15' :
                        'bg-blue-500/8 text-blue-400 border-blue-500/15'
                      )}>
                        {trade.exchange || 'NSE'}
                      </span>
                    </td>
                    <td className="py-3 px-2 text-center hidden lg:table-cell">
                      <span className="text-[9px] font-mono text-slate-400 bg-slate-50 px-1.5 py-0.5 rounded-md border border-slate-200">
                        {trade.timeframe || '1D'}
                      </span>
                    </td>
                    <td className="py-3 px-2 text-center">
                      <div className={cn(
                        'inline-flex items-center gap-0.5 text-[10px] font-bold',
                        (trade.direction === 'LONG' || trade.direction === 'BUY') ? 'text-trading-bull' : 'text-trading-bear'
                      )}>
                        {(trade.direction === 'LONG' || trade.direction === 'BUY') ? <ArrowUpRight size={11} /> : <ArrowDownRight size={11} />}
                        {(trade.direction === 'LONG' || trade.direction === 'BUY') ? 'L' : 'S'}
                      </div>
                    </td>
                    <td className="py-3 px-2 text-right font-mono text-slate-600 text-xs tabular-nums">{trade.entry_price.toFixed(2)}</td>
                    <td className="py-3 px-2 text-right font-mono text-trading-bear/70 text-xs tabular-nums hidden lg:table-cell">{trade.stop_loss.toFixed(2)}</td>
                    <td className="py-3 px-2 text-right font-mono text-trading-bull/70 text-xs tabular-nums hidden lg:table-cell">{trade.target.toFixed(2)}</td>
                    <td className="py-3 px-2 text-center font-mono text-trading-info text-xs tabular-nums hidden lg:table-cell">{trade.prrr.toFixed(1)}</td>
                    <td className="py-3 px-2 text-right font-mono font-semibold text-slate-900 text-xs tabular-nums hidden md:table-cell">{trade.current_price.toFixed(2)}</td>
                    <td className="py-3 px-2 text-center font-mono text-trading-ai text-xs tabular-nums hidden lg:table-cell">{trade.crrr.toFixed(2)}</td>
                    <td className={cn('py-3 px-2 text-right font-mono font-bold text-xs tabular-nums', isProfit ? 'text-trading-bull' : 'text-trading-bear')}>
                      <div className="flex items-center justify-end gap-1">
                        {isProfit ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
                        {isProfit ? '+' : ''}{trade.pnl_pct.toFixed(2)}%
                      </div>
                    </td>
                    <td className="py-3 px-2 hidden md:table-cell">
                      <ProgressBar
                        current={progressValues.current}
                        min={progressValues.min}
                        max={progressValues.max}
                        isShort={trade.direction === 'SHORT' || trade.direction === 'SELL'}
                        pnlPct={trade.pnl_pct}
                      />
                    </td>
                  </motion.tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Summary Row */}
        <div className="flex items-center justify-between py-4 px-4 border-t border-slate-200 bg-slate-50">
          <div className="flex items-center gap-6">
            <div>
              <span className="text-[9px] text-slate-500 uppercase tracking-wider">Positions </span>
              <span className="text-xs font-mono font-bold text-slate-900">{totalPositions}</span>
            </div>
            <div>
              <span className="text-[9px] text-slate-500 uppercase tracking-wider">Avg RRR </span>
              <span className="text-xs font-mono font-bold text-trading-info">{avgRRR.toFixed(2)}</span>
            </div>
          </div>
          <div>
            <span className="text-[9px] text-slate-500 uppercase tracking-wider">Total Unrealized </span>
            <span className={cn('text-xs font-mono font-bold', totalPnlPct >= 0 ? 'text-trading-bull' : 'text-trading-bear')}>
              {totalPnlPct >= 0 ? '+' : ''}{totalPnlPct.toFixed(2)}%
            </span>
          </div>
        </div>
      </GlassCard>

      {/* Legend */}
      <div className="flex items-center gap-4 text-[10px] text-slate-500">
        <div className="flex items-center gap-1.5">
          <StatusBadge status="OPEN" size="sm" />
          <span>Active</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-trading-alert animate-pulse-live" />
          <span>Alert Triggered</span>
        </div>
      </div>

      <p className="sebi-disclaimer mt-4">
        This platform provides AI-powered market analytics and decision support tools for educational purposes only.
        Not SEBI-registered investment advice. Past performance is not indicative of future results.
        Consult a SEBI-registered financial advisor before making investment decisions.
      </p>
    </motion.div>
  );
}
