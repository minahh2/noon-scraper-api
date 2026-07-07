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

# The Native Clicker (Keeps the panel open)
async def native_click_hook(page, *args, **kwargs):
    print("⏳ [HOOK] Opening panel...")
    try:
        # Wait for the button
        btn_selector = 'button:has-text("عروض أكثر"), button:has-text("offers from"), [class*="slidingOptionsTrigger"]'
        btn = page.locator(btn_selector).first
        if await btn.count() > 0:
            await btn.click(force=True)
            await page.wait_for_timeout(3000) # Force wait for React to hydrate panel
        else:
            print("⚠️ [HOOK] No 'Other Offers' button found.")
    except Exception as e:
        print(f"❌ [HOOK] Click failed: {e}")

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.get_json()
    urls = data.get("urls")

    async def run_scraper():
        async with AsyncWebCrawler(config=browser_config, verbose=False) as crawler:
            crawler.crawler_strategy.set_hook("after_goto", native_click_hook)
            
            # NO SCHEMA STRATEGY HERE. We want raw HTML.
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
                    seller = card.select_one("[class*='_sellerName_']")
                    card_price = card.select_one("[class*='_sellingPrice_'] strong")
                    offers.append({
                        "seller": seller.text.strip() if seller else "Unknown",
                        "price": card_price.text.strip() if card_price else "0"
                    })
                
                output.append({
                    "url": result.url,
                    "product": name.text.strip() if name else "N/A",
                    "price": price.text.strip() if price else "N/A",
                    "other_offers": offers
                })
            return output

    return jsonify(asyncio.run(run_scraper()))

if __name__ == '__main__':
    from waitress import serve
    serve(app, host='0.0.0.0', port=5000, threads=4)
