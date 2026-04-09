import axios from 'axios';
import type {
  TradingAgent,
  AgentSignal,
  AgentPosition,
  AgentFollowing,
  ProfitHistoryPoint,
  SignalReply,
  SubscriptionPlan,
  UserSubscription,
} from '../types';

const agentApi = axios.create({
  baseURL: '/api/agents',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
});

// Set auth token for agent requests
export function setAgentToken(token: string) {
  agentApi.defaults.headers.common['Authorization'] = `Bearer ${token}`;
}

export function clearAgentToken() {
  delete agentApi.defaults.headers.common['Authorization'];
}

// Also use the main app's auth token if logged in
const mainToken = localStorage.getItem('mkumaran_auth_token');
if (mainToken) {
  agentApi.defaults.headers.common['Authorization'] = `Bearer ${mainToken}`;
}

// ── Agent Auth ───────────────────────────────────────────────
export const agentAuthApi = {
  register: (name: string, password: string, description?: string) =>
    agentApi.post('/register', { name, password, description }).then((r) => r.data),
  login: (name: string, password: string) =>
    agentApi.post('/login', { name, password }).then((r) => r.data),
  me: () => agentApi.get('/me').then((r) => r.data),
  profile: (agentId: number) =>
    agentApi.get(`/profile/${agentId}`).then((r) => r.data),
  count: () => agentApi.get('/count').then((r) => r.data),
};

// ── Signal Feed ──────────────────────────────────────────────
export const signalFeedApi = {
  getFeed: (params?: {
    signal_type?: string;
    exchange?: string;
    limit?: number;
    offset?: number;
    sort?: string;
  }) =>
    agentApi
      .get<{ signals: AgentSignal[]; disclaimer: string }>('/signals/feed', { params })
      .then((r) => r.data),

  publishTrade: (data: {
    symbol: string;
    exchange: string;
    direction: string;
    entry_price: number;
    stop_loss: number;
    target: number;
    quantity: number;
    pattern?: string;
    timeframe?: string;
    ai_confidence?: number;
    content?: string;
  }) => agentApi.post('/signals/trade', data).then((r) => r.data),

  publishAnalysis: (data: {
    title: string;
    content: string;
    symbol?: string;
    exchange?: string;
    tags?: string;
  }) => agentApi.post('/signals/analysis', data).then((r) => r.data),

  publishDiscussion: (data: {
    title: string;
    content: string;
    tags?: string;
  }) => agentApi.post('/signals/discussion', data).then((r) => r.data),

  reply: (signalId: number, content: string) =>
    agentApi.post('/signals/reply', { signal_id: signalId, content }).then((r) => r.data),

  getReplies: (signalId: number) =>
    agentApi.get<{ replies: SignalReply[] }>(`/signals/${signalId}/replies`).then((r) => r.data),

  acceptReply: (signalId: number, replyId: number) =>
    agentApi.post(`/signals/${signalId}/replies/${replyId}/accept`).then((r) => r.data),
};

// ── Follow / Copy Trading ────────────────────────────────────
export const copyTradeApi = {
  follow: (leaderId: number, copyRatio: number = 1.0) =>
    agentApi.post('/follow', { leader_id: leaderId, copy_ratio: copyRatio }).then((r) => r.data),
  unfollow: (leaderId: number) =>
    agentApi.post('/unfollow', { leader_id: leaderId }).then((r) => r.data),
  getFollowing: () =>
    agentApi.get<{ following: AgentFollowing[] }>('/following').then((r) => r.data),
  getFollowers: () =>
    agentApi.get('/followers').then((r) => r.data),
};

// ── Leaderboard ──────────────────────────────────────────────
export const leaderboardApi = {
  get: (limit: number = 20) =>
    agentApi
      .get<{ leaderboard: TradingAgent[]; currency: string }>('/leaderboard', { params: { limit } })
      .then((r) => r.data),
  getProfitHistory: (agentId: number, days: number = 7) =>
    agentApi
      .get<{ agent_id: number; history: ProfitHistoryPoint[] }>(`/leaderboard/${agentId}/history`, {
        params: { days },
      })
      .then((r) => r.data),
};

// ── Positions ────────────────────────────────────────────────
export const agentPositionApi = {
  myPositions: () =>
    agentApi.get<{ positions: AgentPosition[]; currency: string }>('/positions').then((r) => r.data),
  agentPositions: (agentId: number) =>
    agentApi.get<{ positions: AgentPosition[] }>(`/positions/${agentId}`).then((r) => r.data),
};

// ── Points ───────────────────────────────────────────────────
export const pointsApi = {
  exchange: (amount: number) =>
    agentApi.post('/points/exchange', { amount }).then((r) => r.data),
};

// ── Heartbeat ────────────────────────────────────────────────
export const heartbeatApi = {
  poll: () => agentApi.post('/heartbeat').then((r) => r.data),
};

// ── Subscriptions ────────────────────────────────────────────
export const subscriptionApi = {
  getMySubscription: () =>
    agentApi.get<UserSubscription>('/subscription').then((r) => r.data),
  getPlans: () =>
    agentApi
      .get<{ plans: SubscriptionPlan[]; currency: string }>('/subscription/plans')
      .then((r) => r.data),
  subscribe: (planSlug: string, billingCycle: string = 'monthly') =>
    agentApi
      .post('/subscription/subscribe', { plan_slug: planSlug, billing_cycle: billingCycle })
      .then((r) => r.data),
  cancel: () => agentApi.post('/subscription/cancel').then((r) => r.data),
};

export default agentApi;
