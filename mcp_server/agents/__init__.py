"""
MKUMARAN Trading OS — Institutional Trading Agents

7 dedicated agents, each specializing in one market segment with
institutional-grade logic. Each agent has its own:
  - Scan loop (cadence, market hours)
  - Data sources + indicators
  - Entry/exit rules
  - Risk parameters
  - Telegram card format
  - Learning feedback loop

Agents:
  1. EquitySwingAgent    — NSE/BSE daily swing (existing MWA logic, refined)
  2. EquityIntradayAgent — NSE 5m/15m intraday (ORB, VWAP, EMA, Supertrend)
  3. OptionsIndexAgent   — NIFTY/BANKNIFTY/FINNIFTY weekly expiry plays
  4. OptionsStockAgent   — F&O stock options (directional CE/PE on liquid stocks)
  5. FuturesAgent        — NFO index + stock futures (trend following)
  6. CommodityAgent      — MCX Gold/Silver/Crude/NatGas
  7. ForexAgent          — CDS USDINR/EURINR/GBPINR/JPYINR

All agents implement BaseAgent and are registered with the AgentOrchestrator
which manages lifecycle, scheduling, and cross-agent coordination.
"""
