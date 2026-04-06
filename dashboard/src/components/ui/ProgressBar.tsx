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

  // Color based on actual P&L: green = profit, red = loss
  const isProfit = pnlPct !== undefined ? pnlPct >= 0 : (isShort ? 100 - pct >= 50 : pct >= 50);
  const barColor = isProfit ? 'bg-trading-bull' : 'bg-trading-bear';
  const glowColor = isProfit
    ? 'shadow-[0_0_8px_rgba(16,185,129,0.3)]'
    : 'shadow-[0_0_8px_rgba(244,63,94,0.3)]';

  const slLabel = isShort ? max : min;
  const tLabel = isShort ? min : max;

  return (
    <div className="w-full">
      {label && (
        <p className="text-[10px] text-slate-500 mb-1 font-mono">{label}</p>
      )}
      <div className="relative">
        {/* SL and Target labels */}
        <div className="flex justify-between mb-1">
          <span className="text-[9px] font-mono text-trading-bear">SL {slLabel.toFixed(1)}</span>
          <span className="text-[9px] font-mono text-trading-bull">T {tLabel.toFixed(1)}</span>
        </div>

        {/* Track */}
        <div className="h-2 bg-slate-700/60 rounded-full overflow-visible relative">
          {/* Filled portion */}
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${pct}%` }}
            transition={{ duration: 0.8, ease: 'easeOut' }}
            className={cn('h-full rounded-full', barColor)}
          />

          {/* Current position marker */}
          <motion.div
            initial={{ left: '0%' }}
            animate={{ left: `${pct}%` }}
            transition={{ duration: 0.8, ease: 'easeOut' }}
            className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2"
          >
            <div
              className={cn(
                'w-3.5 h-3.5 rounded-full border-2 border-white',
                barColor,
                glowColor
              )}
            />
          </motion.div>
        </div>

        {/* Current price label */}
        <div className="flex justify-center mt-1">
          <span className="text-[10px] font-mono text-white font-semibold">
            {current.toFixed(1)}
          </span>
        </div>
      </div>
    </div>
  );
}
