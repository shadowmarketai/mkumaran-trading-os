# MKUMARAN Trading OS — Complete Trading Guide

A step-by-step guide to trading using the MKUMARAN Trading OS. Covers all segments (NSE Equity, F&O, Commodity, Forex), timeframes (Intraday, Swing, Positional), and every tool in the system.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Before You Start — Pre-Market Routine](#2-before-you-start--pre-market-routine)
3. [Understanding Segments & Timeframes](#3-understanding-segments--timeframes)
4. [Signal Flow — How Signals Are Generated](#4-signal-flow--how-signals-are-generated)
5. [Reading a Signal Card](#5-reading-a-signal-card)
6. [Risk Management (RRMS)](#6-risk-management-rrms)
7. [AI Confidence & Debate Validator](#7-ai-confidence--debate-validator)
8. [Pre-Trade Checklist](#8-pre-trade-checklist)
9. [Backtesting — When & How to Use It](#9-backtesting--when--how-to-use-it)
10. [Wall Street AI — When & How to Use It](#10-wall-street-ai--when--how-to-use-it)
11. [Pattern Engines — Deep Analysis](#11-pattern-engines--deep-analysis)
12. [Options Trading Guide](#12-options-trading-guide)
13. [Paper Trading — Practice First](#13-paper-trading--practice-first)
14. [Signal Monitor — Auto-Tracking](#14-signal-monitor--auto-tracking)
15. [Momentum Ranker](#15-momentum-ranker)
16. [News & Macro](#16-news--macro)
17. [Trade Memory & Reflection](#17-trade-memory--reflection)
18. [Segment-Wise Trading Workflows](#18-segment-wise-trading-workflows)
19. [Timeframe-Wise Strategies](#19-timeframe-wise-strategies)
20. [Common Mistakes to Avoid](#20-common-mistakes-to-avoid)

---

## 1. System Overview

The Trading OS is a **signal generation + risk management + AI validation** platform:

```
MWA Scan (156 scanners, 15 layers)
  → Promoted stocks identified
  → ATR-based Entry/SL/TGT calculated
  → AI Debate validation
  → Signal card sent to Telegram + Dashboard
  → Auto-monitor tracks SL/TGT hit
  → Result recorded + Trade memory updated
```

**Dashboard URL**: https://money.shadowmarket.ai

**Key pages**: Overview, Active Trades, Signal Monitor, Accuracy, Watchlist, Backtesting, Pattern Engines, Wall Street AI, News & Macro, Momentum, Options Greeks, Payoff Calculator, Paper Trading.

---

## 2. Before You Start — Pre-Market Routine

Every trading day, follow this sequence **before market opens (9:00 AM)**:

### Step 1: Check Overview Dashboard
- Open the Overview page
- Look at **Market Status** (PRE/LIVE/POST/CLOSED)
- Review the **MWA Direction** — this tells you the overall market bias:
  - **STRONG_BULL / BULL**: Market favoring longs
  - **MILD_BULL / NEUTRAL**: Selective trades only
  - **MILD_BEAR / BEAR / STRONG_BEAR**: Market favoring shorts or stay cash

### Step 2: Check MWA Score
- The MWA Score (0-100) aggregates 156 scanners across 15 layers
- **Score > 65**: Bullish — favor LONG trades
- **Score 45-65**: Neutral — be selective, smaller positions
- **Score < 45**: Bearish — favor SHORT trades or stay cash

### Step 3: Review Scanner Heatmap
- Green cells = scanners that fired (found matching stocks)
- The more scanners fire for a stock, the stronger the conviction
- Use **segment tabs** to filter: NSE shows Equity layers, MCX shows Commodity, CDS shows Forex

### Step 4: Check News & Macro
- Go to News & Macro page
- Look for **HIGH impact** news — these can override technical signals
- Red news items = market-moving events (RBI policy, US Fed, earnings)
- **Rule**: If HIGH impact event is within 2 hours, reduce position size by 50% or skip

### Step 5: Run MWA Scan (if needed)
- Click **"Run MWA Scan"** button in the Market Weighted Average section on the Overview page
- If no MWA data exists yet, the button appears prominently in the center
- Wait for scan to complete (takes 2-3 minutes — the button shows a spinner)
- Top 10 promoted stocks get detailed signal cards with Entry/SL/TGT
- These appear in Telegram + Dashboard (MWA Signal Cards section)

---

## 3. Understanding Segments & Timeframes

### Segments

| Segment | What It Covers | Trading Hours | Min Capital |
|---------|---------------|---------------|-------------|
| **NSE Equity** | Stocks on NSE (cash segment) | 9:15 AM - 3:30 PM | ₹50,000 |
| **F&O** | Futures & Options on NSE | 9:15 AM - 3:30 PM | ₹1,00,000 |
| **Commodity (MCX)** | Gold, Silver, Crude, Natural Gas, etc. | 9:00 AM - 11:30 PM | ₹50,000 |
| **Forex (CDS)** | USDINR, EURINR, GBPINR, JPYINR | 9:00 AM - 5:00 PM | ₹25,000 |

### Timeframes

| Timeframe | Holding Period | Best For | Risk Level |
|-----------|---------------|----------|------------|
| **Intraday** | Same day (exit before close) | Quick moves, high volume stocks | High |
| **Swing** | 2-10 days | Pattern breakouts, momentum | Medium |
| **Positional** | 10-60 days | Trend following, sector rotation | Low-Medium |

### Which Segment + Timeframe to Use?

- **Beginner**: Start with NSE Equity + Swing trades
- **Intermediate**: Add F&O for leveraged swing trades
- **Commodity traders**: MCX + Intraday (gold/crude) or Swing
- **Forex**: CDS + Intraday (USDINR is most liquid)

---

## 4. Signal Flow — How Signals Are Generated

### Source 1: TradingView Alerts
```
TradingView alert fires
  → Telegram bot receives
  → Parses ticker, direction, pattern
  → ATR-based Entry/SL/TGT calculated
  → AI validation (debate if 40-75% confidence)
  → If confidence > 50%: Signal recorded + Telegram card sent
```

### Source 2: MWA Scan (98 Scanners)
```
Manual or scheduled scan trigger
  → 34 Chartink + 64 Python scanners run
  → Stocks scored by scanner count
  → Top 10 promoted stocks selected
  → ATR-based trade levels calculated
  → AI debate validation
  → If confidence > 50%: Signal recorded + Telegram card sent
```

### Signal Lifecycle
```
OPEN → (auto-monitor checks every 5 min)
  → TARGET_HIT → outcome = WIN, P&L recorded
  → SL_HIT → outcome = LOSS, P&L recorded
  → Manual close → outcome recorded
```

---

## 5. Reading a Signal Card

When you receive a signal (Telegram or Dashboard), here's how to read it:

```
🟢 MWA Signal
━━━━━━━━━━━━━━━━━━━━━━━━
Ticker: RELIANCE
Segment: NSE Equity | Equity
Timeframe: Daily (Swing)
Direction: LONG
━━━━━━━━━━━━━━━━━━━━━━━━
Entry: ₹2450.0 | SL: ₹2380.0 | TGT: ₹2660.0
RRR: 3.0 | Qty: 28
━━━━━━━━━━━━━━━━━━━━━━━━
Scanners: 8 fired
AI Confidence: 72% (ALERT)
Signal ID: SIG-2024-001
```

### Key Fields Explained

| Field | What It Means | What to Check |
|-------|--------------|---------------|
| **Direction** | LONG = Buy, SHORT = Sell | Must align with MWA direction |
| **Entry** | Price to enter the trade | Current price should be near entry |
| **SL (Stop Loss)** | Exit if price goes against you | Never move SL further away |
| **TGT (Target)** | Exit when price hits this | Can trail SL after 50% of target reached |
| **RRR** | Reward-to-Risk Ratio | Minimum 3.0 (you risk 1 to gain 3) |
| **Qty** | Number of shares to buy | Based on 2% capital risk |
| **AI Confidence** | How confident the AI is | >70% = strong, 50-70% = moderate |
| **Recommendation** | ALERT / WATCHLIST / SKIP | ALERT = trade now, WATCHLIST = wait |

---

## 6. Risk Management (RRMS)

The Risk-Reward Management System (RRMS) is the backbone of position sizing.

### Core Rules

```
Capital at risk per trade:  2% of total capital
Minimum RRR:                3.0 (risk ₹1 to gain ₹3)
Max loss per trade:         ₹2,000 (on ₹1,00,000 capital)
```

### How Position Size Is Calculated

```
Capital = ₹1,00,000
Risk per trade = 2% × ₹1,00,000 = ₹2,000
Risk per share = Entry - SL = ₹2,450 - ₹2,380 = ₹70
Quantity = ₹2,000 ÷ ₹70 = 28 shares
Total position = 28 × ₹2,450 = ₹68,600
```

### RRMS Rules You Must Follow

1. **Never risk more than 2%** per trade — this is non-negotiable
2. **Minimum RRR of 3.0** — don't take trades below this
3. **Max 3-5 open positions** at any time — avoid over-exposure
4. **Kill Switch**: If daily loss exceeds -3%, close ALL positions immediately
5. **Never move your stop loss further away** from entry — you can only trail it closer

### Position Sizing by Segment

| Segment | Risk % | Max Positions | Notes |
|---------|--------|---------------|-------|
| NSE Equity | 2% | 5 | Standard cash trades |
| F&O | 1.5% | 3 | Leverage increases risk |
| MCX | 2% | 3 | Commodity lot sizes apply |
| CDS | 2% | 2 | Forex pairs less volatile |

---

## 7. AI Confidence & Debate Validator

### How AI Confidence Works

Every signal gets an AI confidence score (0-100%):

- **Base confidence**: Calculated from scanner count, MWA alignment, pattern strength
- **If 40-75% (uncertain zone)**: Triggers the **Debate Validator**
- **If >75% or <40%**: Single-pass validation (no debate needed)

### Debate Validator

When confidence is in the uncertain zone (40-75%), two AI agents debate:

```
Bull Agent: Makes the case FOR the trade
Bear Agent: Makes the case AGAINST the trade
  → 2 rounds of debate
  → Final verdict: adjusted confidence + recommendation
```

This costs 6 API calls but catches bad trades that look okay on the surface.

### Recommendations

| Recommendation | Confidence | Action |
|---------------|------------|--------|
| **ALERT** | >65% | Execute the trade at given levels |
| **WATCHLIST** | 50-65% | Add to watchlist, wait for confirmation |
| **SKIP** | <50% | Do not trade — signal rejected |

### What Affects Confidence

| Factor | Boost | Condition |
|--------|-------|-----------|
| MWA alignment | +10% | Signal direction matches MWA direction |
| Scanner count | +3% per scanner | Max +15% from scanners |
| High delivery % | +5% | Delivery > 60% (institutional interest) |
| FII buying | +5% | FII net buy > 0 |
| Sector strength | +5% | Sector in top momentum |
| News sentiment | -10% | Negative HIGH impact news |

---

## 8. Pre-Trade Checklist

Before entering ANY trade, verify these items:

### Universal Checklist (All Segments)

- [ ] MWA Direction aligns with trade direction
- [ ] AI Confidence > 50% (preferably > 65%)
- [ ] RRR >= 3.0
- [ ] No HIGH impact news in next 2 hours
- [ ] Position size follows RRMS (2% risk max)
- [ ] Max open positions not exceeded
- [ ] Current price within 1% of Entry price
- [ ] Market status is LIVE

### NSE Equity Additional Checks

- [ ] Delivery % > 40% (check on previous day's data)
- [ ] FII/DII not heavily selling (check News & Macro)
- [ ] Stock not in F&O ban list (if applicable)
- [ ] Volume above 20-day average

### MCX (Commodity) Additional Checks

- [ ] Check international commodity prices (Gold: COMEX, Crude: NYMEX)
- [ ] Dollar Index (DXY) trend — inverse correlation with gold
- [ ] No OPEC/geopolitical events for crude
- [ ] Trading within commodity market hours

### CDS (Forex) Additional Checks

- [ ] RBI policy announcement not within 24 hours
- [ ] US Fed meeting not within 48 hours
- [ ] DXY trend alignment
- [ ] Trading within CDS market hours (9:00 AM - 5:00 PM)

---

## 9. Backtesting — When & How to Use It

### What Is Backtesting?

Backtesting simulates a trading strategy on **historical data** to see how it would have performed. It tells you:
- Win rate (% of profitable trades)
- Average P&L per trade
- Maximum drawdown
- Sharpe ratio (risk-adjusted return)

### When to Use Backtesting

| Scenario | Why Backtest |
|----------|-------------|
| **New stock you haven't traded** | Check if your strategy works on this stock |
| **Trying a new strategy** | Compare SMC vs Wyckoff vs Harmonic on a stock |
| **After a losing streak** | Verify the strategy still works, not just bad luck |
| **Before positional trades** | Longer holding = more capital at risk, validate first |
| **Comparing all strategies** | Use "Compare All" to find the best strategy for a stock |

### When NOT to Backtest

- Intraday trades on the same day (no time, just follow signals)
- Obvious high-confidence signals (>80% AI confidence)
- When market is strongly trending (backtesting may understate gains)

### Available Strategies

| Strategy | Best For | What It Tests |
|----------|---------|---------------|
| **RRMS** | All trades | Entry/SL/TGT with 3:1 RRR, 2% risk |
| **SMC** | Swing trades | Smart Money Concept (order blocks, fair value gaps) |
| **Wyckoff** | Positional | Accumulation/Distribution phases |
| **VSA** | Volume-heavy stocks | Volume Spread Analysis (climax, no-demand) |
| **Harmonic** | Reversal trades | Gartley, Butterfly, Bat, Crab patterns |
| **Confluence** | Best overall | Runs all strategies, finds convergence zones |

### How to Backtest

1. Go to **Backtesting** page
2. Enter: Ticker (e.g., RELIANCE), Strategy (e.g., RRMS), Days (e.g., 90)
3. Click "Run Backtest"
4. Review results:
   - **Win Rate > 60%**: Strategy works well for this stock
   - **Win Rate 45-60%**: Marginal — use with caution
   - **Win Rate < 45%**: Avoid this strategy for this stock
5. Use "Compare All" to test all strategies at once

### Reading Backtest Results

```
Strategy: RRMS on RELIANCE (90 days)
━━━━━━━━━━━━━━━━━━━━━━━━
Total Trades: 12
Wins: 8 | Losses: 4
Win Rate: 66.7%
Avg Win: +₹4,200 | Avg Loss: -₹1,400
Net P&L: +₹28,000
Max Drawdown: -6.2%
Sharpe Ratio: 1.8
```

**Cost model included**: ₹20/order + 0.03% brokerage + STT/CTT + GST + stamp duty.

---

## 10. Wall Street AI — When & How to Use It

### What Is Wall Street AI?

Wall Street AI provides **10 AI-powered analysis functions** that give institutional-grade insights. It's your research analyst.

### The 10 Functions

| # | Function | When to Use | What You Get |
|---|----------|------------|--------------|
| 1 | **Stock Screener** | Finding new opportunities | Filtered list by sector, market cap, momentum |
| 2 | **Technical Analysis** | Before any trade | Support/resistance, trend, indicators summary |
| 3 | **Fundamental Analysis** | Positional trades | PE, ROE, debt ratios, growth metrics |
| 4 | **Sector Analysis** | Sector rotation plays | Sector vs Nifty performance, top stocks |
| 5 | **Risk Assessment** | Before large positions | VaR, beta, correlation, max drawdown |
| 6 | **Trade Setup** | Getting exact levels | Entry/SL/TGT with reasoning |
| 7 | **Market Overview** | Morning routine | FII/DII, global cues, sentiment |
| 8 | **Earnings Analysis** | Before/after results | Revenue, profit trends, surprise factor |
| 9 | **Correlation Analysis** | Portfolio diversification | How stocks move together |
| 10 | **Volatility Analysis** | Options trading | IV percentile, HV, expected move |

### When to Use Wall Street AI

| Situation | Functions to Use |
|-----------|-----------------|
| **Before a swing trade** | Technical Analysis + Risk Assessment |
| **Before a positional trade** | Fundamental + Technical + Sector Analysis |
| **Before options trade** | Volatility Analysis + Risk Assessment |
| **Morning routine** | Market Overview + Sector Analysis |
| **New stock discovery** | Stock Screener + Fundamental Analysis |
| **Earnings season** | Earnings Analysis (before/after results) |

### Making Decisions with Wall Street AI

**Example workflow for a swing trade on HDFCBANK:**

1. **Technical Analysis** → Shows stock at support, RSI oversold
2. **Risk Assessment** → Beta 0.8 (less volatile than Nifty), Max DD -12%
3. **Trade Setup** → Entry ₹1,650, SL ₹1,610, TGT ₹1,730
4. **Decision**: AI Confidence from signal (72%) + Technical support + Low risk = **TAKE THE TRADE**

**Example workflow for a positional trade on TATAPOWER:**

1. **Fundamental Analysis** → Revenue growing 15% YoY, PE reasonable
2. **Sector Analysis** → Power sector outperforming Nifty by 8%
3. **Technical Analysis** → Breakout from 6-month consolidation
4. **Decision**: Strong fundamentals + Sector strength + Breakout = **TAKE THE TRADE**

---

## 11. Pattern Engines — Deep Analysis

Six pattern detection engines run independently and can validate signals:

### Available Engines

| Engine | What It Detects | Best For |
|--------|----------------|----------|
| **SMC** | Order Blocks, Fair Value Gaps, Break of Structure, Change of Character | Swing trades, finding institutional entry points |
| **Wyckoff** | Accumulation (Phase A-E), Distribution, Springs, Upthrusts | Positional trades, catching major reversals |
| **VSA** | Climax bars, No-demand, Test bars, Stopping volume | Volume confirmation before entry |
| **Harmonic** | Gartley, Butterfly, Bat, Crab patterns | Reversal trades with precise levels |
| **RL (Reinforcement Learning)** | AI-learned patterns from historical data | Novel pattern detection |
| **Confluence** | Runs all engines, finds zones where multiple agree | Highest conviction trades |

### How to Use Pattern Engines

1. Go to **Pattern Engines** page
2. Enter ticker and number of days
3. Choose engine or "Detect All"
4. Review detections:
   - **Pattern found with high confidence** → Adds conviction to your trade
   - **Multiple engines agree** → Very strong signal (Confluence)
   - **No patterns found** → Signal may be based on momentum only (still valid)

### When to Check Engines

- **Before swing trades**: Run SMC + Wyckoff
- **Before reversal trades**: Run Harmonic
- **Volume confirmation**: Run VSA
- **Highest conviction check**: Run "Detect All" / Confluence

---

## 12. Options Trading Guide

### Basics of Options

- **Call Option (CE)**: Right to BUY at strike price — buy when BULLISH
- **Put Option (PE)**: Right to SELL at strike price — buy when BEARISH
- **Strike Price**: The price at which you can exercise the option
- **Expiry**: Date when the option expires (weekly Thursday or monthly last Thursday)
- **Premium**: The price you pay to buy the option

### Using the Options Greeks Calculator

Go to **Options Greeks** page. The Greeks tell you:

| Greek | What It Measures | Why It Matters |
|-------|-----------------|----------------|
| **Delta** | How much option price moves per ₹1 stock move | ATM options: delta ~0.5 |
| **Gamma** | Rate of change of delta | High gamma = more sensitivity near expiry |
| **Theta** | Time decay per day | Options lose value every day — critical for sellers |
| **Vega** | Sensitivity to volatility change | High IV = expensive premiums |
| **Rho** | Sensitivity to interest rate change | Usually negligible for short-term |

### Options Trading Workflow

**Step 1: Get the Signal**
- Receive signal from MWA scan or TradingView
- Note: Direction (LONG/SHORT), Entry, SL, TGT

**Step 2: Check Volatility (Wall Street AI → Volatility Analysis)**
- **IV Percentile > 70%**: Options are expensive — consider SELLING options
- **IV Percentile < 30%**: Options are cheap — consider BUYING options
- **IV Percentile 30-70%**: Normal — use directional strategies

**Step 3: Choose Strike Price**
- **Intraday**: ATM (At The Money) or 1 strike OTM — highest delta
- **Swing (2-5 days)**: 1-2 strikes ITM — less time decay impact
- **Positional**: Deep ITM or futures — lowest theta decay

**Step 4: Calculate Greeks**
- Enter Spot, Strike, Expiry Days in Options Greeks page
- Check Delta (want > 0.4 for directional trades)
- Check Theta (daily decay — can you afford it?)

**Step 5: Use Payoff Calculator**
- Go to **Payoff Calc** page
- Add your option leg(s)
- See max profit, max loss, breakeven
- Available presets: Long Call, Long Put, Bull Call Spread, Bear Put Spread, Iron Condor, Straddle

### Options Strategy Selection

| Market View | IV Level | Strategy | Risk |
|-------------|----------|----------|------|
| Strong Bullish | Low IV | **Buy Call** (ATM) | Premium paid |
| Mild Bullish | High IV | **Bull Call Spread** | Limited |
| Strong Bearish | Low IV | **Buy Put** (ATM) | Premium paid |
| Mild Bearish | High IV | **Bear Put Spread** | Limited |
| Neutral (no direction) | High IV | **Iron Condor** | Limited |
| Big move expected | Low IV | **Straddle** | Premium paid |

### Options Risk Rules

1. **Never sell naked options** — always use spreads
2. **Max 2% of capital** per options trade
3. **Exit at 50% profit** — don't wait for max profit
4. **Exit at 30% loss** — cut losers fast in options
5. **Avoid last 2 days before expiry** unless you're an experienced trader (gamma risk)
6. **Weekly options** for intraday, **Monthly options** for swing/positional

---

## 13. Paper Trading — Practice First

### What Is Paper Trading?

Simulated trading with virtual money. No real money at risk.

### When to Paper Trade

- **New strategy**: Test it for 2 weeks on paper before going live
- **New segment**: First time trading MCX or CDS? Paper trade first
- **After a losing streak**: Reset your psychology, rebuild confidence
- **Learning options**: Practice option strategies risk-free

### How to Use Paper Trading

1. Go to **Paper Trading** page
2. Place simulated trades (same Entry/SL/TGT as real signals)
3. Track P&L in real-time
4. **Kill Switch**: Auto-closes all positions if daily loss > -3%
5. **Trailing SL**: Moves SL to breakeven after 50% of target reached

### Paper Trading Rules

- Treat it exactly like real money — follow all rules
- Run for minimum 20 trades before evaluating
- If win rate < 50% on paper, don't go live
- Once paper trading is profitable for 2+ weeks, start with 50% of planned capital

---

## 14. Signal Monitor — Auto-Tracking

### What It Does

The Signal Monitor **automatically tracks all open signals** and closes them when:
- **Target Hit**: Price reaches TGT → Records as WIN
- **Stop Loss Hit**: Price reaches SL → Records as LOSS

### How It Works

- Background process checks every **5 minutes** during market hours
- Fetches live prices for all OPEN signals
- When SL or TGT is hit:
  1. Updates signal status in database
  2. Records outcome (WIN/LOSS, P&L %, P&L ₹, days held)
  3. Updates Google Sheets
  4. Sends Telegram alert
  5. Updates trade memory for future learning

### Using the Signal Monitor Page

1. **Summary Cards**: Shows Open / Long / Short / Recently Closed counts
2. **Open Signals Table**: All signals being monitored with live data
3. **Check Now Button**: Manually trigger a check (don't wait 5 min)
4. **Recently Closed**: Signals that just hit SL/TGT after Check Now

### What You Should Do

- Check the Signal Monitor page 2-3 times during trading hours
- After market close, review Recently Closed for learning
- If a signal has been open for >10 days without hitting SL/TGT, consider manual exit

---

## 15. Momentum Ranker

### What It Does

Ranks stocks by **multi-timeframe momentum** using weighted scoring:

```
Score = (12-month return × 0.4) + (6-month × 0.3) + (3-month × 0.2) + (volatility × 0.1)
```

### When to Use

- **Sector rotation**: Find strongest sectors to trade
- **Positional trades**: Pick top momentum stocks for 2-4 week holds
- **Avoid weak stocks**: Bottom-ranked stocks = avoid or short

### How to Use

1. Go to **Momentum** page
2. Click "Rebalance" to update rankings (top 10 by default)
3. Green = strong momentum → favor LONG trades
4. Red = weak momentum → avoid or SHORT

---

## 16. News & Macro

### What It Shows

- Latest market news classified by impact: **HIGH / MEDIUM / LOW**
- FII/DII activity (buy/sell data)
- Global market cues
- Upcoming events

### How to Use for Trading

| News Impact | Action |
|-------------|--------|
| **HIGH** (red) | Pause trading or reduce position size by 50% |
| **MEDIUM** (yellow) | Be cautious, tighten stop losses |
| **LOW** (green) | Normal trading, no adjustment needed |

### Key Macro Indicators

- **FII Net Buy > 0**: Positive for market, favor longs
- **FII Net Sell > ₹2,000 Cr**: Cautious, market may fall
- **DXY rising**: Negative for emerging markets (India)
- **US 10Y yield rising**: Negative for growth stocks

---

## 17. Trade Memory & Reflection

### What It Does

The system remembers every trade and learns from it:
- **Trade Memory**: Stores all past trades with outcomes
- **BM25 Search**: Finds similar past trades when a new signal comes
- **Reflector**: Post-trade analysis — what worked, what didn't

### How It Helps You

When a new signal comes for RELIANCE LONG:
1. System searches past trades: "Have we traded RELIANCE LONG before?"
2. Finds 3 similar trades with outcomes
3. Uses this history to adjust AI confidence
4. You can see: "Last 3 similar trades: 2 wins, 1 loss, avg +2.8%"

### What You Should Do

- After each trade closes, review the outcome on the Accuracy page
- Check if the strategy that generated the signal has been consistently profitable
- If a particular stock repeatedly loses, add it to your avoid list

---

## 18. Segment-Wise Trading Workflows

### NSE Equity (Cash) Workflow

```
1. Morning: Check Overview → MWA Score > 65?
2. Run MWA Scan → Get top 10 signals
3. Filter signals: AI Confidence > 65%, RRR >= 3.0
4. For each candidate:
   a. Check delivery % (> 40%)
   b. Check FII/DII activity
   c. Run Backtest (90 days, RRMS strategy)
   d. Win rate > 55%? → Proceed
5. Enter trade at Entry price
6. Set SL and TGT in your broker
7. Signal Monitor tracks automatically
```

### F&O (Futures & Options) Workflow

```
1. Get signal (LONG/SHORT)
2. Check Volatility Analysis (Wall Street AI)
3. If IV < 30%: Buy Call/Put (ATM)
   If IV > 70%: Sell spreads (Bull Call / Bear Put)
   If IV 30-70%: Buy 1-strike ITM
4. Use Payoff Calculator to verify max loss < 2% capital
5. Check Options Greeks: Delta > 0.4, Theta acceptable
6. Enter trade
7. Exit rules: 50% profit or 30% loss, whichever first
```

### MCX (Commodity) Workflow

```
1. Check global commodity prices (COMEX Gold, NYMEX Crude)
2. Check DXY (Dollar Index) — inverse to gold
3. Run MWA Scan with MCX segment filter
4. Signals for GOLD, SILVER, CRUDEOIL, NATURALGAS
5. ATR-based levels already adjusted for MCX lot sizes
6. Enter trade during MCX hours
7. MCX is volatile — consider 1.5% risk instead of 2%
```

### CDS (Forex) Workflow

```
1. Check RBI calendar — no policy meeting within 24h
2. Check US economic calendar — no Fed meeting within 48h
3. Run MWA Scan with CDS segment filter
4. Signals for USDINR, EURINR, GBPINR, JPYINR
5. CDS pairs have lower volatility — wider timeframes work better
6. Best for swing trades (3-7 days)
```

---

## 19. Timeframe-Wise Strategies

### Intraday Trading

| Item | Rule |
|------|------|
| Entry | Within first 30 min of market open, or after 11 AM |
| SL | 0.5-1% from entry (tight) |
| Target | 1.5-3% from entry |
| Exit | Must close before 3:15 PM |
| Best patterns | Breakout, Gap-up/down, Volume spike |
| Position size | Standard RRMS (2% risk) |
| Tools to use | Signal Monitor (5-min checks), News (avoid events) |

### Swing Trading (2-10 days)

| Item | Rule |
|------|------|
| Entry | End of day or next day open |
| SL | 1.5x ATR from entry |
| Target | RRR × risk from entry (min 3:1) |
| Exit | When SL or TGT hit, or after 10 days |
| Best patterns | SMC order blocks, Wyckoff accumulation, Harmonic |
| Position size | Standard RRMS (2% risk) |
| Tools to use | Backtesting, Pattern Engines, Wall Street AI |

### Positional Trading (10-60 days)

| Item | Rule |
|------|------|
| Entry | On weekly chart confirmation |
| SL | 2-3x ATR from entry (wider) |
| Target | 2-5x risk (RRR 2-5) |
| Exit | When SL or TGT hit, or trend reversal |
| Best patterns | Wyckoff phases, Sector rotation, Fundamental strength |
| Position size | Reduced to 1.5% risk (longer exposure) |
| Tools to use | Wall Street AI (Fundamental + Sector), Momentum Ranker, Backtesting (180 days) |

---

## 20. Common Mistakes to Avoid

### Risk Management Mistakes
1. **Moving SL further away** — "It'll come back" is the costliest phrase in trading
2. **Over-sizing positions** — Never exceed 2% risk per trade
3. **Ignoring the Kill Switch** — If daily loss hits -3%, STOP. No exceptions
4. **Too many open positions** — Max 5 for equity, 3 for F&O/MCX
5. **Averaging down on losers** — Don't add to losing positions

### Signal Mistakes
6. **Trading SKIP signals** — If AI says SKIP (<50% confidence), don't trade
7. **Ignoring MWA direction** — Don't go LONG in a BEAR market
8. **Chasing entry** — If price moved >1% from Entry, don't chase. Wait for next signal
9. **Trading during HIGH impact news** — Sit on your hands during RBI/Fed announcements

### Strategy Mistakes
10. **Not backtesting** — Always backtest a new stock/strategy before real money
11. **Skipping Paper Trading** — Practice new strategies on paper first
12. **Ignoring sector strength** — A weak sector drags even strong stocks down
13. **Not using Wall Street AI** — Free institutional-grade analysis, use it

### Psychology Mistakes
14. **Revenge trading** — After a loss, don't immediately take another trade
15. **FOMO** — Missing one trade is okay. There's always another signal tomorrow
16. **Not reviewing trades** — Check Accuracy page weekly, learn from losses
17. **Overtrading** — Quality > Quantity. 2-3 high-conviction trades > 10 random ones

---

## Quick Reference Card

```
BEFORE MARKET:
  ✓ Check Overview → MWA Score & Direction
  ✓ Check News → No HIGH impact events
  ✓ Run MWA Scan → Get signals

BEFORE EACH TRADE:
  ✓ AI Confidence > 50% (prefer > 65%)
  ✓ RRR >= 3.0
  ✓ Position size = 2% risk max
  ✓ Direction aligns with MWA
  ✓ Backtest win rate > 55% (for new stocks)

DURING TRADE:
  ✓ Signal Monitor tracks SL/TGT
  ✓ Don't move SL further away
  ✓ Trail SL to breakeven after 50% target reached
  ✓ Kill Switch at -3% daily loss

AFTER MARKET:
  ✓ Review closed signals
  ✓ Check Accuracy page
  ✓ Note lessons learned
```

---

*This guide is generated for the MKUMARAN Trading OS. For system issues, contact the development team.*
