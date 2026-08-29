"""Contract drift tests for TravelCare skills and Atlas provider specifications (Gate G1)."""

from pathlib import Path
from services.skills import SKILLS_DIR


def test_flight_book_skill_md_no_unconditional_pnr_promise():
    content = (SKILLS_DIR / "flight_book.SKILL.md").read_text()
    # Must NOT unconditionally claim it always returns a PNR
    assert ("returns a PNR." not in content) or ("if ticketing is available" in content)
    # Must explicitly state behavior when ticketing is unavailable
    assert "ticketing" in content.lower()
    assert "no pnr" in content.lower() or "not activated" in content.lower() or "unavailable" in content.lower()


def test_flight_book_skill_md_mentions_required_safety_contracts():
    content = (SKILLS_DIR / "flight_book.SKILL.md").read_text()
    lower = content.lower()
    assert "opaque" in lower or "preserve" in lower
    assert "reapproval" in lower or "price increase" in lower or "re-approval" in lower
    assert "retry" in lower or "side-effect" in lower
    assert "provider" in lower or "code" in lower or "status" in lower


def test_flight_search_skill_md_contracts():
    content = (SKILLS_DIR / "flight_search.SKILL.md").read_text()
    lower = content.lower()
    assert "opaque" in lower or "search_id" in lower or "offer_id" in lower
    assert "currency" in lower
    assert "passenger" in lower or "total" in lower
    assert "reference" in lower or "verified" in lower or "status" in lower


def test_goal_intake_skill_md_contracts():
    content = (SKILLS_DIR / "goal_intake.SKILL.md").read_text()
    lower = content.lower()
    assert "passenger" in lower
    assert "budget" in lower
    assert "privacy" in lower or "pii" in lower or "passport number" in lower


def test_clarify_loop_skill_md_contracts():
    content = (SKILLS_DIR / "clarify_loop.SKILL.md").read_text()
    lower = content.lower()
    assert "one" in lower and "question" in lower
    assert "passport country" in lower or "passport" in lower
    assert "profile" in lower or "consent" in lower or "persist" in lower
    assert "scope" in lower
