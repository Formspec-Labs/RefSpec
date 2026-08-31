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
#
# Two rules keep the closing success line honest, since a script built to
# distrust a successful-looking upload has no business printing an unearned
# success of its own: TARGET is resolved to a physical path before the
# containment check (see abspath), and an empty file selection is a refusal,
# not a zero-work "all files uploaded and verified".
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
  # HEAD would be cheaper but this Worker's HEAD path returns no body either
  # way; use a byte-range GET of just the first byte plus Content-Range to
  # confirm total size cheaply, without downloading the whole object. (An
  # earlier version of this check also did a full GET into /dev/null first
  # -- its http_code/size_download were never compared against anything, so
  # it wasn't buying any integrity property, just burning bandwidth on every
  # object before the real check below. Dropped.)
  local range_result
  range_result="$(curl -s -m 20 -H 'Range: bytes=0-0' -D - -o /dev/null "$WORKER_BASE/data/$key" 2>/dev/null || true)"
  local content_range
  content_range="$(echo "$range_result" | grep -i '^content-range:' | tr -d '\r' | sed -E 's#.*/([0-9]+)#\1#')"
  [[ "$content_range" == "$expected_size" ]]
}

upload_one() {
  local file="$1"
  local key="${file#"$SRC_DIR_ABS"/}"
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
export BUCKET RETRIES WORKER_BASE PUT_TIMEOUT

# Resolve a path to an absolute, PHYSICAL path with plain cd+pwd (no dependence
# on GNU coreutils' `realpath --relative-to`, which macOS's BSD realpath
# doesn't have). Needed below so upload_one's "${file#"$SRC_DIR_ABS"/}" key
# strip actually strips: an absolute or ./-prefixed TARGET (or SRC_DIR) left
# it matching nothing, producing keys like
# "refspec-atlas-explorer-data//Users/..." and burning retries re-uploading
# them.
#
# `cd "$p" && pwd -P` resolves every symlink in a directory path, but a path
# whose LAST component is a symlink never goes through cd at all -- the old
# version resolved only the parent and pasted the basename back on, so a
# symlink sitting under SRC_DIR and pointing anywhere on the filesystem
# answered the containment check below with its own location instead of its
# target's. The loop follows that last link (bounded, so a symlink cycle is a
# refusal rather than a hang) and hands back where the bytes actually are.
abspath() {
  local p="$1"
  local dir base target
  local hops=0
  if [[ -d "$p" ]]; then
    (cd "$p" && pwd -P)
    return
  fi
  [[ -e "$p" ]] || return 1
  dir="$(cd "$(dirname "$p")" && pwd -P)" || return 1
  base="$(basename "$p")"
  while [[ -L "$dir/$base" ]]; do
    hops=$((hops + 1))
    [[ "$hops" -le 40 ]] || return 1
    target="$(readlink "$dir/$base")" || return 1
    # One cd for the link's own directory, one for the target's -- which makes
    # an absolute target absolute and a relative one relative to the link.
    dir="$(cd "$dir" && cd "$(dirname "$target")" && pwd -P)" || return 1
    base="$(basename "$target")"
  done
  printf '%s/%s\n' "$dir" "$base"
}

SRC_DIR_ABS="$(abspath "$SRC_DIR")" || { echo "cannot resolve SRC_DIR ($SRC_DIR)" >&2; exit 1; }
export SRC_DIR_ABS

TARGET="${1:-$SRC_DIR}"
TARGET_ABS="$(abspath "$TARGET")" || { echo "TARGET ($TARGET) does not exist" >&2; exit 1; }
case "$TARGET_ABS" in
  "$SRC_DIR_ABS"|"$SRC_DIR_ABS"/*) ;;
  *)
    echo "TARGET ($TARGET) is not under SRC_DIR ($SRC_DIR) -- refusing to upload (R2 keys would not come out relative to SRC_DIR)" >&2
    exit 1
    ;;
esac

# Enumerate once, into a file, and refuse an empty selection. `find -type f`
# quietly selects nothing for a TARGET that is an empty directory, a directory
# holding only directories, or a symlink -- and uploading zero files then
# printed "all files uploaded and verified" and exited 0, which is the one
# report a script whose whole job is distrusting successful-looking uploads
# must never give. Zero files uploaded is never success.
file_list="$(mktemp)"
trap 'rm -f "$file_list"' EXIT
if ! find "$TARGET_ABS" -type f | sort >"$file_list"; then
  echo "upload-verified FAILED -- could not enumerate $TARGET_ABS" >&2
  exit 1
fi
total="$(wc -l <"$file_list" | tr -d ' ')"
if [[ "$total" -eq 0 ]]; then
  echo "upload-verified FAILED -- TARGET ($TARGET) holds no files, so there is nothing to upload or verify" >&2
  exit 1
fi

xargs -P "$PARALLEL" -I{} bash -c 'upload_one "$@"' _ {} <"$file_list"
status=$?

if [[ "$status" -eq 0 ]]; then
  echo "upload-verified complete -- all $total files uploaded and verified"
else
  echo "upload-verified FAILED -- one or more of $total files did not upload/verify (xargs exit $status)" >&2
fi
exit "$status"
