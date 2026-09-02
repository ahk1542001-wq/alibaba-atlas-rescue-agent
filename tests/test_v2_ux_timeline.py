"""U2 Day-by-Day Timeline hermetic tests — provenance coding and disruption markers.

Gate criteria (§U2):
- Provenance coding:
  * Atlas Sandbox segments carry timeline-segment-sandbox (solid treatment)
  * Suggestion segments carry timeline-segment-suggestion (dashed treatment)
  * Visible legend bar with solid, dashed, and disruption line indicators
- Disruption rendering:
  * Disrupted flights/segments carry timeline-segment-disrupted
  * Struck-through styling via timeline-original-cancelled
  * Explicit cancellation tag matching timeline.original_strikethrough
- Localization hook presence:
  * timeline.day, timeline.time_estimate, timeline.disruption, timeline.recovery,
    timeline.empty, timeline.original_strikethrough all exist in en and zh tables
- Empty state honesty:
  * Honest empty affordance without fabricated placeholder days
- Canary testid immutability:
  * trip-itinerary, trip-itinerary-empty, aj-itinerary-summary, aj-itinerary-day-1 preserved
"""

import json
from pathlib import Path
import re
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "static"
I18N_DIR = STATIC_DIR / "i18n"

REQUIRED_TIMELINE_KEYS = [
    "timeline.empty",
    "timeline.day",
    "timeline.time_estimate",
    "timeline.disruption",
    "timeline.recovery",
    "timeline.original_strikethrough",
]


@pytest.fixture
def index_html():
    with open(STATIC_DIR / "index.html", encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def trip_js():
    with open(STATIC_DIR / "trip.js", encoding="utf-8") as f:
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


class TestTimelineStringTables:
    """Verify all timeline keys exist in both en and zh tables."""

    def test_all_timeline_keys_present_in_en(self, en_table):
        for key in REQUIRED_TIMELINE_KEYS:
            assert key in en_table, f"Missing {key} in strings.en.json"
            assert len(en_table[key].strip()) > 0

    def test_all_timeline_keys_present_in_zh(self, zh_table):
        for key in REQUIRED_TIMELINE_KEYS:
            assert key in zh_table, f"Missing {key} in strings.zh.json"
            assert len(zh_table[key].strip()) > 0


class TestTimelineProvenanceCoding:
    """Verify visual provenance coding in JavaScript and CSS."""

    def test_trip_js_applies_provenance_classes(self, trip_js):
        """trip.js must apply timeline-segment-sandbox and timeline-segment-suggestion."""
        assert "timeline-segment-sandbox" in trip_js
        assert "timeline-segment-suggestion" in trip_js
        assert "timeline-segment-disrupted" in trip_js
        assert "timeline-original-cancelled" in trip_js
        assert "timeline-disruption-tag" in trip_js

    def test_trip_js_renders_timeline_legend(self, trip_js):
        """trip.js must render a visible legend for sandbox vs suggestion."""
        assert "timeline-legend" in trip_js
        assert "Atlas Sandbox (live tooling)" in trip_js
        assert "Suggestion only" in trip_js

    def test_styles_css_defines_provenance_styling(self, styles_css):
        """styles.css must have distinct solid vs dashed border styles."""
        assert ".timeline-segment-sandbox" in styles_css
        assert ".timeline-segment-suggestion" in styles_css
        assert "dashed" in styles_css
        assert ".timeline-original-cancelled" in styles_css
        assert "line-through" in styles_css


class TestDisruptionInterruptionRendering:
    """Verify disruption interruption contract."""

    def test_disruption_marker_contract(self, trip_js):
        """Cancelled segments must preserve original text struck-through."""
        assert "timeline-original-cancelled" in trip_js
        assert "timeline.original_strikethrough" in trip_js


class TestDomIntegrityAndCanaryTestIds:
    """Verify HTML containers and canary selectors."""

    def test_index_html_itinerary_container_exists(self, index_html):
        assert 'id="trip-itinerary"' in index_html
        assert 'data-testid="trip-itinerary"' in index_html
        assert 'id="trip-itinerary-empty"' in index_html
        assert 'data-testid="trip-itinerary-empty"' in index_html
        assert 'data-i18n="timeline.empty"' in index_html

    def test_canary_itinerary_classes_preserved_in_trip_js(self, trip_js):
        """Canary test selectors (trip-itin-flight, aj-itinerary-summary, aj-itinerary-day-) must stay intact."""
        assert "trip-itin-flight" in trip_js
        assert "aj-itinerary-summary" in trip_js
        assert "aj-itinerary-day-" in trip_js
        assert "trip-itin-item" in trip_js
        assert "aj-show-more-itinerary" in trip_js
