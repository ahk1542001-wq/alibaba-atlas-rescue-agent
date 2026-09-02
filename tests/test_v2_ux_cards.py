"""U3 Suggestion Cards hermetic tests — photo honesty, provenance footers, and CTA boundaries.

Gate criteria (§U3):
- String table coverage: all cards.* keys exist in both en and zh tables
- Honesty footer on every card: "suggestion only", "Atlas Sandbox", "deterministic engine", "estimated"
- No booking/payment CTAs: strictly forbidden from cards (only follow-up, add to plan, view on map)
- Photo sourcing honesty:
  * Permitted: owner-approved local assets under /static/assets/ or labeled placeholder block
  * Alt text must honestly describe source (e.g. "illustrative placeholder")
  * Zero unverified external hotlinking
- DOM containers and testids:
  * concierge-suggestion-cards container exists
  * suggestion-cards-grid and suggestion-card rendering logic
  * Canary testids preserved
"""

import json
from pathlib import Path
import re
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "static"
I18N_DIR = STATIC_DIR / "i18n"

REQUIRED_CARD_KEYS = [
    "cards.suggestion_footer",
    "cards.data_footer_atlas",
    "cards.data_footer_engine",
    "cards.data_footer_estimated",
    "cards.action_followup",
    "cards.action_add_plan",
    "cards.action_view_map",
    "cards.no_image",
    "cards.photo_placeholder_alt",
]

FORBIDDEN_CARD_CTAS = [
    "book now",
    "instant book",
    "pay now",
    "checkout",
    "reserve now",
    "立即预订",
    "立即支付",
    "结账",
]


@pytest.fixture
def index_html():
    with open(STATIC_DIR / "index.html", encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def app_js():
    with open(STATIC_DIR / "app.js", encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def styles_css():
    with open(STATIC_DIR / "styles.css", encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def en_table():
    with open(I18N_DIR / "strings.en.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def zh_table():
    with open(I18N_DIR / "strings.zh.json", encoding="utf-8") as f:
        return json.load(f)


class TestCardStringTables:
    """Verify all card keys exist and are populated in en and zh."""

    def test_all_card_keys_present_in_en(self, en_table):
        for key in REQUIRED_CARD_KEYS:
            assert key in en_table, f"Missing {key} in strings.en.json"
            assert len(en_table[key].strip()) > 0

    def test_all_card_keys_present_in_zh(self, zh_table):
        for key in REQUIRED_CARD_KEYS:
            assert key in zh_table, f"Missing {key} in strings.zh.json"
            assert len(zh_table[key].strip()) > 0

    def test_no_payment_ctas_in_card_string_tables(self, en_table, zh_table):
        card_keys = [k for k in REQUIRED_CARD_KEYS if k.startswith("cards.action_")]
        for k in card_keys:
            en_val = en_table[k].lower()
            zh_val = zh_table[k]
            for forbidden in FORBIDDEN_CARD_CTAS:
                assert forbidden not in en_val, f"Card action key {k} has forbidden CTA: {forbidden}"
                assert forbidden not in zh_val, f"Card action key {k} has forbidden CTA: {forbidden}"


class TestCardNoPaymentCtasInCode:
    """Verify renderSuggestionCards code contains zero booking or payment CTAs."""

    def test_app_js_render_cards_has_no_payment_ctas(self, app_js):
        match = re.search(r"function renderSuggestionCards\([^\)]*\)\s*\{([\s\S]*?)\n        \}", app_js)
        assert match, "renderSuggestionCards not found in app.js"
        body = match.group(1)
        lower_body = body.lower()
        for forbidden in FORBIDDEN_CARD_CTAS:
            assert forbidden not in lower_body, f"renderSuggestionCards contains forbidden CTA: {forbidden}"
        assert "stripe" not in lower_body
        assert "payment_intent" not in lower_body
        assert "checkout" not in lower_body
        assert "booking_token" not in lower_body


class TestCardPhotoHonesty:
    """Verify photo honesty and placeholder handling."""

    def test_card_photo_source_allowlist_and_placeholder(self, app_js):
        """Images must only be local assets or honest placeholder blocks."""
        assert "card-photo-placeholder" in app_js
        assert "cards.no_image" in app_js
        assert "cards.photo_placeholder_alt" in app_js
        # Assert external hotlinking is not used as default
        assert "http://" not in app_js.split("renderSuggestionCards")[1].split("window.renderSuggestionCards")[0]
        assert "https://" not in app_js.split("renderSuggestionCards")[1].split("window.renderSuggestionCards")[0]


class TestCardProvenanceFooter:
    """Verify provenance footer rendering."""

    def test_card_provenance_footers_rendered(self, app_js):
        assert "card-honesty-footer" in app_js
        assert "card-honesty-badge" in app_js
        assert "cards.suggestion_footer" in app_js
        assert "cards.data_footer_atlas" in app_js
        assert "cards.data_footer_engine" in app_js
        assert "cards.data_footer_estimated" in app_js


class TestDomIntegrityAndCanaryTestIds:
    """Verify DOM container existence and canary testid stability."""

    def test_concierge_suggestion_cards_container_exists(self, index_html):
        assert 'id="concierge-suggestion-cards"' in index_html
        assert 'data-testid="concierge-suggestion-cards"' in index_html

    def test_canary_concierge_chips_preserved(self, index_html):
        assert 'data-testid="chip-vegetarian"' in index_html
        assert 'data-testid="chip-gate"' in index_html
        assert 'data-testid="chip-baggage"' in index_html
        assert 'data-testid="chip-claim"' in index_html
