"""
Refresh TradingView session cookies via an interactive browser login.

Usage:
    python scripts/refresh_tv_cookies.py [--env PATH] [--timeout SECONDS]

Opens Chromium headed, lets you log in to TradingView manually, polls for
the `sessionid` + `sessionid_sign` cookies (they are HttpOnly, so this is
the only programmatic way to read them), then merges them into .env
while preserving every other entry.

After writing, runs one authenticated scanner query to verify the cookies
actually work against scanner.tradingview.com before exiting.

Installation (one-time):
    pip install playwright
    playwright install chromium

TV sessions typically last ~30 days. Re-run this script when the scanner
starts falling back to anonymous (~15 min delayed) responses.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV = REPO_ROOT / ".env"
LOGIN_URL = "https://in.tradingview.com/"
REQUIRED = ("sessionid", "sessionid_sign")


def _launch_browser_and_wait(timeout: int) -> tuple[str, str]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit(
            "[!] playwright is not installed. Install it with:\n"
            "      pip install playwright\n"
            "      playwright install chromium"
        )

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        print(f"[*] Opening {LOGIN_URL}")
        page.goto(LOGIN_URL)
        print(
            "[*] Log in to TradingView in the browser window.\n"
            "    Polling for session cookies every 2s (timeout {}s)...".format(timeout)
        )

        deadline = time.time() + timeout
        last_report = 0.0
        while time.time() < deadline:
            cookies = {c["name"]: c for c in context.cookies()}
            sid = cookies.get("sessionid")
            sid_sign = cookies.get("sessionid_sign")
            if sid and sid_sign and sid["value"] and sid_sign["value"]:
                print("[+] Session cookies detected.")
                browser.close()
                return sid["value"], sid_sign["value"]

            # Periodic heartbeat so the user knows polling is still active.
            if time.time() - last_report > 15:
                last_report = time.time()
                remaining = int(deadline - time.time())
                print(f"    ...waiting ({remaining}s left)")
            time.sleep(2)

        browser.close()
        raise TimeoutError(f"Did not detect both {REQUIRED} cookies within {timeout}s.")


def _merge_env(env_path: Path, sid: str, sid_sign: str) -> None:
    """Write TV cookies into env_path, preserving every other line."""
    existing_lines = env_path.read_text().splitlines() if env_path.exists() else []

    updates = {
        "TRADINGVIEW_SCANNER_ENABLED": "true",
        "TRADINGVIEW_SESSIONID": sid,
        "TRADINGVIEW_SESSIONID_SIGN": sid_sign,
    }

    # Rewrite existing keys in place; track which ones we've already replaced.
    new_lines: list[str] = []
    applied: set[str] = set()
    for line in existing_lines:
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            applied.add(key)
        else:
            new_lines.append(line)

    # Append any keys that weren't in the file.
    missing = [k for k in updates if k not in applied]
    if missing:
        if new_lines and new_lines[-1].strip() != "":
            new_lines.append("")
        new_lines.append(
            "# ── TradingView Scanner (refreshed by refresh_tv_cookies.py) ──"
        )
        for key in missing:
            new_lines.append(f"{key}={updates[key]}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    print(f"[+] Wrote {len(updates)} keys to {env_path}")


def _verify(sid: str, sid_sign: str) -> bool:
    """Hit scanner.tradingview.com once to confirm the cookies authenticate."""
    os.environ["TRADINGVIEW_SCANNER_ENABLED"] = "true"
    os.environ["TRADINGVIEW_SESSIONID"] = sid
    os.environ["TRADINGVIEW_SESSIONID_SIGN"] = sid_sign

    # Make sure we import from the repo's mcp_server, not any stale install.
    sys.path.insert(0, str(REPO_ROOT))

    # Force fresh import so _ENABLED re-reads env.
    for mod in list(sys.modules):
        if mod.startswith("mcp_server.tradingview_scanner"):
            del sys.modules[mod]

    try:
        from mcp_server import tradingview_scanner as tv
    except Exception as exc:
        print(f"[!] Could not import tradingview_scanner for verification: {exc}")
        return False

    if not tv.is_available():
        print(
            "[!] tradingview_scanner not available after env update — check lib install."
        )
        return False

    symbols = tv.run_scanner("rsi_above_30", limit=5)
    if not symbols:
        print("[!] Verification query returned 0 symbols — cookies may be invalid.")
        return False

    print(
        f"[+] Verified: authenticated query returned {len(symbols)} symbols → {symbols}"
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip())
    parser.add_argument(
        "--env",
        type=Path,
        default=DEFAULT_ENV,
        help=f"Path to .env file to update (default: {DEFAULT_ENV})",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Seconds to wait for login before giving up (default: 300)",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip the post-write verification query.",
    )
    args = parser.parse_args()

    try:
        sid, sid_sign = _launch_browser_and_wait(args.timeout)
    except TimeoutError as exc:
        print(f"[!] {exc}")
        return 1

    _merge_env(args.env, sid, sid_sign)

    if not args.skip_verify:
        if not _verify(sid, sid_sign):
            print("[!] Cookies were written but the verification call failed.")
            return 2

    print("[✓] Done. Restart any running scanner process to pick up new cookies.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
