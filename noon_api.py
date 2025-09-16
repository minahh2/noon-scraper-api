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

# Global browser config
browser_config = BrowserConfig(
    viewport_width=1920,
    viewport_height=1080,
    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    user_agent_mode="random",
    text_mode=True,
    light_mode=True,
    extra_args=["--no-sandbox", "--disable-gpu", "--disable-extensions"]
)

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.get_json()
    urls = data.get("urls")
    schema = data.get("schema")

    if not isinstance(urls, list) or not isinstance(schema, dict):
        return jsonify({"error": "Invalid input"}), 400

    extraction_strategy = JsonCssExtractionStrategy(schema, verbose=True)
    config = CrawlerRunConfig(
    cache_mode=CacheMode.BYPASS,
    extraction_strategy=extraction_strategy,
    scan_full_page=True,
    scroll_delay=0.3,    
    magic=True,
    simulate_user=True    
)


    async def run_scraper():
        async with AsyncWebCrawler(config=browser_config, verbose=True) as crawler:
            results = await crawler.arun_many(urls=urls, config=config)
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

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(asyncio.wait_for(run_scraper(), timeout=60))
        return jsonify(result)
    except asyncio.TimeoutError:
        return jsonify({"error": "Scraping timed out"}), 504

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
