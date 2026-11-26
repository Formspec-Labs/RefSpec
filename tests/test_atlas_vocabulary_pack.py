"""Focused unit and DI contract tests for AtlasVocabularyPack and scoped view verification."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import subprocess
import sys
from array import array
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from refspec.atlas.compact_pack import CompactRecordRole
from refspec.atlas.parquet_artifact import arrow_schema_sha256, canonical_payload_sha256, file_sha256
from refspec.atlas.parquet_search_view import (
    _DICTIONARIES,
    _OMITTED_FIELDS,
    _SCHEMAS,
    MANIFEST_FILE,
    SEARCH_VIEW_ID_PREFIX,
    SEARCH_VIEW_RECORD_TYPE,
    SEARCH_VIEW_SCHEMA_VERSION,
    AtlasParquetSearchViewError,
    verify_atlas_parquet_search_view,
)
from refspec.atlas.parquet_tables import DERIVED_RELATION_ROLE, DERIVED_RELATION_TABLE_SCHEMA
from refspec.atlas.vocabulary_pack import (
    PACK_SCHEMA_VERSION,
    AtlasVocabularyPack,
    PriorGuidedSemanticIndex,
    VocabularyPackManifest,
    build_vocabulary_pack,
)
from refspec.atlas.vocabulary_pack_build import (
    DEFAULT_STRUCTURAL_LONG_LABEL_CHARS,
    DEFAULT_STRUCTURAL_LONG_LABEL_PENALTY,
    DEFAULT_STRUCTURAL_SUBDIVISION_PENALTY,
    _iterative_tarjan_sccs,
    _to_little_endian_bytes,
)
from refspec.atlas.vocabulary_pack_cli import main as cli_main
from refspec.atlas.vocabulary_protocols import (
    DEFAULT_CURATED_SCHEME_WEIGHTS,
    DEFAULT_EXTRACT_MAX_UNIGRAM_DOC_FREQ,
    DEFAULT_MIN_COSINE,
    REGULATORY_BENCHMARK_SCHEME_PRESET,
    AgencyHistoryProvider,
    AuthorityReranker,
    CandidateReranker,
    ExactPinnedRRF,
    GraphExpander,
    LookupPolicy,
    QueryEncoder,
    RankFusionPolicy,
    RelationPolicy,
    SemanticIndex,
    VocabularyInputError,
    VocabularyPackError,
    VocabularyProvider,
    group_by_identical_label,
    normalize_text,
)
from refspec.registry.infrastructure.artifact_serialization import canonical_json_bytes

S_EURO = "urn:ref:atlas-resource-scheme:eurovoc"
S_FR = "urn:ref:atlas-resource-scheme:federal-register-thesaurus-2025"
S_LCSH = "urn:ref:atlas-resource-scheme:lcsh-subjects"
S_UMTHES = "urn:ref:atlas-resource-scheme:umthes"
S_MESH = "urn:ref:atlas-resource-scheme:mesh-descriptors"

R_EURO = "urn:ref:atlas-release:3:eurovoc:4.24"
R_FR = "urn:ref:atlas-release:3:federal-register-thesaurus:2025-04-01"
R_LCSH = "urn:ref:atlas-release:3:lcsh-subjects:consolidated:2026-08-06"
R_UMTHES = "urn:ref:atlas-release:3:umthes:gemet-endpoints:2026-08-15"
R_MESH = "urn:ref:atlas-release:3:mesh-descriptors:2026"

SKOS = "http://www.w3.org/2004/02/skos/core#"
OFFICIAL_ROLE = "https://rulespec.org/ns/v1#officialSourceMetadata"
TEXTUAL_ROLE = "https://rulespec.org/ns/v1#textualEvidence"
APPROVED = "https://rulespec.org/ns/v1#approved"


def _hex32(seed: int) -> bytes:
    return bytes([seed % 256]) * 32


def _refresh_pack_blobs(con: sqlite3.Connection) -> None:
    """Recompute schema v3 pack_meta_blobs after direct SQL test fixture mutations."""

    max_row = con.execute("SELECT max(rid) FROM resources").fetchone()
    max_rid = int(max_row[0]) if max_row and max_row[0] is not None else 0
    priors = array("f", [0.0]) * (max_rid + 1)
    sids = array("H", [0]) * (max_rid + 1)
    for rid, sid, pref in con.execute("SELECT rid, sid, pref_label FROM resources"):
        r_int = int(rid)
        sids[r_int] = int(sid)
        if pref:
            p = 0.0
            depth = pref.count("--")
            if depth > 0:
                p -= DEFAULT_STRUCTURAL_SUBDIVISION_PENALTY * depth
            if len(pref) > DEFAULT_STRUCTURAL_LONG_LABEL_CHARS:
                p -= DEFAULT_STRUCTURAL_LONG_LABEL_PENALTY
            priors[r_int] = p
    con.execute(
        "INSERT OR REPLACE INTO pack_meta_blobs (key, payload) VALUES ('structural_prior_f32', ?)",
        (sqlite3.Binary(_to_little_endian_bytes(priors)),),
    )
    con.execute(
        "INSERT OR REPLACE INTO pack_meta_blobs (key, payload) VALUES ('sid_by_rid_u16', ?)",
        (sqlite3.Binary(_to_little_endian_bytes(sids)),),
    )


def _write_compact_fixture(root: Path, *, include_derived: bool = True) -> tuple[Path, str]:
    """Write a complete, schema-valid Atlas 3.1 compact Parquet search view fixture."""

    tables_dir = root / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    resources = [
        {
            "id": "http://eurovoc.europa.eu/3027",
            "release": R_EURO,
            "scheme": S_EURO,
            "semantic_ring": "subject",
            "resource_profile": "Concept",
            "source_record": "urn:ref:atlas-source-record:" + "1" * 64,
            "definition": "Offence committed via computer systems and networks.",
            "notes": [],
            "notations": ["3027"],
            "record_status": "active",
        },
        {
            "id": "http://eurovoc.europa.eu/9001",
            "release": R_EURO,
            "scheme": S_EURO,
            "semantic_ring": "subject",
            "resource_profile": "Concept",
            "source_record": "urn:ref:atlas-source-record:" + "2" * 64,
            "definition": "Evidence collected from digital devices.",
            "notes": [],
            "notations": ["9001"],
            "record_status": "active",
        },
        {
            "id": "urn:ref:fr:medicare",
            "release": R_FR,
            "scheme": S_FR,
            "semantic_ring": "subject",
            "resource_profile": "Concept",
            "source_record": "urn:ref:atlas-source-record:" + "3" * 64,
            "definition": "Federal health insurance program for older adults.",
            "notes": [],
            "notations": [],
            "record_status": "active",
        },
        {
            "id": "urn:ref:fr:flood-insurance",
            "release": R_FR,
            "scheme": S_FR,
            "semantic_ring": "subject",
            "resource_profile": "Concept",
            "source_record": "urn:ref:atlas-source-record:" + "4" * 64,
            "definition": "Coverage protecting properties from rising water.",
            "notes": [],
            "notations": [],
            "record_status": "active",
        },
        {
            "id": "urn:ref:fr:housing",
            "release": R_FR,
            "scheme": S_FR,
            "semantic_ring": "subject",
            "resource_profile": "Concept",
            "source_record": "urn:ref:atlas-source-record:" + "5" * 64,
            "definition": "Residential dwellings and housing assistance.",
            "notes": [],
            "notations": [],
            "record_status": "active",
        },
        {
            "id": "http://eurovoc.europa.eu/1234",
            "release": R_EURO,
            "scheme": S_EURO,
            "semantic_ring": "subject",
            "resource_profile": "Concept",
            "source_record": "urn:ref:atlas-source-record:" + "6" * 64,
            "definition": "European housing policy and dwellings.",
            "notes": [],
            "notations": [],
            "record_status": "active",
        },
        {
            "id": "http://id.loc.gov/authorities/subjects/sh85029492",
            "release": R_LCSH,
            "scheme": S_LCSH,
            "semantic_ring": "subject",
            "resource_profile": "Concept",
            "source_record": "urn:ref:atlas-source-record:" + "7" * 64,
            "definition": "Crimes involving computers.",
            "notes": [],
            "notations": [],
            "record_status": "active",
        },
        {
            "id": "http://id.loc.gov/authorities/subjects/sh_overflow",
            "release": R_LCSH,
            "scheme": S_LCSH,
            "semantic_ring": "subject",
            "resource_profile": "Concept",
            "source_record": "urn:ref:atlas-source-record:" + "8" * 64,
            "definition": "Deer mouse species with 40 English synonyms.",
            "notes": [],
            "notations": [],
            "record_status": "active",
        },
        {
            "id": "https://sns.uba.de/umthes/_00100010",
            "release": R_UMTHES,
            "scheme": S_UMTHES,
            "semantic_ring": "subject",
            "resource_profile": "Concept",
            "source_record": "urn:ref:atlas-source-record:" + "9" * 64,
            "definition": None,
            "notes": [],
            "notations": [],
            "record_status": "active",
        },
        {
            "id": "https://sns.uba.de/umthes/_de_only",
            "release": R_UMTHES,
            "scheme": S_UMTHES,
            "semantic_ring": "subject",
            "resource_profile": "Concept",
            "source_record": "urn:ref:atlas-source-record:" + "a" * 64,
            "definition": None,
            "notes": [],
            "notations": [],
            "record_status": "active",
        },
        {
            "id": "https://id.nlm.nih.gov/mesh/D006278",
            "release": R_MESH,
            "scheme": S_MESH,
            "semantic_ring": "subject",
            "resource_profile": "Concept",
            "source_record": "urn:ref:atlas-source-record:" + "b" * 64,
            "definition": "MeSH Medicare descriptor.",
            "notes": [],
            "notations": [],
            "record_status": "active",
        },
        {
            "id": "https://id.nlm.nih.gov/mesh/D007348",
            "release": R_MESH,
            "scheme": S_MESH,
            "semantic_ring": "subject",
            "resource_profile": "Concept",
            "source_record": "urn:ref:atlas-source-record:" + "c" * 64,
            "definition": "Insurance, Health parent descriptor.",
            "notes": [],
            "notations": [],
            "record_status": "active",
        },
    ]

    labels = [
        {
            "id": "urn:ref:atlas-label:euro-3027-pref",
            "resource": "http://eurovoc.europa.eu/3027",
            "label_role": "preferred",
            "value": "computer crime",
            "language": "en",
            "release": R_EURO,
            "source_record": "urn:ref:atlas-source-record:" + "1" * 64,
        },
        {
            "id": "urn:ref:atlas-label:euro-3027-alt",
            "resource": "http://eurovoc.europa.eu/3027",
            "label_role": "alternate",
            "value": "cybercrime",
            "language": "en",
            "release": R_EURO,
            "source_record": "urn:ref:atlas-source-record:" + "1" * 64,
        },
        {
            "id": "urn:ref:atlas-label:euro-9001-pref",
            "resource": "http://eurovoc.europa.eu/9001",
            "label_role": "preferred",
            "value": "digital evidence",
            "language": "en",
            "release": R_EURO,
            "source_record": "urn:ref:atlas-source-record:" + "2" * 64,
        },
        {
            "id": "urn:ref:atlas-label:fr-medicare-pref",
            "resource": "urn:ref:fr:medicare",
            "label_role": "preferred",
            "value": "Medicare",
            "language": "en",
            "release": R_FR,
            "source_record": "urn:ref:atlas-source-record:" + "3" * 64,
        },
        {
            "id": "urn:ref:atlas-label:fr-flood-pref",
            "resource": "urn:ref:fr:flood-insurance",
            "label_role": "preferred",
            "value": "Flood insurance",
            "language": "en",
            "release": R_FR,
            "source_record": "urn:ref:atlas-source-record:" + "4" * 64,
        },
        {
            "id": "urn:ref:atlas-label:fr-housing-pref",
            "resource": "urn:ref:fr:housing",
            "label_role": "preferred",
            "value": "Housing",
            "language": "en",
            "release": R_FR,
            "source_record": "urn:ref:atlas-source-record:" + "5" * 64,
        },
        {
            "id": "urn:ref:atlas-label:euro-housing-pref",
            "resource": "http://eurovoc.europa.eu/1234",
            "label_role": "preferred",
            "value": "housing",
            "language": "en",
            "release": R_EURO,
            "source_record": "urn:ref:atlas-source-record:" + "6" * 64,
        },
        {
            "id": "urn:ref:atlas-label:lcsh-cc-pref",
            "resource": "http://id.loc.gov/authorities/subjects/sh85029492",
            "label_role": "preferred",
            "value": "Computer crimes",
            "language": "en",
            "release": R_LCSH,
            "source_record": "urn:ref:atlas-source-record:" + "7" * 64,
        },
        {
            "id": "urn:ref:atlas-label:lcsh-ovf-pref",
            "resource": "http://id.loc.gov/authorities/subjects/sh_overflow",
            "label_role": "preferred",
            "value": "Peromyscus maniculatus",
            "language": "en",
            "release": R_LCSH,
            "source_record": "urn:ref:atlas-source-record:" + "8" * 64,
        },
        *[
            {
                "id": f"urn:ref:atlas-label:lcsh-ovf-alt-{i:02d}",
                "resource": "http://id.loc.gov/authorities/subjects/sh_overflow",
                "label_role": "alternate",
                "value": f"Deer mouse variant {i:02d}",
                "language": "en",
                "release": R_LCSH,
                "source_record": "urn:ref:atlas-source-record:" + "8" * 64,
            }
            for i in range(40)
        ],
        {
            "id": "urn:ref:atlas-label:umthes-en",
            "resource": "https://sns.uba.de/umthes/_00100010",
            "label_role": "preferred",
            "value": "air quality",
            "language": "en",
            "release": R_UMTHES,
            "source_record": "urn:ref:atlas-source-record:" + "9" * 64,
        },
        {
            "id": "urn:ref:atlas-label:umthes-de-only",
            "resource": "https://sns.uba.de/umthes/_de_only",
            "label_role": "preferred",
            "value": "Nur Deutsch",
            "language": "de",
            "release": R_UMTHES,
            "source_record": "urn:ref:atlas-source-record:" + "a" * 64,
        },
        {
            "id": "urn:ref:atlas-label:mesh-medicare",
            "resource": "https://id.nlm.nih.gov/mesh/D006278",
            "label_role": "preferred",
            "value": "Medicare",
            "language": "en",
            "release": R_MESH,
            "source_record": "urn:ref:atlas-source-record:" + "b" * 64,
        },
        {
            "id": "urn:ref:atlas-label:mesh-parent",
            "resource": "https://id.nlm.nih.gov/mesh/D007348",
            "label_role": "preferred",
            "value": "Insurance, Health",
            "language": "en",
            "release": R_MESH,
            "source_record": "urn:ref:atlas-source-record:" + "c" * 64,
        },
    ]

    statements = [
        {
            "id": "urn:ref:atlas-assertion:native-1",
            "statement_type": "NativeRelationAssertion",
            "subject": "http://eurovoc.europa.eu/3027",
            "predicate": SKOS + "related",
            "object": "http://eurovoc.europa.eu/9001",
            "source_release": R_EURO,
            "target_release": R_EURO,
            "policy": "urn:ref:atlas-policy:" + "0" * 64,
            "asserted_at": "2026-08-15T00:00:00Z",
            "semantic_ring": "subject",
            "source_ring": "subject",
            "target_ring": "subject",
            "supersedes_assertion": None,
        },
        # Bilingual crasher: target has ONLY German label -> must be excluded from EN pack!
        {
            "id": "urn:ref:atlas-assertion:umthes-de-target",
            "statement_type": "NativeRelationAssertion",
            "subject": "https://sns.uba.de/umthes/_00100010",
            "predicate": SKOS + "related",
            "object": "https://sns.uba.de/umthes/_de_only",
            "source_release": R_UMTHES,
            "target_release": R_UMTHES,
            "policy": "urn:ref:atlas-policy:" + "0" * 64,
            "asserted_at": "2026-08-15T00:00:00Z",
            "semantic_ring": "subject",
            "source_ring": "subject",
            "target_ring": "subject",
            "supersedes_assertion": None,
        },
        # REF-035 default-eligible symmetric MappingAssertion (EuroVoc -> LCSH)
        {
            "id": "urn:ref:atlas-assertion:map-euro-lcsh",
            "statement_type": "MappingAssertion",
            "subject": "http://eurovoc.europa.eu/3027",
            "predicate": SKOS + "exactMatch",
            "object": "http://id.loc.gov/authorities/subjects/sh85029492",
            "source_release": R_EURO,
            "target_release": R_LCSH,
            "policy": "urn:ref:atlas-policy:" + "0" * 64,
            "asserted_at": "2026-08-15T00:00:00Z",
            "semantic_ring": "subject",
            "source_ring": "subject",
            "target_ring": "subject",
            "supersedes_assertion": None,
        },
        # Non-default REF-035 MappingAssertion (textualEvidence -> excluded unless default_mappings_only=False)
        {
            "id": "urn:ref:atlas-assertion:map-nondefault",
            "statement_type": "MappingAssertion",
            "subject": "http://eurovoc.europa.eu/3027",
            "predicate": SKOS + "relatedMatch",
            "object": "urn:ref:fr:medicare",
            "source_release": R_EURO,
            "target_release": R_FR,
            "policy": "urn:ref:atlas-policy:" + "0" * 64,
            "asserted_at": "2026-08-15T00:00:00Z",
            "semantic_ring": "subject",
            "source_ring": "subject",
            "target_ring": "subject",
            "supersedes_assertion": None,
        },
    ]

    evidence = [
        {
            "evidence_id": _hex32(1),
            "statement": "urn:ref:atlas-assertion:map-euro-lcsh",
            "source_record": "urn:ref:atlas-source-record:" + "1" * 64,
            "evidence_source_digest": _hex32(2),
            "attestor": "urn:ref:attestor:eurovoc",
            "evidence_role": OFFICIAL_ROLE,
            "decision": APPROVED,
            "attested_at": "2026-08-15T00:00:00Z",
        },
        {
            "evidence_id": _hex32(3),
            "statement": "urn:ref:atlas-assertion:map-nondefault",
            "source_record": "urn:ref:atlas-source-record:" + "1" * 64,
            "evidence_source_digest": _hex32(4),
            "attestor": "urn:ref:attestor:heuristic",
            "evidence_role": TEXTUAL_ROLE,
            "decision": APPROVED,
            "attested_at": "2026-08-15T00:00:00Z",
        },
    ]

    role_rows: dict[CompactRecordRole, list[dict[str, Any]]] = {
        CompactRecordRole.RELEASE: [],
        CompactRecordRole.RESOURCE: resources,
        CompactRecordRole.LABEL: labels,
        CompactRecordRole.IDENTIFIER: [],
        CompactRecordRole.STATEMENT: statements,
        CompactRecordRole.EVIDENCE_BINDING: evidence,
        CompactRecordRole.LIFECYCLE_EVENT: [],
        CompactRecordRole.SOURCE_RECORD: [],
    }
    rel_paths = {
        CompactRecordRole.RELEASE: "tables/releases.parquet",
        CompactRecordRole.RESOURCE: "tables/resources.parquet",
        CompactRecordRole.LABEL: "tables/labels.parquet",
        CompactRecordRole.IDENTIFIER: "tables/identifiers.parquet",
        CompactRecordRole.STATEMENT: "tables/statements.parquet",
        CompactRecordRole.EVIDENCE_BINDING: "tables/evidence-bindings.parquet",
        CompactRecordRole.LIFECYCLE_EVENT: "tables/lifecycle-events.parquet",
        CompactRecordRole.SOURCE_RECORD: "tables/source-records.parquet",
    }

    members = []
    counts: dict[str, int] = {}
    for role in CompactRecordRole:
        schema = _SCHEMAS[role]
        rows = role_rows[role]
        table = pa.Table.from_pylist(rows, schema=schema) if rows else schema.empty_table()
        out = root / rel_paths[role]
        with pq.ParquetWriter(
            out,
            schema,
            compression="zstd",
            use_dictionary=_DICTIONARIES[role],
            write_statistics=True,
            version="2.6",
            data_page_version="2.0",
        ) as writer:
            writer.write_table(table)
        members.append(
            {
                "byteLength": out.stat().st_size,
                "mediaType": "application/vnd.apache.parquet",
                "path": rel_paths[role],
                "role": role.value,
                "rowCount": len(rows),
                "schemaDigest": arrow_schema_sha256(pq.ParquetFile(out).schema_arrow),
                "sha256": file_sha256(out),
            }
        )
        counts[role.value] = len(rows)

    if include_derived:
        derived_rows = [
            {
                "id": "urn:ref:derived:mesh-broader-1",
                "subject": "https://id.nlm.nih.gov/mesh/D006278",
                "predicate": SKOS + "broader",
                "object": "https://id.nlm.nih.gov/mesh/D007348",
                "semantic_ring": "subject",
                "derivation_rule": "urn:ref:rule:mesh-tree-number-broader",
                "engine": "refspec",
                "engine_version": "0.1",
                "derived_from_assertions": [],
                "input_digest": _hex32(9),
                "generated_at": "2026-08-15T00:00:00Z",
                "content_digest": _hex32(10),
            }
        ]
        drv_path = root / "tables/derived-relations.parquet"
        with pq.ParquetWriter(
            drv_path,
            DERIVED_RELATION_TABLE_SCHEMA,
            compression="zstd",
            write_statistics=True,
            version="2.6",
            data_page_version="2.0",
        ) as writer:
            writer.write_table(pa.Table.from_pylist(derived_rows, schema=DERIVED_RELATION_TABLE_SCHEMA))
        members.append(
            {
                "byteLength": drv_path.stat().st_size,
                "mediaType": "application/vnd.apache.parquet",
                "path": "tables/derived-relations.parquet",
                "role": DERIVED_RELATION_ROLE,
                "rowCount": len(derived_rows),
                "schemaDigest": arrow_schema_sha256(pq.ParquetFile(drv_path).schema_arrow),
                "sha256": file_sha256(drv_path),
            }
        )
        counts[DERIVED_RELATION_ROLE] = len(derived_rows)

    manifest: dict[str, Any] = {
        "construction": {"implementation": "test", "version": "1.0"},
        "counts": counts,
        "input": {"manifestDigest": "sha256:" + "0" * 64},
        "members": members,
        "recordType": SEARCH_VIEW_RECORD_TYPE,
        "schemaVersion": SEARCH_VIEW_SCHEMA_VERSION,
        "status": {
            "canonicalAtlas": False,
            "consumerViewOnly": True,
            "expansion": "not_used",
            "graphFactsPreserved": True,
            "logicalRecordsPreserved": False,
            "omittedFields": list(_OMITTED_FIELDS),
        },
        "viewId": SEARCH_VIEW_ID_PREFIX + "f" * 64,
    }
    manifest["canonicalPayloadDigest"] = canonical_payload_sha256(manifest)
    mpath = root / MANIFEST_FILE
    mpath.write_bytes(canonical_json_bytes(manifest))
    return root, file_sha256(mpath)


def test_scoped_view_verification_skips_unselected_members_and_refuses_unknown_roles(tmp_path: Path) -> None:
    view_root, digest = _write_compact_fixture(tmp_path / "view")
    # Corrupting an UNSELECTED member (SourceRecord) passes scoped-3 verification,
    # while full verification refuses it.
    src_file = view_root / "tables/source-records.parquet"
    original = src_file.read_bytes()
    src_file.write_bytes(b"corrupted-unread-bytes")

    manifest = verify_atlas_parquet_search_view(
        view_root,
        expected_manifest_digest=digest,
        roles=("Resource", "Label", "Statement"),
    )
    assert manifest["viewId"] == SEARCH_VIEW_ID_PREFIX + "f" * 64

    with pytest.raises(AtlasParquetSearchViewError, match="member bytes differ"):
        verify_atlas_parquet_search_view(view_root, expected_manifest_digest=digest)

    src_file.write_bytes(original)
    with pytest.raises(AtlasParquetSearchViewError, match="unsupported roles"):
        verify_atlas_parquet_search_view(view_root, expected_manifest_digest=digest, roles=("BogusRole",))


def test_build_open_lookup_typo_abstention_grouping_and_label_truncation(tmp_path: Path) -> None:
    view_root, digest = _write_compact_fixture(tmp_path / "view")
    pack_path = tmp_path / "vocab.sqlite"
    manifest = build_vocabulary_pack(
        view_root,
        pack_path,
        trusted_manifest_digest=digest,
        schemes=(S_EURO, S_FR, S_LCSH, S_UMTHES, S_MESH),
        languages=("en",),
        include_mappings=True,
        include_derived=True,
    )
    assert isinstance(manifest, VocabularyPackManifest)
    assert manifest.schema_version == PACK_SCHEMA_VERSION == "3"
    assert manifest.resource_count == 11          # German-only umthes resource (label_count=0 in EN) skipped!
    assert manifest.labeled_resource_count == 11
    assert manifest.native_edge_count == 1       # umthes->de_only excluded cleanly!
    assert manifest.mapping_edge_count == 2
    assert manifest.derived_edge_count == 1

    with AtlasVocabularyPack.open(
        pack_path,
        trusted_pack_digest=manifest.pack_sha256,
        trusted_manifest_digest=digest,
    ) as pack:
        assert isinstance(pack, VocabularyProvider)
        assert pack.requires_sql_executor is False

        # Exact preferred & alternate lookup preserving canonical Label.id (REF-025)
        hits = pack.lookup_sync("cybercrime", limit=5)
        assert hits[0]["id"] == "http://eurovoc.europa.eu/3027"
        assert hits[0]["label"] == "computer crime"
        assert [lbl["id"] for lbl in hits[0]["labels"]] == [
            "urn:ref:atlas-label:euro-3027-pref",
            "urn:ref:atlas-label:euro-3027-alt",
        ]

        # Zero-ML Damerau-Levenshtein spelling recovery (transposition + substitution)
        typo1 = pack.lookup_sync("medciare", limit=5)
        assert any(c["label"] == "Medicare" for c in typo1)
        typo2 = pack.lookup_sync("flood insurence", limit=5)
        assert typo2[0]["id"] == "urn:ref:fr:flood-insurance"

        # Strict abstention on nonsense query (0 false hits!)
        assert pack.lookup_sync("zxqvblargle nonexistent topic 999", limit=10) == []

        # Deterministic 32-label truncation instead of crashing (Peromyscus maniculatus has 41 labels!)
        ovf = pack.lookup_sync("Peromyscus maniculatus", limit=5)
        assert len(ovf) == 1
        assert len(ovf[0]["labels"]) == 32
        assert ovf[0]["labels"][0]["role"] == "preferred"
        assert ovf[0]["labelsTruncated"] is True
        assert ovf[0]["totalLabelCount"] == 41

        # Identical-label grouping collapses EuroVoc + FR-2025 "Housing" while preserving counterparts!
        grouped = pack.lookup_sync("housing", limit=5, group_identical_labels=True)
        assert len(grouped) == 1
        assert len(grouped[0]["counterparts"]) == 1
        schemes_seen = {grouped[0]["scheme"], grouped[0]["counterparts"][0]["scheme"]}
        assert schemes_seen == {S_EURO, S_FR}

        # Async SpicyEngine protocol compatibility works with run=None!
        async_hits = asyncio.run(pack.lookup(None, "computer crime", 5))
        assert async_hits[0]["id"] == "http://eurovoc.europa.eu/3027"


def test_related_fixes_umthes_crash_and_serves_ref035_mappings_and_derived_edges(tmp_path: Path) -> None:
    view_root, digest = _write_compact_fixture(tmp_path / "view")
    pack_path = tmp_path / "vocab.sqlite"
    manifest = build_vocabulary_pack(
        view_root,
        pack_path,
        trusted_manifest_digest=digest,
        schemes=(S_EURO, S_FR, S_LCSH, S_UMTHES, S_MESH),
        languages=("en",),
        include_mappings=True,
        include_derived=True,
    )

    euro_ref = {"id": "http://eurovoc.europa.eu/3027", "scheme": S_EURO, "release": R_EURO}
    lcsh_ref = {"id": "http://id.loc.gov/authorities/subjects/sh85029492", "scheme": S_LCSH, "release": R_LCSH}
    umthes_ref = {"id": "https://sns.uba.de/umthes/_00100010", "scheme": S_UMTHES, "release": R_UMTHES}
    mesh_ref = {"id": "https://id.nlm.nih.gov/mesh/D006278", "scheme": S_MESH, "release": R_MESH}

    with AtlasVocabularyPack.open(pack_path, trusted_pack_digest=manifest.pack_sha256) as pack:
        # 1. Bilingual umthes seed no longer crashes (German-only neighbor cleanly excluded)
        assert pack.related_sync(umthes_ref, limit=20) == []

        # 2. Default related() returns native forward SKOS edges only
        native_only = pack.related_sync(euro_ref, limit=20)
        assert len(native_only) == 1
        assert native_only[0]["concept"]["id"] == "http://eurovoc.europa.eu/9001"
        assert native_only[0]["relation"]["type"] == SKOS + "related"

        # 3. Opt-in REF-035 default mappings (includes officialSourceMetadata, excludes textualEvidence!)
        with_def_maps = pack.related_sync(euro_ref, limit=20, include_mappings=True, default_mappings_only=True)
        assert [r["concept"]["id"] for r in with_def_maps] == [
            "http://eurovoc.europa.eu/9001",
            "http://id.loc.gov/authorities/subjects/sh85029492",
        ]
        assert with_def_maps[1]["relation"]["direction"] == "forward"
        assert with_def_maps[1]["relation"]["evidenceDefaultEligible"] is True

        # 4. Non-default mappings visible only when default_mappings_only=False
        with_all_maps = pack.related_sync(euro_ref, limit=20, include_mappings=True, default_mappings_only=False)
        assert len(with_all_maps) == 3
        assert with_all_maps[2]["relation"]["evidenceDefaultEligible"] is False

        # 5. REF-035 symmetric inverse traversal from LCSH -> EuroVoc WITHOUT fabricating a reverse assertion!
        inv_maps = pack.related_sync(lcsh_ref, limit=20, include_mappings=True, include_symmetric_inverse=True)
        assert len(inv_maps) == 1
        assert inv_maps[0]["concept"]["id"] == "http://eurovoc.europa.eu/3027"
        rel = inv_maps[0]["relation"]
        assert rel["id"] == "urn:ref:atlas-assertion:map-euro-lcsh"
        assert rel["direction"] == "inverse"
        assert rel["assertedSource"] == euro_ref
        assert rel["assertedTarget"] == lcsh_ref

        # 6. Opt-in derived relations unlock MeSH hierarchy with derivationRule + asserted=False!
        assert pack.related_sync(mesh_ref, limit=20) == []
        mesh_derived = pack.related_sync(mesh_ref, limit=20, include_derived=True)
        assert len(mesh_derived) == 1
        assert mesh_derived[0]["concept"]["id"] == "https://id.nlm.nih.gov/mesh/D007348"
        assert mesh_derived[0]["relation"]["asserted"] is False
        assert mesh_derived[0]["relation"]["derivationRule"] == "urn:ref:rule:mesh-tree-number-broader"

        # 7. GraphExpander DI protocol: bounded cycle-safe k-hop closure (native + mappings + derived)
        assert isinstance(pack, GraphExpander)
        closure = pack.expand_sync(euro_ref, max_depth=2, max_nodes=10, include_mappings=True)
        assert {item["concept"]["id"] for item in closure} == {
            "http://eurovoc.europa.eu/9001",
            "http://id.loc.gov/authorities/subjects/sh85029492",
        }
        assert all(item["depth"] == 1 for item in closure)
        mesh_closure = pack.expand_sync(
            mesh_ref, predicates=(SKOS + "broader",), max_depth=2, include_derived=True
        )
        assert [item["concept"]["id"] for item in mesh_closure] == ["https://id.nlm.nih.gov/mesh/D007348"]


def test_di_injection_protocols_encoder_fallback_mismatch_and_error_classes(tmp_path: Path) -> None:
    view_root, digest = _write_compact_fixture(tmp_path / "view")
    pack_path = tmp_path / "vocab.sqlite"
    manifest = build_vocabulary_pack(
        view_root,
        pack_path,
        trusted_manifest_digest=digest,
        schemes=(S_EURO, S_FR),
        languages=("en",),
    )

    class FakeSemanticIndex:
        def __init__(
            self,
            target_rid: int,
            *,
            pack_sha: str,
            manifest_sha: str,
            pack_id: str = "",
            model: str = "fake-m3",
            dim: int = 4,
            vectors_by_rid: dict[int, list[float]] | None = None,
        ):
            self._rid = target_rid
            self.pack_sha256 = pack_sha
            self.pack_id = pack_id
            self.source_manifest_digest = manifest_sha
            self.model_id = model
            self.dimensions = dim
            self.recommended_min_cosine: float | None = None
            self._vectors_by_rid = vectors_by_rid or {target_rid: [1.0] + [0.0] * (dim - 1)}

        def search_rids(
            self,
            query_vector: Sequence[float],
            *,
            top_k: int = 40,
            min_cosine: float = 0.55,
            nprobe: int = 24,
        ) -> list[tuple[int, float]]:
            _ = (query_vector, top_k, nprobe)
            return [(self._rid, 0.91)] if 0.91 >= min_cosine else []

        def vector_for_rid(self, rid: int) -> Sequence[float] | None:
            return self._vectors_by_rid.get(rid)

    class FakeEncoder:
        def __init__(self, *, model: str = "fake-m3", dim: int = 4, fail: bool = False):
            self.model_id = model
            self.dimensions = dim
            self._fail = fail

        def encode_query(self, text: str) -> Sequence[float]:
            if self._fail:
                raise ConnectionError("embedder offline")
            return [1.0] + [0.0] * (self.dimensions - 1)

    class DenseFirstFusion:
        def fuse(
            self,
            *,
            exact_rids: Sequence[int],
            lexical_rids: Sequence[int],
            dense_hits: Sequence[tuple[int, float]],
            limit: int,
        ) -> list[int]:
            ordered = [rid for rid, _ in dense_hits] + list(exact_rids) + list(lexical_rids)
            return list(dict.fromkeys(ordered))[:limit]

    # Look up rid for Medicare in the pack to wire our fake semantic index cleanly.
    con = sqlite3.connect(str(pack_path))
    medicare_rid = con.execute("SELECT rid FROM resources WHERE id = 'urn:ref:fr:medicare'").fetchone()[0]
    con.close()

    good_idx = FakeSemanticIndex(
        medicare_rid, pack_sha=manifest.pack_sha256, manifest_sha=digest, pack_id=manifest.pack_id
    )
    assert isinstance(good_idx, SemanticIndex)
    assert isinstance(FakeEncoder(), QueryEncoder)
    assert isinstance(ExactPinnedRRF(), RankFusionPolicy)
    assert isinstance(DenseFirstFusion(), RankFusionPolicy)

    with AtlasVocabularyPack.open(pack_path, trusted_pack_digest=manifest.pack_sha256) as base_pack:
        # 1. Model / dimension mismatch rejected loudly at DI wiring time (VocabularyPackError -> HTTP 503!)
        with pytest.raises(VocabularyPackError, match="dimensions"):
            base_pack.with_dependencies(semantic_index=good_idx, query_encoder=FakeEncoder(dim=8))
        with pytest.raises(VocabularyPackError, match="model"):
            base_pack.with_dependencies(semantic_index=good_idx, query_encoder=FakeEncoder(model="other-model"))

        # 2. Successful DI wiring recovers Spanish query via FakeEncoder + FakeSemanticIndex!
        hybrid_pack = base_pack.with_dependencies(
            semantic_index=good_idx,
            query_encoder=FakeEncoder(),
            relation_policy=RelationPolicy(include_mappings=True),
        )
        assert hybrid_pack.can_encode_queries is True
        es_hits = hybrid_pack.lookup_sync("seguro medico para mayores", limit=5)
        assert es_hits[0]["id"] == "urn:ref:fr:medicare"

        # 3. ExactPinnedRRF keeps exact match #1 even when dense returned Medicare!
        exact_hits = hybrid_pack.lookup_sync("computer crime", limit=5)
        assert exact_hits[0]["id"] == "http://eurovoc.europa.eu/3027"

        # 4. Swapping RankFusionPolicy via DI changes ranking cleanly without mutating base_pack!
        dense_first = hybrid_pack.with_dependencies(rank_fusion=DenseFirstFusion())
        assert dense_first.lookup_sync("computer crime", limit=5)[0]["id"] == "urn:ref:fr:medicare"

        # 5. Encoder failure falls back gracefully by default, OR raises VocabularyPackError when fail-closed!
        resilient = base_pack.with_dependencies(
            semantic_index=good_idx,
            query_encoder=FakeEncoder(fail=True),
            lookup_policy=LookupPolicy(fallback_on_encoder_error=True),
        )
        assert resilient.lookup_sync("computer crime", limit=5)[0]["id"] == "http://eurovoc.europa.eu/3027"

        strict_enc = base_pack.with_dependencies(
            semantic_index=good_idx,
            query_encoder=FakeEncoder(fail=True),
            lookup_policy=LookupPolicy(fallback_on_encoder_error=False),
        )
        with pytest.raises(VocabularyPackError, match="encoder failed"):
            strict_enc.lookup_sync("computer crime", limit=5)

        # 6. Closing a derived DI view must NOT close base_pack's connection!
        hybrid_pack.close()
        assert base_pack.resolve_sync(
            {"id": "urn:ref:fr:medicare", "scheme": S_FR, "release": R_FR}
        )["label"] == "Medicare"

        # 7. Error class separation: client faults -> ValueError (400), pack faults -> RuntimeError (503)
        with pytest.raises(VocabularyInputError) as exc_in:
            base_pack.lookup_sync("   ", limit=5)
        assert isinstance(exc_in.value, ValueError)
        with pytest.raises(VocabularyInputError):
            base_pack.resolve_sync({"id": "missing", "scheme": S_FR, "release": R_FR})

    # Tampered digest & symlink path refused with VocabularyPackError (RuntimeError -> HTTP 503)
    with pytest.raises(VocabularyPackError) as exc_pk:
        AtlasVocabularyPack.open(pack_path, trusted_pack_digest="sha256:" + "0" * 64)
    assert isinstance(exc_pk.value, RuntimeError)

    link_path = tmp_path / "link.sqlite"
    link_path.symlink_to(pack_path)
    with pytest.raises(VocabularyPackError, match="symlink"):
        AtlasVocabularyPack.open(link_path)


def test_cli_build_verify_and_query_roundtrip(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    view_root, digest = _write_compact_fixture(tmp_path / "view")
    pack_path = tmp_path / "cli_vocab.sqlite"
    rc = cli_main(
        [
            "build",
            "--view-root",
            str(view_root),
            "--manifest-digest",
            digest,
            "--output",
            str(pack_path),
            "--scheme",
            S_EURO,
            "--scheme",
            S_FR,
        ]
    )
    assert rc == 0
    built = json.loads(capsys.readouterr().out)
    assert built["counts"]["labeledResources"] == 6

    rc2 = cli_main(["verify", "--pack", str(pack_path), "--pack-digest", built["packSha256"]])
    assert rc2 == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified["sourceManifestDigest"] == digest

    rc3 = cli_main(["query", "--pack", str(pack_path), "--text", "medciare", "--limit", "3", "--context"])
    assert rc3 == 0
    queried = json.loads(capsys.readouterr().out)
    assert queried["correctedQuery"] == "medicare"
    assert queried["tier"] == "spelling_corrected"
    assert queried["concepts"][0]["id"] == "urn:ref:fr:medicare"

    rc4 = cli_main(["extract", "--pack", str(pack_path), "--text", "Medicare and Flood insurance address cybercrime."])
    assert rc4 == 0
    extracted = json.loads(capsys.readouterr().out)
    assert [m["concept"]["id"] for m in extracted] == [
        "urn:ref:fr:medicare",
        "urn:ref:fr:flood-insurance",
        "http://eurovoc.europa.eu/3027",
    ]


def test_waves1_and_2_context_fast_open_authority_rerank_offline_similar_and_extract(tmp_path: Path) -> None:
    view_root, digest = _write_compact_fixture(tmp_path / "view")
    pack_path = tmp_path / "vocab_w12.sqlite"
    manifest = build_vocabulary_pack(
        view_root,
        pack_path,
        trusted_manifest_digest=digest,
        schemes=(S_EURO, S_FR, S_LCSH, S_MESH),
        languages=("en",),
        include_mappings=True,
        include_derived=True,
    )
    assert manifest.pack_id.startswith("urn:ref:vocabulary-pack:")

    # Verify lossless URI prefix compression actually compressed stored labels in SQLite!
    con = sqlite3.connect(str(pack_path))
    row_euro = con.execute("SELECT rid FROM resources WHERE id = 'http://eurovoc.europa.eu/3027'").fetchone()
    row_med = con.execute("SELECT rid FROM resources WHERE id = 'urn:ref:fr:medicare'").fetchone()
    row_mesh = con.execute("SELECT rid FROM resources WHERE id = 'https://id.nlm.nih.gov/mesh/D006278'").fetchone()
    lbl_pfx_count = con.execute("SELECT count(*) FROM labels WHERE lbl_pfx > 0").fetchone()[0]
    con.close()
    assert row_euro and row_med and row_mesh
    assert lbl_pfx_count > 0
    euro_rid, med_rid, mesh_rid = int(row_euro[0]), int(row_med[0]), int(row_mesh[0])

    class OfflineSidecar:
        pack_sha256 = "sha256:" + "0" * 64  # deliberately wrong SHA to prove verify_pack_digest=False checks pack_id!
        pack_id = manifest.pack_id
        source_manifest_digest = digest
        model_id = "BAAI/bge-m3"
        dimensions = 4

        def vector_for_rid(self, rid: int) -> Sequence[float] | None:
            return [1.0, 0.0, 0.0, 0.0] if rid == med_rid else None

        def search_rids(
            self,
            query_vector: Sequence[float],
            *,
            top_k: int = 40,
            min_cosine: float = 0.55,
            nprobe: int = 24,
        ) -> list[tuple[int, float]]:
            _ = (query_vector, top_k, min_cosine, nprobe)
            return [(med_rid, 1.0), (mesh_rid, 0.94), (euro_rid, 0.72)]

    # Fast-open (verify_pack_digest=False) checks pack_id in <1ms without hashing pack file,
    # while verify_pack_digest=True refuses mismatched pack_sha256!
    with pytest.raises(VocabularyPackError, match="pack digest does not match"):
        AtlasVocabularyPack.open(pack_path, semantic_index=OfflineSidecar(), verify_pack_digest=True)

    bad_id_sidecar = OfflineSidecar()
    bad_id_sidecar.pack_id = "urn:ref:vocabulary-pack:wrong"
    with pytest.raises(VocabularyPackError, match="pack identity does not match"):
        AtlasVocabularyPack.open(pack_path, semantic_index=bad_id_sidecar, verify_pack_digest=False)

    with AtlasVocabularyPack.open(
        pack_path,
        semantic_index=OfflineSidecar(),
        verify_pack_digest=False,
        candidate_reranker=AuthorityReranker(),
        lookup_policy=LookupPolicy(include_context=True),
    ) as pack:
        assert isinstance(AuthorityReranker(), CandidateReranker)

        # 1. Disambiguation breadcrumbs (notations + derived broaderLabels + matchReason + correctedQuery)
        euro_res = pack.resolve_sync(
            {"id": "http://eurovoc.europa.eu/3027", "scheme": S_EURO, "release": R_EURO},
            include_context=True,
        )
        assert euro_res["notations"] == ["3027"]

        mesh_res = pack.resolve_sync(
            {"id": "https://id.nlm.nih.gov/mesh/D006278", "scheme": S_MESH, "release": R_MESH},
            include_context=True,
        )
        assert mesh_res["broaderLabels"] == ["Insurance, Health"]

        meta_typo = pack.lookup_with_meta_sync("medciare", limit=5)
        assert meta_typo["correctedQuery"] == "medicare"
        assert meta_typo["tier"] == "spelling_corrected"
        assert meta_typo["concepts"][0]["matchReason"] == "spelling_corrected"
        assert meta_typo["concepts"][0]["correctedQuery"] == "medicare"

        # 2. AuthorityReranker promotes concise curated concepts over deep "--" subdivisions & long CFR titles!
        reranked = AuthorityReranker().rerank(
            query="veterans health",
            candidates=[
                {
                    "id": "fast:sub",
                    "scheme": "urn:ref:atlas-resource-scheme:fast-topical",
                    "release": "r1",
                    "label": "Veterans--Medical care--Accounting",
                    "definition": None,
                    "sourceRecord": "s1",
                },
                {
                    "id": "cfr:long",
                    "scheme": "urn:ref:atlas-resource-scheme:cfr-subject-index",
                    "release": "r1",
                    "label": "Health information technology standards, implementation specifications, and certification criteria guidance",
                    "definition": None,
                    "sourceRecord": "s2",
                },
                {
                    "id": "fr:concise",
                    "scheme": S_FR,
                    "release": R_FR,
                    "label": "Veterans health care",
                    "definition": None,
                    "sourceRecord": "s3",
                },
            ],
            limit=3,
        )
        assert reranked[0]["id"] == "fr:concise"
        assert reranked[-1]["id"] == "fast:sub"

        # 3. Offline concept-to-concept similarity (zero query encoder!) excludes self & supports exclude_same_scheme
        sim = pack.similar_sync(
            {"id": "urn:ref:fr:medicare", "scheme": S_FR, "release": R_FR},
            limit=5,
            exclude_same_scheme=True,
            include_context=True,
        )
        assert [s["concept"]["id"] for s in sim] == [
            "https://id.nlm.nih.gov/mesh/D006278",
            "http://eurovoc.europa.eu/3027",
        ]
        assert sim[0]["asserted"] is False
        assert sim[0]["semanticSimilarity"] == pytest.approx(0.94, abs=1e-4)
        assert sim[0]["concept"]["broaderLabels"] == ["Insurance, Health"]

        # 4. Zero-ML verbatim concept extraction returns exact character spans + canonical Label.id!
        sentence = "New rules update Medicare and Flood insurance to counter cybercrime."
        mentions = pack.extract_concepts_sync(sentence, limit=10)
        assert [(m["matchedText"], m["concept"]["id"]) for m in mentions] == [
            ("Medicare", "urn:ref:fr:medicare"),
            ("Flood insurance", "urn:ref:fr:flood-insurance"),
            ("cybercrime", "http://eurovoc.europa.eu/3027"),
        ]
        for m in mentions:
            s0, s1 = m["span"]
            assert sentence[s0:s1] == m["matchedText"]
            assert m["matchedLabelId"].startswith("urn:ref:atlas-label:")


def test_review_regressions_min_cosine_scheme_sql_extract_edge_cases_reranker_and_unknown_rids(tmp_path: Path) -> None:
    """Regression suite covering independent review Findings 1, 4, 5, 6, 7, 9, and 15."""
    view_root, digest = _write_compact_fixture(tmp_path / "view")
    pack_path = tmp_path / "vocab_reg.sqlite"
    manifest = build_vocabulary_pack(
        view_root,
        pack_path,
        trusted_manifest_digest=digest,
        schemes=(S_EURO, S_FR, S_LCSH, S_MESH),
        languages=("en",),
        include_mappings=True,
        include_derived=True,
    )

    # Inject a few targeted rows into a writable copy to exercise Unicode, parenthetical labels,
    # repeated phrases, >32 labels, and scheme-filtered SQL LIMIT without duplicating the whole fixture.
    reg_pack = tmp_path / "vocab_reg_custom.sqlite"
    reg_pack.write_bytes(pack_path.read_bytes())
    con = sqlite3.connect(str(reg_pack))
    euro_sid = con.execute("SELECT sid FROM schemes WHERE uri = ?", (S_EURO,)).fetchone()[0]
    fr_sid = con.execute("SELECT sid FROM schemes WHERE uri = ?", (S_FR,)).fetchone()[0]
    euro_rel = con.execute("SELECT rel_id FROM releases WHERE uri = ?", (R_EURO,)).fetchone()[0]
    fr_rel = con.execute("SELECT rel_id FROM releases WHERE uri = ?", (R_FR,)).fetchone()[0]
    max_rid = con.execute("SELECT max(rid) FROM resources").fetchone()[0]

    # Add Unicode ("café"), parenthetical ("Mercury (Element)"), and sub-word ("computer") concepts
    next_rid = max_rid + 1
    for rid, res_id, sid, rel_id, pref, lbl_id in [
        (next_rid, "http://eurovoc.europa.eu/cafe", euro_sid, euro_rel, "café", "urn:ref:atlas-label:cafe-pref"),
        (next_rid + 1, "http://eurovoc.europa.eu/mercury", euro_sid, euro_rel, "Mercury (Element)", "urn:ref:atlas-label:merc-pref"),
        (next_rid + 2, "http://eurovoc.europa.eu/comp", euro_sid, euro_rel, "computer", "urn:ref:atlas-label:comp-pref"),
        (next_rid + 3, "http://eurovoc.europa.eu/crime", euro_sid, euro_rel, "crime", "urn:ref:atlas-label:crime-pref"),
    ]:
        pref_norm = normalize_text(pref)
        con.execute(
            "INSERT INTO resources(rid, id, sid, rel_id, definition, src_pfx, src_suffix, notations_json, pref_label, label_count, has_preferred) "
            "VALUES (?, ?, ?, ?, NULL, 0, 'src', NULL, ?, 1, 1)",
            (rid, res_id, sid, rel_id, pref),
        )
        con.execute(
            "INSERT INTO labels(rid, role_rank, value_lower, value, lbl_pfx, lbl_suffix, role, language) "
            "VALUES (?, 0, ?, ?, 0, ?, 'preferred', 'en')",
            (rid, pref_norm, pref, lbl_id),
        )
        con.execute("INSERT INTO label_exact(value_lower, role_rank, rid) VALUES (?, 0, ?)", (pref_norm, rid))

    # Add 5 early-rid EuroVoc concepts all matching "sharedterm", plus 1 later-rid FR concept matching "sharedterm"
    # so limit=1 with schemes=[S_FR] would fail if SQL LIMIT ran before scheme filtering (Finding 4)!
    for k in range(5):
        r_e = next_rid + 10 + k
        con.execute(
            "INSERT INTO resources(rid, id, sid, rel_id, definition, src_pfx, src_suffix, notations_json, pref_label, label_count, has_preferred) "
            "VALUES (?, ?, ?, ?, NULL, 0, 'src', NULL, 'Sharedterm', 1, 1)",
            (r_e, f"http://eurovoc.europa.eu/st-{k}", euro_sid, euro_rel),
        )
        con.execute(
            "INSERT INTO labels(rid, role_rank, value_lower, value, lbl_pfx, lbl_suffix, role, language) "
            "VALUES (?, 0, 'sharedterm', 'Sharedterm', 0, ?, 'preferred', 'en')",
            (r_e, f"urn:ref:atlas-label:st-e-{k}"),
        )
        con.execute("INSERT INTO label_exact(value_lower, role_rank, rid) VALUES ('sharedterm', 0, ?)", (r_e,))
    fr_st_rid = next_rid + 20
    con.execute(
        "INSERT INTO resources(rid, id, sid, rel_id, definition, src_pfx, src_suffix, notations_json, pref_label, label_count, has_preferred) "
        "VALUES (?, 'urn:ref:fr:sharedterm', ?, ?, NULL, 0, 'src', NULL, 'Sharedterm', 1, 1)",
        (fr_st_rid, fr_sid, fr_rel),
    )
    con.execute(
        "INSERT INTO labels(rid, role_rank, value_lower, value, lbl_pfx, lbl_suffix, role, language) "
        "VALUES (?, 0, 'sharedterm', 'Sharedterm', 0, 'urn:ref:atlas-label:st-fr', 'preferred', 'en')",
        (fr_st_rid,),
    )
    con.execute("INSERT INTO label_exact(value_lower, role_rank, rid) VALUES ('sharedterm', 0, ?)", (fr_st_rid,))

    # Also grab Peromyscus maniculatus rid (41 labels; >32 truncation) and Medicare rid
    pero_rid = con.execute("SELECT rid FROM resources WHERE pref_label = 'Peromyscus maniculatus'").fetchone()[0]
    med_rid = con.execute("SELECT rid FROM resources WHERE id = 'urn:ref:fr:medicare'").fetchone()[0]
    _refresh_pack_blobs(con)
    con.commit()
    con.close()

    class LowCosineAndGhostRidIndex:
        pack_sha256 = "sha256:" + "0" * 64
        pack_id = manifest.pack_id
        source_manifest_digest = digest
        model_id = "low-cos-model"
        dimensions = 4

        def vector_for_rid(self, rid: int) -> Sequence[float] | None:
            return [1.0, 0.0, 0.0, 0.0] if rid == med_rid else None

        def search_rids(
            self,
            query_vector: Sequence[float],
            *,
            top_k: int = 40,
            min_cosine: float = 0.55,
            nprobe: int = 24,
        ) -> list[tuple[int, float]]:
            _ = (query_vector, top_k, nprobe)
            # Return a valid rid at cosine 0.35 (below 0.55!) plus a ghost rid 999999 absent from resources!
            hits = [(999999, 0.99), (med_rid, 0.35)]
            return [(r, s) for r, s in hits if s >= min_cosine]

    class DummyEncoder:
        model_id = "low-cos-model"
        dimensions = 4

        def encode_query(self, text: str) -> Sequence[float]:
            _ = text
            return [1.0, 0.0, 0.0, 0.0]

    with AtlasVocabularyPack.open(
        reg_pack,
        semantic_index=LowCosineAndGhostRidIndex(),
        query_encoder=DummyEncoder(),
        candidate_reranker=AuthorityReranker(),
        verify_pack_digest=False,
        lookup_policy=LookupPolicy(include_context=False),
    ) as pack:
        # Finding 1 + Finding 7: per-call min_cosine=0.30 is NOT dropped by ExactPinnedRRF, AND ghost rid 999999
        # with candidate_reranker + include_context=False does NOT crash zip(..., strict=True)!
        low_hits = pack.lookup_sync("unrelated semantic phrase", limit=5, min_cosine=0.30)
        assert [c["id"] for c in low_hits] == ["urn:ref:fr:medicare"]

        # Finding 7 in similar_sync: ghost rid 999999 is silently skipped without ValueError!
        sim_hits = pack.similar_sync(
            {"id": "urn:ref:fr:medicare", "scheme": S_FR, "release": R_FR},
            limit=5,
            min_cosine=0.30,
        )
        assert sim_hits == []

        # Finding 4: SQL scheme filter runs BEFORE LIMIT so S_FR hit is found even with limit=1 behind 5 EuroVoc hits!
        fr_only = pack.lookup_sync("sharedterm", limit=1, schemes=[S_FR])
        assert [c["id"] for c in fr_only] == ["urn:ref:fr:sharedterm"]

        # Finding 5 + punctuation-crossing rejection: Unicode ("café"), repeated phrase dedup (no spurious
        # "computer"/"crime" sub-spans!), >32-label concept exact matchedLabelId (alt 39 -> lcsh-ovf-alt-39),
        # AND parenthetical punctuation-crossing spans ("Mercury (Element)") are rejected!
        txt = (
            "At the café, Mercury (Element) met computer crime; later computer crime recurred near "
            "Deer mouse variant 39."
        )
        extracted = pack.extract_concepts_sync(txt, limit=10, deduplicate=True)
        matched_texts = [m["matchedText"] for m in extracted]
        assert matched_texts == ["café", "computer crime", "Deer mouse variant 39"]
        # Verify exact matchedLabelId for variant #39 (well past the 32-label truncation cap!)
        pero_hit = extracted[-1]
        assert pero_hit["concept"]["id"] == "http://id.loc.gov/authorities/subjects/sh_overflow"
        assert pero_hit["matchedLabelId"] == "urn:ref:atlas-label:lcsh-ovf-alt-39"
        assert pero_hit["matchRole"] == "alternate"
        assert pero_rid > 0

        # Finding 15: expand_sync traverses symmetric inverse mappings (LCSH -> EuroVoc) when include_mappings=True!
        lcsh_ref = {"id": "http://id.loc.gov/authorities/subjects/sh85029492", "scheme": S_LCSH, "release": R_LCSH}
        inv_exp = pack.expand_sync(lcsh_ref, max_depth=1, include_mappings=True, include_symmetric_inverse=True)
        assert [item["concept"]["id"] for item in inv_exp] == ["http://eurovoc.europa.eu/3027"]

    # Finding 6: empty pack_id cannot bypass BOTH pack_id and pack_sha256 checks!
    empty_id_pack = tmp_path / "empty_id.sqlite"
    empty_id_pack.write_bytes(pack_path.read_bytes())
    con2 = sqlite3.connect(str(empty_id_pack))
    con2.execute("UPDATE pack_meta SET value = '' WHERE key = 'pack_id'")
    con2.commit()
    con2.close()
    with pytest.raises(VocabularyPackError, match="incomplete"):
        AtlasVocabularyPack.open(empty_id_pack, semantic_index=LowCosineAndGhostRidIndex(), verify_pack_digest=False)

    # Finding 9: AuthorityReranker never mutates caller-owned counterparts list and handles empty query + minimal dicts!
    orig_cp = [{"id": "old", "scheme": S_FR, "release": R_FR, "label": "Alpha"}]
    cand_a = {"id": "a", "scheme": S_FR, "release": R_FR, "label": "Alpha", "counterparts": orig_cp}
    cand_b = {"id": "b", "scheme": S_EURO, "release": R_EURO, "label": "Alpha"}
    reranked = AuthorityReranker().rerank(query="", candidates=[cand_a, cand_b], limit=5)
    assert len(orig_cp) == 1
    assert len(reranked[0]["counterparts"]) == 2


def test_exact_token_bm25_before_prefix_fallback_and_typeahead(tmp_path: Path) -> None:
    """Exact-token AND BM25 must rank exact token hits ahead of wildcard prefix hits while keeping typeahead."""
    view_root, digest = _write_compact_fixture(tmp_path / "view")
    base_pack = tmp_path / "vocab_base.sqlite"
    build_vocabulary_pack(
        view_root,
        base_pack,
        trusted_manifest_digest=digest,
        schemes=(S_EURO, S_FR),
        languages=("en",),
    )

    # Inject 2 multi-word exact-"law" concepts and 2 single-word prefix-"law*" concepts ("Lawsuit", "Lawyer")
    # so naive `"law"*` BM25 would rank shorter single-word "Lawsuit"/"Lawyer" ahead of "Criminal law"/"Tax law"!
    pack_path = tmp_path / "vocab_law.sqlite"
    pack_path.write_bytes(base_pack.read_bytes())
    con = sqlite3.connect(str(pack_path))
    fr_sid = con.execute("SELECT sid FROM schemes WHERE uri = ?", (S_FR,)).fetchone()[0]
    fr_rel = con.execute("SELECT rel_id FROM releases WHERE uri = ?", (R_FR,)).fetchone()[0]
    max_rid = con.execute("SELECT max(rid) FROM resources").fetchone()[0]

    injected = [
        (max_rid + 1, "urn:ref:fr:lawsuit", "Lawsuit"),
        (max_rid + 2, "urn:ref:fr:lawyer", "Lawyer"),
        (max_rid + 3, "urn:ref:fr:criminal-law", "Criminal law"),
        (max_rid + 4, "urn:ref:fr:tax-law", "Tax law"),
    ]
    for rid, res_id, pref in injected:
        con.execute(
            "INSERT INTO resources(rid, id, sid, rel_id, definition, src_pfx, src_suffix, notations_json, pref_label, label_count) "
            "VALUES (?, ?, ?, ?, NULL, 0, 'src', NULL, ?, 1)",
            (rid, res_id, fr_sid, fr_rel, pref),
        )
        con.execute(
            "INSERT INTO labels(rid, role_rank, value_lower, value, lbl_pfx, lbl_suffix, role, language) "
            "VALUES (?, 0, ?, ?, 0, ?, 'preferred', 'en')",
            (rid, pref.lower(), pref, f"urn:ref:atlas-label:{rid}"),
        )
        con.execute("INSERT INTO label_exact(value_lower, role_rank, rid) VALUES (?, 0, ?)", (pref.lower(), rid))
        con.execute(
            "INSERT INTO concepts_bm25(rowid, pref_text, alt_text, def_text) VALUES (?, ?, '', '')",
            (rid, pref),
        )
    _refresh_pack_blobs(con)
    con.commit()
    con.close()

    with AtlasVocabularyPack.open(pack_path, verify_pack_digest=False) as pack:
        # 1. When exact-token hits fill limit=2, prefix wildcard is skipped and ONLY exact-"law" concepts return!
        top2 = pack.lookup_sync("law", limit=2)
        assert {c["label"] for c in top2} == {"Criminal law", "Tax law"}

        # 2. When limit=5 exceeds exact-token hits, exact-"law" concepts STILL rank strictly ahead of prefix hits!
        top5 = pack.lookup_sync("law", limit=5)
        labels = [c["label"] for c in top5]
        assert set(labels[:2]) == {"Criminal law", "Tax law"}
        assert set(labels[2:4]) == {"Lawsuit", "Lawyer"}

        # 3. Partial-word typeahead ("medicar" -> 0 exact-token hits -> falls through to "medicar"*) hits Medicare!
        ta = pack.lookup_sync("medicar", limit=5)
        assert [c["id"] for c in ta] == ["urn:ref:fr:medicare"]

        # 4. Multi-word partial typeahead ("flood insur" -> "flood" AND "insur"*) hits Flood insurance!
        ta2 = pack.lookup_sync("flood insur", limit=5)
        assert [c["id"] for c in ta2] == ["urn:ref:fr:flood-insurance"]


def test_extract_curated_scheme_tiebreak_unigram_df_guard_and_cli(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify curated scheme authority tie-breaking, max_unigram_doc_freq guard, and CLI flags."""
    view_root, digest = _write_compact_fixture(tmp_path / "view")
    base_pack = tmp_path / "vocab_base.sqlite"
    build_vocabulary_pack(
        view_root,
        base_pack,
        trusted_manifest_digest=digest,
        schemes=(S_EURO, S_FR, S_LCSH, S_MESH),
        languages=("en",),
    )

    # Inject a generic single-word concept "Rules" (S_LCSH) with high vocab_terms.doc_freq=500,
    # and boost "flood" and "insurance" doc_freq=500 to prove multi-word "Flood insurance" is NEVER suppressed!
    # Also add an alternate label "digital evidence" on an S_FR concept to confirm preferred beats alternate
    # even when the alternate belongs to a higher-weight scheme.
    pack_path = tmp_path / "vocab_extract.sqlite"
    pack_path.write_bytes(base_pack.read_bytes())
    con = sqlite3.connect(str(pack_path))
    lcsh_sid = con.execute("SELECT sid FROM schemes WHERE uri = ?", (S_LCSH,)).fetchone()[0]
    lcsh_rel = con.execute("SELECT rel_id FROM releases WHERE uri = ?", (R_LCSH,)).fetchone()[0]
    fr_med_rid = con.execute("SELECT rid FROM resources WHERE id = 'urn:ref:fr:medicare'").fetchone()[0]
    euro_housing_rid = con.execute("SELECT rid FROM resources WHERE id = 'http://eurovoc.europa.eu/1234'").fetchone()[0]
    fr_housing_rid = con.execute("SELECT rid FROM resources WHERE id = 'urn:ref:fr:housing'").fetchone()[0]
    assert euro_housing_rid < fr_housing_rid  # EuroVoc has lower canonical rid than S_FR!

    max_rid = con.execute("SELECT max(rid) FROM resources").fetchone()[0]
    rules_rid = max_rid + 1
    con.execute(
        "INSERT INTO resources(rid, id, sid, rel_id, definition, src_pfx, src_suffix, notations_json, pref_label, label_count) "
        "VALUES (?, 'http://id.loc.gov/authorities/subjects/sh_rules', ?, ?, NULL, 0, 'src', NULL, 'Rules', 1)",
        (rules_rid, lcsh_sid, lcsh_rel),
    )
    con.execute(
        "INSERT INTO labels(rid, role_rank, value_lower, value, lbl_pfx, lbl_suffix, role, language) "
        "VALUES (?, 0, 'rules', 'Rules', 0, 'urn:ref:atlas-label:lcsh-rules', 'preferred', 'en')",
        (rules_rid,),
    )
    con.execute("INSERT INTO label_exact(value_lower, role_rank, rid) VALUES ('rules', 0, ?)", (rules_rid,))
    con.execute("INSERT OR REPLACE INTO vocab_terms(term, doc_freq) VALUES ('rules', 500)")
    con.execute("UPDATE vocab_terms SET doc_freq = 500 WHERE term IN ('flood', 'insurance')")

    # Add alternate label "digital evidence" on S_FR Medicare (higher weight 0.14 vs EuroVoc preferred 0.11)
    con.execute(
        "INSERT INTO labels(rid, role_rank, value_lower, value, lbl_pfx, lbl_suffix, role, language) "
        "VALUES (?, 1, 'digital evidence', 'digital evidence', 0, 'urn:ref:atlas-label:fr-alt-de', 'alternate', 'en')",
        (fr_med_rid,),
    )
    con.execute("INSERT INTO label_exact(value_lower, role_rank, rid) VALUES ('digital evidence', 1, ?)", (fr_med_rid,))
    _refresh_pack_blobs(con)
    con.commit()
    con.close()

    with AtlasVocabularyPack.open(pack_path, verify_pack_digest=False) as pack:
        # 1. Neutral default scheme_weights (empty): pure canonical rid tie-breaking (EuroVoc wins, zero hardcoded bias!).
        hits_default = pack.extract_concepts_sync("Housing")
        assert len(hits_default) == 1
        assert hits_default[0]["concept"]["id"] == "http://eurovoc.europa.eu/1234"
        assert hits_default[0]["concept"]["scheme"] == S_EURO

        # 2. Explicit opt-in REGULATORY_BENCHMARK_SCHEME_PRESET: S_FR (0.14) beats S_EURO (0.11) on identical "Housing".
        hits_preset = pack.extract_concepts_sync("Housing", scheme_weights=REGULATORY_BENCHMARK_SCHEME_PRESET)
        assert len(hits_preset) == 1
        assert hits_preset[0]["concept"]["id"] == "urn:ref:fr:housing"
        assert hits_preset[0]["concept"]["scheme"] == S_FR

        # scheme_weights=None and scheme_weights={} also preserve pure canonical rid tie-breaking (EuroVoc wins).
        assert pack.extract_concepts_sync("Housing", scheme_weights=None)[0]["concept"]["id"] == (
            "http://eurovoc.europa.eu/1234"
        )
        assert pack.extract_concepts_sync("Housing", scheme_weights={})[0]["concept"]["id"] == (
            "http://eurovoc.europa.eu/1234"
        )

        # 3. Preferred role still beats alternate role regardless of explicit scheme authority weights!
        role_hits = pack.extract_concepts_sync("digital evidence", scheme_weights=REGULATORY_BENCHMARK_SCHEME_PRESET)
        assert role_hits[0]["concept"]["id"] == "http://eurovoc.europa.eu/9001"
        assert role_hits[0]["matchRole"] == "preferred"

        # 4. max_unigram_doc_freq suppresses high-DF generic single word "rules" (df=500) while keeping
        #    low-DF unigram "Medicare" (df=2) AND multi-word "Flood insurance" (never suppressed!).
        sentence = "New rules update Medicare and Flood insurance."
        unfiltered = pack.extract_concepts_sync(sentence)
        assert [m["matchedText"] for m in unfiltered] == ["rules", "Medicare", "Flood insurance"]

        filtered = pack.extract_concepts_sync(sentence, max_unigram_doc_freq=100)
        assert [(m["matchedText"], m["concept"]["id"]) for m in filtered] == [
            ("Medicare", "urn:ref:fr:medicare"),
            ("Flood insurance", "urn:ref:fr:flood-insurance"),
        ]

        # Async extract_concepts forwards both parameters identically.
        async_filtered = asyncio.run(
            pack.extract_concepts(
                None,
                "New rules update Housing and Flood insurance.",
                max_unigram_doc_freq=100,
                scheme_weights=REGULATORY_BENCHMARK_SCHEME_PRESET,
            )
        )
        assert [(m["matchedText"], m["concept"]["id"]) for m in async_filtered] == [
            ("Housing", "urn:ref:fr:housing"),
            ("Flood insurance", "urn:ref:fr:flood-insurance"),
        ]

        # Validation: non-positive or boolean max_unigram_doc_freq raises VocabularyInputError.
        for bad_df in (0, -5, True):
            with pytest.raises(VocabularyInputError, match="max_unigram_doc_freq"):
                pack.extract_concepts_sync("Medicare", max_unigram_doc_freq=bad_df)

    # 5. CLI extract --max-unigram-doc-freq / --max-unigram-df and --scheme-preset round-trip!
    rc1 = cli_main(
        [
            "extract",
            "--pack",
            str(pack_path),
            "--text",
            "New rules update Housing, Medicare, and Flood insurance.",
            "--max-unigram-df",
            "100",
        ]
    )
    assert rc1 == 0
    cli_filtered = json.loads(capsys.readouterr().out)
    assert [(m["matchedText"], m["concept"]["id"]) for m in cli_filtered] == [
        ("Housing", "http://eurovoc.europa.eu/1234"),
        ("Medicare", "urn:ref:fr:medicare"),
        ("Flood insurance", "urn:ref:fr:flood-insurance"),
    ]

    rc2 = cli_main(
        [
            "extract",
            "--pack",
            str(pack_path),
            "--text",
            "Housing",
            "--scheme-preset",
            "none",
        ]
    )
    assert rc2 == 0
    cli_neutral = json.loads(capsys.readouterr().out)
    assert [m["concept"]["id"] for m in cli_neutral] == ["http://eurovoc.europa.eu/1234"]

    rc3 = cli_main(
        [
            "extract",
            "--pack",
            str(pack_path),
            "--text",
            "Housing",
            "--scheme-preset",
            "regulatory-benchmark",
        ]
    )
    assert rc3 == 0
    cli_preset = json.loads(capsys.readouterr().out)
    assert [m["concept"]["id"] for m in cli_preset] == ["urn:ref:fr:housing"]

    # --max-unigram-doc-freq 0 disables the unigram DF cap cleanly!
    rc4 = cli_main(
        [
            "extract",
            "--pack",
            str(pack_path),
            "--text",
            "New rules update Medicare.",
            "--max-unigram-doc-freq",
            "0",
        ]
    )
    assert rc4 == 0
    cli_uncapped = json.loads(capsys.readouterr().out)
    assert [m["matchedText"] for m in cli_uncapped] == ["rules", "Medicare"]


def test_review_regressions_grouping_plural_prefix_and_scheme_weight_validation(tmp_path: Path) -> None:
    """Regressions for Findings 2 & 7: grouping/reranker pool fill, plural/2-token prefix AND, and immutable/validated weights."""
    from refspec.atlas.vocabulary_protocols import DEFAULT_CURATED_SCHEME_WEIGHTS

    # Finding 7: DEFAULT_CURATED_SCHEME_WEIGHTS must be immutable!
    with pytest.raises(TypeError):
        DEFAULT_CURATED_SCHEME_WEIGHTS["urn:ref:scheme:evil"] = 99.0  # type: ignore[index]

    view_root, digest = _write_compact_fixture(tmp_path / "view")
    base_pack = tmp_path / "vocab_base.sqlite"
    build_vocabulary_pack(
        view_root,
        base_pack,
        trusted_manifest_digest=digest,
        schemes=(S_EURO, S_FR, S_LCSH, S_MESH),
        languages=("en",),
    )
    pack_path = tmp_path / "vocab_f27.sqlite"
    pack_path.write_bytes(base_pack.read_bytes())
    con = sqlite3.connect(str(pack_path))
    fr_sid = con.execute("SELECT sid FROM schemes WHERE uri = ?", (S_FR,)).fetchone()[0]
    fr_rel = con.execute("SELECT rel_id FROM releases WHERE uri = ?", (R_FR,)).fetchone()[0]
    euro_sid = con.execute("SELECT sid FROM schemes WHERE uri = ?", (S_EURO,)).fetchone()[0]
    euro_rel = con.execute("SELECT rel_id FROM releases WHERE uri = ?", (R_EURO,)).fetchone()[0]
    max_rid = con.execute("SELECT max(rid) FROM resources").fetchone()[0]

    # Add 1 definition hit mentioning singular "veteran benefits", plus curated plural "Veterans" & "Veterans benefits"
    # and a duplicate-label pair for "Housing" + prefix hit "Housing assistance" to test grouping pool fill!
    rows_to_add = [
        (max_rid + 1, "urn:ref:fr:vet-note", fr_sid, fr_rel, "Legacy note", "Note discussing veteran benefits policy."),
        (max_rid + 2, "urn:ref:fr:veterans", fr_sid, fr_rel, "Veterans", "Military veterans."),
        (max_rid + 3, "urn:ref:fr:vet-benefits", fr_sid, fr_rel, "Veterans benefits", "Benefits for military veterans."),
        (max_rid + 4, "urn:ref:fr:housing-assist", fr_sid, fr_rel, "Housing assistance", "Housing assistance programs."),
        (max_rid + 5, "http://eurovoc.europa.eu/h-dup", euro_sid, euro_rel, "Housing", "Duplicate housing record."),
    ]
    for rid, res_id, sid, rel_id, pref, defn in rows_to_add:
        con.execute(
            "INSERT INTO resources(rid, id, sid, rel_id, definition, src_pfx, src_suffix, notations_json, pref_label, label_count) "
            "VALUES (?, ?, ?, ?, ?, 0, 'src', NULL, ?, 1)",
            (rid, res_id, sid, rel_id, defn, pref),
        )
        con.execute(
            "INSERT INTO labels(rid, role_rank, value_lower, value, lbl_pfx, lbl_suffix, role, language) "
            "VALUES (?, 0, ?, ?, 0, ?, 'preferred', 'en')",
            (rid, pref.lower(), pref, f"urn:ref:atlas-label:f27-{rid}"),
        )
        con.execute("INSERT INTO label_exact(value_lower, role_rank, rid) VALUES (?, 0, ?)", (pref.lower(), rid))
        con.execute("INSERT INTO concepts_bm25(rowid, pref_text, alt_text, def_text) VALUES (?, ?, '', ?)", (rid, pref, defn))
    _refresh_pack_blobs(con)
    con.commit()
    con.close()

    with AtlasVocabularyPack.open(pack_path, verify_pack_digest=False, candidate_reranker=AuthorityReranker()) as pack:
        # 1. Singular "veteran" with AuthorityReranker MUST still run prefix fallback to find plural "Veterans"!
        vet_hits = pack.lookup_sync("veteran", limit=2)
        assert any(c["label"] == "Veterans" for c in vet_hits)

        # 2. 2-token "veteran benefits" with 1 existing exact-token hit ("Legacy note") MUST still rescue
        #    "Veterans benefits" via Step 1c targeted AND-prefix!
        vb_hits = pack.lookup_sync("veteran benefits", limit=2)
        assert any(c["label"] == "Veterans benefits" for c in vb_hits)

        # 3. Grouped lookup for "housing" (limit=2) MUST NOT starve at 1 grouped card when 3 exact "Housing"
        #    records collapse into 1 — must fill slot #2 with "Housing assistance"!
        plain_pack = pack.with_dependencies(candidate_reranker=None, verify_pack_digest=False)
        grouped = plain_pack.lookup_sync("housing", limit=2, group_identical_labels=True)
        assert len(grouped) == 2
        assert grouped[0]["label"].lower() == "housing"
        assert grouped[1]["label"] == "Housing assistance"

        # 4. Finding 7: Invalid / NaN / bool scheme_weights raise VocabularyInputError cleanly!
        for bad_weights in ({S_FR: float("nan")}, {S_FR: float("inf")}, {S_FR: True}, {S_FR: "bad"}):
            with pytest.raises(VocabularyInputError, match="scheme weight"):
                pack.extract_concepts_sync("Medicare", scheme_weights=bad_weights)  # type: ignore[arg-type]


def test_prior_guided_semantic_index_demotes_subdivisions_and_preserves_raw_cosine(tmp_path: Path) -> None:
    """Verify PriorGuidedSemanticIndex rescues concise headings behind '--' subdivisions at Stage-1."""
    from refspec.atlas.vocabulary_pack import PriorGuidedSemanticIndex

    view_root, digest = _write_compact_fixture(tmp_path / "view")
    base_pack = tmp_path / "vocab_base.sqlite"
    manifest = build_vocabulary_pack(
        view_root,
        base_pack,
        trusted_manifest_digest=digest,
        schemes=(S_EURO, S_FR, S_LCSH, S_MESH),
        languages=("en",),
    )
    pack_path = tmp_path / "vocab_prior.sqlite"
    pack_path.write_bytes(base_pack.read_bytes())
    con = sqlite3.connect(str(pack_path))
    lcsh_sid = con.execute("SELECT sid FROM schemes WHERE uri = ?", (S_LCSH,)).fetchone()[0]
    lcsh_rel = con.execute("SELECT rel_id FROM releases WHERE uri = ?", (R_LCSH,)).fetchone()[0]
    med_rid = con.execute("SELECT rid FROM resources WHERE id = 'urn:ref:fr:medicare'").fetchone()[0]
    max_rid = con.execute("SELECT max(rid) FROM resources").fetchone()[0]
    sub_rid = max_rid + 1
    con.execute(
        "INSERT INTO resources(rid, id, sid, rel_id, definition, src_pfx, src_suffix, notations_json, pref_label, label_count) "
        "VALUES (?, 'http://id.loc.gov/authorities/subjects/sh_sub', ?, ?, NULL, 0, 'src', NULL, 'Older people--Medical care--United States', 1)",
        (sub_rid, lcsh_sid, lcsh_rel),
    )
    con.execute(
        "INSERT INTO labels(rid, role_rank, value_lower, value, lbl_pfx, lbl_suffix, role, language) "
        "VALUES (?, 0, 'older people--medical care--united states', 'Older people--Medical care--United States', 0, 'urn:ref:atlas-label:sub', 'preferred', 'en')",
        (sub_rid,),
    )
    _refresh_pack_blobs(con)
    con.commit()
    con.close()

    class StubIndex:
        pack_sha256 = manifest.pack_sha256
        pack_id = manifest.pack_id
        source_manifest_digest = digest
        model_id = "stub-512d"
        dimensions = 4
        closed = False

        def search_rids(self, query_vector: Sequence[float], *, top_k: int = 40, min_cosine: float = 0.55, nprobe: int = 24):
            _ = (query_vector, min_cosine, nprobe)
            # Subdivision has slightly higher raw cosine (0.82) than concise Medicare (0.78)!
            return [(sub_rid, 0.82), (med_rid, 0.78)][:top_k]

        def vector_for_rid(self, rid: int):
            return [1.0, 0.0, 0.0, 0.0] if rid == med_rid else None

        def close(self) -> None:
            self.closed = True

    stub = StubIndex()
    wrapped = PriorGuidedSemanticIndex.from_pack(pack_path, stub, min_oversample=16, owns_inner=False)
    assert isinstance(wrapped, SemanticIndex)
    assert wrapped.pack_id == manifest.pack_id
    assert wrapped.vector_for_rid(med_rid) == [1.0, 0.0, 0.0, 0.0]

    # Medicare (concise, S_FR +0.07) must overtake deep '--' subdivision (-0.14 + 0.01) while preserving raw cosine 0.78!
    ranked = wrapped.search_rids([1.0, 0.0, 0.0, 0.0], top_k=2, min_cosine=0.5)
    assert ranked == [(med_rid, 0.78), (sub_rid, 0.82)]

    wrapped.close()
    assert stub.closed is False

    # owns_inner=True closes inner on context exit
    with PriorGuidedSemanticIndex.from_pack(pack_path, stub, min_oversample=16, owns_inner=True):
        pass
    assert stub.closed is True

    # Invalid weights rejected with VocabularyInputError
    with pytest.raises(VocabularyInputError, match="scheme weight"):
        PriorGuidedSemanticIndex.from_pack(pack_path, stub, scheme_weights={S_FR: float("nan")})






def test_zero_dependency_tier0_serving_blocks_numpy_and_duckdb(tmp_path: Path) -> None:
    """Fix 1: Tier-0 serving imports ZERO numpy/duckdb/pyarrow/rdflib, and pyproject puts numpy in optional [vectors]."""
    import tomllib

    repo_root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    core_deps = pyproject["project"]["dependencies"]
    opt_vectors = pyproject["project"]["optional-dependencies"]["vectors"]
    dev_deps = pyproject["dependency-groups"]["dev"]

    assert not any(dep.lower().startswith("numpy") for dep in core_deps)
    assert any(dep.lower().startswith("numpy") for dep in opt_vectors)
    assert any(dep.lower().startswith("numpy") for dep in dev_deps)

    view_root, digest = _write_compact_fixture(tmp_path / "view")
    pack_path = tmp_path / "tier0.sqlite"
    build_vocabulary_pack(
        view_root,
        pack_path,
        trusted_manifest_digest=digest,
        schemes=(S_EURO, S_FR),
        languages=("en",),
    )

    script = f"""
import sys
from importlib.abc import MetaPathFinder

BLOCKED = frozenset({{"numpy", "duckdb", "pyarrow", "rdflib"}})

class _Blocker(MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        top = fullname.split(".")[0]
        if top in BLOCKED:
            raise ModuleNotFoundError(f"blocked optional dependency: {{fullname}}")
        return None

sys.meta_path.insert(0, _Blocker())
sys.path.insert(0, {str(repo_root / "src")!r})

from refspec.atlas import (
    DEFAULT_CURATED_SCHEME_WEIGHTS,
    REGULATORY_BENCHMARK_SCHEME_PRESET,
    AtlasVocabularyPack,
    AuthorityReranker,
    ExactPinnedRRF,
    PriorGuidedSemanticIndex,
)

for mod in BLOCKED:
    assert mod not in sys.modules, f"{{mod}} was eagerly imported!"

assert len(DEFAULT_CURATED_SCHEME_WEIGHTS) == 0
assert len(REGULATORY_BENCHMARK_SCHEME_PRESET) > 0

with AtlasVocabularyPack.open({str(pack_path)!r}, candidate_reranker=AuthorityReranker()) as pack:
    hits = pack.lookup_sync("computer crime", limit=5)
    assert hits and hits[0]["id"] == "http://eurovoc.europa.eu/3027"
    res = pack.resolve_sync({{"id": "urn:ref:fr:medicare", "scheme": {S_FR!r}, "release": {R_FR!r}}})
    assert res["label"] == "Medicare"
    rel = pack.related_sync({{"id": "http://eurovoc.europa.eu/3027", "scheme": {S_EURO!r}, "release": {R_EURO!r}}})
    assert len(rel) == 1
    exp = pack.expand_sync({{"id": "http://eurovoc.europa.eu/3027", "scheme": {S_EURO!r}, "release": {R_EURO!r}}}, max_depth=1)
    assert len(exp) == 1
    ext = pack.extract_concepts_sync("Medicare and Flood insurance")
    assert [m["matchedText"] for m in ext] == ["Medicare", "Flood insurance"]

for mod in BLOCKED:
    assert mod not in sys.modules, f"{{mod}} was imported during Tier-0 serving!"
"""
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"subprocess failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"


def test_neutral_default_scheme_weights_and_structural_prior_blob(tmp_path: Path) -> None:
    """Fix 2: Zero hardcoded scheme bias by default; neutral structural priors stored in pack_meta_blobs."""
    assert dict(DEFAULT_CURATED_SCHEME_WEIGHTS) == {}
    with pytest.raises(TypeError):
        DEFAULT_CURATED_SCHEME_WEIGHTS["urn:ref:scheme:x"] = 1.0  # type: ignore[index]
    with pytest.raises(TypeError):
        REGULATORY_BENCHMARK_SCHEME_PRESET["urn:ref:scheme:x"] = 1.0  # type: ignore[index]
    assert AuthorityReranker().scheme_weights == {}

    view_root, digest = _write_compact_fixture(tmp_path / "view")
    pack_path = tmp_path / "neutral.sqlite"
    manifest = build_vocabulary_pack(
        view_root,
        pack_path,
        trusted_manifest_digest=digest,
        schemes=(S_EURO, S_FR),
        languages=("en",),
    )

    con = sqlite3.connect(str(pack_path))
    euro_h_rid = int(con.execute("SELECT rid FROM resources WHERE id = 'http://eurovoc.europa.eu/1234'").fetchone()[0])
    fr_h_rid = int(con.execute("SELECT rid FROM resources WHERE id = 'urn:ref:fr:housing'").fetchone()[0])
    prior_blob = bytes(
        con.execute("SELECT payload FROM pack_meta_blobs WHERE key = 'structural_prior_f32'").fetchone()[0]
    )
    sid_blob = bytes(
        con.execute("SELECT payload FROM pack_meta_blobs WHERE key = 'sid_by_rid_u16'").fetchone()[0]
    )
    con.close()

    priors = array("f")
    priors.frombytes(prior_blob)
    if sys.byteorder != "little":
        priors.byteswap()
    sids = array("H")
    sids.frombytes(sid_blob)
    if sys.byteorder != "little":
        sids.byteswap()

    # Concise non-subdivided headings have neutral 0.0 structural prior regardless of scheme!
    assert priors[euro_h_rid] == pytest.approx(0.0)
    assert priors[fr_h_rid] == pytest.approx(0.0)
    assert sids[euro_h_rid] != sids[fr_h_rid] and sids[euro_h_rid] > 0 and sids[fr_h_rid] > 0

    class EqualCosineStub:
        pack_sha256 = manifest.pack_sha256
        pack_id = manifest.pack_id
        source_manifest_digest = digest
        model_id = "stub"
        dimensions = 4

        def search_rids(
            self,
            query_vector: Sequence[float],
            *,
            top_k: int = 40,
            min_cosine: float = 0.55,
            nprobe: int = 24,
            allowed_rids: Any = None,
            rerank_top_r: int | None = None,
        ) -> list[tuple[int, float]]:
            _ = (query_vector, top_k, min_cosine, nprobe, allowed_rids, rerank_top_r)
            return [(euro_h_rid, 0.80), (fr_h_rid, 0.80)]

        def vector_for_rid(self, rid: int) -> Any | None:
            _ = rid
            return None

    # Default PriorGuidedSemanticIndex applies ZERO scheme bias (lower rid euro_h_rid stays #1 on tie).
    neutral_idx = PriorGuidedSemanticIndex.from_pack(pack_path, EqualCosineStub(), min_oversample=8)
    assert [r for r, _ in neutral_idx.search_rids([1.0, 0.0, 0.0, 0.0], top_k=2)] == [euro_h_rid, fr_h_rid]

    # Explicit opt-in REGULATORY_BENCHMARK_SCHEME_PRESET boosts S_FR (+0.14*0.5) over S_EURO (+0.11*0.5) in memory!
    preset_idx = PriorGuidedSemanticIndex.from_pack(
        pack_path,
        EqualCosineStub(),
        scheme_weights=REGULATORY_BENCHMARK_SCHEME_PRESET,
        min_oversample=8,
    )
    assert [r for r, _ in preset_idx.search_rids([1.0, 0.0, 0.0, 0.0], top_k=2)] == [fr_h_rid, euro_h_rid]


def test_prior_guided_mismatch_forwarding_legacy_signature_and_v2_backward_compat(tmp_path: Path) -> None:
    """Fix 3 & Shared Contracts: strict cross-pack mismatch, allowed_rids/rerank_top_r forwarding, legacy fake & v2 pack."""
    view_root, digest = _write_compact_fixture(tmp_path / "view")
    pack_path = tmp_path / "v3_pack.sqlite"
    manifest = build_vocabulary_pack(
        view_root,
        pack_path,
        trusted_manifest_digest=digest,
        schemes=(S_EURO, S_FR),
        languages=("en",),
    )

    con = sqlite3.connect(str(pack_path))
    euro_rid = int(con.execute("SELECT rid FROM resources WHERE id = 'http://eurovoc.europa.eu/3027'").fetchone()[0])
    fr_rid = int(con.execute("SELECT rid FROM resources WHERE id = 'urn:ref:fr:medicare'").fetchone()[0])
    max_rid = int(con.execute("SELECT max(rid) FROM resources").fetchone()[0])
    con.close()

    class RecordingModernIndex:
        def __init__(self, *, pack_id: str, manifest_digest: str, pack_sha: str) -> None:
            self.pack_id = pack_id
            self.source_manifest_digest = manifest_digest
            self.pack_sha256 = pack_sha
            self.model_id = "modern"
            self.dimensions = 4
            self.calls: list[dict[str, Any]] = []

        def search_rids(
            self,
            query_vector: Sequence[float],
            *,
            top_k: int = 40,
            min_cosine: float = 0.55,
            nprobe: int = 24,
            allowed_rids: Any = None,
            rerank_top_r: int | None = None,
        ) -> list[tuple[int, float]]:
            self.calls.append(
                {
                    "top_k": top_k,
                    "min_cosine": min_cosine,
                    "nprobe": nprobe,
                    "allowed_rids": allowed_rids,
                    "rerank_top_r": rerank_top_r,
                }
            )
            hits = [(euro_rid, 0.90), (fr_rid, 0.85)]
            if allowed_rids is not None:
                hits = [(r, s) for r, s in hits if allowed_rids[r] != 0]
            return hits[:top_k]

        def vector_for_rid(self, rid: int) -> Any | None:
            return [1.0, 0.0, 0.0, 0.0] if rid == fr_rid else None

    # 1. Cross-pack mismatch rejection (pack_id, source_manifest_digest, and empty pack_id with wrong sha256)
    with pytest.raises(VocabularyPackError) as exc_id:
        PriorGuidedSemanticIndex.from_pack(
            pack_path,
            RecordingModernIndex(pack_id="urn:ref:vocabulary-pack:wrong", manifest_digest=digest, pack_sha=manifest.pack_sha256),
        )
    assert exc_id.value.code == "pack_mismatch"

    with pytest.raises(VocabularyPackError) as exc_man:
        PriorGuidedSemanticIndex.from_pack(
            pack_path,
            RecordingModernIndex(pack_id=manifest.pack_id, manifest_digest="sha256:" + "0" * 64, pack_sha=manifest.pack_sha256),
        )
    assert exc_man.value.code == "pack_mismatch"

    with pytest.raises(VocabularyPackError) as exc_sha:
        PriorGuidedSemanticIndex.from_pack(
            pack_path,
            RecordingModernIndex(pack_id="", manifest_digest=digest, pack_sha="sha256:" + "0" * 64),
        )
    assert exc_sha.value.code == "pack_mismatch"

    # 2. Modern forwarding: allowed_rids + rerank_top_r=max(req_k*2, 1024)
    modern = RecordingModernIndex(pack_id=manifest.pack_id, manifest_digest=digest, pack_sha=manifest.pack_sha256)
    guided = PriorGuidedSemanticIndex.from_pack(pack_path, modern, min_oversample=64, oversample_factor=4)
    mask = bytearray(max_rid + 1)
    mask[fr_rid] = 1
    out = guided.search_rids([1.0, 0.0, 0.0, 0.0], top_k=10, min_cosine=0.5, allowed_rids=bytes(mask))
    assert out == [(fr_rid, 0.85)]
    assert len(modern.calls) == 1
    assert modern.calls[0]["allowed_rids"] == bytes(mask)
    assert modern.calls[0]["rerank_top_r"] == 1024  # max(64*2, 1024)

    # 3. Minimal legacy SemanticIndex accepting ONLY (query_vec, *, top_k=40) stays 100% compatible!
    class MinimalLegacyIndex:
        pack_sha256 = manifest.pack_sha256
        pack_id = manifest.pack_id
        source_manifest_digest = digest
        model_id = "legacy-minimal"
        dimensions = 4

        def search_rids(self, query_vec: Sequence[float], *, top_k: int = 40) -> list[tuple[int, float]]:
            _ = (query_vec, top_k)
            return [(euro_rid, 0.90), (fr_rid, 0.85), (fr_rid, 0.20)]

        def vector_for_rid(self, rid: int) -> Any | None:
            return [1.0, 0.0, 0.0, 0.0] if rid == fr_rid else None

    legacy_wrapped = PriorGuidedSemanticIndex.from_pack(pack_path, MinimalLegacyIndex(), min_oversample=8)
    assert legacy_wrapped.search_rids([1.0, 0.0, 0.0, 0.0], top_k=5, min_cosine=0.5, allowed_rids={fr_rid}) == [
        (fr_rid, 0.85)
    ]

    # Legacy fake also works directly in AtlasVocabularyPack.open + lookup_sync(schemes=...)
    with AtlasVocabularyPack.open(pack_path, semantic_index=MinimalLegacyIndex(), verify_pack_digest=False) as pack:
        hits = pack.lookup_sync("unrelated semantic phrase", limit=5, schemes=[S_FR], query_vector=[1.0, 0.0, 0.0, 0.0])
        assert [c["id"] for c in hits] == ["urn:ref:fr:medicare"]

    # 4. Legacy schema v2 pack (no pack_meta_blobs table, unstripped diacritic value_lower) opens & serves cleanly!
    v2_pack = tmp_path / "legacy_v2.sqlite"
    v2_pack.write_bytes(pack_path.read_bytes())
    con2 = sqlite3.connect(str(v2_pack))
    con2.execute("DROP TABLE pack_meta_blobs")
    con2.execute("UPDATE pack_meta SET value = '2' WHERE key = 'schema_version'")
    fr_sid = con2.execute("SELECT sid FROM schemes WHERE uri = ?", (S_FR,)).fetchone()[0]
    fr_rel = con2.execute("SELECT rel_id FROM releases WHERE uri = ?", (R_FR,)).fetchone()[0]
    cafe_rid = max_rid + 1
    con2.execute(
        "INSERT INTO resources(rid, id, sid, rel_id, definition, src_pfx, src_suffix, notations_json, pref_label, label_count, has_preferred) "
        "VALUES (?, 'urn:ref:fr:cafe', ?, ?, NULL, 0, 'src', NULL, 'café', 1, 1)",
        (cafe_rid, fr_sid, fr_rel),
    )
    con2.execute(
        "INSERT INTO labels(rid, role_rank, value_lower, value, lbl_pfx, lbl_suffix, role, language) "
        "VALUES (?, 0, 'café', 'café', 0, 'urn:ref:atlas-label:v2-cafe', 'preferred', 'en')",
        (cafe_rid,),
    )
    con2.execute("INSERT INTO label_exact(value_lower, role_rank, rid) VALUES ('café', 0, ?)", (cafe_rid,))
    con2.commit()
    con2.close()

    with AtlasVocabularyPack.open(v2_pack, verify_pack_digest=False) as pack_v2:
        assert pack_v2.schema_version == "2"
        assert pack_v2.lookup_sync("café", limit=5)[0]["id"] == "urn:ref:fr:cafe"
        assert pack_v2.extract_concepts_sync("Visit the café today.")[0]["concept"]["id"] == "urn:ref:fr:cafe"
    v2_guided = PriorGuidedSemanticIndex.from_pack(v2_pack, modern, min_oversample=8)
    assert v2_guided.search_rids([1.0, 0.0, 0.0, 0.0], top_k=2, min_cosine=0.5)

    # 5. Corrupt pack_meta_blobs length fails closed with VocabularyPackError("corrupt_pack", ...)
    corrupt_pack = tmp_path / "corrupt_blob.sqlite"
    corrupt_pack.write_bytes(pack_path.read_bytes())
    con3 = sqlite3.connect(str(corrupt_pack))
    con3.execute("UPDATE pack_meta_blobs SET payload = X'0102' WHERE key = 'sid_by_rid_u16'")
    con3.commit()
    con3.close()
    with pytest.raises(VocabularyPackError) as exc_corrupt:
        AtlasVocabularyPack.open(corrupt_pack, verify_pack_digest=False)
    assert exc_corrupt.value.code == "corrupt_pack"


def test_allowed_rids_pushdown_and_zero_n_plus_1_scheme_sql(tmp_path: Path) -> None:
    """Fix 4: Schemes push bytes 0/1 allowed_rids mask into SemanticIndex with ZERO per-rid SELECT sid SQL."""
    view_root, digest = _write_compact_fixture(tmp_path / "view")
    pack_path = tmp_path / "filter_pushdown.sqlite"
    manifest = build_vocabulary_pack(
        view_root,
        pack_path,
        trusted_manifest_digest=digest,
        schemes=(S_EURO, S_FR, S_LCSH, S_MESH),
        languages=("en",),
    )

    con = sqlite3.connect(str(pack_path))
    euro_rids = [int(r[0]) for r in con.execute("SELECT rid FROM resources r JOIN schemes s ON s.sid=r.sid WHERE s.uri=?", (S_EURO,))]
    euro_3027_rid = int(con.execute("SELECT rid FROM resources WHERE id = 'http://eurovoc.europa.eu/3027'").fetchone()[0])
    fr_med_rid = int(con.execute("SELECT rid FROM resources WHERE id = 'urn:ref:fr:medicare'").fetchone()[0])
    fr_rids = {int(r[0]) for r in con.execute("SELECT rid FROM resources r JOIN schemes s ON s.sid=r.sid WHERE s.uri=?", (S_FR,))}
    max_rid = int(con.execute("SELECT max(rid) FROM resources").fetchone()[0])
    con.close()

    class StarvationProofSpyIndex:
        pack_sha256 = manifest.pack_sha256
        pack_id = manifest.pack_id
        source_manifest_digest = digest
        model_id = "spy"
        dimensions = 4

        def __init__(self) -> None:
            self.received_masks: list[Any] = []

        def vector_for_rid(self, rid: int) -> Sequence[float] | None:
            return [1.0, 0.0, 0.0, 0.0] if rid == euro_3027_rid else None

        def search_rids(
            self,
            query_vector: Sequence[float],
            *,
            top_k: int = 40,
            min_cosine: float = 0.55,
            nprobe: int = 24,
            allowed_rids: Any = None,
            rerank_top_r: int | None = None,
        ) -> list[tuple[int, float]]:
            _ = (query_vector, min_cosine, nprobe, rerank_top_r)
            self.received_masks.append(allowed_rids)
            if allowed_rids is None:
                # Without pushdown, non-FR rids dominate and starve FR!
                return [(r, 0.95) for r in euro_rids][:top_k]
            # With pushdown, return ONLY allowed rids (simulating exact-scan on <1% selectivity).
            candidates = [(r, 0.95) for r in euro_rids] + [(fr_med_rid, 0.88)]
            return [(r, s) for r, s in candidates if allowed_rids[r] != 0][:top_k]

    spy = StarvationProofSpyIndex()
    with AtlasVocabularyPack.open(pack_path, semantic_index=spy, verify_pack_digest=False) as pack:
        traced_sql: list[str] = []
        traced_con = pack._pool._idle[-1]
        traced_con.set_trace_callback(traced_sql.append)
        try:
            hits = pack.lookup_sync("unrelated semantic phrase", limit=5, schemes=[S_FR], query_vector=[1.0, 0.0, 0.0, 0.0])
            assert [c["id"] for c in hits] == ["urn:ref:fr:medicare"]

            sim_hits = pack.similar_sync(
                {"id": "http://eurovoc.europa.eu/3027", "scheme": S_EURO, "release": R_EURO},
                limit=5,
                schemes=[S_FR],
                exclude_same_scheme=True,
            )
            assert [c["concept"]["id"] for c in sim_hits] == ["urn:ref:fr:medicare"]
        finally:
            traced_con.set_trace_callback(None)

        # Verify mask pushed in BOTH lookup_sync and similar_sync is a bytes 0/1 mask matching fr_rids exactly!
        assert len(spy.received_masks) == 2
        for mask in spy.received_masks:
            assert isinstance(mask, bytes)
            assert len(mask) == max_rid + 1
            ones = {rid for rid, b in enumerate(mask) if b != 0}
            assert ones == fr_rids

        # Verify ZERO N+1 `SELECT sid FROM resources WHERE rid = ?` queries were issued!
        assert not any("SELECT sid FROM resources WHERE rid" in sql for sql in traced_sql)


def test_abstention_embarazo_nonsense_duplicate_tokens_tier2_and_stage0_short_circuit(tmp_path: Path) -> None:
    """Fix 5: Cross-lingual non-poisoning, nonsense abstention, dedup token coverage, Tier-2 no-wildcard, Stage-0 short-circuit."""
    view_root, digest = _write_compact_fixture(tmp_path / "view")
    base_pack = tmp_path / "base_f5.sqlite"
    manifest = build_vocabulary_pack(
        view_root,
        base_pack,
        trusted_manifest_digest=digest,
        schemes=(S_EURO, S_FR),
        languages=("en",),
    )

    pack_path = tmp_path / "f5.sqlite"
    pack_path.write_bytes(base_pack.read_bytes())
    con = sqlite3.connect(str(pack_path))
    fr_sid = con.execute("SELECT sid FROM schemes WHERE uri = ?", (S_FR,)).fetchone()[0]
    fr_rel = con.execute("SELECT rel_id FROM releases WHERE uri = ?", (R_FR,)).fetchone()[0]
    max_rid = int(con.execute("SELECT max(rid) FROM resources").fetchone()[0])

    # Add "Embargo" (df=3), "Pregnancy", and near-edit English neighbors for nonsense words ("Quart", "Plank", "Snare", "Group", "Crump"),
    # plus 2 exact "Sharedterm" concepts and 2 "law" concepts.
    added = [
        (max_rid + 1, "urn:ref:fr:embargo", "Embargo", "Trade embargo restrictions.", 3),
        (max_rid + 2, "urn:ref:fr:pregnancy", "Pregnancy", "Maternal pregnancy care.", 3),
        (max_rid + 3, "urn:ref:fr:quart", "Quart", "Liquid measure.", 5),
        (max_rid + 4, "urn:ref:fr:plank", "Plank", "Timber plank.", 5),
        (max_rid + 5, "urn:ref:fr:snare", "Snare", "Wire snare.", 5),
        (max_rid + 6, "urn:ref:fr:crump", "Crump", "Crump locality.", 5),
        (max_rid + 7, "urn:ref:fr:tax-law", "Tax law", "Federal tax law.", 5),
        (max_rid + 8, "urn:ref:fr:crim-law", "Criminal law", "Federal criminal law.", 5),
        (max_rid + 9, "urn:ref:fr:sh-1", "Sharedterm", "First shared term.", 3),
        (max_rid + 10, "urn:ref:fr:sh-2", "Sharedterm", "Second shared term.", 3),
    ]
    for rid, res_id, pref, defn, df in added:
        norm = normalize_text(pref)
        con.execute(
            "INSERT INTO resources(rid, id, sid, rel_id, definition, src_pfx, src_suffix, notations_json, pref_label, label_count, has_preferred) "
            "VALUES (?, ?, ?, ?, ?, 0, 'src', NULL, ?, 1, 1)",
            (rid, res_id, fr_sid, fr_rel, defn, pref),
        )
        con.execute(
            "INSERT INTO labels(rid, role_rank, value_lower, value, lbl_pfx, lbl_suffix, role, language) "
            "VALUES (?, 0, ?, ?, 0, ?, 'preferred', 'en')",
            (rid, norm, pref, f"urn:ref:atlas-label:f5-{rid}"),
        )
        con.execute("INSERT INTO label_exact(value_lower, role_rank, rid) VALUES (?, 0, ?)", (norm, rid))
        con.execute("INSERT INTO concepts_bm25(rowid, pref_text, alt_text, def_text) VALUES (?, ?, '', ?)", (rid, pref, defn))
        for tok in norm.split():
            if len(tok) >= 3:
                con.execute("INSERT OR REPLACE INTO vocab_terms(term, doc_freq) VALUES (?, ?)", (tok, df))
    con.execute("INSERT INTO vocab_terms_trigram(vocab_terms_trigram) VALUES('rebuild')")
    _refresh_pack_blobs(con)
    con.commit()
    con.close()

    pregnancy_rid = max_rid + 2
    tax_law_rid = max_rid + 7

    class EmbarazoDenseIndex:
        pack_sha256 = manifest.pack_sha256
        pack_id = manifest.pack_id
        source_manifest_digest = digest
        model_id = "multi-m3"
        dimensions = 4

        def vector_for_rid(self, rid: int) -> Any | None:
            _ = rid
            return None

        def search_rids(
            self,
            query_vector: Sequence[float],
            *,
            top_k: int = 40,
            min_cosine: float = 0.55,
            nprobe: int = 24,
            allowed_rids: Any = None,
            rerank_top_r: int | None = None,
        ) -> list[tuple[int, float]]:
            _ = (top_k, nprobe, allowed_rids, rerank_top_r)
            if query_vector[0] > 0.5:
                return [(pregnancy_rid, 0.84)] if 0.84 >= min_cosine else []
            return []

    class EmbarazoEncoder:
        model_id = "multi-m3"
        dimensions = 4

        def encode_query(self, text: str) -> Sequence[float]:
            if text.strip().lower() == "embarazo":
                return [1.0, 0.0, 0.0, 0.0]
            return [0.0, 0.0, 0.0, 1.0]

    with AtlasVocabularyPack.open(
        pack_path,
        semantic_index=EmbarazoDenseIndex(),
        query_encoder=EmbarazoEncoder(),
        verify_pack_digest=False,
    ) as pack:
        # 1. Cross-lingual "embarazo" gets dense "Pregnancy" (NEVER poisoned by lexical "Embargo"!).
        es_meta = pack.lookup_with_meta_sync("embarazo", limit=5)
        assert es_meta["tier"] == "semantic_hybrid"
        assert es_meta["correctedQuery"] is None
        assert [c["label"] for c in es_meta["concepts"]] == ["Pregnancy"]

        # 2. Pure lexical "embarazo" (no dense hits) also abstains cleanly instead of turning into "Embargo"!
        lex_only = pack.with_dependencies(semantic_index=None, query_encoder=None, verify_pack_digest=False)
        assert lex_only.lookup_sync("embarazo", limit=5) == []

        # 3. Nonsense 5-letter queries abstain cleanly with 0 hits even with near-edit dictionary words present!
        for nonsense in ("qwert", "plonk", "snark", "grump"):
            meta = pack.lookup_with_meta_sync(nonsense, limit=5)
            assert meta["concepts"] == [], f"expected abstention for {nonsense!r}, got {meta}"
            assert meta["tier"] == "empty"

        # 4. Duplicate query token bypass ("zxqvblargle law law") MUST abstain cleanly!
        assert lex_only.lookup_sync("zxqvblargle law law", limit=5) == []
        assert lex_only._filter_min_token_coverage([tax_law_rid], ["zxqvblargle", "law", "law"], 2) == []

        # 5. Tier-2 soft OR drops stopwords ("the", "for") AND drops `*` wildcards!
        traced_tier2: list[str] = []
        traced_lex_con = lex_only._pool._idle[-1]
        traced_lex_con.set_trace_callback(traced_tier2.append)
        try:
            lex_only.lookup_sync("the policy for zxqvblargle medicare", limit=5)
        finally:
            traced_lex_con.set_trace_callback(None)
        or_queries = [q for q in traced_tier2 if " OR " in q and "concepts_bm25" in q]
        assert or_queries, f"expected Tier-2 OR query in trace: {traced_tier2}"
        for q in or_queries:
            assert "*" not in q
            assert '"the"' not in q
            assert '"for"' not in q

        # 6. Stage-0 hybrid short-circuit: when Stage-0 exact hits fill limit=2, skip FTS5 concepts_bm25 completely!
        traced_stage0: list[str] = []
        traced_pack_con = pack._pool._idle[-1]
        traced_pack_con.set_trace_callback(traced_stage0.append)
        try:
            s0 = pack.lookup_with_meta_sync("sharedterm", limit=2)
        finally:
            traced_pack_con.set_trace_callback(None)
        assert s0["tier"] == "exact"
        assert len(s0["concepts"]) == 2
        assert all(c["label"] == "Sharedterm" for c in s0["concepts"])
        assert not any("concepts_bm25" in q for q in traced_stage0), f"FTS5 ran despite Stage-0 fill: {traced_stage0}"


def test_analyzer_symmetry_diacritics_and_nfkc(tmp_path: Path) -> None:
    """Fix 6: Shared normalize_text makes 'cafe', 'café', NFD 'cafe\\u0301', and NFKC 'ﬁle'/'file' Stage-0 exact."""
    view_root, _digest = _write_compact_fixture(tmp_path / "view", include_derived=False)
    # Inject diacritic & NFKC labels directly into Parquet and re-seal the fixture manifest.
    res_path = view_root / "tables/resources.parquet"
    lbl_path = view_root / "tables/labels.parquet"
    res_rows = pq.read_table(res_path).to_pylist()
    lbl_rows = pq.read_table(lbl_path).to_pylist()
    res_rows.extend(
        [
            {
                "id": "urn:ref:fr:cafe",
                "release": R_FR,
                "scheme": S_FR,
                "semantic_ring": "subject",
                "resource_profile": "Concept",
                "source_record": "urn:ref:atlas-source-record:" + "d" * 64,
                "definition": "Coffee house establishment.",
                "notes": [],
                "notations": [],
                "record_status": "active",
            },
            {
                "id": "urn:ref:fr:resume",
                "release": R_FR,
                "scheme": S_FR,
                "semantic_ring": "subject",
                "resource_profile": "Concept",
                "source_record": "urn:ref:atlas-source-record:" + "e" * 64,
                "definition": "Curriculum vitae document.",
                "notes": [],
                "notations": [],
                "record_status": "active",
            },
            {
                "id": "urn:ref:fr:ligature-file",
                "release": R_FR,
                "scheme": S_FR,
                "semantic_ring": "subject",
                "resource_profile": "Concept",
                "source_record": "urn:ref:atlas-source-record:" + "f" * 64,
                "definition": "Dossier record.",
                "notes": [],
                "notations": [],
                "record_status": "active",
            },
        ]
    )
    lbl_rows.extend(
        [
            {
                "id": "urn:ref:atlas-label:fr-cafe",
                "resource": "urn:ref:fr:cafe",
                "label_role": "preferred",
                "value": "café",
                "language": "en",
                "release": R_FR,
                "source_record": "urn:ref:atlas-source-record:" + "d" * 64,
            },
            {
                "id": "urn:ref:atlas-label:fr-resume",
                "resource": "urn:ref:fr:resume",
                "label_role": "preferred",
                "value": "résumé",
                "language": "en",
                "release": R_FR,
                "source_record": "urn:ref:atlas-source-record:" + "e" * 64,
            },
            {
                "id": "urn:ref:atlas-label:fr-lig-file",
                "resource": "urn:ref:fr:ligature-file",
                "label_role": "preferred",
                "value": "\ufb01le",
                "language": "en",
                "release": R_FR,
                "source_record": "urn:ref:atlas-source-record:" + "f" * 64,
            },
        ]
    )
    pq.write_table(pa.Table.from_pylist(res_rows, schema=_SCHEMAS[CompactRecordRole.RESOURCE]), res_path)
    pq.write_table(pa.Table.from_pylist(lbl_rows, schema=_SCHEMAS[CompactRecordRole.LABEL]), lbl_path)

    mpath = view_root / MANIFEST_FILE
    manifest_doc = json.loads(mpath.read_text(encoding="utf-8"))
    for member in manifest_doc["members"]:
        mp = view_root / member["path"]
        member["byteLength"] = mp.stat().st_size
        member["sha256"] = file_sha256(mp)
        if member["role"] == "Resource":
            member["rowCount"] = len(res_rows)
            manifest_doc["counts"]["Resource"] = len(res_rows)
        elif member["role"] == "Label":
            member["rowCount"] = len(lbl_rows)
            manifest_doc["counts"]["Label"] = len(lbl_rows)
    manifest_doc.pop("canonicalPayloadDigest", None)
    manifest_doc["canonicalPayloadDigest"] = canonical_payload_sha256(manifest_doc)
    mpath.write_bytes(canonical_json_bytes(manifest_doc))
    new_digest = file_sha256(mpath)

    pack_path = tmp_path / "sym.sqlite"
    build_vocabulary_pack(
        view_root,
        pack_path,
        trusted_manifest_digest=new_digest,
        schemes=(S_FR,),
        languages=("en",),
    )

    with AtlasVocabularyPack.open(pack_path) as pack:
        for variant in ("cafe", "café", "CAFÉ", "cafe\u0301"):
            res = pack.lookup_with_meta_sync(variant, limit=5)
            assert res["tier"] == "exact", f"expected Stage-0 exact for {variant!r}"
            assert res["concepts"][0]["id"] == "urn:ref:fr:cafe"

        file_res = pack.lookup_with_meta_sync("file", limit=5)
        assert file_res["tier"] == "exact"
        assert file_res["concepts"][0]["id"] == "urn:ref:fr:ligature-file"

        res_res = pack.lookup_with_meta_sync("resume", limit=5)
        assert res_res["tier"] == "exact"
        assert res_res["concepts"][0]["id"] == "urn:ref:fr:resume"

        extracted = pack.extract_concepts_sync("At the cafe we filed a resume.")
        assert [(m["matchedText"], m["concept"]["id"]) for m in extracted] == [
            ("cafe", "urn:ref:fr:cafe"),
            ("resume", "urn:ref:fr:resume"),
        ]


def test_build_hygiene_gates_tarjan_scc_self_loops_alt_only_prefix_and_symlinks(tmp_path: Path) -> None:
    """Fix 7: Pre-resolve symlink checks, manifest-driven derived path, urn:ref:atlas-derived:, unlabeled drop, self-loops, alt-only BM25, Tarjan SCC."""
    # 1. Direct stress test of strictly iterative Tarjan's SCC (5,000-node cycle > Python recursion limit 1,000!).
    deep_n = 5_000
    deep_adj = {i: [(i + 1) % deep_n] for i in range(deep_n)}
    sccs = _iterative_tarjan_sccs(deep_adj)
    assert len(sccs) == 1
    assert len(sccs[0]) == deep_n

    # 2. Build a view containing:
    #    - 3-node skos:broader cycle (A -> B -> C -> A) + acyclic edge (D -> A)
    #    - reflexive self-loops on native AND forward mapping edges
    #    - alternate-only concept (has_preferred == 0, like ICPSR)
    #    - derived relation with `urn:ref:atlas-derived:` prefix at custom manifest path
    view_root, _orig_digest = _write_compact_fixture(tmp_path / "view", include_derived=False)
    res_path = view_root / "tables/resources.parquet"
    lbl_path = view_root / "tables/labels.parquet"
    stm_path = view_root / "tables/statements.parquet"

    res_rows = pq.read_table(res_path).to_pylist()
    lbl_rows = pq.read_table(lbl_path).to_pylist()
    stm_rows = pq.read_table(stm_path).to_pylist()

    for suffix, label_val, role in [
        ("cyc-a", "Cycle Node Alpha", "preferred"),
        ("cyc-b", "Cycle Node Beta", "preferred"),
        ("cyc-c", "Cycle Node Gamma", "preferred"),
        ("cyc-d", "Acyclic Leaf Delta", "preferred"),
        ("alt-only", "Alternate Only Concept", "alternate"),
    ]:
        res_rows.append(
            {
                "id": f"urn:ref:fr:{suffix}",
                "release": R_FR,
                "scheme": S_FR,
                "semantic_ring": "subject",
                "resource_profile": "Concept",
                "source_record": "urn:ref:atlas-source-record:" + "7" * 64,
                "definition": None,
                "notes": [],
                "notations": [],
                "record_status": "active",
            }
        )
        lbl_rows.append(
            {
                "id": f"urn:ref:atlas-label:fr-{suffix}",
                "resource": f"urn:ref:fr:{suffix}",
                "label_role": role,
                "value": label_val,
                "language": "en",
                "release": R_FR,
                "source_record": "urn:ref:atlas-source-record:" + "7" * 64,
            }
        )

    def _mk_stmt(sid: str, stype: str, subj: str, pred: str, obj: str) -> dict[str, Any]:
        return {
            "id": sid,
            "statement_type": stype,
            "subject": subj,
            "predicate": pred,
            "object": obj,
            "source_release": R_FR,
            "target_release": R_FR,
            "policy": "urn:ref:atlas-policy:" + "0" * 64,
            "asserted_at": "2026-08-15T00:00:00Z",
            "semantic_ring": "subject",
            "source_ring": "subject",
            "target_ring": "subject",
            "supersedes_assertion": None,
        }

    stm_rows.extend(
        [
            # 3-node broader cycle A -> B -> C -> A
            _mk_stmt("urn:ref:atlas-assertion:cyc-1", "NativeRelationAssertion", "urn:ref:fr:cyc-a", SKOS + "broader", "urn:ref:fr:cyc-b"),
            _mk_stmt("urn:ref:atlas-assertion:cyc-2", "NativeRelationAssertion", "urn:ref:fr:cyc-b", SKOS + "broader", "urn:ref:fr:cyc-c"),
            _mk_stmt("urn:ref:atlas-assertion:cyc-3", "NativeRelationAssertion", "urn:ref:fr:cyc-c", SKOS + "broader", "urn:ref:fr:cyc-a"),
            # Acyclic broader edge D -> A (MUST survive cycle quarantine!)
            _mk_stmt("urn:ref:atlas-assertion:acyc-1", "NativeRelationAssertion", "urn:ref:fr:cyc-d", SKOS + "broader", "urn:ref:fr:cyc-a"),
            # Reflexive self-loops (native AND forward mapping) -> MUST be dropped!
            _mk_stmt("urn:ref:atlas-assertion:self-nat", "NativeRelationAssertion", "urn:ref:fr:medicare", SKOS + "related", "urn:ref:fr:medicare"),
            _mk_stmt("urn:ref:atlas-assertion:self-map", "MappingAssertion", "urn:ref:fr:medicare", SKOS + "exactMatch", "urn:ref:fr:medicare"),
        ]
    )

    pq.write_table(pa.Table.from_pylist(res_rows, schema=_SCHEMAS[CompactRecordRole.RESOURCE]), res_path)
    pq.write_table(pa.Table.from_pylist(lbl_rows, schema=_SCHEMAS[CompactRecordRole.LABEL]), lbl_path)
    pq.write_table(pa.Table.from_pylist(stm_rows, schema=_SCHEMAS[CompactRecordRole.STATEMENT]), stm_path)

    # Write derived relations at standard path with `urn:ref:atlas-derived:` prefix
    drv_rows = [
        {
            "id": "urn:ref:atlas-derived:mesh-broader-prefixed",
            "subject": "https://id.nlm.nih.gov/mesh/D006278",
            "predicate": SKOS + "broader",
            "object": "https://id.nlm.nih.gov/mesh/D007348",
            "semantic_ring": "subject",
            "derivation_rule": "urn:ref:rule:mesh-tree-number-broader",
            "engine": "refspec",
            "engine_version": "0.1",
            "derived_from_assertions": [],
            "input_digest": _hex32(9),
            "generated_at": "2026-08-15T00:00:00Z",
            "content_digest": _hex32(10),
        }
    ]
    drv_path = view_root / "tables/derived-relations.parquet"
    pq.write_table(pa.Table.from_pylist(drv_rows, schema=DERIVED_RELATION_TABLE_SCHEMA), drv_path)

    mpath = view_root / MANIFEST_FILE
    manifest_doc = json.loads(mpath.read_text(encoding="utf-8"))
    manifest_doc["members"].append(
        {
            "byteLength": drv_path.stat().st_size,
            "mediaType": "application/vnd.apache.parquet",
            "path": "tables/derived-relations.parquet",
            "role": DERIVED_RELATION_ROLE,
            "rowCount": len(drv_rows),
            "schemaDigest": arrow_schema_sha256(pq.ParquetFile(drv_path).schema_arrow),
            "sha256": file_sha256(drv_path),
        }
    )
    manifest_doc["counts"][DERIVED_RELATION_ROLE] = len(drv_rows)
    for member in manifest_doc["members"]:
        mp = view_root / member["path"]
        member["byteLength"] = mp.stat().st_size
        member["sha256"] = file_sha256(mp)
        if member["role"] == "Resource":
            member["rowCount"] = len(res_rows)
            manifest_doc["counts"]["Resource"] = len(res_rows)
        elif member["role"] == "Label":
            member["rowCount"] = len(lbl_rows)
            manifest_doc["counts"]["Label"] = len(lbl_rows)
        elif member["role"] == "Statement":
            member["rowCount"] = len(stm_rows)
            manifest_doc["counts"]["Statement"] = len(stm_rows)
    manifest_doc.pop("canonicalPayloadDigest", None)
    manifest_doc["canonicalPayloadDigest"] = canonical_payload_sha256(manifest_doc)
    mpath.write_bytes(canonical_json_bytes(manifest_doc))
    new_digest = file_sha256(mpath)

    # Pre-.resolve() symlink rejection on view_root, parent dir, and output_path!
    sym_view = tmp_path / "sym_view"
    sym_view.symlink_to(view_root)
    with pytest.raises(VocabularyPackError) as exc_sv:
        build_vocabulary_pack(sym_view, tmp_path / "x.sqlite", trusted_manifest_digest=new_digest, schemes=(S_FR,))
    assert exc_sv.value.code == "invalid_view_root"

    sym_parent = tmp_path / "sym_parent"
    sym_parent.symlink_to(tmp_path)
    with pytest.raises(VocabularyPackError) as exc_sp:
        build_vocabulary_pack(sym_parent / "view", tmp_path / "x.sqlite", trusted_manifest_digest=new_digest, schemes=(S_FR,))
    assert exc_sp.value.code == "invalid_view_root"

    sym_out = tmp_path / "sym_out.sqlite"
    sym_out.symlink_to(tmp_path / "real_target.sqlite")
    with pytest.raises(VocabularyPackError) as exc_so:
        build_vocabulary_pack(view_root, sym_out, trusted_manifest_digest=new_digest, schemes=(S_FR,))
    assert exc_so.value.code == "invalid_pack"

    # Build with default quarantine_broader_cycles=True
    pack_path = tmp_path / "hygiene.sqlite"
    man = build_vocabulary_pack(
        view_root,
        pack_path,
        trusted_manifest_digest=new_digest,
        schemes=(S_EURO, S_FR, S_UMTHES, S_MESH),
        languages=("en",),
        include_mappings=True,
        include_derived=True,
    )
    assert man.broader_cycle_count == 1
    assert man.quarantined_cycle_edges == 3

    con = sqlite3.connect(str(pack_path))
    meta = dict(con.execute("SELECT key, value FROM pack_meta").fetchall())
    assert meta["broader_cycle_count"] == "1"
    assert meta["quarantined_cycle_edges"] == "3"

    # Unlabeled German-only resource omitted completely (0 rows with label_count == 0)
    assert con.execute("SELECT count(*) FROM resources WHERE label_count = 0").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM resources WHERE id = 'https://sns.uba.de/umthes/_de_only'").fetchone()[0] == 0

    # Zero reflexive self-loops in edges or edges_rev
    assert con.execute("SELECT count(*) FROM edges WHERE src_rid = dst_rid").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM edges_rev WHERE src_rid = dst_rid").fetchone()[0] == 0

    # urn:ref:atlas-derived: compressed in uri_prefixes and used by derived edge
    drv_pfx_row = con.execute("SELECT pfx_id FROM uri_prefixes WHERE prefix = 'urn:ref:atlas-derived:'").fetchone()
    assert drv_pfx_row is not None
    drv_pfx_id = int(drv_pfx_row[0])
    assert con.execute("SELECT count(*) FROM edges WHERE stmt_pfx = ?", (drv_pfx_id,)).fetchone()[0] == 1

    # Alternate-only concept has has_preferred == 0 and is NOT duplicated into concepts_bm25.pref_text!
    alt_row = con.execute("SELECT rid, has_preferred FROM resources WHERE id = 'urn:ref:fr:alt-only'").fetchone()
    assert alt_row is not None and int(alt_row[1]) == 0
    assert con.execute("SELECT has_preferred FROM resources WHERE id = 'urn:ref:fr:medicare'").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM concepts_bm25 WHERE concepts_bm25 MATCH 'pref_text : alternate'").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM concepts_bm25 WHERE concepts_bm25 MATCH 'alt_text : alternate'").fetchone()[0] == 1

    # Acyclic D -> A broader edge survived while A -> B -> C -> A cycle edges were quarantined!
    cyc_a_rid = int(con.execute("SELECT rid FROM resources WHERE id = 'urn:ref:fr:cyc-a'").fetchone()[0])
    cyc_d_rid = int(con.execute("SELECT rid FROM resources WHERE id = 'urn:ref:fr:cyc-d'").fetchone()[0])
    assert con.execute("SELECT count(*) FROM edges WHERE src_rid = ? AND dst_rid = ?", (cyc_d_rid, cyc_a_rid)).fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM edges WHERE src_rid = ?", (cyc_a_rid,)).fetchone()[0] == 0
    con.close()

    # Also verify opt-out quarantine_broader_cycles=False keeps cycle edges while still recording broader_cycle_count=1
    pack_unq = tmp_path / "hygiene_unquarantined.sqlite"
    man_unq = build_vocabulary_pack(
        view_root,
        pack_unq,
        trusted_manifest_digest=new_digest,
        schemes=(S_FR,),
        languages=("en",),
        quarantine_broader_cycles=False,
    )
    assert man_unq.broader_cycle_count == 1
    assert man_unq.quarantined_cycle_edges == 0
    assert man_unq.native_edge_count == 4


def test_concurrent_8_threads_lookup_resolve_related_and_clean_close(tmp_path: Path) -> None:
    """Fix 8: Thread-local read-only connections serve 8 concurrent threads cleanly and close all connections."""
    view_root, digest = _write_compact_fixture(tmp_path / "view")
    pack_path = tmp_path / "concurrent.sqlite"
    build_vocabulary_pack(
        view_root,
        pack_path,
        trusted_manifest_digest=digest,
        schemes=(S_EURO, S_FR, S_LCSH, S_MESH),
        languages=("en",),
        include_mappings=True,
        include_derived=True,
    )

    euro_ref = {"id": "http://eurovoc.europa.eu/3027", "scheme": S_EURO, "release": R_EURO}
    fr_ref = {"id": "urn:ref:fr:medicare", "scheme": S_FR, "release": R_FR}

    pack = AtlasVocabularyPack.open(pack_path)
    try:
        def _worker(worker_id: int) -> int:
            completed = 0
            for step in range(40):
                q = ("computer crime", "Medicare", "Flood insurance", "medciare")[step % 4]
                hits = pack.lookup_sync(q, limit=5, schemes=[S_EURO, S_FR])
                assert hits
                res = pack.resolve_sync(fr_ref)
                assert res["label"] == "Medicare"
                rel = pack.related_sync(euro_ref, limit=10, include_mappings=True)
                assert len(rel) >= 1
                ext = pack.extract_concepts_sync("Medicare and Flood insurance address cybercrime.")
                assert len(ext) == 3
                completed += 1
            return completed + worker_id * 0

        with ThreadPoolExecutor(max_workers=8) as executor:
            totals = list(executor.map(_worker, range(8)))
        assert totals == [40] * 8
        assert 1 <= len(pack._pool._idle) <= pack._pool._max_idle
        assert len(pack._pool._in_use) == 0
    finally:
        pack.close()

    # Idempotent close + post-close operations fail closed with VocabularyPackError("pack_closed", ...)
    pack.close()
    assert len(pack._pool._idle) == 0
    assert len(pack._pool._in_use) == 0
    with pytest.raises(VocabularyPackError) as exc_closed:
        pack.lookup_sync("Medicare", limit=5)
    assert exc_closed.value.code == "pack_closed"


def test_extract_concepts_hardening_punctuation_acronyms_stopwords_and_batched_sql(tmp_path: Path) -> None:
    """Fix 9: Punctuation-crossing spans rejected, <=4-char all-caps acronyms case-checked, stopword/DF defaults, 1 batched SQL."""
    view_root, digest = _write_compact_fixture(tmp_path / "view")
    base_pack = tmp_path / "base_ext.sqlite"
    build_vocabulary_pack(
        view_root,
        base_pack,
        trusted_manifest_digest=digest,
        schemes=(S_EURO, S_FR),
        languages=("en",),
    )

    pack_path = tmp_path / "ext_harden.sqlite"
    pack_path.write_bytes(base_pack.read_bytes())
    con = sqlite3.connect(str(pack_path))
    euro_sid = con.execute("SELECT sid FROM schemes WHERE uri = ?", (S_EURO,)).fetchone()[0]
    euro_rel = con.execute("SELECT rel_id FROM releases WHERE uri = ?", (R_EURO,)).fetchone()[0]
    fr_sid = con.execute("SELECT sid FROM schemes WHERE uri = ?", (S_FR,)).fetchone()[0]
    fr_rel = con.execute("SELECT rel_id FROM releases WHERE uri = ?", (R_FR,)).fetchone()[0]
    max_rid = int(con.execute("SELECT max(rid) FROM resources").fetchone()[0])

    # Add:
    # - GEMET-style forestry concept with all-caps short alternate label "FOR"
    # - WHO concept with all-caps short alternate label "WHO"
    # - EPA concept with all-caps short preferred label "EPA"
    # - High-DF generic unigram "states" (doc_freq = 2500 > DEFAULT_EXTRACT_MAX_UNIGRAM_DOC_FREQ)
    # - Punctuated labels in label_exact to prove spans crossing , ; . : ( ) [ ] \n are NEVER extracted!
    extra = [
        (max_rid + 1, "urn:ref:gemet:forestry", euro_sid, euro_rel, "forestry", [("FOR", "alternate", 1)]),
        (max_rid + 2, "urn:ref:org:who", fr_sid, fr_rel, "World Health Organization", [("WHO", "alternate", 1)]),
        (max_rid + 3, "urn:ref:org:epa", fr_sid, fr_rel, "EPA", []),
        (max_rid + 4, "urn:ref:fr:states", fr_sid, fr_rel, "states", []),
        (max_rid + 5, "urn:ref:fr:punc-comma", fr_sid, fr_rel, "alpha, beta", []),
        (max_rid + 6, "urn:ref:fr:punc-semi", fr_sid, fr_rel, "gamma; delta", []),
        (max_rid + 7, "urn:ref:fr:punc-dot", fr_sid, fr_rel, "eps. zeta", []),
        (max_rid + 8, "urn:ref:fr:punc-colon", fr_sid, fr_rel, "eta: theta", []),
        (max_rid + 9, "urn:ref:fr:punc-paren", fr_sid, fr_rel, "iota (kappa)", []),
        (max_rid + 10, "urn:ref:fr:punc-brack", fr_sid, fr_rel, "lambda [mu]", []),
        (max_rid + 11, "urn:ref:fr:punc-nl", fr_sid, fr_rel, "nu xi", []),
    ]
    for rid, res_id, sid, rel_id, pref, alts in extra:
        con.execute(
            "INSERT INTO resources(rid, id, sid, rel_id, definition, src_pfx, src_suffix, notations_json, pref_label, label_count, has_preferred) "
            "VALUES (?, ?, ?, ?, NULL, 0, 'src', NULL, ?, ?, 1)",
            (rid, res_id, sid, rel_id, pref, 1 + len(alts)),
        )
        pnorm = normalize_text(pref)
        con.execute(
            "INSERT INTO labels(rid, role_rank, value_lower, value, lbl_pfx, lbl_suffix, role, language) "
            "VALUES (?, 0, ?, ?, 0, ?, 'preferred', 'en')",
            (rid, pnorm, pref, f"urn:ref:atlas-label:ext-{rid}-p"),
        )
        con.execute("INSERT INTO label_exact(value_lower, role_rank, rid) VALUES (?, 0, ?)", (pnorm, rid))
        for alt_idx, (aval, arole, arank) in enumerate(alts):
            anorm = normalize_text(aval)
            con.execute(
                "INSERT INTO labels(rid, role_rank, value_lower, value, lbl_pfx, lbl_suffix, role, language) "
                "VALUES (?, ?, ?, ?, 0, ?, ?, 'en')",
                (rid, arank, anorm, aval, f"urn:ref:atlas-label:ext-{rid}-a{alt_idx}", arole),
            )
            con.execute("INSERT INTO label_exact(value_lower, role_rank, rid) VALUES (?, ?, ?)", (anorm, arank, rid))
    con.execute(
        "INSERT OR REPLACE INTO vocab_terms(term, doc_freq) VALUES ('states', ?)",
        (DEFAULT_EXTRACT_MAX_UNIGRAM_DOC_FREQ + 1500,),
    )
    _refresh_pack_blobs(con)
    con.commit()
    con.close()

    with AtlasVocabularyPack.open(pack_path, verify_pack_digest=False) as pack:
        # 1. Punctuation-crossing spans rejected for ALL 9 separators (, ; . : ( ) [ ] \n)!
        punc_prose = "alpha, beta | gamma; delta | eps. zeta | eta: theta | iota (kappa) | lambda [mu] | nu\nxi"
        assert pack.extract_concepts_sync(punc_prose, limit=20) == []

        # 2. Short <=4-char all-caps acronyms require exact uppercase match ("for"/"who"/"epa" never match "FOR"/"WHO"/"EPA")!
        lower_prose = "Rules for states and who funds epa programs."
        assert pack.extract_concepts_sync(lower_prose, limit=20) == []

        upper_prose = "See FOR, WHO, and EPA guidance on Medicare, Flood insurance, and cybercrime."
        traced_sql: list[str] = []
        traced_con = pack._pool._idle[-1]
        traced_con.set_trace_callback(traced_sql.append)
        try:
            hits = pack.extract_concepts_sync(upper_prose, limit=20)
        finally:
            traced_con.set_trace_callback(None)

        assert [(m["matchedText"], m["concept"]["id"], m["matchedLabelId"]) for m in hits] == [
            ("FOR", "urn:ref:gemet:forestry", f"urn:ref:atlas-label:ext-{max_rid + 1}-a0"),
            ("WHO", "urn:ref:org:who", f"urn:ref:atlas-label:ext-{max_rid + 2}-a0"),
            ("EPA", "urn:ref:org:epa", f"urn:ref:atlas-label:ext-{max_rid + 3}-p"),
            ("Medicare", "urn:ref:fr:medicare", "urn:ref:atlas-label:fr-medicare-pref"),
            ("Flood insurance", "urn:ref:fr:flood-insurance", "urn:ref:atlas-label:fr-flood-pref"),
            ("cybercrime", "http://eurovoc.europa.eu/3027", "urn:ref:atlas-label:euro-3027-alt"),
        ]

        # 3. Verify matchedLabelId hydration used ONE batched IN (...) query, NOT 6 N+1 per-item queries!
        matched_lbl_queries = [q for q in traced_sql if "FROM labels" in q and "value_lower IN" in q]
        # 1 query for short-acronym casing check + 1 batched query for matchedLabelId hydration (never 6!)
        assert len(matched_lbl_queries) <= 2
        assert not any("WHERE rid = ?" in q and "FROM labels" in q for q in traced_sql)

        # 4. Default max_unigram_doc_freq suppresses high-DF "states", while explicit None allows it.
        assert pack.extract_concepts_sync("Many states participate.") == []
        unbounded = pack.extract_concepts_sync("Many states participate.", max_unigram_doc_freq=None)
        assert [m["matchedText"] for m in unbounded] == ["states"]


def _build_direct_parquet_view_with_agency_tables(base_dir: Path) -> tuple[Path, str]:
    """Build a real sealed `parquet-view` (`view-manifest.json`) with lifecycle events and agency projections."""

    import hashlib

    from refspec.atlas import agency_projection
    from refspec.atlas.compact_pack import CompactRecordRole, normalize_compact_record
    from refspec.atlas.parquet_artifact import canonical_payload_sha256, file_sha256
    from refspec.atlas.parquet_tables import AtlasParquetTableWriter, write_agency_projection_tables
    from refspec.atlas.parquet_view import MANIFEST_FILE as VIEW_MANIFEST_FILE
    from refspec.atlas.parquet_view import seal_atlas_parquet_view
    from refspec.release_model import canonical_json_bytes

    dist_root = base_dir / "distribution"
    (dist_root / "packs" / "sources").mkdir(parents=True)

    d1 = "sha256:" + "1" * 64
    d2 = "sha256:" + "2" * 64
    d3 = "sha256:" + "3" * 64
    d4 = "sha256:" + "4" * 64
    dist_id = "urn:ref:atlas-distribution:3:bounded:2026-08-21:pv-pack-test"
    created_at = "2026-08-21T00:00:00+00:00"

    pack_path = dist_root / "packs" / "sources" / "sample.nq.zst"
    pack_bytes = b"sample-direct-parquet-view-pack\n"
    pack_path.write_bytes(pack_bytes)
    content_digest = "sha256:" + hashlib.sha256(pack_bytes).hexdigest()
    pack_id = "urn:ref:atlas:pack:" + content_digest.removeprefix("sha256:")

    asserted_inv = [{"contentDigest": content_digest, "packId": pack_id, "quadCount": 1}]
    asserted_inv_digest = canonical_payload_sha256(asserted_inv)
    empty_inv_digest = canonical_payload_sha256([])
    contract_digest = "sha256:" + "a" * 64

    summary: dict[str, Any] = {
        "assertedInventoryDigest": asserted_inv_digest,
        "contractDigest": contract_digest,
        "distributionId": dist_id,
        "type": "AtlasConstructionSummary",
        "version": "3.1",
    }
    summary["canonicalPayloadDigest"] = canonical_payload_sha256(summary)
    summary_path = dist_root / "atlas-construction-summary.json"
    summary_path.write_bytes(canonical_json_bytes(summary) + b"\n")

    manifest: dict[str, Any] = {
        "binding": {"contractDigest": contract_digest, "ontologyDigest": "sha256:" + "b" * 64},
        "counts": {},
        "createdAt": created_at,
        "distributionId": dist_id,
        "format": "refspec-atlas-packed-nquads-3.1",
        "graphs": [
            {
                "id": "urn:ref:graph:asserted",
                "inventoryDigest": asserted_inv_digest,
                "packCount": 1,
                "quadCount": 1,
                "role": "asserted",
            },
            {
                "id": "urn:ref:graph:projection",
                "inventoryDigest": empty_inv_digest,
                "packCount": 0,
                "quadCount": 0,
                "role": "projection",
            },
            {
                "id": "urn:ref:graph:derived",
                "inventoryDigest": empty_inv_digest,
                "packCount": 0,
                "quadCount": 0,
                "role": "derived",
            },
        ],
        "members": [
            {
                "byteLength": summary_path.stat().st_size,
                "digest": file_sha256(summary_path),
                "mediaType": "application/json",
                "path": "atlas-construction-summary.json",
                "role": "constructionSummary",
            }
        ],
        "packs": [
            {
                "content": {"byteLength": len(pack_bytes), "digest": content_digest},
                "graphCounts": {"asserted": 1, "derived": 0, "projection": 0},
                "packId": pack_id,
                "path": "packs/sources/sample.nq.zst",
                "transport": {"byteLength": len(pack_bytes), "digest": file_sha256(pack_path)},
            }
        ],
        "schemaVersion": "3.1",
        "type": "AtlasManifest",
    }
    manifest["canonicalPayloadDigest"] = canonical_payload_sha256(manifest)
    manifest_path = dist_root / "atlas-manifest.json"
    manifest_path.write_bytes(canonical_json_bytes(manifest) + b"\n")

    release = "urn:ref:atlas-release:3:test-agencies:2026-08-21"
    scheme = "urn:ref:atlas-resource-scheme:test-agencies"
    source_record = "urn:ref:atlas-source-record:" + "5" * 64
    statement = "urn:ref:atlas-assertion:" + "3" * 64

    records = {
        CompactRecordRole.RESOURCE: [
            {
                "contentDigest": d1,
                "definition": "United States Environmental Protection Agency",
                "id": "urn:ref:org:epa",
                "notations": ["EPA"],
                "notes": [],
                "recordStatus": "active",
                "release": release,
                "resourceProfile": "resourceCollection",
                "scheme": scheme,
                "semanticRing": "entity",
                "sourceRecord": source_record,
            },
        ],
        CompactRecordRole.LABEL: [
            {
                "contentDigest": d2,
                "id": "urn:ref:atlas-label:" + "7" * 64,
                "labelRole": "preferred",
                "language": "en",
                "release": release,
                "resource": "urn:ref:org:epa",
                "sourceRecord": source_record,
                "value": "Environmental Protection Agency",
            },
        ],
        CompactRecordRole.STATEMENT: [
            {
                "assertedAt": "2026-08-07T00:00:00+00:00",
                "assertionIdentityDigest": d3,
                "contentDigest": d4,
                "id": statement,
                "object": "urn:ref:org:us-gov",
                "policy": "urn:ref:atlas-policy:" + "6" * 64,
                "predicate": "http://www.w3.org/2004/02/skos/core#broader",
                "semanticRing": "entity",
                "sourceRelease": release,
                "statementType": "NativeRelationAssertion",
                "subject": "urn:ref:org:epa",
                "targetRelease": release,
            },
        ],
        CompactRecordRole.EVIDENCE_BINDING: [
            {
                "assertionOrigin": "urn:test:origin",
                "attestedAt": "2026-08-07T00:00:00+00:00",
                "attestor": "urn:test:reviewer",
                "attestorKind": "urn:test:attestor-kind",
                "contentDigest": d2,
                "decision": "urn:test:approved",
                "epistemicBasis": "urn:test:basis",
                "evidenceRole": "urn:test:role",
                "evidenceSourceDigest": d1,
                "evidentiaryFunction": "urn:test:function",
                "id": "urn:ref:atlas-evidence:" + "2" * 64,
                "sourceRecord": source_record,
                "statement": statement,
            },
        ],
        CompactRecordRole.SOURCE_RECORD: [
            {
                "contentDigest": d4,
                "id": source_record,
                "nativePayload": {"publisher": "FR"},
                "representsResource": "urn:ref:org:epa",
                "sourceDigest": d3,
                "sourceLocator": "https://example.test/epa",
                "sourceRelease": "urn:test:source-release",
            },
        ],
        CompactRecordRole.RELEASE: [
            {
                "contentDigest": d1,
                "id": release,
                "identifier": "test-agencies",
                "issued": "2026-08-21",
                "membershipMode": "complete",
                "releaseType": "AtlasRelease",
                "resourceProfile": "resourceCollection",
                "scheme": scheme,
                "semanticRing": "entity",
            },
        ],
        CompactRecordRole.IDENTIFIER: [
            {
                "contentDigest": d2,
                "id": "urn:ref:atlas-identifier:" + "8" * 64,
                "identifierScheme": "urn:test:agency-code",
                "identifierValue": "EPA",
                "identifies": "urn:ref:org:epa",
                "sourceRecord": source_record,
            },
        ],
        CompactRecordRole.LIFECYCLE_EVENT: [
            {
                "appliesTo": "urn:ref:org:epa",
                "contentDigest": d3,
                "effectiveDate": "1970-12-02T00:00:00+00:00",
                "fromRelease": "urn:ref:atlas-release:3:test-agencies:1970-01-01",
                "id": "urn:ref:atlas-change-event:epa-established-1970",
                "lifecycleEventKind": "https://refspec.org/ns/atlas/v3#agencyEstablished",
                "sourceRecords": [source_record],
                "toRelease": release,
            },
            {
                "appliesTo": "urn:ref:org:ins",
                "contentDigest": d4,
                "effectiveDate": "2003-03-01T00:00:00+00:00",
                "id": "urn:ref:atlas-change-event:ins-split-2003",
                "lifecycleEventKind": "https://refspec.org/ns/atlas/v3#agencySplit",
                "sourceRecords": [source_record],
                "toRelease": release,
            },
        ],
    }

    staged = base_dir / "staged-tables"
    writer = AtlasParquetTableWriter(staged)
    try:
        for role, rows in records.items():
            for row in rows:
                writer.add(role, normalize_compact_record(role, row))
        writer.close()
    except BaseException:
        writer.__exit__()
        raise

    # Add real REF-038 agency projection table
    src_rec = agency_projection.AgencyProjectionSourceRecord(
        release_key="regulations-gov-agencies-roster-2026-08-16",
        release_digest=d1,
        resource="urn:ref:regs-gov:EPA",
        source_locator="https://example.test/regulations-gov",
        source_digest=d2,
        field="agencyId",
        value="EPA",
        publisher_name="Environmental Protection Agency",
    )
    tgt_rec = agency_projection.AgencyProjectionSourceRecord(
        release_key="federal-register-agencies-roster-2026-08-15",
        release_digest=d3,
        resource="urn:ref:org:epa",
        source_locator="https://example.test/federal-register",
        source_digest=d4,
        field="name",
        value="Environmental Protection Agency",
        publisher_name="Environmental Protection Agency",
    )
    ev_content = {
        "evidence_tier": "E4",
        "warrant": "humanReview",
        "reviewer": "urn:test:reviewer",
        "adjudicated_on": "2026-08-16",
        "decision_record": "docs/decisions.md#ref-038",
        "decision": "approved",
        "decision_basis": "exactPublisherNameEquality",
        "relation": "https://refspec.org/ns/atlas/v3#sameEntityAs",
        "name_similarity_used": False,
        "reasoning": "Exact publisher name match.",
        "source_record": src_rec.to_dict(),
        "target_record": tgt_rec.to_dict(),
    }
    ev_rec = agency_projection.AgencyProjectionEvidenceRecord(
        record_id="urn:ref:agency-projection-evidence:" + agency_projection._digest(ev_content).removeprefix("sha256:"),
        evidence_tier="E4",
        warrant="humanReview",
        reviewer="urn:test:reviewer",
        adjudicated_on="2026-08-16",
        decision_record="docs/decisions.md#ref-038",
        decision="approved",
        decision_basis="exactPublisherNameEquality",
        relation="https://refspec.org/ns/atlas/v3#sameEntityAs",
        name_similarity_used=False,
        reasoning="Exact publisher name match.",
        source_record=src_rec,
        target_record=tgt_rec,
    )
    proj_row = agency_projection.AgencyProjectionRow(
        source_value_kind="regulationsGovAgencyId",
        source_value="EPA",
        org="urn:ref:org:epa",
        pref_label="Environmental Protection Agency",
        abbreviations=("EPA",),
        aliases=("U.S. EPA",),
        parent_org=None,
        relation="https://refspec.org/ns/atlas/v3#sameEntityAs",
        evidence_tier="E4",
        warrant="humanReview",
        basis="exactPublisherNameEquality",
        evidence_records=(ev_rec,),
    )
    coverage = agency_projection.AgencyProjectionCoverage(
        source_value_kind="regulationsGovAgencyId",
        source_value_count=1,
        resolved_value_count=1,
        unresolved_value_count=0,
        basis_counts={"exactPublisherNameEquality": 1},
        unresolved_reason_counts={},
        rows_with_parent_org=0,
        evidence_record_count=1,
    )
    projection = agency_projection.AgencyProjection(
        rows=(proj_row,),
        unresolved=(),
        coverage=coverage,
        digest=agency_projection._digest(
            {"rows": [proj_row.to_dict()], "unresolved": [], "coverage": coverage.to_dict()}
        ),
    )
    write_agency_projection_tables(staged, projection)

    view_root = base_dir / "parquet-view"
    seal_atlas_parquet_view(
        dist_root,
        staged,
        view_root,
        expected_manifest_digest=file_sha256(manifest_path),
        agency_projection={
            "status": "emitted",
            "decision": "REF-038",
            "digest": projection.digest,
            "coverage": projection.coverage.to_dict(),
        },
        derived_relations={"status": "notEmitted"},
    )
    return view_root, file_sha256(view_root / VIEW_MANIFEST_FILE)


def test_build_vocabulary_pack_directly_from_parquet_view_and_ingests_agency_tables(tmp_path: Path) -> None:
    """build_vocabulary_pack compiles directly from parquet-view and serves agency change events + projections."""

    import asyncio

    view_root, view_digest = _build_direct_parquet_view_with_agency_tables(tmp_path)
    pack_path = tmp_path / "direct-pv-pack.sqlite"

    manifest = build_vocabulary_pack(
        view_root,
        pack_path,
        trusted_manifest_digest=view_digest,
        schemes=["urn:ref:atlas-resource-scheme:test-agencies"],
    )
    assert manifest.source_view_kind == "parquet-view"
    assert manifest.resource_count == 1
    assert manifest.agency_change_event_count == 2
    assert manifest.agency_projection_count == 1
    manifest_dict = manifest.to_dict()
    assert manifest_dict["sourceViewKind"] == "parquet-view"
    assert manifest_dict["counts"]["agencyChangeEvents"] == 2
    assert manifest_dict["counts"]["agencyProjections"] == 1

    with AtlasVocabularyPack.open(pack_path, trusted_manifest_digest=view_digest) as pack:
        assert pack.source_view_kind == "parquet-view"
        stats = pack.stats()
        assert stats["sourceViewKind"] == "parquet-view"
        assert stats["counts"]["agencyChangeEvents"] == 2
        assert stats["counts"]["agencyProjections"] == 1

        # Concepts still serve normally
        hits = pack.lookup_sync("Environmental Protection Agency", limit=5)
        assert hits and hits[0]["id"] == "urn:ref:org:epa"

        # Agency change events accessor (ordered by effective_date, event_id)
        all_events = pack.agency_change_events_sync()
        assert [ev["id"] for ev in all_events] == [
            "urn:ref:atlas-change-event:epa-established-1970",
            "urn:ref:atlas-change-event:ins-split-2003",
        ]
        assert all_events[0]["fromRelease"] == "urn:ref:atlas-release:3:test-agencies:1970-01-01"
        assert all_events[1]["fromRelease"] is None

        epa_events = pack.agency_change_events_sync(applies_to="urn:ref:org:epa")
        assert len(epa_events) == 1 and epa_events[0]["id"] == "urn:ref:atlas-change-event:epa-established-1970"

        split_events = pack.agency_change_events_sync(event_kind="https://refspec.org/ns/atlas/v3#agencySplit")
        assert len(split_events) == 1 and split_events[0]["appliesTo"] == "urn:ref:org:ins"

        # Agency projections accessor
        all_proj = pack.agency_projections_sync()
        assert len(all_proj) == 1
        assert all_proj[0]["sourceValueKind"] == "regulationsGovAgencyId"
        assert all_proj[0]["sourceValue"] == "EPA"
        assert all_proj[0]["org"] == "urn:ref:org:epa"
        assert all_proj[0]["abbreviations"] == ["EPA"]
        assert all_proj[0]["aliases"] == ["U.S. EPA"]
        assert all_proj[0]["evidenceRecordCount"] == 1

        by_org = pack.agency_projections_sync(org="urn:ref:org:epa", source_value="EPA")
        assert by_org == all_proj
        assert pack.agency_projections_sync(source_value="NOPE") == []

        # Async wrappers & with_dependencies() preserve optional-table capability flags
        async_events = asyncio.run(pack.agency_change_events(applies_to="urn:ref:org:epa"))
        assert async_events == epa_events
        async_proj = asyncio.run(pack.agency_projections(org="urn:ref:org:epa"))
        assert async_proj == all_proj

        cloned = pack.with_dependencies()
        assert cloned.agency_change_events_sync() == all_events
        assert cloned.agency_projections_sync() == all_proj

        # Invalid filter validation raises VocabularyInputError
        with pytest.raises(VocabularyInputError, match="applies_to"):
            pack.agency_change_events_sync(applies_to="   ")
        with pytest.raises(VocabularyInputError, match="source_value"):
            pack.agency_projections_sync(source_value="")


def test_build_vocabulary_pack_parquet_view_rejects_symlinks_and_ambiguous_manifests(tmp_path: Path) -> None:
    """Direct parquet-view path preserves pre-.resolve() symlink refusal and rejects ambiguous/missing manifests."""

    import shutil

    view_root, view_digest = _build_direct_parquet_view_with_agency_tables(tmp_path)

    # 1. Symlinked view_root directory refused before .resolve()
    link_view = tmp_path / "symlink-view"
    link_view.symlink_to(view_root, target_is_directory=True)
    with pytest.raises(VocabularyPackError, match="must not be a symlink"):
        build_vocabulary_pack(
            link_view,
            tmp_path / "out1.sqlite",
            trusted_manifest_digest=view_digest,
            schemes=["urn:ref:atlas-resource-scheme:test-agencies"],
        )

    # 2. Ambiguous directory holding BOTH view-manifest.json and search-view-manifest.json refused
    ambiguous = tmp_path / "ambiguous-view"
    shutil.copytree(view_root, ambiguous)
    (ambiguous / "search-view-manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(VocabularyPackError, match="ambiguous Atlas view directory"):
        build_vocabulary_pack(
            ambiguous,
            tmp_path / "out2.sqlite",
            trusted_manifest_digest=view_digest,
            schemes=["urn:ref:atlas-resource-scheme:test-agencies"],
        )

    # 3. Empty directory lacking both manifests refused
    empty_view = tmp_path / "empty-view"
    empty_view.mkdir()
    with pytest.raises(VocabularyPackError, match="lacks view-manifest.json or search-view-manifest.json"):
        build_vocabulary_pack(
            empty_view,
            tmp_path / "out3.sqlite",
            trusted_manifest_digest=view_digest,
            schemes=["urn:ref:atlas-resource-scheme:test-agencies"],
        )

    # 4. Symlinked view-manifest.json refused
    sym_manifest_dir = tmp_path / "sym-manifest-view"
    shutil.copytree(view_root, sym_manifest_dir)
    outside_manifest = tmp_path / "outside-view-manifest.json"
    shutil.move(sym_manifest_dir / "view-manifest.json", outside_manifest)
    (sym_manifest_dir / "view-manifest.json").symlink_to(outside_manifest)
    with pytest.raises(VocabularyPackError, match="must not be a symlink"):
        build_vocabulary_pack(
            sym_manifest_dir,
            tmp_path / "out4.sqlite",
            trusted_manifest_digest=view_digest,
            schemes=["urn:ref:atlas-resource-scheme:test-agencies"],
        )


def test_legacy_pack_without_agency_tables_returns_empty_gracefully(tmp_path: Path) -> None:
    """Packs built prior to agency_change_events/agency_projections tables still open and return []."""

    view_root, view_digest = _build_direct_parquet_view_with_agency_tables(tmp_path)
    pack_path = tmp_path / "legacy-no-agency.sqlite"
    build_vocabulary_pack(
        view_root,
        pack_path,
        trusted_manifest_digest=view_digest,
        schemes=["urn:ref:atlas-resource-scheme:test-agencies"],
    )

    con = sqlite3.connect(str(pack_path))
    con.execute("DROP TABLE agency_change_events")
    con.execute("DROP TABLE agency_projections")
    con.execute("DELETE FROM pack_meta WHERE key IN ('agency_change_event_count', 'agency_projection_count', 'source_view_kind')")
    con.commit()
    con.close()

    with AtlasVocabularyPack.open(pack_path, verify_pack_digest=False) as pack:
        assert pack.agency_change_events_sync() == []
        assert pack.agency_projections_sync() == []
        assert pack.stats()["counts"]["agencyChangeEvents"] == 0
        assert pack.stats()["counts"]["agencyProjections"] == 0


def test_hybrid_typo_recovery_with_noisy_dense_hits_and_recommended_min_cosine(tmp_path: Path) -> None:
    """#34/#38 polish: hybrid 'medciare' wins #1 over noisy dense hits, 'embarazo' avoids 'embargo', and recommended_min_cosine applies when lookup_policy is None."""
    view_root, digest = _write_compact_fixture(tmp_path / "view")
    base_pack = tmp_path / "base_p34.sqlite"
    manifest = build_vocabulary_pack(
        view_root,
        base_pack,
        trusted_manifest_digest=digest,
        schemes=(S_EURO, S_FR),
        languages=("en",),
    )

    pack_path = tmp_path / "p34.sqlite"
    pack_path.write_bytes(base_pack.read_bytes())
    con = sqlite3.connect(str(pack_path))
    fr_sid = con.execute("SELECT sid FROM schemes WHERE uri = ?", (S_FR,)).fetchone()[0]
    fr_rel = con.execute("SELECT rel_id FROM releases WHERE uri = ?", (R_FR,)).fetchone()[0]
    euro_rid_1 = int(con.execute("SELECT rid FROM resources WHERE id = 'http://eurovoc.europa.eu/1234'").fetchone()[0])
    euro_rid_2 = int(con.execute("SELECT rid FROM resources WHERE id = 'http://eurovoc.europa.eu/3027'").fetchone()[0])
    medicare_rid = int(con.execute("SELECT rid FROM resources WHERE id = 'urn:ref:fr:medicare'").fetchone()[0])
    assert euro_rid_1 < medicare_rid  # Ensure noisy dense neighbor has LOWER rid than Medicare!
    max_rid = int(con.execute("SELECT max(rid) FROM resources").fetchone()[0])

    # Add "Embargo" (df=3) and "Pregnancy" so we verify hybrid "embarazo" still avoids "embargo" poisoning!
    embargo_rid = max_rid + 1
    pregnancy_rid = max_rid + 2
    for rid, res_id, pref, defn in [
        (embargo_rid, "urn:ref:fr:embargo", "Embargo", "Trade embargo restrictions."),
        (pregnancy_rid, "urn:ref:fr:pregnancy", "Pregnancy", "Maternal pregnancy care."),
    ]:
        norm = normalize_text(pref)
        con.execute(
            "INSERT INTO resources(rid, id, sid, rel_id, definition, src_pfx, src_suffix, notations_json, pref_label, label_count, has_preferred) "
            "VALUES (?, ?, ?, ?, ?, 0, 'src', NULL, ?, 1, 1)",
            (rid, res_id, fr_sid, fr_rel, defn, pref),
        )
        con.execute(
            "INSERT INTO labels(rid, role_rank, value_lower, value, lbl_pfx, lbl_suffix, role, language) "
            "VALUES (?, 0, ?, ?, 0, ?, 'preferred', 'en')",
            (rid, norm, pref, f"urn:ref:atlas-label:p34-{rid}"),
        )
        con.execute("INSERT INTO label_exact(value_lower, role_rank, rid) VALUES (?, 0, ?)", (norm, rid))
        con.execute("INSERT INTO concepts_bm25(rowid, pref_text, alt_text, def_text) VALUES (?, ?, '', ?)", (rid, pref, defn))
        con.execute("INSERT OR REPLACE INTO vocab_terms(term, doc_freq) VALUES (?, 3)", (norm,))
    con.execute("INSERT INTO vocab_terms_trigram(vocab_terms_trigram) VALUES('rebuild')")
    _refresh_pack_blobs(con)
    con.commit()
    con.close()

    class NoisyCalibratedIndex:
        def __init__(self, *, recommended: float | None) -> None:
            self.pack_sha256 = manifest.pack_sha256
            self.pack_id = manifest.pack_id
            self.source_manifest_digest = digest
            self.model_id = "calibrated-m3"
            self.dimensions = 4
            self.recommended_min_cosine = recommended
            self.seen_min_cosines: list[float] = []

        def vector_for_rid(self, rid: int) -> Sequence[float] | None:
            return [0.0, 0.0, 1.0, 0.0] if rid == medicare_rid else None

        def search_rids(
            self,
            query_vector: Sequence[float],
            *,
            top_k: int = 40,
            min_cosine: float = 0.55,
            nprobe: int = 24,
            allowed_rids: Any = None,
            rerank_top_r: int | None = None,
        ) -> list[tuple[int, float]]:
            _ = (top_k, nprobe, allowed_rids, rerank_top_r)
            self.seen_min_cosines.append(min_cosine)
            if query_vector[0] > 0.5:
                # "medciare": noisy dense neighbors (lower rids than Medicare!) plus Medicare at rank #3.
                hits = [(euro_rid_1, 0.86), (euro_rid_2, 0.85), (medicare_rid, 0.83)]
            elif query_vector[1] > 0.5:
                # "embarazo": genuine cross-lingual dense hit "Pregnancy" at 0.88!
                hits = [(pregnancy_rid, 0.88)]
            else:
                # OOD / calibrated floor probe: noisy neighbor at 0.78 (above 0.55, below recommended 0.82!)
                hits = [(euro_rid_1, 0.78)]
            return [(r, s) for r, s in hits if s >= min_cosine]

    class TestEncoder:
        model_id = "calibrated-m3"
        dimensions = 4

        def encode_query(self, text: str) -> Sequence[float]:
            low = text.strip().lower()
            if low == "medciare":
                return [1.0, 0.0, 0.0, 0.0]
            if low == "embarazo":
                return [0.0, 1.0, 0.0, 0.0]
            return [0.0, 0.0, 1.0, 0.0]

    # Wrap calibrated index in PriorGuidedSemanticIndex to verify recommended_min_cosine forwarding too!
    raw_cal = NoisyCalibratedIndex(recommended=0.82)
    guided_cal = PriorGuidedSemanticIndex.from_pack(pack_path, raw_cal, min_oversample=8)
    assert guided_cal.recommended_min_cosine == pytest.approx(0.82)

    with AtlasVocabularyPack.open(
        pack_path,
        semantic_index=guided_cal,
        query_encoder=TestEncoder(),
        verify_pack_digest=False,
    ) as pack:
        # 1. Hybrid "medciare" fuses spelling-corrected lexical hit with dense rank #3 via RRF to win #1!
        typo_meta = pack.lookup_with_meta_sync("medciare", limit=5)
        assert typo_meta["correctedQuery"] == "medicare"
        assert typo_meta["tier"] == "spelling_corrected"
        assert typo_meta["concepts"][0]["id"] == "urn:ref:fr:medicare"

        # 2. Hybrid "embarazo" still recovers dense "Pregnancy" #1 WITHOUT "embargo" poisoning!
        es_meta = pack.lookup_with_meta_sync("embarazo", limit=5)
        assert es_meta["correctedQuery"] is None
        assert es_meta["tier"] == "semantic_hybrid"
        assert [c["label"] for c in es_meta["concepts"]] == ["Pregnancy"]

        # 3. Default lookup_policy=None honors semantic_index.recommended_min_cosine (0.82), rejecting 0.78 OOD hit!
        ood_meta = pack.lookup_with_meta_sync("zxqvblargle", limit=5)
        assert ood_meta["concepts"] == []
        assert raw_cal.seen_min_cosines[-1] == pytest.approx(0.82)

        # LookupPolicy(include_context=True) leaves min_cosine=None and STILL honors recommended_min_cosine (0.82)!
        ctx_pack = pack.with_dependencies(lookup_policy=LookupPolicy(include_context=True), verify_pack_digest=False)
        ctx_ood = ctx_pack.lookup_with_meta_sync("zxqvblargle", limit=5)
        assert ctx_ood["concepts"] == []
        assert raw_cal.seen_min_cosines[-1] == pytest.approx(0.82)

        # similar_sync also honors recommended_min_cosine when lookup_policy=None and min_cosine=None!
        assert pack.similar_sync({"id": "urn:ref:fr:medicare", "scheme": S_FR, "release": R_FR}, limit=5) == []
        assert raw_cal.seen_min_cosines[-1] == pytest.approx(0.82)

        # Per-call explicit min_cosine overrides recommended_min_cosine cleanly!
        low_override = pack.lookup_sync("zxqvblargle", limit=5, min_cosine=0.70)
        assert [c["id"] for c in low_override] == ["http://eurovoc.europa.eu/1234"]
        assert raw_cal.seen_min_cosines[-1] == pytest.approx(0.70)

        # 4. Explicit LookupPolicy(min_cosine=0.55) stays unchanged and does NOT get overridden by 0.82!
        explicit_pack = pack.with_dependencies(lookup_policy=LookupPolicy(min_cosine=0.55), verify_pack_digest=False)
        exp_hits = explicit_pack.lookup_sync("zxqvblargle", limit=5)
        assert [c["id"] for c in exp_hits] == ["http://eurovoc.europa.eu/1234"]
        assert raw_cal.seen_min_cosines[-1] == pytest.approx(0.55)

        # 5. When recommended_min_cosine is None and lookup_policy.min_cosine is None, falls back to DEFAULT_MIN_COSINE (0.55).
        uncal = NoisyCalibratedIndex(recommended=None)
        uncal_pack = pack.with_dependencies(semantic_index=uncal, verify_pack_digest=False)
        uncal_hits = uncal_pack.lookup_sync("zxqvblargle", limit=5)
        assert [c["id"] for c in uncal_hits] == ["http://eurovoc.europa.eu/1234"]
        assert uncal.seen_min_cosines[-1] == pytest.approx(DEFAULT_MIN_COSINE)



def test_connection_pool_50_ephemeral_threads_zero_leak_and_concurrent_close_safety(tmp_path: Path) -> None:
    """P0: 50 sequential ephemeral threads + concurrent bursts stay <= max_idle, and concurrent close() never races."""
    import threading

    view_root, digest = _write_compact_fixture(tmp_path / "view")
    pack_path = tmp_path / "pool_leak.sqlite"
    build_vocabulary_pack(
        view_root,
        pack_path,
        trusted_manifest_digest=digest,
        schemes=(S_EURO, S_FR),
        languages=("en",),
    )

    pack = AtlasVocabularyPack.open(pack_path)
    try:
        # 1. 50 sequential ephemeral threading.Thread calls (simulating ThreadingHTTPServer per-request threads)
        errors: list[BaseException] = []
        worker_excs = (AssertionError, RuntimeError, ValueError, sqlite3.Error, threading.BrokenBarrierError)

        def _ephemeral_call(idx: int) -> None:
            try:
                hits = pack.lookup_sync("Medicare" if idx % 2 == 0 else "computer crime", limit=5)
                assert hits
            except worker_excs as exc:
                errors.append(exc)

        for idx in range(50):
            t = threading.Thread(target=_ephemeral_call, args=(idx,))
            t.start()
            t.join(timeout=10.0)
            assert not t.is_alive()
        assert errors == []
        assert len(pack._pool._idle) <= pack._pool._max_idle
        assert len(pack._pool._idle) == 1
        assert len(pack._pool._in_use) == 0

        # 2. Burst of 24 concurrent threads (> max_idle=16): idle deque still caps at max_idle!
        burst = 24
        barrier = threading.Barrier(burst)

        def _burst_borrow() -> None:
            try:
                with pack._pool.borrow() as con:
                    barrier.wait(timeout=10.0)
                    row = con.execute("SELECT count(*) FROM resources").fetchone()
                    assert row is not None and int(row[0]) > 0
            except worker_excs as exc:
                errors.append(exc)

        burst_threads = [threading.Thread(target=_burst_borrow) for _ in range(burst)]
        for t in burst_threads:
            t.start()
        for t in burst_threads:
            t.join(timeout=10.0)
        assert errors == []
        assert len(pack._pool._idle) <= pack._pool._max_idle
        assert len(pack._pool._in_use) == 0

        # 3. Concurrent close() safety: an in-flight borrow() completes cleanly while close() drains idle conns,
        #    and closes itself upon context exit without crashing mid-query!
        entered = threading.Event()
        release = threading.Event()
        inflight_ok: list[bool] = []

        def _inflight_reader() -> None:
            try:
                with pack._pool.borrow() as con:
                    entered.set()
                    assert release.wait(timeout=10.0)
                    row = con.execute("SELECT count(*) FROM resources").fetchone()
                    assert row is not None and int(row[0]) > 0
                    inflight_ok.append(True)
            except worker_excs as exc:
                errors.append(exc)

        reader = threading.Thread(target=_inflight_reader)
        reader.start()
        assert entered.wait(timeout=10.0)
        assert len(pack._pool._in_use) == 1

        # Close pack while reader holds its borrowed connection!
        pack.close()
        assert len(pack._pool._idle) == 0
        # New callers immediately fail closed with VocabularyPackError("pack_closed", ...)
        with pytest.raises(VocabularyPackError) as exc_closed:
            pack.lookup_sync("Medicare", limit=5)
        assert exc_closed.value.code == "pack_closed"

        # Release the in-flight reader; its query finishes cleanly and closes its connection on exit.
        release.set()
        reader.join(timeout=10.0)
        assert not reader.is_alive()
        assert errors == []
        assert inflight_ok == [True]
        assert len(pack._pool._idle) == 0
        assert len(pack._pool._in_use) == 0
    finally:
        pack.close()


def test_lookup_policy_validation_exact_pinned_rrf_precedence_and_none_label_safety() -> None:
    """P1: LookupPolicy.min_cosine defaults to None + validates, ExactPinnedRRF preserves exact_preferred > exact_alternate, None labels never become 'None'."""
    assert DEFAULT_MIN_COSINE == pytest.approx(0.55)
    assert LookupPolicy().min_cosine is None
    assert LookupPolicy(include_context=True).min_cosine is None
    assert LookupPolicy(min_cosine=0.75).min_cosine == pytest.approx(0.75)

    for bad_min_cos in (float("nan"), float("inf"), -1.1, 1.1, True, "0.5"):
        with pytest.raises(VocabularyInputError) as exc_bad:
            LookupPolicy(min_cosine=bad_min_cos)  # type: ignore[arg-type]
        assert exc_bad.value.code == "invalid_min_cosine"

    # ExactPinnedRRF: exact_preferred (idx=0, higher rid=500) MUST strictly beat exact_alternate (idx=1, lower rid=10)
    # even when exact_alternate also ranks #1 in BOTH dense_hits and lexical_rids!
    rrf = ExactPinnedRRF(k=60.0, lexical_weight=1.0, dense_weight=1.0)
    fused = rrf.fuse(
        exact_rids=[500, 10],
        lexical_rids=[10, 20],
        dense_hits=[(10, 0.99), (20, 0.95), (30, 0.90)],
        limit=5,
    )
    assert fused[:2] == [500, 10]
    assert fused[2] == 20
    assert fused[3] == 30

    # Even with extreme RRF weights (k=1.0, dense_weight=50.0), exact_rids order still holds strictly!
    extreme_rrf = ExactPinnedRRF(k=1.0, lexical_weight=50.0, dense_weight=50.0)
    assert extreme_rrf.fuse(
        exact_rids=[500, 10],
        lexical_rids=[10, 20],
        dense_hits=[(10, 1.0), (20, 0.99)],
        limit=3,
    ) == [500, 10, 20]

    # group_by_identical_label and AuthorityReranker must NEVER coerce label=None to "None"!
    cards = [
        {"id": "c-none-val", "scheme": S_FR, "release": R_FR, "label": None, "definition": None, "sourceRecord": "s1"},
        {"id": "c-literal-none", "scheme": S_EURO, "release": R_EURO, "label": "None", "definition": None, "sourceRecord": "s2"},
    ]
    grouped = group_by_identical_label(cards, limit=5)
    assert [c["id"] for c in grouped] == ["c-none-val", "c-literal-none"]
    assert "counterparts" not in grouped[0]

    reranked = AuthorityReranker().rerank(query="none", candidates=cards, limit=5)
    assert [c["id"] for c in reranked] == ["c-literal-none", "c-none-val"]


def test_hybrid_spelling_no_false_friend_override_authority_reranker_typo_and_empty_tier(tmp_path: Path) -> None:
    """P1: Hybrid Tier-3 does NOT pin false friends into exact_rids; AuthorityReranker gets corrected_query; empty RRF keeps tier='empty'."""
    view_root, digest = _write_compact_fixture(tmp_path / "view")
    base_pack = tmp_path / "base_hybrid_spell.sqlite"
    manifest = build_vocabulary_pack(
        view_root,
        base_pack,
        trusted_manifest_digest=digest,
        schemes=(S_EURO, S_FR, S_LCSH),
        languages=("en",),
    )

    pack_path = tmp_path / "hybrid_spell.sqlite"
    pack_path.write_bytes(base_pack.read_bytes())
    con = sqlite3.connect(str(pack_path))
    fr_sid = con.execute("SELECT sid FROM schemes WHERE uri = ?", (S_FR,)).fetchone()[0]
    fr_rel = con.execute("SELECT rel_id FROM releases WHERE uri = ?", (R_FR,)).fetchone()[0]
    pero_rid = int(con.execute("SELECT rid FROM resources WHERE pref_label = 'Peromyscus maniculatus'").fetchone()[0])
    euro_rid_1 = int(con.execute("SELECT rid FROM resources WHERE id = 'http://eurovoc.europa.eu/1234'").fetchone()[0])
    max_rid = int(con.execute("SELECT max(rid) FROM resources").fetchone()[0])

    # Add "Carpet" (LOWER rid, df=3) and "Folder" (HIGHER rid) — true adversarial alphabetical order
    # to test Spanish "carpeta" -> "carpet" false friend under BOTH ExactPinnedRRF AND AuthorityReranker!
    carpet_rid = max_rid + 1
    folder_rid = max_rid + 2
    for rid, res_id, pref, defn in [
        (carpet_rid, "urn:ref:fr:carpet", "Carpet", "Woven textile floor covering."),
        (folder_rid, "urn:ref:fr:folder", "Folder", "File folder for organizing documents."),
    ]:
        norm = normalize_text(pref)
        con.execute(
            "INSERT INTO resources(rid, id, sid, rel_id, definition, src_pfx, src_suffix, notations_json, pref_label, label_count, has_preferred) "
            "VALUES (?, ?, ?, ?, ?, 0, 'src', NULL, ?, 1, 1)",
            (rid, res_id, fr_sid, fr_rel, defn, pref),
        )
        con.execute(
            "INSERT INTO labels(rid, role_rank, value_lower, value, lbl_pfx, lbl_suffix, role, language) "
            "VALUES (?, 0, ?, ?, 0, ?, 'preferred', 'en')",
            (rid, norm, pref, f"urn:ref:atlas-label:hs-{rid}"),
        )
        con.execute("INSERT INTO label_exact(value_lower, role_rank, rid) VALUES (?, 0, ?)", (norm, rid))
        con.execute("INSERT INTO concepts_bm25(rowid, pref_text, alt_text, def_text) VALUES (?, ?, '', ?)", (rid, pref, defn))
        con.execute("INSERT OR REPLACE INTO vocab_terms(term, doc_freq) VALUES (?, 3)", (norm,))
    con.execute("INSERT INTO vocab_terms_trigram(vocab_terms_trigram) VALUES('rebuild')")
    _refresh_pack_blobs(con)
    con.commit()
    con.close()

    class RecordingFusion(ExactPinnedRRF):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            object.__setattr__(self, "_recorded", [])

        def fuse(
            self,
            *,
            exact_rids: Sequence[int],
            lexical_rids: Sequence[int],
            dense_hits: Sequence[tuple[int, float]],
            limit: int,
        ) -> list[int]:
            self._recorded.append((list(exact_rids), list(lexical_rids), list(dense_hits)))  # type: ignore[attr-defined]
            return super().fuse(
                exact_rids=exact_rids,
                lexical_rids=lexical_rids,
                dense_hits=dense_hits,
                limit=limit,
            )

    class HybridSpellIndex:
        pack_sha256 = manifest.pack_sha256
        pack_id = manifest.pack_id
        source_manifest_digest = digest
        model_id = "hybrid-spell-m3"
        dimensions = 4
        recommended_min_cosine = 0.55

        def vector_for_rid(self, rid: int) -> Any | None:
            _ = rid
            return None

        def search_rids(
            self,
            query_vector: Sequence[float],
            *,
            top_k: int = 40,
            min_cosine: float = 0.55,
            nprobe: int = 24,
            allowed_rids: Any = None,
            rerank_top_r: int | None = None,
        ) -> list[tuple[int, float]]:
            _ = (top_k, nprobe, allowed_rids, rerank_top_r)
            if query_vector[0] > 0.5:
                # Spanish "carpeta" -> semantic hit "Folder" at rank #1 (NO "Carpet")
                hits = [(folder_rid, 0.90)]
            elif query_vector[1] > 0.5:
                # "peromyscus maniculatuz": noisy lower-rid dense hit without Peromyscus maniculatus!
                hits = [(euro_rid_1, 0.85)]
            else:
                # Low-cosine hit that passes search_rids(0.55) but gets filtered by ExactPinnedRRF(min_cosine=0.90)
                hits = [(euro_rid_1, 0.65)]
            return [(r, s) for r, s in hits if s >= min_cosine]

    class HybridSpellEncoder:
        model_id = "hybrid-spell-m3"
        dimensions = 4

        def encode_query(self, text: str) -> Sequence[float]:
            low = text.strip().lower()
            if low == "carpeta":
                return [1.0, 0.0, 0.0, 0.0]
            if "peromyscus" in low:
                return [0.0, 1.0, 0.0, 0.0]
            return [0.0, 0.0, 1.0, 0.0]

    rec_fusion = RecordingFusion()
    with AtlasVocabularyPack.open(
        pack_path,
        semantic_index=HybridSpellIndex(),
        query_encoder=HybridSpellEncoder(),
        rank_fusion=rec_fusion,
        verify_pack_digest=False,
    ) as pack:
        # 1. Hybrid "carpeta": spelling hit "Carpet" (LOWER rid!) MUST go into lexical_rids (NOT exact_rids!),
        #    and dense "Folder" MUST win rank #1 under BOTH default ExactPinnedRRF AND AuthorityReranker!
        assert carpet_rid < folder_rid
        es_meta = pack.lookup_with_meta_sync("carpeta", limit=5, include_context=True)
        last_exact, last_lex, last_dense = rec_fusion._recorded[-1]  # type: ignore[attr-defined]
        assert last_exact == []
        assert carpet_rid in last_lex
        assert last_dense == [(folder_rid, 0.90)]
        assert es_meta["concepts"][0]["id"] == "urn:ref:fr:folder"
        carpet_card = next(c for c in es_meta["concepts"] if c["id"] == "urn:ref:fr:carpet")
        assert carpet_card["matchReason"] == "spelling_corrected"

        rerank_pack = pack.with_dependencies(candidate_reranker=AuthorityReranker(), verify_pack_digest=False)
        es_reranked = rerank_pack.lookup_with_meta_sync("carpeta", limit=5, include_context=True)
        assert es_reranked["concepts"][0]["id"] == "urn:ref:fr:folder"

        # 2. Pure lexical (dense_hits empty) still pins exact spelling hit into exact_rids with matchReason="spelling_corrected".
        lex_only = pack.with_dependencies(semantic_index=None, query_encoder=None, verify_pack_digest=False)
        lex_carp = lex_only.lookup_with_meta_sync("carpeta", limit=5, include_context=True)
        assert lex_carp["tier"] == "spelling_corrected"
        assert lex_carp["concepts"][0]["id"] == "urn:ref:fr:carpet"
        assert lex_carp["concepts"][0]["matchReason"] == "spelling_corrected"

        # 3. F7: Hybrid multi-token typo "peromyscus maniculatuz" with AuthorityReranker MUST pass corrected_query
        #    ("peromyscus maniculatus") to rerank() so "Peromyscus maniculatus" beats noisy lower-rid dense hit!
        pero_meta = rerank_pack.lookup_with_meta_sync("peromyscus maniculatuz", limit=5)
        assert pero_meta["correctedQuery"] == "peromyscus maniculatus"
        assert pero_meta["concepts"][0]["id"] == "http://id.loc.gov/authorities/subjects/sh_overflow"
        assert pero_meta["concepts"][0]["label"] == "Peromyscus maniculatus"
        assert pero_rid > euro_rid_1

        # 3b. LookupPolicy rejects invalid nprobe / label_limit with VocabularyInputError.
        for bad_kwargs in ({"nprobe": 0}, {"nprobe": True}, {"label_limit": 0}, {"label_limit": False}):
            with pytest.raises(VocabularyInputError):
                LookupPolicy(**bad_kwargs)

        # 4. If RRF filters out all dense hits so final_rids is empty, winning_tier stays "empty" (NOT "semantic_hybrid")!
        strict_rrf_pack = pack.with_dependencies(
            rank_fusion=ExactPinnedRRF(min_cosine=0.90),
            verify_pack_digest=False,
        )
        empty_meta = strict_rrf_pack.lookup_with_meta_sync("zxqvblargle", limit=5)
        assert empty_meta["concepts"] == []
        assert empty_meta["tier"] == "empty"


def test_narrower_cycle_quarantine_deterministic_related_order_and_scoped_member_paths(tmp_path: Path) -> None:
    """P1: Quarantine skos:narrower cycles, deterministic pid/rule_id so related(limit=1)==related(limit=10)[0], scoped member path checks."""
    view_root, _orig_digest = _write_compact_fixture(tmp_path / "view", include_derived=False)
    res_path = view_root / "tables/resources.parquet"
    lbl_path = view_root / "tables/labels.parquet"
    stm_path = view_root / "tables/statements.parquet"

    res_rows = pq.read_table(res_path).to_pylist()
    lbl_rows = pq.read_table(lbl_path).to_pylist()
    stm_rows = pq.read_table(stm_path).to_pylist()

    for suffix, label_val in [
        ("nar-15046", "Narrower Cycle Alpha"),
        ("nar-15125", "Narrower Cycle Beta"),
        ("nar-root", "Narrower Acyclic Root"),
        ("rel-seed", "Order Seed Concept"),
        ("rel-broader", "Order Broader Target"),
        ("rel-related", "Order Related Target"),
    ]:
        res_rows.append(
            {
                "id": f"urn:ref:fr:{suffix}",
                "release": R_FR,
                "scheme": S_FR,
                "semantic_ring": "subject",
                "resource_profile": "Concept",
                "source_record": "urn:ref:atlas-source-record:" + "8" * 64,
                "definition": None,
                "notes": [],
                "notations": [],
                "record_status": "active",
            }
        )
        lbl_rows.append(
            {
                "id": f"urn:ref:atlas-label:fr-{suffix}",
                "resource": f"urn:ref:fr:{suffix}",
                "label_role": "preferred",
                "value": label_val,
                "language": "en",
                "release": R_FR,
                "source_record": "urn:ref:atlas-source-record:" + "8" * 64,
            }
        )

    def _mk_stmt(sid: str, subj: str, pred: str, obj: str) -> dict[str, Any]:
        return {
            "id": sid,
            "statement_type": "NativeRelationAssertion",
            "subject": subj,
            "predicate": pred,
            "object": obj,
            "source_release": R_FR,
            "target_release": R_FR,
            "policy": "urn:ref:atlas-policy:" + "0" * 64,
            "asserted_at": "2026-08-15T00:00:00Z",
            "semantic_ring": "subject",
            "source_ring": "subject",
            "target_ring": "subject",
            "supersedes_assertion": None,
        }

    # Put skos:related FIRST in Parquet before skos:broader to prove deterministic pre-populated pid ordering!
    # Mix uncompressed stmt_pfx=0 ("urn:zzz:ord-brd-z") with compressed stmt_pfx=2 ("urn:ref:atlas-assertion:ord-brd")
    # on the same predicate to verify related_sync(limit=1) == related_sync(limit=10)[0] across prefix classes!
    # Also add GEMET-style 2-node skos:narrower cycle (15046 <-> 15125) + acyclic narrower edge (root -> 15046).
    stm_rows = [
        _mk_stmt("urn:ref:atlas-assertion:ord-rel", "urn:ref:fr:rel-seed", SKOS + "related", "urn:ref:fr:rel-related"),
        _mk_stmt("urn:zzz:ord-brd-z", "urn:ref:fr:rel-seed", SKOS + "broader", "urn:ref:fr:rel-related"),
        _mk_stmt("urn:ref:atlas-assertion:ord-brd", "urn:ref:fr:rel-seed", SKOS + "broader", "urn:ref:fr:rel-broader"),
        _mk_stmt("urn:ref:atlas-assertion:nar-cyc-1", "urn:ref:fr:nar-15046", SKOS + "narrower", "urn:ref:fr:nar-15125"),
        _mk_stmt("urn:ref:atlas-assertion:nar-cyc-2", "urn:ref:fr:nar-15125", SKOS + "narrower", "urn:ref:fr:nar-15046"),
        _mk_stmt("urn:ref:atlas-assertion:nar-acyc", "urn:ref:fr:nar-root", SKOS + "narrower", "urn:ref:fr:nar-15046"),
        *stm_rows,
    ]
    pq.write_table(pa.Table.from_pylist(res_rows, schema=_SCHEMAS[CompactRecordRole.RESOURCE]), res_path)
    pq.write_table(pa.Table.from_pylist(lbl_rows, schema=_SCHEMAS[CompactRecordRole.LABEL]), lbl_path)
    pq.write_table(pa.Table.from_pylist(stm_rows, schema=_SCHEMAS[CompactRecordRole.STATEMENT]), stm_path)

    # Also add derived relations with unsorted rule URIs ("z" before "a") to verify deterministic sorted rule_id!
    drv_rows = [
        {
            "id": "urn:ref:atlas-derived:rule-z",
            "subject": "urn:ref:fr:medicare",
            "predicate": SKOS + "related",
            "object": "urn:ref:fr:housing",
            "semantic_ring": "subject",
            "derivation_rule": "urn:ref:rule:z-rule",
            "engine": "refspec",
            "engine_version": "0.1",
            "derived_from_assertions": [],
            "input_digest": _hex32(9),
            "generated_at": "2026-08-15T00:00:00Z",
            "content_digest": _hex32(10),
        },
        {
            "id": "urn:ref:atlas-derived:rule-a",
            "subject": "urn:ref:fr:flood-insurance",
            "predicate": SKOS + "related",
            "object": "urn:ref:fr:housing",
            "semantic_ring": "subject",
            "derivation_rule": "urn:ref:rule:a-rule",
            "engine": "refspec",
            "engine_version": "0.1",
            "derived_from_assertions": [],
            "input_digest": _hex32(11),
            "generated_at": "2026-08-15T00:00:00Z",
            "content_digest": _hex32(12),
        },
    ]
    drv_path = view_root / "tables/derived-relations.parquet"
    pq.write_table(pa.Table.from_pylist(drv_rows, schema=DERIVED_RELATION_TABLE_SCHEMA), drv_path)

    mpath = view_root / MANIFEST_FILE
    manifest_doc = json.loads(mpath.read_text(encoding="utf-8"))
    manifest_doc["members"].append(
        {
            "byteLength": drv_path.stat().st_size,
            "mediaType": "application/vnd.apache.parquet",
            "path": "tables/derived-relations.parquet",
            "role": DERIVED_RELATION_ROLE,
            "rowCount": len(drv_rows),
            "schemaDigest": arrow_schema_sha256(pq.ParquetFile(drv_path).schema_arrow),
            "sha256": file_sha256(drv_path),
        }
    )
    manifest_doc["counts"][DERIVED_RELATION_ROLE] = len(drv_rows)
    for member in manifest_doc["members"]:
        mp = view_root / member["path"]
        member["byteLength"] = mp.stat().st_size
        member["sha256"] = file_sha256(mp)
        if member["role"] == "Resource":
            member["rowCount"] = len(res_rows)
            manifest_doc["counts"]["Resource"] = len(res_rows)
        elif member["role"] == "Label":
            member["rowCount"] = len(lbl_rows)
            manifest_doc["counts"]["Label"] = len(lbl_rows)
        elif member["role"] == "Statement":
            member["rowCount"] = len(stm_rows)
            manifest_doc["counts"]["Statement"] = len(stm_rows)
    manifest_doc.pop("canonicalPayloadDigest", None)
    manifest_doc["canonicalPayloadDigest"] = canonical_payload_sha256(manifest_doc)
    mpath.write_bytes(canonical_json_bytes(manifest_doc))
    new_digest = file_sha256(mpath)

    pack_path = tmp_path / "narrower_det.sqlite"
    man = build_vocabulary_pack(
        view_root,
        pack_path,
        trusted_manifest_digest=new_digest,
        schemes=(S_FR,),
        languages=("en",),
        include_mappings=True,
        include_derived=True,
    )
    assert man.narrower_cycle_count == 1
    assert man.quarantined_narrower_cycle_edges == 2
    assert man.quarantined_cycle_edges == 2
    assert man.broader_cycle_count == 0

    con = sqlite3.connect(str(pack_path))
    meta = dict(con.execute("SELECT key, value FROM pack_meta").fetchall())
    assert meta["narrower_cycle_count"] == "1"
    assert meta["quarantined_narrower_cycle_edges"] == "2"
    assert meta["quarantined_cycle_edges"] == "2"

    # Verify deterministic sorted pid ordering (broader < narrower < related) and sorted rule_id ordering (a-rule < z-rule)!
    native_preds = con.execute(
        "SELECT pid, uri FROM predicates WHERE stmt_type = 'NativeRelationAssertion' ORDER BY pid"
    ).fetchall()
    assert [uri for _, uri in native_preds] == sorted(uri for _, uri in native_preds)
    rules = con.execute("SELECT rule_id, uri FROM derivation_rules WHERE rule_id > 0 ORDER BY rule_id").fetchall()
    assert [uri for _, uri in rules] == ["urn:ref:rule:a-rule", "urn:ref:rule:z-rule"]

    # Acyclic narrower edge (root -> 15046) survived; 15046 <-> 15125 cycle edges quarantined!
    r_root = int(con.execute("SELECT rid FROM resources WHERE id = 'urn:ref:fr:nar-root'").fetchone()[0])
    r_15046 = int(con.execute("SELECT rid FROM resources WHERE id = 'urn:ref:fr:nar-15046'").fetchone()[0])
    r_15125 = int(con.execute("SELECT rid FROM resources WHERE id = 'urn:ref:fr:nar-15125'").fetchone()[0])
    assert con.execute("SELECT count(*) FROM edges WHERE src_rid = ? AND dst_rid = ?", (r_root, r_15046)).fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM edges WHERE src_rid = ? AND dst_rid = ?", (r_15046, r_15125)).fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM edges WHERE src_rid = ? AND dst_rid = ?", (r_15125, r_15046)).fetchone()[0] == 0
    con.close()

    with AtlasVocabularyPack.open(pack_path) as pack:
        stats = pack.stats()
        assert stats["counts"]["narrowerCycles"] == 1
        assert stats["counts"]["quarantinedNarrowerCycleEdges"] == 2
        seed_ref = {"id": "urn:ref:fr:rel-seed", "scheme": S_FR, "release": R_FR}
        top1 = pack.related_sync(seed_ref, limit=1)
        top10 = pack.related_sync(seed_ref, limit=10)
        assert len(top1) == 1 and len(top10) == 3
        assert top1[0] == top10[0]
        assert top1[0]["relation"]["type"] == SKOS + "broader"
        assert [row["relation"]["id"] for row in top10] == [
            "urn:ref:atlas-assertion:ord-brd",
            "urn:zzz:ord-brd-z",
            "urn:ref:atlas-assertion:ord-rel",
        ]

    # Opt-out quarantine_broader_cycles=False keeps narrower cycle edges while still reporting narrower_cycle_count=1.
    pack_unq = tmp_path / "narrower_unq.sqlite"
    man_unq = build_vocabulary_pack(
        view_root,
        pack_unq,
        trusted_manifest_digest=new_digest,
        schemes=(S_FR,),
        languages=("en",),
        quarantine_broader_cycles=False,
    )
    assert man_unq.narrower_cycle_count == 1
    assert man_unq.quarantined_narrower_cycle_edges == 0

    # F12.1: Scoped member path checks skip EvidenceBinding, derivedRelations, and unselected roles when disabled!
    # 1. Corrupting unselected member files passes scoped verification + build when those features are off.
    (view_root / "tables/evidence-bindings.parquet").write_bytes(b"corrupted-unread-evidence")
    (view_root / "tables/derived-relations.parquet").write_bytes(b"corrupted-unread-derived")
    (view_root / "tables/source-records.parquet").write_bytes(b"corrupted-unread-sources")
    scoped_pack = tmp_path / "scoped_members.sqlite"
    man_scoped = build_vocabulary_pack(
        view_root,
        scoped_pack,
        trusted_manifest_digest=new_digest,
        schemes=(S_FR,),
        languages=("en",),
        include_mappings=False,
        include_derived=False,
        include_agency_tables=False,
    )
    assert man_scoped.resource_count > 0

    # 2. Custom verifier exposing unsafe paths ONLY for disabled roles succeeds when disabled and fails when enabled!
    def _unsafe_optional_verifier(_root: Path, *, expected_manifest_digest: str, roles: Any = None) -> dict[str, Any]:
        _ = (expected_manifest_digest, roles)
        doc = json.loads(mpath.read_text(encoding="utf-8"))
        for member in doc["members"]:
            if member["role"] in ("EvidenceBinding", "derivedRelations", "SourceRecord"):
                member["path"] = "../outside-traversal.parquet"
        return doc

    man_scoped_2 = build_vocabulary_pack(
        view_root,
        tmp_path / "scoped_members_2.sqlite",
        trusted_manifest_digest=new_digest,
        schemes=(S_FR,),
        languages=("en",),
        include_mappings=False,
        include_derived=False,
        include_agency_tables=False,
        view_verifier=_unsafe_optional_verifier,
    )
    assert man_scoped_2.resource_count > 0

    with pytest.raises(VocabularyPackError, match="unsafe"):
        build_vocabulary_pack(
            view_root,
            tmp_path / "scoped_members_fail.sqlite",
            trusted_manifest_digest=new_digest,
            schemes=(S_FR,),
            languages=("en",),
            include_mappings=True,
            include_derived=False,
            include_agency_tables=False,
            view_verifier=_unsafe_optional_verifier,
        )


def test_subject_only_pack_does_not_leak_agency_tables_and_explicit_overrides(tmp_path: Path) -> None:
    """P1: Subject-only packs default include_agency_tables=False (no agency leak), while entity/all/explicit True include them."""
    import hashlib

    from refspec.atlas import agency_projection
    from refspec.atlas.compact_pack import CompactRecordRole, normalize_compact_record
    from refspec.atlas.parquet_artifact import canonical_payload_sha256, file_sha256
    from refspec.atlas.parquet_tables import AtlasParquetTableWriter, write_agency_projection_tables
    from refspec.atlas.parquet_view import MANIFEST_FILE as VIEW_MANIFEST_FILE
    from refspec.atlas.parquet_view import seal_atlas_parquet_view
    from refspec.release_model import canonical_json_bytes

    dist_root = tmp_path / "distribution"
    (dist_root / "packs" / "sources").mkdir(parents=True)
    d1, d2, d3, d4 = ("sha256:" + c * 64 for c in ("1", "2", "3", "4"))
    dist_id = "urn:ref:atlas-distribution:3:bounded:2026-08-21:mixed-rings"
    created_at = "2026-08-21T00:00:00+00:00"

    pack_file = dist_root / "packs" / "sources" / "sample.nq.zst"
    pack_bytes = b"mixed-rings-pack\n"
    pack_file.write_bytes(pack_bytes)
    content_digest = "sha256:" + hashlib.sha256(pack_bytes).hexdigest()
    pack_id = "urn:ref:atlas:pack:" + content_digest.removeprefix("sha256:")
    asserted_inv = [{"contentDigest": content_digest, "packId": pack_id, "quadCount": 1}]
    asserted_inv_digest = canonical_payload_sha256(asserted_inv)
    empty_inv_digest = canonical_payload_sha256([])
    contract_digest = "sha256:" + "a" * 64

    summary: dict[str, Any] = {
        "assertedInventoryDigest": asserted_inv_digest,
        "contractDigest": contract_digest,
        "distributionId": dist_id,
        "type": "AtlasConstructionSummary",
        "version": "3.1",
    }
    summary["canonicalPayloadDigest"] = canonical_payload_sha256(summary)
    summary_path = dist_root / "atlas-construction-summary.json"
    summary_path.write_bytes(canonical_json_bytes(summary) + b"\n")

    manifest: dict[str, Any] = {
        "binding": {"contractDigest": contract_digest, "ontologyDigest": "sha256:" + "b" * 64},
        "counts": {},
        "createdAt": created_at,
        "distributionId": dist_id,
        "format": "refspec-atlas-packed-nquads-3.1",
        "graphs": [
            {"id": "urn:ref:graph:asserted", "inventoryDigest": asserted_inv_digest, "packCount": 1, "quadCount": 1, "role": "asserted"},
            {"id": "urn:ref:graph:projection", "inventoryDigest": empty_inv_digest, "packCount": 0, "quadCount": 0, "role": "projection"},
            {"id": "urn:ref:graph:derived", "inventoryDigest": empty_inv_digest, "packCount": 0, "quadCount": 0, "role": "derived"},
        ],
        "members": [
            {
                "byteLength": summary_path.stat().st_size,
                "digest": file_sha256(summary_path),
                "mediaType": "application/json",
                "path": "atlas-construction-summary.json",
                "role": "constructionSummary",
            }
        ],
        "packs": [
            {
                "content": {"byteLength": len(pack_bytes), "digest": content_digest},
                "graphCounts": {"asserted": 1, "derived": 0, "projection": 0},
                "packId": pack_id,
                "path": "packs/sources/sample.nq.zst",
                "transport": {"byteLength": len(pack_bytes), "digest": file_sha256(pack_file)},
            }
        ],
        "schemaVersion": "3.1",
        "type": "AtlasManifest",
    }
    manifest["canonicalPayloadDigest"] = canonical_payload_sha256(manifest)
    manifest_path = dist_root / "atlas-manifest.json"
    manifest_path.write_bytes(canonical_json_bytes(manifest) + b"\n")

    s_agencies = "urn:ref:atlas-resource-scheme:test-agencies"
    r_agencies = "urn:ref:atlas-release:3:test-agencies:2026-08-21"
    src_ag = "urn:ref:atlas-source-record:" + "5" * 64
    src_eu = "urn:ref:atlas-source-record:" + "6" * 64

    records = {
        CompactRecordRole.RESOURCE: [
            {
                "contentDigest": d1,
                "definition": "United States Environmental Protection Agency",
                "id": "urn:ref:org:epa",
                "notations": ["EPA"],
                "notes": [],
                "recordStatus": "active",
                "release": r_agencies,
                "resourceProfile": "resourceCollection",
                "scheme": s_agencies,
                "semanticRing": "entity",
                "sourceRecord": src_ag,
            },
            {
                "contentDigest": d2,
                "definition": "European trade concept.",
                "id": "http://eurovoc.europa.eu/1001",
                "notations": ["1001"],
                "notes": [],
                "recordStatus": "active",
                "release": R_EURO,
                "resourceProfile": "conceptScheme",
                "scheme": S_EURO,
                "semanticRing": "subject",
                "sourceRecord": src_eu,
            },
        ],
        CompactRecordRole.LABEL: [
            {
                "contentDigest": d1,
                "id": "urn:ref:atlas-label:" + "7" * 64,
                "labelRole": "preferred",
                "language": "en",
                "release": r_agencies,
                "resource": "urn:ref:org:epa",
                "sourceRecord": src_ag,
                "value": "Environmental Protection Agency",
            },
            {
                "contentDigest": d2,
                "id": "urn:ref:atlas-label:" + "8" * 64,
                "labelRole": "preferred",
                "language": "en",
                "release": R_EURO,
                "resource": "http://eurovoc.europa.eu/1001",
                "sourceRecord": src_eu,
                "value": "international trade",
            },
        ],
        CompactRecordRole.STATEMENT: [],
        CompactRecordRole.EVIDENCE_BINDING: [],
        CompactRecordRole.SOURCE_RECORD: [
            {
                "contentDigest": d3,
                "id": src_ag,
                "nativePayload": {"publisher": "FR"},
                "representsResource": "urn:ref:org:epa",
                "sourceDigest": d3,
                "sourceLocator": "https://example.test/epa",
                "sourceRelease": "urn:test:source-release",
            },
            {
                "contentDigest": d4,
                "id": src_eu,
                "nativePayload": {"publisher": "EU"},
                "representsResource": "http://eurovoc.europa.eu/1001",
                "sourceDigest": d4,
                "sourceLocator": "https://example.test/eu",
                "sourceRelease": "urn:test:source-release",
            },
        ],
        CompactRecordRole.RELEASE: [
            {
                "contentDigest": d1,
                "id": r_agencies,
                "identifier": "test-agencies",
                "issued": "2026-08-21",
                "membershipMode": "complete",
                "releaseType": "AtlasRelease",
                "resourceProfile": "resourceCollection",
                "scheme": s_agencies,
                "semanticRing": "entity",
            },
            {
                "contentDigest": d2,
                "id": R_EURO,
                "identifier": "eurovoc",
                "issued": "2026-08-21",
                "membershipMode": "complete",
                "releaseType": "AtlasRelease",
                "resourceProfile": "conceptScheme",
                "scheme": S_EURO,
                "semanticRing": "subject",
            },
        ],
        CompactRecordRole.IDENTIFIER: [],
        CompactRecordRole.LIFECYCLE_EVENT: [
            {
                "appliesTo": "urn:ref:org:epa",
                "contentDigest": d3,
                "effectiveDate": "1970-12-02T00:00:00+00:00",
                "id": "urn:ref:atlas-change-event:epa-est",
                "lifecycleEventKind": "https://refspec.org/ns/atlas/v3#agencyEstablished",
                "sourceRecords": [src_ag],
                "toRelease": r_agencies,
            }
        ],
    }

    staged = tmp_path / "staged-mixed"
    writer = AtlasParquetTableWriter(staged)
    try:
        for role, rows in records.items():
            for row in rows:
                writer.add(role, normalize_compact_record(role, row))
        writer.close()
    except BaseException:
        writer.__exit__()
        raise

    src_rec = agency_projection.AgencyProjectionSourceRecord(
        release_key="regs-gov-2026",
        release_digest=d1,
        resource="urn:ref:regs-gov:EPA",
        source_locator="https://example.test/regs",
        source_digest=d2,
        field="agencyId",
        value="EPA",
        publisher_name="Environmental Protection Agency",
    )
    tgt_rec = agency_projection.AgencyProjectionSourceRecord(
        release_key="fr-agencies-2026",
        release_digest=d3,
        resource="urn:ref:org:epa",
        source_locator="https://example.test/fr",
        source_digest=d4,
        field="name",
        value="Environmental Protection Agency",
        publisher_name="Environmental Protection Agency",
    )
    ev_content = {
        "evidence_tier": "E4",
        "warrant": "humanReview",
        "reviewer": "urn:test:reviewer",
        "adjudicated_on": "2026-08-16",
        "decision_record": "docs/decisions.md#ref-038",
        "decision": "approved",
        "decision_basis": "exactPublisherNameEquality",
        "relation": "https://refspec.org/ns/atlas/v3#sameEntityAs",
        "name_similarity_used": False,
        "reasoning": "Exact publisher name match.",
        "source_record": src_rec.to_dict(),
        "target_record": tgt_rec.to_dict(),
    }
    ev_rec = agency_projection.AgencyProjectionEvidenceRecord(
        record_id="urn:ref:agency-projection-evidence:" + agency_projection._digest(ev_content).removeprefix("sha256:"),
        evidence_tier="E4",
        warrant="humanReview",
        reviewer="urn:test:reviewer",
        adjudicated_on="2026-08-16",
        decision_record="docs/decisions.md#ref-038",
        decision="approved",
        decision_basis="exactPublisherNameEquality",
        relation="https://refspec.org/ns/atlas/v3#sameEntityAs",
        name_similarity_used=False,
        reasoning="Exact publisher name match.",
        source_record=src_rec,
        target_record=tgt_rec,
    )
    proj_row = agency_projection.AgencyProjectionRow(
        source_value_kind="regulationsGovAgencyId",
        source_value="EPA",
        org="urn:ref:org:epa",
        pref_label="Environmental Protection Agency",
        abbreviations=("EPA",),
        aliases=("U.S. EPA",),
        parent_org=None,
        relation="https://refspec.org/ns/atlas/v3#sameEntityAs",
        evidence_tier="E4",
        warrant="humanReview",
        basis="exactPublisherNameEquality",
        evidence_records=(ev_rec,),
    )
    coverage = agency_projection.AgencyProjectionCoverage(
        source_value_kind="regulationsGovAgencyId",
        source_value_count=1,
        resolved_value_count=1,
        unresolved_value_count=0,
        basis_counts={"exactPublisherNameEquality": 1},
        unresolved_reason_counts={},
        rows_with_parent_org=0,
        evidence_record_count=1,
    )
    projection = agency_projection.AgencyProjection(
        rows=(proj_row,),
        unresolved=(),
        coverage=coverage,
        digest=agency_projection._digest(
            {"rows": [proj_row.to_dict()], "unresolved": [], "coverage": coverage.to_dict()}
        ),
    )
    write_agency_projection_tables(staged, projection)

    view_root = tmp_path / "parquet-view-mixed"
    seal_atlas_parquet_view(
        dist_root,
        staged,
        view_root,
        expected_manifest_digest=file_sha256(manifest_path),
        agency_projection={
            "status": "emitted",
            "decision": "REF-038",
            "digest": projection.digest,
            "coverage": projection.coverage.to_dict(),
        },
        derived_relations={"status": "notEmitted"},
    )
    view_digest = file_sha256(view_root / VIEW_MANIFEST_FILE)

    # 1. Subject-only EuroVoc pack (default include_agency_tables=None) MUST NOT leak agency projections/events!
    subj_pack = tmp_path / "eurovoc-only.sqlite"
    subj_man = build_vocabulary_pack(
        view_root,
        subj_pack,
        trusted_manifest_digest=view_digest,
        schemes=[S_EURO],
    )
    assert subj_man.resource_count == 1
    assert subj_man.agency_change_event_count == 0
    assert subj_man.agency_projection_count == 0
    with AtlasVocabularyPack.open(subj_pack) as pack:
        assert pack.agency_change_events_sync() == []
        assert pack.agency_projections_sync() == []

    # 2. Explicit include_agency_tables=True on subject-only pack includes them when requested.
    subj_optin = tmp_path / "eurovoc-with-agency.sqlite"
    optin_man = build_vocabulary_pack(
        view_root,
        subj_optin,
        trusted_manifest_digest=view_digest,
        schemes=[S_EURO],
        include_agency_tables=True,
    )
    assert optin_man.agency_change_event_count == 1
    assert optin_man.agency_projection_count == 1

    # 3. Entity pack with explicit include_agency_tables=False omits them cleanly.
    ent_optout = tmp_path / "entity-no-agency.sqlite"
    optout_man = build_vocabulary_pack(
        view_root,
        ent_optout,
        trusted_manifest_digest=view_digest,
        schemes=[s_agencies],
        include_agency_tables=False,
    )
    assert optout_man.resource_count == 1
    assert optout_man.agency_change_event_count == 0
    assert optout_man.agency_projection_count == 0

    # 4. schemes=None (full view) defaults include_agency_tables=True and includes all schemes + agency tables.
    full_pack = tmp_path / "full-all.sqlite"
    full_man = build_vocabulary_pack(
        view_root,
        full_pack,
        trusted_manifest_digest=view_digest,
        schemes=None,
    )
    assert full_man.resource_count == 2
    assert set(full_man.schemes) == {S_EURO, s_agencies}
    assert full_man.agency_change_event_count == 1
    assert full_man.agency_projection_count == 1


def test_expand_sync_over_999_nodes_chunking_dangling_dst_rid_error_and_protocol_cli_sync(tmp_path: Path) -> None:
    """P2: expand_sync(max_nodes=1024) chunks SQLite IN binds <=400; dangling dst_rid raises VocabularyPackError; protocol & CLI sync."""
    import inspect

    from refspec.atlas.vocabulary_pack_cli import _build_parser

    view_root, digest = _write_compact_fixture(tmp_path / "view")
    base_pack = tmp_path / "base_p2.sqlite"
    build_vocabulary_pack(
        view_root,
        base_pack,
        trusted_manifest_digest=digest,
        schemes=(S_EURO, S_FR),
        languages=("en",),
    )

    # 1. Inject 1010 neighbor concepts linked from Medicare so expand_sync(max_nodes=1024) exceeds SQLite's 999 bind limit!
    big_pack = tmp_path / "big_expand.sqlite"
    big_pack.write_bytes(base_pack.read_bytes())
    con = sqlite3.connect(str(big_pack))
    fr_sid = int(con.execute("SELECT sid FROM schemes WHERE uri = ?", (S_FR,)).fetchone()[0])
    fr_rel = int(con.execute("SELECT rel_id FROM releases WHERE uri = ?", (R_FR,)).fetchone()[0])
    med_rid = int(con.execute("SELECT rid FROM resources WHERE id = 'urn:ref:fr:medicare'").fetchone()[0])
    rel_pid = int(
        con.execute(
            "SELECT pid FROM predicates WHERE uri = ? AND stmt_type = 'NativeRelationAssertion'",
            (SKOS + "related",),
        ).fetchone()[0]
    )
    brd_pid = int(
        con.execute(
            "SELECT pid FROM predicates WHERE uri = ? AND stmt_type = 'NativeRelationAssertion'",
            (SKOS + "broader",),
        ).fetchone()[0]
    )
    max_rid = int(con.execute("SELECT max(rid) FROM resources").fetchone()[0])
    n_extra = 1010
    res_rows = []
    lbl_rows = []
    edge_rows = []
    for k in range(1, n_extra + 1):
        rid = max_rid + k
        pref = f"Bulk Concept {k:04d}"
        res_rows.append((rid, f"urn:ref:fr:bulk-{k:04d}", fr_sid, fr_rel, None, 0, "src", None, pref, 1, 1))
        lbl_rows.append((rid, 0, pref.lower(), pref, 0, f"urn:ref:atlas-label:bulk-{k:04d}", "preferred", "en"))
        edge_rows.append((med_rid, 0, rel_pid, 0, f"urn:ref:atlas-assertion:bulk-rel-{k:04d}", rid, 1, 0))
        # Also attach a broader edge back to Medicare so _fetch_broader_labels over >999 rids is exercised!
        edge_rows.append((rid, 0, brd_pid, 0, f"urn:ref:atlas-assertion:bulk-brd-{k:04d}", med_rid, 1, 0))
    con.executemany("INSERT INTO resources VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", res_rows)
    con.executemany("INSERT INTO labels VALUES (?, ?, ?, ?, ?, ?, ?, ?)", lbl_rows)
    con.executemany("INSERT INTO edges VALUES (?, ?, ?, ?, ?, ?, ?, ?)", edge_rows)
    _refresh_pack_blobs(con)
    con.commit()
    con.close()

    with AtlasVocabularyPack.open(big_pack, verify_pack_digest=False) as pack:
        expanded = pack.expand_sync(
            {"id": "urn:ref:fr:medicare", "scheme": S_FR, "release": R_FR},
            max_depth=1,
            max_nodes=1024,
        )
        assert len(expanded) == n_extra

        # Also exercise _hydrate_pairs(..., include_context=True) across all 1010 rids (chunks both hydrate + broader labels!)
        all_bulk_rids = [max_rid + k for k in range(1, n_extra + 1)]
        hydrated_ctx = pack._hydrate_pairs(all_bulk_rids, include_context=True)
        assert len(hydrated_ctx) == n_extra
        assert hydrated_ctx[-1][1]["broaderLabels"] == ["Medicare"]

        # Protocol checks: AgencyHistoryProvider, SemanticIndex.pack_id/recommended_min_cosine, GraphExpander.include_symmetric_inverse
        assert isinstance(pack, AgencyHistoryProvider)
        assert isinstance(pack, GraphExpander)
        assert isinstance(pack, VocabularyProvider)

    assert "pack_id" in SemanticIndex.__protocol_attrs__  # type: ignore[attr-defined]
    assert "recommended_min_cosine" in SemanticIndex.__protocol_attrs__  # type: ignore[attr-defined]
    assert "include_symmetric_inverse" in inspect.signature(GraphExpander.expand_sync).parameters
    assert "include_symmetric_inverse" in inspect.signature(GraphExpander.expand).parameters

    # 2. Dangling dst_rid in edges MUST raise VocabularyPackError("corrupt_pack", ...) (HTTP 503), NOT raw ValueError (HTTP 400)!
    dangling_pack = tmp_path / "dangling_edge.sqlite"
    dangling_pack.write_bytes(base_pack.read_bytes())
    con2 = sqlite3.connect(str(dangling_pack))
    con2.execute(
        "INSERT INTO edges VALUES (?, 0, ?, 0, 'urn:ref:atlas-assertion:dangling', 999999, 1, 0)",
        (med_rid, rel_pid),
    )
    con2.commit()
    con2.close()

    with AtlasVocabularyPack.open(dangling_pack, verify_pack_digest=False) as dpack:
        with pytest.raises(VocabularyPackError) as exc_corrupt:
            dpack.related_sync({"id": "urn:ref:fr:medicare", "scheme": S_FR, "release": R_FR}, limit=10)
        assert exc_corrupt.value.code == "corrupt_pack"
        assert isinstance(exc_corrupt.value, RuntimeError)
        assert not isinstance(exc_corrupt.value, ValueError)

    # 3. CLI parser check: build-vectors accepts --recommended-min-cosine, extract rejects dead --no-authority-tiebreak
    parser = _build_parser()
    parsed_vec = parser.parse_args(
        [
            "build-vectors",
            "--pack",
            str(base_pack),
            "--embeddings-dir",
            str(tmp_path),
            "--output",
            str(tmp_path / "out.vpack"),
            "--recommended-min-cosine",
            "0.68",
        ]
    )
    assert parsed_vec.recommended_min_cosine == pytest.approx(0.68)

    with pytest.raises(SystemExit):
        parser.parse_args(["extract", "--pack", str(base_pack), "--text", "Medicare", "--no-authority-tiebreak"])
