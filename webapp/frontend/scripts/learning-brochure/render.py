"""Print the brochure HTML built by build.mts to PDF with headless Chromium."""
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
DEST = HERE.parents[1] / "public" / "learning-assets" / "brochures"

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    for name in ("quant", "quant-summary"):
        page.goto((HERE / "out" / f"{name}.html").as_uri())
        page.wait_for_load_state("networkidle")
        page.pdf(path=str(DEST / f"{name}.pdf"), format="A4", print_background=True, prefer_css_page_size=True)
        print("wrote", DEST / f"{name}.pdf")
    browser.close()
