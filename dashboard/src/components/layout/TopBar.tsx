import { useLocation } from 'react-router-dom';
import { TrendingUp, TrendingDown, Wifi, WifiOff, LogOut, Menu, Bell } from 'lucide-react';
import { cn } from '../../lib/utils';
import type { MarketDirection } from '../../types';
import { useAuth } from '../../context/AuthContext';
import { useOverview } from '../../hooks/useOverview';
import SegmentTabs from './SegmentTabs';

const pageNames: Record<string, string> = {
  '/overview': 'Overview',
  '/trades': 'Active Trades',
  '/accuracy': 'Accuracy',
  '/watchlist': 'Watchlist',
  '/backtesting': 'Backtesting',
  '/engines': 'Pattern Engines',
  '/wallstreet': 'Wall Street AI',
  '/news': 'News & Macro',
  '/momentum': 'Momentum Ranking',
  '/options': 'Options Greeks',
  '/payoff': 'Payoff Calculator',
  '/paper': 'Paper Trading',
  '/monitor': 'Signal Monitor',
  '/market-movers': 'Market Movers',
};

interface IndexPriceProps {
  name: string;
  price: number;
  change: number;
  changePct: number;
}

function IndexPrice({ name, price, change, changePct }: IndexPriceProps) {
  const isPositive = change >= 0;
  return (
    <div className="flex items-center gap-2.5">
      <span className="text-[10px] text-slate-500 font-semibold tracking-wider uppercase">{name}</span>
      <span className="text-sm font-mono font-bold text-white tabular-nums">
        {price.toLocaleString('en-IN', { minimumFractionDigits: 1 })}
      </span>
      <div className={cn(
        'flex items-center gap-0.5 text-xs font-mono tabular-nums px-1.5 py-0.5 rounded-md',
        isPositive
          ? 'text-trading-bull bg-trading-bull/8'
          : 'text-trading-bear bg-trading-bear/8'
      )}>
        {isPositive ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
        <span className="font-semibold">{isPositive ? '+' : ''}{changePct.toFixed(2)}%</span>
      </div>
    </div>
  );
}

interface DirectionBadgeProps {
  direction: MarketDirection;
}

function DirectionBadge({ direction }: DirectionBadgeProps) {
  const colorMap: Record<MarketDirection, string> = {
    BULL: 'bg-trading-bull/10 text-trading-bull border-trading-bull/20',
    BEAR: 'bg-trading-bear/10 text-trading-bear border-trading-bear/20',
    SIDEWAYS: 'bg-trading-info/10 text-trading-info border-trading-info/20',
    MILD_BULL: 'bg-trading-bull/8 text-trading-bull-light border-trading-bull-light/15',
    MILD_BEAR: 'bg-trading-bear/8 text-trading-bear-light border-trading-bear-light/15',
  };

  return (
    <span className={cn(
      'px-2.5 py-1 rounded-lg text-[10px] font-mono font-bold border tracking-wider',
      colorMap[direction]
    )}>
      MWA {direction.replace('_', ' ')}
    </span>
  );
}

interface MarketStatusLabelProps {
  status: 'PRE' | 'LIVE' | 'POST' | 'CLOSED';
}

function MarketStatusLabel({ status }: MarketStatusLabelProps) {
  const isLive = status === 'LIVE';
  return (
    <div className="flex items-center gap-1.5">
      {isLive ? (
        <div className="relative">
          <Wifi size={12} className="text-trading-bull" />
          <span className="absolute -top-0.5 -right-0.5 w-1 h-1 bg-trading-bull rounded-full animate-pulse-live" />
        </div>
      ) : (
        <WifiOff size={12} className="text-slate-600" />
      )}
      <span className={cn(
        'text-[10px] font-mono font-semibold tracking-wider',
        status === 'LIVE' ? 'text-trading-bull' : status === 'PRE' ? 'text-trading-alert' : 'text-slate-600'
      )}>
        {status}
      </span>
    </div>
  );
}

interface TopBarProps {
  onMenuClick?: () => void;
}

export default function TopBar({ onMenuClick }: TopBarProps) {
  const location = useLocation();
  const currentPage = pageNames[location.pathname] || 'Dashboard';
  const { logout, email } = useAuth();
  const { market } = useOverview(60000);

  const validDirs: MarketDirection[] = ['BULL', 'BEAR', 'SIDEWAYS', 'MILD_BULL', 'MILD_BEAR'];
  const rawDir = market.mwa_direction || 'SIDEWAYS';
  const mwaDir: MarketDirection = validDirs.includes(rawDir as MarketDirection) ? (rawDir as MarketDirection) : 'SIDEWAYS';

  return (
    <div className="sticky top-0 z-30">
      <header className="h-14 min-h-[56px] bg-trading-bg/80 backdrop-blur-xl border-b border-trading-border/40 flex items-center justify-between px-3 md:px-6">
        {/* Left: Hamburger + Page Title */}
        <div className="flex items-center gap-3">
          <button
            onClick={onMenuClick}
            className="md:hidden p-1.5 rounded-lg text-slate-500 hover:text-white hover:bg-white/5 transition-colors"
          >
            <Menu size={20} />
          </button>
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold text-white">{currentPage}</h2>
          </div>
        </div>

        {/* Center: Index Prices (hidden on mobile) */}
        <div className="hidden lg:flex items-center gap-6 px-4 py-1.5 rounded-xl bg-trading-card/50 border border-trading-border/30">
          <IndexPrice name="NIFTY" price={market.nifty_price} change={market.nifty_change} changePct={market.nifty_change_pct} />
          <div className="w-px h-5 bg-trading-border/40" />
          <IndexPrice name="BANKNIFTY" price={market.banknifty_price} change={market.banknifty_change} changePct={market.banknifty_change_pct} />
        </div>

        {/* Right: Controls */}
        <div className="flex items-center gap-2 sm:gap-3">
          <div className="hidden sm:block">
            <DirectionBadge direction={mwaDir} />
          </div>
          <MarketStatusLabel status={market.market_status} />
          <div className="w-px h-5 bg-trading-border/30 hidden sm:block" />
          <button className="p-1.5 rounded-lg text-slate-500 hover:text-white hover:bg-white/5 transition-colors relative hidden sm:block">
            <Bell size={15} />
          </button>
          <button
            onClick={logout}
            title={email ? `Sign out (${email})` : 'Sign out'}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs text-slate-500 hover:text-white hover:bg-white/5 transition-colors"
          >
            <LogOut size={13} />
            <span className="hidden lg:inline">Sign Out</span>
          </button>
        </div>
      </header>
      <SegmentTabs />
    </div>
  );
}
