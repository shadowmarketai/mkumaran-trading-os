import { useEffect, useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Zap, Clock, RefreshCw, TrendingUp, AlertTriangle,
  BarChart3, Activity, ChevronUp,
} from 'lucide-react';
import GlassCard from '../components/ui/GlassCard';
import { cn } from '../lib/utils';

interface ScreenerResult {
  ticker:    string;
  price:     number;
  vol_ratio: number;
  rsi:       number;
  pe:        number | null;
}

interface ScreenerData {
  market_open: boolean;
  scanning:    boolean;
  last_scan:   string | null;
  next_scan:   number | null;
  results:     ScreenerResult[];
}

function formatCountdown(secs: number | null): string {
  if (secs == null || secs < 0) return '—';
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return m > 0 ? `${m}m ${s.toString().padStart(2, '0')}s` : `${s}s`;
}

function VolRatioBadge({ ratio }: { ratio: number }) {
  const tier = ratio >= 5 ? 'high' : ratio >= 3 ? 'mid' : 'base';
  return (
    <span className={cn(
      'font-mono font-semibold',
      tier === 'high' && 'text-emerald-400',
      tier === 'mid'  && 'text-emerald-300',
      tier === 'base' && 'text-emerald-200/80',
    )}>
      {ratio.toFixed(2)}×
    </span>
  );
}

function RsiBar({ value }: { value: number }) {
  const pct = Math.min(value, 100);
  const color = value >= 70 ? 'bg-rose-400' : value >= 60 ? 'bg-amber-400' : 'bg-blue-400';
  const textColor = value >= 70 ? 'text-rose-400' : value >= 60 ? 'text-amber-400' : 'text-blue-400';
  return (
    <div className="flex items-center gap-2 justify-end">
      <div className="w-14 h-1.5 bg-slate-800 rounded-full overflow-hidden">
        <div className={cn('h-full rounded-full transition-all', color)} style={{ width: `${pct}%` }} />
      </div>
      <span className={cn('font-mono text-sm', textColor)}>{value.toFixed(1)}</span>
    </div>
  );
}

export default function ScreenerPage() {
  const [data, setData]       = useState<ScreenerData | null>(null);
  const [loading, setLoading] = useState(true);
  const [triggering, setTriggering] = useState(false);

  const fetch_ = useCallback(async () => {
    try {
      const res = await fetch('/api/screener/results');
      const json: ScreenerData = await res.json();
      setData(json);
    } catch {
      // silent — keep stale data
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetch_();
    const id = setInterval(fetch_, 5000);
    return () => clearInterval(id);
  }, [fetch_]);

  const triggerScan = async () => {
    if (triggering || !data?.market_open) return;
    setTriggering(true);
    try {
      await fetch('/api/screener/scan', { method: 'POST' });
      setTimeout(fetch_, 1000);
    } finally {
      setTriggering(false);
    }
  };

  const marketOpen = data?.market_open ?? false;

  return (
    <div className="p-6 space-y-5">

      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Zap size={20} className="text-indigo-400" />
            Nifty 500 Screener
          </h1>
          <p className="text-sm text-slate-400 mt-0.5">
            Volume spike ≥ 2× · RSI(14) ≥ 50 · Top 20 by volume ratio
          </p>
        </div>
        <div className="flex items-center gap-3">
          {/* Market status */}
          <div className={cn(
            'flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium border',
            marketOpen
              ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-400'
              : 'border-slate-700 bg-slate-800/50 text-slate-400'
          )}>
            <span className={cn(
              'w-2 h-2 rounded-full',
              marketOpen ? 'bg-emerald-400 animate-pulse' : 'bg-slate-500'
            )} />
            {marketOpen ? 'Market Open' : 'Market Closed'}
          </div>

          <button
            onClick={triggerScan}
            disabled={!marketOpen || triggering || data?.scanning}
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg transition-colors',
              'bg-indigo-600 hover:bg-indigo-500 text-white',
              'disabled:opacity-40 disabled:cursor-not-allowed',
            )}
          >
            <RefreshCw size={12} className={triggering || data?.scanning ? 'animate-spin' : ''} />
            Scan Now
          </button>
        </div>
      </div>

      {/* Market closed banner */}
      <AnimatePresence>
        {!marketOpen && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            className="flex items-start gap-3 bg-amber-500/10 border border-amber-500/25 rounded-xl p-4"
          >
            <AlertTriangle size={16} className="text-amber-400 mt-0.5 flex-shrink-0" />
            <div className="text-sm">
              <div className="text-amber-400 font-medium">Market Closed</div>
              <div className="text-amber-300/60 text-xs mt-0.5">
                NSE trades Mon–Fri 09:15–15:30 IST. Screener auto-resumes at open.
                {data?.results.length ? ' Showing results from last scan.' : ''}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          {
            label: 'Matches',
            value: loading ? '…' : String(data?.results.length ?? '—'),
            icon: <BarChart3 size={14} className="text-indigo-400" />,
          },
          {
            label: 'Last Scan',
            value: data?.last_scan ?? '—',
            icon: <Clock size={14} className="text-slate-400" />,
            mono: true,
          },
          {
            label: 'Next Scan',
            value: data?.scanning ? 'Scanning…' : formatCountdown(data?.next_scan ?? null),
            icon: <Activity size={14} className="text-slate-400" />,
            mono: true,
          },
          {
            label: 'Universe',
            value: '500',
            icon: <TrendingUp size={14} className="text-slate-400" />,
          },
        ].map((s) => (
          <GlassCard key={s.label} className="p-4">
            <div className="flex items-center gap-1.5 text-xs text-slate-500 mb-2">
              {s.icon}
              {s.label}
            </div>
            <div className={cn(
              'text-lg font-bold text-white',
              s.mono && 'font-mono text-sm',
            )}>
              {s.value}
            </div>
          </GlassCard>
        ))}
      </div>

      {/* Scan in progress */}
      <AnimatePresence>
        {data?.scanning && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex items-center gap-2 text-sm text-indigo-400"
          >
            <span className="w-2 h-2 rounded-full bg-indigo-400 animate-pulse" />
            Scanning 500 tickers — this takes ~20 seconds…
          </motion.div>
        )}
      </AnimatePresence>

      {/* Results table */}
      <GlassCard className="overflow-hidden p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800">
                {['#', 'Ticker', 'Price (₹)', 'Vol Ratio', 'RSI(14)', 'P/E'].map((h, i) => (
                  <th
                    key={h}
                    className={cn(
                      'px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wider',
                      i === 0 ? 'text-left w-10' :
                      i === 1 ? 'text-left' : 'text-right',
                    )}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td colSpan={6} className="px-4 py-12 text-center text-slate-600 text-sm">
                    Loading…
                  </td>
                </tr>
              )}
              {!loading && (!data?.results.length) && (
                <tr>
                  <td colSpan={6} className="px-4 py-12 text-center text-slate-600 text-sm">
                    {data?.scanning
                      ? 'Scan in progress…'
                      : marketOpen
                        ? 'No stocks matched filters in last scan.'
                        : 'Waiting for market open to start first scan.'}
                  </td>
                </tr>
              )}
              <AnimatePresence>
                {data?.results.map((r, i) => (
                  <motion.tr
                    key={r.ticker}
                    initial={{ opacity: 0, y: 4 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.03 }}
                    className={cn(
                      'border-b border-slate-800/60 hover:bg-slate-800/30 transition-colors',
                      i === 0 && 'bg-indigo-500/5',
                    )}
                  >
                    <td className="px-4 py-3 text-slate-600 font-mono text-xs">{i + 1}</td>
                    <td className="px-4 py-3">
                      <div className="font-semibold text-white flex items-center gap-1.5">
                        {i === 0 && <ChevronUp size={12} className="text-indigo-400" />}
                        {r.ticker}
                      </div>
                      <div className="text-xs text-slate-500">NSE</div>
                    </td>
                    <td className="px-4 py-3 text-right font-mono font-medium text-white">
                      ₹{r.price.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <VolRatioBadge ratio={r.vol_ratio} />
                    </td>
                    <td className="px-4 py-3">
                      <RsiBar value={r.rsi} />
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-slate-300">
                      {r.pe != null ? r.pe.toFixed(1) : <span className="text-slate-600">—</span>}
                    </td>
                  </motion.tr>
                ))}
              </AnimatePresence>
            </tbody>
          </table>
        </div>
      </GlassCard>

      <p className="text-xs text-slate-600 text-center">
        Data via yfinance · Refreshes every 5 min during market hours · NSE equities only
      </p>
    </div>
  );
}
