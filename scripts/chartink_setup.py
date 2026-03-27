"""
Chartink Scanner Setup — API exploration + creation
Creates 3 scanners on chartink.com.

Usage:
  pip install playwright
  playwright install chromium
  python scripts/chartink_setup.py
"""

import asyncio
import json
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SCANNERS_TO_CREATE = [
    {
        "name": "MK - MACD Buy Call Daily",
        "scan_clause": (
            "( {cash} ( latest macd line( 26 , 12 , 9 ) > latest macd signal( 26 , 12 , 9 ) "
            "and 1 day ago macd line( 26 , 12 , 9 ) < 1 day ago macd signal( 26 , 12 , 9 ) ) )"
        ),
        "slug_key": "macd_buy_daily",
    },
    {
        "name": "MK - 52 Week High Breakout",
        "scan_clause": "( {cash} ( latest close = latest max( 260 , latest close ) ) )",
        "slug_key": "52week_high",
    },
    {
        "name": "MK - Nifty 5-10 EMA Crossover Hourly",
        "scan_clause": (
            "( {57960} ( hourly ema( hourly close , 5 ) > hourly ema( hourly close , 10 ) "
            "and 1 hour ago ema( 1 hour ago close , 5 ) < 1 hour ago ema( 1 hour ago close , 10 ) ) )"
        ),
        "slug_key": "ema_crossover_nifty",
    },
]


async def run():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=200)
        page = await browser.new_page(viewport={"width": 1400, "height": 900})

        # ── Login ───────────────────────────────────────────
        logger.info("Opening Chartink — login manually in the Chromium window")
        await page.goto("https://chartink.com/login", wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(2000)

        if "login" in page.url:
            logger.info("Waiting up to 120s for manual login...")
            for _ in range(24):
                await page.wait_for_timeout(5000)
                if "login" not in page.url:
                    break
            if "login" in page.url:
                logger.error("Login timeout.")
                await browser.close()
                sys.exit(1)

        logger.info("Logged in!")

        # Go to screener to get CSRF token
        await page.goto("https://chartink.com/screener", wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)

        csrf = await page.evaluate(
            "() => document.querySelector('meta[name=\"csrf-token\"]')?.content"
        )

        # ── Try multiple save API patterns ──────────────────
        created_slugs = {}
        for scanner in SCANNERS_TO_CREATE:
            logger.info("Creating: %s", scanner["name"])

            # Try POST to /screener (Inertia-style create)
            result = await page.evaluate("""
                async ([name, clause, token]) => {
                    const results = {};

                    // Attempt 1: POST /screener with Inertia headers
                    try {
                        const r1 = await fetch('/screener', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                'X-CSRF-TOKEN': token,
                                'X-Requested-With': 'XMLHttpRequest',
                                'X-Inertia': 'true',
                                'Accept': 'text/html, application/xhtml+xml',
                            },
                            body: JSON.stringify({
                                name: name,
                                scan_clause: clause,
                                atlas_query: clause,
                                atlas_json: '{}',
                                with_fundamental: false,
                            }),
                        });
                        const t1 = await r1.text();
                        results.inertia = { status: r1.status, body: t1.substring(0, 500) };
                    } catch(e) { results.inertia = { error: e.message }; }

                    // Attempt 2: POST /screener/store
                    try {
                        const fd = new FormData();
                        fd.append('name', name);
                        fd.append('atlas_query', clause);
                        fd.append('atlas_json', '{}');
                        const r2 = await fetch('/screener/store', {
                            method: 'POST',
                            headers: { 'X-CSRF-TOKEN': token, 'X-Requested-With': 'XMLHttpRequest' },
                            body: fd,
                        });
                        const t2 = await r2.text();
                        results.store = { status: r2.status, body: t2.substring(0, 500) };
                    } catch(e) { results.store = { error: e.message }; }

                    // Attempt 3: POST /scan/create
                    try {
                        const fd = new FormData();
                        fd.append('name', name);
                        fd.append('scan_clause', clause);
                        const r3 = await fetch('/scan/create', {
                            method: 'POST',
                            headers: { 'X-CSRF-TOKEN': token, 'X-Requested-With': 'XMLHttpRequest' },
                            body: fd,
                        });
                        const t3 = await r3.text();
                        results.scan_create = { status: r3.status, body: t3.substring(0, 500) };
                    } catch(e) { results.scan_create = { error: e.message }; }

                    // Attempt 4: PUT /screener/save with name
                    try {
                        const fd = new FormData();
                        fd.append('name', name);
                        fd.append('atlas_query', clause);
                        fd.append('atlas_json', '{}');
                        const r4 = await fetch('/screener/save', {
                            method: 'PUT',
                            headers: { 'X-CSRF-TOKEN': token, 'X-Requested-With': 'XMLHttpRequest' },
                            body: fd,
                        });
                        const t4 = await r4.text();
                        results.put_save = { status: r4.status, body: t4.substring(0, 500) };
                    } catch(e) { results.put_save = { error: e.message }; }

                    return results;
                }
            """, [scanner["name"], scanner["scan_clause"], csrf])

            for key, val in result.items():
                status = val.get("status", "err")
                body = val.get("body", val.get("error", ""))[:200]
                logger.info("  %s: status=%s body=%s", key, status, body)

            # Check if any succeeded
            for key in ["inertia", "store", "scan_create"]:
                val = result.get(key, {})
                if val.get("status") == 200 or val.get("status") == 201:
                    try:
                        data = json.loads(val.get("body", "{}"))
                        slug = data.get("slug") or data.get("props", {}).get("slug")
                        if slug:
                            created_slugs[scanner["slug_key"]] = slug
                            break
                    except json.JSONDecodeError:
                        pass

        # ── Check dashboard for any new scanners ────────────
        logger.info("\nChecking dashboard...")
        await page.goto("https://chartink.com/scan_dashboard", wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(3000)

        all_scanners = await page.evaluate("""
            () => {
                const links = document.querySelectorAll('table a[href*="/screener/"]');
                return Array.from(links).map(a => ({
                    name: a.textContent.trim(),
                    slug: a.getAttribute('href').split('/screener/').pop(),
                }));
            }
        """)

        logger.info("Dashboard scanners (page 1):")
        for s in all_scanners:
            marker = ">>>" if "MK" in s["name"] else "   "
            logger.info("  %s %s -> %s", marker, s["name"], s["slug"])

        # ── Summary ─────────────────────────────────────────
        logger.info("\n" + "=" * 50)
        logger.info("RESULTS")
        logger.info("=" * 50)
        if created_slugs:
            for key, slug in created_slugs.items():
                logger.info("  %s -> %s", key, slug)
        else:
            logger.info("  No scanners created via API.")
            logger.info("  The Chartink save API may require premium access.")
            logger.info("  You can create them manually using these scan clauses:")
            for sc in SCANNERS_TO_CREATE:
                logger.info("")
                logger.info("  Name: %s", sc["name"])
                logger.info("  Clause: %s", sc["scan_clause"])

        await page.wait_for_timeout(15000)
        await browser.close()
        return created_slugs


if __name__ == "__main__":
    asyncio.run(run())
