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

function getProgressValues(trade: ActiveTrade): { current: number; min: number; max: number } {
  if (trade.direction === 'LONG') {
    return { current: trade.current_price, min: trade.stop_loss, max: trade.target };
  }
  return { current: trade.current_price, min: trade.target, max: trade.stop_loss };
}

export default function ActiveTradesPage() {
  const { trades, loading, error } = useTrades();

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <Loader2 size={48} className="text-trading-ai animate-spin mb-4" />
        <p className="text-slate-400 text-sm">Loading active trades...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <AlertCircle size={48} className="text-trading-alert mb-4" />
        <p className="text-slate-400 text-sm">Failed to load trades: {error}</p>
      </div>
    );
  }

  if (trades.length === 0) {
    return (
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-6">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <MetricCard title="Total Positions" value={0} icon={Layers} color="info" />
          <MetricCard title="Avg RRR" value="--" icon={BarChart3} color="ai" />
          <MetricCard title="Unrealized P&L" value="--" icon={DollarSign} color="info" />
        </div>
        <GlassCard className="flex flex-col items-center justify-center py-16">
          <Layers size={48} className="text-slate-600 mb-4" />
          <p className="text-slate-500 text-sm">No active trades</p>
          <p className="text-slate-600 text-xs mt-1">Trades will appear here when signals are executed</p>
        </GlassCard>
      </motion.div>
    );
  }

  const totalPositions = trades.length;
  const avgRRR = trades.reduce((sum, t) => sum + t.prrr, 0) / totalPositions;
  const totalPnlPct = trades.reduce((sum, t) => sum + t.pnl_pct, 0);

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.4 }}
      className="space-y-6"
    >
      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <MetricCard
          title="Total Positions"
          value={totalPositions}
          icon={Layers}
          color="info"
        />
        <MetricCard
          title="Avg RRR"
          value={avgRRR.toFixed(2)}
          icon={BarChart3}
          color="ai"
        />
        <MetricCard
          title="Unrealized P&L"
          value={`${totalPnlPct >= 0 ? '+' : ''}${totalPnlPct.toFixed(2)}%`}
          change={totalPnlPct}
          icon={DollarSign}
          color={totalPnlPct >= 0 ? 'bull' : 'bear'}
        />
      </div>

      {/* Trades Table */}
      <GlassCard>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-slate-500 uppercase tracking-wider border-b border-trading-border">
                <th className="text-left py-3 px-3">Ticker</th>
                <th className="text-center py-3 px-2">Exch</th>
                <th className="text-center py-3 px-2">TF</th>
                <th className="text-center py-3 px-2">Dir</th>
                <th className="text-right py-3 px-2 font-mono">Entry</th>
                <th className="text-right py-3 px-2 font-mono">SL</th>
                <th className="text-right py-3 px-2 font-mono">Target</th>
                <th className="text-center py-3 px-2 font-mono">PRRR</th>
                <th className="text-right py-3 px-2 font-mono">Current</th>
                <th className="text-center py-3 px-2 font-mono">CRRR</th>
                <th className="text-right py-3 px-2 font-mono">P&L%</th>
                <th className="text-center py-3 px-2 w-32">Progress</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-trading-border/50">
              {trades.map((trade, idx) => {
                const isProfit = trade.pnl_pct >= 0;
                const progressValues = getProgressValues(trade);

                return (
                  <motion.tr
                    key={trade.id}
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ duration: 0.2, delay: idx * 0.05 }}
                    className={cn(
                      'hover:bg-slate-800/30 transition-colors',
                      trade.alert_sent && 'bg-trading-alert/5'
                    )}
                  >
                    <td className="py-3 px-3">
                      <div className="flex items-center gap-2">
                        <span className="font-mono font-bold text-white">{trade.ticker}</span>
                        {trade.alert_sent && (
                          <span className="w-1.5 h-1.5 rounded-full bg-trading-alert animate-pulse" />
                        )}
                      </div>
                    </td>
                    <td className="py-3 px-2 text-center">
                      <span className={cn(
                        'text-[10px] font-mono font-semibold px-1.5 py-0.5 rounded border',
                        trade.exchange === 'MCX' ? 'bg-amber-500/15 text-amber-400 border-amber-500/20' :
                        trade.exchange === 'NFO' ? 'bg-purple-500/15 text-purple-400 border-purple-500/20' :
                        trade.exchange === 'CDS' ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/20' :
                        'bg-blue-500/15 text-blue-400 border-blue-500/20'
                      )}>
                        {trade.exchange || 'NSE'}
                      </span>
                    </td>
                    <td className="py-3 px-2 text-center">
                      <span className="text-[10px] font-mono text-slate-500 bg-slate-800 px-1.5 py-0.5 rounded">
                        {trade.timeframe || '1D'}
                      </span>
                    </td>
                    <td className="py-3 px-2 text-center">
                      <div className={cn(
                        'inline-flex items-center gap-0.5 text-xs font-bold',
                        trade.direction === 'LONG' ? 'text-trading-bull' : 'text-trading-bear'
                      )}>
                        {trade.direction === 'LONG' ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}
                        {trade.direction === 'LONG' ? 'L' : 'S'}
                      </div>
                    </td>
                    <td className="py-3 px-2 text-right font-mono text-slate-300">
                      {trade.entry_price.toFixed(2)}
                    </td>
                    <td className="py-3 px-2 text-right font-mono text-trading-bear">
                      {trade.stop_loss.toFixed(2)}
                    </td>
                    <td className="py-3 px-2 text-right font-mono text-trading-bull">
                      {trade.target.toFixed(2)}
                    </td>
                    <td className="py-3 px-2 text-center font-mono text-trading-info">
                      {trade.prrr.toFixed(1)}
                    </td>
                    <td className="py-3 px-2 text-right font-mono font-semibold text-white">
                      {trade.current_price.toFixed(2)}
                    </td>
                    <td className="py-3 px-2 text-center font-mono text-trading-ai">
                      {trade.crrr.toFixed(2)}
                    </td>
                    <td className={cn(
                      'py-3 px-2 text-right font-mono font-bold',
                      isProfit ? 'text-trading-bull' : 'text-trading-bear'
                    )}>
                      <div className="flex items-center justify-end gap-1">
                        {isProfit ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
                        {isProfit ? '+' : ''}{trade.pnl_pct.toFixed(2)}%
                      </div>
                    </td>
                    <td className="py-3 px-2">
                      <ProgressBar
                        current={progressValues.current}
                        min={progressValues.min}
                        max={progressValues.max}
                      />
                    </td>
                  </motion.tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Summary Row */}
        <div className="flex items-center justify-between pt-4 mt-4 border-t border-trading-border px-3">
          <div className="flex items-center gap-6">
            <div>
              <span className="text-xs text-slate-500">Positions: </span>
              <span className="text-sm font-mono font-bold text-white">{totalPositions}</span>
            </div>
            <div>
              <span className="text-xs text-slate-500">Avg RRR: </span>
              <span className="text-sm font-mono font-bold text-trading-info">{avgRRR.toFixed(2)}</span>
            </div>
          </div>
          <div>
            <span className="text-xs text-slate-500">Total Unrealized: </span>
            <span className={cn(
              'text-sm font-mono font-bold',
              totalPnlPct >= 0 ? 'text-trading-bull' : 'text-trading-bear'
            )}>
              {totalPnlPct >= 0 ? '+' : ''}{totalPnlPct.toFixed(2)}%
            </span>
          </div>
        </div>
      </GlassCard>

      {/* Trade Status Legend */}
      <div className="flex items-center gap-4 text-xs text-slate-500">
        <div className="flex items-center gap-1.5">
          <StatusBadge status="OPEN" size="sm" />
          <span>Active</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-trading-alert animate-pulse" />
          <span>Alert Triggered</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-trading-bull">Green = Profit</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-trading-bear">Red = Loss</span>
        </div>
      </div>
    </motion.div>
  );
}
