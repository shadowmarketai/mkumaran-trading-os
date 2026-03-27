import { useState, useEffect, useCallback } from 'react';
import type { ActiveTrade } from '../types';
import { tradeApi } from '../services/api';

export function useTrades(refreshInterval = 60000) {
  const [trades, setTrades] = useState<ActiveTrade[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    try {
      const data = await tradeApi.getActiveTrades();
      setTrades(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch trades');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetch();
    const interval = setInterval(fetch, refreshInterval);
    return () => clearInterval(interval);
  }, [fetch, refreshInterval]);

  return { trades, loading, error, refetch: fetch };
}
