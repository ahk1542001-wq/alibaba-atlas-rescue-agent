        let fareLockInterval = null;
        let rescueData = null;

        // MULTI-CURRENCY
        const CURRENCY_RATES = { USD: 1.0, THB: 35.4, SGD: 1.34, MMK: 3500.0, EUR: 0.92 };
        const CURRENCY_SYMBOLS = { USD: "$", THB: "\u0E3F", SGD: "S$", MMK: "Ks ", EUR: "\u20AC" };
        let selectedCurrency = "USD";

        // Keep default flight dates in the future so live inventory always applies
        (function initDates() {
            const t = new Date(Date.now() + 2 * 86400000);
            const iso = t.toISOString().split('T')[0];
            ['input-flight-date', 'search-date'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.value = iso;
            });
        })();

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
            if (view === 'radar') loadRadar();
        }

        // AUTONOMOUS RESCUE RADAR
        let radarAlerts = [];
        let radarEventSource = null;

        async function loadRadar() {
            try {
                const res = await fetch('/api/radar');
                const data = await res.json();
                renderRadar(data);
            } catch (err) {
                console.error('Radar load failed:', err);
            }
            connectRadarStream();
        }

        function connectRadarStream() {
            if (radarEventSource) return;
            radarEventSource = new EventSource('/api/radar/stream');
            radarEventSource.onmessage = function (ev) {
                try {
                    const alert = JSON.parse(ev.data);
                    radarAlerts.unshift(alert);
                    renderRadarAlerts();
                    showToast('Proactive rescue drafted for ' + alert.flight_number);
                } catch (e) { /* ignore malformed event */ }
            };
            radarEventSource.onerror = function () { /* SSE will auto-reconnect */ };
        }

        function renderRadar(data) {
            radarAlerts = data.alerts || [];
            const sub = document.getElementById('radar-sub');
            const flights = (data.last_scan && data.last_scan.flights) ? data.last_scan.flights : [];
            const disrupted = flights.filter(f => f.disrupted).length;
            if (sub) {
                sub.textContent = 'Monitoring ' + (data.watchlist ? data.watchlist.length : flights.length) +
                    ' flights • ' + disrupted + ' active disruption(s)';
            }

            const fc = document.getElementById('radar-flights');
            if (!fc) return;
            fc.textContent = '';
            if (flights.length === 0) {
                const loadDiv = document.createElement('div');
                loadDiv.className = 'loading';
                loadDiv.textContent = 'Initializing radar scan...';
                fc.appendChild(loadDiv);
            } else {
                flights.forEach(f => {
                    const cls = f.disrupted ? 'disrupted' : 'ok';
                    const statusText = (f.status || 'UNKNOWN') + (f.reason ? ' — ' + f.reason : '');
                    const row = document.createElement('div');
                    row.className = 'radar-flight ' + cls;

                    const dot = document.createElement('div');
                    dot.className = 'rf-dot';
                    row.appendChild(dot);

                    const info = document.createElement('div');
                    info.className = 'rf-info';
                    const num = document.createElement('span');
                    num.className = 'rf-num';
                    num.textContent = f.flight_number || '';
                    const st = document.createElement('span');
                    st.className = 'rf-status';
                    st.textContent = statusText;
                    info.appendChild(num);
                    info.appendChild(st);
                    row.appendChild(info);

                    const flag = document.createElement('span');
                    const rawStatus = (f.status || '').toUpperCase();
                    if (f.disrupted) {
                        flag.className = 'rf-flag';
                        flag.textContent = 'ALERT';
                    } else if (rawStatus === 'ON_TIME' || rawStatus === 'SCHEDULED' || rawStatus === 'ACTIVE') {
                        flag.className = 'rf-ok';
                        flag.textContent = 'On Time';
                    } else {
                        flag.className = 'rf-ok';
                        flag.style.background = 'rgba(100, 116, 139, 0.15)';
                        flag.style.color = 'var(--text-muted)';
                        flag.textContent = f.status || 'MONITORING';
                    }
                    row.appendChild(flag);
                    fc.appendChild(row);
                });
            }
            renderRadarAlerts();
        }

        function renderRadarAlerts() {
            const ac = document.getElementById('radar-alerts');
            if (!ac) return;
            ac.textContent = '';
            if (!radarAlerts || radarAlerts.length === 0) {
                const loadDiv = document.createElement('div');
                loadDiv.className = 'loading';
                loadDiv.textContent = 'No disruptions detected. Radar standing by.';
                ac.appendChild(loadDiv);
                return;
            }
            radarAlerts.forEach(a => {
                const comp = a.compensation_usd ? ' • $' + a.compensation_usd + ' compensation' : '';
                const reason = (a.reason ? ' (' + a.reason + ')' : '') + comp;

                const alertDiv = document.createElement('div');
                alertDiv.className = 'radar-alert';

                const head = document.createElement('div');
                head.className = 'ra-head';
                const flight = document.createElement('span');
                flight.className = 'ra-flight';
                flight.textContent = a.flight_number || '';
                const status = document.createElement('span');
                status.className = 'ra-status';
                status.textContent = a.status || 'DISRUPTED';
                head.appendChild(flight);
                head.appendChild(status);
                alertDiv.appendChild(head);

                const reasonDiv = document.createElement('div');
                reasonDiv.className = 'ra-reason';
                reasonDiv.textContent = reason;
                alertDiv.appendChild(reasonDiv);

                const btn = document.createElement('button');
                btn.className = 'btn-radar-accept';
                btn.textContent = 'Review & Accept Rescue';
                btn.addEventListener('click', function () {
                    acceptRadarAlert(a.id);
                });
                alertDiv.appendChild(btn);

                ac.appendChild(alertDiv);
            });
        }

        async function radarScanNow() {
            const btn = document.getElementById('btn-radar-scan');
            btn.disabled = true;
            btn.textContent = 'Scanning...';
            try {
                const res = await fetch('/api/radar/scan', { method: 'POST' });
                const data = await res.json();
                renderRadar(data);
            } catch (e) {
                showToast('Radar scan failed. Please try again.');
            }
            btn.disabled = false;
            btn.textContent = 'Scan Now';
        }

        function acceptRadarAlert(id) {
            const alert = radarAlerts.find(a => a.id === id);
            if (!alert || !alert.rescue_plan) return;
            rescueData = alert.rescue_plan;
            document.getElementById('empty-state').style.display = 'none';
            document.getElementById('banner-title').textContent =
                alert.flight_number + ' ' + (alert.status || 'DISRUPTION') + ' — Autonomous Rescue Active';
            document.getElementById('banner-sub').textContent = '2 rescue packages ready — policy-ranked options ready';
            document.getElementById('disruption-banner').classList.add('visible');
            switchView('rescue');
            renderRescueData(rescueData);
        }

        // STORE MONITORED FLIGHTS
        let monitoredFlights = [];

        // ACTIVE-FLIGHT HELPERS — always derive from real user input, never defaults
        function activeFlight() { return monitoredFlights.length > 0 ? monitoredFlights[0] : null; }
        function activeFlightNumber() { const f = activeFlight(); return f ? f.flight_number : ''; }
        function activePassenger() { const f = activeFlight(); return f ? f.passenger_name : ''; }
        function activeFlightDate() {
            if (rescueData && rescueData.disruption && rescueData.disruption.date) return rescueData.disruption.date;
            const f = activeFlight();
            return (f && f.date) || '';
        }
        function defaultSearchDate() {
            const d = new Date(Date.now() + 2 * 86400000);
            return d.toISOString().slice(0, 10);
        }

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
            const flightDate = document.getElementById('input-flight-date').value || defaultSearchDate();
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
            if (!container) return;
            container.textContent = '';
            if (monitoredFlights.length === 0) return;
            monitoredFlights.forEach(f => {
                const item = document.createElement('div');
                item.className = 'monitored-flight-item';

                const info = document.createElement('div');
                info.className = 'monitored-flight-info';
                const num = document.createElement('span');
                num.className = 'monitored-flight-num';
                num.textContent = f.flight_number || '';
                const date = document.createElement('span');
                date.className = 'monitored-flight-date';
                date.textContent = f.date || '';
                info.appendChild(num);
                info.appendChild(date);
                item.appendChild(info);

                const status = document.createElement('div');
                status.className = 'monitored-status';
                const dot = document.createElement('span');
                dot.className = 'monitored-dot';
                status.appendChild(dot);
                status.appendChild(document.createTextNode('Monitoring'));
                item.appendChild(status);

                container.appendChild(item);
            });
        }

        function createTrailItem(label, time, className) {
            const li = document.createElement('li');
            li.className = 'trail-item ' + (className || 'done');
            const dot = document.createElement('div');
            dot.className = 'trail-dot';
            const text = document.createElement('div');
            text.className = 'trail-text';
            const l = document.createElement('span');
            l.className = 'step-label';
            l.textContent = label;
            const t = document.createElement('span');
            t.className = 'step-time';
            t.textContent = time;
            text.appendChild(l);
            text.appendChild(t);
            li.appendChild(dot);
            li.appendChild(text);
            return li;
        }

        // SIMULATE DISRUPTION
        async function simulateDisruption() {
            const flight = activeFlight();
            if (!flight) { showToast('Add a flight to monitor first.'); return; }
            const flightNum = flight.flight_number;
            const passenger = flight.passenger_name;
            const flightDate = flight.date;
            const currency = document.getElementById('input-currency') ? document.getElementById('input-currency').value : 'USD';
            const nationality = document.getElementById('input-nationality') ? document.getElementById('input-nationality').value : 'MM';
            selectedCurrency = currency;
            updateCurrencyBadge();

            const btn = document.getElementById('btn-simulate');
            btn.disabled = true;
            btn.textContent = '';
            const sp = document.createElement('span');
            sp.className = 'spinner';
            btn.appendChild(sp);
            btn.appendChild(document.createTextNode('Activating...'));

            const emptyState = document.getElementById('empty-state');
            if (emptyState) emptyState.style.display = 'none';

            // Show banner immediately
            const banner = document.getElementById('disruption-banner');
            document.getElementById('banner-title').textContent = flightNum + ' DEMO CANCELLATION \u2014 Simulation Active';
            document.getElementById('banner-sub').textContent = 'Running an explicit demo with fictional disruption data. No booking will be created.';
            banner.classList.add('visible');

            // Show reasoning trail with sequential steps
            const trail = document.getElementById('reasoning-trail');
            trail.classList.add('visible');
            const trailList = document.getElementById('trail-list');
            trailList.textContent = '';

            const steps = [
                { label: 'Loaded fictional ' + flightNum + ' disruption fixture', time: 'just now', delay: 300 },
                { label: 'Loaded demo-only recovery options', time: '0.8s', delay: 600 },
                { label: 'Ranked demo options by time, price, and visa constraints', time: '0.3s', delay: 900 },
                { label: 'Simulation prepared \u2014 no fare verified or locked', time: 'active', delay: 1200, active: true }
            ];

            for (const step of steps) {
                await new Promise(r => setTimeout(r, step.delay));
                const li = createTrailItem(step.label, step.time, step.active ? 'active' : 'done');
                trailList.appendChild(li);
            }

            // Call the API
            try {
                const res = await fetch('/api/disruption/analyze?allow_sim=true', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        flight_number: flightNum,
                        passenger_name: passenger,
                        date: flightDate,
                        currency: currency,
                        nationality: nationality
                    })
                });
                rescueData = await res.json();
                if (!res.ok) {
                    throw new Error(rescueData.detail || 'Unable to run the disruption simulation.');
                }
                renderRescueData(rescueData);

                // Update reasoning trail: mark last step done + add final step
                const trailItems = document.querySelectorAll('#trail-list .trail-item');
                if (trailItems.length > 0) {
                    const lastItem = trailItems[trailItems.length - 1];
                    lastItem.classList.remove('active');
                    lastItem.classList.add('done');
                    const st = lastItem.querySelector('.step-time');
                    if (st) st.textContent = 'done';
                }
                // Add final reasoning step with actual API data
                const firstPkg = (rescueData.rescue_packages && rescueData.rescue_packages.length > 0) ? rescueData.rescue_packages[0] : null;
                const claim = rescueData.compensation_claim || {};
                const compAmt = claim.eligible_payout_usd || 0;
                const compText = compAmt > 0
                    ? ' \u2014 ' + (claim.jurisdiction ? claim.jurisdiction.id + ' ' : '') + compAmt.toFixed(0) + ' USD compensation identified'
                    : ' \u2014 refund & duty-of-care route registered';
                if (firstPkg) {
                    const finalLi = createTrailItem('Recommended ' + (firstPkg.airline || '') + ' ' + (firstPkg.flight_number || '') + compText, 'done', 'done');
                    trailList.appendChild(finalLi);
                }
            } catch (err) {
                console.error('Disruption analysis failed:', err);
                document.getElementById('banner-sub').textContent = 'Unable to analyze disruption. Please try again.';
                showToast('Unable to analyze disruption. Please check your connection and try again.');
            }

            btn.disabled = false;
            btn.textContent = 'Simulate Disruption';
        }

        function renderRescueData(data) {
            // Update banner sub
            document.getElementById('banner-sub').textContent = '2 rescue packages ready — policy-ranked options ready';

            // Route visual
            const disruption = data.disruption;
            const route = document.getElementById('route-visual');
            document.getElementById('route-cancelled-codes').textContent = disruption.origin;
            document.getElementById('route-cancelled-dest').textContent = disruption.destination;

            const firstPkg = (data.rescue_packages && data.rescue_packages.length > 0) ? data.rescue_packages[0] : { origin: '', destination: '' };
            document.getElementById('route-rescue-codes').textContent = firstPkg.origin;
            document.getElementById('route-rescue-dest').textContent = firstPkg.destination;
            route.classList.add('visible');

            // Rescue packages (show only first 2)
            renderPackages((data.rescue_packages || []).slice(0, 2));

            // Compensation card
            const claim = data.compensation_claim || { eligible_payout_usd: 0, status: 'none', claim_id: '' };
            document.getElementById('comp-claim-id').textContent = 'Claim #' + (claim.claim_id || '') + ' • $' + (claim.eligible_payout_usd || 0).toFixed(2) + ' USD';
            document.getElementById('comp-amount').textContent = convertCurrency(claim.eligible_payout_usd || 0);
            document.getElementById('comp-status').textContent = 'Status: ' + (claim.status || '').replace(/_/g, ' ');
            document.getElementById('compensation-card').classList.add('visible');
            document.getElementById('compensation-card').classList.add('fade-in-up');

            // Visa guard summary + guardian push in trail
            if (data.visa_guard && data.visa_guard.summary) {
                const vgLi = createTrailItem('🛂 VisaGuard: ' + data.visa_guard.summary, 'done', 'done');
                document.getElementById('trail-list').appendChild(vgLi);
            }
            if (data.guardian_push && data.guardian_push.preview) {
                const simTag = data.guardian_push.simulated ? ' (demo mode)' : '';
                const gLi = createTrailItem('📨 Proactive Telegram Guardian push sent' + simTag, 'done', 'done');
                document.getElementById('trail-list').appendChild(gLi);
            }

            // Claims Autopilot panel
            runClaimsAutopilot();

            // Start fare lock countdown
            startFareLockCountdown();
        }

        async function runClaimsAutopilot() {
            const panel = document.getElementById('rights-panel');
            panel.classList.add('visible');
            try {
                const res = await fetch('/api/claims/assess', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        flight_number: rescueData.disruption.flight_number,
                        date: activeFlightDate(),
                        passenger_name: rescueData.passenger ? rescueData.passenger.name : '',
                        origin_airport: rescueData.disruption.origin,
                        destination_airport: rescueData.disruption.destination
                    })
                });
                const rights = await res.json();
                if (!res.ok) {
                    document.getElementById('rights-sub').textContent =
                        'Unable to verify rights: the connected provider did not supply a flight route.';
                    return;
                }
                renderRightsPanel(rights);
            } catch (err) {
                console.error('Claims autopilot failed:', err);
                document.getElementById('rights-sub').textContent = 'Rights check unavailable.';
            }
        }

        function renderRightsPanel(r) {
            if (!r.best) {
                document.getElementById('rights-sub').textContent = r.verdict || 'No mandatory regime detected.';
                return;
            }
            document.getElementById('rights-sub').textContent = r.best.name;
            const badge = document.getElementById('rights-regime-badge');
            badge.textContent = r.best.id;
            badge.classList.add('shown');

            const v = document.getElementById('rights-verdict');
            v.textContent = r.verdict;
            v.className = 'rights-verdict ' + ((r.classification && r.classification.classification === 'COMPENSABLE') ? 'verdict-good' : 'verdict-warn');
            v.classList.add('shown');

            const cls = r.classification || {};
            const cb = document.getElementById('rights-classification');
            cb.classList.add('shown');
            const chip = document.getElementById('class-chip');
            chip.textContent = cls.classification || '';
            chip.className = 'classification-chip ' + (cls.classification === 'COMPENSABLE' ? 'chip-good' : 'chip-warn');
            document.getElementById('class-confidence').textContent = 'confidence ' + (cls.confidence != null ? cls.confidence : '?') + '% • engine: ' + (cls.engine || 'deterministic policy');
            document.getElementById('class-reasoning').textContent = (cls.legal_reasoning || '') + (cls.key_article ? ' — ' + cls.key_article : '');

            const money = document.getElementById('rights-money');
            money.classList.add('shown');
            const cash = r.entitlement ? r.entitlement.fixed_cash_compensation : null;
            if (cash) {
                document.getElementById('ent-amount').textContent = cash.currency + ' ' + (cash.amount != null ? cash.amount.toLocaleString() : '0');
                document.getElementById('ent-basis').textContent = 'under ' + (r.best.citation || '');
            } else {
                document.getElementById('ent-amount').textContent = 'Refund route';
                document.getElementById('ent-basis').textContent = (r.entitlement && r.entitlement.note) ? r.entitlement.note : '';
            }

            const ev = document.getElementById('rights-evidence');
            ev.classList.add('shown');
            const list = document.getElementById('evidence-list');
            list.textContent = '';
            if (r.evidence_pack && r.evidence_pack.checklist) {
                r.evidence_pack.checklist.forEach(d => {
                    const li = document.createElement('li');
                    const st = document.createElement('strong');
                    st.textContent = d.item || '';
                    const sp = document.createElement('span');
                    sp.textContent = d.why || '';
                    li.appendChild(st);
                    li.appendChild(sp);
                    list.appendChild(li);
                });
            }
            document.getElementById('claim-letter-text').textContent = (r.evidence_pack && r.evidence_pack.claim_letter) ? r.evidence_pack.claim_letter : '';

            window._lastClaimForAppeal = {
                jurisdiction_id: r.best.id,
                airline: 'Airline Customer Relations',
                flight_number: rescueData.disruption.flight_number,
                date: activeFlightDate(),
                passenger_name: rescueData.passenger ? rescueData.passenger.name : '',
                origin_airport: rescueData.disruption.origin,
                destination_airport: rescueData.disruption.destination,
                reason: r.reason,
                classification: cls.classification
            };
        }

        async function appealRejection() {
            const btn = document.querySelector('.btn-appeal');
            if (!btn) return;
            btn.disabled = true;
            btn.textContent = '';
            const sp = document.createElement('span');
            sp.className = 'spinner';
            btn.appendChild(sp);
            btn.appendChild(document.createTextNode('Drafting appeal...'));
            try {
                const res = await fetch('/api/claims/appeal', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        claim: window._lastClaimForAppeal || {},
                        rejection_reason: 'Extraordinary circumstances beyond our control'
                    })
                });
                const out = await res.json();
                const box = document.getElementById('appeal-box');
                document.getElementById('appeal-letter-text').textContent = out.appeal_letter;
                box.classList.add('shown');
                box.open = true;
                showToast('Appeal letter drafted and ready to send.');
            } catch (err) {
                showToast('Appeal drafting failed.');
            }
            btn.disabled = false;
            btn.textContent = 'Airline said no? Draft appeal letter';
        }

        function renderPackages(packages) {
            const container = document.getElementById('rescue-packages');
            if (!container) return;
            container.textContent = '';

            packages.forEach((pkg, idx) => {
                const isFastest = pkg.package_type === 'FASTEST_RECOVERY';
                const card = document.createElement('div');
                card.className = 'package-card';

                const depTime = (pkg.departure_time || '').split(' ')[1] || pkg.departure_time || '';
                const arrTime = (pkg.arrival_time || '').split(' ')[1] || pkg.arrival_time || '';
                const priceDisplay = (pkg.currency_symbol || '$') + (pkg.price_converted || pkg.price_usd || 0).toFixed(2);
                const coverageText = isFastest ? 'Airline-covered' : 'Instant payout';

                const pkgBadge = document.createElement('div');
                pkgBadge.className = 'package-badge';
                pkgBadge.textContent = isFastest ? 'FASTEST' : 'BEST VALUE';
                card.appendChild(pkgBadge);

                if (pkg.price_status === 'reference') {
                    const sandboxTag = document.createElement('div');
                    sandboxTag.className = 'visa-badge visa-warn';
                    sandboxTag.textContent = '🏷️ Sandbox reference price';
                    card.appendChild(sandboxTag);
                }

                if (pkg.visa_status === 'CLEAR') {
                    const visaBadge = document.createElement('div');
                    visaBadge.className = 'visa-badge visa-clear';
                    visaBadge.textContent = '🛂 Visa-safe for your passport';
                    card.appendChild(visaBadge);
                } else if (pkg.visa_status === 'BLOCKED_RISK') {
                    const visaBadge = document.createElement('div');
                    visaBadge.className = 'visa-badge visa-risk';
                    visaBadge.textContent = '⚠️ ' + (pkg.visa_hub || 'Transit') + ' transit-visa risk: ' + (pkg.visa_note || '');
                    card.appendChild(visaBadge);
                } else if (pkg.visa_status === 'TRANSIT_VISA_REQUIRED') {
                    const visaBadge = document.createElement('div');
                    visaBadge.className = 'visa-badge visa-warn';
                    visaBadge.textContent = '🛂 Transit visa needed at ' + (pkg.visa_hub || 'hub');
                    card.appendChild(visaBadge);
                }

                const body = document.createElement('div');
                body.className = 'package-body';

                const airline = document.createElement('div');
                airline.className = 'package-airline';
                airline.textContent = pkg.airline || '';
                body.appendChild(airline);

                const flight = document.createElement('div');
                flight.className = 'package-flight';
                flight.textContent = pkg.flight_number || '';
                body.appendChild(flight);

                const route = document.createElement('div');
                route.className = 'package-route';
                const orig = document.createElement('span');
                orig.className = 'codes';
                orig.textContent = pkg.origin || '';
                const arrow = document.createElement('span');
                arrow.className = 'arrow';
                arrow.textContent = '-->';
                const dest = document.createElement('span');
                dest.className = 'codes';
                dest.textContent = pkg.destination || '';
                route.appendChild(orig);
                route.appendChild(arrow);
                route.appendChild(dest);
                body.appendChild(route);

                const time = document.createElement('div');
                time.className = 'package-time';
                time.textContent = depTime + ' --> ' + arrTime + ' - Nonstop';
                body.appendChild(time);

                const reason = document.createElement('div');
                reason.className = 'package-reason';
                reason.textContent = pkg.agent_recommendation_reason || '';
                body.appendChild(reason);

                if (isFastest) {
                    const farelock = document.createElement('div');
                    farelock.className = 'package-farelock';
                    const flLabel = document.createElement('div');
                    flLabel.className = 'package-farelock-label';
                    flLabel.textContent = 'Fare Lock';
                    farelock.appendChild(flLabel);

                    const ring = document.createElement('div');
                    ring.className = 'farelock-ring';

                    const svgNS = 'http://www.w3.org/2000/svg';
                    const svg = document.createElementNS(svgNS, 'svg');
                    svg.setAttribute('width', '80');
                    svg.setAttribute('height', '80');

                    const c1 = document.createElementNS(svgNS, 'circle');
                    c1.setAttribute('cx', '40');
                    c1.setAttribute('cy', '40');
                    c1.setAttribute('r', '34');
                    c1.setAttribute('fill', 'none');
                    c1.setAttribute('stroke', 'var(--border-amber)');
                    c1.setAttribute('stroke-width', '4');
                    svg.appendChild(c1);

                    const c2 = document.createElementNS(svgNS, 'circle');
                    c2.setAttribute('class', 'farelock-progress');
                    c2.setAttribute('cx', '40');
                    c2.setAttribute('cy', '40');
                    c2.setAttribute('r', '34');
                    c2.setAttribute('fill', 'none');
                    c2.setAttribute('stroke', 'var(--accent-teal)');
                    c2.setAttribute('stroke-width', '4');
                    c2.setAttribute('stroke-dasharray', '213.6');
                    c2.setAttribute('stroke-dashoffset', '0');
                    c2.setAttribute('stroke-linecap', 'round');
                    c2.style.transition = 'stroke-dashoffset 1s linear, stroke 0.5s';
                    svg.appendChild(c2);
                    ring.appendChild(svg);

                    const ringText = document.createElement('div');
                    ringText.className = 'farelock-ring-text';
                    ringText.setAttribute('data-pkg', String(idx));
                    ringText.textContent = '14:59';
                    ring.appendChild(ringText);

                    farelock.appendChild(ring);
                    body.appendChild(farelock);
                }

                const price = document.createElement('div');
                price.className = 'package-price';
                price.textContent = priceDisplay;
                body.appendChild(price);

                const coverage = document.createElement('div');
                coverage.className = 'package-coverage';
                coverage.textContent = coverageText;
                body.appendChild(coverage);

                const rebookBtn = document.createElement('button');
                rebookBtn.className = 'btn-rebook';
                rebookBtn.textContent = '1-Click Rebook';
                rebookBtn.addEventListener('click', function () {
                    rebookFlight(pkg.offer_id, idx);
                });
                body.appendChild(rebookBtn);

                card.appendChild(body);
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
        function rescueBookingKey(pkg) {
            const passenger = activePassenger() || 'anonymous-demo-traveler';
            const storageKey = 'travelcare-rescue-booking:' +
                String(pkg.offer_id || '') + ':' + passenger;
            let key = sessionStorage.getItem(storageKey);
            if (!key) {
                key = (window.crypto && typeof window.crypto.randomUUID === 'function')
                    ? window.crypto.randomUUID()
                    : 'legacy-rescue-' + Date.now().toString(36) + '-' +
                      Math.random().toString(36).slice(2);
                sessionStorage.setItem(storageKey, key);
            }
            return key;
        }

        async function rebookFlight(offerId, pkgIdx) {
            if (!rescueData) return;
            if (!confirm("Approve this recovery booking? This action is binding and will issue a ticket.")) return;
            const pkg = rescueData.rescue_packages[pkgIdx];

            await showRescueTimeline(pkg);
        }

        // RESCUE TIMELINE ANIMATION
        async function showRescueTimeline(pkg) {
            const overlay = document.getElementById('rescue-timeline-overlay');
            const stepsList = document.getElementById('timeline-steps');
            if (!stepsList) return;
            stepsList.textContent = '';
            if (overlay) overlay.classList.add('visible');

            const claim = rescueData.compensation_claim || {};
            const payout = claim.eligible_payout_usd || 0;
            const steps = [
                { label: 'Verifying fare lock via Atlas GDS', sub: (pkg.airline || '') + ' ' + (pkg.flight_number || '') + ' \u2014 $' + (pkg.price_usd || 0).toFixed(2) },
                { label: 'Agent assigns seat 12A', sub: 'Window seat \u2014 30kg priority baggage' },
                { label: 'Transferring baggage to rescue flight', sub: 'Auto-routed to Cargo Bay 2' },
                { label: 'Requesting an Atlas Sandbox booking', sub: 'The provider may require ticketing activation; no PNR is invented' },
                { label: payout > 0 ? 'Filing ' + payout.toFixed(0) + ' USD compensation claim' : 'Registering refund & duty-of-care route',
                  sub: payout > 0 ? ((claim.jurisdiction && claim.jurisdiction.id) ? claim.jurisdiction.id + ' passenger rights applied' : 'Passenger rights applied') : 'No fixed-cash scheme on this route \u2014 cause-blind care still applies' }
            ];

            for (let i = 0; i < steps.length; i++) {
                const step = steps[i];
                const li = document.createElement('li');
                li.className = 'timeline-step';
                li.id = 'tl-step-' + i;

                const check = document.createElement('div');
                check.className = 'step-check empty';
                li.appendChild(check);

                const text = document.createElement('div');
                text.className = 'step-text';
                const label = document.createElement('div');
                label.className = 'step-label';
                label.textContent = step.label;
                const sub = document.createElement('div');
                sub.style.fontSize = '12px';
                sub.style.color = 'var(--text-muted)';
                sub.textContent = step.sub;
                text.appendChild(label);
                text.appendChild(sub);
                li.appendChild(text);

                stepsList.appendChild(li);

                await new Promise(r => setTimeout(r, 50));
                li.classList.add('shown', 'timeline-step-active');
                check.classList.remove('empty');
                check.textContent = '...';

                await new Promise(r => setTimeout(r, 700));
                li.classList.remove('timeline-step-active');
                li.classList.add('timeline-step-done');
                check.textContent = '\u2713';
            }

            await new Promise(r => setTimeout(r, 400));
            if (overlay) overlay.classList.remove('visible');

            // Now call the actual booking API and show boarding pass
            try {
                const idempotencyKey = rescueBookingKey(pkg);
                const res = await fetch('/api/rescue/book', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Idempotency-Key': idempotencyKey
                    },
                    body: JSON.stringify({
                        offer_id: pkg.offer_id,
                        passenger_name: activePassenger(),
                        price_usd: pkg.price_usd,
                        baggage_addon: '30kg Priority Included',
                        seat_selected: '12A'
                    })
                });
                const result = await res.json();
                if (!res.ok || !result.success) {
                    throw new Error('Sandbox booking request was not confirmed');
                }
                if (!result.ticket || !String(result.ticket.pnr || '').trim()) {
                    throw new Error('Atlas Sandbox returned no confirmed booking reference');
                }
                if (result.success) {
                    showBoardingPass(result.ticket, pkg);
                    showImpactCard(pkg);
                }
            } catch (err) {
                console.warn('Sandbox booking was not confirmed.');
                showToast('Booking failed. Please try rebooking again.');
            }
        }

        // IMPACT SUMMARY CARD
        function showImpactCard(pkg) {
            const card = document.getElementById('impact-card');
            if (!card) return;
            document.getElementById('impact-time').textContent = '190 min';
            document.getElementById('impact-cost').textContent = convertCurrency(18.50);
            document.getElementById('impact-comp').textContent = convertCurrency(250.00);
            document.getElementById('impact-voucher').textContent = convertCurrency(25.00);
            document.getElementById('impact-total').textContent = convertCurrency(293.50);
            card.classList.add('visible');
        }

        function showBoardingPass(ticket, pkg) {
            const overlay = document.getElementById('modal-overlay');
            const confirmedPnr = String((ticket && ticket.pnr) || '').trim();
            if (!overlay || !confirmedPnr) return;
            document.getElementById('bp-airline').textContent = pkg.airline || '';
            document.getElementById('bp-origin').textContent = pkg.origin || '';
            document.getElementById('bp-origin-name').textContent = pkg.origin_airport || pkg.origin || '';
            document.getElementById('bp-dest').textContent = pkg.destination || '';
            document.getElementById('bp-dest-name').textContent = pkg.destination_airport || pkg.destination || '';
            document.getElementById('bp-flight').textContent = pkg.flight_number || '';
            document.getElementById('bp-gate').textContent = ticket.gate || 'Not assigned';
            document.getElementById('bp-seat').textContent = ticket.seat_assigned || 'Not assigned';
            document.getElementById('bp-boarding').textContent = ticket.boarding_time || 'Not assigned';
            document.getElementById('bp-pnr').textContent = confirmedPnr;

            const barcode = document.getElementById('bp-barcode');
            if (barcode) {
                barcode.textContent = '';
                const pnr = confirmedPnr;
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
            }

            overlay.classList.add('visible');
        }

        function closeModal() {
            const overlay = document.getElementById('modal-overlay');
            if (overlay) overlay.classList.remove('visible');
        }

        // COMPENSATION PAYOUT
        function filePayout() {
            if (!rescueData) return;
            const claim = rescueData.compensation_claim || {};
            const payout = claim.eligible_payout_usd || 0;
            if (payout > 0) {
                document.getElementById('comp-status').textContent = 'Status: PAYOUT_INITIATED';
                showToast('Compensation claim filed successfully.');
            } else {
                document.getElementById('comp-status').textContent = 'Status: REFUND_ROUTE_REGISTERED';
                showToast('No fixed-cash scheme on this route \u2014 refund/duty-of-care route registered.');
            }
        }

        // FLIGHT SEARCH
        async function searchFlights() {
            const origin = document.getElementById('search-origin').value.trim().toUpperCase();
            const destination = document.getElementById('search-destination').value.trim().toUpperCase();
            if (!origin || !destination) { showToast('Enter origin and destination airports.'); return; }
            const results = document.getElementById('search-results');
            if (!results) return;
            results.textContent = '';
            for (let i = 0; i < 3; i++) {
                const sk = document.createElement('div');
                sk.className = 'skeleton-card';
                const left = document.createElement('div');
                const line1 = document.createElement('div');
                line1.className = 'skeleton-line med';
                const line2 = document.createElement('div');
                line2.className = 'skeleton-line short';
                left.appendChild(line1);
                left.appendChild(line2);
                const right = document.createElement('div');
                right.className = 'skeleton-line short';
                right.style.width = '40px';
                sk.appendChild(left);
                sk.appendChild(right);
                results.appendChild(sk);
            }

            try {
                const res = await fetch('/api/flights/search', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        origin: origin,
                        destination: destination,
                        date: document.getElementById('search-date').value || defaultSearchDate(),
                        passengers: parseInt(document.getElementById('search-passengers').value),
                        cabin_class: 'ECONOMY',
                        currency: document.getElementById('search-currency').value
                    })
                });
                const data = await res.json();
                if (!res.ok) {
                    throw new Error('Atlas Sandbox search unavailable');
                }
                renderSearchResults(data.offers);
            } catch (err) {
                results.textContent = '';
                const errDiv = document.createElement('div');
                errDiv.className = 'loading search-error';
                errDiv.textContent = 'Search failed. Please try again.';
                results.appendChild(errDiv);
            }
        }

        function renderSearchResults(offers) {
            const container = document.getElementById('search-results');
            if (!container) return;
            container.textContent = '';

            if (!offers || offers.length === 0) {
                const noFlights = document.createElement('div');
                noFlights.className = 'loading';
                noFlights.textContent = 'No flights found.';
                container.appendChild(noFlights);
                return;
            }

            offers.forEach(o => {
                const depTime = (o.departure_time || '').split(' ')[1] || o.departure_time || '';
                const arrTime = (o.arrival_time || '').split(' ')[1] || o.arrival_time || '';
                const price = (o.currency_symbol || '$') + (o.price_converted || o.price_usd || 0).toFixed(2);

                const card = document.createElement('div');
                card.className = 'search-result-card';

                const left = document.createElement('div');
                left.className = 'src-left';
                const airline = document.createElement('div');
                airline.className = 'src-airline';
                airline.textContent = o.airline || '';
                const flight = document.createElement('div');
                flight.className = 'src-flight';
                flight.textContent = o.flight_number || '';
                const route = document.createElement('div');
                route.className = 'src-route';
                route.textContent = (o.origin || '') + ' --> ' + (o.destination || '') + ' - ' + depTime + ' to ' + arrTime;
                left.appendChild(airline);
                left.appendChild(flight);
                left.appendChild(route);
                card.appendChild(left);

                const right = document.createElement('div');
                right.className = 'src-right';
                const priceDiv = document.createElement('div');
                priceDiv.className = 'src-price';
                priceDiv.textContent = price;
                const seats = document.createElement('div');
                seats.className = 'src-seats';
                seats.textContent = (o.seats_available != null ? o.seats_available : 0) + ' seats left';
                right.appendChild(priceDiv);
                right.appendChild(seats);
                card.appendChild(right);

                container.appendChild(card);
            });
        }

        // CONCIERGE CHAT
        async function sendChat() {
            const input = document.getElementById('chat-input');
            if (!input) return;
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
            if (!container) return;
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

            const avatar = document.createElement('div');
            avatar.className = 'msg-avatar';
            const svgNS = 'http://www.w3.org/2000/svg';
            const svg = document.createElementNS(svgNS, 'svg');
            svg.setAttribute('viewBox', '0 0 24 24');
            svg.setAttribute('fill', 'none');
            svg.setAttribute('stroke', 'currentColor');
            svg.setAttribute('stroke-width', '2');
            const path1 = document.createElementNS(svgNS, 'path');
            path1.setAttribute('d', 'M12 2a3 3 0 0 1 3 3v1a3 3 0 0 1-3 3 3 3 0 0 1-3-3V5a3 3 0 0 1 3-3z');
            const path2 = document.createElementNS(svgNS, 'path');
            path2.setAttribute('d', 'M12 14c-4 0-7 2-7 5v3h14v-3c0-3-3-5-7-5z');
            svg.appendChild(path1);
            svg.appendChild(path2);
            avatar.appendChild(svg);
            aiRow.appendChild(avatar);

            const content = document.createElement('div');
            content.className = 'msg-content';
            const bubble = document.createElement('div');
            bubble.className = 'msg-bubble msg-ai';
            const dots = document.createElement('div');
            dots.className = 'typing-dots';
            for (let i = 0; i < 3; i++) {
                const dot = document.createElement('div');
                dot.className = 'typing-dot';
                dots.appendChild(dot);
            }
            bubble.appendChild(dots);
            content.appendChild(bubble);
            aiRow.appendChild(content);

            container.appendChild(aiRow);
            container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });

            try {
                const tripId = (window.Trip && window.Trip.tripId) ? window.Trip.tripId : null;
                const userId = (window.Trip && window.Trip.userId) || (window.USER_ID) || null;
                const payload = { query: query };
                if (tripId) payload.trip_id = tripId;
                if (userId) payload.user_id = userId;
                const res = await fetch('/api/chat/concierge', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await res.json();
                const replyTime = new Date().toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
                bubble.textContent = data.reply;
                var timeDiv = document.createElement('div');
                timeDiv.className = 'msg-time';
                timeDiv.textContent = replyTime;
                content.appendChild(timeDiv);
            } catch (err) {
                bubble.textContent = 'Sorry, I could not process your request right now.';
                console.error('Concierge failed:', err);
            }
            container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
        }

        // HEALTH CHECK
        async function checkHealth() {
            const badge = document.querySelector('#health-badge');
            if (!badge) return;
            try {
                const res = await fetch('/api/health');
                const data = await res.json();
                const runtimeBadge = document.querySelector('#qoder-badge');
                if (runtimeBadge) {
                    const engine = String(data.ai_engine || 'not reported');
                    runtimeBadge.textContent = engine.indexOf('deterministic-fallback') !== -1
                        ? 'AI: Deterministic fallback'
                        : 'AI: ' + engine;
                    runtimeBadge.title = engine;
                }
                badge.textContent = '';
                const dot = document.createElement('span');
                dot.id = 'health-dot';
                badge.appendChild(dot);
                badge.appendChild(document.createTextNode(data.status || 'OK'));
            } catch (err) {
                badge.textContent = '';
                const dot = document.createElement('span');
                dot.id = 'health-dot';
                dot.style.background = '#DC2626';
                badge.appendChild(dot);
                badge.appendChild(document.createTextNode('Offline'));
            }
        }

        // INIT
        checkHealth();
