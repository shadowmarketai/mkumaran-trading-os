"""FastAPI routers per domain.

Each module exports a `router: APIRouter` instance which is included
by the main app factory in `mcp_server.mcp_server`.

Layout follows `docs/MCP_SERVER_ROUTER_SPLIT_PLAN.md`:

    health          /health, /api/info, /api/exchanges
    auth            /auth/*, /api/auth/*
    user_settings   /api/user/*, /api/settings/*
    signals         /api/signals/*, signal-lifecycle tools
    trades          /api/trades/*, order + portfolio tools
    options         /api/options/*
    fno             /api/fno/*, F&O tools
    scanners        /tools/run_mwa_scan, /tools/detect_*, scanner-review
    watchlist       /api/watchlist/*
    wallstreet      /tools/wallstreet/*
    selfdev         /api/selfdev/*, postmortem/predictor/rules tools
    backtest        /api/backtest/*, /tools/backtest_*
    market_data     /api/chart, overview, momentum, news, mwa, etc.
    brokers         /api/kite_login, /api/gwc_login, token-refresh tools
    webhooks        /api/tv_webhook, /api/telegram_webhook
    admin           /tools/reset_sheets, /tools/stitch_*, maintenance

Routers are empty in Phase 0; populated one-at-a-time in phases 1–3.
"""
