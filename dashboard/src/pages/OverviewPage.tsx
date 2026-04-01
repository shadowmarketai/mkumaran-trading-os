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
interface ScannerCellProps {
  scanner: ScannerResult;
}

function ScannerCell({ scanner }: ScannerCellProps) {
  const colorMap: Record<string, string> = {
    BULL: 'bg-trading-bull/20 text-trading-bull border-trading-bull/20',
    BEAR: 'bg-trading-bear/20 text-trading-bear border-trading-bear/20',
    NEUTRAL: 'bg-slate-700/50 text-slate-400 border-slate-600/30',
  };

  return (
    <div
      className={`p-2 rounded-lg border text-center ${colorMap[scanner.direction]}`}
      title={`${scanner.name}: ${scanner.count} stocks`}
    >
      <p className="text-[10px] font-medium truncate">{scanner.name}</p>
      <p className="text-lg font-mono font-bold">{scanner.count}</p>
      <p className="text-[9px] opacity-70">{scanner.group}</p>
    </div>
  );
}

// --- Score Bar ---
interface ScoreBarProps {
  bullPct: number;
  bearPct: number;
}

function ScoreBar({ bullPct, bearPct }: ScoreBarProps) {
  return (
    <div className="space-y-2">
      <div className="flex justify-between text-xs font-mono">
        <span className="text-trading-bull flex items-center gap-1">
          <ArrowUpRight size={12} /> BULL {(bullPct ?? 0).toFixed(1)}%
        </span>
        <span className="text-trading-bear flex items-center gap-1">
          BEAR {(bearPct ?? 0).toFixed(1)}% <ArrowDownRight size={12} />
        </span>
      </div>
      <div className="h-3 bg-slate-700 rounded-full overflow-hidden flex">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${bullPct}%` }}
          transition={{ duration: 1, ease: 'easeOut' }}
          className="h-full bg-gradient-to-r from-trading-bull to-trading-bull-light"
        />
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${bearPct}%` }}
          transition={{ duration: 1, ease: 'easeOut', delay: 0.2 }}
          className="h-full bg-gradient-to-r from-trading-bear-dark to-trading-bear"
        />
      </div>
    </div>
  );
}

// --- Sector Badge ---
interface SectorBadgeProps {
  sector: string;
  strength: SectorStrength;
}

function SectorBadge({ sector, strength }: SectorBadgeProps) {
  return (
    <div className="flex items-center justify-between px-3 py-2 bg-slate-800/50 rounded-lg">
      <span className="text-sm text-slate-300">{sector}</span>
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
};

function groupByLayer(scanners: ScannerResult[]): [string, ScannerResult[]][] {
  const groups: Record<string, ScannerResult[]> = {};
  for (const s of scanners) {
    const layer = s.group || 'Other';
    if (!groups[layer]) groups[layer] = [];
    groups[layer].push(s);
  }
  // Sort layers in a logical order
  const order = ['Trend', 'Volume', 'Breakout', 'RSI', 'Gap', 'MA', 'Filter', 'SMC', 'Wyckoff', 'VSA', 'Harmonic', 'RL', 'Forex', 'Commodity'];
  const entries = Object.entries(groups);
  entries.sort((a, b) => {
    const ia = order.indexOf(a[0]);
    const ib = order.indexOf(b[0]);
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
  });
  return entries;
}

// --- News Widget (compact) ---
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
          <Newspaper size={16} className="text-trading-ai" />
          <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider">
            Market News
          </h3>
          {highItems.length > 0 && (
            <span className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-trading-bear/15 text-trading-bear text-[10px] font-mono font-bold">
              <AlertTriangle size={10} />
              {highItems.length} HIGH
            </span>
          )}
        </div>
        <a href="/news" className="text-[10px] text-trading-ai hover:underline">
          View all
        </a>
      </div>
      <div className="space-y-1.5">
        {displayItems.map((item, idx) => (
          <div
            key={item.url || `${item.title}-${idx}`}
            className={cn(
              'flex items-center gap-2 px-2.5 py-1.5 rounded-lg hover:bg-slate-800/40 transition-colors',
              item.impact === 'HIGH' ? 'bg-trading-bear/5' : 'bg-transparent',
            )}
          >
            <span
              className={cn(
                'w-1.5 h-1.5 rounded-full flex-shrink-0',
                item.impact === 'HIGH' ? 'bg-trading-bear' : 'bg-trading-alert',
              )}
            />
            <span className="text-xs text-slate-300 truncate flex-1">{item.title}</span>
            <span className="text-[9px] text-slate-600 font-mono flex-shrink-0">{item.source}</span>
            {item.url && (
              <a href={item.url} target="_blank" rel="noopener noreferrer" className="flex-shrink-0">
                <ExternalLink size={10} className="text-slate-600 hover:text-slate-400" />
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
      // Refresh MWA data and signal cards after scan
      refreshMwa();
      if (result.mwa_signal_cards) {
        // Reload signal cards from DB
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
    // Fetch MWA signal cards (recent MWA Scan signals from DB)
    mwaApi.getSignalCards().then((data) => {
      if (Array.isArray(data)) setMwaSignals(data);
    }).catch(() => {});
  }, [filter]);

  const loading = mwaLoading || signalsLoading;

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <Loader2 size={48} className="text-trading-ai animate-spin mb-4" />
        <p className="text-slate-400 text-sm">Loading market data...</p>
      </div>
    );
  }

  if (mwaError) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <AlertCircle size={48} className="text-trading-alert mb-4" />
        <p className="text-slate-400 text-sm">Failed to load data: {mwaError}</p>
      </div>
    );
  }

  // Filter scanners by segment
  const allScannerEntries = mwa?.scanner_results ? Object.values(mwa.scanner_results) : [];
  const segmentLayerMap: Record<string, string[]> = {
    NSE: ['Trend', 'Volume', 'Breakout', 'RSI', 'Gap', 'MA', 'Filter', 'SMC', 'Wyckoff', 'VSA', 'Harmonic', 'RL'],
    MCX: ['Commodity'],
    CDS: ['Forex'],
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
      transition={{ duration: 0.4 }}
      className="space-y-6"
    >
      {/* Top Metric Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          title="Today's Signals"
          value={stats.today_signals || signals.length}
          icon={Zap}
          color="ai"
        />
        <MetricCard
          title="Active Trades"
          value={stats.active_trades}
          icon={TrendingUp}
          color="bull"
        />
        <MetricCard
          title="Win Rate"
          value={stats.win_rate > 0 ? `${stats.win_rate}%` : '--'}
          icon={Target}
          color="info"
        />
        <MetricCard
          title="MWA Direction"
          value={mwa?.direction?.replace('_', ' ') || 'N/A'}
          icon={Compass}
          color="alert"
        />
      </div>

      {/* MWA Score + Scanner Grid */}
      {mwa ? (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* MWA Score Section */}
          <GlassCard className="lg:col-span-1">
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider">
                  Market Weighted Average
                </h3>
                <StatusBadge status={mwa.direction} />
              </div>

              {/* Run MWA Scan Button */}
              <button
                onClick={handleRunMwaScan}
                disabled={scanning}
                className={cn(
                  'w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-all',
                  scanning
                    ? 'bg-slate-700 text-slate-400 cursor-not-allowed'
                    : 'bg-trading-ai/20 text-trading-ai-light hover:bg-trading-ai/30 border border-trading-ai/30'
                )}
              >
                {scanning ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <RefreshCw size={14} />
                )}
                {scanning ? 'Running MWA Scan...' : 'Run MWA Scan'}
              </button>
              {scanError && (
                <p className="text-xs text-trading-bear mt-1">{scanError}</p>
              )}

              <ScoreBar bullPct={mwa.bull_pct} bearPct={mwa.bear_pct} />

              <div className="grid grid-cols-2 gap-3">
                <div className="text-center p-3 rounded-lg bg-trading-bull/5 border border-trading-bull/10">
                  <p className="text-2xl font-mono font-bold text-trading-bull">{mwa.bull_score}</p>
                  <p className="text-[10px] text-slate-500 uppercase mt-1">Bull Score</p>
                </div>
                <div className="text-center p-3 rounded-lg bg-trading-bear/5 border border-trading-bear/10">
                  <p className="text-2xl font-mono font-bold text-trading-bear">{mwa.bear_score}</p>
                  <p className="text-[10px] text-slate-500 uppercase mt-1">Bear Score</p>
                </div>
              </div>

              {/* FII / DII */}
              <div className="pt-2 border-t border-trading-border space-y-2">
                <h4 className="text-xs text-slate-500 uppercase tracking-wider">Institutional Flow</h4>
                <div className="grid grid-cols-2 gap-3">
                  <div className="flex items-center justify-between p-2 rounded-lg bg-slate-800/50">
                    <span className="text-xs text-slate-400">FII</span>
                    <span className={`text-sm font-mono font-bold ${(mwa.fii_net ?? 0) >= 0 ? 'text-trading-bull' : 'text-trading-bear'}`}>
                      {(mwa.fii_net ?? 0) >= 0 ? '+' : ''}{(mwa.fii_net ?? 0).toFixed(0)} Cr
                    </span>
                  </div>
                  <div className="flex items-center justify-between p-2 rounded-lg bg-slate-800/50">
                    <span className="text-xs text-slate-400">DII</span>
                    <span className={`text-sm font-mono font-bold ${(mwa.dii_net ?? 0) >= 0 ? 'text-trading-bull' : 'text-trading-bear'}`}>
                      {(mwa.dii_net ?? 0) >= 0 ? '+' : ''}{(mwa.dii_net ?? 0).toFixed(0)} Cr
                    </span>
                  </div>
                </div>
              </div>

              {/* Promoted Stocks */}
              {mwa.promoted_stocks && mwa.promoted_stocks.length > 0 && (
                <div className="pt-2 border-t border-trading-border">
                  <h4 className="text-xs text-slate-500 uppercase tracking-wider mb-2">Promoted Stocks</h4>
                  <div className="flex flex-wrap gap-1.5">
                    {mwa.promoted_stocks.map((stock) => (
                      <span
                        key={stock}
                        className="px-2 py-0.5 text-xs font-mono bg-trading-ai/10 text-trading-ai-light border border-trading-ai/20 rounded"
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
              <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider">
                {scannerEntries.length}-Scanner Heatmap
              </h3>
              <span className="text-[10px] text-slate-500 font-mono">
                {scannerLayers.length} layers
              </span>
            </div>
            {scannerEntries.length > 0 ? (
              <div className="space-y-3 max-h-[500px] overflow-y-auto pr-1">
                {scannerLayers.map(([layer, scanners]) => (
                  <div key={layer}>
                    <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1.5 flex items-center gap-1.5">
                      <span className={`w-1.5 h-1.5 rounded-full ${layerColors[layer] || 'bg-slate-500'}`} />
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
              <p className="text-slate-500 text-sm text-center py-8">No scanner data available</p>
            )}
          </GlassCard>
        </div>
      ) : (
        <GlassCard className="text-center py-12">
          <Compass size={32} className="mx-auto mb-2 text-slate-600" />
          <p className="text-slate-500 text-sm mb-4">No MWA data available yet. Run the MWA scanner to see market breadth.</p>
          <button
            onClick={handleRunMwaScan}
            disabled={scanning}
            className={cn(
              'inline-flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm font-medium transition-all',
              scanning
                ? 'bg-slate-700 text-slate-400 cursor-not-allowed'
                : 'bg-trading-ai/20 text-trading-ai-light hover:bg-trading-ai/30 border border-trading-ai/30'
            )}
          >
            {scanning ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <RefreshCw size={14} />
            )}
            {scanning ? 'Running MWA Scan...' : 'Run MWA Scan'}
          </button>
          {scanError && (
            <p className="text-xs text-trading-bear mt-2">{scanError}</p>
          )}
        </GlassCard>
      )}

      {/* Sector Strength */}
      {sectorEntries.length > 0 && (
        <GlassCard>
          <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-4">
            Sector Strength
          </h3>
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
            <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider flex items-center gap-2">
              <Zap size={14} className="text-trading-ai" />
              MWA Signal Cards
            </h3>
            <a href="/monitor" className="text-[10px] text-trading-ai hover:underline">
              View Monitor
            </a>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
            {mwaSignals.map((signal) => (
              <SignalCard key={signal.id} signal={signal} />
            ))}
          </div>
        </div>
      )}

      {/* News Ticker */}
      <NewsWidget />

      {/* Today's Signals */}
      <div>
        <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-4">
          Today's Signals
        </h3>
        {signals.length > 0 ? (
          <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
            {signals.map((signal) => (
              <SignalCard key={signal.id} signal={signal} />
            ))}
          </div>
        ) : (
          <GlassCard className="text-center py-12">
            <Zap size={32} className="mx-auto mb-2 text-slate-600" />
            <p className="text-slate-500 text-sm">No signals generated yet today</p>
          </GlassCard>
        )}
      </div>
    </motion.div>
  );
}
