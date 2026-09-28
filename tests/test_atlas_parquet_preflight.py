"""Columnar Atlas Parquet preflight: closed relational view, authenticated pins.

A hand-built closed set of compact tables passes with matching view and
distribution counts, while dangling endpoints, duplicate preferred labels,
stale evidence digests, cross-role or duplicate identities and drifted input
pins all refuse; the authenticated path also normalizes the returned view digest.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pyarrow as pa
import pytest

from refspec.atlas import parquet_preflight
from refspec.atlas.compact_pack import CompactRecordRole
from refspec.atlas.parquet_preflight import (
    APPROVED,
    REVIEW_METHODS,
    AtlasParquetPreflightError,
    validate_atlas_parquet_preflight,
    validate_atlas_parquet_tables,
)
from refspec.atlas.parquet_view import VerifiedAtlasParquetSourceMetadata

REVIEW_ROLE = min(REVIEW_METHODS)


def _tables() -> dict[str, pa.Table]:
    """One closed compact-table set: two resources, one mapping assertion with approved evidence."""

    source_release = "urn:test:source-release"
    atlas_release = "urn:test:atlas-release"
    source_record = "urn:test:source-record"
    first_resource = "urn:test:resource:first"
    second_resource = "urn:test:resource:second"
    statement = "urn:test:statement"
    digest = b"1" * 32
    return {
        CompactRecordRole.RESOURCE.value: pa.table(
            {
                "id": [first_resource, second_resource],
                "release": [atlas_release, atlas_release],
                "scheme": ["urn:test:scheme", "urn:test:scheme"],
                "semantic_ring": ["subject", "subject"],
                "resource_profile": ["conceptScheme", "conceptScheme"],
                "source_record": [source_record, source_record],
            }
        ),
        CompactRecordRole.LABEL.value: pa.table(
            {
                "id": ["urn:test:label:first", "urn:test:label:second"],
                "resource": [first_resource, second_resource],
                "label_role": ["preferred", "preferred"],
                "value": ["First", "Second"],
                "language": ["en", "en"],
                "release": [atlas_release, atlas_release],
                "source_record": [source_record, source_record],
            }
        ),
        CompactRecordRole.STATEMENT.value: pa.table(
            {
                "id": [statement],
                "statement_type": ["NativeRelationAssertion"],
                "subject": [first_resource],
                "predicate": ["http://www.w3.org/2004/02/skos/core#broader"],
                "object": [second_resource],
                "source_release": [atlas_release],
                "target_release": [atlas_release],
                "semantic_ring": ["subject"],
                "source_ring": pa.array([None], type=pa.string()),
                "target_ring": pa.array([None], type=pa.string()),
                "supersedes_assertion": pa.array([None], type=pa.string()),
            }
        ),
        CompactRecordRole.EVIDENCE_BINDING.value: pa.table(
            {
                "id": ["urn:test:evidence"],
                "statement": [statement],
                "source_record": [source_record],
                "evidence_source_digest": [digest],
                "review_method": ["https://refspec.org/ns/atlas/v3#publisherAssertion"],
                "decision": [APPROVED],
                "evidence_role": [REVIEW_ROLE],
            }
        ),
        CompactRecordRole.SOURCE_RECORD.value: pa.table(
            {
                "id": [source_record],
                "source_release": [source_release],
                "content_digest": [digest],
            }
        ),
        CompactRecordRole.RELEASE.value: pa.table(
            {
                "id": [source_release, atlas_release],
                "release_type": ["SourceRelease", "AtlasRelease"],
                "resource_profile": [None, "conceptScheme"],
                "semantic_ring": [None, "subject"],
                "scheme": [None, "urn:test:scheme"],
            }
        ),
        CompactRecordRole.IDENTIFIER.value: pa.table(
            {
                "id": ["urn:test:identifier"],
                "identifier_value": ["FIRST"],
                "identifier_scheme": ["urn:test:identifier-scheme"],
                "identifies": [first_resource],
                "source_record": [source_record],
            }
        ),
        CompactRecordRole.LIFECYCLE_EVENT.value: pa.table({"id": pa.array([], type=pa.string())}),
    }


def _counts(tables: Mapping[str, pa.Table]) -> dict[str, int]:
    """Per-role row counts, the view-side half of the preflight's count check."""

    return {role: table.num_rows for role, table in tables.items()}


def _distribution_counts() -> dict[str, int]:
    """Distribution-side counts matching _tables."""

    return {
        "crossRingRelationAssertions": 0,
        "identifiers": 1,
        "labels": 2,
        "mappingAssertions": 0,
        "nativeRelationAssertions": 1,
        "relationAssertions": 1,
        "releases": 1,
        "resources": 2,
        "sourceAssignments": 0,
        "sourceRecords": 1,
    }


def _replace_column(table: pa.Table, name: str, values: list[object]) -> pa.Table:
    """One table with a single column swapped, for mutation cases."""

    return table.set_column(table.schema.get_field_index(name), name, pa.array(values, type=table[name].type))


def _digest(value: str) -> str:
    """A well-formed sha256 pin whose hex body is one repeated character."""

    return "sha256:" + value * 64


def _verified_parquet_input() -> VerifiedAtlasParquetSourceMetadata:
    """A verified source-metadata stand-in with all six pins well formed."""

    return VerifiedAtlasParquetSourceMetadata(
        root=Path("/test/distribution"),
        manifest={
            "binding": {
                "contractDigest": _digest("1"),
                "ontologyDigest": _digest("2"),
            },
            "canonicalPayloadDigest": _digest("3"),
            "counts": {},
            "distributionId": "urn:test:distribution",
            "graphs": [{"inventoryDigest": _digest("4"), "role": "asserted"}],
            "members": [{"digest": _digest("5"), "role": "constructionSummary"}],
        },
        manifest_digest=_digest("6"),
        construction_summary={},
    )


def test_columnar_preflight_accepts_closed_relational_view() -> None:
    """A closed view passes and reports the release-only checks it defers to the full preflight."""

    tables = _tables()

    result = validate_atlas_parquet_tables(
        tables,
        view_counts=_counts(tables),
        distribution_counts=_distribution_counts(),
    )

    assert result["status"] == "passed"
    assert result["mode"] == "authenticatedColumnarPreflight"
    assert {
        "assertion-policy-identity-and-lifecycle-semantics",
        "closed-json-schema-and-binding-pins",
        "normative-shacl",
        "producer-proof-and-acceptance-receipts",
        "reasoning-isolation",
    } <= set(result["releaseOnlyChecks"])


def test_columnar_preflight_rejects_dangling_statement_endpoint() -> None:
    tables = _tables()
    statements = tables[CompactRecordRole.STATEMENT.value]
    tables[CompactRecordRole.STATEMENT.value] = _replace_column(
        statements,
        "object",
        ["urn:test:missing"],
    )

    with pytest.raises(AtlasParquetPreflightError, match="preflight.statement-object"):
        validate_atlas_parquet_tables(
            tables,
            view_counts=_counts(tables),
            distribution_counts=_distribution_counts(),
        )


def test_columnar_preflight_rejects_duplicate_preferred_language() -> None:
    tables = _tables()
    labels = tables[CompactRecordRole.LABEL.value]
    tables[CompactRecordRole.LABEL.value] = _replace_column(
        labels,
        "resource",
        ["urn:test:resource:first", "urn:test:resource:first"],
    )

    with pytest.raises(AtlasParquetPreflightError, match="preflight.label-preferred-language"):
        validate_atlas_parquet_tables(
            tables,
            view_counts=_counts(tables),
            distribution_counts=_distribution_counts(),
        )


def test_columnar_preflight_rejects_stale_evidence_digest() -> None:
    tables = _tables()
    evidence = tables[CompactRecordRole.EVIDENCE_BINDING.value]
    tables[CompactRecordRole.EVIDENCE_BINDING.value] = _replace_column(
        evidence,
        "evidence_source_digest",
        [b"2" * 32],
    )

    with pytest.raises(AtlasParquetPreflightError, match="preflight.evidence-digest"):
        validate_atlas_parquet_tables(
            tables,
            view_counts=_counts(tables),
            distribution_counts=_distribution_counts(),
        )


def test_columnar_preflight_rejects_cross_role_identity() -> None:
    tables = _tables()
    identifiers = tables[CompactRecordRole.IDENTIFIER.value]
    tables[CompactRecordRole.IDENTIFIER.value] = _replace_column(
        identifiers,
        "id",
        ["urn:test:resource:first"],
    )

    with pytest.raises(AtlasParquetPreflightError, match="preflight.cross-role-identity"):
        validate_atlas_parquet_tables(
            tables,
            view_counts=_counts(tables),
            distribution_counts=_distribution_counts(),
        )


def test_columnar_preflight_rejects_duplicate_identity_within_role() -> None:
    tables = _tables()
    labels = tables[CompactRecordRole.LABEL.value]
    tables[CompactRecordRole.LABEL.value] = _replace_column(
        labels,
        "id",
        ["urn:test:label:duplicate", "urn:test:label:duplicate"],
    )

    with pytest.raises(AtlasParquetPreflightError, match="preflight.label-identity"):
        validate_atlas_parquet_tables(
            tables,
            view_counts=_counts(tables),
            distribution_counts=_distribution_counts(),
        )


def test_columnar_preflight_handles_same_and_cross_ring_relations_together() -> None:
    """Same-ring and cross-ring assertions pass together once releases and counts agree."""

    tables = _tables()
    resources = tables[CompactRecordRole.RESOURCE.value]
    tables[CompactRecordRole.RESOURCE.value] = pa.concat_tables(
        [
            resources,
            pa.table(
                {
                    "id": ["urn:test:resource:third"],
                    "release": ["urn:test:atlas-release:entity"],
                    "scheme": ["urn:test:scheme:entity"],
                    "semantic_ring": ["entity"],
                    "resource_profile": ["conceptScheme"],
                    "source_record": ["urn:test:source-record"],
                }
            ),
        ]
    )
    releases = tables[CompactRecordRole.RELEASE.value]
    tables[CompactRecordRole.RELEASE.value] = pa.concat_tables(
        [
            releases,
            pa.table(
                {
                    "id": ["urn:test:atlas-release:entity"],
                    "release_type": ["AtlasRelease"],
                    "resource_profile": ["conceptScheme"],
                    "semantic_ring": ["entity"],
                    "scheme": ["urn:test:scheme:entity"],
                }
            ),
        ]
    )
    statements = tables[CompactRecordRole.STATEMENT.value]
    tables[CompactRecordRole.STATEMENT.value] = pa.concat_tables(
        [
            statements,
            pa.table(
                {
                    "id": ["urn:test:statement:cross-ring"],
                    "statement_type": ["CrossRingRelationAssertion"],
                    "subject": ["urn:test:resource:first"],
                    "predicate": ["urn:test:related"],
                    "object": ["urn:test:resource:third"],
                    "source_release": ["urn:test:atlas-release"],
                    "target_release": ["urn:test:atlas-release:entity"],
                    "semantic_ring": pa.array([None], type=pa.string()),
                    "source_ring": ["subject"],
                    "target_ring": ["entity"],
                    "supersedes_assertion": pa.array([None], type=pa.string()),
                }
            ),
        ]
    )
    evidence = tables[CompactRecordRole.EVIDENCE_BINDING.value]
    tables[CompactRecordRole.EVIDENCE_BINDING.value] = pa.concat_tables(
        [
            evidence,
            pa.table(
                {
                    "id": ["urn:test:evidence:cross-ring"],
                    "statement": ["urn:test:statement:cross-ring"],
                    "source_record": ["urn:test:source-record"],
                    "evidence_source_digest": [b"1" * 32],
                    "review_method": ["https://refspec.org/ns/atlas/v3#publisherAssertion"],
                    "decision": [APPROVED],
                "evidence_role": [REVIEW_ROLE],
                    }
            ),
        ]
    )
    distribution_counts = {
        **_distribution_counts(),
        "crossRingRelationAssertions": 1,
        "relationAssertions": 2,
        "releases": 2,
        "resources": 3,
    }

    result = validate_atlas_parquet_tables(
        tables,
        view_counts=_counts(tables),
        distribution_counts=distribution_counts,
    )

    assert result["status"] == "passed"


def test_authenticated_preflight_rejects_drift_in_any_input_pin(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A tampered ontology digest in the view's input pin refuses as preflight.input-pin."""

    verified_input = _verified_parquet_input()
    view_input_pin = verified_input.view_input_pin
    view_input_pin["ontologyDigest"] = _digest("8")
    view_manifest = {
        "counts": {},
        "input": view_input_pin,
        "members": [],
        "viewId": "urn:test:view",
    }
    monkeypatch.setattr(
        parquet_preflight,
        "verify_atlas_parquet_source_metadata",
        lambda *_args, **_kwargs: verified_input,
    )
    monkeypatch.setattr(
        parquet_preflight,
        "verify_atlas_parquet_view",
        lambda *_args, **_kwargs: view_manifest,
    )

    with pytest.raises(AtlasParquetPreflightError, match="preflight.input-pin"):
        validate_atlas_parquet_preflight(
            tmp_path / "distribution",
            tmp_path / "view",
            expected_distribution_manifest_digest=_digest("6"),
            expected_view_manifest_digest=_digest("9"),
        )


def test_authenticated_preflight_normalizes_returned_view_digest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A bare hex view digest is returned in canonical sha256: spelling."""

    verified_input = _verified_parquet_input()
    view_manifest = {
        "counts": {},
        "input": verified_input.view_input_pin,
        "members": [],
        "viewId": "urn:test:view",
    }
    monkeypatch.setattr(
        parquet_preflight,
        "verify_atlas_parquet_source_metadata",
        lambda *_args, **_kwargs: verified_input,
    )
    monkeypatch.setattr(
        parquet_preflight,
        "verify_atlas_parquet_view",
        lambda *_args, **_kwargs: view_manifest,
    )
    monkeypatch.setattr(
        parquet_preflight,
        "validate_atlas_parquet_tables",
        lambda *_args, **_kwargs: {"status": "passed"},
    )

    view_digest = "9" * 64
    result = validate_atlas_parquet_preflight(
        tmp_path / "distribution",
        tmp_path / "view",
        expected_distribution_manifest_digest=_digest("6"),
        expected_view_manifest_digest=view_digest,
    )

    assert result["viewManifestDigest"] == "sha256:" + view_digest


# Malformed nullable enumeration values cannot occur in the authenticated
# non-null schema. The table API now emits its normal typed refusal instead
# of crashing while the former checker sorted mixed None/string values.
# Both implementations reject; this is an explicit diagnostic change only.
EXPECTED_ORACLE_DIVERGENCES = {
    f"{base}/{role}/{column}/None{suffix}": ("TypeError", f"preflight.{code}")
    for base, suffixes in (("real", ("", "/parquet")), ("synthetic", ("",)))
    for suffix in suffixes
    for role, column, code in (("Release", "release_type", "release-type"), ("Label", "label_role", "label-role"))
}


def _observed_distribution_counts(tables: Mapping[str, pa.Table]) -> dict[str, int]:
    from collections import Counter

    counts = Counter(tables["Statement"]["statement_type"].to_pylist())
    return {
        **{
            name: tables[role].num_rows if role in tables else 0
            for name, role in (
                ("resources", "Resource"),
                ("labels", "Label"),
                ("sourceRecords", "SourceRecord"),
                ("identifiers", "Identifier"),
                ("relationAssertions", "Statement"),
            )
        },
        "releases": tables["Release"]["release_type"].to_pylist().count("AtlasRelease"),
        **{
            name: counts[kind]
            for name, kind in (
                ("mappingAssertions", "MappingAssertion"),
                ("nativeRelationAssertions", "NativeRelationAssertion"),
                ("crossRingRelationAssertions", "CrossRingRelationAssertion"),
                ("sourceAssignments", "SourceAssignment"),
            )
        },
    }


def test_duckdb_matches_copied_arrow_oracle_on_real_rows_and_mutations(tmp_path: Path) -> None:
    """Retained publisher-derived rows and field mutations exercise both input paths."""
    import atlas_parquet_preflight_oracle as oracle
    import pyarrow.parquet as pq

    fixture = Path(__file__).parent / "fixtures" / "atlas_parquet_preflight"
    real = {path.stem: pq.read_table(path) for path in sorted(fixture.glob("*.parquet"))}
    assert len(real) == len(CompactRecordRole)
    cases = {"real": real, "synthetic": _tables()}
    # Check null propagation, every foreign key, profiles, authority scope,
    # statement rings/types, supersession and immutable evidence semantics.
    columns = {
        "Resource": ("id", "release", "scheme", "semantic_ring", "resource_profile", "source_record"),
        "Label": ("id", "resource", "source_record", "release", "label_role", "language", "value"),
        "Statement": (
            "id",
            "statement_type",
            "subject",
            "object",
            "source_release",
            "target_release",
            "semantic_ring",
            "source_ring",
            "target_ring",
            "supersedes_assertion",
        ),
        "EvidenceBinding": ("id", "statement", "source_record", "evidence_source_digest", "decision", "evidence_role"),
        "SourceRecord": ("id", "source_release", "content_digest"),
        "Release": ("id", "release_type", "scheme", "semantic_ring", "resource_profile"),
        "Identifier": ("id", "identifies", "source_record", "identifier_scheme", "identifier_value"),
    }
    for base_name, base in list(cases.items()):
        for role, names in columns.items():
            table = base[role]
            if not table.num_rows:
                continue
            for column in names:
                for value in (
                    None,
                    b"x" * 32
                    if pa.types.is_binary(table[column].type) or pa.types.is_fixed_size_binary(table[column].type)
                    else "urn:unknown",
                ):
                    values = table[column].to_pylist()
                    values[0] = value
                    changed = table.set_column(
                        table.schema.get_field_index(column), column, pa.array(values, type=table[column].type)
                    )
                    cases[f"{base_name}/{role}/{column}/{value!r}"] = {**base, role: changed}
            cases[f"{base_name}/{role}/duplicate-id"] = {**base, role: pa.concat_tables([table, table.slice(0, 1)])}
        cases[f"{base_name}/cross-role-id"] = {
            **base,
            "LifecycleEvent": pa.table({"id": [base["Resource"]["id"][0].as_py()]}),
        }
        cases[f"{base_name}/missing-evidence"] = {**base, "EvidenceBinding": base["EvidenceBinding"].slice(0, 0)}
        cases[f"{base_name}/missing-role"] = {key: value for key, value in base.items() if key != "Label"}
        cases[f"{base_name}/unknown-role"] = {**base, "Unknown": pa.table({"id": []})}
        cases[f"{base_name}/derived-counts"] = {**base, "derivedRelations": pa.table({"subject": ["a"]})}

    base = _tables()
    # Matched null/null must reject just as Arrow's filled-null masks did.
    cases["null-null-profile"] = {
        **base,
        "Resource": _replace_column(base["Resource"], "semantic_ring", [None, None]),
        "Release": _replace_column(base["Release"], "semantic_ring", [None, None]),
    }
    for kind in ("SourceAssignment", "CrossRingRelationAssertion", "MappingAssertion"):
        statement = _replace_column(base["Statement"], "statement_type", [kind])
        if kind == "SourceAssignment":
            statement = _replace_column(statement, "subject", [base["SourceRecord"]["id"][0].as_py()])
            statement = _replace_column(
                statement, "source_release", [base["SourceRecord"]["source_release"][0].as_py()]
            )
        cases[kind] = {**base, "Statement": statement}
        for column in ("subject", "object", "source_release", "target_release", "semantic_ring"):
            cases[f"{kind}/{column}"] = {**base, "Statement": _replace_column(statement, column, ["urn:unknown"])}
    cases["self-supersession"] = {
        **base,
        "Statement": _replace_column(base["Statement"], "supersedes_assertion", [base["Statement"]["id"][0].as_py()]),
    }
    labels = base["Label"]
    cases["preferred-language-duplicate"] = {
        **base,
        "Label": _replace_column(labels, "resource", [labels["resource"][0].as_py()] * 2),
    }
    overlap = _replace_column(cases["preferred-language-duplicate"]["Label"], "label_role", ["preferred", "alternate"])
    cases["label-role-overlap"] = {**base, "Label": _replace_column(overlap, "value", ["First", "First"])}
    identifier = base["Identifier"]
    other = _replace_column(identifier, "id", ["urn:other-identifier"])
    other = _replace_column(other, "identifies", [base["Resource"]["id"][1].as_py()])
    cases["identifier-authority-conflict"] = {**base, "Identifier": pa.concat_tables([identifier, other])}

    cases["view-count-drift"] = base
    cases["distribution-count-drift"] = base
    # A valid cross-ring pair lets mutations reach both ring comparisons.
    cross_resources = _replace_column(base["Resource"], "semantic_ring", ["subject", "entity"])
    cross_resources = _replace_column(cross_resources, "release", ["urn:test:atlas-release", "urn:test:entity-release"])
    release = base["Release"].slice(1, 1)
    release = _replace_column(release, "id", ["urn:test:entity-release"])
    release = _replace_column(release, "semantic_ring", ["entity"])
    cross_statement = _replace_column(base["Statement"], "statement_type", ["CrossRingRelationAssertion"])
    for column, value in (
        ("target_release", "urn:test:entity-release"),
        ("semantic_ring", None),
        ("source_ring", "subject"),
        ("target_ring", "entity"),
    ):
        cross_statement = _replace_column(cross_statement, column, [value])
    cross = {
        **base,
        "Resource": cross_resources,
        "Release": pa.concat_tables([base["Release"], release]),
        "Statement": cross_statement,
        "Label": _replace_column(base["Label"], "release", ["urn:test:atlas-release", "urn:test:entity-release"]),
    }
    cases["valid-cross-ring"] = cross
    for column in ("source_ring", "target_ring", "semantic_ring"):
        for value in (None, "wrong"):
            cases[f"cross-ring/{column}/{value}"] = {
                **cross,
                "Statement": _replace_column(cross_statement, column, [value]),
            }

    disagreements = {}
    for name, tables in cases.items():
        kwargs = {"view_counts": _counts(tables), "distribution_counts": _observed_distribution_counts(tables)}

        if name == "view-count-drift":
            kwargs["view_counts"] = {**kwargs["view_counts"], "Resource": -1}
        if name == "distribution-count-drift":
            kwargs["distribution_counts"] = {**kwargs["distribution_counts"], "resources": -1}

        def verdict(check, inputs, kwargs=kwargs):
            try:
                return check(inputs, **kwargs)
            except (AtlasParquetPreflightError, oracle.AtlasParquetPreflightError) as error:
                return error.code
            except TypeError:
                return "TypeError"

        expected = verdict(oracle.validate_atlas_parquet_tables, tables)
        actual = verdict(validate_atlas_parquet_tables, tables)
        if actual != expected:
            disagreements[name] = (expected, actual)
        # The real input plus its mutations also exercise file scans. The
        # larger synthetic battery above covers authority identifiers absent
        # from this publisher's data.
        if name.startswith("real"):
            paths = {}
            for role, table in tables.items():
                paths[role] = tmp_path / f"{role}.parquet"
                pq.write_table(table, paths[role])
            parquet_actual = verdict(validate_atlas_parquet_tables, paths)
            if parquet_actual != expected:
                disagreements[name + "/parquet"] = (expected, parquet_actual)
    assert disagreements == EXPECTED_ORACLE_DIVERGENCES
