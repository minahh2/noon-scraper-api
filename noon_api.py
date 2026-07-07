import json
import asyncio
from flask import Flask, request, jsonify
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, BrowserConfig, CacheMode
from bs4 import BeautifulSoup

app = Flask(__name__)

browser_config = BrowserConfig(
    viewport_width=1920,
    viewport_height=1080,
    headless=True,
    extra_args=["--no-sandbox", "--disable-gpu"]
)

async def native_click_hook(page, *args, **kwargs):
    print("⏳ [HOOK] Attempting to find and click 'Other Offers' trigger...")
    
    # These are the 3 most common triggers for the "Other Offers" panel on Noon
    selectors = [
        '[class*="slidingOptionsTrigger"]',
        '[data-qa="other-sellers-trigger"]',
        'button:has-text("offers")', 
        'div:has-text("عروض")'
    ]
    
    try:
        clicked = False
        for selector in selectors:
            btn = page.locator(selector).first
            if await btn.count() > 0:
                print(f"🎯 [HOOK] Found button with selector: {selector}")
                await btn.scroll_into_view_if_needed()
                await btn.click(force=True)
                clicked = True
                await page.wait_for_timeout(3000) # Wait for panel to open
                break
        
        if not clicked:
            print("⚠️ [HOOK] Could NOT find the trigger button. Listing all buttons found:")
            # Diagnostic: Print all buttons found on the page to help us debug
            buttons = await page.eval_on_selector_all("button, div[role='button']", "elements => elements.map(el => el.innerText)")
            print(f"Buttons found: {buttons}")

    except Exception as e:
        print(f"❌ [HOOK] Click failed: {e}")

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.get_json()
    urls = data.get("urls")

    async def run_scraper():
        async with AsyncWebCrawler(config=browser_config, verbose=False) as crawler:
            crawler.crawler_strategy.set_hook("after_goto", native_click_hook)
            
            config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)
            results = await crawler.arun_many(urls=urls, config=config, semaphore_count=1)
            
            output = []
            for result in results:
                soup = BeautifulSoup(result.html, 'html.parser')
                
                # Extract main info
                name = soup.select_one("h1")
                price = soup.select_one("[data-qa='div-price-now']")
                
                # Extract offers
                cards = soup.select("a[class*='_card_'][href*='?o=']")
                offers = []
                for card in cards:
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
                    "debug_cards_found": len(cards)
                })
            return output

    return jsonify(asyncio.run(run_scraper()))

if __name__ == '__main__':
    from waitress import serve
    serve(app, host='0.0.0.0', port=5000, threads=4)
