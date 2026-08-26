/* ============================================================
   TravelCare AI — Personal Trip Agent view (G4)
   All trip-view logic lives here; static/app.js stays untouched.
   SECURITY: strict textContent/createElement DOM construction —
   zero innerHTML with data (§9.3 XSS contract).
   HONESTY (§11): sandbox provenance chips, "💡 suggestion only"
   for LLM items, "researched mock data (as_of …)" chips, visible
   degraded/stale warnings — the UI never fabricates.
   ============================================================ */
(function () {
    'use strict';

    var USER_ID = 'victor'; // §16.1 single-user demo id
    var POLL_MS = 1000;     // F9: DAG updates within 1s cadence
    // §16.1 currency display: SGD primary, THB secondary (per 1 USD)
    var RATE_SGD = 1.34;
    var RATE_THB = 35.4;
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

    var Trip = {
        tripId: null,
        pollTimer: null,
        es: null,
        answeredChips: {},
        renderedNodeCount: -1,
        renderedOptionIds: '',
        renderedItineraryCount: -1,
        approval: null,          // current approve_booking approval object
        selectedOptionId: null,
        pnrShown: false,
        busy: false
    };

    // --- strict DOM helpers (never innerHTML with data) -------------------

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined && text !== null) node.textContent = String(text);
        return node;
    }

    function clear(node) {
        while (node.firstChild) node.removeChild(node.firstChild);
    }

    function byId(id) { return document.getElementById(id); }

    function money(usd) {
        return 'S$' + (Number(usd || 0) * RATE_SGD).toFixed(2);
    }
    function moneyThb(usd) {
        return '\u2248 \u0E3F' + (Number(usd || 0) * RATE_THB).toFixed(0);
    }
    function sgdRange(range) {
        if (!range || range.length < 2) return null;
        return 'S$' + Number(range[0]).toFixed(0) + '\u2013' + Number(range[1]).toFixed(0);
    }
    function sgdToThb(range) {
        if (!range || range.length < 2) return null;
        var factor = RATE_THB / RATE_SGD;
        return '\u2248 \u0E3F' + Math.round(range[0] * factor) + '\u2013' + Math.round(range[1] * factor);
    }
    function clock(iso) {
        if (!iso) return '';
        var d = new Date(iso);
        if (isNaN(d.getTime())) return '';
        return d.toTimeString().slice(0, 8);
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
            throw exc;
        }
        return body;
    }

    function jsonOpts(method, payload) {
        return {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        };
    }

    // --- chat surface ------------------------------------------------------

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
        ev.preventDefault();
        if (Trip.busy) return;
        var input = byId('trip-goal-input');
        var text = input.value.trim();
        if (!text) return;
        Trip.busy = true;
        byId('trip-goal-loading').hidden = false;
        byId('trip-goal-submit').disabled = true;
        hideError();
        try {
            var data = await api('/api/trip/start', jsonOpts('POST', {
                goal_text: text, user_id: USER_ID
            }));
            Trip.tripId = data.trip_id;
            Trip.pnrShown = false;
            Trip.renderedNodeCount = -1;
            Trip.renderedOptionIds = '';
            Trip.renderedItineraryCount = -1;
            Trip.answeredChips = {};
            clear(byId('trip-chat'));
            addChat('user', text);
            addChat('agent', 'Trip opened (' + data.trip_id + '). Working the plan now \u2014 follow the live execution panel.');
            byId('trip-status-strip').hidden = false;
            startWatching();
        } catch (err) {
            showError('Could not start the trip: ' + err.message + (err.hint ? ' \u2014 ' + err.hint : ''));
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
    }

    function startWatching() {
        stopWatching();
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

    async function pollState() {
        if (!Trip.tripId) return;
        try {
            var state = await api('/api/trip/' + Trip.tripId + '/state');
            renderState(state);
        } catch (err) {
            showError('State poll failed (' + err.code + '): ' + err.message);
        }
    }

    // --- error surface --------------------------------------------------------

    function showError(text) {
        var box = byId('trip-error');
        clear(box);
        box.appendChild(el('div', 'trip-error-title', '\u26A0 Trip needs attention'));
        box.appendChild(el('div', 'trip-error-text', text));
        box.hidden = false;
    }

    function hideError() {
        var box = byId('trip-error');
        clear(box);
        box.hidden = true;
    }

    // --- main state renderer ----------------------------------------------------

    function renderState(s) {
        renderStatusStrip(s);
        renderDag(s);
        renderClarifyChips(s);
        renderScopeChoices(s);
        renderVisaPanel(s);
        renderOptions(s);
        renderApprovalGate(s);
        renderPnr(s);
        renderItinerary(s);

        if (s.status === 'failed') {
            var failed = null;
            for (var i = s.nodes.length - 1; i >= 0; i--) {
                if (s.nodes[i].status === 'FAILED') { failed = s.nodes[i]; break; }
            }
            if (failed) {
                var d = failed.details || {};
                showError((d.error_code ? d.error_code + ' \u2014 ' : '') +
                    (d.message || failed.name + ' failed') +
                    (d.hint ? ' \u2014 ' + d.hint : ''));
            }
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

    // --- DAG panel (F9) ------------------------------------------------------------

    function renderDag(s) {
        var nodes = s.nodes || [];
        if (nodes.length === Trip.renderedNodeCount) return;
        Trip.renderedNodeCount = nodes.length;
        var list = byId('trip-dag-list');
        clear(list);
        if (nodes.length === 0) {
            var dagEmpty = el('li', 'trip-dag-empty',
                'No nodes yet \u2014 the DAG fills in as the agent works (1s refresh).');
            dagEmpty.setAttribute('data-testid', 'trip-dag-empty');
            list.appendChild(dagEmpty);
            return;
        }
        nodes.forEach(function (n) {
            var li = el('li', 'trip-dag-node trip-dag-' + String(n.status || 'pending').toLowerCase());
            li.setAttribute('data-testid', 'trip-dag-node');
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

    // --- clarification chips (L1 confirm-before-save) --------------------------------

    var PROFILE_CHIP_FIELDS = ['passport_country', 'home_city', 'expiry'];

    function renderClarifyChips(s) {
        var clarify = (s.outputs && s.outputs.clarify) || null;
        var questions = (clarify && clarify.questions) || [];
        var wrap = byId('trip-clarify-chips');
        questions.forEach(function (q) {
            var field = q.field;
            if (!field || Trip.answeredChips[field]) return;
            if (wrap.querySelector('[data-chip-field="' + field + '"]')) return;
            Trip.answeredChips[field] = true; // render once
            var chip = el('div', 'trip-chip');
            chip.setAttribute('data-chip-field', field);
            chip.setAttribute('data-testid', 'trip-chip-' + field);
            chip.appendChild(el('div', 'trip-chip-q', q.question));
            var row = el('div', 'trip-chip-row');
            var input = el('input', 'trip-chip-input');
            input.type = 'text';
            input.placeholder = field === 'passport_country' ? 'e.g. MM' : 'your answer';
            input.setAttribute('data-testid', 'chip-input-' + field);
            var btn = el('button', 'trip-chip-confirm', 'Confirm');
            btn.type = 'button';
            btn.setAttribute('data-testid', 'chip-confirm-' + field);
            btn.addEventListener('click', function () { confirmChip(field, chip, input, btn); });
            row.appendChild(input);
            row.appendChild(btn);
            chip.appendChild(row);
            wrap.appendChild(chip);
        });
    }

    async function confirmChip(field, chip, input, btn) {
        var value = input.value.trim();
        if (!value) { input.focus(); return; }
        btn.disabled = true;
        try {
            if (PROFILE_CHIP_FIELDS.indexOf(field) !== -1) {
                await api('/api/profile/' + USER_ID + '/' + field,
                          jsonOpts('PUT', { value: value, source: 'user' }));
                btn.textContent = '\u2713 saved to profile';
            } else {
                btn.textContent = '\u2713 noted';
            }
            chip.classList.add('confirmed');
            input.disabled = true;
            addChat('agent', field + ': ' + value + ' \u2014 confirmed.');
            refreshProfile();
        } catch (err) {
            btn.disabled = false;
            btn.textContent = 'Retry';
            showError('Saving ' + field + ' failed: ' + err.message);
        }
    }

    // --- scope clarification: exactly three choices -----------------------------------

    function renderScopeChoices(s) {
        var block = byId('trip-scope-block');
        var approval = findApproval(s, 'scope_clarification');
        if (!approval) { block.hidden = true; return; }
        if (!block.hidden && block.getAttribute('data-approval-id') === approval.approval_id) return;
        clear(block);
        block.hidden = false;
        block.setAttribute('data-approval-id', approval.approval_id);
        block.appendChild(el('div', 'trip-block-title', 'How far should the agent go?'));
        block.appendChild(el('p', 'trip-scope-hint',
            'Exactly three scopes \u2014 nothing irreversible happens until you choose.'));
        var grid = el('div', 'trip-scope-grid');
        (approval.options || []).forEach(function (opt) {
            var choice = opt.choice;
            var card = el('button', 'trip-scope-choice');
            card.type = 'button';
            card.setAttribute('data-testid', 'scope-choice-' + choice);
            card.appendChild(el('span', 'trip-scope-code', choice));
            card.appendChild(el('span', 'trip-scope-label', opt.label || choice));
            card.addEventListener('click', function () { chooseScope(approval, choice, block); });
            grid.appendChild(card);
        });
        block.appendChild(grid);
    }

    async function chooseScope(approval, choice, block) {
        block.querySelectorAll('.trip-scope-choice').forEach(function (b) { b.disabled = true; });
        try {
            await api('/api/trip/' + Trip.tripId + '/approvals/' + approval.approval_id,
                      jsonOpts('POST', { decision: choice, value: { choice: choice } }));
            addChat('agent', 'Scope locked: ' + choice + '. Continuing the plan.');
            block.hidden = true;
            pollState();
        } catch (err) {
            block.querySelectorAll('.trip-scope-choice').forEach(function (b) { b.disabled = false; });
            showError('Scope choice failed: ' + err.message + (err.hint ? ' \u2014 ' + err.hint : ''));
        }
    }

    // --- visa panel: dated citations + visible degraded/stale warnings ------------------

    function renderVisaPanel(s) {
        var visa = (s.outputs && s.outputs.visa_check) || null;
        var block = byId('trip-visa-block');
        if (!visa) { block.hidden = true; return; }
        clear(block);
        block.hidden = false;
        block.setAttribute('data-testid', 'trip-visa-panel');

        var head = el('div', 'trip-block-head');
        head.appendChild(el('span', 'trip-block-title', 'Visa & entry check'));
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
            if (r.as_of) li.appendChild(el('span', 'trip-visa-asof', 'as of ' + r.as_of));
            reqs.appendChild(li);
        });
        block.appendChild(reqs);

        var cites = el('ul', 'trip-visa-cites');
        (visa.citations || []).forEach(function (c) {
            var li = el('li', 'trip-visa-cite');
            li.appendChild(el('span', 'trip-cite-title', c.title || c.url));
            li.appendChild(el('span', 'trip-cite-url', c.url || '')); // text only — hostile data
            li.appendChild(el('span', 'trip-cite-date', 'retrieved ' + (c.retrieved_date || '?')));
            cites.appendChild(li);
        });
        block.appendChild(cites);
    }

    function chip(text, cls, testid) {
        var c = el('span', 'trip-honesty-chip ' + cls, text);
        if (testid) c.setAttribute('data-testid', testid);
        return c;
    }

    // --- flight options (Atlas Sandbox data) ---------------------------------------------

    function renderOptions(s) {
        var search = (s.outputs && s.outputs.flight_search) || null;
        var container = byId('trip-options');
        var options = (search && search.options) || [];
        var ids = options.map(function (o) { return o.id; }).join(',');
        if (ids === Trip.renderedOptionIds) return;
        Trip.renderedOptionIds = ids;
        clear(container);
        if (options.length === 0) {
            var optEmpty = el('div', 'trip-empty',
                Trip.tripId ? 'Searching the Atlas Sandbox\u2026'
                            : 'No flight options yet \u2014 submit a travel goal to begin.');
            optEmpty.setAttribute('data-testid', 'trip-options-empty');
            container.appendChild(optEmpty);
            return;
        }
        options.forEach(function (o) {
            var card = el('div', 'trip-option-card');
            card.setAttribute('data-testid', 'trip-option-card');
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
            times.appendChild(el('span', '', (o.dep && o.dep.time) || ''));
            times.appendChild(el('span', '', (o.arr && o.arr.time) || ''));
            card.appendChild(times);
            var price = el('div', 'trip-option-price');
            price.appendChild(el('span', 'trip-option-sgd', money(o.price && o.price.amount)));
            price.appendChild(el('span', 'trip-option-thb', moneyThb(o.price && o.price.amount)));
            card.appendChild(price);
            container.appendChild(card);
        });
    }

    // --- approval gate (L2) -----------------------------------------------------------------

    function findApproval(s, nodeName) {
        var list = s.pending_approvals || [];
        for (var i = 0; i < list.length; i++) {
            if (list[i].node_name === nodeName) return list[i];
        }
        return null;
    }

    function renderApprovalGate(s) {
        var banner = byId('trip-approval-banner');
        var overlay = byId('trip-approval-overlay');
        var approval = findApproval(s, 'approve_booking');
        if (!approval) {
            banner.hidden = true;
            overlay.hidden = true;
            Trip.approval = null;
            return;
        }
        if (Trip.approval && Trip.approval.approval_id === approval.approval_id) return;
        Trip.approval = approval;
        Trip.selectedOptionId = null;
        clear(banner);
        banner.hidden = false;
        banner.appendChild(el('div', 'trip-block-title', 'ApprovalGate \u00B7 booking needs your decision'));
        var row = el('div', 'trip-banner-row');
        row.appendChild(el('span', 'trip-banner-text',
            (approval.options || []).length + ' sandbox option(s) ready \u2014 the agent waits for your explicit approval.'));
        var openBtn = el('button', 'btn-trip-go trip-banner-open', 'Review & approve');
        openBtn.type = 'button';
        openBtn.setAttribute('data-testid', 'approval-open');
        openBtn.addEventListener('click', openApprovalModal);
        row.appendChild(openBtn);
        banner.appendChild(row);
    }

    function openApprovalModal() {
        var approval = Trip.approval;
        if (!approval) return;
        var overlay = byId('trip-approval-overlay');
        Trip.selectedOptionId = null;
        var opts = approval.options || [];
        var list = byId('trip-approval-options');
        clear(list);
        byId('trip-approval-note').hidden = true;
        opts.forEach(function (o, idx) {
            var btn = el('button', 'trip-approval-option');
            btn.type = 'button';
            btn.setAttribute('data-testid', 'approval-option-' + (o.id || idx));
            btn.setAttribute('data-option-id', o.id || '');
            btn.appendChild(el('span', 'trip-option-carrier', o.carrier || ''));
            btn.appendChild(el('span', 'trip-option-flight', o.flight_no || ''));
            var routeTxt = ((o.dep && o.dep.airport) || '?') + ' \u2192 ' + ((o.arr && o.arr.airport) || '?');
            btn.appendChild(el('span', 'trip-approval-route', routeTxt));
            btn.appendChild(el('span', 'trip-option-sgd', money(o.price && o.price.amount)));
            btn.addEventListener('click', function () { selectApprovalOption(btn, o.id); });
            list.appendChild(btn);
            if (idx === 0) selectApprovalOption(btn, o.id); // sensible default, still explicit
        });
        overlay.hidden = false;
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
            note.textContent = 'Pick one of the options above first.';
            note.hidden = false;
            return;
        }
        var approveBtn = byId('trip-approval-approve');
        var rejectBtn = byId('trip-approval-reject');
        approveBtn.disabled = true;
        rejectBtn.disabled = true;
        try {
            var payload = { decision: decision };
            if (decision === 'approve') payload.value = { option_id: Trip.selectedOptionId };
            var result = await api('/api/trip/' + Trip.tripId + '/approvals/' + Trip.approval.approval_id,
                                   jsonOpts('POST', payload));
            byId('trip-approval-overlay').hidden = true;
            byId('trip-approval-banner').hidden = true;
            Trip.approval = null;
            addChat('agent', decision === 'approve'
                ? 'Approved \u2014 booking through the Atlas Sandbox now.'
                : 'Rejected \u2014 the agent will not book. Trip halted.');
            if (result && result.error) {
                showError(result.error.code + ' \u2014 ' + result.error.message +
                          (result.error.hint ? ' \u2014 ' + result.error.hint : ''));
            }
            pollState();
        } catch (err) {
            showError('Approval failed: ' + err.message + (err.hint ? ' \u2014 ' + err.hint : ''));
        } finally {
            approveBtn.disabled = false;
            rejectBtn.disabled = false;
        }
    }

    // --- PNR confirmation screen --------------------------------------------------------------

    function renderPnr(s) {
        var block = byId('trip-pnr-block');
        var booking = (s.outputs && s.outputs.booking) || null;
        if (!booking || Trip.pnrShown) { if (!booking) block.hidden = true; return; }
        Trip.pnrShown = true;
        clear(block);
        block.hidden = false;
        block.appendChild(el('div', 'trip-pnr-kicker', 'Booking confirmed \u00B7 Atlas Sandbox'));
        var pnr = el('div', 'trip-pnr-code', booking.pnr || '');
        pnr.setAttribute('data-testid', 'pnr-code');
        block.appendChild(pnr);
        var status = el('div', 'trip-pnr-status', 'Status: ' + (booking.status || 'CONFIRMED'));
        status.setAttribute('data-testid', 'pnr-status');
        block.appendChild(status);
        var rec = booking.booking || null;
        var opt = (rec && rec.option) || null;
        if (opt) {
            var line = el('div', 'trip-pnr-route',
                (opt.carrier || '') + ' ' + (opt.flight_no || '') + ' \u00B7 ' +
                ((opt.dep && opt.dep.airport) || '?') + ' \u2192 ' + ((opt.arr && opt.arr.airport) || '?'));
            block.appendChild(line);
        }
        var chips = el('div', 'trip-pnr-chips');
        if (booking.monitor_armed || (rec && rec.monitor_armed)) {
            chips.appendChild(chip('monitoring armed', 'trip-chip-good', 'pnr-monitor'));
        }
        chips.appendChild(chip('Atlas Sandbox booking \u2014 not a live airline seat', 'trip-chip-sandbox', 'pnr-provenance'));
        block.appendChild(chips);
        addChat('agent', 'PNR ' + (booking.pnr || '') + ' issued. Monitoring is armed.');
    }

    // --- itinerary with honesty chips -----------------------------------------------------------

    function renderItinerary(s) {
        var itinerary = (s.outputs && s.outputs.itinerary) || null;
        var container = byId('trip-itinerary');
        var items = (itinerary && itinerary.items) || [];
        if (items.length === Trip.renderedItineraryCount) return;
        Trip.renderedItineraryCount = items.length;
        clear(container);
        if (items.length === 0) {
            var itinEmpty = el('div', 'trip-empty',
                'Nothing planned yet \u2014 the itinerary appears after a confirmed booking.');
            itinEmpty.setAttribute('data-testid', 'trip-itinerary-empty');
            container.appendChild(itinEmpty);
            return;
        }
        items.forEach(function (item) {
            var row = el('div', 'trip-itin-item trip-itin-' + (item.kind || 'item'));
            row.setAttribute('data-testid', 'trip-itin-item');
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
                right.appendChild(chip('\uD83D\uDCA1 suggestion only', 'trip-chip-llm', 'itin-chip-llm'));
            }
            var priceTxt = sgdRange(item.price_range_sgd);
            if (priceTxt) {
                right.appendChild(el('span', 'trip-itin-price', priceTxt + ' ' + sgdToThb(item.price_range_sgd)));
            } else if (item.kind !== 'flight') {
                right.appendChild(el('span', 'trip-itin-price trip-itin-noprice', 'price not sourced'));
            }
            row.appendChild(right);
            container.appendChild(row);
        });
    }

    // --- profile editor (F5: view/edit/delete, masked passport) -----------------------------------

    var PROFILE_ROWS = [
        { key: 'passport_country', group: 'identity', label: 'Passport country' },
        { key: 'passport_no', group: 'identity', label: 'Passport number', masked: true },
        { key: 'expiry', group: 'identity', label: 'Passport expiry' },
        { key: 'home_city', group: 'identity', label: 'Home city' },
        { key: 'cabin', group: 'prefs', label: 'Cabin' },
        { key: 'diet', group: 'prefs', label: 'Diet' },
        { key: 'budget_range', group: 'prefs', label: 'Budget range' },
        { key: 'airlines_like', group: 'prefs', label: 'Preferred airlines', list: true }
    ];

    function profileValue(profile, spec) {
        if (spec.group === 'identity') {
            if (spec.masked) return profile.identity.passport_no_masked || '';
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
                'Profile could not be loaded (' + err.code + ').'));
        }
    }

    function renderProfile(profile) {
        var rows = byId('trip-profile-rows');
        clear(rows);
        var consent = byId('trip-consent');
        consent.checked = !!(profile.consent && profile.consent.store_local);

        // greeting (F10 two-run memory moment)
        var greeting = byId('trip-greeting');
        var homeCity = profile.identity.home_city;
        greeting.textContent = homeCity
            ? ('Welcome back \u2014 planning from ' + homeCity + ' again.')
            : 'Tell me where you need to be \u2014 I\u2019ll plan the rest.';

        PROFILE_ROWS.forEach(function (spec) {
            rows.appendChild(profileRow(spec, profileValue(profile, spec), profile));
        });

        var fields = profile.fields || {};
        Object.keys(fields).forEach(function (key) {
            if (PROFILE_ROWS.some(function (s) { return s.key === key; })) return;
            var f = fields[key];
            var row = profileRow({ key: key, group: 'fields', label: key }, f.value, profile);
            var src = el('span', 'trip-profile-source trip-src-' + (f.source || 'user'),
                         f.source === 'ai_inferred' ? 'ai-inferred' : 'user');
            row.querySelector('.trip-profile-label').appendChild(src);
            rows.appendChild(row);
        });

        if (rows.childNodes.length === 0) {
            rows.appendChild(el('div', 'trip-empty', 'Profile is empty \u2014 add details below.'));
        }
    }

    function profileRow(spec, value, profile) {
        var row = el('div', 'trip-profile-row');
        row.setAttribute('data-testid', 'profile-row-' + spec.key);
        var label = el('div', 'trip-profile-label', spec.label);
        var valueEl = el('div', 'trip-profile-value' + (spec.masked ? ' trip-profile-masked' : ''),
                         value || '\u2014');
        valueEl.setAttribute('data-testid', 'profile-value-' + spec.key);
        if (spec.masked) valueEl.setAttribute('data-masked', 'true');
        var actions = el('div', 'trip-profile-actions');

        var input = el('input', 'trip-profile-input');
        input.type = 'text';
        input.placeholder = spec.masked ? 'new passport number (stored masked)' : (value || '');
        input.setAttribute('data-testid', 'profile-input-' + spec.key);
        input.hidden = true;

        var editBtn = el('button', 'trip-profile-edit', 'Edit');
        editBtn.type = 'button';
        editBtn.setAttribute('data-testid', 'profile-edit-' + spec.key);
        var saveBtn = el('button', 'trip-profile-save', 'Save');
        saveBtn.type = 'button';
        saveBtn.hidden = true;
        saveBtn.setAttribute('data-testid', 'profile-save-' + spec.key);
        var delBtn = el('button', 'trip-profile-delete', 'Delete');
        delBtn.type = 'button';
        delBtn.setAttribute('data-testid', 'profile-delete-' + spec.key);

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
            showError('Saving ' + field + ' failed: ' + err.message + (err.hint ? ' \u2014 ' + err.hint : ''));
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

    // --- init ------------------------------------------------------------------------

    function init() {
        byId('trip-goal-form').addEventListener('submit', submitGoal);
        byId('trip-approval-approve').addEventListener('click', function () { resolveApproval('approve'); });
        byId('trip-approval-reject').addEventListener('click', function () { resolveApproval('reject'); });
        byId('trip-consent').addEventListener('change', function (ev) {
            setConsent(ev.target.checked);
        });
        refreshProfile();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
