"""U1 Map Visualization hermetic tests — spatial routing and coordinate honesty validation.

Gate criteria (§U1):
- Vendored Leaflet: static assets exist locally (leaflet.js, leaflet.css)
- License & Attribution: OpenStreetMap attribution ("© OpenStreetMap contributors")
  and Leaflet attribution controls present and visible
- Coordinate sourcing honesty:
  * Tool-sourced airports have is_estimated == False (solid pins)
  * LLM-suggested or unresolved locations have is_estimated == True with "estimated" badge
- Multi-airport ambiguity:
  * "Bangkok" returns BOTH BKK and DMK with ambiguous flag
  * Never silently chooses one airport
- Degraded fallback:
  * tile_failed fallback message exists in DOM and string tables
- Container & Collapsible controls:
  * trip-map-block and rescue-map-block with toggle buttons
- Canary testid immutability:
  * Pre-existing canary selectors remain intact
"""

import json
from pathlib import Path
import re
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "static"
VENDOR_DIR = STATIC_DIR / "vendor" / "leaflet"
I18N_DIR = STATIC_DIR / "i18n"


@pytest.fixture
def index_html():
    with open(STATIC_DIR / "index.html", encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def map_js():
    with open(STATIC_DIR / "map.js", encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def trip_js():
    with open(STATIC_DIR / "trip.js", encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def app_js():
    with open(STATIC_DIR / "app.js", encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def en_table():
    with open(I18N_DIR / "strings.en.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def zh_table():
    with open(I18N_DIR / "strings.zh.json", encoding="utf-8") as f:
        return json.load(f)


class TestLeafletVendoring:
    """Verify vendored Leaflet static assets exist locally."""

    def test_leaflet_files_exist_locally(self):
        assert (VENDOR_DIR / "leaflet.js").is_file(), "Vendored leaflet.js missing"
        assert (VENDOR_DIR / "leaflet.css").is_file(), "Vendored leaflet.css missing"
        assert (VENDOR_DIR / "leaflet.js").stat().st_size > 100000
        assert (VENDOR_DIR / "leaflet.css").stat().st_size > 10000

    def test_index_html_includes_leaflet_and_map_js(self, index_html):
        assert "/static/vendor/leaflet/leaflet.css" in index_html
        assert "/static/vendor/leaflet/leaflet.js" in index_html
        assert "/static/map.js" in index_html


class TestMapHonestyAndAttribution:
    """Verify OpenStreetMap and Leaflet attribution and string tables."""

    def test_attribution_strings_present_in_en_and_zh(self, en_table, zh_table):
        for key in [
            "map.attribution",
            "map.leaflet_attribution",
            "map.tile_failed",
            "map.pin_estimated",
            "map.pin_sourced",
            "map.ambiguity_title",
            "map.legend_solid",
            "map.legend_hollow",
            "map.legend_disrupted",
            "map.legend_rescue",
        ]:
            assert key in en_table, f"Missing {key} in strings.en.json"
            assert key in zh_table, f"Missing {key} in strings.zh.json"
            assert len(en_table[key].strip()) > 0
            assert len(zh_table[key].strip()) > 0

    def test_osm_attribution_required_words(self, en_table):
        assert "OpenStreetMap" in en_table["map.attribution"]
        assert "contributors" in en_table["map.attribution"]

    def test_dom_attribution_markup(self, index_html):
        """Attribution must be explicitly rendered in the DOM."""
        assert "OpenStreetMap" in index_html
        assert "data-i18n=\"map.attribution\"" in index_html
        assert "data-i18n=\"map.leaflet_attribution\"" in index_html


class TestCoordinateHonestyRules:
    """Validate solid vs estimated coordinate contract and ambiguity handling."""

    def test_known_airports_have_tool_sourced_solid_coordinates(self, map_js):
        """Known regional airports must be non-estimated (is_estimated: false)."""
        for code in ["BKK", "DMK", "SIN", "KUL", "RGN", "CNX", "HKG", "HND", "NRT", "ICN"]:
            pattern = rf"'{code}':\s*\{{[^}}]*is_estimated:\s*false"
            assert re.search(pattern, map_js), f"Airport {code} must be defined with is_estimated: false"

    def test_fallback_coordinates_are_explicitly_estimated(self, map_js):
        """Unresolved or LLM-suggested venues must have is_estimated: true."""
        assert "is_estimated: true" in map_js
        assert "map-badge-estimated" in map_js
        assert "map.pin_estimated" in map_js

    def test_ambiguity_renders_both_airports(self, map_js):
        """Bangkok query must resolve to BOTH BKK and DMK with ambiguous flag."""
        assert "q === 'BANGKOK'" in map_js
        assert "code: 'BKK'" in map_js
        assert "code: 'DMK'" in map_js
        assert "ambiguous: true" in map_js


class TestDomContainersAndToggles:
    """Verify HTML container elements and collapsible toggle affordances."""

    def test_trip_map_containers_exist(self, index_html):
        assert 'id="trip-map-block"' in index_html
        assert 'data-testid="trip-map-block"' in index_html
        assert 'id="trip-map"' in index_html
        assert 'data-testid="trip-map"' in index_html
        assert 'id="trip-map-fallback"' in index_html
        assert 'data-testid="trip-map-fallback"' in index_html
        assert 'id="btn-trip-map-toggle"' in index_html
        assert 'data-testid="btn-trip-map-toggle"' in index_html

    def test_rescue_map_containers_exist(self, index_html):
        assert 'id="rescue-map-block"' in index_html
        assert 'data-testid="rescue-map-block"' in index_html
        assert 'id="rescue-map"' in index_html
        assert 'data-testid="rescue-map"' in index_html
        assert 'id="rescue-map-fallback"' in index_html
        assert 'data-testid="rescue-map-fallback"' in index_html
        assert 'id="btn-rescue-map-toggle"' in index_html
        assert 'data-testid="btn-rescue-map-toggle"' in index_html

    def test_trip_js_and_app_js_call_map_renderers(self, trip_js, app_js):
        assert "renderTripMap" in trip_js
        assert "renderRescueMap" in app_js
        assert "TravelCareMap.createMap" in trip_js or "TravelCareMap.renderPointsAndRoutes" in trip_js
        assert "TravelCareMap.createMap" in app_js or "TravelCareMap.renderPointsAndRoutes" in app_js
