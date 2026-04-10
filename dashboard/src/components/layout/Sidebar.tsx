import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard, TrendingUp, Target, Eye, FlaskConical, Cpu, Activity,
  Brain, Newspaper, Rocket, Calculator, LineChart, FileText, Shield,
  BarChart3, X, ChevronLeft, ChevronRight, Wifi, WifiOff,
} from 'lucide-react';
import { useState } from 'react';
import { cn } from '../../lib/utils';
import { useOverview } from '../../hooks/useOverview';

interface NavItem { to: string; label: string; icon: React.ReactNode; group?: string; }

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
  core: 'DASHBOARD', trading: 'TRADING', analysis: 'ANALYSIS', intel: 'INTELLIGENCE', options: 'OPTIONS',
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

interface SidebarProps { isOpen?: boolean; onClose?: () => void; }

export default function Sidebar({ isOpen = false, onClose }: SidebarProps) {
  const { market } = useOverview(60000);
  const [collapsed, setCollapsed] = useState(false);
  const grouped = groupItems(navItems);

  return (
    <>
      {isOpen && <div className="fixed inset-0 bg-black/20 backdrop-blur-sm z-40 md:hidden" onClick={onClose} />}

      <aside className={cn(
        'h-screen flex flex-col bg-white border-r border-trading-border z-50 transition-all duration-300 ease-out',
        'fixed inset-y-0 left-0 md:relative md:translate-x-0',
        isOpen ? 'translate-x-0' : '-translate-x-full',
        collapsed ? 'w-[68px] md:min-w-[68px]' : 'w-[260px] md:min-w-[260px]',
      )}>
        {/* Logo */}
        <div className={cn(
          'border-b border-trading-border flex items-center',
          collapsed ? 'px-3 py-5 justify-center' : 'px-5 py-5 justify-between',
        )}>
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl gradient-ai flex items-center justify-center shadow-brand flex-shrink-0">
              <Activity size={18} className="text-white" />
            </div>
            {!collapsed && (
              <div className="overflow-hidden">
                <h1 className="text-base font-bold text-slate-900 tracking-tight leading-none">Shadow Market</h1>
                <p className="text-[9px] text-trading-ai tracking-[0.2em] uppercase mt-0.5">AI Trading Intelligence</p>
              </div>
            )}
          </div>
          {!collapsed && (
            <button onClick={onClose} className="md:hidden p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-50 transition-colors">
              <X size={18} />
            </button>
          )}
        </div>

        {/* Navigation */}
        <nav className={cn('flex-1 py-3 overflow-y-auto', collapsed ? 'px-2' : 'px-3')}>
          {grouped.map(([group, items]) => (
            <div key={group} className="mb-3">
              {!collapsed && (
                <p className="px-3 mb-1.5 text-[9px] font-semibold text-slate-400 uppercase tracking-[0.15em]">
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
                    className={({ isActive }) => cn(
                      'flex items-center gap-2.5 rounded-xl text-[13px] font-medium transition-all duration-200 group relative',
                      collapsed ? 'px-2.5 py-2.5 justify-center' : 'px-3 py-2',
                      isActive
                        ? 'bg-trading-ai-bg text-trading-ai font-semibold'
                        : 'text-slate-500 hover:text-slate-700 hover:bg-slate-50'
                    )}
                  >
                    {({ isActive }) => (
                      <>
                        {isActive && <div className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-4 rounded-r-full bg-trading-ai" />}
                        <span className={cn('flex-shrink-0', isActive ? 'text-trading-ai' : 'text-slate-400 group-hover:text-slate-600')}>
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

        {/* Collapse Toggle */}
        <div className="hidden md:flex items-center justify-center py-2 border-t border-trading-border">
          <button onClick={() => setCollapsed(!collapsed)} className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-50 transition-colors">
            {collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
          </button>
        </div>

        {/* Market Status */}
        {!collapsed && (
          <div className="border-t border-trading-border flex items-center gap-2.5 px-4 py-3">
            {market.market_status === 'LIVE' ? (
              <><Wifi size={14} className="text-trading-bull" /><span className="text-xs text-trading-bull font-semibold">LIVE</span></>
            ) : (
              <><WifiOff size={14} className="text-slate-400" /><span className="text-xs text-slate-400">{market.market_status}</span></>
            )}
          </div>
        )}
      </aside>
    </>
  );
}
