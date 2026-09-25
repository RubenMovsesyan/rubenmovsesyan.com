#!/usr/bin/env bash
# Production build into dist/ — optimised wasm, hashed filenames.
set -euo pipefail
cd "$(dirname "$0")/.."
trunk build --release "$@"
echo "Built into $(pwd)/dist"
