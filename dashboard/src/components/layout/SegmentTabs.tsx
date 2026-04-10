import { BarChart3, TrendingUp, Gem, Globe, Layers } from 'lucide-react';
import { cn } from '../../lib/utils';
import { useMarketSegment } from '../../context/MarketSegmentContext';
import type { MarketSegment, TimeframeCategory } from '../../types';

const SEGMENTS: { key: MarketSegment; label: string; icon: typeof Layers }[] = [
  { key: 'ALL', label: 'All', icon: Layers },
  { key: 'NSE_EQUITY', label: 'NSE Equity', icon: BarChart3 },
  { key: 'FNO', label: 'F&O', icon: TrendingUp },
  { key: 'COMMODITY', label: 'Commodity', icon: Gem },
  { key: 'FOREX', label: 'Forex', icon: Globe },
];

const TIMEFRAMES: { key: TimeframeCategory; label: string }[] = [
  { key: 'ALL', label: 'All TF' },
  { key: 'INTRADAY', label: 'Intraday' },
  { key: 'SWING', label: 'Swing' },
  { key: 'POSITIONAL', label: 'Positional' },
];

export default function SegmentTabs() {
  const { segment, setSegment, timeframeCategory, setTimeframeCategory } = useMarketSegment();

  return (
    <div className="flex flex-col gap-2 px-4 md:px-6 py-2.5 border-b border-trading-border bg-white/60 backdrop-blur-sm">
      <div className="flex items-center gap-1">
        {SEGMENTS.map(({ key, label, icon: Icon }) => (
          <button key={key} onClick={() => setSegment(key)}
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-200',
              segment === key
                ? 'bg-trading-ai-bg text-trading-ai font-semibold'
                : 'text-slate-400 hover:text-slate-600 hover:bg-slate-50'
            )}>
            <Icon size={12} />{label}
          </button>
        ))}
      </div>
      <div className="flex items-center gap-1">
        {TIMEFRAMES.map(({ key, label }) => (
          <button key={key} onClick={() => setTimeframeCategory(key)}
            className={cn(
              'px-2.5 py-1 rounded-md text-[10px] font-medium uppercase tracking-[0.1em] transition-all duration-200',
              timeframeCategory === key
                ? 'bg-slate-100 text-slate-700 font-semibold'
                : 'text-slate-400 hover:text-slate-600 hover:bg-slate-50'
            )}>
            {label}
          </button>
        ))}
        <span className="ml-2 text-[10px] text-slate-400 font-mono">
          {timeframeCategory === 'INTRADAY' && '15m / 30m / 1H'}
          {timeframeCategory === 'SWING' && '4H / 1D'}
          {timeframeCategory === 'POSITIONAL' && '1W / 1M'}
        </span>
      </div>
    </div>
  );
}
