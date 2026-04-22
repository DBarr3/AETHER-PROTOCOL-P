#!/usr/bin/env bash
# Lint: OTel span/event attribute payloads must not carry PII.
#
# Checks site/lib/router/ and site/app/api/internal/ for forbidden keys
# that appear inside setAttributes / addEvent / recordException calls.
# Forbidden: prompt, message, email, ip, content, user_prompt, body, token.
#
# Exit 0 on clean. Exit 1 with a report on violation.
#
# Run:
#   bash tests/lint/no_pii_in_otel.sh

set -u

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TS_DIRS=("$ROOT/site/lib/router" "$ROOT/site/app/api/internal" "$ROOT/site/middleware.ts")
FORBIDDEN='\b(prompt|message|email|user_prompt|body|ip_address|content|token_value)\b'

violations=0

for target in "${TS_DIRS[@]}"; do
  if [ ! -e "$target" ]; then continue; fi
  # Find setAttributes / addEvent / recordException / attributes={ contexts
  # and flag if a forbidden key appears anywhere in the surrounding 6 lines.
  matches=$(grep -rEn \
    -A 6 -B 0 \
    '(setAttributes|addEvent|recordException|attributes\s*[:=]\s*\{)' \
    "$target" 2>/dev/null \
    | grep -iE "$FORBIDDEN" \
    | grep -v '^\s*//' \
    | grep -v '/\*' \
    || true)

  if [ -n "$matches" ]; then
    echo "PII-in-OTel violation in $target:"
    echo "$matches"
    violations=$((violations + 1))
  fi
done

if [ "$violations" -gt 0 ]; then
  echo ""
  echo "FAIL: $violations PII-in-OTel violation(s) found."
  echo "See diagrams/docs_router_architecture.md § PII rules (spec §5.3)."
  exit 1
fi

echo "PASS: no PII in OTel attribute payloads."
exit 0
