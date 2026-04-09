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
  Calculator,
  LineChart,
  FileText,
  Shield,
  BarChart3,
  X,
  ChevronLeft,
  ChevronRight,
  Wifi,
  WifiOff,
} from 'lucide-react';
import { useState } from 'react';
import { cn } from '../../lib/utils';
import { useOverview } from '../../hooks/useOverview';

interface NavItem {
  to: string;
  label: string;
  icon: React.ReactNode;
  group?: string;
}

const navItems: NavItem[] = [
  { to: '/overview', label: 'Overview', icon: <LayoutDashboard size={18} />, group: 'core' },
  { to: '/market-movers', label: 'Market Movers', icon: <BarChart3 size={18} />, group: 'core' },
  { to: '/trades', label: 'Active Trades', icon: <TrendingUp size={18} />, group: 'core' },
  { to: '/monitor', label: 'Signal Monitor', icon: <Shield size={18} />, group: 'core' },
  { to: '/paper', label: 'Paper Trading', icon: <FileText size={18} />, group: 'trading' },
  { to: '/accuracy', label: 'Accuracy', icon: <Target size={18} />, group: 'trading' },
  { to: '/watchlist', label: 'Watchlist', icon: <Eye size={18} />, group: 'trading' },
  { to: '/backtesting', label: 'Backtesting', icon: <FlaskConical size={18} />, group: 'analysis' },
  { to: '/engines', label: 'Pattern Engines', icon: <Cpu size={18} />, group: 'analysis' },
  { to: '/wallstreet', label: 'Wall Street AI', icon: <Brain size={18} />, group: 'analysis' },
  { to: '/news', label: 'News & Macro', icon: <Newspaper size={18} />, group: 'intel' },
  { to: '/momentum', label: 'Momentum', icon: <Rocket size={18} />, group: 'intel' },
  { to: '/options', label: 'Options Greeks', icon: <Calculator size={18} />, group: 'options' },
  { to: '/payoff', label: 'Payoff Calc', icon: <LineChart size={18} />, group: 'options' },
];

const groupLabels: Record<string, string> = {
  core: 'DASHBOARD',
  trading: 'TRADING',
  analysis: 'ANALYSIS',
  intel: 'INTELLIGENCE',
  options: 'OPTIONS',
};

function groupItems(items: NavItem[]): [string, NavItem[]][] {
  const groups: Record<string, NavItem[]> = {};
  for (const item of items) {
    const g = item.group || 'core';
    if (!groups[g]) groups[g] = [];
    groups[g].push(item);
  }
  return Object.entries(groups);
}

interface MarketStatusProps {
  status: 'PRE' | 'LIVE' | 'POST' | 'CLOSED';
}

function MarketStatusIndicator({ status }: MarketStatusProps) {
  const isLive = status === 'LIVE';
  const isPre = status === 'PRE';

  return (
    <div className="flex items-center gap-2.5 px-4 py-3">
      {isLive ? (
        <div className="relative">
          <Wifi size={14} className="text-trading-bull" />
          <span className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 bg-trading-bull rounded-full animate-pulse-live" />
        </div>
      ) : (
        <WifiOff size={14} className="text-slate-600" />
      )}
      <div className="flex flex-col">
        <span className="text-[10px] text-slate-500 uppercase tracking-wider">Market</span>
        <span className={cn(
          'text-xs font-mono font-semibold',
          isLive ? 'text-trading-bull' : isPre ? 'text-trading-alert' : 'text-slate-500'
        )}>
          {status}
        </span>
      </div>
    </div>
  );
}

interface SidebarProps {
  isOpen?: boolean;
  onClose?: () => void;
}

export default function Sidebar({ isOpen = false, onClose }: SidebarProps) {
  const { market } = useOverview(60000);
  const [collapsed, setCollapsed] = useState(false);
  const grouped = groupItems(navItems);

  return (
    <>
      {/* Mobile overlay */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/70 backdrop-blur-sm z-40 md:hidden"
          onClick={onClose}
        />
      )}

      {/* Sidebar */}
      <aside
        className={cn(
          'h-screen flex flex-col bg-sidebar-gradient z-50 transition-all duration-300 ease-out',
          'border-r border-trading-border/60',
          // Mobile: fixed drawer
          'fixed inset-y-0 left-0 md:relative md:translate-x-0',
          isOpen ? 'translate-x-0' : '-translate-x-full',
          // Width
          collapsed ? 'w-[68px] md:min-w-[68px]' : 'w-[260px] md:min-w-[260px]',
        )}
      >
        {/* Logo */}
        <div className={cn(
          'border-b border-trading-border/40 flex items-center',
          collapsed ? 'px-3 py-5 justify-center' : 'px-5 py-5 justify-between',
        )}>
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl gradient-ai flex items-center justify-center shadow-glow-ai flex-shrink-0">
              <Activity size={18} className="text-white" />
            </div>
            {!collapsed && (
              <div className="overflow-hidden">
                <h1 className="text-base font-bold text-white tracking-tight leading-none">MKUMARAN</h1>
                <p className="text-[10px] text-trading-ai-light tracking-widest uppercase mt-0.5">Trading OS</p>
              </div>
            )}
          </div>
          {/* Close button on mobile */}
          {!collapsed && (
            <button
              onClick={onClose}
              className="md:hidden p-1.5 rounded-lg text-slate-500 hover:text-white hover:bg-white/5 transition-colors"
            >
              <X size={18} />
            </button>
          )}
        </div>

        {/* Navigation */}
        <nav className={cn(
          'flex-1 py-3 overflow-y-auto',
          collapsed ? 'px-2' : 'px-3',
        )}>
          {grouped.map(([group, items]) => (
            <div key={group} className="mb-3">
              {!collapsed && (
                <p className="px-3 mb-1.5 text-[9px] font-semibold text-slate-600 uppercase tracking-[0.15em]">
                  {groupLabels[group]}
                </p>
              )}
              <div className="space-y-0.5">
                {items.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    onClick={onClose}
                    title={collapsed ? item.label : undefined}
                    className={({ isActive }) =>
                      cn(
                        'flex items-center gap-2.5 rounded-xl text-[13px] font-medium transition-all duration-200 group relative',
                        collapsed ? 'px-2.5 py-2.5 justify-center' : 'px-3 py-2',
                        isActive
                          ? 'bg-trading-ai/12 text-white shadow-inner-glow'
                          : 'text-slate-500 hover:text-slate-200 hover:bg-white/[0.03]'
                      )
                    }
                  >
                    {({ isActive }) => (
                      <>
                        {isActive && (
                          <div className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-4 rounded-r-full bg-trading-ai" />
                        )}
                        <span className={cn(
                          'flex-shrink-0 transition-colors',
                          isActive ? 'text-trading-ai-light' : 'text-slate-500 group-hover:text-slate-300'
                        )}>
                          {item.icon}
                        </span>
                        {!collapsed && <span>{item.label}</span>}
                      </>
                    )}
                  </NavLink>
                ))}
              </div>
            </div>
          ))}
        </nav>

        {/* Collapse Toggle (desktop) */}
        <div className="hidden md:flex items-center justify-center py-2 border-t border-trading-border/30">
          <button
            onClick={() => setCollapsed(!collapsed)}
            className="p-1.5 rounded-lg text-slate-600 hover:text-slate-300 hover:bg-white/5 transition-colors"
          >
            {collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
          </button>
        </div>

        {/* Market Status */}
        {!collapsed && (
          <div className="border-t border-trading-border/30">
            <MarketStatusIndicator status={market.market_status} />
          </div>
        )}
      </aside>
    </>
  );
}
