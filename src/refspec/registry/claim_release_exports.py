"""Pinned EuroVoc and GEMET exports for the shared registry claim release."""

from __future__ import annotations

import tempfile
from collections import Counter
from pathlib import Path

from rdflib.namespace import SKOS

from refspec.registry.eurovoc_thesaurus import (
    EUROVOC_RELEASE_4_24,
    acquire_eurovoc_release,
    parse_acquired_eurovoc_release,
)
from refspec.registry.gemet_thesaurus import (
    GEMET_RELEASE_4_2_3,
    SKOS_MAPPING_PREDICATE_IRIS,
    parse_gemet_file,
)
from refspec.registry.infrastructure.rdf_claim_export import (
    RdfClaimExtraction,
    extract_rdf_claims,
    parse_rdf_graph,
)
from refspec.registry.infrastructure.registry_claim_release import (
    RegistryClaim,
    RegistryClaimReleaseError,
    RegistryClaimReleaseView,
    RegistryRawInput,
    build_registry_claim_release,
)

EUROVOC_CLAIM_RELEASE_ID = "urn:ref:registry-claim-release:eurovoc:4.24"
GEMET_CLAIM_RELEASE_ID = "urn:ref:registry-claim-release:gemet:4.2.3"
EUROVOC_RECIPE_ID = "urn:ref:recipe:registry-claim:eurovoc-skos-core:1.0"
GEMET_RECIPE_ID = "urn:ref:recipe:registry-claim:gemet-rdf-xml:1.0"
ENGLISH_LIMITATION_ID = "urn:ref:limitation:registry-claim:english-only:1.0"
RDF_BLANK_NODE_LIMITATION_ID = (
    "urn:ref:limitation:registry-claim:rdf-blank-node-shapes:1.0"
)

EUROVOC_ARCHIVE_LOCAL_NAME = "eurovoc-4.24-skos-core.zip"
EUROVOC_METADATA_LOCAL_NAME = "eurovoc-4.24-metadata.ttl"
GEMET_LOCAL_NAME = "gemet.rdf"


def _source_path(root: Path, filename: str) -> Path:
    path = root / filename
    if path.is_symlink() or not path.is_file():
        raise RegistryClaimReleaseError(
            f"pinned registry source is missing or unsafe: {path}"
        )
    return path


def _language_scope(extractions: tuple[RdfClaimExtraction, ...]) -> dict[str, object]:
    return {
        "included": ["en", "en-*", "untagged"],
        "mode": "englishOnly",
        "omittedBlankNodeClaimCount": sum(
            value.omitted_blank_node_claim_count for value in extractions
        ),
        "omittedNonEnglishLiteralCount": sum(
            value.omitted_non_english_literal_count for value in extractions
        ),
        "omittedUnsupportedTermCount": sum(
            value.omitted_unsupported_term_count for value in extractions
        ),
    }


def _limitations(extractions: tuple[RdfClaimExtraction, ...]) -> tuple[dict[str, str], ...]:
    result = [
        {
            "description": (
                "The release includes English and untagged literals; exact raw "
                "captures retain non-English literals outside the claim table."
            ),
            "id": ENGLISH_LIMITATION_ID,
        }
    ]
    if any(value.omitted_blank_node_claim_count for value in extractions):
        result.append(
            {
                "description": (
                    "RDF statements containing blank nodes remain in the pinned raw "
                    "capture because registry claims require durable IRI subjects and "
                    "IRI or literal objects."
                ),
                "id": RDF_BLANK_NODE_LIMITATION_ID,
            }
        )
    return tuple(sorted(result, key=lambda row: row["id"]))


def _predicate_counts(claims: tuple[RegistryClaim, ...]) -> Counter[str]:
    return Counter(claim.predicate for claim in claims)


def export_eurovoc_4_24_claim_release(
    source_root: Path,
    output: Path,
) -> RegistryClaimReleaseView:
    """Export the exact pinned EuroVoc 4.24 SKOS Core and metadata release."""

    release = EUROVOC_RELEASE_4_24
    archive_path = _source_path(source_root, EUROVOC_ARCHIVE_LOCAL_NAME)
    metadata_path = _source_path(source_root, EUROVOC_METADATA_LOCAL_NAME)
    with tempfile.TemporaryDirectory(prefix="refspec-eurovoc-claim-export-") as raw:
        acquired = acquire_eurovoc_release(
            release,
            Path(raw),
            source_path=archive_path,
            metadata_path=metadata_path,
            include_metadata=True,
        )
        parsed = parse_acquired_eurovoc_release(acquired)
        if acquired.metadata is None:
            raise RegistryClaimReleaseError(
                "EuroVoc claim export requires the pinned metadata input"
            )
        core = extract_rdf_claims(
            parse_rdf_graph(
                acquired.path.read_bytes(),
                rdf_format="xml",
                public_id=release.source_url,
            ),
            release_id=EUROVOC_CLAIM_RELEASE_ID,
            source_locator=release.source_url,
            source_digest=release.expected_member_sha256,
            logical_path=(
                f"raw/{EUROVOC_ARCHIVE_LOCAL_NAME}!/{release.member_filename}"
            ),
            recipe_id=EUROVOC_RECIPE_ID,
        )
        metadata_source = release.metadata_source
        if metadata_source is None:
            raise RegistryClaimReleaseError(
                "EuroVoc 4.24 has no declared metadata source"
            )
        metadata = extract_rdf_claims(
            parse_rdf_graph(
                acquired.metadata.path.read_bytes(),
                rdf_format="turtle",
                public_id=metadata_source.source_url,
            ),
            release_id=EUROVOC_CLAIM_RELEASE_ID,
            source_locator=metadata_source.source_url,
            source_digest=metadata_source.expected_sha256,
            logical_path=f"raw/{EUROVOC_METADATA_LOCAL_NAME}",
            recipe_id=EUROVOC_RECIPE_ID,
        )
    claims = tuple(
        sorted((*core.claims, *metadata.claims), key=RegistryClaim.sort_key)
    )
    memberships = _predicate_counts(claims)[str(SKOS.inScheme)]
    if memberships != 15_438:
        raise RegistryClaimReleaseError(
            f"EuroVoc claim release has {memberships} memberships, expected 15438"
        )
    return build_registry_claim_release(
        output,
        release_id=EUROVOC_CLAIM_RELEASE_ID,
        release_key=release.release_id,
        issued=release.issued,
        release_scope={
            "complete": True,
            "mode": "publisherRelease",
            "population": "EuroVoc 4.24 SKOS Core plus release metadata",
        },
        language_scope=_language_scope((core, metadata)),
        recipes=(
            {
                "description": (
                    "Verify the pinned ZIP, its sole RDF/XML member, and metadata "
                    "Turtle; retain every IRI claim and every English or untagged "
                    "literal without normalization."
                ),
                "id": EUROVOC_RECIPE_ID,
                "implementation": "refspec.registry.claim_release_exports",
                "version": "1.0",
            },
        ),
        limitations=_limitations((core, metadata)),
        claims=claims,
        raw_inputs=(
            RegistryRawInput(
                path=archive_path,
                logical_path=f"raw/{EUROVOC_ARCHIVE_LOCAL_NAME}",
                source_locator=release.source_url,
                role="publisherArchive",
                archive_members=(
                    {
                        "byteLength": release.expected_member_byte_length,
                        "path": release.member_filename,
                        "sha256": release.expected_member_sha256,
                    },
                ),
            ),
            RegistryRawInput(
                path=metadata_path,
                logical_path=f"raw/{EUROVOC_METADATA_LOCAL_NAME}",
                source_locator=metadata_source.source_url,
                role="publisherMetadata",
            ),
        ),
        metadata={
            "attribution": release.attribution,
            "claimCount": len(claims),
            "conceptCount": len(parsed.concepts),
            "domainCount": len(parsed.domains),
            "licenseIri": release.license_iri,
            "membershipCount": memberships,
            "publisher": release.publisher,
            "sourceTripleCount": core.source_triple_count
            + metadata.source_triple_count,
            "version": release.version,
        },
    )


def export_gemet_4_2_3_claim_release(
    source_root: Path,
    output: Path,
) -> RegistryClaimReleaseView:
    """Export the exact pinned, decompressed GEMET 4.2.3 RDF/XML release."""

    release = GEMET_RELEASE_4_2_3
    source_path = _source_path(source_root, GEMET_LOCAL_NAME)
    parsed = parse_gemet_file(
        source_path,
        source_url=release.source_url,
        expected_sha256=release.expected_sha256,
        expected_byte_length=release.expected_byte_length,
    )
    extraction = extract_rdf_claims(
        parse_rdf_graph(
            source_path.read_bytes(),
            rdf_format="xml",
            public_id=release.source_url,
        ),
        release_id=GEMET_CLAIM_RELEASE_ID,
        source_locator=release.source_url,
        source_digest=release.expected_sha256,
        logical_path=f"raw/{GEMET_LOCAL_NAME}",
        recipe_id=GEMET_RECIPE_ID,
    )
    counts = _predicate_counts(extraction.claims)
    mapping_count = sum(counts[predicate] for predicate in SKOS_MAPPING_PREDICATE_IRIS)
    expected = {
        "collectionMemberships": (str(SKOS.member), 16_178),
        "groupMemberships": (str(SKOS.inScheme), 5_651),
        "mappingRelations": ("mapping", 9_658),
        "subgroupRelations": (
            "http://www.eionet.europa.eu/gemet/2004/06/gemet-schema.rdf#subGroupOf",
            32,
        ),
    }
    observed = {
        name: mapping_count if predicate == "mapping" else counts[predicate]
        for name, (predicate, _count) in expected.items()
    }
    mismatches = {
        name: {"actual": observed[name], "expected": count}
        for name, (_predicate, count) in expected.items()
        if observed[name] != count
    }
    if mismatches:
        raise RegistryClaimReleaseError(
            f"GEMET claim release structure counts differ: {mismatches}"
        )
    return build_registry_claim_release(
        output,
        release_id=GEMET_CLAIM_RELEASE_ID,
        release_key="gemet-4.2.3",
        issued="2021-12-06",
        release_scope={
            "complete": True,
            "mode": "publisherRelease",
            "population": "GEMET 4.2.3 decompressed RDF/XML",
        },
        language_scope=_language_scope((extraction,)),
        recipes=(
            {
                "description": (
                    "Verify and parse the pinned decompressed RDF/XML; retain every "
                    "IRI claim and every English or untagged literal without "
                    "normalization."
                ),
                "id": GEMET_RECIPE_ID,
                "implementation": "refspec.registry.claim_release_exports",
                "version": "1.0",
            },
        ),
        limitations=_limitations((extraction,)),
        claims=extraction.claims,
        raw_inputs=(
            RegistryRawInput(
                path=source_path,
                logical_path=f"raw/{GEMET_LOCAL_NAME}",
                source_locator=release.source_url,
                role="decompressedPublisherSource",
            ),
        ),
        metadata={
            "attribution": release.attribution,
            "claimCount": len(extraction.claims),
            "collectionMembershipCount": observed["collectionMemberships"],
            "conceptCount": len(parsed.concepts),
            "groupMembershipCount": observed["groupMemberships"],
            "licenseIri": release.license_iri,
            "mappingRelationCount": observed["mappingRelations"],
            "publisher": release.publisher,
            "sourceTripleCount": extraction.source_triple_count,
            "subgroupRelationCount": observed["subgroupRelations"],
            "version": release.version,
        },
    )


__all__ = [
    "EUROVOC_CLAIM_RELEASE_ID",
    "GEMET_CLAIM_RELEASE_ID",
    "export_eurovoc_4_24_claim_release",
    "export_gemet_4_2_3_claim_release",
]
