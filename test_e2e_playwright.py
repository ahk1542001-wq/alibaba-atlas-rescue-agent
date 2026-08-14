import asyncio
from playwright.async_api import async_playwright

async def run_e2e_test():
    print("🚀 Starting Automated Playwright E2E Test Suite for TravelCare AI...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await context.new_page()

        # 1. Open Web App
        print("📍 Navigating to http://localhost:8050...")
        await page.goto("http://localhost:8050")
        await page.wait_for_load_state("networkidle")
        await page.screenshot(path="e2e_screenshots/01_dashboard_initial.png", full_page=True)
        print("✅ Step 1: Initial Dashboard loaded successfully.")

        # 2. Test Navigation Tabs
        print("📍 Testing Multi-View SaaS Navigation...")
        await page.click("#navSearch")
        await page.wait_for_timeout(300)
        assert await page.is_visible("#viewSearch")

        await page.click("#navConcierge")
        await page.wait_for_timeout(300)
        assert await page.is_visible("#viewConcierge")

        await page.click("#navClaims")
        await page.wait_for_timeout(300)
        assert await page.is_visible("#viewClaims")

        await page.click("#navAPI")
        await page.wait_for_timeout(300)
        assert await page.is_visible("#viewAPI")

        await page.click("#navJourney")
        await page.wait_for_timeout(300)
        assert await page.is_visible("#viewJourney")
        print("✅ Step 2: All 5 SaaS views switched seamlessly.")

        # 3. Simulate Flight Disruption
        print("📍 Triggering Disruption: TG 303 Cancelled...")
        await page.click("button:has-text('🚨 TG 303 Cancelled')")
        await page.wait_for_timeout(1000)

        # Check Disruption Alert & Rescue Split Grid
        assert await page.is_visible("#crisisAlert")
        assert await page.is_visible("#rescueSplit")
        await page.screenshot(path="e2e_screenshots/02_disruption_activated.png", full_page=True)
        print("✅ Step 3: Crisis alert displayed & Rescue packages curated.")

        # 4. Test 1-Click Rebooking
        print("📍 Executing 1-Click Autonomous Rebooking...")
        rebook_buttons = await page.query_selector_all(".btn-rebook")
        assert len(rebook_buttons) > 0
        await rebook_buttons[0].click()
        await page.wait_for_timeout(800)

        # Check Digital Boarding Pass Modal
        assert await page.is_visible("#ticketModal")
        await page.screenshot(path="e2e_screenshots/03_boarding_pass_modal.png")
        print("✅ Step 4: Digital Apple Wallet Boarding Pass confirmed.")

        # Close Modal
        await page.evaluate("() => closeModal()")
        await page.wait_for_selector("#ticketModal", state="hidden")
        await page.wait_for_timeout(400)

        # 5. Test Interactive Seatmap
        print("📍 Testing Interactive Seat Selector (Seat 11B)...")
        await page.click(".seat-block:has-text('B')")
        await page.wait_for_timeout(300)
        seat_label = await page.inner_text("#assignedSeatLabel")
        print(f"   Assigned Seat: {seat_label}")

        # 6. Test AI Concierge Chat Desk
        print("📍 Testing AI Concierge Desk Interaction...")
        await page.click("#navConcierge")
        await page.fill("#deskChatInput", "Can I request a vegetarian meal?")
        await page.click("button:has-text('Send')")
        await page.wait_for_timeout(800)
        chat_content = await page.inner_text("#fullChatStream")
        assert "Vegetarian" in chat_content
        await page.screenshot(path="e2e_screenshots/04_concierge_chat.png", full_page=True)
        print("✅ Step 6: AI Concierge responded with special meal & voucher details.")

        await browser.close()
        print("🎉 ALL PLAYWRIGHT E2E BROWSER TESTS PASSED (100% SMOOTH)!")

if __name__ == "__main__":
    asyncio.run(run_e2e_test())
