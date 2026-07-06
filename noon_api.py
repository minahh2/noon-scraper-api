import json
import asyncio
import logging
from flask import Flask, request, jsonify
from crawl4ai import JsonCssExtractionStrategy
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async

# Configure logging to catch the crash details
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# [Keep your tracker_blackhole here]
tracker_blackhole = "MAP *.google-analytics.com 127.0.0.1, MAP *.googletagmanager.com 127.0.0.1, MAP *.doubleclick.net 127.0.0.1, MAP *.facebook.net 127.0.0.1, MAP *.facebook.com 127.0.0.1, MAP *.criteo.com 127.0.0.1, MAP *.criteo.net 127.0.0.1, MAP *.tiktok.com 127.0.0.1, MAP *.snapchat.com 127.0.0.1, MAP *.hotjar.com 127.0.0.1, MAP *.clarity.ms 127.0.0.1"

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.get_json()
    if not data: return jsonify({"error": "No JSON"}), 400
    
    urls = data.get("urls")
    schema = data.get("schema")

    extraction_strategy = JsonCssExtractionStrategy(schema, verbose=False)

    async def run_scraper():
        output = []
        async with async_playwright() as p:
            logger.info("Launching Browser...")
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled", f"--host-rules={tracker_blackhole}"]
            )
            
            context = await browser.new_context(viewport={'width': 1920, 'height': 1080})

            for url in urls:
                page = await context.new_page()
                await stealth_async(page)
                try:
                    logger.info(f"Navigating to {url}")
                    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    
                    # Logic: Wait for elements
                    await page.wait_for_selector('[data-qa="pdp-add-to-cart-revamp"], [data-qa="div-price-now"]', timeout=30000)
                    
                    # Click Logic
                    btn_selector = 'button:has-text("offers from"), button:has-text("other sellers"), button[class*="slidingOptionsTrigger"]'
                    btn = await page.query_selector(btn_selector)
                    if btn:
                        await btn.click()
                        await page.wait_for_timeout(2000) # Give React time to load cards

                    html = await page.content()
                    extracted = extraction_strategy.extract(url, html)
                    output.append({"url": url, "status": 200, "data": json.loads(extracted) if isinstance(extracted, str) else extracted})
                    
                except Exception as e:
                    logger.error(f"Error scraping {url}: {str(e)}")
                    output.append({"url": url, "status": 500, "error": str(e)})
                finally:
                    await page.close()
            await browser.close()
        return output

    try:
        result = asyncio.run(run_scraper())
        return jsonify(result) 
    except Exception as e:
        logger.critical(f"CRITICAL SYSTEM ERROR: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    from waitress import serve
    logger.info("🚀 Starting Server...")
    # Increased connection timeout
    serve(app, host='0.0.0.0', port=5000, threads=4, channel_timeout=120)
