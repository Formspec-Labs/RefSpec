#!/usr/bin/env bash
# Full-bucket audit: for every local file under precomputed/, confirm R2 has
# an object of the exact same size, checked via a byte-range GET against the
# live Worker (bypasses trusting any past upload log). Prints MISMATCH/MISSING
# for anything wrong; prints a final OK/PROBLEMS summary line.
#
# That OK line is a gate, so it is only printed when the audit actually ran
# over actual files. Two rules keep it honest, because both were broken:
#
#   * the file list is enumerated up front and refused when SRC_DIR is missing
#     or holds nothing -- a nonexistent SRC_DIR used to make `find` print its
#     own error and the script still report "OK (0 problems)" and exit 0.
#     Verifying zero files is a refusal, not a pass.
#   * the summary is gated on every enumerated file having actually reached a
#     verdict, counted independently of the MISSING/MISMATCH lines. A killed
#     worker, an aborted xargs or an unsizable local file used to leave silence
#     where a verdict belonged, and silence counted as a pass.
#   * a request that never got an answer is not an answer. A curl transport
#     failure (timeout, refused, DNS, TLS) and a non-definitive HTTP status
#     (5xx, 403, 429, a 200 that ignored the Range) both used to land in the
#     MISSING bucket, which asserts something about R2's contents that an
#     unanswered request cannot support -- one flaky minute, or a DNS blip
#     mid-deploy, and the audit reports the whole corpus as absent from a
#     bucket it never reached, at exit 1, alongside genuine misses. Only a
#     definitive 404/410 is MISSING; everything else that did not establish a
#     size goes to the ERROR channel, which already forces exit 2.
#
# Exit codes: 0 = verified, 1 = objects missing/wrong, 2 = the audit itself did
# not run to completion (nothing was proven either way).
set -uo pipefail
cd "$(dirname "$0")/.."

SRC_DIR="${SRC_DIR:-precomputed}"
WORKER_BASE="${WORKER_BASE:-https://refspec-atlas-explorer.hotgap.workers.dev}"
PARALLEL="${PARALLEL:-8}"

# Every invocation appends exactly one line to $VERDICT_LOG before it returns,
# whatever it decides, and the summary requires that count to match the number
# of files enumerated. That -- not xargs's exit status, which is 123 on GNU and
# 1 on the BSD xargs macOS ships for the very same situation, and which cannot
# distinguish "a file is missing from the bucket" from "the checker could not
# be run" -- is what proves the audit reached a verdict on every file instead
# of falling over part-way through a directory.
check_one() {
  local file="$1"
  local key="${file#"$SRC_DIR"/}"
  local expected result actual status verdict rc curl_rc

  expected="$(stat -f%z "$file" 2>/dev/null || stat -c%s "$file" 2>/dev/null)"
  if [[ -z "$expected" ]]; then
    # A local file we cannot size is a broken audit, not a verdict about R2:
    # with no expected size there is nothing to compare, and the comparison
    # below would report MISMATCH against an empty string -- inventing a
    # finding out of a stage failure. Its own ERROR channel is what lets the
    # summary tell "the bucket is wrong" from "the check never ran".
    verdict="ERROR $key (cannot read the local file's size)"
    rc=2
  else
    # No `|| true`: curl's own exit status is the difference between "the
    # bucket answered, and the answer was no" and "nothing answered". Both
    # used to arrive here as an empty $actual and both were called MISSING --
    # a definitive claim about R2's contents that a timed-out or refused
    # connection cannot support. A DNS failure during a deploy would have
    # reported the whole corpus as absent from a bucket it never reached.
    result="$(curl -s -m 20 -H 'Range: bytes=0-0' -D - -o /dev/null "$WORKER_BASE/data/$key" 2>/dev/null)"
    curl_rc=$?
    # Last status line wins, so a redirect chain is judged on where it landed.
    status="$(printf '%s\n' "$result" | awk 'toupper($1) ~ /^HTTP\// {code=$2} END {print code}')"
    actual="$(printf '%s\n' "$result" | grep -i '^content-range:' | tr -d '\r' | sed -E 's#.*/([0-9]+)#\1#')"
    if [[ "$curl_rc" -ne 0 ]]; then
      # 6 DNS, 7 refused, 28 timeout, 35/60 TLS, 52 empty reply, 56 recv error.
      verdict="ERROR $key (curl transport failure, exit $curl_rc -- the bucket was never reached)"
      rc=2
    elif [[ "$status" == "404" || "$status" == "410" ]]; then
      # The one status that is an answer about the object rather than about
      # the request: the Worker looked and there was nothing there.
      verdict="MISSING $key (expected $expected, HTTP $status)"
      rc=1
    elif [[ -z "$actual" ]]; then
      # 5xx, 403, 429, or a 200 that ignored the Range header: the request did
      # not fail at the transport, but nothing here establishes a size, so the
      # audit has no verdict about this object either way.
      verdict="ERROR $key (HTTP ${status:-none} with no Content-Range -- size not established)"
      rc=2
    elif [[ "$actual" != "$expected" ]]; then
      verdict="MISMATCH $key (expected $expected, got $actual)"
      rc=1
    else
      verdict=""
      rc=0
    fi
  fi

  [[ -n "$verdict" ]] && echo "$verdict"
  echo "$key" >>"$VERDICT_LOG"
  return "$rc"
}
export -f check_one
export SRC_DIR WORKER_BASE

if [[ ! -d "$SRC_DIR" ]]; then
  echo "verify-all: SRC_DIR ($SRC_DIR) does not exist -- nothing was verified" >&2
  exit 2
fi

# Stream MISSING/MISMATCH lines live (tee) while also keeping a copy to
# count from -- xargs's own exit code only says "something failed
# somewhere," not how many, and the header above promises an honest
# OK/PROBLEMS count, not just a pass/fail bit.
tmp_report="$(mktemp)"
file_list="$(mktemp)"
VERDICT_LOG="$(mktemp)"
export VERDICT_LOG
trap 'rm -f "$tmp_report" "$file_list" "$VERDICT_LOG"' EXIT

# Enumerate once, into a file, rather than piping `find` straight into xargs:
# the count check below and the checking run have to see the same list, and
# find's own failure has to be able to stop the script instead of arriving as
# an empty stream that looks exactly like a clean bucket.
if ! find "$SRC_DIR" -type f | sort >"$file_list"; then
  echo "verify-all: could not enumerate $SRC_DIR -- nothing was verified" >&2
  exit 2
fi

total="$(wc -l <"$file_list" | tr -d ' ')"
if [[ "$total" -eq 0 ]]; then
  echo "verify-all: $SRC_DIR holds no files -- refusing to call an empty audit OK" >&2
  exit 2
fi

xargs -P "$PARALLEL" -I{} bash -c 'check_one "$@"' _ {} <"$file_list" | tee "$tmp_report"
check_status="${PIPESTATUS[0]}"

problems="$(grep -c -E '^(MISSING|MISMATCH) ' "$tmp_report" || true)"
errors="$(grep -c -E '^ERROR ' "$tmp_report" || true)"
problems="${problems:-0}"
errors="${errors:-0}"

# The gate, in the order that matters: an audit that did not reach a verdict on
# every enumerated file proves nothing at all, so it is reported as FAILED
# rather than summarised -- an unreached file is silence, and silence used to
# read as OK here. A nonzero xargs status is only reported alongside, since a
# counted MISSING is itself a nonzero status and cannot be told apart from a
# crashed stage by that number alone.
checked="$(wc -l <"$VERDICT_LOG" | tr -d ' ')"
if [[ "$checked" -ne "$total" || "$errors" -gt 0 ]]; then
  echo "verify-all complete: INCOMPLETE -- $((total - checked)) of $total files were never" \
       "reached and $errors could not be answered for" \
       "($problems confirmed problems, xargs exit $check_status)." \
       "Nothing is proven about the files in those two counts." >&2
  exit 2
elif [[ "$problems" -eq 0 ]]; then
  echo "verify-all complete: OK ($total files, 0 problems)"
  exit 0
else
  echo "verify-all complete: PROBLEMS ($problems of $total)" >&2
  exit 1
fi
