"""Tests for mcp_server.options_seller.position_manager — unit tests
for the helper functions and run_scan logic.

DB-touching methods (open_position, refresh_greeks, close_position) require
a live Postgres connection — those are integration tests excluded from unit
test CI. This file covers the pure-logic helpers only.
"""

from mcp_server.options_seller.position_manager import (
    run_scan,
)


def test_run_scan_empty_no_error(monkeypatch):
    """run_scan with no open positions should return empty list without DB access."""
    monkeypatch.setattr(
        "mcp_server.options_seller.position_manager._fetch_open_positions",
        lambda: [],
    )
    result = run_scan(spot_lookup={}, chain_lookup={})
    assert isinstance(result, list)
    assert result == []


def test_run_scan_skips_zero_spot(monkeypatch):
    """Positions with spot=0 in lookup must be skipped gracefully."""
    monkeypatch.setattr(
        "mcp_server.options_seller.position_manager._fetch_open_positions",
        lambda: [(99, "BANKNIFTY")],
    )
    # spot_lookup has BANKNIFTY=0 → should be skipped without touching refresh
    result = run_scan(spot_lookup={"BANKNIFTY": 0}, chain_lookup={})
    assert result == []


# ── n8n workflow JSON is valid ────────────────────────────────


def test_n8n_workflow_json_valid():
    import json
    from pathlib import Path
    wf_path = Path("n8n_workflows/06_options_seller_monitor.json")
    assert wf_path.exists(), "Workflow file must exist"
    data = json.loads(wf_path.read_text(encoding="utf-8"))
    assert "nodes" in data
    assert "connections" in data
    assert len(data["nodes"]) >= 10   # schedule + gates + IV checks + summarise


def test_n8n_workflow_has_all_6_instruments():
    import json
    from pathlib import Path
    data = json.loads(Path("n8n_workflows/06_options_seller_monitor.json").read_text(encoding="utf-8"))
    node_names = {n["name"] for n in data["nodes"]}
    for inst in ("BANKNIFTY", "NIFTY", "MIDCPNIFTY", "FINNIFTY", "SENSEX", "BANKEX"):
        assert any(inst in name for name in node_names), f"No node for {inst}"


def test_n8n_workflow_has_reconcile_node():
    import json
    from pathlib import Path
    data = json.loads(Path("n8n_workflows/06_options_seller_monitor.json").read_text(encoding="utf-8"))
    node_names = [n["name"] for n in data["nodes"]]
    assert any("Reconcile" in n or "reconcile" in n for n in node_names)


def test_n8n_workflow_uses_correct_base_url():
    import json
    from pathlib import Path
    raw = Path("n8n_workflows/06_options_seller_monitor.json").read_text(encoding="utf-8")
    data = json.loads(raw)
    urls = [
        n.get("parameters", {}).get("url", "")
        for n in data["nodes"]
    ]
    live_urls = [u for u in urls if u]
    assert all("money.shadowmarket.ai" in u for u in live_urls), (
        "All HTTP nodes must point to money.shadowmarket.ai"
    )
