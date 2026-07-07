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

# --- THE HYBRID CLICKER HOOK ---
# JS finds the button. Playwright forces the hardware click.
async def native_click_hook(page, *args, **kwargs):
    print("⏳ [HOOK] Initializing hybrid click strategy...")
    try:
        # 1. Give the page a moment to fully render the React DOM
        await page.wait_for_timeout(2000)

        # 2. JS traverses the DOM to find the exact button and tags it with an ID
        tag_script = """() => {
            const keywords = ["offers from", "other sellers", "عروض أكثر من بائعين آخرين", "عروض أخرى"];
            const elements = document.querySelectorAll('button, div, span, p');
            
            for (let el of elements) {
                let text = (el.innerText || el.textContent || "").trim().toLowerCase();
                if (text.length > 5 && text.length < 60 && keywords.some(kw => text.includes(kw))) {
                    let btn = el.closest('button') || el.closest('[class*="Trigger"]') || el;
                    btn.setAttribute('id', 'NOON_TARGET_BUTTON');
                    return true;
                }
            }
            
            let fallback = document.querySelector('[class*="slidingOptionsTrigger"]');
            if (fallback) {
                fallback.setAttribute('id', 'NOON_TARGET_BUTTON');
                return true;
            }
            return false;
        }"""
        
        found = await page.evaluate(tag_script)
        
        if not found:
            print("⚠️ [HOOK] Button not found by Javascript. Skipping click.")
            return

        print("🎯 [HOOK] Button targeted. Executing forced hardware click...")
        target = page.locator('#NOON_TARGET_BUTTON').first
        
        # force=True BYPASSES all invisible cookie banners and location popups!
        await target.click(force=True)
        
        print("⏳ [HOOK] Waiting for offer cards to hydrate...")
        # Wait for the exact cards your schema is looking for to appear
        await page.wait_for_selector('a[class*="_card_"][href*="?o="]', state="attached", timeout=15000)
        
        # Give React 2 full seconds to paint the EGP prices inside the cards
        await page.wait_for_timeout(2000)
        print("🎉 [HOOK] Cards successfully loaded and hydrated!")
        
    except Exception as e:
        print(f"❌ [HOOK] Exception encountered: {e}")


@app.route('/scrape', methods=['POST'])
def scrape():
    try:
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
                
                # Attach our Hybrid Hook
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
        return jsonify({"error": f"Python Server Crash: {str(e)}"}), 500

if __name__ == '__main__':
    from waitress import serve
    print("🚀 Starting Noon production server with Waitress (Hybrid Click Bridge)...")
    serve(app, host='0.0.0.0', port=5000, threads=4)
