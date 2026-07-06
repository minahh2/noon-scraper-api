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

# --- THE DATADOME BEHAVIORAL BYPASS ---
JS_CLICK_SCRIPT = """
    (async () => {
        const flag = document.createElement('div');
        flag.id = 'noon-scraper-done';
        
        try {
            const delay = ms => new Promise(res => setTimeout(res, ms));
            
            let btn = Array.from(document.querySelectorAll('button')).find(el => 
                (el.textContent || "").toLowerCase().includes("offers from") || 
                (el.textContent || "").toLowerCase().includes("other sellers")
            );

            if (!btn) {
                btn = document.querySelector('button[class*="slidingOptionsTrigger"], div[class*="slidingOptionsTrigger"]');
            }

            if (btn) {
                btn.scrollIntoView({behavior: "smooth", block: "center"});
                await delay(800); 
                
                const rect = btn.getBoundingClientRect();
                const targetX = rect.left + (rect.width / 2);
                const targetY = rect.top + (rect.height / 2);
                
                // 1. BEHAVIORAL SPOOFING: Feed Datadome a human mouse trail
                for(let i = 1; i <= 5; i++) {
                    let moveX = targetX - (20 / i);
                    let moveY = targetY - (20 / i);
                    document.dispatchEvent(new MouseEvent('mousemove', { 
                        bubbles: true, clientX: moveX, clientY: moveY, screenX: moveX, screenY: moveY 
                    }));
                    await delay(40);
                }
                
                // 2. THE REACT FIBER HACK (Combined with the trusted coordinates)
                const reactKey = Object.keys(btn).find(k => k.startsWith('__reactFiber$'));
                let reactInjected = false;

                if (reactKey) {
                    let currentFiber = btn[reactKey];
                    while (currentFiber) {
                        let props = currentFiber.memoizedProps;
                        if (props && (props.onClick || props.onPointerDown)) {
                            let fakeEvent = {
                                preventDefault: () => {},
                                stopPropagation: () => {},
                                nativeEvent: { isTrusted: true }, 
                                isTrusted: true,
                                target: btn,
                                currentTarget: btn,
                                clientX: targetX,
                                clientY: targetY
                            };
                            if (props.onPointerDown) props.onPointerDown(fakeEvent);
                            if (props.onClick) props.onClick(fakeEvent);
                            reactInjected = true;
                            break;
                        }
                        currentFiber = currentFiber.return;
                    }
                }

                if (!reactInjected) {
                    btn.click(); // Fallback
                }
                
                // 3. FAIL-FAST ANTI-SKELETON LOOP (Max 7.5 seconds)
                let attempts = 0;
                while (attempts < 15) { 
                    let cards = document.querySelectorAll('a[class*="_card_"][href*="?o="], [class*="OtherOfferListItem"]');
                    let realCardsLoaded = Array.from(cards).filter(card => card.innerText.trim().length > 5);
                    
                    if (realCardsLoaded.length > 0) {
                        await delay(800); // 800ms buffer for React to inject the prices
                        break;
                    }
                    await delay(500);
                    attempts++;
                }
            }
        } catch (error) {
            console.error("Click script error:", error);
        } finally {
            // 4. GUARANTEED RELEASE: Python will never deadlock again
            document.body.appendChild(flag);
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
    buy_box_wait_selector = '[data-qa="pdp-add-to-cart-revamp"], [data-qa="div-price-now"]'

    config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        extraction_strategy=extraction_strategy,
        js_code_before_wait=[JS_CLICK_SCRIPT],
        wait_for='#noon-scraper-done',
        
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

    try:
        result = asyncio.run(run_scraper())
        return jsonify(result) 
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    from waitress import serve
    print("🚀 Starting Noon production server with Waitress (Max 4 threads)...")
    serve(app, host='0.0.0.0', port=5000, threads=4)
