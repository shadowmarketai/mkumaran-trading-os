# sector_picker.py
# MKUMARAN Trading OS — Bain Competitive Analysis Module
# Auto-runs when any stock is added to Tier 2 watchlist via /add command
# Checks if the requested stock is the BEST in its sector for RRMS setup
#
# Usage:
#   from mcp_server.sector_picker import SectorPicker
#   picker = SectorPicker(kite)
#   result = picker.analyse(ticker="NSE:TATASTEEL")
#   -> Returns: "ADD NSE:TATASTEEL" or "CONSIDER NSE:JSWSTEEL INSTEAD -- reason"

import re
import logging
import time
import requests
import anthropic
import pandas as pd
from datetime import timedelta
from typing import Optional

from mcp_server.config import settings
from mcp_server.market_calendar import now_ist

logger = logging.getLogger(__name__)


# --- NSE SECTOR MAP ---
# Maps every NSE stock to its sector and top 4-6 peers for comparison.
# Extend this as you add new stocks to your watchlist.

NSE_SECTOR_MAP = {

    # -- ENERGY --
    "NSE:RELIANCE":    {"sector": "Energy/Refining",   "peers": ["NSE:ONGC", "NSE:BPCL", "NSE:IOC", "NSE:HINDPETRO", "NSE:GAIL"]},
    "NSE:ONGC":        {"sector": "Oil & Gas E&P",      "peers": ["NSE:RELIANCE", "NSE:OINL", "NSE:GAIL", "NSE:PETRONET"]},
    "NSE:BPCL":        {"sector": "Refineries",         "peers": ["NSE:IOC", "NSE:HINDPETRO", "NSE:RELIANCE", "NSE:MRPL"]},
    "NSE:CHENNPETRO":  {"sector": "Refineries",         "peers": ["NSE:BPCL", "NSE:IOC", "NSE:HINDPETRO", "NSE:MRPL"]},
    "NSE:GUJGASLTD":   {"sector": "Gas Distribution",   "peers": ["NSE:MGL", "NSE:IGL", "NSE:ATGL", "NSE:GAIL"]},

    # -- METALS --
    "NSE:TATASTEEL":   {"sector": "Steel/Metal",        "peers": ["NSE:JSWSTEEL", "NSE:HINDALCO", "NSE:VEDL", "NSE:NMDC", "NSE:SAIL"]},
    "NSE:JINDALSTEL":  {"sector": "Steel/Metal",        "peers": ["NSE:TATASTEEL", "NSE:JSWSTEEL", "NSE:SAIL", "NSE:NMDC"]},
    "NSE:SHYAMMETL":   {"sector": "Steel/Metal",        "peers": ["NSE:TATASTEEL", "NSE:JSWSTEEL", "NSE:NMDC", "NSE:SAIL"]},

    # -- BANKING --
    "NSE:SBIN":        {"sector": "Bank - Public",      "peers": ["NSE:PNB", "NSE:BANKBARODA", "NSE:CANBK", "NSE:UNIONBANK"]},
    "NSE:CDSL":        {"sector": "Financial Services",  "peers": ["NSE:NSDL", "NSE:BSE", "NSE:CAMS", "NSE:KFINTECH"]},
    "NSE:LICHSGFIN":   {"sector": "Housing Finance",    "peers": ["NSE:HDFC", "NSE:CANFINHOME", "NSE:AAVAS", "NSE:PNBHOUSING"]},
    "NSE:ABCAPITAL":   {"sector": "Finance - NBFC",     "peers": ["NSE:BAJFINANCE", "NSE:CHOLAFIN", "NSE:MUTHOOTFIN", "NSE:M&MFIN"]},
    "NSE:PEL":         {"sector": "Finance - NBFC",     "peers": ["NSE:BAJFINANCE", "NSE:CHOLAFIN", "NSE:ABCAPITAL", "NSE:MUTHOOTFIN"]},

    # -- AUTOS --
    "NSE:BAJAJ-AUTO":  {"sector": "Two/Three Wheelers", "peers": ["NSE:HEROMOTOCO", "NSE:TVSMOTORS", "NSE:EICHERMOT", "NSE:MOTHERSON"]},

    # -- IT / TECHNOLOGY --
    "NSE:TANLA":       {"sector": "IT - CPaaS",         "peers": ["NSE:ROUTE", "NSE:TATA_COMM", "NSE:CDSL", "NSE:NAZARA"]},
    "NSE:ECLERX":      {"sector": "IT Services",        "peers": ["NSE:MPHASIS", "NSE:PERSISTENT", "NSE:LTTS", "NSE:COFORGE"]},

    # -- INDUSTRIALS / DEFENCE --
    "NSE:BEL":         {"sector": "Aerospace & Defence","peers": ["NSE:HAL", "NSE:DCAL", "NSE:PARAS", "NSE:MTAR", "NSE:BHEL"]},
    "NSE:GMRINFRA":    {"sector": "Infrastructure",     "peers": ["NSE:ADANIPORTS", "NSE:CONCOR", "NSE:IRB", "NSE:KNRCON"]},
    "NSE:IRB":         {"sector": "Infrastructure",     "peers": ["NSE:GMRINFRA", "NSE:KNRCON", "NSE:ADANIPORTS", "NSE:HCC"]},
    "NSE:NBCC":        {"sector": "Construction - PSU", "peers": ["NSE:NCC", "NSE:PNC", "NSE:KPIL", "NSE:HCC"]},
    "NSE:BHARATFORG":  {"sector": "Industrials/Forging","peers": ["NSE:TIINDIA", "NSE:RAMKRISHNA", "NSE:CRAFTSMAN", "NSE:SUPRAJIT"]},

    # -- CONSUMER / RETAIL --
    "NSE:IRCTC":       {"sector": "Online Services",    "peers": ["NSE:EASEMYTRIP", "NSE:IXIGO", "NSE:YATHARTH", "NSE:INDIAMART"]},
    "NSE:ABFRL":       {"sector": "Retail/Fashion",     "peers": ["NSE:TRENT", "NSE:SHOPERSTOP", "NSE:VEDANT", "NSE:VSTIND"]},
    "NSE:CASTROLIND":  {"sector": "Lubricants",         "peers": ["NSE:GULFOILCORP", "NSE:TIDE", "NSE:BPCL", "NSE:IOC"]},

    # -- CEMENT --
    "NSE:ACC":         {"sector": "Cement",             "peers": ["NSE:ULTRACEMCO", "NSE:SHREECEM", "NSE:AMBUJACEMENT", "NSE:RAMCOCEM"]},
    "NSE:INDIACEM":    {"sector": "Cement",             "peers": ["NSE:ACC", "NSE:ULTRACEMCO", "NSE:RAMCOCEM", "NSE:HEIDELBERG"]},
    "NSE:CENTURYTEX":  {"sector": "Textiles/Cement",    "peers": ["NSE:INDIACEM", "NSE:ULTRACEMCO", "NSE:GRASIM", "NSE:ORIENT"]},

    # -- CHEMICALS / FERTILIZERS --
    "NSE:NFL":         {"sector": "Fertilizers",        "peers": ["NSE:GNFC", "NSE:COROMANDEL", "NSE:CHAMBERFS", "NSE:RCF"]},
    "NSE:APLLTD":      {"sector": "Pharmaceuticals",    "peers": ["NSE:SUNPHARMA", "NSE:DRREDDY", "NSE:CIPLA", "NSE:AUROPHARMA"]},

    # -- INSURANCE --
    "NSE:LICI":        {"sector": "Life Insurance",     "peers": ["NSE:HDFCLIFE", "NSE:SBILIFE", "NSE:ICICIGI", "NSE:STARHEALTH"]},

    # -- TELECOM --
    "NSE:IDEA":        {"sector": "Telecom",            "peers": ["NSE:BHARTIARTL", "NSE:TTML", "NSE:RAILTEL", "NSE:HFCL"]},
}


# --- DATA FETCHER ---

def fetch_stock_fundamentals(ticker: str) -> dict:
    """
    Fetch P/E, Revenue growth, PAT margin, ROE, D/E, Promoter%, FII%
    from Screener.in for competitive comparison.
    """
    clean_ticker = ticker.replace("NSE:", "")
    url = f"https://www.screener.in/api/company/{clean_ticker}/consolidated/"

    try:
        resp = requests.get(url, timeout=15,
                           headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code == 404:
            url = f"https://www.screener.in/api/company/{clean_ticker}/"
            resp = requests.get(url, timeout=15,
                               headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        data = resp.json()

        # Extract key metrics
        return {
            "ticker":            ticker,
            "name":              data.get("name", clean_ticker),
            "market_cap":        data.get("market_cap", "N/A"),
            "pe":                data.get("pe", "N/A"),
            "roe":               data.get("roe", "N/A"),
            "roce":              data.get("roce", "N/A"),
            "debt_equity":       data.get("debt_to_equity", "N/A"),
            "promoter_holding":  data.get("shareholding_promoter", "N/A"),
            "fii_holding":       data.get("shareholding_fii", "N/A"),
            "dii_holding":       data.get("shareholding_dii", "N/A"),
            "revenue_growth_3y": data.get("compounded_sales_growth_3years", "N/A"),
            "profit_growth_3y":  data.get("compounded_profit_growth_3years", "N/A"),
            "pat_margin":        data.get("net_profit_margin", "N/A"),
            "sales_margin":      data.get("operating_profit_margin", "N/A"),
        }

    except Exception as e:
        return {
            "ticker": ticker,
            "name":   clean_ticker,
            "error":  str(e),
            **{k: "N/A" for k in ["market_cap", "pe", "roe", "roce",
                                    "debt_equity", "promoter_holding", "fii_holding",
                                    "dii_holding", "revenue_growth_3y",
                                    "profit_growth_3y", "pat_margin", "sales_margin"]}
        }


def fetch_rrms_setup(ticker: str, kite) -> dict:
    """
    Check current RRMS setup quality for a stock.
    Returns RRR and setup quality for comparison.
    """
    try:
        from mcp_server.rrms_engine import RRMSEngine
        from mcp_server.swing_detector import find_swing_low, find_swing_high

        engine  = RRMSEngine()
        token   = kite.ltp(ticker)[ticker]["instrument_token"]
        candles = kite.historical_data(
            token,
            from_date = now_ist() - timedelta(days=120),
            to_date   = now_ist(),
            interval  = "day"
        )
        df        = pd.DataFrame(candles)
        ltrp      = find_swing_low(df)
        pivot_high = find_swing_high(df)

        if ltrp and pivot_high:
            result = engine.calculate_from_levels(ticker, ltrp, pivot_high, kite)
            return {
                "ticker":      ticker,
                "rrr":         result.get("rrr", 0),
                "within_2pct": result.get("within_2pct", False),
                "setup_grade": "A" if result.get("rrr", 0) >= 4 else
                               "B" if result.get("rrr", 0) >= 3 else
                               "C" if result.get("rrr", 0) >= 2 else "D",
            }
    except Exception as e:
        logger.debug("RRMS setup fetch failed for %s: %s", ticker, e)

    return {"ticker": ticker, "rrr": 0, "within_2pct": False, "setup_grade": "N/A"}


# --- BAIN COMPETITIVE ANALYSIS PROMPT ---

BAIN_PROMPT = """You are a senior partner at a top-tier management consulting firm
conducting a competitive strategy analysis for an Indian institutional investor.

A trader wants to add {ticker} ({company_name}) to their NSE swing trading watchlist.
Before adding, I need to know: is this the BEST stock in the {sector} sector for a
technical swing trade setup right now?

Sector: {sector}

Comparison data for {sector} sector peers:

{comparison_table}

Current RRMS technical setup quality:
{rrms_table}

Analyse for each company:

1. Competitive moat (1-line per company):
   - Brand moat: pricing power, consumer trust
   - Cost moat: operational efficiency, scale advantages
   - Regulatory moat: government contracts, licences, PSU protection
   - Distribution moat: supply chain reach

2. Capital allocation quality:
   - ROCE >20% = excellent allocator | 15-20% = good | <15% = poor
   - Consistent dividend payment or buyback = shareholder friendly
   - High promoter pledge = red flag

3. Institutional confidence:
   - Promoter holding stable/increasing = positive
   - FII holding >15% = international validation
   - FII holding increasing QoQ = smart money accumulating

4. Market position trend:
   - Is this company gaining or losing market share?
   - Is management guiding for growth or managing decline?

Then provide:
5. SWOT analysis for TOP 2 companies only (brief -- 3 points each)

6. Single best stock for RRMS swing trade in this sector:
   - Strongest moat + best technical setup + institutional backing

7. Final decision on the originally requested stock {ticker}:
   - "ADD {ticker}" -- if it IS the best setup
   - "CONSIDER {alternative} INSTEAD -- [specific reason]"
   - "BOTH VALID -- {ticker} for [reason], {alternative} for [reason]"

Indian market moat indicators to weight heavily:
- PSU (government) stocks: regulatory moat but often poor capital allocation (ROCE <10%)
- Promoter holding >60% + stable = strong founding alignment
- FII holding increasing = global institutional validation
- Consistent ROCE >20% over 5 years = genuine competitive moat
- High debt/equity (>2) in cyclical sectors = higher risk in downturns

Keep output concise -- this goes into a Telegram message.
End with a clear DECISION LINE (one sentence, starts with ADD or CONSIDER or BOTH).
"""


# --- MAIN SECTOR PICKER CLASS ---

class SectorPicker:
    """
    Main class -- call analyse(ticker) when stock is added to watchlist.
    Integrates with manage_watchlist() in mcp_server.py.
    """

    def __init__(self, kite, delay_between_requests: float = 1.0):
        self.kite    = kite
        self.delay   = delay_between_requests
        self.client  = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    def get_sector_peers(self, ticker: str) -> Optional[dict]:
        """Get sector and peers for a ticker. Returns None if not mapped."""
        return NSE_SECTOR_MAP.get(ticker)

    def build_comparison_table(self, ticker: str, peers: list) -> tuple:
        """
        Fetch fundamentals for main stock + all peers.
        Returns (formatted_table_string, list_of_all_data)
        """
        all_tickers = [ticker] + peers
        all_data    = []

        logger.info("Fetching fundamentals for %d stocks...", len(all_tickers))
        for t in all_tickers:
            logger.debug("  -> %s", t)
            data = fetch_stock_fundamentals(t)
            all_data.append(data)
            time.sleep(self.delay)  # Polite to Screener.in

        # Build formatted comparison table
        header = (
            f"{'Ticker':15} | {'MCap(Cr)':10} | {'P/E':6} | "
            f"{'ROE%':6} | {'ROCE%':6} | {'D/E':5} | "
            f"{'Promoter%':9} | {'FII%':6} | {'Rev CAGR 3yr':12} | {'PAT Margin':10}\n"
        )
        separator = "-" * 110 + "\n"
        table     = header + separator

        for d in all_data:
            marker = " <- REQUESTED" if d["ticker"] == ticker else ""
            table += (
                f"{d['ticker']:15} | {str(d['market_cap']):10} | {str(d['pe']):6} | "
                f"{str(d['roe']):6} | {str(d['roce']):6} | {str(d['debt_equity']):5} | "
                f"{str(d['promoter_holding']):9} | {str(d['fii_holding']):6} | "
                f"{str(d['revenue_growth_3y']):12} | {str(d['pat_margin']):10}"
                f"{marker}\n"
            )

        return table, all_data

    def build_rrms_table(self, ticker: str, peers: list) -> str:
        """Build RRMS setup quality comparison table."""
        all_tickers = [ticker] + peers
        table       = f"{'Ticker':15} | {'RRR':6} | {'Within 2% of LTRP':18} | Grade\n"
        table      += "-" * 55 + "\n"

        for t in all_tickers:
            try:
                setup  = fetch_rrms_setup(t, self.kite)
                marker = " <- REQUESTED" if t == ticker else ""
                table += (
                    f"{t:15} | {str(round(setup['rrr'], 1)):6} | "
                    f"{'YES' if setup['within_2pct'] else 'No':18} | "
                    f"{setup['setup_grade']}{marker}\n"
                )
            except Exception:
                table += f"{t:15} | N/A    | N/A                | N/A\n"

        return table

    def analyse(self, ticker: str) -> dict:
        """
        Main method -- run Bain competitive analysis for a ticker.
        Called automatically when stock is added via /add command.

        Returns:
            {
                "ticker": str,
                "decision": "ADD" | "CONSIDER" | "BOTH",
                "recommended": str,  # ticker to actually add
                "brief": str,        # full analysis for Telegram
                "telegram_msg": str, # formatted Telegram message
            }
        """
        logger.info("[SectorPicker] Analysing %s...", ticker)

        # Check if ticker is in our sector map
        sector_data = self.get_sector_peers(ticker)
        if not sector_data:
            logger.info("  %s not in sector map -- skipping competitive analysis", ticker)
            return {
                "ticker":       ticker,
                "decision":     "ADD",
                "recommended":  ticker,
                "brief":        f"No sector map for {ticker}. Add to NSE_SECTOR_MAP for competitive analysis.",
                "telegram_msg": f"INFO: {ticker} added. (No sector peers mapped -- update NSE_SECTOR_MAP in sector_picker.py)",
                "skipped":      True,
            }

        sector = sector_data["sector"]
        peers  = sector_data["peers"]

        # Get company name
        fundamentals = fetch_stock_fundamentals(ticker)
        company_name = fundamentals.get("name", ticker.replace("NSE:", ""))

        # Build comparison tables
        logger.info("  Sector: %s | Comparing %d peers", sector, len(peers))
        comparison_table, all_data = self.build_comparison_table(ticker, peers)
        rrms_table = self.build_rrms_table(ticker, peers)

        # Build and send prompt to Claude
        prompt = BAIN_PROMPT.format(
            ticker           = ticker,
            company_name     = company_name,
            sector           = sector,
            comparison_table = comparison_table,
            rrms_table       = rrms_table,
            alternative      = peers[0] if peers else ticker,
        )

        logger.info("  Sending to Claude for analysis...")
        response = self.client.messages.create(
            model      = "claude-sonnet-4-6",
            max_tokens = 1000,
            messages   = [{"role": "user", "content": prompt}]
        )
        brief = response.content[0].text

        # Parse decision from brief
        decision    = "ADD"
        recommended = ticker

        brief_lower = brief.lower()
        if "consider" in brief_lower:
            decision = "CONSIDER"
            # Try to extract the alternative ticker
            lines = brief.split("\n")
            for line in lines:
                if "consider" in line.lower() and "nse:" in line.upper():
                    match = re.search(r'NSE:[A-Z\-]+', line)
                    if match and match.group(0) != ticker:
                        recommended = match.group(0)
                        break
        elif "both" in brief_lower:
            decision = "BOTH"

        # Format Telegram message
        decision_label = {"ADD": "OK", "CONSIDER": "ALT", "BOTH": "BOTH"}.get(decision, "INFO")

        telegram_msg = (
            f"[{decision_label}] SECTOR ANALYSIS -- {ticker}\n"
            f"{'=' * 35}\n"
            f"Sector  : {sector}\n"
            f"Compared: {len(peers)} peers\n"
            f"{'=' * 35}\n"
            f"{brief}\n"
            f"{'=' * 35}\n"
        )

        if decision == "CONSIDER" and recommended != ticker:
            telegram_msg += (
                f"Action: Consider /add {recommended} instead\n"
                f"Or keep: /add {ticker} if you specifically want this stock"
            )
        else:
            telegram_msg += f"Action: {ticker} added to Tier 2 watchlist"

        logger.info("  Decision: %s | Recommended: %s", decision, recommended)

        return {
            "ticker":       ticker,
            "decision":     decision,
            "recommended":  recommended,
            "sector":       sector,
            "brief":        brief,
            "telegram_msg": telegram_msg,
            "all_data":     all_data,
        }

    def batch_analyse(self, tickers: list) -> list:
        """
        Analyse multiple tickers at once.
        Used when seeding the initial 29-stock watchlist.
        """
        results = []
        for ticker in tickers:
            result = self.analyse(ticker)
            results.append(result)
            time.sleep(2)  # Delay between analyses
        return results

    def add_to_sector_map(self, ticker: str, sector: str, peers: list):
        """
        Dynamically add a new stock to the sector map.
        Called when /add is used for a stock not yet mapped.
        """
        NSE_SECTOR_MAP[ticker] = {"sector": sector, "peers": peers}
        logger.info("Added %s to sector map: %s", ticker, sector)


# --- STANDALONE TEST ---

if __name__ == "__main__":
    """Test sector picker without full system -- requires ANTHROPIC_API_KEY in env"""
    import sys
    logging.basicConfig(level=logging.INFO)

    ticker = sys.argv[1] if len(sys.argv) > 1 else "NSE:TATASTEEL"
    logger.info("Testing SectorPicker for %s", ticker)
    logger.info("=" * 60)

    # Check sector map
    if ticker in NSE_SECTOR_MAP:
        data = NSE_SECTOR_MAP[ticker]
        logger.info("Sector: %s", data["sector"])
        logger.info("Peers:  %s", ", ".join(data["peers"]))
    else:
        logger.info("%s not in sector map.", ticker)
        logger.info("Available tickers:")
        for t in sorted(NSE_SECTOR_MAP.keys()):
            logger.info("  %s", t)
        sys.exit(1)

    # Test fundamental fetch (no Kite needed)
    logger.info("Fetching fundamentals for %s...", ticker)
    fund = fetch_stock_fundamentals(ticker)
    logger.info("  Name:     %s", fund["name"])
    logger.info("  P/E:      %s", fund["pe"])
    logger.info("  ROE:      %s%%", fund["roe"])
    logger.info("  ROCE:     %s%%", fund["roce"])
    logger.info("  D/E:      %s", fund["debt_equity"])
    logger.info("  Promoter: %s%%", fund["promoter_holding"])
    logger.info("  FII:      %s%%", fund["fii_holding"])
    logger.info("  Rev CAGR: %s%%", fund["revenue_growth_3y"])

    logger.info("To run full competitive analysis (requires Kite + Anthropic API):")
    logger.info("  picker = SectorPicker(kite)")
    logger.info("  result = picker.analyse('%s')", ticker)
    logger.info("  logger.info(result['telegram_msg'])")
