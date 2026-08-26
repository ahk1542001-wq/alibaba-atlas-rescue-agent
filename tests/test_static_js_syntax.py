"""Static JS syntax gate (G4-DA-fix-2).

A dropped ternary branch in static/trip.js (commit eb0b2b7) produced a
SyntaxError that killed the entire trip module on every page load — the
Playwright suite then burned expect-timeouts instead of failing fast on
the real cause. This gate runs `node --check` over every static/*.js so
ANY syntax regression fails here, first, with the exact line.

Skipped (with a visible note) when no node binary is available — the
browser suites still cover runtime behavior in that case.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def _node():
    return shutil.which("node")


@pytest.mark.skipif(_node() is None,
                    reason="node not available — JS syntax gate skipped "
                           "(browser suites still cover runtime behavior)")
@pytest.mark.parametrize("js_file", sorted(
    p.name for p in STATIC_DIR.glob("*.js")), ids=lambda n: n)
def test_static_js_syntax(js_file):
    proc = subprocess.run([_node(), "--check", str(STATIC_DIR / js_file)],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, (
        f"static/{js_file} failed node --check:\n{proc.stdout}{proc.stderr}")
