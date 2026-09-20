#!/usr/bin/env bash
#
# Runs every check this project has: manifest shape, hooks module scan, and the
# TypeScript build when the generated declarations are present.
#
# Usage: ./scripts/validate.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

status=0
step() { printf '\n== %s\n' "$*"; }

step "JSON manifests"
for file in .claude-plugin/plugin.json hooks/hooks.json; do
  if python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$file"; then
    echo "  ok  $file"
  else
    echo "  BAD $file"; status=1
  fi
done

step "Declared modules exist"
python3 - <<'PY' || status=1
import json, os, sys
manifest = json.load(open("hooks/hooks.json"))
missing = [m for m in manifest.get("modules", [])
           if not os.path.exists(os.path.join("hooks", m))]
for m in missing:
    print(f"  BAD hooks/{m} is declared but absent")
if not missing:
    print("  ok  every declared module is present")
sys.exit(1 if missing else 0)
PY

step "Claude Code plugin validation"
if command -v claude >/dev/null 2>&1; then
  CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1 claude plugin validate . || status=1
else
  echo "  skipped: claude is not on PATH"
fi

step "TypeScript"
if [ ! -f .claude/types/claude-code.d.ts ]; then
  echo "  skipped: no .claude/types/claude-code.d.ts"
  echo "           generate it by running /plugin-types inside a session"
elif command -v tsc >/dev/null 2>&1; then
  tsc -p tsconfig.json && echo "  ok  tsc clean" || status=1
elif command -v npx >/dev/null 2>&1; then
  npx --yes -p typescript tsc -p tsconfig.json && echo "  ok  tsc clean" || status=1
else
  echo "  skipped: no tsc and no npx"
fi

printf '\n'
if [ "$status" -eq 0 ]; then echo "All checks passed."; else echo "Checks failed." >&2; fi
exit "$status"
