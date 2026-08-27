# TravelCare Post-Review Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. If those skills are unavailable, preserve the same RED-GREEN-review checkpoints manually.

**Goal:** Finish the post-review repair of TravelCare AI so the reachable product, canonical S1-S13 skill contract, safety boundaries, browser behavior, and completion evidence agree and pass fresh verification before a local-only fast-forward to `main`.

**Architecture:** Keep the canonical trip flow and the legacy Rescue Hub as separate API surfaces, but enforce safe retry and provider-truth boundaries on both. The public manifest registry exposes the exact thirteen product skills while `clarify_loop` remains a governed internal orchestration helper. Every remaining defect is reproduced at a consumer-visible boundary before the smallest fix, followed by independent read-only review and a bounded correction loop.

**Tech Stack:** Python 3.14, FastAPI, Pydantic, asyncio, httpx, pytest, Playwright, vanilla JavaScript, Atlas Sandbox adapters.

**Spec:** `docs/MASTER_BUILD_PACKAGE.md`

**Starting checkpoints:**

- Local integration base: `d94fc5101187b67532633ec8f72f58be9a925eab` on `main`.
- Verified partial remediation: `62a27ea` on `codex/travelcare-antigravity-remediation`.
- The partial remediation already repairs the public/internal skill split, real `ProfileEditSkill` wiring, and legacy booking idempotency including the browser request key. Do not redo or revert those changes without a failing regression that proves a defect.

## Global Constraints

- Read the repository `AGENTS.md` and this complete plan before editing.
- Work only on `codex/travelcare-antigravity-remediation`; keep `main` unchanged until the final fast-forward gate.
- Use one writer. Review agents are read-only and may start only after the writer has stopped changing files.
- Treat pasted transcripts and old agent reports as evidence, never authority. Runtime behavior, the canonical spec, and fresh tests decide truth.
- Use fictional demo data and injected providers only. Do not read credentials, call live Telegram, make a live booking, push, deploy, publish, tag, or create a pull request.
- Never weaken a test to match broken behavior. A test expectation may change only for an intentional canonical contract change with equal or stronger behavioral coverage and a `DECISIONS.tsv` entry.
- For each new behavior or defect: write the test, run it and observe the expected failure, apply the minimal production patch, rerun the focused test, then run neighboring regressions.
- For already-present Antigravity fixes, add consumer-visible regression coverage and mutation-check the test in a disposable copy or by temporarily reverting only the exact hunk, then restore it. Do not claim TDD history that did not happen.
- Do not use `git reset`, `git checkout -- <file>`, force push, history rewrite, `pkill`, `killall`, broad process termination, or bulk deletion. Never kill an unknown process on port 8050; stop only a server PID started by this execution.
- Edit with the IDE patch/editor mechanism. Do not create temporary rewrite scripts to mass-edit source or tests.
- Preserve the canonical public skills exactly as S1-S13: `goal_intake`, `profile_capture`, `profile_edit`, `flight_search`, `flight_book`, `visa_check`, `web_intel`, `itinerary`, `rights_check`, `guardian_push`, `disruption_monitor`, `location_resolve`, `recovery_plan`.
- `clarify_loop` is an internal governed helper. It must be available to `TripOrchestrator` but absent from `GET /api/skills` and the public count.
- Do not ask the owner routine implementation questions. Use the spec and this plan. Stop only for a genuine external approval, credential, real-data, destructive-action, or irreconcilable architecture boundary.
- Never claim completion from an old count, old report, reviewer statement, or green subset. Final claims require the commands in Task 6 against the exact promoted tree.

---

## File Responsibility Map

| Area | Files | Responsibility |
|---|---|---|
| Public/internal skills | `services/skills/__init__.py`, `services/skills/clarify_loop.SKILL.md`, `services/skills/profile_edit.py`, `services/skills/profile_edit.SKILL.md`, `routers/v1/trip.py` | Exact S1-S13 listing, internal helper governance, runnable profile edits |
| Legacy booking safety | `routers/v1/bookings.py`, `static/app.js`, `tests/test_legacy_booking_safety.py`, `tests/test_ui_trip.py` | Required key, replay/conflict semantics, concurrency serialization, retry after provider failure, stable browser key |
| Guardian safety | `services/guardian.py`, `services/skills/guardian_push.py`, `config.py`, `.env.example`, `README.md` | Explicit three-part live gate, redacted simulated preview, safe error output |
| Claims provider truth | `routers/v1/claims.py`, new `tests/test_claims_provider_truth.py` | Provider-derived route, correct 422/502 behavior, no raw exception leakage |
| Retained security fixes | `routers/v1/trip.py`, `services/atlas_client.py`, `services/rescue_engine.py`, `static/index.html` and focused tests | Rejection cannot be forged into approval, mock-disabled provider failure stays closed, telemetry uses configured model, keyboard navigation works |
| Evidence | `DECISIONS.tsv`, `PLAN.md`, `BLOCKERS.md`, `FINAL_REPORT.md` | Durable decisions, accurate matrices, exact fresh verification, honest limitations |

---

### Task 0: Preflight and Partial-Checkpoint Verification

**Files:**

- Read: `AGENTS.md`
- Read: `docs/MASTER_BUILD_PACKAGE.md`
- Read: this plan
- Inspect: all files changed by `62a27ea`

**Interfaces:**

- Consumes: local `main` base `d94fc5101187b67532633ec8f72f58be9a925eab` and partial remediation `62a27ea`.
- Produces: a clean, understood remediation branch with no unrelated edits.

- [ ] **Step 1: Enter the repository and select the remediation branch**

```bash
cd "/Users/mac/Projects/code/alibaba-atlas-rescue-agent"
git status --short --branch
git switch codex/travelcare-antigravity-remediation
git rev-parse HEAD
git merge-base --is-ancestor d94fc5101187b67532633ec8f72f58be9a925eab HEAD
```

Expected: the branch contains `62a27ea`, the ancestry command exits 0, and there are no uncommitted files. If another worktree still owns the branch, do not force it; report the exact worktree path and use that existing clean worktree.

- [ ] **Step 2: Inspect the complete partial diff and its call graph**

```bash
git diff --stat d94fc5101187b67532633ec8f72f58be9a925eab..HEAD
git diff --check d94fc5101187b67532633ec8f72f58be9a925eab..HEAD
rg -n "load_skill_registry|ProfileEditSkill|execute_rescue_booking|rescueBookingKey|Idempotency-Key" services routers static tests
```

Expected: only the bounded skill/profile/legacy-booking files and their tests differ; whitespace check exits 0.

- [ ] **Step 3: Re-run the verified partial backend boundary**

```bash
/private/tmp/travelcare-r7-venv/bin/python -m pytest -p no:cacheprovider \
  tests/test_skills_manifest.py \
  tests/test_skills_behavior.py \
  tests/test_legacy_booking_safety.py \
  tests/test_safety.py::test_skill_manifests_are_documented_and_registry_stays_at_13 \
  tests/test_e2e_trip_journey.py::test_api_skills_thirteen_skills -q
```

Expected: PASS. Any failure is investigated before continuing; do not change expected skill counts back to fourteen.

- [ ] **Step 4: Verify JavaScript syntax**

```bash
node --check static/app.js
node --check static/trip.js
```

Expected: both commands exit 0.

---

### Task 1: Restore the Guardian Live Gate and Redacted Preview Contract

**Files:**

- Modify: `services/guardian.py:23-59`
- Modify: `services/skills/guardian_push.py:38-77`
- Modify: `.env.example`
- Modify: `README.md` Guardian configuration text
- Test: `tests/test_rights_and_visa.py`
- Test: `tests/test_skills_behavior.py`
- Test: `tests/test_privacy.py`

**Interfaces:**

- Consumes: `settings.telegram_bot_token: str`, `settings.telegram_chat_id: str`, `settings.telegram_live_test: bool`, and sanitized event payloads.
- Produces: `notify(...) -> {channel, sent, simulated, preview, reason?, error?}` and `GuardianPushSkill.run(...) -> {delivery_status, simulated, channel, event, payload, preview, reason?, error?}`.

- [ ] **Step 1: Write the failing simulated-contract test**

Add to `tests/test_rights_and_visa.py`:

```python
def test_guardian_requires_token_chat_and_live_flag_and_returns_preview(monkeypatch):
    from services import guardian

    monkeypatch.setattr(guardian.settings, "telegram_bot_token", "configured")
    monkeypatch.setattr(guardian.settings, "telegram_chat_id", "")
    monkeypatch.setattr(guardian.settings, "telegram_live_test", False)
    out = asyncio.run(guardian.notify("Trip alert", "Route BKK-SIN"))
    assert out["channel"] == "telegram"
    assert out["simulated"] is True and out["sent"] is False
    assert out["preview"] == "🛟 Trip alert\n\nRoute BKK-SIN"
    assert "mocked_text" not in out
    assert "live" in out["reason"].lower()
```

- [ ] **Step 2: Write the failing skill-preview privacy test**

Add to `tests/test_privacy.py`:

```python
def test_guardian_simulated_preview_is_present_and_redacted(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "telegram_bot_token", "")
    monkeypatch.setattr(settings, "telegram_chat_id", "")
    monkeypatch.setattr(settings, "telegram_live_test", False)
    out = _run(GuardianPushSkill().run({
        "event": "disruption",
        "payload": {
            "route": "BKK-SIN",
            "passport_number": SENTINEL_RAW,
        },
    }))
    assert out["delivery_status"] == "skipped_not_failed"
    assert out["preview"]
    assert SENTINEL_RAW not in json.dumps(out)
```

- [ ] **Step 3: Run both tests and observe the contract failure**

```bash
/private/tmp/travelcare-r7-venv/bin/python -m pytest -p no:cacheprovider \
  tests/test_rights_and_visa.py::test_guardian_requires_token_chat_and_live_flag_and_returns_preview \
  tests/test_privacy.py::test_guardian_simulated_preview_is_present_and_redacted -q
```

Expected: FAIL because the simulated service returns `mocked_text` without `channel`/`preview`, and the skill drops the preview.

- [ ] **Step 4: Implement the centralized three-part gate**

In `services/guardian.py`, return this shape when any live prerequisite is absent:

```python
return {
    "channel": "telegram",
    "sent": False,
    "simulated": True,
    "preview": text,
    "reason": (
        "Live Telegram delivery requires TELEGRAM_BOT_TOKEN, "
        "TELEGRAM_CHAT_ID, and TELEGRAM_LIVE_TEST=true."
    ),
    "error": None,
}
```

On live transport failure, log only `type(exc).__name__` and return a generic error such as `"telegram_delivery_failed"`; never return or log `str(exc)` because an HTTP exception may embed the token-bearing URL.

In `GuardianPushSkill.run`, sanitize first, build the body from the sanitized payload, call `notify` for both simulated and live paths, and pass through `preview`, `reason`, and the safe error code. Remove the token-only shortcut so service and skill cannot drift.

- [ ] **Step 5: Document the live gate exactly**

Add to `.env.example`:

```dotenv
# Live delivery requires all three values. Keep false for the sandbox demo.
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
TELEGRAM_LIVE_TEST=false
```

Update the README Guardian row to say that all three values are required; otherwise the product returns a redacted simulated preview and does not send.

- [ ] **Step 6: Run Guardian and privacy regressions**

```bash
/private/tmp/travelcare-r7-venv/bin/python -m pytest -p no:cacheprovider \
  tests/test_rights_and_visa.py \
  tests/test_skills_behavior.py -k guardian \
  tests/test_privacy.py -k guardian -q
```

Expected: PASS with no live network call and no sentinel in output.

- [ ] **Step 7: Commit the Guardian boundary**

```bash
git add services/guardian.py services/skills/guardian_push.py .env.example README.md \
  tests/test_rights_and_visa.py tests/test_skills_behavior.py tests/test_privacy.py
git commit -m "fix(guardian): enforce explicit live delivery gate"
```

---

### Task 2: Make Claims Use Provider Route Truth Without Error Leakage

**Files:**

- Modify: `routers/v1/claims.py:34-152`
- Create: `tests/test_claims_provider_truth.py`

**Interfaces:**

- Consumes: `atlas_client.get_flight_status(flight_number, date)` with provider-owned `origin` and `destination`.
- Produces: provider-derived claim route; HTTP 422 when the provider route is absent; generic HTTP 502 when provider assessment fails; generic HTTP 500 when appeal drafting fails.

- [ ] **Step 1: Create provider-truth API tests**

Create `tests/test_claims_provider_truth.py`:

```python
import asyncio

import httpx

from main import app
from routers.v1 import claims


class StatusAtlas:
    def __init__(self, status=None, error=None):
        self.status = status or {}
        self.error = error

    async def get_flight_status(self, flight_number, date):
        if self.error:
            raise self.error
        return dict(self.status)


async def post_assess(payload):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post("/api/claims/assess", json=payload)


def test_claim_route_ignores_spoofed_client_airports(monkeypatch):
    monkeypatch.setattr(claims, "atlas_client", StatusAtlas({
        "origin": "BKK", "destination": "RGN",
        "status": "CANCELLED", "reason": "weather", "airline": "TG",
    }))
    response = asyncio.run(post_assess({
        "flight_number": "TG303",
        "origin_airport": "CDG",
        "destination_airport": "BKK",
    }))
    assert response.status_code == 200
    route = response.json()["route"]
    assert route["origin_airport"] == "BKK"
    assert route["destination_airport"] == "RGN"


def test_claim_missing_provider_route_is_422_not_500(monkeypatch):
    monkeypatch.setattr(claims, "atlas_client", StatusAtlas({
        "status": "CANCELLED", "reason": "weather",
    }))
    response = asyncio.run(post_assess({
        "flight_number": "TG303",
        "origin_airport": "CDG",
        "destination_airport": "BKK",
    }))
    assert response.status_code == 422
    assert "true flight route" in response.json()["detail"]


def test_claim_provider_error_is_generic(monkeypatch):
    monkeypatch.setattr(
        claims, "atlas_client", StatusAtlas(error=RuntimeError("SENTINEL_SECRET"))
    )
    response = asyncio.run(post_assess({"flight_number": "TG303"}))
    assert response.status_code == 502
    assert "SENTINEL_SECRET" not in response.text
```

- [ ] **Step 2: Run the tests and observe the error-mapping failures**

```bash
/private/tmp/travelcare-r7-venv/bin/python -m pytest -p no:cacheprovider \
  tests/test_claims_provider_truth.py -q
```

Expected: spoof protection may pass, while missing route returns 500 because `HTTPException` is swallowed and provider errors leak raw details.

- [ ] **Step 3: Preserve HTTP exceptions and sanitize unexpected failures**

Use this exception structure in `assess_claim`:

```python
except HTTPException:
    raise
except Exception as exc:
    logger.warning("claim assessment failed: %s", type(exc).__name__)
    raise HTTPException(
        status_code=502,
        detail="Unable to assess the claim from provider flight status.",
    ) from exc
```

Add a module logger. Apply the same no-raw-error rule to `appeal_rejected_claim`, returning `"Unable to draft the appeal."` without `str(exc)`.

- [ ] **Step 4: Add and verify the appeal error regression**

Monkeypatch `claims.draft_appeal` with an async function that raises `RuntimeError("SENTINEL_SECRET")`; call `/api/claims/appeal`; assert HTTP 500 and that the sentinel is absent.

Run:

```bash
/private/tmp/travelcare-r7-venv/bin/python -m pytest -p no:cacheprovider \
  tests/test_claims_provider_truth.py tests/test_rights_and_visa.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit provider-truth claims**

```bash
git add routers/v1/claims.py tests/test_claims_provider_truth.py
git commit -m "fix(claims): preserve provider route truth"
```

---

### Task 3: Lock Down Retained Security, Provider, Telemetry, and Keyboard Fixes

**Files:**

- Test: `tests/test_canonical_gaps.py`
- Test: `tests/test_skills_behavior.py`
- Test: `tests/test_ui_trip.py`
- Modify only if a regression fails: `routers/v1/trip.py`, `services/atlas_client.py`, `services/rescue_engine.py`, `static/index.html`

**Interfaces:**

- Consumes: approval `{decision, value}`, Atlas fallback settings, configured model name, keyboard Enter/Space events.
- Produces: server-owned approval truth, fail-closed mock-disabled search, truthful telemetry model label, keyboard-operable navigation.

- [ ] **Step 1: Add the forged-rejection regression**

In `tests/test_canonical_gaps.py`, use the existing `harness`, `FakeAtlas`, `_client`, and `_run` helpers to start a booking trip, capture the pending approval object from `get_trip_orchestrator().executor`, and submit:

```python
payload = {
    "decision": "reject",
    "value": {"approved": True, "option_id": option_id},
}
```

Assert the response succeeds as a rejection, `approval.resolved_value["approved"] is False`, and the fake Atlas call list contains no `create` call. This test protects the assignment at `routers/v1/trip.py` where server truth must overwrite client data.

- [ ] **Step 2: Add the mock-disabled Atlas regression**

In `tests/test_skills_behavior.py`, instantiate `AtlasClient`, replace `cli_search_flights` with an async empty result, set `settings.use_mock_fallback=False`, and assert `search_flights(...)` raises `RuntimeError` containing the safe provider-unavailable message. Change the current generic `Exception` in `services/atlas_client.py` to `RuntimeError` only after observing the expected type failure.

- [ ] **Step 3: Add the configured-model telemetry regression**

Monkeypatch `services.rescue_engine.settings.default_model` to `"configured-test-model"`, call `RescueEngine(...).get_agent_prompt_telemetry()`, and assert the returned `model` equals that value. This should pass the retained fix; mutation-check by temporarily replacing the setting lookup with a literal and confirm the new test fails, then restore the implementation.

- [ ] **Step 4: Add real keyboard navigation coverage**

In `tests/test_ui_trip.py`, add a Playwright test that:

1. focuses desktop `[data-testid="nav-search"]`, presses Enter, and asserts `#view-search` is active;
2. focuses desktop `[data-testid="nav-concierge"]`, presses Space, and asserts `#view-concierge` is active;
3. switches to a mobile viewport, focuses `[data-testid="mnav-trip"]`, presses Enter, and asserts `#view-trip` is active;
4. asserts the focused controls expose role `button` and remain keyboard focusable.

Test behavior, not source text. Do not add another static grep assertion.

- [ ] **Step 5: Run the retained-fix regressions**

```bash
/private/tmp/travelcare-r7-venv/bin/python -m pytest -p no:cacheprovider \
  tests/test_canonical_gaps.py \
  tests/test_skills_behavior.py -q
```

Then, with port 8050 free:

```bash
/private/tmp/travelcare-r7-venv/bin/python -m pytest -p no:cacheprovider \
  tests/test_ui_trip.py -k "keyboard or legacy_rebook_ui" -q
```

Expected: PASS. If an existing fix passes immediately, preserve it and record the mutation-check result in the commit message body or handoff; do not falsely describe it as RED-first implementation.

- [ ] **Step 6: Commit the regression locks**

```bash
git add tests/test_canonical_gaps.py tests/test_skills_behavior.py tests/test_ui_trip.py \
  routers/v1/trip.py services/atlas_client.py services/rescue_engine.py static/index.html
git commit -m "test(review): lock retained safety fixes"
```

Stage only files that actually changed.

---

### Task 4: Run the Devil's-Advocate Review and Bounded Correction Loop

**Files:**

- Inspect: complete diff from `d94fc5101187b67532633ec8f72f58be9a925eab` to branch HEAD
- Modify: only files proven defective by a reproduced finding
- Test: add one behavioral regression per accepted defect

**Interfaces:**

- Consumes: a stopped writer, clean branch, focused suites green.
- Produces: three independent read-only verdicts and at most three evidence-backed correction cycles.

- [ ] **Step 1: Freeze the writer and capture the review surface**

```bash
git status --short --branch
git diff --check
git diff --stat d94fc5101187b67532633ec8f72f58be9a925eab..HEAD
git diff d94fc5101187b67532633ec8f72f58be9a925eab..HEAD
```

Expected: clean branch before reviewers start. Reviewers must not edit.

- [ ] **Step 2: Run three independent read-only reviews**

Reviewer A — completeness:

```text
Read AGENTS.md, docs/MASTER_BUILD_PACKAGE.md, and the complete base-to-HEAD diff. Check F1-F20 and exact public S1-S13 coverage, runtime wiring, APIs, UI reachability, docs, and degraded modes. Report only high-confidence actionable omissions with file and line evidence. Do not edit.
```

Reviewer B — correctness and security:

```text
Read the same inputs. Attack idempotency races, same-key/different-payload behavior, retry after provider failure, approval forgery, fail-open provider paths, raw exception/credential leakage, privacy boundaries, live-send gates, and cross-trip state. Report reproducible high-confidence issues only. Do not edit.
```

Reviewer C — user impact and evidence honesty:

```text
Read the same inputs and run read-only browser/source inspection. Check beginner flow, keyboard/mobile behavior, duplicate actions, error feedback, loading states, claims/Guardian wording, manifest listing, and every completion claim against actual artifacts. Report high-confidence user-impact or evidence-integrity issues only. Do not edit.
```

- [ ] **Step 3: Triage every finding against code and runtime**

For each finding, record one of:

- `ACCEPTED`: reproduced with an exact command or focused test;
- `REJECTED`: contradicted by cited code plus a passing consumer-visible test;
- `BLOCKED`: requires an external approval, credential, real provider, or architecture choice.

Reviewer wording alone is never proof.

- [ ] **Step 4: Run a maximum of three correction cycles**

For each accepted issue in a cycle:

1. write one focused behavioral test;
2. run it and observe the failure caused by the reported defect;
3. patch the smallest production surface;
4. rerun the focused test and its neighboring suite;
5. inspect `git diff --check`;
6. commit the cycle with the finding IDs in the message body.

After each cycle, rerun the three review dimensions on the new clean HEAD. Stop early when all three return no accepted high-confidence findings. After the third cycle, any accepted unresolved finding blocks completion; do not relabel it as a limitation merely to finish.

- [ ] **Step 5: Confirm no unauthorized side effects occurred**

Verify no remote branch changed, no deployment occurred, no live Telegram/provider call ran, and no real traveler record was introduced.

---

### Task 5: Rebuild Accurate Durable Evidence

**Files:**

- Modify: `DECISIONS.tsv`
- Modify: `PLAN.md`
- Review/modify only if truth changed: `BLOCKERS.md`
- Replace: `FINAL_REPORT.md`

**Interfaces:**

- Consumes: final reviewed implementation and the fresh pre-report verification captured in Step 1; Task 6 repeats the gates against the documented and promoted tree.
- Produces: detailed F1-F20 and S1-S13 matrices with exact commands, actual results, and honest limitations.

- [ ] **Step 1: Capture fresh pre-report verification evidence**

Run the dependency check, collection, complete suite, complete UI suite,
focused remediation suites, legacy canary, JavaScript syntax checks, security
gate, and `git diff --check` using the commands in Task 6 Steps 2 and 3.
Record the exact output from this run for the report. If any command fails,
return to Task 4; do not write a completion verdict around a red gate.

- [ ] **Step 2: Record the two intentional contract decisions**

Append separate `DECISIONS.tsv` rows that state:

1. the public product registry is exactly S1-S13 while `clarify_loop` is validated and loaded only in the internal execution registry;
2. the reachable legacy `/api/rescue/book` endpoint requires `Idempotency-Key`, stores `(payload_hash, exact_response)` only after provider success, serializes same-key concurrency, returns 409 for altered payloads, and permits same-key retry after a failed provider attempt.

Use the actual UTC execution timestamp and cite the concrete implementation/test files. Do not rewrite earlier decision history.

- [ ] **Step 3: Reconcile `PLAN.md`**

Remove the duplicate `121658d` row in the R7 corrective table. Add a new post-review remediation section listing the actual new commits and distinguishing:

- reproduced defects fixed RED-GREEN;
- retained Antigravity fixes protected by regression/mutation checks;
- review findings rejected with evidence;
- remaining external-only limitations.

Do not paste stale test totals into historical sections. Put only the fresh final totals in the new current-authority section.

- [ ] **Step 4: Rebuild `FINAL_REPORT.md` from the detailed structure**

Use `git show 680a1d4:FINAL_REPORT.md` only as a structural reference for its detailed sections and matrices. Do not copy its branch name, counts, timings, screenshots, provider labels, or completion verdict.

The rebuilt report must contain:

- authoritative spec path and SHA-256;
- scope and explicit no-push/no-deploy/no-live-booking boundary;
- post-review correction summary including commit `62a27ea` and later remediation commits;
- exact fresh verification command table from Task 5 Step 1;
- F1-F20 matrix with runtime file, primary behavioral proof, and verdict;
- exact S1-S13 matrix with `profile_edit` as S3 and no public `clarify_loop` row;
- a separate note that `clarify_loop` is a governed internal helper;
- gate reconciliation for G0-G8;
- honest limitations: Sandbox/mock mode, untested live credentials/providers, in-process trip state, no production authentication/multi-tenancy, and unavailable optional security tools only when actually unavailable;
- handoff boundary and local-only promotion result.

Remove the invalid pattern of calling a Git tree object a “Final main SHA.” Do not put a self-referential commit hash inside the report; report the exact final commit in the external handoff after the commit exists.

- [ ] **Step 5: Keep blockers factual**

Preserve the resolved canonical-reconciliation record in `BLOCKERS.md`. Add a blocker only if the review loop leaves a real unresolved product issue. Provider credentials and public deployment remain external gates, not code defects.

- [ ] **Step 6: Run documentation integrity and whitespace checks**

```bash
/private/tmp/travelcare-r7-venv/bin/python -m pytest -p no:cacheprovider \
  tests/test_docs_integrity.py tests/test_skills_manifest.py -q
git diff --check
```

Expected: PASS.

- [ ] **Step 7: Commit evidence reconciliation**

```bash
git add DECISIONS.tsv PLAN.md BLOCKERS.md FINAL_REPORT.md
git commit -m "docs(report): reconcile post-review completion evidence"
```

Stage `BLOCKERS.md` only if it changed.

---

### Task 6: Fresh Verification, Local Main Promotion, and Final Handoff

**Files:**

- Verify: complete tracked tree
- Modify: none during the verification run
- Git operation: local fast-forward only after all gates pass

**Interfaces:**

- Consumes: clean reviewed remediation branch and reconciled evidence.
- Produces: clean local `main` at the exact verified commit; `origin/main` unchanged.

- [ ] **Step 1: Read the completion-verification instructions**

If available, read and follow `superpowers:verification-before-completion` before making any success statement.

- [ ] **Step 2: Run dependency, collection, complete-suite, and focused gates**

```bash
/private/tmp/travelcare-r7-venv/bin/python -m pip check
TZ=UTC /private/tmp/travelcare-r7-venv/bin/python -m pytest \
  -p no:cacheprovider --collect-only -q
TZ=UTC /private/tmp/travelcare-r7-venv/bin/python -m pytest \
  -p no:cacheprovider -q
TZ=UTC /private/tmp/travelcare-r7-venv/bin/python -m pytest \
  -p no:cacheprovider tests/test_ui_trip.py -q
/private/tmp/travelcare-r7-venv/bin/python -m pytest -p no:cacheprovider \
  tests/test_legacy_booking_safety.py \
  tests/test_claims_provider_truth.py \
  tests/test_skills_manifest.py \
  tests/test_privacy.py \
  tests/test_canonical_gaps.py -q
```

Expected: every command exits 0. Record the exact observed collection/pass totals and timings; do not reuse earlier numbers.

- [ ] **Step 3: Run browser canary, syntax, security, and whitespace gates**

```bash
TZ=UTC /private/tmp/travelcare-r7-venv/bin/python tests/e2e_full_journey.py
node --check static/app.js
node --check static/trip.js
PATH="/private/tmp/travelcare-r7-venv/bin:$PATH" bash scripts/security_check.sh
git diff --check
git status --short --branch
```

Expected: canary all-pass, both JavaScript files valid, every executed security section passes, whitespace clean, branch clean.

- [ ] **Step 4: Run a controlled fresh boot smoke without touching port 8050**

Start the app on an unused port such as 8051, capture only the PID created by this step, and stop only that PID in cleanup. Probe:

```text
GET /api/health -> 200 and truthful runtime/mock labels
GET /api/skills -> 200, count 13, includes profile_edit, excludes clarify_loop
```

Do not print environment values. If the chosen port is occupied, select another unused high port; never terminate the owner of an existing listener.

- [ ] **Step 5: Verify branch and remote boundaries**

```bash
git status --short --branch
git rev-parse HEAD
git rev-parse main
git rev-parse origin/main
git log --oneline --decorate d94fc5101187b67532633ec8f72f58be9a925eab..HEAD
```

Expected: remediation branch clean; `main` still at the pre-promotion base; remote unchanged.

- [ ] **Step 6: Fast-forward local `main` only**

```bash
git switch main
git merge --ff-only codex/travelcare-antigravity-remediation
git status --short --branch
```

Abort promotion if `main` moved in a way that prevents a fast-forward. Do not merge with a merge commit, rebase, reset, or resolve unrelated history automatically.

- [ ] **Step 7: Re-run the exact complete suite on promoted `main`**

```bash
TZ=UTC /private/tmp/travelcare-r7-venv/bin/python -m pytest \
  -p no:cacheprovider -q
node --check static/app.js
node --check static/trip.js
git diff --check
git status --short --branch
```

Expected: complete suite exits 0, syntax and whitespace clean, local `main` clean and ahead of `origin/main` only. No push.

- [ ] **Step 8: Return an evidence-only handoff**

Report:

- final local `main` commit from `git rev-parse HEAD`;
- exact fresh test totals and timings;
- focused booking/claims/privacy/skills results;
- browser canary and security-gate results;
- `/api/skills` exact count and internal-helper distinction;
- three reviewer verdicts and number of correction cycles used;
- honest limitations and unavailable optional tools;
- confirmation that `origin/main` did not change and no push, deploy, publication, real data, credential read, live Telegram, or live booking occurred.

Do not delete the remediation branch or any worktree unless the owner separately approves cleanup.

<!-- PLAN_COMPLETE -->
