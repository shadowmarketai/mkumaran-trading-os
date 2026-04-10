import { useState, useEffect, useCallback, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
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
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import GlassCard from '../components/ui/GlassCard';
import MetricCard from '../components/ui/MetricCard';
import StatusBadge from '../components/ui/StatusBadge';
import CandlestickChart from '../components/ui/CandlestickChart';
import { signalMonitorApi } from '../services/api';
import { useMarketSegment } from '../context/MarketSegmentContext';
import { cn } from '../lib/utils';
import type { Signal, ClosedSignal } from '../types';

function isMarketHours(): boolean {
  const now = new Date();
  const utc = now.getTime() + now.getTimezoneOffset() * 60000;
  const ist = new Date(utc + 5.5 * 3600000);
  const h = ist.getHours();
  const m = ist.getMinutes();
  const day = ist.getDay();
  if (day === 0 || day === 6) return false;
  const mins = h * 60 + m;
  return mins >= 9 * 60 + 15 && mins <= 15 * 60 + 30;
}

export default function SignalMonitorPage() {
  const [openSignals, setOpenSignals] = useState<Signal[]>([]);
  const [recentClosed, setRecentClosed] = useState<ClosedSignal[]>([]);
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState(false);
  const [lastChecked, setLastChecked] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expandedSignalId, setExpandedSignalId] = useState<number | null>(null);
  const [marketOpen, setMarketOpen] = useState(isMarketHours());
  const [newSignalIds, setNewSignalIds] = useState<Set<number>>(new Set());
  const prevSignalIdsRef = useRef<Set<number>>(new Set());
  const { filter } = useMarketSegment();

  useEffect(() => {
    const timer = setInterval(() => setMarketOpen(isMarketHours()), 30000);
    return () => clearInterval(timer);
  }, []);

  const fetchOpenSignals = useCallback(async () => {
    try {
      const data = await signalMonitorApi.getOpenSignals(filter);
      const currentIds = new Set(data.map((s) => s.id));
      const prevIds = prevSignalIdsRef.current;
      const freshIds = new Set<number>();
      currentIds.forEach((id) => {
        if (!prevIds.has(id)) freshIds.add(id);
      });
      if (freshIds.size > 0) {
        setNewSignalIds(freshIds);
        setTimeout(() => setNewSignalIds(new Set()), 3000);
      }
      prevSignalIdsRef.current = currentIds;
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
    const interval = setInterval(fetchOpenSignals, 10000);
    return () => clearInterval(interval);
  }, [fetchOpenSignals]);

  const handleCheckNow = async () => {
    setChecking(true);
    try {
      const result = await signalMonitorApi.checkNow();
      setRecentClosed(result.closed_signals);
      setLastChecked(new Date().toLocaleTimeString());
      await fetchOpenSignals();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Check failed');
    } finally {
      setChecking(false);
    }
  };

  const toggleChart = (signalId: number) => {
    setExpandedSignalId((prev) => (prev === signalId ? null : signalId));
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <div className="w-12 h-12 rounded-2xl bg-trading-ai/10 flex items-center justify-center">
          <Loader2 size={24} className="text-trading-ai animate-spin" />
        </div>
        <p className="text-slate-500 text-xs mt-4 font-mono">Loading signal monitor...</p>
      </div>
    );
  }

  const totalOpen = openSignals.length;
  const longCount = openSignals.filter((s) => s.direction === 'LONG' || s.direction === 'BUY').length;
  const shortCount = openSignals.filter((s) => s.direction === 'SHORT' || s.direction === 'SELL').length;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      className="space-y-5"
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-xl bg-trading-ai/10 flex items-center justify-center">
            <Shield size={16} className="text-trading-ai" />
          </div>
          <h2 className="text-sm font-bold text-white">Signal Monitor</h2>
          {marketOpen ? (
            <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-lg bg-trading-bull/10 border border-trading-bull/20">
              <span className="relative flex h-1.5 w-1.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-trading-bull opacity-75" />
                <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-trading-bull" />
              </span>
              <span className="text-[9px] font-bold text-trading-bull uppercase tracking-wider">Live</span>
            </span>
          ) : (
            <span className="text-[10px] text-slate-600 font-mono">Market closed</span>
          )}
          <span className="text-[9px] text-slate-600 font-mono">Polling 10s</span>
        </div>
        <div className="flex items-center gap-3">
          {lastChecked && (
            <span className="text-[10px] text-slate-600 flex items-center gap-1 font-mono">
              <Clock size={10} /> {lastChecked}
            </span>
          )}
          <button
            onClick={handleCheckNow}
            disabled={checking}
            className={cn(
              'flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold transition-all',
              checking
                ? 'bg-trading-bg-secondary text-slate-500 cursor-not-allowed'
                : 'bg-trading-ai/12 text-trading-ai-light hover:bg-trading-ai/18 border border-trading-ai/25'
            )}
          >
            {checking ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
            {checking ? 'Checking...' : 'Check Now'}
          </button>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 p-3 rounded-xl bg-trading-bear/6 border border-trading-bear/12">
          <AlertCircle size={14} className="text-trading-bear" />
          <span className="text-xs text-trading-bear">{error}</span>
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <MetricCard title="Open Signals" value={totalOpen} icon={Target} color="alert" />
        <MetricCard title="Long" value={longCount} icon={TrendingUp} color="bull" />
        <MetricCard title="Short" value={shortCount} icon={TrendingDown} color="bear" />
        <MetricCard title="Recently Closed" value={recentClosed.length} icon={CheckCircle2} color="info" />
      </div>

      {/* Recently Closed */}
      {recentClosed.length > 0 && (
        <GlassCard glowColor={recentClosed.some((c) => c.outcome === 'WIN') ? 'bull' : 'bear'}>
          <h3 className="stat-label mb-3 flex items-center gap-2">
            <CheckCircle2 size={12} className="text-trading-info" />
            Just Closed
          </h3>
          <div className="space-y-1.5">
            {recentClosed.map((c) => (
              <div
                key={c.signal_id}
                className={cn(
                  'flex items-center justify-between p-3 rounded-xl border',
                  c.outcome === 'WIN'
                    ? 'bg-trading-bull/[0.03] border-trading-bull/12'
                    : 'bg-trading-bear/[0.03] border-trading-bear/12'
                )}
              >
                <div className="flex items-center gap-3">
                  {c.outcome === 'WIN' ? (
                    <CheckCircle2 size={14} className="text-trading-bull" />
                  ) : (
                    <XCircle size={14} className="text-trading-bear" />
                  )}
                  <span className="font-mono font-bold text-white text-sm">{c.ticker}</span>
                  <span className="text-[10px] text-slate-500">{c.direction}</span>
                  <span className="text-[10px] text-slate-600">{c.status.replace('_', ' ')}</span>
                </div>
                <div className="flex items-center gap-4">
                  <span className="text-[10px] text-slate-500 font-mono tabular-nums">
                    {c.entry.toFixed(1)} → {c.exit.toFixed(1)}
                  </span>
                  <span className={cn('text-xs font-mono font-bold tabular-nums', c.pnl_pct >= 0 ? 'text-trading-bull' : 'text-trading-bear')}>
                    {c.pnl_pct >= 0 ? '+' : ''}{c.pnl_pct.toFixed(1)}%
                  </span>
                  <span className="text-[10px] text-slate-600 font-mono">{c.days_held}d</span>
                </div>
              </div>
            ))}
          </div>
        </GlassCard>
      )}

      {/* Open Signals Table */}
      {totalOpen > 0 ? (
        <GlassCard className="!p-0 overflow-hidden">
          <div className="px-5 py-3.5 border-b border-trading-border/20">
            <h3 className="stat-label">Open Signals Being Monitored</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[9px] text-slate-500 uppercase tracking-[0.12em] border-b border-trading-border/20">
                  <th className="text-left py-3 px-2 w-6"></th>
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
              <tbody>
                {openSignals.map((sig, idx) => {
                  const isLong = sig.direction === 'LONG' || sig.direction === 'BUY';
                  const confidencePct = Math.round(sig.ai_confidence);
                  const isExpanded = expandedSignalId === sig.id;
                  const isNew = newSignalIds.has(sig.id);

                  return (
                    <motion.tr
                      key={sig.id}
                      initial={isNew ? { opacity: 0, backgroundColor: 'rgba(0,230,118,0.1)' } : { opacity: 0, x: -8 }}
                      animate={isNew
                        ? { opacity: 1, backgroundColor: 'rgba(0,230,118,0)', transition: { duration: 2 } }
                        : { opacity: 1, x: 0 }
                      }
                      transition={{ duration: 0.2, delay: idx * 0.03 }}
                      onClick={() => toggleChart(sig.id)}
                      className={cn(
                        'cursor-pointer transition-colors border-b border-trading-border/10',
                        isExpanded ? 'bg-white/[0.02]' : 'hover:bg-white/[0.015]',
                        isNew && 'ring-1 ring-trading-bull/20'
                      )}
                    >
                      <td className="py-3 px-2">
                        {isExpanded ? <ChevronUp size={12} className="text-slate-500" /> : <ChevronDown size={12} className="text-slate-600" />}
                      </td>
                      <td className="py-3 px-2">
                        <span className="font-mono font-bold text-white text-sm">{sig.ticker}</span>
                      </td>
                      <td className="py-3 px-2 text-center">
                        <span className={cn(
                          'text-[9px] font-mono font-bold px-1.5 py-0.5 rounded-md border',
                          sig.exchange === 'MCX' ? 'bg-amber-500/8 text-amber-400 border-amber-500/15' :
                          sig.exchange === 'CDS' ? 'bg-emerald-500/8 text-emerald-400 border-emerald-500/15' :
                          'bg-blue-500/8 text-blue-400 border-blue-500/15'
                        )}>
                          {sig.exchange || 'NSE'}
                        </span>
                      </td>
                      <td className="py-3 px-2 text-center">
                        <div className={cn(
                          'inline-flex items-center gap-0.5 text-[10px] font-bold',
                          isLong ? 'text-trading-bull' : 'text-trading-bear'
                        )}>
                          {isLong ? <ArrowUpRight size={11} /> : <ArrowDownRight size={11} />}
                          {isLong ? 'LONG' : 'SHORT'}
                        </div>
                      </td>
                      <td className="py-3 px-2 text-right font-mono text-slate-300 text-xs tabular-nums">{sig.entry_price.toFixed(2)}</td>
                      <td className="py-3 px-2 text-right font-mono text-trading-bear/70 text-xs tabular-nums">{sig.stop_loss.toFixed(2)}</td>
                      <td className="py-3 px-2 text-right font-mono text-trading-bull/70 text-xs tabular-nums">{sig.target.toFixed(2)}</td>
                      <td className="py-3 px-2 text-center font-mono text-trading-info text-xs tabular-nums">{sig.rrr.toFixed(1)}</td>
                      <td className="py-3 px-2 text-center">
                        <span className="text-[10px] text-slate-400 bg-trading-bg-secondary px-2 py-0.5 rounded-md border border-trading-border/20">
                          {sig.pattern}
                        </span>
                      </td>
                      <td className="py-3 px-2 text-center">
                        <div className="flex items-center justify-center gap-1.5">
                          <Brain size={11} className="text-trading-ai/60" />
                          <div className="w-10 h-1.5 bg-trading-bg-secondary rounded-full overflow-hidden border border-trading-border/20">
                            <div className="h-full rounded-full gradient-ai" style={{ width: `${confidencePct}%` }} />
                          </div>
                          <span className="text-[9px] font-mono text-trading-ai-light tabular-nums">{confidencePct}%</span>
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

            <AnimatePresence>
              {expandedSignalId && (() => {
                const sig = openSignals.find((s) => s.id === expandedSignalId);
                if (!sig) return null;
                const chartTicker = sig.exchange && sig.exchange !== 'NSE'
                  ? `${sig.exchange}:${sig.ticker}`
                  : sig.ticker;
                return (
                  <motion.div
                    key={`chart-${expandedSignalId}`}
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: 'auto' }}
                    exit={{ opacity: 0, height: 0 }}
                    transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
                    className="border-t border-trading-border/20 p-4"
                  >
                    <CandlestickChart
                      ticker={chartTicker}
                      interval="1D"
                      signal={{
                        entry: sig.entry_price,
                        sl: sig.stop_loss,
                        target: sig.target,
                        direction: sig.direction,
                      }}
                      height={350}
                    />
                  </motion.div>
                );
              })()}
            </AnimatePresence>
          </div>
        </GlassCard>
      ) : (
        <GlassCard className="flex flex-col items-center justify-center py-16">
          <div className="w-12 h-12 rounded-2xl bg-slate-800/50 flex items-center justify-center mb-4">
            <Shield size={24} className="text-slate-600" />
          </div>
          <p className="text-slate-500 text-xs">No open signals being monitored</p>
          <p className="text-slate-600 text-[10px] mt-1">Signals from MWA scan will appear here</p>
        </GlassCard>
      )}

      <p className="sebi-disclaimer mt-4">
        This platform provides AI-powered market analytics and decision support tools for educational purposes only.
        Not SEBI-registered investment advice. Past performance is not indicative of future results.
        Consult a SEBI-registered financial advisor before making investment decisions.
      </p>
    </motion.div>
  );
}
