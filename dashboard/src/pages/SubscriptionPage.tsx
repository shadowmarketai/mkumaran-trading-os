import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { CheckCircle2, XCircle, Crown, Loader2 } from 'lucide-react';
import GlassCard from '../components/ui/GlassCard';
import { cn } from '../lib/utils';
import { subscriptionApi } from '../services/agentApi';
import type { SubscriptionPlan, UserSubscription } from '../types';

const FEATURES = {
  free: [
    { label: 'Real-time Signals', included: true },
    { label: 'Basic Scanner', included: true },
    { label: 'News Feed', included: true },
    { label: 'Signal History (30 days)', included: true },
    { label: 'Advanced Algorithms', included: false },
    { label: 'Priority Support', included: false },
    { label: 'Custom Alerts', included: false },
  ],
  pro: [
    { label: 'Real-time Signals', included: true },
    { label: 'Advanced Scanners (50+)', included: true },
    { label: 'News & Market Analysis', included: true },
    { label: 'Signal History (1 year)', included: true },
    { label: 'IV-aware Options', included: true },
    { label: 'Priority Support', included: true },
    { label: 'Custom Alerts', included: false },
  ],
  elite: [
    { label: 'Real-time Signals', included: true },
    { label: 'All 50+ Scanners', included: true },
    { label: 'AI-powered Analysis', included: true },
    { label: 'Unlimited Signal History', included: true },
    { label: 'IV-aware Options + Greeks', included: true },
    { label: 'VIP Support (24/7)', included: true },
    { label: 'Custom Alerts & Webhooks', included: true },
  ],
};

interface PlanCardProps {
  plan: SubscriptionPlan;
  features: Array<{ label: string; included: boolean }>;
  isCurrentPlan: boolean;
  isProPlan: boolean;
  billingCycle: 'monthly' | 'yearly';
  onSubscribe: (planSlug: string) => void;
  loading: boolean;
}

function PlanCard({ plan, features, isCurrentPlan, isProPlan, billingCycle, onSubscribe, loading }: PlanCardProps) {
  const price = billingCycle === 'monthly' ? plan.price_monthly_inr : plan.price_yearly_inr;
  const yearlyDiscount = billingCycle === 'yearly'
    ? Math.round((1 - (plan.price_yearly_inr / 12) / plan.price_monthly_inr) * 100)
    : 0;

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      className={cn(
        'relative rounded-2xl border transition-all',
        isProPlan
          ? 'border-transparent bg-gradient-to-b from-trading-ai/8 to-transparent p-0.5 shadow-[0_0_48px_rgba(124,77,255,0.12)]'
          : 'border-trading-border/30 bg-trading-bg-secondary/30'
      )}
    >
      {/* Pro card highlight */}
      {isProPlan && (
        <div className="absolute inset-0 rounded-2xl bg-gradient-to-b from-trading-ai/5 to-transparent pointer-events-none" />
      )}

      <div className={cn(
        'relative glass-card space-y-5',
        !isProPlan && 'bg-trading-bg-secondary/20'
      )}>
        {/* Badge */}
        {isProPlan && (
          <div className="flex justify-center">
            <span className="px-3 py-1 rounded-lg bg-trading-ai/15 text-trading-ai text-[9px] font-bold uppercase tracking-widest border border-trading-ai/30">
              Most Popular
            </span>
          </div>
        )}

        {/* Name & Price */}
        <div className="text-center space-y-2">
          <h3 className="text-lg font-bold text-white flex items-center justify-center gap-2">
            {plan.name === 'Elite' && <Crown size={16} className="text-trading-ai" />}
            {plan.name}
          </h3>
          <div className="flex items-baseline justify-center gap-1">
            <span className="text-4xl font-mono font-bold text-white tabular-nums">₹{(price / 12).toFixed(0)}</span>
            <span className="text-slate-500 text-sm">/mo</span>
          </div>
          <p className="text-[10px] text-slate-500">GST Included</p>
          {yearlyDiscount > 0 && (
            <p className="text-[9px] text-trading-bull font-semibold">Save ₹{Math.round(plan.price_monthly_inr * 12 - plan.price_yearly_inr)} ({yearlyDiscount}%) yearly</p>
          )}
        </div>

        {/* Features */}
        <div className="space-y-2.5">
          {features.map((feature, idx) => (
            <div key={idx} className="flex items-center gap-2.5">
              {feature.included ? (
                <CheckCircle2 size={14} className="text-trading-bull flex-shrink-0" />
              ) : (
                <XCircle size={14} className="text-slate-700 flex-shrink-0" />
              )}
              <span className={cn(
                'text-sm',
                feature.included ? 'text-slate-200' : 'text-slate-600'
              )}>
                {feature.label}
              </span>
            </div>
          ))}
        </div>

        {/* Button */}
        <button
          onClick={() => onSubscribe(plan.slug)}
          disabled={loading || isCurrentPlan}
          className={cn(
            'w-full py-2.5 px-4 rounded-xl font-semibold text-sm transition-all',
            isCurrentPlan
              ? 'bg-trading-bg-secondary text-slate-500 cursor-default border border-trading-border/20'
              : isProPlan
              ? 'bg-trading-ai text-trading-bg hover:bg-trading-ai-light border border-trading-ai/50'
              : 'bg-trading-ai/10 text-trading-ai hover:bg-trading-ai/15 border border-trading-ai/30',
            loading && 'opacity-50 cursor-not-allowed'
          )}
        >
          {loading ? (
            <Loader2 size={14} className="inline animate-spin mr-2" />
          ) : isCurrentPlan ? (
            'Current Plan'
          ) : plan.name === 'Elite' ? (
            'Upgrade to Elite'
          ) : (
            'Upgrade to Pro'
          )}
        </button>
      </div>
    </motion.div>
  );
}

export default function SubscriptionPage() {
  const [userSubscription, setUserSubscription] = useState<UserSubscription | null>(null);
  const [plans, setPlans] = useState<SubscriptionPlan[]>([]);
  const [billingCycle, setBillingCycle] = useState<'monthly' | 'yearly'>('monthly');
  const [loading, setLoading] = useState(true);
  const [subscribing, setSubscribing] = useState(false);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [subData, plansData] = await Promise.all([
          subscriptionApi.getMySubscription(),
          subscriptionApi.getPlans(),
        ]);
        setUserSubscription(subData);
        setPlans(plansData.plans || []);
      } catch (err) {
        console.error('Failed to load subscription data:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  const handleSubscribe = async (planSlug: string) => {
    setSubscribing(true);
    try {
      await subscriptionApi.subscribe(planSlug, billingCycle);
      const updated = await subscriptionApi.getMySubscription();
      setUserSubscription(updated);
    } catch (err) {
      console.error('Subscription failed:', err);
    } finally {
      setSubscribing(false);
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <div className="w-12 h-12 rounded-2xl bg-trading-ai/10 flex items-center justify-center">
          <Loader2 size={24} className="text-trading-ai animate-spin" />
        </div>
        <p className="text-slate-500 text-xs mt-4 font-mono">Loading subscription plans...</p>
      </div>
    );
  }

  const currentPlanName = userSubscription?.tier || 'free';
  const sortedPlans = plans.sort((a, b) => a.display_order - b.display_order);

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
      className="space-y-8"
    >
      {/* Status Card */}
      <GlassCard glowColor="ai">
        <div className="space-y-4">
          <div className="flex items-start justify-between">
            <div>
              <p className="stat-label">Current Subscription</p>
              <p className="text-2xl font-bold text-white mt-1 capitalize">{currentPlanName}</p>
            </div>
            <div className="px-3 py-1.5 rounded-lg bg-trading-bull/8 text-trading-bull text-[10px] font-bold uppercase tracking-wider border border-trading-bull/20">
              Active
            </div>
          </div>
          {userSubscription?.current_period_end && (
            <div className="pt-3 border-t border-trading-border/20">
              <p className="text-[11px] text-slate-500 mb-1">Expires</p>
              <p className="text-sm font-mono text-slate-300">
                {new Date(userSubscription.current_period_end).toLocaleDateString('en-IN', {
                  year: 'numeric', month: 'long', day: 'numeric'
                })}
              </p>
            </div>
          )}
        </div>
      </GlassCard>

      {/* Billing Toggle */}
      <div className="flex items-center justify-center gap-4">
        <button
          onClick={() => setBillingCycle('monthly')}
          className={cn(
            'px-4 py-2 rounded-xl font-semibold text-sm transition-all',
            billingCycle === 'monthly'
              ? 'bg-trading-ai text-trading-bg border border-trading-ai/50'
              : 'bg-trading-bg-secondary/30 text-slate-400 border border-trading-border/20 hover:bg-trading-bg-secondary/50'
          )}
        >
          Monthly
        </button>
        <button
          onClick={() => setBillingCycle('yearly')}
          className={cn(
            'px-4 py-2 rounded-xl font-semibold text-sm transition-all relative',
            billingCycle === 'yearly'
              ? 'bg-trading-ai text-trading-bg border border-trading-ai/50'
              : 'bg-trading-bg-secondary/30 text-slate-400 border border-trading-border/20 hover:bg-trading-bg-secondary/50'
          )}
        >
          Yearly
          {billingCycle === 'yearly' && (
            <span className="absolute -top-5 left-1/2 -translate-x-1/2 text-[9px] text-trading-bull font-bold">Save up to 17%</span>
          )}
        </button>
      </div>

      {/* Plan Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        {sortedPlans.map((plan) => (
          <PlanCard
            key={plan.id}
            plan={plan}
            features={FEATURES[plan.slug as keyof typeof FEATURES] || []}
            isCurrentPlan={currentPlanName === plan.slug}
            isProPlan={plan.slug === 'pro'}
            billingCycle={billingCycle}
            onSubscribe={handleSubscribe}
            loading={subscribing}
          />
        ))}
      </div>

      {/* SEBI Disclaimer */}
      <GlassCard className="bg-trading-bg-secondary/20">
        <div className="space-y-3">
          <p className="text-[10px] text-slate-500 leading-relaxed">
            <strong className="text-slate-300">Disclaimer:</strong> Shadow Market Trading OS is a technology platform for market analysis and signal generation. It is not investment advice.
            SEBI does not endorse any trading signals or strategies. Trading in Indian markets involves substantial risk of loss. Past performance is not indicative of future results.
            Please consult a qualified financial advisor before making investment decisions.
          </p>
          <p className="text-[9px] text-slate-600">
            Regulated by SEBI. NSE & BSE member firms. Risk warning applies to all trading activities.
          </p>
        </div>
      </GlassCard>
    </motion.div>
  );
}
