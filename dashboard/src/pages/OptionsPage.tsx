import { useState } from 'react';
import { motion } from 'framer-motion';
import {
  Calculator,
  Loader2,
  AlertCircle,
  Search,
} from 'lucide-react';
import GlassCard from '../components/ui/GlassCard';
import { cn } from '../lib/utils';
import { useOptionChain, useGreeksCalculator } from '../hooks/useOptions';
import type { OptionStrike } from '../types';

interface ChainFormState {
  spot: string;
  expiryDays: string;
  strikeStep: string;
}

interface CalcFormState {
  spot: string;
  strike: string;
  expiryDays: string;
  volatility: string;
  rate: string;
  optionType: 'CE' | 'PE';
}

function OptionChainTable({ chain, spot }: { chain: OptionStrike[]; spot: number }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[9px]">
        <thead>
          <tr className="border-b border-trading-border/15">
            <th colSpan={5} className="text-center py-2 px-1 text-trading-bull font-semibold uppercase tracking-[0.12em] bg-trading-bull/5">
              Calls (CE)
            </th>
            <th className="py-2 px-2 text-center text-white font-bold bg-trading-card">Strike</th>
            <th colSpan={5} className="text-center py-2 px-1 text-trading-bear font-semibold uppercase tracking-[0.12em] bg-trading-bear/5">
              Puts (PE)
            </th>
          </tr>
          <tr className="border-b border-trading-border/15 text-slate-500 uppercase tracking-[0.12em]">
            <th className="py-1.5 px-1.5 text-right">Price</th>
            <th className="py-1.5 px-1.5 text-right">IV%</th>
            <th className="py-1.5 px-1.5 text-right">Delta</th>
            <th className="py-1.5 px-1.5 text-right">Theta</th>
            <th className="py-1.5 px-1.5 text-right">Vega</th>
            <th className="py-1.5 px-2 text-center font-bold">K</th>
            <th className="py-1.5 px-1.5 text-right">Vega</th>
            <th className="py-1.5 px-1.5 text-right">Theta</th>
            <th className="py-1.5 px-1.5 text-right">Delta</th>
            <th className="py-1.5 px-1.5 text-right">IV%</th>
            <th className="py-1.5 px-1.5 text-right">Price</th>
          </tr>
        </thead>
        <tbody>
          {chain.map((row: OptionStrike) => {
            const isITMCall = row.strike < spot;
            const isITMPut = row.strike > spot;
            return (
              <tr
                key={row.strike}
                className={cn(
                  'border-b border-trading-border/15 transition-colors',
                  row.is_atm
                    ? 'bg-trading-ai/10 border-trading-ai/30'
                    : 'hover:bg-white/[0.015]'
                )}
              >
                <td className={cn('py-1.5 px-1.5 text-right font-mono tabular-nums', isITMCall ? 'text-trading-bull' : 'text-slate-400')}>
                  {row.ce.price.toFixed(1)}
                </td>
                <td className="py-1.5 px-1.5 text-right font-mono tabular-nums text-slate-400">
                  {row.ce.iv > 0 ? row.ce.iv.toFixed(1) : '--'}
                </td>
                <td className="py-1.5 px-1.5 text-right font-mono tabular-nums text-slate-300">
                  {row.ce.delta.toFixed(2)}
                </td>
                <td className="py-1.5 px-1.5 text-right font-mono tabular-nums text-trading-bear">
                  {row.ce.theta.toFixed(1)}
                </td>
                <td className="py-1.5 px-1.5 text-right font-mono tabular-nums text-slate-400">
                  {row.ce.vega.toFixed(1)}
                </td>
                <td className={cn(
                  'py-1.5 px-2 text-center font-mono tabular-nums font-bold',
                  row.is_atm ? 'text-trading-ai-light bg-trading-ai/5' : 'text-white'
                )}>
                  {row.strike}
                </td>
                <td className="py-1.5 px-1.5 text-right font-mono tabular-nums text-slate-400">
                  {row.pe.vega.toFixed(1)}
                </td>
                <td className="py-1.5 px-1.5 text-right font-mono tabular-nums text-trading-bear">
                  {row.pe.theta.toFixed(1)}
                </td>
                <td className="py-1.5 px-1.5 text-right font-mono tabular-nums text-slate-300">
                  {row.pe.delta.toFixed(2)}
                </td>
                <td className="py-1.5 px-1.5 text-right font-mono tabular-nums text-slate-400">
                  {row.pe.iv > 0 ? row.pe.iv.toFixed(1) : '--'}
                </td>
                <td className={cn('py-1.5 px-1.5 text-right font-mono tabular-nums', isITMPut ? 'text-trading-bear' : 'text-slate-400')}>
                  {row.pe.price.toFixed(1)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function OptionsPage() {
  // Chain form
  const [chainForm, setChainForm] = useState<ChainFormState>({
    spot: '23500',
    expiryDays: '30',
    strikeStep: '50',
  });
  const { chain, loading: chainLoading, error: chainError, fetchChain } = useOptionChain();

  // Calculator form
  const [calcForm, setCalcForm] = useState<CalcFormState>({
    spot: '23500',
    strike: '23500',
    expiryDays: '30',
    volatility: '15',
    rate: '6.5',
    optionType: 'CE',
  });
  const { greeks, loading: calcLoading, error: calcError, calculate } = useGreeksCalculator();

  const handleFetchChain = () => {
    const spot = parseFloat(chainForm.spot);
    const days = parseFloat(chainForm.expiryDays);
    const step = parseFloat(chainForm.strikeStep);
    if (spot > 0 && days > 0 && step > 0) {
      fetchChain(spot, days, step);
    }
  };

  const handleCalculate = () => {
    const spot = parseFloat(calcForm.spot);
    const strike = parseFloat(calcForm.strike);
    const days = parseFloat(calcForm.expiryDays);
    const vol = parseFloat(calcForm.volatility) / 100;
    const rate = parseFloat(calcForm.rate) / 100;
    if (spot > 0 && strike > 0 && days > 0) {
      calculate({ spot, strike, expiry_days: days, volatility: vol, rate, option_type: calcForm.optionType });
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      className="space-y-5"
    >
      {/* Header */}
      <div>
        <h2 className="text-xl font-bold text-white flex items-center gap-3">
          <Calculator size={22} className="text-trading-ai" />
          Options Greeks Dashboard
        </h2>
        <p className="text-sm text-slate-400 mt-0.5">
          Black-Scholes pricing, Greeks, and IV analysis
        </p>
      </div>

      {/* Option Chain Section */}
      <GlassCard glowColor="ai">
        <h3 className="stat-label">
          Option Chain
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 items-end mb-4">
          <div>
            <label className="text-xs text-slate-500 uppercase block mb-1">Spot Price</label>
            <input
              type="number"
              value={chainForm.spot}
              onChange={(e) => setChainForm({ ...chainForm, spot: e.target.value })}
              className="w-full bg-trading-bg-secondary border border-trading-border/60 rounded-xl px-3 py-2 text-sm font-mono text-white focus:outline-none focus:border-trading-ai/40"
            />
          </div>
          <div>
            <label className="text-xs text-slate-500 uppercase block mb-1">Expiry (Days)</label>
            <input
              type="number"
              value={chainForm.expiryDays}
              onChange={(e) => setChainForm({ ...chainForm, expiryDays: e.target.value })}
              className="w-full bg-trading-bg-secondary border border-trading-border/60 rounded-xl px-3 py-2 text-sm font-mono text-white focus:outline-none focus:border-trading-ai/40"
            />
          </div>
          <div>
            <label className="text-xs text-slate-500 uppercase block mb-1">Strike Step</label>
            <input
              type="number"
              value={chainForm.strikeStep}
              onChange={(e) => setChainForm({ ...chainForm, strikeStep: e.target.value })}
              className="w-full bg-trading-bg-secondary border border-trading-border/60 rounded-xl px-3 py-2 text-sm font-mono text-white focus:outline-none focus:border-trading-ai/40"
            />
          </div>
          <button
            onClick={handleFetchChain}
            disabled={chainLoading}
            className={cn(
              'flex items-center justify-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-all',
              chainLoading ? 'bg-trading-bg-secondary text-slate-400' : 'gradient-ai text-white hover:opacity-90'
            )}
          >
            {chainLoading ? <Loader2 size={16} className="animate-spin" /> : <Search size={16} />}
            Build Chain
          </button>
        </div>

        {chainError && (
          <div className="flex items-center gap-2 text-trading-bear text-sm mb-4">
            <AlertCircle size={16} /> {chainError}
          </div>
        )}

        {chain && chain.chain && chain.chain.length > 0 && (
          <div className="mt-2">
            <div className="flex items-center gap-3 text-xs text-slate-400 mb-3">
              <span>Spot: <span className="text-white font-mono tabular-nums font-medium">{chain.spot}</span></span>
              <span>ATM: <span className="text-trading-ai-light font-mono tabular-nums">{chain.atm_strike}</span></span>
              <span>Expiry: <span className="text-white font-mono tabular-nums">{chain.expiry_days}d</span></span>
              <span>Strikes: <span className="text-white font-mono tabular-nums">{chain.strikes_count}</span></span>
            </div>
            <OptionChainTable chain={chain.chain} spot={chain.spot} />
          </div>
        )}
      </GlassCard>

      {/* Single Option Greeks Calculator */}
      <GlassCard>
        <h3 className="stat-label">
          Single Option Calculator
        </h3>
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3 items-end">
          <div>
            <label className="text-xs text-slate-500 uppercase block mb-1">Spot</label>
            <input
              type="number"
              value={calcForm.spot}
              onChange={(e) => setCalcForm({ ...calcForm, spot: e.target.value })}
              className="w-full bg-trading-bg-secondary border border-trading-border/60 rounded-xl px-3 py-2 text-sm font-mono text-white focus:outline-none focus:border-trading-ai/40"
            />
          </div>
          <div>
            <label className="text-xs text-slate-500 uppercase block mb-1">Strike</label>
            <input
              type="number"
              value={calcForm.strike}
              onChange={(e) => setCalcForm({ ...calcForm, strike: e.target.value })}
              className="w-full bg-trading-bg-secondary border border-trading-border/60 rounded-xl px-3 py-2 text-sm font-mono text-white focus:outline-none focus:border-trading-ai/40"
            />
          </div>
          <div>
            <label className="text-xs text-slate-500 uppercase block mb-1">Expiry (Days)</label>
            <input
              type="number"
              value={calcForm.expiryDays}
              onChange={(e) => setCalcForm({ ...calcForm, expiryDays: e.target.value })}
              className="w-full bg-trading-bg-secondary border border-trading-border/60 rounded-xl px-3 py-2 text-sm font-mono text-white focus:outline-none focus:border-trading-ai/40"
            />
          </div>
          <div>
            <label className="text-xs text-slate-500 uppercase block mb-1">Vol (%)</label>
            <input
              type="number"
              value={calcForm.volatility}
              onChange={(e) => setCalcForm({ ...calcForm, volatility: e.target.value })}
              className="w-full bg-trading-bg-secondary border border-trading-border/60 rounded-xl px-3 py-2 text-sm font-mono text-white focus:outline-none focus:border-trading-ai/40"
            />
          </div>
          <div>
            <label className="text-xs text-slate-500 uppercase block mb-1">Rate (%)</label>
            <input
              type="number"
              value={calcForm.rate}
              onChange={(e) => setCalcForm({ ...calcForm, rate: e.target.value })}
              className="w-full bg-trading-bg-secondary border border-trading-border/60 rounded-xl px-3 py-2 text-sm font-mono text-white focus:outline-none focus:border-trading-ai/40"
            />
          </div>
          <div>
            <label className="text-xs text-slate-500 uppercase block mb-1">Type</label>
            <select
              value={calcForm.optionType}
              onChange={(e) => setCalcForm({ ...calcForm, optionType: e.target.value as 'CE' | 'PE' })}
              className="w-full bg-trading-bg-secondary border border-trading-border/60 rounded-xl px-3 py-2 text-sm font-mono text-white focus:outline-none focus:border-trading-ai/40"
            >
              <option value="CE">Call (CE)</option>
              <option value="PE">Put (PE)</option>
            </select>
          </div>
          <button
            onClick={handleCalculate}
            disabled={calcLoading}
            className={cn(
              'flex items-center justify-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-all',
              calcLoading ? 'bg-trading-bg-secondary text-slate-400' : 'gradient-ai text-white hover:opacity-90'
            )}
          >
            {calcLoading ? <Loader2 size={16} className="animate-spin" /> : <Calculator size={16} />}
            Calculate
          </button>
        </div>

        {calcError && (
          <div className="flex items-center gap-2 text-trading-bear text-sm mt-3">
            <AlertCircle size={16} /> {calcError}
          </div>
        )}

        {greeks && (
          <div className="grid grid-cols-3 sm:grid-cols-6 gap-3 mt-4">
            {[
              { label: 'Price', value: greeks.price.toFixed(2), color: 'text-white' },
              { label: 'Delta', value: greeks.delta.toFixed(4), color: 'text-trading-bull' },
              { label: 'Gamma', value: greeks.gamma.toFixed(6), color: 'text-trading-info' },
              { label: 'Theta', value: greeks.theta.toFixed(2), color: 'text-trading-bear' },
              { label: 'Vega', value: greeks.vega.toFixed(2), color: 'text-trading-alert' },
              { label: 'Rho', value: greeks.rho.toFixed(2), color: 'text-slate-300' },
            ].map((g) => (
              <div key={g.label} className="text-center p-3 rounded-xl bg-trading-card">
                <p className={cn('text-lg font-mono tabular-nums font-bold', g.color)}>{g.value}</p>
                <p className="text-[10px] text-slate-500 uppercase mt-1">{g.label}</p>
              </div>
            ))}
          </div>
        )}
      </GlassCard>
    </motion.div>
  );
}
