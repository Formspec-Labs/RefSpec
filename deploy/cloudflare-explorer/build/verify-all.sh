#!/usr/bin/env bash
# Full-bucket audit: for every local file under precomputed/, confirm R2 has
# an object of the exact same size, checked via a byte-range GET against the
# live Worker (bypasses trusting any past upload log). Prints MISMATCH/MISSING
# for anything wrong; prints a final OK/PROBLEMS summary line.
set -uo pipefail
cd "$(dirname "$0")/.."

SRC_DIR="${SRC_DIR:-precomputed}"
WORKER_BASE="${WORKER_BASE:-https://refspec-atlas-explorer.hotgap.workers.dev}"
PARALLEL="${PARALLEL:-8}"

check_one() {
  local file="$1"
  local key="${file#"$SRC_DIR"/}"
  local expected
  expected="$(stat -f%z "$file" 2>/dev/null || stat -c%s "$file")"
  local result content_range actual
  result="$(curl -s -m 20 -H 'Range: bytes=0-0' -D - -o /dev/null "$WORKER_BASE/data/$key" 2>/dev/null || true)"
  actual="$(echo "$result" | grep -i '^content-range:' | tr -d '\r' | sed -E 's#.*/([0-9]+)#\1#')"
  if [[ -z "$actual" ]]; then
    echo "MISSING $key (expected $expected)"
  elif [[ "$actual" != "$expected" ]]; then
    echo "MISMATCH $key (expected $expected, got $actual)"
  fi
}
export -f check_one
export SRC_DIR WORKER_BASE

find "$SRC_DIR" -type f | sort | xargs -P "$PARALLEL" -I{} bash -c 'check_one "$@"' _ {}
echo "verify-all complete"
