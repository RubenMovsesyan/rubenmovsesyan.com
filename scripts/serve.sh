#!/usr/bin/env bash
# Dev server: builds the wasm, serves the site, and live-reloads the browser
# on any change to index.html, assets/ or src/.
#
#   ./scripts/serve.sh            # http://127.0.0.1:8080
#   ./scripts/serve.sh 3000       # pick another port
#   ./scripts/serve.sh --open     # open a browser once it is up
set -euo pipefail

cd "$(dirname "$0")/.."

PORT=8080
ARGS=()
for arg in "$@"; do
  case "$arg" in
    [0-9]*) PORT="$arg" ;;
    *)      ARGS+=("$arg") ;;
  esac
done

command -v trunk >/dev/null || {
  echo "trunk not found. Install it with: cargo install --locked trunk" >&2
  exit 1
}

rustup target list --installed | grep -qx wasm32-unknown-unknown || {
  echo "Adding the wasm32-unknown-unknown target…"
  rustup target add wasm32-unknown-unknown
}

# Trunk.toml ignores these, and trunk refuses to start if an ignored path is
# missing -- which they are in a fresh checkout.
mkdir -p target dist

echo "Serving on http://127.0.0.1:${PORT}  (ctrl-c to stop)"
exec trunk serve --port "$PORT" "${ARGS[@]+"${ARGS[@]}"}"
