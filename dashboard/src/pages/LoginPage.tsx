import { useState, useEffect } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { Activity, Mail, Loader2, ArrowLeft, Phone, KeyRound, User, Lock } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { cn } from '../lib/utils';
import axios from 'axios';

type PageMode = 'login' | 'register' | 'forgot';
type RegStep = 'identity' | 'otp' | 'password';
type AuthMethod = 'email' | 'mobile';

interface AuthConfig {
  google_enabled: boolean;
  google_client_id: string;
  email_otp_enabled: boolean;
  mobile_otp_enabled: boolean;
}

export default function LoginPage() {
  const [pageMode, setPageMode] = useState<PageMode>('login');
  const [authMethod, setAuthMethod] = useState<AuthMethod>('email');
  const [regStep, setRegStep] = useState<RegStep>('identity');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [city, setCity] = useState('');
  const [tradingExp, setTradingExp] = useState('');
  const [segments, setSegments] = useState<string[]>([]);
  const [regPhone, setRegPhone] = useState(''); // phone during email reg
  const [regEmail, setRegEmail] = useState(''); // email during phone reg
  const [otp, setOtp] = useState('');
  const [verifyToken, setVerifyToken] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const { login } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    axios.get('/api/auth/config').then((r) => setConfig(r.data)).catch(() => {});
  }, []);

  // Google Sign-In
  useEffect(() => {
    if (!config?.google_enabled) return;
    const script = document.createElement('script');
    script.src = 'https://accounts.google.com/gsi/client';
    script.async = true;
    script.onload = () => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const g = (window as any).google;
      g?.accounts?.id?.initialize({ client_id: config.google_client_id, callback: handleGoogle });
      g?.accounts?.id?.renderButton(document.getElementById('google-btn'),
        { theme: 'outline', size: 'large', width: '100%', text: 'signin_with', shape: 'pill' });
    };
    document.body.appendChild(script);
    return () => { try { document.body.removeChild(script); } catch {} };
  }, [config]);

  const handleGoogle = async (resp: { credential: string }) => {
    setLoading(true); setError('');
    try {
      const res = await axios.post('/api/auth/google', { credential: resp.credential });
      localStorage.setItem('mkumaran_auth_token', res.data.access_token);
      localStorage.setItem('mkumaran_auth_email', res.data.email);
      navigate('/overview', { replace: true });
      window.location.reload();
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Google sign-in failed');
    } finally { setLoading(false); }
  };

  // LOGIN with email/phone + password
  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault(); setError(''); setLoading(true);
    try {
      // Try new user-login first
      const res = await axios.post('/api/auth/user-login', {
        email: authMethod === 'email' ? email : undefined,
        phone: authMethod === 'mobile' ? phone : undefined,
        password,
      });
      localStorage.setItem('mkumaran_auth_token', res.data.access_token);
      localStorage.setItem('mkumaran_auth_email', res.data.email);
      navigate('/overview', { replace: true });
      window.location.reload();
    } catch {
      // Fallback to admin login
      try {
        await login(email, password);
        navigate('/overview', { replace: true });
      } catch (err2: unknown) {
        setError((err2 as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Invalid credentials');
      }
    } finally { setLoading(false); }
  };

  // REGISTER step 1: send OTP
  const handleSendOtp = async () => {
    setError(''); setLoading(true);
    try {
      await axios.post('/api/auth/send-otp', {
        method: authMethod,
        email: authMethod === 'email' ? email : undefined,
        phone: authMethod === 'mobile' ? phone : undefined,
      });
      setRegStep('otp');
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to send OTP');
    } finally { setLoading(false); }
  };

  // REGISTER step 2: verify OTP
  const handleVerifyOtp = async () => {
    setError(''); setLoading(true);
    try {
      const res = await axios.post('/api/auth/verify-otp', {
        method: authMethod,
        email: authMethod === 'email' ? email : undefined,
        phone: authMethod === 'mobile' ? phone : undefined,
        otp,
      });
      setVerifyToken(res.data.verify_token);
      setRegStep('password');
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Verification failed');
    } finally { setLoading(false); }
  };

  // REGISTER step 3: set password
  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault(); setError(''); setLoading(true);
    try {
      const res = await axios.post('/api/auth/register', {
        verify_token: verifyToken, password, name, city, trading_experience: tradingExp,
        segments: segments.join(','),
        phone: authMethod === 'email' ? regPhone : phone,
        email: authMethod === 'mobile' ? regEmail : email,
      });
      localStorage.setItem('mkumaran_auth_token', res.data.access_token);
      localStorage.setItem('mkumaran_auth_email', res.data.email);
      navigate('/overview', { replace: true });
      window.location.reload();
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Registration failed');
    } finally { setLoading(false); }
  };

  const resetForm = () => { setError(''); setOtp(''); setVerifyToken(''); setRegStep('identity'); };

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
            {pageMode === 'register' ? 'Join the' : 'Trade with'}<br />
            <span className="bg-gradient-to-r from-trading-ai via-violet-500 to-trading-bull bg-clip-text text-transparent">
              {pageMode === 'register' ? 'Platform' : 'Confidence'}
            </span>
          </h2>
          <p className="text-slate-500 text-sm leading-relaxed max-w-md">
            AI-powered market analytics for Indian markets. 40+ scanners, real-time monitoring, institutional-grade patterns.
          </p>
        </div>
      </div>

      {/* Right Panel */}
      <div className="w-full lg:w-1/2 flex items-center justify-center p-6 relative z-10 bg-white">
        <div className="w-full max-w-sm">
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
            {/* Page Mode Toggle */}
            <div className="flex gap-1 mb-5 bg-slate-50 p-1 rounded-xl">
              {(['login', 'register'] as PageMode[]).map((m) => (
                <button key={m} onClick={() => { setPageMode(m); resetForm(); }}
                  className={cn('flex-1 py-2 rounded-lg text-xs font-semibold transition-all capitalize',
                    pageMode === m ? 'bg-white shadow-soft text-trading-ai' : 'text-slate-400 hover:text-slate-600')}>
                  {m === 'login' ? 'Sign In' : 'Register'}
                </button>
              ))}
            </div>

            <h2 className="text-lg font-bold text-slate-900 mb-1">
              {pageMode === 'login' ? 'Welcome back' : regStep === 'password' ? 'Set your password' : regStep === 'otp' ? 'Verify OTP' : 'Create account'}
            </h2>
            <p className="text-xs text-slate-400 mb-5">
              {pageMode === 'login' ? 'Sign in with your email or phone' : regStep === 'password' ? 'Choose a strong password' : regStep === 'otp' ? `Enter the code sent to your ${authMethod}` : 'Verify your email or phone to get started'}
            </p>

            {error && <div className="mb-4 p-3 rounded-xl bg-red-50 border border-red-200 text-red-600 text-xs">{error}</div>}

            {/* Google (show on both login & register) */}
            {config?.google_enabled && regStep === 'identity' && (
              <>
                <div id="google-btn" className="w-full mb-4" />
                <div className="flex items-center gap-3 mb-4">
                  <div className="flex-1 h-px bg-slate-200" /><span className="text-[10px] text-slate-400 uppercase">or</span><div className="flex-1 h-px bg-slate-200" />
                </div>
              </>
            )}

            {/* Auth Method Tabs (email vs mobile) */}
            {regStep === 'identity' && (
              <div className="flex gap-1 mb-4 bg-slate-50 p-1 rounded-xl">
                <button onClick={() => setAuthMethod('email')}
                  className={cn('flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-[11px] font-medium transition-all',
                    authMethod === 'email' ? 'bg-white shadow-soft text-trading-ai' : 'text-slate-400')}>
                  <Mail size={13} />Email
                </button>
                {(config?.mobile_otp_enabled || pageMode === 'login') && (
                  <button onClick={() => setAuthMethod('mobile')}
                    className={cn('flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-[11px] font-medium transition-all',
                      authMethod === 'mobile' ? 'bg-white shadow-soft text-trading-ai' : 'text-slate-400')}>
                    <Phone size={13} />Mobile
                  </button>
                )}
              </div>
            )}

            {/* ─── LOGIN FORM ─── */}
            {pageMode === 'login' && (
              <form onSubmit={handleLogin} className="space-y-4">
                {authMethod === 'email' ? (
                  <div>
                    <label className="block text-[10px] font-semibold text-slate-400 mb-2 uppercase tracking-[0.12em]">Email</label>
                    <input type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                      className="w-full px-4 py-3 rounded-xl bg-slate-50 border border-slate-200 text-slate-800 text-sm placeholder-slate-400 focus:outline-none focus:border-trading-ai/50 focus:ring-1 focus:ring-trading-ai/25 transition-all"
                      placeholder="you@example.com" required autoFocus />
                  </div>
                ) : (
                  <div>
                    <label className="block text-[10px] font-semibold text-slate-400 mb-2 uppercase tracking-[0.12em]">Mobile</label>
                    <div className="flex gap-2">
                      <span className="flex items-center px-3 py-3 rounded-xl bg-slate-100 border border-slate-200 text-sm text-slate-500 font-mono">+91</span>
                      <input type="tel" value={phone} onChange={(e) => setPhone(e.target.value.replace(/\D/g, '').slice(0, 10))}
                        className="flex-1 px-4 py-3 rounded-xl bg-slate-50 border border-slate-200 text-slate-800 text-sm placeholder-slate-400 focus:outline-none focus:border-trading-ai/50 transition-all"
                        placeholder="9876543210" required maxLength={10} />
                    </div>
                  </div>
                )}
                <div>
                  <label className="block text-[10px] font-semibold text-slate-400 mb-2 uppercase tracking-[0.12em]">Password</label>
                  <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                    className="w-full px-4 py-3 rounded-xl bg-slate-50 border border-slate-200 text-slate-800 text-sm placeholder-slate-400 focus:outline-none focus:border-trading-ai/50 transition-all"
                    placeholder="Enter password" required />
                </div>
                <button type="submit" disabled={loading}
                  className="w-full py-3 rounded-xl font-semibold text-sm gradient-ai shadow-brand hover:opacity-90 disabled:opacity-40 transition-all flex items-center justify-center gap-2 text-white">
                  {loading ? <><Loader2 size={14} className="animate-spin" />Signing in...</> : 'Sign In'}
                </button>
                <button type="button" onClick={() => { setPageMode('forgot'); resetForm(); }}
                  className="w-full text-xs text-slate-400 hover:text-trading-ai transition-colors">
                  Forgot password?
                </button>
              </form>
            )}

            {/* ─── REGISTER: Step 1 — Enter Email/Phone ─── */}
            {pageMode === 'register' && regStep === 'identity' && (
              <div className="space-y-4">
                {authMethod === 'email' ? (
                  <div>
                    <label className="block text-[10px] font-semibold text-slate-400 mb-2 uppercase tracking-[0.12em]">Email</label>
                    <input type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                      className="w-full px-4 py-3 rounded-xl bg-slate-50 border border-slate-200 text-slate-800 text-sm placeholder-slate-400 focus:outline-none focus:border-trading-ai/50 transition-all"
                      placeholder="you@example.com" required autoFocus />
                  </div>
                ) : (
                  <div>
                    <label className="block text-[10px] font-semibold text-slate-400 mb-2 uppercase tracking-[0.12em]">Mobile</label>
                    <div className="flex gap-2">
                      <span className="flex items-center px-3 py-3 rounded-xl bg-slate-100 border border-slate-200 text-sm text-slate-500 font-mono">+91</span>
                      <input type="tel" value={phone} onChange={(e) => setPhone(e.target.value.replace(/\D/g, '').slice(0, 10))}
                        className="flex-1 px-4 py-3 rounded-xl bg-slate-50 border border-slate-200 text-slate-800 text-sm placeholder-slate-400 focus:outline-none focus:border-trading-ai/50 transition-all"
                        placeholder="9876543210" required maxLength={10} />
                    </div>
                  </div>
                )}
                <button onClick={handleSendOtp} disabled={loading || (!email && !phone)}
                  className="w-full py-3 rounded-xl font-semibold text-sm gradient-ai shadow-brand hover:opacity-90 disabled:opacity-40 transition-all flex items-center justify-center gap-2 text-white">
                  {loading ? <Loader2 size={14} className="animate-spin" /> : <KeyRound size={14} />}
                  Send Verification Code
                </button>
              </div>
            )}

            {/* ─── REGISTER: Step 2 — Enter OTP ─── */}
            {(pageMode === 'register' || pageMode === 'forgot') && regStep === 'otp' && (
              <div className="space-y-4">
                <div>
                  <label className="block text-[10px] font-semibold text-slate-400 mb-2 uppercase tracking-[0.12em]">Verification Code</label>
                  <input type="text" value={otp} onChange={(e) => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))}
                    className="w-full px-4 py-3 rounded-xl bg-slate-50 border border-slate-200 text-slate-800 text-center text-lg font-mono tracking-[0.5em] placeholder-slate-400 focus:outline-none focus:border-trading-ai/50 transition-all"
                    placeholder="000000" required maxLength={6} autoFocus />
                  <p className="text-[10px] text-slate-400 mt-1.5">
                    Sent to {authMethod === 'email' ? email : `+91 ${phone}`}
                  </p>
                </div>
                <button onClick={handleVerifyOtp} disabled={loading || otp.length < 6}
                  className="w-full py-3 rounded-xl font-semibold text-sm gradient-ai shadow-brand hover:opacity-90 disabled:opacity-40 transition-all flex items-center justify-center gap-2 text-white">
                  {loading ? <Loader2 size={14} className="animate-spin" /> : null}
                  Verify Code
                </button>
                <button onClick={resetForm} className="w-full text-xs text-slate-400 hover:text-trading-ai transition-colors">
                  Change {authMethod}
                </button>
              </div>
            )}

            {/* ─── REGISTER: Step 3 — Profile Details ─── */}
            {pageMode === 'register' && regStep === 'password' && (
              <form onSubmit={handleRegister} className="space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-[10px] font-semibold text-slate-400 mb-1.5 uppercase tracking-[0.12em]">Full Name *</label>
                    <input type="text" value={name} onChange={(e) => setName(e.target.value)}
                      className="w-full px-3 py-2.5 rounded-xl bg-slate-50 border border-slate-200 text-slate-800 text-sm placeholder-slate-400 focus:outline-none focus:border-trading-ai/50 transition-all"
                      placeholder="John Doe" required autoFocus />
                  </div>
                  <div>
                    <label className="block text-[10px] font-semibold text-slate-400 mb-1.5 uppercase tracking-[0.12em]">City *</label>
                    <input type="text" value={city} onChange={(e) => setCity(e.target.value)}
                      className="w-full px-3 py-2.5 rounded-xl bg-slate-50 border border-slate-200 text-slate-800 text-sm placeholder-slate-400 focus:outline-none focus:border-trading-ai/50 transition-all"
                      placeholder="Mumbai" required />
                  </div>
                </div>

                {/* Collect the other contact method */}
                {authMethod === 'email' && (
                  <div>
                    <label className="block text-[10px] font-semibold text-slate-400 mb-1.5 uppercase tracking-[0.12em]">Mobile Number *</label>
                    <div className="flex gap-2">
                      <span className="flex items-center px-2.5 py-2.5 rounded-xl bg-slate-100 border border-slate-200 text-xs text-slate-500 font-mono">+91</span>
                      <input type="tel" value={regPhone} onChange={(e) => setRegPhone(e.target.value.replace(/\D/g, '').slice(0, 10))}
                        className="flex-1 px-3 py-2.5 rounded-xl bg-slate-50 border border-slate-200 text-slate-800 text-sm placeholder-slate-400 focus:outline-none focus:border-trading-ai/50 transition-all"
                        placeholder="9876543210" maxLength={10} required />
                    </div>
                  </div>
                )}
                {authMethod === 'mobile' && (
                  <div>
                    <label className="block text-[10px] font-semibold text-slate-400 mb-1.5 uppercase tracking-[0.12em]">Email Address *</label>
                    <input type="email" value={regEmail} onChange={(e) => setRegEmail(e.target.value)}
                      className="w-full px-3 py-2.5 rounded-xl bg-slate-50 border border-slate-200 text-slate-800 text-sm placeholder-slate-400 focus:outline-none focus:border-trading-ai/50 transition-all"
                      placeholder="you@example.com" required />
                  </div>
                )}

                <div>
                  <label className="block text-[10px] font-semibold text-slate-400 mb-1.5 uppercase tracking-[0.12em]">Trading Experience *</label>
                  <select value={tradingExp} onChange={(e) => setTradingExp(e.target.value)} required
                    className="w-full px-3 py-2.5 rounded-xl bg-slate-50 border border-slate-200 text-slate-800 text-sm focus:outline-none focus:border-trading-ai/50 transition-all">
                    <option value="">Select experience</option>
                    <option value="beginner">Beginner (0-1 years)</option>
                    <option value="intermediate">Intermediate (1-3 years)</option>
                    <option value="experienced">Experienced (3-5 years)</option>
                    <option value="expert">Expert (5+ years)</option>
                  </select>
                </div>

                <div>
                  <label className="block text-[10px] font-semibold text-slate-400 mb-1.5 uppercase tracking-[0.12em]">Trading Segments *</label>
                  <div className="flex flex-wrap gap-2">
                    {['NSE Equity', 'F&O', 'Commodity', 'Forex', 'Options'].map((seg) => (
                      <button key={seg} type="button"
                        onClick={() => setSegments((prev) => prev.includes(seg) ? prev.filter((s) => s !== seg) : [...prev, seg])}
                        className={cn(
                          'px-3 py-1.5 rounded-lg text-[11px] font-medium transition-all border',
                          segments.includes(seg)
                            ? 'bg-trading-ai-bg text-trading-ai border-violet-200'
                            : 'bg-slate-50 text-slate-500 border-slate-200 hover:border-slate-300'
                        )}>
                        {seg}
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <label className="block text-[10px] font-semibold text-slate-400 mb-1.5 uppercase tracking-[0.12em]">Set Password *</label>
                  <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                    className="w-full px-3 py-2.5 rounded-xl bg-slate-50 border border-slate-200 text-slate-800 text-sm placeholder-slate-400 focus:outline-none focus:border-trading-ai/50 transition-all"
                    placeholder="Minimum 6 characters" required minLength={6} />
                </div>

                <button type="submit" disabled={loading || !name.trim() || !city.trim() || !tradingExp || segments.length === 0 || (authMethod === 'email' ? !regPhone : !regEmail)}
                  className="w-full py-3 rounded-xl font-semibold text-sm gradient-ai shadow-brand hover:opacity-90 disabled:opacity-40 transition-all flex items-center justify-center gap-2 text-white">
                  {loading ? <><Loader2 size={14} className="animate-spin" />Creating...</> : <><User size={14} />Create Account</>}
                </button>
              </form>
            )}

            {/* ─── FORGOT: Step 3 — New Password ─── */}
            {pageMode === 'forgot' && regStep === 'password' && (
              <form onSubmit={async (e) => {
                e.preventDefault(); setError(''); setLoading(true);
                try {
                  await axios.post('/api/auth/reset-password', { verify_token: verifyToken, password });
                  setPageMode('login'); resetForm();
                } catch (err: unknown) {
                  setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Reset failed');
                } finally { setLoading(false); }
              }} className="space-y-4">
                <div>
                  <label className="block text-[10px] font-semibold text-slate-400 mb-2 uppercase tracking-[0.12em]">New Password</label>
                  <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                    className="w-full px-4 py-3 rounded-xl bg-slate-50 border border-slate-200 text-slate-800 text-sm placeholder-slate-400 focus:outline-none focus:border-trading-ai/50 transition-all"
                    placeholder="Minimum 6 characters" required minLength={6} autoFocus />
                </div>
                <button type="submit" disabled={loading}
                  className="w-full py-3 rounded-xl font-semibold text-sm gradient-ai shadow-brand hover:opacity-90 disabled:opacity-40 transition-all flex items-center justify-center gap-2 text-white">
                  {loading ? <Loader2 size={14} className="animate-spin" /> : <Lock size={14} />}
                  Reset Password
                </button>
              </form>
            )}

            {/* Forgot password entry */}
            {pageMode === 'forgot' && regStep === 'identity' && (
              <div className="space-y-4">
                <div>
                  <label className="block text-[10px] font-semibold text-slate-400 mb-2 uppercase tracking-[0.12em]">
                    {authMethod === 'email' ? 'Email' : 'Mobile'}
                  </label>
                  {authMethod === 'email' ? (
                    <input type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                      className="w-full px-4 py-3 rounded-xl bg-slate-50 border border-slate-200 text-slate-800 text-sm placeholder-slate-400 focus:outline-none focus:border-trading-ai/50 transition-all"
                      placeholder="you@example.com" required autoFocus />
                  ) : (
                    <div className="flex gap-2">
                      <span className="flex items-center px-3 py-3 rounded-xl bg-slate-100 border border-slate-200 text-sm text-slate-500 font-mono">+91</span>
                      <input type="tel" value={phone} onChange={(e) => setPhone(e.target.value.replace(/\D/g, '').slice(0, 10))}
                        className="flex-1 px-4 py-3 rounded-xl bg-slate-50 border border-slate-200 text-slate-800 text-sm placeholder-slate-400 focus:outline-none focus:border-trading-ai/50 transition-all"
                        placeholder="9876543210" required maxLength={10} />
                    </div>
                  )}
                </div>
                <button onClick={handleSendOtp} disabled={loading || (!email && !phone)}
                  className="w-full py-3 rounded-xl font-semibold text-sm gradient-ai shadow-brand hover:opacity-90 disabled:opacity-40 transition-all flex items-center justify-center gap-2 text-white">
                  {loading ? <Loader2 size={14} className="animate-spin" /> : null}
                  Send Reset Code
                </button>
                <button onClick={() => { setPageMode('login'); resetForm(); }}
                  className="w-full text-xs text-slate-400 hover:text-trading-ai transition-colors">
                  Back to login
                </button>
              </div>
            )}
          </div>

          <p className="text-center text-[9px] text-slate-400 mt-6 max-w-xs mx-auto">
            AI-powered analytics for educational purposes. Not SEBI-registered investment advice.
          </p>
        </div>
      </div>
    </div>
  );
}
