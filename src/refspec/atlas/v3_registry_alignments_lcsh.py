"""The one consolidated LCSH vocabulary release the held mappings resolve against.

REF-040 (docs/decisions.md) retires three separate LCSH endpoint releases --
``lcsh-eurovoc-alignment-endpoints-2026-08-06`` (alignments.py),
``lcsh-external-links-endpoints-2026-08-15`` (v3_registry_alignments_lc.py),
and ``lcsh-mesh-mapping-endpoints-2026-08-15`` (v3_registry_alignments_subject.py)
-- and replaces them with one release minted from the single pinned LCSH bulk
file via ``refspec.registry.lcsh_topical``.

**Scope, stated exactly.** This release emits every CURRENT LCSH authority of
every authority class the file carries (Topic, Geographic, ComplexSubject,
CorporateName, and the rest -- LCSH mapping targets are not limited to
topical headings), plus only the deprecated authorities that a held FAST, LC
external-links, MeSH-LCSH, or EuroVoc-LCSH mapping candidate actually names
as an LCSH-side IRI. A deprecated heading nothing points at is never
emitted. Every emitted deprecated member keeps LC's own
``madsrdf:DeprecatedAuthority`` status, ``madsrdf:useInstead`` successor
IRIs, and ``madsrdf:deletionNote`` verbatim in its native payload; nothing
here infers, resolves, or hides a successor -- that is a display choice for
a consumer, not a fact this release omits. This release never assembles a
general-purpose LCSH concept scheme: RefSpec's LCSH scope remains
mapping-only (see ``refspec.registry.lcsh_topical``'s module docstring).

**Minted IRIs are byte-identical to what the three retired releases emitted.**
Every resource this release emits keeps the exact ``id.loc.gov`` IRI the
retired releases used, so every existing mapping assertion that names one
still resolves; only the owning release changes.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

from refspec.atlas.v3_registry_large import load_fast_topical_release
from refspec.atlas.v3_source_data import (
    RegistryInputPin,
    RegistryLabel,
    RegistryRelation,
    RegistryRelease,
    RegistryResource,
    canonical_digest,
)
from refspec.registry import lc_external_links as external
from refspec.registry import lcsh_mesh_mapping as mesh_lcsh
from refspec.registry import lcsh_topical as lcsh
from refspec.registry.eurovoc_lcsh_alignment import (
    EUROVOC_LCSH_ALIGNMENT_BYTE_LENGTH,
    EUROVOC_LCSH_ALIGNMENT_FILENAME,
    EUROVOC_LCSH_ALIGNMENT_SHA256,
    EUROVOC_LCSH_ALIGNMENT_URL,
    parse_eurovoc_lcsh_alignment_file,
)
from refspec.vocabulary import is_english_language_tag

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE_ROOT = REPOSITORY_ROOT / "output" / "registry-real-data-sources"

LCSH_BULK_FILENAME = "lcsh-subjects-madsrdf-2026-08-06.jsonld.gz"
LCSH_BULK_SHA256 = "sha256:b33adc284bfb98e39c1331927e9ffee3d73dd0b1b83342906b6ea52c408a5856"
LCSH_BULK_BYTE_LENGTH = 140_187_915
LCSH_BULK_CAPTURED_AT = "2026-08-06"

LCSH_CONSOLIDATED_RELEASE_KEY = "lcsh-subjects-consolidated-2026-08-06"
LCSH_CONSOLIDATED_ATLAS_RELEASE_IRI = "urn:ref:atlas-release:3:lcsh-subjects:consolidated:2026-08-06"
LCSH_CONSOLIDATED_SOURCE_RELEASE_IRI = "urn:ref:source-release:lcsh-subjects:consolidated:2026-08-06"
LCSH_CONSOLIDATED_SCHEME_IRI = "urn:ref:atlas-resource-scheme:lcsh-subjects"

# The declaration module tools/generate_atlas_v3_full.py's adapter-recipe
# group machinery (``_adapter_group_module``) needs to pin THIS module's own
# bytes into the release's provenance recipe: the four input pins and both
# ``gather_referenced_lcsh_iris`` and ``load_lcsh_consolidated_release`` live
# here now, not in v3_registry_alignments.py, which only re-exports the
# loader. See tests/test_atlas_v3_registry_alignments_lcsh.py's
# ``test_recipe_closure_pins_this_module`` for the gap this closes.
LCSH_CONSOLIDATED_RELEASE_KEYS = frozenset({LCSH_CONSOLIDATED_RELEASE_KEY})

# The three retired endpoint releases this one replaces. Retained here, not
# just in prose, so the portfolio and coverage generators can name exactly
# what retired without re-deriving it.
RETIRED_LCSH_ENDPOINT_RELEASE_KEYS = (
    "lcsh-eurovoc-alignment-endpoints-2026-08-06",
    "lcsh-external-links-endpoints-2026-08-15",
    "lcsh-mesh-mapping-endpoints-2026-08-15",
)

LCSH_CONSOLIDATED_SCOPE_STATEMENT = (
    "Every current LCSH authority of every authority class in the pinned "
    "2026-08-06 bulk file (Topic, Geographic, ComplexSubject, CorporateName, "
    "and the rest), plus only the deprecated authorities a held FAST, LC "
    "external-links, MeSH-LCSH, or EuroVoc-LCSH mapping candidate names as an "
    "LCSH-side IRI. A deprecated heading nothing points at is excluded. "
    "Deprecated members keep LC's own status, useInstead successor IRIs, "
    "and deletion note verbatim. This is not a general-purpose LCSH concept "
    "scheme: RefSpec's LCSH scope remains mapping-only."
)


def _pin(source_root: Path, *, filename: str, sha256: str, byte_length: int, source_iri: str, role: str) -> RegistryInputPin:
    return RegistryInputPin(
        path=Path(source_root) / filename,
        logical_path=f"refspec/output/registry-real-data-sources/{filename}",
        sha256=sha256,
        byte_length=byte_length,
        source_iri=source_iri,
        role=role,
    )


def _lcsh_bulk_pin(source_root: Path) -> RegistryInputPin:
    return _pin(
        source_root,
        filename=LCSH_BULK_FILENAME,
        sha256=LCSH_BULK_SHA256,
        byte_length=LCSH_BULK_BYTE_LENGTH,
        source_iri=lcsh.LCSH_TOPICAL_MADS_NDJSON_URL,
        role="publisherBulkSource",
    )


def _eurovoc_alignment_pin(source_root: Path) -> RegistryInputPin:
    return _pin(
        source_root,
        filename=EUROVOC_LCSH_ALIGNMENT_FILENAME,
        sha256=EUROVOC_LCSH_ALIGNMENT_SHA256,
        byte_length=EUROVOC_LCSH_ALIGNMENT_BYTE_LENGTH,
        source_iri=EUROVOC_LCSH_ALIGNMENT_URL,
        role="referencedIriSelection",
    )


def _lc_external_links_pin(source_root: Path) -> RegistryInputPin:
    return _pin(
        source_root,
        filename=external.LC_EXTERNAL_LINKS_FILENAME,
        sha256=external.LC_EXTERNAL_LINKS_SHA256,
        byte_length=external.LC_EXTERNAL_LINKS_BYTE_LENGTH,
        source_iri=external.LC_EXTERNAL_LINKS_URL,
        role="referencedIriSelection",
    )


def _mesh_lcsh_mapping_pin(source_root: Path) -> RegistryInputPin:
    return _pin(
        source_root,
        filename=mesh_lcsh.LCSH_MESH_MAPPING_FILENAME,
        sha256=mesh_lcsh.LCSH_MESH_MAPPING_SHA256,
        byte_length=mesh_lcsh.LCSH_MESH_MAPPING_BYTE_LENGTH,
        source_iri=mesh_lcsh.LCSH_MESH_MAPPING_SOURCE_URL,
        role="referencedIriSelection",
    )


@lru_cache(maxsize=8)
def _cached_fast_topical_release(source_root: Path = DEFAULT_SOURCE_ROOT) -> RegistryRelease:
    """Cache the FAST release load.

    ``load_fast_topical_release`` itself is not cached, and both
    ``gather_referenced_lcsh_iris`` (to read each FAST resource's
    ``lcshLinks``) and ``_lcsh_referenced_selection_pins`` (to declare the
    FAST archive pins that union reads) need the identical loaded release in
    one process. Reparsing the FAST snapshot a second time would repeat a
    multi-second scan for a result that never differs.
    """

    return load_fast_topical_release(source_root)


@lru_cache(maxsize=8)
def _lcsh_referenced_selection_pins(source_root: Path = DEFAULT_SOURCE_ROOT) -> tuple[RegistryInputPin, ...]:
    """Every pin ``gather_referenced_lcsh_iris`` actually reads to select referenced deprecated headings.

    Declared once, separate from the LCSH bulk pin itself, so
    ``load_lcsh_consolidated_release`` can name every file its own selection
    depends on in ``inputs`` -- not only the bulk file its members are
    minted from. These are processing dependencies this release's own
    capture logic reads to decide deprecated-heading membership, the same
    role the retired ``load_lcsh_external_links_endpoint_release`` gave its
    ``(bulk_pin, external_pin, selection_pin, *fast_release.inputs)`` tuple
    before REF-040 folded it into this module.
    """

    fast_release = _cached_fast_topical_release(source_root)
    return (
        _eurovoc_alignment_pin(source_root),
        _lc_external_links_pin(source_root),
        _mesh_lcsh_mapping_pin(source_root),
        *fast_release.inputs,
    )


@lru_cache(maxsize=8)
def gather_referenced_lcsh_iris(source_root: Path = DEFAULT_SOURCE_ROOT) -> frozenset[str]:
    """Union of every LCSH-side IRI a held mapping candidate names.

    "Held" means the source artifact is pinned and captured in this corpus,
    not that every candidate row survives its *other* endpoint's own
    availability check. Admitting a deprecated heading that only such a row
    names costs nothing and keeps the selection simple to audit; whether
    that row is ultimately emitted is each mapping loader's own decision,
    unaffected by this union.

    Cached: three independent mapping loaders each need this set, and it is
    a pure function of pinned bytes this process never mutates.
    """

    referenced: set[str] = set()

    alignment_pin, external_pin, mesh_pin, *_fast_pins = _lcsh_referenced_selection_pins(source_root)

    alignment_pin.verify()
    alignment = parse_eurovoc_lcsh_alignment_file(alignment_pin.path)
    referenced.update(alignment.lcsh_concept_iris)

    fast_release = _cached_fast_topical_release(source_root)
    for resource in fast_release.resources:
        raw_links = resource.native_payload.get("lcshLinks")
        if not isinstance(raw_links, list):
            continue
        for raw_link in raw_links:
            if not isinstance(raw_link, Mapping):
                continue
            target_iri = raw_link.get("targetIri")
            if isinstance(target_iri, str):
                referenced.add(target_iri)

    external_pin.verify()
    external_capture = external.load_lc_external_links_capture(external_pin.path)
    referenced.update(external_capture.lcsh_subject_iris)

    mesh_pin.verify()
    mesh_capture = mesh_lcsh.load_lcsh_mesh_mapping(mesh_pin.path)
    referenced.update(row.object_iri for row in mesh_capture.mappings if row.object_iri.startswith(lcsh.LCSH_SUBJECTS_SCHEME_IRI + "/"))

    return frozenset(referenced)


def _resource_labels(record: lcsh.LcshTopicalRecord) -> tuple[RegistryLabel, ...]:
    if not is_english_language_tag(record.preferred_label.language):
        raise ValueError(f"LCSH consolidated member has no English preferred label: {record.concept_iri}")
    field = "madsrdf:variantLabel" if record.is_deprecated else "madsrdf:authoritativeLabel"
    labels = [
        RegistryLabel(
            value=record.preferred_label.value.strip(),
            role="preferred",
            source_path=f"line-{record.line_number}:{field}",
        )
    ]
    seen = {labels[0].value}
    for index, label in enumerate(record.variant_labels):
        if not is_english_language_tag(label.language):
            continue
        value = label.value.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        labels.append(
            RegistryLabel(
                value=value,
                role="alternate",
                source_path=f"line-{record.line_number}:madsrdf:hasVariant[{index}]",
            )
        )
    return tuple(labels)


def _resource(record: lcsh.LcshTopicalRecord) -> RegistryResource:
    native_payload: dict[str, object] = {
        "authorityTypes": list(record.authority_types),
        "broaderIris": list(record.broader_iris),
        "deprecation": {
            "deletionNote": (record.deletion_note.value if record.deletion_note is not None else None),
            "deprecated": record.is_deprecated,
            "useInsteadIris": list(record.use_instead_iris),
        },
        "lccn": record.lccn,
        "lineNumber": record.line_number,
        "recordByteLength": record.source_byte_length,
        "recordDigest": record.source_sha256,
    }
    return RegistryResource(
        iri=record.concept_iri,
        labels=_resource_labels(record),
        native_payload=native_payload,
        source_locator=f"{record.source_url}#line-{record.line_number}",
        source_digest=record.source_sha256,
        notations=(() if record.lccn is None else (record.lccn,)),
        status="deprecated" if record.is_deprecated else "current",
    )


@lru_cache(maxsize=8)
def load_lcsh_consolidated_release(
    source_root: Path = DEFAULT_SOURCE_ROOT,
) -> RegistryRelease:
    """Load every current LCSH heading plus only the referenced deprecated ones.

    Cached: this is the one release the FAST-LCSH, LC external-links, and
    MeSH-LCSH mapping loaders all depend on, and every caller in one process
    must see the exact same immutable result -- reloading it per caller
    would only repeat a ~75s scan for a result that never differs within a
    process.
    """

    bulk_pin = _lcsh_bulk_pin(source_root)
    bulk_pin.verify()
    referenced_iris = gather_referenced_lcsh_iris(source_root)
    capture = lcsh.capture_lcsh_current_and_referenced_deprecated_from_gzip_path(
        bulk_pin.path,
        source_url=bulk_pin.source_iri,
        referenced_iris=referenced_iris,
    )
    all_records = (*capture.current_records, *capture.deprecated_records)
    record_iris = frozenset(record.concept_iri for record in all_records)
    resources = tuple(_resource(record) for record in sorted(all_records, key=lambda item: item.concept_iri))
    relations = tuple(
        RegistryRelation(
            subject=record.concept_iri,
            predicate="http://www.w3.org/2004/02/skos/core#broader",
            object=broader,
            source_payload={
                "lineNumber": record.line_number,
                "objectIri": broader,
                "predicateIri": "http://www.w3.org/2004/02/skos/core#broader",
                "subjectIri": record.concept_iri,
            },
        )
        for record in sorted(all_records, key=lambda item: item.concept_iri)
        for broader in record.broader_iris
        if broader in record_iris
    )
    type_counts = Counter(
        authority_type
        for record in all_records
        for authority_type in record.authority_types
        if authority_type not in ("madsrdf:Authority", "madsrdf:DeprecatedAuthority", "madsrdf:Variant")
    )
    dropped_label_count = sum(
        not is_english_language_tag(label.language) for record in all_records for label in record.variant_labels
    )
    referenced_selection_digest = canonical_digest(
        {
            "publisherBulkDigest": bulk_pin.sha256,
            "referencedIris": sorted(referenced_iris),
        }
    )
    # This release does not only emit members from the bulk file: it reads
    # the EuroVoc-LCSH alignment, LC external-links, MeSH-LCSH mapping, and
    # FAST archives to decide which deprecated headings are referenced (see
    # gather_referenced_lcsh_iris). Those are processing dependencies, not
    # evidence a mapping assertion cites -- but the release still read them,
    # so they belong in ``inputs`` rather than being left undeclared. Matches
    # the retired load_lcsh_external_links_endpoint_release's
    # ``(bulk_pin, external_pin, selection_pin, *fast_release.inputs)`` shape.
    inputs = (bulk_pin, *_lcsh_referenced_selection_pins(source_root))
    return RegistryRelease(
        key=LCSH_CONSOLIDATED_RELEASE_KEY,
        resource_id="lcsh-subjects",
        source_module="refspec.registry.lcsh_topical",
        profile="conceptScheme",
        ring="subject",
        scope="captureSubset",
        issued=LCSH_BULK_CAPTURED_AT,
        source_release_iri=LCSH_CONSOLIDATED_SOURCE_RELEASE_IRI,
        source_release_digest=referenced_selection_digest,
        atlas_release_iri=LCSH_CONSOLIDATED_ATLAS_RELEASE_IRI,
        scheme_iri=LCSH_CONSOLIDATED_SCHEME_IRI,
        inputs=inputs,
        resources=resources,
        relations=relations,
        dropped_label_count=dropped_label_count,
        metadata={
            "authorityTypeCounts": dict(sorted(type_counts.items())),
            "completePublisherRelease": False,
            "consolidatesRetiredReleases": list(RETIRED_LCSH_ENDPOINT_RELEASE_KEYS),
            "currentHeadingCount": len(capture.current_records),
            "deprecatedHeadingsExcludedCount": (capture.total_deprecated_seen - len(capture.deprecated_records)),
            "deprecatedHeadingsRetainedCount": len(capture.deprecated_records),
            "deprecatedTotalInPublisherFile": capture.total_deprecated_seen,
            "linesScanned": capture.lines_scanned,
            "missingReferencedIriCount": len(capture.missing_referenced_iris),
            "missingReferencedIris": sorted(capture.missing_referenced_iris),
            "publisherBulkDigest": bulk_pin.sha256,
            "referencedIriCount": len(referenced_iris),
            "scopeStatement": LCSH_CONSOLIDATED_SCOPE_STATEMENT,
            "selectionRule": "all-current-headings-plus-referenced-deprecated-headings",
            "sourceIdentifierCount": 0,
        },
    )


__all__ = [
    "DEFAULT_SOURCE_ROOT",
    "LCSH_BULK_BYTE_LENGTH",
    "LCSH_BULK_CAPTURED_AT",
    "LCSH_BULK_FILENAME",
    "LCSH_BULK_SHA256",
    "LCSH_CONSOLIDATED_ATLAS_RELEASE_IRI",
    "LCSH_CONSOLIDATED_RELEASE_KEY",
    "LCSH_CONSOLIDATED_RELEASE_KEYS",
    "LCSH_CONSOLIDATED_SCHEME_IRI",
    "LCSH_CONSOLIDATED_SCOPE_STATEMENT",
    "LCSH_CONSOLIDATED_SOURCE_RELEASE_IRI",
    "RETIRED_LCSH_ENDPOINT_RELEASE_KEYS",
    "gather_referenced_lcsh_iris",
    "load_lcsh_consolidated_release",
]
