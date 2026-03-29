import { useState, useCallback } from 'react';
import { optionsApi } from '../services/api';
import type { PayoffData, PayoffLeg } from '../types';

export function usePayoff() {
  const [payoff, setPayoff] = useState<PayoffData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const calculate = useCallback(async (legs: PayoffLeg[], spotRange?: [number, number]) => {
    setLoading(true);
    setError(null);
    try {
      const data = await optionsApi.calculatePayoff(legs, spotRange);
      setPayoff(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to calculate payoff');
    } finally {
      setLoading(false);
    }
  }, []);

  return { payoff, loading, error, calculate };
}
