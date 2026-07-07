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

# --- THE NATIVE PLAYWRIGHT CLICKER ---
# This simulates a real OS-level mouse click to bypass Datadome
async def native_click_hook(page, context, url, response, **kwargs):
    print(f"⏳ [HOOK] Triggered for {url}. Searching for button...")
    try:
        btn_selector = 'button:has-text("عروض أكثر من بائعين آخرين"), button:has-text("offers from"), button:has-text("other sellers"), [class*="slidingOptionsTrigger"]'
        
        try:
            # Wait up to 5 seconds for the Arabic/English button to render
            btn = await page.wait_for_selector(btn_selector, state="visible", timeout=5000)
        except Exception:
            btn = None
            
        if not btn:
            print("⚠️ [HOOK] Button not found. Product might be single-seller.")
            return

        print("🎯 [HOOK] Button found. Clicking natively...")
        await btn.scroll_into_view_if_needed()
        await page.wait_for_timeout(500)
        
        # Native OS-level click (isTrusted: true)
        await btn.click()
        
        print("⏳ [HOOK] Waiting for offer cards to load data...")
        await page.wait_for_selector('a[class*="_card_"][href*="?o="]', state="visible", timeout=15000)
        
        # Give React 1.5 seconds to paint the EGP prices inside the cards
        await page.wait_for_timeout(1500)
        print("🎉 [HOOK] Cards loaded successfully!")
        
    except Exception as e:
        print(f"⚠️ [HOOK] Error during execution: {e}")


@app.route('/scrape', methods=['POST'])
def scrape():
    # 🔒 SECURE WRAPPER: Ensures Flask never throws an HTML 500 error again
    try:
        data = request.get_json()
        if not data: return jsonify({"error": "No JSON payload"}), 400
             
        urls = data.get("urls")
        schema = data.get("schema")

        if not isinstance(urls, list) or not isinstance(schema, dict):
            return jsonify({"error": "Invalid input"}), 400

        extraction_strategy = JsonCssExtractionStrategy(schema, verbose=False)

        # Removed the invalid page_hooks argument from here!
        config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            extraction_strategy=extraction_strategy,
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
                
                # ✅ PROPER CRAWL4AI 0.9.0 HOOK ATTACHMENT
                crawler.crawler_strategy.set_hook("after_goto", native_click_hook)
                
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

        result = asyncio.run(run_scraper())
        return jsonify(result) 
        
    except Exception as e:
        # If any Python code breaks, n8n gets a clean JSON error response
        return jsonify({"error": f"Python Server Crash: {str(e)}"}), 500

if __name__ == '__main__':
    from waitress import serve
    print("🚀 Starting Noon production server with Waitress (Native Click Bridge)...")
    serve(app, host='0.0.0.0', port=5000, threads=4)
