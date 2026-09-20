#!/usr/bin/env bash
#
# Removes taskcut and the marketplace entry that provided it.
#
# Usage: ./scripts/uninstall.sh [--scope user|project|local]

set -euo pipefail

SCOPE="user"
while [ $# -gt 0 ]; do
  case "$1" in
    --scope) SCOPE="$2"; shift 2 ;;
    -h|--help) sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "uninstall.sh: unknown argument: $1" >&2; exit 2 ;;
  esac
done

claude plugin uninstall taskcut@taskcut --scope "$SCOPE" >/dev/null 2>&1 \
  && echo "Uninstalled taskcut ($SCOPE)" || echo "No taskcut install at $SCOPE scope"
claude plugin marketplace remove taskcut --scope "$SCOPE" >/dev/null 2>&1 \
  && echo "Removed the taskcut marketplace ($SCOPE)" || true

echo
echo "Ledgers are per session and are deleted when a session ends; any left by a"
echo "killed session are swept after a week. To clear them now:"
echo "  rm -f \"\${CLAUDE_CONFIG_DIR:-\$HOME/.claude}\"/plugins/store/taskcut*.json"
