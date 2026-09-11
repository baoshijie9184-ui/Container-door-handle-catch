from playwright.sync_api import sync_playwright
p = sync_playwright().start()
b = p.chromium.launch(headless=True)
print('Chromium OK')
b.close()
p.stop()
