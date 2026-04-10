import { cn } from '../../lib/utils';
import type { MarketDirection, TradeStatus, SectorStrength } from '../../types';

type BadgeStatus = MarketDirection | TradeStatus | SectorStrength;
type BadgeSize = 'sm' | 'md' | 'lg';

interface StatusBadgeProps {
  status: BadgeStatus;
  size?: BadgeSize;
}

const statusColorMap: Record<string, string> = {
  BULL: 'bg-trading-bull-dim text-trading-bull',
  WIN: 'bg-trading-bull-dim text-trading-bull',
  STRONG: 'bg-trading-bull-dim text-trading-bull',
  BEAR: 'bg-red-50 text-trading-bear',
  LOSS: 'bg-red-50 text-trading-bear',
  WEAK: 'bg-red-50 text-trading-bear',
  SIDEWAYS: 'bg-sky-50 text-trading-info',
  NEUTRAL: 'bg-slate-100 text-slate-500',
  MILD_BULL: 'bg-emerald-50 text-emerald-600',
  MILD_BEAR: 'bg-rose-50 text-rose-500',
  OPEN: 'bg-amber-50 text-amber-600',
  EXPIRED: 'bg-slate-100 text-slate-400',
};

const sizeMap: Record<BadgeSize, string> = {
  sm: 'px-1.5 py-0.5 text-[9px]',
  md: 'px-2.5 py-1 text-[10px]',
  lg: 'px-3 py-1.5 text-xs',
};

export default function StatusBadge({ status, size = 'md' }: StatusBadgeProps) {
  return (
    <span className={cn(
      'inline-flex items-center rounded-lg font-mono font-bold whitespace-nowrap tracking-wider uppercase',
      statusColorMap[status] || 'bg-slate-100 text-slate-500',
      sizeMap[size]
    )}>
      {status.replace('_', ' ')}
    </span>
  );
}
