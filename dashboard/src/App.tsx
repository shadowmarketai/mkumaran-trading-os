import { useState, useCallback } from 'react';
import { Routes, Route } from 'react-router-dom';
import Sidebar from './components/layout/Sidebar';
import TopBar from './components/layout/TopBar';
import ProtectedRoute from './components/ProtectedRoute';
import UpgradeGate from './components/ui/UpgradeGate';
import LandingPage from './pages/LandingPage';
import LoginPage from './pages/LoginPage';
import OverviewPage from './pages/OverviewPage';
import ActiveTradesPage from './pages/ActiveTradesPage';
import AccuracyPage from './pages/AccuracyPage';
import WatchlistPage from './pages/WatchlistPage';
import BacktestingPage from './pages/BacktestingPage';
import EnginesPage from './pages/EnginesPage';
import WallStreetPage from './pages/WallStreetPage';
import NewsPage from './pages/NewsPage';
import MomentumPage from './pages/MomentumPage';
import OptionsPage from './pages/OptionsPage';
import PayoffPage from './pages/PayoffPage';
import PaperTradingPage from './pages/PaperTradingPage';
import SignalMonitorPage from './pages/SignalMonitorPage';
import MarketMoversPage from './pages/MarketMoversPage';
import SettingsPage from './pages/SettingsPage';

function App() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const closeSidebar = useCallback(() => setSidebarOpen(false), []);
  const toggleSidebar = useCallback(() => setSidebarOpen((prev) => !prev), []);

  return (
    <Routes>
      {/* Public pages */}
      <Route path="/" element={<LandingPage />} />
      <Route path="/login" element={<LoginPage />} />

      {/* Protected dashboard */}
      <Route
        path="/*"
        element={
          <ProtectedRoute>
            <div className="flex h-screen overflow-hidden bg-trading-bg">
              <Sidebar isOpen={sidebarOpen} onClose={closeSidebar} />
              <div className="flex-1 flex flex-col overflow-hidden min-w-0">
                <TopBar onMenuClick={toggleSidebar} />
                <main className="flex-1 overflow-auto p-3 md:p-5">
                  <Routes>
                    {/* Free tier — open to all */}
                    <Route path="/overview" element={<OverviewPage />} />
                    <Route path="/market-movers" element={<UpgradeGate feature="market_movers"><MarketMoversPage /></UpgradeGate>} />
                    <Route path="/trades" element={<UpgradeGate feature="active_trades"><ActiveTradesPage /></UpgradeGate>} />
                    <Route path="/accuracy" element={<UpgradeGate feature="accuracy"><AccuracyPage /></UpgradeGate>} />
                    <Route path="/watchlist" element={<UpgradeGate feature="watchlist_view"><WatchlistPage /></UpgradeGate>} />
                    <Route path="/news" element={<UpgradeGate feature="news_macro"><NewsPage /></UpgradeGate>} />
                    <Route path="/options" element={<UpgradeGate feature="options_greeks"><OptionsPage /></UpgradeGate>} />
                    <Route path="/paper" element={<UpgradeGate feature="paper_trading"><PaperTradingPage /></UpgradeGate>} />
                    <Route path="/backtesting" element={<UpgradeGate feature="backtesting"><BacktestingPage /></UpgradeGate>} />

                    {/* Pro tier — gated */}
                    <Route path="/monitor" element={<UpgradeGate feature="signal_monitor"><SignalMonitorPage /></UpgradeGate>} />
                    <Route path="/engines" element={<UpgradeGate feature="pattern_engines"><EnginesPage /></UpgradeGate>} />
                    <Route path="/wallstreet" element={<UpgradeGate feature="wallstreet_ai"><WallStreetPage /></UpgradeGate>} />
                    <Route path="/momentum" element={<UpgradeGate feature="momentum"><MomentumPage /></UpgradeGate>} />
                    <Route path="/payoff" element={<UpgradeGate feature="payoff_calc"><PayoffPage /></UpgradeGate>} />
                    <Route path="/settings" element={<UpgradeGate feature="settings"><SettingsPage /></UpgradeGate>} />
                  </Routes>
                </main>
              </div>
            </div>
          </ProtectedRoute>
        }
      />
    </Routes>
  );
}

export default App;
