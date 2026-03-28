import { createContext, useContext, useState, useMemo, type ReactNode } from 'react';
import type { MarketSegment, TimeframeCategory, SegmentFilter } from '../types';

interface MarketSegmentContextType {
  segment: MarketSegment;
  setSegment: (s: MarketSegment) => void;
  timeframeCategory: TimeframeCategory;
  setTimeframeCategory: (t: TimeframeCategory) => void;
  filter: SegmentFilter;
  timeframes: string[];
}

const SEGMENT_MAP: Record<MarketSegment, SegmentFilter> = {
  ALL: {},
  NSE_EQUITY: { exchange: 'NSE', asset_class: 'EQUITY' },
  FNO: { exchange: 'NFO', asset_class: 'FNO' },
  COMMODITY: { exchange: 'MCX', asset_class: 'COMMODITY' },
  FOREX: { exchange: 'CDS', asset_class: 'CURRENCY' },
};

const TIMEFRAME_MAP: Record<TimeframeCategory, string[]> = {
  ALL: [],
  INTRADAY: ['15m', '30m', '1H'],
  SWING: ['4H', '1D'],
  POSITIONAL: ['1W', '1M'],
};

const MarketSegmentContext = createContext<MarketSegmentContextType | null>(null);

export function MarketSegmentProvider({ children }: { children: ReactNode }) {
  const [segment, setSegment] = useState<MarketSegment>('ALL');
  const [timeframeCategory, setTimeframeCategory] = useState<TimeframeCategory>('ALL');

  const filter = useMemo<SegmentFilter>(() => {
    return { ...SEGMENT_MAP[segment] };
  }, [segment]);

  const timeframes = useMemo(() => TIMEFRAME_MAP[timeframeCategory], [timeframeCategory]);

  return (
    <MarketSegmentContext.Provider
      value={{ segment, setSegment, timeframeCategory, setTimeframeCategory, filter, timeframes }}
    >
      {children}
    </MarketSegmentContext.Provider>
  );
}

export function useMarketSegment(): MarketSegmentContextType {
  const ctx = useContext(MarketSegmentContext);
  if (!ctx) throw new Error('useMarketSegment must be used within MarketSegmentProvider');
  return ctx;
}
