# Retain a pinned BILLSTATUS guide

`refspec.registry.billstatus_codes.acquire_billstatus_source` accepts an exact
local capture or an explicitly injected fetcher. A cache hit requires neither.
It does not fetch automatically. The maintained Atlas builder supplies the
checked-in guide fixture.

RefSpec reads at most the pinned byte length plus one byte from local/cache
files, then checks exact length, SHA-256 digest and UTF-8 text. An oversized
file's error reports the bounded observed length, not its unread total size.
For injected responses it also checks HTTP 200, the official HTTPS host and a
plain-text or Markdown media type. It preserves the fetcher's original media
type and final URL. Guide structure and code-set acceptance are checked later
by `parse_billstatus_code_sets`, using the SpicyDocs source reader.

Rulespec Artifacts owns bounded, no-overwrite blob publication and verifies a
competing writer's existing object before reuse. New cache files are stored at
`<store>/objects/sha256/<digest-hex>`. The previous
`<store>/sha256/<digest-hex>/<filename>` directories are left untouched and are
not searched. Supply the retained capture again to populate the new layout;
no published code-set identifiers or source pins change.

A verified existing object reports `acquisition_mode="cache"`, `cache_hit=True`,
`content_type="text/plain"`, and no local path or final URL. These fields describe
this acquisition attempt; a cache hit does not recreate the first attempt's
HTTP evidence. The same rule applies when another writer publishes the exact
object first. Invalid input, a corrupt object or a changed destination refuses
acquisition rather than replacing the stored file.

Run the retained-guide, mutation and frozen-acquisition comparisons with:

```sh
uv run --frozen pytest -q tests/test_billstatus_codes.py \
  tests/test_billstatus_shared.py tests/test_billstatus_acquisition_shared.py
```
