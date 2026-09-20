#!/usr/bin/env bash
#
# One-line installer. Fetches a checkout of taskcut and runs scripts/install.sh.
#
#   bash <(gh api repos/wasd96040501/taskcut/contents/scripts/bootstrap.sh \
#            -H "Accept: application/vnd.github.raw")
#
# Environment:
#   TASKCUT_REPO  owner/name of the repository   (default wasd96040501/taskcut)
#   TASKCUT_REF   branch, tag or commit          (default main)
#   TASKCUT_SRC   where the checkout is kept     (default ~/.claude/src/taskcut)

set -euo pipefail

REPO="${TASKCUT_REPO:-wasd96040501/taskcut}"
REF="${TASKCUT_REF:-main}"
SRC="${TASKCUT_SRC:-$HOME/.claude/src/taskcut}"

info() { printf '  %s\n' "$*"; }
fail() { printf 'error: %s\n' "$*" >&2; exit 1; }

echo "Bootstrapping taskcut from $REPO@$REF"

if [ -d "$SRC/.git" ]; then
  info "Updating $SRC"
  git -C "$SRC" fetch --quiet origin "$REF"
  git -C "$SRC" checkout --quiet FETCH_HEAD
else
  mkdir -p "$(dirname "$SRC")"
  rm -rf "${SRC:?}"
  # The repository is private, so the clone has to carry credentials. gh already
  # holds them; plain git works too when a credential helper is configured.
  if command -v gh >/dev/null 2>&1; then
    info "Cloning with gh"
    gh repo clone "$REPO" "$SRC" -- --quiet
  elif command -v git >/dev/null 2>&1; then
    info "Cloning with git"
    git clone --quiet "https://github.com/$REPO.git" "$SRC"
  else
    fail "neither gh nor git is on PATH"
  fi
  git -C "$SRC" checkout --quiet "$REF" 2>/dev/null || true
fi

info "Checked out $(git -C "$SRC" rev-parse --short HEAD)"
exec "$SRC/scripts/install.sh" "$@"
