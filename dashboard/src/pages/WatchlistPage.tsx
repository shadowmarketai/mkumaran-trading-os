import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Eye,
  EyeOff,
  Plus,
  Trash2,
  Search,
  Filter,
  X,
  Loader2,
  AlertCircle,
} from 'lucide-react';
import GlassCard from '../components/ui/GlassCard';
import StatusBadge from '../components/ui/StatusBadge';
import { cn } from '../lib/utils';
import { useWatchlist } from '../hooks/useWatchlist';

type TierFilter = 0 | 1 | 2 | 3;

interface AddFormData {
  ticker: string;
  timeframe: string;
  ltrp: string;
  pivot_high: string;
}

export default function WatchlistPage() {
  const [selectedTier, setSelectedTier] = useState<TierFilter>(0);
  const [searchQuery, setSearchQuery] = useState('');
  const [showAddForm, setShowAddForm] = useState(false);
  const [formData, setFormData] = useState<AddFormData>({
    ticker: '',
    timeframe: '1D',
    ltrp: '',
    pivot_high: '',
  });

  const { items: watchlist, loading, error, addItem, removeItem, toggleItem } = useWatchlist();

  const tiers: { label: string; value: TierFilter }[] = [
    { label: 'All', value: 0 },
    { label: 'Tier 1', value: 1 },
    { label: 'Tier 2', value: 2 },
    { label: 'Tier 3', value: 3 },
  ];

  const filteredItems = watchlist.filter((item) => {
    const matchesTier = selectedTier === 0 || item.tier === selectedTier;
    const matchesSearch =
      searchQuery === '' ||
      item.ticker.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (item.name && item.name.toLowerCase().includes(searchQuery.toLowerCase()));
    return matchesTier && matchesSearch;
  });

  const handleToggle = async (id: number) => {
    try {
      await toggleItem(id);
    } catch {
      // Error already handled in hook
    }
  };

  const handleRemove = async (id: number) => {
    try {
      await removeItem(id);
    } catch {
      // Error already handled in hook
    }
  };

  const handleAddSubmit = async () => {
    if (!formData.ticker.trim()) return;

    try {
      await addItem({
        ticker: formData.ticker.toUpperCase(),
        tier: 3,
        timeframe: formData.timeframe,
        ltrp: formData.ltrp ? parseFloat(formData.ltrp) : undefined,
        pivot_high: formData.pivot_high ? parseFloat(formData.pivot_high) : undefined,
      });
      setFormData({ ticker: '', timeframe: '1D', ltrp: '', pivot_high: '' });
      setShowAddForm(false);
    } catch {
      // Error already handled in hook
    }
  };

  const tierCounts = {
    0: watchlist.length,
    1: watchlist.filter((i) => i.tier === 1).length,
    2: watchlist.filter((i) => i.tier === 2).length,
    3: watchlist.filter((i) => i.tier === 3).length,
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <Loader2 size={48} className="text-trading-ai animate-spin mb-4" />
        <p className="text-slate-400 text-sm">Loading watchlist...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <AlertCircle size={48} className="text-trading-alert mb-4" />
        <p className="text-slate-400 text-sm">Failed to load watchlist: {error}</p>
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.4 }}
      className="space-y-6"
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-white">Watchlist</h2>
          <p className="text-sm text-slate-400 mt-0.5">{filteredItems.length} stocks tracked</p>
        </div>
        <button
          onClick={() => setShowAddForm(!showAddForm)}
          className={cn(
            'flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all',
            showAddForm
              ? 'bg-slate-700 text-slate-300'
              : 'gradient-ai text-white hover:opacity-90'
          )}
        >
          {showAddForm ? <X size={16} /> : <Plus size={16} />}
          {showAddForm ? 'Cancel' : 'Add Stock'}
        </button>
      </div>

      {/* Add Form */}
      <AnimatePresence>
        {showAddForm && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <GlassCard glowColor="ai">
              <div className="grid grid-cols-1 md:grid-cols-5 gap-4 items-end">
                <div>
                  <label className="text-xs text-slate-500 uppercase tracking-wider block mb-1.5">Ticker</label>
                  <input
                    type="text"
                    placeholder="e.g., RELIANCE"
                    value={formData.ticker}
                    onChange={(e) => setFormData({ ...formData, ticker: e.target.value })}
                    className="w-full bg-slate-800 border border-trading-border rounded-lg px-3 py-2 text-sm font-mono text-white placeholder-slate-600 focus:outline-none focus:border-trading-ai"
                  />
                </div>
                <div>
                  <label className="text-xs text-slate-500 uppercase tracking-wider block mb-1.5">Timeframe</label>
                  <select
                    value={formData.timeframe}
                    onChange={(e) => setFormData({ ...formData, timeframe: e.target.value })}
                    className="w-full bg-slate-800 border border-trading-border rounded-lg px-3 py-2 text-sm font-mono text-white focus:outline-none focus:border-trading-ai"
                  >
                    <option value="15m">15m</option>
                    <option value="1H">1H</option>
                    <option value="4H">4H</option>
                    <option value="1D">1D</option>
                    <option value="1W">1W</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs text-slate-500 uppercase tracking-wider block mb-1.5">LTRP</label>
                  <input
                    type="number"
                    placeholder="Optional"
                    value={formData.ltrp}
                    onChange={(e) => setFormData({ ...formData, ltrp: e.target.value })}
                    className="w-full bg-slate-800 border border-trading-border rounded-lg px-3 py-2 text-sm font-mono text-white placeholder-slate-600 focus:outline-none focus:border-trading-ai"
                  />
                </div>
                <div>
                  <label className="text-xs text-slate-500 uppercase tracking-wider block mb-1.5">Pivot High</label>
                  <input
                    type="number"
                    placeholder="Optional"
                    value={formData.pivot_high}
                    onChange={(e) => setFormData({ ...formData, pivot_high: e.target.value })}
                    className="w-full bg-slate-800 border border-trading-border rounded-lg px-3 py-2 text-sm font-mono text-white placeholder-slate-600 focus:outline-none focus:border-trading-ai"
                  />
                </div>
                <button
                  onClick={handleAddSubmit}
                  className="gradient-bull text-white px-4 py-2 rounded-lg text-sm font-medium hover:opacity-90 transition-opacity"
                >
                  Add to Watchlist
                </button>
              </div>
            </GlassCard>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Tier Tabs + Search */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div className="flex items-center gap-1 bg-slate-800/50 p-1 rounded-lg">
          {tiers.map((tier) => (
            <button
              key={tier.value}
              onClick={() => setSelectedTier(tier.value)}
              className={cn(
                'px-4 py-1.5 rounded-md text-sm font-medium transition-all',
                selectedTier === tier.value
                  ? 'bg-trading-card text-white shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              )}
            >
              {tier.label}
              <span className="ml-1.5 text-xs text-slate-500">({tierCounts[tier.value]})</span>
            </button>
          ))}
        </div>

        <div className="relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            type="text"
            placeholder="Search ticker or name..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="bg-slate-800 border border-trading-border rounded-lg pl-9 pr-3 py-2 text-sm text-white placeholder-slate-600 focus:outline-none focus:border-trading-ai w-64"
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
            >
              <X size={14} />
            </button>
          )}
        </div>
      </div>

      {/* Watchlist Table */}
      <GlassCard>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-slate-500 uppercase tracking-wider border-b border-trading-border">
                <th className="text-left py-3 px-3">Ticker</th>
                <th className="text-left py-3 px-3">Name</th>
                <th className="text-center py-3 px-2">TF</th>
                <th className="text-center py-3 px-2">Tier</th>
                <th className="text-right py-3 px-2 font-mono">LTRP</th>
                <th className="text-right py-3 px-2 font-mono">Pivot High</th>
                <th className="text-center py-3 px-2">Active</th>
                <th className="text-center py-3 px-2">Source</th>
                <th className="text-center py-3 px-2">
                  <Filter size={12} className="inline" />
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-trading-border/50">
              <AnimatePresence>
                {filteredItems.map((item, idx) => (
                  <motion.tr
                    key={item.id}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ delay: idx * 0.03 }}
                    className={cn(
                      'hover:bg-slate-800/30 transition-colors',
                      !item.active && 'opacity-50'
                    )}
                  >
                    <td className="py-2.5 px-3">
                      <span className="font-mono font-bold text-white">{item.ticker}</span>
                    </td>
                    <td className="py-2.5 px-3 text-slate-400">{item.name}</td>
                    <td className="py-2.5 px-2 text-center">
                      <span className="text-xs font-mono bg-slate-800 px-1.5 py-0.5 rounded">{item.timeframe}</span>
                    </td>
                    <td className="py-2.5 px-2 text-center">
                      <span className={cn(
                        'text-xs font-mono font-bold px-2 py-0.5 rounded',
                        item.tier === 1 ? 'bg-trading-bull/10 text-trading-bull' :
                        item.tier === 2 ? 'bg-trading-alert/10 text-trading-alert' :
                        'bg-slate-700 text-slate-400'
                      )}>
                        T{item.tier}
                      </span>
                    </td>
                    <td className="py-2.5 px-2 text-right font-mono text-slate-300">
                      {item.ltrp ? item.ltrp.toFixed(2) : '--'}
                    </td>
                    <td className="py-2.5 px-2 text-right font-mono text-slate-300">
                      {item.pivot_high ? item.pivot_high.toFixed(2) : '--'}
                    </td>
                    <td className="py-2.5 px-2 text-center">
                      <button
                        onClick={() => handleToggle(item.id)}
                        className={cn(
                          'p-1 rounded transition-colors',
                          item.active ? 'text-trading-bull hover:bg-trading-bull/10' : 'text-slate-600 hover:bg-slate-700'
                        )}
                      >
                        {item.active ? <Eye size={16} /> : <EyeOff size={16} />}
                      </button>
                    </td>
                    <td className="py-2.5 px-2 text-center">
                      <StatusBadge
                        status={item.source === 'AI' ? 'STRONG' : item.source === 'RRMS' ? 'BULL' : 'NEUTRAL'}
                        size="sm"
                      />
                    </td>
                    <td className="py-2.5 px-2 text-center">
                      <button
                        onClick={() => handleRemove(item.id)}
                        className="p-1 rounded text-slate-600 hover:text-trading-bear hover:bg-trading-bear/10 transition-colors"
                      >
                        <Trash2 size={14} />
                      </button>
                    </td>
                  </motion.tr>
                ))}
              </AnimatePresence>
            </tbody>
          </table>
        </div>

        {filteredItems.length === 0 && (
          <div className="text-center py-12 text-slate-500">
            <Eye size={32} className="mx-auto mb-2 opacity-50" />
            <p className="text-sm">
              {watchlist.length === 0
                ? 'Watchlist is empty. Add stocks to start tracking.'
                : 'No stocks found matching your criteria'}
            </p>
          </div>
        )}
      </GlassCard>
    </motion.div>
  );
}
