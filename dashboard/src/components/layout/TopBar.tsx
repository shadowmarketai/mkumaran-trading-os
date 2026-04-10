import { useLocation } from 'react-router-dom';
import { TrendingUp, TrendingDown, Wifi, WifiOff, LogOut, Menu, Bell } from 'lucide-react';
import { cn } from '../../lib/utils';
import type { MarketDirection } from '../../types';
import { useAuth } from '../../context/AuthContext';
import { useOverview } from '../../hooks/useOverview';
import SegmentTabs from './SegmentTabs';

const pageNames: Record<string, string> = {
  '/overview': 'Overview', '/trades': 'Active Trades', '/accuracy': 'Accuracy',
  '/watchlist': 'Watchlist', '/backtesting': 'Backtesting', '/engines': 'Pattern Engines',
  '/wallstreet': 'Wall Street AI', '/news': 'News & Macro', '/momentum': 'Momentum Ranking',
  '/options': 'Options Greeks', '/payoff': 'Payoff Calculator', '/paper': 'Paper Trading',
  '/monitor': 'Signal Monitor', '/market-movers': 'Market Movers',
};

function IndexPrice({ name, price, change, changePct }: { name: string; price: number; change: number; changePct: number }) {
  const isPositive = change >= 0;
  return (
    <div className="flex items-center gap-2.5">
      <span className="text-[10px] text-slate-400 font-semibold tracking-wider uppercase">{name}</span>
      <span className="text-sm font-mono font-bold text-slate-900 tabular-nums">
        {price.toLocaleString('en-IN', { minimumFractionDigits: 1 })}
      </span>
      <div className={cn(
        'flex items-center gap-0.5 text-xs font-mono tabular-nums px-1.5 py-0.5 rounded-md font-semibold',
        isPositive ? 'text-trading-bull bg-trading-bull-dim' : 'text-trading-bear bg-red-50'
      )}>
        {isPositive ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
        {isPositive ? '+' : ''}{changePct.toFixed(2)}%
      </div>
    </div>
  );
}

function DirectionBadge({ direction }: { direction: MarketDirection }) {
  const colorMap: Record<MarketDirection, string> = {
    BULL: 'bg-trading-bull-dim text-trading-bull',
    BEAR: 'bg-red-50 text-trading-bear',
    SIDEWAYS: 'bg-sky-50 text-trading-info',
    MILD_BULL: 'bg-emerald-50 text-emerald-600',
    MILD_BEAR: 'bg-rose-50 text-rose-500',
  };
  return (
    <span className={cn('px-2.5 py-1 rounded-lg text-[10px] font-mono font-bold tracking-wider', colorMap[direction])}>
      MWA {direction.replace('_', ' ')}
    </span>
  );
}

interface TopBarProps { onMenuClick?: () => void; }

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
      <header className="h-14 min-h-[56px] bg-white/80 backdrop-blur-xl border-b border-trading-border flex items-center justify-between px-3 md:px-6">
        <div className="flex items-center gap-3">
          <button onClick={onMenuClick} className="md:hidden p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-50 transition-colors">
            <Menu size={20} />
          </button>
          <h2 className="text-sm font-semibold text-slate-900">{currentPage}</h2>
        </div>

        <div className="hidden lg:flex items-center gap-6 px-4 py-1.5 rounded-xl bg-trading-bg-secondary border border-trading-border">
          <IndexPrice name="NIFTY" price={market.nifty_price} change={market.nifty_change} changePct={market.nifty_change_pct} />
          <div className="w-px h-5 bg-trading-border" />
          <IndexPrice name="BANKNIFTY" price={market.banknifty_price} change={market.banknifty_change} changePct={market.banknifty_change_pct} />
        </div>

        <div className="flex items-center gap-2 sm:gap-3">
          <div className="hidden sm:block"><DirectionBadge direction={mwaDir} /></div>
          <div className="flex items-center gap-1.5">
            {market.market_status === 'LIVE' ? (
              <><Wifi size={12} className="text-trading-bull" /><span className="text-[10px] font-mono font-semibold text-trading-bull">LIVE</span></>
            ) : (
              <><WifiOff size={12} className="text-slate-400" /><span className="text-[10px] font-mono text-slate-400">{market.market_status}</span></>
            )}
          </div>
          <div className="w-px h-5 bg-trading-border hidden sm:block" />
          <button className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-50 transition-colors hidden sm:block">
            <Bell size={15} />
          </button>
          <button onClick={logout} title={email ? `Sign out (${email})` : 'Sign out'}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs text-slate-400 hover:text-slate-600 hover:bg-slate-50 transition-colors">
            <LogOut size={13} /><span className="hidden lg:inline">Sign Out</span>
          </button>
        </div>
      </header>
      <SegmentTabs />
    </div>
  );
}
