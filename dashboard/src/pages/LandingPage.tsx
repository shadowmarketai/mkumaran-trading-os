import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import {
  Activity, TrendingUp, Shield, Brain, BarChart3, Cpu,
  Zap, LineChart, ArrowRight, CheckCircle2,
  Rocket, Eye, Calculator,
} from 'lucide-react';
import { cn } from '../lib/utils';

const ease = [0.16, 1, 0.3, 1] as const;

function GradientCircle({ className }: { className?: string }) {
  return <div className={cn('absolute rounded-full blur-[100px] pointer-events-none opacity-60', className)} />;
}

const FEATURES = [
  { icon: Brain, title: 'AI-Powered Analysis', desc: 'Multi-model consensus scoring with Claude + GPT debate validation for every signal', color: 'text-trading-ai', bg: 'bg-violet-50' },
  { icon: BarChart3, title: '40+ Market Scanners', desc: 'Trend, Volume, Breakout, SMC, Wyckoff, Harmonic — across NSE, MCX, F&O, Forex', color: 'text-trading-info', bg: 'bg-blue-50' },
  { icon: Shield, title: 'Risk Management', desc: 'RRMS engine with position sizing, RRR validation, and pre-trade checklists', color: 'text-trading-bull', bg: 'bg-emerald-50' },
  { icon: TrendingUp, title: 'Live Signal Monitor', desc: 'Real-time SL/target tracking with auto-close and instant Telegram alerts', color: 'text-trading-alert', bg: 'bg-amber-50' },
  { icon: Cpu, title: 'Pattern Engines', desc: 'Smart Money Concepts, Wyckoff, VSA, Harmonic patterns — institutional-grade detection', color: 'text-trading-magenta', bg: 'bg-pink-50' },
  { icon: Calculator, title: 'Options Analytics', desc: 'Greeks calculator, IV rank, PCR, payoff charts, and option enrichment on F&O signals', color: 'text-trading-cyan', bg: 'bg-cyan-50' },
  { icon: LineChart, title: 'Backtesting Engine', desc: 'Validate strategies against historical data with equity curves, Sharpe, and drawdown', color: 'text-trading-accent', bg: 'bg-indigo-50' },
  { icon: Eye, title: 'Market Intelligence', desc: 'News impact scoring, sector rotation, FII/DII flows, momentum ranking', color: 'text-trading-gold', bg: 'bg-yellow-50' },
];

const PLANS = [
  {
    name: 'Starter',
    price: 'Free',
    period: '',
    features: ['3 signals/day', 'Basic dashboard', 'Market overview', 'Paper trading (₹1L)'],
    cta: 'Get Started',
    highlighted: false,
  },
  {
    name: 'Pro',
    price: '₹999',
    period: '/month',
    features: ['Unlimited signals', 'Full 40+ scanner heatmap', 'Live trading (Kite Connect)', 'Options analytics', 'Signal monitor + Telegram', '5 strategy backtests', 'Priority support'],
    cta: 'Start Free Trial',
    highlighted: true,
  },
  {
    name: 'Elite',
    price: '₹2,999',
    period: '/month',
    features: ['Everything in Pro', 'Auto-execute with GTT orders', 'Unlimited backtesting', 'API access', 'Custom scanner configs', 'Dedicated WhatsApp support', 'Early access to new features'],
    cta: 'Contact Sales',
    highlighted: false,
  },
];

export default function LandingPage() {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-[#FAFBFC] text-slate-800 overflow-hidden">
      {/* Subtle background gradient circles */}
      <GradientCircle className="w-[500px] h-[500px] bg-violet-200/50 top-[-150px] left-[-100px]" />
      <GradientCircle className="w-[400px] h-[400px] bg-blue-200/40 top-[30%] right-[-120px]" />
      <GradientCircle className="w-[350px] h-[350px] bg-purple-100/60 bottom-[10%] left-[20%]" />

      {/* Nav */}
      <nav className="relative z-10 flex items-center justify-between px-6 md:px-12 py-5 bg-white border-b border-trading-border">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl gradient-ai flex items-center justify-center shadow-brand">
            <Activity size={18} className="text-white" />
          </div>
          <div>
            <span className="text-base font-bold tracking-tight text-slate-900">Shadow Market</span>
            <span className="text-trading-ai text-[9px] tracking-[0.2em] uppercase block -mt-0.5">AI Trading Intelligence</span>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate('/login')}
            className="px-4 py-2 text-sm text-slate-500 hover:text-slate-800 transition-colors"
          >
            Sign In
          </button>
          <button
            onClick={() => navigate('/login')}
            className="px-5 py-2 rounded-xl text-sm font-semibold gradient-ai shadow-brand hover:opacity-90 transition-all text-white"
          >
            Get Started
          </button>
        </div>
      </nav>

      {/* Hero */}
      <section className="relative z-10 px-6 md:px-12 pt-20 pb-24 max-w-6xl mx-auto text-center">
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6, ease }}>
          <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-violet-50 border border-violet-200 mb-6">
            <Zap size={12} className="text-trading-ai" />
            <span className="text-[11px] text-trading-ai font-medium">AI-Powered Indian Market Analytics</span>
          </div>

          <h1 className="text-4xl md:text-6xl font-bold leading-tight tracking-tight mb-6 text-slate-900">
            Trade Smarter with
            <br />
            <span className="bg-gradient-to-r from-trading-ai via-violet-500 to-trading-bull bg-clip-text text-transparent">
              Institutional-Grade AI
            </span>
          </h1>

          <p className="text-lg text-slate-500 max-w-2xl mx-auto mb-10 leading-relaxed">
            40+ scanners, multi-AI validation, real-time monitoring — built for serious Indian market traders.
            NSE, F&O, MCX, Forex. All in one platform.
          </p>

          <div className="flex items-center justify-center gap-4">
            <button
              onClick={() => navigate('/login')}
              className="px-8 py-3.5 rounded-xl text-sm font-bold gradient-ai shadow-brand hover:opacity-90 transition-all flex items-center gap-2 text-white"
            >
              Start Free Trial <ArrowRight size={16} />
            </button>
            <button
              onClick={() => {
                document.getElementById('features')?.scrollIntoView({ behavior: 'smooth' });
              }}
              className="px-8 py-3.5 rounded-xl text-sm font-medium border border-trading-border hover:border-trading-ai/40 text-slate-500 hover:text-slate-800 bg-white transition-all"
            >
              See Features
            </button>
          </div>

          {/* Trust badges */}
          <div className="flex items-center justify-center gap-8 mt-12 text-[10px] text-slate-400 uppercase tracking-wider">
            <span>NSE &middot; BSE &middot; MCX &middot; CDS</span>
            <span className="w-px h-3 bg-trading-border" />
            <span>Kite Connect Integrated</span>
            <span className="w-px h-3 bg-trading-border" />
            <span>256-bit Encrypted</span>
          </div>
        </motion.div>
      </section>

      {/* Features Grid */}
      <section id="features" className="relative z-10 px-6 md:px-12 py-20 max-w-6xl mx-auto">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5, ease }}
          className="text-center mb-14"
        >
          <h2 className="text-3xl md:text-4xl font-bold mb-4 text-slate-900">Everything You Need to Trade</h2>
          <p className="text-slate-500 max-w-xl mx-auto">
            Decision support tools that help you identify, validate, and manage high-probability setups
          </p>
        </motion.div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {FEATURES.map((f, i) => (
            <motion.div
              key={f.title}
              initial={{ opacity: 0, y: 12 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.4, delay: i * 0.06, ease }}
              className="bg-white border border-trading-border rounded-2xl p-5 shadow-card group hover:border-trading-ai/30 hover:shadow-elevated transition-all duration-300"
            >
              <div className={cn('w-10 h-10 rounded-xl flex items-center justify-center mb-3', f.bg, f.color)}>
                <f.icon size={20} />
              </div>
              <h3 className="text-sm font-semibold text-slate-800 mb-1.5">{f.title}</h3>
              <p className="text-[11px] text-slate-500 leading-relaxed">{f.desc}</p>
            </motion.div>
          ))}
        </div>
      </section>

      {/* Pricing */}
      <section className="relative z-10 px-6 md:px-12 py-20 max-w-5xl mx-auto">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5, ease }}
          className="text-center mb-14"
        >
          <h2 className="text-3xl md:text-4xl font-bold mb-4 text-slate-900">Simple, Transparent Pricing</h2>
          <p className="text-slate-500">All plans include 7-day free trial. GST included. Cancel anytime.</p>
        </motion.div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
          {PLANS.map((plan, i) => (
            <motion.div
              key={plan.name}
              initial={{ opacity: 0, y: 12 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.4, delay: i * 0.08, ease }}
              className={cn(
                'bg-white border rounded-2xl p-6 relative overflow-hidden shadow-card',
                plan.highlighted
                  ? 'gradient-border-ai shadow-elevated'
                  : 'border-trading-border'
              )}
            >
              {plan.highlighted && (
                <div className="absolute top-0 right-0 px-3 py-1 text-[9px] font-bold uppercase tracking-wider gradient-ai rounded-bl-xl text-white">
                  Most Popular
                </div>
              )}
              <h3 className="text-lg font-bold mb-1 text-slate-900">{plan.name}</h3>
              <div className="flex items-baseline gap-1 mb-5">
                <span className="text-3xl font-bold font-mono tabular-nums text-slate-900">{plan.price}</span>
                {plan.period && <span className="text-sm text-slate-500">{plan.period}</span>}
              </div>
              <ul className="space-y-2.5 mb-6">
                {plan.features.map((f) => (
                  <li key={f} className="flex items-start gap-2 text-[12px] text-slate-600">
                    <CheckCircle2 size={14} className="text-trading-bull flex-shrink-0 mt-0.5" />
                    {f}
                  </li>
                ))}
              </ul>
              <button
                onClick={() => navigate('/login')}
                className={cn(
                  'w-full py-2.5 rounded-xl text-sm font-semibold transition-all',
                  plan.highlighted
                    ? 'gradient-ai shadow-brand hover:opacity-90 text-white'
                    : 'border border-trading-border hover:border-trading-ai/40 text-slate-600 hover:text-slate-900 bg-white'
                )}
              >
                {plan.cta}
              </button>
            </motion.div>
          ))}
        </div>
      </section>

      {/* CTA */}
      <section className="relative z-10 px-6 md:px-12 py-20 max-w-4xl mx-auto text-center">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5, ease }}
          className="bg-white border border-trading-border rounded-2xl p-10 shadow-elevated gradient-border-ai"
        >
          <Rocket size={32} className="text-trading-ai mx-auto mb-4" />
          <h2 className="text-2xl md:text-3xl font-bold mb-3 text-slate-900">Ready to Trade Smarter?</h2>
          <p className="text-slate-500 mb-6 max-w-lg mx-auto">
            Join traders who use AI-powered analytics to make better decisions. Start your free trial today.
          </p>
          <button
            onClick={() => navigate('/login')}
            className="px-10 py-3.5 rounded-xl text-sm font-bold gradient-ai shadow-brand hover:opacity-90 transition-all text-white"
          >
            Get Started Free
          </button>
        </motion.div>
      </section>

      {/* Footer */}
      <footer className="relative z-10 bg-slate-50 border-t border-trading-border px-6 md:px-12 py-8">
        <div className="max-w-6xl mx-auto flex flex-col md:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <Activity size={16} className="text-trading-ai" />
            <span className="text-sm font-semibold text-slate-800">Shadow Market AI</span>
          </div>
          <p className="text-[10px] text-slate-400 text-center max-w-2xl">
            This platform provides AI-powered market analytics and decision support tools for educational purposes only.
            Not SEBI-registered investment advice. Past performance is not indicative of future results.
            Consult a SEBI-registered financial advisor before making investment decisions.
          </p>
          <span className="text-[10px] text-slate-400">&copy; 2026 Shadow Market AI</span>
        </div>
      </footer>
    </div>
  );
}
