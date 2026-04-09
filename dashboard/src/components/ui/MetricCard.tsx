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

const colorMap: Record<MetricColor, {
  bg: string;
  text: string;
  iconBg: string;
  border: string;
}> = {
  bull: {
    bg: 'from-trading-bull/6 via-transparent to-transparent',
    text: 'text-trading-bull',
    iconBg: 'bg-trading-bull/10 text-trading-bull border-trading-bull/15',
    border: 'border-trading-bull/8',
  },
  bear: {
    bg: 'from-trading-bear/6 via-transparent to-transparent',
    text: 'text-trading-bear',
    iconBg: 'bg-trading-bear/10 text-trading-bear border-trading-bear/15',
    border: 'border-trading-bear/8',
  },
  info: {
    bg: 'from-trading-info/6 via-transparent to-transparent',
    text: 'text-trading-info',
    iconBg: 'bg-trading-info/10 text-trading-info border-trading-info/15',
    border: 'border-trading-info/8',
  },
  alert: {
    bg: 'from-trading-alert/6 via-transparent to-transparent',
    text: 'text-trading-alert',
    iconBg: 'bg-trading-alert/10 text-trading-alert border-trading-alert/15',
    border: 'border-trading-alert/8',
  },
  ai: {
    bg: 'from-trading-ai/6 via-transparent to-transparent',
    text: 'text-trading-ai',
    iconBg: 'bg-trading-ai/10 text-trading-ai border-trading-ai/15',
    border: 'border-trading-ai/8',
  },
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
      className={cn(
        'glass-card p-4 bg-gradient-to-br overflow-hidden relative group',
        colors.bg
      )}
    >
      {/* Subtle corner accent */}
      <div className={cn(
        'absolute top-0 right-0 w-20 h-20 rounded-full blur-2xl opacity-20 -translate-y-1/2 translate-x-1/2',
        color === 'bull' && 'bg-trading-bull',
        color === 'bear' && 'bg-trading-bear',
        color === 'info' && 'bg-trading-info',
        color === 'alert' && 'bg-trading-alert',
        color === 'ai' && 'bg-trading-ai',
      )} />

      <div className="flex items-start justify-between relative">
        <div className="flex-1 min-w-0">
          <p className="stat-label">{title}</p>
          <p className="text-2xl font-bold text-white mt-1.5 font-mono tabular-nums tracking-tight">{value}</p>
          {hasChange && (
            <div className={cn(
              'flex items-center gap-1 mt-1.5 px-1.5 py-0.5 rounded-md w-fit',
              isPositive ? 'text-trading-bull bg-trading-bull/8' : 'text-trading-bear bg-trading-bear/8'
            )}>
              {isPositive ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
              <span className="text-[10px] font-mono font-bold tabular-nums">
                {isPositive ? '+' : ''}{change.toFixed(2)}%
              </span>
            </div>
          )}
        </div>
        <div className={cn(
          'w-10 h-10 rounded-xl flex items-center justify-center border flex-shrink-0',
          colors.iconBg
        )}>
          <Icon size={18} />
        </div>
      </div>
    </motion.div>
  );
}
