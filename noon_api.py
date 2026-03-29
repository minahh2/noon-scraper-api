# Temporarily comment out the strict wait and css selectors
    # buy_box_wait_selector = '[class^="SupportDetailsV2"][class$="_actionList"] [class^="AddToCartWithQuanityV2"]'
    # main_content_selector = '[class^="ProductDetailsDesktop"]'

    config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        extraction_strategy=extraction_strategy,
        js_code=[JS_CLICK_SCRIPT],
        
        # --- DEBUG MODE ---
        screenshot=True, # Takes a picture of the page
        # wait_for=buy_box_wait_selector, # Disabled for debugging
        # css_selector=main_content_selector, # Disabled for debugging
        
        scan_full_page=True, # Let it load everything for the test
        magic=True,
        simulate_user=True,
        page_timeout=30000 
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
                        "data": extracted,
                        # --- NEW DEBUG INFO ---
                        "html_preview": result.html[:500] if result.html else "NO HTML",
                        "screenshot": result.screenshot # This will be a massive Base64 string
                    })
                else:
                    output.append({
                        "url": result.url, 
                        "status": result.status_code, 
                        "error": result.error_message,
                        "html_preview": result.html[:500] if result.html else "NO HTML"
                    })
            return output
