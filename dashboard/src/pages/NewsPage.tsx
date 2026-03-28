import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Newspaper,
  AlertTriangle,
  TrendingUp,
  Globe,
  Shield,
  BarChart3,
  ExternalLink,
  RefreshCw,
  Loader2,
  AlertCircle,
  Clock,
  Filter,
} from 'lucide-react';
import GlassCard from '../components/ui/GlassCard';
import { cn } from '../lib/utils';
import { useNews } from '../hooks/useNews';
import type { NewsItem } from '../types';

type ImpactFilter = 'ALL' | 'HIGH' | 'MEDIUM' | 'LOW';
type CategoryFilter = 'ALL' | 'POLICY' | 'MACRO' | 'GEOPOLITICAL' | 'REGULATORY' | 'MARKET' | 'GENERAL';

const impactConfig: Record<string, { color: string; bg: string; border: string; label: string }> = {
  HIGH: {
    color: 'text-trading-bear',
    bg: 'bg-trading-bear/10',
    border: 'border-trading-bear/30',
    label: 'HIGH',
  },
  MEDIUM: {
    color: 'text-trading-alert',
    bg: 'bg-trading-alert/10',
    border: 'border-trading-alert/30',
    label: 'MEDIUM',
  },
  LOW: {
    color: 'text-slate-400',
    bg: 'bg-slate-500/10',
    border: 'border-slate-500/30',
    label: 'LOW',
  },
};

const categoryIcons: Record<string, React.ReactNode> = {
  POLICY: <Shield size={14} />,
  MACRO: <BarChart3 size={14} />,
  GEOPOLITICAL: <Globe size={14} />,
  REGULATORY: <Shield size={14} />,
  MARKET: <TrendingUp size={14} />,
  GENERAL: <Newspaper size={14} />,
};

const categoryColors: Record<string, string> = {
  POLICY: 'bg-violet-500/15 text-violet-400 border-violet-500/25',
  MACRO: 'bg-cyan-500/15 text-cyan-400 border-cyan-500/25',
  GEOPOLITICAL: 'bg-rose-500/15 text-rose-400 border-rose-500/25',
  REGULATORY: 'bg-amber-500/15 text-amber-400 border-amber-500/25',
  MARKET: 'bg-trading-bull/15 text-trading-bull border-trading-bull/25',
  GENERAL: 'bg-slate-500/15 text-slate-400 border-slate-500/25',
};

function ImpactBadge({ impact }: { impact: string }) {
  const cfg = impactConfig[impact] || impactConfig.LOW;
  return (
    <span className={cn('px-2 py-0.5 rounded text-[10px] font-mono font-bold border', cfg.bg, cfg.color, cfg.border)}>
      {cfg.label}
    </span>
  );
}

function CategoryBadge({ category }: { category: string }) {
  return (
    <span className={cn('inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium border', categoryColors[category] || categoryColors.GENERAL)}>
      {categoryIcons[category] || categoryIcons.GENERAL}
      {category}
    </span>
  );
}

function NewsCard({ item }: { item: NewsItem }) {
  const impactCfg = impactConfig[item.impact] || impactConfig.LOW;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      className={cn(
        'glass-card p-4 border-l-2 hover:bg-slate-800/30 transition-colors',
        item.impact === 'HIGH' ? 'border-l-trading-bear' : item.impact === 'MEDIUM' ? 'border-l-trading-alert' : 'border-l-slate-600',
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          {/* Title */}
          <h3 className="text-sm font-medium text-white leading-snug mb-1.5">
            {item.url ? (
              <a
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-trading-ai-light transition-colors inline-flex items-center gap-1"
              >
                {item.title}
                <ExternalLink size={12} className="text-slate-500 flex-shrink-0" />
              </a>
            ) : (
              item.title
            )}
          </h3>

          {/* Summary */}
          {item.summary && (
            <p className="text-xs text-slate-400 leading-relaxed mb-2 line-clamp-2">{item.summary}</p>
          )}

          {/* Badges row */}
          <div className="flex items-center gap-2 flex-wrap">
            <ImpactBadge impact={item.impact} />
            <CategoryBadge category={item.category} />
            <span className="text-[10px] text-slate-500 font-mono">{item.source}</span>
          </div>

          {/* Keywords */}
          {item.matched_keywords.length > 0 && (
            <div className="flex items-center gap-1 mt-2 flex-wrap">
              {item.matched_keywords.slice(0, 4).map((kw) => (
                <span
                  key={kw}
                  className={cn('px-1.5 py-0.5 text-[9px] font-mono rounded', impactCfg.bg, impactCfg.color)}
                >
                  {kw}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Timestamp */}
        {item.published && (
          <div className="flex items-center gap-1 text-[10px] text-slate-500 flex-shrink-0">
            <Clock size={10} />
            <span>{formatRelativeTime(item.published)}</span>
          </div>
        )}
      </div>
    </motion.div>
  );
}

function formatRelativeTime(dateStr: string): string {
  try {
    const date = new Date(dateStr);
    if (isNaN(date.getTime())) return dateStr.slice(0, 16);

    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);

    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHrs = Math.floor(diffMins / 60);
    if (diffHrs < 24) return `${diffHrs}h ago`;
    const diffDays = Math.floor(diffHrs / 24);
    return `${diffDays}d ago`;
  } catch {
    return dateStr.slice(0, 16);
  }
}

export default function NewsPage() {
  const [impactFilter, setImpactFilter] = useState<ImpactFilter>('ALL');
  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>('ALL');
  const [hoursBack, setHoursBack] = useState(24);

  const { items, loading, error, refresh } = useNews({
    hours: hoursBack,
    minImpact: impactFilter === 'ALL' ? 'LOW' : impactFilter,
    autoRefreshMs: 5 * 60 * 1000, // refresh every 5 minutes
  });

  const filteredItems = items.filter((item) => {
    if (categoryFilter !== 'ALL' && item.category !== categoryFilter) return false;
    return true;
  });

  const highCount = items.filter((i) => i.impact === 'HIGH').length;
  const medCount = items.filter((i) => i.impact === 'MEDIUM').length;

  const impactFilters: { label: string; value: ImpactFilter; count?: number }[] = [
    { label: 'All', value: 'ALL', count: items.length },
    { label: 'High', value: 'HIGH', count: highCount },
    { label: 'Medium', value: 'MEDIUM', count: medCount },
    { label: 'Low', value: 'LOW' },
  ];

  const categoryFilters: { label: string; value: CategoryFilter }[] = [
    { label: 'All', value: 'ALL' },
    { label: 'Policy', value: 'POLICY' },
    { label: 'Macro', value: 'MACRO' },
    { label: 'Geopolitical', value: 'GEOPOLITICAL' },
    { label: 'Regulatory', value: 'REGULATORY' },
    { label: 'Market', value: 'MARKET' },
  ];

  const hoursOptions = [
    { label: '6h', value: 6 },
    { label: '12h', value: 12 },
    { label: '24h', value: 24 },
    { label: '48h', value: 48 },
    { label: '7d', value: 168 },
  ];

  if (loading && items.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <Loader2 size={48} className="text-trading-ai animate-spin mb-4" />
        <p className="text-slate-400 text-sm">Fetching news feeds...</p>
      </div>
    );
  }

  if (error && items.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <AlertCircle size={48} className="text-trading-alert mb-4" />
        <p className="text-slate-400 text-sm">Failed to load news: {error}</p>
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
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Newspaper size={20} className="text-trading-ai" />
          <h2 className="text-lg font-semibold text-white">News & Macro Events</h2>
          {highCount > 0 && (
            <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-trading-bear/15 text-trading-bear text-xs font-mono font-bold">
              <AlertTriangle size={12} />
              {highCount} HIGH
            </span>
          )}
        </div>
        <button
          onClick={refresh}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-slate-400 hover:text-white hover:bg-slate-700/50 transition-colors disabled:opacity-50"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {/* Filters */}
      <GlassCard className="!p-3">
        <div className="flex flex-wrap items-center gap-4">
          {/* Impact filter */}
          <div className="flex items-center gap-1.5">
            <Filter size={12} className="text-slate-500" />
            <span className="text-[10px] text-slate-500 uppercase tracking-wider mr-1">Impact</span>
            {impactFilters.map((f) => (
              <button
                key={f.value}
                onClick={() => setImpactFilter(f.value)}
                className={cn(
                  'px-2.5 py-1 rounded-md text-xs font-medium transition-colors',
                  impactFilter === f.value
                    ? 'bg-trading-card text-white border border-trading-ai/30'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-700/50',
                )}
              >
                {f.label}
                {f.count !== undefined && f.count > 0 && (
                  <span className="ml-1 text-[10px] text-slate-500">{f.count}</span>
                )}
              </button>
            ))}
          </div>

          <div className="w-px h-5 bg-trading-border" />

          {/* Category filter */}
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] text-slate-500 uppercase tracking-wider mr-1">Category</span>
            {categoryFilters.map((f) => (
              <button
                key={f.value}
                onClick={() => setCategoryFilter(f.value)}
                className={cn(
                  'px-2.5 py-1 rounded-md text-xs font-medium transition-colors',
                  categoryFilter === f.value
                    ? 'bg-trading-card text-white border border-trading-ai/30'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-700/50',
                )}
              >
                {f.label}
              </button>
            ))}
          </div>

          <div className="w-px h-5 bg-trading-border" />

          {/* Time range */}
          <div className="flex items-center gap-1.5">
            <Clock size={12} className="text-slate-500" />
            {hoursOptions.map((h) => (
              <button
                key={h.value}
                onClick={() => setHoursBack(h.value)}
                className={cn(
                  'px-2 py-1 rounded-md text-xs font-mono transition-colors',
                  hoursBack === h.value
                    ? 'bg-trading-card text-white border border-trading-ai/30'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-700/50',
                )}
              >
                {h.label}
              </button>
            ))}
          </div>
        </div>
      </GlassCard>

      {/* News Items */}
      <div className="space-y-2">
        <AnimatePresence mode="popLayout">
          {filteredItems.length > 0 ? (
            filteredItems.map((item, idx) => (
              <NewsCard key={item.url || `${item.title}-${idx}`} item={item} />
            ))
          ) : (
            <GlassCard className="text-center py-12">
              <Newspaper size={32} className="mx-auto mb-2 text-slate-600" />
              <p className="text-slate-500 text-sm">
                No news items match the current filters
              </p>
            </GlassCard>
          )}
        </AnimatePresence>
      </div>

      {/* Footer */}
      <p className="text-center text-[10px] text-slate-600">
        Sources: MoneyControl, Economic Times, Livemint
        {items.some((i) => i.source.startsWith('newsapi:')) && ' + NewsAPI'}
        {' | '}Auto-refreshes every 5 minutes
      </p>
    </motion.div>
  );
}
