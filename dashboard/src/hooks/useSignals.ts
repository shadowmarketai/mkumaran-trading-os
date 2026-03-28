import { useState, useEffect, useCallback } from 'react';
import type { Signal } from '../types';
import { signalApi } from '../services/api';
import { useMarketSegment } from '../context/MarketSegmentContext';

export function useSignals(limit = 50, refreshInterval = 60000) {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { filter, timeframes } = useMarketSegment();

  const fetch = useCallback(async () => {
    try {
      const data = await signalApi.getSignals(limit, filter);
      // Client-side timeframe category filter (multi-value)
      const filtered = timeframes.length > 0
        ? data.filter((s) => timeframes.includes(s.timeframe))
        : data;
      setSignals(filtered);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch signals');
    } finally {
      setLoading(false);
    }
  }, [limit, filter, timeframes]);

  useEffect(() => {
    fetch();
    const interval = setInterval(fetch, refreshInterval);
    return () => clearInterval(interval);
  }, [fetch, refreshInterval]);

  return { signals, loading, error, refetch: fetch };
}
