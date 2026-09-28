# Qualify and promote a candidate

`precompute.py` freezes an inventory of everything it wrote and prints its
pin. The inventory is release-grade only when `--manifest-digest` supplied the
trusted search-view manifest pin; a self-hashed input yields a development
inventory, which publication verification refuses. Retain the printed
inventory pin with the trusted search-view manifest pin.

After running the existing vendor bundling step, freeze the complete output
inventory again. The previous inventory pin authenticates the input provenance;
this step verifies every previously inventoried byte before sealing the final
local output set, including bundled vendor files. Additions are allowed; modifying
or removing precomputed outputs is refused. Review and retain its newly printed pin before upload:

```sh
python build/publication_integrity.py freeze --root precomputed \
  --inventory-digest "$PRECOMPUTE_INVENTORY_DIGEST" \
  --search-view-digest "$SEARCH_VIEW_DIGEST"
```

Set `INVENTORY_DIGEST` to that final pin. Both `upload-verified.sh` and
`verify-all.sh` require it plus `SEARCH_VIEW_DIGEST`, `CLOUDFLARE_ACCOUNT_ID`,
`WORKER_VERSION`, `SOURCE_REVISION`, `PUBLICATION_RECEIPT` (outside the frozen
output directory), and the existing `WORKER_BASE`/`SRC_DIR` settings.
`PUBLICATION_PYTHON` can select the Python interpreter. Set account and Worker
version from the selected deployment, not from the inventory.

Uploads use `candidates/<inventory sha256>/<object path>`. Existing active root
keys are untouched. The scripts keep their range probes and then stream each
served object, including the inventory, once to compare its bytes. The Worker
adds `x-atlas-worker-version` from Cloudflare's version metadata binding; every
object must report the expected version. Missing or changed version headers,
same-size corruption, truncation, a different inventory or a different input pin
fail. HTTP 404/410 are missing objects; request failures and other HTTP failures
remain errors. Receipts identify both successful and failed comparisons and
explicitly say `promoted: false`.

Promotion is a separate authorized deployment action. After a candidate receipt
passes, configure the Worker's non-secret `DATA_CANDIDATE_PREFIX` variable to
`candidates/<verified inventory sha256>` in the selected Wrangler environment
and deploy that configuration. The Worker resolves existing `/data/<path>`
frontend URLs under that single candidate prefix. Explicit candidate URLs remain
available for verification. No copying over active object keys is needed.
Re-run `VERIFY_ACTIVE_DATA=1 build/verify-all.sh` with the **new** Worker version
and a separate receipt path. This explicitly probes the frontend’s active
`/data/<path>` URLs, rather than direct candidate URLs, using the same byte and
Worker-version checks. A good candidate served behind the wrong active selection
fails this check. Retain the active verification receipt,
then check search, resource detail, agencies and range reads on the public UI.
Roll back by selecting a previously verified prefix in a new deployment.
Candidate verification remains the default. Successful active verification
records `activeSelectionVerified: true`; neither mode deploys, promotes, or claims
those UI checks ran. Direct CLI callers can use `verify-public --active`.
