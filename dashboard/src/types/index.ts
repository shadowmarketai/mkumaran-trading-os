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
  direction: 'LONG' | 'SHORT' | 'BUY' | 'SELL';
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
  direction: 'LONG' | 'SHORT' | 'BUY' | 'SELL';
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
  equity_curves?: Record<string, EquityPoint[]>;
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
  nifty_change: number;
  nifty_change_pct: number;
  banknifty_price: number;
  banknifty_change: number;
  banknifty_change_pct: number;
  mwa_direction: string;
  // from backend overview endpoint
  watchlist_count: number;
  active_trades: number;
  total_signals: number;
  today_signals: number;
  mwa_bull_pct: number;
  mwa_bear_pct: number;
  win_rate: number;
  total_outcomes: number;
}

export interface NewsItem {
  title: string;
  source: string;
  url: string;
  published: string;
  impact: 'HIGH' | 'MEDIUM' | 'LOW';
  category: 'POLICY' | 'MACRO' | 'GEOPOLITICAL' | 'REGULATORY' | 'MARKET' | 'GENERAL';
  matched_keywords: string[];
  summary: string;
}

// ── Options Greeks ────────────────────────────────────────
export interface GreeksResult {
  price: number;
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
  rho: number;
  iv: number;
  market_price?: number;
}

export interface OptionStrike {
  strike: number;
  is_atm: boolean;
  ce: GreeksResult;
  pe: GreeksResult;
}

export interface OptionChainData {
  spot: number;
  expiry_days: number;
  atm_strike: number;
  strikes_count: number;
  chain: OptionStrike[];
}

// ── Options Payoff ────────────────────────────────────────
export interface PayoffLeg {
  strike: number;
  premium: number;
  qty: number;
  option_type: 'CE' | 'PE';
  action: 'BUY' | 'SELL';
}

export interface PayoffPoint {
  spot: number;
  pnl: number;
}

export interface PayoffData {
  points: PayoffPoint[];
  breakevens: number[];
  max_profit: number;
  max_loss: number;
  net_premium: number;
}

// ── Paper Trading ────────────────────────────────────────
export interface PlaceOrderRequest {
  ticker: string;
  direction: 'BUY' | 'SELL';
  qty: number;
  price: number;
  stop_loss?: number;
  target?: number;
}

export interface OrderResult {
  success: boolean;
  order_id: string;
  message: string;
  ticker: string;
  direction: string;
  qty: number;
  price: number;
  timestamp: string;
}

export interface PaperPosition {
  order_id: string;
  ticker: string;
  direction: string;
  qty: number;
  entry_price: number;
  stop_loss: number;
  trail_active: boolean;
  partial_exits: number;
}

export interface OrderStatus {
  paper_mode: boolean;
  open_positions: number;
  max_positions: number;
  kill_switch_active: boolean;
  kill_switch_reason: string;
  daily_pnl: number;
  capital: number;
  kite_connected: boolean;
  orders_today: number;
  positions: PaperPosition[];
}

// ── Pre-Trade Checklist ──────────────────────────────────────
export interface PreTradeCheck {
  name: string;
  status: 'PASS' | 'WARN' | 'FAIL';
  detail: string;
}

export interface PreTradeResult {
  signal_id: number;
  ticker: string;
  direction: string;
  verdict: 'GO' | 'CAUTION' | 'BLOCK';
  checks: PreTradeCheck[];
  pass_count: number;
  warn_count: number;
  fail_count: number;
  error?: string;
}

// ── Market Movers ────────────────────────────────────────
export interface MarketMoverStock {
  ticker: string;
  exchange: string;
  ltp: number;
  change: number;
  pct_change: number;
  open: number;
  high: number;
  low: number;
  prev_close: number;
  volume: number;
}

export type MarketMoverCategory = 'gainers' | 'losers' | 'week52_high' | 'week52_low' | 'most_active';

export interface MarketMoversData {
  category: MarketMoverCategory;
  exchange: string;
  stocks: MarketMoverStock[];
  total: number;
  fetched_at: string | null;
  total_universe: number;
}

export type MarketDirection = 'BULL' | 'BEAR' | 'SIDEWAYS' | 'MILD_BULL' | 'MILD_BEAR';
export type TradeStatus = 'OPEN' | 'WIN' | 'LOSS' | 'EXPIRED';
export type SectorStrength = 'STRONG' | 'NEUTRAL' | 'WEAK';

// ── Momentum Ranking ──────────────────────────────────────
export interface MomentumStock {
  rank: number;
  ticker: string;
  sector: string;
  score: number;
  ret_3m: number;
  ret_6m: number;
  ret_12m: number;
  volatility: number;
  prev_rank: number | null;
}

export interface RebalanceSignal {
  ticker: string;
  sector: string;
  action: 'BUY' | 'SELL';
  score: number;
  reason: string;
}

export interface MomentumData {
  ranked_at: string | null;
  top_n: number;
  holdings: string[];
  rankings: MomentumStock[];
  signals: RebalanceSignal[];
  message?: string;
}

// ── MWA Signal Cards ────────────────────────────────────────
export interface MWASignalCard {
  ticker: string;
  direction: 'LONG' | 'SHORT';
  entry: number;
  sl: number;
  target: number;
  rrr: number;
  qty: number;
  confidence: number;
  recommendation: string;
  signal_id: string;
}

// ── Signal Monitor ──────────────────────────────────────────
export interface ClosedSignal {
  signal_id: number;
  ticker: string;
  direction: string;
  status: 'TARGET_HIT' | 'SL_HIT';
  entry: number;
  exit: number;
  pnl_pct: number;
  pnl_rs: number;
  outcome: 'WIN' | 'LOSS';
  days_held: number;
}

export interface CheckSignalsResult {
  checked: boolean;
  closed_count: number;
  closed_signals: ClosedSignal[];
}

// ── Chart OHLCV ──────────────────────────────────────────────
export interface OHLCVBar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}
