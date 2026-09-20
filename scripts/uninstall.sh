#!/usr/bin/env bash
#
# Removes taskcut from the Claude Code skills directory.
#
# Usage: ./scripts/uninstall.sh [--dir <claude-config-dir>]

set -euo pipefail

CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"

while [ $# -gt 0 ]; do
  case "$1" in
    --dir) CLAUDE_DIR="$2"; shift 2 ;;
    -h|--help) sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "uninstall.sh: unknown argument: $1" >&2; exit 2 ;;
  esac
done

TARGET="$CLAUDE_DIR/skills/taskcut"

if [ -d "$TARGET" ]; then
  rm -rf "${TARGET:?}"
  echo "Removed $TARGET"
else
  echo "Nothing to remove at $TARGET"
fi

echo "Ledgers are stored per session and are deleted when a session ends."
echo "To clear any left behind: $CLAUDE_DIR/plugins/store/taskcut*.json"
