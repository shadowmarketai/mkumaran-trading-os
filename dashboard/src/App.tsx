import { useState, useCallback } from 'react';
import { Routes, Route } from 'react-router-dom';
import Sidebar from './components/layout/Sidebar';
import TopBar from './components/layout/TopBar';
import ProtectedRoute from './components/ProtectedRoute';
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
      <Route path="/" element={<LandingPage />} />
      <Route path="/login" element={<LoginPage />} />
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
                    <Route path="/overview" element={<OverviewPage />} />
                    <Route path="/market-movers" element={<MarketMoversPage />} />
                    <Route path="/trades" element={<ActiveTradesPage />} />
                    <Route path="/accuracy" element={<AccuracyPage />} />
                    <Route path="/watchlist" element={<WatchlistPage />} />
                    <Route path="/backtesting" element={<BacktestingPage />} />
                    <Route path="/engines" element={<EnginesPage />} />
                    <Route path="/wallstreet" element={<WallStreetPage />} />
                    <Route path="/news" element={<NewsPage />} />
                    <Route path="/momentum" element={<MomentumPage />} />
                    <Route path="/options" element={<OptionsPage />} />
                    <Route path="/payoff" element={<PayoffPage />} />
                    <Route path="/paper" element={<PaperTradingPage />} />
                    <Route path="/monitor" element={<SignalMonitorPage />} />
                    <Route path="/settings" element={<SettingsPage />} />
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
