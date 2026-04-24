"""Wall Street AI prompt tools — fundamental/technical/macro analysis.

Extracted from mcp_server.mcp_server in Phase 1c of the router split.
All 7 handlers moved verbatim.

Each endpoint wraps one of the wallstreet_tools / sector_picker helpers
with the house "investment bank persona" framing (Goldman / Morgan /
Bridgewater / JPMorgan / Citadel / Bain / McKinsey).
"""
from fastapi import APIRouter

router = APIRouter(tags=["wallstreet"])


@router.post("/tools/wallstreet/fundamental_screen")
async def tool_ws_fundamental_screen(ticker: str, company_name: str = ""):
    """Goldman Sachs-style fundamental screening."""
    from mcp_server.wallstreet_tools import fundamental_screen

    result = fundamental_screen(ticker, company_name or ticker)
    return {"status": "ok", "tool": "fundamental_screen", **result}


@router.post("/tools/wallstreet/dcf_valuation")
async def tool_ws_dcf_valuation(ticker: str, company_name: str = ""):
    """Morgan Stanley-style DCF valuation."""
    from mcp_server.wallstreet_tools import dcf_valuation

    result = dcf_valuation(ticker, company_name or ticker)
    return {"status": "ok", "tool": "dcf_valuation", **result}


@router.post("/tools/wallstreet/risk_report")
async def tool_ws_risk_report(portfolio_tickers: str = ""):
    """Bridgewater All Weather risk analysis."""
    from mcp_server.wallstreet_tools import portfolio_risk_report

    tickers = [t.strip() for t in portfolio_tickers.split(",") if t.strip()]
    result = portfolio_risk_report(tickers)
    return {"status": "ok", "tool": "risk_report", **result}


@router.post("/tools/wallstreet/earnings_brief")
async def tool_ws_earnings_brief(ticker: str, company_name: str = ""):
    """JPMorgan pre-earnings brief."""
    from mcp_server.wallstreet_tools import pre_earnings_brief

    result = pre_earnings_brief(ticker, company_name or ticker)
    return {"status": "ok", "tool": "earnings_brief", **result}


@router.post("/tools/wallstreet/technical_summary")
async def tool_ws_technical_summary(ticker: str, ohlcv_summary: str = ""):
    """Citadel 3-sentence technical summary."""
    from mcp_server.wallstreet_tools import citadel_technical_summary

    result = citadel_technical_summary(ticker, ohlcv_summary)
    return {"status": "ok", "tool": "technical_summary", "text": result}


@router.post("/tools/wallstreet/sector_analysis")
async def tool_ws_sector_analysis(ticker: str, company_name: str = ""):
    """Bain competitive sector analysis."""
    from mcp_server.sector_picker import fetch_stock_fundamentals, get_sector_peers

    peers = get_sector_peers(ticker)
    if not peers:
        return {"status": "ok", "tool": "sector_analysis", "message": f"No sector map for {ticker}"}

    fundamentals = fetch_stock_fundamentals(ticker)
    return {
        "status": "ok",
        "tool": "sector_analysis",
        "ticker": ticker,
        "sector": peers["sector"],
        "peers": peers["peers"],
        "fundamentals": fundamentals,
    }


@router.post("/tools/wallstreet/macro_assessment")
async def tool_ws_macro_assessment():
    """McKinsey macro sector rotation assessment."""
    from mcp_server.wallstreet_tools import macro_assessment

    result = macro_assessment()
    return {"status": "ok", "tool": "macro_assessment", **result}
