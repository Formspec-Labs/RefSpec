#!/usr/bin/env bash
# Sourced after each caller preserves its own input/path guards.
# Release publication only writes content-addressed candidates. The caller pins
# the frozen inventory and records the exact deployment that serves the check.
PYTHON="${PUBLICATION_PYTHON:-python3}"
INTEGRITY_HELPER="$PWD/build/publication_integrity.py"
for required in INVENTORY_DIGEST SEARCH_VIEW_DIGEST CLOUDFLARE_ACCOUNT_ID WORKER_VERSION SOURCE_REVISION PUBLICATION_RECEIPT; do
  if [[ -z "${!required:-}" ]]; then
    echo "ERROR publication requires $required" >&2
    exit 2
  fi
done
CANDIDATE_PREFIX="candidates/${INVENTORY_DIGEST#sha256:}"
"$PYTHON" "$INTEGRITY_HELPER" check-local --root "$SRC_DIR" \
  --inventory-digest "$INVENTORY_DIGEST" --search-view-digest "$SEARCH_VIEW_DIGEST" || exit 2
export PYTHON INTEGRITY_HELPER INVENTORY_DIGEST SEARCH_VIEW_DIGEST CANDIDATE_PREFIX

verify_publication() {
  "$PYTHON" "$INTEGRITY_HELPER" verify-public --root "$SRC_DIR" \
    --inventory-digest "$INVENTORY_DIGEST" --search-view-digest "$SEARCH_VIEW_DIGEST" \
    --base "$WORKER_BASE" --account-id "$CLOUDFLARE_ACCOUNT_ID" \
    --worker-version "$WORKER_VERSION" --source-revision "$SOURCE_REVISION" \
    --receipt "$PUBLICATION_RECEIPT" "$@"
}
