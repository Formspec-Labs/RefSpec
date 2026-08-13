from __future__ import annotations

import pytest

from refspec.vocabulary import is_english_language_tag


@pytest.mark.parametrize(
    ("tag", "expected"),
    (
        ("en", True),
        ("en-US", True),
        ("en-Latn", True),
        ("EN-gb", True),
        ("eng", False),
        ("en-", False),
        ("fr", False),
        (None, False),
    ),
)
def test_english_language_family_uses_the_bcp47_primary_subtag(
    tag: str | None,
    expected: bool,
) -> None:
    assert is_english_language_tag(tag) is expected


def test_english_language_family_can_admit_an_explicitly_untagged_source() -> None:
    assert is_english_language_tag(None, untagged_is_english=True) is True
