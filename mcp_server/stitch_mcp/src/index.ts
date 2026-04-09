#!/usr/bin/env node
/**
 * Stitch Data MCP Server for MKUMARAN Trading OS
 *
 * Exposes tools to push trading signals, trade history, and portfolio
 * snapshots to a Stitch-connected data warehouse (BigQuery, Snowflake,
 * Redshift, etc.) via the Stitch Import API v2.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

// ── Config ──────────────────────────────────────────────────────
const STITCH_API_TOKEN = process.env.STITCH_API_TOKEN ?? "";
const STITCH_CLIENT_ID = process.env.STITCH_CLIENT_ID ?? "";
const STITCH_REGION = (process.env.STITCH_REGION ?? "us").toLowerCase();

const BASE_URLS: Record<string, string> = {
  us: "https://api.stitchdata.com",
  eu: "https://api.eu-central-1.stitchdata.com",
};

function baseUrl(): string {
  return BASE_URLS[STITCH_REGION] ?? BASE_URLS.us;
}

function headers(): Record<string, string> {
  return {
    Authorization: `Bearer ${STITCH_API_TOKEN}`,
    "Content-Type": "application/json",
  };
}

function sequence(): number {
  return Date.now();
}

// ── Schemas ─────────────────────────────────────────────────────
const SIGNAL_SCHEMA = {
  signal_id: { type: "string" },
  symbol: { type: "string" },
  exchange: { type: "string" },
  direction: { type: "string" },
  entry: { type: "number" },
  stoploss: { type: "number" },
  target: { type: "number" },
  confidence: { type: "number" },
  scanner: { type: "string" },
  timestamp: { type: "string", format: "date-time" },
};

const TRADE_SCHEMA = {
  trade_id: { type: "string" },
  symbol: { type: "string" },
  direction: { type: "string" },
  entry_price: { type: "number" },
  exit_price: { type: "number" },
  pnl: { type: "number" },
  pnl_pct: { type: "number" },
  status: { type: "string" },
  opened_at: { type: "string", format: "date-time" },
  closed_at: { type: "string", format: "date-time" },
};

const PORTFOLIO_SCHEMA = {
  snapshot_id: { type: "string" },
  date: { type: "string", format: "date-time" },
  total_capital: { type: "number" },
  deployed_capital: { type: "number" },
  realized_pnl: { type: "number" },
  unrealized_pnl: { type: "number" },
  open_positions: { type: "integer" },
  win_rate: { type: "number" },
};

// ── API helpers ─────────────────────────────────────────────────
async function stitchPush(
  tableName: string,
  keyNames: string[],
  records: Record<string, unknown>[]
): Promise<unknown> {
  if (!STITCH_API_TOKEN || !STITCH_CLIENT_ID) {
    return { status: "SKIPPED", message: "Stitch not configured" };
  }

  const clientId = parseInt(STITCH_CLIENT_ID, 10);
  const seq = sequence();

  const body = records.map((rec, i) => ({
    client_id: clientId,
    table_name: tableName,
    sequence: seq + i,
    action: "upsert",
    key_names: keyNames,
    data: rec,
  }));

  const res = await fetch(`${baseUrl()}/v2/import/push`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Stitch push failed (${res.status}): ${text}`);
  }

  return res.json();
}

async function stitchBatch(
  tableName: string,
  schema: Record<string, unknown>,
  keyNames: string[],
  records: Record<string, unknown>[]
): Promise<unknown> {
  if (!STITCH_API_TOKEN) {
    return { status: "SKIPPED", message: "Stitch not configured" };
  }

  const seq = sequence();
  const body = {
    table_name: tableName,
    schema: { properties: schema },
    key_names: keyNames,
    messages: records.map((rec, i) => ({
      action: "upsert",
      sequence: seq + i,
      data: rec,
    })),
  };

  const res = await fetch(`${baseUrl()}/v2/import/batch`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Stitch batch failed (${res.status}): ${text}`);
  }

  return res.json();
}

async function stitchStatus(): Promise<unknown> {
  const res = await fetch(`${baseUrl()}/v2/import/status`, {
    headers: headers(),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Stitch status check failed (${res.status}): ${text}`);
  }
  return res.json();
}

async function stitchValidate(
  tableName: string,
  keyNames: string[],
  records: Record<string, unknown>[]
): Promise<unknown> {
  if (!STITCH_API_TOKEN || !STITCH_CLIENT_ID) {
    return { status: "SKIPPED", message: "Stitch not configured" };
  }

  const clientId = parseInt(STITCH_CLIENT_ID, 10);
  const seq = sequence();

  const body = records.map((rec, i) => ({
    client_id: clientId,
    table_name: tableName,
    sequence: seq + i,
    action: "upsert",
    key_names: keyNames,
    data: rec,
  }));

  const res = await fetch(`${baseUrl()}/v2/import/validate`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Stitch validate failed (${res.status}): ${text}`);
  }

  return res.json();
}

// ── MCP Server ──────────────────────────────────────────────────
const server = new McpServer({
  name: "stitch-trading-os",
  version: "1.0.0",
});

// Tool: Check Stitch pipeline health
server.tool(
  "stitch_status",
  "Check if the Stitch data pipeline is healthy and accepting data",
  {},
  async () => {
    try {
      const result = await stitchStatus();
      return {
        content: [
          { type: "text", text: JSON.stringify(result, null, 2) },
        ],
      };
    } catch (err) {
      return {
        content: [
          {
            type: "text",
            text: `Error: ${err instanceof Error ? err.message : String(err)}`,
          },
        ],
        isError: true,
      };
    }
  }
);

// Tool: Push trading signals
server.tool(
  "push_signals",
  "Push trading signals to the Stitch data warehouse for analytics",
  {
    signals: z
      .array(
        z.object({
          signal_id: z.string(),
          symbol: z.string(),
          exchange: z.string(),
          direction: z.enum(["LONG", "SHORT", "BUY", "SELL"]),
          entry: z.number(),
          stoploss: z.number(),
          target: z.number(),
          confidence: z.number().min(0).max(1),
          scanner: z.string(),
          timestamp: z.string(),
        })
      )
      .describe("Array of trading signal objects"),
  },
  async ({ signals }) => {
    try {
      const result = await stitchBatch(
        "trading_signals",
        SIGNAL_SCHEMA,
        ["signal_id"],
        signals
      );
      return {
        content: [
          {
            type: "text",
            text: `Pushed ${signals.length} signals to warehouse.\n${JSON.stringify(result, null, 2)}`,
          },
        ],
      };
    } catch (err) {
      return {
        content: [
          {
            type: "text",
            text: `Error pushing signals: ${err instanceof Error ? err.message : String(err)}`,
          },
        ],
        isError: true,
      };
    }
  }
);

// Tool: Push trade history
server.tool(
  "push_trades",
  "Push closed trade records to the Stitch data warehouse",
  {
    trades: z
      .array(
        z.object({
          trade_id: z.string(),
          symbol: z.string(),
          direction: z.string(),
          entry_price: z.number(),
          exit_price: z.number(),
          pnl: z.number(),
          pnl_pct: z.number(),
          status: z.enum(["WIN", "LOSS", "EXPIRED"]),
          opened_at: z.string(),
          closed_at: z.string(),
        })
      )
      .describe("Array of closed trade objects"),
  },
  async ({ trades }) => {
    try {
      const result = await stitchBatch(
        "trade_history",
        TRADE_SCHEMA,
        ["trade_id"],
        trades
      );
      return {
        content: [
          {
            type: "text",
            text: `Pushed ${trades.length} trades to warehouse.\n${JSON.stringify(result, null, 2)}`,
          },
        ],
      };
    } catch (err) {
      return {
        content: [
          {
            type: "text",
            text: `Error pushing trades: ${err instanceof Error ? err.message : String(err)}`,
          },
        ],
        isError: true,
      };
    }
  }
);

// Tool: Push portfolio snapshot
server.tool(
  "push_portfolio_snapshot",
  "Push a daily portfolio snapshot to the Stitch data warehouse",
  {
    snapshot_id: z.string(),
    date: z.string(),
    total_capital: z.number(),
    deployed_capital: z.number(),
    realized_pnl: z.number(),
    unrealized_pnl: z.number(),
    open_positions: z.number().int(),
    win_rate: z.number().min(0).max(100),
  },
  async (snapshot) => {
    try {
      const result = await stitchBatch(
        "portfolio_snapshots",
        PORTFOLIO_SCHEMA,
        ["snapshot_id"],
        [snapshot]
      );
      return {
        content: [
          {
            type: "text",
            text: `Portfolio snapshot pushed.\n${JSON.stringify(result, null, 2)}`,
          },
        ],
      };
    } catch (err) {
      return {
        content: [
          {
            type: "text",
            text: `Error pushing snapshot: ${err instanceof Error ? err.message : String(err)}`,
          },
        ],
        isError: true,
      };
    }
  }
);

// Tool: Validate records (dry run)
server.tool(
  "validate_records",
  "Dry-run validation of records against Stitch schema (no data persisted)",
  {
    table_name: z
      .enum(["trading_signals", "trade_history", "portfolio_snapshots"])
      .describe("Destination table"),
    records: z
      .array(z.record(z.unknown()))
      .describe("Records to validate"),
  },
  async ({ table_name, records }) => {
    const keyMap: Record<string, string[]> = {
      trading_signals: ["signal_id"],
      trade_history: ["trade_id"],
      portfolio_snapshots: ["snapshot_id"],
    };
    try {
      const result = await stitchValidate(
        table_name,
        keyMap[table_name],
        records
      );
      return {
        content: [
          {
            type: "text",
            text: `Validation result:\n${JSON.stringify(result, null, 2)}`,
          },
        ],
      };
    } catch (err) {
      return {
        content: [
          {
            type: "text",
            text: `Validation error: ${err instanceof Error ? err.message : String(err)}`,
          },
        ],
        isError: true,
      };
    }
  }
);

// Tool: Push custom records
server.tool(
  "push_custom",
  "Push custom records to any Stitch table with explicit schema",
  {
    table_name: z.string().describe("Destination table name"),
    key_names: z.array(z.string()).describe("Primary key columns"),
    records: z
      .array(z.record(z.unknown()))
      .describe("Array of row objects to upsert"),
  },
  async ({ table_name, key_names, records }) => {
    try {
      const result = await stitchPush(table_name, key_names, records);
      return {
        content: [
          {
            type: "text",
            text: `Pushed ${records.length} records to ${table_name}.\n${JSON.stringify(result, null, 2)}`,
          },
        ],
      };
    } catch (err) {
      return {
        content: [
          {
            type: "text",
            text: `Error: ${err instanceof Error ? err.message : String(err)}`,
          },
        ],
        isError: true,
      };
    }
  }
);

// ── Start ───────────────────────────────────────────────────────
const transport = new StdioServerTransport();
await server.connect(transport);
