#!/usr/bin/env bash
# Mechanical checks of the anti-bloat contract for <slug>-pr.md (PR_GUIDELINES.md).
# Judgment checks (scope discipline, substantive bullets) stay with the agent — this
# script only decides what a regex can decide.
#
# Usage: ./lint-pr-description.sh <slug>-pr.md
# Exit codes: 0 = all mechanical checks pass; 1 = at least one FAIL; 2 = usage error.

set -uo pipefail

profile_value() {
  local key="$1" file value="" found
  for file in .claude/harness/profile.yaml .claude/harness/profile.local.yaml; do
    [ -f "$file" ] || continue
    found="$(sed -n "s/^${key}: *//p" "$file" | head -n1 | sed -e 's/^["'\'']//' -e 's/["'\'']$//')"
    [ -n "$found" ] && value="$found"
  done
  printf '%s' "$value"
}
TICKET_SYSTEM="$(profile_value ticket_system)"

FILE="${1:-}"
[ -n "$FILE" ] && [ -f "$FILE" ] || { echo "usage: $0 <slug>-pr.md" >&2; exit 2; }

fail=0
say() { printf '%-4s %s\n' "$1" "$2"; if [ "$1" = "FAIL" ]; then fail=1; fi; return 0; }

first_section="$(grep -m1 '^## ' "$FILE" || true)"
if [ "$first_section" = "## ⚡ TL;DR" ]; then say PASS "TL;DR is the first section"; else say FAIL "first section is '$first_section', expected '## ⚡ TL;DR'"; fi

tldr_words="$(awk '/^## ⚡ TL;DR/{f=1;next} /^## /{f=0} f' "$FILE" | wc -w)"
if [ "$tldr_words" -le 80 ] && [ "$tldr_words" -gt 0 ]; then say PASS "TL;DR has $tldr_words words (≤80)"; else say FAIL "TL;DR has $tldr_words words (must be 1-80)"; fi

lines="$(wc -l < "$FILE")"
if [ "$lines" -ge 40 ] && [ "$lines" -le 100 ]; then say PASS "$lines lines (40-100)"; else say FAIL "$lines lines (target 40-80, hard ceiling 100, floor 40)"; fi

if grep -q '^## 🎯 Decisões para o reviewer validar' "$FILE"; then say PASS "Decisões section present"; else say FAIL "missing '## 🎯 Decisões para o reviewer validar'"; fi

decision_bullets="$(awk '/^## 🎯/{f=1;next} /^## /{f=0} f && /^- /' "$FILE" | wc -l)"
if [ "$decision_bullets" -ge 2 ] && [ "$decision_bullets" -le 4 ]; then say PASS "Decisões has $decision_bullets bullets (2-4)"; else say FAIL "Decisões has $decision_bullets bullets (expected 2-4)"; fi

passos="$(grep -c '^- \*\*Passo' "$FILE" || true)"
if [ "$passos" -le 5 ]; then say PASS "QA roteiro has $passos passos (≤5)"; else say FAIL "QA roteiro has $passos passos (max 5)"; fi

if grep -q '^## ⚠️ Riscos e impactos' "$FILE"; then say PASS "Riscos section present"; else say FAIL "missing '## ⚠️ Riscos e impactos' (required even when 'nenhum')"; fi

if grep -qE 'https?://' "$FILE"; then say PASS "at least one external link"; else say FAIL "no external link in the body"; fi

if grep -qiE 'árvore de arquitetura|^### Arquitetura|Sem dependências novas|^\| *Arquivo' "$FILE"; then say FAIL "file-inventory/filler content detected"; else say PASS "no file-inventory filler detected"; fi

if grep -q '^## 🏷️ Ticket' "$FILE"; then
  ticket="$(awk '/^## 🏷️ Ticket/{f=1;next} /^## /{f=0} f' "$FILE")"
  if [ "$TICKET_SYSTEM" = "notion" ]; then ticket_url='https?://[^)]*notion\.(so|com)/'; else ticket_url='https?://[^)]*'; fi
  if printf '%s' "$ticket" | grep -qE "\\[([^]\\\\]|\\\\.)+\\]\\(${ticket_url}"; then say PASS "Ticket section links the ticket"; else say FAIL "Ticket section without a [KEY — name](ticket url) link"; fi
  if [ "$(grep -m1 -n '^## ' <(tac "$FILE") | cut -d: -f2-)" = "## 🏷️ Ticket" ]; then say PASS "Ticket is the last section"; else say FAIL "Ticket must be the last section"; fi
fi

if grep -q '^## 🚀 Pós-deploy' "$FILE"; then
  if awk '/^## 🚀 Pós-deploy/{f=1;next} /^## /{f=0} f' "$FILE" | grep -qE '<[a-zA-Z]|\{\{'; then say FAIL "Pós-deploy contains placeholder-looking commands"; else say PASS "Pós-deploy present with concrete commands"; fi
fi

exit $fail
