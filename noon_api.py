import json
import asyncio
from flask import Flask, request, jsonify
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, BrowserConfig, CacheMode
from bs4 import BeautifulSoup

app = Flask(__name__)

# Same config as before
browser_config = BrowserConfig(
    viewport_width=1920,
    viewport_height=1080,
    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    headless=True,
    extra_args=["--no-sandbox", "--disable-gpu"]
)

async def forensic_hook(page, *args, **kwargs):
    print("📸 [FORENSIC] Taking a snapshot of the page...")
    # This saves a file named 'debug_screenshot.png' in your container
    await page.screenshot(path="debug_screenshot.png", full_page=True)
    
    # Check if there is a "Deliver to" or "Login" popup
    content = await page.content()
    if "Deliver to" in content or "login" in content.lower():
        print("⚠️ [FORENSIC] Warning: Found popup in HTML.")
    
    # Try to click the button only if visible
    try:
        btn = page.locator('button:has-text("عروض"), button:has-text("offers")').first
        if await btn.is_visible():
            await btn.click(force=True)
            await page.wait_for_timeout(2000)
    except Exception as e:
        print(f"❌ [FORENSIC] Could not click: {e}")

@app.route('/scrape', methods=['POST'])
def scrape():
    try:
        data = request.get_json()
        urls = data.get("urls")

        async def run_scraper():
            async with AsyncWebCrawler(config=browser_config, verbose=False) as crawler:
                crawler.crawler_strategy.set_hook("after_goto", forensic_hook)
                config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)
                results = await crawler.arun_many(urls=urls, config=config, semaphore_count=1)
                
                output = []
                for result in results:
                    # Return title so we know if we are on the right page
                    soup = BeautifulSoup(result.html, 'html.parser')
                    title = soup.title.string if soup.title else "No Title Found"
                    
                    output.append({
                        "url": result.url,
                        "title_detected": title,
                        "html_sample": result.html[:500] # Just the first 500 chars
                    })
                return output

        return jsonify(asyncio.run(run_scraper()))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    from waitress import serve
    serve(app, host='0.0.0.0', port=5000, threads=4)
