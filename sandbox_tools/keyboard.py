"""usage: python keyboard.py <url> — Tab order, accessible names, visible focus, clickable elements unreachable by keyboard."""
import sys

from common import keyboard, launch, main, open_page, path_of
from playwright.sync_api import sync_playwright


def run():
    if len(sys.argv) < 2:
        raise ValueError("pass the page URL, e.g. python keyboard.py http://127.0.0.1:8765/product.html")
    with sync_playwright() as p:
        b = launch(p)
        k = keyboard(open_page(b, sys.argv[1]))
        b.close()
    return {"page": path_of(sys.argv[1]), **k}


main(run)
