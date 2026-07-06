import json
import asyncio
from flask import Flask, request, jsonify
from crawl4ai import JsonCssExtractionStrategy
from playwright.async_api import async_playwright

app = Flask(__name__)

# YOUR EXACT TRACKER BLACKHOLE
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

    # Retain your exact extraction schema
    extraction_strategy = JsonCssExtractionStrategy(schema, verbose=False)

    async def run_scraper():
        output = []
        
        async with async_playwright() as p:
            # YOUR EXACT BROWSER CONFIG ARGS
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox", 
                    "--disable-gpu", 
                    "--disable-extensions",
                    "--disable-dev-shm-usage", 
                    "--js-flags=--max-old-space-size=512",
                    "--blink-settings=imagesEnabled=false", 
                    "--disable-features=IsolateOrigins,site-per-process",
                    f"--host-rules={tracker_blackhole}"
                ]
            )
            
            # YOUR EXACT VIEWPORT AND USER AGENT
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )

            for url in urls:
                page = await context.new_page()
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    
                    # YOUR EXACT WAIT_FOR SELECTOR
                    await page.wait_for_selector('[data-qa="pdp-add-to-cart-revamp"], [data-qa="div-price-now"]', timeout=20000)

                    # NATIVE PYTHON CLICK (Bypasses the console's isTrusted block)
                    btn_selector = 'button:has-text("offers from"), button:has-text("other sellers"), button[class*="slidingOptionsTrigger"]'
                    
                    try:
                        btn = await page.wait_for_selector(btn_selector, timeout=4000)
                        if btn:
                            await btn.scroll_into_view_if_needed()
                            await page.wait_for_timeout(500)
                            
                            # The true hardware click Datadome requires
                            await btn.click()
                            
                            # Max 5 seconds fail-fast loop to wait for real text to replace skeletons
                            attempts = 0
                            while attempts < 10:
                                has_real_cards = await page.evaluate('''() => {
                                    let cards = document.querySelectorAll('a[class*="_card_"][href*="?o="], [class*="OtherOfferListItem"]');
                                    let realCards = Array.from(cards).filter(c => c.innerText.trim().length > 5);
                                    return realCards.length > 0;
                                }''')
                                if has_real_cards:
                                    await page.wait_for_timeout(800) # Give React time to paint
                                    break
                                await page.wait_for_timeout(500)
                                attempts += 1
                                
                    except Exception as e:
                        print(f"No secondary offers button found or click failed: {e}")
                    
                    # Extract final HTML and pass to Crawl4AI mapping
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
        result = asyncio.run(run_scraper())
        return jsonify(result) 
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    from waitress import serve
    print("🚀 Starting Noon production server with Waitress (Max 4 threads)...")
    serve(app, host='0.0.0.0', port=5000, threads=4)
