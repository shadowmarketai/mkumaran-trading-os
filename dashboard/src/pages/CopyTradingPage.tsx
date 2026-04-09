import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { Trash2, Link as LinkIcon, Users, UserCheck, Copy } from 'lucide-react';
import GlassCard from '../components/ui/GlassCard';
import MetricCard from '../components/ui/MetricCard';
import { copyTradeApi } from '../services/agentApi';
import type { AgentFollowing } from '../types';

const easing = [0.16, 1, 0.3, 1];

export default function CopyTradingPage() {
  const [following, setFollowing] = useState<AgentFollowing[]>([]);
  const [followers, setFollowers] = useState<AgentFollowing[]>([]);
  const [loading, setLoading] = useState(true);
  const [copyRatios, setCopyRatios] = useState<Record<number, number>>({});

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [followingResult, followersResult] = await Promise.all([
          copyTradeApi.getFollowing(),
          copyTradeApi.getFollowers(),
        ]);
        const followingData: AgentFollowing[] = followingResult.following ?? [];
        const followersData: AgentFollowing[] = followersResult.followers ?? followersResult ?? [];
        setFollowing(followingData);
        setFollowers(followersData);
        const ratios: Record<number, number> = {};
        followingData.forEach((f) => (ratios[f.leader_id] = f.copy_ratio ?? 1));
        setCopyRatios(ratios);
      } catch (error) {
        console.error('Error fetching copy trading data:', error);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  const handleUnfollow = async (leaderId: number, agentName: string) => {
    if (window.confirm(`Unfollow ${agentName}?`)) {
      try {
        await copyTradeApi.unfollow(leaderId);
        setFollowing(following.filter((a) => a.leader_id !== leaderId));
      } catch (error) {
        console.error('Error unfollowing agent:', error);
      }
    }
  };

  const handleCopyRatioChange = (leaderId: number, ratio: number) => {
    const clamped = Math.max(0.1, Math.min(10, ratio));
    setCopyRatios((prev) => ({ ...prev, [leaderId]: clamped }));
  };

  return (
    <div className="space-y-8 p-6">
      {/* Metrics */}
      <motion.div
        className="grid grid-cols-1 md:grid-cols-3 gap-4"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: easing as [number, number, number, number] }}
      >
        <MetricCard
          title="Following"
          value={loading ? '-' : following.length}
          icon={UserCheck}
          color="ai"
        />
        <MetricCard
          title="Followers"
          value={loading ? '-' : followers.length}
          icon={Users}
          color="info"
        />
        <MetricCard
          title="Auto-Copy Active"
          value={loading ? '-' : following.filter((f) => f.auto_copy).length}
          icon={Copy}
          color="bull"
        />
      </motion.div>

      {/* Leaders I Follow */}
      <motion.section
        className="space-y-4"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.6, ease: easing as [number, number, number, number], delay: 0.1 }}
      >
        <h2 className="stat-label text-xl">Leaders I Follow</h2>
        {following.length === 0 ? (
          <GlassCard className="p-8 text-center">
            <p className="text-trading-secondary/70 mb-4">Not following any agents yet</p>
            <a href="/agent-hub" className="inline-flex items-center gap-2 text-trading-ai hover:text-trading-ai-light">
              <LinkIcon size={16} /> Browse Agent Hub
            </a>
          </GlassCard>
        ) : (
          <div className="grid gap-4">
            {following.map((agent, idx) => (
              <motion.div
                key={agent.leader_id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, ease: easing as [number, number, number, number], delay: idx * 0.05 }}
              >
                <GlassCard className="p-5">
                  <div className="flex justify-between items-start mb-4">
                    <div className="flex-1">
                      <div className="flex items-center gap-3 mb-2">
                        <h3 className="font-semibold text-white">{agent.name}</h3>
                        <span className="text-xs px-2.5 py-1 rounded-lg bg-trading-ai/10 text-trading-ai border border-trading-ai/20">
                          {agent.auto_copy ? 'Auto-Copy' : 'Manual'}
                        </span>
                      </div>
                    </div>
                    <button
                      onClick={() => handleUnfollow(agent.leader_id, agent.name)}
                      className="p-2 rounded-xl bg-trading-bear/8 text-trading-bear hover:bg-trading-bear/15 transition-colors"
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>

                  <div className="grid grid-cols-3 gap-3 mb-4 text-sm">
                    <div>
                      <p className="text-trading-secondary/60 text-xs">Win Rate</p>
                      <p className="font-semibold text-trading-bull tabular-nums">
                        {(parseFloat(agent.win_rate) * 100).toFixed(1)}%
                      </p>
                    </div>
                    <div>
                      <p className="text-trading-secondary/60 text-xs">Total Trades</p>
                      <p className="font-semibold tabular-nums">{agent.total_trades}</p>
                    </div>
                    <div>
                      <p className="text-trading-secondary/60 text-xs">Points</p>
                      <p className="font-semibold text-trading-ai tabular-nums">{agent.points}</p>
                    </div>
                  </div>

                  <div className="space-y-2">
                    <div className="flex justify-between items-center text-xs">
                      <label className="text-trading-secondary/70">Copy Ratio</label>
                      <span className="font-semibold tabular-nums text-trading-ai">
                        {(copyRatios[agent.leader_id] ?? 1).toFixed(1)}x
                      </span>
                    </div>
                    <input
                      type="range"
                      min="0.1"
                      max="10"
                      step="0.1"
                      value={copyRatios[agent.leader_id] ?? 1}
                      onChange={(e) => handleCopyRatioChange(agent.leader_id, parseFloat(e.target.value))}
                      className="w-full h-1.5 bg-trading-ai/15 rounded-lg appearance-none cursor-pointer"
                    />
                  </div>
                </GlassCard>
              </motion.div>
            ))}
          </div>
        )}
      </motion.section>

      {/* My Followers */}
      {followers.length > 0 && (
        <motion.section
          className="space-y-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.6, ease: easing as [number, number, number, number], delay: 0.2 }}
        >
          <h2 className="stat-label text-xl">My Followers</h2>
          <div className="grid gap-3">
            {followers.map((follower, idx) => (
              <motion.div
                key={follower.leader_id}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.4, ease: easing as [number, number, number, number], delay: idx * 0.05 }}
              >
                <GlassCard className="p-4">
                  <div className="flex justify-between items-center">
                    <div className="flex-1">
                      <p className="font-medium text-white">{follower.name}</p>
                      <p className="text-xs text-trading-secondary/60">
                        {follower.auto_copy ? 'Auto-copy enabled' : 'Manual copy'}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="text-xs text-trading-secondary/70">Copy Ratio</p>
                      <p className="font-semibold text-trading-ai tabular-nums">
                        {(follower.copy_ratio ?? 1).toFixed(1)}x
                      </p>
                    </div>
                  </div>
                </GlassCard>
              </motion.div>
            ))}
          </div>
        </motion.section>
      )}
    </div>
  );
}
