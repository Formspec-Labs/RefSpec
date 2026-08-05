"""Benchmark relation-blind candidate discovery on OAEI BeyondEquivalence.

The selected STROMA/TaSeR cases contain explicit equality, hierarchy,
associative, and meronymic reference relations.  Candidate generators never
receive those relation markers.  The benchmark joins reference relations only
after retrieval so it can report recall separately by type without teaching a
retriever which answer to find.

The default run uses the official OAEI 2025 release and one local dense model::

    uv run --with 'rapidfuzz==3.14.3' --with 'fastembed==0.8.0' \
      tools/benchmark_beyond_equivalence_candidate_retrieval.py \
      --archive /tmp/refspec-candidate-benchmark.ANhNrc/beyond-equivalence-benchmark.zip \
      --wordnet /tmp/refspec-candidate-benchmark.ANhNrc/english-wordnet-2025.xml.gz \
      --output /tmp/beyond-equivalence-candidates.json

No provider API or hosted inference service is used.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.metadata
import re
import struct
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS

from refspec.atlas.candidate_retrieval import (
    DEFAULT_SPARSE_VIEWS,
    bidirectional_sparse_neighbors,
    exact_identifier_neighbors,
    graph_neighborhood_neighbors,
    retrieval_digest,
)
from refspec.atlas.qualification import (
    GENERATION_CLASSES,
    AtlasConcept,
    AtlasConceptContext,
    generate_candidate_pairs,
)
from refspec.storage import canonical_json

DEFAULT_CASES = (
    "g3-text",
    "g4-furniture",
    "g5-groceries",
    "g6-clothing",
    "g7-literature",
)
DEFAULT_TOP_K = (1, 2, 3, 5, 10, 20, 50, 100)
DEFAULT_DENSE_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_QUERY_BLOCK_SIZE = 128
OFFICIAL_ARCHIVE_SHA256 = "04cc6dd2a2f8d173ddcc19822428fa9f505e3855840f06b19072306233d240eb"
OFFICIAL_TRACK_URL = "https://oaei.ontologymatching.org/2025/beyondequivalence/index.html"
OFFICIAL_RECORD_URL = "https://zenodo.org/records/17091043"
OFFICIAL_LICENSE = "CC-BY-4.0"
OEWN_VERSION = "2025"
OEWN_RELEASE_TAG = "2025-edition"
OEWN_RELEASE_COMMIT = "dc343f2683279ecbb13fab4e2fd778d7b162d287"
OEWN_ARCHIVE_SHA256 = "9ca6d1dcb75f822fdd66617f7d9da48142ace38dd544d6ad5e2feca1674ad3fe"
OEWN_RELEASE_URL = "https://github.com/globalwordnet/english-wordnet/releases/tag/2025-edition"
OEWN_ASSET_URL = (
    "https://github.com/globalwordnet/english-wordnet/releases/download/2025-edition/english-wordnet-2025.xml.gz"
)
OEWN_LICENSE_URL = "https://github.com/globalwordnet/english-wordnet/blob/2025-edition/LICENSE.md"

FAMILY_ORDER = (
    "equality",
    "sourceBroader",
    "sourceNarrower",
    "relatedOrOverlap",
    "partOrHasA",
    "disjointOrRejection",
)
MARKER_TO_FAMILY = {
    "=": "equality",
    ">": "sourceBroader",
    "<": "sourceNarrower",
    "Related": "relatedOrOverlap",
    "~": "relatedOrOverlap",
    "HasA": "partOrHasA",
    "PartOf": "partOrHasA",
    "!": "disjointOrRejection",
    "Disjoint": "disjointOrRejection",
}
MARKER_ORDER = ("=", ">", "<", "Related", "~", "HasA", "PartOf", "!", "Disjoint")

SKOS_ANALOGY = {
    "=": {
        "closestSkosProperty": "skos:exactMatch",
        "scopeNote": (
            "The benchmark asserts extensional class equivalence. This is useful evidence for exactMatch, "
            "but it is not a test of SKOS mapping-property entailments."
        ),
    },
    ">": {
        "closestSkosProperty": "skos:narrowMatch",
        "scopeNote": (
            "The source is a superclass of the target, so source skos:narrowMatch target is the closest "
            "source-to-target SKOS direction."
        ),
    },
    "<": {
        "closestSkosProperty": "skos:broadMatch",
        "scopeNote": (
            "The source is a subclass of the target, so source skos:broadMatch target is the closest "
            "source-to-target SKOS direction."
        ),
    },
    "Related": {
        "closestSkosProperty": "skos:relatedMatch",
        "scopeNote": (
            "This is an associative STROMA relation. It is analogous to relatedMatch, not formal set-theoretic overlap."
        ),
    },
    "~": {
        "closestSkosProperty": None,
        "scopeNote": (
            "Formal extensional overlap has no direct SKOS mapping property. relatedMatch may be a useful "
            "search-expansion decision, but it is not logically equivalent."
        ),
    },
    "HasA": {
        "closestSkosProperty": None,
        "scopeNote": "Meronymy has no direct SKOS mapping property.",
    },
    "PartOf": {
        "closestSkosProperty": None,
        "scopeNote": "Meronymy has no direct SKOS mapping property.",
    },
    "disjointOrRejection": {
        "closestSkosProperty": None,
        "scopeNote": (
            "Disjointness has no direct SKOS mapping property. The selected archive contains no disjoint "
            "reference rows, so this benchmark reports a zero-opportunity control."
        ),
    },
    "skos:closeMatch": {
        "benchmarkMarker": None,
        "scopeNote": "The selected STROMA/TaSeR reference files do not contain a close-match marker.",
    },
}


@dataclass(frozen=True, slots=True)
class ReferenceRelation:
    """One reference row with its original marker preserved."""

    source: str
    target: str
    marker: str
    family: str

    @property
    def pair(self) -> tuple[str, str]:
        return self.source, self.target


@dataclass(frozen=True, slots=True)
class TypedAlignmentCase:
    """One relation-blind retrieval input plus separately held reference rows."""

    name: str
    sources: tuple[AtlasConcept, ...]
    targets: tuple[AtlasConcept, ...]
    relations: tuple[ReferenceRelation, ...]
    input_digests: tuple[tuple[str, str], ...] = ()
    source_stats: tuple[tuple[str, int], ...] = ()
    target_stats: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True, slots=True)
class RapidFuzzSpec:
    """One selected lexical control and its declared representation."""

    name: str
    metric: str
    representation: str
    higher_is_better: bool = True


@dataclass(frozen=True, slots=True)
class WordNetIndex:
    """The noun lookup and two-way taxonomy graph from one pinned OEWN file."""

    forms: Mapping[str, frozenset[str]]
    adjacency: Mapping[str, frozenset[str]]
    stats: Mapping[str, int]


RAPIDFUZZ_SPECS = (
    RapidFuzzSpec("levenshtein-distance", "levenshtein-distance", "raw-label", False),
    RapidFuzzSpec("normalized-levenshtein", "normalized-levenshtein", "normalized-label"),
    RapidFuzzSpec("rapidfuzz-token-set-ratio", "token-set-ratio", "normalized-label"),
    RapidFuzzSpec("rapidfuzz-partial-ratio", "partial-ratio", "normalized-label"),
    RapidFuzzSpec("acronym-token-set-ratio", "token-set-ratio", "acronym"),
    RapidFuzzSpec("character-trigram-token-set", "token-set-ratio", "character-trigrams"),
)

PairKey = tuple[str, str, str]
RelationKey = tuple[str, str, str, str]


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _canonical_digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _local_name(value: object) -> str:
    text = str(value)
    if "}" in text:
        text = text.rsplit("}", 1)[-1]
    return text.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def _normalized_tokens(value: str) -> tuple[str, ...]:
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", value)
    value = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
    folded = unicodedata.normalize("NFKD", value.casefold())
    folded = "".join(character for character in folded if not unicodedata.combining(character))
    return tuple(token for token in re.split(r"[^0-9a-z]+", folded) if token)


def _normalized_label(value: str) -> str:
    return " ".join(_normalized_tokens(value))


def _raw_label(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _identifier_tail(value: str) -> str:
    parsed = urlparse(value)
    tail = parsed.fragment or parsed.path.rstrip("/").rsplit("/", 1)[-1]
    if parsed.scheme == "urn":
        tail = value.rsplit(":", 1)[-1]
    return unquote(tail)


def _fallback_label(value: str) -> str:
    tail = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", _identifier_tail(value))
    tail = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", tail)
    return " ".join(token for token in re.split(r"[^0-9A-Za-z]+", tail) if token) or value


def _abbreviation_keys(value: str) -> tuple[str, ...]:
    tokens = _normalized_tokens(value)
    keys: set[str] = set()
    if len(tokens) > 1:
        initials = "".join(token[0] for token in tokens)
        for start in range(len(initials)):
            for end in range(start + 2, len(initials) + 1):
                keys.add(initials[start:end])
    for raw_token in re.findall(r"[A-Za-z0-9]+", value):
        normalized = _normalized_label(raw_token).replace(" ", "")
        if 2 <= len(normalized) <= 8 and (raw_token.isupper() or not set(normalized) & set("aeiou")):
            keys.add(normalized)
    if len(tokens) == 1 and 2 <= len(tokens[0]) <= 8:
        keys.add(tokens[0])
    return tuple(sorted(keys))


def _character_trigrams(value: str) -> str:
    compact = "".join(_normalized_tokens(value))
    if not compact:
        return ""
    padded = f"^^{compact}$$"
    return " ".join(sorted({padded[index : index + 3] for index in range(len(padded) - 2)}))


def lexical_representation(concept: AtlasConcept, representation: str) -> str:
    """Return the declared relation-neutral lexical representation."""

    if representation == "raw-label":
        return _raw_label(concept.pref_label)
    if representation == "normalized-label":
        return _normalized_label(concept.pref_label)
    if representation == "acronym":
        return " ".join(_abbreviation_keys(concept.pref_label))
    if representation == "character-trigrams":
        return _character_trigrams(concept.pref_label)
    raise ValueError(f"unsupported representation {representation!r}")


def _singular_forms(tokens: tuple[str, ...]) -> tuple[str, ...]:
    """Return conservative noun singular variants without choosing one sense."""

    if not tokens:
        return ()
    word = tokens[-1]
    candidates = {word}
    if len(word) > 4 and word.endswith("ies"):
        candidates.add(word[:-3] + "y")
    if len(word) > 4 and word.endswith(("ches", "shes", "xes", "zes")):
        candidates.add(word[:-2])
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        candidates.add(word[:-1])
    prefix = tokens[:-1]
    return tuple(sorted(" ".join((*prefix, candidate)) for candidate in candidates))


def noun_lookup_forms(value: str) -> tuple[str, ...]:
    """Normalize a multiword noun and retain suffix heads of up to three words."""

    tokens = _normalized_tokens(value)
    if not tokens:
        return ()
    forms: set[str] = set()
    for width in range(1, min(3, len(tokens)) + 1):
        forms.update(_singular_forms(tokens[-width:]))
    forms.update(_singular_forms(tokens))
    return tuple(sorted(forms))


def load_wordnet(path: Path) -> WordNetIndex:
    """Stream the pinned OEWN LMF XML into a compact noun-only graph."""

    forms: dict[str, set[str]] = defaultdict(set)
    adjacency: dict[str, set[str]] = defaultdict(set)
    noun_synsets: set[str] = set()
    lexical_entries = 0
    senses = 0
    taxonomy_edges: set[tuple[str, str]] = set()
    allowed_relations = frozenset({"hypernym", "hyponym", "instance_hypernym", "instance_hyponym"})
    with gzip.open(path, "rb") as stream:
        for _event, element in ET.iterparse(stream, events=("end",)):
            tag = _local_name(element.tag)
            if tag == "LexicalEntry":
                lemma = next((child for child in element if _local_name(child.tag) == "Lemma"), None)
                if lemma is not None and lemma.attrib.get("partOfSpeech") == "n":
                    written = lemma.attrib.get("writtenForm", "")
                    normalized = _normalized_label(written)
                    synsets = {
                        child.attrib["synset"]
                        for child in element
                        if _local_name(child.tag) == "Sense" and child.attrib.get("synset")
                    }
                    if normalized and synsets:
                        forms[normalized].update(synsets)
                        lexical_entries += 1
                        senses += len(synsets)
                element.clear()
            elif tag == "Synset":
                if element.attrib.get("partOfSpeech") == "n" and (synset := element.attrib.get("id")):
                    noun_synsets.add(synset)
                    for child in element:
                        if (
                            _local_name(child.tag) == "SynsetRelation"
                            and child.attrib.get("relType") in allowed_relations
                            and (target := child.attrib.get("target"))
                        ):
                            edge = tuple(sorted((synset, target)))
                            taxonomy_edges.add(edge)
                            adjacency[synset].add(target)
                            adjacency[target].add(synset)
                element.clear()
    return WordNetIndex(
        forms={key: frozenset(value) for key, value in sorted(forms.items())},
        adjacency={key: frozenset(value) for key, value in sorted(adjacency.items())},
        stats={
            "nounLexicalEntries": lexical_entries,
            "nounLemmaForms": len(forms),
            "nounSenses": senses,
            "nounSynsets": len(noun_synsets),
            "undirectedTaxonomyEdges": len(taxonomy_edges),
        },
    )


def _concept_wordnet_synsets(concept: AtlasConcept, index: WordNetIndex) -> tuple[tuple[str, ...], frozenset[str]]:
    forms = {form for label in (concept.pref_label, *concept.alt_labels) for form in noun_lookup_forms(label)}
    synsets = frozenset(synset for form in forms for synset in index.forms.get(form, ()))
    return tuple(sorted(forms)), synsets


def _wordnet_neighborhood(
    roots: frozenset[str],
    adjacency: Mapping[str, frozenset[str]],
    *,
    depth: int = 2,
) -> dict[str, int]:
    distances = {synset: 0 for synset in roots}
    frontier = set(roots)
    for distance in range(1, depth + 1):
        following = {
            neighbor for synset in frontier for neighbor in adjacency.get(synset, ()) if neighbor not in distances
        }
        for synset in following:
            distances[synset] = distance
        frontier = following
        if not frontier:
            break
    return distances


def run_wordnet_arm(
    cases: Sequence[TypedAlignmentCase],
    *,
    index: WordNetIndex,
    maximum_depth: int = 2,
) -> tuple[dict[PairKey, int], dict[str, object]]:
    """Propose pairs within a bounded noun-taxonomy distance.

    Every noun sense remains active. Taxonomy edges are traversed in both
    directions because candidate discovery must retain broader and narrower
    possibilities for a later semantic judge.
    """

    if maximum_depth < 0:
        raise ValueError("WordNet taxonomy depth cannot be negative")
    class_names = {
        0: "sharedSynset",
        1: "oneHopTaxonomy",
        2: "twoHopTaxonomy",
        3: "threeHopTaxonomy",
        4: "fourHopTaxonomy",
    }
    generation = {class_names.get(distance, f"{distance}HopTaxonomy"): set() for distance in range(maximum_depth + 1)}
    ranks: dict[PairKey, int] = {}
    feature_hasher = hashlib.sha256()
    evidence_hasher = hashlib.sha256()
    source_with_synsets = 0
    target_with_synsets = 0
    started = time.monotonic()
    neighborhood_cache: dict[frozenset[str], dict[str, int]] = {}

    def neighborhood(synsets: frozenset[str]) -> dict[str, int]:
        if synsets not in neighborhood_cache:
            neighborhood_cache[synsets] = _wordnet_neighborhood(
                synsets,
                index.adjacency,
                depth=maximum_depth,
            )
        return neighborhood_cache[synsets]

    for case in sorted(cases, key=lambda item: item.name):
        source_features = []
        target_features = []
        for role, concepts, destination in (
            ("source", sorted(case.sources, key=lambda item: item.member), source_features),
            ("target", sorted(case.targets, key=lambda item: item.member), target_features),
        ):
            for concept in concepts:
                forms, synsets = _concept_wordnet_synsets(concept, index)
                destination.append((concept, synsets, neighborhood(synsets)))
                feature_hasher.update(
                    f"{case.name}\t{role}\t{concept.member}\t{'|'.join(forms)}\t{'|'.join(sorted(synsets))}\n".encode()
                )
                if synsets:
                    if role == "source":
                        source_with_synsets += 1
                    else:
                        target_with_synsets += 1

        for source, source_synsets, source_neighborhood in source_features:
            if not source_synsets:
                continue
            for target, target_synsets, target_neighborhood in target_features:
                if not target_synsets:
                    continue
                distances = [source_neighborhood[synset] for synset in target_synsets if synset in source_neighborhood]
                distances.extend(
                    target_neighborhood[synset] for synset in source_synsets if synset in target_neighborhood
                )
                if not distances:
                    continue
                distance = min(distances)
                pair = (case.name, source.member, target.member)
                ranks[pair] = 1
                class_name = class_names.get(distance, f"{distance}HopTaxonomy")
                generation[class_name].add(pair)
                evidence_hasher.update(f"{case.name}\t{source.member}\t{target.member}\t{distance}\n".encode())

    metadata = {
        "resource": "Open English WordNet",
        "version": OEWN_VERSION,
        "releaseTag": OEWN_RELEASE_TAG,
        "releaseCommit": OEWN_RELEASE_COMMIT,
        "releaseUrl": OEWN_RELEASE_URL,
        "license": "Princeton WordNet License for underlying data; CC-BY-4.0 for OEWN additions",
        "licenseUrl": OEWN_LICENSE_URL,
        "assetUrl": OEWN_ASSET_URL,
        "method": (
            "all noun senses for normalized multiword labels and suffix heads; shared synset or undirected "
            f"hypernym/hyponym distance at most {maximum_depth}"
        ),
        "maximumTaxonomyDepth": maximum_depth,
        "interpretation": "domain-transferable lexical-knowledge discovery signal, not semantic proof",
        "wordNetStats": dict(index.stats),
        "sourceConceptsWithNounSynsets": source_with_synsets,
        "targetConceptsWithNounSynsets": target_with_synsets,
        "generationClassCandidates": {name: len(values) for name, values in generation.items()},
        "featureDigest": "sha256:" + feature_hasher.hexdigest(),
        "evidenceDigest": "sha256:" + evidence_hasher.hexdigest(),
        "elapsedSeconds": round(time.monotonic() - started, 3),
    }
    return ranks, metadata


def structured_embedding_text(concept: AtlasConcept) -> str:
    """Inject relation-neutral label, note, identifier, and hierarchy context."""

    alternates = "; ".join(concept.alt_labels)
    parents = "; ".join(item.pref_label for item in concept.parents)
    children = "; ".join(item.pref_label for item in concept.children)
    return (
        f"label: {concept.pref_label}\n"
        f"alternate labels: {alternates}\n"
        f"identifier: {_fallback_label(concept.member)}\n"
        f"definition: {concept.definition or ''}\n"
        f"scope note: {concept.scope_note or ''}\n"
        f"broader concepts: {parents}\n"
        f"narrower concepts: {children}"
    )


def parse_reference(data: bytes, *, case_name: str) -> tuple[ReferenceRelation, ...]:
    """Parse Alignment API XML and reject unrecognized relation markers."""

    root = ET.fromstring(data)
    resource = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource"
    relations: list[ReferenceRelation] = []
    for cell in (element for element in root.iter() if _local_name(element.tag) == "Cell"):
        values = {_local_name(child.tag): child for child in cell}
        source = values.get("entity1")
        target = values.get("entity2")
        marker_node = values.get("relation")
        if source is None or target is None or marker_node is None:
            raise ValueError(f"{case_name}: reference Cell is missing entity1, entity2, or relation")
        source_member = source.attrib.get(resource)
        target_member = target.attrib.get(resource)
        marker = (marker_node.text or "").strip()
        if not source_member or not target_member or not marker:
            raise ValueError(f"{case_name}: reference Cell has an empty endpoint or marker")
        family = MARKER_TO_FAMILY.get(marker)
        if family is None:
            raise ValueError(f"{case_name}: unsupported reference relation marker {marker!r}")
        relations.append(ReferenceRelation(source_member, target_member, marker, family))
    if not relations:
        raise ValueError(f"{case_name}: reference file contains no alignment Cells")
    return tuple(relations)


def _literal_values(graph: Graph, member: URIRef, predicates: Iterable[URIRef]) -> tuple[str, ...]:
    values = {
        str(value).strip()
        for predicate in predicates
        for value in graph.objects(member, predicate)
        if isinstance(value, Literal) and str(value).strip()
    }
    return tuple(sorted(values, key=lambda value: (value.casefold(), value)))


def _predicate_literals_by_local_name(
    graph: Graph,
    member: URIRef,
    names: frozenset[str],
) -> tuple[str, ...]:
    values = {
        str(value).strip()
        for predicate, value in graph.predicate_objects(member)
        if _local_name(predicate).casefold() in names and isinstance(value, Literal) and str(value).strip()
    }
    return tuple(sorted(values, key=lambda value: (value.casefold(), value)))


def parse_ontology(
    data: bytes,
    *,
    release: str,
    required_members: Iterable[str],
) -> tuple[tuple[AtlasConcept, ...], dict[str, int]]:
    """Reduce one OWL/RDF ontology to the Atlas retrieval surface."""

    graph = Graph()
    graph.parse(data=data, format="xml")
    members = {subject for subject in graph.subjects(RDF.type, OWL.Class) if isinstance(subject, URIRef)}
    # OAEI's published class counts include the universal OWL class even when
    # an RDF file leaves its declaration implicit.
    members.add(OWL.Thing)
    members.update(URIRef(value) for value in required_members)

    raw: dict[str, dict[str, object]] = {}
    fallback_labels = 0
    for member in sorted(members, key=str):
        preferred = _literal_values(graph, member, (SKOS.prefLabel, RDFS.label))
        if preferred:
            pref_label = preferred[0]
        else:
            pref_label = _fallback_label(str(member))
            fallback_labels += 1
        alternates = set(_literal_values(graph, member, (SKOS.altLabel, SKOS.hiddenLabel)))
        alternates.update(
            _predicate_literals_by_local_name(
                graph,
                member,
                frozenset({"alternativeterm", "exactsynonym", "hasexactsynonym", "synonym"}),
            )
        )
        alternates.discard(pref_label)
        definitions = _literal_values(graph, member, (SKOS.definition,))
        definitions += _predicate_literals_by_local_name(
            graph,
            member,
            frozenset({"definition", "description"}),
        )
        scope_notes = _literal_values(graph, member, (SKOS.scopeNote, RDFS.comment))
        parents = {
            str(value)
            for value in (*graph.objects(member, RDFS.subClassOf), *graph.objects(member, SKOS.broader))
            if isinstance(value, URIRef) and value in members and value != member
        }
        raw[str(member)] = {
            "pref": pref_label,
            "alts": tuple(sorted(alternates, key=lambda value: (value.casefold(), value))),
            "definition": definitions[0] if definitions else None,
            "scope": scope_notes[0] if scope_notes else None,
            "parents": tuple(sorted(parents)),
        }

    children: dict[str, list[str]] = defaultdict(list)
    for member, row in raw.items():
        for parent in row["parents"]:
            children[str(parent)].append(member)

    def context(member: str) -> AtlasConceptContext:
        row = raw[member]
        return AtlasConceptContext(
            member=member,
            pref_label=str(row["pref"]),
            alt_labels=tuple(row["alts"]),
            definition=row["definition"],
            scope_note=row["scope"],
        )

    concepts = tuple(
        AtlasConcept(
            member=member,
            release=release,
            pref_label=str(row["pref"]),
            alt_labels=tuple(row["alts"]),
            definition=row["definition"],
            scope_note=row["scope"],
            broader=tuple(row["parents"]),
            vocabulary=release,
            parents=tuple(context(parent) for parent in row["parents"]),
            children=tuple(context(child) for child in sorted(children.get(member, ()))),
        )
        for member, row in sorted(raw.items())
    )
    stats = {
        "concepts": len(concepts),
        "fallbackLabels": fallback_labels,
        "alternateLabels": sum(len(concept.alt_labels) for concept in concepts),
        "definitions": sum(concept.definition is not None for concept in concepts),
        "scopeNotes": sum(concept.scope_note is not None for concept in concepts),
        "hierarchyEdges": sum(len(concept.broader) for concept in concepts),
    }
    return concepts, stats


def load_case_from_archive(archive: zipfile.ZipFile, case_name: str) -> TypedAlignmentCase:
    """Load one named case without extracting the archive."""

    prefix = f"benchmark/{case_name}"
    names = {kind: f"{prefix}/{kind}.rdf" for kind in ("source", "target", "reference")}
    try:
        payloads = {kind: archive.read(name) for kind, name in names.items()}
    except KeyError as error:
        raise ValueError(f"archive does not contain the complete {case_name!r} case") from error
    relations = parse_reference(payloads["reference"], case_name=case_name)
    sources, source_stats = parse_ontology(
        payloads["source"],
        release=f"urn:oaei:beyond-equivalence:{case_name}:source",
        required_members=(relation.source for relation in relations),
    )
    targets, target_stats = parse_ontology(
        payloads["target"],
        release=f"urn:oaei:beyond-equivalence:{case_name}:target",
        required_members=(relation.target for relation in relations),
    )
    return TypedAlignmentCase(
        name=case_name,
        sources=sources,
        targets=targets,
        relations=relations,
        input_digests=tuple((names[kind], _sha256_bytes(payloads[kind])) for kind in sorted(names)),
        source_stats=tuple(sorted(source_stats.items())),
        target_stats=tuple(sorted(target_stats.items())),
    )


def load_cases(archive_path: Path, case_names: Sequence[str]) -> tuple[TypedAlignmentCase, ...]:
    """Load a canonical sequence of cases from one ZIP."""

    if not case_names:
        raise ValueError("at least one BeyondEquivalence case is required")
    with zipfile.ZipFile(archive_path) as archive:
        return tuple(load_case_from_archive(archive, name) for name in sorted(set(case_names)))


def candidate_input_digest(cases: Sequence[TypedAlignmentCase]) -> str:
    """Digest only facts visible to candidate discovery, never reference markers."""

    rows = []
    for case in sorted(cases, key=lambda item: item.name):
        for role, concepts in (("source", case.sources), ("target", case.targets)):
            for concept in sorted(concepts, key=lambda item: item.member):
                rows.append(
                    {
                        "case": case.name,
                        "role": role,
                        "member": concept.member,
                        "prefLabel": concept.pref_label,
                        "altLabels": list(concept.alt_labels),
                        "definition": concept.definition,
                        "scopeNote": concept.scope_note,
                        "broader": list(concept.broader),
                        "parents": [item.member for item in concept.parents],
                        "children": [item.member for item in concept.children],
                    }
                )
    return _canonical_digest(rows)


def reference_digest(cases: Sequence[TypedAlignmentCase]) -> str:
    rows = [
        {"case": case.name, "source": relation.source, "target": relation.target, "marker": relation.marker}
        for case in sorted(cases, key=lambda item: item.name)
        for relation in case.relations
    ]
    return _canonical_digest(rows)


def _all_relations(cases: Sequence[TypedAlignmentCase]) -> tuple[tuple[str, ReferenceRelation], ...]:
    return tuple(
        (case.name, relation) for case in sorted(cases, key=lambda item: item.name) for relation in case.relations
    )


def _pair_set_digest(pairs: Iterable[PairKey]) -> str:
    digest = hashlib.sha256()
    for case, source, target in sorted(set(pairs)):
        digest.update(f"{case}\t{source}\t{target}\n".encode())
    return "sha256:" + digest.hexdigest()


def _relation_counts(
    rows: Sequence[tuple[str, ReferenceRelation]],
    found_pairs: frozenset[PairKey],
) -> tuple[int, dict[str, dict[str, int | float | None]], dict[str, dict[str, int | float | None]]]:
    found = sum((case, relation.source, relation.target) in found_pairs for case, relation in rows)

    def grouped(
        values: Sequence[str], key: Callable[[ReferenceRelation], str]
    ) -> dict[str, dict[str, int | float | None]]:
        output: dict[str, dict[str, int | float | None]] = {}
        for value in values:
            selected = [(case, relation) for case, relation in rows if key(relation) == value]
            matched = sum((case, relation.source, relation.target) in found_pairs for case, relation in selected)
            output[value] = {
                "total": len(selected),
                "found": matched,
                "recall": round(matched / len(selected), 9) if selected else None,
            }
        return output

    observed_markers = {relation.marker for _case, relation in rows}
    markers = tuple(marker for marker in MARKER_ORDER if marker in observed_markers)
    return (
        found,
        grouped(markers, lambda relation: relation.marker),
        grouped(FAMILY_ORDER, lambda relation: relation.family),
    )


def summarize_pairs(
    pair_ranks: Mapping[PairKey, int],
    *,
    top_k: int,
    cases: Sequence[TypedAlignmentCase],
) -> dict[str, object]:
    """Report relation-blind candidate cost and typed reference recall."""

    selected = frozenset(pair for pair, rank in pair_ranks.items() if rank <= top_k)
    relations = _all_relations(cases)
    found, by_marker, by_family = _relation_counts(relations, selected)
    total = len(relations)
    possible_pairs = sum(len(case.sources) * len(case.targets) for case in cases)
    case_metrics = {}
    for case in sorted(cases, key=lambda item: item.name):
        case_pairs = frozenset(pair for pair in selected if pair[0] == case.name)
        case_rows = tuple((case.name, relation) for relation in case.relations)
        case_found, _markers, _families = _relation_counts(case_rows, case_pairs)
        case_possible = len(case.sources) * len(case.targets)
        case_metrics[case.name] = {
            "candidates": len(case_pairs),
            "possiblePairs": case_possible,
            "candidateFraction": round(len(case_pairs) / case_possible, 9) if case_possible else None,
            "referenceRelations": len(case.relations),
            "found": case_found,
            "recall": round(case_found / len(case.relations), 9) if case.relations else None,
        }
    return {
        "topK": top_k,
        "candidates": len(selected),
        "possiblePairs": possible_pairs,
        "candidateFraction": round(len(selected) / possible_pairs, 9) if possible_pairs else None,
        "referenceRelations": total,
        "found": found,
        "recall": round(found / total, 9) if total else None,
        "pairSetDigest": _pair_set_digest(selected),
        "byMarker": by_marker,
        "byFamily": by_family,
        "byCase": case_metrics,
    }


def _miss_patterns(
    pair_ranks: Mapping[PairKey, int],
    *,
    maximum: int,
    cases: Sequence[TypedAlignmentCase],
    example_limit: int = 12,
) -> dict[str, object]:
    selected = {pair for pair, rank in pair_ranks.items() if rank <= maximum}
    concepts = {(case.name, concept.member): concept for case in cases for concept in (*case.sources, *case.targets)}
    missed = [
        (case, relation)
        for case, relation in _all_relations(cases)
        if (case, relation.source, relation.target) not in selected
    ]
    result: dict[str, object] = {"total": len(missed), "byFamily": {}, "byMarker": {}}
    for family in FAMILY_ORDER:
        rows = [(case, relation) for case, relation in missed if relation.family == family]
        examples = []
        for case, relation in rows[:example_limit]:
            examples.append(
                {
                    "case": case,
                    "marker": relation.marker,
                    "source": relation.source,
                    "sourceLabel": concepts[(case, relation.source)].pref_label,
                    "target": relation.target,
                    "targetLabel": concepts[(case, relation.target)].pref_label,
                }
            )
        result["byFamily"][family] = {"count": len(rows), "examples": examples}
    for marker in MARKER_ORDER:
        count = sum(relation.marker == marker for _case, relation in missed)
        if count or any(relation.marker == marker for _case, relation in _all_relations(cases)):
            result["byMarker"][marker] = count
    return result


def arm_report(
    name: str,
    pair_ranks: Mapping[PairKey, int],
    *,
    top_ks: Sequence[int],
    cases: Sequence[TypedAlignmentCase],
    metadata: Mapping[str, object] | None = None,
) -> dict[str, object]:
    maximum = max(top_ks)
    return {
        "name": name,
        **dict(metadata or {}),
        "results": [summarize_pairs(pair_ranks, top_k=top_k, cases=cases) for top_k in top_ks],
        "missedAtMaximumK": _miss_patterns(pair_ranks, maximum=maximum, cases=cases),
    }


def merge_ranks(*rank_maps: Mapping[PairKey, int]) -> dict[PairKey, int]:
    """Union arms while preserving the minimum bidirectional rank."""

    result: dict[PairKey, int] = {}
    for ranks in rank_maps:
        for pair, rank in ranks.items():
            result[pair] = min(rank, result.get(pair, rank))
    return result


def production_floor(
    cases: Sequence[TypedAlignmentCase],
) -> tuple[dict[PairKey, int], dict[str, object], dict[str, frozenset[PairKey]]]:
    """Run the exact current production lexical floor from qualification.py."""

    started = time.monotonic()
    ranks: dict[PairKey, int] = {}
    by_generation: dict[str, set[PairKey]] = {name: set() for name in GENERATION_CLASSES}
    for case in sorted(cases, key=lambda item: item.name):
        for candidate in generate_candidate_pairs(case.sources, case.targets, production=True):
            key = (case.name, *candidate.key)
            ranks[key] = 1
            by_generation[candidate.generation_class].add(key)
    frozen = {name: frozenset(values) for name, values in by_generation.items()}
    metadata = {
        "implementation": "refspec.atlas.qualification.generate_candidate_pairs(production=True)",
        "coverageMode": "allDeterministicallyGeneratedCandidates",
        "generationClasses": {
            name: summarize_pairs({pair: 1 for pair in frozen[name]}, top_k=1, cases=cases)
            for name in GENERATION_CLASSES
        },
        "elapsedSeconds": round(time.monotonic() - started, 3),
    }
    return ranks, metadata, frozen


def sparse_graph_arms(
    cases: Sequence[TypedAlignmentCase],
    *,
    maximum: int,
    equality_anchors: Mapping[str, frozenset[tuple[str, str]]],
) -> tuple[dict[str, dict[PairKey, int]], dict[str, object]]:
    """Run deterministic sparse views, identifier equality, and one-hop graph expansion."""

    started = time.monotonic()
    arms: dict[str, dict[PairKey, int]] = {view.name: {} for view in DEFAULT_SPARSE_VIEWS}
    arms["normalizedIdentifierEquality"] = {}
    arms["exactAnchorGraph"] = {}
    arms["exactAndMutualTop1Graph"] = {}
    hit_digests: dict[str, dict[str, str]] = defaultdict(dict)

    for case in sorted(cases, key=lambda item: item.name):
        case_view_hits = {}
        mutual_anchors: set[tuple[str, str]] = set()
        for view in DEFAULT_SPARSE_VIEWS:
            hits = bidirectional_sparse_neighbors(case.sources, case.targets, view=view, top_k=maximum)
            case_view_hits[view.name] = hits
            hit_digests[view.name][case.name] = retrieval_digest(hits)
            for hit in hits:
                ranks = [rank for rank in (hit.source_rank, hit.target_rank) if rank is not None]
                if ranks:
                    key = (case.name, hit.source_member, hit.target_member)
                    arms[view.name][key] = min(min(ranks), arms[view.name].get(key, maximum + 1))
                if hit.source_rank == 1 and hit.target_rank == 1:
                    mutual_anchors.add(hit.key)

        identifier_hits = exact_identifier_neighbors(case.sources, case.targets)
        hit_digests["normalizedIdentifierEquality"][case.name] = retrieval_digest(identifier_hits)
        for hit in identifier_hits:
            arms["normalizedIdentifierEquality"][(case.name, *hit.key)] = 1

        exact = set(equality_anchors.get(case.name, frozenset()))
        exact_graph = graph_neighborhood_neighbors(case.sources, case.targets, exact)
        mutual_graph = graph_neighborhood_neighbors(case.sources, case.targets, exact | mutual_anchors)
        hit_digests["exactAnchorGraph"][case.name] = retrieval_digest(exact_graph)
        hit_digests["exactAndMutualTop1Graph"][case.name] = retrieval_digest(mutual_graph)
        for hit in exact_graph:
            arms["exactAnchorGraph"][(case.name, *hit.key)] = 1
        for hit in mutual_graph:
            arms["exactAndMutualTop1Graph"][(case.name, *hit.key)] = 1

    metadata = {
        "implementation": "refspec.atlas.candidate_retrieval deterministic integer sparse and one-hop graph",
        "maximumRank": maximum,
        "anchors": "production preferred/alternate equality plus mutual top-1 sparse pairs",
        "hitDigestsByArmAndCase": {name: dict(sorted(values.items())) for name, values in sorted(hit_digests.items())},
        "elapsedSeconds": round(time.monotonic() - started, 3),
    }
    return arms, metadata


def _rapidfuzz_components() -> tuple[Any, Any, Any, Any, Any]:
    try:
        import numpy as np
        import rapidfuzz
        from rapidfuzz import fuzz, process
        from rapidfuzz.distance import Levenshtein
    except ImportError as error:
        raise RuntimeError(
            "RapidFuzz is required unless --skip-rapidfuzz is set; run with uv run --with 'rapidfuzz==3.14.3'"
        ) from error
    return np, rapidfuzz, fuzz, process, Levenshtein


def _rapid_scorer(spec: RapidFuzzSpec) -> tuple[Callable[..., Any], int]:
    _np, _rapidfuzz, fuzz, _process, levenshtein = _rapidfuzz_components()
    scorers: dict[str, tuple[Callable[..., Any], int]] = {
        "levenshtein-distance": (levenshtein.distance, 1),
        "normalized-levenshtein": (levenshtein.normalized_similarity, 1_000_000),
        "token-set-ratio": (fuzz.token_set_ratio, 1_000_000),
        "partial-ratio": (fuzz.partial_ratio, 1_000_000),
    }
    return scorers[spec.metric]


def run_rapidfuzz_arm(
    cases: Sequence[TypedAlignmentCase],
    *,
    spec: RapidFuzzSpec,
    maximum: int,
    block_size: int,
    workers: int,
) -> tuple[dict[PairKey, int], dict[str, object]]:
    """Run exact bidirectional RapidFuzz ranking in fixed score blocks."""

    np, rapidfuzz, _fuzz, process, _levenshtein = _rapidfuzz_components()
    scorer, multiplier = _rapid_scorer(spec)
    ranks: dict[PairKey, int] = {}
    feature_hasher = hashlib.sha256()
    ranking_hasher = hashlib.sha256()
    started = time.monotonic()

    def score(queries: Sequence[str], choices: Sequence[str]) -> Any:
        return process.cdist(
            list(queries),
            list(choices),
            scorer=scorer,
            score_multiplier=multiplier,
            dtype=np.int32,
            workers=workers,
        )

    for case in sorted(cases, key=lambda item: item.name):
        sources = tuple(sorted(case.sources, key=lambda item: item.member))
        targets = tuple(sorted(case.targets, key=lambda item: item.member))
        source_texts = tuple(lexical_representation(concept, spec.representation) for concept in sources)
        target_texts = tuple(lexical_representation(concept, spec.representation) for concept in targets)
        for role, concepts, texts in (("source", sources, source_texts), ("target", targets, target_texts)):
            for concept, text_value in zip(concepts, texts, strict=True):
                feature_hasher.update(f"{case.name}\t{role}\t{concept.member}\t{text_value}\n".encode())

        forward_limit = min(maximum, len(targets))
        for start in range(0, len(sources), block_size):
            matrix = score(source_texts[start : start + block_size], target_texts)
            ordered_values = -matrix.astype(np.int64) if spec.higher_is_better else matrix.astype(np.int64)
            orders = np.argsort(ordered_values, axis=1, kind="stable")[:, :forward_limit]
            for local_source, selected_targets in enumerate(orders):
                source_index = start + local_source
                for rank, target_value in enumerate(selected_targets, start=1):
                    target_index = int(target_value)
                    key = (case.name, sources[source_index].member, targets[target_index].member)
                    ranks[key] = min(rank, ranks.get(key, maximum + 1))
                    ranking_hasher.update(
                        f"{case.name}\tforward\t{key[1]}\t{key[2]}\t{rank}\t"
                        f"{int(matrix[local_source, target_index])}\n".encode()
                    )

        reverse_limit = min(maximum, len(sources))
        for start in range(0, len(targets), block_size):
            matrix = score(target_texts[start : start + block_size], source_texts)
            ordered_values = -matrix.astype(np.int64) if spec.higher_is_better else matrix.astype(np.int64)
            orders = np.argsort(ordered_values, axis=1, kind="stable")[:, :reverse_limit]
            for local_target, selected_sources in enumerate(orders):
                target_index = start + local_target
                for rank, source_value in enumerate(selected_sources, start=1):
                    source_index = int(source_value)
                    key = (case.name, sources[source_index].member, targets[target_index].member)
                    ranks[key] = min(rank, ranks.get(key, maximum + 1))
                    ranking_hasher.update(
                        f"{case.name}\treverse\t{key[2]}\t{key[1]}\t{rank}\t"
                        f"{int(matrix[local_target, source_index])}\n".encode()
                    )

    metadata = {
        "metric": spec.metric,
        "representation": spec.representation,
        "scoreDirection": "higher-first" if spec.higher_is_better else "lower-first",
        "execution": "exact bidirectional fixed-size score blocks",
        "scoreBlockRows": block_size,
        "workers": workers,
        "rapidfuzzVersion": rapidfuzz.__version__,
        "featureDigest": "sha256:" + feature_hasher.hexdigest(),
        "rankingDigest": "sha256:" + ranking_hasher.hexdigest(),
        "elapsedSeconds": round(time.monotonic() - started, 3),
    }
    return ranks, metadata


def _normalize_rows(values: Any) -> Any:
    import numpy as np

    matrix = np.asarray(values, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms == 0, 1, norms)


def _dense_direction(
    *,
    case_name: str,
    query_ids: Sequence[str],
    document_ids: Sequence[str],
    query_vectors: Any,
    document_vectors: Any,
    maximum: int,
    block_size: int,
    reverse: bool,
    ranks: dict[PairKey, int],
    ranking_hasher: Any,
) -> None:
    import numpy as np

    limit = min(maximum, len(document_ids))
    for start in range(0, len(query_ids), block_size):
        stop = min(start + block_size, len(query_ids))
        scores = query_vectors[start:stop] @ document_vectors.T
        orders = np.argsort(-scores, axis=1, kind="stable")[:, :limit]
        for local_query, selected_documents in enumerate(orders):
            query_index = start + local_query
            for rank, document_value in enumerate(selected_documents, start=1):
                document_index = int(document_value)
                if reverse:
                    key = (case_name, document_ids[document_index], query_ids[query_index])
                else:
                    key = (case_name, query_ids[query_index], document_ids[document_index])
                ranks[key] = min(rank, ranks.get(key, maximum + 1))
                score = float(scores[local_query, document_index])
                ranking_hasher.update(
                    f"{case_name}\t{'reverse' if reverse else 'forward'}\t{key[1]}\t{key[2]}\t{rank}\t".encode()
                )
                ranking_hasher.update(struct.pack("<f", score))


def run_dense_arm(
    cases: Sequence[TypedAlignmentCase],
    *,
    model_name: str,
    maximum: int,
    block_size: int,
) -> tuple[dict[PairKey, int], dict[str, object]]:
    """Run one local exact dense challenger with bounded score matrices."""

    try:
        import fastembed
        import numpy as np
        from fastembed import TextEmbedding
    except ImportError as error:
        raise RuntimeError(
            "FastEmbed is required unless --skip-dense is set; run with uv run --with 'fastembed==0.8.0'"
        ) from error

    model = TextEmbedding(model_name=model_name)
    query_cache: dict[str, Any] = {}
    passage_cache: dict[str, Any] = {}
    text_hasher = hashlib.sha256()
    ranking_hasher = hashlib.sha256()
    ranks: dict[PairKey, int] = {}
    started = time.monotonic()

    def embed(texts: Sequence[str], *, query: bool) -> Any:
        cache = query_cache if query else passage_cache
        missing = sorted(set(texts) - set(cache))
        if missing:
            encoder = model.query_embed if query else model.passage_embed
            values = _normalize_rows(list(encoder(missing)))
            for text_value, vector in zip(missing, values, strict=True):
                cache[text_value] = vector
        return np.stack([cache[text_value] for text_value in texts])

    for case in sorted(cases, key=lambda item: item.name):
        sources = tuple(sorted(case.sources, key=lambda item: item.member))
        targets = tuple(sorted(case.targets, key=lambda item: item.member))
        source_ids = tuple(concept.member for concept in sources)
        target_ids = tuple(concept.member for concept in targets)
        source_texts = tuple(structured_embedding_text(concept) for concept in sources)
        target_texts = tuple(structured_embedding_text(concept) for concept in targets)
        for role, ids, texts in (("source", source_ids, source_texts), ("target", target_ids, target_texts)):
            for member, text_value in zip(ids, texts, strict=True):
                text_hasher.update(f"{case.name}\t{role}\t{member}\t{text_value}\n".encode())
        source_query = embed(source_texts, query=True)
        target_passage = embed(target_texts, query=False)
        target_query = embed(target_texts, query=True)
        source_passage = embed(source_texts, query=False)
        _dense_direction(
            case_name=case.name,
            query_ids=source_ids,
            document_ids=target_ids,
            query_vectors=source_query,
            document_vectors=target_passage,
            maximum=maximum,
            block_size=block_size,
            reverse=False,
            ranks=ranks,
            ranking_hasher=ranking_hasher,
        )
        _dense_direction(
            case_name=case.name,
            query_ids=target_ids,
            document_ids=source_ids,
            query_vectors=target_query,
            document_vectors=source_passage,
            maximum=maximum,
            block_size=block_size,
            reverse=True,
            ranks=ranks,
            ranking_hasher=ranking_hasher,
        )

    vector_hasher = hashlib.sha256()
    for role, cache in (("query", query_cache), ("passage", passage_cache)):
        for text_value, vector in sorted(cache.items()):
            vector_hasher.update(f"{role}\t{text_value}\n".encode())
            vector_hasher.update(np.asarray(vector, dtype="<f4").tobytes(order="C"))
    backend = getattr(model, "model", None)
    description = getattr(backend, "model_description", None)
    sources = getattr(description, "sources", None)
    model_directory = getattr(backend, "_model_dir", None)
    model_file = getattr(description, "model_file", None)
    artifact = Path(model_directory) / model_file if model_directory is not None and model_file else None
    provenance = {
        "modelSource": getattr(sources, "hf", None),
        "modelRevision": Path(model_directory).name if model_directory is not None else None,
        "modelArtifactDigest": _sha256_path(artifact) if artifact is not None and artifact.is_file() else None,
        "modelArtifactBytes": artifact.stat().st_size if artifact is not None and artifact.is_file() else None,
    }
    metadata = {
        "model": model_name,
        **provenance,
        "runtime": "FastEmbed local ONNX",
        "fastembedVersion": getattr(fastembed, "__version__", importlib.metadata.version("fastembed")),
        "numpyVersion": np.__version__,
        "representation": "structured relation-neutral label, aliases, identifier, notes, parents, and children",
        "queryMode": "model-native query_embed in both source-to-target and target-to-source directions",
        "execution": "exact bidirectional cosine ranking in fixed query blocks",
        "scoreBlockRows": block_size,
        "textDigest": "sha256:" + text_hasher.hexdigest(),
        "vectorDigest": "sha256:" + vector_hasher.hexdigest(),
        "rankingDigest": "sha256:" + ranking_hasher.hexdigest(),
        "elapsedSeconds": round(time.monotonic() - started, 3),
    }
    return ranks, metadata


def _stage_cost(
    base: Mapping[PairKey, int],
    addition: Mapping[PairKey, int],
    *,
    top_k: int,
    cases: Sequence[TypedAlignmentCase],
) -> dict[str, object]:
    base_pairs = {pair for pair, rank in base.items() if rank <= top_k}
    addition_pairs = {pair for pair, rank in addition.items() if rank <= top_k}
    added_pairs = addition_pairs - base_pairs
    relation_rows = _all_relations(cases)
    base_found = {
        (case, relation.source, relation.target, relation.marker)
        for case, relation in relation_rows
        if (case, relation.source, relation.target) in base_pairs
    }
    rescued_rows = [
        (case, relation)
        for case, relation in relation_rows
        if (case, relation.source, relation.target) in added_pairs
        and (case, relation.source, relation.target, relation.marker) not in base_found
    ]
    rescued_pairs = frozenset((case, relation.source, relation.target) for case, relation in rescued_rows)
    _found, _markers, by_family = _relation_counts(rescued_rows, rescued_pairs)
    return {
        "topK": top_k,
        "addedCandidates": len(added_pairs),
        "newReferenceRelations": len(rescued_rows),
        "candidatesPerNewReference": round(len(added_pairs) / len(rescued_rows), 3) if rescued_rows else None,
        "newReferenceByFamily": by_family,
        "addedPairSetDigest": _pair_set_digest(added_pairs),
    }


def _staged_rescues(
    floor: Mapping[PairKey, int],
    sparse: Mapping[PairKey, int],
    rapid: Mapping[PairKey, int],
    wordnet_arms: Mapping[str, Mapping[PairKey, int]],
    dense: Mapping[PairKey, int],
    *,
    top_ks: Sequence[int],
    cases: Sequence[TypedAlignmentCase],
) -> list[dict[str, object]]:
    floor_sparse = merge_ranks(floor, sparse)
    floor_sparse_rapid = merge_ranks(floor_sparse, rapid)
    stages: list[tuple[str, Mapping[PairKey, int], Mapping[PairKey, int]]] = [
        ("sparseGraphOverProductionFloor", floor, sparse),
        ("rapidFuzzOverFloorAndSparseGraph", floor_sparse, rapid),
    ]
    deterministic = floor_sparse_rapid
    for name, ranks in wordnet_arms.items():
        depth = name.removeprefix("openEnglishWordNetDepth")
        stages.append((f"wordNetDepth{depth}OverPriorDeterministic", deterministic, ranks))
        deterministic = merge_ranks(deterministic, ranks)
    stages.append(("denseOverAllDeterministic", deterministic, dense))
    return [
        {
            "stage": name,
            "results": [_stage_cost(base, addition, top_k=top_k, cases=cases) for top_k in top_ks],
        }
        for name, base, addition in stages
    ]


def _arm_unique_rescues(
    arms: Mapping[str, Mapping[PairKey, int]],
    *,
    maximum: int,
    cases: Sequence[TypedAlignmentCase],
) -> list[dict[str, object]]:
    relation_rows = _all_relations(cases)
    result = []
    for name in sorted(arms):
        own = {pair for pair, rank in arms[name].items() if rank <= maximum}
        other = {
            pair
            for other_name, ranks in arms.items()
            if other_name != name
            for pair, rank in ranks.items()
            if rank <= maximum
        }
        unique_pairs = frozenset(own - other)
        unique_rows = [
            (case, relation)
            for case, relation in relation_rows
            if (case, relation.source, relation.target) in unique_pairs
        ]
        found, by_marker, by_family = _relation_counts(unique_rows, unique_pairs)
        result.append(
            {
                "arm": name,
                "topK": maximum,
                "uniqueCandidates": len(unique_pairs),
                "uniqueReferenceRelations": found,
                "byMarker": by_marker,
                "byFamily": by_family,
                "pairSetDigest": _pair_set_digest(unique_pairs),
            }
        )
    return result


def _without_runtime(value: object) -> object:
    if isinstance(value, dict):
        return {key: _without_runtime(item) for key, item in value.items() if key != "elapsedSeconds"}
    if isinstance(value, list):
        return [_without_runtime(item) for item in value]
    return value


def _positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--wordnet", type=Path)
    parser.add_argument("--wordnet-depth", action="append", type=_positive_integer, dest="wordnet_depths")
    parser.add_argument("--case", action="append", choices=DEFAULT_CASES, dest="cases")
    parser.add_argument("--top-k", action="append", type=_positive_integer, dest="top_ks")
    parser.add_argument("--dense-model", default=DEFAULT_DENSE_MODEL)
    parser.add_argument("--query-block-size", type=_positive_integer, default=DEFAULT_QUERY_BLOCK_SIZE)
    parser.add_argument("--rapidfuzz-workers", type=int, default=1)
    parser.add_argument("--skip-rapidfuzz", action="store_true")
    parser.add_argument("--skip-wordnet", action="store_true")
    parser.add_argument("--skip-dense", action="store_true")
    parser.add_argument("--allow-unpinned-archive", action="store_true")
    parser.add_argument("--allow-unpinned-wordnet", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    started = time.monotonic()
    top_ks = tuple(sorted(set(args.top_ks or DEFAULT_TOP_K)))
    archive_digest = _sha256_path(args.archive)
    expected = "sha256:" + OFFICIAL_ARCHIVE_SHA256
    if not args.allow_unpinned_archive and archive_digest != expected:
        raise ValueError(
            f"archive digest {archive_digest} does not match the official pinned release {expected}; "
            "use --allow-unpinned-archive only for an intentional fixture"
        )
    cases = load_cases(args.archive, args.cases or DEFAULT_CASES)
    maximum = max(top_ks)

    floor_ranks, floor_metadata, floor_classes = production_floor(cases)
    equality_anchors: dict[str, frozenset[tuple[str, str]]] = {}
    equality_classes = ("normalizedLabelEquality", "alternateLabelEquality")
    for case in cases:
        equality_anchors[case.name] = frozenset(
            (source, target)
            for name in equality_classes
            for candidate_case, source, target in floor_classes[name]
            if candidate_case == case.name
        )

    sparse_arms, sparse_metadata = sparse_graph_arms(
        cases,
        maximum=maximum,
        equality_anchors=equality_anchors,
    )
    sparse_union = merge_ranks(*sparse_arms.values())

    rapid_arms: dict[str, dict[PairKey, int]] = {}
    rapid_metadata: dict[str, dict[str, object]] = {}
    if not args.skip_rapidfuzz:
        for spec in RAPIDFUZZ_SPECS:
            ranks, metadata = run_rapidfuzz_arm(
                cases,
                spec=spec,
                maximum=maximum,
                block_size=args.query_block_size,
                workers=args.rapidfuzz_workers,
            )
            rapid_arms[spec.name] = ranks
            rapid_metadata[spec.name] = metadata
    rapid_union = merge_ranks(*rapid_arms.values())

    wordnet_arms: dict[str, dict[PairKey, int]] = {}
    wordnet_metadata: dict[str, dict[str, object]] = {}
    if not args.skip_wordnet:
        if args.wordnet is None:
            raise ValueError("--wordnet is required unless --skip-wordnet is set")
        wordnet_digest = _sha256_path(args.wordnet)
        expected_wordnet = "sha256:" + OEWN_ARCHIVE_SHA256
        if not args.allow_unpinned_wordnet and wordnet_digest != expected_wordnet:
            raise ValueError(
                f"WordNet digest {wordnet_digest} does not match pinned OEWN 2025 {expected_wordnet}; "
                "use --allow-unpinned-wordnet only for an intentional fixture"
            )
        wordnet_index = load_wordnet(args.wordnet)
        for depth in sorted(set(args.wordnet_depths or (2, 3, 4))):
            name = f"openEnglishWordNetDepth{depth}"
            ranks, metadata = run_wordnet_arm(cases, index=wordnet_index, maximum_depth=depth)
            wordnet_arms[name] = ranks
            wordnet_metadata[name] = {"assetDigest": wordnet_digest, **metadata}
    wordnet_union = merge_ranks(*wordnet_arms.values())

    dense_ranks: dict[PairKey, int] = {}
    dense_metadata: dict[str, object] = {"status": "skipped"}
    if not args.skip_dense:
        dense_ranks, dense_metadata = run_dense_arm(
            cases,
            model_name=args.dense_model,
            maximum=maximum,
            block_size=args.query_block_size,
        )

    pre_wordnet_deterministic = merge_ranks(floor_ranks, sparse_union, rapid_union)
    deterministic_union = merge_ranks(pre_wordnet_deterministic, wordnet_union)
    all_union = merge_ranks(deterministic_union, dense_ranks)
    individual_arms: dict[str, Mapping[PairKey, int]] = {
        "productionFloor": floor_ranks,
        **sparse_arms,
        **rapid_arms,
    }
    individual_arms.update(wordnet_arms)
    if dense_ranks:
        individual_arms["denseStructuredBge"] = dense_ranks

    relation_counts = Counter(relation.marker for case in cases for relation in case.relations)
    family_counts = Counter(relation.family for case in cases for relation in case.relations)
    report: dict[str, object] = {
        "type": "BeyondEquivalenceTypedRelationCandidateBenchmark",
        "schemaVersion": "1.0",
        "purpose": "relation-blind candidate discovery before semantic judging",
        "providerCalls": 0,
        "domainGuardrail": {
            "productionScope": (
                "English regulatory, legislative, public-policy, and social-science subject vocabularies"
            ),
            "benchmarkRole": (
                "typed-relation stress evidence only; text, literature, furniture, groceries, and clothing "
                "are not a representative production corpus"
            ),
            "decisionBoundary": (
                "retail taxonomy behavior, formal overlap, and this benchmark's depth saturation do not set "
                "the Atlas production floor"
            ),
            "languageScope": "English-only production v1; multilingual retrieval is outside this decision",
        },
        "source": {
            "track": "OAEI 2025 BeyondEquivalence",
            "trackUrl": OFFICIAL_TRACK_URL,
            "recordUrl": OFFICIAL_RECORD_URL,
            "license": OFFICIAL_LICENSE,
            "licenseScope": (
                "Selected g3-g7 STROMA/TaSeR cases. The eClass-specific exception described by the "
                "publisher does not apply to these selected cases."
            ),
            "archive": str(args.archive),
            "archiveDigest": archive_digest,
        },
        "cases": [
            {
                "name": case.name,
                "source": dict(case.source_stats),
                "target": dict(case.target_stats),
                "referenceRelations": len(case.relations),
                "relationMarkers": dict(sorted(Counter(row.marker for row in case.relations).items())),
                "inputDigests": dict(case.input_digests),
            }
            for case in cases
        ],
        "candidateInputDigest": candidate_input_digest(cases),
        "referenceDigest": reference_digest(cases),
        "referenceRelationCount": sum(relation_counts.values()),
        "referenceCountsByMarker": {
            marker: relation_counts.get(marker, 0) for marker in MARKER_ORDER if relation_counts.get(marker, 0)
        },
        "referenceCountsByFamily": {family: family_counts.get(family, 0) for family in FAMILY_ORDER},
        "disjointControl": {
            "referenceRows": family_counts.get("disjointOrRejection", 0),
            "status": "zero-opportunity: no disjoint marker occurs in the official archive",
            "fabricatedNegatives": 0,
            "note": (
                "The production floor's seeded randomNegativeControl candidates are retrieval controls, "
                "not disjoint reference gold."
            ),
        },
        "skosAnalogy": SKOS_ANALOGY,
        "topK": list(top_ks),
        "possiblePairs": sum(len(case.sources) * len(case.targets) for case in cases),
        "topKExhaustsOneSide": [case.name for case in cases if min(len(case.sources), len(case.targets)) <= maximum],
        "depthSaturationNote": (
            "Bidirectional top-K becomes a complete Cartesian candidate set for a case when K is at least "
            "the smaller vocabulary size; saturated cases cannot support a cost-sensitive recall claim."
        ),
        "queryBlockRows": args.query_block_size,
        "productionFloor": arm_report(
            "productionFloor",
            floor_ranks,
            top_ks=top_ks,
            cases=cases,
            metadata=floor_metadata,
        ),
        "deterministicSparseGraph": {
            **sparse_metadata,
            "arms": [
                arm_report(name, ranks, top_ks=top_ks, cases=cases) for name, ranks in sorted(sparse_arms.items())
            ],
            "union": arm_report("sparseGraphUnion", sparse_union, top_ks=top_ks, cases=cases),
        },
        "rapidFuzzControls": {
            "status": "skipped" if args.skip_rapidfuzz else "completed",
            "arms": [
                arm_report(
                    name,
                    ranks,
                    top_ks=top_ks,
                    cases=cases,
                    metadata=rapid_metadata[name],
                )
                for name, ranks in sorted(rapid_arms.items())
            ],
            "union": arm_report("selectedRapidFuzzUnion", rapid_union, top_ks=top_ks, cases=cases),
        },
        "wordNetLexicalKnowledge": {
            "status": "skipped" if args.skip_wordnet else "completed",
            "arms": [
                arm_report(
                    name,
                    ranks,
                    top_ks=top_ks,
                    cases=cases,
                    metadata=wordnet_metadata[name],
                )
                for name, ranks in wordnet_arms.items()
            ],
            "union": arm_report("openEnglishWordNetDepthUnion", wordnet_union, top_ks=top_ks, cases=cases),
            "depthFrontier": [
                {
                    "wordNetArm": name,
                    "deterministicUnion": arm_report(
                        f"allDeterministicThrough{name}",
                        merge_ranks(pre_wordnet_deterministic, ranks),
                        top_ks=top_ks,
                        cases=cases,
                    ),
                    "allUnionWithDense": arm_report(
                        f"allThrough{name}WithDense",
                        merge_ranks(pre_wordnet_deterministic, ranks, dense_ranks),
                        top_ks=top_ks,
                        cases=cases,
                    ),
                }
                for name, ranks in wordnet_arms.items()
            ],
        },
        "denseChallenger": arm_report(
            "denseStructuredBge",
            dense_ranks,
            top_ks=top_ks,
            cases=cases,
            metadata=dense_metadata,
        ),
        "unions": [
            arm_report("productionFloor", floor_ranks, top_ks=top_ks, cases=cases),
            arm_report("sparseGraphUnion", sparse_union, top_ks=top_ks, cases=cases),
            arm_report("selectedRapidFuzzUnion", rapid_union, top_ks=top_ks, cases=cases),
            arm_report("openEnglishWordNetDepthUnion", wordnet_union, top_ks=top_ks, cases=cases),
            arm_report("allDeterministicUnion", deterministic_union, top_ks=top_ks, cases=cases),
            arm_report("dense", dense_ranks, top_ks=top_ks, cases=cases),
            arm_report("allUnion", all_union, top_ks=top_ks, cases=cases),
        ],
        "stagedUniqueRescues": _staged_rescues(
            floor_ranks,
            sparse_union,
            rapid_union,
            wordnet_arms,
            dense_ranks,
            top_ks=top_ks,
            cases=cases,
        ),
        "individualArmUniqueRescuesAtMaximumK": _arm_unique_rescues(
            individual_arms,
            maximum=maximum,
            cases=cases,
        ),
        "toolDigest": _sha256_path(Path(__file__).resolve()),
        "elapsedSeconds": round(time.monotonic() - started, 3),
    }
    report["deterministicResultDigest"] = _canonical_digest(_without_runtime(report))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(canonical_json(report) + "\n", encoding="utf-8")
    print(
        canonical_json(
            {
                "deterministicResultDigest": report["deterministicResultDigest"],
                "elapsedSeconds": report["elapsedSeconds"],
                "output": str(args.output),
                "outputDigest": _sha256_path(args.output),
                "referenceRelations": report["referenceRelationCount"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
