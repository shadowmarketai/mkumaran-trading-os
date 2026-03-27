import { useState, useEffect, useCallback } from 'react';
import type { WatchlistItem } from '../types';
import { watchlistApi } from '../services/api';

export function useWatchlist(tier = 0) {
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    try {
      const data = await watchlistApi.getAll(tier);
      setItems(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch watchlist');
    } finally {
      setLoading(false);
    }
  }, [tier]);

  useEffect(() => {
    fetch();
  }, [fetch]);

  const addItem = useCallback(async (data: { ticker: string; tier?: number; ltrp?: number; pivot_high?: number; timeframe?: string }) => {
    const newItem = await watchlistApi.add(data);
    setItems((prev) => [...prev, newItem]);
    return newItem;
  }, []);

  const removeItem = useCallback(async (id: number) => {
    await watchlistApi.remove(id);
    setItems((prev) => prev.filter((item) => item.id !== id));
  }, []);

  const toggleItem = useCallback(async (id: number) => {
    const updated = await watchlistApi.toggle(id);
    setItems((prev) => prev.map((item) => (item.id === id ? updated : item)));
  }, []);

  return { items, loading, error, refetch: fetch, addItem, removeItem, toggleItem };
}
