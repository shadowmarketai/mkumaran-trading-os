import { useState, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import {
  Shield,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  Target,
  AlertCircle,
  Loader2,
  CheckCircle2,
  XCircle,
  Clock,
  ArrowUpRight,
  ArrowDownRight,
  Brain,
} from 'lucide-react';
import GlassCard from '../components/ui/GlassCard';
import MetricCard from '../components/ui/MetricCard';
import StatusBadge from '../components/ui/StatusBadge';
import { signalMonitorApi } from '../services/api';
import { useMarketSegment } from '../context/MarketSegmentContext';
import { cn } from '../lib/utils';
import type { Signal, ClosedSignal } from '../types';

export default function SignalMonitorPage() {
  const [openSignals, setOpenSignals] = useState<Signal[]>([]);
  const [recentClosed, setRecentClosed] = useState<ClosedSignal[]>([]);
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState(false);
  const [lastChecked, setLastChecked] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { filter } = useMarketSegment();

  const fetchOpenSignals = useCallback(async () => {
    try {
      const data = await signalMonitorApi.getOpenSignals(filter);
      setOpenSignals(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch signals');
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    fetchOpenSignals();
    const interval = setInterval(fetchOpenSignals, 60000); // Refresh every 1 min
    return () => clearInterval(interval);
  }, [fetchOpenSignals]);

  const handleCheckNow = async () => {
    setChecking(true);
    try {
      const result = await signalMonitorApi.checkNow();
      setRecentClosed(result.closed_signals);
      setLastChecked(new Date().toLocaleTimeString());
      // Refresh open signals after check
      await fetchOpenSignals();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Check failed');
    } finally {
      setChecking(false);
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <Loader2 size={48} className="text-trading-ai animate-spin mb-4" />
        <p className="text-slate-400 text-sm">Loading signal monitor...</p>
      </div>
    );
  }

  const totalOpen = openSignals.length;
  const longCount = openSignals.filter((s) => s.direction === 'LONG').length;
  const shortCount = openSignals.filter((s) => s.direction === 'SHORT').length;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.4 }}
      className="space-y-6"
    >
      {/* Header with Check Now */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Shield size={20} className="text-trading-ai" />
          <h2 className="text-lg font-bold text-white">Signal Monitor</h2>
          <span className="text-xs text-slate-500 font-mono">Auto-checks every 5 min</span>
        </div>
        <div className="flex items-center gap-3">
          {lastChecked && (
            <span className="text-xs text-slate-500 flex items-center gap-1">
              <Clock size={12} /> Last: {lastChecked}
            </span>
          )}
          <button
            onClick={handleCheckNow}
            disabled={checking}
            className={cn(
              'flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all',
              checking
                ? 'bg-slate-700 text-slate-400 cursor-not-allowed'
                : 'bg-trading-ai/20 text-trading-ai-light hover:bg-trading-ai/30 border border-trading-ai/30'
            )}
          >
            {checking ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <RefreshCw size={14} />
            )}
            {checking ? 'Checking...' : 'Check Now'}
          </button>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 p-3 rounded-lg bg-trading-bear/10 border border-trading-bear/20">
          <AlertCircle size={16} className="text-trading-bear" />
          <span className="text-sm text-trading-bear">{error}</span>
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <MetricCard title="Open Signals" value={totalOpen} icon={Target} color="alert" />
        <MetricCard title="Long" value={longCount} icon={TrendingUp} color="bull" />
        <MetricCard title="Short" value={shortCount} icon={TrendingDown} color="bear" />
        <MetricCard
          title="Recently Closed"
          value={recentClosed.length}
          icon={CheckCircle2}
          color="info"
        />
      </div>

      {/* Recently Closed Signals (after Check Now) */}
      {recentClosed.length > 0 && (
        <GlassCard glowColor={recentClosed.some((c) => c.outcome === 'WIN') ? 'bull' : 'bear'}>
          <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-3 flex items-center gap-2">
            <CheckCircle2 size={14} className="text-trading-info" />
            Just Closed
          </h3>
          <div className="space-y-2">
            {recentClosed.map((c) => (
              <div
                key={c.signal_id}
                className={cn(
                  'flex items-center justify-between p-3 rounded-lg border',
                  c.outcome === 'WIN'
                    ? 'bg-trading-bull/5 border-trading-bull/20'
                    : 'bg-trading-bear/5 border-trading-bear/20'
                )}
              >
                <div className="flex items-center gap-3">
                  {c.outcome === 'WIN' ? (
                    <CheckCircle2 size={16} className="text-trading-bull" />
                  ) : (
                    <XCircle size={16} className="text-trading-bear" />
                  )}
                  <span className="font-mono font-bold text-white">{c.ticker}</span>
                  <span className="text-xs text-slate-400">{c.direction}</span>
                  <span className="text-xs text-slate-500">{c.status.replace('_', ' ')}</span>
                </div>
                <div className="flex items-center gap-4">
                  <span className="text-xs text-slate-400 font-mono">
                    {c.entry.toFixed(1)} → {c.exit.toFixed(1)}
                  </span>
                  <span
                    className={cn(
                      'text-sm font-mono font-bold',
                      c.pnl_pct >= 0 ? 'text-trading-bull' : 'text-trading-bear'
                    )}
                  >
                    {c.pnl_pct >= 0 ? '+' : ''}{c.pnl_pct.toFixed(1)}%
                  </span>
                  <span className="text-xs text-slate-500">{c.days_held}d</span>
                </div>
              </div>
            ))}
          </div>
        </GlassCard>
      )}

      {/* Open Signals Table */}
      {totalOpen > 0 ? (
        <GlassCard>
          <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-4">
            Open Signals Being Monitored
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-slate-500 uppercase tracking-wider border-b border-trading-border">
                  <th className="text-left py-3 px-2">Ticker</th>
                  <th className="text-center py-3 px-2">Exch</th>
                  <th className="text-center py-3 px-2">Dir</th>
                  <th className="text-right py-3 px-2 font-mono">Entry</th>
                  <th className="text-right py-3 px-2 font-mono">SL</th>
                  <th className="text-right py-3 px-2 font-mono">Target</th>
                  <th className="text-center py-3 px-2 font-mono">RRR</th>
                  <th className="text-center py-3 px-2">Pattern</th>
                  <th className="text-center py-3 px-2">Confidence</th>
                  <th className="text-center py-3 px-2">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-trading-border/50">
                {openSignals.map((sig, idx) => {
                  const isLong = sig.direction === 'LONG';
                  const confidencePct = Math.round(sig.ai_confidence * 100);
                  return (
                    <motion.tr
                      key={sig.id}
                      initial={{ opacity: 0, x: -10 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ duration: 0.2, delay: idx * 0.04 }}
                      className="hover:bg-slate-800/30 transition-colors"
                    >
                      <td className="py-3 px-2">
                        <span className="font-mono font-bold text-white">{sig.ticker}</span>
                      </td>
                      <td className="py-3 px-2 text-center">
                        <span
                          className={cn(
                            'text-[10px] font-mono font-semibold px-1.5 py-0.5 rounded border',
                            sig.exchange === 'MCX'
                              ? 'bg-amber-500/15 text-amber-400 border-amber-500/20'
                              : sig.exchange === 'CDS'
                                ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/20'
                                : 'bg-blue-500/15 text-blue-400 border-blue-500/20'
                          )}
                        >
                          {sig.exchange || 'NSE'}
                        </span>
                      </td>
                      <td className="py-3 px-2 text-center">
                        <div
                          className={cn(
                            'inline-flex items-center gap-0.5 text-xs font-bold',
                            isLong ? 'text-trading-bull' : 'text-trading-bear'
                          )}
                        >
                          {isLong ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}
                          {isLong ? 'LONG' : 'SHORT'}
                        </div>
                      </td>
                      <td className="py-3 px-2 text-right font-mono text-slate-300">
                        {sig.entry_price.toFixed(2)}
                      </td>
                      <td className="py-3 px-2 text-right font-mono text-trading-bear">
                        {sig.stop_loss.toFixed(2)}
                      </td>
                      <td className="py-3 px-2 text-right font-mono text-trading-bull">
                        {sig.target.toFixed(2)}
                      </td>
                      <td className="py-3 px-2 text-center font-mono text-trading-info">
                        {sig.rrr.toFixed(1)}
                      </td>
                      <td className="py-3 px-2 text-center">
                        <span className="text-xs text-slate-400 bg-slate-800 px-2 py-0.5 rounded">
                          {sig.pattern}
                        </span>
                      </td>
                      <td className="py-3 px-2 text-center">
                        <div className="flex items-center justify-center gap-1.5">
                          <Brain size={12} className="text-trading-ai" />
                          <div className="w-12 h-1.5 bg-slate-700 rounded-full overflow-hidden">
                            <div
                              className="h-full rounded-full gradient-ai"
                              style={{ width: `${confidencePct}%` }}
                            />
                          </div>
                          <span className="text-[10px] font-mono text-trading-ai-light">
                            {confidencePct}%
                          </span>
                        </div>
                      </td>
                      <td className="py-3 px-2 text-center">
                        <StatusBadge status={sig.status as 'OPEN'} size="sm" />
                      </td>
                    </motion.tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </GlassCard>
      ) : (
        <GlassCard className="flex flex-col items-center justify-center py-16">
          <Shield size={48} className="text-slate-600 mb-4" />
          <p className="text-slate-500 text-sm">No open signals being monitored</p>
          <p className="text-slate-600 text-xs mt-1">
            Signals from MWA scan will appear here when generated
          </p>
        </GlassCard>
      )}
    </motion.div>
  );
}
