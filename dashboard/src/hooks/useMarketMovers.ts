import { useState, useEffect, useCallback } from 'react';
import { marketMoversApi } from '../services/api';
import type { MarketMoversData, MarketMoverCategory } from '../types';

export function useMarketMovers(refreshInterval = 300000) {
  const [data, setData] = useState<MarketMoversData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [category, setCategory] = useState<MarketMoverCategory>('gainers');
  const [exchange, setExchange] = useState('ALL');

  const fetch = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const result = await marketMoversApi.get(category, exchange);
      setData(result);
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Failed to load';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [category, exchange]);

  useEffect(() => {
    fetch();
    const timer = setInterval(fetch, refreshInterval);
    return () => clearInterval(timer);
  }, [fetch, refreshInterval]);

  return { data, loading, error, category, setCategory, exchange, setExchange, refresh: fetch };
}
