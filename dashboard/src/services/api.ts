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
} from '../types';

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const message = error.response?.data?.detail || error.message;
    console.error('[API Error]', message);
    return Promise.reject(error);
  },
);

export const overviewApi = {
  getOverview: () => api.get<OverviewData>('/overview').then((r) => r.data),
};

export const signalApi = {
  getSignals: (limit = 50) => api.get<Signal[]>('/signals', { params: { limit } }).then((r) => r.data),
};

export const tradeApi = {
  getActiveTrades: () => api.get<ActiveTrade[]>('/trades/active').then((r) => r.data),
};

export const mwaApi = {
  getLatest: () => api.get<MWAScore>('/mwa/latest').then((r) => r.data),
};

export const watchlistApi = {
  getAll: (tier = 0) => api.get<WatchlistItem[]>('/watchlist', { params: { tier } }).then((r) => r.data),
  add: (data: { ticker: string; tier?: number; ltrp?: number; pivot_high?: number; timeframe?: string }) =>
    api.post<WatchlistItem>('/watchlist', null, { params: data }).then((r) => r.data),
  remove: (id: number) => api.delete(`/watchlist/${id}`).then((r) => r.data),
  toggle: (id: number) => api.patch<WatchlistItem>(`/watchlist/${id}/toggle`).then((r) => r.data),
};

export const accuracyApi = {
  getMetrics: () => api.get<AccuracyMetrics>('/accuracy').then((r) => r.data),
};

export const backtestApi = {
  run: (ticker: string, strategy: string, days: number) =>
    api.post<BacktestResult>('/backtest', { ticker, strategy, days }).then((r) => r.data),
  compareAll: (ticker: string, days: number) =>
    api.post<BacktestCompareResult>('/backtest/compare', { ticker, days }).then((r) => r.data),
};

export const engineApi = {
  detect: (engine: string, ticker: string, days: number) =>
    api.post<EngineDetectionResult>(`/engines/${engine}/detect`, { ticker, days }).then((r) => r.data),
  detectAll: (ticker: string, days: number) =>
    api.post<EngineDetectionResult[]>('/engines/detect-all', { ticker, days }).then((r) => r.data),
};

export default api;
