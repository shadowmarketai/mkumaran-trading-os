import { useEffect, useRef, useState, useCallback } from 'react';
import { createChart, ColorType, CrosshairMode } from 'lightweight-charts';
import type { IChartApi, ISeriesApi, CandlestickData, HistogramData } from 'lightweight-charts';
import { chartApi } from '../../services/api';
import type { OHLCVBar } from '../../types';
import { Loader2 } from 'lucide-react';

interface SignalOverlay {
  entry: number;
  sl: number;
  target: number;
  direction: 'LONG' | 'SHORT' | 'BUY' | 'SELL';
}

interface CandlestickChartProps {
  ticker: string;
  interval?: string;
  signal?: SignalOverlay;
  height?: number;
}

const TIMEFRAMES = ['5m', '15m', '1H', '1D'] as const;

export default function CandlestickChart({
  ticker,
  interval: initialInterval = '1D',
  signal,
  height = 400,
}: CandlestickChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const [activeInterval, setActiveInterval] = useState(initialInterval);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const daysForInterval = (iv: string) => {
    switch (iv) {
      case '5m': return 5;
      case '15m': return 10;
      case '1H': return 30;
      case '1D': return 180;
      default: return 30;
    }
  };

  const fetchAndRender = useCallback(async (iv: string) => {
    if (!chartContainerRef.current) return;
    setLoading(true);
    setError(null);

    try {
      const bars: OHLCVBar[] = await chartApi.getOHLCV(ticker, iv, daysForInterval(iv));
      if (!bars || bars.length === 0) {
        setError('No chart data available');
        setLoading(false);
        return;
      }

      // Destroy previous chart
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }

      const chart = createChart(chartContainerRef.current, {
        width: chartContainerRef.current.clientWidth,
        height,
        layout: {
          background: { type: ColorType.Solid, color: 'transparent' },
          textColor: '#94a3b8',
          fontSize: 11,
        },
        grid: {
          vertLines: { color: 'rgba(51, 65, 85, 0.3)' },
          horzLines: { color: 'rgba(51, 65, 85, 0.3)' },
        },
        crosshair: { mode: CrosshairMode.Normal },
        rightPriceScale: {
          borderColor: 'rgba(51, 65, 85, 0.5)',
          scaleMargins: { top: 0.1, bottom: 0.25 },
        },
        timeScale: {
          borderColor: 'rgba(51, 65, 85, 0.5)',
          timeVisible: iv !== '1D',
          secondsVisible: false,
        },
      });

      chartRef.current = chart;

      // Candlestick series
      const candleSeries = chart.addCandlestickSeries({
        upColor: '#22c55e',
        downColor: '#ef4444',
        borderUpColor: '#22c55e',
        borderDownColor: '#ef4444',
        wickUpColor: '#22c55e',
        wickDownColor: '#ef4444',
      });

      const candleData: CandlestickData[] = bars.map((b) => ({
        time: b.time as CandlestickData['time'],
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
      }));
      candleSeries.setData(candleData);
      candleSeriesRef.current = candleSeries;

      // Volume histogram
      const volumeSeries = chart.addHistogramSeries({
        color: '#3b82f680',
        priceFormat: { type: 'volume' },
        priceScaleId: 'volume',
      });

      chart.priceScale('volume').applyOptions({
        scaleMargins: { top: 0.8, bottom: 0 },
      });

      const volumeData: HistogramData[] = bars.map((b) => ({
        time: b.time as HistogramData['time'],
        value: b.volume,
        color: b.close >= b.open ? '#22c55e40' : '#ef444440',
      }));
      volumeSeries.setData(volumeData);
      volumeSeriesRef.current = volumeSeries;

      // Signal overlay lines
      if (signal) {
        // Entry line (blue)
        candleSeries.createPriceLine({
          price: signal.entry,
          color: '#3b82f6',
          lineWidth: 2,
          lineStyle: 0, // Solid
          axisLabelVisible: true,
          title: `Entry ${signal.entry.toFixed(1)}`,
        });

        // Stop loss line (red dashed)
        candleSeries.createPriceLine({
          price: signal.sl,
          color: '#ef4444',
          lineWidth: 1,
          lineStyle: 2, // Dashed
          axisLabelVisible: true,
          title: `SL ${signal.sl.toFixed(1)}`,
        });

        // Target line (green dashed)
        candleSeries.createPriceLine({
          price: signal.target,
          color: '#22c55e',
          lineWidth: 1,
          lineStyle: 2, // Dashed
          axisLabelVisible: true,
          title: `Tgt ${signal.target.toFixed(1)}`,
        });
      }

      chart.timeScale().fitContent();

      // Resize observer
      const ro = new ResizeObserver(() => {
        if (chartContainerRef.current && chartRef.current) {
          chartRef.current.applyOptions({
            width: chartContainerRef.current.clientWidth,
          });
        }
      });
      ro.observe(chartContainerRef.current);

      setLoading(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load chart');
      setLoading(false);
    }
  }, [ticker, signal, height]);

  // Initial render + auto-refresh every 60s during market hours
  useEffect(() => {
    fetchAndRender(activeInterval);

    const refreshTimer = setInterval(() => {
      fetchAndRender(activeInterval);
    }, 60000);

    return () => {
      clearInterval(refreshTimer);
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [activeInterval, fetchAndRender]);

  const handleTimeframeChange = (tf: string) => {
    setActiveInterval(tf);
  };

  return (
    <div className="relative w-full">
      {/* Timeframe selector */}
      <div className="flex items-center gap-1 mb-2">
        {TIMEFRAMES.map((tf) => (
          <button
            key={tf}
            onClick={() => handleTimeframeChange(tf)}
            className={`px-3 py-1 text-xs font-mono rounded transition-colors ${
              activeInterval === tf
                ? 'bg-blue-500/20 text-blue-400 border border-blue-500/40'
                : 'bg-slate-800/50 text-slate-500 hover:text-slate-300 border border-slate-700/50'
            }`}
          >
            {tf}
          </button>
        ))}
        <span className="ml-auto text-[10px] text-slate-600 font-mono">{ticker}</span>
      </div>

      {/* Chart container */}
      <div className="relative rounded-lg overflow-hidden border border-slate-700/50 bg-slate-900/50">
        {loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-slate-900/80">
            <Loader2 size={24} className="text-blue-400 animate-spin" />
          </div>
        )}
        {error && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-slate-900/80">
            <span className="text-sm text-red-400">{error}</span>
          </div>
        )}
        <div ref={chartContainerRef} style={{ height }} />
      </div>
    </div>
  );
}
