import json
import asyncio
from flask import Flask, request, jsonify
from crawl4ai import (
    AsyncWebCrawler,
    CrawlerRunConfig,
    BrowserConfig,
    CacheMode
)
from bs4 import BeautifulSoup

app = Flask(__name__)

# Configuration for blocking trackers
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

# Browser settings
browser_config = BrowserConfig(
    viewport_width=1920,
    viewport_height=1080,
    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    user_agent_mode="random",
    text_mode=True, 
    light_mode=True,
    user_data_dir="/app/chrome_cache",
    use_persistent_context=False,
    headless=True,
    extra_args=[
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

# --- NATIVE CLICK HOOK ---
async def native_click_hook(page, *args, **kwargs):
    print("⏳ [HOOK] Initializing hybrid click strategy...")
    try:
        # Wait for page to be ready
        await page.wait_for_timeout(2000)

        # JS finds the button and returns a pointer
        pointer_script = """() => {
            const keywords = ["offers from", "other sellers", "عروض أكثر", "عروض أخرى"];
            const elements = document.querySelectorAll('button, div, span, p');
            for (let el of elements) {
                let text = (el.innerText || el.textContent || "").trim().toLowerCase();
                if (text.length >= 5 && text.length < 60 && keywords.some(kw => text.includes(kw))) {
                    return el.closest('button') || el.closest('[class*="Trigger"]') || el;
                }
            }
            return document.querySelector('[class*="slidingOptionsTrigger"]');
        }"""
        
        element_handle = await page.evaluate_handle(pointer_script)
        is_null = await element_handle.evaluate("node => node === null")
        
        if not is_null:
            print("🎯 [HOOK] Button found. Clicking...")
            element = element_handle.as_element()
            await element.scroll_into_view_if_needed()
            await page.wait_for_timeout(500)
            await element.click(force=True)
            await page.wait_for_timeout(2500) # Ensure panel fully loads
        
    except Exception as e:
        print(f"❌ [HOOK] Exception: {e}")

@app.route('/scrape', methods=['POST'])
def scrape():
    try:
        data = request.get_json()
        if not data: return jsonify({"error": "No JSON payload"}), 400
        
        urls = data.get("urls")
        if not isinstance(urls, list): return jsonify({"error": "Invalid input"}), 400

        async def run_scraper():
            async with AsyncWebCrawler(config=browser_config, verbose=False) as crawler:
                # Attach hook correctly
                crawler.crawler_strategy.set_hook("after_goto", native_click_hook)
                
                config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, magic=True)
                results = await crawler.arun_many(urls=urls, config=config, semaphore_count=2)
                
                output = []
                for result in results:
                    if result.success:
                        # Manual BeautifulSoup Parsing
                        soup = BeautifulSoup(result.html, 'html.parser')
                        
                        # Extract main product info
                        product_name = soup.select_one("h1, [class*='ProductTitle']")
                        price = soup.select_one("[data-qa='div-price-now']")
                        
                        # Extract "Other Offers"
                        cards = soup.select("a[class*='_card_'][href*='?o=']")
                        parsed_offers = []
                        for card in cards:
                            seller = card.select_one("[class*='_sellerName_']")
                            card_price = card.select_one("[class*='_sellingPrice_'] strong")
                            parsed_offers.append({
                                "seller": seller.text.strip() if seller else "Unknown",
                                "price": card_price.text.strip() if card_price else "0"
                            })
                        
                        output.append({
                            "url": result.url,
                            "product_name": product_name.text.strip() if product_name else "N/A",
                            "price": price.text.strip() if price else "N/A",
                            "other_offers": parsed_offers
                        })
                    else:
                        output.append({"url": result.url, "error": result.error_message})
                return output

        return jsonify(asyncio.run(run_scraper()))
    except Exception as e:
        return jsonify({"error": f"Python Crash: {str(e)}"}), 500

if __name__ == '__main__':
    from waitress import serve
    print("🚀 Starting full Noon production server...")
    serve(app, host='0.0.0.0', port=5000, threads=4)
