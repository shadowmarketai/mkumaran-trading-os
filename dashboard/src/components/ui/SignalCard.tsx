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
  NSE: 'bg-blue-500/15 text-blue-400 border-blue-500/20',
  BSE: 'bg-blue-500/15 text-blue-300 border-blue-500/20',
  MCX: 'bg-amber-500/15 text-amber-400 border-amber-500/20',
  NFO: 'bg-purple-500/15 text-purple-400 border-purple-500/20',
  CDS: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/20',
};

const VERDICT_STYLES: Record<string, string> = {
  GO: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  CAUTION: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  BLOCK: 'bg-red-500/20 text-red-400 border-red-500/30',
};

const STATUS_ICON: Record<string, { icon: typeof CheckCircle2; color: string }> = {
  PASS: { icon: CheckCircle2, color: 'text-emerald-400' },
  WARN: { icon: AlertTriangle, color: 'text-amber-400' },
  FAIL: { icon: XCircle, color: 'text-red-400' },
};

function ExchangeBadge({ exchange }: { exchange: string }) {
  const color = EXCHANGE_COLORS[exchange] || 'bg-slate-700 text-slate-400 border-slate-600';
  return (
    <span className={cn('text-[10px] font-mono font-semibold px-1.5 py-0.5 rounded border', color)}>
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
  const directionColor = isLong ? 'text-trading-bull' : 'text-trading-bear';
  const directionBg = isLong ? 'bg-trading-bull/10' : 'bg-trading-bear/10';
  const directionBorder = isLong ? 'border-trading-bull/20' : 'border-trading-bear/20';
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
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className={cn(
        'glass-card-hover p-4 space-y-3',
        isLong ? 'border-l-2 border-l-trading-bull' : 'border-l-2 border-l-trading-bear'
      )}
    >
      {/* Header: Direction + Ticker + Exchange + TF + Pattern */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div
            className={cn(
              'flex items-center gap-1 px-2 py-1 rounded-md text-xs font-bold border',
              directionBg,
              directionColor,
              directionBorder
            )}
          >
            {isLong ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}
            {isLong ? 'BUY' : 'SHORT'}
          </div>
          <span className="text-lg font-bold text-white font-mono">{signal.ticker}</span>
          <ExchangeBadge exchange={signal.exchange} />
          <span className="text-[10px] font-mono text-slate-500 bg-slate-800 px-1.5 py-0.5 rounded">{signal.timeframe || '1D'}</span>
          <span className="text-xs text-slate-400 bg-slate-800 px-2 py-0.5 rounded">{signal.pattern}</span>
        </div>
        <StatusBadge status={signal.status} size="sm" />
      </div>

      {/* Price Levels */}
      <div className="grid grid-cols-3 gap-3">
        <div className="text-center p-2 rounded-lg bg-slate-800/50">
          <p className="text-[10px] text-slate-500 uppercase tracking-wider">Entry</p>
          <p className="text-sm font-mono font-semibold text-white">{signal.entry_price.toFixed(2)}</p>
        </div>
        <div className="text-center p-2 rounded-lg bg-trading-bear/5 border border-trading-bear/10">
          <p className="text-[10px] text-trading-bear uppercase tracking-wider">Stop Loss</p>
          <p className="text-sm font-mono font-semibold text-trading-bear">{signal.stop_loss.toFixed(2)}</p>
        </div>
        <div className="text-center p-2 rounded-lg bg-trading-bull/5 border border-trading-bull/10">
          <p className="text-[10px] text-trading-bull uppercase tracking-wider">Target</p>
          <p className="text-sm font-mono font-semibold text-trading-bull">{signal.target.toFixed(2)}</p>
        </div>
      </div>

      {/* Bottom Row: RRR, AI Confidence, TV Confirmed, MWA */}
      <div className="flex items-center justify-between pt-1">
        <div className="flex items-center gap-3">
          {/* RRR */}
          <div className="flex items-center gap-1">
            <span className="text-[10px] text-slate-500">RRR</span>
            <span className="text-xs font-mono font-bold text-trading-info">{signal.rrr.toFixed(1)}</span>
          </div>

          {/* TV Confirmed */}
          <div className="flex items-center gap-1">
            {signal.tv_confirmed ? (
              <CheckCircle2 size={12} className="text-trading-bull" />
            ) : (
              <XCircle size={12} className="text-slate-500" />
            )}
            <span className="text-[10px] text-slate-500">TV</span>
          </div>

          {/* MWA Score */}
          <StatusBadge status={signal.mwa_score as 'BULL' | 'BEAR' | 'SIDEWAYS' | 'MILD_BULL' | 'MILD_BEAR'} size="sm" />
        </div>

        {/* AI Confidence Bar */}
        <div className="flex items-center gap-2">
          <Brain size={12} className="text-trading-ai" />
          <div className="w-20 h-1.5 bg-slate-700 rounded-full overflow-hidden">
            <div
              className="h-full rounded-full gradient-ai"
              style={{ width: `${confidencePct}%` }}
            />
          </div>
          <span className="text-[10px] font-mono text-trading-ai-light">{confidencePct}%</span>
        </div>
      </div>

      {/* Pre-Trade Check Button — only for OPEN signals */}
      {isOpen && (
        <div className="pt-1 border-t border-slate-700/50">
          <div className="flex items-center gap-2">
            <button
              onClick={runPretradeCheck}
              disabled={loading}
              className={cn(
                'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition-all',
                'bg-slate-700/50 hover:bg-slate-600/50 text-slate-300 hover:text-white border border-slate-600/50',
                loading && 'opacity-60 cursor-not-allowed'
              )}
            >
              {loading ? (
                <Loader2 size={13} className="animate-spin" />
              ) : (
                <ShieldCheck size={13} />
              )}
              {loading ? 'Checking...' : 'Pre-Trade Check'}
            </button>

            {/* Verdict badge (shown after check) */}
            {pretradeResult && (
              <>
                <span
                  className={cn(
                    'px-2 py-0.5 rounded text-xs font-bold border',
                    VERDICT_STYLES[pretradeResult.verdict] || VERDICT_STYLES.BLOCK
                  )}
                >
                  {pretradeResult.verdict}
                </span>
                <span className="text-[10px] text-slate-500">
                  {pretradeResult.pass_count}P / {pretradeResult.warn_count}W / {pretradeResult.fail_count}F
                </span>
                <button
                  onClick={() => setExpanded(!expanded)}
                  className="ml-auto text-slate-400 hover:text-white transition-colors"
                >
                  {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                </button>
              </>
            )}
          </div>

          {/* Expandable results panel */}
          <AnimatePresence>
            {expanded && pretradeResult && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.2 }}
                className="overflow-hidden"
              >
                <div className="mt-2 space-y-1">
                  {pretradeResult.checks.map((check) => {
                    const { icon: Icon, color } = STATUS_ICON[check.status] || STATUS_ICON.FAIL;
                    return (
                      <div
                        key={check.name}
                        className="flex items-start gap-2 px-2 py-1.5 rounded bg-slate-800/40"
                      >
                        <Icon size={13} className={cn('mt-0.5 flex-shrink-0', color)} />
                        <div className="min-w-0">
                          <span className="text-xs font-medium text-slate-300">{check.name}</span>
                          <p className="text-[10px] text-slate-500 truncate">{check.detail}</p>
                        </div>
                        <span
                          className={cn(
                            'ml-auto text-[10px] font-bold flex-shrink-0',
                            color
                          )}
                        >
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
