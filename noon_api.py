import json
import asyncio
from flask import Flask, request, jsonify
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, BrowserConfig, CacheMode
from bs4 import BeautifulSoup
from waitress import serve

app = Flask(__name__)

# Minimal config
browser_config = BrowserConfig(
    headless=True,
    extra_args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"]
)

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.get_json()
    urls = data.get("urls", [])

    async def run_scraper():
        async with AsyncWebCrawler(config=browser_config, verbose=False) as crawler:
            # We will use a very simple click logic that doesn't overwhelm the browser
            async def simple_click(page, *args, **kwargs):
                try:
                    # Look for the specific "Other Sellers" text
                    btn = page.locator('text=Other offers').or_(page.locator('text=عروض أخرى')).first
                    if await btn.count() > 0:
                        await btn.click(force=True)
                        await page.wait_for_timeout(2000)
                except: pass

            crawler.crawler_strategy.set_hook("after_goto", simple_click)
            config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)
            
            results = await crawler.arun_many(urls=urls, config=config, semaphore_count=1)
            
            output = []
            for result in results:
                soup = BeautifulSoup(result.html, 'html.parser')
                cards = soup.select("a[class*='_card_'][href*='?o=']")
                offers = []
                for card in cards:
                    seller = card.select_one("[class*='_sellerName_']")
                    price_el = card.select_one("[class*='_sellingPrice_'] strong")
                    offers.append({"seller": seller.text.strip() if seller else "Unknown", "price": price_el.text.strip() if price_el else "0"})
                
                output.append({
                    "url": result.url,
                    "other_offers": offers,
                    "count": len(cards)
                })
            return output

    try:
        return jsonify(asyncio.run(run_scraper()))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # Use 1 thread to avoid memory spikes
    serve(app, host='0.0.0.0', port=5000, threads=1)
