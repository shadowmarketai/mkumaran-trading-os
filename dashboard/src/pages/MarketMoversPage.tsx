import { motion, AnimatePresence } from 'framer-motion';
import {
  TrendingUp,
  TrendingDown,
  BarChart3,
  ArrowUpRight,
  ArrowDownRight,
  Loader2,
  AlertCircle,
  RefreshCw,
  Clock,
  Star,
} from 'lucide-react';
import GlassCard from '../components/ui/GlassCard';
import { cn } from '../lib/utils';
import { useMarketMovers } from '../hooks/useMarketMovers';
import type { MarketMoverStock, MarketMoverCategory } from '../types';

const TABS: { key: MarketMoverCategory; label: string; icon: React.ReactNode; color: string }[] = [
  { key: 'gainers', label: 'Top Gainers', icon: <TrendingUp size={13} />, color: 'text-trading-bull' },
  { key: 'losers', label: 'Top Losers', icon: <TrendingDown size={13} />, color: 'text-trading-bear' },
  { key: 'week52_high', label: '52W High', icon: <Star size={13} />, color: 'text-trading-gold' },
  { key: 'week52_low', label: '52W Low', icon: <ArrowDownRight size={13} />, color: 'text-trading-alert' },
  { key: 'most_active', label: 'Most Active', icon: <BarChart3 size={13} />, color: 'text-trading-info' },
];

const EXCHANGES = ['ALL', 'NSE', 'MCX', 'CDS'];

const EXCHANGE_COLORS: Record<string, string> = {
  NSE: 'bg-blue-500/8 text-blue-400 border-blue-500/15',
  NFO: 'bg-purple-500/8 text-purple-400 border-purple-500/15',
  MCX: 'bg-amber-500/8 text-amber-400 border-amber-500/15',
  CDS: 'bg-emerald-500/8 text-emerald-400 border-emerald-500/15',
};

function formatVolume(vol: number): string {
  if (vol >= 10000000) return `${(vol / 10000000).toFixed(2)}Cr`;
  if (vol >= 100000) return `${(vol / 100000).toFixed(2)}L`;
  if (vol >= 1000) return `${(vol / 1000).toFixed(1)}K`;
  return vol.toString();
}

function formatTime(dateStr: string | null): string {
  if (!dateStr) return '';
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return '';
    const now = new Date();
    const diffMs = now.getTime() - d.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHrs = Math.floor(diffMins / 60);
    if (diffHrs < 24) return `${diffHrs}h ago`;
    return `${Math.floor(diffHrs / 24)}d ago`;
  } catch {
    return '';
  }
}

function StockRow({ stock, rank, category }: { stock: MarketMoverStock; rank: number; category: MarketMoverCategory }) {
  const positive = stock.pct_change >= 0;
  const showVolume = category === 'most_active';

  return (
    <motion.tr
      initial={{ opacity: 0, x: -6 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: rank * 0.015, ease: [0.16, 1, 0.3, 1] }}
      className="border-b border-slate-200 hover:bg-slate-50 transition-colors"
    >
      <td className="py-2.5 px-2 md:px-3 font-mono text-[10px] text-slate-400 tabular-nums">{rank}</td>
      <td className="py-2.5 px-2 md:px-3">
        <div className="flex items-center gap-2">
          <span className="font-medium text-slate-900 text-sm">{stock.ticker}</span>
          <span className={cn(
            'px-1.5 py-0.5 rounded-md text-[8px] font-mono font-bold border',
            EXCHANGE_COLORS[stock.exchange] || 'bg-slate-100 text-slate-500 border-slate-200',
          )}>
            {stock.exchange}
          </span>
        </div>
      </td>
      <td className="py-2.5 px-2 md:px-3 text-right font-mono text-xs text-slate-900 tabular-nums">
        {stock.ltp.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
      </td>
      <td className="py-2.5 px-2 md:px-3 text-right">
        <span className={cn('font-mono text-[10px] tabular-nums', positive ? 'text-trading-bull' : 'text-trading-bear')}>
          {positive ? '+' : ''}{stock.change.toFixed(2)}
        </span>
      </td>
      <td className="py-2.5 px-2 md:px-3 text-right">
        <span className={cn(
          'inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-md font-mono text-[10px] font-bold tabular-nums',
          positive ? 'bg-trading-bull/6 text-trading-bull' : 'bg-trading-bear/6 text-trading-bear',
        )}>
          {positive ? <ArrowUpRight size={9} /> : <ArrowDownRight size={9} />}
          {positive ? '+' : ''}{stock.pct_change.toFixed(2)}%
        </span>
      </td>
      <td className="py-2.5 px-2 md:px-3 text-right font-mono text-[10px] text-slate-500 tabular-nums hidden md:table-cell">
        {stock.open.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
      </td>
      <td className="py-2.5 px-2 md:px-3 text-right font-mono text-[10px] text-slate-500 tabular-nums hidden md:table-cell">
        {stock.high.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
      </td>
      <td className="py-2.5 px-2 md:px-3 text-right font-mono text-[10px] text-slate-500 tabular-nums hidden md:table-cell">
        {stock.low.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
      </td>
      <td className="py-2.5 px-2 md:px-3 text-right font-mono text-[10px] tabular-nums">
        {showVolume ? (
          <span className="text-trading-info font-bold">{formatVolume(stock.volume)}</span>
        ) : (
          <span className="text-slate-500">{formatVolume(stock.volume)}</span>
        )}
      </td>
    </motion.tr>
  );
}

export default function MarketMoversPage() {
  const { data, loading, error, category, setCategory, exchange, setExchange, refresh } = useMarketMovers();

  const stocks = data?.stocks || [];
  const activeTab = TABS.find((t) => t.key === category) || TABS[0];

  if (loading && !data) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <div className="w-12 h-12 rounded-2xl bg-violet-50 text-trading-ai flex items-center justify-center">
          <Loader2 size={24} className="text-trading-ai animate-spin" />
        </div>
        <p className="text-slate-500 text-xs mt-4 font-mono">Loading market movers...</p>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <div className="w-12 h-12 rounded-2xl bg-amber-50 flex items-center justify-center mb-4">
          <AlertCircle size={24} className="text-trading-alert" />
        </div>
        <p className="text-slate-500 text-xs">{error}</p>
        <button onClick={refresh} className="mt-4 text-trading-ai text-xs hover:text-trading-ai-light transition-colors">Retry</button>
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      className="space-y-4"
    >
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-xl bg-violet-50 flex items-center justify-center">
            <BarChart3 size={16} className="text-trading-ai" />
          </div>
          <h2 className="text-sm font-bold text-slate-900">Market Movers</h2>
          {data?.fetched_at && (
            <span className="flex items-center gap-1 text-[9px] text-slate-400 font-mono">
              <Clock size={9} /> {formatTime(data.fetched_at)}
            </span>
          )}
        </div>
        <button
          onClick={refresh}
          disabled={loading}
          className={cn(
            'flex items-center gap-1.5 px-4 py-1.5 rounded-xl text-xs font-semibold transition-all',
            loading
              ? 'bg-violet-50 text-trading-ai-light cursor-wait'
              : 'bg-violet-50 text-trading-ai-light hover:bg-trading-ai/18 border border-violet-200',
          )}
        >
          {loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
          Refresh
        </button>
      </div>

      {/* Category Tabs */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
        {TABS.map((tab) => {
          const isActive = category === tab.key;
          return (
            <button
              key={tab.key}
              onClick={() => setCategory(tab.key)}
              className={cn(
                'glass-card !p-3 text-center transition-all cursor-pointer border',
                isActive
                  ? 'border-trading-ai/25 bg-trading-ai/[0.04]'
                  : 'border-transparent hover:border-slate-200',
              )}
            >
              <div className={cn('flex items-center justify-center gap-1.5 mb-1', tab.color)}>
                {tab.icon}
                <span className="text-[9px] uppercase tracking-[0.1em] font-semibold">{tab.label}</span>
              </div>
              {isActive && (
                <p className="text-lg font-mono font-bold text-slate-900 tabular-nums">{stocks.length}</p>
              )}
            </button>
          );
        })}
      </div>

      {/* Exchange filter */}
      <div className="flex items-center gap-2">
        <span className="text-[9px] text-slate-400 uppercase tracking-[0.12em]">Exchange:</span>
        {EXCHANGES.map((ex) => (
          <button
            key={ex}
            onClick={() => setExchange(ex)}
            className={cn(
              'px-2.5 py-1 rounded-lg text-[10px] font-mono transition-all',
              exchange === ex
                ? 'bg-white text-slate-900 border border-trading-ai/20'
                : 'text-slate-600 hover:text-slate-900 hover:bg-slate-50',
            )}
          >
            {ex}
          </button>
        ))}
        {data?.total_universe && (
          <span className="ml-auto text-[9px] text-slate-400 font-mono tabular-nums">
            Universe: {data.total_universe}
          </span>
        )}
      </div>

      {/* Table */}
      {stocks.length > 0 ? (
        <GlassCard className="!p-0 overflow-hidden">
          <div className={cn('px-4 py-3 border-b border-slate-200 flex items-center gap-2', activeTab.color)}>
            {activeTab.icon}
            <span className="text-sm font-medium text-slate-900">{activeTab.label}</span>
            <span className="text-[10px] text-slate-400 font-mono ml-1 tabular-nums">({stocks.length})</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[9px] uppercase tracking-[0.12em] text-slate-500 border-b border-slate-200">
                  <th className="py-2.5 px-2 md:px-3 text-left w-10">#</th>
                  <th className="py-2.5 px-2 md:px-3 text-left">Stock</th>
                  <th className="py-2.5 px-2 md:px-3 text-right">LTP</th>
                  <th className="py-2.5 px-2 md:px-3 text-right">Chg</th>
                  <th className="py-2.5 px-2 md:px-3 text-right">%Chg</th>
                  <th className="py-2.5 px-2 md:px-3 text-right hidden md:table-cell">Open</th>
                  <th className="py-2.5 px-2 md:px-3 text-right hidden md:table-cell">High</th>
                  <th className="py-2.5 px-2 md:px-3 text-right hidden md:table-cell">Low</th>
                  <th className="py-2.5 px-2 md:px-3 text-right">Volume</th>
                </tr>
              </thead>
              <tbody>
                <AnimatePresence>
                  {stocks.map((stock, i) => (
                    <StockRow key={`${stock.ticker}-${stock.exchange}`} stock={stock} rank={i + 1} category={category} />
                  ))}
                </AnimatePresence>
              </tbody>
            </table>
          </div>
        </GlassCard>
      ) : (
        <GlassCard className="text-center py-14">
          <div className="w-12 h-12 rounded-2xl bg-slate-100 flex items-center justify-center mx-auto mb-3">
            <BarChart3 size={24} className="text-slate-400" />
          </div>
          <p className="text-slate-500 text-xs mb-1">No data available</p>
          <p className="text-slate-500 text-[10px]">Click Refresh to fetch latest market movers.</p>
        </GlassCard>
      )}

      {error && data && (
        <div className="flex items-center gap-2 px-4 py-2 rounded-xl bg-trading-bear/6 border border-trading-bear/12">
          <AlertCircle size={12} className="text-trading-bear" />
          <span className="text-[10px] text-trading-bear">{error}</span>
        </div>
      )}

      <p className="text-center text-[9px] text-slate-400">
        Data refreshes every 5 minutes during market hours | Source: yfinance | All segments: NSE, MCX, CDS
      </p>
    </motion.div>
  );
}
