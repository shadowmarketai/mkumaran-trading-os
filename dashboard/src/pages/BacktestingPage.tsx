import { useState } from 'react';
import { motion } from 'framer-motion';
import {
  FlaskConical,
  Play,
  Target,
  TrendingDown,
  BarChart3,
  Activity,
  Loader2,
  AlertCircle,
  GitCompare,
  Trophy,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import {
  AreaChart,
  Area,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';
import GlassCard from '../components/ui/GlassCard';
import MetricCard from '../components/ui/MetricCard';
import { cn } from '../lib/utils';
import { useBacktest } from '../hooks/useBacktest';
import { backtestApi } from '../services/api';
import type { EquityPoint, BacktestCompareResult, StrategyComparison } from '../types';

interface FormState {
  ticker: string;
  strategy: string;
  days: string;
}

interface CustomTooltipProps {
  active?: boolean;
  payload?: Array<{ value: number; payload: EquityPoint }>;
  label?: string;
}

function CustomTooltip({ active, payload, label }: CustomTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;
  const data = payload[0];
  return (
    <div className="glass-card p-3 text-xs space-y-1">
      <p className="text-slate-400">{label}</p>
      <p className="font-mono text-white">
        Equity: <span className="text-trading-bull font-bold">{data.value.toLocaleString('en-IN')}</span>
      </p>
      {data.payload.drawdown < 0 && (
        <p className="font-mono text-trading-bear">
          DD: {data.payload.drawdown.toFixed(1)}%
        </p>
      )}
    </div>
  );
}

const STRATEGY_META: Record<string, { label: string; color: string; description: string }> = {
  rrms: { label: 'RRMS', color: 'text-blue-400', description: 'Range-Reversion Mean Strategy' },
  smc: { label: 'SMC/ICT', color: 'text-purple-400', description: 'Smart Money Concepts' },
  wyckoff: { label: 'Wyckoff', color: 'text-amber-400', description: 'Wyckoff Method' },
  vsa: { label: 'VSA', color: 'text-cyan-400', description: 'Volume Spread Analysis' },
  harmonic: { label: 'Harmonic', color: 'text-pink-400', description: 'Harmonic Patterns' },
  confluence: { label: 'Confluence', color: 'text-trading-ai-light', description: '2+ engines agree' },
};

type SortKey = 'strategy' | 'total_trades' | 'win_rate' | 'max_drawdown' | 'profit_factor' | 'sharpe_ratio' | 'total_return';

const STRATEGY_COLORS: Record<string, string> = {
  rrms: '#3B82F6',       // blue
  smc: '#A855F7',        // purple
  wyckoff: '#F59E0B',    // amber
  vsa: '#06B6D4',        // cyan
  harmonic: '#EC4899',   // pink
  confluence: '#8B5CF6', // violet
};

function ComparisonEquityCurves({ data }: { data: BacktestCompareResult }) {
  const curves = data.equity_curves;
  if (!curves || Object.keys(curves).length === 0) return null;

  // Merge all equity curves into unified date-indexed data
  const dateMap: Record<string, Record<string, number>> = {};
  for (const [strat, points] of Object.entries(curves)) {
    if (!Array.isArray(points)) continue;
    for (const pt of points) {
      if (!dateMap[pt.date]) dateMap[pt.date] = {};
      dateMap[pt.date][strat] = pt.equity;
    }
  }

  const merged = Object.entries(dateMap)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([dateStr, values]) => ({ date: dateStr, ...values }));

  if (merged.length === 0) return null;

  return (
    <GlassCard>
      <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-4">
        Multi-Strategy Equity Curves
      </h3>
      <div className="h-80">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={merged} margin={{ top: 5, right: 5, bottom: 5, left: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis
              dataKey="date"
              tick={{ fill: '#94A3B8', fontSize: 10 }}
              tickFormatter={(d: string) => d.slice(5)}
              stroke="#334155"
            />
            <YAxis
              tick={{ fill: '#94A3B8', fontSize: 10 }}
              tickFormatter={(v: number) => `${(v / 1000).toFixed(0)}K`}
              stroke="#334155"
            />
            <Tooltip
              contentStyle={{ backgroundColor: '#1E293B', border: '1px solid #334155', borderRadius: 8 }}
              labelStyle={{ color: '#94A3B8' }}
              formatter={(value: number, name: string) => [
                `${value.toLocaleString('en-IN')}`,
                STRATEGY_META[name]?.label || name,
              ]}
            />
            <Legend
              formatter={(value: string) => STRATEGY_META[value]?.label || value}
              wrapperStyle={{ fontSize: 12 }}
            />
            {Object.keys(curves).map((strat) => (
              <Line
                key={strat}
                type="monotone"
                dataKey={strat}
                stroke={STRATEGY_COLORS[strat] || '#94A3B8'}
                strokeWidth={2}
                dot={false}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </GlassCard>
  );
}

function ComparisonTable({ data }: { data: BacktestCompareResult }) {
  const [sortKey, setSortKey] = useState<SortKey>('profit_factor');
  const [sortAsc, setSortAsc] = useState(false);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortAsc(!sortAsc);
    } else {
      setSortKey(key);
      setSortAsc(false);
    }
  };

  const sorted = [...data.strategies].sort((a, b) => {
    const av = a[sortKey] as number;
    const bv = b[sortKey] as number;
    if (typeof av === 'string') return sortAsc ? (av as string).localeCompare(bv as unknown as string) : (bv as unknown as string).localeCompare(av as string);
    return sortAsc ? av - bv : bv - av;
  });

  // Find best value per column for green highlighting
  const bestValues: Record<string, number> = {};
  const numericKeys: SortKey[] = ['total_trades', 'win_rate', 'profit_factor', 'sharpe_ratio', 'total_return'];
  for (const key of numericKeys) {
    bestValues[key] = Math.max(...data.strategies.map((s) => s[key] as number));
  }
  bestValues['max_drawdown'] = Math.min(...data.strategies.map((s) => s.max_drawdown));

  const SortIcon = ({ col }: { col: SortKey }) => (
    sortKey === col ? (sortAsc ? <ChevronUp size={12} /> : <ChevronDown size={12} />) : null
  );

  return (
    <GlassCard>
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider flex items-center gap-2">
          <GitCompare size={16} /> Strategy Comparison
        </h3>
        <div className="flex items-center gap-2 text-xs">
          <Trophy size={14} className="text-trading-alert" />
          <span className="text-trading-alert font-medium">Best: {STRATEGY_META[data.best_strategy]?.label || data.best_strategy}</span>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-trading-border">
              <th className="text-left py-2 px-3 text-xs text-slate-500 uppercase cursor-pointer select-none" onClick={() => handleSort('strategy')}>Strategy <SortIcon col="strategy" /></th>
              <th className="text-right py-2 px-3 text-xs text-slate-500 uppercase cursor-pointer select-none" onClick={() => handleSort('total_trades')}>Trades <SortIcon col="total_trades" /></th>
              <th className="text-right py-2 px-3 text-xs text-slate-500 uppercase cursor-pointer select-none" onClick={() => handleSort('win_rate')}>Win Rate <SortIcon col="win_rate" /></th>
              <th className="text-right py-2 px-3 text-xs text-slate-500 uppercase cursor-pointer select-none" onClick={() => handleSort('max_drawdown')}>Max DD <SortIcon col="max_drawdown" /></th>
              <th className="text-right py-2 px-3 text-xs text-slate-500 uppercase cursor-pointer select-none" onClick={() => handleSort('profit_factor')}>Profit F. <SortIcon col="profit_factor" /></th>
              <th className="text-right py-2 px-3 text-xs text-slate-500 uppercase cursor-pointer select-none" onClick={() => handleSort('sharpe_ratio')}>Sharpe <SortIcon col="sharpe_ratio" /></th>
              <th className="text-right py-2 px-3 text-xs text-slate-500 uppercase cursor-pointer select-none" onClick={() => handleSort('total_return')}>Return <SortIcon col="total_return" /></th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((s: StrategyComparison) => {
              const meta = STRATEGY_META[s.strategy];
              const isBest = s.strategy === data.best_strategy;
              return (
                <tr
                  key={s.strategy}
                  className={cn(
                    'border-b border-trading-border/50 transition-colors',
                    isBest ? 'bg-trading-ai/5' : 'hover:bg-slate-800/30'
                  )}
                >
                  <td className="py-2.5 px-3">
                    <div className="flex items-center gap-2">
                      <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: STRATEGY_COLORS[s.strategy] || '#94A3B8' }} />
                      {isBest && <Trophy size={12} className="text-trading-alert" />}
                      <span className={cn('font-mono font-medium', meta?.color || 'text-white')}>
                        {meta?.label || s.strategy}
                      </span>
                    </div>
                  </td>
                  <td className="text-right py-2.5 px-3 font-mono text-slate-300">{s.total_trades}</td>
                  <td className={cn('text-right py-2.5 px-3 font-mono font-medium', s.win_rate === bestValues['win_rate'] ? 'text-trading-bull' : s.win_rate >= 50 ? 'text-trading-bull' : 'text-trading-bear')}>
                    {s.win_rate.toFixed(1)}%
                  </td>
                  <td className={cn('text-right py-2.5 px-3 font-mono', s.max_drawdown === bestValues['max_drawdown'] ? 'text-trading-bull' : 'text-trading-bear')}>
                    {s.max_drawdown.toFixed(1)}%
                  </td>
                  <td className={cn('text-right py-2.5 px-3 font-mono', s.profit_factor === bestValues['profit_factor'] ? 'text-trading-bull font-medium' : s.profit_factor >= 1.5 ? 'text-trading-bull' : 'text-slate-300')}>
                    {s.profit_factor.toFixed(2)}
                  </td>
                  <td className={cn('text-right py-2.5 px-3 font-mono', s.sharpe_ratio === bestValues['sharpe_ratio'] ? 'text-trading-bull font-medium' : s.sharpe_ratio >= 1.0 ? 'text-trading-bull' : 'text-slate-300')}>
                    {s.sharpe_ratio.toFixed(2)}
                  </td>
                  <td className={cn('text-right py-2.5 px-3 font-mono font-medium', s.total_return === bestValues['total_return'] ? 'text-trading-bull' : s.total_return >= 0 ? 'text-trading-bull' : 'text-trading-bear')}>
                    {s.total_return >= 0 ? '+' : ''}{s.total_return.toFixed(1)}%
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </GlassCard>
  );
}

export default function BacktestingPage() {
  const [form, setForm] = useState<FormState>({
    ticker: 'RELIANCE',
    strategy: 'rrms',
    days: '180',
  });
  const { result, loading: isRunning, error, run } = useBacktest();
  const [compareResult, setCompareResult] = useState<BacktestCompareResult | null>(null);
  const [comparing, setComparing] = useState(false);
  const [compareError, setCompareError] = useState<string | null>(null);
  const [showPatterns, setShowPatterns] = useState(false);

  const strategies = [
    { value: 'rrms', label: 'RRMS Strategy' },
    { value: 'smc', label: 'SMC / ICT' },
    { value: 'wyckoff', label: 'Wyckoff Method' },
    { value: 'vsa', label: 'Volume Spread Analysis' },
    { value: 'harmonic', label: 'Harmonic Patterns' },
    { value: 'confluence', label: 'Confluence (2+ engines)' },
  ];

  const handleRun = () => {
    if (!form.ticker.trim() || isRunning) return;
    setCompareResult(null);
    run(form.ticker.toUpperCase(), form.strategy, parseInt(form.days, 10) || 180);
  };

  const handleCompareAll = async () => {
    if (!form.ticker.trim() || comparing) return;
    setComparing(true);
    setCompareError(null);
    try {
      const data = await backtestApi.compareAll(form.ticker.toUpperCase(), parseInt(form.days, 10) || 180);
      setCompareResult(data);
    } catch (err) {
      setCompareError(err instanceof Error ? err.message : 'Comparison failed');
    } finally {
      setComparing(false);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.4 }}
      className="space-y-6"
    >
      {/* Header */}
      <div>
        <h2 className="text-xl font-bold text-white flex items-center gap-2">
          <FlaskConical size={22} className="text-trading-ai" />
          Multi-Engine Backtesting
        </h2>
        <p className="text-sm text-slate-400 mt-0.5">
          Test 6 strategies: RRMS, SMC, Wyckoff, VSA, Harmonic, Confluence
        </p>
      </div>

      {/* Input Form */}
      <GlassCard glowColor="ai">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4 items-end">
          <div>
            <label className="text-xs text-slate-500 uppercase tracking-wider block mb-1.5">
              Ticker
            </label>
            <input
              type="text"
              value={form.ticker}
              onChange={(e) => setForm({ ...form, ticker: e.target.value })}
              placeholder="e.g., RELIANCE"
              className="w-full bg-slate-800 border border-trading-border rounded-lg px-3 py-2.5 text-sm font-mono text-white placeholder-slate-600 focus:outline-none focus:border-trading-ai"
            />
          </div>
          <div>
            <label className="text-xs text-slate-500 uppercase tracking-wider block mb-1.5">
              Strategy
            </label>
            <select
              value={form.strategy}
              onChange={(e) => setForm({ ...form, strategy: e.target.value })}
              className="w-full bg-slate-800 border border-trading-border rounded-lg px-3 py-2.5 text-sm font-mono text-white focus:outline-none focus:border-trading-ai"
            >
              {strategies.map((s) => (
                <option key={s.value} value={s.value}>{s.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-slate-500 uppercase tracking-wider block mb-1.5">
              Period (Days)
            </label>
            <input
              type="number"
              value={form.days}
              onChange={(e) => setForm({ ...form, days: e.target.value })}
              placeholder="180"
              min="30"
              max="365"
              className="w-full bg-slate-800 border border-trading-border rounded-lg px-3 py-2.5 text-sm font-mono text-white placeholder-slate-600 focus:outline-none focus:border-trading-ai"
            />
          </div>
          <button
            onClick={handleRun}
            disabled={isRunning || comparing || !form.ticker.trim()}
            className={cn(
              'flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-all',
              isRunning
                ? 'bg-slate-700 text-slate-400 cursor-wait'
                : 'gradient-ai text-white hover:opacity-90'
            )}
          >
            {isRunning ? (
              <><Loader2 size={16} className="animate-spin" /> Running...</>
            ) : (
              <><Play size={16} /> Run Backtest</>
            )}
          </button>
          <button
            onClick={handleCompareAll}
            disabled={isRunning || comparing || !form.ticker.trim()}
            className={cn(
              'flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-all border',
              comparing
                ? 'bg-slate-700 text-slate-400 cursor-wait border-slate-600'
                : 'bg-slate-800 text-trading-ai-light border-trading-ai/30 hover:bg-trading-ai/10'
            )}
          >
            {comparing ? (
              <><Loader2 size={16} className="animate-spin" /> Comparing...</>
            ) : (
              <><GitCompare size={16} /> Compare All</>
            )}
          </button>
        </div>
      </GlassCard>

      {/* Errors */}
      {(error || compareError) && !isRunning && !comparing && (
        <GlassCard className="flex items-center gap-3 py-4">
          <AlertCircle size={20} className="text-trading-bear" />
          <p className="text-trading-bear text-sm">{error || compareError}</p>
        </GlassCard>
      )}

      {/* Compare All Results */}
      {compareResult && !comparing && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="space-y-6"
        >
          <ComparisonTable data={compareResult} />
          <ComparisonEquityCurves data={compareResult} />
        </motion.div>
      )}

      {/* Single Strategy Results */}
      {result && !isRunning && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="space-y-6"
        >
          {/* Result Header */}
          <div className="flex items-center gap-3">
            <span className="text-sm text-slate-400">Results for</span>
            <span className="font-mono font-bold text-white text-lg">{result.ticker}</span>
            <span className={cn(
              'text-xs px-2 py-0.5 rounded border font-mono',
              STRATEGY_META[result.strategy]
                ? `${STRATEGY_META[result.strategy].color} bg-slate-800 border-slate-600`
                : 'text-trading-ai-light bg-trading-ai/10 border-trading-ai/20'
            )}>
              {STRATEGY_META[result.strategy]?.label || result.strategy}
            </span>
            {result.period && (
              <span className="text-xs text-slate-500">{result.period}</span>
            )}
          </div>

          {/* Metric Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
            <MetricCard
              title="Win Rate"
              value={result.win_rate ? `${result.win_rate}%` : '--'}
              icon={Target}
              color="bull"
            />
            <MetricCard
              title="Sharpe Ratio"
              value={result.sharpe_ratio ? result.sharpe_ratio.toFixed(2) : '--'}
              icon={Activity}
              color="info"
            />
            <MetricCard
              title="Max Drawdown"
              value={result.max_drawdown ? `${result.max_drawdown}%` : '--'}
              icon={TrendingDown}
              color="bear"
            />
            <MetricCard
              title="Profit Factor"
              value={result.profit_factor ? result.profit_factor.toFixed(2) : '--'}
              icon={BarChart3}
              color="ai"
            />
            <MetricCard
              title="Total Return"
              value={result.total_return ? `${result.total_return >= 0 ? '+' : ''}${result.total_return}%` : '--'}
              change={result.total_return}
              icon={Target}
              color="bull"
            />
          </div>

          {/* Equity Curve */}
          {result.equity_curve && result.equity_curve.length > 0 && (
            <GlassCard>
              <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-4">
                Equity Curve
              </h3>
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={result.equity_curve} margin={{ top: 5, right: 5, bottom: 5, left: 5 }}>
                    <defs>
                      <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#10B981" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="#10B981" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis
                      dataKey="date"
                      tick={{ fill: '#94A3B8', fontSize: 10 }}
                      tickFormatter={(d: string) => d.slice(5)}
                      stroke="#334155"
                    />
                    <YAxis
                      tick={{ fill: '#94A3B8', fontSize: 10 }}
                      tickFormatter={(v: number) => `${(v / 1000).toFixed(0)}K`}
                      stroke="#334155"
                    />
                    <Tooltip content={<CustomTooltip />} />
                    <Area
                      type="monotone"
                      dataKey="equity"
                      stroke="#10B981"
                      strokeWidth={2}
                      fill="url(#equityGradient)"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </GlassCard>
          )}

          {/* Trade Statistics */}
          <GlassCard>
            <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-4">
              Trade Statistics
            </h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="text-center p-3 rounded-lg bg-slate-800/50">
                <p className="text-2xl font-mono font-bold text-white">{result.total_trades || 0}</p>
                <p className="text-[10px] text-slate-500 uppercase mt-1">Total Trades</p>
              </div>
              <div className="text-center p-3 rounded-lg bg-trading-bull/5 border border-trading-bull/10">
                <p className="text-2xl font-mono font-bold text-trading-bull">
                  {result.total_trades && result.win_rate
                    ? Math.round(result.total_trades * result.win_rate / 100)
                    : 0}
                </p>
                <p className="text-[10px] text-slate-500 uppercase mt-1">Wins</p>
              </div>
              <div className="text-center p-3 rounded-lg bg-trading-bear/5 border border-trading-bear/10">
                <p className="text-2xl font-mono font-bold text-trading-bear">
                  {result.total_trades && result.win_rate
                    ? result.total_trades - Math.round(result.total_trades * result.win_rate / 100)
                    : 0}
                </p>
                <p className="text-[10px] text-slate-500 uppercase mt-1">Losses</p>
              </div>
              <div className="text-center p-3 rounded-lg bg-trading-ai/5 border border-trading-ai/10">
                <p className="text-2xl font-mono font-bold text-trading-ai">
                  {result.total_return ? `${result.total_return >= 0 ? '+' : ''}${result.total_return}%` : '--'}
                </p>
                <p className="text-[10px] text-slate-500 uppercase mt-1">Return</p>
              </div>
            </div>
          </GlassCard>

          {/* Per-Pattern Breakdown (expandable) */}
          {result.per_pattern && Object.keys(result.per_pattern).length > 0 && (
            <GlassCard>
              <button
                onClick={() => setShowPatterns(!showPatterns)}
                className="w-full flex items-center justify-between"
              >
                <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider">
                  Pattern Breakdown
                </h3>
                {showPatterns ? <ChevronUp size={16} className="text-slate-400" /> : <ChevronDown size={16} className="text-slate-400" />}
              </button>
              {showPatterns && (
                <div className="mt-4 space-y-2">
                  {Object.entries(result.per_pattern).map(([pattern, stats]) => (
                    <div key={pattern} className="flex items-center justify-between px-3 py-2 bg-slate-800/50 rounded-lg">
                      <span className="text-xs font-mono text-slate-300">{pattern}</span>
                      <div className="flex items-center gap-4">
                        <span className="text-xs text-slate-500">{stats.total} trades</span>
                        <span className={cn('text-xs font-mono font-medium', stats.win_rate >= 50 ? 'text-trading-bull' : 'text-trading-bear')}>
                          {stats.win_rate.toFixed(0)}% win
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </GlassCard>
          )}
        </motion.div>
      )}

      {/* Empty State */}
      {!result && !isRunning && !error && !compareResult && !comparing && (
        <GlassCard className="flex flex-col items-center justify-center py-16">
          <FlaskConical size={48} className="text-slate-600 mb-4" />
          <p className="text-slate-500 text-sm">Configure parameters and run a backtest to see results</p>
          <p className="text-slate-600 text-xs mt-1">Use "Compare All" to see all 6 strategies side by side</p>
        </GlassCard>
      )}

      {/* Loading State */}
      {(isRunning || comparing) && (
        <GlassCard className="flex flex-col items-center justify-center py-16">
          <Loader2 size={48} className="text-trading-ai animate-spin mb-4" />
          <p className="text-slate-400 text-sm">
            {comparing ? `Comparing all strategies for ${form.ticker.toUpperCase()}...` : `Running backtest for ${form.ticker.toUpperCase()}...`}
          </p>
          <p className="text-slate-600 text-xs mt-1">
            {comparing ? 'Running 6 strategies in sequence' : `Processing ${form.days} days of historical data`}
          </p>
        </GlassCard>
      )}
    </motion.div>
  );
}
