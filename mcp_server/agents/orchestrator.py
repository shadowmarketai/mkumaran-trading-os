"""
Agent Orchestrator — manages lifecycle of all trading agents.

Starts each agent as an independent asyncio task with its own scan
interval and market-hours check. Agents run in parallel and don't
block each other.

Usage (in mcp_server.py startup):
    from mcp_server.agents.orchestrator import start_all_agents
    await start_all_agents()
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def start_all_agents() -> list[asyncio.Task]:
    """Start all trading agents as background tasks. Returns task handles."""
    from mcp_server.agents.options_index_agent import OptionsIndexAgent
    from mcp_server.agents.options_stock_agent import OptionsStockAgent
    from mcp_server.agents.commodity_agent import CommodityAgent
    from mcp_server.agents.forex_agent import ForexAgent
    from mcp_server.agents.futures_agent import FuturesAgent

    agents = [
        OptionsIndexAgent(),
        OptionsStockAgent(),
        CommodityAgent(),
        ForexAgent(),
        FuturesAgent(),
    ]

    tasks = []
    for agent in agents:
        task = asyncio.create_task(agent.run_loop())
        tasks.append(task)
        logger.info(
            "Agent started: %s (segment=%s, interval=%ds)",
            agent.name, agent.segment, agent.scan_interval,
        )

    logger.info("All %d trading agents started", len(agents))
    return tasks


def get_agent_status() -> list[dict[str, Any]]:
    """Return status info for each agent (for dashboard/health endpoint)."""
    from mcp_server.agents.options_index_agent import OptionsIndexAgent
    from mcp_server.agents.options_stock_agent import OptionsStockAgent
    from mcp_server.agents.commodity_agent import CommodityAgent
    from mcp_server.agents.forex_agent import ForexAgent
    from mcp_server.agents.futures_agent import FuturesAgent

    agents = [
        OptionsIndexAgent(),
        OptionsStockAgent(),
        CommodityAgent(),
        ForexAgent(),
        FuturesAgent(),
    ]

    return [
        {
            "name": a.name,
            "segment": a.segment,
            "scan_interval": a.scan_interval,
            "market_hours": f"{a.market_open_time}-{a.market_close_time}",
            "max_signals_per_day": a.max_signals_per_day,
        }
        for a in agents
    ]
