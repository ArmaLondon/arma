"""Step 1 gate: open Chromium, inject vendored axe-core, print violation count."""
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

AXE = Path(__file__).resolve().parent.parent / "vendor" / "axe.min.js"
HTML = "<html><body><img src='x.png'><div onclick='1'>Buy</div></body></html>"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content(HTML)
        await page.add_script_tag(content=AXE.read_text())
        res = await page.evaluate("axe.run()")
        print("violations:", [v["id"] for v in res["violations"]])
        await browser.close()


asyncio.run(main())
