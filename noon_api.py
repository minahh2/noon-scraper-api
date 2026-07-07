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
    (function aggressiveClick() {
    console.log("🔍 Looking for 'More offers from other sellers'...");

    // 1. Find the element containing the text
    const allElements = document.querySelectorAll('*');
    let target = null;
    for (let el of allElements) {
        if (el.innerText && el.innerText.trim().toLowerCase() === "more offers from other sellers") {
            // Ensure it's not a deep container, but a leaf node or close to it
            if (el.children.length === 0) {
                target = el;
                break;
            }
        }
    }

    if (!target) {
        console.error("❌ Still can't find the exact text node. Are you sure you are on the product page?");
        return;
    }

    // 2. Grab the immediate parent (where the event listener is)
    const parent = target.parentElement;
    console.log("🎯 Targeting parent element:", parent);

    // 3. Setup Network Monitor
    const originalFetch = window.fetch;
    window.fetch = async function(...args) {
        const response = await originalFetch.apply(this, args);
        if (args[0].toString().includes("offers")) {
            console.log(`📡 API Status: ${response.status}`);
        }
        return response;
    };

    // 4. Fire events on the parent
    console.log("⚡ Forcing click on parent...");
    
    // We try multiple ways to trigger the JS
    parent.scrollIntoView({ behavior: 'smooth', block: 'center' });
    
    setTimeout(() => {
        // Method A: Standard Click
        parent.click();
        
        // Method B: Dispatch MouseEvent
        const mousedown = new MouseEvent('mousedown', { bubbles: true, cancelable: true });
        const mouseup = new MouseEvent('mouseup', { bubbles: true, cancelable: true });
        parent.dispatchEvent(mousedown);
        parent.dispatchEvent(mouseup);
        
        // Method C: If the parent has an 'onclick' property, call it directly
        if (typeof parent.onclick === 'function') {
            parent.onclick();
            console.log("✅ Executed internal 'onclick' function.");
        }
    }, 500);
})();
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
