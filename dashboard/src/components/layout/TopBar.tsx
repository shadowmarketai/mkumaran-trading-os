import { useLocation } from 'react-router-dom';
import { TrendingUp, TrendingDown, Wifi, WifiOff, LogOut, Menu } from 'lucide-react';
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
    <div className="flex items-center gap-2">
      <span className="text-xs text-slate-400 font-medium">{name}</span>
      <span className="text-sm font-mono font-semibold text-white">
        {price.toLocaleString('en-IN', { minimumFractionDigits: 1 })}
      </span>
      <div className={cn('flex items-center gap-0.5 text-xs font-mono', isPositive ? 'text-trading-bull' : 'text-trading-bear')}>
        {isPositive ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
        <span>{isPositive ? '+' : ''}{change.toFixed(1)}</span>
        <span className="text-slate-500">({isPositive ? '+' : ''}{changePct.toFixed(2)}%)</span>
      </div>
    </div>
  );
}

interface DirectionBadgeProps {
  direction: MarketDirection;
}

function DirectionBadge({ direction }: DirectionBadgeProps) {
  const colorMap: Record<MarketDirection, string> = {
    BULL: 'bg-trading-bull/20 text-trading-bull border-trading-bull/30',
    BEAR: 'bg-trading-bear/20 text-trading-bear border-trading-bear/30',
    SIDEWAYS: 'bg-trading-info/20 text-trading-info border-trading-info/30',
    MILD_BULL: 'bg-trading-bull-light/20 text-trading-bull-light border-trading-bull-light/30',
    MILD_BEAR: 'bg-trading-bear/15 text-rose-400 border-rose-400/30',
  };

  return (
    <span
      className={cn(
        'px-2.5 py-1 rounded-md text-xs font-mono font-semibold border',
        colorMap[direction]
      )}
    >
      MWA: {direction.replace('_', ' ')}
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
        <Wifi size={14} className="text-trading-bull" />
      ) : (
        <WifiOff size={14} className="text-slate-500" />
      )}
      <span
        className={cn(
          'text-xs font-medium',
          status === 'LIVE' ? 'text-trading-bull' : status === 'PRE' ? 'text-trading-alert' : 'text-slate-500'
        )}
      >
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
      <header className="h-14 min-h-[56px] glass-card rounded-none border-x-0 border-t-0 flex items-center justify-between px-3 md:px-6">
        {/* Left: Hamburger + Breadcrumb */}
        <div className="flex items-center gap-2">
          <button
            onClick={onMenuClick}
            className="md:hidden p-1.5 rounded-md text-slate-400 hover:text-white hover:bg-slate-700/50 transition-colors"
          >
            <Menu size={20} />
          </button>
          <span className="text-slate-500 text-sm hidden sm:inline">Dashboard</span>
          <span className="text-slate-600 hidden sm:inline">/</span>
          <span className="text-white text-sm font-medium">{currentPage}</span>
        </div>

        {/* Center: Index Prices (hidden on mobile) */}
        <div className="hidden md:flex items-center gap-6">
          <IndexPrice name="NIFTY" price={market.nifty_price} change={market.nifty_change} changePct={market.nifty_change_pct} />
          <div className="w-px h-5 bg-trading-border" />
          <IndexPrice name="BANKNIFTY" price={market.banknifty_price} change={market.banknifty_change} changePct={market.banknifty_change_pct} />
        </div>

        {/* Right: MWA + Market Status + Sign Out */}
        <div className="flex items-center gap-2 sm:gap-4">
          <div className="hidden sm:block">
            <DirectionBadge direction={mwaDir} />
          </div>
          <MarketStatusLabel status={market.market_status} />
          <button
            onClick={logout}
            title={email ? `Sign out (${email})` : 'Sign out'}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs text-slate-400 hover:text-white hover:bg-slate-700/50 transition-colors"
          >
            <LogOut size={14} />
            <span className="hidden lg:inline">Sign Out</span>
          </button>
        </div>
      </header>
      <SegmentTabs />
    </div>
  );
}
