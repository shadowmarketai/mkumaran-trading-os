import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { Users, TrendingUp, BarChart2 } from 'lucide-react';
import { leaderboardApi, agentAuthApi } from '../services/agentApi';
import type { TradingAgent } from '../types';
import GlassCard from '../components/ui/GlassCard';
import MetricCard from '../components/ui/MetricCard';
import { cn } from '../lib/utils';

export default function AgentHubPage() {
  const [agents, setAgents] = useState<TradingAgent[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [followedAgents, setFollowedAgents] = useState<Set<number>>(new Set());

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      setLoading(true);
      const [result, count] = await Promise.all([
        leaderboardApi.get(),
        agentAuthApi.count(),
      ]);
      setAgents(result.leaderboard);
      setTotalCount(count);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load leaderboard');
    } finally {
      setLoading(false);
    }
  };

  const handleFollow = (agentId: number) => {
    setFollowedAgents((prev) => {
      const updated = new Set(prev);
      if (updated.has(agentId)) {
        updated.delete(agentId);
      } else {
        updated.add(agentId);
      }
      return updated;
    });
  };

  const topProfitAgent = agents.length > 0 ? agents[0] : null;
  const totalSignals = agents.reduce((sum, agent) => sum + agent.total_trades, 0);

  const getAgentTypeBadgeColor = (type: string) => {
    switch (type) {
      case 'system':
        return 'bg-trading-ai/15 text-trading-ai-light border-trading-ai/30';
      case 'external':
        return 'bg-trading-info/15 text-trading-info border-trading-info/30';
      case 'human':
        return 'bg-trading-bull/15 text-trading-bull border-trading-bull/30';
      default:
        return 'bg-slate-500/15 text-slate-400 border-slate-500/30';
    }
  };

  const formatINR = (value: number) => {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: 'INR',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value);
  };

  if (error) {
    return (
      <motion.div
        className="min-h-screen bg-trading-bg p-8"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
      >
        <div className="text-center text-trading-bear">{error}</div>
      </motion.div>
    );
  }

  return (
    <motion.div
      className="min-h-screen bg-trading-bg p-8"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ ease: [0.16, 1, 0.3, 1] }}
    >
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-4xl font-bold text-white mb-2">Agent Hub</h1>
          <p className="text-slate-400">Multi-Agent Trading Leaderboard</p>
        </div>

        {/* Metrics */}
        <div className="grid grid-cols-3 gap-4 mb-8">
          <MetricCard
            title="Total Agents"
            value={loading ? '-' : totalCount.toString()}
            icon={Users}
            color="ai"
          />
          <MetricCard
            title="Top Agent"
            value={loading ? '-' : (topProfitAgent ? topProfitAgent.name : '-')}
            icon={TrendingUp}
            color="bull"
          />
          <MetricCard
            title="Total Signals"
            value={loading ? '-' : totalSignals.toString()}
            icon={BarChart2}
            color="info"
          />
        </div>

        {/* Leaderboard Table */}
        <GlassCard className="overflow-hidden">
          <div className="p-6 border-b border-trading-border/15">
            <h2 className="stat-label">LEADERBOARD</h2>
          </div>

          {loading ? (
            <div className="flex justify-center items-center p-12">
              <div className="w-12 h-12 rounded-2xl bg-trading-ai/10 animate-pulse" />
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-trading-border/15">
                    <th className="text-[9px] text-slate-500 font-medium uppercase tracking-[0.12em] px-6 py-3 text-left">
                      Agent Name
                    </th>
                    <th className="text-[9px] text-slate-500 font-medium uppercase tracking-[0.12em] px-6 py-3 text-left">
                      Type
                    </th>
                    <th className="text-[9px] text-slate-500 font-medium uppercase tracking-[0.12em] px-6 py-3 text-right">
                      Win Rate
                    </th>
                    <th className="text-[9px] text-slate-500 font-medium uppercase tracking-[0.12em] px-6 py-3 text-right">
                      Total Trades
                    </th>
                    <th className="text-[9px] text-slate-500 font-medium uppercase tracking-[0.12em] px-6 py-3 text-right">
                      Latest P&L (INR)
                    </th>
                    <th className="text-[9px] text-slate-500 font-medium uppercase tracking-[0.12em] px-6 py-3 text-right">
                      Points
                    </th>
                    <th className="text-[9px] text-slate-500 font-medium uppercase tracking-[0.12em] px-6 py-3 text-center">
                      Followers
                    </th>
                    <th className="text-[9px] text-slate-500 font-medium uppercase tracking-[0.12em] px-6 py-3 text-center">
                      Action
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {agents.map((agent) => (
                    <tr
                      key={agent.id}
                      className="border-b border-trading-border/15 hover:bg-white/[0.015] transition-colors"
                    >
                      <td className="text-[9px] text-slate-300 px-6 py-4">
                        {agent.name}
                      </td>
                      <td className="text-[9px] px-6 py-4">
                        <span
                          className={cn(
                            'inline-flex items-center px-2 py-1 rounded-lg border text-[8px] font-medium uppercase',
                            getAgentTypeBadgeColor(agent.agent_type)
                          )}
                        >
                          {agent.agent_type}
                        </span>
                      </td>
                      <td className="text-[9px] text-slate-300 px-6 py-4 text-right font-mono tabular-nums">
                        {(parseFloat(agent.win_rate) * 100).toFixed(1)}%
                      </td>
                      <td className="text-[9px] text-slate-300 px-6 py-4 text-right font-mono tabular-nums">
                        {agent.total_trades}
                      </td>
                      <td
                        className={cn(
                          'text-[9px] px-6 py-4 text-right font-mono tabular-nums',
                          (agent.latest_profit ?? 0) >= 0 ? 'text-trading-bull' : 'text-trading-bear'
                        )}
                      >
                        {agent.latest_profit !== undefined ? formatINR(agent.latest_profit) : '-'}
                      </td>
                      <td className="text-[9px] text-slate-300 px-6 py-4 text-right font-mono tabular-nums">
                        {agent.points}
                      </td>
                      <td className="text-[9px] text-slate-300 px-6 py-4 text-center font-mono tabular-nums">
                        {agent.follower_count ?? 0}
                      </td>
                      <td className="text-[9px] px-6 py-4 text-center">
                        <button
                          onClick={() => handleFollow(agent.id)}
                          className={cn(
                            'px-3 py-1 rounded-xl border font-medium text-[8px] uppercase transition-colors',
                            followedAgents.has(agent.id)
                              ? 'bg-trading-ai/20 text-trading-ai-light border-trading-ai/40'
                              : 'bg-trading-ai/8 text-trading-ai-light border-trading-ai/15 hover:bg-trading-ai/12'
                          )}
                        >
                          {followedAgents.has(agent.id) ? 'Following' : 'Follow'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </GlassCard>
      </div>
    </motion.div>
  );
}
