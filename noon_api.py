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

# --- THE TROJAN HORSE WAIT CONDITION ---
    # This script runs inside Playwright's evaluator. It forces Python to wait until the JS says it's done.
JS_WAIT_CONDITION = """js:() => {
        // 1. Check if the main page is loaded by looking for the price
        const priceLoaded = document.querySelector('[data-qa="div-price-now"], [class*="priceNowText"]');
        if (!priceLoaded) return false; // Keep waiting for the main page to load

        // 2. If we already started the click process, wait until it finishes
        if (window._noonScrapingOffers) {
            return window._noonOffersDone === true;
        }
        window._noonScrapingOffers = true;
        window._noonOffersDone = false;

        // 3. Background process to click and wait for sidebar
        (async () => {
            const delay = ms => new Promise(res => setTimeout(res, ms));
            let triggerBtn = null;
            
            // Try to find the trigger button by its class
            const elements = document.querySelectorAll('[class*="slidingOptionsTrigger"]');
            for (let el of elements) {
                if (el.offsetWidth > 0 && el.offsetHeight > 0) {
                    triggerBtn = el;
                    break;
                }
            }
            
            // Fallback: Find the button aggressively by its text content
            if (!triggerBtn) {
                const allEl = Array.from(document.querySelectorAll('*'));
                for (let i = allEl.length - 1; i >= 0; i--) {
                    const txt = (allEl[i].textContent || "").toLowerCase();
                    if (txt.includes("offers from") || txt.includes("offers available") || txt.includes("other sellers")) {
                        if (allEl[i].children.length === 0) {
                            let p = allEl[i].parentElement;
                            while (p && p !== document.body) {
                                if (p.tagName === 'BUTTON' || p.getAttribute('role') === 'button' || p.className.includes('Trigger')) {
                                    triggerBtn = p; 
                                    break;
                                }
                                p = p.parentElement;
                            }
                            if (triggerBtn) break;
                        }
                    }
                }
            }

            if (triggerBtn) {
                triggerBtn.scrollIntoView({behavior: "smooth", block: "center"});
                await delay(300);
                triggerBtn.click();
                
                // Poll for the actual offer cards to load inside the sidebar
                let attempts = 0;
                while(attempts < 30) { // Max 3 seconds
                    let cards = document.querySelectorAll('a[class*="_card_"], [class*="OtherOfferListItem"]');
                    if (cards.length > 0) {
                        await delay(200); // Give React 200ms to populate the text
                        break;
                    }
                    await delay(100);
                    attempts++;
                }
            }
            
            // Signal Playwright that we are 100% done and it can extract the HTML
            window._noonOffersDone = true;
        })();
        
        // Return false initially to force Playwright to keep polling this function
        return false;
}"""
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
    #buy_box_wait_selector = '[data-qa="pdp-add-to-cart-revamp"], [data-qa="div-price-now"]'

    config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        extraction_strategy=extraction_strategy,
        #js_code=[JS_CLICK_SCRIPT],
        wait_for=JS_WAIT_CONDITION, 
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
