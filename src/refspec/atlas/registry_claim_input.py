"""Parser-free Atlas input and fidelity comparison for registry claim releases."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, cast

import pyarrow.parquet as pq

from refspec.atlas.parquet_view import verify_atlas_parquet_view
from refspec.atlas.v3_source_data import (
    LabelRole,
    RegistryInputPin,
    RegistryLabel,
    RegistryRelation,
    RegistryRelease,
    RegistryResource,
    RegistrySupplementalSourceRecord,
)
from refspec.registry.infrastructure.registry_claim_release import (
    CLAIMS_FILE,
    MANIFEST_FILE,
    RegistryClaim,
    RegistryClaimReleaseError,
    RegistryClaimReleaseView,
)

ATLAS_CLAIM_RECORD_VERSION = "1.0"
ATLAS_CLAIM_RECORD_TYPE = "RegistryClaimRecord"


class AtlasRegistryClaimError(ValueError):
    """An injected claim bundle or Atlas claim record is invalid."""


@dataclass(frozen=True, slots=True)
class AtlasRegistryClaimInput:
    """One artifact path and its caller-supplied external manifest pin."""

    path: Path
    expected_manifest_digest: str

    def open(self) -> RegistryClaimReleaseView:
        try:
            return RegistryClaimReleaseView.open(
                self.path,
                expected_manifest_digest=self.expected_manifest_digest,
            )
        except RegistryClaimReleaseError as error:
            raise AtlasRegistryClaimError(str(error)) from error


@dataclass(frozen=True, slots=True)
class AtlasSourceClaimRecord:
    """Canonical native payload for source-visible claims in one source record."""

    source_record_id: str
    source_locator: str
    source_digest: str
    native_payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class AtlasRegistryClaimRelease:
    """One verified bundle adapted without a publisher-specific reader."""

    release_id: str
    release_key: str
    manifest_digest: str
    records: tuple[AtlasSourceClaimRecord, ...]


@dataclass(frozen=True, slots=True)
class RegistryClaimResourceRules:
    """Declarative rules for one normalized resource subset of a claim release."""

    member_predicate: str
    member_object_iri: str
    resource_kind: str
    label_roles: Mapping[str, LabelRole]
    excluded_member_claims: Collection[tuple[str, str]] = ()
    notation_predicates: Collection[str] = ()
    native_iri_predicates: Mapping[str, str] = field(default_factory=dict)
    common_native_payload: Mapping[str, Any] = field(default_factory=dict)
    strip_label_whitespace: bool = False


_LABEL_ROLE_ORDER = {"preferred": 0, "alternate": 1, "hidden": 2}


def _compatibility_labels(
    subject: str,
    claims: Sequence[RegistryClaim],
    rules: RegistryClaimResourceRules,
) -> tuple[RegistryLabel, ...]:
    labels = sorted(
        (
            RegistryLabel(
                value=(
                    cast(str, claim.lexical_value).strip()
                    if rules.strip_label_whitespace
                    else cast(str, claim.lexical_value)
                ),
                role=rules.label_roles[claim.predicate],
                source_path=f"{subject}::{claim.predicate}",
            )
            for claim in claims
            if claim.predicate in rules.label_roles
            and claim.object_kind == "literal"
            and claim.language == "en"
        ),
        key=lambda label: (
            _LABEL_ROLE_ORDER[label.role],
            label.value.casefold(),
            label.value,
            label.source_path,
        ),
    )
    retained: list[RegistryLabel] = []
    retained_by_value: dict[str, RegistryLabel] = {}
    for label in labels:
        previous = retained_by_value.get(label.value)
        if previous is None:
            retained_by_value[label.value] = label
            retained.append(label)
        elif previous.role == label.role:
            raise AtlasRegistryClaimError(
                f"claim resource {subject} repeats {label.role} label {label.value!r}"
            )
    if not retained:
        raise AtlasRegistryClaimError(
            f"claim resource {subject} has no selected English label"
        )
    return tuple(retained)


def registry_resources_from_claim_release(
    view: RegistryClaimReleaseView,
    rules: RegistryClaimResourceRules,
) -> tuple[RegistryResource, ...]:
    """Build normalized resources from exact claims using declarative rules."""

    claims_by_subject: dict[str, list[RegistryClaim]] = defaultdict(list)
    membership_claims: dict[str, list[RegistryClaim]] = defaultdict(list)
    for claim in view.claims:
        claims_by_subject[claim.subject].append(claim)
        if (
            claim.predicate == rules.member_predicate
            and claim.object_kind == "iri"
            and claim.object_iri == rules.member_object_iri
        ):
            membership_claims[claim.subject].append(claim)
    excluded_subjects = {
        claim.subject
        for claim in view.claims
        if claim.object_kind == "iri"
        and (claim.predicate, cast(str, claim.object_iri))
        in rules.excluded_member_claims
    }
    for subject in excluded_subjects:
        membership_claims.pop(subject, None)
    if not membership_claims:
        raise AtlasRegistryClaimError(
            "claim resource rules selected no release members"
        )

    resources: list[RegistryResource] = []
    for subject in sorted(membership_claims):
        subject_claims = claims_by_subject[subject]
        source_digests = {
            claim.source_digest for claim in membership_claims[subject]
        }
        if len(source_digests) != 1:
            raise AtlasRegistryClaimError(
                f"claim resource {subject} membership evidence differs"
            )
        notations = tuple(
            sorted(
                {
                    cast(str, claim.lexical_value)
                    for claim in subject_claims
                    if claim.predicate in rules.notation_predicates
                    and claim.object_kind == "literal"
                }
            )
        )
        if rules.notation_predicates and not notations:
            raise AtlasRegistryClaimError(
                f"claim resource {subject} has no selected notation"
            )
        native_payload = {
            **rules.common_native_payload,
            "publisherConceptIri": subject,
            "publisherResourceKind": rules.resource_kind,
        }
        for payload_key, predicate in sorted(rules.native_iri_predicates.items()):
            native_payload[payload_key] = sorted(
                {
                    cast(str, claim.object_iri)
                    for claim in subject_claims
                    if claim.predicate == predicate
                    and claim.object_kind == "iri"
                }
            )
        resources.append(
            RegistryResource(
                iri=subject,
                labels=_compatibility_labels(subject, subject_claims, rules),
                native_payload=native_payload,
                source_locator=subject,
                source_digest=next(iter(source_digests)),
                notations=notations,
                status="active",
            )
        )
    return tuple(resources)


def registry_relations_from_claim_release(
    view: RegistryClaimReleaseView,
    *,
    member_iris: Collection[str],
    predicate_map: Mapping[str, str],
) -> tuple[RegistryRelation, ...]:
    """Retain direct IRI relations whose endpoints are selected members."""

    members = frozenset(member_iris)
    relations: list[RegistryRelation] = []
    seen: set[tuple[str, str, str]] = set()
    for claim in view.claims:
        if (
            claim.object_kind != "iri"
            or claim.predicate not in predicate_map
            or claim.subject not in members
            or claim.object_iri not in members
        ):
            continue
        publisher_predicate = claim.predicate
        normalized_predicate = predicate_map[publisher_predicate]
        key = (
            claim.subject,
            normalized_predicate,
            cast(str, claim.object_iri),
        )
        if key in seen:
            continue
        seen.add(key)
        relations.append(
            RegistryRelation(
                subject=key[0],
                predicate=key[1],
                object=key[2],
                source_payload={
                    "normalizedPredicateIri": normalized_predicate,
                    "objectIri": key[2],
                    "predicateIri": publisher_predicate,
                    "subjectIri": key[0],
                },
            )
        )
    return tuple(
        sorted(
            relations,
            key=lambda relation: (
                relation.subject,
                relation.predicate,
                relation.object,
            ),
        )
    )


def _record_key(claim: RegistryClaim) -> tuple[str, str, str]:
    return (claim.source_record_id, claim.source_locator, claim.source_digest)


def _group_claims(
    claims: Sequence[RegistryClaim],
) -> dict[tuple[str, str, str], list[RegistryClaim]]:
    grouped: dict[tuple[str, str, str], list[RegistryClaim]] = defaultdict(list)
    for claim in claims:
        grouped[_record_key(claim)].append(claim)
    return grouped


def _claim_payload(
    *,
    release_id: str,
    manifest_digest: str,
    claims: Sequence[RegistryClaim],
) -> dict[str, Any]:
    return {
        "claimRelease": release_id,
        "claimReleaseManifestDigest": manifest_digest,
        "claims": [claim.as_record() for claim in claims],
        "schemaVersion": ATLAS_CLAIM_RECORD_VERSION,
        "type": ATLAS_CLAIM_RECORD_TYPE,
    }


def adapt_registry_claim_release(
    input_: AtlasRegistryClaimInput,
) -> AtlasRegistryClaimRelease:
    """Open an injected bundle and group exact claims into Atlas native records."""

    return _adapt_registry_claim_view(input_.open())


def _adapt_registry_claim_view(
    view: RegistryClaimReleaseView,
) -> AtlasRegistryClaimRelease:
    """Adapt an already verified view without reopening its Parquet table."""

    grouped = _group_claims(view.claims)
    records: list[AtlasSourceClaimRecord] = []
    for (record_id, locator, digest), claims in sorted(grouped.items()):
        payload = _claim_payload(
            release_id=cast(str, view.manifest["releaseId"]),
            manifest_digest=view.manifest_digest,
            claims=claims,
        )
        records.append(
            AtlasSourceClaimRecord(
                source_record_id=record_id,
                source_locator=locator,
                source_digest=digest,
                native_payload=payload,
            )
        )
    return AtlasRegistryClaimRelease(
        release_id=cast(str, view.manifest["releaseId"]),
        release_key=cast(str, view.manifest["releaseKey"]),
        manifest_digest=view.manifest_digest,
        records=tuple(records),
    )


def inject_registry_claim_release(
    release: RegistryRelease,
    input_: AtlasRegistryClaimInput,
) -> RegistryRelease:
    """Attach a verified claim bundle to the current normalized compatibility view.

    The existing registry parser still supplies normalized Atlas members during
    parity work.  The injected manifest and Parquet table become additional
    build inputs, while exact claim records enter Atlas source evidence without
    publisher-specific code after the bundle boundary.
    """

    view = input_.open()
    adapted = _adapt_registry_claim_view(view)
    if release.key != adapted.release_key:
        raise AtlasRegistryClaimError(
            "claim release key differs from the normalized compatibility view: "
            f"claims={adapted.release_key}, release={release.key}"
        )
    manifest_path = view.root / MANIFEST_FILE
    claim_table = cast(Mapping[str, Any], view.manifest["claimTable"])
    if claim_table["path"] != CLAIMS_FILE:
        raise AtlasRegistryClaimError("claim table path is unsupported")
    claims_path = view.root / CLAIMS_FILE
    bundle_prefix = f"registry-claim-releases/{release.key}"
    pins = (
        RegistryInputPin(
            path=manifest_path,
            logical_path=f"{bundle_prefix}/{MANIFEST_FILE}",
            sha256=view.manifest_digest,
            byte_length=manifest_path.stat().st_size,
            source_iri=adapted.release_id,
            role="registryClaimManifest",
        ),
        RegistryInputPin(
            path=claims_path,
            logical_path=f"{bundle_prefix}/{CLAIMS_FILE}",
            sha256=cast(str, claim_table["sha256"]),
            byte_length=cast(int, claim_table["byteLength"]),
            source_iri=adapted.release_id + "#claims",
            role="registryClaims",
        ),
    )
    existing_paths = {pin.logical_path for pin in release.inputs}
    if existing_paths & {pin.logical_path for pin in pins}:
        raise AtlasRegistryClaimError(
            f"normalized release {release.key} already carries claim bundle pins"
        )
    supplemental = tuple(
        RegistrySupplementalSourceRecord(
            source_record_id=record.source_record_id,
            source_locator=record.source_locator,
            source_digest=record.source_digest,
            native_payload=record.native_payload,
        )
        for record in adapted.records
    )
    metadata = {
        **release.metadata,
        "registryClaimRelease": {
            "claimCount": len(view.claims),
            "manifestDigest": view.manifest_digest,
            "releaseId": adapted.release_id,
        },
    }
    return replace(
        release,
        inputs=(*release.inputs, *pins),
        supplemental_source_records=supplemental,
        metadata=metadata,
    )


def claims_from_atlas_records(
    records: Sequence[AtlasSourceClaimRecord],
) -> tuple[RegistryClaim, ...]:
    """Convert Atlas source-record payloads back into exact claim rows."""

    claims: list[RegistryClaim] = []
    seen_records: set[tuple[str, str, str]] = set()
    release_pin: tuple[str, str] | None = None
    for index, record in enumerate(records):
        key = (
            record.source_record_id,
            record.source_locator,
            record.source_digest,
        )
        if key in seen_records:
            raise AtlasRegistryClaimError(
                f"Atlas claim records repeat source record {key!r}"
            )
        seen_records.add(key)
        payload = record.native_payload
        if not isinstance(payload, Mapping) or set(payload) != {
            "claimRelease",
            "claimReleaseManifestDigest",
            "claims",
            "schemaVersion",
            "type",
        }:
            raise AtlasRegistryClaimError(
                f"Atlas claim record {index} payload fields are unsupported"
            )
        if (
            payload["type"] != ATLAS_CLAIM_RECORD_TYPE
            or payload["schemaVersion"] != ATLAS_CLAIM_RECORD_VERSION
        ):
            raise AtlasRegistryClaimError(
                f"Atlas claim record {index} type or version is unsupported"
            )
        current_pin = (
            cast(str, payload["claimRelease"]),
            cast(str, payload["claimReleaseManifestDigest"]),
        )
        if release_pin is None:
            release_pin = current_pin
        elif current_pin != release_pin:
            raise AtlasRegistryClaimError(
                "Atlas claim records refer to different release manifests"
            )
        rows = payload["claims"]
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            raise AtlasRegistryClaimError(
                f"Atlas claim record {index} claims must be an array"
            )
        parsed = tuple(
            RegistryClaim.from_record(cast(Mapping[str, Any], row))
            for row in rows
        )
        if not parsed:
            raise AtlasRegistryClaimError(
                f"Atlas claim record {index} contains no claims"
            )
        if parsed != tuple(sorted(parsed, key=RegistryClaim.sort_key)):
            raise AtlasRegistryClaimError(
                f"Atlas claim record {index} claims are not sorted"
            )
        if any(_record_key(claim) != key for claim in parsed):
            raise AtlasRegistryClaimError(
                f"Atlas claim record {index} claim evidence differs from its record"
            )
        if any(claim.release_id != current_pin[0] for claim in parsed):
            raise AtlasRegistryClaimError(
                f"Atlas claim record {index} release ID differs"
            )
        claims.extend(parsed)
    return tuple(sorted(claims, key=RegistryClaim.sort_key))


def _claim_tuple(claim: RegistryClaim) -> tuple[Any, ...]:
    return claim.sort_key()


def _evidence_key(claim: RegistryClaim) -> tuple[str, ...]:
    return (
        claim.release_id,
        claim.source_locator,
        claim.source_path,
        claim.source_digest,
        claim.origin,
        claim.recipe_id,
    )


def _changed_fields(
    expected: RegistryClaim,
    actual: RegistryClaim,
) -> tuple[str, ...]:
    expected_row = expected.as_record()
    actual_row = actual.as_record()
    return tuple(
        key
        for key in expected_row
        if expected_row[key] != actual_row[key]
    )


@dataclass(frozen=True, slots=True)
class ClaimDifference:
    """One missing, added, or evidence-matched changed claim."""

    kind: str
    expected: RegistryClaim | None
    actual: RegistryClaim | None
    changed_fields: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "actual": None if self.actual is None else self.actual.as_record(),
            "changedFields": list(self.changed_fields),
            "expected": (
                None if self.expected is None else self.expected.as_record()
            ),
            "kind": self.kind,
        }


@dataclass(frozen=True, slots=True)
class ClaimComparisonReport:
    """Complete multiset comparison; no difference is hidden by an earlier one."""

    expected_count: int
    actual_count: int
    exact_count: int
    differences: tuple[ClaimDifference, ...]

    @property
    def passed(self) -> bool:
        return not self.differences

    def as_dict(self) -> dict[str, Any]:
        difference_counts = Counter(item.kind for item in self.differences)
        return {
            "actualCount": self.actual_count,
            "differenceCounts": dict(sorted(difference_counts.items())),
            "differences": [item.as_dict() for item in self.differences],
            "exactCount": self.exact_count,
            "expectedCount": self.expected_count,
            "passed": self.passed,
        }


def compare_registry_claims(
    expected: Sequence[RegistryClaim],
    actual: Sequence[RegistryClaim],
) -> ClaimComparisonReport:
    """Perform an exact multiset comparison and collect every difference."""

    expected_by_row = Counter(_claim_tuple(claim) for claim in expected)
    actual_by_row = Counter(_claim_tuple(claim) for claim in actual)
    exact_count = sum((expected_by_row & actual_by_row).values())
    exact_rows = expected_by_row & actual_by_row

    def residual(
        claims: Sequence[RegistryClaim],
        exact: Counter[tuple[Any, ...]],
    ) -> list[RegistryClaim]:
        remaining = exact.copy()
        result: list[RegistryClaim] = []
        for claim in sorted(claims, key=RegistryClaim.sort_key):
            key = _claim_tuple(claim)
            if remaining[key]:
                remaining[key] -= 1
            else:
                result.append(claim)
        return result

    missing = residual(expected, exact_rows)
    added = residual(actual, exact_rows)
    missing_by_evidence: dict[tuple[str, ...], list[RegistryClaim]] = defaultdict(list)
    added_by_evidence: dict[tuple[str, ...], list[RegistryClaim]] = defaultdict(list)
    for claim in missing:
        missing_by_evidence[_evidence_key(claim)].append(claim)
    for claim in added:
        added_by_evidence[_evidence_key(claim)].append(claim)

    differences: list[ClaimDifference] = []
    for evidence in sorted(set(missing_by_evidence) | set(added_by_evidence)):
        expected_rows = sorted(
            missing_by_evidence[evidence],
            key=RegistryClaim.sort_key,
        )
        actual_rows = sorted(
            added_by_evidence[evidence],
            key=RegistryClaim.sort_key,
        )
        paired = min(len(expected_rows), len(actual_rows))
        differences.extend(
            ClaimDifference(
                kind="changed",
                expected=expected_rows[index],
                actual=actual_rows[index],
                changed_fields=_changed_fields(
                    expected_rows[index],
                    actual_rows[index],
                ),
            )
            for index in range(paired)
        )
        differences.extend(
            ClaimDifference(kind="missing", expected=claim, actual=None)
            for claim in expected_rows[paired:]
        )
        differences.extend(
            ClaimDifference(kind="added", expected=None, actual=claim)
            for claim in actual_rows[paired:]
        )
    return ClaimComparisonReport(
        expected_count=len(expected),
        actual_count=len(actual),
        exact_count=exact_count,
        differences=tuple(differences),
    )


def validate_atlas_registry_claims(
    input_: AtlasRegistryClaimInput,
    records: Sequence[AtlasSourceClaimRecord],
) -> ClaimComparisonReport:
    """Compare Atlas source-visible records with one authenticated input bundle."""

    expected = input_.open().claims
    actual = claims_from_atlas_records(records)
    return compare_registry_claims(expected, actual)


def claim_records_from_atlas_parquet_view(
    path: Path,
    *,
    expected_manifest_digest: str,
    claim_release_manifest_digest: str,
) -> tuple[AtlasSourceClaimRecord, ...]:
    """Read claim-bearing source records from one verified Atlas Parquet view."""

    return claim_records_by_release_from_atlas_parquet_view(
        path,
        expected_manifest_digest=expected_manifest_digest,
        claim_release_manifest_digests=(claim_release_manifest_digest,),
    )[claim_release_manifest_digest]


def claim_records_by_release_from_atlas_parquet_view(
    path: Path,
    *,
    expected_manifest_digest: str,
    claim_release_manifest_digests: Collection[str],
) -> Mapping[str, tuple[AtlasSourceClaimRecord, ...]]:
    """Stream claim-bearing source records and group them by injected release."""

    requested = frozenset(claim_release_manifest_digests)
    if not requested:
        raise AtlasRegistryClaimError(
            "at least one claim release manifest digest is required"
        )

    manifest = verify_atlas_parquet_view(
        path,
        expected_manifest_digest=expected_manifest_digest,
    )
    source_member = next(
        (
            member
            for member in manifest["members"]
            if member["role"] == "SourceRecord"
        ),
        None,
    )
    if source_member is None:
        raise AtlasRegistryClaimError(
            "Atlas Parquet view has no SourceRecord table"
        )
    records: dict[str, list[AtlasSourceClaimRecord]] = {
        digest: [] for digest in requested
    }
    parquet = pq.ParquetFile(path / source_member["path"])
    for batch in parquet.iter_batches(
        columns=("native_payload", "source_digest", "source_locator"),
    ):
        for row in batch.to_pylist():
            payload_bytes = row["native_payload"]
            if not isinstance(payload_bytes, bytes):
                raise AtlasRegistryClaimError(
                    "Atlas Parquet source record native payload is not bytes"
                )
            try:
                payload = json.loads(payload_bytes)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise AtlasRegistryClaimError(
                    "Atlas Parquet source record has invalid native JSON"
                ) from error
            if not isinstance(payload, Mapping) or payload.get("type") != (
                ATLAS_CLAIM_RECORD_TYPE
            ):
                continue
            release_digest = payload.get("claimReleaseManifestDigest")
            if release_digest not in requested:
                continue
            claim_rows = payload.get("claims")
            if not isinstance(claim_rows, Sequence) or isinstance(
                claim_rows, (str, bytes)
            ) or not claim_rows:
                raise AtlasRegistryClaimError(
                    "Atlas Parquet claim record has no claim rows"
                )
            first = RegistryClaim.from_record(
                cast(Mapping[str, Any], claim_rows[0])
            )
            source_digest = row["source_digest"]
            if not isinstance(source_digest, bytes) or len(source_digest) != 32:
                raise AtlasRegistryClaimError(
                    "Atlas Parquet claim record source digest is invalid"
                )
            records[cast(str, release_digest)].append(
                AtlasSourceClaimRecord(
                    source_record_id=first.source_record_id,
                    source_locator=cast(str, row["source_locator"]),
                    source_digest="sha256:" + source_digest.hex(),
                    native_payload=cast(Mapping[str, Any], payload),
                )
            )
    return {
        digest: tuple(records[digest])
        for digest in sorted(records)
    }


def validate_atlas_parquet_registry_claims(
    input_: AtlasRegistryClaimInput,
    atlas_view: Path,
    *,
    expected_atlas_view_manifest_digest: str,
) -> ClaimComparisonReport:
    """Compare an authenticated Atlas Parquet view with its injected bundle."""

    records = claim_records_from_atlas_parquet_view(
        atlas_view,
        expected_manifest_digest=expected_atlas_view_manifest_digest,
        claim_release_manifest_digest=input_.expected_manifest_digest,
    )
    return validate_atlas_registry_claims(input_, records)


__all__ = [
    "AtlasRegistryClaimError",
    "AtlasRegistryClaimInput",
    "AtlasRegistryClaimRelease",
    "AtlasSourceClaimRecord",
    "ClaimComparisonReport",
    "ClaimDifference",
    "RegistryClaimResourceRules",
    "adapt_registry_claim_release",
    "claim_records_by_release_from_atlas_parquet_view",
    "claim_records_from_atlas_parquet_view",
    "claims_from_atlas_records",
    "compare_registry_claims",
    "inject_registry_claim_release",
    "registry_relations_from_claim_release",
    "registry_resources_from_claim_release",
    "validate_atlas_parquet_registry_claims",
    "validate_atlas_registry_claims",
]
