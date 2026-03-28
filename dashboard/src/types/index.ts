export type MarketSegment = 'ALL' | 'NSE_EQUITY' | 'FNO' | 'COMMODITY' | 'FOREX';
export type TimeframeCategory = 'ALL' | 'INTRADAY' | 'SWING' | 'POSITIONAL';
export type Exchange = 'NSE' | 'BSE' | 'MCX' | 'CDS' | 'NFO';
export type AssetClass = 'EQUITY' | 'COMMODITY' | 'CURRENCY' | 'FNO';

export interface SegmentFilter {
  exchange?: string;
  asset_class?: string;
  timeframe?: string;
}

export interface WatchlistItem {
  id: number;
  ticker: string;
  name: string;
  exchange: string;
  asset_class: string;
  timeframe: string;
  tier: number;
  ltrp: number | null;
  pivot_high: number | null;
  active: boolean;
  source: string;
  added_at: string;
  added_by: string;
  notes: string | null;
}

export interface Signal {
  id: number;
  signal_date: string;
  signal_time: string | null;
  ticker: string;
  exchange: string;
  asset_class: string;
  timeframe: string;
  direction: 'LONG' | 'SHORT';
  pattern: string;
  entry_price: number;
  stop_loss: number;
  target: number;
  rrr: number;
  qty: number;
  risk_amt: number;
  ai_confidence: number;
  tv_confirmed: boolean;
  mwa_score: string;
  scanner_count: number;
  tier: number;
  source: string;
  status: 'OPEN' | 'WIN' | 'LOSS' | 'EXPIRED';
}

export interface Outcome {
  id: number;
  signal_id: number;
  exit_date: string;
  exit_price: number;
  outcome: 'WIN' | 'LOSS';
  pnl_amount: number;
  days_held: number;
  exit_reason: 'TARGET' | 'STOPLOSS' | 'MANUAL';
}

export interface MWAScore {
  id: number;
  score_date: string;
  direction: 'BULL' | 'BEAR' | 'SIDEWAYS' | 'MILD_BULL' | 'MILD_BEAR';
  bull_score: number;
  bear_score: number;
  bull_pct: number;
  bear_pct: number;
  scanner_results: Record<string, ScannerResult>;
  promoted_stocks: string[];
  fii_net: number;
  dii_net: number;
  sector_strength: Record<string, 'STRONG' | 'NEUTRAL' | 'WEAK'>;
}

export interface ScannerResult {
  name: string;
  group: string;
  weight: number;
  count: number;
  direction: 'BULL' | 'BEAR' | 'NEUTRAL';
  stocks: string[];
}

export interface ActiveTrade {
  id: number;
  signal_id: number;
  ticker: string;
  exchange: string;
  asset_class: string;
  timeframe: string;
  entry_price: number;
  target: number;
  stop_loss: number;
  prrr: number;
  current_price: number;
  crrr: number;
  last_updated: string;
  alert_sent: boolean;
  direction: 'LONG' | 'SHORT';
  pnl_pct: number;
}

export interface AccuracyMetrics {
  total_signals: number;
  wins: number;
  losses: number;
  open: number;
  win_rate: number;
  target_rate: number;
  total_pnl: number;
  avg_rrr: number;
  by_pattern: PatternAccuracy[];
  by_direction: DirectionAccuracy[];
  monthly_pnl: MonthlyPnL[];
}

export interface PatternAccuracy {
  pattern: string;
  total: number;
  wins: number;
  win_rate: number;
}

export interface DirectionAccuracy {
  direction: 'LONG' | 'SHORT';
  total: number;
  wins: number;
  win_rate: number;
}

export interface MonthlyPnL {
  month: string;
  pnl: number;
  trades: number;
  win_rate: number;
}

export interface BacktestResult {
  strategy: string;
  ticker: string;
  period: string;
  total_trades: number;
  win_rate: number;
  max_drawdown: number;
  profit_factor: number;
  sharpe_ratio: number;
  total_return: number;
  equity_curve: EquityPoint[];
  per_pattern?: Record<string, PatternBreakdown>;
  per_source?: Record<string, PatternBreakdown>;
}

export interface EquityPoint {
  date: string;
  equity: number;
  drawdown: number;
}

export interface PatternBreakdown {
  total: number;
  wins: number;
  win_rate: number;
}

export interface StrategyComparison {
  strategy: string;
  total_trades: number;
  win_rate: number;
  max_drawdown: number;
  profit_factor: number;
  sharpe_ratio: number;
  total_return: number;
}

export interface BacktestCompareResult {
  ticker: string;
  period: string;
  strategies: StrategyComparison[];
  best_strategy: string;
}

export interface EnginePattern {
  name: string;
  direction: 'BULLISH' | 'BEARISH' | 'CONTINUATION';
  confidence: number;
  description: string;
}

export interface EngineDetectionResult {
  engine: string;
  ticker: string;
  patterns: EnginePattern[];
}

export interface OverviewData {
  mwa: MWAScore | null;
  signals_today: Signal[];
  active_trades_count: number;
  market_status: 'PRE' | 'LIVE' | 'POST' | 'CLOSED';
  nifty_price: number;
  banknifty_price: number;
}

export type MarketDirection = 'BULL' | 'BEAR' | 'SIDEWAYS' | 'MILD_BULL' | 'MILD_BEAR';
export type TradeStatus = 'OPEN' | 'WIN' | 'LOSS' | 'EXPIRED';
export type SectorStrength = 'STRONG' | 'NEUTRAL' | 'WEAK';
