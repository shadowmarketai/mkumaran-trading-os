import { cn } from '../../lib/utils';
import type { MarketDirection, TradeStatus, SectorStrength } from '../../types';

type BadgeStatus = MarketDirection | TradeStatus | SectorStrength;
type BadgeSize = 'sm' | 'md' | 'lg';

interface StatusBadgeProps {
  status: BadgeStatus;
  size?: BadgeSize;
}

const statusColorMap: Record<string, string> = {
  BULL: 'bg-trading-bull/20 text-trading-bull border-trading-bull/30',
  WIN: 'bg-trading-bull/20 text-trading-bull border-trading-bull/30',
  STRONG: 'bg-trading-bull/20 text-trading-bull border-trading-bull/30',
  BEAR: 'bg-trading-bear/20 text-trading-bear border-trading-bear/30',
  LOSS: 'bg-trading-bear/20 text-trading-bear border-trading-bear/30',
  WEAK: 'bg-trading-bear/20 text-trading-bear border-trading-bear/30',
  SIDEWAYS: 'bg-trading-info/20 text-trading-info border-trading-info/30',
  NEUTRAL: 'bg-trading-info/20 text-trading-info border-trading-info/30',
  MILD_BULL: 'bg-lime-500/20 text-lime-400 border-lime-500/30',
  MILD_BEAR: 'bg-rose-500/20 text-rose-400 border-rose-500/30',
  OPEN: 'bg-trading-alert/20 text-trading-alert border-trading-alert/30',
  EXPIRED: 'bg-slate-500/20 text-slate-400 border-slate-500/30',
};

const sizeMap: Record<BadgeSize, string> = {
  sm: 'px-1.5 py-0.5 text-[10px]',
  md: 'px-2.5 py-1 text-xs',
  lg: 'px-3 py-1.5 text-sm',
};

export default function StatusBadge({ status, size = 'md' }: StatusBadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-md font-mono font-semibold border whitespace-nowrap',
        statusColorMap[status] || 'bg-slate-500/20 text-slate-400 border-slate-500/30',
        sizeMap[size]
      )}
    >
      {status.replace('_', ' ')}
    </span>
  );
}
