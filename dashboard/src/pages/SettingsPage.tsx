import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Settings, Key, Save, Loader2, CheckCircle2, AlertCircle } from 'lucide-react';
import GlassCard from '../components/ui/GlassCard';
import { cn } from '../lib/utils';
import axios from 'axios';

const api = axios.create({ baseURL: '/api', timeout: 15000 });
const token = localStorage.getItem('mkumaran_auth_token');
if (token) api.defaults.headers.common['Authorization'] = `Bearer ${token}`;

export default function SettingsPage() {
  const [grokKey, setGrokKey] = useState('');
  const [kimiKey, setKimiKey] = useState('');
  const [preferredProvider, setPreferredProvider] = useState('grok');
  const [loading, setLoading] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');
  const [hasKeys, setHasKeys] = useState(false);

  useEffect(() => {
    api.get('/settings/api-keys').then((r) => {
      if (r.data.has_keys) {
        setHasKeys(true);
        const keys = r.data.keys;
        if (keys.grok_key) setGrokKey(keys.grok_key);
        if (keys.kimi_key) setKimiKey(keys.kimi_key);
        if (keys.preferred_provider) setPreferredProvider(keys.preferred_provider);
      }
    }).catch(() => {});
  }, []);

  const handleSave = async () => {
    setLoading(true);
    setError('');
    setSaved(false);
    try {
      await api.post('/settings/api-keys', {
        grok_key: grokKey,
        kimi_key: kimiKey,
        preferred_provider: preferredProvider,
      });
      setSaved(true);
      setHasKeys(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg || 'Failed to save');
    } finally {
      setLoading(false);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      className="space-y-5 max-w-2xl"
    >
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-xl bg-violet-50 flex items-center justify-center">
          <Settings size={16} className="text-trading-ai" />
        </div>
        <h2 className="text-sm font-bold text-slate-900">Settings</h2>
      </div>

      {/* BYOK API Keys */}
      <GlassCard>
        <div className="flex items-center gap-2 mb-4">
          <Key size={16} className="text-trading-ai" />
          <h3 className="text-sm font-semibold text-slate-900">Your AI API Keys</h3>
          <span className="text-[9px] bg-violet-50 text-trading-ai px-2 py-0.5 rounded-full font-medium">BYOK</span>
        </div>

        <p className="text-xs text-slate-500 mb-5 leading-relaxed">
          Use your own API keys for AI analysis. When set, your keys are used instead of the system default.
          Keys are encrypted at rest. Leave blank to use system keys.
        </p>

        {error && (
          <div className="mb-4 p-3 rounded-xl bg-red-50 border border-red-200 text-red-600 text-xs flex items-center gap-2">
            <AlertCircle size={14} />{error}
          </div>
        )}

        {saved && (
          <div className="mb-4 p-3 rounded-xl bg-trading-bull-dim border border-emerald-200 text-trading-bull text-xs flex items-center gap-2">
            <CheckCircle2 size={14} />API keys saved successfully
          </div>
        )}

        <div className="space-y-4">
          {/* Preferred Provider */}
          <div>
            <label className="block text-[10px] font-semibold text-slate-400 mb-2 uppercase tracking-[0.12em]">Primary AI Provider</label>
            <div className="flex gap-2">
              {[
                { key: 'grok', label: 'Grok (xAI)', desc: 'grok-3-mini' },
                { key: 'kimi', label: 'Kimi (Moonshot)', desc: 'moonshot-v1-8k' },
              ].map((p) => (
                <button
                  key={p.key}
                  onClick={() => setPreferredProvider(p.key)}
                  className={cn(
                    'flex-1 p-3 rounded-xl border text-left transition-all',
                    preferredProvider === p.key
                      ? 'border-trading-ai bg-violet-50'
                      : 'border-slate-200 hover:border-slate-300'
                  )}
                >
                  <span className={cn('text-xs font-semibold', preferredProvider === p.key ? 'text-trading-ai' : 'text-slate-700')}>{p.label}</span>
                  <span className="block text-[10px] text-slate-400 mt-0.5">{p.desc}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Grok Key */}
          <div>
            <label className="block text-[10px] font-semibold text-slate-400 mb-2 uppercase tracking-[0.12em]">
              Grok API Key <span className="text-slate-300">(api.x.ai)</span>
            </label>
            <input
              type="password"
              value={grokKey}
              onChange={(e) => setGrokKey(e.target.value)}
              className="w-full px-4 py-3 rounded-xl bg-slate-50 border border-slate-200 text-slate-800 text-sm font-mono placeholder-slate-400 focus:outline-none focus:border-trading-ai/50 focus:ring-1 focus:ring-trading-ai/25 transition-all"
              placeholder={hasKeys ? '****saved****' : 'xai-...'}
            />
          </div>

          {/* Kimi Key */}
          <div>
            <label className="block text-[10px] font-semibold text-slate-400 mb-2 uppercase tracking-[0.12em]">
              Kimi API Key <span className="text-slate-300">(api.moonshot.cn)</span>
            </label>
            <input
              type="password"
              value={kimiKey}
              onChange={(e) => setKimiKey(e.target.value)}
              className="w-full px-4 py-3 rounded-xl bg-slate-50 border border-slate-200 text-slate-800 text-sm font-mono placeholder-slate-400 focus:outline-none focus:border-trading-ai/50 focus:ring-1 focus:ring-trading-ai/25 transition-all"
              placeholder={hasKeys ? '****saved****' : 'sk-...'}
            />
          </div>

          <button
            onClick={handleSave}
            disabled={loading}
            className="flex items-center justify-center gap-2 w-full py-3 rounded-xl font-semibold text-sm gradient-ai shadow-brand hover:opacity-90 disabled:opacity-40 transition-all text-white"
          >
            {loading ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            {loading ? 'Saving...' : 'Save API Keys'}
          </button>
        </div>

        <div className="mt-4 p-3 rounded-xl bg-slate-50 border border-slate-100">
          <p className="text-[10px] text-slate-400 leading-relaxed">
            <strong className="text-slate-500">How it works:</strong> When you set your own keys, all AI features
            (signal validation, reports, /analyze) will use YOUR key and quota instead of the system default.
            You can get keys from{' '}
            <a href="https://console.x.ai" target="_blank" rel="noopener noreferrer" className="text-trading-ai hover:underline">console.x.ai</a>
            {' '}(Grok) or{' '}
            <a href="https://platform.moonshot.cn" target="_blank" rel="noopener noreferrer" className="text-trading-ai hover:underline">platform.moonshot.cn</a>
            {' '}(Kimi).
          </p>
        </div>
      </GlassCard>
    </motion.div>
  );
}
