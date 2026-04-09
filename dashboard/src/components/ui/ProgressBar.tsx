import { motion } from 'framer-motion';
import { cn } from '../../lib/utils';

interface ProgressBarProps {
  current: number;
  min: number;
  max: number;
  label?: string;
  isShort?: boolean;
  pnlPct?: number;
}

export default function ProgressBar({ current, min, max, label, isShort, pnlPct }: ProgressBarProps) {
  const range = max - min;
  const rawPct = range > 0 ? ((current - min) / range) * 100 : 50;
  const pct = Math.max(0, Math.min(100, rawPct));

  const isProfit = pnlPct !== undefined ? pnlPct >= 0 : (isShort ? 100 - pct >= 50 : pct >= 50);
  const barColor = isProfit ? 'bg-trading-bull' : 'bg-trading-bear';

  const slLabel = isShort ? max : min;
  const tLabel = isShort ? min : max;

  return (
    <div className="w-full">
      {label && (
        <p className="text-[9px] text-slate-600 mb-1 font-mono">{label}</p>
      )}
      <div className="relative">
        <div className="flex justify-between mb-1">
          <span className="text-[8px] font-mono text-trading-bear/60 tabular-nums">SL {slLabel.toFixed(1)}</span>
          <span className="text-[8px] font-mono text-trading-bull/60 tabular-nums">T {tLabel.toFixed(1)}</span>
        </div>

        <div className="h-1.5 bg-trading-bg-secondary rounded-full overflow-visible relative border border-trading-border/15">
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${pct}%` }}
            transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
            className={cn('h-full rounded-full', barColor)}
          />

          <motion.div
            initial={{ left: '0%' }}
            animate={{ left: `${pct}%` }}
            transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
            className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2"
          >
            <div className={cn(
              'w-2.5 h-2.5 rounded-full border-[1.5px] border-white/80',
              barColor,
              isProfit ? 'shadow-[0_0_6px_rgba(0,230,118,0.4)]' : 'shadow-[0_0_6px_rgba(255,23,68,0.4)]'
            )} />
          </motion.div>
        </div>

        <div className="flex justify-center mt-1">
          <span className="text-[9px] font-mono text-white font-semibold tabular-nums">{current.toFixed(1)}</span>
        </div>
      </div>
    </div>
  );
}
