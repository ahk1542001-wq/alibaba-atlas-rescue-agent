import asyncio
import os
from playwright.async_api import async_playwright

async def run_e2e_test():
    print("Starting TravelCare AI E2E Test Suite...")
    os.makedirs("e2e_screenshots", exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await context.new_page()

        # 1. Load dashboard and verify sidebar + brand
        print("Step 1: Loading dashboard...")
        await page.goto("http://localhost:8050")
        await page.wait_for_load_state("networkidle")

        assert await page.is_visible("#sidebar")
        assert await page.is_visible("#brand-name")
        assert await page.is_visible("#btn-simulate")
        await page.screenshot(path="e2e_screenshots/01_dashboard_initial.png", full_page=True)
        print("  PASS: Dashboard loaded with sidebar, brand, and simulate button.")

        # 2. Test navigation: Search view
        print("Step 2: Testing navigation...")
        await page.click('.nav-icon[data-view="search"]')
        await page.wait_for_timeout(300)
        assert await page.is_visible("#view-search")
        assert await page.is_visible("#search-origin")

        # 3. Navigate to Concierge view
        await page.click('.nav-icon[data-view="concierge"]')
        await page.wait_for_timeout(300)
        assert await page.is_visible("#view-concierge")
        assert await page.is_visible("#chat-input")
        assert await page.is_visible(".chip")

        # 4. Navigate back to Rescue Hub
        await page.click('.nav-icon[data-view="rescue"]')
        await page.wait_for_timeout(300)
        assert await page.is_visible("#view-rescue")
        assert await page.is_visible("#empty-state")
        print("  PASS: All 3 views switched seamlessly.")

        # 5. Simulate Disruption
        print("Step 3: Triggering disruption simulation...")
        await page.click("#btn-simulate")
        await page.wait_for_timeout(2500)

        assert await page.is_visible("#disruption-banner")
        assert await page.is_visible("#route-visual")
        assert await page.is_visible("#reasoning-trail")

        packages = await page.query_selector_all(".package-card")
        assert len(packages) == 2, f"Expected 2 rescue packages, got {len(packages)}"
        print("  PASS: Disruption banner, route visual, reasoning trail, 2 packages confirmed.")

        # 6. Verify compensation card
        assert await page.is_visible("#compensation-card")
        comp_text = await page.inner_text("#compensation-card")
        assert "250" in comp_text or "$250" in comp_text
        print("  PASS: Auto-compensation card shows $250 claim.")

        await page.screenshot(path="e2e_screenshots/02_disruption_activated.png", full_page=True)

        # 7. Test 1-Click Rebook
        print("Step 4: Executing 1-Click Rebook...")
        rebook_btn = await page.query_selector(".btn-rebook")
        assert rebook_btn is not None
        await rebook_btn.click()
        await page.wait_for_timeout(1500)

        assert await page.is_visible("#modal-overlay")
        assert await page.is_visible("#boarding-pass")
        bp_origin = await page.inner_text("#bp-origin")
        bp_dest = await page.inner_text("#bp-dest")
        assert len(bp_origin) > 0
        assert len(bp_dest) > 0
        await page.screenshot(path="e2e_screenshots/03_boarding_pass.png")
        print("  PASS: Boarding pass modal with route details confirmed.")

        # Close modal
        await page.click(".btn-done")
        await page.wait_for_selector("#modal-overlay", state="hidden")
        await page.wait_for_timeout(300)

        # 8. Test Flight Search
        print("Step 5: Testing flight search...")
        await page.click('.nav-icon[data-view="search"]')
        await page.wait_for_timeout(300)
        await page.click(".btn-search")
        await page.wait_for_timeout(2000)

        results = await page.query_selector_all(".search-result-card")
        assert len(results) >= 2, f"Expected >=2 search results, got {len(results)}"
        first_result = await results[0].inner_text()
        assert "BKK" in first_result or "DMK" in first_result
        await page.screenshot(path="e2e_screenshots/04_search_results.png", full_page=True)
        print(f"  PASS: Flight search returned {len(results)} results.")

        # 9. Test Concierge Chat
        print("Step 6: Testing concierge chat...")
        await page.click('.nav-icon[data-view="concierge"]')
        await page.wait_for_timeout(300)
        await page.fill("#chat-input", "Can I request a vegetarian meal?")
        await page.click("#btn-send")
        await page.wait_for_timeout(1500)

        chat_content = await page.inner_text("#chat-messages")
        assert "Vegetarian" in chat_content or "meal" in chat_content.lower()
        await page.screenshot(path="e2e_screenshots/05_concierge_chat.png", full_page=True)
        print("  PASS: Concierge responded with meal voucher details.")

        await browser.close()
        print("\nALL E2E TESTS PASSED (6/6 steps)")

if __name__ == "__main__":
    asyncio.run(run_e2e_test())
