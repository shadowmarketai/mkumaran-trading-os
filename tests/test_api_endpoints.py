import pytest


@pytest.mark.asyncio
async def test_api_overview(async_client):
    resp = await async_client.get("/api/overview")
    assert resp.status_code == 200
    data = resp.json()
    assert "watchlist_count" in data
    assert "active_trades" in data
    assert "win_rate" in data


@pytest.mark.asyncio
async def test_api_signals_empty(async_client):
    resp = await async_client.get("/api/signals")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_api_trades_active_empty(async_client):
    resp = await async_client.get("/api/trades/active")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_api_mwa_latest_no_data(async_client):
    resp = await async_client.get("/api/mwa/latest")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "no_data"


@pytest.mark.asyncio
async def test_api_watchlist_empty(async_client):
    resp = await async_client.get("/api/watchlist")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_api_accuracy_empty(async_client):
    resp = await async_client.get("/api/accuracy")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_signals"] == 0
    assert data["win_rate"] == 0
    assert data["total_pnl"] == 0
    assert data["by_pattern"] == []
    assert data["by_direction"] == []
    assert data["monthly_pnl"] == []


# --- Watchlist CRUD tests ---


@pytest.mark.asyncio
async def test_api_watchlist_add(async_client):
    resp = await async_client.post("/api/watchlist", params={"ticker": "RELIANCE", "tier": 1})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ticker"] == "NSE:RELIANCE"
    assert data["tier"] == 1
    assert data["active"] is True
    assert "id" in data


@pytest.mark.asyncio
async def test_api_watchlist_add_and_list(async_client):
    await async_client.post("/api/watchlist", params={"ticker": "TCS", "tier": 2, "ltrp": 3900})
    resp = await async_client.get("/api/watchlist")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["ticker"] == "NSE:TCS"
    assert items[0]["ltrp"] == 3900.0


@pytest.mark.asyncio
async def test_api_watchlist_remove(async_client):
    # Add then remove
    add_resp = await async_client.post("/api/watchlist", params={"ticker": "SBIN"})
    item_id = add_resp.json()["id"]
    del_resp = await async_client.delete(f"/api/watchlist/{item_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "ok"
    # Verify empty
    list_resp = await async_client.get("/api/watchlist")
    assert list_resp.json() == []


@pytest.mark.asyncio
async def test_api_watchlist_toggle(async_client):
    add_resp = await async_client.post("/api/watchlist", params={"ticker": "INFY"})
    item_id = add_resp.json()["id"]
    assert add_resp.json()["active"] is True
    # Toggle off
    toggle_resp = await async_client.patch(f"/api/watchlist/{item_id}/toggle")
    assert toggle_resp.status_code == 200
    assert toggle_resp.json()["active"] is False
    # Toggle back on
    toggle_resp2 = await async_client.patch(f"/api/watchlist/{item_id}/toggle")
    assert toggle_resp2.json()["active"] is True


@pytest.mark.asyncio
async def test_api_watchlist_tier_filter(async_client):
    await async_client.post("/api/watchlist", params={"ticker": "A", "tier": 1})
    await async_client.post("/api/watchlist", params={"ticker": "B", "tier": 2})
    await async_client.post("/api/watchlist", params={"ticker": "C", "tier": 1})
    # Filter tier 1
    resp = await async_client.get("/api/watchlist", params={"tier": 1})
    items = resp.json()
    assert len(items) == 2
    assert all(i["tier"] == 1 for i in items)


# --- Backtest API test ---


@pytest.mark.asyncio
async def test_api_backtest(async_client):
    resp = await async_client.post("/api/backtest", json={"ticker": "RELIANCE", "strategy": "rrms", "days": 30})
    assert resp.status_code == 200
    data = resp.json()
    assert "ticker" in data
    assert "strategy" in data
