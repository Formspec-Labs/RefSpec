"""Lossless ELSST RDF/SKOS parser tests."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from refspec.registry.elsst import (
    ADDITIONAL_CONTENT_NOTE_PREDICATE_IRI,
    ALT_LABEL_PREDICATE_IRI,
    BROADER_PREDICATE_IRI,
    DEPRECATED_PREDICATE_IRI,
    ELSST_METADATA_LITERAL_PREDICATE_IRIS,
    ELSST_NOTE_PREDICATE_IRIS,
    HIDDEN_LABEL_PREDICATE_IRI,
    IDENTIFIER_PREDICATE_IRI,
    IS_REPLACED_BY_PREDICATE_IRI,
    IS_VERSION_OF_PREDICATE_IRI,
    NARROWER_PREDICATE_IRI,
    NOTE_PREDICATE_IRIS,
    PREF_LABEL_PREDICATE_IRI,
    PRIOR_VERSION_PREDICATE_IRI,
    RELATED_PREDICATE_IRI,
    REPLACES_PREDICATE_IRI,
    ElsstImportCounts,
    ElsstParseError,
    compare_elsst_releases,
    parse_acquired_elsst_source,
    parse_elsst_file,
    parse_elsst_turtle,
)
from refspec.registry.elsst_acquisition import (
    ELSST_R5,
    ELSST_R6,
    ElsstReleaseSource,
    acquire_elsst_release,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "elsst-mini.ttl"
R5_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "elsst-mini-r5.ttl"
FIXTURE_SOURCE_URL = "https://example.test/elsst-mini.ttl"
CURRENT = "https://elsst.cessda.eu/id/6/4ae8f7d8-3ff9-4258-9dc8-7cf9c345dd6f"
RETIRED = "https://elsst.cessda.eu/id/6/05fd5779-69ad-4872-ae25-a8c400b73e10"
BROADER = "https://elsst.cessda.eu/id/6/8a80f878-851c-4f47-a451-a8fe75b81aad"
ADDED = "https://elsst.cessda.eu/id/6/119d77ee-88cc-4759-9ab7-0cf96a8aba19"

SYNTHETIC_FEATURE_EDGE_TURTLE = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
<urn:example:edge> a skos:Concept ;
    skos:prefLabel "Edge concept"@en ;
    skos:hiddenLabel "Internal term"@en ;
    skos:notation "P-001"^^<urn:example:notation-datatype> ;
    skos:definition "Definition."@en ;
    skos:example "Example."@en ;
    skos:note "Note."@en ;
    skos:scopeNote "Scope."@en ;
    skos:editorialNote "Editorial."@en ;
    skos:historyNote "History."@en ;
    skos:changeNote "Change."@en ;
    <http://rdf-vocabulary.ddialliance.org/xkos#additionalContentNote> "Source."@en .
"""


def _fixture_bytes() -> bytes:
    return FIXTURE_PATH.read_bytes()


def test_parser_preserves_source_derived_multilingual_labels_notes_identifiers_and_iris() -> None:
    source = _fixture_bytes()
    parsed = parse_elsst_turtle(source, source_url=FIXTURE_SOURCE_URL)

    assert parsed.source_url == FIXTURE_SOURCE_URL
    assert parsed.source_bytes == len(source)
    assert parsed.source_sha256 == "sha256:" + hashlib.sha256(source).hexdigest()
    assert parsed.triple_count > 0
    assert parsed == parse_elsst_turtle(source, source_url=FIXTURE_SOURCE_URL)

    current_labels = [item for item in parsed.labels if item.subject_iri == CURRENT]
    preferred = {
        item.value.language_tag: item.value.lexical_form
        for item in current_labels
        if item.property_iri == PREF_LABEL_PREDICATE_IRI
    }
    assert preferred == {
        "el": "ΑΡΧΗΓΟΣ ΝΟΙΚΟΚΥΡΙΟΥ",
        "en": "HEADS OF HOUSEHOLD",
        "es": "CABEZAS DE HOGAR",
    }
    assert {
        (item.property_iri, item.value.language_tag, item.value.lexical_form)
        for item in current_labels
        if item.role != "preferred"
    } == {
        (ALT_LABEL_PREDICATE_IRI, "el", "ΥΠΕΥΘΥΝΟΣ ΝΟΙΚΟΚΥΡΙΟΥ"),
        (ALT_LABEL_PREDICATE_IRI, "en", "HOUSEHOLDERS"),
        (ALT_LABEL_PREDICATE_IRI, "es", "PERSONAS CABEZA DE HOGAR"),
    }

    assert {item.property_iri for item in parsed.notes} == {
        "http://www.w3.org/2004/02/skos/core#definition",
        "http://www.w3.org/2004/02/skos/core#historyNote",
        "http://www.w3.org/2004/02/skos/core#scopeNote",
    }
    assert parsed.notations == ()

    current_identifiers = [
        item
        for item in parsed.metadata_literals
        if item.subject_iri == CURRENT and item.property_iri == IDENTIFIER_PREDICATE_IRI
    ]
    assert {(item.value.language_tag, item.value.lexical_form) for item in current_identifiers} == {
        ("el", "urn:ddi:int.cessda.elsst:4ae8f7d8-3ff9-4258-9dc8-7cf9c345dd6f:6"),
        ("en", "urn:ddi:int.cessda.elsst:4ae8f7d8-3ff9-4258-9dc8-7cf9c345dd6f:6"),
        ("es", "urn:ddi:int.cessda.elsst:4ae8f7d8-3ff9-4258-9dc8-7cf9c345dd6f:6"),
    }
    assert not [
        item
        for item in parsed.metadata_literals
        if item.subject_iri == ADDED and item.property_iri == IDENTIFIER_PREDICATE_IRI
    ]
    assert set(ELSST_METADATA_LITERAL_PREDICATE_IRIS).issuperset(item.property_iri for item in parsed.metadata_literals)

    assert CURRENT in parsed.source_iris
    assert "https://elsst.cessda.eu/id/4ae8f7d8-3ff9-4258-9dc8-7cf9c345dd6f" in parsed.source_iris
    assert "https://elsst.cessda.eu/id/5/4ae8f7d8-3ff9-4258-9dc8-7cf9c345dd6f" in parsed.source_iris


def test_clearly_synthetic_edge_input_covers_hidden_labels_typed_notation_and_all_notes() -> None:
    parsed = parse_elsst_turtle(
        SYNTHETIC_FEATURE_EDGE_TURTLE,
        source_url="https://example.test/synthetic-feature-edge.ttl",
    )

    assert any(item.property_iri == HIDDEN_LABEL_PREDICATE_IRI for item in parsed.labels)
    assert len(parsed.notations) == 1
    notation = parsed.notations[0]
    assert notation.value.lexical_form == "P-001"
    assert notation.value.language_tag is None
    assert notation.value.datatype_iri == "urn:example:notation-datatype"
    assert {item.property_iri for item in parsed.notes} == set(ELSST_NOTE_PREDICATE_IRIS)
    assert set(NOTE_PREDICATE_IRIS).issubset(item.property_iri for item in parsed.notes)
    assert (
        next(
            item for item in parsed.notes if item.property_iri == ADDITIONAL_CONTENT_NOTE_PREDICATE_IRI
        ).value.lexical_form
        == "Source."
    )


def test_parser_keeps_hierarchy_lifecycle_and_version_identity_as_distinct_rows() -> None:
    parsed = parse_elsst_turtle(_fixture_bytes(), source_url=FIXTURE_SOURCE_URL)

    assert {
        (item.predicate_iri, item.object_iri) for item in parsed.semantic_relations if item.subject_iri == CURRENT
    } == {
        (BROADER_PREDICATE_IRI, BROADER),
    }
    assert {
        (item.predicate_iri, item.object_iri) for item in parsed.semantic_relations if item.subject_iri == BROADER
    } == {
        (NARROWER_PREDICATE_IRI, CURRENT),
        (NARROWER_PREDICATE_IRI, ADDED),
        (
            RELATED_PREDICATE_IRI,
            "https://elsst.cessda.eu/id/6/37962809-512d-4f33-826f-15446df86392",
        ),
    }

    assert {(item.subject_iri, item.predicate_iri, item.object_iri) for item in parsed.replacement_relations} == {
        (RETIRED, IS_REPLACED_BY_PREDICATE_IRI, CURRENT),
        (CURRENT, REPLACES_PREDICATE_IRI, RETIRED),
    }
    assert {
        (item.subject_iri, item.predicate_iri, item.object_iri)
        for item in parsed.version_relations
        if item.subject_iri == CURRENT
    } == {
        (
            CURRENT,
            IS_VERSION_OF_PREDICATE_IRI,
            "https://elsst.cessda.eu/id/4ae8f7d8-3ff9-4258-9dc8-7cf9c345dd6f",
        ),
        (
            CURRENT,
            PRIOR_VERSION_PREDICATE_IRI,
            "https://elsst.cessda.eu/id/5/4ae8f7d8-3ff9-4258-9dc8-7cf9c345dd6f",
        ),
    }
    assert CURRENT != "https://elsst.cessda.eu/id/4ae8f7d8-3ff9-4258-9dc8-7cf9c345dd6f"
    assert CURRENT != "https://elsst.cessda.eu/id/5/4ae8f7d8-3ff9-4258-9dc8-7cf9c345dd6f"

    assert len(parsed.deprecated_assertions) == 1
    deprecated = parsed.deprecated_assertions[0]
    assert deprecated.subject_iri == RETIRED
    assert deprecated.predicate_iri == DEPRECATED_PREDICATE_IRI
    assert deprecated.value.lexical_form == "true"
    assert deprecated.value.datatype_iri == "http://www.w3.org/2001/XMLSchema#boolean"

    current_concept = next(item for item in parsed.concepts if item.concept_iri == CURRENT)
    assert current_concept.scheme_iris == ("https://elsst.cessda.eu/id/6/",)
    assert current_concept.top_concept_of_iris == ()
    assert parsed.concept_schemes[0].top_concept_iris == ()


def test_release_comparison_uses_only_exact_stable_and_prior_version_assertions() -> None:
    previous = parse_elsst_turtle(
        R5_FIXTURE_PATH.read_bytes(),
        source_url="https://example.test/elsst-mini-r5.ttl",
    )
    current = parse_elsst_turtle(
        _fixture_bytes(),
        source_url=FIXTURE_SOURCE_URL,
    )

    comparison = compare_elsst_releases(previous, current)

    assert {item.stable_identity_iri for item in comparison.retained_stable_identities} == {
        "https://elsst.cessda.eu/id/05fd5779-69ad-4872-ae25-a8c400b73e10",
        "https://elsst.cessda.eu/id/4ae8f7d8-3ff9-4258-9dc8-7cf9c345dd6f",
        "https://elsst.cessda.eu/id/8a80f878-851c-4f47-a451-a8fe75b81aad",
    }
    assert comparison.added_concept_iris == (ADDED,)
    assert comparison.new_deprecated_concept_iris == (RETIRED,)
    assert comparison.replacement_pairs == (
        next(item for item in current.replacement_relations if item.predicate_iri == IS_REPLACED_BY_PREDICATE_IRI),
    )

    renamed_previous = parse_elsst_turtle(
        R5_FIXTURE_PATH.read_text().replace("HOUSEHOLDERS", "RENAMED PREVIOUS LABEL"),
        source_url="https://example.test/elsst-mini-r5-renamed.ttl",
    )
    renamed_current = parse_elsst_turtle(
        _fixture_bytes().decode("utf-8").replace("HOUSEHOLDERS", "RENAMED CURRENT LABEL"),
        source_url="https://example.test/elsst-mini-r6-renamed.ttl",
    )
    renamed = compare_elsst_releases(renamed_previous, renamed_current)
    assert renamed.retained_stable_identities == comparison.retained_stable_identities
    assert renamed.added_concept_iris == comparison.added_concept_iris
    assert renamed.new_deprecated_concept_iris == comparison.new_deprecated_concept_iris
    assert renamed.replacement_pairs == comparison.replacement_pairs


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            lambda: (
                _fixture_bytes()
                .decode("utf-8")
                .replace(
                    '"HEADS OF HOUSEHOLD"@en',
                    '"HEADS OF HOUSEHOLD"',
                    1,
                )
            ),
            "untagged",
        ),
        (
            lambda: SYNTHETIC_FEATURE_EDGE_TURTLE.replace(
                '"P-001"^^<urn:example:notation-datatype>',
                '"P-001"',
                1,
            ),
            "typed literal",
        ),
        (
            lambda: (
                _fixture_bytes()
                .decode("utf-8")
                .replace(
                    '"HEADS OF HOUSEHOLD"@en,',
                    '"HOUSEHOLD LEADERS"@en, "HEADS OF HOUSEHOLD"@en,',
                    1,
                )
            ),
            "more than one preferred label",
        ),
        (
            lambda: (
                _fixture_bytes()
                .decode("utf-8")
                .replace(
                    "<https://elsst.cessda.eu/id/6/8a80f878-851c-4f47-a451-a8fe75b81aad>",
                    "[]",
                    1,
                )
            ),
            "must be an IRI",
        ),
    ],
)
def test_parser_rejects_lossy_or_ambiguous_skos_features(
    source,
    message: str,
) -> None:
    with pytest.raises(ElsstParseError, match=message):
        parse_elsst_turtle(source(), source_url=FIXTURE_SOURCE_URL)


def test_parser_enforces_optional_distribution_digest_and_size_pins() -> None:
    source = _fixture_bytes()
    digest = "sha256:" + hashlib.sha256(source).hexdigest()
    parsed = parse_elsst_turtle(
        source,
        source_url=FIXTURE_SOURCE_URL,
        expected_sha256=digest,
        expected_byte_length=len(source),
    )
    assert parsed.source_sha256 == digest

    with pytest.raises(ElsstParseError, match="digest mismatch"):
        parse_elsst_turtle(
            source,
            source_url=FIXTURE_SOURCE_URL,
            expected_sha256="sha256:" + "0" * 64,
        )
    with pytest.raises(ElsstParseError, match="byte length mismatch"):
        parse_elsst_turtle(
            source,
            source_url=FIXTURE_SOURCE_URL,
            expected_byte_length=len(source) + 1,
        )


def test_verified_local_acquisition_parses_with_the_same_release_pin(tmp_path: Path) -> None:
    source = _fixture_bytes()
    source_path = tmp_path / "elsst-mini.ttl"
    source_path.write_bytes(source)
    release = ElsstReleaseSource(
        version="fixture",
        release_iri="https://elsst.cessda.eu/id/6",
        concept_scheme_iri="https://elsst.cessda.eu/id/6/",
        source_url=FIXTURE_SOURCE_URL,
        expected_sha256="sha256:" + hashlib.sha256(source).hexdigest(),
        expected_byte_length=len(source),
        filename="elsst-mini.ttl",
    )
    acquired = acquire_elsst_release(
        release,
        tmp_path / "store",
        source_path=source_path,
    )

    parsed = parse_acquired_elsst_source(acquired)

    assert parsed.source_sha256 == acquired.sha256
    assert parsed.source_bytes == acquired.byte_length
    assert {item.scheme_iri for item in parsed.concept_schemes} == {release.concept_scheme_iri}


PINNED_REAL_COUNTS = {
    "5": ElsstImportCounts(
        source_bytes=19_167_985,
        triples=236_925,
        source_iris=10_331,
        concepts=3_435,
        concept_schemes=1,
        preferred_labels=51_428,
        alternate_labels=36_338,
        hidden_labels=0,
        notes=13_916,
        notations=0,
        broader_relations=3_361,
        narrower_relations=3_361,
        related_relations=5_640,
        deprecated_assertions=34,
        metadata_literals=56_986,
        identifier_assertions=51_540,
        issued_assertions=3_436,
        modified_assertions=1_991,
        is_replaced_by_relations=6,
        replaces_relations=6,
        is_version_of_relations=3_436,
        prior_version_relations=3_423,
    ),
    "6": ElsstImportCounts(
        source_bytes=19_915_491,
        triples=239_821,
        source_iris=10_367,
        concepts=3_470,
        concept_schemes=1,
        preferred_labels=51_863,
        alternate_labels=37_065,
        hidden_labels=0,
        notes=15_009,
        notations=0,
        broader_relations=3_393,
        narrower_relations=3_393,
        related_relations=5_696,
        deprecated_assertions=37,
        metadata_literals=57_044,
        identifier_assertions=51_540,
        issued_assertions=3_436,
        modified_assertions=2_049,
        is_replaced_by_relations=9,
        replaces_relations=9,
        is_version_of_relations=3_436,
        prior_version_relations=3_423,
    ),
}


@pytest.mark.parametrize(
    ("release", "path_environment"),
    [
        (ELSST_R5, "REFSPEC_ELSST_R5_PATH"),
        (ELSST_R6, "REFSPEC_ELSST_R6_PATH"),
    ],
)
def test_opt_in_pinned_real_distribution_counts(
    release: ElsstReleaseSource,
    path_environment: str,
) -> None:
    source_path = os.environ.get(path_environment)
    if source_path is None:
        pytest.skip(f"set {path_environment} to the exact verified {release.filename} distribution")

    parsed = parse_elsst_file(
        Path(source_path),
        source_url=release.source_url,
        expected_sha256=release.expected_sha256,
        expected_byte_length=release.expected_byte_length,
    )

    assert parsed.counts == PINNED_REAL_COUNTS[release.version]
    assert {item.scheme_iri for item in parsed.concept_schemes} == {release.concept_scheme_iri}
    assert {item.value.language_tag for item in parsed.labels} == {
        "cs",
        "de",
        "el",
        "en",
        "es",
        "fi",
        "fr",
        "hu",
        "is",
        "lt",
        "nl",
        "no",
        "ro",
        "sl",
        "sv",
    }
    assert all(item.value.language_tag is not None for item in parsed.labels)


def test_opt_in_real_r5_to_r6_identity_and_lifecycle_comparison() -> None:
    r5_path = os.environ.get("REFSPEC_ELSST_R5_PATH")
    r6_path = os.environ.get("REFSPEC_ELSST_R6_PATH")
    if r5_path is None or r6_path is None:
        pytest.skip("set both REFSPEC_ELSST_R5_PATH and REFSPEC_ELSST_R6_PATH")

    previous = parse_elsst_file(
        Path(r5_path),
        source_url=ELSST_R5.source_url,
        expected_sha256=ELSST_R5.expected_sha256,
        expected_byte_length=ELSST_R5.expected_byte_length,
    )
    current = parse_elsst_file(
        Path(r6_path),
        source_url=ELSST_R6.source_url,
        expected_sha256=ELSST_R6.expected_sha256,
        expected_byte_length=ELSST_R6.expected_byte_length,
    )
    comparison = compare_elsst_releases(previous, current)

    assert len(comparison.retained_stable_identities) == 3_435
    assert len(comparison.added_concept_iris) == 35
    assert len(comparison.new_deprecated_concept_iris) == 3
    assert len(comparison.replacement_pairs) == 9
    assert RETIRED in comparison.new_deprecated_concept_iris
