import axios from 'axios';
import type {
  OverviewData,
  Signal,
  ActiveTrade,
  MWAScore,
  WatchlistItem,
  AccuracyMetrics,
  BacktestResult,
  BacktestCompareResult,
  EngineDetectionResult,
  SegmentFilter,
  NewsItem,
  MomentumData,
  OptionChainData,
  GreeksResult,
  PayoffData,
  PayoffLeg,
  PlaceOrderRequest,
  OrderResult,
  OrderStatus,
} from '../types';

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
});

// Second instance for /tools/* endpoints (no /api prefix)
const toolsApi = axios.create({
  baseURL: '/',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
});

function handle401(error: unknown) {
  const err = error as { response?: { status?: number }; config?: { url?: string }; message?: string };
  if (
    err.response?.status === 401 &&
    !err.config?.url?.includes('/auth/login')
  ) {
    localStorage.removeItem('mkumaran_auth_token');
    localStorage.removeItem('mkumaran_auth_email');
    delete api.defaults.headers.common['Authorization'];
    delete toolsApi.defaults.headers.common['Authorization'];
    if (window.location.pathname !== '/login') {
      window.location.href = '/login';
    }
  }
  const message = err.response && 'data' in (err.response as Record<string, unknown>)
    ? ((err.response as Record<string, unknown>).data as Record<string, string>)?.detail || err.message
    : err.message;
  console.error('[API Error]', message);
  return Promise.reject(error);
}

api.interceptors.response.use((r) => r, handle401);
toolsApi.interceptors.response.use((r) => r, handle401);

export const overviewApi = {
  getOverview: (filter?: SegmentFilter) =>
    api.get<OverviewData>('/overview', { params: { ...filter } }).then((r) => r.data),
};

export const signalApi = {
  getSignals: (limit = 50, filter?: SegmentFilter) =>
    api.get<Signal[]>('/signals', { params: { limit, ...filter } }).then((r) => r.data),
};

export const tradeApi = {
  getActiveTrades: (filter?: SegmentFilter) =>
    api.get<ActiveTrade[]>('/trades/active', { params: { ...filter } }).then((r) => r.data),
};

export const mwaApi = {
  getLatest: () => api.get<MWAScore>('/mwa/latest').then((r) => r.data),
};

export const watchlistApi = {
  getAll: (tier = 0, filter?: SegmentFilter) =>
    api.get<WatchlistItem[]>('/watchlist', { params: { tier, ...filter } }).then((r) => r.data),
  add: (data: { ticker: string; tier?: number; ltrp?: number; pivot_high?: number; timeframe?: string }) =>
    api.post<WatchlistItem>('/watchlist', null, { params: data }).then((r) => r.data),
  remove: (id: number) => api.delete(`/watchlist/${id}`).then((r) => r.data),
  toggle: (id: number) => api.patch<WatchlistItem>(`/watchlist/${id}/toggle`).then((r) => r.data),
};

export const accuracyApi = {
  getMetrics: (filter?: SegmentFilter) =>
    api.get<AccuracyMetrics>('/accuracy', { params: { ...filter } }).then((r) => r.data),
};

export const backtestApi = {
  run: (ticker: string, strategy: string, days: number) =>
    api.post<BacktestResult>('/backtest', { ticker, strategy, days }).then((r) => r.data),
  compareAll: (ticker: string, days: number) =>
    api.post<BacktestCompareResult>('/backtest/compare', { ticker, days }, { timeout: 120000 }).then((r) => r.data),
};

export const engineApi = {
  detect: (engine: string, ticker: string, days: number) =>
    api.post<EngineDetectionResult>(`/engines/${engine}/detect`, { ticker, days }).then((r) => r.data),
  detectAll: (ticker: string, days: number) =>
    api.post<EngineDetectionResult[]>('/engines/detect-all', { ticker, days }).then((r) => r.data),
};

export const newsApi = {
  getLatest: (hours = 24, minImpact = 'LOW') =>
    api.get<NewsItem[]>('/news', { params: { hours, min_impact: minImpact } }).then((r) => r.data),
};

export const momentumApi = {
  getRankings: () =>
    api.get<MomentumData>('/momentum').then((r) => r.data),
  triggerRebalance: (topN = 10) =>
    toolsApi.post<MomentumData>('/tools/momentum_rebalance', null, {
      params: { top_n: topN },
      timeout: 120000,
    }).then((r) => r.data),
};

export const optionsApi = {
  getChain: (spot: number, expiryDays: number, strikeStep = 50) =>
    api.get<OptionChainData>('/options/chain', {
      params: { spot, expiry_days: expiryDays, strike_step: strikeStep },
    }).then((r) => r.data),
  calculateGreeks: (params: {
    spot: number;
    strike: number;
    expiry_days: number;
    rate?: number;
    volatility?: number;
    option_type?: string;
  }) =>
    api.post<GreeksResult & { status: string }>('/options/greeks', params).then((r) => r.data),
  calculatePayoff: (legs: PayoffLeg[], spotRange?: [number, number]) =>
    api.post<PayoffData & { status: string }>('/options/payoff', {
      legs,
      spot_min: spotRange?.[0],
      spot_max: spotRange?.[1],
    }).then((r) => r.data),
};

export const orderApi = {
  getStatus: () =>
    toolsApi.get<OrderStatus>('/tools/order_status', { timeout: 10000 }).then((r) => r.data),
  placeOrder: (order: PlaceOrderRequest) =>
    toolsApi.post<OrderResult>('/tools/place_order', order, { timeout: 10000 }).then((r) => r.data),
  cancelOrder: (orderId: string) =>
    toolsApi.post('/tools/cancel_order', { order_id: orderId }, { timeout: 10000 }).then((r) => r.data),
  closePosition: (ticker: string) =>
    toolsApi.post('/tools/close_position', { ticker }, { timeout: 10000 }).then((r) => r.data),
  closeAll: () =>
    toolsApi.post('/tools/close_all', null, { timeout: 10000 }).then((r) => r.data),
};

export { toolsApi };
export default api;
