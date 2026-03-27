import { useState, useCallback } from 'react';
import type { BacktestResult } from '../types';
import { backtestApi } from '../services/api';

export function useBacktest() {
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async (ticker: string, strategy: string, days: number) => {
    setLoading(true);
    setError(null);
    try {
      const data = await backtestApi.run(ticker, strategy, days);
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Backtest failed');
    } finally {
      setLoading(false);
    }
  }, []);

  return { result, loading, error, run };
}
