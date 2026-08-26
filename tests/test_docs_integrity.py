"""Docs-integrity tripwires for the root AGENTS.md agent contract.

Stdlib-only module (pytest is only the runner, and is already a declared
dependency in requirements.txt). Two environment overrides turn this file into
a mutation-evidence harness without touching the working tree:

DOCS_INTEGRITY_AGENTS_MD  document under inspection
                          (default: <repo root>/AGENTS.md)
DOCS_INTEGRITY_ROOT       base directory for path-existence checks
                          (default: repo root)

Banned-literal patterns are assembled from fragments so this source file never
contains, verbatim, the drift it guards against.
"""

import os
import re
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("DOCS_INTEGRITY_ROOT", str(_HERE.parent)))
DOC_PATH = Path(os.environ.get("DOCS_INTEGRITY_AGENTS_MD", str(ROOT / "AGENTS.md")))

PATH_LIKE_SUFFIXES = (".py", ".txt", ".md", ".html", ".css", ".js")


def _frag(*parts: str) -> str:
    return "".join(parts)


BANNED_DRIFT = {
    "volatile-count": r"\d+\s+(?:tests?|endpoints?)",
    "private-home-prefix": _frag("/Us", "ers/m", "ac"),
    "operator-name": _frag("(?i)vic", "tor"),
    "pinned-model-id": _frag("ge", "mini-[", "0-9]"),
    "private-system-reference": _frag("(?i)se", "cond[_ ]br", "ain|\\bAI[_ ]OS\\b"),
}

REQUIRED_SECTIONS = (
    "Source-of-Truth Hierarchy",
    "Pre-Change Context Gate",
    "Safety & Approval Boundaries",
)
REQUIRED_POINTERS = (
    "`main.py`",
    "`routers/",
    "`services/",
    "`config.py`",
    "`requirements.txt`",
    "`tests/",
)


def _doc_text() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


@pytest.mark.parametrize("label", sorted(BANNED_DRIFT), ids=sorted(BANNED_DRIFT))
def test_banned_drift_absent(label: str) -> None:
    match = re.search(BANNED_DRIFT[label], _doc_text())
    assert match is None, (
        f"DOC DRIFT [{label}] matched {match.group(0)!r} at offset {match.start()}; "
        "tracked docs carry durable info only - verify live state instead of "
        "freezing volatile or private facts."
    )


@pytest.mark.parametrize("section", REQUIRED_SECTIONS)
def test_required_section_present(section: str) -> None:
    assert section in _doc_text(), f"missing required section: {section!r}"


def test_required_pointers_present() -> None:
    text = _doc_text()
    missing = [p for p in REQUIRED_POINTERS if p not in text]
    assert not missing, f"missing required pointer(s): {missing}"


def test_import_search_covers_aliases_and_function_local_imports() -> None:
    text = _doc_text().lower()
    for token in ("module path", "aliases", "function-local imports"):
        assert token in text, f"import-search guidance lost: {token!r}"


def _path_like_spans(text: str) -> list:
    found = set()
    for span in re.findall(r"`([^`\n]+)`", text):
        candidate = span.strip().rstrip("/")
        if (
            candidate
            and " " not in candidate
            and not candidate.startswith((".", "http"))
            and not any(ch in candidate for ch in ":@=()<>,")
            and ("/" in candidate or candidate.endswith(PATH_LIKE_SUFFIXES))
        ):
            found.add(candidate)
    return sorted(found)


def test_backticked_paths_exist() -> None:
    missing = [p for p in _path_like_spans(_doc_text()) if not (ROOT / p).exists()]
    assert not missing, f"path-like backtick spans missing on disk: {missing}"


def test_verification_commands_pointed() -> None:
    text = _doc_text()
    for token in ("pip install", "uvicorn", "pytest"):
        assert token in text, f"verification pointer lost: {token!r}"
