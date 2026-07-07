import json
import asyncio
from flask import Flask, request, jsonify
from crawl4ai import (
    AsyncWebCrawler,
    CrawlerRunConfig,
    JsonCssExtractionStrategy,
    BrowserConfig,
    CacheMode
)

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

browser_config = BrowserConfig(
    viewport_width=1920,
    viewport_height=1080,
    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    user_agent_mode="random",
    text_mode=True, 
    light_mode=True,
    user_data_dir="/app/chrome_cache",
    use_persistent_context=False,
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

# --- THE NATIVE PLAYWRIGHT CLICKER (Replaces the JS Script) ---
async def native_click_hook(page, context, **kwargs):
    print("⏳ [PYTHON HOOK] Searching for More Offers button...")
    try:
        # 1. Target the button (Supports English, Arabic, and fallbacks)
        btn_selector = 'button:has-text("عروض أكثر من بائعين آخرين"), button:has-text("offers from"), button:has-text("other sellers"), [class*="slidingOptionsTrigger"]'
        
        # 2. Wait up to 5 seconds for the button to exist
        btn = page.locator(btn_selector).first
        await btn.wait_for(state="visible", timeout=5000)
        
        # 3. NATIVE HARDWARE CLICK (Bypasses Datadome!)
        print("🎯 [PYTHON HOOK] Button found. Clicking natively...")
        await btn.click()
        
        # 4. Wait for YOUR exact schema baseSelector to load in the side panel
        print("⏳ [PYTHON HOOK] Waiting for cards to load data...")
        await page.wait_for_selector('a[class*="_card_"][href*="?o="]', state="visible", timeout=15000)
        
        # Give React 1.5 seconds to paint the actual text inside the cards
        await page.wait_for_timeout(1500)
        print("🎉 [PYTHON HOOK] Cards loaded successfully!")
        
    except Exception as e:
        print("⚠️ [PYTHON HOOK] Button not found or single seller product. Skipping click.")


@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.get_json()
    if not data: return jsonify({"error": "No JSON payload"}), 400
         
    urls = data.get("urls")
    schema = data.get("schema")

    if not isinstance(urls, list) or not isinstance(schema, dict):
        return jsonify({"error": "Invalid input"}), 400

    extraction_strategy = JsonCssExtractionStrategy(schema, verbose=False)

    config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        extraction_strategy=extraction_strategy,
        # We hook into Crawl4AI right after the page loads to do our native click!
        page_hooks={"after_goto": [native_click_hook]}, 
        excluded_tags=['nav', 'footer', 'header', 'script', 'style', 'noscript'],
        exclude_external_links=True,
        exclude_social_media_links=True,
        exclude_external_images=True,
        screenshot=False, 
        scan_full_page=False,
        magic=True,
        simulate_user=True,
        page_timeout=60000 
    )

    async def run_scraper():
        async with AsyncWebCrawler(config=browser_config, verbose=False) as crawler:
            results = await crawler.arun_many(urls=urls, config=config, semaphore_count=3)
            
            output = []
            for result in results:
                if result.success:
                    try:
                        extracted = json.loads(result.extracted_content)
                    except Exception:
                        extracted = {"error": "Failed to parse extracted content"}
                    
                    output.append({
                        "url": result.url, 
                        "status": result.status_code, 
                        "data": extracted
                    })
                else:
                    output.append({
                        "url": result.url, 
                        "status": result.status_code, 
                        "error": result.error_message
                    })
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
