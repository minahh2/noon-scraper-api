import json
import asyncio
from flask import Flask, request, jsonify
from crawl4ai import JsonCssExtractionStrategy
from playwright.async_api import async_playwright

app = Flask(__name__)

tracker_blackhole = (
    "MAP *.google-analytics.com 127.0.0.1, "
    "MAP *.googletagmanager.com 127.0.0.1, "
    "MAP *.doubleclick.net 127.0.0.1, "  
    "MAP *.facebook.net 127.0.0.1, "
    "MAP *.facebook.com 127.0.0.1, "
    "MAP *.criteo.com 127.0.0.1, "
    "MAP *.criteo.net 127.0.0.1, "
    "MAP *.tiktok.com 127.0.0.1, "
    "MAP *.snapchat.com 127.0.0.1, "
    "MAP *.hotjar.com 127.0.0.1, "
    "MAP *.clarity.ms 127.0.0.1"
)

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.get_json()
    
    if not data:
         return jsonify({"error": "No JSON payload received"}), 400
         
    urls = data.get("urls")
    schema = data.get("schema")

    if not isinstance(urls, list) or not isinstance(schema, dict):
        return jsonify({"error": "Invalid input. 'urls' must be a list, 'schema' must be a dict."}), 400

    # Keep Crawl4AI's brilliant JSON extractor
    extraction_strategy = JsonCssExtractionStrategy(schema, verbose=False)

    async def run_python_scraper():
        output = []
        
        # 1. Boot raw Playwright instead of AsyncWebCrawler
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox", 
                    "--disable-gpu", 
                    "--disable-extensions",
                    "--disable-dev-shm-usage", 
                    "--js-flags=--max-old-space-size=512",
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--disable-blink-features=AutomationControlled", 
                    f"--host-rules={tracker_blackhole}"
                ]
            )
            
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            )

            for url in urls:
                page = await context.new_page()
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    
                    # 2. Wait for your exact requested element
                    await page.wait_for_selector('[data-qa="pdp-add-to-cart-revamp"], [data-qa="div-price-now"]', timeout=20000)

                    # 3. Target the button
                    btn_selector = 'button:has-text("offers from"), button:has-text("other sellers"), button[class*="slidingOptionsTrigger"]'
                    
                    try:
                        btn = await page.wait_for_selector(btn_selector, timeout=4000)
                        if btn:
                            await btn.scroll_into_view_if_needed()
                            await page.wait_for_timeout(500)
                            
                            # 4. PYTHON HARDWARE CLICK (The Datadome Killer)
                            # This simulates a physical mouse click via the Chrome DevTools Protocol
                            await btn.click()
                            
                            # 5. Wait for the real text to replace the skeletons
                            await page.wait_for_function('''() => {
                                let cards = document.querySelectorAll('a[class*="_card_"][href*="?o="], [class*="OtherOfferListItem"]');
                                let realCards = Array.from(cards).filter(c => c.innerText.trim().length > 5);
                                return realCards.length > 0;
                            }''', timeout=10000)
                            
                            await page.wait_for_timeout(500) 
                    except Exception:
                        pass # Single-seller product, just move on
                    
                    # 6. Grab the HTML and feed it to Crawl4AI
                    html = await page.content()
                    extracted = extraction_strategy.extract(url, html)
                    
                    try:
                        parsed_data = json.loads(extracted) if isinstance(extracted, str) else extracted
                    except Exception:
                        parsed_data = extracted
                        
                    output.append({
                        "url": url, 
                        "status": 200, 
                        "data": parsed_data
                    })
                    
                except Exception as e:
                    output.append({"url": url, "status": 500, "error": str(e)})
                finally:
                    await page.close()
            
            await browser.close()
        return output

    try:
        result = asyncio.run(run_python_scraper())
        return jsonify(result) 
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    from waitress import serve
    print("🚀 Starting Python-Native Noon Scraper with Waitress...")
    serve(app, host='0.0.0.0', port=5000, threads=4)
