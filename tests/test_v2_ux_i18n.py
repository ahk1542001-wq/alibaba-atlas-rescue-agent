"""U4 i18n hermetic tests — locale system validation.

Gate criteria (§U4):
- Both first-release locales (en, zh) render non-empty text for wave-1 keys
- Zero raw keys exposed (t() never returns key name when en table has it)
- Missing-key fallback to en is silent and logged
- Reserved `my` slot falls back to en without errors
- data-testid values are locale-independent and never translated
- Locale preference persists via localStorage key
- zh table is flagged review_status: machine_draft
- Key coverage: every en key exists in zh (no gaps)
"""

import json
from pathlib import Path

import pytest

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
I18N_DIR = STATIC_DIR / "i18n"


# --- Fixtures ---

@pytest.fixture
def en_table():
    with open(I18N_DIR / "strings.en.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def zh_table():
    with open(I18N_DIR / "strings.zh.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def my_table():
    with open(I18N_DIR / "strings.my.json", encoding="utf-8") as f:
        return json.load(f)


# --- Table structure tests ---

class TestStringTableStructure:
    """Validate JSON structure and metadata of string tables."""

    def test_en_table_is_valid_json(self, en_table):
        assert isinstance(en_table, dict)
        assert len(en_table) > 10, "en table suspiciously small"

    def test_zh_table_is_valid_json(self, zh_table):
        assert isinstance(zh_table, dict)
        assert len(zh_table) > 10, "zh table suspiciously small"

    def test_my_table_is_valid_json_reserved(self, my_table):
        assert isinstance(my_table, dict)
        # my should only have _meta (reserved, not populated)
        non_meta_keys = [k for k in my_table if not k.startswith("_")]
        assert len(non_meta_keys) == 0, (
            f"my table should be reserved/empty but has keys: {non_meta_keys}")

    def test_en_meta_is_source_of_truth(self, en_table):
        meta = en_table.get("_meta", {})
        assert meta.get("locale") == "en"
        assert meta.get("review_status") == "source_of_truth"

    def test_zh_meta_is_machine_draft(self, zh_table):
        meta = zh_table.get("_meta", {})
        assert meta.get("locale") == "zh"
        assert meta.get("review_status") == "machine_draft", (
            "zh table MUST be flagged review_status: machine_draft per §U4 governance")

    def test_my_meta_is_reserved(self, my_table):
        meta = my_table.get("_meta", {})
        assert meta.get("locale") == "my"
        assert meta.get("review_status") == "reserved_not_populated"


# --- Key coverage tests ---

class TestKeyCoverage:
    """Every en key must exist in zh; no orphaned or missing keys."""

    def test_zh_covers_all_en_keys(self, en_table, zh_table):
        en_keys = {k for k in en_table if not k.startswith("_")}
        zh_keys = {k for k in zh_table if not k.startswith("_")}
        missing_in_zh = en_keys - zh_keys
        assert not missing_in_zh, (
            f"zh table missing {len(missing_in_zh)} en keys: "
            f"{sorted(missing_in_zh)[:20]}")

    def test_no_orphan_keys_in_zh(self, en_table, zh_table):
        en_keys = {k for k in en_table if not k.startswith("_")}
        zh_keys = {k for k in zh_table if not k.startswith("_")}
        orphan = zh_keys - en_keys
        assert not orphan, (
            f"zh table has {len(orphan)} keys not in en: {sorted(orphan)[:20]}")

    def test_no_empty_values_in_en(self, en_table):
        for key, value in en_table.items():
            if key.startswith("_"):
                continue
            assert isinstance(value, str) and value.strip(), (
                f"en key '{key}' has empty/non-string value")

    def test_no_empty_values_in_zh(self, zh_table):
        for key, value in zh_table.items():
            if key.startswith("_"):
                continue
            assert isinstance(value, str) and value.strip(), (
                f"zh key '{key}' has empty/non-string value")


# --- Wave-1 surface coverage ---

class TestWave1Surfaces:
    """Wave-1 mandatory surfaces must have keys in both locales."""

    WAVE1_PREFIXES = [
        "chips.",        # Prompt chips (§U5)
        "view.",         # View/section headers
        "safety.label.", # Safety labels and honesty badges
        "topbar.",       # Topbar controls
        "nav.",          # Sidebar navigation
        "nav_mobile.",   # Mobile navigation
    ]

    def test_wave1_keys_present_in_en(self, en_table):
        for prefix in self.WAVE1_PREFIXES:
            keys = [k for k in en_table if k.startswith(prefix)]
            assert len(keys) >= 3, (
                f"Wave-1 prefix '{prefix}' has only {len(keys)} en keys — need >= 3")

    def test_wave1_keys_present_in_zh(self, zh_table):
        for prefix in self.WAVE1_PREFIXES:
            keys = [k for k in zh_table if k.startswith(prefix)]
            assert len(keys) >= 3, (
                f"Wave-1 prefix '{prefix}' has only {len(keys)} zh keys — need >= 3")

    def test_chips_have_both_locales(self, en_table, zh_table):
        chip_keys = [k for k in en_table if k.startswith("chips.")]
        for key in chip_keys:
            assert key in zh_table, f"Chip key '{key}' missing from zh"
            assert zh_table[key].strip(), f"Chip key '{key}' empty in zh"


# --- data-testid immutability ---

class TestTestIdImmutability:
    """data-testid values must NEVER appear as i18n keys or be translated."""

    def test_no_testid_pattern_in_keys(self, en_table):
        for key in en_table:
            assert "data-testid" not in key, (
                f"Key '{key}' contains data-testid — testids must never be translated")
            assert "testid" not in key.lower(), (
                f"Key '{key}' references testid — forbidden")

    def test_index_html_testids_unchanged(self):
        """Verify critical canary-pinned data-testid values are still present."""
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        critical_testids = [
            "locale-toggle", "nav-rescue", "nav-search", "nav-concierge",
            "nav-radar", "nav-trip", "btn-add-flight", "btn-simulate",
            "aj-profile-open", "btn-search", "chat-input", "btn-send",
            "chip-vegetarian", "chip-gate", "chip-baggage", "chip-claim",
            "trip-goal-input", "trip-goal-submit", "trip-options",
            "trip-itinerary", "aj-step-1", "aj-step-2", "aj-step-3",
            "aj-step-4", "aj-step-5", "sandbox-provenance",
        ]
        for tid in critical_testids:
            assert f'data-testid="{tid}"' in html, (
                f"Critical data-testid '{tid}' missing from index.html")


# --- i18n.js module validation ---

class TestI18nModule:
    """Validate the i18n.js module exists and has required API surface."""

    def test_i18n_js_exists(self):
        assert (STATIC_DIR / "i18n.js").exists(), "static/i18n.js not found"

    def test_i18n_js_exports_required_api(self):
        js = (STATIC_DIR / "i18n.js").read_text(encoding="utf-8")
        required_exports = [
            "window.TravelCareI18n",
            "applyLocale",
            "toggleLocale",
            "setLocale",
            "getLocale",
            "STORAGE_KEY",
            "travelcare.locale",
        ]
        for export in required_exports:
            assert export in js, f"i18n.js missing required export/ref: {export}"

    def test_i18n_js_never_renders_raw_key_as_only_fallback(self):
        """i18n.js must fall back to en table, not render raw key."""
        js = (STATIC_DIR / "i18n.js").read_text(encoding="utf-8")
        # Must have en fallback logic
        assert "DEFAULT_LOCALE" in js
        assert "tables[DEFAULT_LOCALE]" in js or "tables[currentLocale]" in js

    def test_setlocale_lazyloads_target_table(self):
        """Regression guard: a runtime en->zh toggle must lazy-load the zh table.

        init() only loads the string table for the locale already stored at page
        load, so setLocale() must fetch the target table on first switch. Without
        this the toggle label shows ZH (and html lang flips to zh-Hans) while t()
        silently falls back to en until the user manually reloads — the UI never
        actually translates. Guards the fix for that defect.
        """
        js = (STATIC_DIR / "i18n.js").read_text(encoding="utf-8")
        body = js.split("function setLocale(", 1)[1].split("\n    }", 1)[0]
        assert "tables[locale]" in body, (
            "setLocale must check whether the target locale table is loaded")
        assert "loadTable(locale)" in body, (
            "setLocale must lazy-load the target locale table on first switch")

    def test_i18n_js_loaded_before_app_js(self):
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        i18n_pos = html.find("i18n.js")
        app_pos = html.find("app.js")
        assert i18n_pos > 0, "i18n.js not loaded in index.html"
        assert app_pos > 0, "app.js not loaded in index.html"
        assert i18n_pos < app_pos, (
            "i18n.js must be loaded BEFORE app.js for t() availability")

    def test_locale_toggle_has_correct_testid(self):
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        assert 'data-testid="locale-toggle"' in html
        assert 'TravelCareI18n.toggleLocale()' in html

    def test_machine_translated_footnote_exists(self):
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        assert 'id="i18n-machine-translated-note"' in html
        assert "hidden" in html.split('id="i18n-machine-translated-note"')[1][:100]


# --- Fallback behavior (my locale) ---

class TestMyLocaleFallback:
    """Reserved `my` locale must silently fall back to en."""

    def test_my_not_in_supported_locales(self):
        js = (STATIC_DIR / "i18n.js").read_text(encoding="utf-8")
        # SUPPORTED_LOCALES should be ['en', 'zh'] only
        assert "'my'" not in js.split("SUPPORTED_LOCALES")[1].split("]")[0], (
            "my must NOT be in SUPPORTED_LOCALES (reserved, not selectable)")

    def test_my_table_has_no_translatable_keys(self, my_table):
        non_meta = {k: v for k, v in my_table.items() if not k.startswith("_")}
        assert len(non_meta) == 0, (
            f"my table has translatable keys but should be empty: {list(non_meta)[:5]}")
