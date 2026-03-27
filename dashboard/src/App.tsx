import { Routes, Route, Navigate } from 'react-router-dom';
import Sidebar from './components/layout/Sidebar';
import TopBar from './components/layout/TopBar';
import OverviewPage from './pages/OverviewPage';
import ActiveTradesPage from './pages/ActiveTradesPage';
import AccuracyPage from './pages/AccuracyPage';
import WatchlistPage from './pages/WatchlistPage';
import BacktestingPage from './pages/BacktestingPage';
import EnginesPage from './pages/EnginesPage';
import WallStreetPage from './pages/WallStreetPage';

function App() {
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <TopBar />
        <main className="flex-1 overflow-auto p-6">
          <Routes>
            <Route path="/" element={<Navigate to="/overview" replace />} />
            <Route path="/overview" element={<OverviewPage />} />
            <Route path="/trades" element={<ActiveTradesPage />} />
            <Route path="/accuracy" element={<AccuracyPage />} />
            <Route path="/watchlist" element={<WatchlistPage />} />
            <Route path="/backtesting" element={<BacktestingPage />} />
            <Route path="/engines" element={<EnginesPage />} />
            <Route path="/wallstreet" element={<WallStreetPage />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}

export default App;
