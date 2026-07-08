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
(async function() {
    function setDebug(msg) {
        let brandEl = document.querySelector('[data-qa="brand-name"], [class*="brandName"]');
        if (brandEl) brandEl.textContent = "DEBUG: " + msg;
    }

    let mainLoaded = false;
    for (let i = 0; i < 40; i++) { 
        if (document.querySelector('[data-qa="pdp-add-to-cart-revamp"]')) {
            mainLoaded = true;
            break;
        }
        await new Promise(r => setTimeout(r, 500));
    }

    if (!mainLoaded) {
        setDebug("TIMEOUT_MAIN_PAGE");
        return "TIMEOUT_MAIN_PAGE_NOT_LOADED";
    }

    window.scrollBy(0, 800);
    await new Promise(r => setTimeout(r, 600));
    window.scrollBy(0, 800);
    await new Promise(r => setTimeout(r, 600));
    
    let btn = null;
    const allElements = document.querySelectorAll('*');
    for (let i = 0; i < allElements.length; i++) {
        let el = allElements[i];
        if (el.children.length === 0) {
            let rawText = el.textContent || el.innerText || "";
            let text = rawText.trim().toLowerCase();
            if (text.length > 0 && (
                text.includes("offers from") || 
                text.includes("other sellers") || 
                (text.includes("عروض") && text.includes("بائعين")) ||
                (text.includes("عروض") && text.includes("أخرى")) ||
                (text.includes("مزيد") && text.includes("عروض")) ||
                text === "عروض أخرى"
            )) {
                btn = el.parentElement || el;
                break;
            }
        }
    }

    if (btn) {
        btn.scrollIntoView({ behavior: 'smooth', block: 'center' });
        await new Promise(r => setTimeout(r, 1500)); // wait for react hydration
        
        if (btn.hasAttribute('href')) btn.removeAttribute('href');
        
        // Try clicking multiple times (fixes React delayed hydration)
        for(let j = 0; j < 3; j++) {
            btn.click();
            await new Promise(r => setTimeout(r, 1000));
            
            const cards = document.querySelectorAll('a[class*="_card_"][href*="?o="]');
            if (cards.length > 0) {
                await new Promise(r => setTimeout(r, 1500));
                return "SUCCESS_CARDS_LOADED";
            }
        }
        
        setDebug("TIMEOUT_NO_CARDS");
        return "TIMEOUT_NO_CARDS_AFTER_CLICK";
    } else {
        setDebug("NO_BUTTON_FOUND");
        return "NO_BUTTON_FOUND";
    }
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
    buy_box_wait_selector = '[data-qa="pdp-add-to-cart-revamp"]'

    config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        extraction_strategy=extraction_strategy,
        js_code=[JS_CLICK_SCRIPT],
        delay_before_return_html=2.5, # Give react time to paint the offers
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
                        "data": extracted,
                        "html_preview": result.html[:300] if result.html else "NO HTML"
                    })
                else:
                    output.append({
                        "url": result.url, 
                        "status": result.status_code, 
                        "error": result.error_message,
                        "html_preview": result.html[:300] if result.html else "NO HTML"
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
