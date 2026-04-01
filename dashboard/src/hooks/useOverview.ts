import { useState, useEffect, useCallback } from 'react';
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

export function useOverview(refreshInterval = 60000) {
  const [market, setMarket] = useState<MarketData>(DEFAULT_MARKET);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const data = await overviewApi.getOverview();
      const d = data as unknown as Record<string, unknown>;
      setMarket({
        market_status: (d.market_status as MarketData['market_status']) || 'CLOSED',
        nifty_price: (d.nifty_price as number) || 0,
        nifty_change: (d.nifty_change as number) || 0,
        nifty_change_pct: (d.nifty_change_pct as number) || 0,
        banknifty_price: (d.banknifty_price as number) || 0,
        banknifty_change: (d.banknifty_change as number) || 0,
        banknifty_change_pct: (d.banknifty_change_pct as number) || 0,
        mwa_direction: (d.mwa_direction as string) || 'N/A',
      });
    } catch {
      // Keep previous data on error
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, refreshInterval);
    return () => clearInterval(interval);
  }, [fetchData, refreshInterval]);

  return { market, loading };
}
