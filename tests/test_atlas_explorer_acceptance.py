"""The explorer acceptance gate executes filters, reachability, and search."""

from __future__ import annotations

import json
import re
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import test_atlas_publication as publication_fixtures

from refspec.atlas.explorer import render_atlas_explorer
from refspec.atlas.explorer_acceptance import (
    ExplorerAcceptanceError,
    _id_digest,
    _normalize_search,
    build_vocabulary_atlas_explorer_acceptance,
    planning_row_eligible,
    rank_explorer_search,
    read_vocabulary_atlas_explorer_acceptance,
)
from refspec.atlas.publication import build_explorer_model
from refspec.registry.infrastructure.artifact_serialization import sha256_digest

# This suite verifies the retired Atlas 1/2 publication explorer model. The
# current explorer is deliberately Atlas 3.0-only; keeping these historical
# assertions active would require restoring the sunset wire format.
pytestmark = pytest.mark.skip(reason="retired Atlas 1/2 explorer acceptance suite")


def _corpus(explorer: dict[str, Any]) -> dict[str, Any]:
    concept = explorer["concepts"][0]
    preferred = concept["label"]
    alternate = f"{preferred} Alias"
    variant = f"{preferred} Variant"
    concept["searchLabels"] = sorted(
        {preferred, alternate, variant},
        key=lambda value: (value.casefold(), value),
    )
    concept["notation"] = "T-001"
    concept["definition"] = "Distinctive regulated harbor terminology"
    cases = (
        ("alias", alternate, 5),
        ("definition-or-scope-note", "regulated harbor terminology", 5),
        ("exact-identifier", concept["conceptId"], 1),
        ("exact-notation", concept["notation"], 5),
        ("exact-preferred-label", preferred, 1),
        (
            "normalized-punctuation-spacing",
            preferred.replace("-", " / "),
            5,
        ),
        ("recognized-variant", variant, 5),
        ("reviewed-one-edit-typo", preferred[:-1] + "f", 5),
        ("useful-prefix", preferred[:5], 5),
    )
    categories = {
        "alias": "alias",
        "definition-or-scope-note": "definitionOrScopeNote",
        "exact-identifier": "exactIdentifier",
        "exact-notation": "exactNotation",
        "exact-preferred-label": "exactPreferredLabel",
        "normalized-punctuation-spacing": "normalizedPunctuationSpacing",
        "recognized-variant": "recognizedVariant",
        "reviewed-one-edit-typo": "reviewedOneEditTypo",
        "useful-prefix": "usefulPrefix",
    }
    source_fact_query = concept["sourceUrls"][0]
    source_fact_results = rank_explorer_search(
        explorer,
        semantic_ring=concept["semanticRing"],
        query=source_fact_query,
    )
    return {
        "type": "VocabularyAtlasExplorerSearchCorpus",
        "schemaVersion": "2.0",
        "reviewedBy": "https://refspec.org/actors/explorer-acceptance-reviewer",
        "reviewedAt": "2026-08-04T23:00:00Z",
        "releaseIds": sorted(
            release["releaseId"] for release in explorer["conceptReleases"]
        ),
        "cases": [
            {
                "id": f"urn:ref:test:explorer-search:{name}",
                "semanticRing": concept["semanticRing"],
                "category": categories[name],
                "query": query,
                "expectedReleaseId": concept["releaseId"],
                "expectedConceptId": concept["conceptId"],
                "maximumRank": maximum_rank,
            }
            for name, query, maximum_rank in cases
        ],
        "aggregateCases": [
            {
                "id": "urn:ref:test:explorer-search:source-fact-aggregate",
                "semanticRing": concept["semanticRing"],
                "category": "sourceFact",
                "query": source_fact_query,
                "expectedReleaseId": concept["releaseId"],
                "expectedResultCount": len(source_fact_results),
                "expectedViewIdDigest": _id_digest(
                    [row["viewId"] for row in source_fact_results]
                ),
                "expectedMatch": "Source or release fact",
            }
        ],
    }


def _run_shipped_search_core(
    explorer: dict[str, Any],
    cases: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    html = render_atlas_explorer(explorer)
    document_core = re.search(
        r"/\* explorer-search-document-core:start \*/(.*?)/\* explorer-search-document-core:end \*/",
        html,
        flags=re.DOTALL,
    )
    ranking_core = re.search(
        r"/\* explorer-search-ranking-core:start \*/(.*?)/\* explorer-search-ranking-core:end \*/",
        html,
        flags=re.DOTALL,
    )
    assert document_core is not None
    assert ranking_core is not None
    facet_fields = [
        "sourceModules",
        "resourceIds",
        "participations",
        "languages",
        "lifecycle",
        "sourceCollections",
        "sourceUrls",
        "cfrTitles",
        "cfrParts",
    ]
    script = "\n".join(
        (
            document_core.group(1),
            ranking_core.group(1),
            f"const concepts = {json.dumps(explorer['concepts'], sort_keys=True)};",
            f"const facetDefinitions = {json.dumps([[field, field] for field in facet_fields])};",
            f"const cases = {json.dumps(cases, sort_keys=True)};",
            """
const documents = buildSearchDocuments(concepts, facetDefinitions);
const outcomes = cases.map(searchCase => {
  const ranked = rankSearchDocuments(
    documents,
    searchCase.query,
    searchCase.semanticRing
  );
  const index = ranked.findIndex(result =>
    result.document.concept.releaseId === searchCase.expectedReleaseId
      && result.document.concept.conceptId === searchCase.expectedConceptId
  );
  const observed = index >= 0 ? ranked[index] : null;
  return {
    id: searchCase.id,
    observedRank: observed ? index + 1 : null,
    observedScore: observed ? observed.score : null,
    observedMatch: observed ? observed.match : null
  };
});
process.stdout.write(JSON.stringify(outcomes));
""",
        )
    )
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_baseline_gate_measures_every_facet_and_assertion_without_public_claim(
    tmp_path: Path,
) -> None:
    scope, asset, decision, relation = publication_fixtures._mapped_fixture(
        tmp_path
    )
    explorer = build_explorer_model(
        asset,
        planning_index=scope.verified_scope().atlas_index,
        decision=decision,
    )

    acceptance = build_vocabulary_atlas_explorer_acceptance(
        asset,
        explorer,
        explorer_html=render_atlas_explorer(explorer).encode("utf-8"),
        release_mode="baselineEvidenceRc",
    )
    record = acceptance.as_record()

    assert record["schemaVersion"] == "2.0"
    assert record["status"] == "measuredBaselineOnly"
    assert record["search"]["status"] == "skippedPublicOnly"
    assert record["reachability"]["mappingAssertions"] == {
        "total": 1,
        "endpointChecks": 2,
        "filterChecks": 1,
        "idDigest": record["reachability"]["mappingAssertions"]["idDigest"],
    }
    facets = {row["facet"]: row for row in record["facetMeasurements"]}
    assert set(facets) == {
        "cfrParts",
        "cfrTitles",
        "evidenceClasses",
        "languages",
        "lifecycle",
        "mappingPredicates",
        "mappingLifecycleStatuses",
        "nativePredicates",
        "participations",
        "planningDispositions",
        "releases",
        "resourceIds",
        "semanticRings",
        "sourceCollections",
        "sourceModules",
        "sourceUrls",
    }
    assert facets["mappingPredicates"]["values"] == [
        {"value": relation, "count": 1}
    ]
    planning = record["planningFilters"]
    assert planning["rowTotal"] == len(explorer["releaseContext"]["planningRows"])
    assert [row["dimension"] for row in planning["individual"]] == [
        "ring",
        "sourceModule",
        "resourceId",
        "participation",
        "disposition",
    ]
    assert planning["combined"]["coveredRowCount"] == planning["rowTotal"]
    filter_execution = record["filterExecution"]
    assert filter_execution["status"] == "passed"
    assert filter_execution["caseCount"] == len(filter_execution["cases"])
    assert filter_execution["nodeVersion"].startswith("v")
    assert filter_execution["setContainsStateRepresentation"] == "Set"
    assert filter_execution["coreDigest"].startswith("sha256:")
    assert filter_execution["caseDigest"].startswith("sha256:")
    assert filter_execution["resultDigest"].startswith("sha256:")
    assert {row["recordKind"] for row in filter_execution["cases"]} == {
        "concept",
        "nativeRelation",
        "mappingAssertion",
    }
    assert {
        "release",
        "ring",
        "sourceModules",
        "resourceIds",
            "participations",
            "languages",
            "mappingVisibility",
        "mappingPredicate",
        "mappingLifecycleStatus",
        "evidenceClass",
    } <= {row["dimension"] for row in filter_execution["cases"]}
    assert record["explorer"]["htmlFileDigest"].startswith("sha256:")


def test_planning_filter_core_uses_and_semantics_in_python_and_shipped_javascript(
    tmp_path: Path,
) -> None:
    scope, asset, decision, _relation = publication_fixtures._mapped_fixture(
        tmp_path
    )
    explorer = build_explorer_model(
        asset,
        planning_index=scope.verified_scope().atlas_index,
        decision=decision,
    )
    row = explorer["releaseContext"]["planningRows"][0]
    positive = {
        "ring": {row["semanticRing"]},
        "sourceModule": row["sourceModule"],
        "resourceId": row["resourceId"],
        "participation": row.get("atlasParticipation", ""),
        "disposition": row["disposition"],
    }
    negative = {**positive, "sourceModule": "refspec.registry.not-this-row"}
    assert planning_row_eligible(row, positive)
    assert not planning_row_eligible(row, negative)

    html = render_atlas_explorer(explorer)
    match = re.search(
        r"/\* planning-filter-core:start \*/(.*?)/\* planning-filter-core:end \*/",
        html,
        flags=re.DOTALL,
    )
    assert match is not None
    script = f"""
{match.group(1)}
const row = {json.dumps(row, sort_keys=True)};
const positive = {{
  activeRings: new Set([row.semanticRing]),
  activeConceptFacets: {{
    sourceModules: row.sourceModule,
    resourceIds: row.resourceId,
    participations: row.atlasParticipation || ""
  }},
  activePlanningDisposition: row.disposition
}};
const negative = {{
  ...positive,
  activeConceptFacets: {{
    ...positive.activeConceptFacets,
    sourceModules: "refspec.registry.not-this-row"
  }}
}};
process.stdout.write(JSON.stringify([
  planningRowEligibleForState(row, positive),
  planningRowEligibleForState(row, negative)
]));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(completed.stdout) == [True, False]

    missing_catalog_value = deepcopy(explorer)
    missing_catalog_value["releaseContext"]["planningRows"][0][
        "sourceModule"
    ] = "refspec.registry.unadvertised"
    with pytest.raises(
        ExplorerAcceptanceError,
        match="planning sourceModule filter omits a row value",
    ):
        build_vocabulary_atlas_explorer_acceptance(
            asset,
            missing_catalog_value,
            explorer_html=render_atlas_explorer(explorer).encode("utf-8"),
            release_mode="baselineEvidenceRc",
        )


def test_multilingual_mark_normalization_matches_the_shipped_javascript(
    tmp_path: Path,
) -> None:
    _scope, asset, _decision, _relation = publication_fixtures._mapped_fixture(
        tmp_path
    )
    explorer = build_explorer_model(asset)
    html = render_atlas_explorer(explorer)
    match = re.search(
        r"/\* explorer-search-document-core:start \*/(.*?)/\* explorer-search-document-core:end \*/",
        html,
        flags=re.DOTALL,
    )
    assert match is not None
    values = [
        "काग",
        "العَرَبِيَّة",
        "Cafe\u0301",
        "สวัสดี",
    ]
    script = f"""
{match.group(1)}
const values = {json.dumps(values, ensure_ascii=False)};
process.stdout.write(JSON.stringify(values.map(normalizeSearch)));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == [
        _normalize_search(value) for value in values
    ]
    assert _normalize_search("काग") == "कग"


def test_public_gate_executes_every_reviewed_search_category_and_round_trips(
    tmp_path: Path,
) -> None:
    _scope, asset, _decision, _relation = publication_fixtures._mapped_fixture(
        tmp_path
    )
    explorer = build_explorer_model(asset)
    corpus = _corpus(explorer)

    acceptance = build_vocabulary_atlas_explorer_acceptance(
        asset,
        explorer,
        explorer_html=render_atlas_explorer(explorer).encode("utf-8"),
        release_mode="publicV1",
        reviewed_corpus=corpus,
        reviewed_corpus_path="research/test-explorer-search-corpus.json",
        reviewed_corpus_file_digest=sha256_digest(b"reviewed corpus"),
    )

    assert acceptance.record["status"] == "passed"
    assert acceptance.record["search"]["caseCount"] == 10
    assert acceptance.record["search"]["rankedCaseCount"] == 9
    assert acceptance.record["search"]["aggregateCaseCount"] == 1
    assert {
        row["category"] for row in acceptance.record["search"]["cases"]
    } == {
        "alias",
        "definitionOrScopeNote",
        "exactIdentifier",
        "exactNotation",
        "exactPreferredLabel",
        "normalizedPunctuationSpacing",
        "recognizedVariant",
        "reviewedOneEditTypo",
        "usefulPrefix",
    }
    assert all(
        row["observedRank"] <= row["maximumRank"]
        for row in acceptance.record["search"]["cases"]
    )
    aggregate = acceptance.record["search"]["aggregateCases"][0]
    assert aggregate["observedMatch"] == "Source or release fact"
    assert aggregate["observedResultCount"] == aggregate["expectedResultCount"]
    assert aggregate["observedViewIdDigest"] == aggregate["expectedViewIdDigest"]
    expected_js = [
        {
            "id": row["id"],
            "observedRank": row["observedRank"],
            "observedScore": row["observedScore"],
            "observedMatch": row["observedMatch"],
        }
        for row in acceptance.record["search"]["cases"]
    ]
    assert _run_shipped_search_core(
        explorer,
        acceptance.as_record()["search"]["cases"],
    ) == expected_js

    path = acceptance.write_to(tmp_path / "explorer-acceptance.json")
    reopened = read_vocabulary_atlas_explorer_acceptance(
        path,
        expected_file_digest=sha256_digest(path.read_bytes()),
    )
    reopened.validate_inputs(
        asset,
        explorer,
        explorer_html=render_atlas_explorer(explorer).encode("utf-8"),
    )


def test_public_gate_rejects_incomplete_corpus_and_unreachable_mapping(
    tmp_path: Path,
) -> None:
    _scope, asset, _decision, _relation = publication_fixtures._mapped_fixture(
        tmp_path
    )
    explorer = build_explorer_model(asset)
    corpus = _corpus(explorer)
    corpus["cases"].pop()

    with pytest.raises(ExplorerAcceptanceError, match="does not cover"):
        build_vocabulary_atlas_explorer_acceptance(
            asset,
            explorer,
            explorer_html=render_atlas_explorer(explorer).encode("utf-8"),
            release_mode="publicV1",
            reviewed_corpus=corpus,
            reviewed_corpus_path="research/test-explorer-search-corpus.json",
            reviewed_corpus_file_digest=sha256_digest(b"reviewed corpus"),
        )

    unreachable = deepcopy(explorer)
    unreachable["mappingAssertions"] = []
    unreachable["facets"]["mappingPredicates"] = []
    unreachable["facets"]["mappingLifecycleStatuses"] = []
    unreachable["facets"]["evidenceClasses"] = []
    with pytest.raises(ExplorerAcceptanceError, match="assertion or evidence class is absent"):
        build_vocabulary_atlas_explorer_acceptance(
            asset,
            unreachable,
            explorer_html=render_atlas_explorer(explorer).encode("utf-8"),
            release_mode="baselineEvidenceRc",
        )
