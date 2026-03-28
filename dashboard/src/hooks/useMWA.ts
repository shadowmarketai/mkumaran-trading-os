import { useState, useEffect, useCallback } from 'react';
import type { MWAScore } from '../types';
import { mwaApi } from '../services/api';

export function useMWA(refreshInterval = 300000) {
  const [mwa, setMwa] = useState<MWAScore | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    try {
      const data = await mwaApi.getLatest();
      // API returns {status: "no_data"} when no MWA scan has run
      if (data && 'direction' in data) {
        setMwa(data);
      } else {
        setMwa(null);
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch MWA');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetch();
    const interval = setInterval(fetch, refreshInterval);
    return () => clearInterval(interval);
  }, [fetch, refreshInterval]);

  return { mwa, loading, error, refetch: fetch };
}
