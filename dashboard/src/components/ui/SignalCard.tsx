import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ArrowUpRight, ArrowDownRight, Brain, CheckCircle2, XCircle,
  ShieldCheck, Loader2, AlertTriangle, ChevronDown, ChevronUp,
} from 'lucide-react';
import { cn } from '../../lib/utils';
import type { Signal, PreTradeResult } from '../../types';
import { signalApi } from '../../services/api';
import StatusBadge from './StatusBadge';

const EXCHANGE_COLORS: Record<string, string> = {
  NSE: 'bg-blue-500/10 text-blue-400 border-blue-500/15',
  BSE: 'bg-blue-500/10 text-blue-300 border-blue-500/15',
  MCX: 'bg-amber-500/10 text-amber-400 border-amber-500/15',
  NFO: 'bg-purple-500/10 text-purple-400 border-purple-500/15',
  CDS: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/15',
};

const VERDICT_STYLES: Record<string, string> = {
  GO: 'bg-trading-bull/12 text-trading-bull border-trading-bull/20',
  CAUTION: 'bg-trading-alert/12 text-trading-alert border-trading-alert/20',
  BLOCK: 'bg-trading-bear/12 text-trading-bear border-trading-bear/20',
};

const STATUS_ICON: Record<string, { icon: typeof CheckCircle2; color: string }> = {
  PASS: { icon: CheckCircle2, color: 'text-trading-bull' },
  WARN: { icon: AlertTriangle, color: 'text-trading-alert' },
  FAIL: { icon: XCircle, color: 'text-trading-bear' },
};

function ExchangeBadge({ exchange }: { exchange: string }) {
  const color = EXCHANGE_COLORS[exchange] || 'bg-slate-700/30 text-slate-500 border-slate-600/20';
  return (
    <span className={cn('text-[9px] font-mono font-bold px-1.5 py-0.5 rounded-md border tracking-wider', color)}>
      {exchange}
    </span>
  );
}

interface SignalCardProps {
  signal: Signal;
}

export default function SignalCard({ signal }: SignalCardProps) {
  const [pretradeResult, setPretradeResult] = useState<PreTradeResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const isLong = signal.direction === 'LONG' || signal.direction === 'BUY';
  const confidencePct = Math.round(signal.ai_confidence * 100);
  const isOpen = signal.status === 'OPEN';

  const runPretradeCheck = async () => {
    setLoading(true);
    try {
      const result = await signalApi.pretradeCheck(signal.id);
      setPretradeResult(result);
      setExpanded(true);
    } catch {
      setPretradeResult({
        signal_id: signal.id,
        ticker: signal.ticker,
        direction: signal.direction,
        verdict: 'BLOCK',
        checks: [{ name: 'Error', status: 'FAIL', detail: 'Failed to run pre-trade checks' }],
        pass_count: 0,
        warn_count: 0,
        fail_count: 1,
      });
      setExpanded(true);
    } finally {
      setLoading(false);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
      className={cn(
        'glass-card-hover p-4 space-y-3 relative overflow-hidden',
        isLong ? 'border-l-2 border-l-trading-bull/60' : 'border-l-2 border-l-trading-bear/60'
      )}
    >
      {/* Subtle direction glow */}
      <div className={cn(
        'absolute top-0 left-0 w-32 h-32 rounded-full blur-3xl opacity-[0.04] -translate-x-1/2 -translate-y-1/2',
        isLong ? 'bg-trading-bull' : 'bg-trading-bear'
      )} />

      {/* Header */}
      <div className="flex items-center justify-between relative">
        <div className="flex items-center gap-2 flex-wrap">
          <div className={cn(
            'flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-bold border',
            isLong
              ? 'bg-trading-bull/8 text-trading-bull border-trading-bull/15'
              : 'bg-trading-bear/8 text-trading-bear border-trading-bear/15'
          )}>
            {isLong ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}
            {isLong ? 'BUY' : 'SHORT'}
          </div>
          <span className="text-base font-bold text-white font-mono tracking-tight">{signal.ticker}</span>
          <ExchangeBadge exchange={signal.exchange} />
          <span className="text-[9px] font-mono text-slate-600 bg-trading-card px-1.5 py-0.5 rounded-md border border-trading-border/30">
            {signal.timeframe || '1D'}
          </span>
          <span className="text-[10px] text-slate-400 bg-trading-card px-2 py-0.5 rounded-md border border-trading-border/30">
            {signal.pattern}
          </span>
        </div>
        <StatusBadge status={signal.status} size="sm" />
      </div>

      {/* Price Levels */}
      <div className="grid grid-cols-3 gap-2">
        <div className="text-center p-2.5 rounded-xl bg-trading-bg-secondary/60 border border-trading-border/20">
          <p className="stat-label mb-1">Entry</p>
          <p className="text-sm font-mono font-bold text-white tabular-nums">{signal.entry_price.toFixed(2)}</p>
        </div>
        <div className="text-center p-2.5 rounded-xl bg-trading-bear/[0.04] border border-trading-bear/10">
          <p className="text-[10px] text-trading-bear/70 uppercase tracking-[0.12em] font-medium mb-1">Stop Loss</p>
          <p className="text-sm font-mono font-bold text-trading-bear tabular-nums">{signal.stop_loss.toFixed(2)}</p>
        </div>
        <div className="text-center p-2.5 rounded-xl bg-trading-bull/[0.04] border border-trading-bull/10">
          <p className="text-[10px] text-trading-bull/70 uppercase tracking-[0.12em] font-medium mb-1">Target</p>
          <p className="text-sm font-mono font-bold text-trading-bull tabular-nums">{signal.target.toFixed(2)}</p>
        </div>
      </div>

      {/* Bottom Row */}
      <div className="flex items-center justify-between pt-1">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <span className="text-[9px] text-slate-600 uppercase tracking-wider">RRR</span>
            <span className="text-xs font-mono font-bold text-trading-info tabular-nums">{signal.rrr.toFixed(1)}</span>
          </div>
          <div className="flex items-center gap-1">
            {signal.tv_confirmed ? (
              <CheckCircle2 size={11} className="text-trading-bull" />
            ) : (
              <XCircle size={11} className="text-slate-600" />
            )}
            <span className="text-[9px] text-slate-600">TV</span>
          </div>
          <StatusBadge status={signal.mwa_score as 'BULL' | 'BEAR' | 'SIDEWAYS' | 'MILD_BULL' | 'MILD_BEAR'} size="sm" />
        </div>

        {/* AI Confidence */}
        <div className="flex items-center gap-2">
          <Brain size={11} className="text-trading-ai/70" />
          <div className="w-16 h-1.5 bg-trading-bg-secondary rounded-full overflow-hidden border border-trading-border/20">
            <div className="h-full rounded-full gradient-ai" style={{ width: `${confidencePct}%` }} />
          </div>
          <span className="text-[10px] font-mono font-bold text-trading-ai-light tabular-nums">{confidencePct}%</span>
        </div>
      </div>

      {/* Pre-Trade Check */}
      {isOpen && (
        <div className="pt-2 border-t border-trading-border/20">
          <div className="flex items-center gap-2">
            <button
              onClick={runPretradeCheck}
              disabled={loading}
              className={cn(
                'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[10px] font-semibold transition-all',
                'bg-white/[0.03] hover:bg-white/[0.06] text-slate-400 hover:text-white border border-trading-border/30',
                loading && 'opacity-50 cursor-not-allowed'
              )}
            >
              {loading ? <Loader2 size={12} className="animate-spin" /> : <ShieldCheck size={12} />}
              {loading ? 'Checking...' : 'Pre-Trade Check'}
            </button>

            {pretradeResult && (
              <>
                <span className={cn(
                  'px-2 py-0.5 rounded-lg text-[10px] font-bold border',
                  VERDICT_STYLES[pretradeResult.verdict] || VERDICT_STYLES.BLOCK
                )}>
                  {pretradeResult.verdict}
                </span>
                <span className="text-[9px] text-slate-600 font-mono tabular-nums">
                  {pretradeResult.pass_count}P / {pretradeResult.warn_count}W / {pretradeResult.fail_count}F
                </span>
                <button
                  onClick={() => setExpanded(!expanded)}
                  className="ml-auto text-slate-500 hover:text-white transition-colors"
                >
                  {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                </button>
              </>
            )}
          </div>

          <AnimatePresence>
            {expanded && pretradeResult && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
                className="overflow-hidden"
              >
                <div className="mt-2 space-y-1">
                  {pretradeResult.checks.map((check) => {
                    const { icon: Icon, color } = STATUS_ICON[check.status] || STATUS_ICON.FAIL;
                    return (
                      <div
                        key={check.name}
                        className="flex items-start gap-2 px-2.5 py-2 rounded-lg bg-trading-bg-secondary/50 border border-trading-border/15"
                      >
                        <Icon size={12} className={cn('mt-0.5 flex-shrink-0', color)} />
                        <div className="min-w-0 flex-1">
                          <span className="text-[10px] font-medium text-slate-300">{check.name}</span>
                          <p className="text-[9px] text-slate-600 truncate">{check.detail}</p>
                        </div>
                        <span className={cn('text-[9px] font-bold flex-shrink-0', color)}>
                          {check.status}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}
    </motion.div>
  );
}
