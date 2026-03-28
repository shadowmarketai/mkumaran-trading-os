import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { MarketSegmentProvider } from './context/MarketSegmentContext';
import App from './App';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <MarketSegmentProvider>
        <App />
      </MarketSegmentProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
