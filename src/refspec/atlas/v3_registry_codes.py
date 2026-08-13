"""Load exact small registry code sets into normalized Atlas 3 source data.

The registry modules remain responsible for publisher-specific parsing and
source-drift checks.  This adapter only turns their verified results into the
small immutable model consumed by the Atlas 3 writer.  It never creates
cross-source mappings and never treats a source-controlled observation as a
publisher concept IRI.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date
from pathlib import Path
from typing import Any, cast

from refspec.atlas.v3_registry_selection import (
    normalize_only_keys,
    select_declared_group,
    wants_group,
)
from refspec.atlas.v3_source_data import (
    RegistryInputPin,
    RegistryLabel,
    RegistryRelease,
    RegistryResource,
    canonical_digest,
)
from refspec.immutable import deep_freeze_json
from refspec.registry.infrastructure.source_controlled_resource import (
    SourceControlledResourceBundle,
)
from refspec.registry.infrastructure.source_identity import derive_uuid7
from refspec.vocabulary import is_english_language_tag

_SOURCE_TOKEN = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class _Item:
    """One parser result before its source-local Atlas identity is assigned."""

    label: str
    source_path: str
    notations: tuple[str, ...]
    native_payload: Mapping[str, Any]
    definition: str | None = None
    status: str | None = None


def _token_fragment(value: str) -> str:
    return _CAMEL_BOUNDARY.sub("-", value).replace("_", "-").lower()


def _json_value(value: Any) -> Any:
    """Return a JSON-safe copy of a registry parser value."""

    if is_dataclass(value) and not isinstance(value, type):
        return _json_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_value(child) for key, child in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(child) for child in value]
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _input_pin(
    repo_root: Path,
    logical_path: str,
    *,
    source_iri: str,
    sha256: str,
    byte_length: int,
    role: str = "publisherSource",
) -> RegistryInputPin:
    pin = RegistryInputPin(
        path=repo_root / logical_path,
        logical_path=logical_path,
        sha256=sha256,
        byte_length=byte_length,
        source_iri=source_iri,
        role=role,
    )
    pin.verify()
    return pin


def _mint_resource_iri(
    *,
    source_token: str,
    issued: str,
    source_locator: str,
    source_path: str,
    notations: Sequence[str],
    identity_hint: str,
) -> str:
    if _SOURCE_TOKEN.fullmatch(source_token) is None:
        raise ValueError(f"invalid readable source token: {source_token!r}")
    seed = json.dumps(
        {
            "source": source_locator,
            "path": source_path,
            "notations": list(notations),
            "identityHint": identity_hint,
        },
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    uuid = derive_uuid7(issued, seed=seed)
    return f"urn:ref:source-concept:v2:{source_token}:{uuid}"


def _release(
    *,
    key: str,
    resource_id: str,
    source_module: str,
    source_token: str,
    profile: str,
    ring: str,
    scope: str,
    issued: str,
    inputs: Sequence[RegistryInputPin],
    items: Sequence[_Item],
    source_release_digest: str | None = None,
    source_digests: Mapping[str, str] | None = None,
) -> RegistryRelease:
    if not inputs:
        raise ValueError(f"registry release {key} has no exact inputs")
    if not items:
        raise ValueError(f"registry release {key} parsed no resources")
    recorded_at = issued if "T" in issued else f"{issued}T00:00:00Z"
    issued_date = issued[:10]
    try:
        date.fromisoformat(issued_date)
    except ValueError as error:
        raise ValueError(f"registry release {key} has an invalid issued date") from error
    digest_by_source = {pin.source_iri: pin.sha256 for pin in inputs}
    if source_digests is not None:
        digest_by_source.update(source_digests)
    resources: list[RegistryResource] = []
    seen_iris: set[str] = set()
    for item in items:
        if item.source_path == "" or not item.label.strip():
            raise ValueError(f"registry release {key} has an incomplete source row")
        source_locator = str(item.native_payload.get("sourceArtifact", inputs[0].source_iri))
        source_digest = digest_by_source.get(source_locator)
        if source_digest is None:
            raise ValueError(f"registry release {key} row points outside its exact inputs: {source_locator}")
        iri = _mint_resource_iri(
            source_token=source_token,
            issued=recorded_at,
            source_locator=source_locator,
            source_path=item.source_path,
            notations=item.notations,
            identity_hint=str(item.native_payload.get("id", item.label)),
        )
        if iri in seen_iris:
            raise ValueError(f"registry release {key} produced duplicate identity {iri}")
        seen_iris.add(iri)
        resources.append(
            RegistryResource(
                iri=iri,
                labels=(
                    RegistryLabel(
                        value=item.label.strip(),
                        role="preferred",
                        source_path=item.source_path,
                    ),
                ),
                native_payload=cast(
                    Mapping[str, Any],
                    deep_freeze_json(_json_value(item.native_payload)),
                ),
                source_locator=source_locator,
                source_digest=source_digest,
                definition=item.definition.strip() if item.definition else None,
                notations=tuple(dict.fromkeys(value for value in item.notations if value)),
                status=item.status,
            )
        )
    release_digest = source_release_digest or canonical_digest(
        {
            "key": key,
            "inputs": [
                {
                    "logicalPath": pin.logical_path,
                    "sha256": pin.sha256,
                    "byteLength": pin.byte_length,
                    "sourceIri": pin.source_iri,
                }
                for pin in inputs
            ],
            "resources": [resource.iri for resource in resources],
        }
    )
    if _DIGEST.fullmatch(release_digest) is None:
        raise ValueError(f"registry release {key} has an invalid source release digest")
    digest_token = release_digest.removeprefix("sha256:")
    return RegistryRelease(
        key=key,
        resource_id=resource_id,
        source_module=source_module,
        profile=profile,
        ring=ring,
        scope=scope,  # type: ignore[arg-type]
        issued=issued_date,
        source_release_iri=f"urn:ref:registry-release:{source_token}:{digest_token}",
        source_release_digest=release_digest,
        atlas_release_iri=f"urn:ref:atlas-release:v3:{source_token}:{digest_token}",
        scheme_iri=f"urn:ref:atlas-resource-scheme:{resource_id}",
        inputs=tuple(inputs),
        resources=tuple(resources),
    )


def _bundle_release(
    bundle: SourceControlledResourceBundle,
    *,
    key: str,
    resource_id: str,
    source_module: str,
    source_token: str,
    profile: str,
    ring: str,
    scope: str,
    inputs: Sequence[RegistryInputPin],
    expected_count: int,
) -> RegistryRelease:
    """Normalize a verified source-controlled package without changing identity claims."""

    if len(bundle.observations) != expected_count:
        raise ValueError(
            f"registry release {key} count drift: expected {expected_count}, parsed {len(bundle.observations)}"
        )
    bundle_source_digests = _bundle_source_digests(bundle)
    issued = str(bundle.resource_manifest["capturedAt"])
    items = _bundle_items(bundle.observations, key=key)
    return _release(
        key=key,
        resource_id=resource_id,
        source_module=source_module,
        source_token=source_token,
        profile=profile,
        ring=ring,
        scope=scope,
        issued=issued,
        inputs=inputs,
        items=items,
        source_release_digest=bundle.logical_digest,
        source_digests=bundle_source_digests,
    )


def _bundle_source_digests(bundle: SourceControlledResourceBundle) -> dict[str, str]:
    return {
        source_iri: "sha256:" + hashlib.sha256(payload).hexdigest()
        for source_iri, payload in bundle.source_artifacts.items()
    }


def _bundle_items(
    observations: Sequence[Mapping[str, Any]],
    *,
    key: str,
) -> tuple[_Item, ...]:
    items: list[_Item] = []
    for observation in observations:
        labels_by_value = {
            str(row["value"]): row
            for row in observation["labels"]
            if isinstance(row, Mapping)
            and isinstance(row.get("language"), str)
            and is_english_language_tag(cast(str, row["language"]))
            and row.get("role") == "preferred"
        }
        if len(labels_by_value) != 1:
            raise ValueError(
                f"registry release {key} row {observation['sourcePath']} must have one preferred English label"
            )
        label = next(iter(labels_by_value))
        identifiers = observation.get("identifiers", ())
        notations = tuple(
            str(identifier["value"])
            for identifier in identifiers
            if isinstance(identifier, Mapping) and identifier.get("value") not in (None, "")
        )
        definition = observation.get("description") or observation.get("definition")
        retired = observation.get("retired")
        items.append(
            _Item(
                label=label,
                source_path=str(observation["sourcePath"]),
                notations=notations,
                native_payload=observation,
                definition=str(definition) if isinstance(definition, str) else None,
                status="retired" if retired is True else "active" if retired is False else None,
            )
        )
    return tuple(items)


def _acquire(
    function: Callable[..., Any],
    pin: Any,
    source_path: Path,
    temporary: Path,
) -> Any:
    return function(pin, temporary, source_path=source_path)


def _identifier_values(code: Any) -> tuple[str, ...]:
    return tuple(str(identifier.value) for identifier in code.identifiers)


def _stamp_source_artifact(native: dict[str, Any], source_iri: str) -> dict[str, Any]:
    """Record the artifact a record came from, and the medium it was read through.

    PDF is not a data format. Reading a code list out of one means reconstructing
    columns from a text layer that encodes typography rather than structure, and
    every unit sourced that way in this registry has shown it: ligatures and
    U+2010 hyphens copied verbatim, four-column tables arriving space-joined,
    description cells merged across rows. Those are properties of the medium, not
    mistakes a consumer can be expected to anticipate. Stamping the medium makes
    the caveat travel with the data instead of living in a reviewer's memory --
    a consumer that sees `sourceMedium: pdf` knows to treat the text with more
    suspicion than it would a JSON field. Derived from the artifact itself so a
    new PDF-backed unit cannot forget to declare it.
    """

    native["sourceArtifact"] = source_iri
    if source_iri.split("?", 1)[0].rstrip("/").lower().endswith(".pdf"):
        native["sourceMedium"] = "pdf"
    return native


def _code_items(codes: Iterable[Any], *, resource_name: str, source_iri: str) -> tuple[_Item, ...]:
    items: list[_Item] = []
    for ordinal, code in enumerate(codes):
        notations = _identifier_values(code)
        label = str(code.publisher_label)
        native = _json_value(code)
        _stamp_source_artifact(native, source_iri)
        definition = getattr(code, "description", None)
        items.append(
            _Item(
                label=label,
                source_path=f"$.{resource_name}[{ordinal}]",
                notations=notations,
                native_payload=native,
                definition=definition if isinstance(definition, str) else None,
                status=(
                    "retired"
                    if getattr(code, "retired", None) is True
                    else "active"
                    if getattr(code, "retired", None) is False
                    else None
                ),
            )
        )
    return tuple(items)


def _load_census(repo_root: Path, temporary: Path) -> tuple[RegistryRelease, ...]:
    from refspec.registry import census_gov_finance_codes as source

    rows = (
        (
            "census-function-items",
            "census-aspep-function-item-codes",
            "census-aspep-function-items",
            source.CENSUS_FUNCTION_ITEM_CODES_2026_08_03,
            "tests/fixtures/census_gov_finance_codes/census-aspep-function-item-codes-2026-08-03.html",
            source.parse_census_function_item_codes,
            source.build_census_function_item_code_package,
            33,
        ),
        (
            "census-data-flags",
            "census-aspep-data-flags",
            "census-aspep-data-flags",
            source.CENSUS_DATA_FLAG_CODES_2026_08_03,
            "tests/fixtures/census_gov_finance_codes/census-aspep-data-flag-codes-2026-08-03.html",
            source.parse_census_data_flag_codes,
            source.build_census_data_flag_code_package,
            16,
        ),
        (
            "nasbo-program-areas",
            "nasbo-state-expenditure-program-areas",
            "nasbo-program-areas",
            source.NASBO_PROGRAM_AREA_CHAPTERS_2026_08_03,
            "tests/fixtures/census_gov_finance_codes/nasbo-ser-program-area-chapters-2026-08-03.html",
            source.parse_nasbo_program_area_chapters,
            source.build_nasbo_program_area_chapter_package,
            7,
        ),
    )
    releases: list[RegistryRelease] = []
    for key, resource_id, token, pin, logical_path, parser, builder, count in rows:
        input_pin = _input_pin(
            repo_root,
            logical_path,
            source_iri=pin.source.source_url,
            sha256=pin.expected_sha256,
            byte_length=pin.expected_byte_length,
        )
        acquired = _acquire(source.acquire_census_nasbo_page, pin, input_pin.path, temporary / key)
        bundle = builder(acquired, parser(acquired))
        releases.append(
            _bundle_release(
                bundle,
                key=key,
                resource_id=resource_id,
                source_module="refspec.registry.census_gov_finance_codes",
                source_token=token,
                profile=("conceptScheme" if resource_id == "nasbo-state-expenditure-program-areas" else "codeScheme"),
                ring="value",
                scope="completeCapture",
                inputs=(input_pin,),
                expected_count=count,
            )
        )
    return tuple(releases)


def _load_census_geo(repo_root: Path, temporary: Path) -> tuple[RegistryRelease, ...]:
    from refspec.registry import census_geo_codes as source

    page_rows = (
        (
            source.ACS_GEOGRAPHY_AND_PREDICATE_SPAN_2026_08_03,
            "tests/fixtures/census_geo_codes/acs-variables-2026-08-03.html",
            "census-acs-variables-page",
        ),
        (
            source.ACS_S0201_ESTIMATE_VARIABLES_SPAN_2026_08_03,
            "tests/fixtures/census_geo_codes/acs-variables-2026-08-03.html",
            "census-acs-variables-page",
        ),
        (
            source.GEOID_STRUCTURE_TABLE_SPAN_2026_08_03,
            "tests/fixtures/census_geo_codes/geoid-structure-2026-08-03.html",
            "census-geoid-guidance-page",
        ),
        (
            source.GEOID_DOWNLOAD_EXAMPLE_TABLE_SPAN_2026_08_03,
            "tests/fixtures/census_geo_codes/geoid-structure-2026-08-03.html",
            "census-geoid-guidance-page",
        ),
    )
    full_page_inputs: dict[str, RegistryInputPin] = {}
    acquired_spans: list[Any] = []
    for index, (pin, logical_path, input_key) in enumerate(page_rows):
        if input_key not in full_page_inputs:
            payload = (repo_root / logical_path).read_bytes()
            full_page_inputs[input_key] = _input_pin(
                repo_root,
                logical_path,
                source_iri=pin.span.page_url,
                sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
                byte_length=len(payload),
                role="publisherPageContainingPinnedSpan",
            )
        acquired_spans.append(
            _acquire(
                source.acquire_census_geo_html_span,
                pin,
                full_page_inputs[input_key].path,
                temporary / f"census-geo-{index}",
            )
        )
    gnis_pin = source.GNIS_FILE_FORMAT_PIN_2026_08_03
    gnis_input = _input_pin(
        repo_root,
        "tests/fixtures/census_geo_codes/gnis-file-format-2026-08-03.pdf",
        source_iri=gnis_pin.source_url,
        sha256=gnis_pin.expected_sha256,
        byte_length=gnis_pin.expected_byte_length,
    )
    gnis = _acquire(
        source.acquire_gnis_file_format,
        gnis_pin,
        gnis_input.path,
        temporary / "census-geo-gnis",
    )
    bundle = source.build_census_geo_identifier_authority_package(
        *acquired_spans,
        gnis,
    )
    source_digests = _bundle_source_digests(bundle)
    groups = (
        (
            "census-acs-geography-identifiers",
            "census-acs-geography",
            lambda iri: iri.startswith(source.CENSUS_ACS_VARIABLES_AUTHORITY_URI),
            (full_page_inputs["census-acs-variables-page"],),
            7,
        ),
        (
            "census-tiger-geoid-structure",
            "census-tiger-geoid",
            lambda iri: iri.startswith(source.CENSUS_GEOID_GUIDANCE_URL),
            (full_page_inputs["census-geoid-guidance-page"],),
            14,
        ),
        (
            "usgs-gnis-identifiers",
            "usgs-gnis-identifiers",
            lambda iri: iri == source.GNIS_FILE_FORMAT_PDF_URL,
            (gnis_input,),
            3,
        ),
    )
    releases: list[RegistryRelease] = []
    for resource_id, token, selector, inputs, expected_count in groups:
        observations = tuple(
            observation for observation in bundle.observations if selector(str(observation["sourceArtifact"]))
        )
        if len(observations) != expected_count:
            raise ValueError(f"{resource_id} count drifted")
        releases.append(
            _release(
                key=resource_id,
                resource_id=resource_id,
                source_module="refspec.registry.census_geo_codes",
                source_token=token,
                profile="identifierScheme",
                ring="value",
                scope="captureSubset",
                issued=str(bundle.resource_manifest["capturedAt"]),
                inputs=inputs,
                items=_bundle_items(observations, key=resource_id),
                source_release_digest=canonical_digest({"bundle": bundle.logical_digest, "resourceId": resource_id}),
                source_digests=source_digests,
            )
        )
    return tuple(releases)


def _load_billstatus(repo_root: Path, temporary: Path) -> tuple[RegistryRelease, ...]:
    from refspec.registry import billstatus_codes as source

    pin = source.BILLSTATUS_USER_GUIDE_2026_08_03
    input_pin = _input_pin(
        repo_root,
        "tests/fixtures/billstatus_codes/billstatus-xml-user-guide-2026-08-03.md",
        source_iri=pin.source.source_url,
        sha256=pin.expected_sha256,
        byte_length=pin.expected_byte_length,
    )
    acquired = _acquire(
        source.acquire_billstatus_source,
        pin,
        input_pin.path,
        temporary / "billstatus",
    )
    portfolio = source.parse_billstatus_code_sets(acquired)
    rows = (
        ("bill-types", portfolio.bill_types, 8, "completeCapture"),
        ("summary-version-codes", portfolio.summary_version_codes, 88, "completeCapture"),
        ("action-codes", portfolio.action_codes, 36, "captureSubset"),
    )
    releases: list[RegistryRelease] = []
    for suffix, parsed, expected_count, scope in rows:
        if len(parsed.codes) != expected_count:
            raise ValueError(f"BILLSTATUS {suffix} count drifted")
        releases.append(
            _release(
                key=f"billstatus-{suffix}",
                resource_id="congress-billstatus-native-controls",
                source_module="refspec.registry.billstatus_codes",
                source_token=f"billstatus-{suffix}",
                profile="structureScheme",
                ring="value",
                scope=scope,
                issued=parsed.retrieved_at,
                inputs=(input_pin,),
                items=_code_items(
                    parsed.codes,
                    resource_name=parsed.resource_name,
                    source_iri=pin.source.source_url,
                ),
                source_release_digest=parsed.source_sha256,
            )
        )
    return tuple(releases)


def _load_fcc(repo_root: Path) -> tuple[RegistryRelease, ...]:
    from refspec.registry import fcc_ecfs_codes as source

    pin = source.FCC_ECFS_FILINGS_SNAPSHOT_2026_08_03
    input_pin = _input_pin(
        repo_root,
        "tests/fixtures/fcc_ecfs_codes/fcc-ecfs-filings-2026-08-03.json",
        source_iri=pin.source.source_url,
        sha256=pin.expected_sha256,
        byte_length=pin.expected_byte_length,
    )
    rows = (
        ("fcc-ecfs-filing-types", "fcc-ecfs-filing-types", source.build_fcc_ecfs_filing_type_package, 6, "value"),
        (
            "fcc-ecfs-access-statuses",
            "fcc-ecfs-access-statuses",
            source.build_fcc_ecfs_access_status_package,
            1,
            "value",
        ),
        ("fcc-ecfs-bureaus", "fcc-ecfs-bureaus", source.build_fcc_ecfs_bureau_package, 5, "entity"),
        ("fcc-ecfs-proceedings", "fcc-ecfs-proceedings", source.build_fcc_ecfs_proceeding_package, 15, "legalIdentity"),
    )
    return tuple(
        _bundle_release(
            builder(input_pin.path),
            key=key,
            resource_id="fcc-ecfs-native-controls",
            source_module="refspec.registry.fcc_ecfs_codes",
            source_token=token,
            profile="structureScheme",
            ring=ring,
            scope="captureSubset",
            inputs=(input_pin,),
            expected_count=count,
        )
        for key, token, builder, count, ring in rows
    )


def _load_fec(repo_root: Path, temporary: Path) -> tuple[RegistryRelease, ...]:
    from refspec.registry import fec_committee_codes as source

    acquired: dict[str, Any] = {}
    inputs: dict[str, RegistryInputPin] = {}
    source_rows = (
        (
            "master",
            source.FEC_COMMITTEE_MASTER_FILE_2026_08_03,
            "tests/fixtures/fec_committee_codes/fec-committee-master-file-description-2026-08-03.html",
        ),
        (
            "committeeType",
            source.FEC_COMMITTEE_TYPE_CODES_2026_08_03,
            "tests/fixtures/fec_committee_codes/fec-committee-type-code-descriptions-2026-08-03.html",
        ),
        (
            "party",
            source.FEC_PARTY_CODES_2026_08_03,
            "tests/fixtures/fec_committee_codes/fec-party-code-descriptions-2026-08-03.html",
        ),
    )
    for name, pin, logical_path in source_rows:
        input_pin = _input_pin(
            repo_root,
            logical_path,
            source_iri=pin.source.source_url,
            sha256=pin.expected_sha256,
            byte_length=pin.expected_byte_length,
        )
        inputs[name] = input_pin
        acquired[name] = _acquire(
            source.acquire_fec_doc,
            pin,
            input_pin.path,
            temporary / f"fec-{name}",
        )
    rows = (
        (
            "committeeDesignation",
            source.parse_committee_designation_codes(acquired["master"]),
            "master",
            6,
        ),
        (
            "filingFrequency",
            source.parse_filing_frequency_codes(acquired["master"]),
            "master",
            6,
        ),
        (
            "organizationType",
            source.parse_organization_type_codes(acquired["master"]),
            "master",
            6,
        ),
        (
            "committeeType",
            source.parse_committee_type_codes(acquired["committeeType"]),
            "committeeType",
            16,
        ),
        ("party", source.parse_party_codes(acquired["party"]), "party", 95),
    )
    return tuple(
        _bundle_release(
            source.build_fec_committee_code_package(
                resource_name,
                parsed,
                acquired[input_name],
            ),
            key=f"fec-{_token_fragment(resource_name)}",
            resource_id="fec-native-controls",
            source_module="refspec.registry.fec_committee_codes",
            source_token=f"fec-{_token_fragment(resource_name)}",
            profile="codeScheme",
            ring="value",
            scope="completeCapture",
            inputs=(inputs[input_name],),
            expected_count=count,
        )
        for resource_name, parsed, input_name, count in rows
    )


def _load_ferc(repo_root: Path) -> tuple[RegistryRelease, ...]:
    from refspec.registry import ferc_elibrary_codes as source

    issued = "2026-08-03T19:18:32Z"
    class_input = _input_pin(
        repo_root,
        "output/registry-real-data-sources/ferc-class-types-january-2025.pdf",
        source_iri=source.FERC_CLASS_TYPE_PDF_URL,
        sha256=source.FERC_CLASS_TYPE_PDF_SHA256,
        byte_length=source.FERC_CLASS_TYPE_PDF_BYTE_LENGTH,
    )
    class_capture = source.parse_ferc_class_type_pdf(class_input.path.read_bytes())
    if len(class_capture.rows) != source.FERC_CLASS_TYPE_PDF_ROW_COUNT:
        raise ValueError("FERC class/type PDF count drifted")
    class_items = tuple(
        _Item(
            label=row.text,
            source_path=f"$.rows[{ordinal}]",
            notations=(),
            native_payload=_stamp_source_artifact(
                _json_value(row), class_capture.source_url
            ),
        )
        for ordinal, row in enumerate(class_capture.rows)
    )
    class_release = _release(
        key="ferc-document-class-types",
        resource_id="ferc-elibrary-native-controls",
        source_module="refspec.registry.ferc_elibrary_codes",
        source_token="ferc-document-class-types",
        profile="codeScheme",
        ring="value",
        scope="publisherRelease",
        issued=issued,
        inputs=(class_input,),
        items=class_items,
        source_release_digest=class_capture.source_sha256,
    )

    docket_input = _input_pin(
        repo_root,
        "output/registry-real-data-sources/ferc-docket-prefix-june-2025.pdf",
        source_iri=source.FERC_DOCKET_PREFIX_PDF_URL,
        sha256=source.FERC_DOCKET_PREFIX_PDF_SHA256,
        byte_length=source.FERC_DOCKET_PREFIX_PDF_BYTE_LENGTH,
    )
    docket_capture = source.parse_ferc_docket_prefix_pdf(docket_input.path.read_bytes())
    if len(docket_capture.rows) != 95:
        raise ValueError("FERC docket-prefix PDF count drifted")
    docket_items = tuple(
        _Item(
            label=row.definition,
            source_path=f"$.rows[{ordinal}]",
            notations=(row.prefix,),
            native_payload=_stamp_source_artifact(
                _json_value(row), docket_capture.source_url
            ),
            definition=row.definition,
            status=row.status,
        )
        for ordinal, row in enumerate(docket_capture.rows)
    )
    docket_release = _release(
        key="ferc-docket-prefixes",
        resource_id="ferc-elibrary-identifiers",
        source_module="refspec.registry.ferc_elibrary_codes",
        source_token="ferc-docket-prefixes",
        profile="identifierScheme",
        ring="value",
        scope="publisherRelease",
        issued=issued,
        inputs=(docket_input,),
        items=docket_items,
        source_release_digest=docket_capture.source_sha256,
    )

    search_input = _input_pin(
        repo_root,
        "output/registry-real-data-sources/ferc-general-search-help.html",
        source_iri=source.FERC_GENERAL_SEARCH_HELP_URL,
        sha256=source.FERC_GENERAL_SEARCH_HELP_SHA256,
        byte_length=source.FERC_GENERAL_SEARCH_HELP_BYTE_LENGTH,
    )
    search_capture = source.parse_ferc_general_search_help(search_input.path.read_bytes())
    releases = [class_release, docket_release]
    for suffix, values in (
        ("sectors", search_capture.sectors),
        ("security-levels", search_capture.security_levels),
    ):
        items = tuple(
            _Item(
                label=value,
                source_path=f"$.{suffix}[{ordinal}]",
                notations=(value,),
                native_payload={
                    "sourceArtifact": search_capture.source_url,
                    "value": value,
                },
            )
            for ordinal, value in enumerate(values)
        )
        releases.append(
            _release(
                key=f"ferc-{suffix}",
                resource_id="ferc-elibrary-native-controls",
                source_module="refspec.registry.ferc_elibrary_codes",
                source_token=f"ferc-{suffix}",
                profile="codeScheme",
                ring="value",
                scope="completeCapture",
                issued=issued,
                inputs=(search_input,),
                items=items,
                source_release_digest=canonical_digest({"input": search_capture.source_sha256, "resource": suffix}),
            )
        )

    accessibility_input = _input_pin(
        repo_root,
        "output/registry-real-data-sources/ferc-accessibility-tips.html",
        source_iri=source.FERC_ACCESSIBILITY_TIPS_URL,
        sha256=source.FERC_ACCESSIBILITY_TIPS_SHA256,
        byte_length=source.FERC_ACCESSIBILITY_TIPS_BYTE_LENGTH,
    )
    formats = source.parse_ferc_accessibility_tips(accessibility_input.path.read_bytes())
    format_items = tuple(
        _Item(
            label=f"FERC accession number format {value}",
            source_path=f"$.accessionFormats[{ordinal}]",
            notations=(value,),
            native_payload={
                "sourceArtifact": formats.source_url,
                "format": value,
            },
        )
        for ordinal, value in enumerate(formats.accession_formats)
    )
    releases.append(
        _release(
            key="ferc-accession-number-formats",
            resource_id="ferc-elibrary-identifiers",
            source_module="refspec.registry.ferc_elibrary_codes",
            source_token="ferc-accession-formats",
            profile="identifierScheme",
            ring="value",
            scope="completeCapture",
            issued=issued,
            inputs=(accessibility_input,),
            items=format_items,
            source_release_digest=formats.source_sha256,
        )
    )
    if tuple(len(release.resources) for release in releases) != (235, 95, 6, 4, 2):
        raise ValueError("FERC official control counts drifted")
    return tuple(releases)


def _load_grants(repo_root: Path, temporary: Path) -> tuple[RegistryRelease, ...]:
    from refspec.registry import grants_gov_codes as source

    pin = source.GRANTS_GOV_STATUS_CODES_2026_08_03
    input_pin = _input_pin(
        repo_root,
        "tests/fixtures/grants_gov_codes/grants-gov-status-codes-2026-08-03.html",
        source_iri=pin.source.source_url,
        sha256=pin.expected_sha256,
        byte_length=pin.expected_byte_length,
    )
    acquired = _acquire(
        source.acquire_grants_gov_status_codes,
        pin,
        input_pin.path,
        temporary / "grants",
    )
    portfolio = source.parse_grants_gov_status_codes(acquired)
    rows = (("eligibilities", 17, "value"), ("fundingCategories", 26, "value"))
    return tuple(
        _bundle_release(
            source.build_grants_gov_code_package(resource_name, portfolio, acquired),
            key=f"grants-gov-{_token_fragment(resource_name)}",
            resource_id="grants-gov-status-codes",
            source_module="refspec.registry.grants_gov_codes",
            source_token=f"grants-gov-{_token_fragment(resource_name)}",
            profile="codeScheme",
            ring=ring,
            scope="completeCapture",
            inputs=(input_pin,),
            expected_count=count,
        )
        for resource_name, count, ring in rows
    )


def _load_lda(repo_root: Path, temporary: Path) -> tuple[RegistryRelease, ...]:
    from refspec.registry import lda_controlled_codes as source

    rows = (
        (
            "lda-general-issue-codes",
            "lda-general-issues",
            source.LDA_GENERAL_ISSUE_CODES_2026_07_30,
            "tests/fixtures/lda-general-issue-codes-2026-07-30.json",
            79,
            "conceptScheme",
            "subject",
        ),
        (
            "lda-filing-types",
            "lda-filing-types",
            source.LDA_FILING_TYPES_2026_07_30,
            "tests/fixtures/lda-filing-types-2026-07-30.json",
            50,
            "codeScheme",
            "value",
        ),
    )
    releases: list[RegistryRelease] = []
    for key, token, pin, logical_path, expected_count, profile, ring in rows:
        input_pin = _input_pin(
            repo_root,
            logical_path,
            source_iri=pin.source.source_url,
            sha256=pin.expected_sha256,
            byte_length=pin.expected_byte_length,
        )
        acquired = _acquire(
            source.acquire_lda_constants,
            pin,
            input_pin.path,
            temporary / key,
        )
        parsed = source.parse_lda_constants(acquired)
        if len(parsed.codes) != expected_count:
            raise ValueError(f"{key} count drifted")
        releases.append(
            _release(
                key=key,
                resource_id=key,
                source_module="refspec.registry.lda_controlled_codes",
                source_token=token,
                profile=profile,
                ring=ring,
                scope="completeCapture",
                issued=parsed.retrieved_at,
                inputs=(input_pin,),
                items=_code_items(
                    parsed.codes,
                    resource_name=parsed.source.resource_name,
                    source_iri=pin.source.source_url,
                ),
                source_release_digest=parsed.source_sha256,
            )
        )
    return tuple(releases)


def _load_oira(repo_root: Path, temporary: Path) -> tuple[RegistryRelease, ...]:
    from refspec.registry import oira_review_codes as source

    paths = (
        (
            "output/registry-real-data-sources/oira-controls/sha256/"
            "bc92190b16d9855c05700592bd957491089434bed031aff369103add47af4f76/reviewStatus.html"
        ),
        (
            "output/registry-real-data-sources/oira-controls/sha256/"
            "90ccba72caf4a3b98654937fd9a5297c0413b803b9e513c85b1851daf7fbb15a/ruleStage.html"
        ),
        (
            "output/registry-real-data-sources/oira-controls/sha256/"
            "a402dfde370f0b506dc5262b6002a41983e28f1ac7a4338c1ed048ee49cadbef/concludedAction.html"
        ),
        (
            "output/registry-real-data-sources/oira-controls/sha256/"
            "9bec2066ff2c01731b201765cad4a175a0b34230c30dfc854655341040cc9aea/meetingStatus.html"
        ),
    )
    pins: list[RegistryInputPin] = []
    acquired: list[Any] = []
    for index, (pin, logical_path) in enumerate(zip(source.OIRA_FIELD_PINS_2026_08_03, paths, strict=True)):
        input_pin = _input_pin(
            repo_root,
            logical_path,
            source_iri=pin.field.source_id,
            sha256=pin.expected_sha256,
            byte_length=pin.expected_byte_length,
        )
        pins.append(input_pin)
        acquired.append(
            _acquire(
                source.acquire_oira_field,
                pin,
                input_pin.path,
                temporary / f"oira-{index}",
            )
        )
    bundle = source.build_oira_review_and_meeting_package(*acquired)
    return (
        _bundle_release(
            bundle,
            key="oira-review-controls",
            resource_id="oira-review-native-controls",
            source_module="refspec.registry.oira_review_codes",
            source_token="oira-review-controls",
            profile="codeScheme",
            ring="value",
            scope="completeCapture",
            inputs=tuple(pins),
            expected_count=20,
        ),
    )


def _load_omb_a11(repo_root: Path, temporary: Path) -> tuple[RegistryRelease, ...]:
    from refspec.registry import omb_a11_budget_codes as source

    document_input = _input_pin(
        repo_root,
        "output/registry-real-data-sources/omb-a11-2025-wayback.pdf",
        source_iri=source.OMB_A11_DOCUMENT_URL,
        sha256=source.OMB_A11_DOCUMENT_SHA256,
        byte_length=source.OMB_A11_DOCUMENT_BYTE_LENGTH,
        role="publisherSource",
    )
    rows = (
        (
            "functional-classification",
            source.OMB_A11_FUNCTIONAL_CLASSIFICATION_2025,
            "tests/fixtures/omb_a11_budget_codes/exhibit-79a-functional-classification-2025.txt",
            source.parse_omb_a11_functional_classification,
            98,
        ),
        (
            "object-classification",
            source.OMB_A11_OBJECT_CLASSIFICATION_2025,
            "tests/fixtures/omb_a11_budget_codes/exhibit-83a-object-classification-2025.txt",
            source.parse_omb_a11_object_classification,
            38,
        ),
        (
            "apportionment-categories",
            source.OMB_A11_APPORTIONMENT_CATEGORIES_2025,
            "tests/fixtures/omb_a11_budget_codes/section-120-13-apportionment-categories-2025.txt",
            source.parse_omb_a11_apportionment_categories,
            8,
        ),
    )
    releases: list[RegistryRelease] = []
    for suffix, pin, logical_path, parser, expected_count in rows:
        input_pin = _input_pin(
            repo_root,
            logical_path,
            source_iri=(
                "urn:ref:derived-artifact:"
                + pin.expected_sha256.removeprefix("sha256:")
            ),
            sha256=pin.expected_sha256,
            byte_length=pin.expected_byte_length,
            role="publisherPdfTextExtraction",
        )
        acquired = _acquire(
            source.acquire_omb_a11_page,
            pin,
            input_pin.path,
            temporary / f"omb-a11-{suffix}",
        )
        parsed = parser(acquired)
        if len(parsed.codes) != expected_count:
            raise ValueError(f"OMB A-11 {suffix} count drifted")
        releases.append(
            _release(
                key=f"omb-a11-{suffix}",
                resource_id="omb-a11-budget-codes",
                source_module="refspec.registry.omb_a11_budget_codes",
                source_token=f"omb-a11-{suffix}",
                profile="codeScheme",
                ring="value",
                scope="captureSubset",
                issued=parsed.retrieved_at,
                inputs=(document_input, input_pin),
                items=_code_items(
                    parsed.codes,
                    resource_name=pin.source.resource_name,
                    source_iri=pin.source.document_url,
                ),
                source_release_digest=document_input.sha256,
            )
        )
    return tuple(releases)


def _load_sam_assistance(repo_root: Path, temporary: Path) -> tuple[RegistryRelease, ...]:
    from refspec.registry import sam_assistance_listing_codes as source

    pin = source.SAM_ASSISTANCE_DOC_2026_08_03
    input_pin = _input_pin(
        repo_root,
        "tests/fixtures/sam_assistance_listing_codes/sam-assistance-listings-api-2026-08-03.html",
        source_iri=pin.source.source_url,
        sha256=pin.expected_sha256,
        byte_length=pin.expected_byte_length,
    )
    acquired = _acquire(
        source.acquire_sam_assistance_listing_doc,
        pin,
        input_pin.path,
        temporary / "sam-assistance",
    )
    portfolio = source.parse_sam_assistance_listing_codes(acquired)
    rows = (
        ("assistanceTypes", 17),
        ("eligibleApplicantTypes", 44),
        ("eligibleBeneficiaryTypes", 73),
    )
    return tuple(
        _bundle_release(
            source.build_sam_assistance_listing_code_package(resource_name, portfolio, acquired),
            key=f"sam-assistance-{_token_fragment(resource_name)}",
            resource_id="sam-assistance-listing-controls",
            source_module="refspec.registry.sam_assistance_listing_codes",
            source_token=f"sam-assistance-{_token_fragment(resource_name)}",
            profile="codeScheme",
            ring="value",
            scope="completeCapture",
            inputs=(input_pin,),
            expected_count=count,
        )
        for resource_name, count in rows
    )


def _load_sam_opportunities(repo_root: Path, temporary: Path) -> tuple[RegistryRelease, ...]:
    from refspec.registry import sam_opportunities_codes as source

    pin = source.SAM_OPPORTUNITIES_DOC_2026_08_03
    input_pin = _input_pin(
        repo_root,
        "tests/fixtures/sam_opportunities_codes/sam-get-opportunities-public-api-2026-08-03.html",
        source_iri=pin.source.source_url,
        sha256=pin.expected_sha256,
        byte_length=pin.expected_byte_length,
    )
    acquired = _acquire(
        source.acquire_sam_opportunities_doc,
        pin,
        input_pin.path,
        temporary / "sam-opportunities",
    )
    portfolio = source.parse_sam_opportunities_codes(acquired)
    rows = (("noticeTypes", 11), ("opportunityStatuses", 5), ("setAsideCodes", 18))
    return tuple(
        _bundle_release(
            source.build_sam_opportunities_code_package(resource_name, portfolio, acquired),
            key=f"sam-opportunities-{_token_fragment(resource_name)}",
            resource_id="sam-opportunities-native-controls",
            source_module="refspec.registry.sam_opportunities_codes",
            source_token=f"sam-opportunities-{_token_fragment(resource_name)}",
            profile="codeScheme",
            ring="value",
            scope="completeCapture",
            inputs=(input_pin,),
            expected_count=count,
        )
        for resource_name, count in rows
    )


def _load_nasa_technology(repo_root: Path) -> tuple[RegistryRelease, ...]:
    from refspec.registry import nasa_technology_taxonomy as source

    root_pin = source.NASA_TAXONOMY_ROOT_INDEX_2026_08_03
    child_pin = source.NASA_TAXONOMY_ROOT_CHILDREN_2026_08_03
    root = _input_pin(
        repo_root,
        "tests/fixtures/nasa_technology_taxonomy/techport-taxonomy-roots-2026-08-03.json",
        source_iri=root_pin.source.source_url,
        sha256=root_pin.expected_sha256,
        byte_length=root_pin.expected_byte_length,
    )
    children = _input_pin(
        repo_root,
        "tests/fixtures/nasa_technology_taxonomy/techport-taxonomy-8817-children-2026-08-03.json",
        source_iri=child_pin.source.source_url,
        sha256=child_pin.expected_sha256,
        byte_length=child_pin.expected_byte_length,
    )
    bundle = source.build_nasa_technology_taxonomy_package(root.path, children.path)
    return (
        _bundle_release(
            bundle,
            key="nasa-technology-taxonomy-8817",
            resource_id="nasa-technology-taxonomy",
            source_module="refspec.registry.nasa_technology_taxonomy",
            source_token="nasa-techport-taxonomy",
            profile="conceptScheme",
            ring="subject",
            scope="captureSubset",
            inputs=(root, children),
            expected_count=17,
        ),
    )


def _load_nature_of_suit(repo_root: Path) -> tuple[RegistryRelease, ...]:
    from refspec.registry import nature_of_suit_codes as source

    document_pin = _input_pin(
        repo_root,
        "output/registry-real-data-sources/js_044_code_descriptions.pdf",
        source_iri=source.NATURE_OF_SUIT_CODE_DESCRIPTIONS_URL,
        sha256="sha256:aeaff2476c8cc926191466ff571e91b0f0896858f4f00deed1117c1aa33daa95",
        byte_length=316_187,
        role="publisherSource",
    )
    logical_path = "tests/fixtures/nature_of_suit_codes/js_044_code_descriptions.layout.txt"
    payload = (repo_root / logical_path).read_bytes()
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    pin = _input_pin(
        repo_root,
        logical_path,
        source_iri="urn:ref:derived-artifact:" + digest.removeprefix("sha256:"),
        sha256=digest,
        byte_length=len(payload),
        role="publisherPdfTextExtraction",
    )
    parsed = source.parse_nature_of_suit_code_descriptions(payload)
    bundle = source.build_nature_of_suit_code_package(
        parsed,
        captured_at="2026-08-03T00:00:00Z",
    )
    return (
        _release(
            key="uscourts-nature-of-suit",
            resource_id="nature-of-suit",
            source_module="refspec.registry.nature_of_suit_codes",
            source_token="uscourts-nature-of-suit",
            profile="codeScheme",
            ring="value",
            scope="completeCapture",
            issued=str(bundle.resource_manifest["capturedAt"]),
            inputs=(document_pin, pin),
            items=_bundle_items(
                bundle.observations,
                key="uscourts-nature-of-suit",
            ),
            source_release_digest=document_pin.sha256,
            source_digests={
                source.NATURE_OF_SUIT_CODE_DESCRIPTIONS_URL: document_pin.sha256
            },
        ),
    )


def _load_govinfo(repo_root: Path, temporary: Path) -> tuple[RegistryRelease, ...]:
    from refspec.registry import govinfo_collections as source

    pin = source.GOVINFO_COLLECTIONS_2026_08_03
    input_pin = _input_pin(
        repo_root,
        "tests/fixtures/govinfo_collections/govinfo-collections-2026-08-03.json",
        source_iri=pin.source.source_url,
        sha256=pin.expected_sha256,
        byte_length=pin.expected_byte_length,
    )
    bundle = source.build_govinfo_collections_package(input_pin.path)
    collections = _bundle_release(
        bundle,
        key="govinfo-collections",
        resource_id="govinfo-collections",
        source_module="refspec.registry.govinfo_collections",
        source_token="govinfo-collections",
        profile="codeScheme",
        ring="value",
        scope="completeCapture",
        inputs=(input_pin,),
        expected_count=42,
    )
    title_pin = source.ECFR_CFR_TITLES_2026_08_03
    title_input = _input_pin(
        repo_root,
        "tests/fixtures/govinfo_collections/ecfr-cfr-titles-2026-08-03.json",
        source_iri=title_pin.source.source_url,
        sha256=title_pin.expected_sha256,
        byte_length=title_pin.expected_byte_length,
    )
    acquired = _acquire(
        source.acquire_govinfo_source,
        title_pin,
        title_input.path,
        temporary / "ecfr-titles",
    )
    parsed = source.parse_ecfr_cfr_titles(acquired)
    if len(parsed.titles) != 50:
        raise ValueError("eCFR title roster count drifted")
    title_items = tuple(
        _Item(
            label=title.name,
            source_path=f"$.titles[{ordinal}]",
            notations=(str(title.title_number),),
            native_payload={
                **_json_value(title),
                "sourceArtifact": title_pin.source.source_url,
            },
            status="reserved" if title.reserved else "active",
        )
        for ordinal, title in enumerate(parsed.titles)
    )
    titles = _release(
        key="ecfr-cfr-titles",
        resource_id="ecfr-cfr-structure",
        source_module="refspec.registry.govinfo_collections",
        source_token="ecfr-cfr-titles",
        profile="structureScheme",
        ring="legalIdentity",
        scope="completeCapture",
        issued=parsed.retrieved_at,
        inputs=(title_input,),
        items=title_items,
        source_release_digest=parsed.source_sha256,
    )
    return (collections, titles)


def _load_oversight(repo_root: Path, temporary: Path) -> tuple[RegistryRelease, ...]:
    from refspec.registry import oversight_report_types as source

    pin = source.OVERSIGHT_REPORT_TYPES_2026_08_03
    input_pin = _input_pin(
        repo_root,
        "tests/fixtures/oversight_report_types/oversight-reports-federal-2026-08-03.html",
        source_iri=pin.source_url,
        sha256=pin.expected_sha256,
        byte_length=pin.expected_byte_length,
    )
    acquired = _acquire(
        source.acquire_oversight_report_types_page,
        pin,
        input_pin.path,
        temporary / "oversight",
    )
    parsed = source.parse_oversight_report_types_page(acquired)
    return (
        _bundle_release(
            source.build_oversight_report_types_package(acquired, parsed),
            key="oversight-report-types",
            resource_id="oversight-report-types",
            source_module="refspec.registry.oversight_report_types",
            source_token="oversight-report-types",
            profile="codeScheme",
            ring="value",
            scope="completeCapture",
            inputs=(input_pin,),
            expected_count=10,
        ),
    )


def _load_pra(repo_root: Path) -> tuple[RegistryRelease, ...]:
    from refspec.registry import pra_icr_codes as source

    pin = source.PRA_SEARCH_PAGE_2026_08_03
    input_pin = _input_pin(
        repo_root,
        "tests/fixtures/pra_icr_codes/pra-search-2026-08-03.html",
        source_iri=pin.source.source_url,
        sha256=pin.expected_sha256,
        byte_length=pin.expected_byte_length,
    )
    return (
        _bundle_release(
            source.build_pra_icr_controlled_value_package(input_pin.path),
            key="pra-icr-controls",
            resource_id="pra-icr-native-controls",
            source_module="refspec.registry.pra_icr_codes",
            source_token="pra-icr-controls",
            profile="codeScheme",
            ring="value",
            scope="completeCapture",
            inputs=(input_pin,),
            expected_count=21,
        ),
    )


def _load_regulatory_native_controls(repo_root: Path) -> tuple[RegistryRelease, ...]:
    from refspec.registry import regulatory_native_controls as source

    capture_path = "research/evidence/regulatory-native-controls-2026-08-03/source-native-control-capture.json"
    capture_payload = (repo_root / capture_path).read_bytes()
    capture_file_digest = "sha256:" + hashlib.sha256(capture_payload).hexdigest()
    capture_iri = "urn:ref:registry:regulatory-native-control-capture:2026-08-03"
    capture_input = _input_pin(
        repo_root,
        capture_path,
        source_iri=capture_iri,
        sha256=capture_file_digest,
        byte_length=len(capture_payload),
        role="normalizedControlCapture",
    )
    capture = source.parse_control_capture(
        capture_payload,
        expected_sha256=capture_file_digest,
        expected_byte_length=len(capture_payload),
    )
    paths_by_table = {
        "dockets": "output/registry-real-data-sources/regulatory-native-current/dockets.parquet",
        "documents": "output/registry-real-data-sources/regulatory-native-current/documents.parquet",
        "federal_register": ("output/registry-real-data-sources/regulatory-native-current/federal_register.parquet"),
        "unified_agenda": ("output/registry-real-data-sources/regulatory-native-current/unified_agenda.parquet"),
    }
    table_inputs: dict[str, RegistryInputPin] = {}
    for table, pin in capture.source_pins.by_table.items():
        table_inputs[table] = _input_pin(
            repo_root,
            paths_by_table[table],
            source_iri=pin.uri,
            sha256=pin.sha256,
            byte_length=pin.byte_length,
            role="sourceDistribution",
        )

    releases: list[RegistryRelease] = []
    for control in capture.controls:
        source_pin = capture.source_pins.by_table[control.spec.source_table]
        control_metadata = {key: value for key, value in control.native_payload().items() if key != "values"}
        items = tuple(
            _Item(
                label=value.value,
                source_path=(f"$.controls[{control.spec.control_id}].values[{ordinal}]"),
                notations=(value.value,),
                native_payload={
                    "sourceArtifact": source_pin.uri,
                    "control": control_metadata,
                    "value": value.native_payload(),
                },
            )
            for ordinal, value in enumerate(control.values)
        )
        # These releases contain publisher field values, including agency codes
        # and unresolved agency-name strings. They do not identify the agencies.
        ring = "value"
        profiles_by_resource = {
            "federal-register-native-controls": "conceptScheme",
            "regulations-gov-native-controls": "structureScheme",
            "unified-agenda-native-controls": "codeScheme",
        }
        profile = profiles_by_resource[control.spec.resource_id]
        releases.append(
            _release(
                key=f"regulatory-native-{control.spec.control_id}",
                resource_id=control.spec.resource_id,
                source_module="refspec.registry.regulatory_native_controls",
                source_token=control.spec.control_id,
                profile=profile,
                ring=ring,
                scope="completeCapture",
                issued=capture.source_pins.captured_at,
                inputs=(capture_input, table_inputs[control.spec.source_table]),
                items=items,
                source_release_digest=canonical_digest(
                    {
                        "captureDigest": capture.digest,
                        "control": control.native_payload(),
                    }
                ),
            )
        )
    if len(releases) != 14 or sum(len(release.resources) for release in releases) != 1_861:
        raise ValueError("regulatory-native control capture count drifted")
    return tuple(releases)


def _load_regulations_gov(repo_root: Path, temporary: Path) -> tuple[RegistryRelease, ...]:
    from refspec.registry import regulations_gov_codes as source

    pin = source.RGOV_OPENAPI_2026_08_03
    input_pin = _input_pin(
        repo_root,
        "tests/fixtures/regulations_gov_codes/regulations-gov-openapi-v4-2026-08-03.yaml",
        source_iri=pin.source.source_url,
        sha256=pin.expected_sha256,
        byte_length=pin.expected_byte_length,
    )
    acquired = _acquire(
        source.acquire_regulations_gov_openapi,
        pin,
        input_pin.path,
        temporary / "regulations-gov-openapi",
    )
    rows = (("documentType", 5), ("docketType", 2), ("submitterType", 3))
    releases: list[RegistryRelease] = []
    parsed_resources: list[Any] = []
    for resource_name, expected_count in rows:
        parsed = source.parse_regulations_gov_resource(acquired, resource_name)
        parsed_resources.append(parsed)
        if len(parsed.codes) != expected_count:
            raise ValueError(f"Regulations.gov {resource_name} count drifted")
        releases.append(
            _release(
                key=f"regulations-gov-{_token_fragment(resource_name)}",
                resource_id="regulations-gov-native-controls",
                source_module="refspec.registry.regulations_gov_codes",
                source_token=f"regulations-gov-{_token_fragment(resource_name)}",
                profile="structureScheme",
                ring="value",
                scope="publisherRelease",
                issued=parsed.retrieved_at,
                inputs=(input_pin,),
                items=_code_items(
                    parsed.codes,
                    resource_name=resource_name,
                    source_iri=pin.source.source_url,
                ),
                source_release_digest=canonical_digest({"input": parsed.source_sha256, "resource": resource_name}),
            )
        )
    source.assemble_regulations_gov_control_portfolio(parsed_resources)
    return tuple(releases)


def _load_scotus(repo_root: Path, temporary: Path) -> tuple[RegistryRelease, ...]:
    from refspec.registry import scotus_opinion_types as source

    pin = source.SCOTUS_OPINIONS_2026_08_03
    input_pin = _input_pin(
        repo_root,
        "tests/fixtures/scotus_opinion_types/scotus-opinions-2026-08-03.html",
        source_iri=pin.source_url,
        sha256=pin.expected_sha256,
        byte_length=pin.expected_byte_length,
    )
    acquired = _acquire(
        source.acquire_scotus_opinions_page,
        pin,
        input_pin.path,
        temporary / "scotus",
    )
    parsed = source.parse_scotus_opinions_page(acquired)
    return (
        _bundle_release(
            source.build_scotus_opinion_type_package(acquired, parsed),
            key="scotus-opinion-types",
            resource_id="scotus-opinion-and-package-types",
            source_module="refspec.registry.scotus_opinion_types",
            source_token="scotus-opinion-types",
            profile="codeScheme",
            ring="value",
            scope="completeCapture",
            inputs=(input_pin,),
            expected_count=7,
        ),
    )


def _load_sec(repo_root: Path, temporary: Path) -> tuple[RegistryRelease, ...]:
    from refspec.registry import sec_series_categories as source

    pin = source.SEC_RULES_REGULATIONS_PIN_2026_08_03
    input_pin = _input_pin(
        repo_root,
        "tests/fixtures/sec_series_categories/sec-rules-regulations-2026-08-03.html",
        source_iri=pin.source.source_url,
        sha256=pin.expected_sha256,
        byte_length=pin.expected_byte_length,
    )
    acquired = _acquire(source.acquire_sec_page, pin, input_pin.path, temporary / "sec")
    parsed = source.parse_sec_rules_regulations_page(acquired)
    return (
        _bundle_release(
            source.build_sec_series_category_package(acquired, parsed),
            key="sec-series-categories",
            resource_id="sec-rules-regulations-categories",
            source_module="refspec.registry.sec_series_categories",
            source_token="sec-series-categories",
            profile="codeScheme",
            ring="value",
            scope="completeCapture",
            inputs=(input_pin,),
            expected_count=19,
        ),
    )


def _load_usaspending(repo_root: Path, temporary: Path) -> tuple[RegistryRelease, ...]:
    from refspec.registry import usaspending_gsdm_codes as source

    pin = source.USASPENDING_AWARD_TYPES_2026_08_03
    input_pin = _input_pin(
        repo_root,
        "tests/fixtures/usaspending_gsdm_codes/usaspending-award-types-2026-08-03.json",
        source_iri=pin.source.source_url,
        sha256=pin.expected_sha256,
        byte_length=pin.expected_byte_length,
    )
    acquired = _acquire(
        source.acquire_usaspending_award_types,
        pin,
        input_pin.path,
        temporary / "usaspending",
    )
    parsed = source.parse_award_types(acquired)
    if len(parsed.codes) != 33:
        raise ValueError("USAspending award type count drifted")
    return (
        _release(
            key="usaspending-award-types",
            resource_id="usaspending-award-type-codes",
            source_module="refspec.registry.usaspending_gsdm_codes",
            source_token="usaspending-award-types",
            profile="codeScheme",
            ring="value",
            scope="completeCapture",
            issued=parsed.retrieved_at,
            inputs=(input_pin,),
            items=_code_items(
                parsed.codes,
                resource_name=parsed.source.resource_name,
                source_iri=pin.source.source_url,
            ),
            source_release_digest=parsed.source_sha256,
        ),
    )


def _load_unified_agenda(repo_root: Path, temporary: Path) -> tuple[RegistryRelease, ...]:
    from refspec.registry import unified_agenda_codes as source

    schema_pin = source.UA_REGINFO_SCHEMA_2026_08_03
    schema_input = _input_pin(
        repo_root,
        "tests/fixtures/unified_agenda_codes/reginfo-rin-data-ver10262011.xsd",
        source_iri=schema_pin.document.source_url,
        sha256=schema_pin.expected_sha256,
        byte_length=schema_pin.expected_byte_length,
    )
    schema_acquired = _acquire(
        source.acquire_unified_agenda_document,
        schema_pin,
        schema_input.path,
        temporary / "unified-agenda-schema",
    )
    parsed = source.parse_reginfo_schema(schema_acquired)
    fields = (
        ("rule-stage", parsed.rule_stage, 6),
        ("priority-category", parsed.priority_category, 6),
        ("timetable-action", parsed.timetable_action, 34),
    )
    releases: list[RegistryRelease] = []
    for suffix, field, expected_count in fields:
        if len(field.values) != expected_count or len(field.identifiers) != expected_count:
            raise ValueError(f"Unified Agenda {suffix} count drifted")
        items = tuple(
            _Item(
                label=value,
                source_path=f"$.{field.field_name}[{ordinal}]",
                notations=(identifier.value,),
                native_payload={
                    "sourceArtifact": parsed.source_url,
                    "fieldName": field.field_name,
                    "value": value,
                    "identifier": _json_value(identifier),
                },
            )
            for ordinal, (value, identifier) in enumerate(zip(field.values, field.identifiers, strict=True))
        )
        releases.append(
            _release(
                key=f"unified-agenda-{suffix}",
                resource_id="unified-agenda-native-controls",
                source_module="refspec.registry.unified_agenda_codes",
                source_token=f"unified-agenda-{suffix}",
                profile="codeScheme",
                ring="value",
                scope="captureSubset",
                issued=parsed.retrieved_at,
                inputs=(schema_input,),
                items=items,
                source_release_digest=canonical_digest({"input": parsed.source_sha256, "field": field.field_name}),
            )
        )

    preamble_pin = source.UA_RISC_PREAMBLE_2026_08_03
    preamble_input = _input_pin(
        repo_root,
        "tests/fixtures/unified_agenda_codes/risc-preamble-202210.pdf",
        source_iri=preamble_pin.document.source_url,
        sha256=preamble_pin.expected_sha256,
        byte_length=preamble_pin.expected_byte_length,
    )
    preamble_acquired = _acquire(
        source.acquire_unified_agenda_document,
        preamble_pin,
        preamble_input.path,
        temporary / "unified-agenda-preamble",
    )
    evidence = source.pin_risc_preamble_evidence(preamble_acquired)
    if len(evidence.legal_authority_citation_types) != 3:
        raise ValueError("Unified Agenda legal authority citation type count drifted")
    citation_items = tuple(
        _Item(
            label=value,
            source_path=f"$.legalAuthorityCitationTypes[{ordinal}]",
            notations=(identifier.value,),
            native_payload={
                "sourceArtifact": evidence.source_url,
                "value": value,
                "identifier": _json_value(identifier),
            },
        )
        for ordinal, (value, identifier) in enumerate(
            zip(
                evidence.legal_authority_citation_types,
                evidence.legal_authority_citation_type_identifiers,
                strict=True,
            )
        )
    )
    releases.append(
        _release(
            key="unified-agenda-legal-authority-citation-types",
            resource_id="unified-agenda-legal-authority-citations",
            source_module="refspec.registry.unified_agenda_codes",
            source_token="unified-agenda-legal-authority",
            profile="identifierScheme",
            ring="value",
            scope="captureSubset",
            issued=evidence.retrieved_at,
            inputs=(preamble_input,),
            items=citation_items,
            source_release_digest=evidence.source_sha256,
        )
    )
    source.assemble_unified_agenda_portfolio(parsed, evidence)
    return tuple(releases)


REGISTRY_CODE_RELEASE_GROUPS = (
    (
        "billstatus",
        frozenset(
            {
                "billstatus-action-codes",
                "billstatus-bill-types",
                "billstatus-summary-version-codes",
            }
        ),
    ),
    (
        "census",
        frozenset(
            {"census-data-flags", "census-function-items", "nasbo-program-areas"}
        ),
    ),
    (
        "census-geo",
        frozenset(
            {
                "census-acs-geography-identifiers",
                "census-tiger-geoid-structure",
                "usgs-gnis-identifiers",
            }
        ),
    ),
    (
        "fcc",
        frozenset(
            {
                "fcc-ecfs-access-statuses",
                "fcc-ecfs-bureaus",
                "fcc-ecfs-filing-types",
                "fcc-ecfs-proceedings",
            }
        ),
    ),
    (
        "fec",
        frozenset(
            {
                "fec-committee-designation",
                "fec-committee-type",
                "fec-filing-frequency",
                "fec-organization-type",
                "fec-party",
            }
        ),
    ),
    (
        "ferc",
        frozenset(
            {
                "ferc-accession-number-formats",
                "ferc-docket-prefixes",
                "ferc-document-class-types",
                "ferc-sectors",
                "ferc-security-levels",
            }
        ),
    ),
    ("govinfo", frozenset({"ecfr-cfr-titles", "govinfo-collections"})),
    (
        "grants",
        frozenset(
            {"grants-gov-eligibilities", "grants-gov-funding-categories"}
        ),
    ),
    ("lda", frozenset({"lda-filing-types", "lda-general-issue-codes"})),
    ("nasa-technology", frozenset({"nasa-technology-taxonomy-8817"})),
    ("nature-of-suit", frozenset({"uscourts-nature-of-suit"})),
    ("oira", frozenset({"oira-review-controls"})),
    (
        "omb-a11",
        frozenset(
            {
                "omb-a11-apportionment-categories",
                "omb-a11-functional-classification",
                "omb-a11-object-classification",
            }
        ),
    ),
    ("oversight", frozenset({"oversight-report-types"})),
    ("pra", frozenset({"pra-icr-controls"})),
    (
        "regulatory-native",
        frozenset(
            {
                "regulatory-native-federal-register-agency-slug",
                "regulatory-native-federal-register-document-type",
                "regulatory-native-federal-register-presidential-subtype",
                "regulatory-native-federal-register-unresolved-agency-name",
                "regulatory-native-regulations-gov-attachment-format",
                "regulatory-native-regulations-gov-docket-agency-code",
                "regulatory-native-regulations-gov-docket-type",
                "regulatory-native-regulations-gov-document-agency-code",
                "regulatory-native-regulations-gov-document-type",
                "regulatory-native-unified-agenda-agency-code",
                "regulatory-native-unified-agenda-major-flag",
                "regulatory-native-unified-agenda-priority-category",
                "regulatory-native-unified-agenda-rin-status",
                "regulatory-native-unified-agenda-rule-stage",
            }
        ),
    ),
    (
        "regulations-gov",
        frozenset(
            {
                "regulations-gov-docket-type",
                "regulations-gov-document-type",
                "regulations-gov-submitter-type",
            }
        ),
    ),
    (
        "sam-assistance",
        frozenset(
            {
                "sam-assistance-assistance-types",
                "sam-assistance-eligible-applicant-types",
                "sam-assistance-eligible-beneficiary-types",
            }
        ),
    ),
    (
        "sam-opportunities",
        frozenset(
            {
                "sam-opportunities-notice-types",
                "sam-opportunities-opportunity-statuses",
                "sam-opportunities-set-aside-codes",
            }
        ),
    ),
    ("scotus", frozenset({"scotus-opinion-types"})),
    ("sec", frozenset({"sec-series-categories"})),
    (
        "unified-agenda",
        frozenset(
            {
                "unified-agenda-legal-authority-citation-types",
                "unified-agenda-priority-category",
                "unified-agenda-rule-stage",
                "unified-agenda-timetable-action",
            }
        ),
    ),
    ("usaspending", frozenset({"usaspending-award-types"})),
)
REGISTRY_CODE_RELEASE_KEYS = frozenset(
    key
    for _group_name, group_keys in REGISTRY_CODE_RELEASE_GROUPS
    for key in group_keys
)


def load_registry_code_releases(
    repo_root: Path,
    *,
    only_keys: Collection[str] | None = None,
) -> tuple[RegistryRelease, ...]:
    """Load selected exact, supported small registry code/value releases.

    The returned order is stable.  Every parser executes against the pinned
    local bytes for a selected source group, so stale pins and count drift fail
    before graph generation begins.
    """

    requested = normalize_only_keys(
        only_keys,
        allowed_keys=REGISTRY_CODE_RELEASE_KEYS,
        loader_name="load_registry_code_releases",
    )
    if requested == frozenset():
        return ()
    root = Path(repo_root)
    loaders: dict[
        str,
        tuple[Callable[..., tuple[RegistryRelease, ...]], bool],
    ] = {
        "billstatus": (_load_billstatus, True),
        "census": (_load_census, True),
        "census-geo": (_load_census_geo, True),
        "fcc": (_load_fcc, False),
        "fec": (_load_fec, True),
        "ferc": (_load_ferc, False),
        "govinfo": (_load_govinfo, True),
        "grants": (_load_grants, True),
        "lda": (_load_lda, True),
        "nasa-technology": (_load_nasa_technology, False),
        "nature-of-suit": (_load_nature_of_suit, False),
        "oira": (_load_oira, True),
        "omb-a11": (_load_omb_a11, True),
        "oversight": (_load_oversight, True),
        "pra": (_load_pra, False),
        "regulatory-native": (_load_regulatory_native_controls, False),
        "regulations-gov": (_load_regulations_gov, True),
        "sam-assistance": (_load_sam_assistance, True),
        "sam-opportunities": (_load_sam_opportunities, True),
        "scotus": (_load_scotus, True),
        "sec": (_load_sec, True),
        "unified-agenda": (_load_unified_agenda, True),
        "usaspending": (_load_usaspending, True),
    }
    releases: list[RegistryRelease] = []
    with tempfile.TemporaryDirectory(prefix="refspec-atlas-v3-registry-") as directory:
        temporary = Path(directory)
        for group_name, group_keys in REGISTRY_CODE_RELEASE_GROUPS:
            if not wants_group(requested, group_keys):
                continue
            loader, needs_temporary = loaders[group_name]
            loaded = (
                loader(root, temporary)
                if needs_temporary
                else loader(root)
            )
            releases.extend(
                select_declared_group(
                    loaded,
                    declared_keys=group_keys,
                    requested_keys=requested,
                    loader_name=loader.__name__,
                )
            )
    keys = [release.key for release in releases]
    if len(keys) != len(set(keys)):
        raise ValueError("small registry loaders produced duplicate release keys")
    return tuple(sorted(releases, key=lambda release: release.key))


__all__ = [
    "REGISTRY_CODE_RELEASE_GROUPS",
    "REGISTRY_CODE_RELEASE_KEYS",
    "load_registry_code_releases",
]
