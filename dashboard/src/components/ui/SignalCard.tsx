import { motion } from 'framer-motion';
import { ArrowUpRight, ArrowDownRight, Brain, CheckCircle2, XCircle } from 'lucide-react';
import { cn } from '../../lib/utils';
import type { Signal } from '../../types';
import StatusBadge from './StatusBadge';

interface SignalCardProps {
  signal: Signal;
}

export default function SignalCard({ signal }: SignalCardProps) {
  const isLong = signal.direction === 'LONG';
  const directionColor = isLong ? 'text-trading-bull' : 'text-trading-bear';
  const directionBg = isLong ? 'bg-trading-bull/10' : 'bg-trading-bear/10';
  const directionBorder = isLong ? 'border-trading-bull/20' : 'border-trading-bear/20';
  const confidencePct = Math.round(signal.ai_confidence * 100);

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
      {/* Header: Direction + Ticker + Pattern */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
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
    </motion.div>
  );
}
