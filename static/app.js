        let fareLockInterval = null;
        let rescueData = null;

        // MULTI-CURRENCY
        const CURRENCY_RATES = { USD: 1.0, THB: 35.4, SGD: 1.34, MMK: 3500.0, EUR: 0.92 };
        const CURRENCY_SYMBOLS = { USD: "$", THB: "\u0E3F", SGD: "S$", MMK: "Ks ", EUR: "\u20AC" };
        let selectedCurrency = "USD";

        function convertCurrency(usdAmount) {
            const rate = CURRENCY_RATES[selectedCurrency] || 1.0;
            const symbol = CURRENCY_SYMBOLS[selectedCurrency] || "$";
            const converted = (usdAmount * rate).toFixed(2);
            return symbol + converted;
        }

        function updateCurrencyBadge() {
            const badge = document.getElementById('currency-badge');
            if (badge) badge.textContent = selectedCurrency;
        }

        // TOAST NOTIFICATION
        let toastTimer = null;
        function showToast(message) {
            const toast = document.getElementById('toast');
            toast.textContent = message;
            toast.classList.add('visible');
            if (toastTimer) clearTimeout(toastTimer);
            toastTimer = setTimeout(function() { toast.classList.remove('visible'); }, 4000);
        }

        // VIEW SWITCHING
        function switchView(view, el) {
            document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
            document.querySelectorAll('.nav-icon').forEach(n => n.classList.remove('active'));
            document.querySelectorAll('.bottom-nav-item').forEach(n => n.classList.remove('active'));
            document.getElementById('view-' + view).classList.add('active');
            if (el) {
                el.classList.add('active');
                // Sync the other nav (sidebar <-> bottom nav)
                const viewName = el.getAttribute('data-view');
                document.querySelectorAll('[data-view="' + viewName + '"]').forEach(n => n.classList.add('active'));
            }
        }

        // STORE MONITORED FLIGHTS
        let monitoredFlights = [];

        // ADD FLIGHT MODAL
        function openAddFlightModal() {
            document.getElementById('add-flight-overlay').classList.add('visible');
            document.getElementById('input-flight-number').focus();
        }

        function closeAddFlightModal() {
            document.getElementById('add-flight-overlay').classList.remove('visible');
        }

        function submitAddFlight() {
            const flightNum = document.getElementById('input-flight-number').value.trim().toUpperCase();
            const flightDate = document.getElementById('input-flight-date').value;
            const passenger = document.getElementById('input-passenger-name').value.trim();
            if (!flightNum) return;

            monitoredFlights.push({ flight_number: flightNum, date: flightDate, passenger_name: passenger });
            const currencySelect = document.getElementById('input-currency');
            if (currencySelect) {
                selectedCurrency = currencySelect.value;
                updateCurrencyBadge();
            }
            renderMonitoredFlights();
            closeAddFlightModal();

            // Clear for next time
            document.getElementById('input-flight-number').value = '';
        }

        function renderMonitoredFlights() {
            const container = document.getElementById('monitored-flights');
            if (monitoredFlights.length === 0) { container.innerHTML = ''; return; }
            container.innerHTML = monitoredFlights.map(f =>
                '<div class="monitored-flight-item">' +
                    '<div class="monitored-flight-info">' +
                        '<span class="monitored-flight-num">' + f.flight_number + '</span>' +
                        '<span class="monitored-flight-date">' + f.date + '</span>' +
                    '</div>' +
                    '<div class="monitored-status"><span class="monitored-dot"></span>Monitoring</div>' +
                '</div>'
            ).join('');
        }

        // SIMULATE DISRUPTION
        async function simulateDisruption() {
            // Use entered flight if available, otherwise use defaults
            const flightNum = (monitoredFlights.length > 0 ? monitoredFlights[0].flight_number : 'TG303');
            const passenger = (monitoredFlights.length > 0 ? monitoredFlights[0].passenger_name : 'Aung Hein Kyaw');
            const flightDate = (monitoredFlights.length > 0 ? monitoredFlights[0].date : '2026-08-20');
            const currency = document.getElementById('input-currency') ? document.getElementById('input-currency').value : 'USD';
            selectedCurrency = currency;
            updateCurrencyBadge();

            const btn = document.getElementById('btn-simulate');
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner"></span>Activating...';

            document.getElementById('empty-state').style.display = 'none';

            // Show banner immediately
            const banner = document.getElementById('disruption-banner');
            document.getElementById('banner-title').textContent = flightNum + ' CANCELLED \u2014 Autonomous Rescue Active';
            document.getElementById('banner-sub').textContent = 'Scanning 140+ airlines via Atlas GDS...';
            banner.classList.add('visible');

            // Show reasoning trail with sequential steps
            const trail = document.getElementById('reasoning-trail');
            trail.classList.add('visible');
            const trailList = document.getElementById('trail-list');
            trailList.innerHTML = '';

            const steps = [
                { label: 'Detected ' + flightNum + ' cancellation via Atlas GDS', time: 'just now', delay: 300 },
                { label: 'Searched 140+ airlines across Atlas Sandbox', time: '0.8s', delay: 600 },
                { label: 'Qwen-2.5 via Qoder: multi-criteria ranking (time + price + coverage)', time: '0.3s', delay: 900 },
                { label: 'Fare locked on 2 alternatives \u2014 awaiting selection', time: 'active', delay: 1200, active: true }
            ];

            for (const step of steps) {
                await new Promise(r => setTimeout(r, step.delay));
                const li = document.createElement('li');
                li.className = 'trail-item ' + (step.active ? 'active' : 'done');
                li.innerHTML = '<div class="trail-dot"></div><div class="trail-text"><span class="step-label">' +
                    step.label + '</span><span class="step-time">' + step.time + '</span></div>';
                trailList.appendChild(li);
            }

            // Call the API
            try {
                const res = await fetch('/api/disruption/analyze', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        flight_number: flightNum,
                        passenger_name: passenger,
                        date: flightDate,
                        currency: currency
                    })
                });
                rescueData = await res.json();
                renderRescueData(rescueData);

                // Update reasoning trail: mark last step done + add final step
                const trailItems = document.querySelectorAll('#trail-list .trail-item');
                if (trailItems.length > 0) {
                    const lastItem = trailItems[trailItems.length - 1];
                    lastItem.classList.remove('active');
                    lastItem.classList.add('done');
                    lastItem.querySelector('.step-time').textContent = 'done';
                }
                // Add final reasoning step with actual API data
                const pkgCount = rescueData.rescue_packages.length;
                const firstPkg = rescueData.rescue_packages[0];
                const compAmt = rescueData.compensation_claim.eligible_payout_usd.toFixed(0);
                const finalLi = document.createElement('li');
                finalLi.className = 'trail-item done';
                finalLi.innerHTML = '<div class="trail-dot"></div><div class="trail-text"><span class="step-label">Recommended ' + firstPkg.airline + ' ' + firstPkg.flight_number + ' \u2014 $' + compAmt + ' compensation auto-filed</span><span class="step-time">done</span></div>';
                trailList.appendChild(finalLi);
            } catch (err) {
                console.error('Disruption analysis failed:', err);
                document.getElementById('banner-sub').textContent = 'Unable to analyze disruption. Please try again.';
                showToast('Unable to analyze disruption. Please check your connection and try again.');
            }

            btn.disabled = false;
            btn.innerHTML = 'Simulate Disruption';
        }

        function renderRescueData(data) {
            // Update banner sub
            document.getElementById('banner-sub').textContent = '2 rescue packages ready — Qwen-2.5 ranking complete';

            // Route visual
            const disruption = data.disruption;
            const route = document.getElementById('route-visual');
            document.getElementById('route-cancelled-codes').textContent = disruption.origin;
            document.getElementById('route-cancelled-dest').textContent = disruption.destination;

            const firstPkg = data.rescue_packages[0];
            document.getElementById('route-rescue-codes').textContent = firstPkg.origin;
            document.getElementById('route-rescue-dest').textContent = firstPkg.destination;
            route.classList.add('visible');

            // Rescue packages (show only first 2)
            renderPackages(data.rescue_packages.slice(0, 2));

            // Compensation card
            const claim = data.compensation_claim;
            document.getElementById('comp-claim-id').textContent = 'Claim #' + claim.claim_id + ' • $' + claim.eligible_payout_usd.toFixed(2) + ' USD';
            document.getElementById('comp-amount').textContent = convertCurrency(claim.eligible_payout_usd);
            document.getElementById('comp-status').textContent = 'Status: ' + claim.status.replace(/_/g, ' ');
            document.getElementById('compensation-card').classList.add('visible');
            document.getElementById('compensation-card').classList.add('fade-in-up');

            // Start fare lock countdown
            startFareLockCountdown();
        }

        function renderPackages(packages) {
            const container = document.getElementById('rescue-packages');
            container.innerHTML = '';

            packages.forEach((pkg, idx) => {
                const isFastest = pkg.package_type === 'FASTEST_RECOVERY';
                const card = document.createElement('div');
                card.className = 'package-card';

                const depTime = pkg.departure_time.split(' ')[1] || pkg.departure_time;
                const arrTime = pkg.arrival_time.split(' ')[1] || pkg.arrival_time;
                const priceDisplay = pkg.currency_symbol + (pkg.price_converted || pkg.price_usd).toFixed(2);
                const coverageText = isFastest ? 'Airline-covered' : 'Instant payout';

                card.innerHTML =
                    '<div class="package-badge">' + (isFastest ? 'FASTEST' : 'BEST VALUE') + '</div>' +
                    '<div class="package-body">' +
                        '<div class="package-airline">' + pkg.airline + '</div>' +
                        '<div class="package-flight">' + pkg.flight_number + '</div>' +
                        '<div class="package-route">' +
                            '<span class="codes">' + pkg.origin + '</span>' +
                            '<span class="arrow">--></span>' +
                            '<span class="codes">' + pkg.destination + '</span>' +
                        '</div>' +
                        '<div class="package-time">' + depTime + ' --> ' + arrTime + ' - Nonstop</div>' +
                        '<div class="package-reason">' + pkg.agent_recommendation_reason + '</div>' +
                        (isFastest ?
                            '<div class="package-farelock"><div class="package-farelock-label">Fare Lock</div>' +
                            '<div class="farelock-ring">' +
                                '<svg width="80" height="80">' +
                                    '<circle cx="40" cy="40" r="34" fill="none" stroke="var(--border-amber)" stroke-width="4"/>' +
                                    '<circle class="farelock-progress" cx="40" cy="40" r="34" fill="none" stroke="var(--accent-teal)" stroke-width="4" stroke-dasharray="213.6" stroke-dashoffset="0" stroke-linecap="round" style="transition: stroke-dashoffset 1s linear, stroke 0.5s"/>' +
                                '</svg>' +
                                '<div class="farelock-ring-text" data-pkg="' + idx + '">14:59</div>' +
                            '</div></div>' : '') +
                        '<div class="package-price">' + priceDisplay + '</div>' +
                        '<div class="package-coverage">' + coverageText + '</div>' +
                        '<button class="btn-rebook" onclick="rebookFlight(\'' + pkg.offer_id + '\', ' + idx + ')">1-Click Rebook</button>' +
                    '</div>';
                container.appendChild(card);
                setTimeout(() => card.classList.add('fade-in-up'), idx * 200);
            });
        }

        function startFareLockCountdown() {
            if (fareLockInterval) clearInterval(fareLockInterval);
            let seconds = 899;
            const total = 899;
            const circumference = 2 * Math.PI * 34;

            fareLockInterval = setInterval(() => {
                seconds--;
                if (seconds < 0) { clearInterval(fareLockInterval); return; }

                const m = Math.floor(seconds / 60);
                const s = seconds % 60;
                const display = String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');

                document.querySelectorAll('.farelock-ring-text').forEach(el => el.textContent = display);

                const progress = seconds / total;
                const offset = circumference * (1 - progress);
                document.querySelectorAll('.farelock-progress').forEach(ring => {
                    ring.style.strokeDashoffset = offset;
                    if (seconds > 600) ring.style.stroke = 'var(--accent-teal)';
                    else if (seconds > 300) ring.style.stroke = 'var(--status-warning)';
                    else ring.style.stroke = 'var(--status-danger)';
                });
            }, 1000);
        }

        // 1-CLICK REBOOK
        async function rebookFlight(offerId, pkgIdx) {
            if (!rescueData) return;
            const pkg = rescueData.rescue_packages[pkgIdx];
            await showRescueTimeline(pkg);
        }

        // RESCUE TIMELINE ANIMATION
        async function showRescueTimeline(pkg) {
            const overlay = document.getElementById('rescue-timeline-overlay');
            const stepsList = document.getElementById('timeline-steps');
            stepsList.innerHTML = '';
            overlay.classList.add('visible');

            const steps = [
                { label: 'Verifying fare lock via Atlas GDS', sub: pkg.airline + ' ' + pkg.flight_number + ' \u2014 $' + pkg.price_usd.toFixed(2) },
                { label: 'Qwen-2.5 via Qoder selects seat 12A', sub: 'Window seat \u2014 30kg priority baggage' },
                { label: 'Transferring baggage to rescue flight', sub: 'Auto-routed to Cargo Bay 2' },
                { label: 'Issuing e-ticket via Atlas Sandbox', sub: 'PNR generation \u2014 instant settlement' },
                { label: 'Filing $250 compensation claim', sub: 'EU261 passenger rights auto-applied' }
            ];

            for (let i = 0; i < steps.length; i++) {
                const step = steps[i];
                const li = document.createElement('li');
                li.className = 'timeline-step';
                li.id = 'tl-step-' + i;
                li.innerHTML = '<div class="step-check empty"></div><div class="step-text"><div class="step-label">' +
                    step.label + '</div><div style="font-size:12px;color:var(--text-muted)">' + step.sub + '</div></div>';
                stepsList.appendChild(li);

                await new Promise(r => setTimeout(r, 50));
                li.classList.add('shown', 'timeline-step-active');
                li.querySelector('.step-check').classList.remove('empty');
                li.querySelector('.step-check').textContent = '...';

                await new Promise(r => setTimeout(r, 700));
                li.classList.remove('timeline-step-active');
                li.classList.add('timeline-step-done');
                li.querySelector('.step-check').textContent = '';
                li.querySelector('.step-check').innerHTML = '&#10003;';
            }

            await new Promise(r => setTimeout(r, 400));
            overlay.classList.remove('visible');

            // Now call the actual booking API and show boarding pass
            try {
                const res = await fetch('/api/rescue/book', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        offer_id: pkg.offer_id,
                        passenger_name: (monitoredFlights.length > 0 ? monitoredFlights[0].passenger_name : 'Aung Hein Kyaw'),
                        passport_number: 'MB987654',
                        price_usd: pkg.price_usd,
                        baggage_addon: '30kg Priority Included',
                        seat_selected: '12A'
                    })
                });
                const result = await res.json();
                if (result.success) {
                    showBoardingPass(result.ticket, pkg);
                    showImpactCard(pkg);
                }
            } catch (err) {
                console.error('Rebooking failed:', err);
                showToast('Booking failed. Please try rebooking again.');
            }
        }

        // IMPACT SUMMARY CARD
        function showImpactCard(pkg) {
            const card = document.getElementById('impact-card');
            document.getElementById('impact-time').textContent = '190 min';
            document.getElementById('impact-cost').textContent = convertCurrency(18.50);
            document.getElementById('impact-comp').textContent = convertCurrency(250.00);
            document.getElementById('impact-voucher').textContent = convertCurrency(25.00);
            document.getElementById('impact-total').textContent = convertCurrency(293.50);
            card.classList.add('visible');
        }

        function showBoardingPass(ticket, pkg) {
            const overlay = document.getElementById('modal-overlay');
            document.getElementById('bp-airline').textContent = pkg.airline;
            document.getElementById('bp-origin').textContent = pkg.origin;
            document.getElementById('bp-origin-name').textContent = pkg.origin_airport || pkg.origin;
            document.getElementById('bp-dest').textContent = pkg.destination;
            document.getElementById('bp-dest-name').textContent = pkg.destination_airport || pkg.destination;
            document.getElementById('bp-flight').textContent = pkg.flight_number;
            document.getElementById('bp-gate').textContent = ticket.gate || pkg.gate || 'D4';
            document.getElementById('bp-seat').textContent = ticket.seat_assigned || '12A';
            document.getElementById('bp-boarding').textContent = ticket.boarding_time || '11:05 AM';
            document.getElementById('bp-pnr').textContent = ticket.pnr || 'ATLAS-XXXXXX';

            const barcode = document.getElementById('bp-barcode');
            barcode.innerHTML = '';
            const pnr = ticket.pnr || 'ATLAS-XXXXXX';
            for (let i = 0; i < 50; i++) {
                const charCode = pnr.charCodeAt(i % pnr.length);
                const isThick = (charCode + i) % 3 === 0;
                const bar = document.createElement('div');
                bar.className = 'bp-bar';
                bar.style.width = isThick ? '4px' : '2px';
                bar.style.height = (24 + ((charCode + i) % 12)) + 'px';
                bar.style.opacity = (charCode + i) % 2 === 0 ? '1' : '0.4';
                barcode.appendChild(bar);
            }

            overlay.classList.add('visible');
        }

        function closeModal() {
            document.getElementById('modal-overlay').classList.remove('visible');
        }

        // COMPENSATION PAYOUT
        async function filePayout() {
            if (!rescueData) return;
            try {
                await fetch('/api/claims/generate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        flight_number: (monitoredFlights.length > 0 ? monitoredFlights[0].flight_number : 'TG303'),
                        passenger_name: (monitoredFlights.length > 0 ? monitoredFlights[0].passenger_name : 'Aung Hein Kyaw')
                    })
                });
                document.getElementById('comp-status').textContent = 'Status: PAYOUT_INITIATED';
                showToast('Compensation claim filed successfully.');
            } catch (err) {
                console.error('Claim filing failed:', err);
                document.getElementById('comp-status').textContent = 'Status: PAYOUT_FAILED';
                showToast('Unable to file compensation claim. Please try again.');
            }
        }

        // FLIGHT SEARCH
        async function searchFlights() {
            const results = document.getElementById('search-results');
            results.innerHTML = '<div class="skeleton-card"><div><div class="skeleton-line med"></div><div class="skeleton-line short"></div></div><div class="skeleton-line short" style="width:40px"></div></div><div class="skeleton-card"><div><div class="skeleton-line med"></div><div class="skeleton-line short"></div></div><div class="skeleton-line short" style="width:40px"></div></div><div class="skeleton-card"><div><div class="skeleton-line med"></div><div class="skeleton-line short"></div></div><div class="skeleton-line short" style="width:40px"></div></div>';

            try {
                const res = await fetch('/api/flights/search', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        origin: document.getElementById('search-origin').value,
                        destination: document.getElementById('search-destination').value,
                        date: document.getElementById('search-date').value,
                        passengers: parseInt(document.getElementById('search-passengers').value),
                        cabin_class: 'ECONOMY',
                        currency: document.getElementById('search-currency').value
                    })
                });
                const data = await res.json();
                renderSearchResults(data.offers);
            } catch (err) {
                results.innerHTML = '<div class="loading">Search failed. Please try again.</div>';
                console.error('Search failed:', err);
            }
        }

        function renderSearchResults(offers) {
            const container = document.getElementById('search-results');
            container.innerHTML = '';

            if (!offers || offers.length === 0) {
                container.innerHTML = '<div class="loading">No flights found.</div>';
                return;
            }

            offers.forEach(o => {
                const depTime = o.departure_time.split(' ')[1] || o.departure_time;
                const arrTime = o.arrival_time.split(' ')[1] || o.arrival_time;
                const price = (o.currency_symbol || '$') + (o.price_converted || o.price_usd).toFixed(2);

                const card = document.createElement('div');
                card.className = 'search-result-card';
                card.innerHTML =
                    '<div class="src-left">' +
                        '<div class="src-airline">' + o.airline + '</div>' +
                        '<div class="src-flight">' + o.flight_number + '</div>' +
                        '<div class="src-route">' + o.origin + ' --> ' + o.destination + ' - ' + depTime + ' to ' + arrTime + '</div>' +
                    '</div>' +
                    '<div class="src-right">' +
                        '<div class="src-price">' + price + '</div>' +
                        '<div class="src-seats">' + o.seats_available + ' seats left</div>' +
                    '</div>';
                container.appendChild(card);
            });
        }

        // CONCIERGE CHAT
        async function sendChat() {
            const input = document.getElementById('chat-input');
            const msg = input.value.trim();
            if (!msg) return;
            input.value = '';
            await sendConciergeQuery(msg);
        }

        async function sendQuickChat(msg) {
            await sendConciergeQuery(msg);
        }

        async function sendConciergeQuery(query) {
            const container = document.getElementById('chat-messages');
            const now = new Date();
            const timeStr = now.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });

            // User message with timestamp
            const userRow = document.createElement('div');
            userRow.className = 'msg-content';
            userRow.style.alignSelf = 'flex-end';

            const userBubble = document.createElement('div');
            userBubble.className = 'msg-bubble msg-user';
            userBubble.textContent = query;

            const userTime = document.createElement('div');
            userTime.className = 'msg-time';
            userTime.style.textAlign = 'right';
            userTime.textContent = timeStr;

            userRow.appendChild(userBubble);
            userRow.appendChild(userTime);
            container.appendChild(userRow);

            // AI typing indicator with avatar
            const aiRow = document.createElement('div');
            aiRow.className = 'msg-row msg-ai-row';
            aiRow.innerHTML = '<div class="msg-avatar"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v1a3 3 0 0 1-3 3 3 3 0 0 1-3-3V5a3 3 0 0 1 3-3z"/><path d="M12 14c-4 0-7 2-7 5v3h14v-3c0-3-3-5-7-5z"/></svg></div><div class="msg-content"><div class="msg-bubble msg-ai"><div class="typing-dots"><div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div></div></div></div>';
            container.appendChild(aiRow);
            container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });

            try {
                const res = await fetch('/api/chat/concierge', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ query: query })
                });
                const data = await res.json();
                const replyTime = new Date().toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
                aiRow.querySelector('.msg-bubble').textContent = data.reply;
                var timeDiv = document.createElement('div');
                timeDiv.className = 'msg-time';
                timeDiv.textContent = replyTime;
                aiRow.querySelector('.msg-content').appendChild(timeDiv);
            } catch (err) {
                aiRow.querySelector('.msg-bubble').textContent = 'Sorry, I could not process your request right now.';
                console.error('Concierge failed:', err);
            }
            container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
        }

        // HEALTH CHECK
        async function checkHealth() {
            try {
                const res = await fetch('/api/health');
                const data = await res.json();
                document.querySelector('#health-badge').innerHTML = '<span id="health-dot"></span>' + data.status;
            } catch (err) {
                document.querySelector('#health-badge').innerHTML = '<span id="health-dot" style="background:#DC2626"></span>Offline';
            }
        }

        // INIT
        checkHealth();
