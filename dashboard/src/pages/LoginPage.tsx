import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Activity, Lock, Mail, Loader2 } from 'lucide-react';
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
      const msg =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : undefined;
      setError(msg || 'Login failed. Check your credentials.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-trading-bg relative overflow-hidden">
      {/* Background effects */}
      <div className="absolute inset-0">
        <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-trading-ai/5 rounded-full blur-[128px]" />
        <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-trading-bull/3 rounded-full blur-[128px]" />
        <div className="absolute top-0 left-0 w-full h-full bg-[radial-gradient(ellipse_at_center,rgba(124,77,255,0.04)_0%,transparent_70%)]" />
      </div>

      <div className="w-full max-w-sm relative z-10">
        {/* Logo */}
        <div className="text-center mb-10">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl gradient-ai shadow-glow-ai mb-5">
            <Activity size={24} className="text-white" />
          </div>
          <h1 className="text-2xl font-bold text-white tracking-tight">
            MKUMARAN
          </h1>
          <p className="text-trading-ai-light text-[10px] tracking-[0.3em] uppercase mt-1">Trading OS</p>
        </div>

        {/* Login Card */}
        <div className="glass-card p-8">
          <h2 className="text-sm font-semibold text-white mb-6 tracking-wide">Sign In</h2>

          {error && (
            <div className="mb-5 p-3 rounded-xl bg-trading-bear/8 border border-trading-bear/15 text-trading-bear text-xs">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-[10px] font-medium text-slate-500 mb-2 uppercase tracking-wider">Email</label>
              <div className="relative">
                <Mail size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-600" />
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full pl-10 pr-4 py-3 rounded-xl bg-trading-bg-secondary border border-trading-border/60 text-white text-sm placeholder-slate-600 focus:outline-none focus:border-trading-ai/40 focus:ring-1 focus:ring-trading-ai/20 transition-all"
                  placeholder="admin@shadowmarket.ai"
                  required
                  autoFocus
                />
              </div>
            </div>

            <div>
              <label className="block text-[10px] font-medium text-slate-500 mb-2 uppercase tracking-wider">Password</label>
              <div className="relative">
                <Lock size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-600" />
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full pl-10 pr-4 py-3 rounded-xl bg-trading-bg-secondary border border-trading-border/60 text-white text-sm placeholder-slate-600 focus:outline-none focus:border-trading-ai/40 focus:ring-1 focus:ring-trading-ai/20 transition-all"
                  placeholder="Enter password"
                  required
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 rounded-xl bg-gradient-to-r from-trading-ai to-trading-ai-light text-white font-semibold text-sm hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed transition-all shadow-glow-ai mt-2 flex items-center justify-center gap-2"
            >
              {loading ? (
                <>
                  <Loader2 size={14} className="animate-spin" />
                  Signing in...
                </>
              ) : (
                'Sign In'
              )}
            </button>
          </form>
        </div>

        <p className="text-center text-[10px] text-slate-700 mt-8 tracking-wider">
          Shadow Market Intelligence
        </p>
      </div>
    </div>
  );
}
