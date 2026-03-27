import { useState } from 'react';
import { motion } from 'framer-motion';
import {
  Cpu,
  Search,
  Loader2,
  AlertCircle,
  ArrowUpRight,
  ArrowDownRight,
  Shield,
  BarChart3,
  Waves,
  Hexagon,
} from 'lucide-react';
import GlassCard from '../components/ui/GlassCard';
import { cn } from '../lib/utils';
import { engineApi } from '../services/api';
import type { EngineDetectionResult, EnginePattern } from '../types';

interface EngineConfig {
  id: string;
  label: string;
  description: string;
  icon: React.ReactNode;
  color: string;
  bgColor: string;
  borderColor: string;
}

const ENGINES: EngineConfig[] = [
  {
    id: 'smc',
    label: 'SMC / ICT',
    description: 'BOS, CHoCH, Order Blocks, FVG, Liquidity Sweeps',
    icon: <Shield size={20} />,
    color: 'text-purple-400',
    bgColor: 'bg-purple-400/5',
    borderColor: 'border-purple-400/20',
  },
  {
    id: 'wyckoff',
    label: 'Wyckoff',
    description: 'Accumulation, Distribution, Spring, Upthrust, SOS/SOW',
    icon: <BarChart3 size={20} />,
    color: 'text-amber-400',
    bgColor: 'bg-amber-400/5',
    borderColor: 'border-amber-400/20',
  },
  {
    id: 'vsa',
    label: 'VSA',
    description: 'No Demand/Supply, Stopping Volume, Climax, Effort vs Result',
    icon: <Waves size={20} />,
    color: 'text-cyan-400',
    bgColor: 'bg-cyan-400/5',
    borderColor: 'border-cyan-400/20',
  },
  {
    id: 'harmonic',
    label: 'Harmonic',
    description: 'Gartley, Butterfly, Bat, Crab, Cypher patterns',
    icon: <Hexagon size={20} />,
    color: 'text-pink-400',
    bgColor: 'bg-pink-400/5',
    borderColor: 'border-pink-400/20',
  },
];

function PatternCard({ pattern }: { pattern: EnginePattern }) {
  const isBull = pattern.direction === 'BULLISH';
  const dirColor = isBull ? 'text-trading-bull' : 'text-trading-bear';
  const dirBg = isBull ? 'bg-trading-bull/5 border-trading-bull/10' : 'bg-trading-bear/5 border-trading-bear/10';

  return (
    <div className={cn('p-3 rounded-lg border', dirBg)}>
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-1.5">
          {isBull ? (
            <ArrowUpRight size={14} className="text-trading-bull" />
          ) : (
            <ArrowDownRight size={14} className="text-trading-bear" />
          )}
          <span className={cn('text-sm font-medium', dirColor)}>{pattern.name}</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-12 h-1.5 bg-slate-700 rounded-full overflow-hidden">
            <div
              className={cn('h-full rounded-full', isBull ? 'bg-trading-bull' : 'bg-trading-bear')}
              style={{ width: `${pattern.confidence * 100}%` }}
            />
          </div>
          <span className="text-[10px] font-mono text-slate-400">
            {(pattern.confidence * 100).toFixed(0)}%
          </span>
        </div>
      </div>
      <p className="text-xs text-slate-500 leading-relaxed">{pattern.description}</p>
    </div>
  );
}

function EngineResultCard({ engine, result }: { engine: EngineConfig; result: EngineDetectionResult | null }) {
  const bullPatterns = result?.patterns.filter((p) => p.direction === 'BULLISH') || [];
  const bearPatterns = result?.patterns.filter((p) => p.direction === 'BEARISH') || [];
  const totalPatterns = result?.patterns.length || 0;

  return (
    <GlassCard className={cn('border', engine.borderColor)}>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <span className={engine.color}>{engine.icon}</span>
          <div>
            <h4 className={cn('text-sm font-semibold', engine.color)}>{engine.label}</h4>
            <p className="text-[10px] text-slate-500">{engine.description}</p>
          </div>
        </div>
        {totalPatterns > 0 && (
          <span className={cn('text-xs font-mono px-2 py-0.5 rounded', engine.bgColor, engine.color)}>
            {totalPatterns} detected
          </span>
        )}
      </div>

      {totalPatterns === 0 ? (
        <p className="text-xs text-slate-600 text-center py-4">No patterns detected</p>
      ) : (
        <div className="space-y-4">
          {bullPatterns.length > 0 && (
            <div>
              <p className="text-[10px] text-trading-bull uppercase tracking-wider mb-1.5 flex items-center gap-1">
                <ArrowUpRight size={10} /> Bullish ({bullPatterns.length})
              </p>
              <div className="space-y-2">
                {bullPatterns.map((p, i) => (
                  <PatternCard key={i} pattern={p} />
                ))}
              </div>
            </div>
          )}
          {bearPatterns.length > 0 && (
            <div>
              <p className="text-[10px] text-trading-bear uppercase tracking-wider mb-1.5 flex items-center gap-1">
                <ArrowDownRight size={10} /> Bearish ({bearPatterns.length})
              </p>
              <div className="space-y-2">
                {bearPatterns.map((p, i) => (
                  <PatternCard key={i} pattern={p} />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </GlassCard>
  );
}

export default function EnginesPage() {
  const [ticker, setTicker] = useState('RELIANCE');
  const [days, setDays] = useState('60');
  const [results, setResults] = useState<Record<string, EngineDetectionResult>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleScan = async () => {
    if (!ticker.trim() || loading) return;
    setLoading(true);
    setError(null);
    setResults({});
    try {
      const data = await engineApi.detectAll(ticker.toUpperCase(), parseInt(days, 10) || 60);
      const mapped: Record<string, EngineDetectionResult> = {};
      for (const r of data) {
        mapped[r.engine] = r;
      }
      setResults(mapped);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Detection failed');
    } finally {
      setLoading(false);
    }
  };

  const totalDetected = Object.values(results).reduce((sum, r) => sum + r.patterns.length, 0);
  const bullTotal = Object.values(results).reduce(
    (sum, r) => sum + r.patterns.filter((p) => p.direction === 'BULLISH').length, 0
  );
  const bearTotal = Object.values(results).reduce(
    (sum, r) => sum + r.patterns.filter((p) => p.direction === 'BEARISH').length, 0
  );

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.4 }}
      className="space-y-6"
    >
      {/* Header */}
      <div>
        <h2 className="text-xl font-bold text-white flex items-center gap-2">
          <Cpu size={22} className="text-trading-ai" />
          Advanced Pattern Engines
        </h2>
        <p className="text-sm text-slate-400 mt-0.5">
          Detect SMC, Wyckoff, VSA, and Harmonic patterns on any stock
        </p>
      </div>

      {/* Search Bar */}
      <GlassCard glowColor="ai">
        <div className="flex items-end gap-4">
          <div className="flex-1">
            <label className="text-xs text-slate-500 uppercase tracking-wider block mb-1.5">
              Ticker
            </label>
            <input
              type="text"
              value={ticker}
              onChange={(e) => setTicker(e.target.value)}
              placeholder="e.g., RELIANCE"
              onKeyDown={(e) => e.key === 'Enter' && handleScan()}
              className="w-full bg-slate-800 border border-trading-border rounded-lg px-3 py-2.5 text-sm font-mono text-white placeholder-slate-600 focus:outline-none focus:border-trading-ai"
            />
          </div>
          <div className="w-28">
            <label className="text-xs text-slate-500 uppercase tracking-wider block mb-1.5">
              Lookback
            </label>
            <input
              type="number"
              value={days}
              onChange={(e) => setDays(e.target.value)}
              min="30"
              max="365"
              className="w-full bg-slate-800 border border-trading-border rounded-lg px-3 py-2.5 text-sm font-mono text-white focus:outline-none focus:border-trading-ai"
            />
          </div>
          <button
            onClick={handleScan}
            disabled={loading || !ticker.trim()}
            className={cn(
              'flex items-center justify-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium transition-all',
              loading ? 'bg-slate-700 text-slate-400 cursor-wait' : 'gradient-ai text-white hover:opacity-90'
            )}
          >
            {loading ? (
              <><Loader2 size={16} className="animate-spin" /> Scanning...</>
            ) : (
              <><Search size={16} /> Detect Patterns</>
            )}
          </button>
        </div>
      </GlassCard>

      {/* Error */}
      {error && (
        <GlassCard className="flex items-center gap-3 py-4">
          <AlertCircle size={20} className="text-trading-bear" />
          <p className="text-trading-bear text-sm">{error}</p>
        </GlassCard>
      )}

      {/* Summary Strip */}
      {totalDetected > 0 && (
        <div className="flex items-center gap-4 px-1">
          <span className="text-sm text-slate-400">
            <span className="font-mono font-bold text-white">{totalDetected}</span> patterns detected for{' '}
            <span className="font-mono font-bold text-white">{ticker.toUpperCase()}</span>
          </span>
          <span className="text-xs text-trading-bull font-mono">{bullTotal} bull</span>
          <span className="text-xs text-trading-bear font-mono">{bearTotal} bear</span>
        </div>
      )}

      {/* Engine Results Grid */}
      {Object.keys(results).length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {ENGINES.map((engine) => (
            <EngineResultCard
              key={engine.id}
              engine={engine}
              result={results[engine.id] || null}
            />
          ))}
        </div>
      )}

      {/* Empty State */}
      {Object.keys(results).length === 0 && !loading && !error && (
        <GlassCard className="flex flex-col items-center justify-center py-16">
          <Cpu size={48} className="text-slate-600 mb-4" />
          <p className="text-slate-500 text-sm">Enter a ticker and click "Detect Patterns" to scan with all 4 engines</p>
          <div className="flex items-center gap-3 mt-4">
            {ENGINES.map((e) => (
              <span key={e.id} className={cn('text-xs font-mono px-2 py-0.5 rounded border', e.bgColor, e.color, e.borderColor)}>
                {e.label}
              </span>
            ))}
          </div>
        </GlassCard>
      )}

      {/* Loading State */}
      {loading && (
        <GlassCard className="flex flex-col items-center justify-center py-16">
          <Loader2 size={48} className="text-trading-ai animate-spin mb-4" />
          <p className="text-slate-400 text-sm">Running 4 engines on {ticker.toUpperCase()}...</p>
          <p className="text-slate-600 text-xs mt-1">SMC + Wyckoff + VSA + Harmonic</p>
        </GlassCard>
      )}
    </motion.div>
  );
}
