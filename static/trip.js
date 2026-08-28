/* ============================================================
   TravelCare AI — ATLAS JOURNEY trip view (G4.5 redesign)
   All trip-view logic lives here; static/app.js stays untouched.
   SECURITY: strict textContent/createElement DOM construction —
   zero innerHTML with data (§9.3 XSS contract). No selector is
   ever built from server-supplied field names (F9 discipline).
   HONESTY: Atlas Sandbox provenance sentence, "💡 suggestion
   only", "researched mock data (as_of …)", visa warnings, price
   notes and degradation are NEVER hidden — translated, not
   removed (§5.5 honesty contract).
   IA: 3 destinations (Plan a trip / My trip / Help) + a profile
   drawer; 5-step guided flow derived ONLY from server state.
   ============================================================ */
(function () {
    'use strict';

    var USER_ID = 'victor'; // §16.1 single-user demo id
    var POLL_MS = 1000;     // F9: DAG updates within 1s cadence
    // §16.1 honesty (G4-DA-fix F6): conversions are LABELED indicative
    // estimates, never presented as the fare itself.
    var RATE_SGD = 1.34;
    var RATE_THB = 35.4; // per 1 USD; only used for labeled SGD→THB hints
    // Atlas Sandbox carrier display names (sandbox data only — never
    // presented as live airline inventory).
    var CARRIER_NAMES = {
        SQ: 'Singapore Airlines',
        TR: 'Scoot',
        MI: 'SilkAir',
        TG: 'Thai Airways',
        FD: 'AirAsia',
        '3K': 'Jetstar Asia'
    };

    // --- ATLAS JOURNEY vocabulary (spec §4/§5.1) ------------------------------

    // One-question-at-a-time card order + static allow-list (§4: question
    // cards key off this map; hostile field names fall back to generic).
    var FIELD_ORDER = ['origin_city', 'confirmed_origin_airport', 'dest_city',
                       'confirmed_destination_airport', 'date_window',
                       'passport_country', 'home_city', 'expiry'];
    var FIELD_WHY = {
        origin_city: 'Needed to search flights from the right airport.',
        confirmed_origin_airport: 'Needed so we search only the airport you choose.',
        dest_city: 'Needed to find flights to the right place.',
        confirmed_destination_airport: 'Needed so we arrive at the airport you choose.',
        date_window: 'Needed to check flights on the right days.',
        passport_country: 'Needed to check entry requirements for you.',
        home_city: 'Helps us plan trips that start from your home.',
        expiry: 'Needed to make sure your passport is valid for travel.'
    };
    var FACT_LABELS = {
        origin_city: 'From',
        confirmed_origin_airport: 'Departure airport',
        dest_city: 'To',
        confirmed_destination_airport: 'Arrival airport',
        date_window: 'Dates',
        passport_country: 'Passport country',
        home_city: 'Home city',
        expiry: 'Passport expiry'
    };
    var SERVICE_LABELS = {
        flight_search: 'Find flights',
        flight_booking: 'Book flights',
        visa_check: 'Entry requirements check',
        hotel: 'Hotel',
        activities: 'Activities',
        local_transport: 'Local transport'
    };
    var STEP_TITLES = ['Tell us what you need', 'Choose your options',
                       'Review your plan', 'Confirm booking',
                       'Track your trip'];
    // Starters pre-fill an EDITABLE goal text (spec §3); the server still
    // confirms scope through the 3-choice card when it cannot be inferred.
    var STARTER_GOALS = {
        'aj-starter-flight-only':
            'Find me a flight \u2014 I\u2019m just comparing options for now.',
        'aj-starter-flight-booking':
            'Find me a flight and book it for me.',
        'aj-starter-complete':
            'Plan my complete trip \u2014 flights, hotel and activities.'
    };
    var STARTER_SERVICES = {
        'aj-starter-flight-only': ['flight_search'],
        'aj-starter-flight-booking': ['flight_search', 'flight_booking'],
        'aj-starter-complete': ['flight_search', 'flight_booking', 'hotel',
                                'activities', 'local_transport']
    };

    var Trip = {
        tripId: null,
        pollTimer: null,
        es: null,
        answeredChips: {},      // field -> CONFIRMED answer (never build-time)
        answeredFacts: {},      // field -> confirmed value (AJ facts)
        deferredSkip: {},       // field -> question deferred via Back
        deferredValue: {},      // field -> preserved input value
        factsEdited: {},
        renderedNodeCount: -1,
        renderedDagSig: '',
        renderedOptionIds: null,
        renderedItineraryCount: -1,
        renderedItinerarySig: '',
        itineraryEditorId: null,
        approval: null,          // current approve_booking approval object
        recoveryApproval: null,  // current recovery_booking approval object
        selectedOptionId: null,
        recoverySelectedId: null,
        approvalKeys: {},        // approval id -> stable retry key
        pnrShown: false,
        busy: false,
        // G4-DA-fix F1/F2: race-safety + lifecycle
        epoch: 0,                // bumped whenever in-flight polls go stale
        pollSeq: 0,              // monotonic request sequence
        appliedSeq: 0,           // newest response actually rendered
        pollAbort: null,         // AbortController of the in-flight poll
        terminal: false,
        errorKind: null,         // action errors outlive same-state polling
        errorEpoch: -1,
        // ATLAS JOURNEY state
        goalText: '',
        dest: 'plan',            // plan | mytrip | help
        currentStep: 1,
        forceStep: null,
        provServices: null,      // starter-provisional service chips
        pendingProvServices: null, // starter intent crossing the trip reset
        removedServices: {},
        shownOptions: 3,
        shownItin: 6,
        booked: false,
        switchedMytrip: false,
        pulsed: false,
        lastState: null,
        homeCityProfile: '',
        lastFocus: null,
        announced: {},
        // G4.6 safety card
        safetyTried: false       // one-shot auto-fetch guard
    };

    // --- strict DOM helpers (never innerHTML with data) -------------------

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined && text !== null) node.textContent = String(text);
        return node;
    }

    function clear(node) {
        while (node && node.firstChild) node.removeChild(node.firstChild);
    }

    function byId(id) { return document.getElementById(id); }

    function tid(node, id) { node.setAttribute('data-testid', id); return node; }
    function tidAj(node, id) { node.setAttribute('data-testid-aj', id); return node; }

    // G4-DA-fix F6 honest pricing: render the option's ACTUAL currency
    // natively; non-THB fares carry a labeled indicative SGD estimate and
    // never a misleading ฿ pairing.
    function priceNative(price) {
        var amount = (price && price.amount) || 0;
        var cur = (price && price.currency) || 'USD';
        if (cur === 'THB') return '\u0E3F' + Number(amount).toFixed(0);
        if (cur === 'SGD') return 'S$' + Number(amount).toFixed(2);
        return '$' + Number(amount).toFixed(2);
    }
    function priceSecondary(price) {
        var cur = (price && price.currency) || 'USD';
        if (cur !== 'USD' && cur !== 'SGD') return '';
        var sgd = (cur === 'SGD') ? Number(price.amount || 0)
                                  : Number(price.amount || 0) * RATE_SGD;
        return '\u2248 S$' + sgd.toFixed(2) + ' (indicative SGD)';
    }
    function sgdRange(range) {
        if (!range || range.length < 2) return null;
        return 'S$' + Number(range[0]).toFixed(0) + '\u2013' + Number(range[1]).toFixed(0);
    }
    function sgdToThb(range) {
        if (!range || range.length < 2) return null;
        var factor = RATE_THB / RATE_SGD;
        // labeled indicative estimate (§11 honesty), never the price itself
        return '\u2248 \u0E3F' + Math.round(range[0] * factor) + '\u2013' +
            Math.round(range[1] * factor) + ' (indicative)';
    }
    function clock(iso) {
        if (!iso) return '';
        var d = new Date(iso);
        if (isNaN(d.getTime())) return '';
        return d.toTimeString().slice(0, 8);
    }
    function hhmm(t) { return String(t || '').slice(11, 16); }
    function reducedMotion() {
        return !!(window.matchMedia &&
                  window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    }

    async function api(path, opts) {
        var res = await fetch(path, opts);
        var body = null;
        try { body = await res.json(); } catch (e) { body = null; }
        if (!res.ok) {
            var err = (body && body.error) || { code: 'http_' + res.status, message: res.statusText };
            var exc = new Error(err.message || 'request failed');
            exc.code = err.code;
            exc.hint = err.hint || '';
            exc.status = res.status;
            exc.recoverable = !!err.recoverable;
            throw exc;
        }
        return body;
    }

    function generateUUID() {
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
            var r = Math.random() * 16 | 0, v = c === 'x' ? r : (r & 0x3 | 0x8);
            return v.toString(16);
        });
    }

    function jsonOpts(method, payload, extraHeaders) {
        var opts = {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        };
        if (extraHeaders) {
            for (var k in extraHeaders) {
                opts.headers[k] = extraHeaders[k];
            }
        }
        return opts;
    }

    // --- ARIA live announcements (spec §9.2) ------------------------------

    function announce(msg, mode) {
        var live = byId('aj-live');
        if (!live || !msg) return;
        live.setAttribute('aria-live', mode === 'assertive' ? 'assertive' : 'polite');
        clear(live);
        live.textContent = msg;
    }

    // --- chat surface (collapsed "Conversation so far" disclosure) ---------

    function addChat(role, text) {
        var chat = byId('trip-chat');
        var msg = el('div', 'trip-msg ' + (role === 'user' ? 'trip-msg-user' : 'trip-msg-agent'));
        var bubble = el('div', 'trip-msg-bubble', text);
        msg.appendChild(bubble);
        chat.appendChild(msg);
        chat.scrollTop = chat.scrollHeight;
    }

    // --- goal intake ---------------------------------------------------------

    async function submitGoal(ev) {
        if (ev && ev.preventDefault) ev.preventDefault();
        if (Trip.busy) return;
        var input = byId('trip-goal-input');
        var text = input.value.trim();
        if (!text) { input.focus(); return; }
        Trip.busy = true;
        byId('trip-goal-loading').hidden = false;
        byId('trip-goal-submit').disabled = true;
        hideError();
        clearStateBox();
        showStateBox('loading', 'Working on your plan\u2026 this usually takes a few seconds.',
                     null, null);
        announce('Working on your plan.');
        try {
            var data = await api('/api/trips', jsonOpts('POST', {
                goal_text: text, user_id: USER_ID
            }));
            invalidatePolls();          // any in-flight poll is for the old trip
            Trip.tripId = data.trip_id;
            window.__tripId = data.trip_id; // test/diagnostic hook
            Trip.goalText = text;
            Trip.pnrShown = false;
            Trip.terminal = false;
            Trip.booked = false;
            Trip.switchedMytrip = false;
            Trip.pulsed = false;
            Trip.forceStep = null;
            Trip.renderedNodeCount = -1;
            Trip.renderedDagSig = '';
            Trip.renderedOptionIds = null;  // null sentinel: force re-render
            Trip.renderedItineraryCount = -1;
            Trip.renderedItinerarySig = '';
            Trip.itineraryEditorId = null;
            Trip.answeredChips = {};
            Trip.answeredFacts = {};
            Trip.deferredSkip = {};
            Trip.deferredValue = {};
            Trip.shownOptions = 3;
            Trip.shownItin = 6;
            Trip.recoverySelectedId = null;
            Trip.approvalKeys = {};
            resetTripSurfaces();        // per-trip panels never leak across trips
            // provisional services from a STARTER tap belong to THIS trip —
            // restore them after the reset (typed goals carry none)
            if (Trip.pendingProvServices) {
                Trip.provServices = Trip.pendingProvServices;
                Trip.pendingProvServices = null;
                renderServices(null);
            }
            clear(byId('trip-chat'));
            addChat('user', text);
            addChat('agent', 'Trip opened \u2014 working on your plan now. ' +
                             'Follow the steps below.');
            byId('trip-status-strip').hidden = false;
            clearStateBox();
            switchDestination('plan');
            startWatching();
        } catch (err) {
            clearStateBox();
            if (err.status === 422 && (err.code === 'invalid_goal' ||
                    /parse|could not/i.test(err.message))) {
                // spec §3/D2: plain guidance, never "parse" wording
                showStateBox('validation',
                    'We couldn\u2019t work out the trip yet. Please include ' +
                    'where you\u2019re going and roughly when \u2014 e.g. ' +
                    '\u201cBangkok to Singapore, Sep 29\u201330\u201d.',
                    'Plan my trip', function () { byId('trip-goal-input').focus(); });
                announce('We need a little more detail to plan the trip.');
            } else {
                showStateBox('provider',
                    'We hit a snag starting your trip \u2014 ' + err.message +
                    (err.hint ? '. ' + err.hint : ''),
                    'Try again', function () { submitGoal(null); });
            }
        } finally {
            Trip.busy = false;
            byId('trip-goal-loading').hidden = true;
            byId('trip-goal-submit').disabled = false;
        }
    }

    // --- watching: 1s polling + SSE -----------------------------------------

    function stopWatching() {
        if (Trip.pollTimer) { clearInterval(Trip.pollTimer); Trip.pollTimer = null; }
        if (Trip.es) { Trip.es.close(); Trip.es = null; }
        if (Trip.pollAbort) { Trip.pollAbort.abort(); Trip.pollAbort = null; }
    }

    function invalidatePolls() {
        // G4-DA-fix F2: any response captured before this moment must be
        // dropped when it lands — bump the epoch and abort the in-flight GET.
        Trip.epoch += 1;
        if (Trip.pollAbort) { Trip.pollAbort.abort(); Trip.pollAbort = null; }
    }

    function startWatching() {
        stopWatching();
        Trip.terminal = false;
        pollState();
        Trip.pollTimer = setInterval(pollState, POLL_MS);
        try {
            Trip.es = new EventSource('/api/trip/' + Trip.tripId + '/stream');
            Trip.es.addEventListener('node', pollState);
            Trip.es.addEventListener('approval', pollState);
            Trip.es.addEventListener('status', function () {
                pollState();
                if (Trip.es) { Trip.es.close(); Trip.es = null; } // terminal: stop reconnects
            });
            Trip.es.onerror = function () { /* polling remains the backstop */ };
        } catch (e) { /* SSE is an enhancement; polling alone satisfies F9 */ }
    }

    // G4-DA-fix F1: the watcher stops on terminal status (after the final
    // render) and whenever the user leaves the trip view — app.js is frozen,
    // so view switches are observed via the .active class it toggles.
    function observeTripView() {
        var view = byId('view-trip');
        if (!view || typeof MutationObserver === 'undefined') return;
        var mo = new MutationObserver(function () {
            if (view.classList.contains('active')) {
                if (Trip.tripId && !Trip.pollTimer && !Trip.terminal) startWatching();
            } else {
                stopWatching();
            }
        });
        mo.observe(view, { attributes: true, attributeFilter: ['class'] });
    }

    // Restore every per-trip surface to its honest empty state (legacy + AJ).
    function resetTripSurfaces() {
        var chips = byId('trip-clarify-chips');
        if (chips) clear(chips);
        var scopeBlock = byId('trip-scope-block');
        scopeBlock.hidden = true;
        scopeBlock.removeAttribute('data-approval-id');
        var banner = byId('trip-approval-banner');
        banner.hidden = true;
        var overlay = byId('trip-approval-overlay');
        overlay.hidden = true;
        Trip.approval = null;
        Trip.recoveryApproval = null;
        Trip.selectedOptionId = null;
        byId('trip-pnr-block').hidden = true;
        byId('trip-visa-block').hidden = true;
        var optEmpty = el('div', 'trip-empty',
            'No flight options yet \u2014 tell us your travel goal to begin.');
        tid(optEmpty, 'trip-options-empty');
        var optionsBox = byId('trip-options');
        clear(optionsBox);
        optionsBox.appendChild(optEmpty);
        var itinEmpty = el('div', 'trip-empty',
            'Nothing planned yet \u2014 the itinerary appears after a confirmed booking.');
        tid(itinEmpty, 'trip-itinerary-empty');
        var itinBox = byId('trip-itinerary');
        clear(itinBox);
        itinBox.appendChild(itinEmpty);
        var dagEmpty = el('li', 'trip-dag-empty',
            'No steps yet \u2014 this trace fills in as the agent works (1s refresh).');
        tid(dagEmpty, 'trip-dag-empty');
        var dagList = byId('trip-dag-list');
        clear(dagList);
        dagList.appendChild(dagEmpty);
        // AJ surfaces
        clear(byId('aj-requested-services'));
        byId('aj-requested-services').hidden = true;
        Trip.provServices = null;
        Trip.removedServices = {};
        clear(byId('aj-facts-summary'));
        byId('aj-facts-summary').hidden = true;
        clear(byId('aj-review-summary'));
        clear(byId('aj-review-total'));
        clear(byId('aj-sources-body'));
        clear(byId('aj-confirm-summary'));
        byId('aj-confirm-price').textContent = '';
        byId('aj-confirm-pax').textContent = '';
        clear(byId('aj-recovery-panel'));
        byId('aj-recovery-panel').hidden = true;
        // G4.6 safety card reset
        Trip.safetyTried = false;
        clear(byId('aj-safety-body'));
        clear(byId('aj-safety-actions'));
        byId('aj-safety-checked').textContent = '';
        byId('aj-safety-card').hidden = true;
        byId('aj-booking-status').hidden = true;
        byId('aj-next-action').hidden = true;
        byId('aj-monitor-status').hidden = true;
        byId('aj-step-5').classList.remove('is-done');
        for (var n = 1; n <= 5; n++) {
            var sum = byId('aj-step-' + n + '-summary');
            if (sum) sum.textContent = '';
        }
        clear(byId('aj-live'));
    }

    async function pollState() {
        if (!Trip.tripId || Trip.terminal) return;
        var seq = (Trip.pollSeq += 1);
        var epochAtSend = Trip.epoch;
        if (Trip.pollAbort) Trip.pollAbort.abort();
        Trip.pollAbort = new AbortController();
        try {
            var state = await api('/api/trip/' + Trip.tripId + '/state',
                                  { signal: Trip.pollAbort.signal });
            // G4-DA-fix F2: a response is stale if a trip-mutating action
            // happened after it was sent, or a newer one was already applied.
            if (epochAtSend !== Trip.epoch || seq <= Trip.appliedSeq) return;
            Trip.appliedSeq = seq;
            renderState(state);
        } catch (err) {
            if (err && err.name === 'AbortError') return; // superseded on purpose
            if (epochAtSend !== Trip.epoch) return;
            if (!err.status) {
                // network failure — offline-fallback state (§9.1): last
                // rendered view stays, honest banner + Retry
                showStateBox('offline',
                    'We can\u2019t reach Atlas right now. Your last saved view ' +
                    'is below.', 'Retry', pollState);
            } else {
                showError('State check failed: ' + plainError(err), 'state');
            }
        } finally {
            if (Trip.pollAbort && Trip.pollAbort.signal.aborted) Trip.pollAbort = null;
        }
    }

    // --- error / state surfaces (§9.1) ---------------------------------------

    // Translate §6 envelopes through §5.1 vocabulary — raw codes stay inside
    // the "How this plan was made" disclosure, never on the main surface.
    function plainError(err) {
        var msg = err.message || 'something went wrong';
        if (err.hint) msg += '. ' + err.hint;
        return msg;
    }

    function showError(text, kind) {
        var box = byId('trip-error');
        clear(box);
        box.appendChild(el('div', 'trip-error-title', '\u26A0 Trip needs attention'));
        box.appendChild(el('div', 'trip-error-text', text));
        box.hidden = false;
        Trip.errorKind = kind || 'action';
        Trip.errorEpoch = Trip.epoch;
    }

    function hideError() {
        var box = byId('trip-error');
        clear(box);
        box.hidden = true;
        Trip.errorKind = null;
        Trip.errorEpoch = -1;
    }

    // AJ inline state boxes: empty|loading|validation|provider|expired|
    // uncertain|offline (spec §9.1 + §10.2 aj-state-*).
    function clearStateBox() {
        var slot = byId('aj-state-slot');
        var boxes = slot.querySelectorAll('.aj-state');
        for (var i = 0; i < boxes.length; i++) {
            boxes[i].parentNode.removeChild(boxes[i]);
        }
    }

    function showStateBox(kind, message, actionLabel, actionFn, testidExtra) {
        clearStateBox();
        var slot = byId('aj-state-slot');
        var box = el('div', 'aj-state aj-state-' + kind);
        tid(box, testidExtra || ('aj-state-' + kind));
        tidAj(box, testidExtra || ('aj-state-' + kind));
        box.appendChild(el('p', 'aj-state-msg', message));
        if (actionLabel && actionFn) {
            var btn = el('button', 'aj-state-action', actionLabel);
            btn.type = 'button';
            tid(btn, (testidExtra || ('aj-state-' + kind)) + '-retry');
            btn.addEventListener('click', actionFn);
            box.appendChild(btn);
        }
        slot.appendChild(box);
        return box;
    }

    // --- step derivation (spec §2 mapping; server state only) ----------------

    function findApproval(s, nodeName) {
        var list = (s && s.pending_approvals) || [];
        for (var i = 0; i < list.length; i++) {
            if (list[i].node_name === nodeName) return list[i];
        }
        return null;
    }

    function deriveStep(s) {
        if (!Trip.tripId || !s) return 1;
        var out = s.outputs || {};
        if (firstUnansweredQuestion(s)) return 1;
        if (out.recovery || findApproval(s, 'recovery_booking')) return 5;
        if (out.booking) return 5;
        if (findApproval(s, 'approve_booking')) return 4;
        if (out.flight_search) {
            var rs = ((out.clarify || {}).requested_services) || {};
            if (rs.flight_booking === 'requested') return 2; // review waits w/ step 3
            return 3; // flight_only: review closes the plan
        }
        return 1;
    }

    // --- main state renderer ----------------------------------------------------

    function renderState(s) {
        // A successful state poll clears a state-fetch error.  A rejected
        // user action (for example a safety gate) must remain visible while
        // same-state polling continues; it clears only after a newer action
        // advances the epoch.
        if (Trip.errorKind === 'state' || Trip.errorEpoch < Trip.epoch) {
            hideError();
        }
        clearStateBox();
        Trip.lastState = s;
        renderStatusStrip(s);
        renderDag(s);
        renderServices(s);
        renderQuestionCards(s);
        renderScopeChoices(s);
        renderFacts(s);
        renderVisaPanel(s);
        renderSources(s);
        renderOptions(s);
        renderReview(s);
        renderApprovalGate(s);
        renderConfirm(s);
        renderMyTrip(s);
        renderSafety(s);
        renderPnr(s);
        renderItinerary(s);
        renderRecovery(s);
        var step = Trip.forceStep || deriveStep(s);
        // the My trip destination always shows its own step expanded
        if (Trip.dest === 'mytrip') step = 5;
        Trip.currentStep = step;
        renderStepRail(s, step);
        renderJourneyLine(s, deriveStep(s));
        announceTransitions(s);
        window.__tripState = s; // test/diagnostic hook (last rendered state)

        if (s.status === 'failed') {
            var failed = null;
            for (var i = (s.nodes || []).length - 1; i >= 0; i--) {
                if (s.nodes[i].status === 'FAILED') { failed = s.nodes[i]; break; }
            }
            if (failed) {
                var d = failed.details || {};
                showStateBox('provider',
                    (d.message || 'We hit a snag while planning.') +
                    (d.hint ? ' ' + d.hint : '') +
                    (Trip.deferredSkipIsEmpty(s) ? ''
                        : ' Answering the open questions below can fix this.'),
                    'Try again', function () {
                        Trip.terminal = false;
                        startWatching();
                    });
            }
        }

        // Auto-move to My trip once a booking lands (once per trip).
        if (deriveStep(s) === 5 && !Trip.switchedMytrip &&
                ((s.outputs || {}).booking || (s.outputs || {}).recovery)) {
            Trip.switchedMytrip = true;
            switchDestination('mytrip');
        }

        // G4-DA-fix F1: terminal status -> one final render, then stop.
        if (s.status === 'completed' || s.status === 'failed') {
            Trip.terminal = true;
            stopWatching();
        }
    }

    function deferredSkipIsEmpty(s) {
        for (var k in Trip.deferredSkip) {
            if (Trip.deferredSkip[k]) return false;
        }
        return true;
    }

    // Plain-language async milestones via the aj-live region (§9.2).
    function announceTransitions(s) {
        var out = s.outputs || {};
        var key;
        if (out.recovery && !Trip.announced.recovery) {
            Trip.announced.recovery = true;
            announce('Something changed with your flight \u2014 review your ' +
                     'replacement options in My trip.', 'assertive');
        } else if (out.booking && !Trip.announced.booked) {
            Trip.announced.booked = true;
            Trip.booked = true;
            announce('Booking confirmed \u2014 booking reference ' +
                     (out.booking.pnr || '') + '. Find it under My trip.');
        } else if (findApproval(s, 'approve_booking') && !Trip.announced.approval) {
            Trip.announced.approval = true;
            announce('Your flight options are ready \u2014 waiting for your approval.');
        } else if (out.flight_search && !Trip.announced.options) {
            Trip.announced.options = true;
            key = ((out.flight_search.options || []).length);
            announce(key + ' flight options found.');
        }
    }

    function renderStatusStrip(s) {
        var strip = byId('trip-status-strip');
        strip.hidden = false;
        var pill = byId('trip-status-pill');
        pill.textContent = s.status || 'unknown';
        pill.setAttribute('data-status', s.status || '');
        byId('trip-status-node').textContent = s.current_state ? ('at node: ' + s.current_state) : '';
        byId('trip-status-latency').textContent = (Number(s.total_latency_ms || 0)).toFixed(0) + ' ms total';
        var live = byId('trip-dag-live');
        live.textContent = (s.status === 'completed' || s.status === 'failed')
            ? ('finished \u00B7 ' + s.status) : 'live \u00B7 1s refresh';
    }

    // --- Agent Trace (old DAG panel — collapsed disclosure, spec §5.5) -----

    function renderDag(s) {
        var nodes = s.nodes || [];
        var last = nodes[nodes.length - 1];
        var sig = nodes.length + ':' + (last ? last.name + '/' + last.status : '-');
        // G4-DA-fix F2: the trace is monotonic — a stale snapshot with fewer
        // nodes can never regress the panel.
        if (nodes.length < Trip.renderedNodeCount ||
                (nodes.length === Trip.renderedNodeCount &&
                 sig === Trip.renderedDagSig)) return;
        Trip.renderedNodeCount = nodes.length;
        Trip.renderedDagSig = sig;
        var list = byId('trip-dag-list');
        clear(list);
        if (nodes.length === 0) {
            var dagEmpty = el('li', 'trip-dag-empty',
                'No steps yet \u2014 this trace fills in as the agent works (1s refresh).');
            tid(dagEmpty, 'trip-dag-empty');
            list.appendChild(dagEmpty);
            return;
        }
        nodes.forEach(function (n) {
            var li = el('li', 'trip-dag-node trip-dag-' + String(n.status || 'pending').toLowerCase());
            tid(li, 'trip-dag-node');
            li.appendChild(el('span', 'trip-dag-dot'));
            var body = el('div', 'trip-dag-body');
            var head = el('div', 'trip-dag-head');
            head.appendChild(el('span', 'trip-dag-name', n.name));
            head.appendChild(el('span', 'trip-dag-status', n.status));
            body.appendChild(head);
            var meta = el('div', 'trip-dag-meta');
            meta.appendChild(el('span', 'trip-dag-skill', n.skill_ref || ''));
            meta.appendChild(el('span', 'trip-dag-latency',
                (Number(n.latency_ms || 0)).toFixed(0) + ' ms'));
            meta.appendChild(el('span', 'trip-dag-time', clock(n.timestamp)));
            body.appendChild(meta);
            li.appendChild(body);
            list.appendChild(li);
        });
    }

    // --- clarification: ONE focused question card at a time (spec §4) ----------

    var PROFILE_CHIP_FIELDS = ['passport_country', 'home_city', 'expiry'];

    // G4-DA-fix F9: server-supplied field names may carry quotes/brackets —
    // never build a selector from them; scan children by attribute instead.
    function chipByField(wrap, field) {
        var kids = wrap.children;
        for (var i = 0; i < kids.length; i++) {
            if (kids[i].getAttribute && kids[i].getAttribute('data-chip-field') === field) {
                return kids[i];
            }
        }
        return null;
    }

    function clarificationQuestions(s) {
        var clarify = ((s && s.outputs) || {}).clarify || null;
        var questions = ((clarify && clarify.questions) || []).map(function (q) {
            var copy = Object.assign({}, q);
            copy.required = q.field === 'passport_country' &&
                !!findApproval(s, 'approve_booking');
            return copy;
        });
        ((s && s.confirmation_chips) || []).forEach(function (pending) {
            if (pending.state !== 'pending') return;
            var replacement = {
                field: pending.field,
                question: pending.message || ('Confirm ' + pending.field),
                chip_id: pending.chip_id,
                proposed_value: pending.proposed_value,
                options: pending.options || [],
                required: pending.field === 'confirmed_origin_airport' ||
                    pending.field === 'confirmed_destination_airport' ||
                    (pending.field === 'passport_country' &&
                     !!findApproval(s, 'approve_booking'))
            };
            var found = -1;
            for (var p = 0; p < questions.length; p++) {
                if (questions[p].field === pending.field) { found = p; break; }
            }
            if (found === -1) questions.push(replacement);
            else questions[found] = Object.assign({}, questions[found], replacement);
        });
        return questions;
    }

    function firstUnansweredQuestion(s) {
        var questions = clarificationQuestions(s);
        for (var i = 0; i < FIELD_ORDER.length; i++) {
            for (var j = 0; j < questions.length; j++) {
                var q = questions[j];
                if (q.field !== FIELD_ORDER[i]) continue;
                if (Trip.answeredChips[q.field]) continue;
                if (Trip.deferredSkip[q.field]) continue;
                return q;
            }
        }
        // hostile/unknown field names still surface (F9), after known ones
        for (var k = 0; k < questions.length; k++) {
            var qq = questions[k];
            if (!qq.field || FIELD_ORDER.indexOf(qq.field) !== -1) continue;
            if (Trip.answeredChips[qq.field] || Trip.deferredSkip[qq.field]) continue;
            return qq;
        }
        return null;
    }

    function renderQuestionCards(s) {
        var wrap = byId('trip-clarify-chips');
        var desired = firstUnansweredQuestion(s);
        var existing = wrap.querySelector('.aj-question-card');
        if (existing) {
            var ef = existing.getAttribute('data-chip-field');
            // keep an in-progress card untouched (never lose typed input);
            // a confirmed card clears the way for the next question
            if (existing.classList.contains('confirmed') ||
                    (desired && ef !== desired.field) || !desired) {
                if (!desired || ef !== desired.field ||
                        existing.classList.contains('confirmed')) {
                    wrap.removeChild(existing);
                }
            }
        }
        if (desired && !chipByField(wrap, desired.field)) {
            buildQuestionCard(wrap, desired);
        }
    }

    function buildQuestionCard(wrap, q) {
        var field = q.field;
        // NB: do NOT mark Trip.answeredChips here — that flag means
        // "confirmed answer"; presence is guarded by the chipByField
        // DOM scan in renderQuestionCards.
        var isProfile = PROFILE_CHIP_FIELDS.indexOf(field) !== -1;
        var card = el('div', 'trip-chip aj-question-card');
        card.setAttribute('data-chip-field', field);
        if (q.chip_id) card.setAttribute('data-confirmation-chip-id', q.chip_id);
        tid(card, 'trip-chip-' + field);
        card.setAttribute('role', 'group');
        var qid = 'aj-q-' + (FIELD_ORDER.indexOf(field) !== -1
            ? FIELD_ORDER.indexOf(field) : 'x');
        card.setAttribute('aria-labelledby', qid);

        card.appendChild(el('div', 'aj-question-kicker',
            isProfile ? 'Save to your details?' : 'One quick question'));
        var question = el('h4', 'trip-chip-q aj-question-text', q.question);
        question.id = qid;
        card.appendChild(question);
        card.appendChild(el('p', 'aj-question-why',
            FIELD_WHY[field] || 'Needed to finish your plan.'));
        if (isProfile) {
            card.appendChild(el('p', 'aj-question-consent',
                'Only saved with your consent \u2014 you can delete it any time.'));
        }

        var row = el('div', 'trip-chip-row');
        var input;
        if ((q.options || []).length) {
            input = el('select', 'trip-chip-input aj-question-input');
            var placeholder = el('option', '', 'Choose one');
            placeholder.value = ''; placeholder.disabled = true;
            placeholder.selected = true;
            input.appendChild(placeholder);
            q.options.forEach(function (value) {
                var opt = el('option', '', String(value));
                opt.value = String(value);
                input.appendChild(opt);
            });
        } else {
            input = el('input', 'trip-chip-input aj-question-input');
            input.type = 'text';
            input.placeholder = field === 'passport_country' ? 'e.g. MM' : 'your answer';
        }
        if (q.proposed_value != null) {
            input.value = confirmationValue(q.proposed_value);
            card.setAttribute('data-confirmation-proposed', input.value);
        }
        tid(input, 'chip-input-' + field);
        input.setAttribute('data-testid-aj', 'aj-question-input');
        if (Trip.deferredValue[field] !== undefined) {
            input.value = Trip.deferredValue[field]; // Back never loses data
        }
        var btn = el('button', 'trip-chip-confirm aj-question-save', 'Save & continue');
        btn.type = 'button';
        tid(btn, 'chip-confirm-' + field);
        btn.setAttribute('data-testid-aj', 'aj-question-save');
        btn.addEventListener('click', function () { confirmChip(field, card, input, btn); });
        input.addEventListener('keydown', function (ev) {
            if (ev.key === 'Enter') { ev.preventDefault(); btn.click(); }
        });
        row.appendChild(input);
        row.appendChild(btn);
        card.appendChild(row);

        var footer = el('div', 'aj-question-footer');
        if (q.required) {
            footer.appendChild(el('span', 'aj-question-required',
                'Required before a booking can be approved.'));
        } else {
            var back = el('button', 'aj-question-back', 'Back');
            back.type = 'button';
            tid(back, 'aj-question-back');
            back.addEventListener('click', function () { deferQuestion(field); });
            footer.appendChild(back);
        }
        card.appendChild(footer);
        wrap.appendChild(card);
        input.focus();
    }

    // Back returns to the composer/facts; the entered value is preserved and
    // the question re-surfaces as a pending fact chip (§4).
    function deferQuestion(field) {
        var wrap = byId('trip-clarify-chips');
        var card = chipByField(wrap, field);
        if (card) {
            var input = card.querySelector('input');
            if (input) Trip.deferredValue[field] = input.value;
            wrap.removeChild(card);
        }
        Trip.answeredChips[field] = false;
        Trip.deferredSkip[field] = true;
        if (Trip.lastState) renderFacts(Trip.lastState);
        var composer = byId('trip-goal-input');
        if (composer) composer.focus();
    }

    function reopenQuestion(field) {
        Trip.deferredSkip[field] = false;
        Trip.answeredChips[field] = false;
        if (Trip.lastState) {
            renderQuestionCards(Trip.lastState);
            renderFacts(Trip.lastState);
        }
    }

    function confirmationValue(value) {
        if (value && typeof value === 'object' && value.start) {
            return value.start + (value.end ? ' to ' + value.end : '');
        }
        return String(value == null ? '' : value);
    }

    async function confirmChip(field, chip, input, btn) {
        var value = input.value.trim();
        if (!value) { input.focus(); return; }
        btn.disabled = true;
        try {
            var confirmationId = chip.getAttribute('data-confirmation-chip-id');
            if (!confirmationId) {
                invalidatePolls();
                var answers = {};
                answers[field] = value;
                var proposal = await api(
                    '/api/trips/' + Trip.tripId + '/clarifications',
                    jsonOpts('POST', { answers: answers }));
                var pending = (proposal.confirmation_chips || []).find(
                    function (candidate) { return candidate.field === field; });
                if (!pending) throw new Error('The confirmation could not be prepared.');
                confirmationId = pending.chip_id;
                var proposed = confirmationValue(pending.proposed_value);
                chip.setAttribute('data-confirmation-chip-id', confirmationId);
                if (proposed) {
                    input.value = proposed;
                    chip.setAttribute('data-confirmation-proposed', proposed);
                }
                btn.textContent = 'Confirm this answer';
                btn.disabled = false;
                input.focus();
                announce('Check the answer, then confirm it to continue.');
                return;
            }
            invalidatePolls();
            var proposedValue = chip.getAttribute('data-confirmation-proposed');
            var decision = proposedValue !== null && value === proposedValue
                ? 'confirm' : 'corrected';
            var decisionBody = { decision: decision };
            if (decision === 'corrected') decisionBody.corrected_value = value;
            var ack = await api(
                '/api/trips/' + Trip.tripId + '/confirmations/' +
                encodeURIComponent(confirmationId),
                jsonOpts('POST', decisionBody));
            btn.textContent = '\u2713 confirmed';
            chip.classList.add('confirmed');
            input.disabled = true;
            Trip.answeredChips[field] = true;   // answered → never re-ask
            Trip.answeredFacts[field] = value;
            delete Trip.deferredValue[field];
            addChat('agent', (FACT_LABELS[field] || field) + ': ' + value +
                             (PROFILE_CHIP_FIELDS.indexOf(field) !== -1
                                 ? ' \u2014 confirmed and saved to your details.'
                                 : ' \u2014 confirmed for this trip.'));
            announce((FACT_LABELS[field] || 'Answer') +
                     ' confirmed. Continuing your trip plan.');
            if (Trip.lastState) renderFacts(Trip.lastState);
            refreshProfile();
            // a chip answer can resume a terminal (failed) trip — the watcher
            // was stopped on the terminal render, so restart it; otherwise a
            // single poll picks the change up
            if (ack && ack.state) {
                Trip.terminal = false;
                renderState(ack.state);
            } else if (Trip.terminal) {
                Trip.terminal = false; startWatching();
            } else { pollState(); }
        } catch (err) {
            btn.disabled = false;
            btn.textContent = 'Retry';
            showError('Saving ' + (FACT_LABELS[field] || field) + ' failed: ' +
                      plainError(err));
        }
    }

    // --- scope clarification: exactly three choices -----------------------------------

    function tripFactsOutstanding(s) {
        var clarify = ((s && s.outputs) || {}).clarify || null;
        var questions = (clarify && clarify.questions) || [];
        for (var i = 0; i < questions.length; i++) {
            var f = questions[i].field;
            if (['origin_city', 'dest_city', 'date_window'].indexOf(f) === -1) continue;
            if (!Trip.answeredFacts[f]) return true;
        }
        return false;
    }

    function renderScopeChoices(s) {
        var block = byId('trip-scope-block');
        var approval = findApproval(s, 'scope_clarification');
        // One question at a time: the scope card appears once the trip facts
        // (from/to/dates) are answered AND no question card is active
        // (one primary action per screen; deferred questions don't block).
        if (!approval || tripFactsOutstanding(s) || firstUnansweredQuestion(s)) {
            block.hidden = true;
            return;
        }
        if (!block.hidden && block.getAttribute('data-approval-id') === approval.approval_id) return;
        clear(block);
        block.hidden = false;
        block.setAttribute('data-approval-id', approval.approval_id);
        block.appendChild(el('div', 'trip-block-title aj-scope-title',
            'How far should we go?'));
        block.appendChild(el('p', 'trip-scope-hint',
            'Pick one \u2014 nothing is booked until you say so.'));
        var grid = el('div', 'trip-scope-grid');
        (approval.options || []).forEach(function (opt) {
            var choice = opt.choice;
            var card = el('button', 'trip-scope-choice');
            card.type = 'button';
            tid(card, 'scope-choice-' + choice);
            card.appendChild(el('span', 'trip-scope-label', opt.label || choice));
            card.addEventListener('click', function () { chooseScope(approval, choice, block); });
            grid.appendChild(card);
        });
        block.appendChild(grid);
    }

    async function chooseScope(approval, choice, block) {
        block.querySelectorAll('.trip-scope-choice').forEach(function (b) { b.disabled = true; });
        try {
            invalidatePolls(); // in-flight snapshots are pre-resolution: stale
            await api('/api/trip/' + Trip.tripId + '/approvals/' + approval.approval_id,
                      jsonOpts('POST', { decision: choice, value: { choice: choice } }));
            var label = choice;
            (approval.options || []).forEach(function (o) {
                if (o.choice === choice) label = o.label || choice;
            });
            addChat('agent', 'Got it \u2014 ' + label + '. Continuing your plan.');
            announce('Scope chosen. Continuing your plan.');
            block.hidden = true;
            pollState();
        } catch (err) {
            block.querySelectorAll('.trip-scope-choice').forEach(function (b) { b.disabled = false; });
            showError('Scope choice failed: ' + plainError(err));
        }
    }

    // --- requested services chips (editable, never auto-added; spec §3) ------

    function renderServices(s) {
        var box = byId('aj-requested-services');
        var rs = (((s && s.outputs) || {}).clarify || {}).requested_services || null;
        var names = [];
        if (rs) {
            Object.keys(SERVICE_LABELS).forEach(function (k) {
                if (rs[k] === 'requested') names.push(k);
            });
        }
        // Provisional starter choices stay visible until the user locks a
        // scope — an all-'unknown' server snapshot never hides their intent.
        if (!names.length && Trip.provServices) {
            names = Trip.provServices.slice();
        }
        names = names.filter(function (n) { return !Trip.removedServices[n]; });
        clear(box);
        if (!names.length) { box.hidden = true; return; }
        box.hidden = false;
        box.appendChild(el('span', 'aj-services-label', 'Planning:'));
        names.forEach(function (name) {
            var chipRow = el('span', 'aj-service-chip');
            tid(chipRow, 'aj-service-chip-' + name);
            chipRow.appendChild(el('span', 'aj-service-name', SERVICE_LABELS[name] || name));
            var rm = el('button', 'aj-service-remove', '\u00D7');
            rm.type = 'button';
            rm.setAttribute('aria-label', 'Remove ' + (SERVICE_LABELS[name] || name));
            tid(rm, 'aj-service-remove-' + name);
            rm.addEventListener('click', function () {
                Trip.removedServices[name] = true;
                renderServices(Trip.lastState);
                announce((SERVICE_LABELS[name] || name) +
                         ' removed from view. The final scope locks when you answer \u201cHow far should we go?\u201d');
            });
            chipRow.appendChild(rm);
            box.appendChild(chipRow);
        });
    }

    // --- confirmed facts summary (spec §4) ------------------------------------

    function renderFacts(s) {
        var box = byId('aj-facts-summary');
        clear(box);
        var any = false;
        FIELD_ORDER.forEach(function (field) {
            if (Trip.deferredSkip[field]) {
                any = true;
                var pend = el('span', 'aj-fact aj-fact-pending');
                tid(pend, 'aj-fact-' + field);
                pend.appendChild(el('span', 'aj-fact-text',
                    (FACT_LABELS[field] || field) + ': answer needed'));
                var openBtn = el('button', 'aj-fact-edit', '\u270E');
                openBtn.type = 'button';
                openBtn.setAttribute('aria-label', 'Answer ' + (FACT_LABELS[field] || field));
                tid(openBtn, 'aj-fact-edit-' + field);
                openBtn.addEventListener('click', function () { reopenQuestion(field); });
                pend.appendChild(openBtn);
                box.appendChild(pend);
            } else if (Trip.answeredFacts[field] !== undefined) {
                any = true;
                var fact = el('span', 'aj-fact');
                tid(fact, 'aj-fact-' + field);
                fact.appendChild(el('span', 'aj-fact-text',
                    (FACT_LABELS[field] || field) + ': ' + Trip.answeredFacts[field]));
                var editBtn = el('button', 'aj-fact-edit', '\u270E');
                editBtn.type = 'button';
                editBtn.setAttribute('aria-label', 'Edit ' + (FACT_LABELS[field] || field));
                tid(editBtn, 'aj-fact-edit-' + field);
                editBtn.addEventListener('click', function () {
                    Trip.deferredValue[field] = Trip.answeredFacts[field];
                    reopenQuestion(field);
                });
                fact.appendChild(editBtn);
                box.appendChild(fact);
            }
        });
        // D6: remembered home city is an EDITABLE confirmed fact, never
        // leaked into greeting prose.
        if (!any && !Trip.tripId && Trip.homeCityProfile) {
            any = true;
            var home = el('span', 'aj-fact');
            tid(home, 'aj-fact-home_city');
            home.appendChild(el('span', 'aj-fact-text', 'From: ' + Trip.homeCityProfile));
            var homeEdit = el('button', 'aj-fact-edit', '\u270E');
            homeEdit.type = 'button';
            homeEdit.setAttribute('aria-label', 'Edit your home city');
            tid(homeEdit, 'aj-fact-edit-home_city');
            homeEdit.addEventListener('click', openDrawer);
            home.appendChild(homeEdit);
            box.appendChild(home);
        }
        box.hidden = !any;
    }


    // --- entry requirements (renamed visa panel; spec §1.2/§5.1) ------------
    // Warnings (degraded/stale) are NEVER hidden — amber, above the fold of
    // Review. Raw citations move into the collapsed "Sources" disclosure.

    function chip(text, cls, testid) {
        var c = el('span', 'trip-honesty-chip ' + cls, text);
        if (testid) tid(c, testid);
        return c;
    }

    function renderVisaPanel(s) {
        var visa = ((s && s.outputs) || {}).visa_check || null;
        var block = byId('trip-visa-block');
        if (!visa) { block.hidden = true; return; }
        clear(block);
        block.hidden = false;
        tid(block, 'trip-visa-panel');

        var head = el('div', 'trip-block-head');
        head.appendChild(el('span', 'trip-block-title', 'Check entry requirements'));
        var fresh = visa.freshness_state || 'unknown';
        if (visa.degraded || visa.baseline_only) {
            head.appendChild(chip('\u26A0 degraded \u00B7 baseline, unverified', 'trip-chip-warn', 'visa-degraded-warning'));
        } else if (fresh === 'stale') {
            head.appendChild(chip('\u26A0 stale visa data \u2014 re-verify before booking', 'trip-chip-warn', 'visa-stale-warning'));
        } else if (fresh === 'fresh') {
            head.appendChild(chip('verified fresh', 'trip-chip-good', 'visa-fresh-chip'));
        } else {
            head.appendChild(chip('freshness unknown', 'trip-chip-warn', 'visa-unknown-chip'));
        }
        block.appendChild(head);

        if (visa.visa_blocked) {
            block.appendChild(chip('BLOCKED ROUTE \u2014 booking refused, no override', 'trip-chip-danger', 'visa-blocked-chip'));
        }

        var reqs = el('ul', 'trip-visa-reqs');
        (visa.requirements || []).forEach(function (r) {
            var li = el('li', 'trip-visa-req trip-risk-' + (r.risk_level || 'info'));
            li.appendChild(el('span', 'trip-visa-kind', (r.kind || 'entry') + ' \u00B7 ' + (r.country || '')));
            li.appendChild(el('span', 'trip-visa-name', r.name || ''));
            if (r.as_of) li.appendChild(el('span', 'trip-visa-asof', 'Last checked ' + r.as_of));
            reqs.appendChild(li);
        });
        block.appendChild(reqs);
        // citations intentionally rendered by renderSources (collapsed)
    }

    // "Sources" disclosure: raw citations + Last checked (§5.1 translations).
    function renderSources(s) {
        var body = byId('aj-sources-body');
        var out = (s && s.outputs) || {};
        var visa = out.visa_check || null;
        var search = out.flight_search || null;
        clear(body);
        if (search) {
            var fs = el('div', 'aj-source-item');
            fs.appendChild(el('span', 'aj-source-title', 'Flight options \u00B7 Atlas Sandbox'));
            fs.appendChild(el('span', 'aj-source-url', search.source_url || ''));
            fs.appendChild(el('span', 'aj-source-date',
                'Last checked ' + (search.retrieved_date || '?')));
            body.appendChild(fs);
        }
        ((visa && visa.citations) || []).forEach(function (c) {
            var item = el('div', 'aj-source-item');
            item.appendChild(el('span', 'aj-source-title', c.title || c.url));
            item.appendChild(el('span', 'aj-source-url', c.url || '')); // text only — hostile data
            item.appendChild(el('span', 'aj-source-date',
                'Last checked ' + (c.retrieved_date || '?')));
            body.appendChild(item);
        });
        if (!body.childNodes.length) {
            body.appendChild(el('p', 'aj-source-empty', 'No sources yet.'));
        }
    }

    // --- flight options: max 3 ranked + Show more (spec §5.3) ----------------

    function optionReason(options, idx) {
        // Derived ONLY from returned data — never invented.
        var cheapest = 0;
        for (var i = 1; i < options.length; i++) {
            if ((options[i].price && options[i].price.amount || 0) <
                    (options[cheapest].price && options[cheapest].price.amount || 0)) {
                cheapest = i;
            }
        }
        if (idx === 0 && cheapest === 0) return 'Best overall \u2014 shortest flight at the lowest price';
        if (idx === 0) return 'Best overall \u2014 shortest flight';
        if (idx === cheapest) return 'Lowest price';
        return 'Good balance of time and price';
    }

    function renderOptions(s) {
        var search = ((s && s.outputs) || {}).flight_search || null;
        var container = byId('trip-options');
        var options = (search && search.options) || [];
        var ids = options.map(function (o) { return o.id; }).join(',');
        // null sentinel: an empty-options render must still clear stale cards.
        if (ids === Trip.renderedOptionIds && Trip.renderedOptionIds !== null) return;
        Trip.renderedOptionIds = ids;
        // a Show-more re-render keeps the expanded cap; only NEW option sets
        // collapse back to the ranked top-3
        if (!Trip.preserveOptionCap) Trip.shownOptions = 3;
        Trip.preserveOptionCap = false;
        clear(container);
        var summary = byId('aj-step-2-summary');
        if (options.length === 0) {
            var optEmpty = el('div', 'trip-empty',
                Trip.tripId ? 'Searching the Atlas Sandbox\u2026'
                            : 'No flight options yet \u2014 tell us your travel goal to begin.');
            tid(optEmpty, 'trip-options-empty');
            container.appendChild(optEmpty);
            if (summary) summary.textContent = Trip.tripId
                ? 'Searching flights\u2026' : 'No flight options yet';
            return;
        }
        if (summary) summary.textContent = options.length + ' flight' +
            (options.length === 1 ? '' : 's') + ' found';
        // G4-DA-fix F5 honesty: a substituted date window is surfaced, never
        // presented silently as the requested dates (wraps inside container).
        if (search.date_note) {
            container.appendChild(chip('\u26A0 ' + search.date_note,
                                       'trip-chip-warn', 'trip-date-note'));
        }
        var extraBtn = null;
        options.forEach(function (o, idx) {
            var card = el('div', 'trip-option-card aj-option-card');
            tid(card, 'trip-option-card');           // legacy pinned testid
            tidAj(card, 'aj-option-card-' + (idx + 1));
            if (idx >= Trip.shownOptions) card.classList.add('is-extra', 'hidden-extra');
            var rank = el('div', 'aj-option-rank-row');
            rank.appendChild(el('span', 'aj-option-rank', '#' + (idx + 1)));
            var reason = el('span', 'aj-option-reason', optionReason(options, idx));
            tid(reason, 'aj-option-reason-' + (idx + 1));
            rank.appendChild(reason);
            card.appendChild(rank);
            var top = el('div', 'trip-option-top');
            var carrierName = CARRIER_NAMES[o.carrier] || o.carrier || '?';
            var carrierLabel = carrierName + (CARRIER_NAMES[o.carrier] ? ' (' + o.carrier + ')' : '');
            top.appendChild(el('span', 'trip-option-carrier', carrierLabel));
            top.appendChild(el('span', 'trip-option-flight', o.flight_no));
            top.appendChild(chip('Atlas Sandbox data', 'trip-chip-sandbox'));
            card.appendChild(top);
            var route = el('div', 'trip-option-route');
            route.appendChild(el('span', 'trip-option-code', (o.dep && o.dep.airport) || '?'));
            route.appendChild(el('span', 'trip-option-arrow', '\u2192'));
            route.appendChild(el('span', 'trip-option-code', (o.arr && o.arr.airport) || '?'));
            route.appendChild(el('span', 'trip-option-dur',
                Math.floor((o.duration_min || 0) / 60) + 'h ' + ((o.duration_min || 0) % 60) + 'm'));
            card.appendChild(route);
            var times = el('div', 'trip-option-times');
            times.appendChild(el('span', '', hhmm(o.dep && o.dep.time)));
            times.appendChild(el('span', '', hhmm(o.arr && o.arr.time)));
            card.appendChild(times);
            var price = el('div', 'trip-option-price');
            price.appendChild(el('span', 'trip-option-sgd', priceNative(o.price)));
            var secondary = priceSecondary(o.price);
            if (secondary) {
                price.appendChild(el('span', 'trip-option-thb', secondary));
            }
            card.appendChild(price);
            var choose = el('button', 'aj-option-select', 'Choose this flight');
            choose.type = 'button';
            tid(choose, 'aj-option-select-' + (idx + 1));
            choose.addEventListener('click', function () { selectOption(o, card); });
            card.appendChild(choose);
            container.appendChild(card);
        });
        if (options.length > Trip.shownOptions) {
            extraBtn = el('button', 'aj-show-more',
                'Show more flights (' + (options.length - Trip.shownOptions) + ' more)');
            extraBtn.type = 'button';
            tid(extraBtn, 'aj-show-more-options');
            extraBtn.addEventListener('click', function () {
                Trip.shownOptions += 3;
                renderOptionsForce(s);
            });
            container.appendChild(extraBtn);
        }
    }

    function renderOptionsForce(s) {
        Trip.renderedOptionIds = null; // force re-render with new cap
        Trip.preserveOptionCap = true;
        renderOptions(s);
    }

    function selectOption(option, card) {
        Trip.selectedOptionId = option.id || null;
        var container = byId('trip-options');
        container.querySelectorAll('.trip-option-card').forEach(function (c) {
            c.classList.remove('is-selected');
        });
        card.classList.add('is-selected');
        announce('Selected ' + (option.carrier || '') + ' ' + (option.flight_no || '') +
                 '. Review your plan when you\u2019re ready.');
        if (Trip.lastState && findApproval(Trip.lastState, 'approve_booking')) {
            editStep(4);
        }
    }

    // --- step rail + review/confirm surfaces ----------------------------------

    function chosenOption(s) {
        var out = (s && s.outputs) || {};
        var rec = ((out.booking || {}).booking) || {};
        if (rec.option) return rec.option;
        var list = ((out.flight_search || {}).options) || [];
        for (var i = 0; i < list.length; i++) {
            if (list[i].id === Trip.selectedOptionId) return list[i];
        }
        return list[0] || null;
    }

    function optionLine(o) {
        if (!o) return '';
        return ((o.carrier || '') + ' ' + (o.flight_no || '')).trim() + ' \u00B7 ' +
            ((o.dep && o.dep.airport) || '?') + ' \u2192 ' + ((o.arr && o.arr.airport) || '?') +
            ' \u00B7 ' + hhmm(o.dep && o.dep.time) + ' \u2013 ' + hhmm(o.arr && o.arr.time);
    }

    function renderReview(s) {
        var out = (s && s.outputs) || {};
        var search = out.flight_search || null;
        var summary = byId('aj-review-summary');
        var total = byId('aj-review-total');
        clear(summary);
        clear(total);
        if (!search) return;
        var opts = search.options || [];
        var line1 = el('div', 'aj-review-line');
        line1.appendChild(el('span', 'aj-review-key', 'Your goal'));
        line1.appendChild(el('span', 'aj-review-val', Trip.goalText || '\u2014'));
        summary.appendChild(line1);
        var line2 = el('div', 'aj-review-line');
        line2.appendChild(el('span', 'aj-review-key', 'Flights found'));
        line2.appendChild(el('span', 'aj-review-val',
            opts.length + ' option' + (opts.length === 1 ? '' : 's') +
            ' in the Atlas Sandbox'));
        summary.appendChild(line2);
        var chosen = Trip.selectedOptionId ? chosenOption(s) : null;
        if (chosen) {
            var line3 = el('div', 'aj-review-line');
            line3.appendChild(el('span', 'aj-review-key', 'Your flight'));
            line3.appendChild(el('span', 'aj-review-val', optionLine(chosen)));
            summary.appendChild(line3);
            total.textContent = 'Total (indicative): ' + priceNative(chosen.price) +
                (priceSecondary(chosen.price) ? ' \u00B7 ' + priceSecondary(chosen.price) : '');
        } else if (opts.length) {
            var from = opts.reduce(function (m, o) {
                var a = (o.price && o.price.amount) || 0;
                return m === null || a < m ? a : m;
            }, null);
            total.textContent = 'From ' + priceNative(opts[0] && { amount: from, currency: (opts[0].price || {}).currency });
        }
    }

    function renderConfirm(s) {
        var approval = findApproval(s, 'approve_booking');
        var summary = byId('aj-confirm-summary');
        var priceEl = byId('aj-confirm-price');
        var paxEl = byId('aj-confirm-pax');
        clear(summary);
        priceEl.textContent = '';
        paxEl.textContent = '';
        if (!approval) return;
        var chosen = chosenOption(s);
        if (chosen) {
            var line = el('div', 'aj-review-line');
            line.appendChild(el('span', 'aj-review-key', 'Flight'));
            line.appendChild(el('span', 'aj-review-val', optionLine(chosen)));
            summary.appendChild(line);
            priceEl.textContent = 'Price snapshot: ' + priceNative(chosen.price) +
                (priceSecondary(chosen.price) ? ' \u00B7 ' + priceSecondary(chosen.price) : '');
        } else {
            summary.appendChild(el('div', 'aj-review-line', null));
            summary.lastChild.appendChild(el('span', 'aj-review-val',
                (approval.options || []).length + ' sandbox options ready \u2014 pick one below.'));
        }
        paxEl.textContent = 'Travellers: 1';
        var conseq = el('div', 'aj-confirm-consequence');
        conseq.textContent = chosen
            ? ('Approving requests an Atlas Sandbox booking for ' + (chosen.carrier || '') + ' ' + (chosen.flight_no || '') +
               ', ' + ((chosen.dep && chosen.dep.airport) || '?') + ' \u2192 ' +
               ((chosen.arr && chosen.arr.airport) || '?') + '. A PNR exists only if Atlas confirms it. ' +
               'You can still change plans before you approve.')
            : 'Approving requests a booking for your chosen Atlas Sandbox offer. No PNR is invented if ticketing is unavailable.';
        summary.appendChild(conseq);
    }

    function renderStepRail(s, cur) {
        var expanded = {};
        expanded[cur] = true;
        if (cur === 4) expanded[3] = true; // review stays visible at confirm
        var summaries = {
            1: Trip.goalText ? ('Goal: ' + truncate(Trip.goalText, 48)) : '',
            2: stepSummary2(s),
            3: stepSummary3(s),
            4: stepSummary4(s),
            5: stepSummary5(s)
        };
        for (var n = 1; n <= 5; n++) {
            var li = byId('aj-step-' + n);
            if (!li) continue;
            var body = byId('aj-step-' + n + '-body');
            var editBtn = byId('aj-step-' + n + '-edit');
            var sum = byId('aj-step-' + n + '-summary');
            var isExpanded = !!expanded[n];
            var isFuture = !isExpanded && n > cur;
            var isDone = !isExpanded && n < cur;
            li.classList.toggle('is-current', isExpanded);
            li.classList.toggle('is-done', isDone);
            li.classList.toggle('is-future', isFuture);
            if (isFuture) li.setAttribute('aria-disabled', 'true');
            else li.removeAttribute('aria-disabled');
            if (body) body.hidden = !isExpanded;
            if (editBtn) editBtn.hidden = !isDone;
            if (sum) sum.textContent = isExpanded ? '' : (summaries[n] || '');
        }
        var current = byId('aj-step-' + cur);
        if (current) tid(current, 'aj-step-' + cur); // keep pinned testid
        var mark = byId('aj-shell');
        if (mark) mark.setAttribute('data-aj-step', String(cur));
    }

    function truncate(text, n) {
        return text.length > n ? text.slice(0, n - 1) + '\u2026' : text;
    }
    function stepSummary2(s) {
        var opts = ((((s && s.outputs) || {}).flight_search) || {}).options;
        if (!opts || !opts.length) return '';
        return opts.length + ' flight options found';
    }
    function stepSummary3(s) {
        var visa = (((s && s.outputs) || {}).visa_check) || null;
        if (!visa) return '';
        if (visa.degraded || visa.baseline_only) return 'Entry requirements checked \u2014 needs re-verification';
        if (visa.freshness_state === 'stale') return 'Entry requirements checked \u2014 data is stale';
        return 'Entry requirements checked';
    }
    function stepSummary4(s) {
        if (findApproval(s, 'approve_booking')) return 'Waiting for your approval';
        if ((((s && s.outputs) || {}).booking)) return 'Approved';
        return '';
    }
    function stepSummary5(s) {
        var booking = (((s && s.outputs) || {}).booking) || null;
        if (booking) return 'Booked \u2014 reference ' + (booking.pnr || '');
        if ((((s && s.outputs) || {}).recovery)) return 'Something changed \u2014 review your options';
        return '';
    }

    // --- Living Journey Line (spec §7; classes onto static SVG) --------------

    function renderJourneyLine(s, cur) {
        var line = byId('aj-journey-line');
        var mobile = byId('aj-line-mobile');
        var st = 'empty';
        if (Trip.tripId && s) {
            var out = s.outputs || {};
            if (out.recovery || findApproval(s, 'recovery_booking')) st = 'disrupted';
            else if (out.booking) st = 'confirmed';
            else if (cur === 4) st = 's3';
            else if (cur === 3) st = 's2';
            else if (cur === 2) st = 's1';
            else st = (s.status === 'running') ? 'drawing' : 'origin';
        }
        if (line.getAttribute('data-state') !== st) line.setAttribute('data-state', st);
        if (mobile) mobile.setAttribute('data-state', st);
        var label = byId('aj-line-mobile-label');
        if (label) {
            label.textContent = !Trip.tripId ? 'Plan your trip to begin'
                : (st === 'disrupted' ? 'Recovery \u2014 review your options'
                : (STEP_TITLES[(cur || 1) - 1] || ''));
        }
        // ONE restrained confirmation pulse (spec §7.2), never under
        // prefers-reduced-motion, never repeating.
        if (st === 'confirmed' && !Trip.pulsed) {
            Trip.pulsed = true;
            if (!reducedMotion()) {
                var node = byId('aj-node-5');
                node.classList.add('aj-pulse');
                window.setTimeout(function () { node.classList.remove('aj-pulse'); }, 1100);
            }
        }
    }

    // --- approval gate (L2) -----------------------------------------------------

    function renderApprovalGate(s) {
        var banner = byId('trip-approval-banner');
        var overlay = byId('trip-approval-overlay');
        var approval = findApproval(s, 'approve_booking');
        if (!approval) {
            banner.hidden = true;
            if (overlay.hidden === false) untrapDialog(overlay);
            Trip.approval = null;
            return;
        }
        if (Trip.approval && Trip.approval.approval_id === approval.approval_id) return;
        Trip.approval = approval;
        Trip.selectedOptionId = null;
        clear(banner);
        banner.hidden = false;
        banner.appendChild(el('div', 'trip-block-title', 'Ready to book'));
        var row = el('div', 'trip-banner-row');
        row.appendChild(el('span', 'trip-banner-text',
            'Your flight ' + ((approval.options || []).length > 1 ? 'options are' : 'option is') +
            ' ready. Nothing is booked until you approve.'));
        var openBtn = el('button', 'btn-trip-go trip-banner-open', 'Approve Sandbox booking');
        openBtn.type = 'button';
        tid(openBtn, 'approval-open');
        openBtn.addEventListener('click', openApprovalModal);
        row.appendChild(openBtn);
        banner.appendChild(row);
    }

    function openApprovalModal() {
        var approval = Trip.approval;
        if (!approval) return;
        var overlay = byId('trip-approval-overlay');
        var opts = approval.options || [];
        var list = byId('trip-approval-options');
        clear(list);
        byId('trip-approval-note').hidden = true;
        opts.forEach(function (o, idx) {
            var btn = el('button', 'trip-approval-option');
            btn.type = 'button';
            tid(btn, 'approval-option-' + (o.id || idx));
            btn.setAttribute('data-option-id', o.id || '');
            btn.appendChild(el('span', 'trip-option-carrier', o.carrier || ''));
            btn.appendChild(el('span', 'trip-option-flight', o.flight_no || ''));
            var routeTxt = ((o.dep && o.dep.airport) || '?') + ' \u2192 ' + ((o.arr && o.arr.airport) || '?');
            btn.appendChild(el('span', 'trip-approval-route', routeTxt));
            btn.appendChild(el('span', 'trip-option-sgd', priceNative(o.price)));
            btn.addEventListener('click', function () { selectApprovalOption(btn, o.id); });
            list.appendChild(btn);
            // sensible default: previously chosen card, else first — still explicit
            if ((Trip.selectedOptionId && o.id === Trip.selectedOptionId) ||
                    (!Trip.selectedOptionId && idx === 0)) {
                selectApprovalOption(btn, o.id);
            }
        });
        trapDialog(overlay);
        byId('trip-approval-approve').focus();
    }

    function selectApprovalOption(btn, optionId) {
        Trip.selectedOptionId = optionId;
        var list = byId('trip-approval-options');
        list.querySelectorAll('.trip-approval-option').forEach(function (b) {
            b.classList.remove('selected');
            b.setAttribute('aria-pressed', 'false');
        });
        btn.classList.add('selected');
        btn.setAttribute('aria-pressed', 'true');
    }

    async function resolveApproval(decision) {
        if (!Trip.approval) return;
        if (decision === 'approve' && !Trip.selectedOptionId) {
            var note = byId('trip-approval-note');
            note.textContent = 'Pick one of the flights above first.';
            note.hidden = false;
            return;
        }
        var approveBtn = byId('trip-approval-approve');
        var rejectBtn = byId('trip-approval-reject');
        var approveIdleText = approveBtn.textContent;
        approveBtn.disabled = true;
        rejectBtn.disabled = true;
        approveBtn.textContent = decision === 'approve'
            ? 'Checking safety & booking…' : 'Working…';
        announce(decision === 'approve'
            ? 'Checking current safety information before booking.'
            : 'Keeping your trip unbooked.');
        try {
            invalidatePolls(); // in-flight snapshots predate this decision
            var payload = { decision: decision };
            if (decision === 'approve') payload.value = { option_id: Trip.selectedOptionId };
            var headers = {};
            if (Trip.approval && (Trip.approval.node_name === 'approve_booking' ||
                    Trip.approval.node_name === 'flight_book' ||
                    Trip.approval.purpose === 'initial_booking')) {
                var approvalId = Trip.approval.approval_id;
                if (!Trip.approvalKeys[approvalId]) {
                    Trip.approvalKeys[approvalId] = generateUUID();
                }
                headers['Idempotency-Key'] = Trip.approvalKeys[approvalId];
            }
            var result = await api('/api/trip/' + Trip.tripId + '/approvals/' + Trip.approval.approval_id,
                                   jsonOpts('POST', payload, headers));
            untrapDialog(byId('trip-approval-overlay'));
            byId('trip-approval-banner').hidden = true;
            Trip.approval = null;
            addChat('agent', decision === 'approve'
                ? 'Approved \u2014 requesting the booking from Atlas Sandbox now.'
                : 'Rejected \u2014 nothing was booked.');
            announce(decision === 'approve' ? 'Approved. Requesting the Sandbox booking now.' : 'Booking rejected. Nothing was booked.');
            if (result && result.error) {
                showError(plainError(result.error));
            }
            pollState();
        } catch (err) {
            if (err.status === 410) {
                // expired-approval state (§9.1): fresh approval from state
                untrapDialog(byId('trip-approval-overlay'));
                Trip.approval = null;
                showStateBox('expired',
                    'That approval link timed out.',
                    'Get a fresh approval', function () {
                        clearStateBox();
                        pollState();
                    });
            } else {
                showError('Approval failed: ' + plainError(err));
            }
        } finally {
            approveBtn.textContent = approveIdleText;
            approveBtn.disabled = false;
            rejectBtn.disabled = false;
            // a disabled-then-re-enabled button loses focus; if the dialog
            // is still open (e.g. safety gate refused the booking) return
            // focus inside it so Escape/keyboard control keep working
            var overlayEl = byId('trip-approval-overlay');
            if (Trip.approval && overlayEl && !overlayEl.hidden) {
                approveBtn.focus();
            }
        }
    }

    // --- My trip: booking status, reference, itinerary (spec §8.5) -------------

    function plainStatus(s) {
        var out = (s && s.outputs) || {};
        if (out.recovery && !((out.recovery).resolved)) return 'Something changed \u2014 review your options';
        if (out.booking) return 'Booked';
        if (findApproval(s, 'approve_booking')) return 'Waiting for your approval';
        if (s && s.status === 'failed') return 'Needs attention';
        if (s && s.status === 'completed') return 'Plan complete';
        return 'Being planned';
    }

    function whatNext(s) {
        var node = (s && s.current_state) || '';
        if ((s && s.status === 'completed')) {
            return ((s.outputs || {}).booking)
                ? 'You\u2019re all set \u2014 we\u2019ll watch this flight for changes.'
                : 'All set \u2014 nothing needs your attention right now.';
        }
        if (s && s.status === 'failed') return 'Answer the open question or try again \u2014 we\u2019ll pick up where we left off.';
        var map = {
            goal_intake: 'We\u2019re understanding your goal\u2026',
            clarify_loop: 'We\u2019re checking we have everything we need\u2026',
            scope_clarification: 'Waiting for you to choose how far we go.',
            flight_search: 'We\u2019re searching flights now. This usually takes a few seconds.',
            visa_check: 'Checking entry requirements for your route\u2026',
            approve_booking: 'Waiting for your approval to book.',
            flight_book: 'Booking your flight in the Atlas Sandbox\u2026',
            itinerary: 'Putting your itinerary together\u2026',
            recovery_booking: 'Review your replacement options below.'
        };
        return map[node] || 'Working on your plan\u2026';
    }

    function renderMyTrip(s) {
        var out = (s && s.outputs) || {};
        var statusEl = byId('aj-booking-status');
        var nextEl = byId('aj-next-action');
        var monEl = byId('aj-monitor-status');
        if (!Trip.tripId) {
            statusEl.hidden = true;
            nextEl.hidden = true;
            monEl.hidden = true;
            return;
        }
        statusEl.hidden = false;
        clear(statusEl);
        statusEl.appendChild(el('span', 'aj-status-key', 'Booking status'));
        statusEl.appendChild(el('span', 'aj-status-val', plainStatus(s)));
        nextEl.hidden = false;
        clear(nextEl);
        nextEl.appendChild(el('span', 'aj-status-key', 'What happens next'));
        nextEl.appendChild(el('span', 'aj-status-val', whatNext(s)));
        var booking = out.booking || null;
        var armed = booking && (booking.monitor_armed ||
            ((booking.booking || {}).monitor_armed));
        monEl.hidden = !armed;
        if (armed) {
            clear(monEl);
            monEl.appendChild(el('span', 'aj-status-key', 'Monitoring'));
            monEl.appendChild(el('span', 'aj-status-val',
                'We\u2019re watching this flight for changes.'));
        }
    }

    // --- Safety card (G4.6) -------------------------------------------------
    // The displayed status is computed server-side by the deterministic
    // SafetyPolicyEngine; this card only renders what the server returns,
    // in beginner-friendly plain language. It never claims anything is
    // absolutely safe and never shows a numeric score.

    var SAFETY_LABELS = {
        normal_precautions: { text: 'Routine precautions \u2014 no special warnings right now', tone: 'ok' },
        increased_caution: { text: 'Be extra careful \u2014 official warnings apply', tone: 'caution' },
        reconsider_travel: { text: 'Official advice says reconsider this trip', tone: 'warn' },
        do_not_travel: { text: 'Official advice says do not travel here', tone: 'block' },
        unable_to_verify: { text: 'We could not verify this destination yet', tone: 'unknown' }
    };

    var SAFETY_CATEGORY_LABELS = {
        severe_weather: 'Severe weather',
        disaster: 'Natural disaster',
        transport_disruption: 'Transport disruption',
        security: 'Security alert',
        health: 'Health event',
        advisory: 'General advisory',
        local_laws: 'Local laws',
        cultural: 'Cultural notes'
    };

    var SAFETY_COUNTRY_NAMES = {
        GB: 'United Kingdom', UK: 'United Kingdom', US: 'United States',
        AU: 'Australia', CA: 'Canada', NZ: 'New Zealand'
    };

    function safetyCountryName(code) {
        if (!code) return 'that country\u2019s';
        var key = String(code).toUpperCase();
        return SAFETY_COUNTRY_NAMES[key] || String(code);
    }

    function safetyDate(iso) {
        if (!iso) return '';
        var d = new Date(iso);
        if (isNaN(d.getTime())) return String(iso);
        return d.toISOString().slice(0, 16).replace('T', ' ') + ' UTC';
    }

    function safetyChip(text, tone, testid) {
        var c = el('span', 'aj-safety-chip aj-safety-chip-' + tone, text);
        if (testid) { tid(c, testid); tidAj(c, testid); }
        return c;
    }

    function safetyTone(level) {
        if (level === 'do_not_travel') return 'block';
        if (level === 'reconsider_travel') return 'warn';
        if (level === 'increased_caution') return 'caution';
        if (level === 'normal_precautions') return 'ok';
        return 'unknown';
    }

    async function renderSafety(s) {
        var card = byId('aj-safety-card');
        if (!Trip.tripId) { card.hidden = true; return; }
        var out = (s && s.outputs) || {};
        var safety = out.safety || null;
        if (safety && safety.assessment) {
            renderSafetyCard(safety, out.safety_events || []);
            return;
        }
        // one-shot fetch only once a destination is known (goal intake done)
        // so the card never fires a doomed request (zero-console contract)
        var goalDone = ((s && s.nodes) || []).some(function (n) {
            return n.name === 'goal_intake' && n.status === 'COMPLETED';
        });
        if (Trip.safetyTried || !out.safety_enabled || !goalDone) return;
        Trip.safetyTried = true;
        try {
            var resp = await api('/api/trip/' + Trip.tripId + '/safety');
            renderSafetyCard({
                assessment: resp.assessment,
                source_reports: resp.source_reports,
                query: resp.query,
                risk_acknowledged: resp.risk_acknowledged,
                monitor_enabled: resp.monitor_enabled,
                checked_at: resp.checked_at
            }, resp.safety_events || []);
        } catch (e) {
            // pipeline disabled or no destination yet — hide honestly
            card.hidden = true;
        }
    }

    function renderSafetyCard(safety, events) {
        var card = byId('aj-safety-card');
        var a = (safety && safety.assessment) || null;
        if (!a) { card.hidden = true; return; }
        card.hidden = false;
        var body = byId('aj-safety-body');
        var acts = byId('aj-safety-actions');
        clear(body); clear(acts);
        byId('aj-safety-checked').textContent = safety.checked_at
            ? 'Checked ' + safetyDate(safety.checked_at) : '';

        // status row
        var label = SAFETY_LABELS[a.overall_status] || SAFETY_LABELS.unable_to_verify;
        var statusRow = el('div', 'aj-safety-row');
        statusRow.appendChild(el('span', 'aj-safety-key', 'Status'));
        statusRow.appendChild(safetyChip(label.text, label.tone, 'aj-safety-status'));
        body.appendChild(statusRow);

        // destination + dates checked (from the query)
        var q = safety.query || {};
        var where = q.destination_country || '';
        if ((q.destination_regions || []).length) {
            where += ' (' + q.destination_regions.join(', ') + ')';
        }
        if (where) {
            var destRow = el('div', 'aj-safety-row');
            destRow.appendChild(el('span', 'aj-safety-key', 'Destination'));
            var destVal = el('span', 'aj-safety-val', where);
            tid(destVal, 'aj-safety-destination'); tidAj(destVal, 'aj-safety-destination');
            destRow.appendChild(destVal);
            body.appendChild(destRow);
        }
        var win = q.travel_window || null;
        if (win && (win.start || win.end)) {
            var dateRow = el('div', 'aj-safety-row');
            dateRow.appendChild(el('span', 'aj-safety-key', 'Dates checked'));
            var dateVal = el('span', 'aj-safety-val',
                (win.start || '?') + ' \u2192 ' + (win.end || '?'));
            tid(dateVal, 'aj-safety-dates'); tidAj(dateVal, 'aj-safety-dates');
            dateRow.appendChild(dateVal);
            body.appendChild(dateRow);
        }

        // why this status was selected + confidence
        if (a.why_selected) {
            body.appendChild(el('div', 'aj-safety-key', 'Why this status'));
            var why = el('p', 'aj-safety-text', a.why_selected);
            tid(why, 'aj-safety-why'); tidAj(why, 'aj-safety-why');
            body.appendChild(why);
        }
        if (a.confidence_or_unable_to_verify) {
            var conf = el('p', 'aj-safety-text aj-safety-muted',
                          a.confidence_or_unable_to_verify);
            tid(conf, 'aj-safety-confidence'); tidAj(conf, 'aj-safety-confidence');
            body.appendChild(conf);
        }

        // category chips across applicable sources
        var cats = {};
        (a.assessments_per_source || []).forEach(function (src) {
            if (!src.applies) return;
            (src.risk_categories || []).forEach(function (c) { cats[c] = true; });
        });
        var catKeys = Object.keys(cats);
        if (catKeys.length) {
            var chipRow = el('div', 'aj-safety-chips');
            tid(chipRow, 'aj-safety-categories'); tidAj(chipRow, 'aj-safety-categories');
            catKeys.forEach(function (c) {
                chipRow.appendChild(el('span', 'aj-safety-chip aj-safety-chip-cat',
                    SAFETY_CATEGORY_LABELS[c] || c));
            });
            body.appendChild(chipRow);
        }

        // applicable sources (native wording preserved, dates, official link)
        var srcs = (a.assessments_per_source || []).filter(function (x) {
            return x.applies;
        });
        srcs.forEach(function (src, i) {
            var row = el('div', 'aj-safety-source');
            tid(row, 'aj-safety-source-' + i); tidAj(row, 'aj-safety-source-' + i);
            var head = el('div', 'aj-safety-source-head');
            head.appendChild(el('strong', 'aj-safety-source-auth',
                src.authority || src.source_id));
            if (src.native_level) {
                head.appendChild(safetyChip(src.native_level,
                                            safetyTone(src.normalized_level), null));
            }
            row.appendChild(head);
            if (src.foreign_advice) {
                row.appendChild(el('div', 'aj-safety-foreign',
                    'Advice issued for ' + safetyCountryName(src.authority_country) +
                    ' citizens; shown as an additional safety signal.'));
            }
            var meta = [];
            if (src.updated_at) meta.push('Updated ' + safetyDate(src.updated_at));
            if (src.retrieved_at) meta.push('Retrieved ' + safetyDate(src.retrieved_at));
            if (src.freshness === 'stale') {
                meta.push('STALE \u2014 this information may be out of date');
            }
            if (meta.length) {
                row.appendChild(el('div', 'aj-safety-meta', meta.join(' \u00B7 ')));
            }
            if ((src.affected_regions || []).length) {
                row.appendChild(el('div', 'aj-safety-meta',
                    'Affected areas: ' + src.affected_regions.join(', ')));
            }
            if (src.canonical_url) {
                var link = el('a', 'aj-safety-link', 'Open official source');
                link.href = src.canonical_url;
                link.target = '_blank';
                link.rel = 'noopener noreferrer';
                row.appendChild(link);
            }
            body.appendChild(row);
        });

        // stale prior warnings: visible, labeled, never silently cleared
        (a.stale_warnings || []).forEach(function (w) {
            var note = el('div', 'aj-safety-stale',
                'Earlier warning from ' + (w.authority || w.source_id) +
                ' is past its update window \u2014 kept visible; never silently cleared.');
            tid(note, 'aj-safety-stale-warning'); tidAj(note, 'aj-safety-stale-warning');
            body.appendChild(note);
        });

        // disagreements between official sources
        if ((a.disagreements || []).length) {
            body.appendChild(el('div', 'aj-safety-key', 'Official sources disagree'));
            (a.disagreements || []).forEach(function (d) {
                var txt = (typeof d === 'string')
                    ? d : (d.note || d.description || JSON.stringify(d));
                body.appendChild(el('div', 'aj-safety-text', txt));
            });
        }

        // unverified sources
        if ((a.unverified_sources || []).length) {
            var unv = el('div', 'aj-safety-unverified',
                'Could not verify: ' + a.unverified_sources.join(', ') +
                '. We never treat an unverified destination as verified.');
            tid(unv, 'aj-safety-unverified'); tidAj(unv, 'aj-safety-unverified');
            body.appendChild(unv);
        }

        // recommended actions + safer alternatives
        if ((a.recommended_actions || []).length) {
            body.appendChild(el('div', 'aj-safety-key', 'Recommended actions'));
            var ulA = el('ul', 'aj-safety-list');
            tid(ulA, 'aj-safety-actions-list'); tidAj(ulA, 'aj-safety-actions-list');
            a.recommended_actions.forEach(function (t) {
                ulA.appendChild(el('li', '', t));
            });
            body.appendChild(ulA);
        }
        if ((a.safer_alternatives || []).length) {
            body.appendChild(el('div', 'aj-safety-key', 'Safer alternatives'));
            var ulS = el('ul', 'aj-safety-list');
            tid(ulS, 'aj-safety-alternatives'); tidAj(ulS, 'aj-safety-alternatives');
            a.safer_alternatives.forEach(function (t) {
                ulS.appendChild(el('li', '', t));
            });
            body.appendChild(ulS);
        }

        // acknowledgement badge + monitoring line
        if (safety.risk_acknowledged) {
            var ackNote = el('div', 'aj-safety-acknote',
                'You acknowledged this warning. Acknowledging does not remove the risk.');
            tid(ackNote, 'aj-safety-ack-badge'); tidAj(ackNote, 'aj-safety-ack-badge');
            body.appendChild(ackNote);
        }
        var monLine = el('div', 'aj-safety-text aj-safety-muted',
            safety.monitor_enabled
                ? 'Monitoring is on \u2014 we will only alert you about material changes.'
                : 'Monitoring is off \u2014 turn it on below to watch for changes.');
        tid(monLine, 'aj-safety-monitor-line'); tidAj(monLine, 'aj-safety-monitor-line');
        body.appendChild(monLine);

        // safety change events
        if ((events || []).length) {
            body.appendChild(el('div', 'aj-safety-key', 'Recent changes'));
            var evBox = el('div', 'aj-safety-events');
            tid(evBox, 'aj-safety-events'); tidAj(evBox, 'aj-safety-events');
            events.forEach(function (ev) {
                evBox.appendChild(el('div', 'aj-safety-event',
                    safetyDate(ev.detected_at) + ' \u2014 ' +
                    (ev.differences || []).join('; ') +
                    '. Any change to your trip needs your approval first.'));
            });
            body.appendChild(evBox);
        }

        // actions
        var reBtn = el('button', 'aj-btn aj-btn-secondary', 'Check again');
        reBtn.type = 'button';
        tid(reBtn, 'aj-safety-recheck'); tidAj(reBtn, 'aj-safety-recheck');
        reBtn.addEventListener('click', safetyRecheck);
        acts.appendChild(reBtn);

        if (a.overall_status === 'reconsider_travel' && !safety.risk_acknowledged) {
            var ackBtn = el('button', 'aj-btn aj-btn-warn', 'I understand this risk');
            ackBtn.type = 'button';
            tid(ackBtn, 'aj-safety-acknowledge'); tidAj(ackBtn, 'aj-safety-acknowledge');
            ackBtn.addEventListener('click', safetyAcknowledge);
            acts.appendChild(ackBtn);
        }

        var monBtn = el('button', 'aj-btn aj-btn-secondary',
            safety.monitor_enabled ? 'Turn off monitoring' : 'Turn on monitoring');
        monBtn.type = 'button';
        tid(monBtn, 'aj-safety-monitor-toggle'); tidAj(monBtn, 'aj-safety-monitor-toggle');
        monBtn.addEventListener('click', function () {
            safetyToggleMonitor(!safety.monitor_enabled);
        });
        acts.appendChild(monBtn);
    }

    async function safetyRecheck() {
        var btn = byId('aj-safety-recheck');
        if (btn) { btn.disabled = true; btn.textContent = 'Checking\u2026'; }
        try {
            var resp = await api('/api/trip/' + Trip.tripId + '/safety/recheck',
                                 jsonOpts('POST', {}));
            renderSafetyCard({
                assessment: resp.assessment,
                source_reports: resp.source_reports,
                query: resp.query,
                risk_acknowledged: resp.risk_acknowledged,
                monitor_enabled: resp.monitor_enabled,
                checked_at: resp.checked_at
            }, resp.safety_events || []);
            var lbl = SAFETY_LABELS[((resp || {}).assessment || {}).overall_status] || {};
            announce('Safety check refreshed. ' + (lbl.text || ''), 'assertive');
        } catch (err) {
            showError('Safety recheck failed: ' + plainError(err));
            if (btn) { btn.disabled = false; btn.textContent = 'Check again'; }
            return;
        }
        pollState();
    }

    async function safetyAcknowledge() {
        var btn = byId('aj-safety-acknowledge');
        if (btn) btn.disabled = true;
        try {
            await api('/api/trip/' + Trip.tripId + '/safety/acknowledge',
                      jsonOpts('POST', {}));
            announce('Warning acknowledged. Acknowledging does not remove the risk.',
                     'assertive');
            pollState();
        } catch (err) {
            showError('Could not record acknowledgement: ' + plainError(err));
            if (btn) btn.disabled = false;
        }
    }

    async function safetyToggleMonitor(enable) {
        var btn = byId('aj-safety-monitor-toggle');
        if (btn) btn.disabled = true;
        try {
            await api('/api/trip/' + Trip.tripId + '/safety/monitor',
                      jsonOpts('POST', { enabled: !!enable }));
            announce(enable ? 'Safety monitoring turned on.'
                            : 'Safety monitoring turned off.', 'polite');
            pollState();
        } catch (err) {
            showError('Could not update monitoring: ' + plainError(err));
            if (btn) btn.disabled = false;
        }
    }

    // --- PNR confirmation (renamed "Booking reference"; testids kept) ----------

    function renderPnr(s) {
        var block = byId('trip-pnr-block');
        var booking = ((s && s.outputs) || {}).booking || null;
        if (!booking || Trip.pnrShown) { if (!booking) block.hidden = true; return; }
        Trip.pnrShown = true;
        clear(block);
        block.hidden = false;
        block.appendChild(el('div', 'trip-pnr-kicker', 'Booking confirmed \u00B7 Atlas Sandbox'));
        block.appendChild(el('div', 'aj-booking-ref-label', 'Booking reference'));
        var pnr = el('div', 'trip-pnr-code', booking.pnr || '');
        tid(pnr, 'pnr-code');
        tidAj(pnr, 'aj-booking-ref');
        block.appendChild(pnr);
        var status = el('div', 'trip-pnr-status', 'Status: ' + (booking.status || 'CONFIRMED'));
        tid(status, 'pnr-status');
        block.appendChild(status);
        var rec = booking.booking || null;
        var opt = (rec && rec.option) || null;
        if (opt) {
            var line = el('div', 'trip-pnr-route',
                (opt.carrier || '') + ' ' + (opt.flight_no || '') + ' \u00B7 ' +
                ((opt.dep && opt.dep.airport) || '?') + ' \u2192 ' + ((opt.arr && opt.arr.airport) || '?'));
            block.appendChild(line);
        }
        var chipsRow = el('div', 'trip-pnr-chips');
        if (booking.monitor_armed || (rec && rec.monitor_armed)) {
            chipsRow.appendChild(chip('monitoring armed', 'trip-chip-good', 'pnr-monitor'));
        }
        chipsRow.appendChild(chip('Atlas Sandbox booking \u2014 not a live airline seat', 'trip-chip-sandbox', 'pnr-provenance'));
        block.appendChild(chipsRow);
        addChat('agent', 'Booking reference ' + (booking.pnr || '') +
                         ' issued. We\u2019re watching the flight.');
    }

    // --- itinerary: day-grouped, first 6 items + Show more (Decision D4) --------

    function renderItinerary(s, preserveCap) {
        var itinerary = ((s && s.outputs) || {}).itinerary || null;
        var container = byId('trip-itinerary');
        var items = (itinerary && itinerary.items) || [];
        var signature = JSON.stringify({
            items: items.map(function (item) {
                return [item.item_id, item.name, item.kind, item.honesty_label,
                        item.price_range_sgd, item.details];
            }),
            timezone: itinerary && itinerary.timezone,
            budget: itinerary && itinerary.budget,
            validation: itinerary && itinerary.validation
        });
        if (signature === Trip.renderedItinerarySig) return;
        Trip.renderedItinerarySig = signature;
        Trip.renderedItineraryCount = items.length;
        if (!preserveCap) Trip.shownItin = 6;
        clear(container);
        if (items.length === 0) {
            var itinEmpty = el('div', 'trip-empty',
                'Nothing planned yet \u2014 the itinerary appears after a confirmed booking.');
            tid(itinEmpty, 'trip-itinerary-empty');
            container.appendChild(itinEmpty);
            return;
        }
        buildItinerary(container, itinerary, Trip.shownItin, s);
    }

    function buildItinerary(container, itinerary, cap, s) {
        var items = (itinerary && itinerary.items) || [];
        var summary = el('div', 'aj-itin-summary');
        tid(summary, 'aj-itinerary-summary');
        var timezoneName = itinerary.timezone || 'Timezone not available';
        var budget = (itinerary.budget || {}).total_range_sgd || [0, 0];
        var validation = itinerary.validation || {};
        var issueCount = ['overlaps', 'invalid_ranges', 'invalid_prices',
                          'transfer_warnings', 'check_in_warnings']
            .reduce(function (total, key) {
                return total + ((validation[key] || []).length);
            }, 0);
        function metric(label, value, tone) {
            var box = el('div', 'aj-itin-metric' + (tone ? ' is-' + tone : ''));
            box.appendChild(el('span', 'aj-itin-metric-label', label));
            box.appendChild(el('strong', 'aj-itin-metric-value', value));
            return box;
        }
        summary.appendChild(metric('Timezone', timezoneName));
        summary.appendChild(metric('Budget',
            budget[0] || budget[1] ? sgdRange(budget) : 'No sourced total'));
        summary.appendChild(metric('Plan check',
            issueCount ? issueCount + ' item' + (issueCount === 1 ? '' : 's') +
                ' need review' : 'No timing conflicts',
            issueCount ? 'warn' : 'good'));
        container.appendChild(summary);

        // Honest grouping without fabricated dates: the booked flight is the
        // travel day; researched items have no dates in the data, so they go
        // under "During your stay" (never invented day numbers).
        var flightItems = items.filter(function (i) { return i.kind === 'flight'; });
        var stayItems = items.filter(function (i) { return i.kind !== 'flight'; });
        var shown = 0;
        var groupIdx = 0;
        function group(label, list) {
            if (!list.length) return;
            groupIdx += 1;
            var head = el('div', 'aj-itin-day');
            tid(head, 'aj-itinerary-day-' + groupIdx);
            head.appendChild(el('span', 'aj-itin-day-label', label));
            container.appendChild(head);
            for (var i = 0; i < list.length && shown < cap; i++, shown++) {
                container.appendChild(itineraryRow(list[i], s));
            }
        }
        group('Travel day', flightItems);
        group('During your stay', stayItems);
        if (items.length > cap) {
            var more = el('button', 'aj-show-more',
                'Show more (' + (items.length - cap) + ' more)');
            more.type = 'button';
            tid(more, 'aj-show-more-itinerary');
            more.addEventListener('click', function () {
                Trip.shownItin += 6;
                Trip.renderedItineraryCount = -1; // force rebuild
                renderItineraryForce(s);
            });
            container.appendChild(more);
        }
    }

    function renderItineraryForce(s) {
        Trip.renderedItinerarySig = '';
        renderItinerary(s, true);
    }

    function itineraryRow(item, s) {
        var row = el('div', 'trip-itin-item trip-itin-' + (item.kind || 'item'));
        tid(row, 'trip-itin-item');
        var left = el('div', 'trip-itin-left');
        left.appendChild(el('span', 'trip-itin-kind', item.kind || ''));
        left.appendChild(el('span', 'trip-itin-name', item.name || ''));
        row.appendChild(left);
        var right = el('div', 'trip-itin-right');
        if (item.source === 'atlas_real') {
            right.appendChild(chip(item.honesty_label || 'booked flight (Atlas Sandbox record)',
                                   'trip-chip-real', 'itin-chip-real'));
        } else if (item.source === 'researched_mock') {
            var asOf = (item.provenance && item.provenance.researched_as_of) || '';
            right.appendChild(chip('researched mock data (as_of ' + (asOf || 'unverified date') + ')',
                                   'trip-chip-mock', 'itin-chip-mock'));
        } else {
            // G4-DA-fix F8: unknown provider sources fall back to the
            // item's honesty_label before the blanket suggestion chip.
            right.appendChild(chip(item.honesty_label || '\uD83D\uDCA1 suggestion only',
                                   'trip-chip-llm', 'itin-chip-llm'));
        }
        var priceTxt = sgdRange(item.price_range_sgd);
        if (priceTxt) {
            right.appendChild(el('span', 'trip-itin-price', priceTxt + ' ' + sgdToThb(item.price_range_sgd)));
        } else if (item.kind !== 'flight') {
            right.appendChild(el('span', 'trip-itin-price trip-itin-noprice', 'price not sourced'));
        }
        if (!item.booked && item.kind !== 'flight') {
            var replace = el('button', 'aj-itin-replace', 'Replace');
            replace.type = 'button';
            tid(replace, 'aj-itinerary-replace');
            replace.setAttribute('aria-expanded',
                Trip.itineraryEditorId === item.item_id ? 'true' : 'false');
            replace.addEventListener('click', function () {
                Trip.itineraryEditorId = item.item_id;
                renderItineraryForce(s);
                var editor = byId('aj-itin-editor-' + item.item_id);
                if (editor) {
                    var first = editor.querySelector('input');
                    if (first) first.focus();
                }
            });
            right.appendChild(replace);
        }
        row.appendChild(right);
        if (Trip.itineraryEditorId === item.item_id) {
            row.appendChild(itineraryEditor(item, s));
        }
        return row;
    }

    function itineraryEditor(item, s) {
        var form = el('form', 'aj-itin-editor');
        form.id = 'aj-itin-editor-' + item.item_id;
        tid(form, 'aj-itinerary-editor');

        function field(labelText, input, testId) {
            var fieldWrap = el('label', 'aj-itin-field');
            fieldWrap.appendChild(el('span', 'aj-itin-field-label', labelText));
            tid(input, testId);
            fieldWrap.appendChild(input);
            return fieldWrap;
        }

        var intro = el('p', 'aj-itin-editor-intro',
            'Change only this suggestion. Your booked flight stays unchanged.');
        form.appendChild(intro);
        var grid = el('div', 'aj-itin-editor-grid');
        var name = el('input', 'aj-itin-input');
        name.type = 'text'; name.required = true; name.maxLength = 160;
        name.value = item.name || '';
        grid.appendChild(field('Name', name, 'aj-itinerary-name'));

        var kind = el('select', 'aj-itin-input');
        ['hotel', 'activity', 'local_transport'].forEach(function (value) {
            var option = el('option', '',
                value === 'local_transport' ? 'Local transport' :
                value.charAt(0).toUpperCase() + value.slice(1));
            option.value = value;
            if (value === item.kind) option.selected = true;
            kind.appendChild(option);
        });
        grid.appendChild(field('Type', kind, 'aj-itinerary-kind'));

        var range = item.price_range_sgd || [];
        var low = el('input', 'aj-itin-input');
        low.type = 'number'; low.min = '0'; low.step = '1';
        low.value = range.length === 2 ? String(range[0]) : '';
        grid.appendChild(field('Budget from (SGD)', low,
                               'aj-itinerary-price-low'));
        var high = el('input', 'aj-itin-input');
        high.type = 'number'; high.min = '0'; high.step = '1';
        high.value = range.length === 2 ? String(range[1]) : '';
        grid.appendChild(field('Budget to (SGD)', high,
                               'aj-itinerary-price-high'));
        form.appendChild(grid);

        var feedback = el('p', 'aj-itin-feedback');
        feedback.setAttribute('aria-live', 'polite');
        form.appendChild(feedback);
        var actions = el('div', 'aj-itin-editor-actions');
        var cancel = el('button', 'aj-itin-cancel', 'Cancel');
        cancel.type = 'button'; tid(cancel, 'aj-itinerary-cancel');
        cancel.addEventListener('click', function () {
            Trip.itineraryEditorId = null;
            renderItineraryForce(s);
        });
        var save = el('button', 'aj-itin-save', 'Save changes');
        save.type = 'submit'; tid(save, 'aj-itinerary-save');
        actions.appendChild(cancel); actions.appendChild(save);
        form.appendChild(actions);

        form.addEventListener('submit', async function (event) {
            event.preventDefault();
            var lowText = low.value.trim();
            var highText = high.value.trim();
            if ((lowText && !highText) || (!lowText && highText)) {
                feedback.textContent = 'Enter both budget values, or leave both blank.';
                return;
            }
            var price = null;
            if (lowText && highText) {
                price = [Number(lowText), Number(highText)];
                if (!Number.isFinite(price[0]) || !Number.isFinite(price[1]) ||
                        price[0] < 0 || price[1] < price[0]) {
                    feedback.textContent = 'The “to” budget must be at least the “from” budget.';
                    return;
                }
            }
            save.disabled = true;
            cancel.disabled = true;
            feedback.textContent = 'Saving this section…';
            var body = {
                name: name.value.trim(),
                kind: kind.value,
                details: item.details || {}
            };
            if (price) body.price_range_sgd = price;
            try {
                var result = await api(
                    '/api/trips/' + Trip.tripId + '/itinerary/sections/' +
                    encodeURIComponent(item.item_id) + '/replace',
                    jsonOpts('POST', body));
                Trip.itineraryEditorId = null;
                Trip.renderedItinerarySig = '';
                renderState(result.state);
                announce('Itinerary section replaced. Budget and timing checks updated.');
            } catch (err) {
                feedback.textContent = plainError(err);
                save.disabled = false;
                cancel.disabled = false;
            }
        });
        return form;
    }

    // --- recovery surface (spec §8.6; SEPARATE approval) ------------------------

    function renderRecovery(s) {
        var panel = byId('aj-recovery-panel');
        var recovery = ((s && s.outputs) || {}).recovery || null;
        var approval = findApproval(s, 'recovery_booking');
        if (!recovery) { panel.hidden = true; Trip.recoveryApproval = null; return; }
        Trip.recoveryApproval = approval;
        clear(panel);
        panel.hidden = false;

        panel.appendChild(el('h4', 'aj-recovery-title',
            'Something changed with your flight'));
        panel.appendChild(el('p', 'aj-recovery-sub',
            'Your original plan is preserved below. Nothing is rebooked without ' +
            'your separate approval.'));

        // (a) original trip preserved, muted-coral
        var orig = recovery.original || {};
        var origCard = el('div', 'aj-recovery-original');
        tid(origCard, 'aj-recovery-original');
        origCard.appendChild(el('span', 'aj-recovery-tag', 'Your original booking'));
        origCard.appendChild(el('div', 'aj-recovery-flight', optionLine(orig)));
        if (orig.price) {
            origCard.appendChild(el('div', 'aj-recovery-price', priceNative(orig.price)));
        }
        panel.appendChild(origCard);

        if (recovery.degraded) {
            var warn = el('div', 'aj-recovery-warn',
                recovery.note || 'Replacement search is degraded \u2014 no options are shown rather than invented.');
            tid(warn, 'aj-recovery-degraded');
            panel.appendChild(warn);
        }

        // (b) replacement options with plain suitability reasons
        var opts = recovery.options || [];
        opts.forEach(function (o, idx) {
            var card = el('div', 'aj-recovery-card');
            tid(card, 'aj-recovery-card-' + (idx + 1));
            var top = el('div', 'trip-option-top');
            var carrierName = CARRIER_NAMES[o.carrier] || o.carrier || '?';
            top.appendChild(el('span', 'trip-option-carrier',
                carrierName + (CARRIER_NAMES[o.carrier] ? ' (' + o.carrier + ')' : '')));
            top.appendChild(el('span', 'trip-option-flight', o.flight_no));
            top.appendChild(chip('Atlas Sandbox data', 'trip-chip-sandbox'));
            card.appendChild(top);
            card.appendChild(el('div', 'trip-option-route',
                ((o.dep && o.dep.airport) || '?') + ' \u2192 ' + ((o.arr && o.arr.airport) || '?') +
                ' \u00B7 ' + hhmm(o.dep && o.dep.time)));
            var reason = el('p', 'aj-recovery-reason', o.reason || 'Same route, available in the Atlas Sandbox.');
            tid(reason, 'aj-recovery-reason-' + (idx + 1));
            card.appendChild(reason);
            card.appendChild(el('div', 'aj-recovery-price', priceNative(o.price)));
            if (approval) {
                var pick = el('button', 'aj-recovery-pick', 'Pick this replacement');
                pick.type = 'button';
                tid(pick, 'aj-recovery-pick-' + (idx + 1));
                pick.addEventListener('click', function () {
                    Trip.recoverySelectedId = o.id;
                    panel.querySelectorAll('.aj-recovery-card').forEach(function (c) {
                        c.classList.remove('is-selected');
                    });
                    card.classList.add('is-selected');
                    announce('Replacement selected: ' + (o.carrier || '') + ' ' + (o.flight_no || ''));
                });
                card.appendChild(pick);
            }
            panel.appendChild(card);
        });
        if (!opts.length && !recovery.degraded) {
            panel.appendChild(el('p', 'aj-recovery-none',
                'No replacement options are available right now \u2014 we won\u2019t invent any.'));
        }

        // (c) SEPARATE recovery approval with its own consequence sentence
        if (approval) {
            var note = el('p', 'aj-recovery-consequence',
                'Approving requests ONLY the replacement flight from Atlas Sandbox. ' +
                'No replacement PNR exists unless Atlas confirms it; your original record is preserved.');
            tid(note, 'aj-recovery-consequence');
            panel.appendChild(note);
            var actions = el('div', 'aj-recovery-actions');
            var approve = el('button', 'aj-recovery-approve', 'Approve replacement booking');
            approve.type = 'button';
            tid(approve, 'aj-recovery-approve');
            approve.addEventListener('click', function () { resolveRecovery('approve'); });
            var reject = el('button', 'aj-recovery-reject', 'Keep my original plan');
            reject.type = 'button';
            tid(reject, 'aj-recovery-reject');
            reject.addEventListener('click', function () { resolveRecovery('reject'); });
            actions.appendChild(reject);
            actions.appendChild(approve);
            panel.appendChild(actions);
            if (!Trip.recoverySelectedId && opts.length) {
                Trip.recoverySelectedId = opts[0].id;
                var firstCard = panel.querySelector('.aj-recovery-card');
                if (firstCard) firstCard.classList.add('is-selected');
            }
        } else if (recovery.resolved) {
            var outcome = el('p', 'aj-recovery-outcome');
            tid(outcome, 'aj-recovery-outcome');
            outcome.textContent = recovery.resolved.approved
                ? 'Replacement approved \u2014 booked in the Atlas Sandbox. Your original booking record is kept for reference.'
                : 'Keeping your original plan. No replacement was booked.';
            panel.appendChild(outcome);
        }
        var receipts = recovery.receipts || {};
        if (receipts.original || receipts.replacement) {
            var evidence = el('div', 'aj-recovery-evidence');
            evidence.appendChild(el('h5', 'aj-recovery-evidence-title',
                'Sandbox booking records'));
            if (receipts.original) {
                var originalReceipt = el('div', 'aj-recovery-receipt');
                tid(originalReceipt, 'aj-recovery-original-receipt');
                originalReceipt.appendChild(el('span', 'aj-recovery-receipt-label',
                    'Original record'));
                originalReceipt.appendChild(el('strong', '',
                    receipts.original.pnr || 'Reference unavailable'));
                evidence.appendChild(originalReceipt);
            }
            if (receipts.replacement) {
                var replacementReceipt = el('div', 'aj-recovery-receipt is-replacement');
                tid(replacementReceipt, 'aj-recovery-replacement-receipt');
                replacementReceipt.appendChild(el('span', 'aj-recovery-receipt-label',
                    'Replacement record'));
                replacementReceipt.appendChild(el('strong', '',
                    receipts.replacement.pnr || 'Reference unavailable'));
                evidence.appendChild(replacementReceipt);
            }
            panel.appendChild(evidence);
        }
        var rights = recovery.rights || ((((s || {}).outputs || {}).rights) || null);
        if (rights) {
            var rightsLine = el('p', 'aj-recovery-rights',
                rights.regime === 'NONE'
                    ? 'Passenger rights: no automatic regime matched this route. ' +
                      (rights.note || '')
                    : 'Passenger rights: ' + rights.regime +
                      (rights.legal_citation ? ' · ' + rights.legal_citation : ''));
            tid(rightsLine, 'aj-recovery-rights');
            panel.appendChild(rightsLine);
        }
        if (recovery.monitor && recovery.monitor.armed) {
            var monitorLine = el('p', 'aj-recovery-monitor',
                'Monitoring the replacement flight under ' +
                (recovery.monitor.pnr || 'the replacement record') + '.');
            tid(monitorLine, 'aj-recovery-monitor');
            panel.appendChild(monitorLine);
        }
        if (recovery.sandbox_note) {
            panel.appendChild(el('p', 'aj-sandbox-note', recovery.sandbox_note));
        }
    }

    async function resolveRecovery(decision) {
        var approval = Trip.recoveryApproval;
        if (!approval) return;
        if (decision === 'approve' && !Trip.recoverySelectedId) {
            announce('Pick one replacement option first.');
            return;
        }
        try {
            invalidatePolls();
            var payload = { decision: decision };
            if (decision === 'approve') payload.value = { option_id: Trip.recoverySelectedId };
            var headers = {};
            if (decision === 'approve') {
                if (!Trip.approvalKeys[approval.approval_id]) {
                    Trip.approvalKeys[approval.approval_id] = generateUUID();
                }
                headers['Idempotency-Key'] =
                    Trip.approvalKeys[approval.approval_id];
            }
            await api('/api/trip/' + Trip.tripId + '/approvals/' + approval.approval_id,
                      jsonOpts('POST', payload, headers));
            addChat('agent', decision === 'approve'
                ? 'Replacement approved \u2014 booked in the Atlas Sandbox.'
                : 'Keeping your original plan.');
            announce(decision === 'approve'
                ? 'Replacement booked in the Atlas Sandbox.'
                : 'Keeping your original plan.');
            pollState();
        } catch (err) {
            showError('Recovery decision failed: ' + plainError(err));
        }
    }

    // --- destinations + disclosures + dialogs ------------------------------------

    function switchDestination(dest) {
        Trip.dest = dest;
        Trip.forceStep = null;
        ['plan', 'mytrip', 'help'].forEach(function (d) {
            var pane = byId('aj-dest-' + d);
            var btn = byId('aj-nav-' + d);
            if (!pane || !btn) return;
            var active = d === dest;
            pane.hidden = !active;
            pane.classList.toggle('is-active', active);
            btn.classList.toggle('is-active', active);
            if (active) btn.setAttribute('aria-current', 'page');
            else btn.removeAttribute('aria-current');
        });
        // My trip's single step is always expanded inside its destination.
        var step5 = byId('aj-step-5');
        var body5 = byId('aj-step-5-body');
        if (dest === 'mytrip') {
            step5.classList.remove('is-future');
            step5.classList.add('is-current');
            step5.removeAttribute('aria-disabled');
            if (body5) body5.hidden = false;
        }
    }

    function editStep(n) {
        Trip.forceStep = n;
        if (n <= 4 && Trip.dest !== 'plan') switchDestination('plan');
        if (Trip.lastState) renderStepRail(Trip.lastState, n);
        announce('Step ' + n + ' reopened \u2014 ' + STEP_TITLES[n - 1] +
                 '. Steps after it will update when you continue.');
        var li = byId('aj-step-' + n);
        if (li && li.scrollIntoView) li.scrollIntoView({ block: 'start', behavior: reducedMotion() ? 'auto' : 'smooth' });
    }

    function wireDisclosure(btnId, bodyId) {
        var btn = byId(btnId);
        var body = byId(bodyId);
        if (!btn || !body) return;
        btn.addEventListener('click', function () {
            var open = body.hidden;
            body.hidden = !open;
            btn.setAttribute('aria-expanded', open ? 'true' : 'false');
            btn.classList.toggle('is-open', open);
        });
    }

    // Dialogs: focus trap + Esc + focus restore (spec §9.2).
    function focusablesIn(container) {
        return Array.prototype.slice.call(container.querySelectorAll(
            'button, input, select, textarea, a[href]')).filter(function (f) {
            return !f.disabled && f.offsetParent !== null;
        });
    }

    function trapDialog(container) {
        Trip.lastFocus = document.activeElement;
        container.hidden = false;
        container._trap = function (e) {
            if (e.key === 'Escape') {
                e.preventDefault();
                untrapDialog(container);
            } else if (e.key === 'Tab') {
                var list = focusablesIn(container);
                if (!list.length) return;
                var first = list[0];
                var last = list[list.length - 1];
                if (e.shiftKey && document.activeElement === first) {
                    e.preventDefault(); last.focus();
                } else if (!e.shiftKey && document.activeElement === last) {
                    e.preventDefault(); first.focus();
                }
            }
        };
        container.addEventListener('keydown', container._trap);
    }

    function untrapDialog(container) {
        container.hidden = true;
        if (container._trap) {
            container.removeEventListener('keydown', container._trap);
            container._trap = null;
        }
        if (Trip.lastFocus && Trip.lastFocus.focus) Trip.lastFocus.focus();
    }

    function openDrawer() {
        trapDialog(byId('aj-profile-drawer'));
        var first = focusablesIn(byId('aj-profile-drawer'))[0];
        if (first) first.focus();
    }
    function closeDrawer() {
        untrapDialog(byId('aj-profile-drawer'));
    }

    // --- profile editor (F5/F17: safe fields only — this demo NEVER stores a
    // passport number, expiry, legal identity, or payment data) ---------------

    var PROFILE_ROWS = [
        { key: 'passport_country', group: 'identity', label: 'Passport country' },
        { key: 'home_city', group: 'identity', label: 'Home city' },
        { key: 'preferred_origin_airport', group: 'prefs', label: 'Preferred origin airport' },
        { key: 'cabin', group: 'prefs', label: 'Cabin' },
        { key: 'diet', group: 'prefs', label: 'Diet' },
        { key: 'budget_range', group: 'prefs', label: 'Budget range' },
        { key: 'display_currency', group: 'prefs', label: 'Display currency' },
        { key: 'accessibility_notes', group: 'prefs', label: 'Accessibility notes' },
        { key: 'airlines_like', group: 'prefs', label: 'Preferred airlines', list: true }
    ];

    function profileValue(profile, spec) {
        if (spec.group === 'identity') {
            return profile.identity[spec.key] || '';
        }
        if (spec.group === 'prefs') {
            var v = profile.prefs[spec.key];
            if (spec.list) return Array.isArray(v) ? v.join(', ') : (v || '');
            return v || '';
        }
        var f = (profile.fields || {})[spec.key];
        return f ? f.value : '';
    }

    async function refreshProfile() {
        var rows = byId('trip-profile-rows');
        try {
            var profile = await api('/api/profile/' + USER_ID);
            renderProfile(profile);
        } catch (err) {
            clear(rows);
            rows.appendChild(el('div', 'trip-empty trip-error-text',
                'Your details could not be loaded (' + (err.code || 'error') + ').'));
        }
    }

    function renderProfile(profile) {
        var rows = byId('trip-profile-rows');
        clear(rows);
        var consent = byId('trip-consent');
        consent.checked = !!(profile.consent && profile.consent.store_local);

        // D6: greeting stays neutral; the remembered city lives ONLY as an
        // editable confirmed fact (renderFacts), never leaked into prose.
        var homeCity = profile.identity.home_city;
        Trip.homeCityProfile = homeCity || '';
        byId('trip-greeting').textContent = homeCity
            ? 'Welcome back.' : 'Tell me where you need to be \u2014 I\u2019ll plan the rest.';
        var ajGreeting = byId('aj-greeting');
        ajGreeting.textContent = homeCity ? 'Welcome back.' : 'Welcome.';
        if (!Trip.tripId) renderFacts(null);

        PROFILE_ROWS.forEach(function (spec) {
            rows.appendChild(profileRow(spec, profileValue(profile, spec), profile));
        });

        var fields = profile.fields || {};
        Object.keys(fields).forEach(function (key) {
            if (PROFILE_ROWS.some(function (s) { return s.key === key; })) return;
            var f = fields[key];
            var row = profileRow({ key: key, group: 'fields', label: key }, f.value, profile);
            var src = el('span', 'trip-profile-source trip-src-' + (f.source || 'user'),
                         f.source === 'ai_inferred' ? 'Suggested by Atlas' : 'user');
            row.querySelector('.trip-profile-label').appendChild(src);
            rows.appendChild(row);
        });

        if (rows.childNodes.length === 0) {
            rows.appendChild(el('div', 'trip-empty', 'Nothing saved yet \u2014 add details below.'));
        }
    }

    function profileRow(spec, value, profile) {
        var row = el('div', 'trip-profile-row');
        tid(row, 'profile-row-' + spec.key);
        row.setAttribute('data-testid-aj', 'aj-profile-field-' + spec.key);
        var label = el('div', 'trip-profile-label', spec.label);
        var valueEl = el('div', 'trip-profile-value', value || '\u2014');
        tid(valueEl, 'profile-value-' + spec.key);
        var actions = el('div', 'trip-profile-actions');

        var input = el('input', 'trip-profile-input');
        input.type = 'text';
        input.placeholder = value || '';
        tid(input, 'profile-input-' + spec.key);
        input.hidden = true;

        var editBtn = el('button', 'trip-profile-edit', 'Edit');
        editBtn.type = 'button';
        tid(editBtn, 'profile-edit-' + spec.key);
        var saveBtn = el('button', 'trip-profile-save', 'Save');
        saveBtn.type = 'button';
        saveBtn.hidden = true;
        tid(saveBtn, 'profile-save-' + spec.key);
        var delBtn = el('button', 'trip-profile-delete', 'Delete');
        delBtn.type = 'button';
        tid(delBtn, 'profile-delete-' + spec.key);

        editBtn.addEventListener('click', function () {
            valueEl.hidden = true;
            input.hidden = false;
            input.value = '';
            editBtn.hidden = true;
            saveBtn.hidden = false;
            input.focus();
        });
        saveBtn.addEventListener('click', function () {
            var raw = input.value.trim();
            if (!raw) { input.focus(); return; }
            var out = raw;
            if (spec.list) out = raw.split(',').map(function (x) { return x.trim(); }).filter(Boolean);
            saveProfileField(spec.key, out);
        });
        delBtn.addEventListener('click', function () { deleteProfileField(spec.key); });

        actions.appendChild(editBtn);
        actions.appendChild(saveBtn);
        actions.appendChild(delBtn);
        row.appendChild(label);
        row.appendChild(valueEl);
        row.appendChild(input);
        row.appendChild(actions);
        return row;
    }

    async function saveProfileField(field, value) {
        try {
            await api('/api/profile/' + USER_ID + '/' + field,
                      jsonOpts('PUT', { value: value, source: 'user' }));
            await refreshProfile();
        } catch (err) {
            showError('Saving ' + field + ' failed: ' + plainError(err));
        }
    }

    async function deleteProfileField(field) {
        try {
            await api('/api/profile/' + USER_ID + '/' + field, { method: 'DELETE' });
            await refreshProfile();
        } catch (err) {
            showError('Deleting ' + field + ' failed: ' + err.message);
        }
    }

    async function setConsent(storeLocal) {
        try {
            await api('/api/profile/' + USER_ID + '/consent',
                      jsonOpts('POST', { store_local: storeLocal }));
            await refreshProfile();
        } catch (err) {
            showError('Consent update failed: ' + err.message);
        }
    }

    // --- transplant: legacy surfaces move INTO the AJ shell (ids stay single) ---

    function transplant(nodeId, slotId) {
        var node = byId(nodeId);
        var slot = byId(slotId);
        if (node && slot) slot.appendChild(node);
    }

    function transplantLegacySurfaces() {
        transplant('trip-goal-form', 'aj-goal-slot');       // hero composer
        transplant('trip-error', 'aj-state-slot');          // inline states
        transplant('trip-chat', 'aj-chat-slot');            // conversation disclosure
        transplant('trip-clarify-chips', 'aj-questions-slot');
        transplant('trip-scope-block', 'aj-questions-slot');
        transplant('trip-options-block', 'aj-step-2-body'); // step 2
        transplant('trip-visa-block', 'aj-review-entry-req'); // step 3
        transplant('trip-approval-banner', 'aj-approval-slot'); // step 4
        transplant('trip-pnr-block', 'aj-pnr-slot');        // step 5
        transplant('trip-itinerary-block', 'aj-itinerary-slot'); // step 5
        transplant('trip-status-strip', 'aj-trace-body');   // Agent Trace
        transplant('trip-dag', 'aj-trace-body');            // Agent Trace
        var consentLabel = byId('trip-consent') ? byId('trip-consent').parentElement : null;
        if (consentLabel && consentLabel.tagName === 'LABEL') {
            byId('aj-consent-slot').appendChild(consentLabel);
        }
        transplant('trip-profile-rows', 'aj-drawer-rows');  // profile drawer
    }

    // --- disruption trigger: legacy rescue flow + trip recovery (app.js frozen) --

    function wrapSimulateDisruption() {
        var legacy = window.simulateDisruption;
        if (typeof legacy !== 'function') return;
        window.simulateDisruption = async function () {
            var result = await legacy.apply(this, arguments);
            // mount the trip recovery surface ONLY for a booked trip; the
            // legacy rescue demo flow above runs unchanged (canary-safe).
            if (Trip.tripId && Trip.booked) {
                try {
                    await api('/api/trip/' + Trip.tripId +
                              '/simulate-disruption?allow_sim=1');
                    invalidatePolls();
                    Trip.terminal = false;
                    Trip.switchedMytrip = false;
                    startWatching();
                } catch (err) {
                    showError('Disruption simulation failed: ' + plainError(err));
                }
            }
            return result;
        };
    }

    // --- init ------------------------------------------------------------------------

    function init() {
        transplantLegacySurfaces();
        byId('trip-goal-form').addEventListener('submit', submitGoal);
        byId('trip-approval-approve').addEventListener('click', function () { resolveApproval('approve'); });
        byId('trip-approval-reject').addEventListener('click', function () { resolveApproval('reject'); });
        byId('trip-consent').addEventListener('change', function (ev) {
            setConsent(ev.target.checked);
        });
        // AJ nav + disclosures
        byId('aj-nav-plan').addEventListener('click', function () { switchDestination('plan'); });
        byId('aj-nav-mytrip').addEventListener('click', function () { switchDestination('mytrip'); });
        byId('aj-nav-help').addEventListener('click', function () { switchDestination('help'); });
        wireDisclosure('aj-disclosure-chat', 'aj-chat-body');
        wireDisclosure('aj-disclosure-sources', 'aj-sources-body');
        wireDisclosure('aj-disclosure-trace', 'aj-trace-body');
        // step Edit buttons (completed-step re-entry)
        for (var n = 1; n <= 5; n++) {
            (function (step) {
                var b = byId('aj-step-' + step + '-edit');
                if (b) b.addEventListener('click', function () { editStep(step); });
            })(n);
        }
        // starters: pre-fill editable goal text, show provisional services,
        // then submit (one tap).
        Object.keys(STARTER_GOALS).forEach(function (btnId) {
            var b = byId(btnId);
            if (!b) return;
            b.addEventListener('click', function () {
                byId('trip-goal-input').value = STARTER_GOALS[btnId];
                Trip.provServices = STARTER_SERVICES[btnId].slice();
                Trip.pendingProvServices = STARTER_SERVICES[btnId].slice();
                renderServices(null);
                submitGoal(null);
            });
        });
        // profile drawer
        byId('btn-aj-profile').addEventListener('click', openDrawer);
        byId('aj-profile-close').addEventListener('click', closeDrawer);
        // modal backdrop click closes without discarding anything silently
        byId('trip-approval-overlay').addEventListener('click', function (ev) {
            if (ev.target === this) untrapDialog(this);
        });
        wrapSimulateDisruption();
        observeTripView(); // G4-DA-fix F1: stop polling when the view is left
        window.__tripRender = renderState; // diagnostic/test hook
        byId('aj-step-2-summary').textContent = 'No flight options yet';
        refreshProfile();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
