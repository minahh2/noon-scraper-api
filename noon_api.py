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

# --- NEW: GLOBAL COUNTERS FOR SESSION ROTATION ---
request_counter = 0
current_session_batch = 1

# GLOBAL BROWSER CONFIG: Optimized for production/Coolify memory limits
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

# JAVASCRIPT SPOOFING: Forces the dynamic React panel to load data
JS_CLICK_SCRIPT = """
const elements = document.querySelectorAll('[class*="_slidingOptionsTriggerContainer"]');
for (let el of elements) {
    let hasClass = Array.from(el.classList).some(className => className.endsWith('_slidingOptionsTriggerContainer'));
    let isVisible = el.offsetWidth > 0 && el.offsetHeight > 0;

    if (hasClass && isVisible) {
        const rect = el.getBoundingClientRect();
        const x = rect.left + (rect.width / 2);
        const y = rect.top + (rect.height / 2);

        const eventTypes = ['mouseenter', 'mouseover', 'pointerdown', 'mousedown', 'mouseup', 'pointerup', 'click'];
        eventTypes.forEach(eventType => {
            const event = new MouseEvent(eventType, {
                view: window, bubbles: true, cancelable: true, buttons: 1,
                clientX: x, clientY: y, screenX: x, screenY: y
            });
            let target = el.firstElementChild ? el.firstElementChild : el;
            target.dispatchEvent(event);
        });
        break; 
    }
}
"""

@app.route('/scrape', methods=['POST'])
async def scrape():
    # Bring in the global variables so we can modify them
    global request_counter, current_session_batch

    data = request.get_json()
    
    # Safety check to prevent Flask crashes if payload is missing
    if not data:
         return jsonify({"error": "No JSON payload received"}), 400
         
    urls = data.get("urls")
    schema = data.get("schema")

    if not isinstance(urls, list) or not isinstance(schema, dict):
        return jsonify({"error": "Invalid input. 'urls' must be a list, 'schema' must be a dict."}), 400

    # --- SESSION ROTATION LOGIC ---
    # Add the number of URLs in this request to our counter
    request_counter += len(urls)
    
    # If we have processed more than 50 URLs, rotate to a fresh session!
    if request_counter > 50:
        current_session_batch += 1
        request_counter = len(urls) # Reset the counter, carrying over the current batch size
        print(f"🔄 Rotating to new session batch: n_daily_{current_session_batch:02d}")

    # Generate the dynamic session string (e.g., n_daily_01, n_daily_02)
    dynamic_session_id = f"n_daily_{current_session_batch:02d}"

    extraction_strategy = JsonCssExtractionStrategy(schema, verbose=False)

    # --- CSS SELECTORS ---
    buy_box_wait_selector = '[class^="AddToCartWithQuanityV2"][class$="_isVisible"], [class^="AddToCartWithQuanityV2"][class$="_disabledElement"]'
    main_content_selector = '[data-qa="pdp-container"]'

    # --- PRODUCTION CONFIGURATION ---
    config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        
        # USE THE DYNAMIC SESSION ID HERE
        session_id=dynamic_session_id, 
        
        extraction_strategy=extraction_strategy,
        js_code=[JS_CLICK_SCRIPT],
        
        # Smart waiting instead of fixed delays
        wait_for=buy_box_wait_selector, 
        
        # Performance Targeting & Exclusions
        excluded_tags=['nav', 'footer', 'header', 'script', 'style', 'noscript'],
        exclude_external_links=True,
        exclude_social_media_links=True,
        exclude_external_images=True,
        
        # Crawler Behavior Settings
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
                    
                    # Clean return object
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

    # --- PROPER ERROR HANDLING AND RETURN BLOCK ---
    try:
        # Note: If your array of URLs is very large (e.g., 10+), you might need to increase this 90-second timeout
        result = await asyncio.wait_for(run_scraper(), timeout=90) 
        return jsonify(result) 
    except asyncio.TimeoutError:
        return jsonify({"error": "Overall scraping process timed out"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)
