"""Contract tests pinning row-level ``mapping_source`` provenance for SSSOM export.

A SeMRA integration spike (``output/semra-fast-spike-2026-08-03/RESULTS.md``,
section "``mapping_source`` is required for multi-source provenance") proved
that set-level SSSOM metadata does not survive mapping fusion: two mapping
sets with different ``mapping_set_id`` but no per-row ``mapping_source``
collapsed to one evidence record. RefSpec's exporter therefore must write
provenance on every row, and that provenance must be recoverable even if the
``#``-commented header block is discarded entirely.

These tests never assume a specific compact-prefix spelling (``frt25:``,
``elsst:``, or otherwise) — prefix names are an interop detail the exporter
may change. Every identifier check goes through the ``curie_map`` parsed out
of the header at run time.
"""

from __future__ import annotations

import csv
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from refspec.atlas import CrosswalkArtifact, CrosswalkBundle, MachineValidation, MappingCandidate

sssom_export = pytest.importorskip("refspec.atlas.sssom_export")

GENERATED_AT = "2026-08-03T12:00:00Z"

# Realistic member shapes from the two real releases this exporter targets:
# Federal Register members are multi-colon URNs, ELSST members are HTTPS IRIs
# with an opaque UUID-shaped local part. Neither format is a SeMRA/SSSOM
# concern; they are exactly what RefSpec's own registries already mint.
_FR_RELEASE = "urn:ref:federal-register-thesaurus:2025-04-01:reference-resource-release:v1"
_FR_CONCEPT_PREFIX = "urn:ref:federal-register-thesaurus:2025-04-01:concept:"
_ELSST_RELEASE = "urn:ref:elsst:reference-resource-release:r6"
_ELSST_CONCEPT_PREFIX = "https://elsst.cessda.eu/id/6/"

# (fr local id, elsst local id, actor suffix, qualifies)
_CANDIDATE_SPECS = (
    ("0001", "4b7b29d8-4044-420f-8e13-9115a98b7918", "alpha", True),
    ("0002", "5185ead6-1c1b-412b-9df2-2422a63faedb", "beta", True),
    ("0003", "ccf910e8-d3c0-4a71-b3d6-056e5eb6affa", "gamma", False),
)


# ---------------------------------------------------------------------------
# synthetic bundle construction
# ---------------------------------------------------------------------------


def _fr_member(local: str) -> str:
    return _FR_CONCEPT_PREFIX + local


def _elsst_member(local: str) -> str:
    return _ELSST_CONCEPT_PREFIX + local


def _build_candidate(
    *,
    source_member: str,
    target_member: str,
    suffix: str,
    qualify: bool,
) -> tuple[MappingCandidate, list[CrosswalkArtifact], list[MachineValidation]]:
    """Seal one FR-to-ELSST candidate, closed against the bundle's own artifacts.

    Two independent machine validations (distinct validator, independence
    group, provider, provider model, and response artifact) qualify the
    candidate; one validation leaves it not-yet-eligible, so a single bundle
    exercises both ``qualified_only`` states.
    """

    context = CrosswalkArtifact.create(
        role="inputContext",
        media_type="application/json",
        content={
            "protocol": "refspec-atlas-model-input-v1",
            "sourceMember": source_member,
            "targetMember": target_member,
        },
    )
    evidence = CrosswalkArtifact.create(
        role="evidence",
        media_type="application/json",
        content={"method": "sealed-label-comparison", "version": "1", "candidateSuffix": suffix},
    )
    input_digest = context.content_digest
    candidate = MappingCandidate.create(
        source_member=source_member,
        source_release=_FR_RELEASE,
        target_member=target_member,
        target_release=_ELSST_RELEASE,
        proposed_relation="http://www.w3.org/2004/02/skos/core#closeMatch",
        generator_kind="aiAgent",
        generator_actor=f"urn:test:sssom:generator:{suffix}",
        generator_provider=f"urn:test:sssom:provider:generator:{suffix}",
        model_id="sssom-fixture-generator",
        model_version="1",
        prompt_template=f"urn:test:sssom:prompt:{suffix}:v1",
        input_context_digest=input_digest,
        temperature="0",
        evidence=[evidence.reference()],
        generated_at=GENERATED_AT,
        seed=1,
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
    artifacts = [context, evidence, request]
    validations: list[MachineValidation] = []

    def _add_validation(tag: str) -> None:
        actor_suffix = f"{suffix}-{tag}"
        response = CrosswalkArtifact.create(
            role="validationResponse",
            media_type="application/json",
            content={
                "candidate": candidate.reference(),
                "inputDigest": input_digest,
                "requestArtifact": request.reference(),
                "validatorActor": f"urn:test:sssom:validator:{actor_suffix}",
                "provider": f"urn:test:sssom:provider:{actor_suffix}",
                "providerModelId": f"provider-model-{actor_suffix}",
                "deterministicChecksPassed": True,
                "outcome": "supports",
            },
        )
        artifacts.append(response)
        validations.append(
            MachineValidation.create(
                candidate=candidate.reference(),
                validator_kind="aiAgent",
                validator_actor=f"urn:test:sssom:validator:{actor_suffix}",
                independence_group=f"urn:test:sssom:group:{actor_suffix}",
                provider=f"urn:test:sssom:provider:{actor_suffix}",
                provider_model_id=f"provider-model-{actor_suffix}",
                sealed_input_digest=input_digest,
                request_artifact=request.reference(),
                response_artifact=response.reference(),
                deterministic_checks_passed=True,
                outcome="supports",
                completed_at=GENERATED_AT,
            )
        )

    _add_validation("a")
    if qualify:
        _add_validation("b")

    return candidate, artifacts, validations


@dataclass(frozen=True, slots=True)
class _Fixture:
    bundle: CrosswalkBundle
    all_candidates: tuple[MappingCandidate, ...]
    qualified_candidates: tuple[MappingCandidate, ...]


def _make_fixture(variant: str) -> _Fixture:
    """Build one small, self-contained crosswalk bundle.

    ``variant`` is folded into every identity field (member local ids,
    actors, providers, prompt template) so two fixtures with different
    variants are never bytewise identical bundles.
    """

    candidates: list[MappingCandidate] = []
    qualified: list[MappingCandidate] = []
    artifacts: list[CrosswalkArtifact] = []
    validations: list[MachineValidation] = []

    for fr_local, elsst_local, suffix, qualify in _CANDIDATE_SPECS:
        candidate, c_artifacts, c_validations = _build_candidate(
            source_member=_fr_member(f"{fr_local}-{variant}"),
            target_member=_elsst_member(f"{elsst_local}-{variant}"),
            suffix=f"{variant}-{suffix}",
            qualify=qualify,
        )
        candidates.append(candidate)
        if qualify:
            qualified.append(candidate)
        artifacts.extend(c_artifacts)
        validations.extend(c_validations)

    bundle = CrosswalkBundle.create(
        artifacts=tuple(artifacts),
        mapping_candidates=tuple(candidates),
        machine_validations=tuple(validations),
    )
    return _Fixture(bundle=bundle, all_candidates=tuple(candidates), qualified_candidates=tuple(qualified))


@pytest.fixture
def fx() -> _Fixture:
    return _make_fixture("primary")


# ---------------------------------------------------------------------------
# TSV and header parsing helpers (no assumption about the exporter's
# compact-prefix spelling anywhere below)
# ---------------------------------------------------------------------------


def _split_header_and_body(text: str) -> tuple[list[str], list[str]]:
    header_lines: list[str] = []
    body_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("#"):
            header_lines.append(line)
        elif line.strip():
            body_lines.append(line)
    return header_lines, body_lines


def _rows_from_body(body_lines: list[str]) -> list[dict[str, str]]:
    assert body_lines, "expected a TSV header row plus at least one mapping row"
    reader = csv.DictReader(body_lines, delimiter="\t")
    rows = list(reader)
    assert reader.fieldnames, "expected a TSV column header row"
    assert rows, "expected at least one mapping row"
    return rows


def _rows(text: str) -> list[dict[str, str]]:
    _, body_lines = _split_header_and_body(text)
    return _rows_from_body(body_lines)


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _parse_flow_mapping(inner: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in inner.split(","):
        if ":" not in part:
            continue
        key, _, value = part.partition(":")
        result[_unquote(key)] = _unquote(value)
    return result


def _parse_header_yaml(header_lines: list[str]) -> dict[str, Any]:
    """Parse the small YAML subset an SSSOM ``#``-commented header uses.

    Handles top-level ``key: value`` lines and ``key:`` followed by an
    indented block of ``key: value`` pairs one level deep (what
    ``mapping_set_id`` and ``curie_map`` need), without a PyYAML dependency
    the project does not otherwise carry. Falls back to inline ``{...}``
    flow mappings too, in case the exporter ever writes curie_map that way.
    """

    root: dict[str, Any] = {}
    current_key: str | None = None
    nested: dict[str, str] | None = None
    for raw_line in header_lines:
        content = raw_line[1:].removeprefix(" ")
        if not content.strip():
            continue
        indent = len(content) - len(content.lstrip(" "))
        stripped = content.strip()
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()
        if indent == 0:
            if value:
                if value.startswith("{") and value.endswith("}"):
                    root[key] = _parse_flow_mapping(value[1:-1])
                else:
                    root[key] = _unquote(value)
                current_key = None
                nested = None
            else:
                nested = {}
                root[key] = nested
                current_key = key
        else:
            if nested is None:
                nested = {}
                if current_key is not None:
                    root[current_key] = nested
            nested[key] = _unquote(value)
    return root


def _parse_header(text: str) -> dict[str, Any]:
    header_lines, _ = _split_header_and_body(text)
    assert header_lines, "expected a '#'-commented YAML metadata header"
    return _parse_header_yaml(header_lines)


def _curie_map(text: str) -> dict[str, str]:
    header = _parse_header(text)
    raw = header.get("curie_map")
    assert isinstance(raw, dict) and raw, f"SSSOM header has no usable curie_map: {header!r}"
    return {str(key): str(value) for key, value in raw.items()}


def _expand_curie(curie: str, curie_map: Mapping[str, str]) -> str:
    prefix, sep, local = curie.partition(":")
    assert sep, f"{curie!r} is not a CURIE"
    assert prefix in curie_map, f"curie_map has no entry for prefix {prefix!r} (from {curie!r})"
    return curie_map[prefix] + local


def _member_pairs(candidates: tuple[MappingCandidate, ...]) -> set[tuple[str, str]]:
    return {
        (candidate.to_dict()["sourceMember"], candidate.to_dict()["targetMember"]) for candidate in candidates
    }


# ---------------------------------------------------------------------------
# 1. every row carries mapping_source
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("qualified_only", [True, False])
def test_every_row_carries_the_bundle_identifier_as_mapping_source(fx: _Fixture, qualified_only: bool) -> None:
    """``mapping_source`` is written as a compacted CURIE like every other

    identifier column (a lesson of its own, from the OAK spike), so "equal to
    ``bundle.identifier``" is checked the same way the identifier round trip
    is: expand through the header's own ``curie_map``, never a hardcoded
    prefix name.
    """

    text = sssom_export.sssom_text(fx.bundle, qualified_only=qualified_only)
    curie_map = _curie_map(text)
    rows = _rows(text)
    for row in rows:
        assert row["mapping_source"], "mapping_source must not be empty"
        assert _expand_curie(row["mapping_source"], curie_map) == fx.bundle.identifier


def test_qualified_only_flag_changes_row_count_but_not_the_provenance_contract(fx: _Fixture) -> None:
    """The fixture has one not-yet-qualified candidate, so the two modes differ."""

    qualified_text = sssom_export.sssom_text(fx.bundle, qualified_only=True)
    full_text = sssom_export.sssom_text(fx.bundle, qualified_only=False)
    qualified_curie_map = _curie_map(qualified_text)
    full_curie_map = _curie_map(full_text)
    qualified_rows = _rows(qualified_text)
    full_rows = _rows(full_text)
    assert len(full_rows) > len(qualified_rows) >= 1
    for row in qualified_rows:
        assert _expand_curie(row["mapping_source"], qualified_curie_map) == fx.bundle.identifier
    for row in full_rows:
        assert _expand_curie(row["mapping_source"], full_curie_map) == fx.bundle.identifier


# ---------------------------------------------------------------------------
# 2. provenance survives header loss
# ---------------------------------------------------------------------------


def test_row_level_mapping_source_survives_full_header_loss(fx: _Fixture) -> None:
    """This is exactly the SeMRA lesson: never rely on set-level metadata.

    Strip every '#' header line — the way a fusion tool that only reads the
    TSV body would see this file, and the way SeMRA read the two mapping sets
    that collapsed to one evidence record — and confirm every remaining row
    still carries a provenance token that is: present, identical across every
    row of *this* bundle's export, and never shared with another bundle's
    export. That combination is exactly what a fusion step needs to keep two
    sources' evidence apart, and it asks nothing of the header this test just
    threw away (recovering the literal bundle IRI from a compacted token is a
    header-parsing concern, covered by the round-trip test instead).
    """

    text = sssom_export.sssom_text(fx.bundle, qualified_only=False)
    header_lines, body_lines = _split_header_and_body(text)
    assert header_lines, "fixture export should actually have a header to strip"

    rows = _rows_from_body(body_lines)
    assert len(rows) == len(fx.all_candidates)
    own_values = {row["mapping_source"] for row in rows}
    assert own_values, "no rows survived header loss"
    assert all(value for value in own_values), "mapping_source must not be empty"
    assert len(own_values) == 1, "mapping_source must be the same bundle-wide token on every row"

    other = _make_fixture("secondary")
    _, other_body_lines = _split_header_and_body(sssom_export.sssom_text(other.bundle, qualified_only=False))
    other_values = {row["mapping_source"] for row in _rows_from_body(other_body_lines)}
    assert own_values.isdisjoint(other_values), "two different bundles must not share a row-level provenance token"


# ---------------------------------------------------------------------------
# 3. lossless identifier round trip through curie_map alone
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("qualified_only", [True, False])
def test_identifier_round_trip_is_lossless_via_curie_map(fx: _Fixture, qualified_only: bool) -> None:
    text = sssom_export.sssom_text(fx.bundle, qualified_only=qualified_only)
    curie_map = _curie_map(text)
    rows = _rows(text)

    observed_pairs = {
        (_expand_curie(row["subject_id"], curie_map), _expand_curie(row["object_id"], curie_map)) for row in rows
    }
    pool = fx.qualified_candidates if qualified_only else fx.all_candidates
    assert observed_pairs == _member_pairs(pool)

    # One side of every pair is a multi-colon URN (the Federal Register
    # member shape); the round trip must restore it exactly through
    # curie_map alone, regardless of what the exporter names that prefix.
    assert any(subject.count(":") >= 3 for subject, _ in observed_pairs)


# ---------------------------------------------------------------------------
# 4. byte-determinism
# ---------------------------------------------------------------------------


def test_export_is_byte_deterministic(fx: _Fixture) -> None:
    for qualified_only in (True, False):
        first = sssom_export.sssom_text(fx.bundle, qualified_only=qualified_only)
        second = sssom_export.sssom_text(fx.bundle, qualified_only=qualified_only)
        assert first == second
        assert _parse_header(first)["mapping_set_id"] == _parse_header(second)["mapping_set_id"]


def test_mapping_set_id_has_no_random_component_across_different_bundles(fx: _Fixture) -> None:
    other = _make_fixture("secondary")
    assert fx.bundle.identifier != other.bundle.identifier

    first_id = _parse_header(sssom_export.sssom_text(fx.bundle, qualified_only=True))["mapping_set_id"]
    other_id = _parse_header(sssom_export.sssom_text(other.bundle, qualified_only=True))["mapping_set_id"]
    assert first_id != other_id
    # Same bundle, called again: still the same id, never a fresh random one.
    repeat_id = _parse_header(sssom_export.sssom_text(fx.bundle, qualified_only=True))["mapping_set_id"]
    assert first_id == repeat_id


# ---------------------------------------------------------------------------
# 5. optional second-implementation parse (isolated so sssom stays optional)
# ---------------------------------------------------------------------------


def test_sssom_py_parses_the_export_and_keeps_row_level_mapping_source(tmp_path: Path, fx: _Fixture) -> None:
    pytest.importorskip("sssom")
    from sssom.parsers import parse_sssom_table

    path = sssom_export.write_sssom(fx.bundle, tmp_path / "crosswalk.sssom.tsv", qualified_only=True)
    msdf = parse_sssom_table(str(path))
    df = msdf.df

    assert len(df) == len(fx.qualified_candidates)
    # sssom-py keeps entity columns compacted in the dataframe too; its own
    # converter (built from the file's curie_map) is the second, independent
    # implementation doing the expansion this time, not this test file's.
    expanded_sources = {msdf.converter.expand(value) for value in df["mapping_source"]}
    assert expanded_sources == {fx.bundle.identifier}
