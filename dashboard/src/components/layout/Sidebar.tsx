import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  TrendingUp,
  Target,
  Eye,
  FlaskConical,
  Cpu,
  Activity,
  Brain,
  Newspaper,
  Rocket,
  X,
} from 'lucide-react';
import { cn } from '../../lib/utils';

interface NavItem {
  to: string;
  label: string;
  icon: React.ReactNode;
}

const navItems: NavItem[] = [
  { to: '/overview', label: 'Overview', icon: <LayoutDashboard size={20} /> },
  { to: '/trades', label: 'Active Trades', icon: <TrendingUp size={20} /> },
  { to: '/accuracy', label: 'Accuracy', icon: <Target size={20} /> },
  { to: '/watchlist', label: 'Watchlist', icon: <Eye size={20} /> },
  { to: '/backtesting', label: 'Backtesting', icon: <FlaskConical size={20} /> },
  { to: '/engines', label: 'Pattern Engines', icon: <Cpu size={20} /> },
  { to: '/wallstreet', label: 'Wall Street AI', icon: <Brain size={20} /> },
  { to: '/news', label: 'News & Macro', icon: <Newspaper size={20} /> },
  { to: '/momentum', label: 'Momentum', icon: <Rocket size={20} /> },
];

interface MarketStatusProps {
  status: 'PRE' | 'LIVE' | 'POST' | 'CLOSED';
}

function MarketStatusIndicator({ status }: MarketStatusProps) {
  const colorMap: Record<string, string> = {
    LIVE: 'bg-trading-bull',
    PRE: 'bg-trading-alert',
    POST: 'bg-trading-info',
    CLOSED: 'bg-slate-500',
  };

  const pulseMap: Record<string, string> = {
    LIVE: 'animate-pulse',
    PRE: 'animate-pulse',
    POST: '',
    CLOSED: '',
  };

  return (
    <div className="flex items-center gap-2 px-4 py-3">
      <div className={cn('w-2.5 h-2.5 rounded-full', colorMap[status], pulseMap[status])} />
      <span className="text-sm text-slate-400">
        Market: <span className="text-slate-200 font-medium">{status}</span>
      </span>
    </div>
  );
}

interface SidebarProps {
  isOpen?: boolean;
  onClose?: () => void;
}

export default function Sidebar({ isOpen = false, onClose }: SidebarProps) {
  return (
    <>
      {/* Mobile overlay */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/60 z-40 md:hidden"
          onClick={onClose}
        />
      )}

      {/* Sidebar */}
      <aside
        className={cn(
          'h-screen flex flex-col bg-[#0C1222] border-r border-trading-border z-50 transition-transform duration-300 ease-in-out',
          // Mobile: fixed drawer
          'fixed inset-y-0 left-0 w-[240px] md:relative md:translate-x-0',
          isOpen ? 'translate-x-0' : '-translate-x-full',
          // Desktop: always visible, static width
          'md:min-w-[240px]',
        )}
      >
        {/* Logo */}
        <div className="px-5 py-6 border-b border-trading-border flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg gradient-ai flex items-center justify-center">
              <Activity size={20} className="text-white" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-white tracking-tight">MKUMARAN</h1>
              <p className="text-xs text-slate-400 -mt-0.5">Trading OS</p>
            </div>
          </div>
          {/* Close button on mobile */}
          <button
            onClick={onClose}
            className="md:hidden p-1 rounded-md text-slate-400 hover:text-white hover:bg-slate-700/50 transition-colors"
          >
            <X size={20} />
          </button>
        </div>

        {/* Navigation */}
        <nav className="flex-1 py-4 px-3 space-y-1 overflow-y-auto">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              onClick={onClose}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-200',
                  isActive
                    ? 'bg-trading-card text-white border-l-2 border-trading-ai'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-trading-card/50 border-l-2 border-transparent'
                )
              }
            >
              {item.icon}
              {item.label}
            </NavLink>
          ))}
        </nav>

        {/* Market Status */}
        <div className="border-t border-trading-border">
          <MarketStatusIndicator status="CLOSED" />
        </div>
      </aside>
    </>
  );
}
