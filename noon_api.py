import json
import asyncio
from flask import Flask, request, jsonify
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, BrowserConfig, CacheMode
from bs4 import BeautifulSoup

app = Flask(__name__)

# Browser config (same as before)
browser_config = BrowserConfig(
    viewport_width=1920,
    viewport_height=1080,
    headless=True,
    extra_args=["--no-sandbox", "--disable-gpu"]
)

# The Native Clicker (Updated to be Universal)
async def native_click_hook(page, *args, **kwargs):
    print("⏳ [HOOK] Attempting to click 'Other Offers'...")
    try:
        # This will find ANY element (button, div, span) containing the text
        # It covers both Arabic and English scenarios
        target_text = "عروض" 
        
        # We use a JavaScript expression to find the element that contains the text
        # and click it directly. This bypasses selector type issues.
        script = f"""
        () => {{
            const elements = Array.from(document.querySelectorAll('*'));
            const btn = elements.find(el => 
                el.innerText && 
                el.innerText.includes('{target_text}') && 
                el.innerText.length < 50 &&
                el.children.length === 0
            );
            if (btn) {{
                btn.click();
                return true;
            }}
            return false;
        }}
        """
        
        clicked = await page.evaluate(script)
        if clicked:
            print("✅ [HOOK] Click successful!")
            await page.wait_for_timeout(3000) # Give React 3 seconds to render the list
        else:
            print("⚠️ [HOOK] Could not find the button with text 'عروض'.")
            
    except Exception as e:
        print(f"❌ [HOOK] Click failed: {e}")

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.get_json()
    urls = data.get("urls")

    async def run_scraper():
        async with AsyncWebCrawler(config=browser_config, verbose=False) as crawler:
            crawler.crawler_strategy.set_hook("after_goto", native_click_hook)
            
            # Using BYPASS cache to force fresh page
            config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)
            results = await crawler.arun_many(urls=urls, config=config, semaphore_count=1)
            
            output = []
            for result in results:
                soup = BeautifulSoup(result.html, 'html.parser')
                
                # Extract main info
                name = soup.select_one("h1")
                price = soup.select_one("[data-qa='div-price-now']")
                
                # Extract offers using your verified CSS
                cards = soup.select("a[class*='_card_'][href*='?o=']")
                offers = []
                for card in cards:
                    # Robust parsing
                    seller = card.select_one("[class*='_sellerName_']")
                    price_el = card.select_one("[class*='_sellingPrice_'] strong")
                    
                    offers.append({
                        "seller": seller.text.strip() if seller else "Unknown",
                        "price": price_el.text.strip() if price_el else "0"
                    })
                
                output.append({
                    "url": result.url,
                    "product": name.text.strip() if name else "N/A",
                    "price": price.text.strip() if price else "N/A",
                    "other_offers": offers,
                    "debug_cards_found": len(cards) # We add this to help you debug
                })
            return output

    return jsonify(asyncio.run(run_scraper()))

if __name__ == '__main__':
    from waitress import serve
    serve(app, host='0.0.0.0', port=5000, threads=4)
