#!/usr/bin/env bash
# Dev server: builds the wasm, serves the site, and live-reloads the browser
# on any change to layout.html, pages/, assets/ or crates/.
#
# Served on the local network by default, so a phone on the same Wi-Fi can
# open it too (the URL is printed at start).
#
#   ./scripts/serve.sh            # http://<this machine's LAN address>:8080
#   ./scripts/serve.sh 3000       # pick another port
#   ./scripts/serve.sh --local    # this machine only (127.0.0.1)
#   ./scripts/serve.sh --open     # open a browser once it is up
#
# If the phone can't connect, the firewall is likely blocking the port:
#   sudo ufw allow from 192.168.0.0/16 to any port 8080 proto tcp
set -euo pipefail

cd "$(dirname "$0")/.."

PORT=8080
ADDRESS=0.0.0.0
ARGS=()
for arg in "$@"; do
  case "$arg" in
    [0-9]*)  PORT="$arg" ;;
    --local) ADDRESS=127.0.0.1 ;;
    *)       ARGS+=("$arg") ;;
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

if [ "$ADDRESS" = 0.0.0.0 ]; then
  # The address other devices on the network reach this machine at.
  LAN=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "src") print $(i + 1)}')
  echo "Serving on http://127.0.0.1:${PORT} and, on the local network, http://${LAN:-<this machine>}:${PORT}  (ctrl-c to stop)"
else
  echo "Serving on http://127.0.0.1:${PORT}  (this machine only; ctrl-c to stop)"
fi
exec trunk serve --address "$ADDRESS" --port "$PORT" "${ARGS[@]+"${ARGS[@]}"}"
