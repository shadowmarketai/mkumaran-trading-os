import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { Activity, Lock, Mail, Loader2, ArrowLeft } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

export default function LoginPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(email, password);
      navigate('/overview', { replace: true });
    } catch (err: unknown) {
      const msg = err && typeof err === 'object' && 'response' in err
        ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        : undefined;
      setError(msg || 'Login failed. Check your credentials.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex bg-[#FAFBFC] relative overflow-hidden">
      {/* Subtle background gradient circles */}
      <div className="absolute inset-0 pointer-events-none">
        <div className="absolute top-[-10%] left-[-5%] w-[500px] h-[500px] bg-violet-200/40 rounded-full blur-[120px]" />
        <div className="absolute bottom-[-10%] right-[-5%] w-[400px] h-[400px] bg-blue-200/30 rounded-full blur-[110px]" />
        <div className="absolute top-[40%] right-[30%] w-[300px] h-[300px] bg-purple-100/50 rounded-full blur-[100px]" />
      </div>

      {/* Left — Branding Panel */}
      <div className="hidden lg:flex lg:w-1/2 relative z-10 flex-col justify-between p-12 bg-trading-ai-bg">
        <div>
          <Link to="/" className="flex items-center gap-3 mb-20">
            <div className="w-10 h-10 rounded-xl gradient-ai flex items-center justify-center shadow-brand">
              <Activity size={20} className="text-white" />
            </div>
            <div>
              <span className="text-lg font-bold tracking-tight text-slate-900">Shadow Market</span>
              <span className="text-trading-ai text-[9px] tracking-[0.25em] uppercase block -mt-0.5">AI Trading Intelligence</span>
            </div>
          </Link>
          <h2 className="text-4xl font-bold leading-tight mb-6 text-slate-900">
            Trade with<br />
            <span className="bg-gradient-to-r from-trading-ai via-violet-500 to-trading-bull bg-clip-text text-transparent">Confidence</span>
          </h2>
          <p className="text-slate-500 text-sm leading-relaxed max-w-md">
            AI-powered market analytics and decision support for Indian markets. 40+ scanners, real-time monitoring, and institutional-grade pattern detection.
          </p>
        </div>
        <div className="space-y-4">
          {[
            { label: 'Multi-Scanner MWA Engine', desc: 'NSE, F&O, MCX, Forex — all segments' },
            { label: 'AI Confidence Scoring', desc: 'Claude + GPT debate validation' },
            { label: 'Risk-First Architecture', desc: 'RRMS, GTT orders, position sizing' },
          ].map((f) => (
            <div key={f.label} className="flex items-start gap-3">
              <div className="w-1.5 h-1.5 rounded-full bg-trading-ai mt-2 flex-shrink-0" />
              <div>
                <p className="text-sm font-medium text-slate-800">{f.label}</p>
                <p className="text-[11px] text-slate-500">{f.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Right — Login Form */}
      <div className="w-full lg:w-1/2 flex items-center justify-center p-6 relative z-10 bg-white">
        <div className="w-full max-w-sm">
          <div className="lg:hidden text-center mb-10">
            <Link to="/" className="inline-flex items-center gap-2 mb-6">
              <ArrowLeft size={14} className="text-slate-500" />
              <span className="text-xs text-slate-500">Back</span>
            </Link>
            <div>
              <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl gradient-ai shadow-brand mb-4">
                <Activity size={22} className="text-white" />
              </div>
              <h1 className="text-xl font-bold text-slate-900">Shadow Market AI</h1>
              <p className="text-trading-ai text-[9px] tracking-[0.3em] uppercase mt-0.5">Trading Intelligence</p>
            </div>
          </div>

          <div className="bg-white border border-trading-border rounded-2xl p-8 shadow-elevated">
            <h2 className="text-lg font-bold text-slate-900 mb-1">Welcome back</h2>
            <p className="text-xs text-slate-500 mb-6">Sign in to your trading dashboard</p>

            {error && (
              <div className="mb-5 p-3 rounded-xl bg-red-50 border border-red-200 text-red-600 text-xs">{error}</div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-[10px] font-semibold text-slate-500 mb-2 uppercase tracking-[0.12em]">Email</label>
                <div className="relative">
                  <Mail size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
                  <input type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                    className="w-full pl-10 pr-4 py-3 rounded-xl bg-trading-bg-secondary border border-trading-border text-slate-800 text-sm placeholder-slate-400 focus:outline-none focus:border-trading-ai/50 focus:ring-1 focus:ring-trading-ai/25 transition-all"
                    placeholder="you@example.com" required autoFocus />
                </div>
              </div>
              <div>
                <label className="block text-[10px] font-semibold text-slate-500 mb-2 uppercase tracking-[0.12em]">Password</label>
                <div className="relative">
                  <Lock size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
                  <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                    className="w-full pl-10 pr-4 py-3 rounded-xl bg-trading-bg-secondary border border-trading-border text-slate-800 text-sm placeholder-slate-400 focus:outline-none focus:border-trading-ai/50 focus:ring-1 focus:ring-trading-ai/25 transition-all"
                    placeholder="Enter password" required />
                </div>
              </div>
              <button type="submit" disabled={loading}
                className="w-full py-3 rounded-xl font-semibold text-sm gradient-ai shadow-brand hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed transition-all mt-2 flex items-center justify-center gap-2 text-white">
                {loading ? (<><Loader2 size={14} className="animate-spin" />Signing in...</>) : 'Sign In'}
              </button>
            </form>
            <p className="text-center text-[10px] text-slate-500 mt-6">
              Don't have an account? <Link to="/" className="text-trading-ai hover:text-violet-700 transition-colors">View Plans</Link>
            </p>
          </div>
          <p className="text-center text-[9px] text-slate-400 mt-6 max-w-xs mx-auto leading-relaxed">
            AI-powered analytics for educational purposes. Not SEBI-registered investment advice.
          </p>
        </div>
      </div>
    </div>
  );
}
