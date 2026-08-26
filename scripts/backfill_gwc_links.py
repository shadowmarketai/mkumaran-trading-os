#!/usr/bin/env python
"""
Re-run the improved GWC auto-linker against existing unlinked LOG rows.

Usage:
    python scripts/backfill_gwc_links.py            # dry-run (prints matches, no writes)
    python scripts/backfill_gwc_links.py --live      # actually update Sheets

The script reads every RESULT row in GWC LOG whose "Linked Signal" cell is
empty, re-runs the fixed linker using each row's own date as the anchor, and
optionally writes the match back to both the LOG and TRACKER.

Review the dry-run output carefully before passing --live.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def run_backfill(live: bool) -> None:
    from mcp_server.gwc_tracker import (
        GWCMessageType,
        classify_gwc_message,
        link_gwc_outcome_from_message,
    )
    from mcp_server.sheets_sync import _get_sheets_client

    _, sheet = _get_sheets_client()
    if not sheet:
        logger.error("Google Sheets not connected.")
        sys.exit(1)

    try:
        log_ws   = sheet.worksheet("GWC LOG")
        log_rows = log_ws.get_all_values()
    except Exception as exc:
        logger.error("Cannot read GWC LOG: %s", exc)
        sys.exit(1)

    if len(log_rows) <= 1:
        logger.info("GWC LOG is empty.")
        return

    header = log_rows[0]
    try:
        col_date   = header.index("Date")
        col_type   = header.index("Type")
        col_raw    = header.index("Raw Message")
        col_linked = header.index("Linked Signal")
    except ValueError as exc:
        logger.error("GWC LOG header missing column: %s", exc)
        sys.exit(1)

    unlinked_results: list[tuple[int, str, str]] = []  # (sheet_row, raw_text, row_date)
    for i, row in enumerate(log_rows[1:], start=2):
        if len(row) <= max(col_date, col_type, col_raw, col_linked):
            continue
        if row[col_type] != "RESULT":
            continue
        if row[col_linked].strip():
            continue  # already linked
        raw  = row[col_raw]
        rdate = row[col_date]
        if raw:
            unlinked_results.append((i, raw, rdate))

    logger.info("Found %d unlinked RESULT rows in GWC LOG.", len(unlinked_results))
    if not unlinked_results:
        logger.info("Nothing to backfill.")
        return

    matched = 0
    for sheet_row, raw_text, row_date_str in unlinked_results:
        try:
            as_of = date.fromisoformat(row_date_str)
        except ValueError:
            logger.warning("Row %d: cannot parse date '%s', skipping.", sheet_row, row_date_str)
            continue

        msg_type, extracted = classify_gwc_message(raw_text)
        if msg_type != GWCMessageType.RESULT:
            continue

        # Widen the window by also checking day-after (some results arrive at EOD
        # for signals posted the previous day, but here we anchor on the LOG date)
        desc = link_gwc_outcome_from_message(raw_text, extracted, as_of_date=as_of)

        if not desc:
            logger.info("  Row %d (%s): no match — %s", sheet_row, row_date_str, raw_text[:60])
            continue

        matched += 1
        if live:
            # Write back to the LOG row's Linked Signal column (1-based)
            log_ws.update_cell(sheet_row, col_linked + 1, desc)
            logger.info("  Row %d (%s): LINKED -> %s", sheet_row, row_date_str, desc)
        else:
            logger.info("  Row %d (%s): WOULD LINK -> %s", sheet_row, row_date_str, desc)

    mode = "Updated" if live else "Would update"
    logger.info("%s %d / %d unlinked rows.", mode, matched, len(unlinked_results))
    if not live and matched > 0:
        logger.info("Re-run with --live to apply.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill GWC LOG auto-links")
    parser.add_argument("--live", action="store_true", help="Write changes to Sheets (default: dry-run)")
    args = parser.parse_args()

    if not args.live:
        logger.info("DRY-RUN mode — no Sheets writes. Pass --live to apply.")

    run_backfill(live=args.live)


if __name__ == "__main__":
    main()
