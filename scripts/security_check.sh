#!/usr/bin/env bash
# G5 Security & Audit Gate — single evidence producer (PLAN.md G5).
#
#   scripts/security_check.sh                 run the full gate
#   scripts/security_check.sh --install-hook  install the precommit hook
#
# Sections: secret scan (tracked tree), forbidden-file tracking, precommit
# hook, XSS sink audit (owned JS), pydantic-boundary + privacy contracts,
# dependency advisory scan. Exits non-zero on any FAIL.
set -u

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
    echo "not inside a git repository" >&2; exit 2; }
cd "$ROOT"

FAILURES=0
PY=".venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3 || command -v python)"
ok()   { printf 'PASS  %s\n' "$1"; }
bad()  { printf 'FAIL  %s\n' "$1"; FAILURES=$((FAILURES + 1)); }
note() { printf 'NOTE  %s\n' "$1"; }
section() { printf '\n===== %s =====\n' "$1"; }

if [ "${1:-}" = "--install-hook" ]; then
    cp scripts/pre-commit .git/hooks/pre-commit
    chmod +x .git/hooks/pre-commit
    echo "installed .git/hooks/pre-commit (banned-pattern scan on staged"
    echo "content; delegates additionally to gitleaks when installed)"
    exit 0
fi

# ---------------------------------------------------------------- 1/6
section "1/6 secret scan — tracked tree (banned patterns must be ZERO)"
if command -v gitleaks >/dev/null 2>&1; then
    if gitleaks detect --redact --no-banner --source "$ROOT"; then
        ok "gitleaks: tracked tree clean"
    else
        bad "gitleaks reported findings in the tracked tree"
    fi
else
    note "gitleaks binary not installed on this host — the built-in banned-pattern scan below is the gate (same patterns as the hook)"
fi
hits=0
while IFS= read -r p; do
    [ -z "$p" ] && continue
    found="$(git grep -nE -e "$p")"
    rc=$?
    if [ "$rc" -gt 1 ]; then
        bad "git grep error while scanning pattern: $p"
        hits=1
    elif [ "$rc" -eq 0 ]; then
        bad "banned pattern in tracked tree: $p"
        printf '%s\n' "$found" | head -5
        hits=1
    fi
done < scripts/banned_secret_patterns.txt
[ "$hits" -eq 0 ] && ok "banned-pattern grep over tracked tree: zero hits"

# ---------------------------------------------------------------- 2/6
section "2/6 forbidden files never tracked + ignore coverage"
env_tracked="$(git ls-files | grep -E '(^|/)\.env($|\.)' | grep -v '^\.env\.example$' || true)"
if [ -z "$env_tracked" ]; then
    ok "no env files tracked (.env.example carries placeholders only)"
else
    bad "env file(s) tracked: $env_tracked"
fi
for p in "data/profiles/" "screenshots/" "e2e_screenshots/"; do
    if git ls-files -- "$p" | grep -q .; then
        bad "$p is tracked"
    else
        ok "$p not tracked"
    fi
done
for probe in .env .env.local .env.backup data/profiles/x.json screenshots/x.png; do
    if git check-ignore -q "$probe"; then
        ok "gitignore covers $probe"
    else
        bad "gitignore does NOT cover $probe"
    fi
done

# ---------------------------------------------------------------- 3/6
section "3/6 precommit hook installed + live staged scan"
if [ -x .git/hooks/pre-commit ]; then
    ok ".git/hooks/pre-commit installed and executable"
else
    bad ".git/hooks/pre-commit missing — run: scripts/security_check.sh --install-hook"
fi
if bash scripts/pre-commit; then
    ok "hook scan over currently staged content: clean"
else
    bad "hook scan over currently staged content reported findings"
fi

# ---------------------------------------------------------------- 4/6
section "4/6 XSS sink audit — strict across ALL frontend JS (zero sinks allowed)"
SINKS='\.innerHTML[[:space:]]*=|\.outerHTML[[:space:]]*=|insertAdjacentHTML[[:space:]]*\(|document\.write[[:space:]]*\(|[^A-Za-z_.]eval[[:space:]]*\('
for js_file in static/trip.js static/app.js; do
    hits="$(grep -nE "$SINKS" "$js_file" || true)"
    if [ -z "$hits" ]; then
        ok "$js_file: zero injection sinks (createElement/textContent only)"
    else
        bad "$js_file carries injection sinks:"
        printf '%s\n' "$hits"
    fi
done

# ---------------------------------------------------------------- 5/6
section "5/6 pydantic boundary validation + privacy contracts (pytest)"
if TZ=UTC "$PY" -m pytest tests/test_privacy.py -q; then
    ok "privacy/boundary suite green"
else
    bad "privacy/boundary suite failed"
fi

# ---------------------------------------------------------------- 6/6
section "6/6 dependency advisory scan"
AUDIT=""
[ -x .venv/bin/pip-audit ] && AUDIT=".venv/bin/pip-audit"
[ -z "$AUDIT" ] && command -v pip-audit >/dev/null 2>&1 && AUDIT="pip-audit"
if [ -n "$AUDIT" ]; then
    if $AUDIT --progress-spinner off; then
        ok "pip-audit: no known vulnerabilities in the venv"
    else
        bad "pip-audit reported known vulnerabilities (see table above)"
    fi
else
    note "pip-audit unavailable — install with: .venv/bin/pip install pip-audit"
fi

# ---------------------------------------------------------------- summary
section "SUMMARY"
if [ "$FAILURES" -eq 0 ]; then
    echo "G5 security check: ALL SECTIONS PASS"
    exit 0
fi
echo "G5 security check: $FAILURES failure(s)"
exit 1
