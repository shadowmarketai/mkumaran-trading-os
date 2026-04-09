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
    <div className="flex flex-col gap-2 px-4 md:px-6 py-2.5 border-b border-trading-border/30 bg-trading-bg-secondary/40 backdrop-blur-sm">
      {/* Row 1: Market Segment Tabs */}
      <div className="flex items-center gap-1">
        {SEGMENTS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setSegment(key)}
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-200',
              segment === key
                ? 'bg-trading-ai/10 text-trading-ai-light border border-trading-ai/20 shadow-inner-glow'
                : 'text-slate-500 hover:text-slate-300 hover:bg-white/[0.03]'
            )}
          >
            <Icon size={12} />
            {label}
          </button>
        ))}
      </div>

      {/* Row 2: Timeframe Category Pills */}
      <div className="flex items-center gap-1">
        {TIMEFRAMES.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setTimeframeCategory(key)}
            className={cn(
              'px-2.5 py-1 rounded-md text-[10px] font-medium uppercase tracking-[0.1em] transition-all duration-200',
              timeframeCategory === key
                ? 'bg-trading-card text-white border border-trading-border/60'
                : 'text-slate-600 hover:text-slate-400 hover:bg-white/[0.02]'
            )}
          >
            {label}
          </button>
        ))}
        <span className="ml-2 text-[10px] text-slate-700 font-mono">
          {timeframeCategory === 'INTRADAY' && '15m / 30m / 1H'}
          {timeframeCategory === 'SWING' && '4H / 1D'}
          {timeframeCategory === 'POSITIONAL' && '1W / 1M'}
        </span>
      </div>
    </div>
  );
}
