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
  bull: {
    bg: 'from-trading-bull/10 to-transparent',
    text: 'text-trading-bull',
    iconBg: 'bg-trading-bull/15 text-trading-bull',
  },
  bear: {
    bg: 'from-trading-bear/10 to-transparent',
    text: 'text-trading-bear',
    iconBg: 'bg-trading-bear/15 text-trading-bear',
  },
  info: {
    bg: 'from-trading-info/10 to-transparent',
    text: 'text-trading-info',
    iconBg: 'bg-trading-info/15 text-trading-info',
  },
  alert: {
    bg: 'from-trading-alert/10 to-transparent',
    text: 'text-trading-alert',
    iconBg: 'bg-trading-alert/15 text-trading-alert',
  },
  ai: {
    bg: 'from-trading-ai/10 to-transparent',
    text: 'text-trading-ai',
    iconBg: 'bg-trading-ai/15 text-trading-ai',
  },
};

export default function MetricCard({ title, value, change, icon: Icon, color }: MetricCardProps) {
  const colors = colorMap[color];
  const hasChange = change !== undefined && change !== null;
  const isPositive = hasChange && change >= 0;

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className={cn(
        'glass-card p-4 bg-gradient-to-br',
        colors.bg
      )}
    >
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <p className="text-xs text-slate-400 font-medium uppercase tracking-wider">{title}</p>
          <p className="text-2xl font-bold text-white mt-1 font-mono">{value}</p>
          {hasChange && (
            <div className={cn('flex items-center gap-1 mt-1', isPositive ? 'text-trading-bull' : 'text-trading-bear')}>
              {isPositive ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
              <span className="text-xs font-mono font-medium">
                {isPositive ? '+' : ''}{change.toFixed(2)}%
              </span>
            </div>
          )}
        </div>
        <div className={cn('w-10 h-10 rounded-lg flex items-center justify-center', colors.iconBg)}>
          <Icon size={20} />
        </div>
      </div>
    </motion.div>
  );
}
