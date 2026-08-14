import asyncio
from playwright.async_api import async_playwright

async def run_e2e_test():
    print("🚀 Starting Automated Playwright E2E Test Suite for TravelCare AI...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await context.new_page()

        # 1. Open Web App & Verify Dynamic Island & Predictive Radar
        print("📍 Navigating to http://localhost:8050...")
        await page.goto("http://localhost:8050")
        await page.wait_for_load_state("networkidle")
        
        assert await page.is_visible("#topDynamicIsland")
        assert await page.is_visible("#radarCard")
        await page.screenshot(path="e2e_screenshots/01_dashboard_initial.png", full_page=True)
        print("✅ Step 1: Initial Dashboard & AI Predictive Radar loaded.")

        # 2. Test Multi-View Navigation
        print("📍 Testing Multi-View SaaS Navigation...")
        await page.click("#navSearch")
        await page.wait_for_timeout(300)
        assert await page.is_visible("#viewSearch")

        await page.click("#navConcierge")
        await page.wait_for_timeout(300)
        assert await page.is_visible("#viewConcierge")
        assert await page.is_visible("#audioWaveCanvas")

        await page.click("#navClaims")
        await page.wait_for_timeout(300)
        assert await page.is_visible("#viewClaims")

        await page.click("#navTelemetry")
        await page.wait_for_timeout(300)
        assert await page.is_visible("#viewTelemetry")
        assert await page.is_visible("#dagFlowGrid")

        await page.click("#navJourney")
        await page.wait_for_timeout(300)
        assert await page.is_visible("#viewJourney")
        print("✅ Step 2: All 5 SaaS views switched seamlessly.")

        # 3. Simulate Flight Disruption & Verify Visual Diff
        print("📍 Triggering Disruption Simulation...")
        await page.click("#btnSimulateDisruption")
        await page.wait_for_timeout(600)

        assert await page.is_visible("#crisisAlertBanner")
        assert await page.is_visible("#flightDiffCard")
        await page.screenshot(path="e2e_screenshots/02_disruption_activated.png", full_page=True)
        print("✅ Step 3: Crisis alert & Visual Flight Rescue Diff confirmed.")

        # 4. Test 1-Click Rebooking & Apple Wallet PKPass Modal
        print("📍 Executing 1-Click Autonomous Rebooking...")
        rebook_buttons = await page.query_selector_all(".btn-rebook")
        assert len(rebook_buttons) > 0
        await rebook_buttons[0].click()
        await page.wait_for_timeout(600)

        assert await page.is_visible("#ticketModal")
        await page.screenshot(path="e2e_screenshots/03_boarding_pass_modal.png")
        print("✅ Step 4: Photorealistic Apple Wallet PKPass Boarding Pass confirmed.")

        # Close Modal
        await page.evaluate("() => closeModal()")
        await page.wait_for_selector("#ticketModal", state="hidden")
        await page.wait_for_timeout(300)

        # 5. Test Interactive Seatmap (Select 11B)
        print("📍 Testing Interactive Seat Selector (Seat 11B)...")
        await page.click(".seat-block:has-text('B')")
        await page.wait_for_timeout(300)
        seat_label = await page.inner_text("#assignedSeatLabel")
        assert "11B" in seat_label
        print(f"   Assigned Seat: {seat_label}")

        # 6. Test AI Concierge Desk Interaction
        print("📍 Testing AI Concierge Desk Interaction...")
        await page.click("#navConcierge")
        await page.fill("#deskChatInput", "Can I request a vegetarian meal?")
        await page.click("button:has-text('Send')")
        await page.wait_for_timeout(800)
        chat_content = await page.inner_text("#fullChatStream")
        assert "Vegetarian" in chat_content
        await page.screenshot(path="e2e_screenshots/04_concierge_chat.png", full_page=True)
        print("✅ Step 6: AI Concierge responded with special meal voucher details.")

        # 7. Test Self-Healing Loop Fault Injection
        print("📍 Testing Self-Healing Loop Fault Injection in Browser...")
        await page.click("#navJourney")
        await page.click("#btnSelfHealLoop")
        await page.wait_for_timeout(800)
        assert await page.is_visible("#ticketModal")
        diff_flight = await page.inner_text("#diffRescueFlight")
        assert "TG 307" in diff_flight or "Self-Healed" in diff_flight
        await page.screenshot(path="e2e_screenshots/05_self_healing_modal.png")
        await page.evaluate("() => closeModal()")
        print("✅ Step 7: Self-Healing Loop Fault Injection successfully tested and verified.")

        await browser.close()
        print("🎉 ALL PLAYWRIGHT E2E BROWSER TESTS PASSED (100% ZERO DEFECTS)!")

if __name__ == "__main__":
    asyncio.run(run_e2e_test())
