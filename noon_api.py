import asyncio
from flask import Flask, request, jsonify
from crawl4ai import (
    AsyncWebCrawler,
    CrawlerRunConfig,
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
    text_mode=False, # Must be False to allow React to render fully
    light_mode=True,
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

async def native_click_hook(page, *args, **kwargs):
    print("⏳ [DIAGNOSTIC HOOK] Initializing...")
    try:
        await page.wait_for_timeout(2000)

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
        
        if is_null:
            print("⚠️ [DIAGNOSTIC] Button not found.")
            return

        print("🎯 [DIAGNOSTIC] Clicking...")
        element = element_handle.as_element()
        await element.scroll_into_view_if_needed()
        await page.wait_for_timeout(500)
        await element.click(force=True)
        
        print("⏳ [DIAGNOSTIC] Waiting for 3 seconds to ensure panel is open...")
        await page.wait_for_timeout(3000)
        
    except Exception as e:
        print(f"❌ [DIAGNOSTIC] Exception: {e}")

@app.route('/scrape', methods=['POST'])
def scrape():
    try:
        data = request.get_json()
        if not data: return jsonify({"error": "No JSON payload"}), 400
             
        urls = data.get("urls")

        if not isinstance(urls, list):
            return jsonify({"error": "Invalid input: urls must be a list"}), 400

        # Note: No schema strategy here. We just want raw HTML.
        config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
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
                crawler.crawler_strategy.set_hook("after_goto", native_click_hook)
                results = await crawler.arun_many(urls=urls, config=config, semaphore_count=3)
                
                output = []
                for result in results:
                    if result.success:
                        # Return the RAW HTML string
                        output.append({
                            "url": result.url, 
                            "status": result.status_code, 
                            "raw_html_length": len(result.html), # Check how big the HTML is
                            "raw_html": result.html[:2000] # Return the first 2000 chars to verify
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
        return jsonify({"error": f"Python Crash: {str(e)}"}), 500

if __name__ == '__main__':
    from waitress import serve
    print("🚀 Starting Diagnostic Server...")
    serve(app, host='0.0.0.0', port=5000, threads=4)
