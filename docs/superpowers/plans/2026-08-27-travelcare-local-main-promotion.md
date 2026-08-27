# TravelCare AI R7 Local Main Promotion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Safely promote the verified TravelCare AI R7 full product from
`feature/trip-agent` into local `main`, reconcile the remaining stale evidence,
independently challenge the build for real bugs, fix only reproduced defects,
and leave an exact green handoff without pushing, deploying, publishing, or
using real traveler data.

**Architecture:** Treat `feature/trip-agent` as the verified source branch and
`main` as a local promotion target. One coordinator is the only writer;
reviewers are read-only and must inspect actual code and evidence. Promotion is
fast-forward-only because current preflight proves `main` is an ancestor of the
feature branch; any drift or divergence stops the merge instead of inventing a
conflict resolution.

**Tech Stack:** Python 3 / FastAPI / Pydantic, pytest, Playwright Chromium,
vanilla JavaScript/CSS, Git, Atlas Sandbox adapters.

**Spec:** `docs/MASTER_BUILD_PACKAGE.md` and
`docs/superpowers/plans/2026-08-27-travelcare-r7-canonical-completion.md`

## Global Constraints

- Execute this plan; do not merely summarize it or return a suggested prompt.
- Repository: `/Users/mac/Projects/code/alibaba-atlas-rescue-agent`.
- Verified product baseline: `dbbe2d7c0155f2821213741e43ddf736268167f8`.
- At plan authoring time, local `main` is `eae9f6b1ee3e0f3511bab409fe5759d72188bf60`,
  local `main` is one commit ahead of `origin/main`, and `main...feature/trip-agent`
  is `0 38`. Re-read live state; do not assume it stayed unchanged.
- Do not run `git pull`, `git fetch`, `git push`, deploy, publish, submit, tag,
  create a PR, or perform a live airline booking.
- Do not run `git reset`, `git clean`, `git stash`, force checkout, force merge,
  force push, branch deletion, or worktree deletion.
- Never read or print `.env`, `.env.local`, credential files, tokens, raw
  profiles, or stored traveler data. Do not expose environment-variable values.
- Use only fictional tracked demo fixtures. Never request or store a passport
  number, legal identity, payment details, or real traveler record.
- Do not install tools, plugins, packages, or security scanners. If an optional
  scanner is unavailable, record it honestly as unavailable.
- One writer only. Review agents are read-only. Never allow two agents to edit
  the same repository, branch, file, or shared registry concurrently.
- Do not ask the owner routine questions. Resolve ordinary implementation and
  test choices from the canonical spec and current code. Stop only for an
  authorization boundary, unexpected user changes, ambiguous merge conflict,
  credential requirement, or destructive action.
- Preserve all user/unrelated changes. Use `git add <exact-paths>`; never use
  `git add .`.
- Do not trust earlier agent completion claims. Inspect diffs and rerun the
  required checks yourself.

---

## Agent Roles and Ownership

### Integration Coordinator — sole writer

Owns preflight, documentation reconciliation, validated bug fixes, commits,
fast-forward promotion, final verification, and the handoff. It must inspect
every reviewer finding before changing code.

### Completeness Reviewer — read-only

Checks F1–F20, S1–S13, G0–G8, API/UI wiring, degraded paths, and evidence
coverage against `docs/MASTER_BUILD_PACKAGE.md`. It must cite file and line,
state the missed requirement, and give a reproducible check.

### Correctness and Security Reviewer — read-only

Checks confirmation boundaries, exact-route enforcement, approval scope,
idempotency concurrency, recovery evidence, safety fail-closed behavior,
privacy, XSS sinks, and config-dependent runtime honesty. It must report only
high-confidence actionable defects.

### User-Flow and Impact Reviewer — read-only

Checks the beginner path, one-question-at-a-time intake, loading/error states,
mobile overflow, keyboard/accessibility, recovery approval separation, and
whether a defect materially affects the demo or traveler.

Reviewers must not edit files, weaken tests, repeat report claims as evidence,
or return generic advice. “No findings” is acceptable only after listing the
files and commands actually inspected.

---

## Non-Looping Failure Contract

Every failure enters this bounded loop. Never rerun the same failing command
without a changed hypothesis, environment, or code state.

1. **Observe:** Capture the exact failing command, first useful traceback,
   affected file/line, branch, and HEAD. Do not dump secrets or full unrelated
   logs.
2. **Classify:** Choose exactly one class:
   `product_regression`, `test_defect`, `environment_permission`,
   `provider_unavailable`, `repository_drift`, or `authorization_block`.
3. **Hypothesize:** Write one falsifiable root-cause statement. Do not list
   several vague possibilities.
4. **Reproduce narrowly:** Run the smallest deterministic test that proves the
   failure. For code defects, add or identify a regression test that is red for
   the correct reason before implementation.
5. **Fix minimally:** Change only the files required by the reproduced defect.
   Do not refactor adjacent working code or broaden product scope.
6. **Verify upward:** Run the focused test, its containing suite, then the full
   required gate. A focused pass alone never closes a product bug.
7. **Devil's advocate:** Explain how the fix could still be wrong and run one
   check that would expose that failure mode.
8. **Commit exactly:** Stage only owned paths and create one purpose-specific
   commit.

Maximum: three cycles per distinct failure. After three unsuccessful cycles,
record the attempts in `BLOCKERS.md`, preserve the last known-good state, stop
that path, and report the exact blocker. Never claim completion and never keep
looping.

Known classification example: `PermissionError` while binding
`127.0.0.1:8050` inside a restricted sandbox is
`environment_permission`. Rerun the same suite once in the approved host
environment; do not change product code to “fix” the sandbox. A configured AI
runtime showing a configured model instead of `Deterministic fallback` is not
a product failure if `/api/health.ai_engine` and the badge agree.

---

### Task 1: Lock Scope and Revalidate Repository State

**Files:**
- Read: `/Users/mac/Documents/Second Brain Test/AGENTS.md`
- Read: `/Users/mac/Documents/Second Brain Test/system/AGENT_REGISTRY.md`
- Read: `docs/MASTER_BUILD_PACKAGE.md`
- Read: `FINAL_REPORT.md`
- Read: `PLAN.md`
- Read: `BLOCKERS.md`
- Modify: none

**Interfaces:**
- Consumes: current Git branches, worktrees, and active-writer registry.
- Produces: a written preflight snapshot used by every later task.

- [ ] **Step 1: Confirm no competing writer**

Read the active registry and `git worktree list --porcelain`. If another agent
is actively writing this repository, do not start edits. Wait for its handoff
or report the collision. The existing Codex plan-authoring row may be treated
as complete only when the plan commit/handoff is present.

- [ ] **Step 2: Record the live branch snapshot**

Run each command separately from the repository root:

```bash
git status --short --branch
```

```bash
git rev-parse main feature/trip-agent origin/main
```

```bash
git rev-list --left-right --count main...feature/trip-agent
```

```bash
git worktree list --porcelain
```

Expected before execution drift: the working tree is clean; the verified
product baseline `dbbe2d7` is an ancestor of `feature/trip-agent`; `main` has
zero unique commits relative to the feature branch.

- [ ] **Step 3: Prove fast-forward eligibility without changing refs**

```bash
git merge-base --is-ancestor main feature/trip-agent
```

Expected: exit 0.

```bash
git merge-base --is-ancestor dbbe2d7c0155f2821213741e43ddf736268167f8 feature/trip-agent
```

Expected: exit 0.

If either command fails, classify it as `repository_drift`. Do not merge, do
not invent a conflict resolution, and do not reset either branch.

- [ ] **Step 4: Confirm protected boundaries**

Use `git status --porcelain=v1 -uall` and tracked-file searches only. Do not
open ignored environment or profile files. Confirm the plan authoring itself
did not change product source.

---

### Task 2: Reconcile Stale Completion Evidence on the Feature Branch

**Files:**
- Modify: `BLOCKERS.md`
- Modify: `FINAL_REPORT.md`
- Modify: `PLAN.md`
- Test: `tests/test_docs_integrity.py`

**Interfaces:**
- Consumes: verified R7 commits through `dbbe2d7` and the fresh preflight.
- Produces: one non-contradictory current completion record before promotion.

- [ ] **Step 1: Capture the documentation defects before editing**

```bash
rg -n "Canonical spec reconciliation|Status: OPEN|dbbe2d7|827be74|Verification branch|Integration target" BLOCKERS.md FINAL_REPORT.md PLAN.md
```

Expected red evidence: the canonical reconciliation entry still says `OPEN`;
`FINAL_REPORT.md` omits the final report/test-honesty commits from its R7
commit table or still describes promotion as pending.

- [ ] **Step 2: Correct `BLOCKERS.md` without erasing history**

Keep the original repro, hypothesis, and corrective-sequence narrative. Change
only its current resolution:

- canonical spec reconciliation becomes `RESOLVED` by R0–R7 through
  `dbbe2d7`;
- the bare Atlas-unreachable note becomes a structured provider-availability
  limitation, not an open product bug;
- every current entry must end in `RESOLVED`, `WORKAROUND`, or `NONE OPEN`.

- [ ] **Step 3: Correct the current report and plan**

In `FINAL_REPORT.md`:

- identify `feature/trip-agent` as the verified product source branch;
- identify local `main` as the promotion target;
- add `827be74` (evidence reconciliation) and `dbbe2d7` (configured-runtime
  honesty test) to the R7 additive commit list;
- state that there are no known open code blockers;
- preserve all sandbox/live-provider/security-tool limitations.

In the final R7 authority section of `PLAN.md`:

- add `dbbe2d7` to the corrective sequence;
- state that the former open canonical reconciliation blocker is resolved;
- do not rewrite or delete historical gate snapshots.

- [ ] **Step 4: Verify documentation reconciliation**

```bash
rg -n "Canonical spec reconciliation|Status: OPEN|dbbe2d7|827be74|feature/trip-agent|local main" BLOCKERS.md FINAL_REPORT.md PLAN.md
```

Expected: no current canonical-reconciliation `OPEN`; both final commits and
the local-main boundary are present.

```bash
.venv/bin/python -m pytest -p no:cacheprovider tests/test_docs_integrity.py -q
```

Expected: all collected documentation-integrity tests pass.

```bash
git diff --check
```

Expected: no whitespace errors.

- [ ] **Step 5: Commit exact documentation paths**

```bash
git add BLOCKERS.md FINAL_REPORT.md PLAN.md
```

```bash
git diff --cached --check
```

```bash
git commit -m "docs(report): close R7 promotion evidence"
```

Do not stage the Antigravity IDE state, screenshots, profiles, environment
files, or unrelated vault changes.

---

### Task 3: Run Independent Read-Only Reviews Before Promotion

**Files:**
- Read: `docs/MASTER_BUILD_PACKAGE.md`
- Read: runtime source under `models/`, `routers/`, `services/`, and `static/`
- Read: tests under `tests/`
- Modify: none by reviewers

**Interfaces:**
- Consumes: the clean feature-branch documentation commit.
- Produces: three independent finding lists with reproducible evidence.

- [ ] **Step 1: Dispatch the Completeness Reviewer**

Require it to map F1–F20 and S1–S13 to actual runtime paths and tests. It must
focus on missing user-visible behavior, skipped scope, dead UI wiring, and
evidence that claims more than the runtime proves.

- [ ] **Step 2: Dispatch the Correctness and Security Reviewer**

Require it to challenge plural confirmation, BKK/DMK ambiguity, exact initial
and recovery airport pairs, immutable approval snapshots, concurrency and
idempotency, safety fail-closed behavior, receipts/rights/monitoring, privacy,
and XSS boundaries.

- [ ] **Step 3: Dispatch the User-Flow and Impact Reviewer**

Require it to inspect the rendered flow or Playwright coverage for first-time
users, loading/error states, mobile width, keyboard navigation, recovery
approval, source labels, and actual configured-runtime honesty.

- [ ] **Step 4: Validate every finding centrally**

The coordinator must reproduce each finding. Reject duplicate, speculative,
out-of-scope, or already-covered findings with evidence. Deduplicate accepted
findings by root cause, not by reviewer wording.

- [ ] **Step 5: Enter the bounded failure loop only for accepted defects**

For each accepted defect, use the Non-Looping Failure Contract. A code fix
requires a red regression test, minimal implementation, focused green test,
containing-suite green test, and a purpose-specific commit. Documentation-only
defects require a failing search/assertion and `test_docs_integrity.py`.

---

### Task 4: Verify the Complete Feature Branch

**Files:**
- Read/test: entire tracked repository
- Modify: none unless Task 3 produced a reproduced defect

**Interfaces:**
- Consumes: clean feature branch plus any validated corrective commits.
- Produces: a complete pre-promotion evidence snapshot.

- [ ] **Step 1: Check dependency consistency**

```bash
.venv/bin/python -m pip check
```

Expected: `No broken requirements found.`

- [ ] **Step 2: Collect the entire suite**

```bash
/usr/bin/env TZ=UTC .venv/bin/python -m pytest -p no:cacheprovider --collect-only -q
```

Expected: at least 376 tests and zero collection errors. A higher count is
allowed only when this plan added legitimate regression tests.

- [ ] **Step 3: Run the complete suite**

```bash
/usr/bin/env TZ=UTC .venv/bin/python -m pytest -p no:cacheprovider -q
```

Expected: every collected test passes. If local port binding is denied by a
sandbox, classify the result as `environment_permission` and rerun once in the
approved host environment; do not modify code.

- [ ] **Step 4: Run the legacy browser canary**

```bash
/usr/bin/env TZ=UTC .venv/bin/python tests/e2e_full_journey.py
```

Expected: `14/14 passed`.

- [ ] **Step 5: Run static and security gates**

```bash
node --check static/app.js
```

```bash
node --check static/trip.js
```

```bash
bash scripts/security_check.sh
```

```bash
git diff --check
```

Expected: both JavaScript files are valid; all six available security sections
pass; privacy is green; no whitespace errors. Record `gitleaks` or `pip-audit`
as unavailable if missing—do not silently install them and do not call them a
pass.

- [ ] **Step 6: Run a bounded boot smoke**

Start `.venv/bin/python main.py` in a managed background terminal. Probe only
the local application:

- `GET http://127.0.0.1:8050/api/health` returns HTTP 200 and `healthy`;
- `GET http://127.0.0.1:8050/api/skills` returns 13 skills;
- `ai_engine` is non-empty and the UI label agrees with it;
- `mock_mode` and Sandbox provenance remain visible and honest.

Stop only the exact server process started by this task. Do not stop a
pre-existing listener and do not call live providers during this smoke.

- [ ] **Step 7: Freeze the promotion source**

Record:

```bash
git rev-parse feature/trip-agent
```

```bash
git status --short --branch
```

The feature branch must be clean. This recorded SHA is
`PROMOTION_SOURCE_HEAD` for Task 5.

---

### Task 5: Fast-Forward Local Main

**Files:**
- Modify: Git reference `refs/heads/main` through a normal fast-forward merge
- Modify: no source file in this task

**Interfaces:**
- Consumes: clean `PROMOTION_SOURCE_HEAD` and green Task 4 evidence.
- Produces: local `main` containing the exact verified source history.

- [ ] **Step 1: Repeat the no-drift gate immediately before merge**

```bash
git status --porcelain=v1 -uall
```

Expected: empty.

```bash
git merge-base --is-ancestor main feature/trip-agent
```

Expected: exit 0.

```bash
git rev-parse feature/trip-agent
```

Expected: equals the recorded `PROMOTION_SOURCE_HEAD`.

If any check differs, stop with `repository_drift`. Do not stash, reset, clean,
or merge around it.

- [ ] **Step 2: Switch the canonical checkout to local main**

```bash
git switch main
```

Do not pull. Local `main` intentionally contains `eae9f6b` ahead of
`origin/main`, and the feature history already contains it.

- [ ] **Step 3: Perform the fast-forward-only promotion**

```bash
git merge --ff-only feature/trip-agent
```

Expected: fast-forward succeeds with no merge commit and no conflict.

- [ ] **Step 4: Prove exact ref equality**

```bash
git rev-parse main feature/trip-agent
```

Expected: both lines equal `PROMOTION_SOURCE_HEAD`.

```bash
git status --short --branch
```

Expected: branch `main`, clean working tree. Do not push.

---

### Task 6: Verify the Exact Promoted Main Tree

**Files:**
- Read/test: entire tracked repository on `main`
- Modify: none unless a failure is reproduced through the bounded loop

**Interfaces:**
- Consumes: local fast-forwarded `main`.
- Produces: final merged-result evidence; feature evidence alone is not enough.

- [ ] **Step 1: Run dependency, collection, and complete-suite gates on main**

Run the exact Task 4 dependency, collection, and full-suite commands from the
`main` checkout. Expected: no broken dependencies, zero collection errors, and
all tests pass.

- [ ] **Step 2: Run canary, JavaScript, security, and whitespace gates on main**

Run the exact Task 4 canary, two `node --check` commands,
`scripts/security_check.sh`, and `git diff --check`. Expected: all available
gates green with the same honest optional-tool limitations.

- [ ] **Step 3: Repeat the bounded boot smoke on main**

Use the Task 4 local-only boot procedure. Verify health, 13 skills, runtime
label truth, Sandbox/mock provenance, and clean shutdown of only the process
this task started.

- [ ] **Step 4: Handle any failure without undoing the promotion**

Enter the Non-Looping Failure Contract. A failure on fast-forwarded `main`
should reproduce on the identical feature tree unless caused by local ignored
configuration. Do not reset `main`; diagnose and make an additive fix commit on
`main`, then rerun focused, containing, and full gates.

---

### Task 7: Final Devil's-Advocate Audit and Fix Loop

**Files:**
- Read: current `main` source, tests, final report, plan, and blockers
- Modify: only if an accepted finding is reproduced

**Interfaces:**
- Consumes: green exact-main evidence.
- Produces: final independent review verdict and zero unresolved accepted bugs.

- [ ] **Step 1: Give each reviewer the final main SHA, not an old handoff**

Each reviewer must start from `git rev-parse HEAD` and `git status --short`.
They must inspect current files and cannot rely on prior “zero findings.”

- [ ] **Step 2: Require adversarial checks**

At minimum, reviewers must challenge:

- changing a confirmed BKK route to DMK during recovery;
- two concurrent approval calls with the same and different idempotency keys;
- stale confirmation invalidating search/visa/approval snapshots;
- replacement itinerary mutation of the booked flight or unrelated sections;
- safety unavailable/stale/do-not-travel/reconsider paths;
- configured-provider versus deterministic-fallback UI truth;
- slow approval feedback, duplicate click prevention, keyboard path, and mobile
  overflow;
- forbidden profile fields and hostile HTML/provider payloads.

- [ ] **Step 3: Validate and fix only reproduced defects**

Use the Non-Looping Failure Contract. Never accept a reviewer recommendation
because it sounds plausible. Never weaken an assertion merely to make a suite
green.

- [ ] **Step 4: Rerun the complete Task 6 gate after the last accepted fix**

The final full-suite run must occur after the final source/test commit. A green
run from before the last change is not final evidence.

---

### Task 8: Close Records and Produce the Exact Handoff

**Files:**
- Modify: `/Users/mac/Documents/Second Brain Test/system/AGENT_REGISTRY.md`
- Read: `FINAL_REPORT.md`
- Read: `BLOCKERS.md`
- Read: Git status/log

**Interfaces:**
- Consumes: clean, green local `main` and final reviewer verdicts.
- Produces: one truthful completion record and explicit remaining owner gates.

- [ ] **Step 1: Re-read the registry immediately before editing**

Preserve all unrelated/user changes. Remove only this Antigravity task's active
row and add one activity-log row with branch, HEAD, tests, limitations, and
“no push/deploy.” Do not stage or commit unrelated vault changes.

- [ ] **Step 2: Capture the final Git handoff**

```bash
git branch --show-current
```

Expected: `main`.

```bash
git rev-parse HEAD
```

```bash
git status --short --branch
```

```bash
git log --oneline --decorate --max-count=20
```

State explicitly: no more writes are running.

- [ ] **Step 3: Return the final report in this exact structure**

1. `Outcome`: local main promotion complete or exact blocker.
2. `Branch and HEAD`: final main SHA and source feature SHA.
3. `Changes`: documentation correction plus any reproduced bug-fix commits.
4. `Verification`: collection count, full-suite result, UI/browser canary,
   security, JavaScript, dependency, boot smoke, and reviewer verdicts.
5. `Honest limitations`: Sandbox/mock mode, live providers not exercised,
   in-process trip state, single-user/no auth, optional scanner availability.
6. `External actions`: explicitly say no push, deploy, publication, submission,
   tag, or live booking.
7. `Remaining owner gates`: demo recording, exact push/PR target approval,
   deployment approval, and Devpost submission approval.

Do not end with a vague “should be good.” Use exact evidence and name every
remaining gate.

---

## Definition of Done

All conditions must be true at the same time:

- local `main` contains the verified product baseline and every accepted
  additive correction;
- `main` and the recorded promotion-source feature SHA were equal immediately
  after fast-forward, with later main-only fixes fully documented if any;
- the final main working tree is clean;
- all collected pytest tests pass on the exact final source/test tree;
- legacy canary is 14/14, JavaScript syntax is valid, dependency consistency is
  clean, all available security sections pass, and boot smoke returns healthy
  with 13 skills;
- configured-runtime and fallback labels remain honest;
- `BLOCKERS.md` contains no falsely open R7 reconciliation blocker;
- all accepted reviewer findings are fixed and independently reverified, or an
  exact blocker is reported after three bounded attempts;
- no real PII, credential, payment data, push, deploy, publication, Devpost
  submission, tag, PR, or live booking occurred;
- activity registry is closed and the handoff says “no more writes running.”

## Mandatory Stop Conditions

Stop without merging or claiming completion if:

- the repository has unexplained tracked/untracked changes;
- another writer is active on the same repository or canonical registry file;
- `main` is no longer an ancestor of `feature/trip-agent`;
- the verified baseline is missing from the feature history;
- a merge conflict appears;
- a step requires secrets, real traveler data, network publication, push,
  deployment, payment, live booking, or destructive cleanup;
- the same failure survives three evidence-changing fix cycles.

The stop report must include the exact command, branch/HEAD, failure class,
three attempts if applicable, preserved state, and the smallest owner decision
needed. It must not ask broad questions or restart the entire plan.
