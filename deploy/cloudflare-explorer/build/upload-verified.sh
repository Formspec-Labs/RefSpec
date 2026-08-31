#!/usr/bin/env bash
# Robust variant of upload.sh for unreliable network conditions: uploads
# each file, then verifies it actually landed in R2 by HEAD-checking the
# live Worker and comparing Content-Length against the local file size --
# `wrangler r2 object put` was observed to exit 0 and log "Upload complete"
# for objects that did not actually exist afterward (confirmed via direct
# HEAD checks against the deployed Worker), which plain upload.sh has no
# way to catch. Retries a few times with a short backoff before giving up
# on a file. Lower default parallelism than upload.sh -- degraded/high
# -latency networks do better with less contention, not more.
set -uo pipefail

cd "$(dirname "$0")/.."

BUCKET="${BUCKET:-refspec-atlas-explorer-data}"
SRC_DIR="${SRC_DIR:-precomputed}"
PARALLEL="${PARALLEL:-2}"
RETRIES="${RETRIES:-4}"
WORKER_BASE="${WORKER_BASE:-https://refspec-atlas-explorer.hotgap.workers.dev}"
# Hard per-attempt cap so a stalled TCP connection (observed: wrangler stuck
# at 0% CPU for 30+ minutes with no error, no progress) can't block a whole
# upload run. A genuine PUT of a small shard finishes in well under this.
PUT_TIMEOUT="${PUT_TIMEOUT:-90}"

if [[ ! -d "$SRC_DIR" ]]; then
  echo "missing $SRC_DIR -- run build/precompute.py first" >&2
  exit 1
fi

content_type_for() {
  case "$1" in
    *.json) echo "application/json" ;;
    *.ndjson) echo "application/x-ndjson; charset=utf-8" ;;
    *.parquet) echo "application/vnd.apache.parquet" ;;
    *.mjs) echo "text/javascript" ;;
    *.js) echo "text/javascript" ;;
    *.wasm) echo "application/wasm" ;;
    *) echo "application/octet-stream" ;;
  esac
}

verify_one() {
  local key="$1" expected_size="$2"
  local actual
  actual="$(curl -s -o /dev/null -m 20 -w '%{http_code} %{size_download}' "$WORKER_BASE/data/$key" 2>/dev/null || true)"
  # HEAD would be cheaper but this Worker's HEAD path returns no body either
  # way; use a byte-range GET of just the first byte plus Content-Range to
  # confirm total size cheaply instead of re-downloading the whole object.
  local range_result
  range_result="$(curl -s -m 20 -H 'Range: bytes=0-0' -D - -o /dev/null "$WORKER_BASE/data/$key" 2>/dev/null || true)"
  local content_range
  content_range="$(echo "$range_result" | grep -i '^content-range:' | tr -d '\r' | sed -E 's#.*/([0-9]+)#\1#')"
  [[ "$content_range" == "$expected_size" ]]
}

upload_one() {
  local file="$1"
  local key="${file#"$SRC_DIR"/}"
  local ct expected_size attempt
  ct="$(content_type_for "$file")"
  expected_size="$(stat -f%z "$file" 2>/dev/null || stat -c%s "$file")"
  local logfile="/tmp/r2-upload-$(echo "$key" | tr '/' '_').log"

  for attempt in $(seq 1 "$RETRIES"); do
    echo "uploading $key attempt $attempt/$RETRIES ($(du -h "$file" | cut -f1))"
    if timeout "$PUT_TIMEOUT" npx wrangler r2 object put "$BUCKET/$key" \
        --file "$file" \
        --content-type "$ct" \
        --cache-control "public, max-age=300, must-revalidate" \
        --remote -y >"$logfile" 2>&1; then
      if verify_one "$key" "$expected_size"; then
        echo "verified $key"
        return 0
      else
        echo "unverified $key (wrangler exited 0 but object size didn't match after upload) -- retrying"
      fi
    else
      echo "put-failed $key -- retrying"
    fi
    sleep $((attempt * 3))
  done
  echo "FAILED $key (exhausted $RETRIES attempts)"
  tail -20 "$logfile"
  return 1
}
export -f upload_one verify_one content_type_for
export BUCKET SRC_DIR RETRIES WORKER_BASE PUT_TIMEOUT

TARGET="${1:-$SRC_DIR}"
find "$TARGET" -type f | sort | xargs -P "$PARALLEL" -I{} bash -c 'upload_one "$@"' _ {}

echo "upload-verified complete"
