#!/usr/bin/env bash
#
# Installs taskcut through Claude Code's own plugin mechanism, from a checkout.
#
# For a repository you can reach by name, prefer the two native commands and
# skip this script entirely:
#
#   claude plugin marketplace add wasd96040501/taskcut
#   claude plugin install taskcut@taskcut --scope project
#
# This script is for a private or air-gapped checkout, where the marketplace has
# to be added from a local path.
#
# Usage: ./scripts/install.sh [--scope user|project|local] [--everywhere]
#
#   --scope       Where to record the install. Default: user.
#   --everywhere  Set activation to "always", so taskcut runs in every session
#                 rather than only where a .taskcut marker or TASKCUT=1 says so.

set -euo pipefail

REQUIRED_VERSION="2.1.278"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCOPE="user"
ACTIVATION="opt-in"

while [ $# -gt 0 ]; do
  case "$1" in
    --scope) SCOPE="$2"; shift 2 ;;
    --everywhere) ACTIVATION="always"; shift ;;
    -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "install.sh: unknown argument: $1" >&2; exit 2 ;;
  esac
done

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
version_at_least "$VERSION" "$REQUIRED_VERSION" \
  || fail "Claude Code $VERSION is older than the required $REQUIRED_VERSION. Run: claude update"
info "Claude Code $VERSION"

[ -f "$REPO_ROOT/.claude-plugin/marketplace.json" ] || fail "run this from a taskcut checkout"

claude plugin validate "$REPO_ROOT" >/dev/null || fail "validation failed; nothing will load"
info "Validated"

claude plugin marketplace remove taskcut --scope "$SCOPE" >/dev/null 2>&1 || true
claude plugin marketplace add "$REPO_ROOT" --scope "$SCOPE" >/dev/null
info "Marketplace added from $REPO_ROOT ($SCOPE)"

claude plugin uninstall taskcut@taskcut --scope "$SCOPE" >/dev/null 2>&1 || true
claude plugin install taskcut@taskcut --scope "$SCOPE" --config "activation=$ACTIVATION" >/dev/null
info "Installed ($SCOPE), activation=$ACTIVATION"

cat <<NEXT

Done.

taskcut is inert until a session opts in. In a repository where you want it:

    touch .taskcut        # commit it, and the repository carries the decision

or, for one session only:

    TASKCUT=1 claude

TASKCUT=0 switches it off wherever it would otherwise run.

Settings live under /config, or: claude plugin install ... --config KEY=VALUE
NEXT
