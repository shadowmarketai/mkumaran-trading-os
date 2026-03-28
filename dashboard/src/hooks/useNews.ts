import { useState, useEffect, useCallback } from 'react';
import type { NewsItem } from '../types';
import { newsApi } from '../services/api';

interface UseNewsOptions {
  hours?: number;
  minImpact?: string;
  autoRefreshMs?: number;
}

export function useNews(options: UseNewsOptions = {}) {
  const { hours = 24, minImpact = 'LOW', autoRefreshMs = 0 } = options;
  const [items, setItems] = useState<NewsItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    try {
      setLoading(true);
      const data = await newsApi.getLatest(hours, minImpact);
      setItems(data);
      setError(null);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to fetch news';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [hours, minImpact]);

  useEffect(() => {
    fetch();
  }, [fetch]);

  // Optional auto-refresh
  useEffect(() => {
    if (autoRefreshMs <= 0) return;
    const interval = setInterval(fetch, autoRefreshMs);
    return () => clearInterval(interval);
  }, [fetch, autoRefreshMs]);

  return { items, loading, error, refresh: fetch };
}
