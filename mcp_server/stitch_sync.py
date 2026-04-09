"""Stitch Data Import API integration for MKUMARAN Trading OS.

Pushes trading signals, portfolio snapshots, and trade history to a
Stitch-connected data warehouse (BigQuery, Snowflake, Redshift, etc.)
via the Stitch Import API v2.
"""

import logging
import time
from typing import Any

import httpx

from mcp_server.config import settings

logger = logging.getLogger(__name__)

# ── Stitch API constants ────────────────────────────────────────────
_BASE_URLS = {
    "us": "https://api.stitchdata.com",
    "eu": "https://api.eu-central-1.stitchdata.com",
}
_MAX_BATCH_RECORDS = 20_000
_MAX_BATCH_BYTES = 20 * 1024 * 1024  # 20 MB


# ── Helpers ─────────────────────────────────────────────────────────

def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.STITCH_API_TOKEN}",
        "Content-Type": "application/json",
    }


def _base_url() -> str:
    region = getattr(settings, "STITCH_REGION", "us").lower()
    return _BASE_URLS.get(region, _BASE_URLS["us"])


def _sequence() -> int:
    """Monotonically increasing sequence (epoch ms)."""
    return int(time.time() * 1000)


# ── Core API functions ──────────────────────────────────────────────

async def stitch_status() -> dict:
    """GET /v2/import/status — check if Stitch pipeline is healthy."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{_base_url()}/v2/import/status")
        r.raise_for_status()
        return r.json()


async def stitch_push(
    table_name: str,
    key_names: list[str],
    records: list[dict[str, Any]],
) -> dict:
    """POST /v2/import/push — upsert records into Stitch pipeline.

    Args:
        table_name: Destination table (e.g. "trading_signals").
        key_names: Primary-key columns for upsert dedup.
        records: List of row dicts to push.

    Returns:
        Stitch batch-status response.
    """
    if not settings.STITCH_API_TOKEN or not settings.STITCH_CLIENT_ID:
        return {"status": "SKIPPED", "message": "Stitch not configured"}

    if len(records) > _MAX_BATCH_RECORDS:
        return {"status": "ERROR", "message": f"Batch exceeds {_MAX_BATCH_RECORDS} records"}

    client_id = int(settings.STITCH_CLIENT_ID)
    seq = _sequence()

    body = [
        {
            "client_id": client_id,
            "table_name": table_name,
            "sequence": seq + i,
            "action": "upsert",
            "key_names": key_names,
            "data": rec,
        }
        for i, rec in enumerate(records)
    ]

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{_base_url()}/v2/import/push",
            headers=_headers(),
            json=body,
        )
        r.raise_for_status()
        result = r.json()
        logger.info("Stitch push → %s: %d records → %s", table_name, len(records), result.get("status"))
        return result


async def stitch_batch(
    table_name: str,
    schema: dict[str, Any],
    key_names: list[str],
    records: list[dict[str, Any]],
) -> dict:
    """POST /v2/import/batch — push records with explicit JSON schema.

    Use this when sending a new table or when schema changes.
    """
    if not settings.STITCH_API_TOKEN:
        return {"status": "SKIPPED", "message": "Stitch not configured"}

    seq = _sequence()
    body = {
        "table_name": table_name,
        "schema": {"properties": schema},
        "key_names": key_names,
        "messages": [
            {"action": "upsert", "sequence": seq + i, "data": rec}
            for i, rec in enumerate(records)
        ],
    }

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{_base_url()}/v2/import/batch",
            headers=_headers(),
            json=body,
        )
        r.raise_for_status()
        result = r.json()
        logger.info("Stitch batch → %s: %d records → %s", table_name, len(records), result.get("status"))
        return result


async def stitch_validate(
    table_name: str,
    key_names: list[str],
    records: list[dict[str, Any]],
) -> dict:
    """POST /v2/import/validate — dry-run validation (no persist)."""
    if not settings.STITCH_API_TOKEN or not settings.STITCH_CLIENT_ID:
        return {"status": "SKIPPED", "message": "Stitch not configured"}

    client_id = int(settings.STITCH_CLIENT_ID)
    seq = _sequence()

    body = [
        {
            "client_id": client_id,
            "table_name": table_name,
            "sequence": seq + i,
            "action": "upsert",
            "key_names": key_names,
            "data": rec,
        }
        for i, rec in enumerate(records)
    ]

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            f"{_base_url()}/v2/import/validate",
            headers=_headers(),
            json=body,
        )
        r.raise_for_status()
        return r.json()


# ── Trading-OS convenience wrappers ─────────────────────────────────

SIGNAL_SCHEMA = {
    "signal_id": {"type": "string"},
    "symbol": {"type": "string"},
    "exchange": {"type": "string"},
    "direction": {"type": "string"},
    "entry": {"type": "number"},
    "stoploss": {"type": "number"},
    "target": {"type": "number"},
    "confidence": {"type": "number"},
    "scanner": {"type": "string"},
    "timestamp": {"type": "string", "format": "date-time"},
}

TRADE_SCHEMA = {
    "trade_id": {"type": "string"},
    "symbol": {"type": "string"},
    "direction": {"type": "string"},
    "entry_price": {"type": "number"},
    "exit_price": {"type": "number"},
    "pnl": {"type": "number"},
    "pnl_pct": {"type": "number"},
    "status": {"type": "string"},
    "opened_at": {"type": "string", "format": "date-time"},
    "closed_at": {"type": "string", "format": "date-time"},
}

PORTFOLIO_SCHEMA = {
    "snapshot_id": {"type": "string"},
    "date": {"type": "string", "format": "date-time"},
    "total_capital": {"type": "number"},
    "deployed_capital": {"type": "number"},
    "realized_pnl": {"type": "number"},
    "unrealized_pnl": {"type": "number"},
    "open_positions": {"type": "integer"},
    "win_rate": {"type": "number"},
}


async def push_signals(signals: list[dict]) -> dict:
    """Push trading signals to Stitch → warehouse."""
    return await stitch_batch("trading_signals", SIGNAL_SCHEMA, ["signal_id"], signals)


async def push_trades(trades: list[dict]) -> dict:
    """Push closed trades to Stitch → warehouse."""
    return await stitch_batch("trade_history", TRADE_SCHEMA, ["trade_id"], trades)


async def push_portfolio_snapshot(snapshot: dict) -> dict:
    """Push daily portfolio snapshot to Stitch → warehouse."""
    return await stitch_batch("portfolio_snapshots", PORTFOLIO_SCHEMA, ["snapshot_id"], [snapshot])
