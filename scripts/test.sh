#!/usr/bin/env bash
#
# Runs the unit tests for the pure modules.
#
# Node 22.18 or newer runs the TypeScript sources directly, so there is nothing
# to install and no build step. The hooks themselves are exercised by
# scripts/validate.sh and by running the plugin in a real session; what is tested
# here is the logic those hooks delegate to.
#
# Usage: ./scripts/test.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

command -v node >/dev/null 2>&1 || { echo "error: node is not on PATH" >&2; exit 1; }
exec node --test "test/**/*.test.ts"
