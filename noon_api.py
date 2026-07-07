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

JS_CLICK_SCRIPT = """
new Promise((resolve) => {
    (async () => {
        try {
            console.log("⏳ Starting execution...");
            
            // Scan for 'Other Offers' button
            let btn = null;
            for (let i = 0; i < 20; i++) {
                btn = Array.from(document.querySelectorAll('*')).find(el => 
                    el.innerText && 
                    el.innerText.trim().toLowerCase().includes("more offers from other sellers") &&
                    el.children.length === 0
                );
                if (btn) break;
                await new Promise(r => setTimeout(r, 100));
            }

            if (!btn) {
                console.warn("⚠️ Button not detected. Product might be single-seller.");
                resolve(true); // Releases Python instantly
                return;
            }

            // Target parent and Execute Click
            const target = btn.parentElement || btn;
            console.log("🎯 Targeting element:", target);
            target.scrollIntoView({ behavior: 'smooth', block: 'center' });
            
            // YOUR EXACT FIX: Non-blocking setTimeout to prevent UI crashing
            setTimeout(() => {
                try {
                    target.click();
                    target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
                    target.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true }));
                    if (typeof target.onclick === 'function') target.onclick();
                } catch(e) {
                    console.error("Click execution error:", e);
                }
            }, 300);

            // Wait for Content
            console.log("⏳ Checking for loaded offers...");
            let offersCount = 0;
            for (let i = 0; i < 15; i++) {
                const items = Array.from(document.querySelectorAll('*')).filter(el => 
                    el.innerText && 
                    el.innerText.includes("EGP") && 
                    (el.innerText.includes("Sold by") || el.innerText.includes("Add To Cart"))
                );
                
                if (items.length > offersCount) {
                    offersCount = items.length;
                    console.log(`📡 Detected ${offersCount} offers so far...`);
                }
                
                if (offersCount > 2) {
                    console.log(`🎉 SUCCESS: ${offersCount} offers loaded.`);
                    // Buffer to let React paint, then instantly release Python
                    setTimeout(() => resolve(true), 800); 
                    return;
                }
                await new Promise(r => setTimeout(r, 500));
            }

            console.log("🏁 Loop finished without finding offers.");
            resolve(true); // Failsafe release

        } catch (error) {
            console.error("❌ Exception caught:", error);
            resolve(true); // Failsafe release
        }
    })();
});
"""
@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.get_json()
    
    if not data:
         return jsonify({"error": "No JSON payload received"}), 400
         
    urls = data.get("urls")
    schema = data.get("schema")

    if not isinstance(urls, list) or not isinstance(schema, dict):
        return jsonify({"error": "Invalid input. 'urls' must be a list, 'schema' must be a dict."}), 400

    extraction_strategy = JsonCssExtractionStrategy(schema, verbose=False)
    #buy_box_wait_selector = '[class^="AddToCartWithQuanityV2"][class$="_isVisible"], [class^="AddToCartWithQuanityV2"][class$="_disabledElement"]'
    # --- NEW, BULLETPROOF CSS SELECTORS ---
    # We now target data-qa attributes because they don't change when Noon updates their CSS
    buy_box_wait_selector = '[data-qa="pdp-add-to-cart-revamp"], [data-qa="div-price-now"]'

    config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        extraction_strategy=extraction_strategy,
        #js_code_before_wait=[JS_CLICK_SCRIPT],
        #wait_for='#noon-other-offers-loaded',
        wait_for=buy_box_wait_selector,
        js_code=[JS_CLICK_SCRIPT],
       
        excluded_tags=['nav', 'footer', 'header', 'script', 'style', 'noscript'],
        exclude_external_links=True,
        exclude_social_media_links=True,
        exclude_external_images=True,
        screenshot=False, 
        scan_full_page=False,
        magic=True,
        simulate_user=True,
        page_timeout=180000 
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

    # --- THE CLEAN EXECUTION FIX ---
    try:
        result = asyncio.run(run_scraper())
        return jsonify(result) 
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    from waitress import serve
    print("🚀 Starting Noon production server with Waitress (Max 4 threads)...")
    serve(app, host='0.0.0.0', port=5000, threads=4)
