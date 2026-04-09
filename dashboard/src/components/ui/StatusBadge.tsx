import { cn } from '../../lib/utils';
import type { MarketDirection, TradeStatus, SectorStrength } from '../../types';

type BadgeStatus = MarketDirection | TradeStatus | SectorStrength;
type BadgeSize = 'sm' | 'md' | 'lg';

interface StatusBadgeProps {
  status: BadgeStatus;
  size?: BadgeSize;
}

const statusColorMap: Record<string, string> = {
  BULL: 'bg-trading-bull/10 text-trading-bull border-trading-bull/20',
  WIN: 'bg-trading-bull/10 text-trading-bull border-trading-bull/20',
  STRONG: 'bg-trading-bull/10 text-trading-bull border-trading-bull/20',
  BEAR: 'bg-trading-bear/10 text-trading-bear border-trading-bear/20',
  LOSS: 'bg-trading-bear/10 text-trading-bear border-trading-bear/20',
  WEAK: 'bg-trading-bear/10 text-trading-bear border-trading-bear/20',
  SIDEWAYS: 'bg-trading-info/10 text-trading-info border-trading-info/20',
  NEUTRAL: 'bg-slate-500/10 text-slate-400 border-slate-500/20',
  MILD_BULL: 'bg-trading-bull/8 text-trading-bull-light border-trading-bull-light/15',
  MILD_BEAR: 'bg-trading-bear/8 text-trading-bear-light border-trading-bear-light/15',
  OPEN: 'bg-trading-alert/10 text-trading-alert border-trading-alert/20',
  EXPIRED: 'bg-slate-500/10 text-slate-500 border-slate-500/15',
};

const sizeMap: Record<BadgeSize, string> = {
  sm: 'px-1.5 py-0.5 text-[9px]',
  md: 'px-2.5 py-1 text-[10px]',
  lg: 'px-3 py-1.5 text-xs',
};

export default function StatusBadge({ status, size = 'md' }: StatusBadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-lg font-mono font-bold border whitespace-nowrap tracking-wider uppercase',
        statusColorMap[status] || 'bg-slate-500/10 text-slate-500 border-slate-500/15',
        sizeMap[size]
      )}
    >
      {status.replace('_', ' ')}
    </span>
  );
}
