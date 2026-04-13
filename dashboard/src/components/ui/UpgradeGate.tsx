import { useNavigate } from 'react-router-dom';
import { Lock, ArrowRight, Sparkles } from 'lucide-react';
import { useTier } from '../../context/TierContext';
import { cn } from '../../lib/utils';

interface UpgradeGateProps {
  feature: string;
  children: React.ReactNode;
  className?: string;
}

const TIER_LABELS: Record<string, string> = {
  free: 'Free',
  pro: 'Pro',
  elite: 'Elite',
};

const FEATURE_LABELS: Record<string, string> = {
  scanner_heatmap: 'Full Scanner Heatmap',
  signal_monitor: 'Signal Monitor',
  pattern_engines: 'Pattern Engines',
  wallstreet_ai: 'Wall Street AI',
  momentum: 'Momentum Ranking',
  payoff_calc: 'Payoff Calculator',
  live_trading: 'Live Trading',
  settings: 'Settings & BYOK',
  byok_keys: 'API Key Management',
};

export default function UpgradeGate({ feature, children, className }: UpgradeGateProps) {
  const { canAccess, tierInfo } = useTier();
  const navigate = useNavigate();

  if (canAccess(feature)) {
    return <>{children}</>;
  }

  const requiredTier = tierInfo?.features[feature]?.min_tier || 'pro';
  const featureLabel = FEATURE_LABELS[feature] || feature;

  return (
    <div className={cn('relative', className)}>
      {/* Blurred content preview */}
      <div className="blur-[6px] opacity-40 pointer-events-none select-none" aria-hidden>
        {children}
      </div>

      {/* Upgrade overlay */}
      <div className="absolute inset-0 flex items-center justify-center z-10">
        <div className="bg-white border border-slate-200 rounded-2xl shadow-elevated p-8 max-w-sm text-center">
          <div className="w-14 h-14 rounded-2xl bg-violet-50 flex items-center justify-center mx-auto mb-4">
            <Lock size={24} className="text-trading-ai" />
          </div>

          <h3 className="text-lg font-bold text-slate-900 mb-2">
            Upgrade to {TIER_LABELS[requiredTier] || 'Pro'}
          </h3>

          <p className="text-sm text-slate-500 mb-4">
            <span className="font-medium text-slate-700">{featureLabel}</span> is available on the{' '}
            <span className="font-semibold text-trading-ai">{TIER_LABELS[requiredTier] || 'Pro'}</span> plan.
          </p>

          <div className="space-y-2">
            <button
              onClick={() => navigate('/subscription')}
              className="w-full py-3 rounded-xl font-semibold text-sm gradient-ai shadow-brand hover:opacity-90 transition-all flex items-center justify-center gap-2 text-white"
            >
              <Sparkles size={14} />
              Upgrade Now
              <ArrowRight size={14} />
            </button>

            <p className="text-[10px] text-slate-400">
              {requiredTier === 'pro' ? 'Starting at ₹999/month' : 'Starting at ₹2,999/month'}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * Simple inline gate — hides content instead of blurring.
 * Use for individual buttons/sections within a page.
 */
export function TierBadge({ requiredTier }: { requiredTier: string }) {
  const { canAccess } = useTier();

  if (canAccess(requiredTier)) return null;

  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-violet-50 text-trading-ai text-[9px] font-bold uppercase tracking-wider">
      <Lock size={9} />
      {TIER_LABELS[requiredTier] || 'PRO'}
    </span>
  );
}
