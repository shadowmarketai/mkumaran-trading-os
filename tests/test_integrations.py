"""
Tests for integration wiring:
1. n8n workflow JSON structure validation
2. Kite connect endpoint
3. Google Sheets auto-sync helper
4. TradingView webhook endpoint
5. Full signal pipeline flow
"""

import json
import os

import pytest


# ============================================================
# 1. n8n Workflow Structure Validation
# ============================================================

WORKFLOWS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "n8n_workflows"
)

EXPECTED_WORKFLOWS = {
    "00_morning_startup.json": {"min_nodes": 8, "has_schedule": True},
    "01_signal_receiver.json": {"min_nodes": 8, "has_schedule": False},
    "02_market_monitor.json": {"min_nodes": 10, "has_schedule": True},
    "03_eod_report.json": {"min_nodes": 6, "has_schedule": True},
}


class TestN8nWorkflows:

    def _load_workflow(self, filename):
        path = os.path.join(WORKFLOWS_DIR, filename)
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def test_all_4_workflows_exist(self):
        for filename in EXPECTED_WORKFLOWS:
            path = os.path.join(WORKFLOWS_DIR, filename)
            assert os.path.exists(path), f"Missing workflow: {filename}"

    def test_all_workflows_valid_json(self):
        for filename in EXPECTED_WORKFLOWS:
            data = self._load_workflow(filename)
            assert "nodes" in data
            assert "connections" in data
            assert isinstance(data["nodes"], list)

    def test_workflows_have_enough_nodes(self):
        for filename, spec in EXPECTED_WORKFLOWS.items():
            data = self._load_workflow(filename)
            assert len(data["nodes"]) >= spec["min_nodes"], (
                f"{filename} has {len(data['nodes'])} nodes, need {spec['min_nodes']}"
            )

    def test_workflows_have_connections(self):
        for filename in EXPECTED_WORKFLOWS:
            data = self._load_workflow(filename)
            assert len(data["connections"]) > 0, (
                f"{filename} has no connections"
            )

    def test_scheduled_workflows_have_cron(self):
        for filename, spec in EXPECTED_WORKFLOWS.items():
            if not spec["has_schedule"]:
                continue
            data = self._load_workflow(filename)
            trigger = data["nodes"][0]
            assert "scheduleTrigger" in trigger["type"] or "cron" in str(trigger.get("parameters", {})).lower(), (
                f"{filename} should have schedule trigger"
            )

    def test_workflows_have_http_requests(self):
        """Every workflow should call at least one MCP server endpoint."""
        for filename in EXPECTED_WORKFLOWS:
            data = self._load_workflow(filename)
            http_nodes = [
                n for n in data["nodes"]
                if "httpRequest" in n.get("type", "")
            ]
            assert len(http_nodes) >= 1, (
                f"{filename} has no HTTP request nodes"
            )

    def test_workflows_target_mcp_server(self):
        for filename in EXPECTED_WORKFLOWS:
            data = self._load_workflow(filename)
            raw = json.dumps(data)
            # Workflows should target money.shadowmarket.ai or localhost:8001
            has_mcp = "money.shadowmarket.ai" in raw or "localhost:8001" in raw
            if "signal_receiver" not in filename:
                assert has_mcp, f"{filename} should target MCP server"

    def test_morning_startup_calls_connect_kite_and_mwa(self):
        data = self._load_workflow("00_morning_startup.json")
        urls = [n.get("parameters", {}).get("url", "") for n in data["nodes"]]
        assert any("connect_kite" in u for u in urls)
        assert any("run_mwa_scan" in u for u in urls)

    def test_signal_receiver_has_tv_webhook(self):
        data = self._load_workflow("01_signal_receiver.json")
        urls = [n.get("parameters", {}).get("url", "") for n in data["nodes"]]
        assert any("tv_webhook" in u for u in urls)
        assert any("telegram_webhook" in u for u in urls)

    def test_eod_calls_summary_and_momentum(self):
        # EOD workflow was simplified to a two-phase flow: pull `eod_summary`
        # (aggregate P&L, accuracy, open signals) and `momentum` (end-of-day
        # momentum snapshot), each followed by a Telegram push. The earlier
        # `signal_accuracy` + `reflect_trades` endpoints were folded into
        # `eod_summary` server-side.
        data = self._load_workflow("03_eod_report.json")
        urls = [n.get("parameters", {}).get("url", "") for n in data["nodes"]]
        assert any("eod_summary" in u for u in urls), "EOD should pull aggregate summary"
        assert any("momentum" in u for u in urls), "EOD should pull momentum snapshot"

    def test_market_monitor_has_kill_switch_and_fo(self):
        data = self._load_workflow("02_market_monitor.json")
        urls = [n.get("parameters", {}).get("url", "") for n in data["nodes"]]
        assert any("order_status" in u for u in urls)
        assert any("close_all" in u for u in urls)
        assert any("get_fo_signal" in u for u in urls)

    def test_all_workflows_tagged(self):
        for filename in EXPECTED_WORKFLOWS:
            data = self._load_workflow(filename)
            tags = [t.get("name", "") for t in data.get("tags", [])]
            assert "mkumaran-trading-os" in tags


# ============================================================
# 2. Kite Connect Endpoint
# ============================================================

class TestKiteConnect:

    @pytest.mark.asyncio
    async def test_connect_kite_without_credentials(self, async_client):
        """Without Kite credentials, should fail gracefully."""
        resp = await async_client.post("/tools/connect_kite")
        assert resp.status_code == 200
        data = resp.json()
        # Either already connected=False or error message
        assert "kite_connected" in data

    @pytest.mark.asyncio
    async def test_order_status_endpoint(self, async_client):
        resp = await async_client.get("/tools/order_status")
        assert resp.status_code == 200
        data = resp.json()
        assert "kill_switch_active" in data
        assert "open_positions" in data


# ============================================================
# 3. Google Sheets Auto-Sync Helper
# ============================================================

class TestSheetsAutoSync:

    def test_sheets_sync_functions_exist(self):
        from mcp_server.sheets_sync import (
            sync_watchlist, log_signal, update_accuracy,
            log_mwa, sync_active_trades,
        )
        assert callable(sync_watchlist)
        assert callable(log_signal)
        assert callable(update_accuracy)
        assert callable(log_mwa)
        assert callable(sync_active_trades)

    def test_sheets_sync_no_credentials_returns_false(self):
        from mcp_server.sheets_sync import log_signal
        result = log_signal({"ticker": "NSE:TEST", "direction": "BUY"})
        assert result is False  # No Google credentials configured

    def test_auto_sync_helper_exists(self):
        """The _auto_sync_sheets async helper should exist in mcp_server."""
        from mcp_server.mcp_server import _auto_sync_sheets
        import asyncio
        assert asyncio.iscoroutinefunction(_auto_sync_sheets)


# ============================================================
# 4. TradingView Webhook Endpoint
# ============================================================

class TestTVWebhook:

    @pytest.mark.asyncio
    async def test_tv_webhook_exists(self, async_client):
        """TV webhook endpoint should respond."""
        resp = await async_client.post("/api/tv_webhook", json={
            "ticker": "RELIANCE",
            "direction": "LONG",
            "entry": 2500,
            "sl": 2400,
            "target": 2800,
            "rrr": 3.0,
            "qty": 10,
            "source": "tradingview",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "tradingview"
        assert "NSE:RELIANCE" in data["ticker"]

    @pytest.mark.asyncio
    async def test_tv_webhook_normalizes_ticker(self, async_client):
        """Ticker without exchange prefix gets NSE: added."""
        resp = await async_client.post("/api/tv_webhook", json={
            "ticker": "SBIN",
            "direction": "BUY",
            "entry": 600,
            "sl": 580,
            "target": 680,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "NSE:SBIN"

    @pytest.mark.asyncio
    async def test_tv_webhook_with_exchange_prefix(self, async_client):
        """Ticker with exchange prefix kept as-is."""
        resp = await async_client.post("/api/tv_webhook", json={
            "ticker": "MCX:GOLD",
            "direction": "LONG",
            "entry": 70000,
            "sl": 69000,
            "target": 72000,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "MCX:GOLD"

    @pytest.mark.asyncio
    async def test_tv_webhook_returns_signal_id(self, async_client):
        resp = await async_client.post("/api/tv_webhook", json={
            "ticker": "TATAMOTORS",
            "direction": "LONG",
            "entry": 950,
            "sl": 920,
            "target": 1050,
        })
        data = resp.json()
        assert "signal_id" in data

    @pytest.mark.asyncio
    async def test_tv_webhook_short_direction(self, async_client):
        resp = await async_client.post("/api/tv_webhook", json={
            "ticker": "NIFTY",
            "direction": "SHORT",
            "entry": 22000,
            "sl": 22200,
            "target": 21600,
        })
        data = resp.json()
        assert data["direction"] == "SHORT"


# ============================================================
# 5. Full Signal Pipeline
# ============================================================

class TestSignalPipeline:

    @pytest.mark.asyncio
    async def test_record_then_accuracy(self, async_client):
        """Record a signal, then check accuracy returns it."""
        # Record
        resp = await async_client.post("/tools/record_signal", json={
            "ticker": "NSE:INFY",
            "direction": "BUY",
            "entry_price": 1500,
            "stop_loss": 1450,
            "target": 1650,
        })
        assert resp.status_code == 200

        # Accuracy check should work (even if Sheets not connected)
        resp2 = await async_client.get("/tools/signal_accuracy")
        assert resp2.status_code == 200

    @pytest.mark.asyncio
    async def test_telegram_webhook_parses_signal(self, async_client):
        resp = await async_client.post("/api/telegram_webhook", json={
            "text": "BUY NSE:HDFCBANK @ 1600 SL 1550 TGT 1800",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["parsed"] is True
        assert "HDFCBANK" in data.get("ticker", "")

    @pytest.mark.asyncio
    async def test_telegram_webhook_rejects_nonsignal(self, async_client):
        resp = await async_client.post("/api/telegram_webhook", json={
            "text": "Good morning everyone",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["parsed"] is False
