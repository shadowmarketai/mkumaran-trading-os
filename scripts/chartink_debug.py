"""Debug: inspect the Chartink Save Scan dialog."""
import asyncio, json, logging
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=200)
        page = await browser.new_page(viewport={"width": 1400, "height": 900})

        await page.goto("https://chartink.com/login", wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(2000)

        if "login" in page.url:
            logger.info("Login manually...")
            for _ in range(24):
                await page.wait_for_timeout(5000)
                if "login" not in page.url:
                    break

        await page.goto("https://chartink.com/screener", wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)

        # Click Save Scan
        save_btn = page.locator('text="Save Scan"').first
        await save_btn.click()
        await page.wait_for_timeout(2000)

        # Get FULL modal HTML
        modal_info = await page.evaluate("""
            () => {
                const modal = document.querySelector('.modal.show, [role="dialog"], .modal-dialog, [class*="modal"]');
                if (!modal) return { found: false };

                // Find all inputs in the modal
                const inputs = modal.querySelectorAll('input, textarea, select');
                const inputInfo = [];
                inputs.forEach(inp => {
                    inputInfo.push({
                        tag: inp.tagName,
                        type: inp.type,
                        name: inp.name,
                        placeholder: inp.placeholder,
                        class: inp.className.substring(0, 100),
                        id: inp.id,
                        value: inp.value,
                    });
                });

                // Find all buttons
                const buttons = modal.querySelectorAll('button');
                const btnInfo = [];
                buttons.forEach(btn => {
                    btnInfo.push({ text: btn.textContent.trim().substring(0, 50), class: btn.className.substring(0, 50) });
                });

                return {
                    found: true,
                    className: modal.className,
                    inputs: inputInfo,
                    buttons: btnInfo,
                    html: modal.innerHTML.substring(0, 2000),
                };
            }
        """)

        print(json.dumps(modal_info, indent=2))

        # Also try getting ALL visible inputs on the page
        all_inputs = await page.evaluate("""
            () => {
                const inputs = document.querySelectorAll('input:not([type="hidden"]), textarea');
                return Array.from(inputs).filter(el => el.offsetHeight > 0).map(el => ({
                    tag: el.tagName,
                    type: el.type,
                    name: el.name,
                    placeholder: el.placeholder,
                    id: el.id,
                    class: el.className.substring(0, 80),
                    rect: el.getBoundingClientRect(),
                }));
            }
        """)
        print("\nAll visible inputs:")
        for inp in all_inputs:
            print(f"  {inp['tag']} type={inp['type']} name={inp['name']} placeholder={inp['placeholder']} id={inp['id']}")

        await page.wait_for_timeout(30000)
        await browser.close()

asyncio.run(run())
