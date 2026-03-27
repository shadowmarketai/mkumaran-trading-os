import { motion } from 'framer-motion';
import { cn } from '../../lib/utils';

interface ProgressBarProps {
  current: number;
  min: number;
  max: number;
  label?: string;
}

export default function ProgressBar({ current, min, max, label }: ProgressBarProps) {
  const range = max - min;
  const rawPct = range > 0 ? ((current - min) / range) * 100 : 50;
  const pct = Math.max(0, Math.min(100, rawPct));

  // Determine color: near SL (min) = red, middle = amber, near target (max) = green
  const getColor = (percentage: number): string => {
    if (percentage < 30) return 'bg-trading-bear';
    if (percentage < 60) return 'bg-trading-alert';
    return 'bg-trading-bull';
  };

  const getGlowColor = (percentage: number): string => {
    if (percentage < 30) return 'shadow-[0_0_8px_rgba(244,63,94,0.3)]';
    if (percentage < 60) return 'shadow-[0_0_8px_rgba(245,158,11,0.3)]';
    return 'shadow-[0_0_8px_rgba(16,185,129,0.3)]';
  };

  return (
    <div className="w-full">
      {label && (
        <p className="text-[10px] text-slate-500 mb-1 font-mono">{label}</p>
      )}
      <div className="relative">
        {/* SL and Target labels */}
        <div className="flex justify-between mb-1">
          <span className="text-[9px] font-mono text-trading-bear">SL {min.toFixed(1)}</span>
          <span className="text-[9px] font-mono text-trading-bull">T {max.toFixed(1)}</span>
        </div>

        {/* Track */}
        <div className="h-2 bg-slate-700/60 rounded-full overflow-visible relative">
          {/* Filled portion */}
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${pct}%` }}
            transition={{ duration: 0.8, ease: 'easeOut' }}
            className={cn('h-full rounded-full', getColor(pct))}
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
                getColor(pct),
                getGlowColor(pct)
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
