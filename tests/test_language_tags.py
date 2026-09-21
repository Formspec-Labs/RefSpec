"""BCP 47 English-family detection for ``is_english_language_tag`` and its untagged override.

Only the primary subtag decides: region/script variants are English, while
three-letter codes, malformed tags, and non-English tags are not. The
``untagged_is_english`` override admits a source that declares no tag at all.
"""

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
    """Only an ``en`` primary subtag is English; ``eng``, ``en-``, ``fr`` and None are not."""

    assert is_english_language_tag(tag) is expected


def test_english_language_family_can_admit_an_explicitly_untagged_source() -> None:
    """The caller may opt an untagged source into the English family."""

    assert is_english_language_tag(None, untagged_is_english=True) is True
