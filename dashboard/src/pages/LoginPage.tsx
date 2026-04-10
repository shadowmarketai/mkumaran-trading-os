import { useState, useEffect } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { Activity, Mail, Loader2, ArrowLeft, Phone, KeyRound } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { cn } from '../lib/utils';
import axios from 'axios';

type AuthMode = 'password' | 'email_otp' | 'mobile_otp';

interface AuthConfig {
  google_enabled: boolean;
  google_client_id: string;
  email_otp_enabled: boolean;
  mobile_otp_enabled: boolean;
  password_enabled: boolean;
}

export default function LoginPage() {
  const [mode, setMode] = useState<AuthMode>('password');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [phone, setPhone] = useState('');
  const [otp, setOtp] = useState('');
  const [otpSent, setOtpSent] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const { login } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    axios.get('/api/auth/config').then((r) => setConfig(r.data)).catch(() => {});
  }, []);

  // Load Google Sign-In script
  useEffect(() => {
    if (!config?.google_enabled || !config.google_client_id) return;
    const script = document.createElement('script');
    script.src = 'https://accounts.google.com/gsi/client';
    script.async = true;
    script.onload = () => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const g = (window as any).google;
      g?.accounts?.id?.initialize({
        client_id: config.google_client_id,
        callback: handleGoogleResponse,
      });
      g?.accounts?.id?.renderButton(
        document.getElementById('google-signin-btn'),
        { theme: 'outline', size: 'large', width: '100%', text: 'signin_with', shape: 'pill' }
      );
    };
    document.body.appendChild(script);
    return () => { document.body.removeChild(script); };
  }, [config]);

  const handleGoogleResponse = async (response: { credential: string }) => {
    setLoading(true);
    setError('');
    try {
      const res = await axios.post('/api/auth/google', { credential: response.credential });
      localStorage.setItem('mkumaran_auth_token', res.data.access_token);
      localStorage.setItem('mkumaran_auth_email', res.data.email);
      navigate('/overview', { replace: true });
      window.location.reload();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg || 'Google sign-in failed');
    } finally {
      setLoading(false);
    }
  };

  const handlePasswordLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(email, password);
      navigate('/overview', { replace: true });
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg || 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  const handleSendOtp = async () => {
    setError('');
    setLoading(true);
    try {
      if (mode === 'email_otp') {
        await axios.post('/api/auth/email/send-otp', { email });
      } else {
        await axios.post('/api/auth/mobile/send-otp', { phone });
      }
      setOtpSent(true);
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg || 'Failed to send OTP');
    } finally {
      setLoading(false);
    }
  };

  const handleVerifyOtp = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const endpoint = mode === 'email_otp' ? '/api/auth/email/verify-otp' : '/api/auth/mobile/verify-otp';
      const payload = mode === 'email_otp' ? { email, otp } : { phone, otp };
      const res = await axios.post(endpoint, payload);
      localStorage.setItem('mkumaran_auth_token', res.data.access_token);
      localStorage.setItem('mkumaran_auth_email', res.data.email);
      navigate('/overview', { replace: true });
      window.location.reload();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg || 'Verification failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex bg-[#FAFBFC] relative overflow-hidden">
      <div className="absolute inset-0 pointer-events-none">
        <div className="absolute top-[-10%] left-[-5%] w-[500px] h-[500px] bg-violet-200/40 rounded-full blur-[120px]" />
        <div className="absolute bottom-[-10%] right-[-5%] w-[400px] h-[400px] bg-blue-200/30 rounded-full blur-[110px]" />
      </div>

      {/* Left Panel */}
      <div className="hidden lg:flex lg:w-1/2 relative z-10 flex-col justify-between p-12 bg-violet-50/50">
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
            AI-powered market analytics for Indian markets. 40+ scanners, real-time monitoring, institutional-grade patterns.
          </p>
        </div>
        <div className="space-y-4">
          {['Multi-Scanner MWA Engine', 'AI Confidence Scoring', 'Risk-First Architecture'].map((f) => (
            <div key={f} className="flex items-center gap-3">
              <div className="w-1.5 h-1.5 rounded-full bg-trading-ai flex-shrink-0" />
              <p className="text-sm font-medium text-slate-700">{f}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Right Panel — Login */}
      <div className="w-full lg:w-1/2 flex items-center justify-center p-6 relative z-10 bg-white">
        <div className="w-full max-w-sm">
          {/* Mobile header */}
          <div className="lg:hidden text-center mb-8">
            <Link to="/" className="inline-flex items-center gap-2 mb-4">
              <ArrowLeft size={14} className="text-slate-400" /><span className="text-xs text-slate-400">Back</span>
            </Link>
            <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl gradient-ai shadow-brand mb-3">
              <Activity size={22} className="text-white" />
            </div>
            <h1 className="text-xl font-bold text-slate-900">Shadow Market AI</h1>
          </div>

          <div className="bg-white border border-slate-200 rounded-2xl p-8 shadow-elevated">
            <h2 className="text-lg font-bold text-slate-900 mb-1">Welcome</h2>
            <p className="text-xs text-slate-400 mb-6">Sign in to your trading dashboard</p>

            {error && (
              <div className="mb-4 p-3 rounded-xl bg-red-50 border border-red-200 text-red-600 text-xs">{error}</div>
            )}

            {/* Google Sign-In */}
            {config?.google_enabled && (
              <>
                <div id="google-signin-btn" className="w-full mb-4" />
                <div className="flex items-center gap-3 mb-4">
                  <div className="flex-1 h-px bg-slate-200" />
                  <span className="text-[10px] text-slate-400 uppercase tracking-wider">or</span>
                  <div className="flex-1 h-px bg-slate-200" />
                </div>
              </>
            )}

            {/* Auth Mode Tabs */}
            <div className="flex gap-1 mb-5 bg-slate-50 p-1 rounded-xl">
              {[
                { key: 'password' as AuthMode, label: 'Email', icon: Mail },
                ...(config?.email_otp_enabled ? [{ key: 'email_otp' as AuthMode, label: 'Email OTP', icon: KeyRound }] : []),
                ...(config?.mobile_otp_enabled ? [{ key: 'mobile_otp' as AuthMode, label: 'Mobile', icon: Phone }] : []),
              ].map(({ key, label, icon: Icon }) => (
                <button
                  key={key}
                  onClick={() => { setMode(key); setOtpSent(false); setError(''); setOtp(''); }}
                  className={cn(
                    'flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-[11px] font-medium transition-all',
                    mode === key ? 'bg-white shadow-soft text-trading-ai' : 'text-slate-400 hover:text-slate-600'
                  )}
                >
                  <Icon size={13} />{label}
                </button>
              ))}
            </div>

            {/* Password Login */}
            {mode === 'password' && (
              <form onSubmit={handlePasswordLogin} className="space-y-4">
                <div>
                  <label className="block text-[10px] font-semibold text-slate-400 mb-2 uppercase tracking-[0.12em]">Email</label>
                  <input type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                    className="w-full px-4 py-3 rounded-xl bg-slate-50 border border-slate-200 text-slate-800 text-sm placeholder-slate-400 focus:outline-none focus:border-trading-ai/50 focus:ring-1 focus:ring-trading-ai/25 transition-all"
                    placeholder="you@example.com" required autoFocus />
                </div>
                <div>
                  <label className="block text-[10px] font-semibold text-slate-400 mb-2 uppercase tracking-[0.12em]">Password</label>
                  <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                    className="w-full px-4 py-3 rounded-xl bg-slate-50 border border-slate-200 text-slate-800 text-sm placeholder-slate-400 focus:outline-none focus:border-trading-ai/50 focus:ring-1 focus:ring-trading-ai/25 transition-all"
                    placeholder="Enter password" required />
                </div>
                <button type="submit" disabled={loading}
                  className="w-full py-3 rounded-xl font-semibold text-sm gradient-ai shadow-brand hover:opacity-90 disabled:opacity-40 transition-all flex items-center justify-center gap-2 text-white">
                  {loading ? <><Loader2 size={14} className="animate-spin" />Signing in...</> : 'Sign In'}
                </button>
              </form>
            )}

            {/* Email OTP */}
            {mode === 'email_otp' && (
              <form onSubmit={otpSent ? handleVerifyOtp : (e) => { e.preventDefault(); handleSendOtp(); }} className="space-y-4">
                <div>
                  <label className="block text-[10px] font-semibold text-slate-400 mb-2 uppercase tracking-[0.12em]">Email</label>
                  <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} disabled={otpSent}
                    className="w-full px-4 py-3 rounded-xl bg-slate-50 border border-slate-200 text-slate-800 text-sm placeholder-slate-400 focus:outline-none focus:border-trading-ai/50 transition-all disabled:opacity-60"
                    placeholder="you@example.com" required />
                </div>
                {otpSent && (
                  <div>
                    <label className="block text-[10px] font-semibold text-slate-400 mb-2 uppercase tracking-[0.12em]">Enter OTP</label>
                    <input type="text" value={otp} onChange={(e) => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))}
                      className="w-full px-4 py-3 rounded-xl bg-slate-50 border border-slate-200 text-slate-800 text-center text-lg font-mono tracking-[0.5em] placeholder-slate-400 focus:outline-none focus:border-trading-ai/50 transition-all"
                      placeholder="000000" required maxLength={6} autoFocus />
                    <p className="text-[10px] text-slate-400 mt-1">Check your email for the 6-digit code</p>
                  </div>
                )}
                <button type="submit" disabled={loading}
                  className="w-full py-3 rounded-xl font-semibold text-sm gradient-ai shadow-brand hover:opacity-90 disabled:opacity-40 transition-all flex items-center justify-center gap-2 text-white">
                  {loading ? <Loader2 size={14} className="animate-spin" /> : null}
                  {otpSent ? 'Verify OTP' : 'Send OTP'}
                </button>
                {otpSent && (
                  <button type="button" onClick={() => { setOtpSent(false); setOtp(''); }}
                    className="w-full text-xs text-slate-400 hover:text-trading-ai transition-colors">
                    Change email
                  </button>
                )}
              </form>
            )}

            {/* Mobile OTP */}
            {mode === 'mobile_otp' && (
              <form onSubmit={otpSent ? handleVerifyOtp : (e) => { e.preventDefault(); handleSendOtp(); }} className="space-y-4">
                <div>
                  <label className="block text-[10px] font-semibold text-slate-400 mb-2 uppercase tracking-[0.12em]">Mobile Number</label>
                  <div className="flex gap-2">
                    <span className="flex items-center px-3 py-3 rounded-xl bg-slate-100 border border-slate-200 text-sm text-slate-500 font-mono">+91</span>
                    <input type="tel" value={phone} onChange={(e) => setPhone(e.target.value.replace(/\D/g, '').slice(0, 10))} disabled={otpSent}
                      className="flex-1 px-4 py-3 rounded-xl bg-slate-50 border border-slate-200 text-slate-800 text-sm placeholder-slate-400 focus:outline-none focus:border-trading-ai/50 transition-all disabled:opacity-60"
                      placeholder="9876543210" required maxLength={10} />
                  </div>
                </div>
                {otpSent && (
                  <div>
                    <label className="block text-[10px] font-semibold text-slate-400 mb-2 uppercase tracking-[0.12em]">Enter OTP</label>
                    <input type="text" value={otp} onChange={(e) => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))}
                      className="w-full px-4 py-3 rounded-xl bg-slate-50 border border-slate-200 text-slate-800 text-center text-lg font-mono tracking-[0.5em] placeholder-slate-400 focus:outline-none focus:border-trading-ai/50 transition-all"
                      placeholder="000000" required maxLength={6} autoFocus />
                    <p className="text-[10px] text-slate-400 mt-1">SMS sent to your mobile</p>
                  </div>
                )}
                <button type="submit" disabled={loading}
                  className="w-full py-3 rounded-xl font-semibold text-sm gradient-ai shadow-brand hover:opacity-90 disabled:opacity-40 transition-all flex items-center justify-center gap-2 text-white">
                  {loading ? <Loader2 size={14} className="animate-spin" /> : null}
                  {otpSent ? 'Verify OTP' : 'Send OTP'}
                </button>
                {otpSent && (
                  <button type="button" onClick={() => { setOtpSent(false); setOtp(''); }}
                    className="w-full text-xs text-slate-400 hover:text-trading-ai transition-colors">
                    Change number
                  </button>
                )}
              </form>
            )}

            <p className="text-center text-[10px] text-slate-400 mt-6">
              Don't have an account? <Link to="/" className="text-trading-ai hover:text-violet-700 transition-colors">View Plans</Link>
            </p>
          </div>

          <p className="text-center text-[9px] text-slate-400 mt-6 max-w-xs mx-auto">
            AI-powered analytics for educational purposes. Not SEBI-registered investment advice.
          </p>
        </div>
      </div>
    </div>
  );
}
