"""
Nifty 500 Screener — FastAPI app

Run:
    uvicorn screener.main:app --host 0.0.0.0 --port 8080 --reload

Or:
    python -m screener.main
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import uvicorn
from fastapi import FastAPI
from fastapi.requests import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from screener.scanner import is_market_open, run_scan

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("screener.main")

IST           = ZoneInfo("Asia/Kolkata")
SCAN_INTERVAL = 300  # seconds

app       = FastAPI(title="Nifty 500 Screener", docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# ── In-memory state ───────────────────────────────────────────────────────

_state: dict = {
    "results":      [],
    "last_scan":    None,
    "next_scan":    None,
    "scanning":     False,
    "market_open":  False,
    "scan_count":   0,
}


async def _do_scan() -> None:
    if _state["scanning"]:
        return
    _state["scanning"]     = True
    _state["market_open"]  = is_market_open()
    logger.info("Starting scan (market_open=%s)...", _state["market_open"])
    try:
        results = await asyncio.get_event_loop().run_in_executor(None, run_scan)
        _state["results"]   = results
        _state["last_scan"] = datetime.now(IST).strftime("%H:%M:%S IST")
        _state["scan_count"] += 1
        logger.info("Scan #%d done — %d results", _state["scan_count"], len(results))
    except Exception as e:
        logger.error("Scan failed: %s", e)
    finally:
        _state["scanning"] = False
        _state["next_scan"] = SCAN_INTERVAL


async def _scheduler() -> None:
    await asyncio.sleep(2)
    while True:
        _state["market_open"] = is_market_open()
        if _state["market_open"]:
            await _do_scan()
        else:
            logger.info("Market closed — skipping scan")
            _state["last_scan"] = _state["last_scan"] or "—"
        _state["next_scan"] = SCAN_INTERVAL
        for _ in range(SCAN_INTERVAL):
            await asyncio.sleep(1)
            if _state["next_scan"] is not None:
                _state["next_scan"] = max(0, _state["next_scan"] - 1)


@app.on_event("startup")
async def startup() -> None:
    asyncio.create_task(_scheduler())


# ── Routes ────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/status")
async def status() -> dict:
    return {
        "market_open": _state["market_open"],
        "scanning":    _state["scanning"],
        "last_scan":   _state["last_scan"],
        "next_scan":   _state["next_scan"],
        "result_count": len(_state["results"]),
    }


@app.get("/api/results")
async def results() -> dict:
    return {
        "market_open": _state["market_open"],
        "scanning":    _state["scanning"],
        "last_scan":   _state["last_scan"],
        "next_scan":   _state["next_scan"],
        "results":     _state["results"],
    }


@app.post("/api/scan")
async def trigger_scan() -> dict:
    if _state["scanning"]:
        return {"status": "already_scanning"}
    if not is_market_open():
        return {"status": "market_closed"}
    asyncio.create_task(_do_scan())
    return {"status": "started"}


if __name__ == "__main__":
    uvicorn.run("screener.main:app", host="0.0.0.0", port=8080, reload=False)
