import { useState } from 'react';
import { motion } from 'framer-motion';
import {
  LineChart as LineChartIcon,
  Plus,
  Trash2,
  Loader2,
  AlertCircle,
  Zap,
  DollarSign,
  TrendingUp,
  TrendingDown,
  Target,
} from 'lucide-react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts';
import GlassCard from '../components/ui/GlassCard';
import MetricCard from '../components/ui/MetricCard';
import { cn } from '../lib/utils';
import { usePayoff } from '../hooks/usePayoff';
import type { PayoffLeg } from '../types';

const EMPTY_LEG: PayoffLeg = {
  strike: 23500,
  premium: 200,
  qty: 1,
  option_type: 'CE',
  action: 'BUY',
};

const PRESETS: Record<string, { label: string; legs: PayoffLeg[] }> = {
  long_straddle: {
    label: 'Straddle',
    legs: [
      { strike: 23500, premium: 250, qty: 1, option_type: 'CE', action: 'BUY' },
      { strike: 23500, premium: 230, qty: 1, option_type: 'PE', action: 'BUY' },
    ],
  },
  long_strangle: {
    label: 'Strangle',
    legs: [
      { strike: 23700, premium: 150, qty: 1, option_type: 'CE', action: 'BUY' },
      { strike: 23300, premium: 140, qty: 1, option_type: 'PE', action: 'BUY' },
    ],
  },
  bull_call_spread: {
    label: 'Bull Call Spread',
    legs: [
      { strike: 23400, premium: 300, qty: 1, option_type: 'CE', action: 'BUY' },
      { strike: 23600, premium: 180, qty: 1, option_type: 'CE', action: 'SELL' },
    ],
  },
  bear_put_spread: {
    label: 'Bear Put Spread',
    legs: [
      { strike: 23600, premium: 280, qty: 1, option_type: 'PE', action: 'BUY' },
      { strike: 23400, premium: 160, qty: 1, option_type: 'PE', action: 'SELL' },
    ],
  },
  iron_condor: {
    label: 'Iron Condor',
    legs: [
      { strike: 23100, premium: 30, qty: 1, option_type: 'PE', action: 'BUY' },
      { strike: 23300, premium: 80, qty: 1, option_type: 'PE', action: 'SELL' },
      { strike: 23700, premium: 75, qty: 1, option_type: 'CE', action: 'SELL' },
      { strike: 23900, premium: 25, qty: 1, option_type: 'CE', action: 'BUY' },
    ],
  },
  butterfly: {
    label: 'Butterfly',
    legs: [
      { strike: 23300, premium: 300, qty: 1, option_type: 'CE', action: 'BUY' },
      { strike: 23500, premium: 200, qty: 2, option_type: 'CE', action: 'SELL' },
      { strike: 23700, premium: 130, qty: 1, option_type: 'CE', action: 'BUY' },
    ],
  },
};

export default function PayoffPage() {
  const [legs, setLegs] = useState<PayoffLeg[]>([
    { ...PRESETS.iron_condor.legs[0] },
    { ...PRESETS.iron_condor.legs[1] },
    { ...PRESETS.iron_condor.legs[2] },
    { ...PRESETS.iron_condor.legs[3] },
  ]);
  const { payoff, loading, error, calculate } = usePayoff();

  const addLeg = () => setLegs([...legs, { ...EMPTY_LEG }]);
  const removeLeg = (index: number) => setLegs(legs.filter((_, i) => i !== index));
  const updateLeg = (index: number, field: keyof PayoffLeg, value: string | number) => {
    const updated = [...legs];
    (updated[index] as unknown as Record<string, unknown>)[field] = value;
    setLegs(updated);
  };

  const applyPreset = (presetKey: string) => {
    const preset = PRESETS[presetKey];
    if (preset) {
      setLegs(preset.legs.map((l) => ({ ...l })));
    }
  };

  const handleCalculate = () => {
    if (legs.length === 0) return;
    calculate(legs);
  };

  // Transform payoff points for Recharts
  const chartData = payoff?.points.map((p) => ({
    spot: p.spot,
    pnl: p.pnl,
    positive: p.pnl >= 0 ? p.pnl : 0,
    negative: p.pnl < 0 ? p.pnl : 0,
  })) || [];

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      className="space-y-5"
    >
      {/* Header */}
      <div>
        <h2 className="text-xl font-bold text-white flex items-center gap-2">
          <LineChartIcon size={22} className="text-trading-ai" />
          Options Payoff Calculator
        </h2>
        <p className="text-sm text-slate-400 mt-0.5">
          Multi-leg P&L visualization with strategy presets
        </p>
      </div>

      {/* Presets */}
      <GlassCard>
        <h3 className="stat-label">
          Strategy Presets
        </h3>
        <div className="flex flex-wrap gap-3">
          {Object.entries(PRESETS).map(([key, preset]) => (
            <button
              key={key}
              onClick={() => applyPreset(key)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium bg-trading-ai/8 text-trading-ai-light border border-trading-ai/15 hover:border-trading-ai hover:text-trading-ai-light transition-all"
            >
              <Zap size={12} />
              {preset.label}
            </button>
          ))}
        </div>
      </GlassCard>

      {/* Leg Builder */}
      <GlassCard glowColor="ai">
        <div className="flex items-center justify-between mb-4">
          <h3 className="stat-label">
            Option Legs ({legs.length})
          </h3>
          <button
            onClick={addLeg}
            className="flex items-center gap-1 text-xs text-trading-ai-light hover:text-white transition-colors"
          >
            <Plus size={14} /> Add Leg
          </button>
        </div>

        <div className="space-y-2">
          {legs.map((leg, i) => (
            <div key={i} className="grid grid-cols-6 gap-3 items-center">
              <select
                value={leg.action}
                onChange={(e) => updateLeg(i, 'action', e.target.value)}
                className={cn(
                  'bg-trading-bg-secondary border rounded-xl px-2 py-1.5 text-xs font-mono tabular-nums focus:outline-none',
                  leg.action === 'BUY'
                    ? 'border-trading-bull/30 text-trading-bull'
                    : 'border-trading-bear/30 text-trading-bear'
                )}
              >
                <option value="BUY">BUY</option>
                <option value="SELL">SELL</option>
              </select>
              <select
                value={leg.option_type}
                onChange={(e) => updateLeg(i, 'option_type', e.target.value)}
                className="bg-trading-bg-secondary border border-trading-border/60 rounded-xl px-2 py-1.5 text-xs font-mono tabular-nums text-white focus:outline-none focus:border-trading-ai/40"
              >
                <option value="CE">CE</option>
                <option value="PE">PE</option>
              </select>
              <input
                type="number"
                value={leg.strike}
                onChange={(e) => updateLeg(i, 'strike', parseFloat(e.target.value) || 0)}
                placeholder="Strike"
                className="bg-trading-bg-secondary border border-trading-border/60 rounded-xl px-2 py-1.5 text-xs font-mono tabular-nums text-white focus:outline-none focus:border-trading-ai/40"
              />
              <input
                type="number"
                value={leg.premium}
                onChange={(e) => updateLeg(i, 'premium', parseFloat(e.target.value) || 0)}
                placeholder="Premium"
                className="bg-trading-bg-secondary border border-trading-border/60 rounded-xl px-2 py-1.5 text-xs font-mono tabular-nums text-white focus:outline-none focus:border-trading-ai/40"
              />
              <input
                type="number"
                value={leg.qty}
                onChange={(e) => updateLeg(i, 'qty', parseInt(e.target.value) || 1)}
                placeholder="Qty"
                min="1"
                className="bg-trading-bg-secondary border border-trading-border/60 rounded-xl px-2 py-1.5 text-xs font-mono tabular-nums text-white focus:outline-none focus:border-trading-ai/40"
              />
              <button
                onClick={() => removeLeg(i)}
                className="flex items-center justify-center p-1.5 rounded-xl text-slate-500 hover:text-trading-bear hover:bg-trading-bear/10 transition-colors"
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>

        <button
          onClick={handleCalculate}
          disabled={loading || legs.length === 0}
          className={cn(
            'mt-4 flex items-center justify-center gap-2 px-6 py-2.5 rounded-xl text-sm font-medium transition-all w-full',
            loading ? 'bg-trading-bg-secondary text-slate-400' : 'gradient-ai text-white hover:opacity-90'
          )}
        >
          {loading ? <Loader2 size={16} className="animate-spin" /> : <LineChartIcon size={16} />}
          Calculate Payoff
        </button>
      </GlassCard>

      {error && (
        <GlassCard className="flex items-center gap-3 py-4">
          <AlertCircle size={20} className="text-trading-bear" />
          <p className="text-trading-bear text-sm">{error}</p>
        </GlassCard>
      )}

      {/* Results */}
      {payoff && !loading && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
          className="space-y-5"
        >
          {/* Summary Cards */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <MetricCard
              title="Net Premium"
              value={`${payoff.net_premium >= 0 ? '+' : ''}${payoff.net_premium.toLocaleString('en-IN')}`}
              icon={DollarSign}
              color={payoff.net_premium >= 0 ? 'bull' : 'bear'}
            />
            <MetricCard
              title="Max Profit"
              value={payoff.max_profit >= 99999 ? 'Unlimited' : `+${payoff.max_profit.toLocaleString('en-IN')}`}
              icon={TrendingUp}
              color="bull"
            />
            <MetricCard
              title="Max Loss"
              value={payoff.max_loss <= -99999 ? 'Unlimited' : payoff.max_loss.toLocaleString('en-IN')}
              icon={TrendingDown}
              color="bear"
            />
            <MetricCard
              title="Breakevens"
              value={payoff.breakevens.length > 0 ? payoff.breakevens.map((b) => b.toFixed(0)).join(', ') : 'None'}
              icon={Target}
              color="info"
            />
          </div>

          {/* Payoff Chart */}
          <GlassCard>
            <h3 className="stat-label">
              Payoff Diagram
            </h3>
            <div className="h-80">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chartData} margin={{ top: 10, right: 10, bottom: 5, left: 10 }}>
                  <defs>
                    <linearGradient id="profitGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#10B981" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#10B981" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="lossGrad" x1="0" y1="1" x2="0" y2="0">
                      <stop offset="5%" stopColor="#EF4444" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#EF4444" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis
                    dataKey="spot"
                    tick={{ fill: '#94A3B8', fontSize: 10 }}
                    tickFormatter={(v: number) => v.toFixed(0)}
                    stroke="#334155"
                  />
                  <YAxis
                    tick={{ fill: '#94A3B8', fontSize: 10 }}
                    tickFormatter={(v: number) => v.toLocaleString('en-IN')}
                    stroke="#334155"
                  />
                  <Tooltip
                    contentStyle={{ backgroundColor: '#1E293B', border: '1px solid #334155', borderRadius: 8 }}
                    formatter={(value: number) => [value.toLocaleString('en-IN'), 'P&L']}
                    labelFormatter={(label: number) => `Spot: ${label.toFixed(0)}`}
                  />
                  <ReferenceLine y={0} stroke="#64748B" strokeDasharray="3 3" />
                  {payoff.breakevens.map((be, i) => (
                    <ReferenceLine
                      key={i}
                      x={be}
                      stroke="#F59E0B"
                      strokeDasharray="5 3"
                      label={{ value: `BE: ${be.toFixed(0)}`, fill: '#F59E0B', fontSize: 10, position: 'top' }}
                    />
                  ))}
                  <Area
                    type="monotone"
                    dataKey="positive"
                    stroke="#10B981"
                    strokeWidth={2}
                    fill="url(#profitGrad)"
                  />
                  <Area
                    type="monotone"
                    dataKey="negative"
                    stroke="#EF4444"
                    strokeWidth={2}
                    fill="url(#lossGrad)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </GlassCard>
        </motion.div>
      )}

      {/* Empty State */}
      {!payoff && !loading && !error && (
        <GlassCard className="flex flex-col items-center justify-center py-16">
          <div className="w-12 h-12 rounded-2xl bg-trading-ai/10 flex items-center justify-center mb-4">
            <LineChartIcon size={24} className="text-slate-600" />
          </div>
          <p className="text-slate-500 text-sm">Add option legs and click Calculate to see the payoff diagram</p>
          <p className="text-slate-600 text-xs mt-1">Use presets for common strategies like Iron Condor or Straddle</p>
        </GlassCard>
      )}
    </motion.div>
  );
}
