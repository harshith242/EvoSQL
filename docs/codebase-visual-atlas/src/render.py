"""Render every scene in this folder (scene_*.js) to a 1920x1080 PNG in ../images with headless Chromium.
Usage (from the repo root, with Playwright installed): python3 docs/codebase-visual-atlas/src/render.py [names]"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
PAGE = """<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Caveat:wght@500;600;700&display=block" rel="stylesheet">
<script src="https://unpkg.com/roughjs@4.6.6/bundled/rough.js"></script>
<style>html,body{{margin:0;background:#fff}}svg{{display:block}}</style></head><body>
<svg id="scene" xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080"
     style="background:#fff"><rect width="1920" height="1080" fill="#fff"/></svg>
<script>{kit}</script><script>{scene}</script></body></html>"""

names = sys.argv[1:] or sorted(p.stem.removeprefix("scene_") for p in HERE.glob("scene_*.js"))
out = HERE.parent / "images"
out.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch()
    for name in names:
        page = browser.new_page(viewport={"width": 1920, "height": 1080})  # fresh globals per scene
        html = PAGE.format(kit=(HERE / "kit.js").read_text(), scene=(HERE / f"scene_{name}.js").read_text())
        page.set_content(html, wait_until="networkidle")
        page.wait_for_function("window.sceneDone === true", timeout=20000)
        page.locator("#scene").screenshot(path=str(out / f"{name}.png"))
        page.close()
        print(f"rendered images/{name}.png")
    browser.close()
