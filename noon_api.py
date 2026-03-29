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

# GLOBAL BROWSER CONFIG
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
        "--disable-dev-shm-usage",
        "--js-flags=--max-old-space-size=512" 
    ]
)

# JAVASCRIPT SPOOFING
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
    
    # Safety check to prevent NoneType errors if JSON isn't passed correctly
    if not data:
         return jsonify({"error": "No JSON payload received"}), 400
         
    urls = data.get("urls")
    schema = data.get("schema")

    if not isinstance(urls, list) or not isinstance(schema, dict):
        return jsonify({"error": "Invalid input. 'urls' must be a list, 'schema' must be a dict."}), 400

    extraction_strategy = JsonCssExtractionStrategy(schema, verbose=False)

    # --- DEBUG CONFIGURATION ---
    config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        extraction_strategy=extraction_strategy,
        js_code=[JS_CLICK_SCRIPT],
        
        screenshot=True, # Takes a picture to see if we are blocked
        scan_full_page=True, # Let it load naturally for the debug test
        magic=True,
        simulate_user=True,
        page_timeout=30000 
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
                        "data": extracted,
                        "html_preview": result.html[:500] if result.html else "NO HTML",
                        "screenshot": result.screenshot 
                    })
                else:
                    output.append({
                        "url": result.url, 
                        "status": result.status_code, 
                        "error": result.error_message,
                        "html_preview": result.html[:500] if result.html else "NO HTML"
                    })
            return output

    # --- THIS IS THE BLOCK THAT WAS MISSING ---
    try:
        result = await asyncio.wait_for(run_scraper(), timeout=90) 
        return jsonify(result) # This actually sends the data back to n8n
    except asyncio.TimeoutError:
        return jsonify({"error": "Overall scraping process timed out"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)
