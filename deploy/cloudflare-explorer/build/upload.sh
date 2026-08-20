#!/usr/bin/env bash
# Upload deploy/cloudflare-explorer/precomputed/* to the R2 bucket, key-for-
# key (precomputed/tables/resources.parquet -> R2 key tables/resources.parquet).
#
# Every artifact here is under R2's 5GiB single-part PUT limit, but more
# importantly under `wrangler r2 object put`'s own, much lower ceiling:
# "Wrangler only supports uploading files up to 300 MiB in size" (this is
# a wrangler-CLI limitation, not an R2 API one -- confirmed empirically:
# every shard above 300MiB failed outright, which is why
# build/precompute.py shards the resource-detail bodies to ~250MB each).
# No multipart upload needed as a result. Uploads run with modest
# parallelism (default 6) since there are a few hundred objects; each
# `wrangler` invocation has real process-startup overhead, so serial
# upload would waste minutes on that alone.
#
# Safe to re-run: it always overwrites, which is exactly what you want
# after generating a new precomputed/ from an updated search view.
set -euo pipefail

cd "$(dirname "$0")/.."

BUCKET="${BUCKET:-refspec-atlas-explorer-data}"
SRC_DIR="${SRC_DIR:-precomputed}"
PARALLEL="${PARALLEL:-6}"

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

upload_one() {
  local file="$1"
  local key="${file#"$SRC_DIR"/}"
  local ct
  ct="$(content_type_for "$file")"
  echo "uploading $key ($(du -h "$file" | cut -f1))"
  npx wrangler r2 object put "$BUCKET/$key" \
    --file "$file" \
    --content-type "$ct" \
    --cache-control "public, max-age=300, must-revalidate" \
    --remote -y >/tmp/r2-upload-"$(echo "$key" | tr '/' '_')".log 2>&1 \
    || { echo "FAILED $key"; cat /tmp/r2-upload-"$(echo "$key" | tr '/' '_')".log; return 1; }
  echo "done $key"
}
export -f upload_one content_type_for
export BUCKET SRC_DIR

find "$SRC_DIR" -type f | sort | xargs -P "$PARALLEL" -I{} bash -c 'upload_one "$@"' _ {}

echo "upload complete: $(find "$SRC_DIR" -type f | wc -l | tr -d ' ') objects"
