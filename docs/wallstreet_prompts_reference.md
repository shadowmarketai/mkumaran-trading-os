# MKUMARAN Trading OS -- 10 Wall Street Prompts (NSE/India Adapted)

These prompts are implemented in `mcp_server/prompts.py` and callable via `mcp_server/wallstreet_tools.py`.

| # | Prompt | Trigger | Frequency |
|---|--------|---------|-----------|
| 1 | Goldman Screener | Auto -- signal validation | Per signal |
| 2 | Morgan Stanley DCF | Cowork Dispatch "DCF TICKER" | On demand |
| 3 | Bridgewater Risk | Auto -- n8n Sunday 6 PM | Weekly |
| 4 | JPMorgan Earnings | Auto -- 2 days before results | Per event |
| 5 | BlackRock Portfolio | Cowork Dispatch "Portfolio review" | Quarterly |
| 6 | Citadel Technical | Auto -- signal validation | Per signal |
| 7 | Harvard Dividend | Cowork Dispatch "Dividend portfolio" | On demand |
| 8 | Bain Competitive | Auto -- /add command | Per watchlist add |
| 9 | Renaissance Patterns | Auto -- Tier 2 promotion | Per promotion |
| 10 | McKinsey Macro | Auto -- n8n 1st of month | Monthly |

See original spec: MKUMARAN_WallStreet_Prompts_NSE_Adapted.md
