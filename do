#!/usr/bin/env bash
# Local-dev wrapper for the demo template. Replace name + commands as your
# demo grows; the platform only requires that production `uvicorn src.app:app`
# can be started and that `frontend/out/` exists for static export.
#
#   ./do install                  uv sync + npm install (one-time after bootstrap)
#   ./do dev                      run backend (uvicorn) + frontend (next dev)
#   ./do build                    build the frontend static export (frontend/out/)
#   ./do backend                  run backend only (foreground; matches production shape)
#   ./do test                     run pytest unit tests (tests/)
#   ./do test-book                run booktest snapshot tests (book/, via booktest CLI)
#   ./do screenshot-teaser        render assets/teaser.html → assets/teaser.png (1200×630)
#   ./do product-sheet            compile docs/product-sheet/product-sheet.typ → PDF (needs typst)
#   ./do screenshot-pages [...]   desktop full-page screenshots of given paths
#   ./do inspect-mobile [...]     iPhone-sized screenshots of given paths
#   ./do clean                    wipe build artifacts

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

# Local-dev ports, chosen in the 4100+ range to avoid common local conflicts
# (3000 = many node apps, 8000/8401 = other services, 4000/4001 in local use).
# UI on 4100, backend 4101.
FRONTEND_PORT="${FRONTEND_PORT:-4100}"
BACKEND_PORT="${BACKEND_PORT:-4101}"

die() { echo "✗ $*" >&2; exit 1; }
say() { echo "→ $*"; }

cmd_install() {
  command -v uv >/dev/null 2>&1 || die "uv not found (see https://docs.astral.sh/uv/)"
  command -v npm >/dev/null 2>&1 || die "npm not found"
  say "uv sync"
  uv sync
  say "npm install (frontend)"
  ( cd frontend && npm install --no-audit --no-fund )
}

cmd_build() {
  ( cd frontend && NODE_ENV=production npx next build )
  say "frontend/out/ ready ($(find frontend/out -type f | wc -l) files)"
}

cmd_backend() {
  exec uv run uvicorn src.app:app --host 0.0.0.0 --port "$BACKEND_PORT" --reload
}

cmd_dev() {
  [ -d frontend/node_modules ] || cmd_install
  say "backend → http://localhost:${BACKEND_PORT} (uvicorn, hot-reload)"
  say "frontend → http://localhost:${FRONTEND_PORT} (next dev, proxies /api/* → backend)"
  ( BACKEND_PORT="$BACKEND_PORT" uv run uvicorn src.app:app --host 127.0.0.1 --port "$BACKEND_PORT" --reload ) &
  BACK=$!
  trap 'kill $BACK 2>/dev/null || true' EXIT INT TERM
  ( cd frontend && BACKEND_PORT="$BACKEND_PORT" npx next dev -p "$FRONTEND_PORT" )
}

cmd_test() {
  # plain pytest unit tests live under tests/ (book/ is booktest — see test-book)
  exec uv run pytest tests/ "$@"
}

cmd_test_book() {
  # booktest snapshot tests live under book/ and run via the booktest CLI
  # (NOT pytest — booktest supplies the `t` test-case fixture itself).
  # @bt.snapshot_httpx() records httpx interactions on first capture, replays after.
  #   ./do test-book              run / replay all book tests (no live calls)
  #   ./do test-book -s -a        first capture / re-record (hits live Aito; accepts new output)
  #   ./do test-book -u <sel>     accept updated output on success for a selector
  exec uv run booktest "${@:-book}"
}

cmd_screenshot_teaser() {
  [ -d frontend/node_modules ] || cmd_install
  ( cd frontend && node scripts/screenshot-teaser.cjs )
}

cmd_screenshot_pages() {
  [ -d frontend/node_modules ] || cmd_install
  ( cd frontend && node scripts/screenshot-pages.cjs "$@" )
}

cmd_inspect_mobile() {
  [ -d frontend/node_modules ] || cmd_install
  ( cd frontend && node scripts/inspect-mobile.cjs "$@" )
}

cmd_product_sheet() {
  # Compile docs/product-sheet/product-sheet.typ → PDF. Needs typst (typst.app);
  # on a nix box: `nix-shell -p typst --run '...'` works without installing.
  local typ=docs/product-sheet/product-sheet.typ out=docs/product-sheet/product-sheet.pdf
  [ -f "$typ" ] || die "missing $typ"
  if [ ! -f docs/product-sheet/shots/home.png ]; then
    say "shots/ missing — run ./do backend (or dev) then:"
    say "  node frontend/scripts/screenshot-pages.cjs  # or re-capture into docs/product-sheet/shots/"
  fi
  if command -v typst >/dev/null 2>&1; then
    typst compile --root . "$typ" "$out"
  elif command -v nix-shell >/dev/null 2>&1; then
    nix-shell -p typst --run "typst compile --root . $typ $out"
  else
    die "typst not found — install from typst.app or 'nix-shell -p typst'"
  fi
  say "wrote $out"
}

cmd_clean() {
  rm -rf frontend/.next frontend/out .pytest_cache frontend/scripts/output/*
  find . -type d -name __pycache__ -prune -exec rm -rf {} +
  say "cleaned"
}

cmd_help() { sed -n '1,20p' "$0" | sed -n '/^#/p'; }

case "${1:-help}" in
  install)             shift; cmd_install "$@" ;;
  dev)                 shift; cmd_dev "$@" ;;
  build)               shift; cmd_build "$@" ;;
  backend)             shift; cmd_backend "$@" ;;
  test)                shift; cmd_test "$@" ;;
  test-book)           shift; cmd_test_book "$@" ;;
  screenshot-teaser)   shift; cmd_screenshot_teaser "$@" ;;
  product-sheet)       shift; cmd_product_sheet "$@" ;;
  screenshot-pages)    shift; cmd_screenshot_pages "$@" ;;
  inspect-mobile)      shift; cmd_inspect_mobile "$@" ;;
  clean)               shift; cmd_clean "$@" ;;
  help|-h|--help)      cmd_help ;;
  *) die "unknown command: $1 (run './do help')" ;;
esac
