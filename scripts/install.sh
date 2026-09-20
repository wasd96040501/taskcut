#!/usr/bin/env bash
#
# Installs taskcut into the Claude Code skills directory, where it is loaded
# automatically from the next session on.
#
# Usage: ./scripts/install.sh [--dir <claude-config-dir>]

set -euo pipefail

REQUIRED_VERSION="2.1.278"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"

while [ $# -gt 0 ]; do
  case "$1" in
    --dir) CLAUDE_DIR="$2"; shift 2 ;;
    -h|--help) sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "install.sh: unknown argument: $1" >&2; exit 2 ;;
  esac
done

TARGET="$CLAUDE_DIR/skills/taskcut"

info() { printf '  %s\n' "$*"; }
fail() { printf 'error: %s\n' "$*" >&2; exit 1; }

# A pure-shell version compare, so this does not depend on sort -V being present.
version_at_least() {
  local have="$1" want="$2" i h w
  local -a have_parts want_parts
  IFS='.' read -r -a have_parts <<<"${have%%[^0-9.]*}"
  IFS='.' read -r -a want_parts <<<"$want"
  for i in 0 1 2; do
    h="${have_parts[i]:-0}"; w="${want_parts[i]:-0}"
    if [ "$h" -gt "$w" ]; then return 0; fi
    if [ "$h" -lt "$w" ]; then return 1; fi
  done
  return 0
}

echo "Installing taskcut"

command -v claude >/dev/null 2>&1 || fail "claude is not on PATH. See https://claude.com/claude-code"

VERSION="$(claude --version 2>/dev/null | awk '{print $1}')"
if version_at_least "$VERSION" "$REQUIRED_VERSION"; then
  info "Claude Code $VERSION"
else
  fail "Claude Code $VERSION is older than the required $REQUIRED_VERSION. Run: claude update"
fi

[ -f "$REPO_ROOT/.claude-plugin/plugin.json" ] || fail "run this from a taskcut checkout"

mkdir -p "$TARGET"
rm -rf "${TARGET:?}/.claude-plugin" "${TARGET:?}/hooks"
cp -R "$REPO_ROOT/.claude-plugin" "$REPO_ROOT/hooks" "$TARGET/"
info "Installed to $TARGET"

if CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1 claude plugin validate "$TARGET" >/tmp/taskcut-validate.$$ 2>&1; then
  info "Validated"
else
  cat /tmp/taskcut-validate.$$ >&2
  rm -f /tmp/taskcut-validate.$$
  fail "validation failed; nothing will load"
fi
rm -f /tmp/taskcut-validate.$$

cat <<'NEXT'

Done. Two things remain:

  1. Function hooks are early access and off by default. Enable them:

       export CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1

     Add that line to your shell profile to make it permanent.

  2. Start a new session. taskcut loads as taskcut@skills-dir; confirm with:

       claude plugin list | grep -A3 taskcut

Compaction needs an interactive session: a terminal, or claude --bg. It is
unavailable under claude -p and the stream-json SDK transport.

Settings live under /config, in the taskcut section.
NEXT
