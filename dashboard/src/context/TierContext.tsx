import { createContext, useContext, useState, useEffect, type ReactNode } from 'react';
import axios from 'axios';

interface FeatureAccess {
  accessible: boolean;
  daily_limit: number;
  min_tier: string;
}

interface TierInfo {
  tier: string;
  paper_capital: number;
  watchlist_max: number;
  features: Record<string, FeatureAccess>;
}

interface TierContextType {
  tier: string;
  tierInfo: TierInfo | null;
  canAccess: (feature: string) => boolean;
  loading: boolean;
}

const TierContext = createContext<TierContextType | null>(null);

const api = axios.create({ baseURL: '/api', timeout: 10000 });

export function TierProvider({ children }: { children: ReactNode }) {
  const [tierInfo, setTierInfo] = useState<TierInfo | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem('mkumaran_auth_token');
    if (token) {
      api.defaults.headers.common['Authorization'] = `Bearer ${token}`;
    }
    api.get('/user/tier')
      .then((r) => setTierInfo(r.data))
      .catch(() => setTierInfo({ tier: 'free', paper_capital: 100000, watchlist_max: 5, features: {} }))
      .finally(() => setLoading(false));
  }, []);

  const canAccess = (feature: string): boolean => {
    if (!tierInfo) return true; // Loading — allow
    if (tierInfo.tier === 'admin') return true;
    const feat = tierInfo.features[feature];
    if (!feat) return true; // Unknown feature — allow
    return feat.accessible;
  };

  return (
    <TierContext.Provider value={{ tier: tierInfo?.tier || 'free', tierInfo, canAccess, loading }}>
      {children}
    </TierContext.Provider>
  );
}

export function useTier(): TierContextType {
  const ctx = useContext(TierContext);
  if (!ctx) throw new Error('useTier must be used within TierProvider');
  return ctx;
}
