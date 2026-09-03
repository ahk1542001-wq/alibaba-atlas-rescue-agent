"""U5 Prompt Chips hermetic tests — contextual quick-action suggestions validation.

Gate criteria (§U5):
- Contextual sets per state:
  * Trip view: empty state vs active trip state
  * Concierge view: normal vs active disruption
  * Rescue view: active disruption chips
- String table coverage: all chip keys present in both first-release locales (en, zh)
- Suggestion-grade wording: disruption chips must not imply auto-booking or guaranteed payout
- No-gate-bypass assertion: chips route through existing input pipelines;
  no approval gates skipped, no direct booking/payout mutations
- Canary testid immutability: pre-existing chip testids remain untouched
"""

import json
from pathlib import Path
import re
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "static"
I18N_DIR = STATIC_DIR / "i18n"

REQUIRED_CHIP_KEYS = [
    "chips.concierge.vegetarian",
    "chips.concierge.gate",
    "chips.concierge.baggage",
    "chips.concierge.claim",
    "chips.trip.visa",
    "chips.trip.rights",
    "chips.trip.tomorrow",
    "chips.trip.hotel",
    "chips.trip.safety",
    "chips.rescue.options",
    "chips.rescue.compensation",
    "chips.rescue.alternatives",
]

FORBIDDEN_AUTONOMY_WORDS = [
    "auto-book",
    "autobook",
    "guaranteed payout",
    "instant rebook",
    "auto-rebook",
    "自动预订",
    "保证赔付",
]


@pytest.fixture
def en_table():
    with open(I18N_DIR / "strings.en.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def zh_table():
    with open(I18N_DIR / "strings.zh.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def index_html():
    with open(STATIC_DIR / "index.html", encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def trip_js():
    with open(STATIC_DIR / "trip.js", encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def app_js():
    with open(STATIC_DIR / "app.js", encoding="utf-8") as f:
        return f.read()


class TestChipStringTables:
    """Validate string table coverage and parity for all chip keys."""

    def test_all_chip_keys_in_en_table(self, en_table):
        for key in REQUIRED_CHIP_KEYS:
            assert key in en_table, f"Missing required chip key in strings.en.json: {key}"
            assert len(en_table[key].strip()) > 0, f"Empty value for chip key in strings.en.json: {key}"

    def test_all_chip_keys_in_zh_table(self, zh_table):
        for key in REQUIRED_CHIP_KEYS:
            assert key in zh_table, f"Missing required chip key in strings.zh.json: {key}"
            assert len(zh_table[key].strip()) > 0, f"Empty value for chip key in strings.zh.json: {key}"

    def test_disruption_chips_are_suggestion_grade(self, en_table, zh_table):
        """Disruption chips must be suggestion-grade, never implying auto-booking."""
        rescue_keys = [k for k in REQUIRED_CHIP_KEYS if k.startswith("chips.rescue.")]
        for key in rescue_keys:
            en_val = en_table[key].lower()
            zh_val = zh_table[key]
            for forbidden in FORBIDDEN_AUTONOMY_WORDS:
                assert forbidden not in en_val, f"Chip key {key} contains forbidden autonomy wording: {forbidden}"
                assert forbidden not in zh_val, f"Chip key {key} contains forbidden autonomy wording: {forbidden}"


class TestContextualSetsDerivation:
    """Validate deterministic contextual chip derivation rules."""

    def test_trip_js_defines_contextual_sets(self, trip_js):
        """trip.js must define distinct chip sets for empty vs active trip."""
        assert "renderContextualTripChips" in trip_js
        assert "chips.trip.tomorrow" in trip_js
        assert "chips.trip.visa" in trip_js
        assert "chips.trip.safety" in trip_js
        assert "chips.trip.hotel" in trip_js
        assert "chips.trip.rights" in trip_js

    def test_app_js_defines_rescue_and_concierge_chips(self, app_js):
        """app.js must define rescue prompt chips and contextual concierge chips."""
        assert "renderRescuePromptChips" in app_js
        assert "renderContextualConciergeChips" in app_js
        assert "chips.rescue.options" in app_js
        assert "chips.rescue.compensation" in app_js
        assert "chips.rescue.alternatives" in app_js


class TestNoGateBypass:
    """Verify that clicking chips strictly routes through existing input pipelines."""

    def test_trip_chips_route_to_submit_goal(self, trip_js):
        """Trip chips must populate trip-goal-input and call submitGoal."""
        # Find renderContextualTripChips function block
        match = re.search(r"function renderContextualTripChips\([^\)]*\)\s*\{([\s\S]*?)\n    \}", trip_js)
        assert match, "renderContextualTripChips function not found in trip.js"
        body = match.group(1)
        assert "submitGoal" in body, "Trip chips must route through existing submitGoal pipeline"
        assert "approve_booking" not in body, "Trip chips must NOT bypass approval"
        assert "fetch(" not in body, "Trip chips must NOT execute direct raw API mutations"

    def test_rescue_chips_route_to_concierge_or_scroll(self, app_js):
        """Rescue chips must route to concierge or scroll, never trigger direct payouts."""
        match = re.search(r"function renderRescuePromptChips\([^\)]*\)\s*\{([\s\S]*?)\n        \}", app_js)
        assert match, "renderRescuePromptChips function not found in app.js"
        body = match.group(1)
        assert "sendQuickChat" in body or "scrollIntoView" in body
        assert "filePayout" not in body, "Rescue chips must NOT bypass payout user approval"
        assert "bookRescue" not in body, "Rescue chips must NOT trigger unapproved booking"


class TestDomIntegrityAndTestIds:
    """Verify HTML container existence and immutable canary testids."""

    def test_trip_prompt_chips_container_exists(self, index_html):
        assert 'data-testid="trip-prompt-chips"' in index_html
        assert 'id="trip-prompt-chips"' in index_html

    def test_rescue_prompt_chips_container_exists(self, index_html):
        assert 'data-testid="rescue-prompt-chips"' in index_html
        assert 'id="rescue-prompt-chips"' in index_html

    def test_concierge_context_chips_container_exists(self, index_html):
        assert 'data-testid="concierge-context-chips"' in index_html
        assert 'id="concierge-context-chips"' in index_html

    def test_canary_pinned_chip_testids_preserved(self, index_html):
        """Canary pins these exact testids: they must remain present and unchanged."""
        assert 'data-testid="chip-vegetarian"' in index_html
        assert 'data-testid="chip-gate"' in index_html
        assert 'data-testid="chip-baggage"' in index_html
        assert 'data-testid="chip-claim"' in index_html
        assert 'data-testid="aj-starter-flight-only"' in index_html
        assert 'data-testid="aj-starter-flight-booking"' in index_html
        assert 'data-testid="aj-starter-complete"' in index_html


class TestLocaleReactivity:
    """Verify chips subscribe to locale changes."""

    def test_trip_js_subscribes_to_on_locale_change(self, trip_js):
        assert "onLocaleChange" in trip_js
        assert "renderContextualTripChips" in trip_js

    def test_app_js_subscribes_to_on_locale_change(self, app_js):
        assert "onLocaleChange" in app_js
        assert "renderContextualConciergeChips" in app_js
