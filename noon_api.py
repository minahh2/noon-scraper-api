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
    use_persistent_context=True,
    extra_args=[
        "--no-sandbox", 
        "--disable-gpu", 
        "--disable-extensions",
        "--disable-dev-shm-usage", 
        "--js-flags=--max-old-space-size=512",
        "--disable-features=IsolateOrigins,site-per-process",
        "--disable-blink-features=AutomationControlled",
        f"--host-rules={tracker_blackhole}"
    ]
)

JS_CLICK_SCRIPT = """
return new Promise((resolve) => {
    (async () => {
        try {
            // Block all client-side and server-side navigations to prevent React from soft-reloading the page
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

            console.log("⏳ Starting execution...");

            let btn = null;
            for (let i = 0; i < 20; i++) {
                btn = Array.from(document.querySelectorAll('*')).find(el => {
                    if (!el.innerText || el.children.length > 0) return false;
                    let text = el.innerText.trim().toLowerCase();
                    return text.includes('offers from') ||
                        text.includes('other sellers') ||
                        text.includes('عروض أكثر من بائعين آخرين') ||
                        text.includes('عروض أخرى');
                });
                if (!btn) {
                    btn = document.querySelector('[class*="slidingOptionsTrigger"]');
                }
                if (btn) break;
                await new Promise(r => setTimeout(r, 100));
            }

            if (!btn) {
                console.warn("⚠️ Button not detected. Product might be single-seller.");
                resolve(true);
                return;
            }

            const target = btn.parentElement || btn;
            console.log("🎯 Targeting element:", target);
            target.scrollIntoView({ behavior: 'smooth', block: 'center' });
            await new Promise(r => setTimeout(r, 1000));

            const eventOpts = { bubbles: true, cancelable: true, view: window, pointerId: 1, pointerType: 'mouse' };
            target.dispatchEvent(new PointerEvent('pointerdown', eventOpts));
            target.dispatchEvent(new MouseEvent('mousedown', eventOpts));
            target.dispatchEvent(new PointerEvent('pointerup', eventOpts));
            target.dispatchEvent(new MouseEvent('mouseup', eventOpts));
            target.dispatchEvent(new MouseEvent('click', eventOpts));
            
            let fiberKey = Object.keys(target).find(k => k.startsWith('__reactFiber$'));
            if (fiberKey) {
                let fiber = target[fiberKey];
                let found = false;
                while (fiber && !found) {
                    if (fiber.memoizedProps) {
                        ['onClick', 'onPointerDown', 'onMouseDown'].forEach(h => {
                            if (typeof fiber.memoizedProps[h] === 'function') {
                                try {
                                    fiber.memoizedProps[h]({ preventDefault: () => {}, stopPropagation: () => {}, target: target, currentTarget: target });
                                    found = true;
                                } catch(e) {}
                            }
                        });
                    }
                    fiber = fiber.return;
                }
            }

            console.log("⏳ Checking for loaded offers...");
            for (let i = 0; i < 15; i++) {
                const cards = document.querySelectorAll('a[class*="_card_"][href*="?o="]');
                if (cards.length > 0) {
                    console.log(`🎉 SUCCESS: ${cards.length} offers loaded visually.`);
                    setTimeout(() => resolve(true), 800);
                    return;
                }
                await new Promise(r => setTimeout(r, 500));
            }
            
            console.log("🏁 Visual drawer failed, injecting LD+JSON fallback...");
            let ldJson = Array.from(document.querySelectorAll('script[type="application/ld+json"]')).find(s => s.innerText.includes('"offers"'));
            if (ldJson) {
                try {
                    let data = JSON.parse(ldJson.innerText);
                    let offers = data.offers;
                    if (Array.isArray(offers) && offers.length > 0) {
                        let html = '<div id="injected-offers-drawer" class="_container_nz0ky offersListCtr">';
                        offers.forEach(o => {
                            let sName = o.seller ? o.seller.name : 'Unknown';
                            let oPrice = o.price || '';
                            html += '<a class="_card_" href="?o=fallback">' + 
                                '<div class="_sellerName_">' + sName + '</div>' + 
                                '<div class="_sellingPrice_"><strong>' + oPrice + '</strong></div>' + 
                                '<div class="_textValue_">N/A</div>' + 
                            '</a>';
                        });
                        html += '</div>';
                        document.body.insertAdjacentHTML('beforeend', html);
                        console.log("🎉 SUCCESS: Injected " + offers.length + " cards via LD+JSON.");
                        resolve(true);
                        return;
                    }
                } catch(e) {}
            }

            console.log("❌ Both visual and LD+JSON fallbacks failed.");
            resolve(true);

        } catch (error) {
            console.error("❌ Exception caught:", error);
            resolve(true);
        }
    })();
});
"""

import time

# Global state for intelligent session batching
_scrape_counter = 0
_current_session_id = f"noon_session_{int(time.time())}"

@app.route('/scrape', methods=['POST'])
def scrape():
    global _scrape_counter, _current_session_id
    
    _scrape_counter += 1
    if _scrape_counter > 50:
        _scrape_counter = 1
        _current_session_id = f"noon_session_{int(time.time())}"
        print(f"🔄 Rotating Session ID: {_current_session_id}")
        
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
        session_id=_current_session_id,
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
    print("Starting Noon production server with Waitress (Max 4 threads)...")
    serve(app, host='0.0.0.0', port=5000, threads=4)
