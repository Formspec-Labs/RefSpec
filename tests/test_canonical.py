from __future__ import annotations

import math

import pytest

from refspec.canonical import (
    CanonicalValueError,
    canonical_json_bytes,
    seal_vocabulary_release,
    vocabulary_release_digest,
)


def test_canonical_json_is_sorted_compact_unicode_utf8() -> None:
    assert canonical_json_bytes({"z": "café", "a": 1}) == (b'{"a":1,"z":"caf\xc3\xa9"}')


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_canonical_json_rejects_nonfinite_numbers(value: float) -> None:
    with pytest.raises(CanonicalValueError):
        canonical_json_bytes({"value": value})


def test_release_digest_omits_only_root_identity_fields() -> None:
    release = seal_vocabulary_release(
        {"nested": {"release_id": "must-be-hashed"}, "value": 1}
    )
    changed_root = dict(release)
    changed_root["release_id"] = "ignored-by-digest-function"
    changed_root["release_digest"] = "ignored-by-digest-function"
    assert vocabulary_release_digest(changed_root) == release["release_digest"]

    changed_nested = {
        **release,
        "nested": {"release_id": "different-and-therefore-hashed"},
    }
    assert vocabulary_release_digest(changed_nested) != release["release_digest"]
