import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import { MarketSegmentProvider } from './context/MarketSegmentContext';
import { TierProvider } from './context/TierContext';
import App from './App';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <MarketSegmentProvider>
          <TierProvider>
            <App />
          </TierProvider>
        </MarketSegmentProvider>
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
