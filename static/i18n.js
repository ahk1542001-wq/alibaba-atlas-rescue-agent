/* ============================================================
   TravelCare AI — i18n Locale System (U4)
   Static string-table approach: no framework, no build step.
   Locales: en (source of truth), zh (machine_draft).
   Reserved: my (not populated, not selectable in first release).
   Persistence: localStorage key "travelcare.locale".
   Toggle: data-testid="locale-toggle" cycles en ↔ zh.
   Fallback: missing key → en value + console.warn (fail-closed).
   Never renders raw keys or invents translations at runtime.
   ============================================================ */
(function () {
    'use strict';

    var STORAGE_KEY = 'travelcare.locale';
    var SUPPORTED_LOCALES = ['en', 'zh'];
    var DEFAULT_LOCALE = 'en';
    var tables = {};          // locale -> { key: string }
    var currentLocale = DEFAULT_LOCALE;
    var loaded = false;
    var pendingCallbacks = [];

    // --- Core API (exposed on window.TravelCareI18n) ---

    /**
     * t(key, params) — translate a key in the current locale.
     * Falls back to en if key is missing; never returns the raw key.
     * Supports {param} interpolation.
     */
    function t(key, params) {
        var value = null;
        var table = tables[currentLocale];
        if (table && Object.prototype.hasOwnProperty.call(table, key)) {
            value = table[key];
        }
        if (value === null || value === undefined) {
            // fallback to en
            var enTable = tables[DEFAULT_LOCALE];
            if (enTable && Object.prototype.hasOwnProperty.call(enTable, key)) {
                value = enTable[key];
                if (currentLocale !== DEFAULT_LOCALE) {
                    console.warn('[i18n] Missing key in "' + currentLocale + '": "' + key + '" — fell back to en.');
                }
            }
        }
        if (value === null || value === undefined) {
            // absolute fallback: return en key value or descriptive placeholder
            console.warn('[i18n] Key "' + key + '" not found in any locale table.');
            value = key;
        }
        // interpolation
        if (params && typeof params === 'object') {
            Object.keys(params).forEach(function (k) {
                value = value.replace(new RegExp('\\{' + k + '\\}', 'g'), String(params[k]));
            });
        }
        return value;
    }

    /**
     * getLocale() — returns the current active locale code.
     */
    function getLocale() {
        return currentLocale;
    }

    /**
     * isMachineTranslated() — true when zh is active (per §U4 governance).
     */
    function isMachineTranslated() {
        return currentLocale === 'zh';
    }

    /**
     * applyLocale() — re-render all data-i18n elements with current locale.
     * Called automatically after setLocale() and on init.
     */
    function applyLocale() {
        if (!loaded) return;

        // Process all elements with data-i18n attribute
        var elements = document.querySelectorAll('[data-i18n]');
        for (var i = 0; i < elements.length; i++) {
            var el = elements[i];
            var key = el.getAttribute('data-i18n');
            if (!key) continue;
            var translated = t(key);
            // Support data-i18n-attr for attribute translation (e.g. placeholder)
            var attrTarget = el.getAttribute('data-i18n-attr');
            if (attrTarget) {
                el.setAttribute(attrTarget, translated);
            } else {
                el.textContent = translated;
            }
        }

        // Process sidebar nav labels (data-label values for display)
        var navItems = document.querySelectorAll('.nav-icon[data-i18n-nav]');
        for (var j = 0; j < navItems.length; j++) {
            var navKey = navItems[j].getAttribute('data-i18n-nav');
            if (navKey) {
                navItems[j].setAttribute('title', t(navKey));
                navItems[j].setAttribute('aria-label', t(navKey));
            }
        }

        // Process bottom nav labels
        var mnavItems = document.querySelectorAll('.bottom-nav-item[data-i18n-nav]');
        for (var k = 0; k < mnavItems.length; k++) {
            var mnavKey = mnavItems[k].getAttribute('data-i18n-nav');
            if (mnavKey) {
                var span = mnavItems[k].querySelector('span');
                if (span) span.textContent = t(mnavKey);
            }
        }

        // Update locale toggle display
        updateToggleDisplay();

        // Show/hide machine-translated footnote
        updateMachineTranslatedFootnote();

        // Update html lang attribute
        document.documentElement.setAttribute('lang', currentLocale === 'zh' ? 'zh-Hans' : 'en');

        // Notify listeners
        notifyListeners();
    }

    /**
     * setLocale(locale) — switch locale, persist, re-render.
     */
    function setLocale(locale) {
        if (SUPPORTED_LOCALES.indexOf(locale) === -1) {
            console.warn('[i18n] Unsupported locale "' + locale + '" — falling back to en.');
            locale = DEFAULT_LOCALE;
        }
        currentLocale = locale;
        try {
            localStorage.setItem(STORAGE_KEY, locale);
        } catch (e) { /* storage unavailable */ }
        applyLocale();
    }

    /**
     * toggleLocale() — cycle en ↔ zh.
     */
    function toggleLocale() {
        var next = (currentLocale === 'en') ? 'zh' : 'en';
        setLocale(next);
    }

    /**
     * onLocaleChange(fn) — register a callback for locale changes.
     */
    function onLocaleChange(fn) {
        if (typeof fn === 'function') pendingCallbacks.push(fn);
    }

    function notifyListeners() {
        pendingCallbacks.forEach(function (fn) {
            try { fn(currentLocale); } catch (e) { /* listener error */ }
        });
    }

    function updateToggleDisplay() {
        var toggle = document.querySelector('[data-testid="locale-toggle"]');
        if (toggle) {
            var label = toggle.querySelector('.locale-toggle-label');
            if (label) label.textContent = currentLocale.toUpperCase();
            toggle.setAttribute('aria-label', t('topbar.locale_label') + ': ' + currentLocale.toUpperCase());
        }
    }

    function updateMachineTranslatedFootnote() {
        var footnote = document.getElementById('i18n-machine-translated-note');
        if (footnote) {
            footnote.hidden = !isMachineTranslated();
            if (!footnote.hidden) {
                footnote.textContent = t('safety.label.machine_translated');
            }
        }
    }

    // --- Loading ---

    function loadTable(locale) {
        return fetch('/static/i18n/strings.' + locale + '.json')
            .then(function (res) {
                if (!res.ok) throw new Error('HTTP ' + res.status);
                return res.json();
            })
            .then(function (data) {
                tables[locale] = data;
            })
            .catch(function (err) {
                console.warn('[i18n] Failed to load strings.' + locale + '.json:', err);
                tables[locale] = {};
            });
    }

    function init() {
        // Determine initial locale from localStorage
        var stored = null;
        try {
            stored = localStorage.getItem(STORAGE_KEY);
        } catch (e) { /* storage unavailable */ }
        if (stored && SUPPORTED_LOCALES.indexOf(stored) !== -1) {
            currentLocale = stored;
        }

        // Load en always (source of truth), then current locale if different
        var promises = [loadTable(DEFAULT_LOCALE)];
        if (currentLocale !== DEFAULT_LOCALE) {
            promises.push(loadTable(currentLocale));
        }

        Promise.all(promises).then(function () {
            loaded = true;
            applyLocale();
        });
    }

    // --- Public API ---

    window.TravelCareI18n = {
        t: t,
        getLocale: getLocale,
        setLocale: setLocale,
        toggleLocale: toggleLocale,
        applyLocale: applyLocale,
        isMachineTranslated: isMachineTranslated,
        onLocaleChange: onLocaleChange,
        SUPPORTED_LOCALES: SUPPORTED_LOCALES,
        DEFAULT_LOCALE: DEFAULT_LOCALE,
        STORAGE_KEY: STORAGE_KEY
    };

    // Shorthand for dynamic JS usage
    window.t = t;

    // Initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
