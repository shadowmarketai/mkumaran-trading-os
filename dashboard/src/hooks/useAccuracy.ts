import { useState, useEffect, useCallback } from 'react';
import type { AccuracyMetrics } from '../types';
import { accuracyApi } from '../services/api';

export function useAccuracy() {
  const [metrics, setMetrics] = useState<AccuracyMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    try {
      const data = await accuracyApi.getMetrics();
      setMetrics(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch accuracy');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetch();
  }, [fetch]);

  return { metrics, loading, error, refetch: fetch };
}
