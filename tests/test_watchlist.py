import pytest


@pytest.mark.asyncio
async def test_add_stock(async_client):
    resp = await async_client.post(
        "/tools/manage_watchlist",
        params={"action": "add", "ticker": "RELIANCE", "tier": 2},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["action"] == "added"
    assert data["ticker"] == "NSE:RELIANCE"


@pytest.mark.asyncio
async def test_list_stocks(async_client):
    # Add first
    await async_client.post(
        "/tools/manage_watchlist",
        params={"action": "add", "ticker": "SBIN", "tier": 2},
    )
    # List
    resp = await async_client.post(
        "/tools/manage_watchlist",
        params={"action": "list"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["count"] >= 1
    tickers = [s["ticker"] for s in data["stocks"]]
    assert "NSE:SBIN" in tickers


@pytest.mark.asyncio
async def test_remove_stock(async_client):
    # Add then remove
    await async_client.post(
        "/tools/manage_watchlist",
        params={"action": "add", "ticker": "TCS"},
    )
    resp = await async_client.post(
        "/tools/manage_watchlist",
        params={"action": "remove", "ticker": "TCS"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["action"] == "removed"


@pytest.mark.asyncio
async def test_pause_stock(async_client):
    await async_client.post(
        "/tools/manage_watchlist",
        params={"action": "add", "ticker": "HDFCBANK"},
    )
    resp = await async_client.post(
        "/tools/manage_watchlist",
        params={"action": "pause", "ticker": "HDFCBANK"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["action"] == "paused"


@pytest.mark.asyncio
async def test_add_with_ltrp(async_client):
    resp = await async_client.post(
        "/tools/manage_watchlist",
        params={"action": "add", "ticker": "INFY", "ltrp": 1500.50, "pivot_high": 1800.75},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
