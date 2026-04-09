import { motion } from 'framer-motion';
import {
  Target,
  Trophy,
  TrendingUp,
  TrendingDown,
  BarChart3,
  DollarSign,
  Loader2,
  AlertCircle,
} from 'lucide-react';
import GlassCard from '../components/ui/GlassCard';
import MetricCard from '../components/ui/MetricCard';
import { cn } from '../lib/utils';
import { useAccuracy } from '../hooks/useAccuracy';
import type { PatternAccuracy, DirectionAccuracy, MonthlyPnL } from '../types';

// --- Donut Chart (SVG) ---
interface DonutChartProps {
  wins: number;
  losses: number;
  open: number;
}

function DonutChart({ wins, losses, open }: DonutChartProps) {
  const total = wins + losses + open;
  if (total === 0) {
    return (
      <div className="relative flex items-center justify-center">
        <svg width="200" height="200" viewBox="0 0 200 200">
          <circle cx="100" cy="100" r="80" fill="none" stroke="#334155" strokeWidth="20" />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-3xl font-mono font-bold text-slate-500">--</span>
          <span className="text-xs text-slate-500 uppercase">No Data</span>
        </div>
      </div>
    );
  }

  const winAngle = (wins / total) * 360;
  const lossAngle = (losses / total) * 360;
  const openAngle = (open / total) * 360;

  function polarToCartesian(cx: number, cy: number, r: number, angleDeg: number) {
    const angleRad = ((angleDeg - 90) * Math.PI) / 180;
    return { x: cx + r * Math.cos(angleRad), y: cy + r * Math.sin(angleRad) };
  }

  function describeArc(cx: number, cy: number, r: number, startAngle: number, endAngle: number) {
    const start = polarToCartesian(cx, cy, r, endAngle);
    const end = polarToCartesian(cx, cy, r, startAngle);
    const largeArc = endAngle - startAngle > 180 ? 1 : 0;
    return `M ${start.x} ${start.y} A ${r} ${r} 0 ${largeArc} 0 ${end.x} ${end.y}`;
  }

  const r = 80;
  const cx = 100;
  const cy = 100;
  const strokeWidth = 20;
  const winRate = wins + losses > 0 ? ((wins / (wins + losses)) * 100).toFixed(1) : '0';

  return (
    <div className="relative flex items-center justify-center">
      <svg width="200" height="200" viewBox="0 0 200 200">
        {winAngle > 0.5 && (
          <path
            d={describeArc(cx, cy, r, 0, winAngle)}
            fill="none"
            stroke="#10B981"
            strokeWidth={strokeWidth}
            strokeLinecap="round"
          />
        )}
        {lossAngle > 0.5 && (
          <path
            d={describeArc(cx, cy, r, winAngle, winAngle + lossAngle)}
            fill="none"
            stroke="#F43F5E"
            strokeWidth={strokeWidth}
            strokeLinecap="round"
          />
        )}
        {openAngle > 0.5 && (
          <path
            d={describeArc(cx, cy, r, winAngle + lossAngle, winAngle + lossAngle + openAngle)}
            fill="none"
            stroke="#F59E0B"
            strokeWidth={strokeWidth}
            strokeLinecap="round"
          />
        )}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-3xl font-mono font-bold text-white tabular-nums">{winRate}%</span>
        <span className="text-xs text-slate-500 uppercase">Win Rate</span>
      </div>
    </div>
  );
}

// --- Pattern Row ---
function PatternRow({ pattern, index }: { pattern: PatternAccuracy; index: number }) {
  const barWidth = (pattern.win_rate / 100) * 100;
  const barColor = pattern.win_rate >= 70 ? 'bg-trading-bull' : pattern.win_rate >= 50 ? 'bg-trading-alert' : 'bg-trading-bear';

  return (
    <motion.tr
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: index * 0.05, ease: [0.16, 1, 0.3, 1] }}
      className="hover:bg-white/[0.015] transition-colors"
    >
      <td className="py-2.5 px-3 font-medium text-slate-200 border-b border-trading-border/15">{pattern.pattern}</td>
      <td className="py-2.5 px-3 text-center font-mono font-medium text-slate-400 tabular-nums border-b border-trading-border/15">{pattern.total}</td>
      <td className="py-2.5 px-3 text-center font-mono font-medium text-trading-bull tabular-nums border-b border-trading-border/15">{pattern.wins}</td>
      <td className="py-2.5 px-3 border-b border-trading-border/15">
        <div className="flex items-center gap-2">
          <div className="flex-1 h-2 bg-trading-bg-secondary rounded-full overflow-hidden">
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: `${barWidth}%` }}
              transition={{ duration: 0.6, delay: index * 0.05, ease: [0.16, 1, 0.3, 1] }}
              className={cn('h-full rounded-full', barColor)}
            />
          </div>
          <span className={cn(
            'text-xs font-mono font-bold w-12 text-right tabular-nums',
            pattern.win_rate >= 70 ? 'text-trading-bull' : pattern.win_rate >= 50 ? 'text-trading-alert' : 'text-trading-bear'
          )}>
            {pattern.win_rate.toFixed(1)}%
          </span>
        </div>
      </td>
    </motion.tr>
  );
}

// --- Direction Comparison ---
function DirectionComparison({ directions }: { directions: DirectionAccuracy[] }) {
  const longDir = directions.find((d) => d.direction === 'LONG');
  const shortDir = directions.find((d) => d.direction === 'SHORT');

  return (
    <div className="grid grid-cols-2 gap-3">
      {longDir && (
        <div className="p-4 rounded-xl bg-trading-bull/[0.04] border border-trading-bull/15 text-center space-y-2">
          <TrendingUp size={24} className="text-trading-bull mx-auto" />
          <p className="stat-label">Long</p>
          <p className="text-2xl font-mono font-bold text-trading-bull tabular-nums">{longDir.win_rate.toFixed(1)}%</p>
          <p className="text-xs text-slate-400 font-mono tabular-nums">{longDir.wins}/{longDir.total} trades</p>
        </div>
      )}
      {shortDir && (
        <div className="p-4 rounded-xl bg-trading-bear/[0.04] border border-trading-bear/15 text-center space-y-2">
          <TrendingDown size={24} className="text-trading-bear mx-auto" />
          <p className="stat-label">Short</p>
          <p className="text-2xl font-mono font-bold text-trading-bear tabular-nums">{shortDir.win_rate.toFixed(1)}%</p>
          <p className="text-xs text-slate-400 font-mono tabular-nums">{shortDir.wins}/{shortDir.total} trades</p>
        </div>
      )}
      {!longDir && !shortDir && (
        <div className="col-span-2 text-center py-4 text-slate-500 text-sm">No direction data yet</div>
      )}
    </div>
  );
}

// --- Monthly PnL Bar ---
function MonthlyPnLBar({ month, index, maxPnl }: { month: MonthlyPnL; index: number; maxPnl: number }) {
  const isPositive = month.pnl >= 0;
  const barHeight = maxPnl > 0 ? Math.min(100, (Math.abs(month.pnl) / maxPnl) * 100) : 0;

  return (
    <motion.div
      initial={{ opacity: 0, scaleY: 0 }}
      animate={{ opacity: 1, scaleY: 1 }}
      transition={{ delay: index * 0.1, duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      style={{ transformOrigin: 'bottom' }}
      className="flex flex-col items-center gap-1"
    >
      <span className={cn(
        'text-[10px] font-mono font-bold tabular-nums',
        isPositive ? 'text-trading-bull' : 'text-trading-bear'
      )}>
        {isPositive ? '+' : ''}{(month.pnl / 1000).toFixed(1)}K
      </span>
      <div className="w-8 h-24 bg-trading-bg-secondary rounded-t relative flex items-end">
        <div
          className={cn(
            'w-full rounded-t transition-all',
            isPositive ? 'bg-trading-bull/60' : 'bg-trading-bear/60'
          )}
          style={{ height: `${barHeight}%` }}
        />
      </div>
      <span className="text-[9px] text-slate-500 whitespace-nowrap">{month.month.split(' ')[0]}</span>
      <span className="text-[9px] text-slate-600 font-mono tabular-nums">{month.win_rate.toFixed(0)}%</span>
    </motion.div>
  );
}

// --- Main Page ---
export default function AccuracyPage() {
  const { metrics, loading, error } = useAccuracy();

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <div className="w-12 h-12 rounded-2xl bg-trading-ai/10 flex items-center justify-center">
          <Loader2 size={24} className="text-trading-ai animate-spin" />
        </div>
        <p className="text-slate-400 text-sm mt-4">Loading accuracy metrics...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <div className="w-12 h-12 rounded-2xl bg-slate-800/50 flex items-center justify-center">
          <AlertCircle size={24} className="text-trading-alert" />
        </div>
        <p className="text-slate-400 text-sm mt-4">Failed to load metrics: {error}</p>
      </div>
    );
  }

  if (!metrics) {
    return (
      <GlassCard className="flex flex-col items-center justify-center py-16">
        <div className="w-12 h-12 rounded-2xl bg-slate-800/50 flex items-center justify-center mb-4">
          <Target size={24} className="text-slate-600" />
        </div>
        <p className="text-slate-500 text-sm">No accuracy data available yet</p>
      </GlassCard>
    );
  }

  const maxMonthlyPnl = metrics.monthly_pnl.length > 0
    ? Math.max(...metrics.monthly_pnl.map((m) => Math.abs(m.pnl)))
    : 1;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      className="space-y-5"
    >
      {/* Top Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
        <MetricCard title="Total Signals" value={metrics.total_signals} icon={BarChart3} color="info" />
        <MetricCard title="Win Rate" value={metrics.win_rate > 0 ? `${metrics.win_rate}%` : '--'} icon={Target} color="bull" />
        <MetricCard
          title="Total P&L"
          value={metrics.total_pnl !== 0 ? `${metrics.total_pnl >= 0 ? '+' : ''}${(metrics.total_pnl / 1000).toFixed(1)}K` : '--'}
          icon={DollarSign}
          color={metrics.total_pnl >= 0 ? 'bull' : 'bear'}
        />
        <MetricCard title="Avg RRR" value={metrics.avg_rrr > 0 ? metrics.avg_rrr.toFixed(2) : '--'} icon={Trophy} color="ai" />
      </div>

      {/* Donut + Direction */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Donut Chart */}
        <GlassCard className="flex flex-col items-center justify-center">
          <DonutChart wins={metrics.wins} losses={metrics.losses} open={metrics.open} />
          <div className="flex items-center gap-6 mt-4">
            <div className="flex items-center gap-1.5">
              <span className="w-3 h-3 rounded-full bg-trading-bull" />
              <span className="text-xs text-slate-400 font-mono tabular-nums">Wins ({metrics.wins})</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-3 h-3 rounded-full bg-trading-bear" />
              <span className="text-xs text-slate-400 font-mono tabular-nums">Losses ({metrics.losses})</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-3 h-3 rounded-full bg-trading-alert" />
              <span className="text-xs text-slate-400 font-mono tabular-nums">Open ({metrics.open})</span>
            </div>
          </div>
        </GlassCard>

        {/* Direction Comparison */}
        <GlassCard>
          <h3 className="stat-label mb-4">
            Direction Accuracy
          </h3>
          <DirectionComparison directions={metrics.by_direction} />
        </GlassCard>
      </div>

      {/* Pattern Accuracy Table */}
      {metrics.by_pattern.length > 0 && (
        <GlassCard className="!p-0">
          <div className="p-6">
            <h3 className="stat-label mb-4">
              Pattern Accuracy
            </h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[9px]">
              <thead>
                <tr className="text-[9px] text-slate-600 uppercase tracking-[0.12em] font-medium border-b border-trading-border/15">
                  <th className="text-left py-2.5 px-3">Pattern</th>
                  <th className="text-center py-2.5 px-3">Total</th>
                  <th className="text-center py-2.5 px-3">Wins</th>
                  <th className="text-left py-2.5 px-3 w-1/3">Win Rate</th>
                </tr>
              </thead>
              <tbody>
                {metrics.by_pattern.map((pattern, idx) => (
                  <PatternRow key={pattern.pattern} pattern={pattern} index={idx} />
                ))}
              </tbody>
            </table>
          </div>
        </GlassCard>
      )}

      {/* Monthly PnL */}
      {metrics.monthly_pnl.length > 0 && (
        <GlassCard>
          <h3 className="stat-label mb-4">
            Monthly P&L
          </h3>
          <div className="flex items-end justify-around gap-3 pt-2 overflow-x-auto">
            {metrics.monthly_pnl.map((month, idx) => (
              <MonthlyPnLBar key={month.month} month={month} index={idx} maxPnl={maxMonthlyPnl} />
            ))}
          </div>
        </GlassCard>
      )}
    </motion.div>
  );
}
