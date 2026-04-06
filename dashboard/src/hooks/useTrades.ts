import { useState, useEffect, useCallback, useRef } from 'react';
import type { ActiveTrade } from '../types';
import { tradeApi } from '../services/api';
import { useMarketSegment } from '../context/MarketSegmentContext';

export function useTrades(refreshInterval = 60000) {
  const [trades, setTrades] = useState<ActiveTrade[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { filter, timeframes } = useMarketSegment();
  const retryCount = useRef(0);

  const fetch = useCallback(async () => {
    try {
      const data = await tradeApi.getActiveTrades(filter);
      const filtered = timeframes.length > 0
        ? data.filter((t) => timeframes.includes(t.timeframe))
        : data;
      setTrades(filtered);
      setError(null);
      retryCount.current = 0;
    } catch (err) {
      // On timeout, retry once silently before showing error
      if (retryCount.current < 1) {
        retryCount.current += 1;
        setTimeout(() => fetch(), 3000);
        return;
      }
      setError(err instanceof Error ? err.message : 'Failed to fetch trades');
    } finally {
      setLoading(false);
    }
  }, [filter, timeframes]);

  useEffect(() => {
    fetch();
    const interval = setInterval(fetch, refreshInterval);
    return () => clearInterval(interval);
  }, [fetch, refreshInterval]);

  return { trades, loading, error, refetch: fetch };
}
