# --- Update ONLY this block in your noon_api.py ---
async def native_click_hook(page, *args, **kwargs):
    print("⏳ [HOOK] Attempting to find trigger...")
    
    # Aggressive selector: Looking for buttons, divs, and Links (<a>)
    selectors = [
        '[class*="slidingOptionsTrigger"]',
        'button:has-text("offers")', 
        'div:has-text("عروض")',
        'a:has-text("عروض")',
        'a:has-text("offers")'
    ]
    
    try:
        for selector in selectors:
            btn = page.locator(selector).first
            if await btn.count() > 0:
                print(f"🎯 [HOOK] Found element with selector: {selector}")
                await btn.scroll_into_view_if_needed()
                await btn.click(force=True)
                await page.wait_for_timeout(3000)
                return # Stop after first successful click

        # If we reach here, we failed. Print EVERYTHING to logs for debugging.
        elements = await page.eval_on_selector_all("button, div, a", "els => els.map(el => el.innerText.trim())")
        print(f"⚠️ [HOOK] Could not find button. All actionable text found: {elements[:50]}") # First 50 items

    except Exception as e:
        print(f"❌ [HOOK] Click failed: {e}")
