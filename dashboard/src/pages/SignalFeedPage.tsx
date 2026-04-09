import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { signalFeedApi } from '../services/agentApi';
import type { AgentSignal } from '../types';

const SignalFeedPage = () => {
  const [signals, setSignals] = useState<AgentSignal[]>([]);
  const [loading, setLoading] = useState(true);
  const [signalType, setSignalType] = useState<'all' | 'trade' | 'analysis' | 'discussion'>('all');
  const [exchange, setExchange] = useState<string>('all');
  const [sortBy, setSortBy] = useState<'new' | 'active' | 'following'>('new');

  const easing: [number, number, number, number] = [0.16, 1, 0.3, 1];

  useEffect(() => {
    const fetchSignals = async () => {
      setLoading(true);
      try {
        const result = await signalFeedApi.getFeed({
          signal_type: signalType === 'all' ? undefined : signalType,
          exchange: exchange === 'all' ? undefined : exchange,
          sort: sortBy,
        });
        setSignals(result.signals);
      } catch (error) {
        console.error('Failed to fetch signals:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchSignals();
  }, [signalType, exchange, sortBy]);

  const getExchangeColor = (ex: string) => {
    const colors: Record<string, string> = {
      NSE: 'blue',
      MCX: 'amber',
      NFO: 'purple',
      CDS: 'emerald',
    };
    return colors[ex] || 'blue';
  };

  const getDirectionColor = (direction: string) => {
    return direction === 'BUY' ? 'text-trading-bull' : 'text-trading-bear';
  };

  return (
    <div className="min-h-screen bg-trading-bg p-6">
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="stat-label text-3xl mb-6">Social Signal Feed</h1>

          {/* Tab Filters */}
          <div className="flex gap-3 mb-6 overflow-x-auto pb-2">
            {(['all', 'trade', 'analysis', 'discussion'] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => setSignalType(tab)}
                className={`px-4 py-2 rounded-xl whitespace-nowrap transition-all ${
                  signalType === tab
                    ? 'bg-trading-ai text-white'
                    : 'bg-trading-ai/8 text-trading-ai-light border border-trading-ai/15 hover:border-trading-ai/30'
                }`}
              >
                {tab.charAt(0).toUpperCase() + tab.slice(1)}
              </button>
            ))}
          </div>

          {/* Sort Options */}
          <div className="flex gap-2 mb-6">
            <span className="text-trading-info text-sm py-2">Sort by:</span>
            {(['new', 'active', 'following'] as const).map((sort) => (
              <button
                key={sort}
                onClick={() => setSortBy(sort)}
                className={`px-3 py-2 rounded-lg text-sm transition-all ${
                  sortBy === sort
                    ? 'bg-trading-info/20 text-trading-info border border-trading-info/30'
                    : 'text-trading-info/60 hover:text-trading-info/80'
                }`}
              >
                {sort.charAt(0).toUpperCase() + sort.slice(1)}
              </button>
            ))}
          </div>

          {/* Exchange Filters */}
          <div className="flex gap-2 overflow-x-auto pb-2">
            {(['all', 'NSE', 'MCX', 'NFO', 'CDS'] as const).map((ex) => {
              const color = ex === 'all' ? 'blue' : getExchangeColor(ex);
              return (
                <button
                  key={ex}
                  onClick={() => setExchange(ex)}
                  className={`px-3 py-1.5 rounded-lg text-sm whitespace-nowrap transition-all ${
                    exchange === ex
                      ? `bg-${color}-500/30 text-white border border-${color}-500/50`
                      : `bg-${color}/8 text-${color}-300 border border-${color}/15 hover:border-${color}/30`
                  }`}
                >
                  {ex}
                </button>
              );
            })}
          </div>
        </div>

        {/* Signals List */}
        {loading ? (
          <div className="text-center py-12 text-trading-info/50">Loading signals...</div>
        ) : signals.length === 0 ? (
          <div className="text-center py-12 text-trading-info/50">No signals found</div>
        ) : (
          <AnimatePresence mode="popLayout">
            <motion.div className="space-y-4">
              {signals.map((signal, idx) => (
                <motion.div
                  key={signal.id}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -20 }}
                  transition={{ duration: 0.3, ease: easing, delay: idx * 0.02 }}
                  className="glass-card rounded-2xl p-5 bg-white/5 border border-white/10 hover:border-trading-ai/20 transition-all"
                >
                  {/* Header */}
                  <div className="flex items-start justify-between mb-4">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-full bg-trading-ai/20 flex items-center justify-center">
                        <span className="text-trading-ai text-sm font-bold">
                          {signal.agent_name.charAt(0)}
                        </span>
                      </div>
                      <div>
                        <p className="font-semibold text-white">{signal.agent_name}</p>
                        <p className="text-trading-info/60 text-xs">
                          {new Date(signal.created_at).toLocaleDateString()}
                        </p>
                      </div>
                    </div>
                    {signal.exchange && (
                      <span
                        className={`px-2 py-1 rounded-lg text-xs font-medium bg-${getExchangeColor(signal.exchange)}/8 border border-${getExchangeColor(signal.exchange)}/15 text-white`}
                      >
                        {signal.exchange}
                      </span>
                    )}
                  </div>

                  {/* Trade Signal Content */}
                  {signal.signal_type === 'trade' && (
                    <div className="space-y-4">
                      <div className="flex items-center gap-3 mb-3">
                        {signal.direction && (
                          <span className={`text-xl font-bold ${getDirectionColor(signal.direction)}`}>
                            {signal.direction}
                          </span>
                        )}
                        {signal.symbol && (
                          <span className="text-white font-semibold">{signal.symbol}</span>
                        )}
                        {signal.entry_price != null && (
                          <span className="text-trading-info/60 text-sm">
                            ₹{signal.entry_price.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
                          </span>
                        )}
                      </div>
                      <div className="grid grid-cols-3 gap-4 text-sm">
                        <div>
                          <p className="text-trading-info/50 text-xs stat-label">Entry</p>
                          <p className="text-white font-mono tabular-nums">
                            ₹{signal.entry_price?.toFixed(2) ?? '-'}
                          </p>
                        </div>
                        <div>
                          <p className="text-trading-info/50 text-xs stat-label">SL</p>
                          <p className="text-trading-bear font-mono tabular-nums">
                            ₹{signal.stop_loss?.toFixed(2) ?? '-'}
                          </p>
                        </div>
                        <div>
                          <p className="text-trading-info/50 text-xs stat-label">Target</p>
                          <p className="text-trading-bull font-mono tabular-nums">
                            ₹{signal.target?.toFixed(2) ?? '-'}
                          </p>
                        </div>
                      </div>
                      <div className="flex items-center justify-between pt-2">
                        <div>
                          <p className="text-trading-info/50 text-xs stat-label">R:R Ratio</p>
                          <p className="text-trading-bull font-semibold tabular-nums">
                            {signal.rrr?.toFixed(2) ?? '-'}:1
                          </p>
                        </div>
                        {signal.ai_confidence != null && (
                          <>
                            <div className="flex-1 mx-4">
                              <p className="text-trading-info/50 text-xs stat-label mb-1">AI Confidence</p>
                              <div className="w-full bg-white/10 rounded-full h-2">
                                <motion.div
                                  className="h-full bg-gradient-to-r from-trading-ai to-trading-bull rounded-full"
                                  initial={{ width: 0 }}
                                  animate={{ width: `${(signal.ai_confidence) * 100}%` }}
                                  transition={{ duration: 0.6, ease: easing }}
                                />
                              </div>
                            </div>
                            <div className="text-right">
                              <p className="text-trading-ai font-semibold tabular-nums">
                                {(signal.ai_confidence * 100).toFixed(0)}%
                              </p>
                            </div>
                          </>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Analysis/Discussion Content */}
                  {(signal.signal_type === 'analysis' || signal.signal_type === 'discussion') && (
                    <div className="space-y-3">
                      {signal.title && (
                        <h3 className="text-white font-semibold">{signal.title}</h3>
                      )}
                      {signal.content && (
                        <p className="text-trading-info/70 text-sm line-clamp-2">{signal.content}</p>
                      )}
                      {signal.tags && (
                        <div className="flex gap-2 flex-wrap">
                          {signal.tags.split(',').map((tag) => (
                            <span
                              key={tag.trim()}
                              className="px-2 py-1 rounded text-xs bg-trading-ai/10 text-trading-ai border border-trading-ai/20"
                            >
                              {tag.trim()}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Footer */}
                  <div className="flex items-center justify-between mt-4 pt-4 border-t border-white/10">
                    <div className="flex gap-4 text-sm text-trading-info/60">
                      <span>👥 {signal.follower_count}</span>
                      <span>💬 {signal.reply_count}</span>
                    </div>
                    <button className="px-4 py-2 rounded-xl bg-trading-ai/8 text-trading-ai-light border border-trading-ai/15 hover:border-trading-ai/30 text-sm font-medium transition-all">
                      Reply
                    </button>
                  </div>
                </motion.div>
              ))}
            </motion.div>
          </AnimatePresence>
        )}

        {/* SEBI Disclaimer */}
        <div className="mt-12 p-4 rounded-xl bg-trading-bear/5 border border-trading-bear/20">
          <p className="text-trading-bear/70 text-xs leading-relaxed">
            <span className="font-semibold">SEBI Disclaimer:</span> The signals, analysis, and discussions on this platform are for informational purposes only and do not constitute investment advice. Past performance is not indicative of future results. Trading involves substantial risk of loss. Please conduct your own research and consult with a qualified financial advisor before making any investment decisions.
          </p>
        </div>
      </div>
    </div>
  );
};

export default SignalFeedPage;
