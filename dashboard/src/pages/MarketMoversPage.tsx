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
  { key: 'gainers', label: 'Top Gainers', icon: <TrendingUp size={14} />, color: 'text-trading-bull' },
  { key: 'losers', label: 'Top Losers', icon: <TrendingDown size={14} />, color: 'text-trading-bear' },
  { key: 'week52_high', label: '52W High', icon: <Star size={14} />, color: 'text-trading-gold' },
  { key: 'week52_low', label: '52W Low', icon: <ArrowDownRight size={14} />, color: 'text-trading-alert' },
  { key: 'most_active', label: 'Most Active', icon: <BarChart3 size={14} />, color: 'text-trading-info' },
];

const EXCHANGES = ['ALL', 'NSE', 'MCX', 'CDS'];

const EXCHANGE_COLORS: Record<string, string> = {
  NSE: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
  NFO: 'bg-purple-500/15 text-purple-400 border-purple-500/30',
  MCX: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
  CDS: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
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
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: rank * 0.02 }}
      className="border-b border-trading-border/50 hover:bg-slate-800/30 transition-colors"
    >
      <td className="py-2.5 px-2 md:px-3 font-mono text-xs text-slate-500">{rank}</td>
      <td className="py-2.5 px-2 md:px-3">
        <div className="flex items-center gap-2">
          <span className="font-medium text-white text-sm">{stock.ticker}</span>
          <span
            className={cn(
              'px-1.5 py-0.5 rounded text-[9px] font-mono font-bold border',
              EXCHANGE_COLORS[stock.exchange] || 'bg-slate-700/50 text-slate-400 border-slate-600/30',
            )}
          >
            {stock.exchange}
          </span>
        </div>
      </td>
      <td className="py-2.5 px-2 md:px-3 text-right font-mono text-sm text-white">
        {stock.ltp.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
      </td>
      <td className="py-2.5 px-2 md:px-3 text-right">
        <span
          className={cn(
            'font-mono text-xs',
            positive ? 'text-trading-bull' : 'text-trading-bear',
          )}
        >
          {positive ? '+' : ''}{stock.change.toFixed(2)}
        </span>
      </td>
      <td className="py-2.5 px-2 md:px-3 text-right">
        <span
          className={cn(
            'inline-flex items-center gap-0.5 px-2 py-0.5 rounded font-mono text-xs font-bold',
            positive
              ? 'bg-trading-bull/10 text-trading-bull'
              : 'bg-trading-bear/10 text-trading-bear',
          )}
        >
          {positive ? <ArrowUpRight size={10} /> : <ArrowDownRight size={10} />}
          {positive ? '+' : ''}{stock.pct_change.toFixed(2)}%
        </span>
      </td>
      <td className="py-2.5 px-2 md:px-3 text-right font-mono text-xs text-slate-400 hidden md:table-cell">
        {stock.open.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
      </td>
      <td className="py-2.5 px-2 md:px-3 text-right font-mono text-xs text-slate-400 hidden md:table-cell">
        {stock.high.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
      </td>
      <td className="py-2.5 px-2 md:px-3 text-right font-mono text-xs text-slate-400 hidden md:table-cell">
        {stock.low.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
      </td>
      <td className="py-2.5 px-2 md:px-3 text-right font-mono text-xs text-slate-400">
        {showVolume ? (
          <span className="text-trading-info font-bold">{formatVolume(stock.volume)}</span>
        ) : (
          formatVolume(stock.volume)
        )}
      </td>
    </motion.tr>
  );
}

export default function MarketMoversPage() {
  const {
    data, loading, error, category, setCategory, exchange, setExchange, refresh,
  } = useMarketMovers();

  const stocks = data?.stocks || [];
  const activeTab = TABS.find((t) => t.key === category) || TABS[0];

  if (loading && !data) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <Loader2 size={48} className="text-trading-ai animate-spin mb-4" />
        <p className="text-slate-400 text-sm">Loading market movers...</p>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <AlertCircle size={48} className="text-trading-alert mb-4" />
        <p className="text-slate-400 text-sm">Failed to load: {error}</p>
        <button onClick={refresh} className="mt-4 text-trading-ai text-sm hover:underline">
          Retry
        </button>
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.4 }}
      className="space-y-4"
    >
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <BarChart3 size={20} className="text-trading-ai" />
          <h2 className="text-lg font-semibold text-white">Market Movers</h2>
          {data?.fetched_at && (
            <span className="flex items-center gap-1 text-[10px] text-slate-500 font-mono">
              <Clock size={10} />
              {formatTime(data.fetched_at)}
            </span>
          )}
        </div>
        <button
          onClick={refresh}
          disabled={loading}
          className={cn(
            'flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-medium transition-all',
            loading
              ? 'bg-trading-ai/20 text-trading-ai-light cursor-wait'
              : 'bg-trading-ai/10 text-trading-ai hover:bg-trading-ai/20 border border-trading-ai/30',
          )}
        >
          {loading ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <RefreshCw size={14} />
          )}
          Refresh
        </button>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {TABS.map((tab) => {
          const isActive = category === tab.key;
          return (
            <button
              key={tab.key}
              onClick={() => setCategory(tab.key)}
              className={cn(
                'glass-card !p-3 text-center transition-all cursor-pointer border',
                isActive
                  ? 'border-trading-ai/40 bg-trading-ai/5'
                  : 'border-transparent hover:border-trading-border',
              )}
            >
              <div className={cn('flex items-center justify-center gap-1.5 mb-1', tab.color)}>
                {tab.icon}
                <span className="text-[10px] uppercase tracking-wider font-medium">{tab.label}</span>
              </div>
              {isActive && (
                <p className="text-lg font-mono font-bold text-white">{stocks.length}</p>
              )}
            </button>
          );
        })}
      </div>

      {/* Exchange filter */}
      <div className="flex items-center gap-2">
        <span className="text-[10px] text-slate-500 uppercase tracking-wider">Exchange:</span>
        {EXCHANGES.map((ex) => (
          <button
            key={ex}
            onClick={() => setExchange(ex)}
            className={cn(
              'px-2.5 py-1 rounded-md text-xs font-mono transition-colors',
              exchange === ex
                ? 'bg-trading-card text-white border border-trading-ai/30'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-700/50',
            )}
          >
            {ex}
          </button>
        ))}
        {data?.total_universe && (
          <span className="ml-auto text-[10px] text-slate-600 font-mono">
            Universe: {data.total_universe} stocks
          </span>
        )}
      </div>

      {/* Table */}
      {stocks.length > 0 ? (
        <GlassCard className="!p-0 overflow-hidden">
          <div className={cn('px-4 py-3 border-b border-trading-border flex items-center gap-2', activeTab.color)}>
            {activeTab.icon}
            <span className="text-sm font-medium text-white">{activeTab.label}</span>
            <span className="text-xs text-slate-500 font-mono ml-1">({stocks.length})</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[10px] uppercase tracking-wider text-slate-500 border-b border-trading-border">
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
                    <StockRow
                      key={`${stock.ticker}-${stock.exchange}`}
                      stock={stock}
                      rank={i + 1}
                      category={category}
                    />
                  ))}
                </AnimatePresence>
              </tbody>
            </table>
          </div>
        </GlassCard>
      ) : (
        <GlassCard className="text-center py-12">
          <BarChart3 size={32} className="mx-auto mb-3 text-slate-600" />
          <p className="text-slate-400 text-sm mb-1">No data available</p>
          <p className="text-slate-500 text-xs">
            Click Refresh to fetch latest market movers data.
          </p>
        </GlassCard>
      )}

      {/* Error display */}
      {error && data && (
        <div className="flex items-center gap-2 px-4 py-2 rounded-lg bg-trading-bear/10 border border-trading-bear/20">
          <AlertCircle size={14} className="text-trading-bear" />
          <span className="text-xs text-trading-bear">{error}</span>
        </div>
      )}

      {/* Footer */}
      <p className="text-center text-[10px] text-slate-600">
        Data refreshes every 5 minutes during market hours | Source: yfinance | All segments: NSE, MCX, CDS
      </p>
    </motion.div>
  );
}
