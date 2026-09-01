#!/usr/bin/env bash
# Build the standalone Linux TUI binary (OpenTUI + Bun compile) and leave it
# at tui/dist/quiver-tui. Reinstalling the Python tool afterwards bundles it:
#   scripts/build-tui.sh && uv tool install . --reinstall --force
set -euo pipefail

cd "$(dirname "$0")/../tui"

if ! command -v bun >/dev/null 2>&1; then
  echo "error: Bun >= 1.3 is required to build the TUI" >&2
  echo "  install: curl -fsSL https://bun.sh/install | bash" >&2
  exit 1
fi

bun install
bun run scripts/build.ts
ls -lh dist/quiver-tui
