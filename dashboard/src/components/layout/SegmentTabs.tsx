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
    <div className="flex flex-col gap-2 px-6 py-2 border-b border-trading-border bg-slate-900/50">
      {/* Row 1: Market Segment Tabs */}
      <div className="flex items-center gap-1">
        {SEGMENTS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setSegment(key)}
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all',
              segment === key
                ? 'bg-trading-ai/20 text-trading-ai-light border border-trading-ai/30'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
            )}
          >
            <Icon size={13} />
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
              'px-2.5 py-1 rounded-md text-[10px] font-medium uppercase tracking-wider transition-all',
              timeframeCategory === key
                ? 'bg-slate-700 text-white'
                : 'text-slate-500 hover:text-slate-300 hover:bg-slate-800/50'
            )}
          >
            {label}
          </button>
        ))}
        <span className="ml-2 text-[10px] text-slate-600 font-mono">
          {timeframeCategory === 'INTRADAY' && '15m / 30m / 1H'}
          {timeframeCategory === 'SWING' && '4H / 1D'}
          {timeframeCategory === 'POSITIONAL' && '1W / 1M'}
        </span>
      </div>
    </div>
  );
}
