# earnings_calendar.py
# MKUMARAN Trading OS — JPMorgan Pre-Earnings Alert Module
# Triggers 2 days before any Tier 2 stock reports quarterly results
# Sends pre-earnings brief to Telegram automatically
#
# Usage:
#   from mcp_server.earnings_calendar import EarningsCalendar
#   cal = EarningsCalendar(kite, db, telegram, claude_client)
#   cal.run_daily_check()  # called by n8n at 8:45 AM daily

import logging
import time
import requests
import anthropic
from datetime import date, datetime, timedelta

from mcp_server.db import SessionLocal
from mcp_server.models import Watchlist, ActiveTrade
from mcp_server.config import settings

logger = logging.getLogger(__name__)


# --- CONFIG ---

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
    "Connection": "keep-alive",
}

ALERT_DAYS_BEFORE = 2       # Alert this many days before earnings
SCREENER_BASE     = "https://www.screener.in/api/company"
NSE_BASE          = "https://www.nseindia.com/api"

# Track already-sent alerts to avoid duplicates (in-memory; reset on restart)
_sent_alerts: dict[str, str] = {}


# --- NSE SESSION HELPER ---

def get_nse_session() -> requests.Session:
    """
    Create an authenticated NSE session.
    NSE requires visiting the homepage first to get cookies.
    """
    session = requests.Session()
    session.headers.update(NSE_HEADERS)
    try:
        session.get("https://www.nseindia.com", timeout=10)
        time.sleep(1)  # Polite delay
    except Exception:
        pass
    return session


# --- EARNINGS CALENDAR ---

def fetch_nse_earnings_calendar(days_ahead: int = 30) -> list:
    """
    Fetch upcoming NSE earnings dates from NSE corporate actions API.
    Returns list of dicts: {ticker, company_name, results_date, quarter}
    """
    session = get_nse_session()
    today     = date.today()
    end_date  = today + timedelta(days=days_ahead)

    url = f"{NSE_BASE}/corporates-corporateActions"
    params = {
        "index":     "equities",
        "from_date": today.strftime("%d-%m-%Y"),
        "to_date":   end_date.strftime("%d-%m-%Y"),
        "type":      "financial results",
    }

    try:
        resp = session.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error("NSE earnings calendar fetch failed: %s", e)
        return []

    earnings = []
    for item in data:
        purpose = item.get("purpose", "").lower()
        # Filter to quarterly/annual financial results only
        if any(kw in purpose for kw in ["financial result", "quarterly result",
                                         "annual result", "q1", "q2", "q3", "q4"]):
            try:
                results_date = datetime.strptime(item["exDate"], "%d-%b-%Y").date()
            except Exception:
                continue

            # Determine quarter
            quarter = "Unknown"
            for q in ["Q1", "Q2", "Q3", "Q4"]:
                if q.lower() in purpose:
                    quarter = q
                    break
            if "annual" in purpose:
                quarter = "Annual/Q4"

            earnings.append({
                "ticker":       item.get("symbol", ""),
                "company_name": item.get("companyName", ""),
                "results_date": str(results_date),
                "quarter":      quarter,
                "purpose":      item.get("purpose", ""),
            })

    logger.info("Found %d earnings events in next %d days", len(earnings), days_ahead)
    return earnings


def get_watchlist_earnings_alerts() -> list:
    """
    Cross-reference earnings calendar with Tier 2 watchlist.
    Returns stocks reporting within ALERT_DAYS_BEFORE days.
    """
    db = SessionLocal()
    try:
        watchlist_items = db.query(Watchlist).filter(
            Watchlist.tier == 2, Watchlist.active.is_(True)
        ).all()
        watchlist = [w.ticker.replace("NSE:", "") for w in watchlist_items]
    finally:
        db.close()

    calendar  = fetch_nse_earnings_calendar(days_ahead=7)
    today     = date.today()
    alerts    = []

    for event in calendar:
        if event["ticker"] not in watchlist:
            continue
        try:
            results_date = date.fromisoformat(event["results_date"])
            days_away    = (results_date - today).days
            if 0 <= days_away <= ALERT_DAYS_BEFORE:
                event["days_away"]       = days_away
                event["nse_ticker"]      = f"NSE:{event['ticker']}"
                event["urgency"]         = "TODAY" if days_away == 0 else \
                                           "TOMORROW" if days_away == 1 else \
                                           f"IN {days_away} DAYS"
                alerts.append(event)
        except Exception:
            continue

    return alerts


# --- FUNDAMENTAL DATA FETCHER ---

def fetch_quarterly_history(ticker: str) -> dict:
    """
    Fetch last 4 quarters: revenue, PAT, EPS from Screener.in
    Returns dict with quarterly data for JPMorgan prompt.
    """
    url = f"{SCREENER_BASE}/{ticker}/consolidated/"
    try:
        resp = requests.get(url, timeout=15,
                           headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code == 404:
            url = f"{SCREENER_BASE}/{ticker}/"
            resp = requests.get(url, timeout=15,
                               headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        data = resp.json()

        # Extract quarterly results
        quarters = []
        results  = data.get("quarterly_results", data.get("results", []))

        for q in results[:4]:  # Last 4 quarters
            quarters.append({
                "period":       q.get("title", ""),
                "revenue":      q.get("Sales", q.get("Revenue", "N/A")),
                "pat":          q.get("Net profit", q.get("PAT", "N/A")),
                "eps":          q.get("EPS", "N/A"),
                "beat_or_miss": "N/A",  # Would need analyst estimates API
            })

        return {
            "ticker":      ticker,
            "quarters":    quarters,
            "sector":      data.get("sector", "Unknown"),
            "industry":    data.get("industry", "Unknown"),
            "pe":          data.get("pe", "N/A"),
            "market_cap":  data.get("market_cap", "N/A"),
        }

    except Exception as e:
        logger.error("Screener.in fetch failed for %s: %s", ticker, e)
        return {
            "ticker":   ticker,
            "quarters": [],
            "sector":   "Unknown",
            "error":    str(e),
        }


def fetch_historical_price_reactions(ticker: str, kite) -> list:
    """
    Fetch stock price reaction on last 4 earnings days.
    Uses Kite historical data to calculate day-of return.
    """
    calendar = fetch_nse_earnings_calendar(days_ahead=400)
    past_earnings = [
        e for e in calendar
        if e["ticker"] == ticker
        and date.fromisoformat(e["results_date"]) < date.today()
    ][:4]

    reactions = []
    for event in past_earnings:
        try:
            earnings_date = date.fromisoformat(event["results_date"])
            token = kite.ltp(f"NSE:{ticker}")[f"NSE:{ticker}"]["instrument_token"]

            # Get candle data around earnings date
            candles = kite.historical_data(
                token,
                from_date=earnings_date - timedelta(days=2),
                to_date=earnings_date + timedelta(days=1),
                interval="day"
            )

            if len(candles) >= 2:
                prev_close   = candles[-2]["close"]
                results_close = candles[-1]["close"]
                pct_move = ((results_close - prev_close) / prev_close) * 100

                reactions.append({
                    "date":       str(earnings_date),
                    "quarter":    event["quarter"],
                    "pct_move":   round(pct_move, 2),
                    "direction":  "UP" if pct_move > 0 else "DOWN",
                })
        except Exception:
            continue

    return reactions


# --- JPMORGAN PRE-EARNINGS PROMPT ---

JPMORGAN_PROMPT = """You are a senior equity research analyst at JPMorgan Chase
specialising in Indian corporate earnings analysis for institutional investors.

A trader has {ticker} ({company_name}) in their watchlist.
Results are due in {days_away} day(s) on {results_date} ({quarter}).

Current position details:
- CMP: Rs.{cmp}
- Position: {position_type}
- Entry price: Rs.{entry_price}
- Target: Rs.{target} | Stop Loss: Rs.{stop_loss}
- Current P&L: {current_pnl}

Last 4 quarters performance:
{quarterly_table}

Stock price reaction on last 4 earnings days:
{price_reactions}

Sector: {sector} | Market cap: Rs.{market_cap} Cr | P/E: {pe}

Deliver a pre-earnings brief covering:

1. Beat/miss pattern: has this company been consistently beating or missing estimates?
2. Key metric Street is watching for {sector} sector specifically
3. Historical price behaviour: does this stock rally into results or sell on news?
4. Average % move on earnings day (last 4 quarters)
5. Bull case: what a beat looks like + estimated price impact
6. Bear case: what a miss looks like + estimated downside
7. Risk assessment for the current position:
   - Is the current entry price exposed to gap-down risk?
   - What is the risk in absolute Rs. terms if results disappoint?

MY RECOMMENDATION for this specific position:
Choose one and explain briefly:
A) HOLD FULL POSITION through results -- reason
B) REDUCE to 50% before results -- reason
C) EXIT COMPLETELY before results -- reason
D) HOLD + add stop-loss adjustment suggestion

Keep output concise. This is a decision brief, not a research report.
End with a single ACTION LINE: the one thing to do before market close today.

Indian earnings context:
- Results season: Apr=Q4, Jul=Q1, Oct=Q2, Jan=Q3
- Check NSE exchange filings for any pre-announcement in last 48 hours
- Promoter pledge data: high pledge = results disappointment = sharper fall
"""


def generate_pre_earnings_brief(event: dict, kite, db_session) -> str:
    """
    Generate JPMorgan-style pre-earnings brief using Claude API.
    Returns formatted brief as string for Telegram.
    """
    ticker       = event["ticker"]
    nse_ticker   = f"NSE:{ticker}"

    # Fetch live price
    try:
        quote = kite.ltp(nse_ticker)
        cmp   = quote[nse_ticker]["last_price"]
    except Exception:
        cmp   = 0

    # Fetch active trade details from DB
    trade = db_session.query(ActiveTrade).filter(
        ActiveTrade.ticker == nse_ticker
    ).order_by(ActiveTrade.id.desc()).first()

    position_type = "LONG" if trade else "WATCHING"
    entry_price   = float(trade.entry_price) if trade else cmp
    target        = float(trade.target) if trade else cmp * 1.10
    stop_loss     = float(trade.stop_loss) if trade else cmp * 0.95
    qty           = int(trade.signal.qty) if trade and trade.signal else 0
    current_pnl   = f"Rs.{round((cmp - entry_price) * qty, 0)}" if trade else "Not in trade"

    # Fetch fundamental data
    fundamentals = fetch_quarterly_history(ticker)
    reactions    = fetch_historical_price_reactions(ticker, kite)

    # Build quarterly table
    q_table = "Quarter | Revenue (Cr) | PAT (Cr) | EPS\n"
    q_table += "-" * 45 + "\n"
    for q in fundamentals.get("quarters", []):
        q_table += f"{q['period']:10} | {str(q['revenue']):12} | {str(q['pat']):8} | {q['eps']}\n"

    # Build price reactions table
    r_table = "Quarter | Date | Move\n"
    r_table += "-" * 35 + "\n"
    for r in reactions:
        direction = "+" if r["direction"] == "UP" else ""
        r_table += f"{r['quarter']:6} | {r['date']} | {direction}{r['pct_move']}%\n"
    if not reactions:
        r_table += "Insufficient historical data\n"

    # Build prompt
    prompt = JPMORGAN_PROMPT.format(
        ticker          = ticker,
        company_name    = event["company_name"],
        days_away       = event["days_away"],
        results_date    = event["results_date"],
        quarter         = event["quarter"],
        cmp             = cmp,
        position_type   = position_type,
        entry_price     = entry_price,
        target          = target,
        stop_loss       = stop_loss,
        current_pnl     = current_pnl,
        quarterly_table = q_table,
        price_reactions = r_table,
        sector          = fundamentals.get("sector", "Unknown"),
        market_cap      = fundamentals.get("market_cap", "N/A"),
        pe              = fundamentals.get("pe", "N/A"),
    )

    # Call Claude
    client   = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model      = "claude-sonnet-4-6",
        max_tokens = 800,
        messages   = [{"role": "user", "content": prompt}]
    )

    return response.content[0].text


# --- TELEGRAM FORMATTER ---

def format_earnings_telegram(event: dict, brief: str) -> str:
    """Format the pre-earnings brief as a Telegram message."""
    urgency_emoji = {
        "TODAY":    "\U0001f534",
        "TOMORROW": "\U0001f7e1",
    }.get(event["urgency"], "\U0001f7e2")

    header = (
        f"{urgency_emoji} PRE-EARNINGS ALERT -- {event['ticker']}\n"
        f"{'=' * 35}\n"
        f"Company  : {event['company_name']}\n"
        f"Results  : {event['results_date']} ({event['quarter']})\n"
        f"Timing   : {event['urgency']}\n"
        f"{'=' * 35}\n"
    )

    return header + brief


# --- MAIN DAILY CHECK ---

class EarningsCalendar:
    """
    Main class -- instantiate in mcp_server.py and call run_daily_check()
    Called by n8n at 8:45 AM daily.
    """

    def __init__(self, kite, telegram_bot, claude_client=None):
        self.kite           = kite
        self.telegram       = telegram_bot
        self.chat_id        = settings.TELEGRAM_CHAT_ID

    def run_daily_check(self) -> list:
        """
        Main entry point -- called daily at 8:45 AM.
        Checks for upcoming earnings and sends pre-earnings briefs.
        Returns list of alerts sent.
        """
        logger.info("Running earnings calendar check...")

        alerts = get_watchlist_earnings_alerts()

        if not alerts:
            logger.info("No upcoming earnings for Tier 2 watchlist.")
            return []

        sent_alerts = []
        db = SessionLocal()
        try:
            for event in alerts:
                ticker = event["ticker"]

                # Skip if already alerted today (in-memory check)
                alert_key = f"{ticker}:{event['results_date']}"
                if alert_key in _sent_alerts:
                    logger.info("Already alerted for %s earnings -- skipping", ticker)
                    continue

                logger.info("Generating pre-earnings brief for %s...", ticker)
                try:
                    brief   = generate_pre_earnings_brief(event, self.kite, db)
                    message = format_earnings_telegram(event, brief)

                    # Send to Telegram
                    self.telegram.send_message(
                        chat_id    = self.chat_id,
                        text       = message,
                        parse_mode = "Markdown"
                    )

                    # Mark as sent
                    _sent_alerts[alert_key] = str(date.today())
                    sent_alerts.append(ticker)
                    logger.info("Pre-earnings brief sent for %s", ticker)

                except Exception as e:
                    logger.error("Failed to generate brief for %s: %s", ticker, e)
                    # Send simplified alert as fallback
                    fallback = (
                        f"EARNINGS ALERT -- {ticker}\n"
                        f"Results: {event['results_date']} ({event['quarter']})\n"
                        f"Timing: {event['urgency']}\n"
                        f"(Full brief generation failed -- review manually)"
                    )
                    try:
                        self.telegram.send_message(chat_id=self.chat_id, text=fallback)
                    except Exception:
                        pass
        finally:
            db.close()

        return sent_alerts


# --- STANDALONE RUN (for testing) ---

if __name__ == "__main__":
    """Test the earnings calendar without full system"""
    logging.basicConfig(level=logging.INFO)
    logger.info("Testing NSE earnings calendar fetch...")
    calendar = fetch_nse_earnings_calendar(days_ahead=14)
    logger.info("Found %d earnings events in next 14 days:", len(calendar))
    for e in calendar[:10]:
        logger.info("  %s | %s | %s", e["ticker"], e["results_date"], e["quarter"])

    logger.info("Checking against a sample watchlist...")
    sample = ["INFY", "TCS", "HDFCBANK", "RELIANCE", "BAJAJ-AUTO"]
    today  = date.today()

    matches = [e for e in calendar if e["ticker"] in sample]
    if matches:
        logger.info("Found %d watchlist stocks with upcoming earnings:", len(matches))
        for m in matches:
            results_date = date.fromisoformat(m["results_date"])
            days_away    = (results_date - today).days
            logger.info("  %s reports in %d days (%s)", m["ticker"], days_away, m["results_date"])
    else:
        logger.info("No watchlist matches -- try expanding the date range or watchlist")
