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
    headless=True,
    viewport_width=1920,
    viewport_height=1080,
    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
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
        "--disable-blink-features=AutomationControlled",
        f"--host-rules={tracker_blackhole}"
    ]
)

JS_CLICK_SCRIPT = """
return new Promise((resolve) => {
    (async function() {
        try {
            let mainLoaded = false;
            for (let i = 0; i < 40; i++) { 
                if (document.querySelector('[data-qa="product-name"], h1, [class*="ProductTitle"], [class*="productTitle"]')) {
                    mainLoaded = true;
                    break;
                }
                await new Promise(r => setTimeout(r, 500));
            }

            if (!mainLoaded) {
                return resolve("TIMEOUT_MAIN_PAGE_NOT_LOADED");
            }

            window.scrollBy(0, 800);
            await new Promise(r => setTimeout(r, 600));
            window.scrollBy(0, 800);
            await new Promise(r => setTimeout(r, 600));
            
            let btn = null;
            let attempts = 0;
            
            // Poll for the React DOM to render
            while (attempts < 10) {
                // Strict text matching on leaf nodes
                const allElements = document.querySelectorAll('button, div, span, p');
                for (let i = 0; i < allElements.length; i++) {
                    let el = allElements[i];
                    if (el.children.length === 0) {
                        let rawText = el.textContent || el.innerText || "";
                        let text = rawText.trim().toLowerCase();
                        if (text.length > 0 && (
                            text === "offers from" ||
                            text.includes("other sellers") || 
                            text.includes("\\u0639\\u0631\\u0648\\u0636 \\u0645\\u0646") || 
                            text.includes("\\u0628\\u0627\\u0626\\u0639\\u064a\\u0646 \\u0622\\u062e\\u0631\\u064a\\u0646") ||
                            text.includes("offers") && text.includes("other") ||
                            text.includes("new from")
                        )) {
                            btn = el.closest('button') || el;
                            break;
                        }
                    }
                }
                
                if (btn) break;
                await new Promise(r => setTimeout(r, 1000));
                attempts++;
            }

            if (btn) {
                btn.scrollIntoView({ behavior: 'smooth', block: 'center' });
                await new Promise(r => setTimeout(r, 2000)); 
                
                if (btn.hasAttribute('href')) btn.removeAttribute('href');
                
                for(let j = 0; j < 10; j++) {
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
                        let jsonStr = JSON.stringify(extractedOffers);
                        await new Promise(r => setTimeout(r, 1000));
                        return resolve("|||EXTRACTED_OFFERS|||" + jsonStr + "|||END|||");
                    }
                }
                
                return resolve("TIMEOUT_NO_CARDS_AFTER_CLICK: " + btn.outerHTML.substring(0, 300));
            } else {
                return resolve("NO_BUTTON_FOUND");
            }
        } catch (err) {
            return resolve("JS_CRASH: " + err.toString());
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
    buy_box_wait_selector = '[data-qa="pdp-add-to-cart-revamp"]'

    JS_CLICK_SCRIPT = """
    return new Promise((resolve) => {
        (async function() {
            try {
                // Block all client-side and server-side navigations
                history.pushState = function() {};
                history.replaceState = function() {};
                window.onbeforeunload = function() { return false; };
                window.addEventListener('click', e => {
                    let a = e.target.closest('a');
                    if (a && a.href && !a.href.includes('?o=')) {
                        e.preventDefault();
                        e.stopPropagation();
                    }
                }, true);

                let mainLoaded = false;
                for (let i = 0; i < 40; i++) { 
                    if (document.querySelector('[data-qa="product-name"], h1, [class*="ProductTitle"]')) {
                        mainLoaded = true;
                        break;
                    }
                    await new Promise(r => setTimeout(r, 500));
                }

                if (!mainLoaded) return resolve("TIMEOUT_MAIN_PAGE_NOT_LOADED");

                window.scrollBy(0, 800);
                await new Promise(r => setTimeout(r, 600));
                window.scrollBy(0, 800);
                await new Promise(r => setTimeout(r, 600));
                
                let btn = null;
                let attempts = 0;
                
                while (attempts < 10) {
                    const allElements = document.querySelectorAll('button, div, span, p, a');
                    for (let i = 0; i < allElements.length; i++) {
                        let el = allElements[i];
                        if (el.children.length === 0) {
                            let text = (el.textContent || el.innerText || "").trim().toLowerCase();
                            if (text.length > 0 && (
                                text.includes("other sellers") || 
                                text.includes("other offers") ||
                                text.includes("compare offers") ||
                                text === "view more sellers" ||
                                text.includes("\\u0628\\u0627\\u0626\\u0639\\u064a\\u0646 \\u0622\\u062e\\u0631\\u064a\\u0646") ||
                                text.includes("\\u0639\\u0631\\u0648\\u0636 \\u0623\\u062e\\u0631\\u0649")
                            )) {
                                btn = el.closest('button') || el.closest('a') || el.parentElement || el;
                                break;
                            }
                        }
                    }
                    if (btn) break;
                    await new Promise(r => setTimeout(r, 1000));
                    attempts++;
                }

                if (btn) {
                    btn.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    await new Promise(r => setTimeout(r, 1000)); 
                    
                    if (btn.hasAttribute('href')) btn.removeAttribute('href');
                    let initialChildren = document.body.children.length;
                    
                    btn.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
                    btn.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
                    btn.click();
                    
                    // React 17/18 Fiber Trick
                    let fiberKey = Object.keys(btn).find(k => k.startsWith('__reactFiber$'));
                    if (fiberKey) {
                        let fiber = btn[fiberKey];
                        while (fiber) {
                            if (fiber.memoizedProps && typeof fiber.memoizedProps.onClick === 'function') {
                                try {
                                    fiber.memoizedProps.onClick({
                                        preventDefault: () => {}, 
                                        stopPropagation: () => {}, 
                                        target: btn, 
                                        currentTarget: btn
                                    });
                                } catch(e) {}
                                break;
                            }
                            fiber = fiber.return;
                        }
                    }
                    
                    await new Promise(r => setTimeout(r, 3000));
                    
                    let newHtml = "NO_NEW_ELEMENTS";
                    let portal = document.getElementById('overlay-portal') || document.body;
                    let drawer = portal.querySelector('[class*="offersListCtr"], [class*="_container_nz0ky"], [class*="Panel"]');
                    if (drawer) {
                        newHtml = drawer.outerHTML;
                    }
                    
                    return resolve("|||DRAWER_HTML|||" + newHtml.substring(0, 5000) + "|||END|||");
                } else {
                    return resolve("NO_BUTTON_FOUND");
                }
            } catch (err) {
                return resolve("JS_CRASH: " + err.toString());
            }
        })();
    });
    """

    config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        extraction_strategy=extraction_strategy,
        js_code=[JS_CLICK_SCRIPT],
        delay_before_return_html=2.5, 
        excluded_tags=['nav', 'footer', 'header', 'style', 'noscript'],
        remove_overlay_elements=False,
        exclude_external_links=True,
        exclude_social_media_links=True,
        exclude_external_images=True,
        word_count_threshold=10,
        magic=True
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
                        js_res = getattr(result, "js_execution_result", None)
                        js_debug = str(js_res)[:500] if js_res else "js_execution_result_is_none"
                            
                        if isinstance(extracted, list) and len(extracted) > 0:
                            extracted[0]["js_debug"] = js_debug
                        elif isinstance(extracted, dict) and "data" in extracted and len(extracted["data"]) > 0:
                            extracted["data"][0]["js_debug"] = js_debug
                        elif isinstance(extracted, dict) and "original" not in extracted:
                            extracted["js_debug"] = js_debug
                            
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
