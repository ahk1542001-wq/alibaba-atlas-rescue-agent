"""Runtime regressions for the merged U1/U4 frontend modules.

These tests execute the production JavaScript with Node and replace only the
browser/Leaflet boundaries.  They assert user-visible behavior rather than
source text.
"""

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


def _run_node(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [NODE, "-e", textwrap.dedent(script)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_unconfigured_legacy_llm_uses_supported_default_model() -> None:
    """A deployment without DEFAULT_MODEL must not select the retired model."""
    env = os.environ.copy()
    env.pop("DEFAULT_MODEL", None)
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import dotenv; dotenv.load_dotenv = lambda *a, **k: False; "
                "from config import settings; print(settings.default_model)"
            ),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.strip() == "Qwen/Qwen3-235B-A22B-Instruct-2507"


@pytest.mark.skipif(NODE is None, reason="node is required for frontend runtime checks")
def test_missing_translation_never_exposes_internal_key() -> None:
    """Removing both locale entries must show an honest placeholder, not the key."""
    proc = _run_node(
        r"""
        global.window = {};
        global.localStorage = {getItem: () => null, setItem: () => {}};
        global.document = {
          readyState: 'loading',
          addEventListener: () => {},
          querySelectorAll: () => [],
          querySelector: () => null,
          getElementById: () => null,
          documentElement: {setAttribute: () => {}}
        };
        require('./static/i18n.js');
        const result = window.TravelCareI18n.t('internal.missing_key');
        if (result === 'internal.missing_key') {
          console.error('raw translation key leaked to visible output');
          process.exit(1);
        }
        if (!result || !result.toLowerCase().includes('translation')) {
          console.error('missing translation did not produce an honest placeholder: ' + result);
          process.exit(2);
        }
        """
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.skipif(NODE is None, reason="node is required for frontend runtime checks")
def test_map_rerender_replaces_previous_data_layers() -> None:
    """A state refresh must clear old pins/routes before adding the new state."""
    proc = _run_node(
        r"""
        let clearCalls = 0;
        const dataLayer = {
          addTo: function () { return this; },
          clearLayers: function () { clearCalls += 1; return this; }
        };
        global.document = {
          createElement: () => ({style: {}, appendChild: () => {}})
        };
        global.window = {
          t: (key) => key,
          L: {
            layerGroup: () => dataLayer,
            circleMarker: () => ({bindPopup: function () { return this; }, addTo: function () { return this; }}),
            polyline: () => ({addTo: function () { return this; }}),
            latLngBounds: (points) => points
          }
        };
        const map = {
          fitBounds: () => {},
          setView: () => {}
        };
        const TravelCareMap = require('./static/map.js');
        const point = {lat: 13.7, lng: 100.5, code: 'BKK', name: 'Bangkok'};
        TravelCareMap.renderPointsAndRoutes(map, [point], {});
        TravelCareMap.renderPointsAndRoutes(map, [], {});
        if (clearCalls !== 1) {
          console.error('expected one prior-layer clear, observed ' + clearCalls);
          process.exit(1);
        }
        """
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
