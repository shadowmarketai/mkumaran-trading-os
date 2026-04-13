import { useState, useEffect, useCallback, useRef } from 'react';
import { overviewApi } from '../services/api';

export interface MarketData {
  market_status: 'PRE' | 'LIVE' | 'POST' | 'CLOSED';
  nifty_price: number;
  nifty_change: number;
  nifty_change_pct: number;
  banknifty_price: number;
  banknifty_change: number;
  banknifty_change_pct: number;
  mwa_direction: string;
}

const DEFAULT_MARKET: MarketData = {
  market_status: 'CLOSED',
  nifty_price: 0,
  nifty_change: 0,
  nifty_change_pct: 0,
  banknifty_price: 0,
  banknifty_change: 0,
  banknifty_change_pct: 0,
  mwa_direction: 'N/A',
};

// Global cache — shared across all components using this hook
let _cachedMarket: MarketData = DEFAULT_MARKET;
let _lastFetch = 0;
const CACHE_TTL = 30000; // 30 seconds

export function useOverview(refreshInterval = 60000) {
  const [market, setMarket] = useState<MarketData>(_cachedMarket);
  const [loading, setLoading] = useState(_lastFetch === 0);
  const fetchingRef = useRef(false);

  const fetchData = useCallback(async () => {
    // Skip if another instance is already fetching
    if (fetchingRef.current) return;
    // Skip if cache is fresh
    if (Date.now() - _lastFetch < CACHE_TTL) {
      setMarket(_cachedMarket);
      setLoading(false);
      return;
    }

    fetchingRef.current = true;
    try {
      const data = await overviewApi.getOverview();
      const d = data as unknown as Record<string, unknown>;
      const newMarket: MarketData = {
        market_status: (d.market_status as MarketData['market_status']) || 'CLOSED',
        nifty_price: (d.nifty_price as number) || 0,
        nifty_change: (d.nifty_change as number) || 0,
        nifty_change_pct: (d.nifty_change_pct as number) || 0,
        banknifty_price: (d.banknifty_price as number) || 0,
        banknifty_change: (d.banknifty_change as number) || 0,
        banknifty_change_pct: (d.banknifty_change_pct as number) || 0,
        mwa_direction: (d.mwa_direction as string) || 'N/A',
      };
      _cachedMarket = newMarket;
      _lastFetch = Date.now();
      setMarket(newMarket);
    } catch {
      // Use cached data on error — don't block UI
      setMarket(_cachedMarket);
    } finally {
      setLoading(false);
      fetchingRef.current = false;
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, refreshInterval);
    return () => clearInterval(interval);
  }, [fetchData, refreshInterval]);

  return { market, loading };
}
