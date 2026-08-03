"""The SSSOM projection of a sealed crosswalk bundle.

The properties proven here are the ones two external tools broke in the
2026-08-03 spikes: row-level provenance survives, every identifier is a
single-colon CURIE that expands back to the original IRI, and the same bundle
exports the same bytes.  The last test reads the real 2026-08-02 pilot bundle,
because a synthetic fixture cannot prove the exporter handles 121 qualified
mappings drawn from 365 candidates over two real vocabularies.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from refspec import binding
from refspec.atlas import (
    CrosswalkArtifact,
    CrosswalkBundle,
    MachineValidation,
    MappingCandidate,
)
from refspec.atlas.sssom_export import (
    COLUMNS,
    MAPPING_SET_NAMESPACE,
    REVIEWED_JUSTIFICATION,
    UNREVIEWED_JUSTIFICATION,
    SssomExportError,
    sssom_text,
    write_sssom,
)

CLOSE_MATCH = "http://www.w3.org/2004/02/skos/core#closeMatch"
SOURCE_RELEASE = "urn:ref:test:alpha:reference-resource-release:v1"
TARGET_RELEASE = "https://example.org/vocab/beta/2"
GENERATED_AT = "2026-08-03T09:00:00Z"

REAL_BUNDLE = Path("research/evidence/atlas-crosswalk-qualification-2026-08-02/crosswalk-bundle.json")
REAL_FILE_DIGEST = "sha256:508dd5611714ebbfb786bd87e814046ae40d072a8dd67e12c9e7f48e251c9b92"
REAL_BUNDLE_DIGEST = "sha256:d9a905a0d96bdf22ed829bfb7c5afc54b2084b1ebbcf3dbd88aebab0350d35d2"


# ---------------------------------------------------------------------------
# a small bundle whose qualification outcome is known by construction
# ---------------------------------------------------------------------------


def _nested_context(number: str, source_label: str, target_label: str) -> dict[str, Any]:
    """The shape the qualification runner seals: nested concept blocks."""

    return {
        "payload": {
            "source": {
                "member": f"urn:ref:test:alpha:concept:{number}",
                "prefLabel": source_label,
                "release": SOURCE_RELEASE,
            },
            "target": {
                "member": f"https://example.org/vocab/beta/2/{number}",
                "prefLabel": target_label,
                "release": TARGET_RELEASE,
            },
        },
        "protocol": "refspec-atlas-model-input-v1",
    }


def _flat_context(number: str, source_label: str, target_label: str) -> dict[str, Any]:
    """The smaller shape other sealed contexts use: flat member/label pairs."""

    return {
        "protocol": "refspec-atlas-model-input-v1",
        "sourceLabel": source_label,
        "sourceMember": f"urn:ref:test:alpha:concept:{number}",
        "targetLabel": target_label,
        "targetMember": f"https://example.org/vocab/beta/2/{number}",
    }


def _proposal(
    number: str,
    *,
    context: dict[str, Any],
    method: str,
) -> tuple[MappingCandidate, list[CrosswalkArtifact]]:
    context_artifact = CrosswalkArtifact.create(
        role="inputContext",
        media_type="application/json",
        content=context,
    )
    evidence = CrosswalkArtifact.create(
        role="evidence",
        media_type="application/json",
        content={"method": method, "version": "1"},
    )
    input_digest = binding.canonical_sha256(dict(context))
    candidate = MappingCandidate.create(
        source_member=f"urn:ref:test:alpha:concept:{number}",
        source_release=SOURCE_RELEASE,
        target_member=f"https://example.org/vocab/beta/2/{number}",
        target_release=TARGET_RELEASE,
        proposed_relation=CLOSE_MATCH,
        generator_kind="aiModel",
        generator_actor="urn:ref:test:actor:generator",
        generator_provider="urn:ref:test:provider:generator",
        model_id="test-candidate-generator",
        model_version="1",
        prompt_template="urn:ref:test:prompt:v1",
        input_context_digest=input_digest,
        temperature="0",
        evidence=[evidence.reference()],
        generated_at=GENERATED_AT,
    )
    request = CrosswalkArtifact.create(
        role="validationRequest",
        media_type="application/json",
        content={
            "candidate": candidate.reference(),
            "inputDigest": input_digest,
            "protocol": "refspec-atlas-machine-validation-v1",
        },
    )
    return candidate, [context_artifact, evidence, request]


def _review(
    candidate: MappingCandidate,
    request: CrosswalkArtifact,
    input_digest: str,
    suffix: str,
) -> tuple[MachineValidation, CrosswalkArtifact]:
    response = CrosswalkArtifact.create(
        role="validationResponse",
        media_type="application/json",
        content={
            "candidate": candidate.reference(),
            "deterministicChecksPassed": True,
            "inputDigest": input_digest,
            "outcome": "supports",
            "provider": f"urn:ref:test:provider:{suffix}",
            "providerModelId": f"provider-model-{suffix}",
            "requestArtifact": request.reference(),
            "validatorActor": f"urn:ref:test:validator:{suffix}",
        },
    )
    validation = MachineValidation.create(
        candidate=candidate.reference(),
        validator_kind="aiModel",
        validator_actor=f"urn:ref:test:validator:{suffix}",
        independence_group=f"urn:ref:test:group:{suffix}",
        provider=f"urn:ref:test:provider:{suffix}",
        provider_model_id=f"provider-model-{suffix}",
        sealed_input_digest=input_digest,
        request_artifact=request.reference(),
        response_artifact=response.reference(),
        deterministic_checks_passed=True,
        outcome="supports",
        completed_at=GENERATED_AT,
    )
    return validation, response


@pytest.fixture(scope="module")
def bundle() -> CrosswalkBundle:
    """Two qualified candidates and one that only one machine reviewed."""

    artifacts: list[CrosswalkArtifact] = []
    candidates: list[MappingCandidate] = []
    validations: list[MachineValidation] = []
    plan = (
        ("0002", _nested_context("0002", "Water pollution", "WATER POLLUTION"), "preferred-label-equality", 2),
        ("0001", _flat_context("0001", "Energy policy", "ENERGY POLICY"), "alternate-label-equality", 2),
        ("0003", _nested_context("0003", "Labor unions", "TRADE UNIONS"), "edit-distance", 1),
    )
    for number, context, method, reviewers in plan:
        candidate, produced = _proposal(number, context=context, method=method)
        artifacts.extend(produced)
        candidates.append(candidate)
        request = produced[-1]
        for suffix in ("a", "b")[:reviewers]:
            validation, response = _review(
                candidate,
                request,
                binding.canonical_sha256(dict(context)),
                suffix,
            )
            validations.append(validation)
            artifacts.append(response)
    return CrosswalkBundle.create(
        artifacts=artifacts,
        mapping_candidates=candidates,
        machine_validations=validations,
    )


def _split(text: str) -> tuple[list[str], list[str], list[dict[str, str]]]:
    lines = text.splitlines()
    header = [line for line in lines if line.startswith("#")]
    body = [line for line in lines if not line.startswith("#")]
    columns = body[0].split("\t")
    rows = [dict(zip(columns, line.split("\t"), strict=True)) for line in body[1:]]
    return header, columns, rows


def _curie_map(header: list[str]) -> dict[str, str]:
    start = header.index("# curie_map:") + 1
    prefixes: dict[str, str] = {}
    for line in header[start:]:
        if not line.startswith("#   "):
            break
        prefix, _, expansion = line.removeprefix("#   ").partition(": ")
        prefixes[prefix] = expansion.strip('"')
    return prefixes


def _expand(value: str, prefixes: dict[str, str]) -> str:
    prefix, _, local = value.partition(":")
    assert prefix in prefixes, f"{value} uses an undeclared prefix"
    return prefixes[prefix] + local


# ---------------------------------------------------------------------------
# shape
# ---------------------------------------------------------------------------


def test_table_is_a_metadata_header_a_column_row_and_mapping_rows(bundle: CrosswalkBundle) -> None:
    header, columns, rows = _split(sssom_text(bundle))

    assert header[0].startswith("# ")
    assert columns == list(COLUMNS)
    assert len(rows) == 2
    assert sssom_text(bundle).endswith("\n")


def test_required_columns_are_present_and_confidence_is_not_invented(bundle: CrosswalkBundle) -> None:
    _, columns, _ = _split(sssom_text(bundle))

    assert {
        "subject_id",
        "subject_label",
        "predicate_id",
        "object_id",
        "object_label",
        "mapping_justification",
        "mapping_source",
    } <= set(columns)
    assert "confidence" not in columns


def test_header_declares_a_mapping_set_id_derived_from_the_bundle_digest(bundle: CrosswalkBundle) -> None:
    header, _, _ = _split(sssom_text(bundle))
    declared = next(line for line in header if line.startswith("# mapping_set_id:"))

    digest = bundle.digest.removeprefix("sha256:")
    assert declared == f'# mapping_set_id: "{MAPPING_SET_NAMESPACE}{digest}/qualified"'
    assert "# curie_map:" in header


def _set_id(header: list[str]) -> str:
    return next(line for line in header if line.startswith("# mapping_set_id:"))


def test_exporting_all_candidates_names_a_different_mapping_set(bundle: CrosswalkBundle) -> None:
    """Two different row sets from one bundle must not claim one set identity."""

    qualified, _, _ = _split(sssom_text(bundle))
    everything, _, _ = _split(sssom_text(bundle, qualified_only=False))

    assert _set_id(qualified) != _set_id(everything)
    assert _set_id(everything).endswith('/all-candidates"')


# ---------------------------------------------------------------------------
# the three properties the spikes broke
# ---------------------------------------------------------------------------


def test_every_row_carries_the_bundle_identifier_in_full(bundle: CrosswalkBundle) -> None:
    """Provenance a consumer can lose is provenance a consumer will lose.

    A reader that keeps only the TSV body — no header, so no ``curie_map`` —
    must still be able to say which sealed bundle each mapping came from.
    """

    _, _, rows = _split(sssom_text(bundle, qualified_only=False))

    assert rows
    for row in rows:
        assert row["mapping_source"] == bundle.identifier
        assert row["see_also"] in _candidate_ids(bundle)


def test_concept_level_identifiers_are_single_colon_curies_that_expand_losslessly(
    bundle: CrosswalkBundle,
) -> None:
    header, _, rows = _split(sssom_text(bundle, qualified_only=False))
    prefixes = _curie_map(header)
    entity_columns = (
        "subject_id",
        "predicate_id",
        "object_id",
        "mapping_justification",
        "subject_source",
        "object_source",
    )
    expanded = {column: {_expand(row[column], prefixes) for row in rows} for column in entity_columns}

    for row in rows:
        for column in entity_columns:
            assert row[column].count(":") == 1, f"{column} is not a CURIE: {row[column]}"
    assert expanded["subject_source"] == {SOURCE_RELEASE}
    assert expanded["object_source"] == {TARGET_RELEASE}
    assert expanded["predicate_id"] == {CLOSE_MATCH}
    assert expanded["subject_id"] == {f"urn:ref:test:alpha:concept:{n}" for n in ("0001", "0002", "0003")}
    assert expanded["object_id"] == {f"https://example.org/vocab/beta/2/{n}" for n in ("0001", "0002", "0003")}


def test_full_form_record_identifiers_still_resolve_through_the_declared_scheme(
    bundle: CrosswalkBundle,
) -> None:
    """``urn:`` is declared, so splitting at the first colon is still lossless.

    That is what keeps a strict reader's prefix-completeness check satisfied
    without shortening the two columns that must survive header loss.
    """

    header, _, rows = _split(sssom_text(bundle, qualified_only=False))
    prefixes = _curie_map(header)

    assert prefixes["urn"] == "urn:"
    for row in rows:
        for column in ("mapping_source", "see_also"):
            assert _expand(row[column], prefixes) == row[column]


def _candidate_ids(bundle: CrosswalkBundle) -> set[str]:
    return {str(item["id"]) for item in bundle.to_dict()["mappingCandidates"]}


def test_the_same_bundle_exports_the_same_bytes(bundle: CrosswalkBundle) -> None:
    assert sssom_text(bundle) == sssom_text(bundle)
    assert sssom_text(bundle, qualified_only=False) == sssom_text(bundle, qualified_only=False)


def test_prefixes_are_edition_scoped_so_a_registry_cannot_redirect_an_edition() -> None:
    """A bare ``elsst`` prefix resolves to edition 3 in the Bioregistry."""

    from refspec.atlas.sssom_export import WELL_KNOWN_PREFIXES

    assert WELL_KNOWN_PREFIXES["https://elsst.cessda.eu/id/6/"] == "elsst6"
    assert "elsst" not in set(WELL_KNOWN_PREFIXES.values())


# ---------------------------------------------------------------------------
# what qualifies, and what a row claims about it
# ---------------------------------------------------------------------------


def test_qualified_only_exports_exactly_the_candidates_that_passed_the_gate(
    bundle: CrosswalkBundle,
) -> None:
    _, _, rows = _split(sssom_text(bundle))

    assert {row["see_also"] for row in rows} == set(bundle.qualified())
    assert {row["mapping_justification"] for row in rows} == {"semapv:MappingReview"}


def test_exporting_every_candidate_does_not_claim_they_were_reviewed(bundle: CrosswalkBundle) -> None:
    header, _, rows = _split(sssom_text(bundle, qualified_only=False))
    prefixes = _curie_map(header)
    qualified = set(bundle.qualified())
    by_candidate = {row["see_also"]: row for row in rows}

    assert len(rows) == 3
    assert set(by_candidate) == _candidate_ids(bundle)
    for identifier, row in by_candidate.items():
        expected = REVIEWED_JUSTIFICATION if identifier in qualified else UNREVIEWED_JUSTIFICATION
        assert _expand(row["mapping_justification"], prefixes) == expected


def test_generation_method_is_reported_beside_the_justification_not_inside_it(
    bundle: CrosswalkBundle,
) -> None:
    _, _, rows = _split(sssom_text(bundle, qualified_only=False))

    assert {row["comment"] for row in rows} == {
        "preferred-label-equality",
        "alternate-label-equality",
        "edit-distance",
    }
    assert {row["mapping_tool"] for row in rows} == {"test-candidate-generator"}
    assert {row["mapping_tool_version"] for row in rows} == {"1"}


def test_labels_are_read_from_both_sealed_input_context_shapes(bundle: CrosswalkBundle) -> None:
    _, _, rows = _split(sssom_text(bundle, qualified_only=False))
    labels = {row["subject_label"]: row["object_label"] for row in rows}

    assert labels == {
        "Energy policy": "ENERGY POLICY",
        "Water pollution": "WATER POLLUTION",
        "Labor unions": "TRADE UNIONS",
    }


def test_rows_are_sorted_by_subject_then_object(bundle: CrosswalkBundle) -> None:
    _, _, rows = _split(sssom_text(bundle, qualified_only=False))
    keys = [(row["subject_id"], row["object_id"]) for row in rows]

    assert keys == sorted(keys)
    assert keys[0][0].endswith(":0001")


# ---------------------------------------------------------------------------
# fail closed
# ---------------------------------------------------------------------------


def test_a_label_carrying_a_tab_is_refused_rather_than_silently_split() -> None:
    context = _flat_context("0009", "Energy\tpolicy", "ENERGY POLICY")
    candidate, artifacts = _proposal("0009", context=context, method="preferred-label-equality")
    broken = CrosswalkBundle.create(artifacts=artifacts, mapping_candidates=[candidate])

    with pytest.raises(SssomExportError, match="tab, newline, or carriage return"):
        sssom_text(broken, qualified_only=False)


def test_an_identifier_with_no_local_name_is_refused_rather_than_written_malformed() -> None:
    from refspec.atlas.sssom_export import _split_iri

    with pytest.raises(SssomExportError, match="multi-colon CURIE"):
        _split_iri("https://example.org/vocab/a:b")
    with pytest.raises(SssomExportError, match="no local name"):
        _split_iri("https://example.org/vocab/")


# ---------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------


def test_write_sssom_writes_exactly_the_exported_text(bundle: CrosswalkBundle, tmp_path: Path) -> None:
    target = write_sssom(bundle, tmp_path / "nested" / "crosswalk.sssom.tsv")

    assert target.read_bytes() == sssom_text(bundle).encode("utf-8")
    assert write_sssom(bundle, target).read_bytes() == target.read_bytes()


def test_write_sssom_honours_qualified_only(bundle: CrosswalkBundle, tmp_path: Path) -> None:
    every = write_sssom(bundle, tmp_path / "all.sssom.tsv", qualified_only=False)

    assert every.read_text(encoding="utf-8") == sssom_text(bundle, qualified_only=False)


# ---------------------------------------------------------------------------
# an independent reader, and the real pilot bundle
# ---------------------------------------------------------------------------


def test_sssom_py_reads_the_table_and_keeps_the_row_level_source(
    bundle: CrosswalkBundle,
    tmp_path: Path,
) -> None:
    """Self-validation is not validation; a real SSSOM reader has to agree."""

    pytest.importorskip("sssom")
    from sssom.parsers import parse_sssom_table

    target = write_sssom(bundle, tmp_path / "roundtrip.sssom.tsv", qualified_only=False)
    parsed = parse_sssom_table(str(target))
    frame = parsed.df

    assert len(frame) == 3
    assert frame["mapping_source"].notna().all()
    assert set(frame["mapping_source"]) == {bundle.identifier}


def test_sssom_py_finds_every_prefix_the_export_uses(bundle: CrosswalkBundle, tmp_path: Path) -> None:
    """An undeclared prefix is what made a strict reader drop rows before."""

    pytest.importorskip("sssom")
    from sssom.parsers import parse_sssom_table
    from sssom.validators import SchemaValidationType, validate

    target = write_sssom(bundle, tmp_path / "complete.sssom.tsv", qualified_only=False)
    parsed = parse_sssom_table(str(target))

    validate(parsed, [SchemaValidationType.JsonSchema, SchemaValidationType.PrefixMapCompleteness])


@pytest.fixture(scope="module")
def pilot_bundle() -> CrosswalkBundle:
    if not REAL_BUNDLE.exists():  # pragma: no cover - the file is committed
        pytest.skip("the 2026-08-02 pilot bundle is not present")
    return CrosswalkBundle.open(
        REAL_BUNDLE,
        expected_file_digest=REAL_FILE_DIGEST,
        expected_bundle_digest=REAL_BUNDLE_DIGEST,
    )


def test_the_real_pilot_bundle_exports_its_121_qualified_mappings(
    pilot_bundle: CrosswalkBundle,
) -> None:
    text = sssom_text(pilot_bundle)
    header, columns, rows = _split(text)
    prefixes = _curie_map(header)

    assert len(rows) == 121
    assert text == sssom_text(pilot_bundle)
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == (
        "5b44de14a499d882fecc1b25103910a4bb088ec1ddf176fb1b35df606cf35b13"
    )
    assert prefixes["frt25"] == "urn:ref:federal-register-thesaurus:2025-04-01:concept:"
    assert prefixes["elsst6"] == "https://elsst.cessda.eu/id/6/"
    assert {row["predicate_id"] for row in rows} == {"skos:closeMatch"}
    assert {row["mapping_justification"] for row in rows} == {"semapv:MappingReview"}
    assert all(row["subject_label"] and row["object_label"] for row in rows)
    assert {row["mapping_source"] for row in rows} == {pilot_bundle.identifier}
    assert "confidence" not in columns


def test_the_real_pilot_bundle_satisfies_an_independent_reader(pilot_bundle: CrosswalkBundle, tmp_path: Path) -> None:
    pytest.importorskip("sssom")
    from sssom.parsers import parse_sssom_table
    from sssom.validators import SchemaValidationType, validate

    target = write_sssom(pilot_bundle, tmp_path / "pilot.sssom.tsv")
    parsed = parse_sssom_table(str(target))

    assert len(parsed.df) == 121
    assert set(parsed.df["mapping_source"]) == {pilot_bundle.identifier}
    validate(parsed, [SchemaValidationType.JsonSchema, SchemaValidationType.PrefixMapCompleteness])
