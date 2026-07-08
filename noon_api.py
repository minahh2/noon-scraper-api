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
        document.body.innerHTML = '<h1>DEBUG_NOON_API: ' + msg + '</h1>';
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
                text.includes("\\u0639\\u0631\\u0648\\u0636") || 
                text.includes("\\u0628\\u0627\\u0626\\u0639\\u064a\\u0646") ||
                text.includes("\\u0623\\u062e\\u0631\\u0649") ||
                text.includes("\\u0645\\u0632\\u064a\\u062f")
            )) {
                btn = el.closest('button') || el.parentElement || el;
                break;
            }
        }
    }

    function setDebug(msg) {
        let brandEl = document.querySelector('[class*="_brand_"], [class*="brandStoreLink"]');
        let titleEl = document.querySelector('[class*="productTitle"], [class*="ProductTitle"]');
        if (brandEl) brandEl.textContent = "DEBUG_NOON_API: " + msg;
        if (titleEl) titleEl.textContent = "DEBUG_NOON_API: " + msg;
    }

    if (btn) {
        try {
            btn.scrollIntoView({ behavior: 'smooth', block: 'center' });
            await new Promise(r => setTimeout(r, 3000)); 
            
            if (btn.hasAttribute('href')) btn.removeAttribute('href');
            
            for(let j = 0; j < 4; j++) {
                // Dispatch full React synthetic event chain
                btn.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
                btn.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
                btn.click();
                
                await new Promise(r => setTimeout(r, 1000));
                
                const cards = document.querySelectorAll('a[class*="_card_"][href*="?o="]');
                if (cards.length > 0) {
                    let extractedOffers = [];
                    cards.forEach(card => {
                        let nameEl = card.querySelector('[class*="_sellerName_"]');
                        let priceEl = card.querySelector('[class*="_sellingPrice_"] strong, [class*="_sellingPrice_"]');
                        let ratingEl = card.querySelector('[class*="_textValue_"]');
                        extractedOffers.push({
                            seller_name: nameEl ? nameEl.innerText.trim() : "",
                            price: priceEl ? priceEl.innerText.trim() : "",
                            rating: ratingEl ? ratingEl.innerText.trim() : ""
                        });
                    });
                    
                    let titleEl = document.querySelector('[class*="productTitle"], [class*="ProductTitle"]');
                    if (titleEl) {
                        titleEl.textContent = titleEl.textContent + "|||JSON|||" + JSON.stringify(extractedOffers);
                    } else {
                        // Fallback
                        let h1 = document.querySelector("h1") || document.body;
                        if(h1 && h1.textContent) {
                            h1.textContent = h1.textContent + "|||JSON|||" + JSON.stringify(extractedOffers);
                        }
                    }
                    
                    await new Promise(r => setTimeout(r, 1000));
                    return "SUCCESS_CARDS_LOADED";
                }
            }
            
            setDebug("TIMEOUT_NO_CARDS_AFTER_CLICKS");
            return "TIMEOUT_NO_CARDS_AFTER_CLICK";
        } catch (err) {
            setDebug("JS_CRASH: " + err.toString());
            return "JS_CRASH";
        }
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
    buy_box_wait_selector = '[data-qa="pdp-add-to-cart-revamp"]'

    config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        extraction_strategy=extraction_strategy,
        js_code=[JS_CLICK_SCRIPT],
        delay_before_return_html=2.5, 
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
        from bs4 import BeautifulSoup
        async with AsyncWebCrawler(config=browser_config, verbose=False) as crawler:
            results = await crawler.arun_many(urls=urls, config=config, semaphore_count=3)
            
            output = []
            for result in results:
                if result.success:
                    try:
                        extracted = json.loads(result.extracted_content)
                        # Inject our natively extracted JS data to bypass strategy bugs
                        native_offers = [{"debug_error": "json_not_appended_to_text"}]
                        
                        if isinstance(extracted, list) and len(extracted) > 0:
                            product_name = extracted[0].get("product_name", "")
                            if "|||JSON|||" in product_name:
                                parts = product_name.split("|||JSON|||")
                                extracted[0]["product_name"] = parts[0].strip()
                                try:
                                    native_offers = json.loads(parts[1])
                                except Exception as e:
                                    native_offers = [{"debug_error": "json_parse_failed: " + str(e)}]
                            extracted[0]["other_offers"] = native_offers
                            
                        elif isinstance(extracted, dict) and "data" in extracted and len(extracted["data"]) > 0:
                            product_name = extracted["data"][0].get("product_name", "")
                            if "|||JSON|||" in product_name:
                                parts = product_name.split("|||JSON|||")
                                extracted["data"][0]["product_name"] = parts[0].strip()
                                try:
                                    native_offers = json.loads(parts[1])
                                except Exception as e:
                                    native_offers = [{"debug_error": "json_parse_failed: " + str(e)}]
                            extracted["data"][0]["other_offers"] = native_offers
                        else:
                            extracted = {"original": extracted, "other_offers": native_offers}
                            
                    except Exception as e:
                        extracted = {"error": "Failed to parse content: " + str(e)}
                    
                    output.append({
                        "url": result.url, 
                        "status": result.status_code, 
                        "data": extracted,
                        "html_preview": result.html[:500] if result.html else "NO HTML"
                    })
                else:
                    output.append({
                        "url": result.url, 
                        "status": result.status_code, 
                        "error": result.error_message,
                        "html_preview": result.html[:500] if result.html else "NO HTML"
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
