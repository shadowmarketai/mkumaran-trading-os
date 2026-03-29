import { useState, useCallback } from 'react';
import { optionsApi } from '../services/api';
import type { OptionChainData, GreeksResult } from '../types';

export function useOptionChain() {
  const [chain, setChain] = useState<OptionChainData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchChain = useCallback(async (spot: number, expiryDays: number, strikeStep = 50) => {
    setLoading(true);
    setError(null);
    try {
      const data = await optionsApi.getChain(spot, expiryDays, strikeStep);
      setChain(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch chain');
    } finally {
      setLoading(false);
    }
  }, []);

  return { chain, loading, error, fetchChain };
}

export function useGreeksCalculator() {
  const [greeks, setGreeks] = useState<GreeksResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const calculate = useCallback(async (params: {
    spot: number;
    strike: number;
    expiry_days: number;
    rate?: number;
    volatility?: number;
    option_type?: string;
  }) => {
    setLoading(true);
    setError(null);
    try {
      const data = await optionsApi.calculateGreeks(params);
      setGreeks(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to calculate Greeks');
    } finally {
      setLoading(false);
    }
  }, []);

  return { greeks, loading, error, calculate };
}
