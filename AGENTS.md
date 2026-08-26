# Autonomous Rescue Agent - Agent Instructions

TravelCare AI is an autonomous flight-disruption recovery service: it watches
flights, ranks rescue packages, rebooks through the Atlas sandbox, and drafts
air-passenger-rights claims. This repository is its FastAPI implementation.

## Purpose & Boundary
This file governs AI-assisted work inside this repository only: it maps the
codebase and fixes the process every change must follow. Product narrative and
marketing claims live in `README.md`. Tracked docs carry durable engineering
facts exclusively - never statuses, deadlines, counts, model identifiers,
machine-local paths, or private system references; verify such facts live
instead of writing them down.

## Source-of-Truth Hierarchy
1. Runtime behavior and version-controlled code (`git log`, `git blame`).
2. This `AGENTS.md` - architecture map plus change-process contract.
3. `README.md` - quickstart narrative and product framing.
Trust runtime over code, code over docs. Path-shaped inline spans below resolve
against the repo root and exist on the tree; other spans name modules or shell
commands. If docs contradict code, code wins - fix the doc in the same change.

## Codebase Map
- Entry point: `main.py` builds the FastAPI app, mounts `static/`, registers
  every router from `routers/v1` (flights, disruptions, bookings, concierge,
  claims, telemetry, hotels, radar).
- Domain services under `services/`: `atlas_client` (GDS search, booking,
  e-ticket), `guardian` (push notifications), `llm` (model calls), `radar`
  (background watch loop), `rescue_engine` and `state_graph` (recovery
  reasoning), `rights_engine` and `visa_guard` (entitlements, passport rules).
- Settings come from `config.py`, which reads environment variables only;
  secrets stay env-only. Schemas: `models/schemas.py`.
- Automated suites are collected by pytest under `tests/`.
- Dependencies: `requirements.txt`.

## Setup, Run, Verify
    pip install -r requirements.txt
    uvicorn main:app --reload
    python -m pytest -q
The full command inventory lives in `README.md` (Quickstart). If a documented
command drifts from reality, repair the doc or the code in the same change -
never skip verification silently.

## Pre-Change Context Gate
Assemble an 11-field packet before editing: objective; files in scope; entry
points touched; upstream callers; downstream callees; settings impact;
persisted-state impact; boundary check (approval needed?); verification plan;
rollback plan; open assumptions. Then run the six required searches and record
what they surface:
1. definition, callers, and importers of every changed symbol; search both the
   module path and symbol so aliases and function-local imports are included
2. route handlers or API surface affected by the change
3. existing coverage under `tests/` pinning current behavior
4. settings keys read by touched modules
5. docs mentioning changed paths (`git grep`)
6. TODO/FIXME markers near the change site

## Safety & Approval Boundaries
- No deploy, publish, or release action without explicit owner approval.
- Credentials and key material: env-only; never commit, open, echo, or log them.
- No destructive operations (history rewrite, force-push, bulk deletion)
  without approval; external repos and scripts get review before execution.
- Sandbox or demo externals only; never touch production systems or real
  traveler data.
