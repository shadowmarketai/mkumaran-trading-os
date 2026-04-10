import { useState, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import {
  Zap,
  TrendingUp,
  Target,
  Compass,
  ArrowUpRight,
  ArrowDownRight,
  Loader2,
  AlertCircle,
  AlertTriangle,
  Newspaper,
  ExternalLink,
  RefreshCw,
} from 'lucide-react';
import MetricCard from '../components/ui/MetricCard';
import GlassCard from '../components/ui/GlassCard';
import StatusBadge from '../components/ui/StatusBadge';
import SignalCard from '../components/ui/SignalCard';
import { useMWA } from '../hooks/useMWA';
import { useSignals } from '../hooks/useSignals';
import { overviewApi, mwaApi } from '../services/api';
import { useMarketSegment } from '../context/MarketSegmentContext';
import { useNews } from '../hooks/useNews';
import { cn } from '../lib/utils';
import type { Signal, ScannerResult, SectorStrength } from '../types';

// --- Scanner Heatmap ---
function ScannerCell({ scanner }: { scanner: ScannerResult }) {
  const colorMap: Record<string, string> = {
    BULL: 'bg-trading-bull/10 text-trading-bull border-trading-bull/12',
    BEAR: 'bg-trading-bear/10 text-trading-bear border-trading-bear/12',
    NEUTRAL: 'bg-trading-bg-secondary/60 text-slate-500 border-trading-border/20',
  };

  return (
    <div
      className={cn('p-2 rounded-xl border text-center transition-all hover:scale-[1.02]', colorMap[scanner.direction])}
      title={`${scanner.name}: ${scanner.count} stocks`}
    >
      <p className="text-[9px] font-medium truncate text-slate-400">{scanner.name}</p>
      <p className="text-lg font-mono font-bold tabular-nums">{scanner.count}</p>
      <p className="text-[8px] opacity-50 font-mono">{scanner.group}</p>
    </div>
  );
}

// --- Score Bar ---
function ScoreBar({ bullPct, bearPct }: { bullPct: number; bearPct: number }) {
  return (
    <div className="space-y-2">
      <div className="flex justify-between text-[10px] font-mono">
        <span className="text-trading-bull flex items-center gap-1">
          <ArrowUpRight size={10} /> BULL {(bullPct ?? 0).toFixed(1)}%
        </span>
        <span className="text-trading-bear flex items-center gap-1">
          BEAR {(bearPct ?? 0).toFixed(1)}% <ArrowDownRight size={10} />
        </span>
      </div>
      <div className="h-2 bg-trading-bg-secondary rounded-full overflow-hidden flex border border-trading-border/20">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${bullPct}%` }}
          transition={{ duration: 1.2, ease: [0.16, 1, 0.3, 1] }}
          className="h-full bg-gradient-to-r from-trading-bull to-trading-bull-light"
        />
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${bearPct}%` }}
          transition={{ duration: 1.2, ease: [0.16, 1, 0.3, 1], delay: 0.15 }}
          className="h-full bg-gradient-to-r from-trading-bear-dark to-trading-bear"
        />
      </div>
    </div>
  );
}

// --- Sector Badge ---
function SectorBadge({ sector, strength }: { sector: string; strength: SectorStrength }) {
  return (
    <div className="flex items-center justify-between px-3 py-2.5 bg-trading-bg-secondary/40 rounded-xl border border-trading-border/20">
      <span className="text-xs text-slate-400">{sector}</span>
      <StatusBadge status={strength} size="sm" />
    </div>
  );
}

// --- Layer colors ---
const layerColors: Record<string, string> = {
  Trend: 'bg-blue-400',
  Volume: 'bg-cyan-400',
  Breakout: 'bg-amber-400',
  RSI: 'bg-purple-400',
  Gap: 'bg-red-400',
  MA: 'bg-teal-400',
  Filter: 'bg-slate-400',
  SMC: 'bg-violet-400',
  Wyckoff: 'bg-amber-500',
  VSA: 'bg-cyan-500',
  Harmonic: 'bg-pink-400',
  RL: 'bg-emerald-400',
  Forex: 'bg-indigo-400',
  Commodity: 'bg-orange-400',
  FnO: 'bg-lime-400',
};

function groupByLayer(scanners: ScannerResult[]): [string, ScannerResult[]][] {
  const groups: Record<string, ScannerResult[]> = {};
  for (const s of scanners) {
    const layer = s.group || 'Other';
    if (!groups[layer]) groups[layer] = [];
    groups[layer].push(s);
  }
  const order = ['Trend', 'Volume', 'Breakout', 'RSI', 'Gap', 'MA', 'Filter', 'SMC', 'Wyckoff', 'VSA', 'Harmonic', 'RL', 'Forex', 'Commodity', 'FnO'];
  const entries = Object.entries(groups);
  entries.sort((a, b) => {
    const ia = order.indexOf(a[0]);
    const ib = order.indexOf(b[0]);
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
  });
  return entries;
}

// --- News Widget ---
function NewsWidget() {
  const { items, loading } = useNews({ hours: 12, minImpact: 'MEDIUM' });
  const highItems = items.filter((i) => i.impact === 'HIGH');
  const medItems = items.filter((i) => i.impact === 'MEDIUM');
  const displayItems = [...highItems, ...medItems].slice(0, 5);

  if (loading || displayItems.length === 0) return null;

  return (
    <GlassCard>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Newspaper size={14} className="text-trading-ai" />
          <h3 className="stat-label">Market News</h3>
          {highItems.length > 0 && (
            <span className="flex items-center gap-1 px-1.5 py-0.5 rounded-lg bg-trading-bear/10 text-trading-bear text-[9px] font-mono font-bold border border-trading-bear/20">
              <AlertTriangle size={9} />
              {highItems.length} HIGH
            </span>
          )}
        </div>
        <a href="/news" className="text-[9px] text-trading-ai hover:text-trading-ai-light transition-colors">
          View all
        </a>
      </div>
      <div className="space-y-1">
        {displayItems.map((item, idx) => (
          <div
            key={item.url || `${item.title}-${idx}`}
            className={cn(
              'flex items-center gap-2 px-3 py-2 rounded-xl hover:bg-white/[0.02] transition-colors',
              item.impact === 'HIGH' ? 'bg-trading-bear/[0.03]' : '',
            )}
          >
            <span className={cn(
              'w-1.5 h-1.5 rounded-full flex-shrink-0',
              item.impact === 'HIGH' ? 'bg-trading-bear' : 'bg-trading-alert',
            )} />
            <span className="text-[11px] text-slate-300 truncate flex-1">{item.title}</span>
            <span className="text-[9px] text-slate-600 font-mono flex-shrink-0">{item.source}</span>
            {item.url && (
              <a href={item.url} target="_blank" rel="noopener noreferrer" className="flex-shrink-0">
                <ExternalLink size={9} className="text-slate-600 hover:text-slate-400 transition-colors" />
              </a>
            )}
          </div>
        ))}
      </div>
    </GlassCard>
  );
}

// --- Main Page ---
export default function OverviewPage() {
  const { mwa, loading: mwaLoading, error: mwaError, refetch: refreshMwa } = useMWA();
  const { signals, loading: signalsLoading } = useSignals(20);
  const { filter } = useMarketSegment();
  const [stats, setStats] = useState({ active_trades: 0, win_rate: 0, today_signals: 0 });
  const [mwaSignals, setMwaSignals] = useState<Signal[]>([]);
  const [scanning, setScanning] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);

  const handleRunMwaScan = useCallback(async () => {
    setScanning(true);
    setScanError(null);
    try {
      const result = await mwaApi.runScan();
      refreshMwa();
      if (result.mwa_signal_cards) {
        const cards = await mwaApi.getSignalCards();
        if (Array.isArray(cards)) setMwaSignals(cards);
      }
    } catch (err) {
      setScanError(err instanceof Error ? err.message : 'MWA scan failed');
    } finally {
      setScanning(false);
    }
  }, [refreshMwa]);

  useEffect(() => {
    overviewApi.getOverview(filter).then((data) => {
      const d = data as unknown as Record<string, number>;
      setStats({
        active_trades: d.active_trades ?? 0,
        win_rate: d.win_rate ?? 0,
        today_signals: d.today_signals ?? 0,
      });
    }).catch(() => {});
    mwaApi.getSignalCards().then((data) => {
      if (Array.isArray(data)) setMwaSignals(data);
    }).catch(() => {});
  }, [filter]);

  const loading = mwaLoading || signalsLoading;

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <div className="relative">
          <div className="w-12 h-12 rounded-2xl bg-trading-ai/10 flex items-center justify-center">
            <Loader2 size={24} className="text-trading-ai animate-spin" />
          </div>
          <div className="absolute inset-0 rounded-2xl bg-trading-ai/5 animate-ping" />
        </div>
        <p className="text-slate-500 text-xs mt-4 font-mono">Loading market data...</p>
      </div>
    );
  }

  if (mwaError) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <div className="w-12 h-12 rounded-2xl bg-trading-alert/10 flex items-center justify-center mb-4">
          <AlertCircle size={24} className="text-trading-alert" />
        </div>
        <p className="text-slate-500 text-xs">{mwaError}</p>
      </div>
    );
  }

  const allScannerEntries = mwa?.scanner_results ? Object.values(mwa.scanner_results) : [];
  const segmentLayerMap: Record<string, string[]> = {
    NSE: ['Trend', 'Volume', 'Breakout', 'RSI', 'Gap', 'MA', 'Filter', 'SMC', 'Wyckoff', 'VSA', 'Harmonic', 'RL'],
    MCX: ['Commodity'],
    CDS: ['Forex'],
    NFO: ['FnO'],
  };
  const scannerEntries = filter.exchange && segmentLayerMap[filter.exchange]
    ? allScannerEntries.filter((s) => segmentLayerMap[filter.exchange!].includes(s.group))
    : allScannerEntries;
  const scannerLayers = groupByLayer(scannerEntries);
  const sectorEntries = mwa?.sector_strength ? Object.entries(mwa.sector_strength) : [];

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
      className="space-y-5"
    >
      {/* Top Metric Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
        <MetricCard title="Today's Signals" value={stats.today_signals || signals.length} icon={Zap} color="ai" />
        <MetricCard title="Active Trades" value={stats.active_trades} icon={TrendingUp} color="bull" />
        <MetricCard title="Win Rate" value={stats.win_rate > 0 ? `${stats.win_rate}%` : '--'} icon={Target} color="info" />
        <MetricCard title="MWA Direction" value={mwa?.direction?.replace('_', ' ') || 'N/A'} icon={Compass} color="alert" />
      </div>

      {/* MWA Score + Scanner Grid */}
      {mwa ? (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
          {/* MWA Score */}
          <GlassCard className="lg:col-span-1">
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="stat-label">Market Weighted Average</h3>
                <StatusBadge status={mwa.direction} />
              </div>

              <button
                onClick={handleRunMwaScan}
                disabled={scanning}
                className={cn(
                  'w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-xs font-semibold transition-all',
                  scanning
                    ? 'bg-trading-bg-secondary text-slate-500 cursor-not-allowed'
                    : 'bg-trading-ai/12 text-trading-ai-light hover:bg-trading-ai/18 border border-trading-ai/25'
                )}
              >
                {scanning ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
                {scanning ? 'Running MWA Scan...' : 'Run MWA Scan'}
              </button>
              {scanError && <p className="text-[10px] text-trading-bear">{scanError}</p>}

              <ScoreBar bullPct={mwa.bull_pct} bearPct={mwa.bear_pct} />

              <div className="grid grid-cols-2 gap-2">
                <div className="text-center p-3 rounded-xl bg-trading-bull/[0.04] border border-trading-bull/10">
                  <p className="text-2xl font-mono font-bold text-trading-bull tabular-nums">{mwa.bull_score}</p>
                  <p className="stat-label mt-1">Bull Score</p>
                </div>
                <div className="text-center p-3 rounded-xl bg-trading-bear/[0.04] border border-trading-bear/10">
                  <p className="text-2xl font-mono font-bold text-trading-bear tabular-nums">{mwa.bear_score}</p>
                  <p className="stat-label mt-1">Bear Score</p>
                </div>
              </div>

              {/* FII / DII */}
              <div className="pt-3 border-t border-trading-border/20 space-y-2">
                <h4 className="stat-label">Institutional Flow</h4>
                <div className="grid grid-cols-2 gap-2">
                  <div className="flex items-center justify-between p-2.5 rounded-xl bg-trading-bg-secondary/40 border border-trading-border/20">
                    <span className="text-[10px] text-slate-500">FII</span>
                    <span className={cn('text-xs font-mono font-bold tabular-nums', (mwa.fii_net ?? 0) >= 0 ? 'text-trading-bull' : 'text-trading-bear')}>
                      {(mwa.fii_net ?? 0) >= 0 ? '+' : ''}{(mwa.fii_net ?? 0).toFixed(0)} Cr
                    </span>
                  </div>
                  <div className="flex items-center justify-between p-2.5 rounded-xl bg-trading-bg-secondary/40 border border-trading-border/20">
                    <span className="text-[10px] text-slate-500">DII</span>
                    <span className={cn('text-xs font-mono font-bold tabular-nums', (mwa.dii_net ?? 0) >= 0 ? 'text-trading-bull' : 'text-trading-bear')}>
                      {(mwa.dii_net ?? 0) >= 0 ? '+' : ''}{(mwa.dii_net ?? 0).toFixed(0)} Cr
                    </span>
                  </div>
                </div>
              </div>

              {/* Promoted Stocks */}
              {mwa.promoted_stocks && mwa.promoted_stocks.length > 0 && (
                <div className="pt-3 border-t border-trading-border/20">
                  <h4 className="stat-label mb-2">Promoted Stocks</h4>
                  <div className="flex flex-wrap gap-1.5">
                    {mwa.promoted_stocks.map((stock) => (
                      <span
                        key={stock}
                        className="px-2 py-0.5 text-[10px] font-mono bg-trading-ai/6 text-trading-ai-light border border-trading-ai/12 rounded-lg"
                      >
                        {stock}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </GlassCard>

          {/* Scanner Heatmap */}
          <GlassCard className="lg:col-span-2">
            <div className="flex items-center justify-between mb-4">
              <h3 className="stat-label">{scannerEntries.length}-Scanner Heatmap</h3>
              <span className="text-[9px] text-slate-600 font-mono">{scannerLayers.length} layers</span>
            </div>
            {scannerEntries.length > 0 ? (
              <div className="space-y-3 max-h-[500px] overflow-y-auto pr-1">
                {scannerLayers.map(([layer, scanners]) => (
                  <div key={layer}>
                    <p className="text-[9px] text-slate-600 uppercase tracking-[0.12em] mb-1.5 flex items-center gap-1.5">
                      <span className={cn('w-1.5 h-1.5 rounded-full', layerColors[layer] || 'bg-slate-600')} />
                      {layer}
                      <span className="text-slate-600">({scanners.length})</span>
                    </p>
                    <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-5 gap-1.5">
                      {scanners.map((scanner) => (
                        <ScannerCell key={scanner.name} scanner={scanner} />
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-slate-600 text-xs text-center py-8">No scanner data available</p>
            )}
          </GlassCard>
        </div>
      ) : (
        <GlassCard className="text-center py-14">
          <div className="w-12 h-12 rounded-2xl bg-slate-800/50 flex items-center justify-center mx-auto mb-3">
            <Compass size={24} className="text-slate-600" />
          </div>
          <p className="text-slate-500 text-xs mb-4">No MWA data. Run the scanner to see market breadth.</p>
          <button
            onClick={handleRunMwaScan}
            disabled={scanning}
            className={cn(
              'inline-flex items-center gap-2 px-6 py-2.5 rounded-xl text-xs font-semibold transition-all',
              scanning
                ? 'bg-trading-bg-secondary text-slate-500 cursor-not-allowed'
                : 'bg-trading-ai/12 text-trading-ai-light hover:bg-trading-ai/18 border border-trading-ai/25'
            )}
          >
            {scanning ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
            {scanning ? 'Running...' : 'Run MWA Scan'}
          </button>
          {scanError && <p className="text-[10px] text-trading-bear mt-2">{scanError}</p>}
        </GlassCard>
      )}

      {/* Sector Strength */}
      {sectorEntries.length > 0 && (
        <GlassCard>
          <h3 className="stat-label mb-4">Sector Strength</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            {sectorEntries.map(([sector, strength]) => (
              <SectorBadge key={sector} sector={sector} strength={strength as SectorStrength} />
            ))}
          </div>
        </GlassCard>
      )}

      {/* MWA Signal Cards */}
      {mwaSignals.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-4">
            <h3 className="stat-label flex items-center gap-2">
              <Zap size={12} className="text-trading-ai" />
              MWA Signal Cards
            </h3>
            <a href="/monitor" className="text-[9px] text-trading-ai hover:text-trading-ai-light transition-colors">View Monitor</a>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-3">
            {mwaSignals.map((signal) => (
              <SignalCard key={signal.id} signal={signal} />
            ))}
          </div>
        </div>
      )}

      {/* News */}
      <NewsWidget />

      {/* Today's Signals */}
      {(() => {
        const mwaIds = new Set(mwaSignals.map((s) => s.id));
        const otherSignals = signals.filter((s) => !mwaIds.has(s.id));
        return otherSignals.length > 0 ? (
          <div>
            <h3 className="stat-label mb-4">Today's Signals</h3>
            <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-3">
              {otherSignals.map((signal) => (
                <SignalCard key={signal.id} signal={signal} />
              ))}
            </div>
          </div>
        ) : mwaSignals.length === 0 ? (
          <div>
            <h3 className="stat-label mb-4">Today's Signals</h3>
            <GlassCard className="text-center py-14">
              <div className="w-12 h-12 rounded-2xl bg-slate-800/50 flex items-center justify-center mx-auto mb-3">
                <Zap size={24} className="text-slate-600" />
              </div>
              <p className="text-slate-600 text-xs">No signals generated yet today</p>
            </GlassCard>
          </div>
        ) : null;
      })()}

      <p className="sebi-disclaimer mt-4">
        This platform provides AI-powered market analytics and decision support tools for educational purposes only.
        Not SEBI-registered investment advice. Past performance is not indicative of future results.
        Consult a SEBI-registered financial advisor before making investment decisions.
      </p>
    </motion.div>
  );
}
