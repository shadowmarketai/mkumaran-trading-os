import { motion } from 'framer-motion';
import { TrendingUp, TrendingDown, type LucideIcon } from 'lucide-react';
import { cn } from '../../lib/utils';

type MetricColor = 'bull' | 'bear' | 'info' | 'alert' | 'ai';

interface MetricCardProps {
  title: string;
  value: string | number;
  change?: number;
  icon: LucideIcon;
  color: MetricColor;
}

const colorMap: Record<MetricColor, { bg: string; text: string; iconBg: string }> = {
  bull: { bg: 'bg-trading-bull-bg', text: 'text-trading-bull', iconBg: 'bg-trading-bull-dim text-trading-bull' },
  bear: { bg: 'bg-trading-bear-bg', text: 'text-trading-bear', iconBg: 'bg-red-50 text-trading-bear' },
  info: { bg: 'bg-trading-info-dim', text: 'text-trading-info', iconBg: 'bg-sky-50 text-trading-info' },
  alert: { bg: 'bg-trading-alert-bg', text: 'text-trading-alert', iconBg: 'bg-amber-50 text-trading-alert' },
  ai: { bg: 'bg-trading-ai-bg', text: 'text-trading-ai', iconBg: 'bg-violet-50 text-trading-ai' },
};

export default function MetricCard({ title, value, change, icon: Icon, color }: MetricCardProps) {
  const colors = colorMap[color];
  const hasChange = change !== undefined && change !== null;
  const isPositive = hasChange && change >= 0;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
      className="glass-card p-4 overflow-hidden"
    >
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <p className="stat-label">{title}</p>
          <p className="text-2xl font-bold text-slate-900 mt-1.5 font-mono tabular-nums tracking-tight">{value}</p>
          {hasChange && (
            <div className={cn(
              'flex items-center gap-1 mt-1.5 px-1.5 py-0.5 rounded-md w-fit text-[10px] font-mono font-bold tabular-nums',
              isPositive ? 'text-trading-bull bg-trading-bull-dim' : 'text-trading-bear bg-red-50'
            )}>
              {isPositive ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
              {isPositive ? '+' : ''}{change.toFixed(2)}%
            </div>
          )}
        </div>
        <div className={cn('w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0', colors.iconBg)}>
          <Icon size={18} />
        </div>
      </div>
    </motion.div>
  );
}
