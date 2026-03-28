import { useState, useEffect, useCallback } from 'react';
import type { MomentumData } from '../types';
import { momentumApi } from '../services/api';

interface UseMomentumOptions {
  autoRefreshMs?: number;
}

export function useMomentum(options: UseMomentumOptions = {}) {
  const { autoRefreshMs = 0 } = options;
  const [data, setData] = useState<MomentumData | null>(null);
  const [loading, setLoading] = useState(true);
  const [rebalancing, setRebalancing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchRankings = useCallback(async () => {
    try {
      setLoading(true);
      const result = await momentumApi.getRankings();
      setData(result);
      setError(null);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to fetch momentum data';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  const triggerRebalance = useCallback(async (topN = 10) => {
    try {
      setRebalancing(true);
      setError(null);
      await momentumApi.triggerRebalance(topN);
      // Refresh cached data after rebalance
      await fetchRankings();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Rebalance failed';
      setError(msg);
    } finally {
      setRebalancing(false);
    }
  }, [fetchRankings]);

  useEffect(() => {
    fetchRankings();
  }, [fetchRankings]);

  useEffect(() => {
    if (autoRefreshMs <= 0) return;
    const interval = setInterval(fetchRankings, autoRefreshMs);
    return () => clearInterval(interval);
  }, [fetchRankings, autoRefreshMs]);

  return { data, loading, rebalancing, error, refresh: fetchRankings, triggerRebalance };
}
