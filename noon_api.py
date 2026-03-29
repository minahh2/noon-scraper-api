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

# GLOBAL BROWSER CONFIG: Optimized for Docker/Coolify memory limits
browser_config = BrowserConfig(
    viewport_width=1920,
    viewport_height=1080,
    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    user_agent_mode="random",
    text_mode=True, 
    light_mode=True,
    extra_args=[
        "--no-sandbox", 
        "--disable-gpu", 
        "--disable-extensions",
        "--disable-dev-shm-usage", # Crucial for Coolify/Docker stability
        "--js-flags=--max-old-space-size=512" 
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
    data = request.get_json()
    urls = data.get("urls")
    schema = data.get("schema")

    if not isinstance(urls, list) or not isinstance(schema, dict):
        return jsonify({"error": "Invalid input. 'urls' must be a list, 'schema' must be a dict."}), 400

    extraction_strategy = JsonCssExtractionStrategy(schema, verbose=False)
    
    # CSS Selectors
    buy_box_wait_selector = '[class^="SupportDetailsV2"][class$="_actionList"] [class^="AddToCartWithQuanityV2"]'
    main_content_selector = '[class^="ProductDetailsDesktop"]'

    config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        extraction_strategy=extraction_strategy,
        js_code=[JS_CLICK_SCRIPT],
        
        # --- SMART WAITING ---
        wait_for=buy_box_wait_selector, 
        
        # --- PERFORMANCE TARGETING & EXCLUSIONS ---
        css_selector=main_content_selector, # Only extract from this container
        excluded_tags=['nav', 'footer', 'header', 'aside', 'script', 'style', 'noscript'],
        exclude_external_links=True,
        exclude_social_media_links=True,
        exclude_external_images=True,
        
        # --- CRAWLER BEHAVIOR ---
        scan_full_page=False, 
        magic=True,
        simulate_user=True,
        page_timeout=30000 
    )

    async def run_scraper():
        async with AsyncWebCrawler(config=browser_config, verbose=False) as crawler:
            # semaphore_count limits concurrent tabs so your server doesn't crash
            results = await crawler.arun_many(urls=urls, config=config, semaphore_count=3)
            
            output = []
            for result in results:
                if result.success:
                    try:
                        extracted = json.loads(result.extracted_content)
                    except Exception:
                        extracted = {"error": "Failed to parse extracted content"}
                    output.append({"url": result.url, "status": result.status_code, "data": extracted})
                else:
                    output.append({"url": result.url, "status": result.status_code, "error": result.error_message})
            return output

    try:
        # 90 second hard timeout for the entire batch request
        result = await asyncio.wait_for(run_scraper(), timeout=90) 
        return jsonify(result)
    except asyncio.TimeoutError:
        return jsonify({"error": "Overall scraping process timed out"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)
