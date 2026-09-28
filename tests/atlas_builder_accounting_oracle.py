"""Frozen pre-repair accounting oracle; bound inputs in callers.

Only unchanged model/wire helpers are imported; both replaced checks are copied.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from generate_atlas_v3_full import (
    _SOURCE_CLAIM_ACCOUNTING_REASON,
    _TRANSFORMED_RELATION_ACCOUNTING_REASON,
    ATLAS,
    RKAF,
    LoadedRelease,
    RegistryMappingRelease,
    _accounting_membership_mode,
    _canonical_digest,
    _expected_mapping_asserted_graph,
    _source_record_constructor,
    distribution_identity,
)
from rdflib import URIRef
from rdflib.namespace import RDF


def _mapping_accounting_expectations(
    mapping_releases: Sequence[RegistryMappingRelease],
) -> dict[str, dict[str, set[str]]]:
    """Group exact mapping assertion identities by evidence SourceRecord."""

    graph = _expected_mapping_asserted_graph(mapping_releases)
    expected: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    try:
        for binding in graph.subjects(RDF.type, RKAF.EvidenceBinding):
            assertion = graph.value(binding, RKAF.bindsAssertion)
            record = graph.value(binding, ATLAS.evidenceSourceRecord)
            source_release = graph.value(record, ATLAS.inSourceRelease) if isinstance(record, URIRef) else None
            if not all(isinstance(value, URIRef) for value in (assertion, record, source_release)):
                raise AssertionError("expected mapping evidence lacks assertion or release ownership")
            expected[str(source_release)][str(record)].add(str(assertion))
        return {
            release: {record: set(assertions) for record, assertions in records.items()}
            for release, records in expected.items()
        }
    finally:
        graph.close()


def _validate_compiled_source_accounting(
    releases: Sequence[LoadedRelease],
    accounting: Mapping[str, Any],
    mapping_releases: Sequence[RegistryMappingRelease] = (),
) -> str:
    """Reconcile the generated ledger with the compact source membership."""

    if set(accounting) != {"assertedInventoryDigest", "distributionId", "inputs", "totals", "type", "version"}:
        raise ValueError("compiled producer source accounting fields differ")
    if (
        accounting.get("distributionId") != distribution_identity(accounting)
        or accounting.get("type") != "AtlasSourceAccounting"
        or accounting.get("version") != "3.1"
    ):
        raise ValueError("compiled producer source accounting identity differs")
    inputs = accounting.get("inputs")
    if not isinstance(inputs, list):
        raise TypeError("compiled producer source accounting inputs are not a list")
    rows_by_release: dict[str, Mapping[str, Any]] = {}
    for row in inputs:
        if not isinstance(row, Mapping) or set(row) != {
            "dispositions",
            "membershipMode",
            "sourceRelease",
        }:
            raise ValueError("compiled producer source accounting row fields differ")
        source_release = row.get("sourceRelease")
        if not isinstance(source_release, str) or source_release in rows_by_release:
            raise ValueError("compiled producer source accounting repeats a release")
        rows_by_release[source_release] = row

    expected_releases = {release.source_release_iri for release in releases} | {
        release.source_release_iri for release in mapping_releases
    }
    if set(rows_by_release) != expected_releases:
        raise ValueError("compiled producer source accounting release set differs")

    mapping_expectations = _mapping_accounting_expectations(mapping_releases)
    source_records: set[str] = set()
    represented_total = 0
    excluded_total = 0
    for release in releases:
        row = rows_by_release[release.source_release_iri]
        if row["membershipMode"] != _accounting_membership_mode(release.spec.scope):
            raise ValueError(f"{release.spec.key} source accounting membership mode differs")
        dispositions = row["dispositions"]
        if not isinstance(dispositions, list):
            raise ValueError(f"{release.spec.key} source accounting dispositions are not a list")
        expected_resources = {resource.iri for resource in release.resources}
        represented_resources: set[str] = set()
        excluded = 0
        supplemental_records: set[str] = set()
        for disposition in dispositions:
            if not isinstance(disposition, Mapping):
                raise TypeError(f"{release.spec.key} source accounting disposition is not an object")
            source_record = disposition.get("sourceRecord")
            if (
                not isinstance(source_record, str)
                or not source_record.startswith("urn:ref:atlas-source-record:")
                or source_record in source_records
            ):
                raise ValueError(f"{release.spec.key} source accounting SourceRecord is invalid or repeated")
            source_records.add(source_record)
            status = disposition.get("status")
            if status == "represented":
                if set(disposition) != {
                    "atlasResources",
                    "sourceRecord",
                    "status",
                }:
                    raise ValueError(f"{release.spec.key} represented disposition fields differ")
                resources = disposition.get("atlasResources")
                if not isinstance(resources, list) or len(resources) != 1:
                    raise ValueError(f"{release.spec.key} represented disposition is not one resource")
                resource = resources[0]
                if not isinstance(resource, str) or resource in represented_resources:
                    raise ValueError(f"{release.spec.key} represented resource is invalid or repeated")
                represented_resources.add(resource)
            elif status == "excluded":
                reason = disposition.get("reason")
                if set(disposition) != {"reason", "sourceRecord", "status"} or reason not in {
                    _TRANSFORMED_RELATION_ACCOUNTING_REASON,
                    _SOURCE_CLAIM_ACCOUNTING_REASON,
                }:
                    raise ValueError(f"{release.spec.key} excluded disposition differs")
                if reason == _SOURCE_CLAIM_ACCOUNTING_REASON:
                    supplemental_records.add(source_record)
                excluded += 1
            else:
                raise ValueError(f"{release.spec.key} source accounting status is unsupported")
        if represented_resources != expected_resources:
            raise ValueError(f"{release.spec.key} source accounting resource membership differs")
        expected_transformed = sum(relation.predicate == str(ATLAS.thesaurusRelated) for relation in release.relations)
        expected_supplemental = set()
        for supplemental in release.supplemental_source_records:
            record, _ = _source_record_constructor(
                source_release=URIRef(release.source_release_iri),
                source_locator=URIRef(supplemental.source_locator),
                source_digest=supplemental.source_digest,
                native_payload=supplemental.native_payload,
            )
            expected_supplemental.add(str(record))
        if supplemental_records != expected_supplemental:
            raise ValueError(f"{release.spec.key} supplemental SourceRecord membership differs")
        expected_excluded = expected_transformed + len(expected_supplemental)
        if excluded != expected_excluded:
            raise ValueError(f"{release.spec.key} source accounting excluded count differs")
        represented_total += len(represented_resources)
        excluded_total += excluded

    for mapping_release in mapping_releases:
        row = rows_by_release[mapping_release.source_release_iri]
        if row["membershipMode"] != _accounting_membership_mode(mapping_release.scope):
            raise ValueError(f"{mapping_release.key} mapping source accounting membership mode differs")
        dispositions = row["dispositions"]
        if not isinstance(dispositions, list):
            raise ValueError(f"{mapping_release.key} mapping source accounting dispositions are not a list")
        expected_records = mapping_expectations.get(
            mapping_release.source_release_iri,
            {},
        )
        observed_records: set[str] = set()
        for disposition in dispositions:
            if (
                not isinstance(disposition, Mapping)
                or set(disposition)
                != {
                    "atlasAssertions",
                    "sourceRecord",
                    "status",
                }
                or disposition.get("status") != "represented"
                or not isinstance(disposition.get("atlasAssertions"), list)
            ):
                raise ValueError(f"{mapping_release.key} represented mapping disposition differs")
            source_record = disposition.get("sourceRecord")
            if (
                not isinstance(source_record, str)
                or source_record in source_records
                or source_record in observed_records
            ):
                raise ValueError(f"{mapping_release.key} mapping SourceRecord is invalid or repeated")
            assertions = disposition["atlasAssertions"]
            expected_assertions = expected_records.get(source_record)
            if (
                expected_assertions is None
                or any(not isinstance(assertion, str) for assertion in assertions)
                or len(assertions) != len(set(assertions))
                or set(assertions) != expected_assertions
            ):
                raise ValueError(f"{mapping_release.key} represented mapping assertions differ")
            observed_records.add(source_record)
        if observed_records != set(expected_records):
            raise ValueError(f"{mapping_release.key} mapping SourceRecord membership differs")
        source_records.update(observed_records)
        represented_total += len(observed_records)

    expected_totals = {
        "excluded": excluded_total,
        "represented": represented_total,
        "sourceRecords": represented_total + excluded_total,
        "sourceReleases": len(releases) + len(mapping_releases),
        "unresolved": 0,
    }
    if accounting.get("totals") != expected_totals:
        raise ValueError("compiled producer source accounting totals differ")
    return _canonical_digest(accounting)
