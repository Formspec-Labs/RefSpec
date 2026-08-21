"""The Agenda series as a witness against the Atlas's pinned code lists.

The Atlas holds the Unified Agenda's controlled value sets as the 2011 XSD
declares them, which is correct: the schema is the authority's declaration,
and every edition through Fall 2025 still names ``REGINFO_XML_Ver10262011``
in its own ``xsi:noNamespaceSchemaLocation``. The publisher has issued no
newer schema.

What the 60-edition series adds is not a competing declaration but evidence
about that one. Nothing here changes an Atlas code list -- under REF-035 an
observation licenses no assertion the authority has not made, and RINs
themselves are a population REF-031 keeps out of the Atlas entirely. These
tests pin the divergence so that a schema update, or a newly-minted code,
breaks a check instead of passing unnoticed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

EVIDENCE = (
    Path(__file__).resolve().parents[1]
    / "research"
    / "evidence"
    / "unified-agenda-schema-divergence-2026-08-20"
    / "divergence.json"
)


@pytest.fixture(scope="module")
def divergence() -> dict:
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))


def _field(divergence: dict, name: str) -> dict:
    return next(row for row in divergence["fields"] if row["field"] == name)


def test_the_publishers_data_violates_the_schema_its_own_files_cite(divergence: dict) -> None:
    """One real code, minted after the schema and never added to it.

    EO 14094 (April 2023) amended EO 12866 and introduced the Section 3(f)(1)
    threshold. It appears in 833 records from the Spring 2023 edition onward,
    inside documents that declare conformance to the 2011 schema. This is the
    only undeclared value in the series that is a genuine new code rather
    than a spelling of an existing one.
    """

    priority = _field(divergence, "priorityCategory")
    assert set(priority["undeclared_observed"]) == {"Section 3(f)(1) Significant"}
    entry = priority["undeclared_observed"]["Section 3(f)(1) Significant"]
    assert entry["records"] == 833
    assert entry["firstEdition"] == "202304"
    # And one declared code that thirty years of agenda never used.
    assert priority["declared_never_observed"] == ["Not Major"]


def test_rin_status_is_declared_in_a_casing_that_never_occurs(divergence: dict) -> None:
    """Both declared values match zero of 241,726 records.

    The schema says "First time published in the Unified Agenda"; every
    record says "First Time Published in The Unified Agenda". A consumer
    joining Atlas code values against agenda data on exact string equality
    matches nothing at all, which is the kind of failure that looks like an
    empty result rather than an error.
    """

    status = _field(divergence, "rinStatus")
    assert len(status["declared"]) == 2
    assert status["declared_never_observed"] == status["declared"]
    assert set(status["undeclared_observed"]) == {
        "First Time Published in The Unified Agenda",
        "Previously Published in The Unified Agenda",
    }
    assert sum(v["records"] for v in status["undeclared_observed"].values()) == 241_724


def test_the_remaining_divergences_are_publisher_defects_not_codes(divergence: dict) -> None:
    """Case variants and two truncated strings, named so they are not mistaken for vocabulary."""

    assert set(_field(divergence, "rfaRequired")["undeclared_observed"]) == {"YES"}
    relation = _field(divergence, "rinRelation")["undeclared_observed"]
    # "Merge with" is declared; "Merged with" is the same code in past tense.
    assert relation["Merged with"]["records"] == 2_283
    # Two values are cut mid-word -- 'Previously reported as', 'Related to'.
    assert relation["Previously report"]["records"] == 1
    assert relation["Related t"]["records"] == 3


def test_the_witness_covers_the_whole_published_series(divergence: dict) -> None:
    assert divergence["editions"] == 60
    assert divergence["records"] == 241_726
    assert divergence["schema"] == "REGINFO_XML_Ver10262011.xsd"
    # If this ever goes False, the publisher has issued a new schema and the
    # Atlas code lists should be rebuilt from it rather than from this file.
    assert divergence["schemaDeclaredByEveryEdition"] is True
