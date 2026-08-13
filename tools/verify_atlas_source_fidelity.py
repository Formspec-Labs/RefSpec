"""Independent source-fidelity verifier for a packed RefSpec Atlas 3.1 distribution.

The eleven acceptance gates recorded in ``atlas-acceptance.json`` prove that a
distribution is internally consistent: canonical JSON, schema conformance, SHACL
conformance, referential closure, projection determinism, reasoner isolation, and
a ledger that reconciles with the graph it was written from. Every one of those
gates reads only the built artifact. None of them opens the pinned publisher
bytes. A build that read every publisher file, transcribed every label wrong, and
then wrote a self-consistent ledger would pass all eleven with ``verdict: passed``.

This verifier closes that gap from the other side. It parses the pinned
publisher bytes with stock format libraries, streams what the Atlas actually
asserts out of the distribution packs, and compares the two directly. It imports
no RefSpec semantic reader, builder, or normalisation code because a defect in
ingestion would be reproduced identically by any check written from the same
code, and the two would agree. It shares only the transformation-free file-pin
helper used to authenticate bytes. Agreement between a program and its own
reflection is not evidence.

The comparison includes only claims attributable to publisher inputs. Atlas-owned
release nodes, semantic rings, resource profiles, governed schemes, and class
assignments are outside its scope. The Atlas binding validator checks those
Atlas-specific structures separately; this command does not run or report it.

Two load-bearing facts about the join, stated here so they are not silently
rediscovered:

* An Atlas resource for a vocabulary source **is** the publisher's own IRI. The
  data join is IRI identity, not a minted key and not a digest. Source locators
  are adapter-specific evidence addresses and are checked independently. The one
  exceptions are checked row sources whose publishers ship no IRIs:
  ``source-extract`` joins on the source-local identity in
  ``atlas:nativePayload``, while ``source-list`` compares the complete multiset of
  publisher labels and notations. Each comparison states that narrower join in
  the receipt.
* ``atlas:sourceDigest`` is source-specific: some adapters retain a publisher
  file or archive-member digest, while others digest a constructed native
  relation. The verifier checks the applicable digest rule, but never treats a
  matching digest as a substitute for field-level comparison.

Findings are separated by who owns them. A ``source`` finding is a defect in the
publisher's own data; preserving it faithfully is correct behaviour and it never
fails the run. A ``pipeline`` finding is a difference between the publisher bytes
and what we assert about them, and it fails the run. Narrow executable policies
may define an Atlas representation only after checking their exact prerequisites
and exact permitted claim set; a policy name is never a waiver.

Usage. ``--distribution`` is required: there is no default distribution, because
a default silently audits whatever build happens to be on disk (the retired
``output/atlas-3.0-full-2026-08-07-ring-audit`` tree was exactly that). Name the
artifact, or go through the Makefile target, which names it for you::

    make audit-atlas-v3-source-fidelity \\
        ATLAS_V3_AUDIT_ROOT=output/atlas-3.1-federal-register-thesaurus-2025-04-01

    uv run python tools/verify_atlas_source_fidelity.py \\
        --distribution output/atlas-3.1-federal-register-thesaurus-2025-04-01/distribution \\
        --output findings.json

``--only NAME`` (repeatable) restricts the run to named comparisons, so a bounded
artifact costs a bounded run. It narrows what is proven, never what is claimed:
construction units owned by the comparisons left out are reported as *not
evaluated (scoped out)*, never as covered and never as failed, and the receipt
names every comparison the run skipped. Within the scope both directions still
fail closed.

Exit codes: ``0`` all checks passed and ``1`` one or more checks failed. Missing
or malformed inputs are collected as check failures so the remaining independent
inputs and checks still run.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import logging
import re
import sys
import threading
import urllib.parse
import zipfile
from collections import Counter, defaultdict
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from refspec.input_pin import read_verified_file_pin
from refspec.registry.infrastructure.source_controlled_resource import LABEL_ROLES

try:  # Python 3.14 ships zstd in the standard library.
    from compression import zstd
except ImportError:  # pragma: no cover - exercised by the older interpreter
    from backports import zstd

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
# No default distribution, deliberately. The old one
# (output/atlas-3.0-full-2026-08-07-ring-audit) outlived the wire it was built
# from and stayed on disk, so a bare invocation kept auditing a retired artifact
# and reporting a fidelity verdict about a distribution nobody ships. Same
# reasoning as ATLAS_V3_AUDIT_ROOT in the Makefile: the caller names the
# artifact under audit, every time.
DEFAULT_SOURCE_ROOT = REPOSITORY_ROOT / "output" / "registry-real-data-sources"

VERIFIER_VERSION = "atlas-source-fidelity/12"
ASSERTED_GRAPH = "urn:ref:atlas:graph:v3:asserted"
CONSTRUCTION_SUMMARY = "atlas-construction-summary.json"

RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
SKOS = "http://www.w3.org/2004/02/skos/core#"
SKOSXL = "http://www.w3.org/2008/05/skos-xl#"
XSD = "http://www.w3.org/2001/XMLSchema#"
ATLAS = "https://refspec.org/ns/atlas/v3#"
# RuleSpec's rkaf namespace. Atlas mints its evidence records in it: an
# rkaf:EvidenceBinding node and its rkaf: predicates are Atlas representation
# structure, not a publisher claim, exactly like an atlas: class is. Classifying
# only the ATLAS namespace made every evidence binding an unknown subject, so
# each one's claims were reported as escaping comparison.
RKAF = "https://rulespec.org/ns/v1#"
ATLAS_REPRESENTATION_NAMESPACES = (ATLAS, RKAF)


def _is_atlas_representation_iri(iri: str) -> bool:
    """Return whether an IRI is minted in a namespace Atlas itself owns."""
    return iri.startswith(ATLAS_REPRESENTATION_NAMESPACES)


RDF_TYPE = f"{RDF}type"
RDF_SUBJECT = f"{RDF}subject"
RDF_PREDICATE = f"{RDF}predicate"
RDF_OBJECT = f"{RDF}object"
RDF_STATEMENT = f"{RDF}Statement"

SKOS_CONCEPT = f"{SKOS}Concept"
SKOS_CONCEPT_SCHEME = f"{SKOS}ConceptScheme"
SKOS_IN_SCHEME = f"{SKOS}inScheme"
SKOS_PREF_LABEL = f"{SKOS}prefLabel"
SKOS_ALT_LABEL = f"{SKOS}altLabel"
SKOS_HIDDEN_LABEL = f"{SKOS}hiddenLabel"
SKOS_NOTATION = f"{SKOS}notation"
SKOS_DEFINITION = f"{SKOS}definition"
SKOS_EXAMPLE = f"{SKOS}example"
SKOS_NOTE = f"{SKOS}note"
SKOS_SCOPE_NOTE = f"{SKOS}scopeNote"
SKOS_EDITORIAL_NOTE = f"{SKOS}editorialNote"
SKOS_HISTORY_NOTE = f"{SKOS}historyNote"
SKOS_CHANGE_NOTE = f"{SKOS}changeNote"
SKOS_TOP_CONCEPT_OF = f"{SKOS}topConceptOf"
SKOS_HAS_TOP_CONCEPT = f"{SKOS}hasTopConcept"
XKOS_ADDITIONAL_CONTENT_NOTE = (
    "http://rdf-vocabulary.ddialliance.org/xkos#additionalContentNote"
)

SOURCE_NOTE_PREDICATES = (
    SKOS_EXAMPLE,
    SKOS_NOTE,
    SKOS_SCOPE_NOTE,
    SKOS_EDITORIAL_NOTE,
    SKOS_HISTORY_NOTE,
    SKOS_CHANGE_NOTE,
    XKOS_ADDITIONAL_CONTENT_NOTE,
)

SKOSXL_PREF_LABEL = f"{SKOSXL}prefLabel"
SKOSXL_ALT_LABEL = f"{SKOSXL}altLabel"
SKOSXL_HIDDEN_LABEL = f"{SKOSXL}hiddenLabel"
SKOSXL_LITERAL_FORM = f"{SKOSXL}literalForm"
SKOSXL_LABEL_PREDICATES = frozenset(
    {SKOSXL_PREF_LABEL, SKOSXL_ALT_LABEL, SKOSXL_HIDDEN_LABEL}
)

ATLAS_SOURCE_RECORD = f"{ATLAS}SourceRecord"
ATLAS_SOURCE_RELEASE = f"{ATLAS}SourceRelease"
ATLAS_RESOURCE = f"{ATLAS}AtlasResource"
ATLAS_RELEASE = f"{ATLAS}AtlasRelease"
ATLAS_SUBJECT_CONCEPT = f"{ATLAS}SubjectConcept"
ATLAS_ENTITY_RESOURCE = f"{ATLAS}EntityResource"
ATLAS_VALUE_RESOURCE = f"{ATLAS}ValueResource"
ATLAS_LEGAL_IDENTITY_RESOURCE = f"{ATLAS}LegalIdentityResource"
ATLAS_SOURCE_LOCATOR = f"{ATLAS}sourceLocator"
ATLAS_SOURCE_DIGEST = f"{ATLAS}sourceDigest"
ATLAS_NATIVE_PAYLOAD = f"{ATLAS}nativePayload"
ATLAS_REPRESENTS_RESOURCE = f"{ATLAS}representsResource"
ATLAS_IN_SCHEME = f"{ATLAS}inScheme"
ATLAS_RESOURCE_PROFILE = f"{ATLAS}resourceProfile"
ATLAS_SEMANTIC_RING = f"{ATLAS}semanticRing"
ATLAS_IN_RELEASE = f"{ATLAS}inRelease"
ATLAS_SOURCE_RECORD_LINK = f"{ATLAS}sourceRecord"
ATLAS_CONTENT_DIGEST = f"{ATLAS}contentDigest"
ATLAS_NOTATION = f"{ATLAS}notation"
ATLAS_DEFINITION = f"{ATLAS}definition"
ATLAS_NOTE = f"{ATLAS}note"
ATLAS_RECORD_STATUS = f"{ATLAS}recordStatus"

# Predicates Atlas mints to say where a record sits in its own representation,
# never to restate a publisher claim. Each one is admitted only on a subject the
# comparison already knows -- a publisher concept, a source-native scheme, or a
# source label node -- and stays a failure on every other subject, so an
# Atlas-minted field on a manufactured subject is still caught.
ATLAS_SOURCE_REPRESENTATION_STRUCTURE_PREDICATES = frozenset(
    {
        ATLAS_IN_RELEASE,
        ATLAS_IN_SCHEME,
        ATLAS_RESOURCE_PROFILE,
        ATLAS_SEMANTIC_RING,
        ATLAS_SOURCE_RECORD_LINK,
        ATLAS_CONTENT_DIGEST,
        # atlas:recordStatus belongs with its siblings above. The builder writes
        # the record's own lifecycle state ("active", "deprecated",
        # "boundedMappingReference") from the registry row it is minting; no
        # publisher ships a field of that shape, so there is no source claim to
        # compare it against and no direction in which a comparison could fail.
        # Where a publisher *does* flag a retired term (ELSST's owl:deprecated),
        # that flag is a publisher claim in its own right and stays declared on
        # the spec -- folding it into a status value never discharges it.
        ATLAS_RECORD_STATUS,
    }
)

DCTERMS = "http://purl.org/dc/terms/"
OWL = "http://www.w3.org/2002/07/owl#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
DCAT = "http://www.w3.org/ns/dcat#"
CDM = "http://publications.europa.eu/ontology/cdm#"
# Dataset-description vocabularies. Publishers use these to describe the files
# and releases they ship; none of them says anything about a term.
VOID = "http://rdfs.org/ns/void#"
LIME = "http://www.w3.org/ns/lemon/lime#"
MDR = "https://w3id.org/mdr#"
STMDR = "http://semanticturkey.uniroma2.it/ns/stmdr#"
ALIGNMENT = "http://knowledgeweb.semanticweb.org/heterogeneity/alignment#"
# GEMET's own schema namespace: the entity kinds it publishes beside its
# concepts (collections and a bibliographic source register).
GEMET_SCHEMA = "http://www.eionet.europa.eu/gemet/2004/06/gemet-schema.rdf#"

KNOWN_CLASS_IRIS = frozenset(
    {
        f"{DCAT}CatalogRecord",
    }
)

IRI_OBJECT_PREDICATES = frozenset(
    {
        RDF_TYPE,
        SKOS_IN_SCHEME,
        SKOSXL_PREF_LABEL,
        SKOSXL_ALT_LABEL,
        SKOSXL_HIDDEN_LABEL,
        RDF_SUBJECT,
        RDF_PREDICATE,
        RDF_OBJECT,
        ATLAS_SOURCE_LOCATOR,
        ATLAS_REPRESENTS_RESOURCE,
        ATLAS_IN_SCHEME,
        ATLAS_RESOURCE_PROFILE,
        ATLAS_SEMANTIC_RING,
    }
)
LITERAL_OBJECT_PREDICATES = frozenset(
    {
        SKOSXL_LITERAL_FORM,
        ATLAS_NATIVE_PAYLOAD,
        ATLAS_SOURCE_DIGEST,
        ATLAS_NOTATION,
        ATLAS_DEFINITION,
        ATLAS_NOTE,
    }
)

HIERARCHY_PREDICATES = (f"{SKOS}broader", f"{SKOS}narrower", f"{SKOS}related")
MAPPING_PREDICATES = (
    f"{SKOS}exactMatch",
    f"{SKOS}closeMatch",
    f"{SKOS}broadMatch",
    f"{SKOS}narrowMatch",
    f"{SKOS}relatedMatch",
)

# Mapping predicates ordered weakest to strongest. Substituting a predicate that
# appears later in this tuple for one that appears earlier is a strengthening and
# is never permitted; the publisher's own choice of strength is the assertion.
MAPPING_STRENGTH = {
    f"{SKOS}relatedMatch": 0,
    f"{SKOS}closeMatch": 1,
    f"{SKOS}broadMatch": 2,
    f"{SKOS}narrowMatch": 2,
    f"{SKOS}exactMatch": 3,
}

# These are executable policies, not count waivers.  A policy may pass only
# after its implementation proves the exact prerequisite and the exact claim
# set it permits.  Merely naming one never authorizes an arbitrary difference.
EXECUTABLE_POLICIES: Mapping[str, str] = {
    "english-label-selection": (
        "Compare every publisher label in both directions, including language and datatype; "
        "the historical policy name grants no non-English waiver."
    ),
    "english-annotation-selection": (
        "Compare every publisher definition and note in both directions; the historical policy "
        "name grants no non-English waiver."
    ),
    "skos-note-to-atlas-note": (
        "Compare each exact SKOS or XKOS note literal with generic atlas:note, reject "
        "collisions, and require the original source predicate to remain in native payload evidence."
    ),
    "top-concept-source-shape-inverse": (
        "Reverse nativePayload.topConceptOfIris into each top-concept direction that the "
        "publisher graph actually asserts, and reject claims absent in both directions."
    ),
}

DIRECT_SKOS_POLICIES = frozenset(
    {
        "english-label-selection",
        "english-annotation-selection",
        "skos-note-to-atlas-note",
        "top-concept-source-shape-inverse",
    }
)


@dataclass(frozen=True)
class Finding:
    """One observation, attributed to whoever owns the defect."""

    kind: str  # "source" or "model"
    source: str
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "source": self.source, "detail": self.detail}


@dataclass
class CheckResult:
    """Outcome of one named fidelity check."""

    name: str
    passed: bool
    summary: str
    failures: list[str] = field(default_factory=list)
    source_findings: list[Finding] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "check": self.name,
            "passed": self.passed,
            "summary": self.summary,
            "failures": list(self.failures),
            "sourceFindings": [finding.as_dict() for finding in self.source_findings],
        }


def _result(
    name: str,
    summary: str,
    failures: Sequence[str],
    source_findings: Sequence[Finding] = (),
) -> CheckResult:
    """Build a result whose ``passed`` is derived from its failures, never asserted."""
    return CheckResult(
        name=name,
        passed=not failures,
        summary=summary,
        failures=list(failures),
        source_findings=list(source_findings),
    )


# --------------------------------------------------------------------------------------
# N-Quads reading: the Atlas side
# --------------------------------------------------------------------------------------

_ESCAPES = {"t": "\t", "b": "\b", "n": "\n", "r": "\r", "f": "\f", '"': '"', "'": "'", "\\": "\\"}


def unescape_literal(raw: str) -> str:
    """Decode an N-Triples literal body to the exact characters it denotes.

    Byte fidelity is the whole point of this verifier, so this must be exact: a
    label that differs from the publisher only by a decoded escape is identical,
    and a label that differs by a real character is not.
    """
    out: list[str] = []
    index = 0
    length = len(raw)
    while index < length:
        char = raw[index]
        if char != "\\":
            out.append(char)
            index += 1
            continue
        index += 1
        if index >= length:
            raise ValueError("truncated escape in literal")
        marker = raw[index]
        if marker in _ESCAPES:
            out.append(_ESCAPES[marker])
            index += 1
        elif marker in ("u", "U"):
            width = 4 if marker == "u" else 8
            hex_digits = raw[index + 1 : index + 1 + width]
            if len(hex_digits) != width:
                raise ValueError(f"truncated \\{marker} escape in literal")
            out.append(chr(int(hex_digits, 16)))
            index += 1 + width
        else:
            raise ValueError(f"unknown escape \\{marker} in literal")
    return "".join(out)


@dataclass(frozen=True)
class Quad:
    """One losslessly parsed canonical N-Quads statement."""

    subject: str
    predicate: str
    obj: str
    is_literal: bool
    language: str | None
    datatype: str | None
    graph: str


_LITERAL_BODY = re.compile(r'^"((?:[^"\\]|\\.)*)"(?:@([A-Za-z0-9-]+)|\^\^<([^>]*)>)?\s*$')


def parse_nquads_line(line: str) -> Quad | None:
    """Parse one canonical N-Quads line; return ``None`` for blanks and comments."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if not stripped.endswith("."):
        raise ValueError(f"N-Quads line does not terminate with '.': {stripped[:120]!r}")
    body = stripped[:-1].strip()

    if not body.startswith("<"):
        raise ValueError(f"expected an IRI subject: {stripped[:120]!r}")
    subject_end = body.index(">")
    subject = body[1:subject_end]
    rest = body[subject_end + 1 :].lstrip()

    if not rest.startswith("<"):
        raise ValueError(f"expected an IRI predicate: {stripped[:120]!r}")
    predicate_end = rest.index(">")
    predicate = rest[1:predicate_end]
    rest = rest[predicate_end + 1 :].lstrip()

    if rest.startswith("<"):
        object_end = rest.index(">")
        obj = rest[1:object_end]
        graph = _graph_term(rest[object_end + 1 :], stripped)
        return Quad(
            subject,
            predicate,
            obj,
            is_literal=False,
            language=None,
            datatype=None,
            graph=graph,
        )

    if not rest.startswith('"'):
        raise ValueError(f"unsupported object term: {stripped[:120]!r}")
    closing = _closing_quote(rest)
    literal_tail = rest[closing + 1 :].lstrip()
    graph_start = _graph_start(literal_tail)
    suffix = literal_tail[:graph_start].rstrip()
    match = _LITERAL_BODY.match(rest[: closing + 1] + suffix)
    if match is None:
        raise ValueError(f"unsupported literal object: {stripped[:120]!r}")
    graph = _graph_term(literal_tail[graph_start:], stripped)
    return Quad(
        subject,
        predicate,
        unescape_literal(match.group(1)),
        is_literal=True,
        language=match.group(2),
        datatype=match.group(3),
        graph=graph,
    )


def _closing_quote(text: str) -> int:
    """Index of the quote that closes the literal opening at position 0."""
    index = 1
    while index < len(text):
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == '"':
            return index
        index += 1
    raise ValueError("unterminated literal")


def _graph_start(tail: str) -> int:
    """Return the start of the required graph IRI after a literal suffix."""
    if tail.startswith("<"):
        return 0
    if tail.startswith("@"):
        marker = tail.find(" <")
        if marker >= 0:
            return marker + 1
    if tail.startswith("^^<"):
        datatype_end = tail.find(">")
        if datatype_end >= 0:
            marker = tail.find("<", datatype_end + 1)
            if marker >= 0:
                return marker
    raise ValueError(f"literal has no graph IRI: {tail[:120]!r}")


def _graph_term(tail: str, line: str) -> str:
    """Parse a graph IRI and reject unconsumed terms."""
    text = tail.strip()
    if not text.startswith("<") or not text.endswith(">") or text.count("<") != 1:
        raise ValueError(f"invalid or missing graph IRI: {line[:120]!r}")
    return text[1:-1]


def read_pack(
    path: Path,
    failures: list[str] | None = None,
    observations: dict[str, tuple[str, int]] | None = None,
    logical_path: str | None = None,
) -> Iterator[Quad]:
    """Parse one immutable pack snapshot and retain its actual transport identity."""
    payload = path.read_bytes()
    if observations is not None:
        observations[logical_path or path.as_posix()] = (
            "sha256:" + hashlib.sha256(payload).hexdigest(),
            len(payload),
        )
    with zstd.open(io.BytesIO(payload), "rt", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            try:
                quad = parse_nquads_line(line)
            except ValueError as error:
                detail = f"{path.name}:{number}: {error}"
                if failures is None:
                    raise ValueError(detail) from error
                failures.append(detail)
                continue
            if quad is not None:
                yield quad


# --------------------------------------------------------------------------------------
# Views
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class LiteralValue:
    """One literal with the language and datatype needed to detect silent rewrites."""

    value: str
    language: str | None
    datatype: str | None


@dataclass(frozen=True)
class ReifiedStatement:
    """One exact RDF reification row from publisher bytes."""

    statement_iri: str
    subject_iri: str
    predicate_iri: str
    object_iri: str | None = None
    object_literal: LiteralValue | None = None


def _literal_value(value: str, language: str | None, datatype: str | None) -> LiteralValue:
    """Represent the RDF 1.1 datatype of a plain literal explicitly."""
    if language is None and datatype is None:
        datatype = f"{XSD}string"
    return LiteralValue(value, language, datatype)


def _literal_repr(literal: LiteralValue) -> str:
    """Render one literal with the tag or datatype that makes a rewrite visible."""
    if literal.language is not None:
        return f"{literal.value!r}@{literal.language}"
    return f"{literal.value!r}^^<{literal.datatype}>"


@dataclass(frozen=True)
class PublisherView:
    """What the pinned publisher bytes say, in the least-transformed form usable."""

    concepts: frozenset[str]
    schemes: frozenset[str]
    pref_labels: Mapping[str, frozenset[LiteralValue]]
    alt_labels: Mapping[str, frozenset[LiteralValue]]
    hidden_labels: Mapping[str, frozenset[LiteralValue]]
    notations: Mapping[str, frozenset[LiteralValue]]
    annotations: frozenset[tuple[str, str, LiteralValue]]
    resource_annotations: frozenset[tuple[str, str, str]]
    resource_annotation_target_claim_counts: Mapping[str, int]
    literal_claims: frozenset[tuple[str, str, LiteralValue]]
    iri_claims: frozenset[tuple[str, str, str]]
    reified_statements: frozenset[ReifiedStatement]
    pref_label_count_all_languages: int
    alt_label_count_all_languages: int
    hidden_label_count_all_languages: int
    relations: frozenset[tuple[str, str, str]]
    memberships: frozenset[tuple[str, str]]
    top_concept_of: frozenset[tuple[str, str]]
    has_top_concept: frozenset[tuple[str, str]]
    resource_predicate_counts: Mapping[tuple[str, str], int]
    defects: tuple[Finding, ...]
    resource_input_digests: Mapping[str, frozenset[str]]
    input_content_digests: Mapping[str, str]
    unevaluated_claims: tuple[str, ...] = ()
    # Blank-node claims a declared exclusion accounts for, by exclusion name.
    # They never reach ``iri_claims``/``literal_claims`` (both require an IRI
    # subject), so the exclusion report counts them from here instead of losing
    # them between the two accountings.
    declared_out_of_scope_blank_node_claims: Mapping[str, tuple[str, ...]] = field(
        default_factory=dict
    )
    # The subjects each exclusion selected out of the publisher's whole graph,
    # before any subset selector narrowed this view. EuroVoc's main/domains
    # split drops the dataset-description subjects entirely, which would leave
    # the exclusion's Atlas-side proof ranging over an empty set -- vacuously
    # true, and therefore worthless. Keeping the roots makes that proof real.
    declared_out_of_scope_subjects: Mapping[str, tuple[str, ...]] = field(
        default_factory=dict
    )


@dataclass(frozen=True)
class AtlasView:
    """What the Atlas actually asserts for one source, read out of its packs."""

    resources: frozenset[str]
    releases: frozenset[str]
    rdf_types: Mapping[str, frozenset[str]]
    resource_profiles: Mapping[str, frozenset[str]]
    semantic_rings: Mapping[str, frozenset[str]]
    atlas_scheme_iris: Mapping[str, frozenset[str]]
    skos_schemes: frozenset[str]
    pref_labels: Mapping[str, frozenset[LiteralValue]]
    alt_labels: Mapping[str, frozenset[LiteralValue]]
    hidden_labels: Mapping[str, frozenset[LiteralValue]]
    notations: Mapping[str, frozenset[LiteralValue]]
    definitions: Mapping[str, frozenset[LiteralValue]]
    notes: Mapping[str, frozenset[LiteralValue]]
    relations: frozenset[tuple[str, str, str]]
    memberships: frozenset[tuple[str, str]]
    source_records: frozenset[str]
    record_locators: frozenset[str]
    record_locator_pairs: frozenset[tuple[str, str]]
    record_targets: Mapping[str, str]
    record_source_locators: Mapping[str, str]
    record_source_digests: Mapping[str, str]
    native_payloads: Mapping[str, Mapping[str, Any]]
    native_scheme_iris: Mapping[str, frozenset[str]]
    native_top_concept_of_iris: Mapping[str, frozenset[str]]
    native_literal_claims: frozenset[tuple[str, str, LiteralValue]]
    native_relations: frozenset[tuple[str, str, str]]
    raw_source_iri_claims: frozenset[tuple[str, str, str]]
    raw_source_literal_claims: frozenset[tuple[str, str, LiteralValue]]
    all_raw_iri_claims: frozenset[tuple[str, str, str]]
    all_raw_literal_claims: frozenset[tuple[str, str, LiteralValue]]
    label_links: frozenset[tuple[str, str, str]]
    relation_assertions: frozenset[str]
    structural_failures: tuple[str, ...]
    checked_packs: tuple[str, ...]
    checked_pack_transports: Mapping[str, tuple[str, int]]


@dataclass(frozen=True)
class SourcePin:
    """One independent pin for publisher bytes read by this verifier."""

    path: str
    sha256: str
    byte_length: int
    fmt: str = "turtle"
    zip_member: str | None = None
    role: str | None = None
    source_iri: str | None = None
    construction_path: str | None = None


@dataclass(frozen=True)
class DistributionUnit:
    """One authenticated construction-summary work item."""

    key: str
    kind: str
    inputs: tuple[Mapping[str, Any], ...]
    packs: tuple[str, ...]
    record_counts: Mapping[str, int]


@dataclass(frozen=True)
class PackPin:
    """Transport identity for one pack from the authenticated Atlas manifest."""

    path: str
    sha256: str
    byte_length: int


@dataclass(frozen=True)
class NativeControlSelector:
    """One direct value extraction from a pinned Parquet source table."""

    control_id: str
    source_table: str
    source_field: str
    extraction: str
    source_iri: str
    expected_row_count: int
    expected_columns: tuple[str, ...]
    construction_key: str


@dataclass(frozen=True)
class SourceExtractSelector:
    """One non-RDF publisher artifact compared through its checked-in extract.

    Some publishers ship no machine-readable distribution at all -- the Federal
    Register thesaurus is a styled PDF. For those releases the comparison basis
    is the repository-checked semantic extract of the pinned artifact: bytes
    that live in git, are pinned here by digest, are *not* read by the builder
    (which re-parses the PDF on every build), and whose own header binds the
    exact publisher artifact this comparison authenticates.

    This is weaker than the RDF comparisons and says so in the receipt: it is
    not an independent re-parse of the publisher's bytes, it is a frozen
    re-statement of them. What it does catch is every drift between what the
    builder parsed out of the pinned artifact and what git recorded.
    """

    reader: str
    extract: SourcePin
    source_release_iri: str
    label_language: str
    relation_predicate: str


@dataclass(frozen=True)
class SourceListSelector:
    """One exact row set read directly from authenticated publisher bytes.

    These sources publish small code lists or bounded record tables without RDF.
    A stock parser reads the publisher's declared row fields, and the auditor
    compares that complete row multiset with the dedicated Atlas pack. Most
    documentation tables expose only labels and notations; a selector may also
    require a publisher resource IRI and exact scalar fields retained in
    ``atlas:nativePayload``.
    """

    reader: str
    extraction: str
    expected_record_count: int
    source_assertion: str
    source_key: str | None = None
    label_language: str = "en"
    input_path: str | None = None
    table_headers: tuple[str, ...] = ()
    table_index: int | None = None
    table_indices: tuple[int, ...] = ()
    data_row_start: int = 1
    label_column: int = 0
    notation_columns: tuple[int, ...] = ()
    split_pattern: str | None = None
    ignored_single_cell_rows: tuple[str, ...] = ()
    included_notations: frozenset[str] = frozenset()
    compare_labels: bool = True
    casefold_labels: bool = False
    compare_resource_iri: bool = False
    native_payload_fields: tuple[str, ...] = ()
    normalize_whitespace: bool = True


@dataclass(frozen=True)
class RdfSourcePolicy:
    """Independent source-record provenance policy for one RDF adapter."""

    evaluated_native_payload_fields: frozenset[str]
    atlas_only_native_payload_fields: frozenset[str] = frozenset()
    additional_annotation_predicates: tuple[str, ...] = ()
    additional_relation_predicates: tuple[str, ...] = ()
    label_language_inverse: str = "english-tagged"
    literal_reification_id_rules: tuple[tuple[str, str, str], ...] = ()
    note_predicate_inverse: str | None = None
    reification_base_iri: str | None = None
    reification_predicates: tuple[str, ...] = ()
    reification_weight_predicate: str | None = None
    reification_weight_value: LiteralValue | None = None
    relation_predicate_inverse: tuple[tuple[str, str], ...] = ()
    relation_scope: str = "member-subject"
    source_wide_literal_predicates: tuple[str, ...] = ()
    record_digest_input_paths: tuple[str, ...] = ()
    record_locator: str | None = None
    record_input_path_by_resource: tuple[tuple[str, str], ...] = ()
    record_locator_by_resource: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class DeclaredClaimExclusion:
    """One publisher entity layer a release declares Atlas does not represent.

    This is a claim-scope declaration, never a waiver. Some publishers ship
    entity kinds beside their terms -- GEMET's Group/Theme/SuperGroup
    collections and its bibliographic Source register, the Publications Office's
    void/lime dataset descriptions -- that Atlas deliberately does not model.
    Leaving those claims in the uncovered report says "we have not looked yet",
    which is false; dropping them silently is worse. An exclusion says instead:
    here is the exact subject set, here is every claim it covers counted by
    predicate, and here is the paired assertion that Atlas asserts *nothing*
    about any of those subjects.

    That pairing is what keeps it fail-closed. The exclusion only ever removes
    publisher claims from the residue; the Atlas side of the same subjects stays
    in the comparison, so one manufactured claim about an excluded subject fails
    both ``source-claim-coverage`` and ``claim-scope``. An exclusion that
    overlaps a subject the comparison actually compares is itself a failure.

    Subjects are selected by declared rdf:type or by IRI prefix -- both
    enumerable from the publisher's own bytes, so the receipt can print the set.
    """

    name: str
    reason: str
    subject_types: frozenset[str] = frozenset()
    subject_iri_prefixes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.subject_types and not self.subject_iri_prefixes:
            raise ValueError(
                f"declared claim exclusion {self.name!r} selects no subjects; an "
                "exclusion must name the exact subject set it covers"
            )

    def selects(self, subject: str, types: frozenset[str]) -> bool:
        """Return whether one publisher subject falls inside this declaration."""
        if self.subject_types & types:
            return True
        return bool(self.subject_iri_prefixes) and subject.startswith(
            self.subject_iri_prefixes
        )


@dataclass(frozen=True)
class SourceSpec:
    """One source vocabulary the verifier knows how to compare end to end."""

    name: str
    kind: str  # vocabulary, mapping, native-control, source-extract, or source-list
    release_keys: tuple[str, ...]
    inputs: tuple[SourcePin, ...]
    policies: frozenset[str] = frozenset()
    subset: str = "all"
    included_concept_iris: frozenset[str] = frozenset()
    excluded_resource_predicates: frozenset[str] = frozenset()
    declared_claim_exclusions: tuple[DeclaredClaimExclusion, ...] = ()
    native_control: NativeControlSelector | None = None
    rdf_source: RdfSourcePolicy | None = None
    source_extract: SourceExtractSelector | None = None
    source_list: SourceListSelector | None = None

    def has_policy(self, name: str) -> bool:
        return name in self.policies


@dataclass(frozen=True)
class SourcePair:
    """A publisher view and the Atlas view that claims to represent it."""

    spec: SourceSpec
    publisher: PublisherView
    atlas: AtlasView


@dataclass(frozen=True)
class NativeControlPublisherView:
    """Values and counts read directly from one authenticated Parquet column."""

    values: Mapping[str, int]
    source_row_count: int
    source_field_missing_row_count: int
    value_occurrence_count: int
    unresolved_value_count: int
    capture: Mapping[str, Any]
    capture_source_pin: Mapping[str, Any]
    failures: tuple[str, ...]


@dataclass(frozen=True)
class NativeControlPair:
    """One raw Parquet control and the dedicated Atlas pack representing it."""

    spec: SourceSpec
    publisher: NativeControlPublisherView
    atlas: AtlasView


@dataclass(frozen=True)
class SourceExtractPublisherView:
    """One repository-checked semantic extract, read with a stock JSON parser."""

    concept_labels: Mapping[str, str]
    concept_entry_ids: Mapping[str, str]
    concept_locators: Mapping[str, Mapping[str, int]]
    alternate_labels: Mapping[str, frozenset[str]]
    alternate_label_occurrence_count: int
    relations: frozenset[tuple[str, str, str]]
    unrepresented_rows: Mapping[str, int]
    declared_publisher_artifact: Mapping[str, Any]
    extract_digest: str
    failures: tuple[str, ...]


@dataclass(frozen=True)
class SourceExtractPair:
    """One checked-in source extract and the Atlas pack that claims to represent it."""

    spec: SourceSpec
    publisher: SourceExtractPublisherView
    atlas: AtlasView


@dataclass(frozen=True)
class SourceListRow:
    """One publisher row at the comparison boundary."""

    label: LiteralValue | None
    notations: tuple[str, ...]
    resource_iri: str | None = None
    native_attributes: tuple[tuple[str, str | None], ...] = ()


@dataclass(frozen=True)
class SourceListPublisherView:
    """A complete row multiset read from one pinned non-RDF source."""

    rows: tuple[SourceListRow, ...]
    source_assertion: str
    failures: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceListPair:
    """Pinned publisher rows and the Atlas pack that represents them."""

    spec: SourceSpec
    publisher: SourceListPublisherView
    atlas: AtlasView


@dataclass(frozen=True)
class KeyedAtlasExtractView:
    """Atlas claims re-keyed from minted resource IRIs to source-local identities."""

    resource_by_local: Mapping[str, str]
    pref_labels: Mapping[str, frozenset[LiteralValue]]
    alt_labels: Mapping[str, frozenset[LiteralValue]]
    entry_ids: Mapping[str, str]
    locators: Mapping[str, Any]
    relations: frozenset[tuple[str, str, str]]
    failures: tuple[str, ...]


@dataclass
class Expectations:
    """Declared shape of the run; overridable so tests need no real distribution."""

    minimum_label_sample: int = 200
    required_sources: tuple[str, ...] = ()
    require_complete_coverage: bool = True
    require_input_pins: bool = True
    require_pack_pins: bool = True


@dataclass(frozen=True)
class Context:
    """Everything the checks read, gathered once."""

    distribution: Path
    source_root: Path
    specs: tuple[SourceSpec, ...]
    pairs: tuple[SourcePair, ...]
    native_control_pairs: tuple[NativeControlPair, ...]
    atlas_views: tuple[tuple[SourceSpec, AtlasView], ...]
    expectations: Expectations
    units: tuple[DistributionUnit, ...]
    construction_summary_digest: str | None
    manifest_digest: str | None
    pack_pins: Mapping[str, PackPin]
    verified_pins: frozenset[SourcePin]
    pin_failures: tuple[str, ...]
    load_failures: tuple[str, ...]
    source_extract_pairs: tuple[SourceExtractPair, ...] = ()
    source_list_pairs: tuple[SourceListPair, ...] = ()
    # Specs this run deliberately did not evaluate. They stay visible so the
    # coverage arithmetic can report their construction units as scoped out
    # instead of silently counting them covered or failing them unread.
    scoped_out_specs: tuple[SourceSpec, ...] = ()
    comparison_claim_scope_cache: dict[SourceSpec, dict[str, Any]] = field(
        default_factory=dict,
        compare=False,
        repr=False,
    )

    def vocabularies(self) -> tuple[SourcePair, ...]:
        return tuple(pair for pair in self.pairs if pair.spec.kind == "vocabulary")

    def mappings(self) -> tuple[SourcePair, ...]:
        return tuple(pair for pair in self.pairs if pair.spec.kind == "mapping")

    def loaded_specs(self) -> frozenset[SourceSpec]:
        return frozenset(
            [
                *(pair.spec for pair in self.pairs),
                *(pair.spec for pair in self.native_control_pairs),
                *(pair.spec for pair in self.source_extract_pairs),
                *(pair.spec for pair in self.source_list_pairs),
            ]
        )

    def declared_specs(self) -> tuple[SourceSpec, ...]:
        """Every spec the registry declares, whether or not this run ran it."""
        return (*self.specs, *self.scoped_out_specs)

    def scoped_out_release_keys(self) -> frozenset[str]:
        return frozenset(
            key for spec in self.scoped_out_specs for key in spec.release_keys
        )


# --------------------------------------------------------------------------------------
# Publisher readers -- stock parsers only, no RefSpec code
# --------------------------------------------------------------------------------------


_RDFLIB_LITERAL_MODE_LOCK = threading.Lock()


def _load_graph_payload(
    payload: bytes,
    fmt: str,
    zip_member: str | None = None,
    *,
    public_id: str | None = None,
) -> Any:
    """Parse one immutable byte snapshot without RDFLib lexical normalization."""
    import rdflib

    graph = rdflib.Graph()
    if zip_member is not None:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            payload = archive.read(zip_member)
    # Literal normalization would turn publisher "01"^^xsd:integer into "1" and
    # make a rewritten Atlas value look faithful. RDFLib exposes this as a module
    # setting, so serialize the small critical section and restore it immediately.
    with _RDFLIB_LITERAL_MODE_LOCK:
        prior = rdflib.NORMALIZE_LITERALS
        term_logger = logging.getLogger("rdflib.term")
        prior_log_level = term_logger.level
        rdflib.NORMALIZE_LITERALS = False
        # RDFLib logs a traceback for each ill-typed literal even though it
        # keeps the lexical RDF term and continues parsing. Preserve the term
        # here; _publisher_defects reports counted defects after the parse.
        term_logger.setLevel(logging.ERROR)
        try:
            graph.parse(data=payload, format=fmt, publicID=public_id)
        finally:
            rdflib.NORMALIZE_LITERALS = prior
            term_logger.setLevel(prior_log_level)
    return graph


def _load_graph(path: Path, fmt: str, zip_member: str | None = None) -> Any:
    """Compatibility wrapper for callers that do not already hold pinned bytes."""
    return _load_graph_payload(path.read_bytes(), fmt, zip_member)


def _publisher_defects(graph: Any, source: str) -> tuple[Finding, ...]:
    """Detect defects in the publisher's own data, generically.

    These are reported, never repaired. Each detector is written against a general
    property of RDF rather than a known source, so a new source gets the same
    scrutiny without new code.
    """
    import rdflib

    findings: list[Finding] = []

    # Keep ill-typed publisher literals unchanged, but report every distinct
    # lexical/datatype defect with the exact number of affected claims.
    ill_typed: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for subject, predicate, obj in graph:
        if not isinstance(obj, rdflib.Literal) or getattr(obj, "ill_typed", None) is not True:
            continue
        datatype = str(obj.datatype) if obj.datatype is not None else ""
        ill_typed[(datatype, str(obj))].append((str(subject), str(predicate)))
    for (datatype, lexical), claims in sorted(ill_typed.items()):
        examples = ", ".join(
            f"<{subject}> <{predicate}>" for subject, predicate in sorted(claims)[:5]
        )
        suffix = "" if len(claims) <= 5 else f"; {len(claims) - 5} more claims"
        findings.append(
            Finding(
                kind="source",
                source=source,
                detail=(
                    f"publisher ships {len(claims)} ill-typed literal occurrence(s) with lexical "
                    f"form {lexical!r} and datatype <{datatype}>; claim examples: {examples}{suffix}"
                ),
            )
        )

    # A term explicitly declared as a class and then used as a predicate.
    declared_classes = KNOWN_CLASS_IRIS | {
        str(subject)
        for class_iri in (rdflib.RDFS.Class, rdflib.OWL.Class)
        for subject in graph.subjects(rdflib.RDF.type, class_iri)
    }
    predicate_counts: dict[str, int] = defaultdict(int)
    for predicate in graph.predicates():
        predicate_counts[str(predicate)] += 1
    for predicate, count in sorted(predicate_counts.items()):
        if predicate in declared_classes:
            share = 100.0 * count / max(len(graph), 1)
            basis = (
                "is a class in a fixed standards vocabulary"
                if predicate in KNOWN_CLASS_IRIS
                else "is explicitly declared as an RDF class"
            )
            findings.append(
                Finding(
                    kind="source",
                    source=source,
                    detail=(
                        f"publisher uses <{predicate}> as a predicate on {count} triples "
                        f"({share:.1f}% of the graph); the same IRI {basis}"
                    ),
                )
            )

    declared_concepts = {
        str(subject)
        for subject in graph.subjects(
            rdflib.RDF.type,
            rdflib.URIRef(SKOS_CONCEPT),
        )
        if isinstance(subject, rdflib.URIRef)
    }
    dangling_top_concepts = sorted(
        (str(scheme), str(concept))
        for scheme, concept in graph.subject_objects(
            rdflib.URIRef(SKOS_HAS_TOP_CONCEPT)
        )
        if isinstance(scheme, rdflib.URIRef)
        and isinstance(concept, rdflib.URIRef)
        and str(concept) not in declared_concepts
    )
    if dangling_top_concepts:
        findings.append(
            Finding(
                kind="source",
                source=source,
                detail=(
                    f"publisher asserts {len(dangling_top_concepts)} skos:hasTopConcept "
                    "target(s) that are not declared skos:Concept resources; examples: "
                    f"{dangling_top_concepts[:5]}"
                ),
            )
        )

    # A namespace IRI carrying whitespace, raw or percent-encoded.
    for prefix, namespace in graph.namespaces():
        text = str(namespace)
        if " " in text or "%20" in text:
            findings.append(
                Finding(
                    kind="source",
                    source=source,
                    detail=(
                        f"publisher declares prefix {prefix!r} with whitespace in its namespace IRI "
                        f"({text!r}); this fails strict RDF/XML parsers and can make distributions of "
                        f"the same release disagree"
                    ),
                )
            )

    # A concept the publisher gave no preferred label in any language.
    concepts = set(graph.subjects(rdflib.RDF.type, rdflib.URIRef(SKOS_CONCEPT)))
    unlabelled = sorted(
        str(concept) for concept in concepts if not list(graph.objects(concept, rdflib.URIRef(SKOS_PREF_LABEL)))
    )
    if unlabelled:
        findings.append(
            Finding(
                kind="source",
                source=source,
                detail=(
                    f"publisher ships {len(unlabelled)} skos:Concept resources with no skos:prefLabel in any "
                    f"language: {unlabelled}"
                ),
            )
        )
    return tuple(findings)


def _rdflib_literal_value(value: Any) -> LiteralValue:
    """Convert one stock RDFLib literal without source-specific normalization."""
    import rdflib

    if not isinstance(value, rdflib.Literal):
        raise TypeError(f"expected RDF literal, got {type(value).__name__}")
    datatype = getattr(value, "datatype", None)
    return _literal_value(
        str(value),
        getattr(value, "language", None),
        str(datatype) if datatype is not None else None,
    )


def _publisher_view(
    graph: Any,
    source: str,
    *,
    additional_annotation_predicates: Sequence[str] = (),
    additional_relation_predicates: Sequence[str] = (),
    resource_input_digests: Mapping[str, frozenset[str]] | None = None,
    input_content_digests: Mapping[str, str] | None = None,
    declared_claim_exclusions: Sequence[DeclaredClaimExclusion] = (),
) -> PublisherView:
    """Extract exact SKOS claims from a stock RDFLib graph."""
    import rdflib

    defects = list(_publisher_defects(graph, source))
    unevaluated_claims: list[str] = []

    def source_term_defect(subject: Any, predicate: str, obj: Any, expectation: str) -> None:
        detail = (
            f"publisher claim {subject!r} {_short(predicate)} {obj!r} has the wrong RDF term "
            f"kind; expected {expectation}"
        )
        defects.append(
            Finding(
                kind="source",
                source=source,
                detail=detail,
            )
        )
        unevaluated_claims.append(detail)

    concepts: set[str] = set()
    for term in graph.subjects(rdflib.RDF.type, rdflib.URIRef(SKOS_CONCEPT)):
        if isinstance(term, rdflib.URIRef):
            concepts.add(str(term))
        else:
            source_term_defect(term, RDF_TYPE, rdflib.URIRef(SKOS_CONCEPT), "an IRI subject")
    schemes: set[str] = set()
    for term in graph.subjects(rdflib.RDF.type, rdflib.URIRef(SKOS_CONCEPT_SCHEME)):
        if isinstance(term, rdflib.URIRef):
            schemes.add(str(term))
        else:
            source_term_defect(term, RDF_TYPE, rdflib.URIRef(SKOS_CONCEPT_SCHEME), "an IRI subject")

    pref: dict[str, set[LiteralValue]] = defaultdict(set)
    alt: dict[str, set[LiteralValue]] = defaultdict(set)
    hidden: dict[str, set[LiteralValue]] = defaultdict(set)
    notations: dict[str, set[LiteralValue]] = defaultdict(set)
    annotations: set[tuple[str, str, LiteralValue]] = set()
    resource_annotations: set[tuple[str, str, str]] = set()
    resource_annotation_targets: set[str] = set()
    pref_all = 0
    alt_all = 0
    hidden_all = 0
    def add_literal_claim(
        subject: Any,
        predicate: str,
        obj: Any,
        target: dict[str, set[LiteralValue]],
    ) -> bool:
        if not isinstance(subject, rdflib.URIRef) or not isinstance(obj, rdflib.Literal):
            source_term_defect(subject, predicate, obj, "an IRI subject and literal object")
            return False
        target[str(subject)].add(_rdflib_literal_value(obj))
        return True

    for subject, obj in graph.subject_objects(rdflib.URIRef(SKOS_PREF_LABEL)):
        pref_all += 1
        add_literal_claim(subject, SKOS_PREF_LABEL, obj, pref)
    for subject, obj in graph.subject_objects(rdflib.URIRef(SKOS_ALT_LABEL)):
        alt_all += 1
        add_literal_claim(subject, SKOS_ALT_LABEL, obj, alt)
    for subject, obj in graph.subject_objects(rdflib.URIRef(SKOS_HIDDEN_LABEL)):
        hidden_all += 1
        add_literal_claim(subject, SKOS_HIDDEN_LABEL, obj, hidden)

    def add_skosxl_claims(predicate: str, target: dict[str, set[LiteralValue]]) -> int:
        count = 0
        for subject, label_node in graph.subject_objects(rdflib.URIRef(predicate)):
            if not isinstance(subject, rdflib.URIRef) or not isinstance(
                label_node,
                (rdflib.URIRef, rdflib.BNode),
            ):
                source_term_defect(
                    subject,
                    predicate,
                    label_node,
                    "an IRI subject and RDF resource label node",
                )
                continue
            forms = list(graph.objects(label_node, rdflib.URIRef(SKOSXL_LITERAL_FORM)))
            if len(forms) != 1:
                detail = (
                    f"publisher SKOS-XL label node {label_node!r} referenced by "
                    f"{_short(predicate)} has {len(forms)} skosxl:literalForm values"
                )
                defects.append(
                    Finding(
                        kind="source",
                        source=source,
                        detail=detail,
                    )
                )
                # An empty label node is a defect in the publisher's data, not a
                # claim that escaped comparison: it carries no literal, so there
                # is nothing for a comparison to read, and the label edge that
                # points at it is compared as an IRI claim on its concept. It is
                # reported by check-source-defects and left exactly as published.
                # More than one form is different -- every form does enter the
                # label comparison, but the node's own multiplicity does not
                # survive the set-valued representation, so that stays declared
                # as uncompared.
                if len(forms) > 1:
                    unevaluated_claims.append(detail)
            for form in forms:
                if add_literal_claim(subject, predicate, form, target):
                    count += 1
        return count

    pref_all += add_skosxl_claims(SKOSXL_PREF_LABEL, pref)
    alt_all += add_skosxl_claims(SKOSXL_ALT_LABEL, alt)
    hidden_all += add_skosxl_claims(SKOSXL_HIDDEN_LABEL, hidden)
    for subject, obj in graph.subject_objects(rdflib.URIRef(SKOS_NOTATION)):
        add_literal_claim(subject, SKOS_NOTATION, obj, notations)
    for predicate in dict.fromkeys(
        (SKOS_DEFINITION, *SOURCE_NOTE_PREDICATES, *additional_annotation_predicates)
    ):
        for subject, obj in graph.subject_objects(rdflib.URIRef(predicate)):
            if not isinstance(subject, rdflib.URIRef):
                source_term_defect(subject, predicate, obj, "an IRI subject")
                continue
            if isinstance(obj, rdflib.Literal):
                annotations.add((str(subject), predicate, _rdflib_literal_value(obj)))
            elif isinstance(obj, rdflib.URIRef):
                resource_annotations.add((str(subject), predicate, str(obj)))
                resource_annotation_targets.add(str(obj))
            else:
                source_term_defect(
                    subject,
                    predicate,
                    obj,
                    "an IRI or literal annotation object",
                )

    relations: set[tuple[str, str, str]] = set()
    for predicate in dict.fromkeys(
        (*HIERARCHY_PREDICATES, *MAPPING_PREDICATES, *additional_relation_predicates)
    ):
        for subject, obj in graph.subject_objects(rdflib.URIRef(predicate)):
            if not isinstance(subject, rdflib.URIRef) or not isinstance(obj, rdflib.URIRef):
                source_term_defect(subject, predicate, obj, "IRI subject and IRI object")
                continue
            relations.add((str(subject), predicate, str(obj)))

    def iri_pairs(predicate: str) -> frozenset[tuple[str, str]]:
        rows: set[tuple[str, str]] = set()
        for subject, obj in graph.subject_objects(rdflib.URIRef(predicate)):
            if not isinstance(subject, rdflib.URIRef) or not isinstance(obj, rdflib.URIRef):
                source_term_defect(subject, predicate, obj, "IRI subject and IRI object")
                continue
            rows.add((str(subject), str(obj)))
        return frozenset(rows)

    memberships = iri_pairs(SKOS_IN_SCHEME)
    top_concept_of = iri_pairs(SKOS_TOP_CONCEPT_OF)
    has_top_concept = iri_pairs(SKOS_HAS_TOP_CONCEPT)
    source_scheme_references = {
        *(scheme for _, scheme in memberships),
        *(scheme for _, scheme in top_concept_of),
        *(scheme for scheme, _ in has_top_concept),
    }
    resource_iris = concepts | schemes | source_scheme_references
    literal_claims = frozenset(
        (str(subject), str(predicate), _rdflib_literal_value(obj))
        for subject, predicate, obj in graph
        if isinstance(subject, rdflib.URIRef) and isinstance(obj, rdflib.Literal)
    )
    iri_claims = frozenset(
        (str(subject), str(predicate), str(obj))
        for subject, predicate, obj in graph
        if isinstance(subject, rdflib.URIRef) and isinstance(obj, rdflib.URIRef)
    )
    reified_statements: set[ReifiedStatement] = set()
    for statement in graph.subjects(rdflib.RDF.type, rdflib.URIRef(RDF_STATEMENT)):
        subjects = set(graph.objects(statement, rdflib.RDF.subject))
        predicates = set(graph.objects(statement, rdflib.RDF.predicate))
        objects = set(graph.objects(statement, rdflib.RDF.object))
        if (
            not isinstance(statement, rdflib.URIRef)
            or len(subjects) != 1
            or len(predicates) != 1
            or len(objects) != 1
        ):
            defects.append(
                Finding(
                    kind="source",
                    source=source,
                    detail=(
                        f"publisher reification {statement!r} does not contain exactly one "
                        "rdf:subject, rdf:predicate, and rdf:object"
                    ),
                )
            )
            continue
        reified_subject = next(iter(subjects))
        reified_predicate = next(iter(predicates))
        reified_object = next(iter(objects))
        if not isinstance(reified_subject, rdflib.URIRef) or not isinstance(
            reified_predicate,
            rdflib.URIRef,
        ):
            defects.append(
                Finding(
                    kind="source",
                    source=source,
                    detail=(
                        f"publisher reification <{statement}> has a non-IRI subject or predicate"
                    ),
                )
            )
            continue
        if isinstance(reified_object, rdflib.URIRef):
            reified_statements.add(
                ReifiedStatement(
                    statement_iri=str(statement),
                    subject_iri=str(reified_subject),
                    predicate_iri=str(reified_predicate),
                    object_iri=str(reified_object),
                )
            )
        elif isinstance(reified_object, rdflib.Literal):
            reified_statements.add(
                ReifiedStatement(
                    statement_iri=str(statement),
                    subject_iri=str(reified_subject),
                    predicate_iri=str(reified_predicate),
                    object_literal=_rdflib_literal_value(reified_object),
                )
            )
        else:
            defects.append(
                Finding(
                    kind="source",
                    source=source,
                    detail=f"publisher reification <{statement}> has a blank-node object",
                )
            )
            unevaluated_claims.append(
                f"publisher reification <{statement}> has a blank-node object"
            )

    label_predicate_terms = frozenset(
        rdflib.URIRef(value) for value in SKOSXL_LABEL_PREDICATES
    )
    label_nodes = {
        obj
        for subject, predicate, obj in graph
        if isinstance(subject, rdflib.URIRef)
        and predicate in label_predicate_terms
        and isinstance(obj, rdflib.BNode)
    }
    # A declared exclusion names an entity layer by rdf:type or IRI prefix, and
    # publishers describe those entities with blank nodes too -- void:classPartition
    # hangs its per-class counts off one. Those claims never reach iri_claims or
    # literal_claims (both need an IRI subject), so the exclusion has to reach
    # them here or they would be reported as uncovered while the layer they
    # belong to is declared. The closure follows blank nodes out of an excluded
    # subject and no further: a blank node reachable from anything else stays in
    # the uncovered report.
    excluded_blank_node_claims: dict[str, list[str]] = {}
    excluded_subjects: dict[str, tuple[str, ...]] = {}
    exclusion_nodes: list[tuple[str, set[Any]]] = []
    for exclusion in declared_claim_exclusions:
        roots = {
            term
            for term in graph.subjects()
            if isinstance(term, rdflib.URIRef)
            and exclusion.selects(
                str(term),
                frozenset(
                    str(value) for value in graph.objects(term, rdflib.RDF.type)
                ),
            )
        }
        reached: set[Any] = set(roots)
        frontier = list(roots)
        while frontier:
            for obj in graph.objects(frontier.pop(), None):
                if isinstance(obj, rdflib.BNode) and obj not in reached:
                    reached.add(obj)
                    frontier.append(obj)
        if roots:
            exclusion_nodes.append((exclusion.name, reached))
            excluded_blank_node_claims[exclusion.name] = []
            excluded_subjects[exclusion.name] = tuple(
                sorted(str(term) for term in roots)
            )
    for subject, predicate, obj in graph:
        if not isinstance(subject, rdflib.BNode) and not isinstance(obj, rdflib.BNode):
            continue
        supported_label_edge = (
            isinstance(subject, rdflib.URIRef)
            and str(predicate) in SKOSXL_LABEL_PREDICATES
            and obj in label_nodes
        )
        supported_label_form = (
            subject in label_nodes
            and str(predicate) == SKOSXL_LITERAL_FORM
            and isinstance(obj, rdflib.Literal)
        )
        if supported_label_edge or supported_label_form:
            continue
        detail = (
            f"publisher blank-node claim {subject!r} <{predicate}> {obj!r} has no "
            "executable source-shape inverse"
        )
        declaring = next(
            (name for name, nodes in exclusion_nodes if subject in nodes),
            None,
        )
        if declaring is not None:
            if detail not in excluded_blank_node_claims[declaring]:
                excluded_blank_node_claims[declaring].append(detail)
            continue
        if detail not in unevaluated_claims:
            unevaluated_claims.append(detail)
            defects.append(Finding(kind="source", source=source, detail=detail))
    resource_predicate_counts: dict[tuple[str, str], int] = defaultdict(int)
    for subject, predicate, _ in graph:
        if isinstance(subject, rdflib.URIRef) and str(subject) in resource_iris:
            resource_predicate_counts[(str(subject), str(predicate))] += 1

    return PublisherView(
        concepts=frozenset(concepts),
        schemes=frozenset(schemes),
        pref_labels={key: frozenset(value) for key, value in pref.items()},
        alt_labels={key: frozenset(value) for key, value in alt.items()},
        hidden_labels={key: frozenset(value) for key, value in hidden.items()},
        notations={key: frozenset(value) for key, value in notations.items()},
        annotations=frozenset(annotations),
        resource_annotations=frozenset(resource_annotations),
        resource_annotation_target_claim_counts={
            target: sum(1 for _ in graph.predicate_objects(rdflib.URIRef(target)))
            for target in sorted(resource_annotation_targets)
        },
        literal_claims=literal_claims,
        iri_claims=iri_claims,
        reified_statements=frozenset(reified_statements),
        pref_label_count_all_languages=pref_all,
        alt_label_count_all_languages=alt_all,
        hidden_label_count_all_languages=hidden_all,
        relations=frozenset(relations),
        memberships=memberships,
        top_concept_of=top_concept_of,
        has_top_concept=has_top_concept,
        resource_predicate_counts=dict(resource_predicate_counts),
        defects=tuple(defects),
        resource_input_digests=dict(resource_input_digests or {}),
        input_content_digests=dict(input_content_digests or {}),
        unevaluated_claims=tuple(dict.fromkeys(unevaluated_claims)),
        declared_out_of_scope_blank_node_claims={
            name: tuple(details)
            for name, details in excluded_blank_node_claims.items()
        },
        declared_out_of_scope_subjects=dict(excluded_subjects),
    )


def read_publisher_skos(path: Path, fmt: str, source: str, zip_member: str | None = None) -> PublisherView:
    """Read one pinned SKOS distribution into the comparison form."""
    return _publisher_view(_load_graph(path, fmt, zip_member), source)


def _resolve_source_pin(source_root: Path, pin: SourcePin) -> Path:
    """Resolve a declared input without allowing it to escape the two approved roots."""
    candidates = (source_root / pin.path, REPOSITORY_ROOT / pin.path)
    for candidate in candidates:
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    return candidates[0]


def _read_publisher_pin_set(
    inputs: Sequence[SourcePin],
    source: str,
    authenticated_payloads: Mapping[SourcePin, bytes],
    *,
    additional_annotation_predicates: Sequence[str] = (),
    additional_relation_predicates: Sequence[str] = (),
    declared_claim_exclusions: Sequence[DeclaredClaimExclusion] = (),
) -> PublisherView:
    """Read all RDF inputs, reporting every unreadable member before failing the set."""
    import rdflib

    graph = rdflib.Graph()
    failures: list[str] = []
    resource_input_digests: dict[str, set[str]] = defaultdict(set)
    input_content_digests: dict[str, str] = {}
    for pin in inputs:
        try:
            payload = authenticated_payloads[pin]
            loaded = _load_graph_payload(
                payload,
                pin.fmt,
                pin.zip_member,
                public_id=pin.source_iri,
            )
            content = payload
            if pin.zip_member is not None:
                with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                    content = archive.read(pin.zip_member)
        except Exception as error:  # noqa: BLE001 - inspect the remaining declared inputs
            failures.append(f"{pin.path}: {type(error).__name__}: {error}")
            continue
        content_digest = "sha256:" + hashlib.sha256(content).hexdigest()
        input_content_digests[pin.path] = content_digest
        for subject in loaded.subjects():
            if isinstance(subject, rdflib.URIRef):
                resource_input_digests[str(subject)].add(content_digest)
        graph += loaded
        for prefix, namespace in loaded.namespaces():
            graph.bind(prefix, namespace, replace=True)
    if failures:
        raise ValueError("; ".join(failures))
    return _publisher_view(
        graph,
        source,
        additional_annotation_predicates=additional_annotation_predicates,
        additional_relation_predicates=additional_relation_predicates,
        resource_input_digests={
            resource: frozenset(digests)
            for resource, digests in resource_input_digests.items()
        },
        input_content_digests=input_content_digests,
        declared_claim_exclusions=declared_claim_exclusions,
    )


def read_publisher_inputs(source_root: Path, spec: SourceSpec) -> PublisherView:
    """Read and union every independently pinned RDF input for one comparison scope."""
    payloads = {
        pin: read_verified_file_pin(
            _resolve_source_pin(source_root, pin),
            expected_sha256=pin.sha256,
            expected_byte_length=pin.byte_length,
            logical_path=pin.path,
        )
        for pin in spec.inputs
    }
    view = _select_publisher_view(
        _read_publisher_pin_set(
            spec.inputs,
            spec.name,
            payloads,
            additional_annotation_predicates=(
                spec.rdf_source.additional_annotation_predicates
                if spec.rdf_source is not None
                else ()
            ),
            additional_relation_predicates=(
                spec.rdf_source.additional_relation_predicates
                if spec.rdf_source is not None
                else ()
            ),
            declared_claim_exclusions=spec.declared_claim_exclusions,
        ),
        spec.subset,
    )
    return _select_publisher_concepts(view, spec.included_concept_iris)


def _publisher_source_scheme_subjects(view: PublisherView) -> frozenset[str]:
    """Return explicit and referenced publisher-native scheme IRIs."""
    return frozenset(
        {
            *view.schemes,
            *(scheme for _, scheme in view.memberships),
            *(scheme for _, scheme in view.top_concept_of),
            *(scheme for scheme, _ in view.has_top_concept),
        }
    )


def _select_publisher_view(view: PublisherView, subset: str) -> PublisherView:
    """Apply one narrow, source-declared partition selector to publisher claims."""
    if subset == "all":
        return view
    if subset not in {"eurovoc-main", "eurovoc-domains"}:
        raise ValueError(f"unsupported publisher subset selector: {subset}")

    domain_scheme = "http://eurovoc.europa.eu/domains"
    domain_concepts = frozenset(subject for subject, target in view.memberships if target == domain_scheme)
    concepts = view.concepts - domain_concepts if subset == "eurovoc-main" else domain_concepts
    schemes = view.schemes - {domain_scheme} if subset == "eurovoc-main" else frozenset({domain_scheme})
    relations = frozenset(row for row in view.relations if row[0] in concepts)
    memberships = frozenset(row for row in view.memberships if row[0] in concepts)
    top_concept_of = frozenset(row for row in view.top_concept_of if row[0] in concepts)
    has_top_concept = frozenset(row for row in view.has_top_concept if row[1] in concepts)
    source_scheme_references = {
        *(scheme for _, scheme in memberships),
        *(scheme for _, scheme in top_concept_of),
        *(scheme for scheme, _ in has_top_concept),
    }
    resources = concepts | schemes | source_scheme_references
    pref = {subject: values for subject, values in view.pref_labels.items() if subject in resources}
    alt = {subject: values for subject, values in view.alt_labels.items() if subject in resources}
    hidden = {subject: values for subject, values in view.hidden_labels.items() if subject in resources}
    notations = {subject: values for subject, values in view.notations.items() if subject in resources}
    annotations = frozenset(row for row in view.annotations if row[0] in resources)
    resource_annotations = frozenset(
        row for row in view.resource_annotations if row[0] in resources
    )
    annotation_targets = frozenset(target for _, _, target in resource_annotations)
    retained_claim_subjects = resources | annotation_targets
    resource_predicate_counts = {
        row: count
        for row, count in view.resource_predicate_counts.items()
        if row[0] in resources
    }
    return PublisherView(
        concepts=frozenset(concepts),
        schemes=frozenset(schemes),
        pref_labels=pref,
        alt_labels=alt,
        hidden_labels=hidden,
        notations=notations,
        annotations=annotations,
        resource_annotations=resource_annotations,
        resource_annotation_target_claim_counts={
            target: view.resource_annotation_target_claim_counts.get(target, 0)
            for _, _, target in resource_annotations
        },
        literal_claims=frozenset(
            row for row in view.literal_claims if row[0] in retained_claim_subjects
        ),
        iri_claims=frozenset(
            row for row in view.iri_claims if row[0] in retained_claim_subjects
        ),
        reified_statements=frozenset(
            row for row in view.reified_statements if row.subject_iri in concepts
        ),
        pref_label_count_all_languages=sum(len(values) for values in pref.values()),
        alt_label_count_all_languages=sum(len(values) for values in alt.values()),
        hidden_label_count_all_languages=sum(len(values) for values in hidden.values()),
        relations=relations,
        memberships=memberships,
        top_concept_of=top_concept_of,
        has_top_concept=has_top_concept,
        resource_predicate_counts=resource_predicate_counts,
        defects=view.defects,
        resource_input_digests={
            resource: digests
            for resource, digests in view.resource_input_digests.items()
            if resource in resources
        },
        input_content_digests=view.input_content_digests,
        unevaluated_claims=view.unevaluated_claims,
        declared_out_of_scope_blank_node_claims=(
            view.declared_out_of_scope_blank_node_claims
        ),
        declared_out_of_scope_subjects=view.declared_out_of_scope_subjects,
    )


def _select_publisher_concepts(
    view: PublisherView,
    included_concept_iris: frozenset[str],
) -> PublisherView:
    """Select an explicitly bounded concept capture without interpreting its fields."""
    if not included_concept_iris:
        return view
    missing = sorted(included_concept_iris - view.concepts)
    if missing:
        raise ValueError(f"included publisher concepts are absent from the pinned bytes: {missing}")

    concepts = included_concept_iris
    memberships = frozenset(row for row in view.memberships if row[0] in concepts)
    scheme_iris = {scheme for _, scheme in memberships}
    schemes = frozenset(scheme for scheme in view.schemes if scheme in scheme_iris)
    top_concept_of = frozenset(
        row for row in view.top_concept_of if row[0] in concepts
    )
    has_top_concept = frozenset(
        row for row in view.has_top_concept if row[1] in concepts
    )
    source_scheme_references = {
        *scheme_iris,
        *(scheme for _, scheme in top_concept_of),
        *(scheme for scheme, _ in has_top_concept),
    }
    resources = concepts | schemes | source_scheme_references

    def selected_literals(
        values: Mapping[str, frozenset[LiteralValue]],
    ) -> dict[str, frozenset[LiteralValue]]:
        return {subject: rows for subject, rows in values.items() if subject in resources}

    pref = selected_literals(view.pref_labels)
    alt = selected_literals(view.alt_labels)
    hidden = selected_literals(view.hidden_labels)
    resource_annotations = frozenset(
        row for row in view.resource_annotations if row[0] in resources
    )
    annotation_targets = frozenset(target for _, _, target in resource_annotations)
    retained_claim_subjects = resources | annotation_targets
    return PublisherView(
        concepts=concepts,
        schemes=schemes,
        pref_labels=pref,
        alt_labels=alt,
        hidden_labels=hidden,
        notations=selected_literals(view.notations),
        annotations=frozenset(row for row in view.annotations if row[0] in resources),
        resource_annotations=resource_annotations,
        resource_annotation_target_claim_counts={
            target: view.resource_annotation_target_claim_counts.get(target, 0)
            for subject, _, target in view.resource_annotations
            if subject in resources
        },
        literal_claims=frozenset(
            row for row in view.literal_claims if row[0] in retained_claim_subjects
        ),
        iri_claims=frozenset(
            row for row in view.iri_claims if row[0] in retained_claim_subjects
        ),
        reified_statements=frozenset(
            row for row in view.reified_statements if row.subject_iri in concepts
        ),
        pref_label_count_all_languages=sum(len(values) for values in pref.values()),
        alt_label_count_all_languages=sum(len(values) for values in alt.values()),
        hidden_label_count_all_languages=sum(len(values) for values in hidden.values()),
        relations=frozenset(row for row in view.relations if row[0] in concepts),
        memberships=memberships,
        top_concept_of=top_concept_of,
        has_top_concept=has_top_concept,
        resource_predicate_counts={
            row: count
            for row, count in view.resource_predicate_counts.items()
            if row[0] in resources
        },
        defects=view.defects,
        resource_input_digests={
            resource: digests
            for resource, digests in view.resource_input_digests.items()
            if resource in resources
        },
        input_content_digests=view.input_content_digests,
        unevaluated_claims=view.unevaluated_claims,
        declared_out_of_scope_blank_node_claims=(
            view.declared_out_of_scope_blank_node_claims
        ),
        declared_out_of_scope_subjects=view.declared_out_of_scope_subjects,
    )


def _json_without_duplicate_keys(payload: bytes, label: str) -> Any:
    """Parse UTF-8 JSON and reject duplicate object fields."""

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} repeats JSON field {key!r}")
            result[key] = value
        return result

    return json.loads(payload, object_pairs_hook=reject_duplicates)


FEDERAL_REGISTER_THESAURUS_2025_EXTRACT_READER = (
    "federal-register-thesaurus-2025-styled-pdf-v1/1.0"
)


def _source_extract_failure_view(
    extract_digest: str,
    failures: Sequence[str],
) -> SourceExtractPublisherView:
    """Return a view that compares against nothing and says why, so runs fail closed."""
    return SourceExtractPublisherView(
        concept_labels={},
        concept_entry_ids={},
        concept_locators={},
        alternate_labels={},
        alternate_label_occurrence_count=0,
        relations=frozenset(),
        unrepresented_rows={},
        declared_publisher_artifact={},
        extract_digest=extract_digest,
        failures=tuple(failures),
    )


def _read_source_extract(
    source_root: Path,
    selector: SourceExtractSelector,
) -> SourceExtractPublisherView:
    """Authenticate and read one checked-in extract, or say exactly why it could not."""
    reader = _SOURCE_EXTRACT_READERS.get(selector.reader)
    if reader is None:
        return _source_extract_failure_view(
            "",
            [f"no extract reader is declared for {selector.reader!r}"],
        )
    try:
        payload = read_verified_file_pin(
            _resolve_source_pin(source_root, selector.extract),
            expected_sha256=selector.extract.sha256,
            expected_byte_length=selector.extract.byte_length,
            logical_path=selector.extract.path,
        )
    except Exception as error:  # noqa: BLE001 - report and keep auditing everything else
        return _source_extract_failure_view(
            "",
            [
                (
                    f"{selector.extract.path}: checked source extract was not "
                    f"authenticated: {type(error).__name__}: {error}"
                )
            ],
        )
    return reader(payload, selector)



def _read_federal_register_thesaurus_2025_extract(
    payload: bytes,
    selector: SourceExtractSelector,
) -> SourceExtractPublisherView:
    """Read the checked-in 2025 thesaurus extract with a stock JSON parser.

    Nothing here interprets the PDF. The extract's own vocabulary is read
    literally: an official term is a concept, a ``recognizedVariant`` occurrence
    is an alternate label of every concept it names, and a ``resolved`` related
    reference is one directed associative relation. Rows the source itself marks
    as unresolved, ambiguous, open-term patterns, or index anomalies are counted
    and reported as rows Atlas must not turn into claims -- the exact set
    comparisons below are what enforce that.
    """
    failures: list[str] = []
    extract_digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    try:
        data = _json_without_duplicate_keys(payload, "source extract")
    except (UnicodeError, ValueError) as error:
        return _source_extract_failure_view(
            extract_digest,
            [f"source extract is not valid JSON: {error}"],
        )
    if not isinstance(data, Mapping):
        return _source_extract_failure_view(
            extract_digest,
            ["source extract must be a JSON object"],
        )

    declared_source = data.get("source")
    if not isinstance(declared_source, Mapping):
        failures.append("source extract declares no source object")
        declared_source = {}
    schema_version = data.get("schemaVersion")
    parser_version = data.get("parserVersion")
    if f"{parser_version}/{schema_version}" != (
        FEDERAL_REGISTER_THESAURUS_2025_EXTRACT_READER
    ):
        failures.append(
            "source extract version is not the one this comparison reads -- expected "
            f"{FEDERAL_REGISTER_THESAURUS_2025_EXTRACT_READER!r}, observed "
            f"{parser_version!r}/{schema_version!r}"
        )

    def rows(name: str) -> list[Mapping[str, Any]]:
        value = data.get(name)
        if not isinstance(value, list) or any(
            not isinstance(item, Mapping) for item in value
        ):
            failures.append(f"source extract {name} must be an array of objects")
            return []
        return list(value)

    concept_labels: dict[str, str] = {}
    concept_entry_ids: dict[str, str] = {}
    concept_locators: dict[str, Mapping[str, int]] = {}
    for index, item in enumerate(rows("officialTerms")):
        concept_id = item.get("concept_id")
        entry_id = item.get("entry_id")
        label = item.get("label")
        locator = item.get("locator")
        if (
            not isinstance(concept_id, str)
            or not concept_id
            or not isinstance(entry_id, str)
            or not entry_id
            or not isinstance(label, str)
            or not isinstance(locator, Mapping)
            or any(
                not isinstance(locator.get(key), int)
                or isinstance(locator.get(key), bool)
                for key in ("pdf_page", "printed_page", "source_ordinal")
            )
        ):
            failures.append(f"source extract officialTerms[{index}] is malformed")
            continue
        if concept_id in concept_labels:
            failures.append(
                f"source extract repeats official term identity {concept_id!r}"
            )
            continue
        concept_labels[concept_id] = label
        concept_entry_ids[concept_id] = entry_id
        concept_locators[concept_id] = {
            key: int(locator[key])
            for key in ("pdf_page", "printed_page", "source_ordinal")
        }

    alternate: dict[str, set[str]] = defaultdict(set)
    alternate_occurrences = 0
    unrepresented_variant_rows = 0
    for index, item in enumerate(rows("variants")):
        label = item.get("label")
        status = item.get("resolution_status")
        targets = item.get("target_concept_ids")
        if (
            not isinstance(label, str)
            or not isinstance(status, str)
            or not isinstance(targets, list)
            or any(not isinstance(target, str) for target in targets)
        ):
            failures.append(f"source extract variants[{index}] is malformed")
            continue
        if status != "recognizedVariant":
            unrepresented_variant_rows += len(targets) or 1
            continue
        for target in targets:
            if target not in concept_labels:
                failures.append(
                    f"source extract variants[{index}] names unknown concept {target!r}"
                )
                continue
            alternate[target].add(label)
            alternate_occurrences += 1

    relations: set[tuple[str, str, str]] = set()
    unrepresented_relation_rows = 0
    for index, item in enumerate(rows("relatedReferences")):
        status = item.get("resolution_status")
        subject = item.get("source_concept_id")
        obj = item.get("target_concept_id")
        if not isinstance(status, str) or not isinstance(subject, str):
            failures.append(f"source extract relatedReferences[{index}] is malformed")
            continue
        if status != "resolved" or obj is None:
            unrepresented_relation_rows += 1
            continue
        if not isinstance(obj, str) or obj not in concept_labels or subject not in concept_labels:
            failures.append(
                f"source extract relatedReferences[{index}] names an unknown concept"
            )
            continue
        relations.add((subject, selector.relation_predicate, obj))

    return SourceExtractPublisherView(
        concept_labels=concept_labels,
        concept_entry_ids=concept_entry_ids,
        concept_locators=concept_locators,
        alternate_labels={key: frozenset(value) for key, value in alternate.items()},
        alternate_label_occurrence_count=alternate_occurrences,
        relations=frozenset(relations),
        unrepresented_rows={
            "ambiguousOrUnresolvedVariantOccurrences": unrepresented_variant_rows,
            "indexAnomalies": len(rows("indexAnomalies")),
            "suggestedOpenTermPatterns": len(rows("suggestedOpenTermPatterns")),
            "unresolvedReferences": len(rows("unresolvedReferences")),
            "unresolvedOrRedirectedRelatedReferences": unrepresented_relation_rows,
            "variantRedirects": len(rows("variantRedirects")),
        },
        declared_publisher_artifact=dict(declared_source),
        extract_digest=extract_digest,
        failures=tuple(failures),
    )


_SOURCE_EXTRACT_READERS: Mapping[
    str,
    Callable[[bytes, SourceExtractSelector], SourceExtractPublisherView],
] = {
    FEDERAL_REGISTER_THESAURUS_2025_EXTRACT_READER: (
        _read_federal_register_thesaurus_2025_extract
    ),
}


SOURCE_LIST_READER = "pinned-publisher-row-list-v1"


class _FlatHtmlTableReader(HTMLParser):
    """Read flat HTML tables without interpreting page-specific registry rules."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[tuple[str, ...]]] = []
        self._table_depth = 0
        self._rows: list[tuple[str, ...]] | None = None
        self._row: list[str] | None = None
        self._cell_chunks: list[str] | None = None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        if tag == "table":
            self._table_depth += 1
            if self._table_depth == 1:
                self._rows = []
            return
        if self._table_depth != 1:
            return
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell_chunks = []

    def handle_data(self, data: str) -> None:
        if self._cell_chunks is not None:
            self._cell_chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "table":
            if self._table_depth == 1 and self._rows is not None:
                self.tables.append(self._rows)
                self._rows = None
            self._table_depth = max(0, self._table_depth - 1)
            return
        if self._table_depth != 1:
            return
        if tag in {"td", "th"} and self._cell_chunks is not None:
            if self._row is not None:
                self._row.append(" ".join("".join(self._cell_chunks).split()))
            self._cell_chunks = None
        elif tag == "tr" and self._row is not None:
            if self._rows is not None:
                self._rows.append(tuple(self._row))
            self._row = None

    def close(self) -> None:
        """Retain a table from an explicitly bounded publisher-page excerpt."""
        super().close()
        if self._table_depth == 1 and self._rows is not None:
            self.tables.append(self._rows)
            self._rows = None
            self._table_depth = 0


def _source_list_failure_view(
    selector: SourceListSelector,
    failures: Sequence[str],
) -> SourceListPublisherView:
    return SourceListPublisherView(
        rows=(),
        source_assertion=selector.source_assertion,
        failures=tuple(failures),
    )


def _source_list_input(
    spec: SourceSpec,
    selector: SourceListSelector,
    authenticated_payloads: Mapping[SourcePin, bytes],
) -> tuple[SourcePin, bytes]:
    pins = [
        pin
        for pin in spec.inputs
        if selector.input_path is None or pin.path == selector.input_path
    ]
    if len(pins) != 1:
        raise ValueError(
            f"source-list extraction selects {len(pins)} inputs; expected exactly one"
        )
    pin = pins[0]
    return pin, authenticated_payloads[pin]


def _source_list_row(
    label: str | None,
    notations: Iterable[str],
    selector: SourceListSelector,
    *,
    resource_iri: str | None = None,
    native_attributes: Mapping[str, str | None] | None = None,
) -> SourceListRow:
    normalized_label = (
        " ".join(label.split())
        if label is not None and selector.normalize_whitespace
        else label
    )
    if normalized_label is not None and selector.casefold_labels:
        normalized_label = normalized_label.casefold()
    normalized_notations = tuple(
        sorted(
            {
                " ".join(value.split()) if selector.normalize_whitespace else value
                for value in notations
                if value.strip()
            }
        )
    )
    if selector.compare_labels and not normalized_label:
        raise ValueError("publisher row has an empty label")
    return SourceListRow(
        label=(
            _literal_value(normalized_label, selector.label_language, None)
            if selector.compare_labels and normalized_label is not None
            else None
        ),
        notations=normalized_notations,
        resource_iri=resource_iri,
        native_attributes=tuple(
            (
                name,
                " ".join(value.split())
                if value is not None and selector.normalize_whitespace
                else value,
            )
            for name, value in sorted((native_attributes or {}).items())
        ),
    )


def _read_html_table_source_list(
    spec: SourceSpec,
    selector: SourceListSelector,
    authenticated_payloads: Mapping[SourcePin, bytes],
) -> SourceListPublisherView:
    pin, payload = _source_list_input(spec, selector, authenticated_payloads)
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"{pin.path} is not UTF-8 HTML") from error
    parser = _FlatHtmlTableReader()
    parser.feed(text)
    parser.close()
    selected_tables: list[list[tuple[str, ...]]]
    if selector.table_indices:
        selected_tables = []
        for table_index in selector.table_indices:
            try:
                candidate = parser.tables[table_index]
            except IndexError as error:
                raise ValueError(
                    f"HTML table index {table_index} is absent; "
                    f"observed {len(parser.tables)} tables"
                ) from error
            if selector.table_headers and (
                not candidate or candidate[0] != selector.table_headers
            ):
                observed = candidate[0] if candidate else ()
                raise ValueError(
                    f"HTML table {table_index} headers differ -- expected "
                    f"{selector.table_headers!r}, observed {observed!r}"
                )
            selected_tables.append(candidate)
    elif selector.table_index is not None:
        try:
            table = parser.tables[selector.table_index]
        except IndexError as error:
            raise ValueError(
                f"HTML table index {selector.table_index} is absent; "
                f"observed {len(parser.tables)} tables"
            ) from error
        if selector.table_headers and (
            not table or table[0] != selector.table_headers
        ):
            observed = table[0] if table else ()
            raise ValueError(
                f"HTML table {selector.table_index} headers differ -- expected "
                f"{selector.table_headers!r}, observed {observed!r}"
            )
        selected_tables = [table]
    elif selector.table_headers:
        tables = [
            table
            for table in parser.tables
            if table and table[0] == selector.table_headers
        ]
        if len(tables) != 1:
            raise ValueError(
                f"expected one HTML table headed {selector.table_headers!r}, "
                f"observed {len(tables)}"
        )
        selected_tables = [tables[0]]
    else:
        raise ValueError("HTML table extraction declares neither headers nor an index")

    rows: list[SourceListRow] = []
    selected_rows = [
        cells
        for table in selected_tables
        for cells in table[selector.data_row_start :]
    ]
    for ordinal, cells in enumerate(selected_rows):
        if len(cells) == 1 and cells[0] in selector.ignored_single_cell_rows:
            continue
        if selector.split_pattern is not None:
            if len(cells) != 1:
                raise ValueError(
                    f"HTML row {ordinal} must contain one split cell, observed {cells!r}"
                )
            match = re.fullmatch(selector.split_pattern, cells[0])
            if match is None:
                raise ValueError(
                    f"HTML row {ordinal} does not match {selector.split_pattern!r}: "
                    f"{cells[0]!r}"
                )
            rows.append(
                _source_list_row(
                    match.group("label"),
                    (match.group("notation"),),
                    selector,
                )
            )
            continue
        required_columns = (selector.label_column, *selector.notation_columns)
        if any(column < 0 or column >= len(cells) for column in required_columns):
            raise ValueError(
                f"HTML row {ordinal} has {len(cells)} cells; required columns are "
                f"{required_columns}"
            )
        notations = tuple(cells[column] for column in selector.notation_columns)
        if selector.included_notations and not (
            set(notations) & selector.included_notations
        ):
            continue
        rows.append(
            _source_list_row(
                cells[selector.label_column],
                notations,
                selector,
            )
        )
    return SourceListPublisherView(
        rows=tuple(rows),
        source_assertion=selector.source_assertion,
    )


def _markdown_table_rows(text: str, headers: tuple[str, ...]) -> list[tuple[str, ...]]:
    lines = text.splitlines()
    def cells(line: str) -> tuple[str, ...]:
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            raise ValueError(f"malformed Markdown table row: {line!r}")
        return tuple(cell.strip() for cell in stripped[1:-1].split("|"))

    matches = [
        index
        for index, line in enumerate(lines)
        if line.strip().startswith("|")
        and line.strip().endswith("|")
        and cells(line) == headers
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected one Markdown table headed {headers!r}, observed {len(matches)}"
        )
    index = matches[0] + 1
    if index >= len(lines):
        raise ValueError("Markdown table has no separator")

    separator = cells(lines[index])
    if len(separator) != len(headers) or any(
        re.fullmatch(r":?-{3,}:?", cell) is None for cell in separator
    ):
        raise ValueError("Markdown table separator does not match its header")
    index += 1
    result: list[tuple[str, ...]] = []
    while index < len(lines) and lines[index].strip().startswith("|"):
        row = cells(lines[index])
        if len(row) != len(headers):
            raise ValueError(
                f"Markdown table row has {len(row)} cells, expected {len(headers)}"
            )
        result.append(row)
        index += 1
    return result


def _read_markdown_source_list(
    spec: SourceSpec,
    selector: SourceListSelector,
    authenticated_payloads: Mapping[SourcePin, bytes],
) -> SourceListPublisherView:
    pin, payload = _source_list_input(spec, selector, authenticated_payloads)
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"{pin.path} is not UTF-8 Markdown") from error
    if selector.extraction == "billstatus-bill-types":
        match = re.search(
            r"^Bill type \(Possible values are ([^)]+)\)\.[ \t]*$",
            text,
            re.MULTILINE,
        )
        if match is None:
            raise ValueError("BILLSTATUS bill-type sentence is absent or changed")
        values = re.split(r",\s*(?:and\s+)?", match.group(1))
        rows = tuple(_source_list_row(value, (value,), selector) for value in values)
        return SourceListPublisherView(rows, selector.source_assertion)

    table = _markdown_table_rows(text, selector.table_headers)
    rows: list[SourceListRow] = []
    for cells in table:
        clean = tuple(
            re.sub(r"^\*\*(.*?)\*\*$", r"\1", value).strip()
            for value in cells
        )
        rows.append(
            _source_list_row(
                clean[selector.label_column],
                (clean[column] for column in selector.notation_columns),
                selector,
            )
        )
    return SourceListPublisherView(tuple(rows), selector.source_assertion)


def _read_cbo_publication_source_list(
    spec: SourceSpec,
    selector: SourceListSelector,
    authenticated_payloads: Mapping[SourcePin, bytes],
) -> SourceListPublisherView:
    pin, payload = _source_list_input(spec, selector, authenticated_payloads)
    if b"<!ENTITY" in payload[:8192].upper():
        raise ValueError("CBO XML must not declare custom entities")
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as error:
        raise ValueError(f"{pin.path} is not well-formed XML") from error
    if root.tag != "response":
        raise ValueError(f"CBO XML root must be 'response', observed {root.tag!r}")
    rows: list[SourceListRow] = []
    seen_keys: set[str] = set()
    for ordinal, item in enumerate(root):
        if item.tag != "item":
            raise ValueError(f"CBO root child {ordinal} is not an item")
        if tuple(child.tag for child in item) != (
            "Title",
            "Date",
            "Link",
            "Description",
            "Bill_Number",
        ):
            raise ValueError(f"CBO item {ordinal} fields changed")
        key = item.get("key")
        title = (item.findtext("Title") or "").strip()
        link = (item.findtext("Link") or "").strip()
        publication = re.fullmatch(r"https://www\.cbo\.gov/publication/(\d+)", link)
        if not key or key in seen_keys:
            raise ValueError(f"CBO item {ordinal} has a missing or repeated key")
        if not title or publication is None:
            raise ValueError(f"CBO item {ordinal} lacks an exact title or publication URL")
        seen_keys.add(key)
        bill_number = (item.findtext("Bill_Number") or "").strip()
        rows.append(
            _source_list_row(
                title,
                (),
                selector,
                resource_iri=link,
                native_attributes={
                    "billNumber": bill_number or None,
                    "date": (item.findtext("Date") or "").strip(),
                    "description": (item.findtext("Description") or "").strip(),
                    "feedItemKey": key,
                },
            )
        )
    return SourceListPublisherView(tuple(rows), selector.source_assertion)


def _decode_source_list_payload(pin: SourcePin, payload: bytes) -> str:
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"{pin.path} is not UTF-8 text") from error


def _plain_html(value: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value)).split())


class _FormValueReader(HTMLParser):
    """Collect ordinary select options and input/label value pairs."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.selects: list[tuple[Mapping[str, str | None], list[tuple[str | None, str]]]] = []
        self.inputs: dict[str, tuple[str | None, str | None]] = {}
        self.labels: list[tuple[str | None, str]] = []
        self._select: tuple[Mapping[str, str | None], list[tuple[str | None, str]]] | None = None
        self._option_value: str | None = None
        self._option_chunks: list[str] | None = None
        self._label_for: str | None = None
        self._label_input: str | None = None
        self._label_chunks: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        if tag == "select":
            self._select = (attr_map, [])
            self.selects.append(self._select)
        elif tag == "option" and self._select is not None:
            self._option_value = attr_map.get("value")
            self._option_chunks = []
        elif tag == "label":
            self._label_for = attr_map.get("for")
            self._label_input = None
            self._label_chunks = []
        elif tag == "input":
            element_id = attr_map.get("id")
            if element_id:
                self.inputs[element_id] = (attr_map.get("name"), attr_map.get("value"))
                if self._label_chunks is not None:
                    self._label_input = element_id

    def handle_data(self, data: str) -> None:
        if self._option_chunks is not None:
            self._option_chunks.append(data)
        if self._label_chunks is not None:
            self._label_chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "option" and self._option_chunks is not None and self._select is not None:
            self._select[1].append(
                (self._option_value, " ".join("".join(self._option_chunks).split()))
            )
            self._option_value = None
            self._option_chunks = None
        elif tag == "select":
            self._select = None
        elif tag == "label" and self._label_chunks is not None:
            self.labels.append(
                (
                    self._label_for or self._label_input,
                    " ".join("".join(self._label_chunks).split()),
                )
            )
            self._label_for = None
            self._label_input = None
            self._label_chunks = None


def _read_census_tiger_source_list(
    spec: SourceSpec,
    selector: SourceListSelector,
    authenticated_payloads: Mapping[SourcePin, bytes],
) -> SourceListPublisherView:
    pin, payload = _source_list_input(spec, selector, authenticated_payloads)
    parser = _FlatHtmlTableReader()
    parser.feed(_decode_source_list_payload(pin, payload))
    parser.close()
    if len(parser.tables) != 2:
        raise ValueError(f"Census GEOID page must contain two tables, observed {len(parser.tables)}")
    structure = [row for row in parser.tables[0][1:] if len(row) == 5]
    examples = [row for row in parser.tables[1][2:] if len(row) == 2]
    rows = [
        _source_list_row(row[0], (row[1],), selector)
        for row in structure
    ] + [
        _source_list_row(row[1], (row[0],), selector)
        for row in examples
    ]
    return SourceListPublisherView(tuple(rows), selector.source_assertion)


def _read_epa_comptox_source_list(
    spec: SourceSpec,
    selector: SourceListSelector,
    authenticated_payloads: Mapping[SourcePin, bytes],
) -> SourceListPublisherView:
    pin, payload = _source_list_input(spec, selector, authenticated_payloads)
    text = _decode_source_list_payload(pin, payload)
    patterns = {
        "dtxsid": r"DTXSID\d{6,9}",
        "dtxcid": r"DTXCID\d{4,9}",
        "casrn": r'casrn:"(\d{2,7}-\d{2}-\d)"',
        "preferredName": r'preferredName:"([^"\\]+)"',
    }
    values: dict[str, str] = {}
    for name, pattern in patterns.items():
        matches = sorted(set(re.findall(pattern, text)))
        if len(matches) != 1:
            raise ValueError(f"CompTox page exposes {len(matches)} distinct {name} values")
        values[name] = matches[0]
    row = _source_list_row(
        values["preferredName"],
        (),
        selector,
        native_attributes=values,
    )
    return SourceListPublisherView((row,), selector.source_assertion)


def _read_fac_dictionary_source_list(
    spec: SourceSpec,
    selector: SourceListSelector,
    authenticated_payloads: Mapping[SourcePin, bytes],
) -> SourceListPublisherView:
    pin, payload = _source_list_input(spec, selector, authenticated_payloads)
    text = _decode_source_list_payload(pin, payload)
    section_pattern = re.compile(
        r'<h3 id="endpoint-([a-z_]+)">Endpoint: <code>[a-z_]+</code> '
        r'\(formerly <code>([^)<]*)\)(?:</code>)?</h3>.*?'
        r'<table class="usa-table">(.*?)</table>',
        re.DOTALL,
    )
    row_pattern = re.compile(
        r"<tr>\s*<td>(.*?)</td>\s*<th scope=\"row\">(.*?)</th>\s*"
        r"<td>(.*?)</td>\s*</tr>",
        re.DOTALL,
    )
    rows: list[SourceListRow] = []
    for endpoint, formerly, table in section_pattern.findall(text):
        distinct: dict[str, SourceListRow] = {}
        for census, gsa, data_type in row_pattern.findall(table):
            gsa_field = _plain_html(gsa)
            row = _source_list_row(
                gsa_field,
                (gsa_field,),
                selector,
                native_attributes={
                    "data_type": _plain_html(data_type),
                    "endpoint": endpoint,
                    "formerly_endpoint": _plain_html(formerly),
                    "gsa_field": gsa_field,
                    "legacy_census_field": (
                        None if _plain_html(census) == "____" else _plain_html(census)
                    ),
                },
            )
            existing = distinct.get(gsa_field)
            if existing is not None and existing != row:
                raise ValueError(f"FAC field {gsa_field!r} repeats with conflicting metadata")
            distinct[gsa_field] = row
        rows.extend(distinct.values())
    return SourceListPublisherView(tuple(rows), selector.source_assertion)


def _read_fec_inline_source_list(
    spec: SourceSpec,
    selector: SourceListSelector,
    authenticated_payloads: Mapping[SourcePin, bytes],
) -> SourceListPublisherView:
    pin, payload = _source_list_input(spec, selector, authenticated_payloads)
    if selector.source_key is None:
        raise ValueError("FEC inline extraction requires a column name")
    text = _decode_source_list_payload(pin, payload)
    table_rows = re.findall(r"<tr>(.*?)</tr>", text, re.DOTALL)
    descriptions: list[str] = []
    for table_row in table_rows:
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", table_row, re.DOTALL)
        if cells and _plain_html(cells[0]) == selector.source_key:
            if len(cells) != 7:
                raise ValueError(f"FEC {selector.source_key} row has {len(cells)} cells")
            descriptions.append(cells[5])
    if len(descriptions) != 1:
        raise ValueError(f"FEC {selector.source_key} row count is {len(descriptions)}, expected one")
    rows: list[SourceListRow] = []
    for part in re.split(r"<br\s*/?>", descriptions[0]):
        line = _plain_html(part)
        if not line:
            continue
        match = re.fullmatch(r"([A-Z])\s*=\s*(.+)", line)
        if match is None:
            raise ValueError(f"FEC {selector.source_key} line is malformed: {line!r}")
        rows.append(_source_list_row(match.group(2), (match.group(1),), selector))
    return SourceListPublisherView(tuple(rows), selector.source_assertion)


def _read_ferc_source_list(
    spec: SourceSpec,
    selector: SourceListSelector,
    authenticated_payloads: Mapping[SourcePin, bytes],
) -> SourceListPublisherView:
    pin, payload = _source_list_input(spec, selector, authenticated_payloads)
    text = _decode_source_list_payload(pin, payload)
    if selector.extraction == "ferc-accession-formats":
        match = re.search(
            r'<td scope="row">Accession</td>\s*<td>([^<]+)</td>',
            text,
        )
        if match is None:
            raise ValueError("FERC accessibility page omitted accession formats")
        values = tuple(part.strip() for part in match.group(1).split(", or "))
        rows = tuple(_source_list_row(None, (value,), selector) for value in values)
        return SourceListPublisherView(rows, selector.source_assertion)
    if selector.source_key is None:
        raise ValueError("FERC list extraction requires a heading")
    match = re.search(
        r"<li>" + re.escape(selector.source_key) + r"</li>\s*<ul[^>]*>(.*?)</ul>",
        text,
        re.DOTALL,
    )
    if match is None:
        raise ValueError(f"FERC page omitted {selector.source_key!r}")
    values = tuple(_plain_html(value) for value in re.findall(r"<li>(.*?)</li>", match.group(1), re.DOTALL))
    rows = tuple(_source_list_row(value, (value,), selector) for value in values)
    return SourceListPublisherView(rows, selector.source_assertion)


def _form_rows(
    text: str,
    selector: SourceListSelector,
    *,
    names: Collection[str],
) -> tuple[SourceListRow, ...]:
    parser = _FormValueReader()
    parser.feed(text)
    parser.close()
    labels_by_id = {element_id: label for element_id, label in parser.labels if element_id}
    rows: list[SourceListRow] = []
    for element_id, (name, value) in parser.inputs.items():
        if name in names and value not in (None, ""):
            label = labels_by_id.get(element_id)
            if not label:
                raise ValueError(f"form input {element_id!r} has no non-empty label")
            rows.append(_source_list_row(label, (value,), selector))
    for attrs, options in parser.selects:
        if attrs.get("name") not in names and attrs.get("id") not in names:
            continue
        rows.extend(
            _source_list_row(label, (value,), selector)
            for value, label in options
            if value not in (None, "")
        )
    return tuple(rows)


def _read_gao_cra_source_list(
    spec: SourceSpec,
    selector: SourceListSelector,
    authenticated_payloads: Mapping[SourcePin, bytes],
) -> SourceListPublisherView:
    pin, payload = _source_list_input(spec, selector, authenticated_payloads)
    rows = _form_rows(
        _decode_source_list_payload(pin, payload),
        selector,
        names={"priority", "type"},
    )
    return SourceListPublisherView(rows, selector.source_assertion)


def _gao_product_values(text: str) -> dict[str, str]:
    canonical = re.findall(
        r'<link[^>]+rel="canonical"[^>]+href="([^"]+)"',
        text,
    )
    identity_blocks = re.findall(
        r'<section[^>]+class="[^"]*block-post-title-info[^"]*"[^>]*>(.*?)</section>',
        text,
        re.DOTALL,
    )
    titles = re.findall(r"<h1[^>]*>(.*?)</h1>", text, re.DOTALL)
    if len(canonical) != 1 or len(identity_blocks) != 1 or len(titles) != 1:
        raise ValueError("GAO product page identity structure changed")
    report_numbers = re.findall(r"<strong[^>]*>(.*?)</strong>", identity_blocks[0], re.DOTALL)
    published = re.findall(r"Published:\s*([A-Z][a-z]+ \d{1,2}, \d{4})", _plain_html(identity_blocks[0]))
    if len(report_numbers) != 1 or len(published) != 1:
        raise ValueError("GAO product page report number or publication date is ambiguous")
    month, day, year = re.fullmatch(
        r"([A-Z][a-z]+) (\d{1,2}), (\d{4})",
        published[0],
    ).groups()
    months = {
        name: index
        for index, name in enumerate(
            (
                "January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December",
            ),
            start=1,
        )
    }
    return {
        "canonicalUrl": canonical[0],
        "productReportNumber": _plain_html(report_numbers[0]),
        "productTitle": _plain_html(titles[0]),
        "publicationDate": f"{year}-{months[month]:02d}-{int(day):02d}",
    }


def _gao_topic_rows(text: str, selector: SourceListSelector) -> tuple[SourceListRow, ...]:
    heading = re.search(r'<h2[^>]*class="[^"]*block__title[^"]*"[^>]*>\s*Topics\s*</h2>', text)
    if heading is None:
        raise ValueError("GAO product page has no Topics block heading")
    rest = text[heading.end() :]
    next_heading = re.search(r"<h2\b", rest)
    block = rest[: next_heading.start()] if next_heading else rest
    links = re.findall(r'<a href="(/topics/[a-z0-9-]+)"[^>]*>(.*?)</a>', block, re.DOTALL)
    product = _gao_product_values(text)["productReportNumber"]
    return tuple(
        _source_list_row(
            _plain_html(label),
            (),
            selector,
            native_attributes={
                "observedOnProduct": product,
                "topicPath": path,
            },
        )
        for path, label in links
    )


def _read_gao_product_source_list(
    spec: SourceSpec,
    selector: SourceListSelector,
    authenticated_payloads: Mapping[SourcePin, bytes],
) -> SourceListPublisherView:
    pin, payload = _source_list_input(spec, selector, authenticated_payloads)
    text = _decode_source_list_payload(pin, payload)
    if selector.extraction == "gao-product-topic":
        rows = _gao_topic_rows(text, selector)
    else:
        values = _gao_product_values(text)
        rows = (
            _source_list_row(
                values["productTitle"],
                (),
                selector,
                resource_iri=values["canonicalUrl"],
                native_attributes={
                    "productReportNumber": values["productReportNumber"],
                    "publicationDate": values["publicationDate"],
                },
            ),
        )
    return SourceListPublisherView(rows, selector.source_assertion)


def _read_nasbo_source_list(
    spec: SourceSpec,
    selector: SourceListSelector,
    authenticated_payloads: Mapping[SourcePin, bytes],
) -> SourceListPublisherView:
    pin, payload = _source_list_input(spec, selector, authenticated_payloads)
    parser = _FlatHtmlTableReader()
    parser.feed(_decode_source_list_payload(pin, payload))
    parser.close()
    if len(parser.tables) != 1:
        raise ValueError(f"NASBO page must contain one table, observed {len(parser.tables)}")
    labels: list[str] = []
    for row in parser.tables[0]:
        for cell in row:
            if not cell:
                continue
            match = re.fullmatch(r'(.+?)\s+Read\s*\|\s*Tables', cell)
            if match is None:
                raise ValueError(f"NASBO chapter cell has unexpected text {cell!r}")
            labels.append(match.group(1).strip())
    rows = tuple(_source_list_row(label, (), selector) for label in labels)
    return SourceListPublisherView(rows, selector.source_assertion)


def _read_oira_source_list(
    spec: SourceSpec,
    selector: SourceListSelector,
    authenticated_payloads: Mapping[SourcePin, bytes],
) -> SourceListPublisherView:
    expected_names = {
        "eoStatusCode",
        "ruleStages",
        "concludedActionCode",
        "meetingType",
    }
    rows: list[SourceListRow] = []
    for pin in spec.inputs:
        rows.extend(
            _form_rows(
                _decode_source_list_payload(pin, authenticated_payloads[pin]),
                selector,
                names=expected_names,
            )
        )
    return SourceListPublisherView(tuple(rows), selector.source_assertion)


def _read_oversight_source_list(
    spec: SourceSpec,
    selector: SourceListSelector,
    authenticated_payloads: Mapping[SourcePin, bytes],
) -> SourceListPublisherView:
    pin, payload = _source_list_input(spec, selector, authenticated_payloads)
    rows = _form_rows(
        _decode_source_list_payload(pin, payload),
        selector,
        names={"field_report_type[]", "edit-field-report-type--2"},
    )
    return SourceListPublisherView(rows, selector.source_assertion)


def _read_pra_source_list(
    spec: SourceSpec,
    selector: SourceListSelector,
    authenticated_payloads: Mapping[SourcePin, bytes],
) -> SourceListPublisherView:
    pin, payload = _source_list_input(spec, selector, authenticated_payloads)
    text = _decode_source_list_payload(pin, payload)
    rows = list(_form_rows(text, selector, names={"requestType", "icrStatus"}))
    burden = re.compile(
        r'<td[^>]*style="font-weight:600;">\s*([^<]+?)\s*</td>\s*<td[^>]*>\s*Between\s*'
        r'<input id="(low\w+)"[^>]*/>.*?<input id="(high\w+)"[^>]*/>',
        re.DOTALL,
    )
    rows.extend(
        _source_list_row(_plain_html(label), (low_id, high_id), selector)
        for label, low_id, high_id in burden.findall(text)
    )
    omb = re.search(r'<input id="ombControlNumber"[^>]*maxlength="(\d+)"[^>]*>', text)
    if omb is None:
        raise ValueError("PRA page omitted OMB Control Number maxlength")
    rows.append(_source_list_row("OMB Control Number", ("ombControlNumber", omb.group(1)), selector))
    return SourceListPublisherView(tuple(rows), selector.source_assertion)


def _read_yaml_enum_source_list(
    spec: SourceSpec,
    selector: SourceListSelector,
    authenticated_payloads: Mapping[SourcePin, bytes],
) -> SourceListPublisherView:
    pin, payload = _source_list_input(spec, selector, authenticated_payloads)
    if selector.source_key is None:
        raise ValueError("YAML enum extraction requires a schema name")
    text = _decode_source_list_payload(pin, payload)
    pattern = re.compile(
        r"\n {4}" + re.escape(selector.source_key) + r":\n"
        r" {6}type: string\n"
        r" {6}description: [^\n]+\n"
        r" {6}enum:\n(?P<items>(?: {8}- [^\n]*\n)+)"
    )
    match = pattern.search(text)
    if match is None:
        raise ValueError(f"YAML schema {selector.source_key!r} enum is absent or changed")
    values = tuple(
        line.removeprefix("        - ").rstrip()
        for line in match.group("items").splitlines()
    )
    rows = tuple(_source_list_row(value, (value,), selector) for value in values)
    return SourceListPublisherView(rows, selector.source_assertion)


def _request_parameter_cell(text: str, name: str) -> str:
    match = re.search(
        r"<tr>\s*<td>" + re.escape(name) + r"</td>\s*<td>(.*?)</td>\s*<td>",
        text,
        re.DOTALL,
    )
    if match is None:
        raise ValueError(f"SAM.gov request parameter {name!r} is absent")
    return match.group(1)


def _read_sam_source_list(
    spec: SourceSpec,
    selector: SourceListSelector,
    authenticated_payloads: Mapping[SourcePin, bytes],
) -> SourceListPublisherView:
    pin, payload = _source_list_input(spec, selector, authenticated_payloads)
    text = _decode_source_list_payload(pin, payload)
    if selector.extraction == "sam-notice-types":
        cell = _request_parameter_cell(text, "ptype")
        lines = [_plain_html(part) for part in re.split(r"<br\s*/?>", cell)]
        rows: list[SourceListRow] = []
        for line in lines[1:]:
            lowered = line.casefold()
            if not line or lowered.startswith(("note: below services", "use justification")):
                continue
            match = re.fullmatch(r"([a-z])\s*=\s*(.+)", line)
            if match is None:
                raise ValueError(f"SAM.gov ptype line is malformed: {line!r}")
            rows.append(_source_list_row(match.group(2), (match.group(1),), selector))
        return SourceListPublisherView(tuple(rows), selector.source_assertion)
    cell = _request_parameter_cell(text, "status (Coming Soon)")
    flattened = _plain_html(cell.replace("<br>", " "))
    match = re.search(r"Accepts following:\s*(.+)$", flattened)
    if match is None:
        raise ValueError("SAM.gov opportunity status sentence is absent")
    values = tuple(value.strip() for value in match.group(1).split(",") if value.strip())
    rows = tuple(_source_list_row(value, (value,), selector) for value in values)
    return SourceListPublisherView(rows, selector.source_assertion)


def _read_scotus_source_list(
    spec: SourceSpec,
    selector: SourceListSelector,
    authenticated_payloads: Mapping[SourcePin, bytes],
) -> SourceListPublisherView:
    pin, payload = _source_list_input(spec, selector, authenticated_payloads)
    text = _decode_source_list_payload(pin, payload)
    sidenav = re.findall(r'<ul class="sidenav-list">(.*?)</ul>', text, re.DOTALL)
    if len(sidenav) != 1:
        raise ValueError(f"SCOTUS page has {len(sidenav)} sidenav lists, expected one")
    links = re.findall(r"<a[^>]*>(.*?)</a>", sidenav[0], re.DOTALL)
    if len(links) < 4:
        raise ValueError("SCOTUS sidenav has fewer than four opinion categories")
    labels = [_plain_html(value) for value in links[:4]]
    page_text = _plain_html(text).casefold()
    for phrase in ("slip opinion", "preliminary print", "bound volume"):
        if page_text.count(phrase) < 1:
            raise ValueError(f"SCOTUS page does not state the {phrase!r} publication stage")
        labels.append(phrase)
    rows = tuple(_source_list_row(label, (), selector) for label in labels)
    return SourceListPublisherView(rows, selector.source_assertion)


def _read_sec_source_list(
    spec: SourceSpec,
    selector: SourceListSelector,
    authenticated_payloads: Mapping[SourcePin, bytes],
) -> SourceListPublisherView:
    pin, payload = _source_list_input(spec, selector, authenticated_payloads)
    text = _decode_source_list_payload(pin, payload)
    sidenavs = re.findall(r'<ul class="usa-sidenav">(.*?)</ul>', text, re.DOTALL)
    if len(sidenavs) != 2:
        raise ValueError(f"SEC page has {len(sidenavs)} side navigation blocks, expected two")
    blocks = [
        tuple(_plain_html(value) for value in re.findall(r"<a[^>]*>(.*?)</a>", block, re.DOTALL))
        for block in sidenavs
    ]
    if blocks[0] != blocks[1] or len(blocks[0]) != 14:
        raise ValueError("SEC mobile and desktop navigation blocks differ or changed count")
    card_labels = tuple(
        _plain_html(value)
        for value in re.findall(
            r'<a[^>]*class="[^"]*subpage-card__headline__link[^"]*"[^>]*>(.*?)</a>',
            text,
            re.DOTALL,
        )
    )
    if len(card_labels) != 6:
        raise ValueError(f"SEC page has {len(card_labels)} subpage cards, expected six")
    labels = (*blocks[0][1:], *card_labels)
    rows = tuple(_source_list_row(label, (), selector) for label in labels)
    return SourceListPublisherView(rows, selector.source_assertion)


def _read_xsd_documentation_source_list(
    spec: SourceSpec,
    selector: SourceListSelector,
    authenticated_payloads: Mapping[SourcePin, bytes],
) -> SourceListPublisherView:
    _pin, payload = _source_list_input(spec, selector, authenticated_payloads)
    if selector.source_key is None:
        raise ValueError("XSD documentation extraction requires container:element:mode")
    parts = selector.source_key.split(":")
    if len(parts) != 3:
        raise ValueError("XSD source key must be container:element:mode")
    container, element_name, mode = parts
    if b"<!ENTITY" in payload[:8192].upper():
        raise ValueError("XSD source must not declare custom entities")
    root = ElementTree.fromstring(payload)
    namespace = "{http://www.w3.org/2001/XMLSchema}"
    complex_type = root.find(f"./{namespace}complexType[@name='{container}']")
    element = (
        complex_type.find(f".//{namespace}element[@name='{element_name}']")
        if complex_type is not None
        else None
    )
    documentation = (
        element.find(f"./{namespace}annotation/{namespace}documentation")
        if element is not None
        else None
    )
    if documentation is None or not documentation.text:
        raise ValueError(f"XSD documentation for {container}.{element_name} is absent")
    text = documentation.text.strip()
    match = re.match(r"One of the following(?: options)?:\s*(.*)", text)
    if match is None:
        raise ValueError(f"XSD option sentence for {element_name} changed")
    body = match.group(1).strip().rstrip(".")
    raw_values = (
        re.findall(r'"([^"]+)"', body)
        if mode == "quoted"
        else [part.strip() for part in body.split(",") if part.strip()]
    )
    values = tuple(dict.fromkeys(raw_values))
    rows = tuple(_source_list_row(value, (value,), selector) for value in values)
    return SourceListPublisherView(rows, selector.source_assertion)


def _read_source_list(
    spec: SourceSpec,
    authenticated_payloads: Mapping[SourcePin, bytes],
) -> SourceListPublisherView:
    """Dispatch one declared non-RDF row extraction without importing an adapter."""
    selector = spec.source_list
    if selector is None:
        return SourceListPublisherView((), "", ("source-list selector is missing",))
    if selector.reader != SOURCE_LIST_READER:
        return _source_list_failure_view(
            selector,
            [f"unsupported source-list reader {selector.reader!r}"],
        )
    readers: Mapping[
        str,
        Callable[
            [SourceSpec, SourceListSelector, Mapping[SourcePin, bytes]],
            SourceListPublisherView,
        ],
    ] = {
        "html-table": _read_html_table_source_list,
        "html-table-split": _read_html_table_source_list,
        "markdown-table": _read_markdown_source_list,
        "billstatus-bill-types": _read_markdown_source_list,
        "cbo-publication-xml": _read_cbo_publication_source_list,
        "census-tiger-geoid": _read_census_tiger_source_list,
        "epa-comptox-html": _read_epa_comptox_source_list,
        "fac-dictionary-html": _read_fac_dictionary_source_list,
        "fec-inline-html": _read_fec_inline_source_list,
        "ferc-help-list": _read_ferc_source_list,
        "ferc-accession-formats": _read_ferc_source_list,
        "gao-cra-radio": _read_gao_cra_source_list,
        "gao-product-report": _read_gao_product_source_list,
        "gao-product-topic": _read_gao_product_source_list,
        "nasbo-chapters": _read_nasbo_source_list,
        "oira-controls": _read_oira_source_list,
        "oversight-report-select": _read_oversight_source_list,
        "pra-controls": _read_pra_source_list,
        "yaml-enum": _read_yaml_enum_source_list,
        "sam-notice-types": _read_sam_source_list,
        "sam-opportunity-statuses": _read_sam_source_list,
        "scotus-opinion-types": _read_scotus_source_list,
        "sec-categories": _read_sec_source_list,
        "xsd-documentation-options": _read_xsd_documentation_source_list,
    }
    reader = readers.get(selector.extraction)
    if reader is None:
        return _source_list_failure_view(
            selector,
            [f"unsupported source-list extraction {selector.extraction!r}"],
        )
    try:
        view = reader(spec, selector, authenticated_payloads)
    except Exception as error:  # noqa: BLE001 - report every later source too
        return _source_list_failure_view(
            selector,
            [f"{type(error).__name__}: {error}"],
        )
    failures = list(view.failures)
    if len(view.rows) != selector.expected_record_count:
        failures.append(
            f"publisher row count differs -- expected {selector.expected_record_count}, "
            f"observed {len(view.rows)}"
        )
    return SourceListPublisherView(
        rows=view.rows,
        source_assertion=view.source_assertion,
        failures=tuple(failures),
    )


def _extract_native_control_value(
    raw: object,
    extraction: str,
    label: str,
) -> tuple[list[str], bool, int]:
    """Apply one small, explicit value selector without importing production ETL."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return [], True, 0
    if extraction == "scalar":
        if not isinstance(raw, str):
            raise TypeError(f"{label} must be text, observed {type(raw).__name__}")
        return [raw], False, 0
    if extraction not in {
        "jsonArrayFormat",
        "jsonArrayAgencySlug",
        "jsonArrayUnresolvedAgencyRawName",
    }:
        raise ValueError(f"unsupported native-control extraction {extraction!r}")

    value = _json_without_duplicate_keys(raw.encode("utf-8"), label) if isinstance(raw, str) else raw
    if not isinstance(value, list):
        raise TypeError(f"{label} must contain a JSON array")

    values: list[str] = []
    unresolved = 0
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise TypeError(f"{label}[{index}] must be an object")
        if extraction == "jsonArrayFormat":
            candidate = item.get("format")
        elif extraction == "jsonArrayAgencySlug":
            candidate = item.get("slug")
        else:
            slug = item.get("slug")
            if isinstance(slug, str) and slug.strip():
                continue
            candidate = item.get("raw_name")
        if not isinstance(candidate, str) or not candidate.strip():
            unresolved += 1
            continue
        values.append(candidate)
    return values, False, unresolved


def _parse_native_control_capture(
    capture_pin: SourcePin,
    payload: bytes | None,
    specs: Sequence[SourceSpec],
) -> tuple[dict[str, Mapping[str, Any]], dict[str, Mapping[str, Any]], list[str]]:
    """Parse one shared capture once and close it against every declared adapter."""
    failures: list[str] = []
    capture_by_id: dict[str, Mapping[str, Any]] = {}
    source_pin_by_table: dict[str, Mapping[str, Any]] = {}
    if payload is None:
        return {}, {}, [f"authenticated normalized control capture is unavailable: {capture_pin.path}"]
    try:
        document = _json_without_duplicate_keys(payload, capture_pin.path)
    except Exception as error:  # noqa: BLE001 - Parquet scans must still run
        return {}, {}, [
            f"normalized control capture could not be read: {type(error).__name__}: {error}"
        ]

    controls = document.get("controls") if isinstance(document, Mapping) else None
    if not isinstance(controls, list):
        failures.append("normalized control capture has no controls array")
    else:
        for index, row in enumerate(controls):
            control_id = row.get("controlId") if isinstance(row, Mapping) else None
            if not isinstance(control_id, str):
                failures.append(
                    f"normalized control capture controls[{index}] is not a named object"
                )
                continue
            if control_id in capture_by_id:
                failures.append(f"normalized control capture repeats {control_id!r}")
                continue
            capture_by_id[control_id] = row

    source_pins = document.get("sourcePins") if isinstance(document, Mapping) else None
    if not isinstance(source_pins, list):
        failures.append("normalized control capture has no sourcePins array")
    else:
        for index, row in enumerate(source_pins):
            table = row.get("table") if isinstance(row, Mapping) else None
            if not isinstance(table, str):
                failures.append(
                    f"normalized control capture sourcePins[{index}] is not a named object"
                )
                continue
            if table in source_pin_by_table:
                failures.append(f"normalized control capture repeats source pin {table!r}")
                continue
            source_pin_by_table[table] = row

    selectors = [spec.native_control for spec in specs if spec.native_control is not None]
    expected_ids = {selector.control_id for selector in selectors}
    expected_tables = {selector.source_table for selector in selectors}
    missing_ids = sorted(expected_ids - set(capture_by_id))
    unexpected_ids = sorted(set(capture_by_id) - expected_ids)
    missing_tables = sorted(expected_tables - set(source_pin_by_table))
    unexpected_tables = sorted(set(source_pin_by_table) - expected_tables)
    if missing_ids:
        failures.append(f"normalized control capture is missing declared controls: {missing_ids}")
    if unexpected_ids:
        failures.append(f"normalized control capture has undeclared controls: {unexpected_ids}")
    if missing_tables:
        failures.append(f"normalized control capture is missing source tables: {missing_tables}")
    if unexpected_tables:
        failures.append(f"normalized control capture has undeclared source tables: {unexpected_tables}")
    return capture_by_id, source_pin_by_table, failures


def _read_native_control_publishers(
    specs: Sequence[SourceSpec],
    authenticated_payloads: Mapping[SourcePin, bytes],
) -> tuple[dict[SourceSpec, NativeControlPublisherView], list[str]]:
    """Scan each pinned Parquet table once and compare its normalized capture later."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    views: dict[SourceSpec, NativeControlPublisherView] = {}
    load_failures: list[str] = []
    groups: dict[tuple[SourcePin, SourcePin], list[SourceSpec]] = defaultdict(list)
    for spec in specs:
        if spec.native_control is None:
            load_failures.append(f"{spec.name}: native-control selector is missing")
            continue
        parquet_pins = [pin for pin in spec.inputs if pin.fmt == "parquet"]
        capture_pins = [pin for pin in spec.inputs if pin.fmt == "json"]
        if len(parquet_pins) != 1 or len(capture_pins) != 1 or len(spec.inputs) != 2:
            load_failures.append(
                f"{spec.name}: native-control comparison requires exactly one Parquet and one JSON input"
            )
            continue
        groups[(parquet_pins[0], capture_pins[0])].append(spec)

    capture_specs: dict[SourcePin, list[SourceSpec]] = defaultdict(list)
    for (_parquet_pin, capture_pin), group_specs in groups.items():
        capture_specs[capture_pin].extend(group_specs)
    capture_cache = {
        capture_pin: _parse_native_control_capture(
            capture_pin,
            authenticated_payloads.get(capture_pin),
            tuple(dict.fromkeys(shared_specs)),
        )
        for capture_pin, shared_specs in capture_specs.items()
    }

    for (parquet_pin, capture_pin), group_specs in groups.items():
        selectors = {
            spec: selector
            for spec in group_specs
            if (selector := spec.native_control) is not None
        }
        group_failures: dict[SourceSpec, list[str]] = defaultdict(list)
        capture_by_id, source_pin_by_table, capture_failures = capture_cache[capture_pin]
        for spec in group_specs:
            group_failures[spec].extend(capture_failures)

        parquet_payload = authenticated_payloads.get(parquet_pin)
        if parquet_payload is None:
            load_failures.extend(
                f"{spec.name}: {detail}"
                for spec in group_specs
                for detail in group_failures[spec]
            )
            load_failures.extend(
                f"{spec.name}: authenticated Parquet input is unavailable: {parquet_pin.path}"
                for spec in group_specs
            )
            continue
        try:
            parquet_file = pq.ParquetFile(pa.BufferReader(parquet_payload))
        except Exception as error:  # noqa: BLE001 - report every other source group
            load_failures.extend(
                f"{spec.name}: {detail}"
                for spec in group_specs
                for detail in group_failures[spec]
            )
            load_failures.extend(
                f"{spec.name}: Parquet input could not be read: {type(error).__name__}: {error}"
                for spec in group_specs
            )
            continue

        counters = {spec: Counter[str]() for spec in group_specs}
        missing_counts = Counter[SourceSpec]()
        unresolved_counts = Counter[SourceSpec]()
        try:
            columns = tuple(parquet_file.schema_arrow.names)
            parquet_row_count = parquet_file.metadata.num_rows
        except Exception as error:  # noqa: BLE001 - report later Parquet groups
            load_failures.extend(
                f"{spec.name}: Parquet metadata could not be read: "
                f"{type(error).__name__}: {error}"
                for spec in group_specs
            )
            load_failures.extend(
                f"{spec.name}: {detail}"
                for spec in group_specs
                for detail in group_failures[spec]
            )
            continue
        for spec, selector in selectors.items():
            if columns != selector.expected_columns:
                group_failures[spec].append(
                    f"Parquet schema differs -- expected {selector.expected_columns}, observed {columns}"
                )
            if parquet_row_count != selector.expected_row_count:
                group_failures[spec].append(
                    f"Parquet row count differs -- expected {selector.expected_row_count}, "
                    f"observed {parquet_row_count}"
                )
            if selector.source_field not in columns:
                group_failures[spec].append(
                    f"Parquet source field {selector.source_field!r} is absent"
                )

        readable_specs = [
            spec for spec, selector in selectors.items() if selector.source_field in columns
        ]
        required_columns = tuple(
            dict.fromkeys(selectors[spec].source_field for spec in readable_specs)
        )
        row_offset = 0
        if not required_columns:
            row_offset = parquet_row_count
        else:
            try:
                for batch in parquet_file.iter_batches(
                    columns=list(required_columns),
                    batch_size=50_000,
                ):
                    column_values = batch.to_pydict()
                    for spec in readable_specs:
                        selector = selectors[spec]
                        for index, raw in enumerate(column_values[selector.source_field]):
                            try:
                                extracted, missing, unresolved = _extract_native_control_value(
                                    raw,
                                    selector.extraction,
                                    f"{selector.source_table}[{row_offset + index}].{selector.source_field}",
                                )
                            except Exception as error:  # noqa: BLE001 - collect every malformed row
                                group_failures[spec].append(
                                    f"row {row_offset + index}: {type(error).__name__}: {error}"
                                )
                                continue
                            counters[spec].update(extracted)
                            missing_counts[spec] += int(missing)
                            unresolved_counts[spec] += unresolved
                    row_offset += batch.num_rows
            except Exception as error:  # noqa: BLE001 - retain every earlier finding
                for spec in group_specs:
                    group_failures[spec].append(
                        f"Parquet scan failed after {row_offset} rows: "
                        f"{type(error).__name__}: {error}"
                    )

        for spec in group_specs:
            selector = selectors.get(spec)
            if selector is None:
                continue
            capture = capture_by_id.get(selector.control_id)
            if capture is None:
                group_failures[spec].append(
                    f"normalized control capture has no {selector.control_id!r} row"
                )
                capture = {}
            capture_source_pin = source_pin_by_table.get(selector.source_table)
            if capture_source_pin is None:
                group_failures[spec].append(
                    f"normalized control capture has no source pin for {selector.source_table!r}"
                )
                capture_source_pin = {}
            views[spec] = NativeControlPublisherView(
                values=dict(sorted(counters[spec].items())),
                source_row_count=row_offset,
                source_field_missing_row_count=missing_counts[spec],
                value_occurrence_count=sum(counters[spec].values()),
                unresolved_value_count=unresolved_counts[spec],
                capture=capture,
                capture_source_pin=capture_source_pin,
                failures=tuple(group_failures[spec]),
            )
    return views, load_failures


def read_atlas_source(
    distribution: Path,
    packs: Sequence[str],
    source_claim_subjects: frozenset[str] = frozenset(),
) -> AtlasView:
    """Read what the Atlas asserts for one source out of its distribution packs."""
    resources: set[str] = set()
    releases: set[str] = set()
    rdf_types: dict[str, set[str]] = defaultdict(set)
    resource_profiles: dict[str, set[str]] = defaultdict(set)
    semantic_rings: dict[str, set[str]] = defaultdict(set)
    atlas_scheme_iris: dict[str, set[str]] = defaultdict(set)
    skos_schemes: set[str] = set()
    memberships: set[tuple[str, str]] = set()
    locator_by_subject: dict[str, str] = {}
    source_records: set[str] = set()
    label_forms: dict[str, set[LiteralValue]] = defaultdict(set)
    pref_edges: list[tuple[str, str]] = []
    alt_edges: list[tuple[str, str]] = []
    hidden_edges: list[tuple[str, str]] = []
    notations: dict[str, set[LiteralValue]] = defaultdict(set)
    definitions: dict[str, set[LiteralValue]] = defaultdict(set)
    notes: dict[str, set[LiteralValue]] = defaultdict(set)
    reified: dict[str, dict[str, str]] = defaultdict(dict)
    native_schemes: dict[str, frozenset[str]] = {}
    native_top_concepts: dict[str, frozenset[str]] = {}
    native_literal_claims_by_record: dict[
        str, set[tuple[str | None, str, LiteralValue]]
    ] = defaultdict(set)
    native_label_claims_by_record: dict[
        str, set[tuple[str, LiteralValue]]
    ] = defaultdict(set)
    native_relations: set[tuple[str, str, str]] = set()
    native_payloads: dict[str, Mapping[str, Any]] = {}
    checked_pack_transports: dict[str, tuple[str, int]] = {}
    record_targets: dict[str, str] = {}
    record_source_digests: dict[str, str] = {}
    structural_failures: list[str] = []
    native_payload_values: dict[str, set[str]] = defaultdict(set)
    raw_source_iri_claims: set[tuple[str, str, str]] = set()
    raw_source_literal_claims: set[tuple[str, str, LiteralValue]] = set()
    all_raw_iri_claims: set[tuple[str, str, str]] = set()
    all_raw_literal_claims: set[tuple[str, str, LiteralValue]] = set()

    if not packs:
        structural_failures.append("no Atlas RDF packs were discovered for this comparison")

    source_evidence_atlas_predicates = frozenset(
        {
            ATLAS_NOTATION,
            ATLAS_DEFINITION,
            ATLAS_NOTE,
            ATLAS_SOURCE_LOCATOR,
            ATLAS_SOURCE_DIGEST,
            ATLAS_REPRESENTS_RESOURCE,
            ATLAS_NATIVE_PAYLOAD,
        }
    )

    def atlas_only_quad(quad: Quad) -> bool:
        if quad.predicate == SKOS_IN_SCHEME:
            return True
        if quad.predicate == RDF_TYPE:
            return (
                not quad.is_literal
                and quad.obj.startswith(ATLAS)
                and quad.obj != ATLAS_SOURCE_RECORD
            )
        return (
            quad.predicate.startswith(ATLAS)
            and quad.predicate not in source_evidence_atlas_predicates
        )

    for pack in packs:
        try:
            quads = read_pack(
                distribution / "packs" / pack,
                structural_failures,
                checked_pack_transports,
                pack,
            )
            for quad in quads:
                literal_claim = (
                    quad.subject,
                    quad.predicate,
                    _literal_value(
                        quad.obj,
                        quad.language,
                        quad.datatype,
                    ),
                )
                iri_claim = (quad.subject, quad.predicate, quad.obj)
                if quad.is_literal:
                    all_raw_literal_claims.add(literal_claim)
                else:
                    all_raw_iri_claims.add(iri_claim)
                if quad.subject in source_claim_subjects:
                    if quad.is_literal:
                        raw_source_literal_claims.add(literal_claim)
                    else:
                        raw_source_iri_claims.add(iri_claim)
                predicate = quad.predicate
                if (
                    predicate in IRI_OBJECT_PREDICATES
                    and quad.is_literal
                    and not atlas_only_quad(quad)
                ):
                    structural_failures.append(
                        f"{pack}: <{quad.subject}> {_short(predicate)} has a literal object "
                        f"{quad.obj!r}; an IRI is required"
                    )
                    continue
                if (
                    predicate in LITERAL_OBJECT_PREDICATES
                    and not quad.is_literal
                    and not atlas_only_quad(quad)
                ):
                    structural_failures.append(
                        f"{pack}: <{quad.subject}> {_short(predicate)} has an IRI object "
                        f"<{quad.obj}>; a literal is required"
                    )
                    continue
                if predicate == RDF_TYPE:
                    rdf_types[quad.subject].add(quad.obj)
                    if quad.obj in (SKOS_CONCEPT, ATLAS_RESOURCE):
                        resources.add(quad.subject)
                    if quad.obj == ATLAS_RELEASE:
                        releases.add(quad.subject)
                    if quad.obj == SKOS_CONCEPT_SCHEME:
                        skos_schemes.add(quad.subject)
                    if quad.obj == ATLAS_SOURCE_RECORD:
                        source_records.add(quad.subject)
                elif predicate == SKOS_IN_SCHEME:
                    memberships.add((quad.subject, quad.obj))
                elif predicate == ATLAS_IN_SCHEME:
                    atlas_scheme_iris[quad.subject].add(quad.obj)
                elif predicate == ATLAS_RESOURCE_PROFILE:
                    resource_profiles[quad.subject].add(quad.obj)
                elif predicate == ATLAS_SEMANTIC_RING:
                    semantic_rings[quad.subject].add(quad.obj)
                elif predicate == SKOSXL_LITERAL_FORM:
                    label_forms[quad.subject].add(_literal_value(quad.obj, quad.language, quad.datatype))
                elif predicate == SKOSXL_PREF_LABEL:
                    pref_edges.append((quad.subject, quad.obj))
                elif predicate == SKOSXL_ALT_LABEL:
                    alt_edges.append((quad.subject, quad.obj))
                elif predicate == SKOSXL_HIDDEN_LABEL:
                    hidden_edges.append((quad.subject, quad.obj))
                elif predicate == ATLAS_NOTATION:
                    if not quad.is_literal:
                        structural_failures.append(
                            f"{pack}: <{quad.subject}> atlas:notation has a non-literal value <{quad.obj}>"
                        )
                    else:
                        notations[quad.subject].add(_literal_value(quad.obj, quad.language, quad.datatype))
                elif predicate in (ATLAS_DEFINITION, ATLAS_NOTE):
                    if not quad.is_literal:
                        structural_failures.append(
                            f"{pack}: <{quad.subject}> {_short(predicate)} has a non-literal value <{quad.obj}>"
                        )
                    else:
                        target = definitions if predicate == ATLAS_DEFINITION else notes
                        target[quad.subject].add(_literal_value(quad.obj, quad.language, quad.datatype))
                elif predicate in (RDF_SUBJECT, RDF_PREDICATE, RDF_OBJECT):
                    if predicate in reified[quad.subject] and reified[quad.subject][predicate] != quad.obj:
                        structural_failures.append(
                            f"{pack}: relation assertion <{quad.subject}> has contradictory {_short(predicate)} values"
                        )
                    reified[quad.subject][predicate] = quad.obj
                elif predicate == ATLAS_SOURCE_LOCATOR:
                    if quad.subject in locator_by_subject and locator_by_subject[quad.subject] != quad.obj:
                        structural_failures.append(
                            f"{pack}: source record <{quad.subject}> has contradictory atlas:sourceLocator values"
                        )
                    locator_by_subject[quad.subject] = quad.obj
                elif predicate == ATLAS_SOURCE_DIGEST:
                    if (
                        quad.subject in record_source_digests
                        and record_source_digests[quad.subject] != quad.obj
                    ):
                        structural_failures.append(
                            f"{pack}: source record <{quad.subject}> has contradictory "
                            "atlas:sourceDigest values"
                        )
                    record_source_digests[quad.subject] = quad.obj
                elif predicate == ATLAS_REPRESENTS_RESOURCE:
                    if quad.subject in record_targets and record_targets[quad.subject] != quad.obj:
                        structural_failures.append(
                            f"{pack}: source record <{quad.subject}> represents more than one resource"
                        )
                    record_targets[quad.subject] = quad.obj
                elif predicate == ATLAS_NATIVE_PAYLOAD:
                    native_payload_values[quad.subject].add(quad.obj)
                    if len(native_payload_values[quad.subject]) > 1:
                        structural_failures.append(
                            f"{pack}: source record <{quad.subject}> has contradictory atlas:nativePayload values"
                        )
                    try:
                        payload = _json_without_duplicate_keys(
                            quad.obj.encode("utf-8"),
                            f"{pack}: source record <{quad.subject}> native payload",
                        )
                    except (UnicodeError, ValueError) as error:
                        structural_failures.append(
                            f"{pack}: source record <{quad.subject}> has invalid atlas:nativePayload JSON: {error}"
                        )
                        continue
                    if not isinstance(payload, dict):
                        structural_failures.append(
                            f"{pack}: source record <{quad.subject}> has non-object atlas:nativePayload JSON"
                        )
                        continue
                    native_payloads[quad.subject] = payload
                    scheme_iris = payload.get("schemeIris")
                    if isinstance(scheme_iris, list):
                        native_schemes[quad.subject] = frozenset(str(item) for item in scheme_iris)
                    elif scheme_iris is not None:
                        structural_failures.append(
                            f"{pack}: source record <{quad.subject}> has non-array nativePayload.schemeIris"
                        )
                    top_concept_iris = payload.get("topConceptOfIris")
                    if isinstance(top_concept_iris, list):
                        native_top_concepts[quad.subject] = frozenset(
                            str(item) for item in top_concept_iris
                        )
                    elif top_concept_iris is not None:
                        structural_failures.append(
                            f"{pack}: source record <{quad.subject}> has non-array "
                            "nativePayload.topConceptOfIris"
                        )
                    concept_payload = payload.get("concept")
                    if isinstance(concept_payload, Mapping):
                        nested_schemes = concept_payload.get("scheme_iris")
                        if isinstance(nested_schemes, list):
                            native_schemes[quad.subject] = frozenset(
                                str(item) for item in nested_schemes
                            )
                        elif nested_schemes is not None:
                            structural_failures.append(
                                f"{pack}: source record <{quad.subject}> has non-array "
                                "nativePayload.concept.scheme_iris"
                            )
                        nested_top = concept_payload.get("top_concept_of_iris")
                        if isinstance(nested_top, list):
                            native_top_concepts[quad.subject] = frozenset(
                                str(item) for item in nested_top
                            )
                        elif nested_top is not None:
                            structural_failures.append(
                                f"{pack}: source record <{quad.subject}> has non-array "
                                "nativePayload.concept.top_concept_of_iris"
                            )
                    label_normalization = payload.get("labelRoleNormalization")
                    if isinstance(label_normalization, Mapping):
                        conflicts = label_normalization.get("conflicts")
                        if not isinstance(conflicts, list):
                            structural_failures.append(
                                f"{pack}: source record <{quad.subject}> has non-array "
                                "nativePayload.labelRoleNormalization.conflicts"
                            )
                        else:
                            for index, conflict in enumerate(conflicts):
                                if not isinstance(conflict, Mapping):
                                    structural_failures.append(
                                        f"{pack}: source record <{quad.subject}> has non-object "
                                        "nativePayload.labelRoleNormalization.conflicts"
                                        f"[{index}]"
                                    )
                                    continue
                                role = conflict.get("suppressedRole")
                                value = conflict.get("value")
                                language = conflict.get("language")
                                if (
                                    role not in LABEL_ROLES
                                    or not isinstance(value, str)
                                    or (
                                        language is not None
                                        and not isinstance(language, str)
                                    )
                                ):
                                    structural_failures.append(
                                        f"{pack}: source record <{quad.subject}> has invalid "
                                        "nativePayload.labelRoleNormalization.conflicts"
                                        f"[{index}]"
                                    )
                                    continue
                                native_label_claims_by_record[quad.subject].add(
                                    (role, _literal_value(value, language, None))
                                )
                    elif label_normalization is not None:
                        structural_failures.append(
                            f"{pack}: source record <{quad.subject}> has non-object "
                            "nativePayload.labelRoleNormalization"
                        )
                    for field_name, field_value in payload.items():
                        if not isinstance(field_value, list):
                            continue
                        for index, row in enumerate(field_value):
                            if not isinstance(row, dict) or not {
                                "propertyIri",
                                "property_iri",
                            }.intersection(row):
                                continue
                            property_iri = row.get(
                                "propertyIri",
                                row.get("property_iri"),
                            )
                            value = next(
                                (
                                    row[name]
                                    for name in ("value", "lexicalForm", "lexical_form")
                                    if name in row
                                ),
                                None,
                            )
                            language = next(
                                (
                                    row[name]
                                    for name in ("language", "languageTag", "language_tag")
                                    if name in row
                                ),
                                None,
                            )
                            datatype = next(
                                (
                                    row[name]
                                    for name in ("datatype", "datatypeIri", "datatype_iri")
                                    if name in row
                                ),
                                None,
                            )
                            claim_subject = row.get(
                                "subjectIri",
                                row.get("subject_iri"),
                            )
                            if (
                                not isinstance(property_iri, str)
                                or ":" not in property_iri
                                or not isinstance(value, str)
                                or (
                                    claim_subject is not None
                                    and (
                                        not isinstance(claim_subject, str)
                                        or ":" not in claim_subject
                                    )
                                )
                                or (language is not None and not isinstance(language, str))
                                or (datatype is not None and not isinstance(datatype, str))
                                or (language is not None and datatype is not None)
                            ):
                                structural_failures.append(
                                    f"{pack}: source record <{quad.subject}> has invalid "
                                    f"nativePayload.{field_name}[{index}] literal evidence"
                                )
                                continue
                            native_literal_claims_by_record[quad.subject].add(
                                (
                                    claim_subject,
                                    property_iri,
                                    _literal_value(value, language, datatype),
                                )
                            )
                    for field_name in (
                        "mappingRelations",
                        "semanticRelations",
                        "directSemanticRelations",
                    ):
                        rows = payload.get(field_name)
                        if rows is None:
                            continue
                        if not isinstance(rows, list):
                            structural_failures.append(
                                f"{pack}: source record <{quad.subject}> has non-array "
                                f"nativePayload.{field_name}"
                            )
                            continue
                        for index, row in enumerate(rows):
                            if not isinstance(row, Mapping):
                                structural_failures.append(
                                    f"{pack}: source record <{quad.subject}> has non-object "
                                    f"nativePayload.{field_name}[{index}]"
                                )
                                continue
                            subject = row.get("subject_iri", row.get("subjectIri"))
                            predicate = row.get("predicate_iri", row.get("predicateIri"))
                            obj = row.get("object_iri", row.get("objectIri"))
                            if not all(
                                isinstance(value, str) and ":" in value
                                for value in (subject, predicate, obj)
                            ):
                                structural_failures.append(
                                    f"{pack}: source record <{quad.subject}> has invalid "
                                    f"nativePayload.{field_name}[{index}] relation"
                                )
                                continue
                            native_relations.add((subject, predicate, obj))
                    publisher_relation = payload.get("publisherRelation")
                    if publisher_relation is not None:
                        if not isinstance(publisher_relation, Mapping):
                            structural_failures.append(
                                f"{pack}: source record <{quad.subject}> has non-object "
                                "nativePayload.publisherRelation"
                            )
                        else:
                            subject = publisher_relation.get("subjectIri")
                            predicate = publisher_relation.get("predicateIri")
                            obj = publisher_relation.get("objectIri")
                            if not all(
                                isinstance(value, str) and ":" in value
                                for value in (subject, predicate, obj)
                            ):
                                structural_failures.append(
                                    f"{pack}: source record <{quad.subject}> has invalid "
                                    "nativePayload.publisherRelation"
                                )
                            else:
                                native_relations.add((subject, predicate, obj))
        except Exception as error:  # noqa: BLE001 - inspect every other pack in the comparison
            structural_failures.append(f"{pack}: could not be read: {type(error).__name__}: {error}")

    pref: dict[str, set[LiteralValue]] = defaultdict(set)
    alt: dict[str, set[LiteralValue]] = defaultdict(set)
    hidden: dict[str, set[LiteralValue]] = defaultdict(set)
    for subject, label_node in pref_edges:
        forms = label_forms.get(label_node, set())
        if len(forms) != 1:
            structural_failures.append(
                f"label node <{label_node}> referenced as preferred label has {len(forms)} literal forms"
            )
        pref[subject].update(forms)
    for subject, label_node in alt_edges:
        forms = label_forms.get(label_node, set())
        if len(forms) != 1:
            structural_failures.append(
                f"label node <{label_node}> referenced as alternate label has {len(forms)} literal forms"
            )
        alt[subject].update(forms)
    for subject, label_node in hidden_edges:
        forms = label_forms.get(label_node, set())
        if len(forms) != 1:
            structural_failures.append(
                f"label node <{label_node}> referenced as hidden label has {len(forms)} literal forms"
            )
        hidden[subject].update(forms)

    # Some source labels are intentionally suppressed from the Atlas display role
    # to satisfy SKOS S13. Restore only the exact publisher role/value retained in
    # native evidence before comparing the source claim set.
    role_targets = {
        "preferred": pref,
        "alternate": alt,
        "hidden": hidden,
    }
    for record, claims in native_label_claims_by_record.items():
        target = record_targets.get(record)
        if target is None:
            continue
        for role, literal in claims:
            role_targets[role][target].add(literal)

    relation_rows: set[tuple[str, str, str]] = set()
    for assertion, parts in sorted(reified.items()):
        missing_parts = [
            _short(predicate)
            for predicate in (RDF_SUBJECT, RDF_PREDICATE, RDF_OBJECT)
            if predicate not in parts
        ]
        if missing_parts:
            structural_failures.append(
                f"relation assertion <{assertion}> is incomplete; missing {missing_parts}"
            )
            continue
        relation_rows.add((parts[RDF_SUBJECT], parts[RDF_PREDICATE], parts[RDF_OBJECT]))
    relations = frozenset(relation_rows)

    # A comparison pack must not silently collapse multiple source records onto one resource.
    record_claim_subjects = set(record_targets) | set(native_payloads)
    for record in sorted(record_claim_subjects - source_records):
        structural_failures.append(
            f"record-like subject <{record}> is not typed atlas:SourceRecord"
        )

    record_by_target: dict[str, str] = {}
    for record, target in sorted(record_targets.items()):
        prior_record = record_by_target.get(target)
        if prior_record is not None and prior_record != record:
            structural_failures.append(
                f"source records <{prior_record}> and <{record}> both represent <{target}>"
            )
        record_by_target[target] = record

    # Re-key native scheme memberships from source record to the resource it represents.
    keyed_native: dict[str, frozenset[str]] = {}
    for record, scheme_iris in native_schemes.items():
        target = record_targets.get(record)
        if target is not None:
            if target in keyed_native and keyed_native[target] != scheme_iris:
                structural_failures.append(
                    f"source records for <{target}> carry contradictory nativePayload.schemeIris values"
                )
            keyed_native[target] = scheme_iris

    keyed_native_top_concepts: dict[str, frozenset[str]] = {}
    for record, scheme_iris in native_top_concepts.items():
        target = record_targets.get(record)
        if target is not None:
            if (
                target in keyed_native_top_concepts
                and keyed_native_top_concepts[target] != scheme_iris
            ):
                structural_failures.append(
                    f"source records for <{target}> carry contradictory "
                    "nativePayload.topConceptOfIris values"
                )
            keyed_native_top_concepts[target] = scheme_iris

    keyed_native_literal_claims: set[tuple[str, str, LiteralValue]] = set()
    for record, claims in native_literal_claims_by_record.items():
        target = record_targets.get(record)
        if target is not None:
            keyed_native_literal_claims.update(
                (claim_subject or target, predicate, literal)
                for claim_subject, predicate, literal in claims
            )

    return AtlasView(
        resources=frozenset(resources),
        releases=frozenset(releases),
        rdf_types={key: frozenset(value) for key, value in rdf_types.items()},
        resource_profiles={
            key: frozenset(value) for key, value in resource_profiles.items()
        },
        semantic_rings={key: frozenset(value) for key, value in semantic_rings.items()},
        atlas_scheme_iris={
            key: frozenset(value) for key, value in atlas_scheme_iris.items()
        },
        skos_schemes=frozenset(skos_schemes),
        pref_labels={key: frozenset(value) for key, value in pref.items()},
        alt_labels={key: frozenset(value) for key, value in alt.items()},
        hidden_labels={key: frozenset(value) for key, value in hidden.items()},
        notations={key: frozenset(value) for key, value in notations.items()},
        definitions={key: frozenset(value) for key, value in definitions.items()},
        notes={key: frozenset(value) for key, value in notes.items()},
        relations=relations,
        memberships=frozenset(memberships),
        source_records=frozenset(source_records),
        record_locators=frozenset(
            locator for subject, locator in locator_by_subject.items() if subject in source_records
        ),
        record_locator_pairs=frozenset(
            (target, locator_by_subject[record])
            for record, target in record_targets.items()
            if record in source_records and record in locator_by_subject
        ),
        record_targets=dict(sorted(record_targets.items())),
        record_source_locators=dict(sorted(locator_by_subject.items())),
        record_source_digests=dict(sorted(record_source_digests.items())),
        native_payloads=dict(sorted(native_payloads.items())),
        native_scheme_iris=keyed_native,
        native_top_concept_of_iris=keyed_native_top_concepts,
        native_literal_claims=frozenset(keyed_native_literal_claims),
        native_relations=frozenset(native_relations),
        raw_source_iri_claims=frozenset(raw_source_iri_claims),
        raw_source_literal_claims=frozenset(raw_source_literal_claims),
        all_raw_iri_claims=frozenset(all_raw_iri_claims),
        all_raw_literal_claims=frozenset(all_raw_literal_claims),
        label_links=frozenset(
            {
                *((subject, SKOSXL_PREF_LABEL, node) for subject, node in pref_edges),
                *((subject, SKOSXL_ALT_LABEL, node) for subject, node in alt_edges),
                *((subject, SKOSXL_HIDDEN_LABEL, node) for subject, node in hidden_edges),
            }
        ),
        relation_assertions=frozenset(reified),
        structural_failures=tuple(structural_failures),
        checked_packs=tuple(packs),
        checked_pack_transports=dict(sorted(checked_pack_transports.items())),
    )


# --------------------------------------------------------------------------------------
# Source registry
# --------------------------------------------------------------------------------------


def _registry_source_pin(
    filename: str,
    sha256: str,
    byte_length: int,
    source_iri: str,
    *,
    fmt: str = "turtle",
    zip_member: str | None = None,
    role: str = "publisherSource",
    construction_path: str | None = None,
) -> SourcePin:
    """Declare one local publisher file and its exact construction-summary identity."""
    return SourcePin(
        path=filename,
        sha256=sha256,
        byte_length=byte_length,
        fmt=fmt,
        zip_member=zip_member,
        role=role,
        source_iri=source_iri,
        construction_path=(
            construction_path
            if construction_path is not None
            else f"refspec/output/registry-real-data-sources/{filename}"
        ),
    )


_NATIVE_CONTROL_CAPTURE_PIN = SourcePin(
    path="research/evidence/regulatory-native-controls-2026-08-03/source-native-control-capture.json",
    sha256="sha256:7bd204d3e2070a81cc1a52e232032ac673779f5c3fd434330bc383726dc7c25d",
    byte_length=183_479,
    fmt="json",
    role="normalizedControlCapture",
    source_iri="urn:ref:registry:regulatory-native-control-capture:2026-08-03",
)

_NATIVE_CONTROL_TABLES: Mapping[
    str,
    tuple[SourcePin, str, int, tuple[str, ...]],
] = {
    "dockets": (
        SourcePin(
            path="output/registry-real-data-sources/regulatory-native-current/dockets.parquet",
            sha256="sha256:b14cd488b7898391cff448ac4de19f85936072dcb1aa105da32eea88e6fd7938",
            byte_length=14_347_053,
            fmt="parquet",
            role="sourceDistribution",
            source_iri="https://r2.spicy-regs.dev/dockets.parquet",
        ),
        "https://r2.spicy-regs.dev/dockets.parquet",
        276_326,
        (
            "docket_id",
            "agency_code",
            "title",
            "docket_type",
            "modify_date",
            "abstract",
            "rin",
        ),
    ),
    "documents": (
        SourcePin(
            path="output/registry-real-data-sources/regulatory-native-current/documents.parquet",
            sha256="sha256:bb42f79eacd0a1bfb19b7711f5d6859d288133acffa8f585ee468acdd5cb4975",
            byte_length=54_865_512,
            fmt="parquet",
            role="sourceDistribution",
            source_iri="https://r2.spicy-regs.dev/documents.parquet",
        ),
        "https://r2.spicy-regs.dev/documents.parquet",
        1_990_136,
        (
            "document_id",
            "docket_id",
            "agency_code",
            "title",
            "document_type",
            "posted_date",
            "modify_date",
            "comment_start_date",
            "comment_end_date",
            "file_url",
            "attachments_json",
            "fr_doc_num",
            "withdrawn",
            "reason_withdrawn",
            "additional_rins",
            "text_content",
            "text_extraction_status",
        ),
    ),
    "federal_register": (
        SourcePin(
            path="output/registry-real-data-sources/regulatory-native-current/federal_register.parquet",
            sha256="sha256:702018767f73b914ef11696b47ff360e616acc2da4769f40b0d0d90f03c5ffea",
            byte_length=122_957_045,
            fmt="parquet",
            role="sourceDistribution",
            source_iri="https://r2.spicy-regs.dev/federal_register.parquet",
        ),
        "https://r2.spicy-regs.dev/federal_register.parquet",
        800_619,
        (
            "document_number",
            "title",
            "abstract",
            "document_type",
            "publication_date",
            "effective_on",
            "comments_close_on",
            "signing_date",
            "agencies_json",
            "agency_slugs",
            "docket_ids_json",
            "regulation_id_numbers_json",
            "cfr_references_json",
            "html_url",
            "pdf_url",
            "body_html_url",
            "volume",
            "start_page",
            "end_page",
            "subtype",
            "executive_order_number",
            "modify_date",
        ),
    ),
    "unified_agenda": (
        SourcePin(
            path="output/registry-real-data-sources/regulatory-native-current/unified_agenda.parquet",
            sha256="sha256:e6862d5d6a5300f10c70eeaf321f1e82e1f5332f71069d07723cc584ee6a85ae",
            byte_length=1_017_503,
            fmt="parquet",
            role="sourceDistribution",
            source_iri="https://r2.spicy-regs.dev/unified_agenda.parquet",
        ),
        "https://r2.spicy-regs.dev/unified_agenda.parquet",
        3_954,
        (
            "rin",
            "agency_code",
            "agency_name",
            "title",
            "abstract",
            "rin_status",
            "rule_stage",
            "priority_category",
            "agenda_edition",
            "major",
            "publication_id",
            "timetable_json",
            "cfr_references_json",
            "legal_authority_json",
            "first_action_date",
            "next_action_date",
            "url",
        ),
    ),
}

_NATIVE_CONTROL_SELECTORS = (
    ("regulations-gov-docket-type", "dockets", "docket_type", "scalar"),
    ("regulations-gov-docket-agency-code", "dockets", "agency_code", "scalar"),
    ("regulations-gov-document-type", "documents", "document_type", "scalar"),
    ("regulations-gov-document-agency-code", "documents", "agency_code", "scalar"),
    (
        "regulations-gov-attachment-format",
        "documents",
        "attachments_json",
        "jsonArrayFormat",
    ),
    ("federal-register-document-type", "federal_register", "document_type", "scalar"),
    (
        "federal-register-presidential-subtype",
        "federal_register",
        "subtype",
        "scalar",
    ),
    (
        "federal-register-agency-slug",
        "federal_register",
        "agencies_json",
        "jsonArrayAgencySlug",
    ),
    (
        "federal-register-unresolved-agency-name",
        "federal_register",
        "agencies_json",
        "jsonArrayUnresolvedAgencyRawName",
    ),
    ("unified-agenda-rin-status", "unified_agenda", "rin_status", "scalar"),
    ("unified-agenda-rule-stage", "unified_agenda", "rule_stage", "scalar"),
    (
        "unified-agenda-priority-category",
        "unified_agenda",
        "priority_category",
        "scalar",
    ),
    ("unified-agenda-major-flag", "unified_agenda", "major", "scalar"),
    ("unified-agenda-agency-code", "unified_agenda", "agency_code", "scalar"),
)


def _native_control_source_spec(
    control_id: str,
    source_table: str,
    source_field: str,
    extraction: str,
) -> SourceSpec:
    parquet_pin, source_iri, row_count, columns = _NATIVE_CONTROL_TABLES[source_table]
    release_key = f"regulatory-native-{control_id}"
    return SourceSpec(
        name=release_key,
        kind="native-control",
        release_keys=(release_key,),
        inputs=(parquet_pin, _NATIVE_CONTROL_CAPTURE_PIN),
        native_control=NativeControlSelector(
            control_id=control_id,
            source_table=source_table,
            source_field=source_field,
            extraction=extraction,
            source_iri=source_iri,
            expected_row_count=row_count,
            expected_columns=columns,
            construction_key=release_key,
        ),
    )


NATIVE_CONTROL_SOURCES = tuple(
    _native_control_source_spec(*selector) for selector in _NATIVE_CONTROL_SELECTORS
)


def _rdf_source_policy(
    evaluated_native_payload_fields: frozenset[str] = frozenset(),
    *,
    atlas_only_native_payload_fields: frozenset[str] = frozenset(),
    additional_annotation_predicates: tuple[str, ...] = (),
    additional_relation_predicates: tuple[str, ...] = (),
    label_language_inverse: str = "english-tagged",
    literal_reification_id_rules: tuple[tuple[str, str, str], ...] = (),
    note_predicate_inverse: str | None = None,
    reification_base_iri: str | None = None,
    reification_predicates: tuple[str, ...] = (),
    reification_weight_predicate: str | None = None,
    reification_weight_value: LiteralValue | None = None,
    relation_predicate_inverse: tuple[tuple[str, str], ...] = (),
    relation_scope: str = "member-subject",
    source_wide_literal_predicates: tuple[str, ...] = (),
    record_digest_input_paths: tuple[str, ...] = (),
    record_locator: str | None = None,
    record_input_path_by_resource: tuple[tuple[str, str], ...] = (),
    record_locator_by_resource: tuple[tuple[str, str], ...] = (),
) -> RdfSourcePolicy:
    """Declare only the publisher-evidence fields one RDF adapter reverses."""
    return RdfSourcePolicy(
        evaluated_native_payload_fields=evaluated_native_payload_fields,
        atlas_only_native_payload_fields=atlas_only_native_payload_fields,
        additional_annotation_predicates=additional_annotation_predicates,
        additional_relation_predicates=additional_relation_predicates,
        label_language_inverse=label_language_inverse,
        literal_reification_id_rules=literal_reification_id_rules,
        note_predicate_inverse=note_predicate_inverse,
        reification_base_iri=reification_base_iri,
        reification_predicates=reification_predicates,
        reification_weight_predicate=reification_weight_predicate,
        reification_weight_value=reification_weight_value,
        relation_predicate_inverse=relation_predicate_inverse,
        relation_scope=relation_scope,
        source_wide_literal_predicates=source_wide_literal_predicates,
        record_digest_input_paths=record_digest_input_paths,
        record_locator=record_locator,
        record_input_path_by_resource=record_input_path_by_resource,
        record_locator_by_resource=record_locator_by_resource,
    )


_GENERIC_SKOS_NATIVE_FIELDS = frozenset(
    {"publisherConceptIri", "schemeIris", "topConceptOfIris"}
)

# Every Publications Office release ships the same dataset-description layer in
# its metadata file, so the comparisons that read those files share one
# declaration rather than several drifting copies of it.
#
# cdm:work and its relatives ARE listed here, which needs saying plainly. The
# publisher describes a whole family of release entities -- the abstract work,
# the dated release, its documentation, the agent that published it. Atlas
# adopts exactly one of them as its own source-release node, and that one can
# never be covered by this declaration: adopted release IRIs are compared
# subjects (see _compared_publisher_subjects), so the overlap guard fails the
# declaration rather than letting it hide them. The split is made by evidence
# from the Atlas pack, not by a hand-picked predicate allowlist.
_PUBLICATIONS_OFFICE_DATASET_DESCRIPTION = DeclaredClaimExclusion(
    name="publisherDatasetDescription",
    reason=(
        "the pinned metadata files carry the Publications Office's own "
        "description of the datasets they ship -- void:Linkset and void:Dataset "
        "statistics (including the blank-node void:classPartition counts), lime "
        "lexicalization sets, dcat catalogue, distribution and service records, "
        "the align:Ontology/align:Alignment header, the cdm release works that "
        "Atlas does not adopt, and the EU authority entries those records cite. "
        "Every one of them describes a FILE or a publication event, not a term. "
        "Atlas asserts nothing about any of these subjects, which is what the "
        "paired Atlas-side count proves; the one release IRI Atlas DOES adopt is "
        "a compared subject and is excluded from this exclusion by the overlap "
        "guard, then compared field by field by source-release-metadata"
    ),
    subject_types=frozenset(
        {
            f"{ALIGNMENT}Alignment",
            f"{ALIGNMENT}Ontology",
            f"{CDM}agent",
            f"{CDM}complex_work",
            f"{CDM}concept",
            f"{CDM}documentation",
            f"{CDM}work",
            f"{CDM}work_dataset",
            f"{DCAT}Catalog",
            f"{DCAT}DataService",
            f"{DCAT}Dataset",
            f"{DCAT}Distribution",
            f"{LIME}LexicalizationSet",
            f"{MDR}DatasetArchetype",
            f"{MDR}DatasetRealization",
            f"{MDR}RDFDataset",
            f"{STMDR}SemanticTurkeyInstance",
            f"{VOID}Dataset",
            f"{VOID}DatasetDescription",
            f"{VOID}Linkset",
        }
    ),
)


def _repository_source_pin(
    path: str,
    sha256: str,
    byte_length: int,
    source_iri: str,
    *,
    fmt: str,
    role: str = "publisherSource",
) -> SourcePin:
    """Declare publisher bytes pinned directly from a repository fixture."""
    return SourcePin(
        path=path,
        sha256=sha256,
        byte_length=byte_length,
        fmt=fmt,
        role=role,
        source_iri=source_iri,
    )


_BILLSTATUS_GUIDE_PIN = _repository_source_pin(
    "tests/fixtures/billstatus_codes/billstatus-xml-user-guide-2026-08-03.md",
    "sha256:a10909696b2ed2244d75c76e75fa32bc3e4eb926deab7e4e00592a6a01c3ad3a",
    38_802,
    "https://raw.githubusercontent.com/usgpo/bill-status/master/BILLSTATUS-XML_User_User-Guide.md",
    fmt="markdown",
)


LONG_TAIL_SOURCE_LISTS: tuple[SourceSpec, ...] = (
    SourceSpec(
        name="billstatus-action-codes",
        kind="source-list",
        release_keys=("billstatus-action-codes",),
        inputs=(_BILLSTATUS_GUIDE_PIN,),
        source_list=SourceListSelector(
            reader=SOURCE_LIST_READER,
            extraction="markdown-table",
            expected_record_count=36,
            source_assertion="action-code value and description",
            table_headers=("Code", "Text in the `<actionCode>` Element"),
            label_column=1,
            notation_columns=(0,),
        ),
    ),
    SourceSpec(
        name="billstatus-bill-types",
        kind="source-list",
        release_keys=("billstatus-bill-types",),
        inputs=(_BILLSTATUS_GUIDE_PIN,),
        source_list=SourceListSelector(
            reader=SOURCE_LIST_READER,
            extraction="billstatus-bill-types",
            expected_record_count=8,
            source_assertion="bill-type possible value",
        ),
    ),
    SourceSpec(
        name="billstatus-summary-version-codes",
        kind="source-list",
        release_keys=("billstatus-summary-version-codes",),
        inputs=(_BILLSTATUS_GUIDE_PIN,),
        source_list=SourceListSelector(
            reader=SOURCE_LIST_READER,
            extraction="markdown-table",
            expected_record_count=88,
            source_assertion="summary version code, chamber, and action description",
            table_headers=(
                "LOC Summaries `<versionCode>`",
                "Chamber",
                "Text in the `<actionDesc>` Element",
            ),
            label_column=2,
            notation_columns=(0, 1),
        ),
    ),
    SourceSpec(
        name="cbo-119th-congress-publications",
        kind="source-list",
        release_keys=("cbo-119th-congress-publications",),
        inputs=(
            _repository_source_pin(
                "tests/fixtures/cbo_topic_codes/cbo-119congress-cost-estimates-2026-08-04.xml",
                "sha256:edc957a1115320f1c0da4b02c33d1af146a3c508592ee20b4909e0a8db44d968",
                375_365,
                "https://www.cbo.gov/rss/119congress-cost-estimates.xml",
                fmt="xml",
            ),
        ),
        source_list=SourceListSelector(
            reader=SOURCE_LIST_READER,
            extraction="cbo-publication-xml",
            expected_record_count=1_058,
            source_assertion=(
                "publication URL identity, title, date, description, feed key, and bill number"
            ),
            compare_resource_iri=True,
            native_payload_fields=(
                "billNumber",
                "date",
                "description",
                "feedItemKey",
            ),
            normalize_whitespace=False,
        ),
    ),
    SourceSpec(
        name="census-data-flags",
        kind="source-list",
        release_keys=("census-data-flags",),
        inputs=(
            _repository_source_pin(
                "tests/fixtures/census_gov_finance_codes/census-aspep-data-flag-codes-2026-08-03.html",
                "sha256:ef47e5a56d2997b4a05f1a3d5c6d112c92735bc876990ae03038020d07b19c39",
                323_893,
                "https://www.census.gov/programs-surveys/apes/technical-documentation/code-lists/data-flags.html",
                fmt="html",
            ),
        ),
        source_list=SourceListSelector(
            reader=SOURCE_LIST_READER,
            extraction="html-table",
            expected_record_count=16,
            source_assertion="data-flag code and description",
            table_headers=("Reported Data",),
            label_column=1,
            notation_columns=(0,),
            ignored_single_cell_rows=("Imputed Data",),
        ),
    ),
    SourceSpec(
        name="census-function-items",
        kind="source-list",
        release_keys=("census-function-items",),
        inputs=(
            _repository_source_pin(
                "tests/fixtures/census_gov_finance_codes/census-aspep-function-item-codes-2026-08-03.html",
                "sha256:77b6ddf18572165b6e4526042dacba9fcff80b79cc7f21f1193db3210730dcb3",
                321_793,
                "https://www.census.gov/programs-surveys/apes/technical-documentation/code-lists/data-function.html",
                fmt="html",
            ),
        ),
        source_list=SourceListSelector(
            reader=SOURCE_LIST_READER,
            extraction="html-table-split",
            expected_record_count=33,
            source_assertion="function item code and label",
            table_index=0,
            data_row_start=0,
            split_pattern=r"(?P<notation>\d{3}) = (?P<label>.+)",
        ),
    ),
    SourceSpec(
        name="courtlistener-jurisdictions-2026-08-03",
        kind="source-list",
        release_keys=("courtlistener-jurisdictions-2026-08-03",),
        inputs=(
            _registry_source_pin(
                "courtlistener-jurisdictions-zyte.html",
                "sha256:883446028b029078c032bfe7c3545f9e109bb328c79ec486fbbbdbf35580b292",
                3_156_029,
                "https://www.courtlistener.com/help/api/jurisdictions/",
                fmt="html",
            ),
        ),
        source_list=SourceListSelector(
            reader=SOURCE_LIST_READER,
            extraction="html-table",
            expected_record_count=3_359,
            source_assertion=(
                "court name, platform abbreviation, and citation abbreviation"
            ),
            table_headers=(
                "Name",
                "Count",
                "Jurisdiction",
                "Homepage",
                "Abbreviation",
                "Citation Abbreviation",
                "Start Date",
                "End Date",
                "In Use",
                "Modified",
            ),
            label_column=0,
            notation_columns=(4, 5),
        ),
    ),
    SourceSpec(
        name="fec-committee-type",
        kind="source-list",
        release_keys=("fec-committee-type",),
        inputs=(
            _repository_source_pin(
                "tests/fixtures/fec_committee_codes/fec-committee-type-code-descriptions-2026-08-03.html",
                "sha256:84e9f16628fd2475750cd89a3947f2c737a5f66c8ced04aea6b1118ac2aecaa4",
                28_121,
                "https://www.fec.gov/campaign-finance-data/committee-type-code-descriptions/",
                fmt="html",
            ),
        ),
        source_list=SourceListSelector(
            reader=SOURCE_LIST_READER,
            extraction="html-table",
            expected_record_count=16,
            source_assertion="committee-type code and name",
            table_headers=("Committee type code", "Committee type", "Explanation"),
            label_column=1,
            notation_columns=(0,),
        ),
    ),
    SourceSpec(
        name="fec-party",
        kind="source-list",
        release_keys=("fec-party",),
        inputs=(
            _repository_source_pin(
                "tests/fixtures/fec_committee_codes/fec-party-code-descriptions-2026-08-03.html",
                "sha256:e17420381df0e5709449a8c9702600fde97503ea378ef357beef4c40ed6a6b09",
                29_578,
                "https://www.fec.gov/campaign-finance-data/party-code-descriptions/",
                fmt="html",
            ),
        ),
        source_list=SourceListSelector(
            reader=SOURCE_LIST_READER,
            extraction="html-table",
            expected_record_count=95,
            source_assertion="party code and description",
            table_headers=("Party code", "Party code description", "Notes"),
            label_column=1,
            notation_columns=(0,),
        ),
    ),
    SourceSpec(
        name="grants-gov-eligibilities",
        kind="source-list",
        release_keys=("grants-gov-eligibilities",),
        inputs=(
            _repository_source_pin(
                "tests/fixtures/grants_gov_codes/grants-gov-status-codes-2026-08-03.html",
                "sha256:bcbe4c44f8c1743eeaa26ab9f350c53214238c31d807057f248af8dd96cd5f85",
                46_093,
                "https://www.grants.gov/api/status-codes",
                fmt="html",
            ),
        ),
        source_list=SourceListSelector(
            reader=SOURCE_LIST_READER,
            extraction="html-table",
            expected_record_count=17,
            source_assertion="eligibility code and description",
            table_headers=("Code", "Description"),
            table_index=1,
            label_column=1,
            notation_columns=(0,),
        ),
    ),
    SourceSpec(
        name="grants-gov-funding-categories",
        kind="source-list",
        release_keys=("grants-gov-funding-categories",),
        inputs=(
            _repository_source_pin(
                "tests/fixtures/grants_gov_codes/grants-gov-status-codes-2026-08-03.html",
                "sha256:bcbe4c44f8c1743eeaa26ab9f350c53214238c31d807057f248af8dd96cd5f85",
                46_093,
                "https://www.grants.gov/api/status-codes",
                fmt="html",
            ),
        ),
        source_list=SourceListSelector(
            reader=SOURCE_LIST_READER,
            extraction="html-table",
            expected_record_count=26,
            source_assertion="funding-category code and description",
            table_headers=("Code", "Description"),
            table_index=2,
            label_column=1,
            notation_columns=(0,),
        ),
    ),
    SourceSpec(
        name="census-acs-geography-identifiers",
        kind="source-list",
        release_keys=("census-acs-geography-identifiers",),
        inputs=(
            _repository_source_pin(
                "tests/fixtures/census_geo_codes/acs-variables-2026-08-03.html",
                "sha256:cc018ff0aa9b5e9c73d57f537d281add5211fc47f2e3023940dbd0498386b416",
                5_326,
                "https://api.census.gov/data/2024/acs/acs1/spp/variables.html",
                fmt="html",
                role="publisherPageContainingPinnedSpan",
            ),
        ),
        source_list=SourceListSelector(
            reader=SOURCE_LIST_READER,
            extraction="html-table",
            expected_record_count=7,
            source_assertion="selected ACS variable name and label",
            table_index=0,
            label_column=1,
            notation_columns=(0,),
            ignored_single_cell_rows=("635 variables",),
            included_notations=frozenset(
                {"COUNTY", "for", "GEO_ID", "GEOCOMP", "in", "S0201_001E", "S0201_002E"}
            ),
        ),
    ),
    SourceSpec(
        name="census-tiger-geoid-structure",
        kind="source-list",
        release_keys=("census-tiger-geoid-structure",),
        inputs=(
            _repository_source_pin(
                "tests/fixtures/census_geo_codes/geoid-structure-2026-08-03.html",
                "sha256:61cfc7b6b8b4b5a20365e8a71985b7151e7e90b937f747db83f2a8d53b801f49",
                5_920,
                "https://www.census.gov/programs-surveys/geography/guidance/geo-identifiers.html",
                fmt="html",
                role="publisherPageContainingPinnedSpan",
            ),
        ),
        source_list=SourceListSelector(
            reader=SOURCE_LIST_READER,
            extraction="census-tiger-geoid",
            expected_record_count=14,
            source_assertion="GEOID structure/example label and published value",
        ),
    ),
    SourceSpec(
        name="epa-comptox-substance-bounded-2026-08-03",
        kind="source-list",
        release_keys=("epa-comptox-substance-bounded-2026-08-03",),
        inputs=(
            _registry_source_pin(
                "comptox-DTXSID7020182.normalized.html",
                "sha256:96166f421b896b79f0f0273b26908a5d0dbbcc6ab484e6b15fa41d71ca082803",
                334_109,
                "https://comptox.epa.gov/dashboard/chemical/details/DTXSID7020182",
                fmt="html",
                role="boundedPublisherSubstancePage",
                construction_path=(
                    "output/registry-real-data-sources/"
                    "comptox-DTXSID7020182.normalized.html"
                ),
            ),
        ),
        source_list=SourceListSelector(
            reader=SOURCE_LIST_READER,
            extraction="epa-comptox-html",
            expected_record_count=1,
            source_assertion="preferred name and DTXSID, DTXCID, and CASRN values",
            native_payload_fields=("casrn", "dtxcid", "dtxsid", "preferredName"),
            normalize_whitespace=False,
        ),
    ),
    SourceSpec(
        name="fac-api-field-dictionary-2026-08-03",
        kind="source-list",
        release_keys=("fac-api-field-dictionary-2026-08-03",),
        inputs=(
            _repository_source_pin(
                "tests/fixtures/fac_dictionary/fac-api-dictionary-2026-08-03.html",
                "sha256:95799a6f28b2f9a4d48bb0a88a1429381f2bc6e0677a9ec3a6608aa46a5a369c",
                74_851,
                "https://www.fac.gov/api/dictionary/",
                fmt="html",
                role="publisherFieldDictionary",
            ),
        ),
        source_list=SourceListSelector(
            reader=SOURCE_LIST_READER,
            extraction="fac-dictionary-html",
            expected_record_count=163,
            source_assertion="endpoint, field name, legacy field, and SQL data type",
            native_payload_fields=(
                "data_type",
                "endpoint",
                "formerly_endpoint",
                "gsa_field",
                "legacy_census_field",
            ),
        ),
    ),
    *(
        SourceSpec(
            name=name,
            kind="source-list",
            release_keys=(name,),
            inputs=(
                _repository_source_pin(
                    "tests/fixtures/fec_committee_codes/"
                    "fec-committee-master-file-description-2026-08-03.html",
                    "sha256:dda49be2e360d39bb1b7dcbc53239e627109a26fbaefe172688aca84abc4ff66",
                    29_343,
                    "https://www.fec.gov/campaign-finance-data/committee-master-file-description/",
                    fmt="html",
                ),
            ),
            source_list=SourceListSelector(
                reader=SOURCE_LIST_READER,
                extraction="fec-inline-html",
                expected_record_count=6,
                source_assertion=assertion,
                source_key=column,
            ),
        )
        for name, column, assertion in (
            ("fec-committee-designation", "CMTE_DSGN", "committee designation code and label"),
            ("fec-filing-frequency", "CMTE_FILING_FREQ", "filing frequency code and label"),
            ("fec-organization-type", "ORG_TP", "organization type code and label"),
        )
    ),
    SourceSpec(
        name="ferc-accession-number-formats",
        kind="source-list",
        release_keys=("ferc-accession-number-formats",),
        inputs=(
            _registry_source_pin(
                "ferc-accessibility-tips.html",
                "sha256:c9219bd08b8712e35389ff26f079a21e16d2b5fea68aaebf561bb9b203010688",
                39_466,
                "https://elibrary.ferc.gov/eLibrary/assets/Accessibility_Tips.html",
                fmt="html",
                construction_path=(
                    "output/registry-real-data-sources/ferc-accessibility-tips.html"
                ),
            ),
        ),
        source_list=SourceListSelector(
            reader=SOURCE_LIST_READER,
            extraction="ferc-accession-formats",
            expected_record_count=2,
            source_assertion="published accession-number format examples",
            compare_labels=False,
        ),
    ),
    *(
        SourceSpec(
            name=name,
            kind="source-list",
            release_keys=(name,),
            inputs=(
                _registry_source_pin(
                    "ferc-general-search-help.html",
                    "sha256:1f4b2883879602530c59095cc3d33fedbbf50a2d630e7bdf0226785259dd2b45",
                    7_447,
                    "https://elibrary.ferc.gov/eLibraryhelp/General_Search.htm",
                    fmt="html",
                    construction_path=(
                        "output/registry-real-data-sources/ferc-general-search-help.html"
                    ),
                ),
            ),
            source_list=SourceListSelector(
                reader=SOURCE_LIST_READER,
                extraction="ferc-help-list",
                expected_record_count=count,
                source_assertion=assertion,
                source_key=heading,
            ),
        )
        for name, heading, count, assertion in (
            ("ferc-sectors", "Industry Sector", 6, "industry-sector option"),
            ("ferc-security-levels", "Security Level", 4, "security-level option"),
        )
    ),
    SourceSpec(
        name="gao-cra-database-facets-2026-08-04",
        kind="source-list",
        release_keys=("gao-cra-database-facets-2026-08-04",),
        inputs=(
            _repository_source_pin(
                "tests/fixtures/gao_cra_facets/gao-cra-database-real-capture-2026-08-04.html",
                "sha256:50c6a5a94627a09539ddfb991397a22e257e2d1ec1f25e1206be5214322d9c12",
                130_944,
                "https://www.gao.gov/legal/congressional-review-act/search-database-of-rules?priority=all&processed=1&type=all",
                fmt="html",
                role="publisherSearchFacets",
            ),
        ),
        source_list=SourceListSelector(
            reader=SOURCE_LIST_READER,
            extraction="gao-cra-radio",
            expected_record_count=6,
            source_assertion="priority/type radio value and label",
        ),
    ),
    *(
        SourceSpec(
            name=name,
            kind="source-list",
            release_keys=(name,),
            inputs=(
                _repository_source_pin(
                    "tests/fixtures/gao_topics/gao-product-gao-26-108505-2026-08-04.html",
                    "sha256:c50268888ddb9c7cae2277d55229394b6434ba7503d79a61cb3ff3775a0683fd",
                    107_634,
                    "https://www.gao.gov/products/gao-26-108505",
                    fmt="html",
                ),
            ),
            source_list=selector,
        )
        for name, selector in (
            (
                "gao-report-gao-26-108505",
                SourceListSelector(
                    reader=SOURCE_LIST_READER,
                    extraction="gao-product-report",
                    expected_record_count=1,
                    source_assertion="canonical report identity, title, report number, and publication date",
                    compare_resource_iri=True,
                    native_payload_fields=("productReportNumber", "publicationDate"),
                ),
            ),
            (
                "gao-topics-observed-on-gao-26-108505",
                SourceListSelector(
                    reader=SOURCE_LIST_READER,
                    extraction="gao-product-topic",
                    expected_record_count=1,
                    source_assertion="topic label, topic path, and assigning report",
                    native_payload_fields=("observedOnProduct", "topicPath"),
                ),
            ),
        )
    ),
    SourceSpec(
        name="nasbo-program-areas",
        kind="source-list",
        release_keys=("nasbo-program-areas",),
        inputs=(
            _repository_source_pin(
                "tests/fixtures/census_gov_finance_codes/"
                "nasbo-ser-program-area-chapters-2026-08-03.html",
                "sha256:cff509abccd46a7bba32e5261164a430934db29004024c2b66d389d83ef9ba57",
                189_899,
                "https://www.nasbo.org/mainsite/reports-data/state-expenditure-report",
                fmt="html",
            ),
        ),
        source_list=SourceListSelector(
            reader=SOURCE_LIST_READER,
            extraction="nasbo-chapters",
            expected_record_count=7,
            source_assertion="program-area chapter title",
        ),
    ),
    SourceSpec(
        name="oira-review-controls",
        kind="source-list",
        release_keys=("oira-review-controls",),
        inputs=(
            _registry_source_pin(
                "oira-controls/sha256/bc92190b16d9855c05700592bd957491089434bed031aff369103add47af4f76/reviewStatus.html",
                "sha256:bc92190b16d9855c05700592bd957491089434bed031aff369103add47af4f76",
                405,
                "https://www.reginfo.gov/public/do/eoAdvancedSearch?eoStatusCode=CD#eoStatusCode",
                fmt="html",
                construction_path=(
                    "output/registry-real-data-sources/oira-controls/sha256/"
                    "bc92190b16d9855c05700592bd957491089434bed031aff369103add47af4f76/"
                    "reviewStatus.html"
                ),
            ),
            _registry_source_pin(
                "oira-controls/sha256/90ccba72caf4a3b98654937fd9a5297c0413b803b9e513c85b1851daf7fbb15a/ruleStage.html",
                "sha256:90ccba72caf4a3b98654937fd9a5297c0413b803b9e513c85b1851daf7fbb15a",
                1_390,
                "https://www.reginfo.gov/public/do/eoAdvancedSearch?eoStatusCode=CD#ruleStages",
                fmt="html",
                construction_path=(
                    "output/registry-real-data-sources/oira-controls/sha256/"
                    "90ccba72caf4a3b98654937fd9a5297c0413b803b9e513c85b1851daf7fbb15a/"
                    "ruleStage.html"
                ),
            ),
            _registry_source_pin(
                "oira-controls/sha256/a402dfde370f0b506dc5262b6002a41983e28f1ac7a4338c1ed048ee49cadbef/concludedAction.html",
                "sha256:a402dfde370f0b506dc5262b6002a41983e28f1ac7a4338c1ed048ee49cadbef",
                570,
                "https://www.reginfo.gov/public/do/eoAdvancedSearch?eoStatusCode=CD#concludedActionCode",
                fmt="html",
                construction_path=(
                    "output/registry-real-data-sources/oira-controls/sha256/"
                    "a402dfde370f0b506dc5262b6002a41983e28f1ac7a4338c1ed048ee49cadbef/"
                    "concludedAction.html"
                ),
            ),
            _registry_source_pin(
                "oira-controls/sha256/9bec2066ff2c01731b201765cad4a175a0b34230c30dfc854655341040cc9aea/meetingStatus.html",
                "sha256:9bec2066ff2c01731b201765cad4a175a0b34230c30dfc854655341040cc9aea",
                379,
                "https://www.reginfo.gov/public/do/eom12866Search#meetingType",
                fmt="html",
                construction_path=(
                    "output/registry-real-data-sources/oira-controls/sha256/"
                    "9bec2066ff2c01731b201765cad4a175a0b34230c30dfc854655341040cc9aea/"
                    "meetingStatus.html"
                ),
            ),
        ),
        source_list=SourceListSelector(
            reader=SOURCE_LIST_READER,
            extraction="oira-controls",
            expected_record_count=20,
            source_assertion="review, rule-stage, action, and meeting control value and label",
        ),
    ),
    SourceSpec(
        name="oversight-report-types",
        kind="source-list",
        release_keys=("oversight-report-types",),
        inputs=(
            _repository_source_pin(
                "tests/fixtures/oversight_report_types/oversight-reports-federal-2026-08-03.html",
                "sha256:8f1f8b29a5ecb224e19505ccdb24edf59b785273a60e807dc95355ffbc1785dd",
                110_293,
                "https://www.oversight.gov/reports/federal",
                fmt="html",
            ),
        ),
        source_list=SourceListSelector(
            reader=SOURCE_LIST_READER,
            extraction="oversight-report-select",
            expected_record_count=10,
            source_assertion="Report Type facet value and label",
        ),
    ),
    SourceSpec(
        name="pra-icr-controls",
        kind="source-list",
        release_keys=("pra-icr-controls",),
        inputs=(
            _repository_source_pin(
                "tests/fixtures/pra_icr_codes/pra-search-2026-08-03.html",
                "sha256:7f1e24bbe278c67171a71c9e85d50bf7c886646ae25c835194bda5a6e9d4fa4e",
                174_551,
                "https://www.reginfo.gov/public/do/PRASearch",
                fmt="html",
            ),
        ),
        source_list=SourceListSelector(
            reader=SOURCE_LIST_READER,
            extraction="pra-controls",
            expected_record_count=21,
            source_assertion="request/status options, burden input pairs, and OMB-number field shape",
        ),
    ),
    *(
        SourceSpec(
            name=name,
            kind="source-list",
            release_keys=(name,),
            inputs=(
                _repository_source_pin(
                    "tests/fixtures/regulations_gov_codes/regulations-gov-openapi-v4-2026-08-03.yaml",
                    "sha256:be43c866f5ca424a456bde36ea03cb9326c454ef4e1894a13df80b6dc6e22488",
                    60_826,
                    "https://open.gsa.gov/api/regulationsgov/v4/openapi.yaml",
                    fmt="yaml",
                ),
            ),
            source_list=SourceListSelector(
                reader=SOURCE_LIST_READER,
                extraction="yaml-enum",
                expected_record_count=count,
                source_assertion=f"{schema} enum value",
                source_key=schema,
            ),
        )
        for name, schema, count in (
            ("regulations-gov-docket-type", "DocketType", 2),
            ("regulations-gov-document-type", "DocumentType", 5),
            ("regulations-gov-submitter-type", "SubmitterType", 3),
        )
    ),
    *(
        SourceSpec(
            name=name,
            kind="source-list",
            release_keys=(name,),
            inputs=(
                _repository_source_pin(
                    "tests/fixtures/sam_assistance_listing_codes/"
                    "sam-assistance-listings-api-2026-08-03.html",
                    "sha256:6ea76d040e2190b02cad8192f50dbe00d39f01f5366f893cd24b6491dfdeeffd",
                    210_611,
                    "https://open.gsa.gov/api/assistance-listings-api/",
                    fmt="html",
                ),
            ),
            source_list=SourceListSelector(
                reader=SOURCE_LIST_READER,
                extraction="html-table",
                expected_record_count=count,
                source_assertion=assertion,
                table_headers=headers,
                table_indices=indices,
                label_column=1,
                notation_columns=(0,),
            ),
        )
        for name, count, assertion, headers, indices in (
            (
                "sam-assistance-assistance-types",
                17,
                "assistance type code and name",
                ("Assistance Type Code", "Assistance Type Name"),
                (29, 30),
            ),
            (
                "sam-assistance-eligible-applicant-types",
                44,
                "eligible applicant entity type code and name",
                ("Entity Type Code", "Entity Type Name"),
                (31,),
            ),
            (
                "sam-assistance-eligible-beneficiary-types",
                73,
                "eligible beneficiary entity type code and name",
                ("Entity Type Code", "Entity Type Name"),
                (32,),
            ),
        )
    ),
    *(
        SourceSpec(
            name=name,
            kind="source-list",
            release_keys=(name,),
            inputs=(
                _repository_source_pin(
                    "tests/fixtures/sam_opportunities_codes/"
                    "sam-get-opportunities-public-api-2026-08-03.html",
                    "sha256:448b85ab4a22e33d139295cb1d6a3a6384b685a936d8c645dd12e69ed938fa62",
                    46_217,
                    "https://open.gsa.gov/api/get-opportunities-public-api/",
                    fmt="html",
                ),
            ),
            source_list=selector,
        )
        for name, selector in (
            (
                "sam-opportunities-notice-types",
                SourceListSelector(
                    reader=SOURCE_LIST_READER,
                    extraction="sam-notice-types",
                    expected_record_count=11,
                    source_assertion="ptype code and label",
                ),
            ),
            (
                "sam-opportunities-opportunity-statuses",
                SourceListSelector(
                    reader=SOURCE_LIST_READER,
                    extraction="sam-opportunity-statuses",
                    expected_record_count=5,
                    source_assertion="opportunity status accepted value",
                ),
            ),
            (
                "sam-opportunities-set-aside-codes",
                SourceListSelector(
                    reader=SOURCE_LIST_READER,
                    extraction="html-table",
                    expected_record_count=18,
                    source_assertion="set-aside code and description",
                    table_headers=("Code", "SetAside Values"),
                    table_index=2,
                    label_column=1,
                    notation_columns=(0,),
                ),
            ),
        )
    ),
    SourceSpec(
        name="scotus-opinion-types",
        kind="source-list",
        release_keys=("scotus-opinion-types",),
        inputs=(
            _repository_source_pin(
                "tests/fixtures/scotus_opinion_types/scotus-opinions-2026-08-03.html",
                "sha256:26d9c70afb7ee7b66678eea7eb32851c74a10ee8e60249ffc5433a45a82b2bd5",
                42_237,
                "https://www.supremecourt.gov/opinions/opinions.aspx",
                fmt="html",
            ),
        ),
        source_list=SourceListSelector(
            reader=SOURCE_LIST_READER,
            extraction="scotus-opinion-types",
            expected_record_count=7,
            source_assertion="opinion navigation category and publication-stage term",
            casefold_labels=True,
        ),
    ),
    SourceSpec(
        name="sec-series-categories",
        kind="source-list",
        release_keys=("sec-series-categories",),
        inputs=(
            _repository_source_pin(
                "tests/fixtures/sec_series_categories/sec-rules-regulations-2026-08-03.html",
                "sha256:2f39c9d08f0dc55462e30fbda57315fd5159d47a4894dd113dc0bf226112c1b1",
                70_936,
                "https://www.sec.gov/rules-regulations",
                fmt="html",
            ),
        ),
        source_list=SourceListSelector(
            reader=SOURCE_LIST_READER,
            extraction="sec-categories",
            expected_record_count=19,
            source_assertion="side-navigation and subpage-card category label",
        ),
    ),
    *(
        SourceSpec(
            name=name,
            kind="source-list",
            release_keys=(name,),
            inputs=(
                _repository_source_pin(
                    "tests/fixtures/unified_agenda_codes/reginfo-rin-data-ver10262011.xsd",
                    "sha256:94fdcf4b382830cc44b9956c00439dc20a9643de402c298cee71293a14153b24",
                    22_730,
                    "https://www.reginfo.gov/public/xml/REGINFO_XML_Ver10262011.xsd",
                    fmt="xml",
                ),
            ),
            source_list=SourceListSelector(
                reader=SOURCE_LIST_READER,
                extraction="xsd-documentation-options",
                expected_record_count=count,
                source_assertion=f"{element} distinct documented option",
                source_key=f"{container}:{element}:{mode}",
            ),
        )
        for name, container, element, mode, count in (
            ("unified-agenda-priority-category", "RIN_INFOType", "PRIORITY_CATEGORY", "quoted", 6),
            ("unified-agenda-rule-stage", "RIN_INFOType", "RULE_STAGE", "quoted", 6),
            ("unified-agenda-timetable-action", "TIMETABLEType", "TTBL_ACTION", "plain", 34),
        )
    ),
)


SOURCES: tuple[SourceSpec, ...] = (
    *LONG_TAIL_SOURCE_LISTS,
    SourceSpec(
        name="agrovoc-c330-bounded-2026-08-03",
        kind="vocabulary",
        release_keys=("agrovoc-c330-bounded-2026-08-03",),
        inputs=(
            SourcePin(
                path="tests/fixtures/agrovoc_thesaurus/agrovoc-c330-sample.ttl",
                sha256="sha256:6e66080437622f9ccff470ec930203ca125e3c1e778df9f43a3fe4d78d98df15",
                byte_length=5_338,
                role="boundedPublisherConcept",
                source_iri="https://aims.fao.org/aos/agrovoc/c_330.ttl",
            ),
        ),
        policies=DIRECT_SKOS_POLICIES,
        included_concept_iris=frozenset(
            {"http://aims.fao.org/aos/agrovoc/c_330"}
        ),
        rdf_source=_rdf_source_policy(
            relation_scope="member-subject",
            record_digest_input_paths=(
                "tests/fixtures/agrovoc_thesaurus/agrovoc-c330-sample.ttl",
            ),
            record_locator_by_resource=(
                (
                    "http://aims.fao.org/aos/agrovoc/c_330",
                    "https://aims.fao.org/aos/agrovoc/c_330.ttl",
                ),
            ),
        ),
    ),
    SourceSpec(
        name="doe-osti-semantic-thesaurus-2020",
        kind="vocabulary",
        release_keys=("doe-osti-semantic-thesaurus-2020",),
        inputs=(
            _registry_source_pin(
                "osti-semantic-thesaurus-2020.rdf",
                "sha256:aeb9fb2d16caff675c7c9e12e0baff04ac4aded07488944acdf73ed859abe1d5",
                18_087_998,
                "https://www.osti.gov/servlets/purl/1668761",
                fmt="xml",
            ),
        ),
        policies=DIRECT_SKOS_POLICIES,
        rdf_source=_rdf_source_policy(
            _GENERIC_SKOS_NATIVE_FIELDS,
            note_predicate_inverse=SKOS_SCOPE_NOTE,
            record_digest_input_paths=("osti-semantic-thesaurus-2020.rdf",),
        ),
    ),
    SourceSpec(
        name="elsst-r6",
        kind="vocabulary",
        release_keys=("elsst-r6",),
        inputs=(
            _registry_source_pin(
                "ELSST_R6.ttl",
                "sha256:c362aec545db916ecb67af0eb9b8b4cecac1cb2118a717b69d8e6dad5591aa95",
                19_915_491,
                "https://storage.googleapis.com/cessda-elsst-datadump/2025/ELSST_R6.ttl",
            ),
        ),
        policies=DIRECT_SKOS_POLICIES,
        excluded_resource_predicates=frozenset(
            {
                f"{DCTERMS}created",
                f"{DCTERMS}description",
                f"{DCTERMS}identifier",
                f"{DCTERMS}isReplacedBy",
                f"{DCTERMS}isVersionOf",
                f"{DCTERMS}issued",
                f"{DCTERMS}license",
                f"{DCTERMS}modified",
                f"{DCTERMS}publisher",
                f"{DCTERMS}replaces",
                f"{DCTERMS}rightsHolder",
                f"{OWL}deprecated",
                f"{OWL}imports",
                f"{OWL}priorVersion",
                f"{OWL}versionInfo",
                f"{RDFS}label",
                f"{DCAT}CatalogRecord",
            }
        ),
        declared_claim_exclusions=(
            DeclaredClaimExclusion(
                name="importedVocabularyTermLabels",
                reason=(
                    "ELSST ships display labels for the PREDICATES its file uses "
                    "-- dcterms:identifier as 'URN', owl:imports as 'Uses other "
                    "schema:' -- so a browsing UI can render its own field names. "
                    "The subjects are terms in vocabularies ELSST imports, never "
                    "ELSST concepts (which all live under elsst.cessda.eu/id/6/), "
                    "so this is a legend for the file's own schema rather than "
                    "thesaurus content. Atlas asserts nothing about them. The "
                    "file's owl:Ontology header is deliberately NOT declared "
                    "here: Atlas adopts that IRI as its source release, so "
                    "source-release-metadata compares it"
                ),
                subject_iri_prefixes=(
                    DCTERMS,
                    OWL,
                    "http://rdf-vocabulary.ddialliance.org/xkos#",
                    DCAT,
                ),
            ),
        ),
        rdf_source=_rdf_source_policy(
            _GENERIC_SKOS_NATIVE_FIELDS | {"metadata"},
            record_digest_input_paths=("ELSST_R6.ttl",),
        ),
    ),
    SourceSpec(
        name="eurovoc-4.24",
        kind="vocabulary",
        release_keys=("eurovoc-4.24",),
        inputs=(
            _registry_source_pin(
                "eurovoc-4.24-metadata.ttl",
                "sha256:2c58402422f8588aada476f3516051e7fc980182130557a0d8c67497ffd8731d",
                36_011,
                "https://op.europa.eu/o/opportal-service/euvoc-download-handler?cellarURI=http%3A%2F%2Fpublications.europa.eu%2Fresource%2Fdistribution%2Feurovoc%2F20260708-0%2Fttl%2Fmetadata%2Feurovoc_metadata.ttl&fileName=eurovoc_metadata.ttl",
            ),
            _registry_source_pin(
                "eurovoc-4.24-skos-core.zip",
                "sha256:91bdb24e833ba431707f3980a19f475434ea8dcddb2b4d5e32e79e9fc1a0ca2f",
                8_567_290,
                "https://op.europa.eu/o/opportal-service/euvoc-download-handler?cellarURI=http%3A%2F%2Fpublications.europa.eu%2Fresource%2Fdistribution%2Feurovoc%2F20260708-0%2Fzip%2Fskos_core%2Feurovoc_in_skos_core_concepts.zip&fileName=eurovoc_in_skos_core_concepts.zip",
                fmt="xml",
                zip_member="eurovoc_in_skos_core_concepts.rdf",
            ),
        ),
        policies=DIRECT_SKOS_POLICIES,
        subset="eurovoc-main",
        declared_claim_exclusions=(_PUBLICATIONS_OFFICE_DATASET_DESCRIPTION,),
        rdf_source=_rdf_source_policy(
            _GENERIC_SKOS_NATIVE_FIELDS,
            record_digest_input_paths=("eurovoc-4.24-skos-core.zip",),
        ),
    ),
    SourceSpec(
        name="eurovoc-domains-4.24",
        kind="vocabulary",
        release_keys=("eurovoc-domains-4.24",),
        inputs=(
            _registry_source_pin(
                "eurovoc-4.24-metadata.ttl",
                "sha256:2c58402422f8588aada476f3516051e7fc980182130557a0d8c67497ffd8731d",
                36_011,
                "https://op.europa.eu/o/opportal-service/euvoc-download-handler?cellarURI=http%3A%2F%2Fpublications.europa.eu%2Fresource%2Fdistribution%2Feurovoc%2F20260708-0%2Fttl%2Fmetadata%2Feurovoc_metadata.ttl&fileName=eurovoc_metadata.ttl",
            ),
            _registry_source_pin(
                "eurovoc-4.24-skos-core.zip",
                "sha256:91bdb24e833ba431707f3980a19f475434ea8dcddb2b4d5e32e79e9fc1a0ca2f",
                8_567_290,
                "https://op.europa.eu/o/opportal-service/euvoc-download-handler?cellarURI=http%3A%2F%2Fpublications.europa.eu%2Fresource%2Fdistribution%2Feurovoc%2F20260708-0%2Fzip%2Fskos_core%2Feurovoc_in_skos_core_concepts.zip&fileName=eurovoc_in_skos_core_concepts.zip",
                fmt="xml",
                zip_member="eurovoc_in_skos_core_concepts.rdf",
            ),
        ),
        policies=DIRECT_SKOS_POLICIES,
        subset="eurovoc-domains",
        declared_claim_exclusions=(_PUBLICATIONS_OFFICE_DATASET_DESCRIPTION,),
        rdf_source=_rdf_source_policy(
            _GENERIC_SKOS_NATIVE_FIELDS,
            record_digest_input_paths=("eurovoc-4.24-skos-core.zip",),
        ),
    ),
    SourceSpec(
        name="eurovoc-lcsh-alignment-20240711",
        kind="mapping",
        release_keys=("eurovoc-lcsh-alignment-20240711",),
        inputs=(
            _registry_source_pin(
                "eurovoc-4.20-20240711-metadata.rdf",
                "sha256:ee86254e0635b9e3ea51ae365153eecd81f0040cb4580d28401986639b0b895d",
                14_093,
                "http://publications.europa.eu/resource/dataset/eurovoc/20240711-0",
                fmt="xml",
                role="publisherSourceReleaseMetadata",
            ),
            _registry_source_pin(
                "eurovoc-4.24-metadata.ttl",
                "sha256:2c58402422f8588aada476f3516051e7fc980182130557a0d8c67497ffd8731d",
                36_011,
                "https://op.europa.eu/o/opportal-service/euvoc-download-handler?cellarURI=http%3A%2F%2Fpublications.europa.eu%2Fresource%2Fdistribution%2Feurovoc%2F20260708-0%2Fttl%2Fmetadata%2Feurovoc_metadata.ttl&fileName=eurovoc_metadata.ttl",
                role="currentPublisherLinksetMetadata",
            ),
            _registry_source_pin(
                "eurovoc-lcsh-alignment-20240711-metadata.rdf",
                "sha256:3792ef3e3ebb18a01c97aa9d7a34f177ed947dd68496b7497a5693f06257faa6",
                8_157,
                "http://publications.europa.eu/resource/dataset/eurovoc_alignment_lcsh/20240711-0",
                fmt="xml",
                role="publisherAlignmentReleaseMetadata",
            ),
            _registry_source_pin(
                "eurovoc-lcsh-alignment-20240711.rdf",
                "sha256:dbd6e610ff497c4a39a79924cf50dcf92d5f3e9ab316d58d83c460dba6fb4853",
                332_124,
                "https://op.europa.eu/o/opportal-service/euvoc-download-handler?cellarURI=http%3A%2F%2Fpublications.europa.eu%2Fresource%2Fdistribution%2Feurovoc_alignment_lcsh%2F20240711-0%2Frdf%2Fskos_core_alignment%2Falign_EuroVoc_LCSH.rdf&fileName=align_EuroVoc_LCSH.rdf",
                fmt="xml",
                role="publisherAlignment",
            ),
        ),
        excluded_resource_predicates=frozenset(
            {
                RDF_TYPE,
                SKOS_IN_SCHEME,
                f"{CDM}concept_type_dataset_is_type_of_work_dataset",
                f"{CDM}frequency_of",
                f"{CDM}is_type_of",
                f"{CDM}publication_frequency_is_frequency_of_work_dataset",
            }
        ),
        declared_claim_exclusions=(
            _PUBLICATIONS_OFFICE_DATASET_DESCRIPTION,
            DeclaredClaimExclusion(
                name="cellarDocumentStoreResources",
                reason=(
                    "the metadata files name the Publications Office's own Cellar "
                    "storage objects and stamp them with owl:sameAs and cmr "
                    "creation/modification dates. These identify where the "
                    "publisher keeps the file, not what any term means"
                ),
                subject_iri_prefixes=(
                    "http://publications.europa.eu/resource/cellar/",
                ),
            ),
        ),
        rdf_source=RdfSourcePolicy(
            evaluated_native_payload_fields=frozenset(),
            relation_scope="all",
            record_digest_input_paths=("eurovoc-lcsh-alignment-20240711.rdf",),
            record_locator=(
                "https://op.europa.eu/o/opportal-service/euvoc-download-handler?"
                "cellarURI=http%3A%2F%2Fpublications.europa.eu%2Fresource%2Fdistribution%2F"
                "eurovoc_alignment_lcsh%2F20240711-0%2Frdf%2Fskos_core_alignment%2F"
                "align_EuroVoc_LCSH.rdf&fileName=align_EuroVoc_LCSH.rdf"
            ),
        ),
    ),
    SourceSpec(
        name="gemet-4.2.3",
        kind="vocabulary",
        release_keys=("gemet-4.2.3",),
        inputs=(
            _registry_source_pin(
                "gemet.rdf",
                "sha256:1b784b1a6387b8ec6c0d75ea5f0543970933172fcb0428a52de2c8ca536d20f1",
                33_332_557,
                "https://www.eionet.europa.eu/gemet/latest/gemet.rdf.gz",
                fmt="xml",
            ),
        ),
        policies=DIRECT_SKOS_POLICIES,
        declared_claim_exclusions=(
            DeclaredClaimExclusion(
                name="publisherCollectionAndSourceRegister",
                reason=(
                    "GEMET ships two entity kinds beside its concepts: the "
                    "Group/Theme/SuperGroup collections that arrange concepts for "
                    "browsing, and a bibliographic Source register naming the "
                    "dictionaries its definitions came from. Both reuse SKOS "
                    "predicates in ways GEMET does not use them on concepts -- "
                    "skos:prefLabel on a Group, an untagged skos:notation on every "
                    "Source -- which is why the reader declares its catalog scope "
                    "as the concept IRIs and their scheme membership and models "
                    "neither layer (see refspec.registry.gemet_thesaurus). Atlas "
                    "therefore asserts nothing at all about these 165 subjects, "
                    "which is what the paired Atlas-side count proves"
                ),
                subject_types=frozenset(
                    {
                        f"{SKOS}Collection",
                        f"{GEMET_SCHEMA}Group",
                        f"{GEMET_SCHEMA}Source",
                        f"{GEMET_SCHEMA}SuperGroup",
                        f"{GEMET_SCHEMA}Theme",
                    }
                ),
            ),
        ),
        rdf_source=_rdf_source_policy(
            _GENERIC_SKOS_NATIVE_FIELDS | {"labelRoleNormalization", "metadata"},
            additional_annotation_predicates=(f"{GEMET_SCHEMA}source",),
            record_digest_input_paths=("gemet.rdf",),
        ),
    ),
    SourceSpec(
        name="nalt-core-bounded-concepts-2026-08-03",
        kind="vocabulary",
        release_keys=("nalt-core-bounded-concepts-2026-08-03",),
        inputs=(
            SourcePin(
                path="tests/fixtures/nalt_core/nalt-core-127295-top-concept.ttl",
                sha256="sha256:ff37a0cb2d33a080c6d55b0bcf338673cbc26db6ea48a094761edc02c0e4e2ee",
                byte_length=3_238,
                role="publisherSource",
                source_iri=(
                    "https://lod.nal.usda.gov/rest/v1/nalt-core/data?"
                    "uri=https%3A%2F%2Flod.nal.usda.gov%2Fnalt%2F127295&format=text%2Fturtle"
                ),
            ),
            SourcePin(
                path="tests/fixtures/nalt_core/nalt-core-9084-animal-welfare.ttl",
                sha256="sha256:a038aff09a7ae825ea947a3f564748b3702ef36fe53cdc117cb22fc0aa8b3691",
                byte_length=5_523,
                role="publisherSource",
                source_iri=(
                    "https://lod.nal.usda.gov/rest/v1/nalt-core/data?"
                    "uri=https%3A%2F%2Flod.nal.usda.gov%2Fnalt%2F9084&format=text%2Fturtle"
                ),
            ),
        ),
        policies=DIRECT_SKOS_POLICIES,
        included_concept_iris=frozenset(
            {
                "https://lod.nal.usda.gov/nalt/127295",
                "https://lod.nal.usda.gov/nalt/9084",
            }
        ),
        rdf_source=_rdf_source_policy(
            relation_scope="member-subject",
            record_input_path_by_resource=(
                (
                    "https://lod.nal.usda.gov/nalt/127295",
                    "tests/fixtures/nalt_core/nalt-core-127295-top-concept.ttl",
                ),
                (
                    "https://lod.nal.usda.gov/nalt/9084",
                    "tests/fixtures/nalt_core/nalt-core-9084-animal-welfare.ttl",
                ),
            ),
            record_locator_by_resource=(
                (
                    "https://lod.nal.usda.gov/nalt/127295",
                    (
                        "https://lod.nal.usda.gov/rest/v1/nalt-core/data?"
                        "uri=https%3A%2F%2Flod.nal.usda.gov%2Fnalt%2F127295&format=text%2Fturtle"
                    ),
                ),
                (
                    "https://lod.nal.usda.gov/nalt/9084",
                    (
                        "https://lod.nal.usda.gov/rest/v1/nalt-core/data?"
                        "uri=https%3A%2F%2Flod.nal.usda.gov%2Fnalt%2F9084&format=text%2Fturtle"
                    ),
                ),
            ),
        ),
    ),
    SourceSpec(
        name="nasa-thesaurus-skos",
        kind="vocabulary",
        release_keys=("nasa-thesaurus-skos",),
        inputs=(
            _registry_source_pin(
                "thesaurus-SKOS.xml",
                "sha256:3cd92a0eb67c5656e4c740394abd2d27042ded79a4acf3e1286e73a7d863010f",
                32_943_406,
                "https://sti.nasa.gov/docs/thesaurus/thesaurus-SKOS.xml",
                fmt="xml",
            ),
        ),
        policies=DIRECT_SKOS_POLICIES,
        rdf_source=_rdf_source_policy(
            frozenset({"metadata", "publisherConceptIri"}),
            atlas_only_native_payload_fields=frozenset(
                {"detachedAnnotationsNotJoined"}
            ),
            additional_annotation_predicates=(
                "http://synaptica.net/zthes/termNote",
            ),
            additional_relation_predicates=(
                "http://synaptica.net/skm/UF",
                "http://synaptica.net/skm/Use",
            ),
            label_language_inverse="atlas-en-to-source-untagged",
            literal_reification_id_rules=(
                (
                    "http://synaptica.net/zthes/termNote",
                    "Definition",
                    "Definition-",
                ),
                (
                    "http://synaptica.net/zthes/termNote",
                    "Definition Source",
                    "DefinitionSource-",
                ),
                (
                    "http://synaptica.net/zthes/termNote",
                    "Scope Note",
                    "ScopeNote-",
                ),
            ),
            reification_base_iri=(
                "https://sti.nasa.gov/docs/thesaurus/thesaurus-SKOS.xml"
            ),
            reification_predicates=(
                *HIERARCHY_PREDICATES,
                "http://synaptica.net/skm/UF",
                "http://synaptica.net/skm/Use",
                "http://synaptica.net/zthes/termNote",
            ),
            reification_weight_predicate="http://synaptica.net/zthes/weight",
            reification_weight_value=_literal_value("100", None, None),
            relation_predicate_inverse=(
                (
                    "https://refspec.org/ns/atlas/v3#thesaurusRelated",
                    f"{SKOS}related",
                ),
                (
                    "https://refspec.org/ns/atlas/v3#thesaurusUse",
                    "http://synaptica.net/skm/Use",
                ),
                (
                    "https://refspec.org/ns/atlas/v3#thesaurusUsedFor",
                    "http://synaptica.net/skm/UF",
                ),
            ),
            record_digest_input_paths=("thesaurus-SKOS.xml",),
            source_wide_literal_predicates=(
                "http://synaptica.net/zthes/label",
            ),
        ),
    ),
    SourceSpec(
        name="federal-register-thesaurus-2025",
        kind="source-extract",
        release_keys=("federal-register-thesaurus-2025",),
        inputs=(
            _registry_source_pin(
                "federal-register-thesaurus-2025.pdf",
                "sha256:66dd28fff5defedfb151d04dc4ef255181085cce76618cb10c9372db6540810f",
                1_051_423,
                "https://www.archives.gov/files/federal-register/cfr/thesaurus-4-1-2025.pdf",
                fmt="pdf",
            ),
        ),
        source_extract=SourceExtractSelector(
            reader=FEDERAL_REGISTER_THESAURUS_2025_EXTRACT_READER,
            extract=SourcePin(
                path=(
                    "src/refspec/resources/federal_register_thesaurus/"
                    "2025-04-01/source-extract.json"
                ),
                sha256=(
                    "sha256:1ef6bb4ea2af001b8f2450888fb48715de2efda3"
                    "3190138a4ca5b90dafe71eb1"
                ),
                byte_length=789_855,
                fmt="json",
                role="repositoryCheckedSourceExtract",
                source_iri=(
                    "https://www.archives.gov/files/federal-register/cfr/"
                    "thesaurus-4-1-2025.pdf"
                ),
            ),
            source_release_iri=(
                "https://www.archives.gov/files/federal-register/cfr/"
                "thesaurus-4-1-2025.pdf"
            ),
            label_language="en",
            relation_predicate=f"{SKOS}related",
        ),
    ),
    *NATIVE_CONTROL_SOURCES,
)


def build_context(
    distribution: Path,
    source_root: Path,
    expectations: Expectations | None = None,
    specs: Sequence[SourceSpec] = SOURCES,
    scoped_out_specs: Sequence[SourceSpec] = (),
) -> Context:
    """Authenticate and read all declared inputs while collecting recoverable errors."""
    specs = tuple(specs)
    scoped_out_specs = tuple(scoped_out_specs)
    expectations = expectations or Expectations()
    summary_path = distribution / CONSTRUCTION_SUMMARY
    units: list[DistributionUnit] = []
    summary_digest: str | None = None
    manifest_digest: str | None = None
    pack_pins: dict[str, PackPin] = {}
    load_failures: list[str] = []

    manifest_path = distribution / "atlas-manifest.json"
    if manifest_path.is_file():
        try:
            manifest_bytes = manifest_path.read_bytes()
            manifest_digest = "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()
            manifest_payload = json.loads(manifest_bytes)
        except (OSError, TypeError, ValueError) as error:
            load_failures.append(f"cannot read atlas-manifest.json: {error}")
        else:
            manifest_packs = (
                manifest_payload.get("packs") if isinstance(manifest_payload, dict) else None
            )
            if not isinstance(manifest_packs, list):
                load_failures.append("atlas-manifest.json: packs must be an array")
            else:
                for index, row in enumerate(manifest_packs):
                    try:
                        if not isinstance(row, dict):
                            raise TypeError("pack row must be an object")
                        path = row.get("path")
                        transport = row.get("transport")
                        if not isinstance(path, str) or not path.startswith("packs/"):
                            raise TypeError("path must be a packs/ relative string")
                        if not isinstance(transport, dict):
                            raise TypeError("transport must be an object")
                        digest = transport.get("digest")
                        byte_length = transport.get("byteLength")
                        if not isinstance(digest, str) or re.fullmatch(
                            r"sha256:[0-9a-f]{64}", digest
                        ) is None:
                            raise TypeError("transport.digest must be a SHA-256")
                        if (
                            not isinstance(byte_length, int)
                            or isinstance(byte_length, bool)
                            or byte_length < 0
                        ):
                            raise TypeError("transport.byteLength must be a nonnegative integer")
                        logical_path = path.removeprefix("packs/")
                        if logical_path in pack_pins:
                            raise ValueError(f"duplicate manifest pack path {path!r}")
                        pack_pins[logical_path] = PackPin(
                            path=logical_path,
                            sha256=digest,
                            byte_length=byte_length,
                        )
                    except (TypeError, ValueError) as error:
                        load_failures.append(
                            f"atlas-manifest.json: packs[{index}]: {error}"
                        )
    elif expectations.require_pack_pins:
        load_failures.append("missing atlas-manifest.json for pack transport authentication")

    if summary_path.is_file():
        try:
            summary_bytes = summary_path.read_bytes()
            summary_digest = "sha256:" + hashlib.sha256(summary_bytes).hexdigest()
            payload = json.loads(summary_bytes)
        except (OSError, TypeError, ValueError) as error:
            load_failures.append(f"cannot read {CONSTRUCTION_SUMMARY}: {error}")
        else:
            releases = payload.get("releases") if isinstance(payload, dict) else None
            if not isinstance(releases, list):
                load_failures.append(f"{CONSTRUCTION_SUMMARY}: releases must be an array")
            else:
                seen_keys: set[str] = set()
                for index, row in enumerate(releases):
                    try:
                        if not isinstance(row, dict):
                            raise TypeError("release row must be an object")
                        key = row["key"]
                        kind = row["kind"]
                        inputs = row.get("inputs", ())
                        rdf_packs = row.get("rdfPacks", ())
                        record_counts = row.get("recordCounts", {})
                        if not isinstance(key, str) or not key:
                            raise TypeError("key must be a non-empty string")
                        if key in seen_keys:
                            raise ValueError(f"duplicate construction unit key {key!r}")
                        if not isinstance(kind, str):
                            raise TypeError("kind must be a string")
                        if not isinstance(inputs, list) or not all(isinstance(item, dict) for item in inputs):
                            raise TypeError("inputs must be an array of objects")
                        if not isinstance(rdf_packs, list) or not all(
                            isinstance(item, dict) and isinstance(item.get("path"), str) for item in rdf_packs
                        ):
                            raise TypeError("rdfPacks must be an array of objects with string paths")
                        if not isinstance(record_counts, dict):
                            raise TypeError("recordCounts must be an object")
                        units.append(
                            DistributionUnit(
                                key=key,
                                kind=kind,
                                inputs=tuple(inputs),
                                packs=tuple(pack["path"].removeprefix("packs/") for pack in rdf_packs),
                                record_counts=record_counts,
                            )
                        )
                        seen_keys.add(key)
                    except (KeyError, TypeError, ValueError) as error:
                        load_failures.append(f"{CONSTRUCTION_SUMMARY}: releases[{index}]: {error}")
    else:
        load_failures.append(f"missing {CONSTRUCTION_SUMMARY}")
    units_by_key = {unit.key: unit for unit in units}

    verified_pins: set[SourcePin] = set()
    authenticated_payloads: dict[SourcePin, bytes] = {}
    pin_failures: list[str] = []
    for pin in dict.fromkeys(pin for spec in specs for pin in spec.inputs):
        try:
            authenticated_payloads[pin] = read_verified_file_pin(
                _resolve_source_pin(source_root, pin),
                expected_sha256=pin.sha256,
                expected_byte_length=pin.byte_length,
                logical_path=pin.path,
            )
        except Exception as error:  # noqa: BLE001 - authenticate every other declared input
            pin_failures.append(f"{pin.path}: {type(error).__name__}: {error}")
        else:
            verified_pins.add(pin)

    pairs: list[SourcePair] = []
    native_control_pairs: list[NativeControlPair] = []
    source_extract_pairs: list[SourceExtractPair] = []
    source_list_pairs: list[SourceListPair] = []
    atlas_views: list[tuple[SourceSpec, AtlasView]] = []
    publisher_cache: dict[
        tuple[tuple[SourcePin, ...], tuple[str, ...], tuple[str, ...]],
        PublisherView | str,
    ] = {}
    native_specs = [spec for spec in specs if spec.kind == "native-control"]
    native_control_publishers: dict[SourceSpec, NativeControlPublisherView] = {}
    if native_specs:
        try:
            native_control_publishers, native_control_load_failures = (
                _read_native_control_publishers(native_specs, authenticated_payloads)
            )
        except Exception as error:  # noqa: BLE001 - RDF comparisons must still run
            load_failures.extend(
                f"{spec.name}: native source reader failed: {type(error).__name__}: {error}"
                for spec in native_specs
            )
        else:
            load_failures.extend(native_control_load_failures)
    for spec in specs:
        packs = tuple(
            pack
            for release_key in spec.release_keys
            for pack in units_by_key.get(
                release_key,
                DistributionUnit(release_key, "missing", (), (), {}),
            ).packs
        )
        publisher: PublisherView | None = None
        if spec.kind in RDF_COMPARISON_KINDS:
            additional_annotation_predicates = (
                spec.rdf_source.additional_annotation_predicates
                if spec.rdf_source is not None
                else ()
            )
            additional_relation_predicates = (
                spec.rdf_source.additional_relation_predicates
                if spec.rdf_source is not None
                else ()
            )
            cache_key = (
                spec.inputs,
                additional_annotation_predicates,
                additional_relation_predicates,
                # Two comparisons can share the same pinned bytes and declare
                # different scopes (EuroVoc main and domains do), so the
                # declarations belong in the key: a cached view built under one
                # spec's exclusions is not the other's view.
                spec.declared_claim_exclusions,
            )
            cached = publisher_cache.get(cache_key)
            if cached is None:
                try:
                    cached = _read_publisher_pin_set(
                        spec.inputs,
                        " + ".join(sorted(pin.path for pin in spec.inputs)),
                        authenticated_payloads,
                        additional_annotation_predicates=(
                            additional_annotation_predicates
                        ),
                        additional_relation_predicates=additional_relation_predicates,
                        declared_claim_exclusions=spec.declared_claim_exclusions,
                    )
                except Exception as error:  # noqa: BLE001 - keep reading independent sources
                    cached = f"{type(error).__name__}: {error}"
                publisher_cache[cache_key] = cached
            if isinstance(cached, str):
                load_failures.append(f"{spec.name}: publisher inputs could not be read: {cached}")
            else:
                try:
                    selected_publisher = _select_publisher_view(cached, spec.subset)
                    selected_publisher = _select_publisher_concepts(
                        selected_publisher,
                        spec.included_concept_iris,
                    )
                except Exception as error:  # noqa: BLE001 - continue with every later source
                    load_failures.append(
                        f"{spec.name}: publisher comparison scope could not be selected: "
                        f"{type(error).__name__}: {error}"
                    )
                else:
                    publisher = selected_publisher

        source_claim_subjects = (
            frozenset(
                {
                    *publisher.concepts,
                    *_publisher_source_scheme_subjects(publisher),
                    *publisher.resource_annotation_target_claim_counts,
                    *(subject for subject, _, _ in publisher.relations),
                    *(obj for _, _, obj in publisher.relations),
                }
            )
            if publisher is not None
            else frozenset()
        )
        try:
            atlas = read_atlas_source(
                distribution,
                packs,
                source_claim_subjects,
            )
        except Exception as error:  # noqa: BLE001 - continue with every later source
            load_failures.append(
                f"{spec.name}: Atlas packs could not be read: {type(error).__name__}: {error}"
            )
            continue
        atlas_views.append((spec, atlas))
        if spec.kind == "native-control":
            native_publisher = native_control_publishers.get(spec)
            if native_publisher is not None:
                native_control_pairs.append(
                    NativeControlPair(
                        spec=spec,
                        publisher=native_publisher,
                        atlas=atlas,
                    )
                )
        elif spec.kind == "source-extract":
            if spec.source_extract is None:
                load_failures.append(
                    f"{spec.name}: source-extract comparison declares no extract selector"
                )
            else:
                source_extract_pairs.append(
                    SourceExtractPair(
                        spec=spec,
                        publisher=_read_source_extract(source_root, spec.source_extract),
                        atlas=atlas,
                    )
                )
        elif spec.kind == "source-list":
            source_list_pairs.append(
                SourceListPair(
                    spec=spec,
                    publisher=_read_source_list(spec, authenticated_payloads),
                    atlas=atlas,
                )
            )
        elif publisher is not None:
            pairs.append(SourcePair(spec=spec, publisher=publisher, atlas=atlas))
    return Context(
        distribution=distribution,
        source_root=source_root,
        specs=specs,
        pairs=tuple(pairs),
        native_control_pairs=tuple(native_control_pairs),
        atlas_views=tuple(atlas_views),
        expectations=expectations,
        units=tuple(units),
        construction_summary_digest=summary_digest,
        manifest_digest=manifest_digest,
        pack_pins=dict(sorted(pack_pins.items())),
        verified_pins=frozenset(verified_pins),
        pin_failures=tuple(pin_failures),
        load_failures=tuple(load_failures),
        source_extract_pairs=tuple(source_extract_pairs),
        source_list_pairs=tuple(source_list_pairs),
        scoped_out_specs=scoped_out_specs,
    )


# --------------------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------------------


RDF_COMPARISON_KINDS = frozenset({"vocabulary", "mapping"})
COMPARISON_KINDS = frozenset(
    {*RDF_COMPARISON_KINDS, "native-control", "source-extract", "source-list"}
)


def _not_evaluated(ctx: Context, kind: str | None = None) -> list[str]:
    """Name declared comparisons whose publisher view could not be constructed."""
    declared = [
        spec
        for spec in ctx.specs
        if (spec.kind in RDF_COMPARISON_KINDS if kind is None else spec.kind == kind)
    ]
    if kind == "native-control":
        loaded = {pair.spec for pair in ctx.native_control_pairs}
    elif kind == "source-extract":
        loaded = {pair.spec for pair in ctx.source_extract_pairs}
    elif kind == "source-list":
        loaded = {pair.spec for pair in ctx.source_list_pairs}
    else:
        loaded = {pair.spec for pair in ctx.pairs}
    return sorted(spec.name for spec in declared if spec not in loaded)


def _incomplete_evaluation_failure(ctx: Context, check: str, kind: str | None = None) -> list[str]:
    missing = _not_evaluated(ctx, kind)
    if not missing:
        return []
    return [f"{check} was not evaluated for {len(missing)} declared comparisons: {missing}"]


def check_load_errors(ctx: Context) -> CheckResult:
    """Report every source or pack that could not be loaded without stopping the run."""
    return _result(
        "load-errors",
        f"{len(ctx.load_failures)} source, inventory, or pack loading errors collected",
        ctx.load_failures,
    )


def check_configuration(ctx: Context) -> CheckResult:
    """Reject fail-open audit settings while allowing every data check to continue."""
    failures: list[str] = []
    if ctx.expectations.minimum_label_sample < 1:
        failures.append(
            "minimum_label_sample must be at least 1; the label check used an effective floor of 1"
        )
    if not ctx.expectations.require_complete_coverage:
        failures.append(
            "require_complete_coverage=False cannot produce a source-fidelity verdict"
        )
    if not ctx.expectations.require_input_pins:
        failures.append("require_input_pins=False cannot produce a source-fidelity verdict")
    if not ctx.expectations.require_pack_pins:
        failures.append("require_pack_pins=False cannot produce a source-fidelity verdict")
    # Declaration checks run over every declared comparison, scoped in or out, so
    # --only can never weaken them by hiding half the registry from review.
    declared_specs = ctx.declared_specs()
    names = [spec.name for spec in declared_specs]
    duplicate_names = sorted(name for name, count in Counter(names).items() if count > 1)
    if duplicate_names:
        failures.append(f"comparison names must be unique: {duplicate_names}")
    release_key_owners: dict[str, list[str]] = defaultdict(list)
    for spec in declared_specs:
        for release_key in spec.release_keys:
            release_key_owners[release_key].append(spec.name)
    duplicate_release_keys = {
        key: owners
        for key, owners in sorted(release_key_owners.items())
        if len(owners) > 1
    }
    if duplicate_release_keys:
        failures.append(
            f"construction-unit comparison ownership must be unique: {duplicate_release_keys}"
        )
    for spec in declared_specs:
        selector = spec.native_control
        if spec.kind not in COMPARISON_KINDS:
            failures.append(f"{spec.name}: unsupported comparison kind {spec.kind!r}")
        for pin in spec.inputs:
            if not pin.role:
                failures.append(
                    f"{spec.name}: publisher pin {pin.path!r} has no construction role"
                )
            if not pin.source_iri:
                failures.append(
                    f"{spec.name}: publisher pin {pin.path!r} has no source IRI"
                )
        if not spec.release_keys:
            failures.append(f"{spec.name}: comparison declares no construction-unit key")
        if len(spec.release_keys) != 1:
            failures.append(
                f"{spec.name}: source comparison must own exactly one construction-unit key"
            )
        if spec.kind == "native-control" and selector is None:
            failures.append(f"{spec.name}: native-control comparison has no selector")
        if spec.kind != "native-control" and selector is not None:
            failures.append(
                f"{spec.name}: {spec.kind!r} comparison must not declare a native-control selector"
            )
        if spec.kind == "source-extract" and spec.source_extract is None:
            failures.append(f"{spec.name}: source-extract comparison has no selector")
        if spec.kind != "source-extract" and spec.source_extract is not None:
            failures.append(
                f"{spec.name}: {spec.kind!r} comparison must not declare a source-extract selector"
            )
        if spec.source_extract is not None:
            if spec.source_extract.reader not in _SOURCE_EXTRACT_READERS:
                failures.append(
                    f"{spec.name}: no extract reader is declared for "
                    f"{spec.source_extract.reader!r}"
                )
            if spec.rdf_source is not None:
                failures.append(
                    f"{spec.name}: source-extract comparison must not declare RDF source policy"
                )
            if not any(pin.role == "publisherSource" for pin in spec.inputs):
                failures.append(
                    f"{spec.name}: source-extract comparison declares no publisher artifact pin"
                )
        if spec.kind == "source-list" and spec.source_list is None:
            failures.append(f"{spec.name}: source-list comparison has no selector")
        if spec.kind != "source-list" and spec.source_list is not None:
            failures.append(
                f"{spec.name}: {spec.kind!r} comparison must not declare a source-list selector"
            )
        if spec.source_list is not None:
            if spec.source_list.reader != SOURCE_LIST_READER:
                failures.append(
                    f"{spec.name}: no source-list reader is declared for "
                    f"{spec.source_list.reader!r}"
                )
            if spec.rdf_source is not None:
                failures.append(
                    f"{spec.name}: source-list comparison must not declare RDF source policy"
                )
        if spec.kind in {"source-extract", "source-list"}:
            continue
        if selector is not None:
            expected_release_keys = (selector.construction_key,)
            if spec.release_keys != expected_release_keys:
                failures.append(
                    f"{spec.name}: release keys {spec.release_keys} do not match native-control "
                    f"emission policy {expected_release_keys}"
                )
            if spec.rdf_source is not None:
                failures.append(
                    f"{spec.name}: native-control comparison must not declare RDF source policy"
                )
        elif spec.rdf_source is None:
            failures.append(
                f"{spec.name}: RDF comparison has no independent source-record policy"
            )
        elif (
            spec.rdf_source.evaluated_native_payload_fields
            & spec.rdf_source.atlas_only_native_payload_fields
        ):
            failures.append(
                f"{spec.name}: native payload fields cannot be both source-evaluated "
                "and Atlas-only"
            )
        elif spec.rdf_source.relation_scope not in {
            "all",
            "member-endpoints",
            "member-subject",
        }:
            failures.append(
                f"{spec.name}: unsupported publisher relation scope "
                f"{spec.rdf_source.relation_scope!r}"
            )
        elif spec.rdf_source.label_language_inverse not in {
            "atlas-en-to-source-untagged",
            "english-tagged",
        }:
            failures.append(
                f"{spec.name}: unsupported label language inverse "
                f"{spec.rdf_source.label_language_inverse!r}"
            )
        elif (
            spec.rdf_source.note_predicate_inverse is not None
            and spec.rdf_source.note_predicate_inverse
            not in {
                *SOURCE_NOTE_PREDICATES,
                *spec.rdf_source.additional_annotation_predicates,
            }
        ):
            failures.append(
                f"{spec.name}: note predicate inverse is outside the declared "
                f"annotation predicates: {spec.rdf_source.note_predicate_inverse!r}"
            )
        elif spec.rdf_source.reification_predicates and not (
            spec.rdf_source.reification_base_iri
        ):
            failures.append(
                f"{spec.name}: reification predicates require a source base IRI"
            )
        elif len(
            {
                (predicate, marker)
                for predicate, marker, _ in spec.rdf_source.literal_reification_id_rules
            }
        ) != len(spec.rdf_source.literal_reification_id_rules):
            failures.append(
                f"{spec.name}: literal reification ID rules repeat a predicate and marker"
            )
        elif any(
            predicate not in spec.rdf_source.reification_predicates
            for predicate, _, _ in spec.rdf_source.literal_reification_id_rules
        ):
            failures.append(
                f"{spec.name}: literal reification ID rules must use declared "
                "reification predicates"
            )
        elif (
            spec.rdf_source.reification_weight_predicate is None
        ) != (spec.rdf_source.reification_weight_value is None):
            failures.append(
                f"{spec.name}: reification weight predicate and value must be declared together"
            )
        elif len(dict(spec.rdf_source.relation_predicate_inverse)) != len(
            spec.rdf_source.relation_predicate_inverse
        ):
            failures.append(
                f"{spec.name}: relation predicate inverse repeats an Atlas predicate"
            )
    missing_native = _not_evaluated(ctx, "native-control")
    if missing_native:
        failures.append(
            f"native source reader did not evaluate {len(missing_native)} comparisons: "
            f"{missing_native}"
        )
    return _result(
        "configuration",
        "audit settings checked for fail-open values",
        failures,
    )


def check_distribution_coverage(ctx: Context) -> CheckResult:
    """Fail closed unless every construction unit has an independent comparison."""
    failures: list[str] = []
    # Manifest pack paths are keyed without their "packs/" prefix (build_context
    # strips it), so this exemption has to be keyed the same way or it never
    # matches and the Atlas catalog is reported as an unowned source pack on
    # every distribution. The catalog carries only Atlas descriptors, profiles,
    # rings and titles -- no source-shaped claim -- which is why it is exempt.
    atlas_only_manifest_packs = frozenset({"catalog.nq.zst"})
    unit_keys = {unit.key for unit in ctx.units}
    covered_keys = {
        key for spec in ctx.loaded_specs() for key in spec.release_keys
    }
    # A scoped run evaluates fewer comparisons on purpose. Those units are
    # neither covered nor failed: they are reported as not evaluated, and the
    # arithmetic below never counts them as proven.
    scoped_out_keys = ctx.scoped_out_release_keys() & unit_keys
    source_names = {spec.name for spec in ctx.loaded_specs()}

    if not ctx.units:
        failures.append(f"{CONSTRUCTION_SUMMARY} is missing or contains no construction units")
    missing_required = sorted(set(ctx.expectations.required_sources) - source_names)
    if missing_required:
        failures.append(f"required comparison sources are absent: {missing_required}")
    for spec in ctx.specs:
        expected_kind = {
            "vocabulary": "sourceRelease",
            "mapping": "mapping",
            "native-control": "sourceRelease",
            "source-extract": "sourceRelease",
            "source-list": "sourceRelease",
        }.get(spec.kind)
        if expected_kind is None:
            failures.append(f"{spec.name}: unsupported comparison kind {spec.kind!r}")
        else:
            for key in spec.release_keys:
                unit = next((item for item in ctx.units if item.key == key), None)
                if unit is not None and unit.kind != expected_kind:
                    failures.append(
                        f"{spec.name}: comparison kind {spec.kind!r} requires construction kind "
                        f"{expected_kind!r}, but {key!r} is {unit.kind!r}"
                    )
        unknown_policies = sorted(spec.policies - set(EXECUTABLE_POLICIES))
        if unknown_policies:
            failures.append(f"{spec.name}: unknown executable policies: {unknown_policies}")
    unknown = sorted(covered_keys - unit_keys)
    if unknown:
        failures.append(f"comparison specs name construction units absent from the candidate: {unknown}")
    construction_packs = {
        pack
        for unit in ctx.units
        for pack in unit.packs
    }
    manifest_packs = set(ctx.pack_pins)
    for pack in sorted(construction_packs - manifest_packs):
        failures.append(
            f"construction pack {pack!r} has no authenticated manifest entry"
        )
    for pack in sorted(
        manifest_packs - construction_packs - atlas_only_manifest_packs
    ):
        failures.append(
            f"authenticated manifest pack {pack!r} is not owned by any construction unit; "
            "its source-shaped claims would escape this audit"
        )
    uncovered = sorted(unit_keys - covered_keys - scoped_out_keys)
    if uncovered and ctx.expectations.require_complete_coverage:
        failures.append(
            f"{len(uncovered)} of {len(unit_keys)} construction units have no independent publisher adapter; "
            "each uncovered unit is reported separately below"
        )
        failures.extend(f"{key}: no independent publisher comparison was performed" for key in uncovered)
    scoped_note = (
        f"; {len(scoped_out_keys)} not evaluated (scoped out)" if scoped_out_keys else ""
    )
    return _result(
        "distribution-coverage",
        f"{len(covered_keys & unit_keys)}/{len(unit_keys)} construction units have an "
        f"independent comparison{scoped_note}",
        failures,
    )


def check_publisher_input_pins(ctx: Context) -> CheckResult:
    """Authenticate exact publisher bytes and reconcile them to construction inputs."""
    failures: list[str] = []
    verified = {(pin.sha256, pin.path) for pin in ctx.verified_pins}
    expected_occurrences = 0
    matched_occurrences = 0
    units_by_key = {unit.key: unit for unit in ctx.units}
    for spec in ctx.specs:
        for pin in spec.inputs:
            if pin not in ctx.verified_pins:
                matching_failures = [
                    detail for detail in ctx.pin_failures if detail.startswith(f"{pin.path}:")
                ]
                failures.extend(
                    f"{spec.name}: {detail}"
                    for detail in (
                        matching_failures
                        or [f"{pin.path}: publisher input was not authenticated"]
                    )
                )
        selector = spec.native_control
        unit_keys = spec.release_keys
        if (
            not unit_keys
            and selector is not None
            and selector.construction_key in units_by_key
        ):
            unit_keys = (selector.construction_key,)
        for unit_key in unit_keys:
            unit = units_by_key.get(unit_key)
            if unit is None:
                continue
            observed_rows = list(unit.inputs)
            expected_occurrences += len(spec.inputs)
            if len(observed_rows) != len(spec.inputs):
                failures.append(
                    f"{spec.name}: construction unit {unit_key!r} declares {len(observed_rows)} "
                    f"inputs; the independent comparison expects exactly {len(spec.inputs)}"
                )
            matched_indexes: set[int] = set()
            for pin in spec.inputs:
                if pin not in ctx.verified_pins:
                    continue
                matches = [
                    index
                    for index, row in enumerate(observed_rows)
                    if row.get("path") == (pin.construction_path or pin.path)
                    and row.get("sha256") == pin.sha256
                    and row.get("byteLength") == pin.byte_length
                    and (pin.role is None or row.get("role") == pin.role)
                    and (pin.source_iri is None or row.get("sourceIri") == pin.source_iri)
                ]
                if len(matches) != 1:
                    failures.append(
                        f"{spec.name}: independently pinned input {pin.path!r} "
                        f"(construction path {(pin.construction_path or pin.path)!r}) has "
                        f"{len(matches)} exact construction rows in {unit_key!r}; expected one "
                        "with the same path, digest, length, role, and source IRI"
                    )
                else:
                    matched_occurrences += 1
                matched_indexes.update(matches)
            unmatched_rows = [
                row for index, row in enumerate(observed_rows) if index not in matched_indexes
            ]
            for row in unmatched_rows:
                failures.append(
                    f"{spec.name}: construction input is not one of the independently declared "
                    f"inputs for {unit_key!r}: {dict(row)}"
                )
    if ctx.expectations.require_input_pins and not verified:
        failures.append("no publisher input bytes were authenticated")
    return _result(
        "publisher-input-pins",
        f"{len(verified)} distinct publisher inputs authenticated; "
        f"{matched_occurrences}/{expected_occurrences} construction input rows matched exactly",
        failures,
    )


def check_graph_structure(ctx: Context) -> CheckResult:
    """Reject malformed source evidence and bad pack transport before comparison."""
    failures = [
        f"{spec.name}: {failure}"
        for spec, atlas in ctx.atlas_views
        for failure in atlas.structural_failures
    ]
    for spec, atlas in ctx.atlas_views:
        for pack, (observed_digest, observed_length) in atlas.checked_pack_transports.items():
            expected = ctx.pack_pins.get(pack)
            if expected is None:
                if ctx.expectations.require_pack_pins:
                    failures.append(
                        f"{spec.name}: {pack} has no transport pin in atlas-manifest.json"
                    )
                continue
            if (observed_digest, observed_length) != (
                expected.sha256,
                expected.byte_length,
            ):
                failures.append(
                    f"{spec.name}: {pack} transport differs from atlas-manifest.json -- "
                    f"expected ({expected.byte_length}, {expected.sha256}), observed "
                    f"({observed_length}, {observed_digest})"
                )
    checked = sum(len(atlas.checked_packs) for _, atlas in ctx.atlas_views)
    return _result(
        "graph-structure",
        f"{checked} manifest-discovered packs checked for transport and source-evidence structure",
        failures,
    )


def _canonical_json_digest(value: Any) -> str:
    """Digest JSON independently of the Atlas writer."""
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _payload_relation(
    value: object,
    *,
    snake_case: bool = False,
) -> tuple[str, str, str] | None:
    """Read one relation object without changing any IRI or direction."""
    if not isinstance(value, Mapping):
        return None
    keys = ("subject_iri", "predicate_iri", "object_iri") if snake_case else ("subjectIri", "predicateIri", "objectIri")
    row = tuple(value.get(key) for key in keys)
    if not all(isinstance(item, str) and ":" in item for item in row):
        return None
    return row  # type: ignore[return-value]


def _rdf_provenance_failures(pair: SourcePair) -> list[str]:
    """Reverse source-record evidence and compare it with authenticated bytes."""
    source = pair.spec.name
    policy = pair.spec.rdf_source
    if policy is None:
        return [f"{source}: RDF comparison has no independent provenance policy"]

    failures: list[str] = []

    default_digests = {
        pair.publisher.input_content_digests[path]
        for path in policy.record_digest_input_paths
        if path in pair.publisher.input_content_digests
    }
    missing_digest_paths = sorted(
        set(policy.record_digest_input_paths) - set(pair.publisher.input_content_digests)
    )
    if missing_digest_paths:
        failures.append(
            f"{source}: provenance policy names unavailable publisher inputs: {missing_digest_paths}"
        )

    per_record_resource_fields = frozenset(
        {"publisherConceptIri", "schemeIris", "topConceptOfIris"}
    )
    aggregate_relation_fields = frozenset(
        {"mappingRelations", "semanticRelations", "directSemanticRelations"}
    )
    aggregate_source_evidence_fields = frozenset(
        {"labelRoleNormalization", "metadata"}
    )
    supported_resource_fields = (
        per_record_resource_fields
        | aggregate_relation_fields
        | aggregate_source_evidence_fields
    )
    expected_payload_fields = policy.evaluated_native_payload_fields
    unsupported_declared_fields = sorted(
        expected_payload_fields - supported_resource_fields
    )
    if unsupported_declared_fields:
        failures.append(
            f"{source}: provenance policy declares native payload fields without an "
            f"independent inverse: {unsupported_declared_fields}"
        )
    unexpected_payload_fields: dict[str, list[str]] = defaultdict(list)
    source_memberships: dict[str, set[str]] = defaultdict(set)
    for resource, scheme in pair.publisher.memberships:
        source_memberships[resource].add(scheme)
    source_top_concepts: dict[str, set[str]] = defaultdict(set)
    for resource, scheme in pair.publisher.top_concept_of:
        source_top_concepts[resource].add(scheme)
    for scheme, resource in pair.publisher.has_top_concept:
        source_top_concepts[resource].add(scheme)
    input_path_by_resource = dict(policy.record_input_path_by_resource)
    locator_by_resource = dict(policy.record_locator_by_resource)

    mapping_records: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    record_ids = (
        set(pair.atlas.source_records)
        | set(pair.atlas.record_targets)
        | set(pair.atlas.native_payloads)
    )
    for record in sorted(record_ids):
        target = pair.atlas.record_targets.get(record)
        payload = pair.atlas.native_payloads.get(record)
        if target is None:
            if payload is None:
                failures.append(
                    f"{source}: targetless source record <{record}> has no native payload"
                )
                continue

            publisher_relation = _payload_relation(payload.get("publisherRelation"))
            if publisher_relation is not None:
                relation_payload = payload["publisherRelation"]
                relation_digest = _canonical_json_digest(relation_payload)
                if publisher_relation not in pair.publisher.relations:
                    failures.append(
                        f"{source}: source record <{record}> publisherRelation "
                        f"{publisher_relation!r} is absent from publisher bytes"
                    )
                if payload.get("publisherRelationDigest") != relation_digest:
                    failures.append(
                        f"{source}: source record <{record}> publisherRelationDigest differs "
                        f"from its exact relation payload"
                    )
                if pair.atlas.record_source_digests.get(record) != relation_digest:
                    failures.append(
                        f"{source}: source record <{record}> sourceDigest differs from its "
                        "exact publisherRelation payload"
                    )
                expected_locator = (
                    "urn:ref:publisher-relation:" + relation_digest.removeprefix("sha256:")
                )
                if pair.atlas.record_source_locators.get(record) != expected_locator:
                    failures.append(
                        f"{source}: source record <{record}> relation locator differs -- "
                        f"expected <{expected_locator}>"
                    )
                continue

            mapping_relation = _payload_relation(payload)
            if pair.spec.kind == "mapping" and mapping_relation is not None:
                mapping_records[mapping_relation].append(record)
                if mapping_relation not in pair.publisher.relations:
                    failures.append(
                        f"{source}: source record <{record}> mapping triple "
                        f"{mapping_relation!r} is absent from publisher bytes"
                    )
                mapping_digest = _canonical_json_digest(
                    {
                        "object": mapping_relation[2],
                        "predicate": mapping_relation[1],
                        "subject": mapping_relation[0],
                    }
                )
                if payload.get("mappingTripleDigest") != mapping_digest:
                    failures.append(
                        f"{source}: source record <{record}> mappingTripleDigest differs "
                        "from its exact publisher triple"
                    )
                locator = pair.atlas.record_source_locators.get(record)
                if locator != policy.record_locator:
                    failures.append(
                        f"{source}: source record <{record}> locator differs -- expected "
                        f"<{policy.record_locator}>, observed {locator!r}"
                    )
                observed_digest = pair.atlas.record_source_digests.get(record)
                if len(default_digests) != 1:
                    failures.append(
                        f"{source}: mapping record <{record}> has {len(default_digests)} "
                        "direct publisher digest candidates"
                    )
                elif observed_digest != next(iter(default_digests)):
                    failures.append(
                        f"{source}: mapping record <{record}> digest differs -- expected "
                        f"{next(iter(default_digests))}, observed {observed_digest!r}"
                    )
                independently_checked = {
                    "mappingTripleDigest",
                    "objectIri",
                    "predicateIri",
                    "publisherAlignmentDigest",
                    "subjectIri",
                }
                if (
                    len(default_digests) == 1
                    and payload.get("publisherAlignmentDigest")
                    != next(iter(default_digests))
                ):
                    failures.append(
                        f"{source}: source record <{record}> publisherAlignmentDigest differs "
                        "from the pinned alignment bytes"
                    )
                for field_name in sorted(
                    set(payload)
                    - independently_checked
                    - policy.atlas_only_native_payload_fields
                ):
                    unexpected_payload_fields[field_name].append(record)
                continue

            failures.append(
                f"{source}: source record <{record}> has neither a represented publisher "
                "resource nor an independently reversible publisher relation"
            )
            continue
        if pair.spec.kind == "vocabulary" and target not in pair.publisher.concepts:
            failures.append(
                f"{source}: source record <{record}> represents <{target}>, which is not "
                "a publisher concept in the selected pinned bytes"
            )
        locator = pair.atlas.record_source_locators.get(record)
        expected_locator = locator_by_resource.get(target, policy.record_locator or target)
        if locator != expected_locator:
            failures.append(
                f"{source}: source record <{record}> locator differs -- expected "
                f"<{expected_locator}>, observed {locator!r}"
            )

        resource_input_path = input_path_by_resource.get(target)
        expected_digests = (
            {pair.publisher.input_content_digests[resource_input_path]}
            if resource_input_path in pair.publisher.input_content_digests
            else default_digests
            or set(pair.publisher.resource_input_digests.get(target, frozenset()))
        )
        observed_digest = pair.atlas.record_source_digests.get(record)
        if len(expected_digests) != 1:
            failures.append(
                f"{source}: source record <{record}> has {len(expected_digests)} direct "
                f"publisher digest candidates for <{target}>; exact sourceDigest is not proven"
            )
        elif observed_digest != next(iter(expected_digests)):
            failures.append(
                f"{source}: source record <{record}> digest differs -- expected "
                f"{next(iter(expected_digests))}, observed {observed_digest!r}"
            )

        if payload is None:
            failures.append(f"{source}: source record <{record}> has no native payload")
            continue
        for field_name in sorted(
            set(payload)
            - expected_payload_fields
            - policy.atlas_only_native_payload_fields
        ):
            unexpected_payload_fields[field_name].append(record)
        missing_fields = sorted(
            (expected_payload_fields & per_record_resource_fields) - set(payload)
        )
        if missing_fields:
            failures.append(
                f"{source}: source record <{record}> native payload omits independently "
                f"evaluated fields {missing_fields}"
            )
        if (
            "publisherConceptIri" in expected_payload_fields
            and payload.get("publisherConceptIri") != target
        ):
            failures.append(
                f"{source}: source record <{record}> publisherConceptIri does not equal <{target}>"
            )
        if "schemeIris" in expected_payload_fields:
            expected = sorted(source_memberships.get(target, set()))
            if payload.get("schemeIris") != expected:
                failures.append(
                    f"{source}: source record <{record}> schemeIris differs -- expected "
                    f"{expected!r}, observed {payload.get('schemeIris')!r}"
                )
        if "topConceptOfIris" in expected_payload_fields:
            expected = sorted(source_top_concepts.get(target, set()))
            if payload.get("topConceptOfIris") != expected:
                failures.append(
                    f"{source}: source record <{record}> topConceptOfIris differs -- expected "
                    f"{expected!r}, observed {payload.get('topConceptOfIris')!r}"
                )

    if pair.spec.kind == "mapping":
        publisher_relations = set(pair.publisher.relations)
        observed_relations = set(mapping_records)
        for relation in sorted(publisher_relations - observed_relations):
            failures.append(
                f"{source}: publisher mapping {relation!r} has no source record payload"
            )
        for relation, records in sorted(mapping_records.items()):
            if len(records) != 1:
                failures.append(
                    f"{source}: mapping {relation!r} has {len(records)} source records; expected one"
                )

    for field_name, records in sorted(unexpected_payload_fields.items()):
        examples = ", ".join(f"<{record}>" for record in records[:5])
        suffix = "" if len(records) <= 5 else f"; {len(records) - 5} more records"
        failures.append(
            f"{source}: nativePayload field {field_name!r} is not independently evaluated "
            f"for {len(records)} source records; examples: {examples}{suffix}"
        )
    return failures


def check_rdf_provenance_fidelity(ctx: Context) -> CheckResult:
    """Validate source-record evidence directly without production semantic ETL."""
    failures = _incomplete_evaluation_failure(ctx, "RDF provenance fidelity")
    checked_records = 0
    for pair in ctx.pairs:
        failures.extend(_rdf_provenance_failures(pair))
        checked_records += len(pair.atlas.source_records)
    return _result(
        "rdf-provenance-fidelity",
        f"{checked_records} RDF source records checked against publisher bytes",
        failures,
    )


def _counter_differences(
    source: str,
    label: str,
    expected: Mapping[str, int],
    observed: Mapping[str, int],
) -> list[str]:
    failures: list[str] = []
    for value in sorted(set(expected) | set(observed)):
        expected_count = expected.get(value, 0)
        observed_count = observed.get(value, 0)
        if expected_count != observed_count:
            failures.append(
                f"{source}: {label} count for {value!r} differs -- "
                f"publisher {expected_count}, observed {observed_count}"
            )
    return failures


def _capture_value_counts(
    source: str,
    capture: Mapping[str, Any],
) -> tuple[dict[str, int], list[str]]:
    failures: list[str] = []
    values = capture.get("values")
    if not isinstance(values, list):
        return {}, [f"{source}: normalized control capture values must be an array"]
    result: dict[str, int] = {}
    for index, row in enumerate(values):
        if not isinstance(row, Mapping) or set(row) != {"count", "value"}:
            failures.append(
                f"{source}: normalized control capture values[{index}] must contain exactly count and value"
            )
            continue
        value = row.get("value")
        count = row.get("count")
        if not isinstance(value, str) or not value.strip():
            failures.append(
                f"{source}: normalized control capture values[{index}].value must be nonblank text"
            )
            continue
        if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
            failures.append(
                f"{source}: normalized control capture count for {value!r} must be positive"
            )
            continue
        if value in result:
            failures.append(
                f"{source}: normalized control capture repeats value {value!r}"
            )
            continue
        result[value] = count
    if list(result) != sorted(result):
        failures.append(
            f"{source}: normalized control capture values are not in lexical order"
        )
    return result, failures


def check_native_control_fidelity(ctx: Context) -> CheckResult:
    """Compare Atlas controlled values and counts directly with pinned Parquet rows."""
    failures = _incomplete_evaluation_failure(
        ctx,
        "native-control fidelity",
        "native-control",
    )
    compared_values = 0
    for pair in ctx.native_control_pairs:
        source = pair.spec.name
        selector = pair.spec.native_control
        if selector is None:
            failures.append(f"{source}: native-control selector is missing")
            continue
        failures.extend(f"{source}: {detail}" for detail in pair.publisher.failures)

        capture = pair.publisher.capture
        required_capture_fields = {
            "controlId",
            "extraction",
            "sourceField",
            "sourceFieldMissingRowCount",
            "sourceRowCount",
            "sourceTable",
            "unresolvedValueCount",
            "valueOccurrenceCount",
            "values",
        }
        missing_capture_fields = sorted(required_capture_fields - set(capture))
        if missing_capture_fields:
            failures.append(
                f"{source}: normalized control capture omits source-data fields "
                f"{missing_capture_fields}"
            )
        capture_static = {
            "controlId": selector.control_id,
            "extraction": selector.extraction,
            "sourceField": selector.source_field,
            "sourceTable": selector.source_table,
        }
        for field_name, expected in capture_static.items():
            if capture.get(field_name) != expected:
                failures.append(
                    f"{source}: normalized control capture {field_name} differs -- "
                    f"expected {expected!r}, observed {capture.get(field_name)!r}"
                )

        parquet_pin = next(
            (pin for pin in pair.spec.inputs if pin.fmt == "parquet"),
            None,
        )
        if parquet_pin is None:
            failures.append(f"{source}: comparison declares no direct Parquet pin")
        else:
            expected_capture_source_pin = {
                "byteLength": parquet_pin.byte_length,
                "columns": list(selector.expected_columns),
                "rowCount": selector.expected_row_count,
                "sha256": parquet_pin.sha256,
                "table": selector.source_table,
                "uri": selector.source_iri,
            }
            for field_name, expected in expected_capture_source_pin.items():
                observed = pair.publisher.capture_source_pin.get(field_name)
                if observed != expected:
                    failures.append(
                        f"{source}: normalized control capture source pin {field_name} differs -- "
                        f"expected {expected!r}, observed {observed!r}"
                    )

        raw_summary = {
            "sourceRowCount": pair.publisher.source_row_count,
            "sourceFieldMissingRowCount": pair.publisher.source_field_missing_row_count,
            "valueOccurrenceCount": pair.publisher.value_occurrence_count,
            "unresolvedValueCount": pair.publisher.unresolved_value_count,
        }
        for field_name, expected in raw_summary.items():
            if capture.get(field_name) != expected:
                failures.append(
                    f"{source}: normalized control capture {field_name} differs from direct Parquet scan -- "
                    f"expected {expected}, observed {capture.get(field_name)!r}"
                )
        capture_values, capture_failures = _capture_value_counts(source, capture)
        failures.extend(capture_failures)
        failures.extend(
            _counter_differences(
                source,
                "normalized control capture",
                pair.publisher.values,
                capture_values,
            )
        )

        atlas_values: Counter[str] = Counter()
        target_by_value: dict[str, str] = {}
        record_ids = set(pair.atlas.source_records) | set(pair.atlas.record_targets)
        payload_record_ids = set(pair.atlas.native_payloads)
        for record in sorted(record_ids | payload_record_ids):
            target = pair.atlas.record_targets.get(record)
            payload = pair.atlas.native_payloads.get(record)
            if target is None:
                detail = (
                    "has native payload but no represented resource"
                    if payload is not None
                    else "has no represented resource"
                )
                failures.append(f"{source}: source record <{record}> {detail}")
                continue
            if payload is None:
                failures.append(
                    f"{source}: source record <{record}> represents <{target}> but has no native payload"
                )
                continue
            if set(payload) != {"control", "sourceArtifact", "value"}:
                failures.append(
                    f"{source}: source record <{record}> native payload fields differ -- "
                    "expected exactly control, sourceArtifact, value"
                )
            control = payload.get("control")
            if not isinstance(control, Mapping):
                failures.append(
                    f"{source}: source record <{record}> control must be an object"
                )
            else:
                expected_control_source = {
                    "controlId": selector.control_id,
                    "extraction": selector.extraction,
                    "sourceField": selector.source_field,
                    "sourceFieldMissingRowCount": (
                        pair.publisher.source_field_missing_row_count
                    ),
                    "sourceRowCount": pair.publisher.source_row_count,
                    "sourceTable": selector.source_table,
                    "unresolvedValueCount": pair.publisher.unresolved_value_count,
                    "valueOccurrenceCount": pair.publisher.value_occurrence_count,
                }
                for field_name, expected in expected_control_source.items():
                    if control.get(field_name) != expected:
                        failures.append(
                            f"{source}: source record <{record}> control.{field_name} differs "
                            f"from direct Parquet evidence -- expected {expected!r}, "
                            f"observed {control.get(field_name)!r}"
                        )
            if payload.get("sourceArtifact") != selector.source_iri:
                failures.append(
                    f"{source}: source record <{record}> sourceArtifact differs from the pinned Parquet URI"
                )
            value_row = payload.get("value")
            if not isinstance(value_row, Mapping) or set(value_row) != {"count", "value"}:
                failures.append(
                    f"{source}: source record <{record}> value must contain exactly count and value"
                )
                continue
            value = value_row.get("value")
            count = value_row.get("count")
            if not isinstance(value, str) or not value.strip():
                failures.append(
                    f"{source}: source record <{record}> value must be nonblank text"
                )
                continue
            if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
                failures.append(
                    f"{source}: source record <{record}> count for {value!r} must be positive"
                )
                continue
            if value in target_by_value:
                failures.append(
                    f"{source}: Atlas repeats native value {value!r} across resources "
                    f"<{target_by_value[value]}> and <{target}>"
                )
            target_by_value[value] = target
            atlas_values[value] += count

            locator = pair.atlas.record_source_locators.get(record)
            if locator != selector.source_iri:
                failures.append(
                    f"{source}: source record <{record}> locator differs -- "
                    f"expected <{selector.source_iri}>, observed {locator!r}"
                )
            digest = pair.atlas.record_source_digests.get(record)
            if parquet_pin is None or digest != parquet_pin.sha256:
                failures.append(
                    f"{source}: source record <{record}> digest does not match the pinned Parquet bytes"
                )

            expected_label = frozenset({_literal_value(value, "en", None)})
            if pair.atlas.pref_labels.get(target, frozenset()) != expected_label:
                failures.append(
                    f"{source}: resource <{target}> preferred label is not exactly {value!r}@en"
                )
            expected_notation = frozenset({_literal_value(value, None, None)})
            if pair.atlas.notations.get(target, frozenset()) != expected_notation:
                failures.append(
                    f"{source}: resource <{target}> notation is not exactly {value!r}^^xsd:string"
                )

        represented_targets = set(pair.atlas.record_targets.values())
        unexpected_claim_counts = {
            "alternate labels": sum(
                len(values)
                for target, values in pair.atlas.alt_labels.items()
                if target in represented_targets
            ),
            "hidden labels": sum(
                len(values)
                for target, values in pair.atlas.hidden_labels.items()
                if target in represented_targets
            ),
            "definitions": sum(
                len(values)
                for target, values in pair.atlas.definitions.items()
                if target in represented_targets
            ),
            "notes": sum(
                len(values)
                for target, values in pair.atlas.notes.items()
                if target in represented_targets
            ),
            "source relations": sum(
                1 for subject, _, _ in pair.atlas.relations if subject in represented_targets
            ),
        }
        for claim_family, count in unexpected_claim_counts.items():
            if count:
                failures.append(
                    f"{source}: Atlas adds {count} {claim_family} outside the direct control values"
                )
        failures.extend(
            _counter_differences(
                source,
                "Atlas native value",
                pair.publisher.values,
                atlas_values,
            )
        )
        compared_values += len(pair.publisher.values)
    return _result(
        "native-control-fidelity",
        f"{compared_values} controlled values compared directly with pinned Parquet rows",
        failures,
    )


def _source_extract_atlas_view(pair: SourceExtractPair) -> KeyedAtlasExtractView:
    """Key the Atlas pack by the source-local identity its own records declare."""
    failures: list[str] = []
    atlas = pair.atlas
    resource_by_local: dict[str, str] = {}
    entry_by_local: dict[str, str] = {}
    locator_by_local: dict[str, Any] = {}
    local_by_resource: dict[str, str] = {}
    for record in sorted(atlas.native_payloads):
        payload = atlas.native_payloads[record]
        target = atlas.record_targets.get(record)
        if target is None:
            failures.append(
                f"source record <{record}> has a native payload but represents no resource"
            )
            continue
        local_id = payload.get("sourceLocalConceptId")
        if not isinstance(local_id, str) or not local_id:
            failures.append(
                f"source record <{record}> declares no sourceLocalConceptId, so <{target}> "
                "cannot be traced to a row of the checked source extract"
            )
            continue
        if local_id in resource_by_local:
            failures.append(
                f"source-local concept {local_id!r} is claimed by both "
                f"<{resource_by_local[local_id]}> and <{target}>"
            )
            continue
        resource_by_local[local_id] = target
        local_by_resource[target] = local_id
        entry_id = payload.get("sourceLocalEntryId")
        if isinstance(entry_id, str) and entry_id:
            entry_by_local[local_id] = entry_id
        locator_by_local[local_id] = payload.get("pdfLocator")

    pref = {
        local_by_resource[resource]: values
        for resource, values in atlas.pref_labels.items()
        if resource in local_by_resource
    }
    alt = {
        local_by_resource[resource]: values
        for resource, values in atlas.alt_labels.items()
        if resource in local_by_resource
    }
    relations: set[tuple[str, str, str]] = set()
    for subject, predicate, obj in sorted(atlas.relations):
        keyed_subject = local_by_resource.get(subject)
        keyed_object = local_by_resource.get(obj)
        if keyed_subject is None or keyed_object is None:
            failures.append(
                f"relation <{subject}> {_short(predicate)} <{obj}> has an endpoint that no "
                "source record traces to the checked source extract"
            )
            continue
        relations.add((keyed_subject, predicate, keyed_object))
    return KeyedAtlasExtractView(
        resource_by_local=resource_by_local,
        pref_labels=pref,
        alt_labels=alt,
        entry_ids=entry_by_local,
        locators=locator_by_local,
        relations=frozenset(relations),
        failures=tuple(failures),
    )


def check_source_extract_fidelity(ctx: Context) -> CheckResult:
    """Compare Atlas packs with the checked-in extract of a non-RDF publisher artifact."""
    failures = _incomplete_evaluation_failure(
        ctx,
        "source-extract fidelity",
        "source-extract",
    )
    compared_concepts = 0
    for pair in ctx.source_extract_pairs:
        source = pair.spec.name
        selector = pair.spec.source_extract
        if selector is None:
            failures.append(f"{source}: source-extract selector is missing")
            continue
        failures.extend(f"{source}: {detail}" for detail in pair.publisher.failures)

        publisher_pin = next(
            (pin for pin in pair.spec.inputs if pin.role == "publisherSource"),
            None,
        )
        declared = pair.publisher.declared_publisher_artifact
        if publisher_pin is None:
            failures.append(f"{source}: comparison declares no publisher artifact pin")
        else:
            expected_binding = {
                "id": publisher_pin.source_iri,
                "sha256": publisher_pin.sha256,
                "byteLength": publisher_pin.byte_length,
            }
            for field_name, expected in expected_binding.items():
                if declared.get(field_name) != expected:
                    failures.append(
                        f"{source}: the checked source extract binds a different publisher "
                        f"artifact {field_name} -- expected {expected!r}, observed "
                        f"{declared.get(field_name)!r}"
                    )
            release_digest = next(
                (
                    literal.value
                    for subject, predicate, literal in pair.atlas.all_raw_literal_claims
                    if subject == selector.source_release_iri
                    and predicate == ATLAS_SOURCE_DIGEST
                ),
                None,
            )
            if release_digest != publisher_pin.sha256:
                failures.append(
                    f"{source}: Atlas source release <{selector.source_release_iri}> declares "
                    f"digest {release_digest!r}, not the authenticated publisher bytes "
                    f"{publisher_pin.sha256!r}"
                )

        keyed = _source_extract_atlas_view(pair)
        failures.extend(f"{source}: {detail}" for detail in keyed.failures)

        publisher_concepts = set(pair.publisher.concept_labels)
        atlas_concepts = set(keyed.resource_by_local)
        for local_id in sorted(publisher_concepts - atlas_concepts):
            failures.append(
                f"{source}: source extract concept {local_id!r} "
                f"({pair.publisher.concept_labels[local_id]!r}) is not asserted by Atlas"
            )
        for local_id in sorted(atlas_concepts - publisher_concepts):
            failures.append(
                f"{source}: Atlas asserts <{keyed.resource_by_local[local_id]}> for source-local "
                f"concept {local_id!r}, which the checked source extract does not contain"
            )

        for local_id in sorted(publisher_concepts & atlas_concepts):
            compared_concepts += 1
            expected_pref = frozenset(
                {
                    _literal_value(
                        pair.publisher.concept_labels[local_id],
                        selector.label_language,
                        None,
                    )
                }
            )
            observed_pref = keyed.pref_labels.get(local_id, frozenset())
            if observed_pref != expected_pref:
                failures.append(
                    f"{source}: {local_id} preferred label differs -- expected "
                    f"{sorted(_literal_repr(item) for item in expected_pref)}, observed "
                    f"{sorted(_literal_repr(item) for item in observed_pref)}"
                )
            expected_alt = frozenset(
                _literal_value(value, selector.label_language, None)
                for value in pair.publisher.alternate_labels.get(local_id, frozenset())
            )
            observed_alt = keyed.alt_labels.get(local_id, frozenset())
            if observed_alt != expected_alt:
                failures.append(
                    f"{source}: {local_id} alternate labels differ -- expected "
                    f"{sorted(_literal_repr(item) for item in expected_alt)}, observed "
                    f"{sorted(_literal_repr(item) for item in observed_alt)}"
                )
            expected_entry = pair.publisher.concept_entry_ids.get(local_id)
            if keyed.entry_ids.get(local_id) != expected_entry:
                failures.append(
                    f"{source}: {local_id} source entry identity differs -- expected "
                    f"{expected_entry!r}, observed {keyed.entry_ids.get(local_id)!r}"
                )
            expected_locator = dict(pair.publisher.concept_locators.get(local_id, {}))
            observed_locator = keyed.locators.get(local_id)
            if (
                not isinstance(observed_locator, Mapping)
                or dict(observed_locator) != expected_locator
            ):
                failures.append(
                    f"{source}: {local_id} source locator differs -- expected "
                    f"{expected_locator}, observed {observed_locator!r}"
                )

        missing_relations = pair.publisher.relations - keyed.relations
        added_relations = keyed.relations - pair.publisher.relations
        for subject, predicate, obj in sorted(missing_relations):
            failures.append(
                f"{source}: source extract relation {subject} {_short(predicate)} {obj} "
                "is not asserted by Atlas"
            )
        for subject, predicate, obj in sorted(added_relations):
            failures.append(
                f"{source}: Atlas asserts relation {subject} {_short(predicate)} {obj}, "
                "which the checked source extract does not record as resolved"
            )

        represented = set(keyed.resource_by_local.values())
        unexpected_claim_counts = {
            "hidden labels": sum(
                len(values)
                for resource, values in pair.atlas.hidden_labels.items()
                if resource in represented
            ),
            "definitions": sum(
                len(values)
                for resource, values in pair.atlas.definitions.items()
                if resource in represented
            ),
            "notes": sum(
                len(values)
                for resource, values in pair.atlas.notes.items()
                if resource in represented
            ),
            "notations": sum(
                len(values)
                for resource, values in pair.atlas.notations.items()
                if resource in represented
            ),
        }
        for claim_family, count in unexpected_claim_counts.items():
            if count:
                failures.append(
                    f"{source}: Atlas adds {count} {claim_family} that the checked source "
                    "extract does not record"
                )
    return _result(
        "source-extract-fidelity",
        f"{compared_concepts} extract concepts compared with the Atlas packs that represent them",
        failures,
    )


def _atlas_source_list_rows(pair: SourceListPair) -> tuple[tuple[SourceListRow, ...], tuple[str, ...]]:
    """Read label/notation rows from one dedicated Atlas source pack."""
    failures: list[str] = []
    rows: list[SourceListRow] = []
    selector = pair.spec.source_list
    if selector is None:
        return (), ("source-list selector is missing",)
    for record in sorted(pair.atlas.native_payloads):
        target = pair.atlas.record_targets.get(record)
        if target is None:
            failures.append(
                f"source record <{record}> has native data but represents no resource"
            )
            continue
        label: LiteralValue | None = None
        if selector.compare_labels:
            labels = pair.atlas.pref_labels.get(target, frozenset())
            expected_language_labels = {
                item
                for item in labels
                if item.language == selector.label_language and item.datatype is None
            }
            if len(labels) != 1 or len(expected_language_labels) != 1:
                failures.append(
                    f"resource <{target}> must have exactly one preferred label in "
                    f"{selector.label_language!r}; observed "
                    f"{sorted(_literal_repr(item) for item in labels)}"
                )
                continue
            label = next(iter(expected_language_labels))
            label_value = (
                " ".join(label.value.split())
                if selector.normalize_whitespace
                else label.value
            )
            if selector.casefold_labels:
                label_value = label_value.casefold()
            label = _literal_value(label_value, label.language, label.datatype)
        notations = tuple(
            sorted(literal.value for literal in pair.atlas.notations.get(target, ()))
        )
        payload = pair.atlas.native_payloads[record]
        missing_fields = [
            name for name in selector.native_payload_fields if name not in payload
        ]
        if missing_fields:
            failures.append(
                f"resource <{target}> native data lacks declared fields {missing_fields}"
            )
            continue
        native_attributes: list[tuple[str, str | None]] = []
        invalid_fields: list[str] = []
        for name in sorted(selector.native_payload_fields):
            value = payload[name]
            if value is not None and not isinstance(value, str):
                invalid_fields.append(name)
                continue
            native_attributes.append(
                (
                    name,
                    " ".join(value.split())
                    if isinstance(value, str) and selector.normalize_whitespace
                    else value,
                )
            )
        if invalid_fields:
            failures.append(
                f"resource <{target}> native fields must be strings or null: {invalid_fields}"
            )
            continue
        rows.append(
            SourceListRow(
                label=label,
                notations=notations,
                resource_iri=target if selector.compare_resource_iri else None,
                native_attributes=tuple(native_attributes),
            )
        )
    return tuple(rows), tuple(failures)


def _source_list_row_repr(row: SourceListRow) -> str:
    return (
        f"resourceIri={row.resource_iri!r}, "
        f"label={_literal_repr(row.label) if row.label is not None else None}, "
        f"notations={list(row.notations)!r}, "
        f"nativeAttributes={dict(row.native_attributes)!r}"
    )


def check_source_list_fidelity(ctx: Context) -> CheckResult:
    """Compare complete publisher row multisets with Atlas labels and notations."""
    failures = _incomplete_evaluation_failure(
        ctx,
        "source-list fidelity",
        "source-list",
    )
    compared_rows = 0
    for pair in ctx.source_list_pairs:
        source = pair.spec.name
        failures.extend(f"{source}: {detail}" for detail in pair.publisher.failures)
        atlas_rows, atlas_failures = _atlas_source_list_rows(pair)
        failures.extend(f"{source}: {detail}" for detail in atlas_failures)
        publisher_counts = Counter(pair.publisher.rows)
        atlas_counts = Counter(atlas_rows)
        compared_rows += sum((publisher_counts & atlas_counts).values())
        for row, count in sorted(
            (publisher_counts - atlas_counts).items(),
            key=lambda item: _source_list_row_repr(item[0]),
        ):
            failures.append(
                f"{source}: publisher row missing from Atlas ({count} occurrence(s)): "
                f"{_source_list_row_repr(row)}"
            )
        for row, count in sorted(
            (atlas_counts - publisher_counts).items(),
            key=lambda item: _source_list_row_repr(item[0]),
        ):
            failures.append(
                f"{source}: Atlas row not asserted by the publisher ({count} occurrence(s)): "
                f"{_source_list_row_repr(row)}"
            )
    return _result(
        "source-list-fidelity",
        f"{compared_rows} publisher label/notation rows compared with dedicated Atlas packs",
        failures,
    )


def _scope_requires(ctx: Context, kind: str) -> bool:
    """Whether this run's scope can prove anything about one comparison kind.

    A --only run that names no comparison of this kind has nothing to inspect,
    and a check that reports "I inspected nothing" for a deliberately excluded
    kind would be reporting a scope decision as an infidelity. A run that loaded
    no comparison at all still fails: proving nothing is never a pass.
    """
    return any(spec.kind == kind for spec in ctx.specs) or not ctx.loaded_specs()


def check_concept_traceability(ctx: Context) -> CheckResult:
    """Publisher and Atlas concept identities match exactly in both directions."""
    failures = _incomplete_evaluation_failure(ctx, "concept traceability", "vocabulary")
    traced = 0
    for pair in ctx.vocabularies():
        publisher_ids = pair.publisher.concepts
        atlas_concepts = _atlas_publisher_concepts(pair)
        unknown = sorted(atlas_concepts - publisher_ids)
        missing = sorted(publisher_ids - atlas_concepts)
        traced += len(atlas_concepts) - len(unknown)
        for resource in unknown:
            failures.append(
                f"{pair.spec.name}: Atlas asserts concept <{resource}> which appears in no rdf:type "
                f"record of the pinned publisher bytes ({pair.spec.inputs[0]})"
            )
        for resource in missing:
            failures.append(
                f"{pair.spec.name}: publisher concept <{resource}> is missing from the Atlas release"
            )
    if not ctx.vocabularies() and _scope_requires(ctx, "vocabulary"):
        failures.append("no vocabulary sources were compared; traceability is unproven")
    return _result(
        "concept-traceability",
        f"{traced} asserted concepts traced to a publisher record across {len(ctx.vocabularies())} sources",
        failures,
    )


def check_identifier_retention(ctx: Context) -> CheckResult:
    """The publisher's own identifier is retained rather than minted."""
    failures = _incomplete_evaluation_failure(ctx, "identifier retention", "vocabulary")
    checked = 0
    for pair in ctx.vocabularies():
        atlas_concepts = _atlas_publisher_concepts(pair)
        minted = sorted(resource for resource in atlas_concepts if resource.startswith("urn:ref:"))
        checked += len(atlas_concepts)
        for resource in minted:
            failures.append(
                f"{pair.spec.name}: Atlas concept <{resource}> carries a minted RefSpec identifier "
                f"where the publisher supplies its own IRI"
            )

    return _result(
        "identifier-retention",
        f"{checked} concept identities checked; publisher IRIs retained verbatim",
        failures,
    )


def check_label_fidelity(ctx: Context) -> CheckResult:
    """Exact English label claims match in both directions, including literal metadata."""
    failures = _incomplete_evaluation_failure(ctx, "label fidelity", "vocabulary")
    source_findings: list[Finding] = []
    compared = 0
    for pair in ctx.vocabularies():
        if not pair.spec.has_policy("english-label-selection"):
            failures.append(f"{pair.spec.name}: no executable label-selection policy is declared")
            continue
        if (
            pair.spec.rdf_source is not None
            and pair.spec.rdf_source.label_language_inverse
            == "atlas-en-to-source-untagged"
        ):
            tagged_source_labels = sorted(
                (
                    resource,
                    role,
                    literal,
                )
                for role, values in (
                    ("prefLabel", pair.publisher.pref_labels),
                    ("altLabel", pair.publisher.alt_labels),
                    ("hiddenLabel", pair.publisher.hidden_labels),
                )
                for resource, literals in values.items()
                if resource in pair.publisher.concepts
                for literal in literals
                if literal.language is not None
            )
            if tagged_source_labels:
                examples = [
                    f"<{resource}> {role} {literal.value!r}@{literal.language}"
                    for resource, role, literal in tagged_source_labels[:5]
                ]
                failures.append(
                    f"{pair.spec.name}: atlas-en-to-source-untagged cannot be applied: "
                    f"{len(tagged_source_labels)} publisher labels are language-tagged; "
                    f"examples {examples}"
                )
        repaired: list[tuple[str, str, LiteralValue, LiteralValue]] = []

        for role, source_predicate, atlas_map, publisher_map in (
            (
                "prefLabel",
                SKOS_PREF_LABEL,
                pair.atlas.pref_labels,
                pair.publisher.pref_labels,
            ),
            (
                "altLabel",
                SKOS_ALT_LABEL,
                pair.atlas.alt_labels,
                pair.publisher.alt_labels,
            ),
            (
                "hiddenLabel",
                SKOS_HIDDEN_LABEL,
                pair.atlas.hidden_labels,
                pair.publisher.hidden_labels,
            ),
        ):
            publisher_claims = set(_publisher_label_claims(pair, publisher_map))
            atlas_claims = set(
                _atlas_label_claims(pair, atlas_map, source_predicate)
            )
            compared += len(atlas_claims)

            missing = sorted(publisher_claims - atlas_claims, key=lambda row: (row[0], row[1].value))
            added = sorted(atlas_claims - publisher_claims, key=lambda row: (row[0], row[1].value))
            for resource, literal in added:
                publisher_values = publisher_map.get(resource, frozenset())
                origin = next(
                    (
                        candidate
                        for candidate in publisher_values
                        if candidate.language == literal.language and candidate.value.strip() == literal.value
                    ),
                    None,
                )
                if origin is not None:
                    repaired.append((resource, role, origin, literal))
                    continue
                failures.append(
                    f"{pair.spec.name}: Atlas {role} for <{resource}> adds "
                    f"{literal.value!r}@{literal.language or '-'}^^{literal.datatype or '-'}, absent from publisher bytes"
                )
            for resource, literal in missing:
                if any(row[0] == resource and row[1] == role and row[2] == literal for row in repaired):
                    continue
                failures.append(
                    f"{pair.spec.name}: publisher {role} for <{resource}> "
                    f"{literal.value!r}@{literal.language or '-'}^^{literal.datatype or '-'} is missing from Atlas"
                )

        if repaired:
            for resource, role, origin, asserted in repaired:
                failures.append(
                    f"{pair.spec.name}: Atlas silently repairs surrounding whitespace for <{resource}> {role}: "
                    f"publisher {origin.value!r}, Atlas {asserted.value!r}; the repair is invisible in the distribution"
                )
                source_findings.append(
                    Finding(
                        kind="source",
                        source=pair.spec.name,
                        detail=(
                            f"publisher ships an English {role} for <{resource}> with leading or trailing "
                            f"whitespace (newline or U+00A0 NO-BREAK SPACE): {origin.value!r}"
                        ),
                    )
                )

    minimum_label_sample = max(1, ctx.expectations.minimum_label_sample)
    if compared < minimum_label_sample and _scope_requires(ctx, "vocabulary"):
        failures.append(
            f"only {compared} labels were compared, below the {minimum_label_sample} floor; "
            f"a label check that inspects nothing cannot pass"
        )
    return _result(
        "label-fidelity",
        f"{compared} Atlas labels compared byte-for-byte against publisher literals",
        failures,
        source_findings,
    )


def check_notation_fidelity(ctx: Context) -> CheckResult:
    """Exact SKOS notations survive as Atlas notations, including RDF datatypes."""
    failures = _incomplete_evaluation_failure(ctx, "notation fidelity", "vocabulary")
    compared = 0
    for pair in ctx.vocabularies():
        source_targets = _atlas_source_targets(pair)
        publisher_claims = {
            (resource, literal)
            for resource, values in pair.publisher.notations.items()
            if resource in pair.publisher.concepts
            for literal in values
        }
        atlas_claims = {
            (resource, literal)
            for resource, values in pair.atlas.notations.items()
            if resource in source_targets
            for literal in values
        }
        atlas_claims.update(
            (resource, literal)
            for resource, predicate, literal in pair.atlas.raw_source_literal_claims
            if resource in pair.publisher.concepts and predicate == SKOS_NOTATION
        )
        compared += len(atlas_claims)
        for resource, literal in sorted(
            publisher_claims - atlas_claims,
            key=lambda row: (row[0], row[1].value, row[1].datatype or ""),
        ):
            failures.append(
                f"{pair.spec.name}: publisher notation for <{resource}> "
                f"{literal.value!r}@{literal.language or '-'}^^{literal.datatype or '-'} is missing from Atlas"
            )
        for resource, literal in sorted(
            atlas_claims - publisher_claims,
            key=lambda row: (row[0], row[1].value, row[1].datatype or ""),
        ):
            failures.append(
                f"{pair.spec.name}: Atlas notation for <{resource}> "
                f"{literal.value!r}@{literal.language or '-'}^^{literal.datatype or '-'} is absent from publisher bytes"
            )
    return _result(
        "notation-fidelity",
        f"{compared} Atlas notations compared as exact RDF literals",
        failures,
    )


def check_annotation_fidelity(ctx: Context) -> CheckResult:
    """Definitions and notes retain their exact English RDF literal claims."""
    failures = _incomplete_evaluation_failure(ctx, "annotation fidelity", "vocabulary")
    compared = 0
    for pair in ctx.vocabularies():
        if not pair.spec.has_policy("english-annotation-selection"):
            failures.append(
                f"{pair.spec.name}: no executable annotation-language policy is declared"
            )
            continue
        if not pair.spec.has_policy("skos-note-to-atlas-note"):
            failures.append(
                f"{pair.spec.name}: no executable SKOS-note representation policy is declared"
            )
            continue
        if (
            pair.spec.rdf_source is not None
            and pair.spec.rdf_source.label_language_inverse
            == "atlas-en-to-source-untagged"
        ):
            tagged_source_annotations = sorted(
                (resource, predicate, literal)
                for resource, predicate, literal in pair.publisher.annotations
                if resource in pair.publisher.concepts
                and literal.language is not None
            )
            if tagged_source_annotations:
                examples = [
                    f"<{resource}> <{predicate}> {literal.value!r}@{literal.language}"
                    for resource, predicate, literal in tagged_source_annotations[:5]
                ]
                failures.append(
                    f"{pair.spec.name}: atlas-en-to-source-untagged cannot be applied to "
                    f"{len(tagged_source_annotations)} language-tagged publisher annotations; "
                    f"examples {examples}"
                )

        publisher_definitions = {
            (resource, literal)
            for resource, predicate, literal in pair.publisher.annotations
            if resource in pair.publisher.concepts
            and predicate == SKOS_DEFINITION
        }
        note_predicates = _source_note_predicates(pair)
        publisher_note_origins: dict[tuple[str, LiteralValue], set[str]] = defaultdict(set)
        for resource, predicate, literal in pair.publisher.annotations:
            if (
                resource in pair.publisher.concepts
                and predicate in note_predicates
            ):
                publisher_note_origins[(resource, literal)].add(predicate)
        publisher_notes = set(publisher_note_origins)
        publisher_note_claims = {
            (resource, predicate, literal)
            for (resource, literal), predicates in publisher_note_origins.items()
            for predicate in predicates
        }
        source_targets = _atlas_source_targets(pair)

        atlas_definitions = {
            (resource, _reverse_atlas_english_literal(pair, literal))
            for resource, values in pair.atlas.definitions.items()
            if resource in source_targets
            for literal in values
        }
        atlas_definitions.update(
            (resource, _reverse_atlas_english_literal(pair, literal))
            for resource, predicate, literal in pair.atlas.raw_source_literal_claims
            if resource in pair.publisher.concepts and predicate == SKOS_DEFINITION
        )
        atlas_notes = {
            (resource, _reverse_atlas_english_literal(pair, literal))
            for resource, values in pair.atlas.notes.items()
            if resource in source_targets
            for literal in values
        }
        atlas_notes.update(
            (resource, _reverse_atlas_english_literal(pair, literal))
            for resource, predicate, literal in pair.atlas.raw_source_literal_claims
            if resource in pair.publisher.concepts and predicate in note_predicates
        )
        compared += len(atlas_definitions) + len(atlas_notes)
        recovered_note_claims = {
            row
            for row in (
                pair.atlas.native_literal_claims
                | pair.atlas.raw_source_literal_claims
            )
            if row[0] in source_targets and row[1] in note_predicates
        }
        note_predicate_inverse = (
            pair.spec.rdf_source.note_predicate_inverse
            if pair.spec.rdf_source is not None
            else None
        )
        if note_predicate_inverse is not None:
            recovered_note_claims.update(
                (resource, note_predicate_inverse, literal)
                for resource, literal in atlas_notes
            )
        resource_annotation_predicates = frozenset(
            {SKOS_DEFINITION, *note_predicates}
        )
        publisher_resource_annotations = {
            row
            for row in pair.publisher.resource_annotations
            if row[0] in pair.publisher.concepts
            and row[1] in resource_annotation_predicates
        }
        atlas_resource_annotations = {
            row
            for row in (
                pair.atlas.relations
                | pair.atlas.native_relations
                | pair.atlas.raw_source_iri_claims
            )
            if row[0] in source_targets and row[1] in resource_annotation_predicates
        }
        compared += len(atlas_resource_annotations)
        for resource, predicate, target in sorted(
            publisher_resource_annotations - atlas_resource_annotations
        ):
            target_claim_count = pair.publisher.resource_annotation_target_claim_counts.get(
                target,
                0,
            )
            failures.append(
                f"{pair.spec.name}: publisher resource-valued annotation <{resource}> "
                f"{_short(predicate)} <{target}> is missing from Atlas; the publisher "
                f"annotation target carries {target_claim_count} additional direct claims"
            )
        for resource, predicate, target in sorted(
            atlas_resource_annotations - publisher_resource_annotations
        ):
            failures.append(
                f"{pair.spec.name}: Atlas adds resource-valued annotation <{resource}> "
                f"{_short(predicate)} <{target}>, absent from publisher bytes"
            )

        annotation_targets = frozenset(
            target for _, _, target in publisher_resource_annotations
        )
        publisher_target_iri_claims = frozenset(
            row
            for row in pair.publisher.iri_claims
            if row[0] in annotation_targets
        )
        publisher_target_literal_claims = frozenset(
            row
            for row in pair.publisher.literal_claims
            if row[0] in annotation_targets
        )
        atlas_target_raw_iri_claims = frozenset(
            row
            for row in pair.atlas.raw_source_iri_claims
            if row[0] in annotation_targets
            and not row[1].startswith(ATLAS)
        )
        atlas_target_iri_claims = frozenset(
            {
                *(
                    row
                    for row in atlas_target_raw_iri_claims
                    if not _atlas_only_raw_type_claim(
                        row,
                        publisher_target_iri_claims,
                    )
                ),
                *(
                    row
                    for row in (
                        pair.atlas.native_relations | pair.atlas.relations
                    )
                    if row[0] in annotation_targets
                    and not row[1].startswith(ATLAS)
                ),
            }
        )
        atlas_target_literal_claims = frozenset(
            row
            for row in (
                pair.atlas.raw_source_literal_claims
                | pair.atlas.native_literal_claims
            )
            if row[0] in annotation_targets
            and not row[1].startswith(ATLAS)
        )
        compared += len(atlas_target_iri_claims) + len(
            atlas_target_literal_claims
        )
        for subject, predicate, obj in sorted(
            publisher_target_iri_claims - atlas_target_iri_claims
        ):
            failures.append(
                f"{pair.spec.name}: publisher annotation-target claim <{subject}> "
                f"<{predicate}> <{obj}> is missing from reversible Atlas source evidence"
            )
        for subject, predicate, obj in sorted(
            atlas_target_iri_claims - publisher_target_iri_claims
        ):
            failures.append(
                f"{pair.spec.name}: Atlas source evidence adds annotation-target claim "
                f"<{subject}> <{predicate}> <{obj}>, absent from publisher bytes"
            )

        def target_literal_sort_key(
            row: tuple[str, str, LiteralValue],
        ) -> tuple[str, str, str, str, str]:
            return (
                row[0],
                row[1],
                row[2].value,
                row[2].language or "",
                row[2].datatype or "",
            )

        for subject, predicate, literal in sorted(
            publisher_target_literal_claims - atlas_target_literal_claims,
            key=target_literal_sort_key,
        ):
            failures.append(
                f"{pair.spec.name}: publisher annotation-target literal <{subject}> "
                f"<{predicate}> {literal.value!r}@{literal.language or '-'}"
                f"^^{literal.datatype or '-'} is missing from reversible Atlas source evidence"
            )
        for subject, predicate, literal in sorted(
            atlas_target_literal_claims - publisher_target_literal_claims,
            key=target_literal_sort_key,
        ):
            failures.append(
                f"{pair.spec.name}: Atlas source evidence adds annotation-target literal "
                f"<{subject}> <{predicate}> {literal.value!r}@{literal.language or '-'}"
                f"^^{literal.datatype or '-'}, absent from publisher bytes"
            )
        for (resource, literal), predicates in sorted(
            publisher_note_origins.items(),
            key=lambda row: (row[0][0], row[0][1].value),
        ):
            expected_rows = {
                (resource, predicate, literal) for predicate in predicates
            }
            if len(predicates) > 1 and not expected_rows <= recovered_note_claims:
                failures.append(
                    f"{pair.spec.name}: publisher note for <{resource}> {literal.value!r} is asserted "
                    f"with distinct predicates {sorted(_short(item) for item in predicates)}; "
                    "generic atlas:note would collapse those source claims without the exact "
                    "native predicate evidence"
                )
        for resource, predicate, literal in sorted(
            publisher_note_claims - recovered_note_claims,
            key=lambda row: (row[0], row[1], row[2].value),
        ):
            failures.append(
                f"{pair.spec.name}: publisher note predicate {_short(predicate)} for <{resource}> "
                f"{literal.value!r} is reduced to generic atlas:note and its source predicate "
                "is not retained in native payload evidence"
            )
        for resource, predicate, literal in sorted(
            recovered_note_claims - publisher_note_claims,
            key=lambda row: (row[0], row[1], row[2].value),
        ):
            failures.append(
                f"{pair.spec.name}: native payload adds publisher note predicate "
                f"{_short(predicate)} for <{resource}> {literal.value!r}, absent from source bytes"
            )

        for role, publisher_claims, atlas_claims in (
            ("definition", publisher_definitions, atlas_definitions),
            ("note", publisher_notes, atlas_notes),
        ):
            for resource, literal in sorted(
                publisher_claims - atlas_claims,
                key=lambda row: (row[0], row[1].value, row[1].language or "", row[1].datatype or ""),
            ):
                source_predicates = (
                    [SKOS_DEFINITION]
                    if role == "definition"
                    else sorted(publisher_note_origins[(resource, literal)])
                )
                failures.append(
                    f"{pair.spec.name}: publisher {role} for <{resource}> from "
                    f"{[_short(item) for item in source_predicates]} "
                    f"{literal.value!r}@{literal.language or '-'}^^{literal.datatype or '-'} "
                    "is missing from Atlas"
                )
            for resource, literal in sorted(
                atlas_claims - publisher_claims,
                key=lambda row: (row[0], row[1].value, row[1].language or "", row[1].datatype or ""),
            ):
                failures.append(
                    f"{pair.spec.name}: Atlas {role} for <{resource}> "
                    f"{literal.value!r}@{literal.language or '-'}^^{literal.datatype or '-'} "
                    "is absent from publisher bytes in that role"
                )

    return _result(
        "annotation-fidelity",
        f"{compared} Atlas definitions and notes compared as exact RDF literals in every language",
        failures,
    )


def check_member_iri_fidelity(ctx: Context) -> CheckResult:
    """Compare uninterpreted publisher IRI-object metadata on source members."""
    failures = _incomplete_evaluation_failure(
        ctx,
        "member IRI fidelity",
        "vocabulary",
    )
    compared = 0
    for pair in ctx.vocabularies():
        publisher_claims = _publisher_member_iri_claims(pair)
        atlas_claims = _atlas_member_iri_claims(pair)
        compared += len(atlas_claims)
        for subject, predicate, obj in sorted(publisher_claims - atlas_claims):
            failures.append(
                f"{pair.spec.name}: publisher member IRI claim <{subject}> "
                f"<{predicate}> <{obj}> is absent from reversible Atlas source evidence"
            )
        for subject, predicate, obj in sorted(atlas_claims - publisher_claims):
            failures.append(
                f"{pair.spec.name}: Atlas source evidence adds member IRI claim "
                f"<{subject}> <{predicate}> <{obj}>, absent from publisher bytes"
            )
    return _result(
        "member-iri-fidelity",
        f"{compared} Atlas member IRI claims compared with publisher claims",
        failures,
    )


def check_member_literal_fidelity(ctx: Context) -> CheckResult:
    """Compare source member metadata literals retained in native evidence."""
    failures = _incomplete_evaluation_failure(
        ctx,
        "member literal fidelity",
        "vocabulary",
    )
    compared = 0

    def compare_literals(
        pair: SourcePair,
        claim_family: str,
        publisher_claims: frozenset[tuple[str, str, LiteralValue]],
        atlas_claims: frozenset[tuple[str, str, LiteralValue]],
    ) -> None:
        nonlocal compared
        compared += len(atlas_claims)
        def sort_key(
            row: tuple[str, str, LiteralValue],
        ) -> tuple[str, str, str, str, str]:
            return (
                row[0],
                row[1],
                row[2].value,
                row[2].language or "",
                row[2].datatype or "",
            )
        for resource, predicate, literal in sorted(
            publisher_claims - atlas_claims,
            key=sort_key,
        ):
            failures.append(
                f"{pair.spec.name}: publisher {claim_family} <{resource}> "
                f"{_short(predicate)} {literal.value!r}@{literal.language or '-'}"
                f"^^{literal.datatype or '-'} is absent from reversible Atlas source evidence"
            )
        for resource, predicate, literal in sorted(
            atlas_claims - publisher_claims,
            key=sort_key,
        ):
            failures.append(
                f"{pair.spec.name}: Atlas native evidence adds {claim_family} <{resource}> "
                f"{_short(predicate)} {literal.value!r}@{literal.language or '-'}"
                f"^^{literal.datatype or '-'}, absent from publisher bytes"
            )

    for pair in ctx.vocabularies():
        compare_literals(
            pair,
            "member literal",
            _publisher_member_metadata_literals(pair),
            _atlas_member_metadata_literals(pair),
        )
        compare_literals(
            pair,
            "source-wide literal",
            _publisher_source_wide_literals(pair),
            _atlas_source_wide_literals(pair),
        )
    return _result(
        "member-literal-fidelity",
        f"{compared} Atlas member metadata literals compared with publisher claims",
        failures,
    )


def check_top_concept_fidelity(ctx: Context) -> CheckResult:
    """Reverse Atlas top-concept evidence into the publisher's asserted directions."""
    failures = _incomplete_evaluation_failure(ctx, "top-concept fidelity", "vocabulary")
    compared = 0
    for pair in ctx.vocabularies():
        if not pair.spec.has_policy("top-concept-source-shape-inverse"):
            failures.append(
                f"{pair.spec.name}: no executable top-concept representation policy is declared"
            )
            continue
        publisher_claims = {
            claim
            for claim in pair.publisher.top_concept_of
            if claim[0] in pair.publisher.concepts
        }
        publisher_inverse_claims = {
            (concept, scheme)
            for scheme, concept in pair.publisher.has_top_concept
        }
        atlas_claims = {
            (resource, scheme)
            for resource, schemes in pair.atlas.native_top_concept_of_iris.items()
            if resource in pair.publisher.concepts
            for scheme in schemes
        }
        atlas_claims.update(
            (subject, obj)
            for subject, predicate, obj in pair.atlas.raw_source_iri_claims
            if subject in pair.publisher.concepts
            and predicate == SKOS_TOP_CONCEPT_OF
        )
        atlas_claims.update(
            (concept, scheme)
            for scheme, predicate, concept in pair.atlas.raw_source_iri_claims
            if predicate == SKOS_HAS_TOP_CONCEPT
        )
        compared += len(atlas_claims)
        for resource, scheme in sorted(publisher_claims - atlas_claims):
            failures.append(
                f"{pair.spec.name}: publisher top-concept assignment <{resource}> -> <{scheme}> "
                "is missing from nativePayload.topConceptOfIris"
            )
        for resource, scheme in sorted(publisher_inverse_claims - atlas_claims):
            failures.append(
                f"{pair.spec.name}: publisher inverse top-concept assignment <{scheme}> "
                f"skos:hasTopConcept <{resource}> cannot be reconstructed from "
                "nativePayload.topConceptOfIris"
            )
        publisher_supported_claims = publisher_claims | publisher_inverse_claims
        for resource, scheme in sorted(atlas_claims - publisher_supported_claims):
            failures.append(
                f"{pair.spec.name}: nativePayload.topConceptOfIris adds <{resource}> -> <{scheme}>, "
                "absent from publisher bytes in either top-concept direction"
            )
    return _result(
        "top-concept-fidelity",
        f"{compared} Atlas topConceptOf assignments compared against exact publisher claims",
        failures,
    )


def _atlas_source_relations(pair: SourcePair) -> frozenset[tuple[str, str, str]]:
    """Reverse asserted and source-payload relations into the publisher triple shape."""
    additional = (
        pair.spec.rdf_source.additional_relation_predicates
        if pair.spec.rdf_source is not None
        else ()
    )
    source_predicates = frozenset(
        (*HIERARCHY_PREDICATES, *MAPPING_PREDICATES, *additional)
    )
    predicate_inverse = dict(
        pair.spec.rdf_source.relation_predicate_inverse
        if pair.spec.rdf_source is not None
        else ()
    )
    asserted_source_relations = {
        (subject, predicate_inverse.get(predicate, predicate), obj)
        for subject, predicate, obj in pair.atlas.relations
        if predicate in source_predicates
        or predicate in predicate_inverse
        or (pair.spec.kind == "mapping" and not predicate.startswith(ATLAS))
    }
    asserted_source_relations.update(
        (subject, predicate_inverse.get(predicate, predicate), obj)
        for subject, predicate, obj in pair.atlas.raw_source_iri_claims
        if predicate in source_predicates or predicate in predicate_inverse
    )
    return frozenset(asserted_source_relations) | pair.atlas.native_relations


def _publisher_source_relations(
    pair: SourcePair,
) -> frozenset[tuple[str, str, str]]:
    """Select source relations using only the publisher's declared member set."""
    policy = pair.spec.rdf_source
    scope = policy.relation_scope if policy is not None else "member-subject"
    if scope == "all" or pair.spec.kind == "mapping":
        return pair.publisher.relations
    members = pair.publisher.concepts
    if scope == "member-subject":
        return frozenset(
            relation for relation in pair.publisher.relations if relation[0] in members
        )
    if scope == "member-endpoints":
        return frozenset(
            relation
            for relation in pair.publisher.relations
            if relation[0] in members and relation[2] in members
        )
    raise ValueError(f"unsupported publisher relation scope {scope!r}")


def _source_note_predicates(pair: SourcePair) -> frozenset[str]:
    """Return standard and source-declared note predicates for one comparison."""
    additional = (
        pair.spec.rdf_source.additional_annotation_predicates
        if pair.spec.rdf_source is not None
        else ()
    )
    return frozenset((*SOURCE_NOTE_PREDICATES, *additional))


def _standard_member_literal_predicates(pair: SourcePair) -> frozenset[str]:
    """Literal predicates compared by dedicated label, notation, or note checks."""
    return frozenset(
        {
            SKOS_PREF_LABEL,
            SKOS_ALT_LABEL,
            SKOS_HIDDEN_LABEL,
            SKOSXL_PREF_LABEL,
            SKOSXL_ALT_LABEL,
            SKOSXL_HIDDEN_LABEL,
            SKOSXL_LITERAL_FORM,
            SKOS_NOTATION,
            SKOS_DEFINITION,
            *_source_note_predicates(pair),
        }
    )


def _reverse_atlas_english_literal(
    pair: SourcePair,
    literal: LiteralValue,
) -> LiteralValue:
    """Restore a source's untagged literal when its narrow inverse declares it."""
    inverse = (
        pair.spec.rdf_source.label_language_inverse
        if pair.spec.rdf_source is not None
        else "english-tagged"
    )
    if inverse == "atlas-en-to-source-untagged" and literal.language == "en":
        return _literal_value(literal.value, None, None)
    return literal


def _publisher_label_claims(
    pair: SourcePair,
    values: Mapping[str, frozenset[LiteralValue]],
) -> frozenset[tuple[str, LiteralValue]]:
    """Read every publisher label; language is part of the compared value."""
    return frozenset(
        (resource, literal)
        for resource, literals in values.items()
        if resource in pair.publisher.concepts
        for literal in literals
    )


def _atlas_label_claims(
    pair: SourcePair,
    values: Mapping[str, frozenset[LiteralValue]],
    source_predicate: str,
) -> frozenset[tuple[str, LiteralValue]]:
    """Reverse Atlas label language metadata into the publisher's exact shape."""
    source_targets = _atlas_source_targets(pair)
    claims: set[tuple[str, LiteralValue]] = set()
    for resource, literals in values.items():
        if resource not in source_targets:
            continue
        for literal in literals:
            claims.add((resource, _reverse_atlas_english_literal(pair, literal)))
    claims.update(
        (resource, _reverse_atlas_english_literal(pair, literal))
        for resource, predicate, literal in pair.atlas.raw_source_literal_claims
        if resource in pair.publisher.concepts and predicate == source_predicate
    )
    return frozenset(claims)


def _publisher_member_metadata_literals(
    pair: SourcePair,
) -> frozenset[tuple[str, str, LiteralValue]]:
    """Read non-display literals directly from selected publisher concepts."""
    dedicated = _standard_member_literal_predicates(pair)
    return frozenset(
        row
        for row in pair.publisher.literal_claims
        if row[0] in pair.publisher.concepts
        and row[1] not in dedicated
    )


def _atlas_member_metadata_literals(
    pair: SourcePair,
) -> frozenset[tuple[str, str, LiteralValue]]:
    """Reverse non-display literals retained in Atlas native source evidence."""
    dedicated = _standard_member_literal_predicates(pair)
    return frozenset(
        row
        for row in (
            pair.atlas.native_literal_claims
            | pair.atlas.raw_source_literal_claims
        )
        if row[0] in pair.publisher.concepts
        and row[1] not in dedicated
        and not row[1].startswith(ATLAS)
    )


def _standard_member_iri_predicates(pair: SourcePair) -> frozenset[str]:
    """IRI predicates compared by dedicated source-shape checks."""
    additional_relations = (
        pair.spec.rdf_source.additional_relation_predicates
        if pair.spec.rdf_source is not None
        else ()
    )
    return frozenset(
        {
            SKOS_IN_SCHEME,
            SKOS_TOP_CONCEPT_OF,
            SKOS_HAS_TOP_CONCEPT,
            SKOSXL_PREF_LABEL,
            SKOSXL_ALT_LABEL,
            SKOSXL_HIDDEN_LABEL,
            SKOS_DEFINITION,
            *_source_note_predicates(pair),
            *HIERARCHY_PREDICATES,
            *MAPPING_PREDICATES,
            *additional_relations,
        }
    )


def _publisher_member_iri_claims(
    pair: SourcePair,
) -> frozenset[tuple[str, str, str]]:
    """Read publisher IRI-object metadata without interpreting its values."""
    dedicated = _standard_member_iri_predicates(pair)
    return frozenset(
        row
        for row in pair.publisher.iri_claims
        if row[0] in pair.publisher.concepts and row[1] not in dedicated
    )


def _atlas_member_iri_claims(
    pair: SourcePair,
) -> frozenset[tuple[str, str, str]]:
    """Read exact or native Atlas evidence for publisher IRI-object metadata."""
    publisher_claims = _publisher_member_iri_claims(pair)
    dedicated = _standard_member_iri_predicates(pair)
    raw_claims = {
        row
        for row in pair.atlas.raw_source_iri_claims
        if row[0] in pair.publisher.concepts
        and row[1] not in dedicated
        and not row[1].startswith(ATLAS)
    }
    source_evidence_claims = {
        row
        for row in (pair.atlas.native_relations | pair.atlas.relations)
        if row[0] in pair.publisher.concepts
        and row[1] not in dedicated
        and not row[1].startswith(ATLAS)
    }
    return frozenset(
        {
            *source_evidence_claims,
            *(
                row
                for row in raw_claims
                if not _atlas_only_raw_type_claim(row, publisher_claims)
            ),
        }
    )


def _atlas_only_raw_type_claim(
    row: tuple[str, str, str],
    publisher_claims: Collection[tuple[str, str, str]],
) -> bool:
    """Ignore an added direct class assertion, while requiring every source type."""
    return row[1] == RDF_TYPE and row not in publisher_claims


def _atlas_source_scheme_identities(pair: SourcePair) -> frozenset[str]:
    """Read explicit publisher scheme types without counting governed schemes."""
    exact_type_claims = {
        subject
        for subject, predicate, obj in (
            pair.atlas.raw_source_iri_claims
            | pair.atlas.native_relations
            | pair.atlas.relations
        )
        if predicate == RDF_TYPE and obj == SKOS_CONCEPT_SCHEME
    }
    return frozenset(
        pair.publisher.schemes
        & (exact_type_claims | set(pair.atlas.skos_schemes))
    )


def _publisher_source_scheme_iri_metadata(
    pair: SourcePair,
) -> frozenset[tuple[str, str, str]]:
    """Read source-scheme IRI claims not owned by another dedicated check."""
    subjects = _publisher_source_scheme_subjects(pair.publisher)
    return frozenset(
        row
        for row in pair.publisher.iri_claims
        if row[0] in subjects
        and not (
            row[0] in pair.publisher.schemes
            and row[1] == RDF_TYPE
            and row[2] == SKOS_CONCEPT_SCHEME
        )
        and row[1] != SKOS_HAS_TOP_CONCEPT
        and row[1] not in SKOSXL_LABEL_PREDICATES
    )


def _atlas_source_scheme_iri_metadata(
    pair: SourcePair,
) -> frozenset[tuple[str, str, str]]:
    """Reverse only claims about publisher schemes, never governed schemes."""
    publisher_claims = _publisher_source_scheme_iri_metadata(pair)
    subjects = _publisher_source_scheme_subjects(pair.publisher)
    raw_candidates = {
        row
        for row in pair.atlas.raw_source_iri_claims
        if row[0] in subjects
        and not row[1].startswith(ATLAS)
        and not (
            row[0] in pair.publisher.schemes
            and row[1] == RDF_TYPE
            and row[2] == SKOS_CONCEPT_SCHEME
        )
        and row[1] != SKOS_HAS_TOP_CONCEPT
        and row[1] not in SKOSXL_LABEL_PREDICATES
    }
    source_evidence_candidates = {
        row
        for row in (pair.atlas.native_relations | pair.atlas.relations)
        if row[0] in subjects
        and not row[1].startswith(ATLAS)
        and not (
            row[0] in pair.publisher.schemes
            and row[1] == RDF_TYPE
            and row[2] == SKOS_CONCEPT_SCHEME
        )
        and row[1] != SKOS_HAS_TOP_CONCEPT
        and row[1] not in SKOSXL_LABEL_PREDICATES
    }
    return frozenset(
        {
            *source_evidence_candidates,
            *(
                row
                for row in raw_candidates
                if not _atlas_only_raw_type_claim(row, publisher_claims)
            ),
        }
    )


def _publisher_source_scheme_literal_claims(
    pair: SourcePair,
) -> frozenset[tuple[str, str, LiteralValue]]:
    """Read direct and flattened label claims on publisher-native schemes."""
    subjects = _publisher_source_scheme_subjects(pair.publisher)
    claims = {
        row
        for row in pair.publisher.literal_claims
        if row[0] in subjects
    }
    for predicate, values_by_scheme in (
        (SKOS_PREF_LABEL, pair.publisher.pref_labels),
        (SKOS_ALT_LABEL, pair.publisher.alt_labels),
        (SKOS_HIDDEN_LABEL, pair.publisher.hidden_labels),
    ):
        claims.update(
            (scheme, predicate, literal)
            for scheme, values in values_by_scheme.items()
            if scheme in subjects
            for literal in values
        )
    return frozenset(claims)


def _atlas_source_scheme_literal_claims(
    pair: SourcePair,
) -> frozenset[tuple[str, str, LiteralValue]]:
    """Reverse normalized scheme values into direct publisher-shaped claims."""
    subjects = _publisher_source_scheme_subjects(pair.publisher)
    claims = {
        row
        for row in (
            pair.atlas.raw_source_literal_claims
            | pair.atlas.native_literal_claims
        )
        if row[0] in subjects
        and not row[1].startswith(ATLAS)
    }

    normalized_values = (
        (SKOS_PREF_LABEL, pair.atlas.pref_labels),
        (SKOS_ALT_LABEL, pair.atlas.alt_labels),
        (SKOS_HIDDEN_LABEL, pair.atlas.hidden_labels),
        (SKOS_NOTATION, pair.atlas.notations),
        (SKOS_DEFINITION, pair.atlas.definitions),
    )
    for predicate, values_by_scheme in normalized_values:
        for scheme, values in values_by_scheme.items():
            if scheme not in subjects:
                continue
            claims.update(
                (
                    scheme,
                    predicate,
                    _reverse_atlas_english_literal(pair, literal),
                )
                for literal in values
            )

    inverse_note_predicate = (
        pair.spec.rdf_source.note_predicate_inverse
        if pair.spec.rdf_source is not None
        else None
    )
    if inverse_note_predicate is not None:
        for scheme, values in pair.atlas.notes.items():
            if scheme not in subjects:
                continue
            claims.update(
                (
                    scheme,
                    inverse_note_predicate,
                    _reverse_atlas_english_literal(pair, literal),
                )
                for literal in values
            )
    else:
        native_note_values = {
            (subject, literal)
            for subject, predicate, literal in pair.atlas.native_literal_claims
            if subject in subjects and predicate in _source_note_predicates(pair)
        }
        claims.update(
            (scheme, ATLAS_NOTE, literal)
            for scheme, values in pair.atlas.notes.items()
            if scheme in subjects
            for literal in values
            if (
                scheme,
                _reverse_atlas_english_literal(pair, literal),
            )
            not in native_note_values
        )
    return frozenset(claims)


def _literal_claim_sort_key(
    row: tuple[str, str, LiteralValue],
) -> tuple[str, str, str, str, str]:
    """Sort literal claims without erasing language or datatype differences."""
    return (
        row[0],
        row[1],
        row[2].value,
        row[2].language or "",
        row[2].datatype or "",
    )


def _publisher_source_wide_literals(
    pair: SourcePair,
) -> frozenset[tuple[str, str, LiteralValue]]:
    """Read explicitly declared source-wide literals outside member subjects."""
    predicates = (
        frozenset(pair.spec.rdf_source.source_wide_literal_predicates)
        if pair.spec.rdf_source is not None
        else frozenset()
    )
    return frozenset(
        row for row in pair.publisher.literal_claims if row[1] in predicates
    )


def _atlas_source_wide_literals(
    pair: SourcePair,
) -> frozenset[tuple[str, str, LiteralValue]]:
    """Reverse explicitly declared source-wide literals from native evidence."""
    predicates = (
        frozenset(pair.spec.rdf_source.source_wide_literal_predicates)
        if pair.spec.rdf_source is not None
        else frozenset()
    )
    return frozenset(
        row for row in pair.atlas.native_literal_claims if row[1] in predicates
    )


def _atlas_source_targets(pair: SourcePair) -> frozenset[str]:
    """Resources explicitly linked to publisher evidence by a source record."""
    return frozenset(pair.atlas.record_targets.values())


def _atlas_publisher_concepts(pair: SourcePair) -> frozenset[str]:
    """Resources explicitly asserted in the publisher's SKOS concept shape.

    Atlas-owned resources, rings, profiles, and governed schemes are deliberately
    absent from this view. The binding validator owns those claims.
    """
    return frozenset(
        resource
        for resource, types in pair.atlas.rdf_types.items()
        if SKOS_CONCEPT in types
    )


def check_relation_fidelity(ctx: Context) -> CheckResult:
    """Publisher and Atlas relation sets match exactly in both directions."""
    failures = _incomplete_evaluation_failure(ctx, "relation fidelity")
    verified = 0
    for pair in ctx.pairs:
        publisher = _publisher_source_relations(pair)
        by_pair: dict[tuple[str, str], set[str]] = defaultdict(set)
        for subject, predicate, obj in publisher:
            by_pair[(subject, obj)].add(predicate)

        atlas_relations = _atlas_source_relations(pair)
        for subject, predicate, obj in sorted(atlas_relations):
            if (subject, predicate, obj) in publisher:
                verified += 1
                continue
            reverse = (obj, predicate, subject)
            if reverse in publisher:
                failures.append(
                    f"{pair.spec.name}: Atlas asserts <{subject}> {_short(predicate)} <{obj}> but the "
                    f"publisher states the reverse direction only"
                )
                continue
            alternatives = by_pair.get((subject, obj))
            if alternatives:
                observed = sorted(_short(item) for item in alternatives)
                failures.append(
                    f"{pair.spec.name}: Atlas asserts <{subject}> {_short(predicate)} <{obj}> but the "
                    f"publisher asserts {observed} for that pair"
                )
                continue
            failures.append(
                f"{pair.spec.name}: Atlas asserts <{subject}> {_short(predicate)} <{obj}> which has no "
                f"counterpart in the pinned publisher bytes"
            )
        missing = sorted(publisher - atlas_relations)
        for subject, predicate, obj in missing:
            failures.append(
                f"{pair.spec.name}: publisher asserts <{subject}> {_short(predicate)} <{obj}> but the "
                f"relation is missing from Atlas"
            )
    return _result(
        "relation-fidelity",
        f"{verified} asserted relations matched a publisher triple exactly, direction included",
        failures,
    )


def check_no_manufactured_relations(ctx: Context) -> CheckResult:
    """No relation is manufactured or strengthened relative to publisher claims."""
    failures = _incomplete_evaluation_failure(ctx, "manufactured-relation review")
    checked = 0
    for pair in ctx.pairs:
        publisher_relations = _publisher_source_relations(pair)
        publisher_pairs: dict[tuple[str, str], set[str]] = defaultdict(set)
        for subject, predicate, obj in publisher_relations:
            publisher_pairs[(subject, obj)].add(predicate)
        for subject, predicate, obj in sorted(_atlas_source_relations(pair)):
            checked += 1
            if (subject, predicate, obj) not in publisher_relations:
                failures.append(
                    f"{pair.spec.name}: Atlas manufactures <{subject}> {_short(predicate)} <{obj}>"
                )
            if predicate not in MAPPING_STRENGTH:
                continue
            asserted_strength = MAPPING_STRENGTH[predicate]
            source_predicates = publisher_pairs.get((subject, obj), set())
            source_strengths = [MAPPING_STRENGTH[item] for item in source_predicates if item in MAPPING_STRENGTH]
            if source_strengths and asserted_strength > max(source_strengths):
                strongest = max(source_predicates, key=lambda item: MAPPING_STRENGTH.get(item, -1))
                failures.append(
                    f"{pair.spec.name}: Atlas strengthens <{subject}> -> <{obj}> from publisher "
                    f"{_short(strongest)} to {_short(predicate)}"
                )
    return _result(
        "no-manufactured-relations",
        f"{checked} asserted relations checked for manufacture and predicate strengthening",
        failures,
    )


def _reconstructed_reification(
    pair: SourcePair,
) -> tuple[
    frozenset[ReifiedStatement],
    frozenset[tuple[str, str, LiteralValue]],
    tuple[str, ...],
]:
    """Apply one declared source-specific inverse for relation statement evidence."""
    policy = pair.spec.rdf_source
    if policy is None or policy.reification_base_iri is None:
        return frozenset(), frozenset(), ()
    predicates = frozenset(policy.reification_predicates)
    statements: set[ReifiedStatement] = set()
    weights: set[tuple[str, str, LiteralValue]] = set()
    failures: list[str] = []
    base = policy.reification_base_iri.split("#", 1)[0]
    for subject, predicate, obj in sorted(_atlas_source_relations(pair)):
        if predicate not in predicates:
            continue
        subject_fragment = urllib.parse.urlsplit(subject).fragment
        object_fragment = urllib.parse.urlsplit(obj).fragment
        if not subject_fragment or not object_fragment:
            failures.append(
                f"{pair.spec.name}: cannot reconstruct publisher reification ID for "
                f"<{subject}> {_short(predicate)} <{obj}> because an endpoint has no fragment"
            )
            continue
        local_id = f"r{subject_fragment}-{object_fragment}"
        statements.add(
            ReifiedStatement(
                statement_iri=f"{base}#{local_id}",
                subject_iri=subject,
                predicate_iri=predicate,
                object_iri=obj,
            )
        )
        if (
            policy.reification_weight_predicate is not None
            and policy.reification_weight_value is not None
        ):
            weights.add(
                (
                    urllib.parse.urljoin(base, local_id),
                    policy.reification_weight_predicate,
                    policy.reification_weight_value,
                )
            )
    literal_id_prefixes = {
        (predicate, marker): prefix
        for predicate, marker, prefix in policy.literal_reification_id_rules
    }
    for subject, predicate, literal in sorted(
        pair.atlas.native_literal_claims,
        key=lambda row: (
            row[0],
            row[1],
            row[2].value,
            row[2].language or "",
            row[2].datatype or "",
        ),
    ):
        local_prefix = literal_id_prefixes.get((predicate, literal.value))
        if local_prefix is None:
            continue
        subject_fragment = urllib.parse.urlsplit(subject).fragment
        if not subject_fragment:
            failures.append(
                f"{pair.spec.name}: cannot reconstruct publisher literal reification "
                f"ID for <{subject}> {_short(predicate)} because the subject has no fragment"
            )
            continue
        statements.add(
            ReifiedStatement(
                statement_iri=f"{base}#{local_prefix}{subject_fragment}",
                subject_iri=subject,
                predicate_iri=predicate,
                object_literal=literal,
            )
        )
    return frozenset(statements), frozenset(weights), tuple(failures)


def check_reification_fidelity(ctx: Context) -> CheckResult:
    """Reconstruct declared source reification IDs and detached relation weights."""
    failures = _incomplete_evaluation_failure(ctx, "reification fidelity")
    compared = 0
    for pair in ctx.pairs:
        policy = pair.spec.rdf_source
        if policy is None or not policy.reification_predicates:
            continue
        predicates = frozenset(policy.reification_predicates)
        publisher_statements = frozenset(
            row
            for row in pair.publisher.reified_statements
            if row.predicate_iri in predicates
        )
        atlas_statements, atlas_weights, reconstruction_failures = (
            _reconstructed_reification(pair)
        )
        failures.extend(reconstruction_failures)
        compared += len(atlas_statements)
        missing_statements = publisher_statements - atlas_statements
        added_statements = atlas_statements - publisher_statements
        if missing_statements:
            by_predicate = Counter(row.predicate_iri for row in missing_statements)
            examples = [row.statement_iri for row in sorted(
                missing_statements,
                key=lambda row: row.statement_iri,
            )[:5]]
            failures.append(
                f"{pair.spec.name}: {len(missing_statements)} publisher reified statements "
                f"({4 * len(missing_statements)} RDF reification triples) cannot be "
                f"reconstructed from Atlas; counts by predicate {dict(sorted(by_predicate.items()))}; "
                f"examples {examples}"
            )
        if added_statements:
            examples = [row.statement_iri for row in sorted(
                added_statements,
                key=lambda row: row.statement_iri,
            )[:5]]
            failures.append(
                f"{pair.spec.name}: Atlas reconstructs {len(added_statements)} reified "
                f"statements absent from publisher bytes; examples {examples}"
            )

        if policy.reification_weight_predicate is not None:
            publisher_weights = frozenset(
                row
                for row in pair.publisher.literal_claims
                if row[1] == policy.reification_weight_predicate
            )
            missing_weights = publisher_weights - atlas_weights
            added_weights = atlas_weights - publisher_weights
            if missing_weights:
                failures.append(
                    f"{pair.spec.name}: {len(missing_weights)} publisher detached relation "
                    "weights cannot be reconstructed from Atlas"
                )
            if added_weights:
                failures.append(
                    f"{pair.spec.name}: Atlas reconstructs {len(added_weights)} detached "
                    "relation weights absent from publisher bytes"
                )
    return _result(
        "reification-fidelity",
        f"{compared} relation statement reifications reconstructed from Atlas",
        failures,
    )


def check_count_reconciliation(ctx: Context) -> CheckResult:
    """Summarize exact claim-set comparisons; counts never authorize a mismatch."""
    failures = _incomplete_evaluation_failure(ctx, "count reconciliation")
    reconciled: list[str] = []
    for pair in ctx.pairs:
        source_targets = _atlas_source_targets(pair)
        publisher_pref = _publisher_label_claims(pair, pair.publisher.pref_labels)
        publisher_alt = _publisher_label_claims(pair, pair.publisher.alt_labels)
        publisher_hidden = _publisher_label_claims(
            pair,
            pair.publisher.hidden_labels,
        )
        atlas_pref = _atlas_label_claims(
            pair,
            pair.atlas.pref_labels,
            SKOS_PREF_LABEL,
        )
        atlas_alt = _atlas_label_claims(
            pair,
            pair.atlas.alt_labels,
            SKOS_ALT_LABEL,
        )
        atlas_hidden = _atlas_label_claims(
            pair,
            pair.atlas.hidden_labels,
            SKOS_HIDDEN_LABEL,
        )
        publisher_notations = {
            (resource, literal)
            for resource, values in pair.publisher.notations.items()
            if resource in pair.publisher.concepts
            for literal in values
        }
        atlas_notations = {
            (resource, literal)
            for resource, values in pair.atlas.notations.items()
            if resource in source_targets
            for literal in values
        }
        atlas_notations.update(
            (resource, literal)
            for resource, predicate, literal in pair.atlas.raw_source_literal_claims
            if resource in pair.publisher.concepts and predicate == SKOS_NOTATION
        )
        publisher_definitions = {
            (resource, literal)
            for resource, predicate, literal in pair.publisher.annotations
            if resource in pair.publisher.concepts
            and predicate == SKOS_DEFINITION
        }
        publisher_notes = {
            (resource, literal)
            for resource, predicate, literal in pair.publisher.annotations
            if resource in pair.publisher.concepts
            and predicate in _source_note_predicates(pair)
        }
        atlas_definitions = {
            (resource, _reverse_atlas_english_literal(pair, literal))
            for resource, values in pair.atlas.definitions.items()
            if resource in source_targets
            for literal in values
        }
        atlas_definitions.update(
            (resource, _reverse_atlas_english_literal(pair, literal))
            for resource, predicate, literal in pair.atlas.raw_source_literal_claims
            if resource in pair.publisher.concepts and predicate == SKOS_DEFINITION
        )
        atlas_notes = {
            (resource, _reverse_atlas_english_literal(pair, literal))
            for resource, values in pair.atlas.notes.items()
            if resource in source_targets
            for literal in values
        }
        atlas_notes.update(
            (resource, _reverse_atlas_english_literal(pair, literal))
            for resource, predicate, literal in pair.atlas.raw_source_literal_claims
            if resource in pair.publisher.concepts
            and predicate in _source_note_predicates(pair)
        )
        publisher_top_concepts = {
            claim
            for claim in pair.publisher.top_concept_of
            if claim[0] in pair.publisher.concepts
        }
        publisher_has_top_concepts = {
            (scheme, concept)
            for scheme, concept in pair.publisher.has_top_concept
        }
        atlas_top_concepts = {
            (resource, scheme)
            for resource, schemes in pair.atlas.native_top_concept_of_iris.items()
            if resource in pair.publisher.concepts
            for scheme in schemes
        }
        atlas_top_concepts.update(
            (subject, obj)
            for subject, predicate, obj in pair.atlas.raw_source_iri_claims
            if subject in pair.publisher.concepts
            and predicate == SKOS_TOP_CONCEPT_OF
        )
        atlas_top_concepts.update(
            (concept, scheme)
            for scheme, predicate, concept in pair.atlas.raw_source_iri_claims
            if predicate == SKOS_HAS_TOP_CONCEPT
        )
        categories = {
            "relations": (_publisher_source_relations(pair), _atlas_source_relations(pair))
        }
        if pair.spec.kind == "vocabulary":
            resource_annotation_predicates = frozenset(
                {SKOS_DEFINITION, *_source_note_predicates(pair)}
            )
            publisher_resource_annotations = frozenset(
                row
                for row in pair.publisher.resource_annotations
                if row[0] in pair.publisher.concepts
                and row[1] in resource_annotation_predicates
            )
            atlas_resource_annotations = frozenset(
                row
                for row in (
                    pair.atlas.relations
                    | pair.atlas.native_relations
                    | pair.atlas.raw_source_iri_claims
                )
                if row[0] in source_targets
                and row[1] in resource_annotation_predicates
            )
            categories.update(
                {
                    "concepts": (pair.publisher.concepts, _atlas_publisher_concepts(pair)),
                    "prefLabels": (publisher_pref, atlas_pref),
                    "altLabels": (publisher_alt, atlas_alt),
                    "hiddenLabels": (publisher_hidden, atlas_hidden),
                    "memberMetadataLiterals": (
                        _publisher_member_metadata_literals(pair),
                        _atlas_member_metadata_literals(pair),
                    ),
                    "memberIriMetadata": (
                        _publisher_member_iri_claims(pair),
                        _atlas_member_iri_claims(pair),
                    ),
                    "sourceSchemeIdentities": (
                        pair.publisher.schemes,
                        _atlas_source_scheme_identities(pair),
                    ),
                    "sourceSchemeIriMetadata": (
                        _publisher_source_scheme_iri_metadata(pair),
                        _atlas_source_scheme_iri_metadata(pair),
                    ),
                    "sourceSchemeLiterals": (
                        _publisher_source_scheme_literal_claims(pair),
                        _atlas_source_scheme_literal_claims(pair),
                    ),
                    "notations": (publisher_notations, atlas_notations),
                    "definitions": (publisher_definitions, atlas_definitions),
                    "notes": (publisher_notes, atlas_notes),
                    "resourceAnnotations": (
                        publisher_resource_annotations,
                        atlas_resource_annotations,
                    ),
                    "sourceWideLiterals": (
                        _publisher_source_wide_literals(pair),
                        _atlas_source_wide_literals(pair),
                    ),
                    "hasTopConcepts": (
                        publisher_has_top_concepts,
                        frozenset(
                            (scheme, concept)
                            for concept, scheme in atlas_top_concepts
                            if (scheme, concept) in publisher_has_top_concepts
                        ),
                    ),
                    "topConceptOf": (
                        publisher_top_concepts,
                        frozenset(atlas_top_concepts & publisher_top_concepts),
                    ),
                }
            )
            policy = pair.spec.rdf_source
            if policy is not None and policy.reification_predicates:
                reification_predicates = frozenset(policy.reification_predicates)
                atlas_reifications, atlas_weights, _ = _reconstructed_reification(
                    pair
                )
                categories["reifications"] = (
                    frozenset(
                        row
                        for row in pair.publisher.reified_statements
                        if row.predicate_iri in reification_predicates
                    ),
                    atlas_reifications,
                )
                if policy.reification_weight_predicate is not None:
                    categories["relationWeights"] = (
                        frozenset(
                            row
                            for row in pair.publisher.literal_claims
                            if row[1] == policy.reification_weight_predicate
                        ),
                        atlas_weights,
                    )
        for category, (expected_set, observed_set) in sorted(categories.items()):
            expected = len(expected_set)
            observed = len(observed_set)
            if expected_set == observed_set:
                reconciled.append(f"{pair.spec.name}/{category}")
                continue
            failures.append(
                f"{pair.spec.name}: {category} do not reconcile -- publisher {expected}, Atlas {observed}, "
                f"difference {observed - expected:+d}; counts cannot waive a claim-set difference"
            )
    return _result(
        "count-reconciliation",
        f"{len(reconciled)} source claim categories reconciled exactly",
        failures,
    )


def check_scheme_organisation(ctx: Context) -> CheckResult:
    """Reverse publisher-native scheme data and compare it claim for claim."""
    failures = _incomplete_evaluation_failure(ctx, "scheme organisation", "vocabulary")
    checked = 0
    for pair in ctx.vocabularies():
        checked += 1
        publisher_scheme_iris = pair.publisher.schemes
        atlas_scheme_iris = _atlas_source_scheme_identities(pair)
        for scheme in sorted(publisher_scheme_iris - atlas_scheme_iris):
            failures.append(
                f"{pair.spec.name}: publisher scheme <{scheme}> cannot be reconstructed "
                "from source-native Atlas evidence"
            )

        publisher_scheme_iri_metadata = _publisher_source_scheme_iri_metadata(
            pair
        )
        atlas_scheme_iri_metadata = _atlas_source_scheme_iri_metadata(pair)
        for subject, predicate, obj in sorted(
            publisher_scheme_iri_metadata - atlas_scheme_iri_metadata
        ):
            failures.append(
                f"{pair.spec.name}: publisher scheme claim <{subject}> "
                f"<{predicate}> <{obj}> is missing from reversible Atlas source evidence"
            )
        for subject, predicate, obj in sorted(
            atlas_scheme_iri_metadata - publisher_scheme_iri_metadata
        ):
            failures.append(
                f"{pair.spec.name}: Atlas source evidence adds scheme claim <{subject}> "
                f"<{predicate}> <{obj}>, absent from publisher bytes"
            )

        publisher_scheme_literals = _publisher_source_scheme_literal_claims(pair)
        atlas_scheme_literals = _atlas_source_scheme_literal_claims(pair)
        for subject, predicate, literal in sorted(
            publisher_scheme_literals - atlas_scheme_literals,
            key=_literal_claim_sort_key,
        ):
            failures.append(
                f"{pair.spec.name}: publisher scheme literal <{subject}> "
                f"<{predicate}> {literal.value!r}@{literal.language or '-'}"
                f"^^{literal.datatype or '-'} is missing from reversible Atlas source evidence"
            )
        for subject, predicate, literal in sorted(
            atlas_scheme_literals - publisher_scheme_literals,
            key=_literal_claim_sort_key,
        ):
            failures.append(
                f"{pair.spec.name}: Atlas source evidence adds scheme literal <{subject}> "
                f"<{predicate}> {literal.value!r}@{literal.language or '-'}"
                f"^^{literal.datatype or '-'}, absent from publisher bytes"
            )

        native_memberships = {
            (subject, scheme)
            for subject, schemes in pair.atlas.native_scheme_iris.items()
            if subject in pair.publisher.concepts
            for scheme in schemes
        }
        publisher_memberships = {
            membership
            for membership in pair.publisher.memberships
            if membership[0] in pair.publisher.concepts
        }
        for subject, scheme in sorted(publisher_memberships - native_memberships):
            failures.append(
                f"{pair.spec.name}: publisher membership <{subject}> skos:inScheme <{scheme}> "
                "is absent from nativePayload.schemeIris"
            )
        for subject, scheme in sorted(native_memberships - publisher_memberships):
            failures.append(
                f"{pair.spec.name}: nativePayload.schemeIris adds <{subject}> -> <{scheme}>, "
                "absent from publisher memberships"
            )
    return _result(
        "scheme-organisation",
        f"{checked} vocabularies checked by reversing publisher-native scheme claims",
        failures,
    )


# Field families for release-metadata reporting. Publishers describe a release
# with dozens of near-synonymous predicates (work_title beside title,
# work_date_creation beside date_creation), and one failure line per predicate
# turns a characterised gap into a wall. These buckets are for READING only:
# every count below is over exact claims, and the claim sets are compared whole.
_RELEASE_METADATA_FAMILIES: tuple[tuple[str, str], ...] = (
    # Agent needles come first on purpose: cdm:created_by names who made the
    # release, not when, and "created" would otherwise capture it as a date.
    ("created_by", "agent"),
    ("creator", "agent"),
    ("creates", "agent"),
    ("published_by", "agent"),
    ("publish", "agent"),
    ("agent", "agent"),
    ("title", "title"),
    ("version", "version"),
    ("identifier", "identity"),
    ("datetime", "dates"),
    ("date", "dates"),
    ("issued", "dates"),
    ("created", "dates"),
    ("modified", "dates"),
    ("frequency", "classification"),
    ("type", "classification"),
    ("language", "language"),
    ("licen", "rights"),
    ("rights", "rights"),
    ("access", "rights"),
    ("descri", "description"),
    ("keyword", "description"),
    ("editorial", "description"),
    ("comment", "description"),
    ("label", "description"),
    ("import", "imports"),
    ("member", "structure"),
    ("expression", "structure"),
    ("documentation", "structure"),
    ("related", "structure"),
    ("has", "structure"),
    ("id", "identity"),
)


def _release_metadata_family(predicate: str) -> str:
    """Bucket one release predicate into a readable field family."""
    local = predicate.rsplit("#", 1)[-1].rsplit("/", 1)[-1].lower()
    for needle, family in _RELEASE_METADATA_FAMILIES:
        if needle in local:
            return family
    return "other"


def _atlas_source_release_subjects(pair: SourcePair) -> frozenset[str]:
    """Publisher release IRIs that Atlas reuses as its own source-release node.

    Atlas does not mint a fresh identifier for a publisher release; it adopts
    the publisher's own release IRI and hangs its provenance off it. That makes
    every publisher claim about that IRI a claim Atlas is standing on, so it
    belongs in a comparison rather than in a scope declaration -- an exclusion
    covering it would be exactly the waiver this verifier must not grant.
    """
    return frozenset(
        subject
        for subject, types in pair.atlas.rdf_types.items()
        if ATLAS_SOURCE_RELEASE in types
    )


def _publisher_release_metadata_claims(
    pair: SourcePair,
) -> tuple[
    frozenset[tuple[str, str, str]],
    frozenset[tuple[str, str, LiteralValue]],
]:
    """Every publisher claim about a release IRI Atlas adopted."""
    subjects = _atlas_source_release_subjects(pair)
    return (
        frozenset(row for row in pair.publisher.iri_claims if row[0] in subjects),
        frozenset(row for row in pair.publisher.literal_claims if row[0] in subjects),
    )


def _atlas_release_metadata_claims(
    pair: SourcePair,
) -> tuple[
    frozenset[tuple[str, str, str]],
    frozenset[tuple[str, str, LiteralValue]],
]:
    """Every source-shaped claim Atlas makes about a release IRI it adopted.

    Atlas-minted predicates and Atlas class memberships are excluded: those are
    the representation structure already declared in the receipt, not a
    restatement of anything the publisher said.
    """
    subjects = _atlas_source_release_subjects(pair)
    return (
        frozenset(
            row
            for row in pair.atlas.all_raw_iri_claims
            if row[0] in subjects
            and not _is_atlas_representation_iri(row[1])
            and not (row[1] == RDF_TYPE and _is_atlas_representation_iri(row[2]))
        ),
        frozenset(
            row
            for row in pair.atlas.all_raw_literal_claims
            if row[0] in subjects and not _is_atlas_representation_iri(row[1])
        ),
    )


def check_source_release_metadata(ctx: Context) -> CheckResult:
    """Publisher release descriptions match what Atlas asserts about the same IRI.

    Both directions, exact. Where a publisher describes its release in fifty
    fields and Atlas restates two, this reports the gap as a difference rather
    than leaving it in the uncovered pile -- the truth is that Atlas speaks
    about that subject and drops most of what the publisher said about it.
    """
    failures = _incomplete_evaluation_failure(ctx, "source release metadata")
    compared = 0
    for pair in ctx.pairs:
        subjects = _atlas_source_release_subjects(pair)
        if not subjects:
            continue
        publisher_iri, publisher_literals = _publisher_release_metadata_claims(pair)
        atlas_iri, atlas_literals = _atlas_release_metadata_claims(pair)
        compared += len(atlas_iri) + len(atlas_literals)

        missing: dict[str, list[str]] = defaultdict(list)
        for subject, predicate, obj in sorted(publisher_iri - atlas_iri):
            missing[_release_metadata_family(predicate)].append(
                f"<{subject}> {_short(predicate)} <{obj}>"
            )
        for subject, predicate, literal in sorted(
            publisher_literals - atlas_literals, key=_literal_claim_sort_key
        ):
            missing[_release_metadata_family(predicate)].append(
                f"<{subject}> {_short(predicate)} {_literal_repr(literal)}"
            )
        for family, rows in sorted(missing.items()):
            failures.append(
                f"{pair.spec.name}: {len(rows)} publisher release claim(s) in the "
                f"{family} family are missing from Atlas; examples {rows[:3]}"
            )

        added: dict[str, list[str]] = defaultdict(list)
        for subject, predicate, obj in sorted(atlas_iri - publisher_iri):
            added[_release_metadata_family(predicate)].append(
                f"<{subject}> {_short(predicate)} <{obj}>"
            )
        for subject, predicate, literal in sorted(
            atlas_literals - publisher_literals, key=_literal_claim_sort_key
        ):
            added[_release_metadata_family(predicate)].append(
                f"<{subject}> {_short(predicate)} {_literal_repr(literal)}"
            )
        for family, rows in sorted(added.items()):
            failures.append(
                f"{pair.spec.name}: Atlas adds {len(rows)} release claim(s) in the "
                f"{family} family, absent from publisher bytes; examples {rows[:3]}"
            )
    return _result(
        "source-release-metadata",
        f"{compared} Atlas release claims compared against publisher release descriptions",
        failures,
    )


def _publisher_subject_types(view: PublisherView) -> dict[str, frozenset[str]]:
    """Index the rdf:type values the publisher's own bytes assert per subject."""
    types: dict[str, set[str]] = defaultdict(set)
    for subject, predicate, obj in view.iri_claims:
        if predicate == RDF_TYPE:
            types[subject].add(obj)
    return {subject: frozenset(values) for subject, values in types.items()}


def _compared_publisher_subjects(pair: SourcePair) -> frozenset[str]:
    """Return the publisher subjects this adapter's comparisons actually read.

    A declared exclusion that touches one of these would be hiding a compared
    claim behind a scope declaration, so this is what the overlap guard tests.
    """
    endpoints = {
        *(subject for subject, _, _ in pair.publisher.relations),
        *(obj for _, _, obj in pair.publisher.relations),
    }
    if pair.spec.kind == "mapping":
        return frozenset(endpoints)
    return frozenset(
        {
            *endpoints,
            *pair.publisher.concepts,
            *_publisher_source_scheme_subjects(pair.publisher),
            *pair.publisher.resource_annotation_target_claim_counts,
        }
    )


def _declared_exclusion_subjects(
    pair: SourcePair,
) -> tuple[tuple[DeclaredClaimExclusion, frozenset[str]], ...]:
    """Resolve each declared exclusion to the exact publisher subjects it selects."""
    exclusions = pair.spec.declared_claim_exclusions
    if not exclusions:
        return ()
    types = _publisher_subject_types(pair.publisher)
    subjects = {
        *(subject for subject, _, _ in pair.publisher.iri_claims),
        *(subject for subject, _, _ in pair.publisher.literal_claims),
    }
    # A release IRI Atlas adopted is never selectable by a declaration, however
    # the declaration is worded: those claims belong to source-release-metadata,
    # which reads every one of them in both directions. This is routing, not a
    # waiver -- the claims stay compared, and the routing is reported on the
    # family as ``routedToReleaseComparison`` rather than happening silently.
    adopted_releases = _atlas_source_release_subjects(pair)
    resolved: list[tuple[DeclaredClaimExclusion, frozenset[str]]] = []
    for exclusion in exclusions:
        empty: frozenset[str] = frozenset()
        resolved.append(
            (
                exclusion,
                frozenset(
                    {
                        *(
                            subject
                            for subject in subjects
                            if exclusion.selects(subject, types.get(subject, empty))
                        ),
                        # Roots the reader selected out of the whole publisher
                        # graph, which a subset selector may since have dropped
                        # from this view. Without them the Atlas-side proof
                        # would range over nothing and pass by vacancy.
                        *pair.publisher.declared_out_of_scope_subjects.get(
                            exclusion.name, ()
                        ),
                    }
                )
                - adopted_releases,
            )
        )
    return tuple(resolved)


def _declared_excluded_publisher_claims(
    pair: SourcePair,
) -> tuple[
    frozenset[tuple[str, str, str]],
    frozenset[tuple[str, str, LiteralValue]],
]:
    """Return the publisher claims every declared exclusion accounts for.

    Subjects the comparison actually compares are never excluded, whatever a
    declaration says: the overlap is reported as a failure by ``claim-scope``
    instead of quietly shrinking the residue.
    """
    resolved = _declared_exclusion_subjects(pair)
    if not resolved:
        return frozenset(), frozenset()
    compared = _compared_publisher_subjects(pair)
    selected = frozenset().union(*(subjects for _, subjects in resolved)) - compared
    return (
        frozenset(row for row in pair.publisher.iri_claims if row[0] in selected),
        frozenset(row for row in pair.publisher.literal_claims if row[0] in selected),
    )


def _declared_claim_exclusion_report(pair: SourcePair) -> list[dict[str, Any]]:
    """Report each declared exclusion, what it covers, and whether it still holds."""
    resolved = _declared_exclusion_subjects(pair)
    if not resolved:
        return []
    compared = _compared_publisher_subjects(pair)
    types = _publisher_subject_types(pair.publisher)
    empty: frozenset[str] = frozenset()
    adopted_releases = _atlas_source_release_subjects(pair)
    rows: list[dict[str, Any]] = []
    for exclusion, subjects in resolved:
        # Only the subjects THIS declaration would otherwise have covered.
        routed = sorted(
            subject
            for subject in adopted_releases
            if exclusion.selects(subject, types.get(subject, empty))
        )
        overlap = sorted(subjects & compared)
        selected = subjects - compared
        counts: dict[str, int] = defaultdict(int)
        for subject, predicate, _ in pair.publisher.iri_claims:
            if subject in selected:
                counts[predicate] += 1
        for subject, predicate, _ in pair.publisher.literal_claims:
            if subject in selected:
                counts[predicate] += 1
        atlas_iri = sorted(
            row for row in pair.atlas.all_raw_iri_claims if row[0] in selected
        )
        atlas_literals = sorted(
            (row for row in pair.atlas.all_raw_literal_claims if row[0] in selected),
            key=_literal_claim_sort_key,
        )
        atlas_claims = [
            *(list(row) for row in atlas_iri[:5]),
            *(
                [subject, predicate, _literal_repr(literal)]
                for subject, predicate, literal in atlas_literals[:5]
            ),
        ]
        blank_node_claims = pair.publisher.declared_out_of_scope_blank_node_claims.get(
            exclusion.name, ()
        )
        holds = not atlas_iri and not atlas_literals and not overlap
        rows.append(
            {
                "name": exclusion.name,
                "reason": exclusion.reason,
                "subjectTypes": sorted(exclusion.subject_types),
                "subjectIriPrefixes": list(exclusion.subject_iri_prefixes),
                "subjectCount": len(selected),
                "publisherClaimCount": sum(counts.values()),
                "publisherClaimCountsByPredicate": dict(sorted(counts.items())),
                "publisherBlankNodeClaimCount": len(blank_node_claims),
                "publisherBlankNodeClaimExamples": list(blank_node_claims[:5]),
                "atlasClaimCount": len(atlas_iri) + len(atlas_literals),
                "atlasClaimExamples": atlas_claims,
                "comparedSubjectOverlapCount": len(overlap),
                "comparedSubjectOverlapExamples": overlap[:5],
                "routedToReleaseComparison": routed,
                "status": "declared-out-of-scope" if holds else "violated",
                "meaning": (
                    "publisher claims this release declares Atlas does not "
                    "represent; the declaration holds only while Atlas asserts "
                    "nothing about these subjects and never covers a subject the "
                    "comparison reads"
                ),
            }
        )
    return rows


def _publisher_claims_outside_comparison(
    pair: SourcePair,
) -> tuple[
    frozenset[tuple[str, str, str]],
    frozenset[tuple[str, str, LiteralValue]],
]:
    """Return source triples that no executable inverse currently evaluates."""
    excluded_iri, excluded_literals = _declared_excluded_publisher_claims(pair)
    publisher_iri = set(pair.publisher.iri_claims) - excluded_iri
    publisher_literals = set(pair.publisher.literal_claims) - excluded_literals
    supported_iri: set[tuple[str, str, str]] = set()
    supported_literals: set[tuple[str, str, LiteralValue]] = set()

    # Release IRIs Atlas adopted are compared claim for claim by
    # source-release-metadata, so they leave the uncovered accounting the only
    # way anything ever should: because something now reads them.
    release_iri, release_literals = _publisher_release_metadata_claims(pair)
    supported_iri.update(release_iri)
    supported_literals.update(release_literals)

    if pair.spec.kind == "mapping":
        supported_iri.update(pair.publisher.relations)
    else:
        primary_subjects = {
            *pair.publisher.concepts,
            *_publisher_source_scheme_subjects(pair.publisher),
            *pair.publisher.resource_annotation_target_claim_counts,
        }
        supported_iri.update(
            row for row in publisher_iri if row[0] in primary_subjects
        )
        supported_literals.update(
            row for row in publisher_literals if row[0] in primary_subjects
        )

        label_parent_subjects = {
            *pair.publisher.concepts,
            *_publisher_source_scheme_subjects(pair.publisher),
        }
        label_nodes = {
            obj
            for subject, predicate, obj in publisher_iri
            if subject in label_parent_subjects
            and predicate in SKOSXL_LABEL_PREDICATES
        }
        supported_literals.update(
            row
            for row in publisher_literals
            if row[0] in label_nodes and row[1] == SKOSXL_LITERAL_FORM
        )

        policy = pair.spec.rdf_source
        if policy is not None:
            supported_literals.update(
                row
                for row in publisher_literals
                if row[1] in policy.source_wide_literal_predicates
            )
            reification_predicates = frozenset(policy.reification_predicates)
            for statement in pair.publisher.reified_statements:
                if statement.predicate_iri not in reification_predicates:
                    continue
                supported_iri.update(
                    {
                        (statement.statement_iri, RDF_TYPE, RDF_STATEMENT),
                        (
                            statement.statement_iri,
                            RDF_SUBJECT,
                            statement.subject_iri,
                        ),
                        (
                            statement.statement_iri,
                            RDF_PREDICATE,
                            statement.predicate_iri,
                        ),
                    }
                )
                if statement.object_iri is not None:
                    supported_iri.add(
                        (
                            statement.statement_iri,
                            RDF_OBJECT,
                            statement.object_iri,
                        )
                    )
                elif statement.object_literal is not None:
                    supported_literals.add(
                        (
                            statement.statement_iri,
                            RDF_OBJECT,
                            statement.object_literal,
                        )
                    )
            if policy.reification_weight_predicate is not None:
                supported_literals.update(
                    row
                    for row in publisher_literals
                    if row[1] == policy.reification_weight_predicate
                )

    return (
        frozenset(publisher_iri - supported_iri),
        frozenset(publisher_literals - supported_literals),
    )


def _atlas_claims_outside_comparison(
    pair: SourcePair,
) -> tuple[
    frozenset[tuple[str, str, str]],
    frozenset[tuple[str, str, LiteralValue]],
]:
    """Return unconsumed source-shaped Atlas claims, excluding Atlas-owned data.

    Dedicated checks compare every non-Atlas claim on a known publisher concept,
    source-native scheme, or annotation target. This final accounting catches
    claims on unknown subjects and malformed label-node claims that those checks
    cannot see. Atlas classes, rings, profiles, governed schemes, releases,
    Atlas-minted evidence records (rkaf:EvidenceBinding and its rkaf: claims),
    and the complete label closure of Atlas-owned resources are deliberately
    outside the source-data comparison: none of them is a publisher claim.
    """
    publisher = pair.publisher
    atlas = pair.atlas
    source_schemes = _publisher_source_scheme_subjects(publisher)
    annotation_targets = frozenset(
        publisher.resource_annotation_target_claim_counts
    )
    source_primary = frozenset(
        {
            *publisher.concepts,
            *source_schemes,
            *annotation_targets,
        }
    )
    mapping_endpoints = (
        frozenset(
            {
                *(subject for subject, _, _ in publisher.relations),
                *(obj for _, _, obj in publisher.relations),
            }
        )
        if pair.spec.kind == "mapping"
        else frozenset()
    )

    source_label_nodes = frozenset(
        obj
        for subject, predicate, obj in atlas.label_links
        if subject in source_primary and predicate in SKOSXL_LABEL_PREDICATES
    )
    atlas_classified_subjects = {
        subject
        for subject, types in atlas.rdf_types.items()
        if any(_is_atlas_representation_iri(class_iri) for class_iri in types)
    }
    atlas_owned_primary = frozenset(
        {
            *atlas.source_records,
            *atlas.releases,
            *atlas_classified_subjects,
            *(set(atlas.skos_schemes) - set(source_schemes)),
            *atlas.resource_profiles,
            *atlas.semantic_rings,
            *atlas.atlas_scheme_iris,
        }
        - set(source_primary)
        - set(mapping_endpoints)
    )
    atlas_owned_label_nodes = frozenset(
        {
            obj
            for subject, predicate, obj in atlas.label_links
            if subject in atlas_owned_primary
            and predicate in SKOSXL_LABEL_PREDICATES
        }
        - set(source_label_nodes)
    )

    policy = pair.spec.rdf_source
    relation_predicate_values = {
        *HIERARCHY_PREDICATES,
        *MAPPING_PREDICATES,
    }
    if policy is not None:
        relation_predicate_values.update(policy.additional_relation_predicates)
        relation_predicate_values.update(
            source_predicate
            for source_predicate, _ in policy.relation_predicate_inverse
        )
        relation_predicate_values.update(
            atlas_predicate
            for _, atlas_predicate in policy.relation_predicate_inverse
        )
    relation_predicates = frozenset(relation_predicate_values)
    normalized_source_value_predicates = frozenset(
        {ATLAS_NOTATION, ATLAS_DEFINITION, ATLAS_NOTE}
    )
    normalized_source_value_subjects = frozenset(
        {*publisher.concepts, *source_schemes}
    )
    reification_predicates = frozenset(
        {RDF_TYPE, RDF_SUBJECT, RDF_PREDICATE, RDF_OBJECT}
    )

    residual_iri: set[tuple[str, str, str]] = set()
    for row in atlas.all_raw_iri_claims:
        subject, predicate, _ = row
        if subject in atlas_owned_primary or subject in atlas_owned_label_nodes:
            continue
        if predicate == RDF_TYPE:
            continue
        if (
            subject in atlas.relation_assertions
            and predicate in reification_predicates
        ):
            continue
        if predicate in ATLAS_SOURCE_REPRESENTATION_STRUCTURE_PREDICATES:
            if subject in source_primary or subject in source_label_nodes:
                continue
            residual_iri.add(row)
            continue
        if _is_atlas_representation_iri(predicate):
            if (
                subject in source_primary or subject in mapping_endpoints
            ) and predicate in relation_predicates:
                continue
            residual_iri.add(row)
            continue
        if subject in source_primary:
            continue
        if subject in mapping_endpoints and predicate in relation_predicates:
            continue
        residual_iri.add(row)

    residual_literals: set[tuple[str, str, LiteralValue]] = set()
    for row in atlas.all_raw_literal_claims:
        subject, predicate, _ = row
        if subject in atlas_owned_primary or subject in atlas_owned_label_nodes:
            continue
        if (
            subject in atlas.relation_assertions
            and predicate in reification_predicates
        ):
            continue
        if predicate in ATLAS_SOURCE_REPRESENTATION_STRUCTURE_PREDICATES:
            if subject in source_primary or subject in source_label_nodes:
                continue
            residual_literals.add(row)
            continue
        if _is_atlas_representation_iri(predicate):
            if (
                subject in normalized_source_value_subjects
                and predicate in normalized_source_value_predicates
            ):
                continue
            residual_literals.add(row)
            continue
        if subject in source_label_nodes and predicate == SKOSXL_LITERAL_FORM:
            continue
        if subject in source_primary and predicate != SKOSXL_LITERAL_FORM:
            continue
        residual_literals.add(row)

    return frozenset(residual_iri), frozenset(residual_literals)


def check_source_claim_coverage(ctx: Context) -> CheckResult:
    """Fail when publisher or Atlas source claims escape executable comparison."""
    failures = _incomplete_evaluation_failure(ctx, "source claim coverage")
    uncovered = 0
    declared_out_of_scope = 0
    for pair in ctx.pairs:
        excluded_iri, excluded_literals = _declared_excluded_publisher_claims(pair)
        declared_out_of_scope += (
            len(excluded_iri)
            + len(excluded_literals)
            + sum(
                len(details)
                for details in (
                    pair.publisher.declared_out_of_scope_blank_node_claims.values()
                )
            )
        )
        for detail in pair.publisher.unevaluated_claims:
            failures.append(
                f"{pair.spec.name}: publisher claim could not enter an exact comparison: {detail}"
            )
            uncovered += 1

        residual_iri, residual_literals = _publisher_claims_outside_comparison(pair)
        iri_by_predicate: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
        for row in sorted(residual_iri):
            iri_by_predicate[row[1]].append(row)
        for predicate, rows in sorted(iri_by_predicate.items()):
            failures.append(
                f"{pair.spec.name}: {len(rows)} publisher IRI claim(s) using <{predicate}> "
                f"fall outside every executable comparison; examples {rows[:5]}"
            )
            uncovered += len(rows)

        literal_by_predicate: dict[
            str,
            list[tuple[str, str, LiteralValue]],
        ] = defaultdict(list)
        for row in sorted(residual_literals, key=_literal_claim_sort_key):
            literal_by_predicate[row[1]].append(row)
        for predicate, rows in sorted(literal_by_predicate.items()):
            examples = [
                (
                    subject,
                    literal.value,
                    literal.language,
                    literal.datatype,
                )
                for subject, _, literal in rows[:5]
            ]
            failures.append(
                f"{pair.spec.name}: {len(rows)} publisher literal claim(s) using "
                f"<{predicate}> fall outside every executable comparison; examples {examples}"
            )
            uncovered += len(rows)

        atlas_iri, atlas_literals = _atlas_claims_outside_comparison(pair)
        atlas_iri_by_predicate: dict[
            str,
            list[tuple[str, str, str]],
        ] = defaultdict(list)
        for row in sorted(atlas_iri):
            atlas_iri_by_predicate[row[1]].append(row)
        for predicate, rows in sorted(atlas_iri_by_predicate.items()):
            failures.append(
                f"{pair.spec.name}: {len(rows)} Atlas IRI claim(s) using <{predicate}> "
                "are source-shaped but fall outside every executable comparison; "
                f"examples {rows[:5]}"
            )
            uncovered += len(rows)

        atlas_literals_by_predicate: dict[
            str,
            list[tuple[str, str, LiteralValue]],
        ] = defaultdict(list)
        for row in sorted(atlas_literals, key=_literal_claim_sort_key):
            atlas_literals_by_predicate[row[1]].append(row)
        for predicate, rows in sorted(atlas_literals_by_predicate.items()):
            examples = [
                (
                    subject,
                    literal.value,
                    literal.language,
                    literal.datatype,
                )
                for subject, _, literal in rows[:5]
            ]
            failures.append(
                f"{pair.spec.name}: {len(rows)} Atlas literal claim(s) using "
                f"<{predicate}> are source-shaped but fall outside every executable "
                f"comparison; examples {examples}"
            )
            uncovered += len(rows)
    return _result(
        "source-claim-coverage",
        f"{uncovered} publisher or Atlas source claims remain outside executable "
        f"comparisons; {declared_out_of_scope} more are declared out of scope and "
        "itemised in the receipt",
        failures,
    )


def check_source_defects(ctx: Context) -> CheckResult:
    """Report defects in the publisher's own data; preserving them is correct."""
    findings = sorted(
        {
            finding
            for pair in ctx.pairs
            for finding in pair.publisher.defects
        },
        key=lambda finding: (finding.source, finding.detail),
    )
    return _result(
        "source-defects",
        f"{len(findings)} defects observed in publisher data and reported, not repaired",
        [],
        findings,
    )


def _short(iri: str) -> str:
    """Abbreviate a well-known IRI for readable failure text."""
    for namespace, prefix in (
        (SKOS, "skos"),
        (SKOSXL, "skosxl"),
        (ATLAS, "atlas"),
        (RKAF, "rkaf"),
        (RDF, "rdf"),
    ):
        if iri.startswith(namespace):
            return f"{prefix}:{iri[len(namespace):]}"
    return f"<{iri}>"


def check_claim_scope(ctx: Context) -> CheckResult:
    """Run the receipt-scope evaluator declared later in the module."""
    return _evaluate_claim_scope(ctx)


_CHECKS: tuple[Callable[[Context], CheckResult], ...] = (
    check_load_errors,
    check_configuration,
    check_claim_scope,
    check_distribution_coverage,
    check_publisher_input_pins,
    check_graph_structure,
    check_rdf_provenance_fidelity,
    check_native_control_fidelity,
    check_source_extract_fidelity,
    check_source_list_fidelity,
    check_concept_traceability,
    check_identifier_retention,
    check_label_fidelity,
    check_notation_fidelity,
    check_annotation_fidelity,
    check_member_iri_fidelity,
    check_member_literal_fidelity,
    check_top_concept_fidelity,
    check_relation_fidelity,
    check_no_manufactured_relations,
    check_reification_fidelity,
    check_count_reconciliation,
    check_scheme_organisation,
    check_source_release_metadata,
    check_source_claim_coverage,
    check_source_defects,
)

CHECK_NAMES: tuple[str, ...] = tuple(check.__name__.removeprefix("check_").replace("_", "-") for check in _CHECKS)


def run_checks(ctx: Context, checks: Sequence[Callable[[Context], CheckResult]] = _CHECKS) -> list[CheckResult]:
    """Run every check, converting a broken check into evidence instead of aborting."""
    results: list[CheckResult] = []
    for check in checks:
        try:
            results.append(check(ctx))
        except Exception as error:  # noqa: BLE001 - the remaining checks must still run
            name = check.__name__.removeprefix("check_").replace("_", "-")
            results.append(
                _result(
                    name,
                    "check raised an internal error; remaining checks continued",
                    [f"{type(error).__name__}: {error}"],
                )
            )
    return results


def verify(
    distribution: Path,
    source_root: Path,
    expectations: Expectations | None = None,
    specs: Sequence[SourceSpec] = SOURCES,
    scoped_out_specs: Sequence[SourceSpec] = (),
) -> list[CheckResult]:
    """Run every named check and return the results in declaration order."""
    ctx = build_context(distribution, source_root, expectations, specs, scoped_out_specs)
    return run_checks(ctx)


def select_scope(
    only: Sequence[str],
    specs: Sequence[SourceSpec] = SOURCES,
) -> tuple[tuple[SourceSpec, ...], tuple[SourceSpec, ...]]:
    """Split the declared comparisons into the ones this run evaluates and the rest.

    An empty selection means the whole registry. Every named comparison must
    exist: silently ignoring a typo would produce a receipt that looks like a
    proof of something nobody asked for.
    """
    specs = tuple(specs)
    if not only:
        return specs, ()
    requested = tuple(dict.fromkeys(only))
    known = {spec.name for spec in specs}
    unknown = [name for name in requested if name not in known]
    if unknown:
        raise ValueError(
            f"unknown comparison name(s) {unknown}; declared comparisons are "
            f"{sorted(known)}"
        )
    selected = tuple(spec for spec in specs if spec.name in set(requested))
    scoped_out = tuple(spec for spec in specs if spec.name not in set(requested))
    return selected, scoped_out


COMPARED_VOCABULARY_PREDICATES = frozenset(
    {
        RDF_TYPE,
        SKOS_PREF_LABEL,
        SKOS_ALT_LABEL,
        SKOS_HIDDEN_LABEL,
        SKOSXL_PREF_LABEL,
        SKOSXL_ALT_LABEL,
        SKOSXL_HIDDEN_LABEL,
        SKOS_NOTATION,
        SKOS_DEFINITION,
        *SOURCE_NOTE_PREDICATES,
        *HIERARCHY_PREDICATES,
        *MAPPING_PREDICATES,
        SKOS_IN_SCHEME,
        SKOS_TOP_CONCEPT_OF,
        SKOS_HAS_TOP_CONCEPT,
    }
)


def _claim_status(source_claims: set[Any], atlas_claims: set[Any]) -> str:
    if not source_claims and not atlas_claims:
        return "not-applicable"
    if source_claims == atlas_claims:
        return "exact"
    if source_claims and not atlas_claims:
        return "unrepresented"
    return "differences-found"


def _claim_family(
    *,
    name: str,
    source_predicates: Sequence[str],
    atlas_predicates: Sequence[str],
    source_claims: set[Any],
    atlas_claims: set[Any],
    checked_by: str,
    status: str | None = None,
    **details: Any,
) -> dict[str, Any]:
    return {
        "name": name,
        "sourcePredicates": list(source_predicates),
        "atlasPredicates": list(atlas_predicates),
        "sourceClaimCount": len(source_claims),
        "atlasClaimCount": len(atlas_claims),
        "status": status or _claim_status(source_claims, atlas_claims),
        "checkedBy": checked_by,
        **details,
    }


def _comparison_claim_scope(spec: SourceSpec, pair: SourcePair | None) -> dict[str, Any]:
    """Describe exactly which publisher claim families one adapter evaluated."""
    if pair is None:
        return {
            "status": "not-evaluated",
            "claimFamilies": [],
            "intentionallyExcludedFamilies": [],
            "unexpectedPublisherPredicates": [],
        }

    publisher = pair.publisher
    atlas = pair.atlas
    source_targets = _atlas_source_targets(pair)
    families: list[dict[str, Any]] = []
    if spec.kind == "mapping":
        families.append(
            _claim_family(
                name="mappingRelations",
                source_predicates=MAPPING_PREDICATES,
                atlas_predicates=(RDF_SUBJECT, RDF_PREDICATE, RDF_OBJECT),
                source_claims=set(_publisher_source_relations(pair)),
                atlas_claims=set(_atlas_source_relations(pair)),
                checked_by="relation-fidelity",
                sourcePredicateIdentityRetained=True,
                sourceDirectionRetained=True,
            )
        )
        compared_predicates = frozenset(MAPPING_PREDICATES)
    else:
        publisher_pref = set(_publisher_label_claims(pair, publisher.pref_labels))
        publisher_alt = set(_publisher_label_claims(pair, publisher.alt_labels))
        publisher_hidden = set(
            _publisher_label_claims(pair, publisher.hidden_labels)
        )
        atlas_pref = set(
            _atlas_label_claims(pair, atlas.pref_labels, SKOS_PREF_LABEL)
        )
        atlas_alt = set(
            _atlas_label_claims(pair, atlas.alt_labels, SKOS_ALT_LABEL)
        )
        atlas_hidden = set(
            _atlas_label_claims(pair, atlas.hidden_labels, SKOS_HIDDEN_LABEL)
        )
        for name, source_predicate, atlas_predicate, source_claims, atlas_claims in (
            (
                "preferredLabels",
                (SKOS_PREF_LABEL, SKOSXL_PREF_LABEL, SKOSXL_LITERAL_FORM),
                SKOSXL_PREF_LABEL,
                publisher_pref,
                atlas_pref,
            ),
            (
                "alternateLabels",
                (SKOS_ALT_LABEL, SKOSXL_ALT_LABEL, SKOSXL_LITERAL_FORM),
                SKOSXL_ALT_LABEL,
                publisher_alt,
                atlas_alt,
            ),
            (
                "hiddenLabels",
                (SKOS_HIDDEN_LABEL, SKOSXL_HIDDEN_LABEL, SKOSXL_LITERAL_FORM),
                SKOSXL_HIDDEN_LABEL,
                publisher_hidden,
                atlas_hidden,
            ),
        ):
            families.append(
                _claim_family(
                    name=name,
                    source_predicates=source_predicate,
                    atlas_predicates=(atlas_predicate, SKOSXL_LITERAL_FORM),
                    source_claims=source_claims,
                    atlas_claims=atlas_claims,
                    checked_by="label-fidelity",
                    languageSelection="all",
                    lexicalFormRetained=True,
                    languageAndDatatypeCompared=True,
                )
            )

        publisher_notations = {
            (resource, literal)
            for resource, values in publisher.notations.items()
            if resource in publisher.concepts
            for literal in values
        }
        atlas_notations = {
            (resource, literal)
            for resource, values in atlas.notations.items()
            if resource in source_targets
            for literal in values
        }
        atlas_notations.update(
            (resource, literal)
            for resource, predicate, literal in atlas.raw_source_literal_claims
            if resource in publisher.concepts and predicate == SKOS_NOTATION
        )
        families.append(
            _claim_family(
                name="notations",
                source_predicates=(SKOS_NOTATION,),
                atlas_predicates=(ATLAS_NOTATION,),
                source_claims=publisher_notations,
                atlas_claims=atlas_notations,
                checked_by="notation-fidelity",
                lexicalFormRetained=True,
                languageAndDatatypeCompared=True,
            )
        )

        publisher_definitions = {
            (resource, literal)
            for resource, predicate, literal in publisher.annotations
            if resource in publisher.concepts
            and predicate == SKOS_DEFINITION
        }
        atlas_definitions = {
            (resource, _reverse_atlas_english_literal(pair, literal))
            for resource, values in atlas.definitions.items()
            if resource in source_targets
            for literal in values
        }
        atlas_definitions.update(
            (resource, _reverse_atlas_english_literal(pair, literal))
            for resource, predicate, literal in atlas.raw_source_literal_claims
            if resource in publisher.concepts and predicate == SKOS_DEFINITION
        )
        families.append(
            _claim_family(
                name="definitions",
                source_predicates=(SKOS_DEFINITION,),
                atlas_predicates=(ATLAS_DEFINITION,),
                source_claims=publisher_definitions,
                atlas_claims=atlas_definitions,
                checked_by="annotation-fidelity",
                languageSelection="all",
                sourcePredicateIdentityRetained=True,
            )
        )

        note_predicates = _source_note_predicates(pair)
        publisher_note_claims = {
            (resource, predicate, literal)
            for resource, predicate, literal in publisher.annotations
            if resource in publisher.concepts
            and predicate in note_predicates
        }
        publisher_note_values = {
            (resource, literal) for resource, _, literal in publisher_note_claims
        }
        atlas_note_values = {
            (resource, _reverse_atlas_english_literal(pair, literal))
            for resource, values in atlas.notes.items()
            if resource in source_targets
            for literal in values
        }
        atlas_note_values.update(
            (resource, _reverse_atlas_english_literal(pair, literal))
            for resource, predicate, literal in atlas.raw_source_literal_claims
            if resource in publisher.concepts and predicate in note_predicates
        )
        recovered_note_claim_candidates = set(
            atlas.native_literal_claims | atlas.raw_source_literal_claims
        )
        if (
            spec.rdf_source is not None
            and spec.rdf_source.note_predicate_inverse is not None
        ):
            recovered_note_claim_candidates.update(
                (
                    resource,
                    spec.rdf_source.note_predicate_inverse,
                    literal,
                )
                for resource, literal in atlas_note_values
            )
        native_note_claims = (
            publisher_note_claims & recovered_note_claim_candidates
        )
        note_status = _claim_status(publisher_note_values, atlas_note_values)
        if (
            note_status == "exact"
            and publisher_note_claims
            and len(native_note_claims) != len(publisher_note_claims)
        ):
            note_status = "normalized-lossy"
        families.append(
            _claim_family(
                name="notes",
                source_predicates=tuple(sorted(note_predicates)),
                atlas_predicates=(ATLAS_NOTE, ATLAS_NATIVE_PAYLOAD),
                source_claims=publisher_note_claims,
                atlas_claims=atlas_note_values,
                checked_by="annotation-fidelity",
                status=note_status,
                languageSelection="all",
                mappedSourceValueCount=len(publisher_note_values),
                recoveredSourcePredicateCount=len(native_note_claims),
                sourcePredicateIdentityReconstructable=(
                    len(native_note_claims) == len(publisher_note_claims)
                ),
            )
        )

        resource_annotation_predicates = frozenset(
            {SKOS_DEFINITION, *note_predicates}
        )
        publisher_resource_annotations = {
            row
            for row in publisher.resource_annotations
            if row[0] in publisher.concepts
            and row[1] in resource_annotation_predicates
        }
        atlas_resource_annotations = {
            row
            for row in (
                atlas.relations
                | atlas.native_relations
                | atlas.raw_source_iri_claims
            )
            if row[0] in source_targets and row[1] in resource_annotation_predicates
        }
        families.append(
            _claim_family(
                name="resourceValuedAnnotations",
                source_predicates=tuple(sorted(resource_annotation_predicates)),
                atlas_predicates=(RDF_SUBJECT, RDF_PREDICATE, RDF_OBJECT),
                source_claims=publisher_resource_annotations,
                atlas_claims=atlas_resource_annotations,
                checked_by="annotation-fidelity",
                sourcePredicateIdentityRetained=True,
                sourceDirectionRetained=True,
            )
        )
        annotation_targets = frozenset(
            target for _, _, target in publisher_resource_annotations
        )
        publisher_annotation_target_claims = {
            *(
                row
                for row in publisher.iri_claims
                if row[0] in annotation_targets
            ),
            *(
                row
                for row in publisher.literal_claims
                if row[0] in annotation_targets
            ),
        }
        annotation_target_predicates = frozenset(
            row[1] for row in publisher_annotation_target_claims
        )
        atlas_annotation_target_raw_iri_claims = {
            row
            for row in atlas.raw_source_iri_claims
            if row[0] in annotation_targets
            and not row[1].startswith(ATLAS)
        }
        atlas_annotation_target_claims = {
            *(
                row
                for row in atlas_annotation_target_raw_iri_claims
                if not _atlas_only_raw_type_claim(
                    row,
                    publisher_annotation_target_claims,
                )
            ),
            *(
                row
                for row in (atlas.native_relations | atlas.relations)
                if row[0] in annotation_targets
                and not row[1].startswith(ATLAS)
            ),
            *(
                row
                for row in (
                    atlas.raw_source_literal_claims
                    | atlas.native_literal_claims
                )
                if row[0] in annotation_targets
                and not row[1].startswith(ATLAS)
            ),
        }
        families.append(
            _claim_family(
                name="annotationTargetClosure",
                source_predicates=tuple(sorted(annotation_target_predicates)),
                atlas_predicates=(ATLAS_NATIVE_PAYLOAD,),
                source_claims=publisher_annotation_target_claims,
                atlas_claims=atlas_annotation_target_claims,
                checked_by="annotation-fidelity",
                sourcePredicateIdentityRetained=True,
            )
        )

        publisher_member_iris = _publisher_member_iri_claims(pair)
        atlas_member_iris = _atlas_member_iri_claims(pair)
        member_iri_predicates = tuple(
            sorted({predicate for _, predicate, _ in publisher_member_iris})
        )
        families.append(
            _claim_family(
                name="memberIriMetadata",
                source_predicates=member_iri_predicates,
                atlas_predicates=(ATLAS_NATIVE_PAYLOAD,),
                source_claims=set(publisher_member_iris),
                atlas_claims=set(atlas_member_iris),
                checked_by="member-iri-fidelity",
                sourcePredicateIdentityRetained=True,
                sourceDirectionRetained=True,
            )
        )
        publisher_member_literals = _publisher_member_metadata_literals(pair)
        atlas_member_literals = _atlas_member_metadata_literals(pair)
        member_literal_predicates = tuple(
            sorted({predicate for _, predicate, _ in publisher_member_literals})
        )
        families.append(
            _claim_family(
                name="memberMetadataLiterals",
                source_predicates=member_literal_predicates,
                atlas_predicates=(ATLAS_NATIVE_PAYLOAD,),
                source_claims=set(publisher_member_literals),
                atlas_claims=set(atlas_member_literals),
                checked_by="member-literal-fidelity",
                lexicalFormRetained=True,
                languageAndDatatypeCompared=True,
                sourcePredicateIdentityRetained=True,
            )
        )
        publisher_source_wide_literals = _publisher_source_wide_literals(pair)
        atlas_source_wide_literals = _atlas_source_wide_literals(pair)
        source_wide_literal_predicates = tuple(
            sorted(
                {
                    predicate
                    for _, predicate, _ in publisher_source_wide_literals
                }
            )
        )
        families.append(
            _claim_family(
                name="sourceWideLiterals",
                source_predicates=source_wide_literal_predicates,
                atlas_predicates=(ATLAS_NATIVE_PAYLOAD,),
                source_claims=set(publisher_source_wide_literals),
                atlas_claims=set(atlas_source_wide_literals),
                checked_by="member-literal-fidelity",
                lexicalFormRetained=True,
                languageAndDatatypeCompared=True,
                sourcePredicateIdentityRetained=True,
            )
        )

        source_top = {
            claim for claim in publisher.top_concept_of if claim[0] in publisher.concepts
        }
        source_has_top = {
            (scheme, concept)
            for scheme, concept in publisher.has_top_concept
        }
        atlas_top = {
            (resource, scheme)
            for resource, schemes in atlas.native_top_concept_of_iris.items()
            if resource in publisher.concepts
            for scheme in schemes
        }
        atlas_top.update(
            (subject, obj)
            for subject, predicate, obj in atlas.raw_source_iri_claims
            if subject in publisher.concepts
            and predicate == SKOS_TOP_CONCEPT_OF
        )
        atlas_top.update(
            (concept, scheme)
            for scheme, predicate, concept in atlas.raw_source_iri_claims
            if predicate == SKOS_HAS_TOP_CONCEPT
        )
        publisher_memberships = {
            membership
            for membership in publisher.memberships
            if membership[0] in publisher.concepts
        }
        native_memberships = {
            (resource, scheme)
            for resource, schemes in atlas.native_scheme_iris.items()
            if resource in publisher.concepts
            for scheme in schemes
        }
        publisher_scheme_iri_metadata = _publisher_source_scheme_iri_metadata(
            pair
        )
        atlas_scheme_iri_metadata = _atlas_source_scheme_iri_metadata(pair)
        publisher_scheme_literals = _publisher_source_scheme_literal_claims(pair)
        atlas_scheme_literals = _atlas_source_scheme_literal_claims(pair)
        membership_status = _claim_status(
            publisher_memberships, native_memberships
        )
        additional_relation_predicates = (
            spec.rdf_source.additional_relation_predicates
            if spec.rdf_source is not None
            else ()
        )
        families.extend(
            (
                _claim_family(
                    name="conceptIdentities",
                    source_predicates=(RDF_TYPE,),
                    atlas_predicates=(RDF_TYPE,),
                    source_claims=set(publisher.concepts),
                    atlas_claims=set(_atlas_publisher_concepts(pair)),
                    checked_by="concept-traceability",
                ),
                _claim_family(
                    name="semanticRelations",
                    source_predicates=(
                        *HIERARCHY_PREDICATES,
                        *MAPPING_PREDICATES,
                        *additional_relation_predicates,
                    ),
                    atlas_predicates=(RDF_SUBJECT, RDF_PREDICATE, RDF_OBJECT),
                    source_claims=set(_publisher_source_relations(pair)),
                    atlas_claims=set(_atlas_source_relations(pair)),
                    checked_by="relation-fidelity",
                    sourcePredicateIdentityRetained=True,
                    sourceDirectionRetained=True,
                ),
                _claim_family(
                    name="schemeMemberships",
                    source_predicates=(SKOS_IN_SCHEME,),
                    atlas_predicates=(ATLAS_NATIVE_PAYLOAD,),
                    source_claims=publisher_memberships,
                    atlas_claims=native_memberships,
                    checked_by="scheme-organisation",
                    status=membership_status,
                    nativeSourceMembershipCount=len(
                        publisher_memberships & native_memberships
                    ),
                ),
                _claim_family(
                    name="sourceSchemeIdentities",
                    source_predicates=(RDF_TYPE,),
                    atlas_predicates=(RDF_TYPE,),
                    source_claims=set(publisher.schemes),
                    atlas_claims=set(_atlas_source_scheme_identities(pair)),
                    checked_by="scheme-organisation",
                    reconstruction=(
                        "exact source type; native scheme references prove membership, "
                        "not an explicit publisher rdf:type claim"
                    ),
                ),
                _claim_family(
                    name="sourceSchemeIriMetadata",
                    source_predicates=tuple(
                        sorted(
                            {
                                predicate
                                for _, predicate, _ in publisher_scheme_iri_metadata
                            }
                        )
                    ),
                    atlas_predicates=(ATLAS_NATIVE_PAYLOAD,),
                    source_claims=set(publisher_scheme_iri_metadata),
                    atlas_claims=set(atlas_scheme_iri_metadata),
                    checked_by="scheme-organisation",
                    sourcePredicateIdentityRetained=True,
                ),
                _claim_family(
                    name="sourceSchemeLiterals",
                    source_predicates=tuple(
                        sorted(
                            {
                                predicate
                                for _, predicate, _ in publisher_scheme_literals
                            }
                        )
                    ),
                    atlas_predicates=(
                        ATLAS_NATIVE_PAYLOAD,
                        SKOSXL_PREF_LABEL,
                        SKOSXL_ALT_LABEL,
                        SKOSXL_HIDDEN_LABEL,
                        ATLAS_NOTATION,
                        ATLAS_DEFINITION,
                        ATLAS_NOTE,
                    ),
                    source_claims=set(publisher_scheme_literals),
                    atlas_claims=set(atlas_scheme_literals),
                    checked_by="scheme-organisation",
                    lexicalFormRetained=True,
                    languageAndDatatypeCompared=True,
                    sourcePredicateIdentityRetained=True,
                ),
                _claim_family(
                    name="topConceptOfAssignments",
                    source_predicates=(SKOS_TOP_CONCEPT_OF,),
                    atlas_predicates=(ATLAS_NATIVE_PAYLOAD,),
                    source_claims=source_top,
                    atlas_claims=atlas_top & source_top,
                    checked_by="top-concept-fidelity",
                    nativePayloadEvidence=True,
                ),
                _claim_family(
                    name="hasTopConceptAssignments",
                    source_predicates=(SKOS_HAS_TOP_CONCEPT,),
                    atlas_predicates=(ATLAS_NATIVE_PAYLOAD,),
                    source_claims=source_has_top,
                    atlas_claims={
                        (scheme, concept)
                        for concept, scheme in atlas_top
                        if (scheme, concept) in source_has_top
                    },
                    checked_by="top-concept-fidelity",
                    sourcePredicateIdentityRetained=True,
                    sourceDirectionRetained=True,
                    reconstruction="inverse nativePayload.topConceptOfIris",
                ),
            )
        )
        if spec.rdf_source is not None and spec.rdf_source.reification_predicates:
            reification_predicates = frozenset(
                spec.rdf_source.reification_predicates
            )
            publisher_reifications = {
                row
                for row in publisher.reified_statements
                if row.predicate_iri in reification_predicates
            }
            atlas_reifications, atlas_weights, _ = _reconstructed_reification(pair)
            families.append(
                _claim_family(
                    name="publisherReifications",
                    source_predicates=(
                        RDF_TYPE,
                        RDF_SUBJECT,
                        RDF_PREDICATE,
                        RDF_OBJECT,
                    ),
                    atlas_predicates=(ATLAS_NATIVE_PAYLOAD,),
                    source_claims=publisher_reifications,
                    atlas_claims=set(atlas_reifications),
                    checked_by="reification-fidelity",
                    sourcePredicateIdentityRetained=True,
                    sourceDirectionRetained=True,
                )
            )
            if spec.rdf_source.reification_weight_predicate is not None:
                publisher_weights = {
                    row
                    for row in publisher.literal_claims
                    if row[1] == spec.rdf_source.reification_weight_predicate
                }
                families.append(
                    _claim_family(
                        name="detachedRelationWeights",
                        source_predicates=(
                            spec.rdf_source.reification_weight_predicate,
                        ),
                        atlas_predicates=(ATLAS_NATIVE_PAYLOAD,),
                        source_claims=publisher_weights,
                        atlas_claims=set(atlas_weights),
                        checked_by="reification-fidelity",
                        lexicalFormRetained=True,
                        languageAndDatatypeCompared=True,
                    )
                )
        compared_predicates = COMPARED_VOCABULARY_PREDICATES | frozenset(
            (
                *additional_relation_predicates,
                *note_predicates,
                *member_iri_predicates,
                *member_literal_predicates,
                *source_wide_literal_predicates,
                *(
                    predicate
                    for _, predicate, _ in publisher_scheme_iri_metadata
                ),
                *(
                    predicate
                    for _, predicate, _ in publisher_scheme_literals
                ),
            )
        )

    release_publisher_iri, release_publisher_literals = (
        _publisher_release_metadata_claims(pair)
    )
    release_atlas_iri, release_atlas_literals = _atlas_release_metadata_claims(pair)
    release_publisher_claims = {
        *(("iri", *row) for row in release_publisher_iri),
        *(("literal", *row) for row in release_publisher_literals),
    }
    release_atlas_claims = {
        *(("iri", *row) for row in release_atlas_iri),
        *(("literal", *row) for row in release_atlas_literals),
    }
    families.append(
        _claim_family(
            name="sourceReleaseMetadata",
            source_predicates=tuple(
                sorted({row[1] for row in release_publisher_claims})
            ),
            atlas_predicates=tuple(sorted({row[1] for row in release_atlas_claims})),
            source_claims=release_publisher_claims,
            atlas_claims=release_atlas_claims,
            checked_by="source-release-metadata",
            sourcePredicateIdentityRetained=True,
            adoptedReleaseIris=sorted(_atlas_source_release_subjects(pair)),
            sourceFieldFamilies=dict(
                sorted(
                    Counter(
                        _release_metadata_family(row[1])
                        for row in release_publisher_claims
                    ).items()
                )
            ),
        )
    )

    residual_iri, residual_literals = _publisher_claims_outside_comparison(pair)
    residual_atlas_iri, residual_atlas_literals = (
        _atlas_claims_outside_comparison(pair)
    )
    uncovered_source_claims = {
        *(("publisher-iri", *row) for row in residual_iri),
        *(("publisher-literal", *row) for row in residual_literals),
        *(("unevaluated", detail) for detail in publisher.unevaluated_claims),
    }
    uncovered_atlas_claims = {
        *(("atlas-iri", *row) for row in residual_atlas_iri),
        *(("atlas-literal", *row) for row in residual_atlas_literals),
    }
    families.append(
        _claim_family(
            name="completeSourceClaimCoverage",
            source_predicates=(),
            atlas_predicates=(),
            source_claims=uncovered_source_claims,
            atlas_claims=uncovered_atlas_claims,
            checked_by="source-claim-coverage",
            meaning="publisher or Atlas source-shaped claims not owned by any executable comparison",
        )
    )

    provenance_failures = _rdf_provenance_failures(pair)
    families.append(
        _claim_family(
            name="sourceRecordProvenance",
            source_predicates=(),
            atlas_predicates=(
                ATLAS_REPRESENTS_RESOURCE,
                ATLAS_SOURCE_LOCATOR,
                ATLAS_SOURCE_DIGEST,
                ATLAS_NATIVE_PAYLOAD,
            ),
            source_claims=set(),
            atlas_claims=set(),
            checked_by="rdf-provenance-fidelity",
            status=("differences-found" if provenance_failures else "exact"),
            evaluationFailureCount=len(provenance_failures),
        )
    )

    predicate_counts: dict[str, int] = defaultdict(int)
    for (resource, predicate), count in publisher.resource_predicate_counts.items():
        if resource in (
            publisher.concepts
            | _publisher_source_scheme_subjects(publisher)
        ):
            predicate_counts[predicate] += count
    unexpected_predicates = sorted(set(predicate_counts) - compared_predicates)

    excluded_families: list[dict[str, Any]] = [
        {
            "name": "atlasRepresentationStructure",
            "predicates": sorted(ATLAS_SOURCE_REPRESENTATION_STRUCTURE_PREDICATES),
            "reason": (
                "classes, rings, profiles, releases, schemes, source records, "
                "relation assertions, rkaf evidence bindings, and the record "
                "lifecycle state are Atlas-minted and are not publisher claims; "
                "each listed predicate is still a failure on any subject the "
                "comparison does not already know"
            ),
        },
        *_declared_claim_exclusion_report(pair),
    ]
    family_statuses = {family["status"] for family in families}
    violated_exclusions = [
        family
        for family in excluded_families
        if family.get("status", "declared-out-of-scope") != "declared-out-of-scope"
    ]
    if (
        family_statuses & {"differences-found", "unrepresented"}
        or unexpected_predicates
        or violated_exclusions
    ):
        status = "differences-found"
    elif "normalized-lossy" in family_statuses:
        status = "partial-lossy"
    else:
        status = "exact"
    return {
        "status": status,
        "claimFamilies": families,
        "intentionallyExcludedFamilies": excluded_families,
        "unexpectedPublisherPredicates": [
            {"predicate": predicate, "claimCount": predicate_counts[predicate]}
            for predicate in unexpected_predicates
        ],
    }


def _native_control_claim_scope(
    spec: SourceSpec,
    pair: NativeControlPair | None,
    evaluation_failures: Sequence[str] = (),
) -> dict[str, Any]:
    """Describe the exact source values reconstructed from one Parquet field."""
    if pair is None or spec.native_control is None:
        return {
            "status": "not-evaluated",
            "claimFamilies": [],
            "intentionallyExcludedFamilies": [],
            "unexpectedPublisherPredicates": [],
        }

    raw_counts = set(pair.publisher.values.items())
    atlas_counts: set[tuple[str, int]] = set()
    atlas_labels: set[str] = set()
    atlas_notations: set[str] = set()
    for record, payload in pair.atlas.native_payloads.items():
        if record not in pair.atlas.record_targets:
            continue
        value_row = payload.get("value")
        if isinstance(value_row, Mapping):
            value = value_row.get("value")
            count = value_row.get("count")
            if isinstance(value, str) and isinstance(count, int) and not isinstance(count, bool):
                atlas_counts.add((value, count))
        target = pair.atlas.record_targets[record]
        atlas_labels.update(
            literal.value
            for literal in pair.atlas.pref_labels.get(target, frozenset())
            if literal.language == "en"
        )
        atlas_notations.update(
            literal.value
            for literal in pair.atlas.notations.get(target, frozenset())
        )
    raw_values = set(pair.publisher.values)
    capture_values, _ = _capture_value_counts(spec.name, pair.publisher.capture)
    families = [
        _claim_family(
            name="controlledValues",
            source_predicates=(),
            atlas_predicates=(ATLAS_NATIVE_PAYLOAD,),
            source_claims=raw_values,
            atlas_claims={value for value, _ in atlas_counts},
            checked_by="native-control-fidelity",
            sourceField=spec.native_control.source_field,
            extraction=spec.native_control.extraction,
        ),
        _claim_family(
            name="occurrenceCounts",
            source_predicates=(),
            atlas_predicates=(ATLAS_NATIVE_PAYLOAD,),
            source_claims=raw_counts,
            atlas_claims=atlas_counts,
            checked_by="native-control-fidelity",
        ),
        _claim_family(
            name="preferredLabels",
            source_predicates=(),
            atlas_predicates=(SKOSXL_PREF_LABEL, SKOSXL_LITERAL_FORM),
            source_claims=raw_values,
            atlas_claims=atlas_labels,
            checked_by="native-control-fidelity",
        ),
        _claim_family(
            name="notations",
            source_predicates=(),
            atlas_predicates=(ATLAS_NOTATION,),
            source_claims=raw_values,
            atlas_claims=atlas_notations,
            checked_by="native-control-fidelity",
        ),
        _claim_family(
            name="normalizedCaptureValues",
            source_predicates=(),
            atlas_predicates=(ATLAS_NATIVE_PAYLOAD,),
            source_claims=raw_counts,
            atlas_claims=set(capture_values.items()),
            checked_by="native-control-fidelity",
        ),
        _claim_family(
            name="completeSourceEvaluation",
            source_predicates=(),
            atlas_predicates=(
                ATLAS_SOURCE_LOCATOR,
                ATLAS_SOURCE_DIGEST,
                ATLAS_NATIVE_PAYLOAD,
                ATLAS_REPRESENTS_RESOURCE,
                SKOSXL_PREF_LABEL,
                ATLAS_NOTATION,
            ),
            source_claims=set(),
            atlas_claims=set(),
            checked_by="native-control-fidelity",
            status=("differences-found" if evaluation_failures else "exact"),
            evaluationFailureCount=len(evaluation_failures),
            evaluatedClaims=(
                "input pins, raw Parquet values and counts, capture source fields, "
                "locators, digests, source payload values, labels, and notations"
            ),
        ),
    ]
    statuses = {family["status"] for family in families}
    status = (
        "differences-found"
        if statuses & {"differences-found", "unrepresented"}
        or pair.publisher.failures
        or evaluation_failures
        else "exact"
    )
    return {
        "status": status,
        "claimFamilies": families,
        "intentionallyExcludedFamilies": [
            {
                "name": "unselectedParquetColumns",
                "columns": [
                    column
                    for column in spec.native_control.expected_columns
                    if column != spec.native_control.source_field
                ],
                "reason": "this release declares one source-native control field",
            }
        ],
        "unexpectedPublisherPredicates": [],
    }


def _source_extract_claim_scope(
    spec: SourceSpec,
    pair: SourceExtractPair | None,
    evaluation_failures: Sequence[str] = (),
) -> dict[str, Any]:
    """Describe exactly what one checked-in source extract was compared on."""
    if pair is None or spec.source_extract is None:
        return {
            "status": "not-evaluated",
            "claimFamilies": [],
            "intentionallyExcludedFamilies": [],
            "unexpectedPublisherPredicates": [],
        }

    selector = spec.source_extract
    publisher = pair.publisher
    keyed = _source_extract_atlas_view(pair)
    source_concepts = set(publisher.concept_labels)
    source_pref = {
        (local_id, _literal_value(label, selector.label_language, None))
        for local_id, label in publisher.concept_labels.items()
    }
    atlas_pref_claims = {
        (local_id, literal)
        for local_id, values in keyed.pref_labels.items()
        for literal in values
    }
    source_alt = {
        (local_id, _literal_value(value, selector.label_language, None))
        for local_id, values in publisher.alternate_labels.items()
        for value in values
    }
    atlas_alt_claims = {
        (local_id, literal)
        for local_id, values in keyed.alt_labels.items()
        for literal in values
    }
    source_locators = {
        (local_id, tuple(sorted(locator.items())))
        for local_id, locator in publisher.concept_locators.items()
    }
    atlas_locator_claims = {
        (local_id, tuple(sorted(locator.items())))
        for local_id, locator in keyed.locators.items()
        if isinstance(locator, Mapping)
    }
    families = [
        _claim_family(
            name="conceptIdentities",
            source_predicates=(),
            atlas_predicates=(ATLAS_NATIVE_PAYLOAD, ATLAS_REPRESENTS_RESOURCE),
            source_claims=source_concepts,
            atlas_claims=set(keyed.resource_by_local),
            checked_by="source-extract-fidelity",
            joinedOn="nativePayload.sourceLocalConceptId",
        ),
        _claim_family(
            name="preferredLabels",
            source_predicates=(),
            atlas_predicates=(SKOSXL_PREF_LABEL, SKOSXL_LITERAL_FORM),
            source_claims=source_pref,
            atlas_claims=atlas_pref_claims,
            checked_by="source-extract-fidelity",
            languageSelection=selector.label_language,
            lexicalFormRetained=True,
            languageAndDatatypeCompared=True,
        ),
        _claim_family(
            name="alternateLabels",
            source_predicates=(),
            atlas_predicates=(SKOSXL_ALT_LABEL, SKOSXL_LITERAL_FORM),
            source_claims=source_alt,
            atlas_claims=atlas_alt_claims,
            checked_by="source-extract-fidelity",
            sourceRowSelector="variants with resolution_status recognizedVariant",
        ),
        _claim_family(
            name="associativeRelations",
            source_predicates=(),
            atlas_predicates=(RDF_SUBJECT, RDF_PREDICATE, RDF_OBJECT),
            source_claims=set(publisher.relations),
            atlas_claims=set(keyed.relations),
            checked_by="source-extract-fidelity",
            sourceRowSelector="relatedReferences with resolution_status resolved",
            sourceDirectionRetained=True,
        ),
        _claim_family(
            name="sourceEntryIdentities",
            source_predicates=(),
            atlas_predicates=(ATLAS_NATIVE_PAYLOAD,),
            source_claims=set(publisher.concept_entry_ids.items()),
            atlas_claims=set(keyed.entry_ids.items()),
            checked_by="source-extract-fidelity",
        ),
        _claim_family(
            name="sourceLocators",
            source_predicates=(),
            atlas_predicates=(ATLAS_NATIVE_PAYLOAD,),
            source_claims=source_locators,
            atlas_claims=atlas_locator_claims,
            checked_by="source-extract-fidelity",
        ),
        _claim_family(
            name="completeSourceEvaluation",
            source_predicates=(),
            atlas_predicates=(ATLAS_SOURCE_DIGEST,),
            source_claims=set(),
            atlas_claims=set(),
            checked_by="source-extract-fidelity",
            status=("differences-found" if evaluation_failures else "exact"),
            evaluationFailureCount=len(evaluation_failures),
            evaluatedClaims=(
                "publisher artifact pin, the extract's own binding to those bytes, "
                "concept identities, preferred and alternate labels, associative "
                "relations, source entry identities, and source locators"
            ),
        ),
    ]
    statuses = {family["status"] for family in families}
    status = (
        "differences-found"
        if statuses & {"differences-found", "unrepresented"}
        or publisher.failures
        or evaluation_failures
        else "exact"
    )
    return {
        "status": status,
        "claimFamilies": families,
        "intentionallyExcludedFamilies": [
            {
                "name": "sourceRowsAtlasMustNotAssert",
                "rowCounts": dict(sorted(publisher.unrepresented_rows.items())),
                "reason": (
                    "the publisher's own extract marks these rows unresolved, "
                    "ambiguous, or as open-term suggestions; the exact set "
                    "comparisons above are what prove Atlas asserts none of them"
                ),
            },
            {
                "name": "atlasRepresentationStructure",
                "reason": (
                    "classes, rings, profiles, releases, schemes, source records, "
                    "relation assertions, and rkaf evidence bindings are Atlas-minted "
                    "and are not publisher claims"
                ),
            },
        ],
        "unexpectedPublisherPredicates": [],
        "comparisonBasis": {
            "reader": selector.reader,
            "extractPath": selector.extract.path,
            "extractSha256": selector.extract.sha256,
            "extractByteLength": selector.extract.byte_length,
            "observedExtractDigest": publisher.extract_digest,
            "independentReparseOfPublisherBytes": False,
            "note": (
                "the publisher ships a styled PDF; the comparison basis is the "
                "repository-checked semantic extract of the authenticated artifact, "
                "which the builder does not read"
            ),
        },
    }


def _counted_source_list_claims(rows: Sequence[SourceListRow]) -> set[tuple[str, int]]:
    """Keep duplicate publisher rows visible to the receipt's set arithmetic."""
    return {
        (_source_list_row_repr(row), occurrence)
        for row, count in Counter(rows).items()
        for occurrence in range(count)
    }


def _source_list_claim_scope(
    spec: SourceSpec,
    pair: SourceListPair | None,
    evaluation_failures: Sequence[str] = (),
) -> dict[str, Any]:
    """Describe the exact publisher row claims one source-list reader owns."""
    if pair is None or spec.source_list is None:
        return {
            "status": "not-evaluated",
            "claimFamilies": [],
            "intentionallyExcludedFamilies": [],
            "unexpectedPublisherPredicates": [],
        }
    atlas_rows, _ = _atlas_source_list_rows(pair)
    source_rows = pair.publisher.rows
    source_notations = {
        (notations, occurrence)
        for notations, count in Counter(row.notations for row in source_rows).items()
        for occurrence in range(count)
    }
    atlas_notations = {
        (notations, occurrence)
        for notations, count in Counter(row.notations for row in atlas_rows).items()
        for occurrence in range(count)
    }
    families = [
        _claim_family(
            name="publisherRows",
            source_predicates=(),
            atlas_predicates=(ATLAS_NATIVE_PAYLOAD, ATLAS_REPRESENTS_RESOURCE),
            source_claims=_counted_source_list_claims(source_rows),
            atlas_claims=_counted_source_list_claims(atlas_rows),
            checked_by="source-list-fidelity",
            sourceAssertion=pair.publisher.source_assertion,
            rowMultiplicityCompared=True,
        ),
        _claim_family(
            name="notations",
            source_predicates=(),
            atlas_predicates=(ATLAS_NOTATION,),
            source_claims=source_notations,
            atlas_claims=atlas_notations,
            checked_by="source-list-fidelity",
            rowGroupingRetained=True,
        ),
    ]
    if spec.source_list.compare_labels:
        source_labels = {
            (_literal_repr(label), occurrence)
            for label, count in Counter(row.label for row in source_rows).items()
            if label is not None
            for occurrence in range(count)
        }
        atlas_labels = {
            (_literal_repr(label), occurrence)
            for label, count in Counter(row.label for row in atlas_rows).items()
            if label is not None
            for occurrence in range(count)
        }
        families.append(
            _claim_family(
                name="preferredLabels",
                source_predicates=(),
                atlas_predicates=(SKOSXL_PREF_LABEL, SKOSXL_LITERAL_FORM),
                source_claims=source_labels,
                atlas_claims=atlas_labels,
                checked_by="source-list-fidelity",
                languageSelection=spec.source_list.label_language,
                lexicalFormRetained=not spec.source_list.casefold_labels,
                casefolded=spec.source_list.casefold_labels,
            )
        )
    if spec.source_list.compare_resource_iri:
        source_identities = {
            (identity, occurrence)
            for identity, count in Counter(
                row.resource_iri for row in source_rows
            ).items()
            for occurrence in range(count)
        }
        atlas_identities = {
            (identity, occurrence)
            for identity, count in Counter(
                row.resource_iri for row in atlas_rows
            ).items()
            for occurrence in range(count)
        }
        families.append(
            _claim_family(
                name="resourceIdentities",
                source_predicates=(),
                atlas_predicates=(ATLAS_REPRESENTS_RESOURCE,),
                source_claims=source_identities,
                atlas_claims=atlas_identities,
                checked_by="source-list-fidelity",
                publisherIriRetained=True,
            )
        )
    if spec.source_list.native_payload_fields:
        source_attributes = {
            (attributes, occurrence)
            for attributes, count in Counter(
                row.native_attributes for row in source_rows
            ).items()
            for occurrence in range(count)
        }
        atlas_attributes = {
            (attributes, occurrence)
            for attributes, count in Counter(
                row.native_attributes for row in atlas_rows
            ).items()
            for occurrence in range(count)
        }
        families.append(
            _claim_family(
                name="nativePayloadAttributes",
                source_predicates=(),
                atlas_predicates=(ATLAS_NATIVE_PAYLOAD,),
                source_claims=source_attributes,
                atlas_claims=atlas_attributes,
                checked_by="source-list-fidelity",
                fields=list(spec.source_list.native_payload_fields),
                scalarValuesCompared=True,
            )
        )
    statuses = {family["status"] for family in families}
    status = (
        "differences-found"
        if statuses & {"differences-found", "unrepresented"}
        or pair.publisher.failures
        or evaluation_failures
        else "exact"
    )
    return {
        "status": status,
        "claimFamilies": families,
        "intentionallyExcludedFamilies": [
            {
                "name": "publisherFieldsOutsideDeclaredRowShape",
                "reason": (
                    "the SourceSpec names the exact publisher fields this Atlas unit "
                    "represents; other page or record fields are authenticated but do not "
                    "enter this row comparison"
                ),
            },
            {
                "name": "atlasRepresentationStructure",
                "reason": (
                    "classes, rings, profiles, releases, schemes, source records, "
                    "and rkaf evidence bindings are Atlas-minted"
                ),
            },
        ],
        "unexpectedPublisherPredicates": [],
        "comparisonBasis": {
            "reader": spec.source_list.reader,
            "extraction": spec.source_list.extraction,
            "independentReparseOfPublisherBytes": True,
            "sourceAssertion": spec.source_list.source_assertion,
        },
    }


def _cached_comparison_claim_scope(
    ctx: Context,
    spec: SourceSpec,
    pair: SourcePair | None,
) -> dict[str, Any]:
    """Compute one immutable-input claim scope once and reuse it in the receipt."""
    cached = ctx.comparison_claim_scope_cache.get(spec)
    if cached is not None:
        return cached
    scope = _comparison_claim_scope(spec, pair)
    ctx.comparison_claim_scope_cache[spec] = scope
    return scope


def _evaluate_claim_scope(ctx: Context) -> CheckResult:
    """Fail closed on unhandled publisher predicates or known lossy representations."""
    failures = _incomplete_evaluation_failure(ctx, "claim-scope review")
    for kind in ("native-control", "source-extract", "source-list"):
        failures.extend(
            _incomplete_evaluation_failure(ctx, "claim-scope review", kind)
        )
    checked = 0
    for pair in ctx.pairs:
        scope = _cached_comparison_claim_scope(ctx, pair.spec, pair)
        checked += len(scope["claimFamilies"])
        for row in scope["unexpectedPublisherPredicates"]:
            failures.append(
                f"{pair.spec.name}: publisher predicate <{row['predicate']}> has "
                f"{row['claimCount']} resource claims but no comparison or explicit exclusion"
            )
        for family in scope["intentionallyExcludedFamilies"]:
            if family.get("status", "declared-out-of-scope") == "declared-out-of-scope":
                continue
            if family["atlasClaimCount"]:
                failures.append(
                    f"{pair.spec.name}: declared exclusion {family['name']} does not "
                    f"hold -- Atlas asserts {family['atlasClaimCount']} claim(s) about "
                    f"subjects it declares out of scope; examples "
                    f"{family['atlasClaimExamples'][:5]}"
                )
            if family["comparedSubjectOverlapCount"]:
                failures.append(
                    f"{pair.spec.name}: declared exclusion {family['name']} covers "
                    f"{family['comparedSubjectOverlapCount']} subject(s) this "
                    "comparison also compares; a scope declaration may never hide a "
                    f"compared claim; examples {family['comparedSubjectOverlapExamples']}"
                )
        for family in scope["claimFamilies"]:
            if family["status"] == "normalized-lossy":
                failures.append(
                    f"{pair.spec.name}: {family['name']} is represented with known semantic loss"
                )
            elif family["status"] not in {"exact", "not-applicable"}:
                failures.append(
                    f"{pair.spec.name}: {family['name']} source claims are "
                    f"{family['status']}"
                )
    native_fidelity = check_native_control_fidelity(ctx)
    for pair in ctx.native_control_pairs:
        prefix = f"{pair.spec.name}:"
        pair_failures = [
            failure for failure in native_fidelity.failures if failure.startswith(prefix)
        ]
        scope = _native_control_claim_scope(pair.spec, pair, pair_failures)
        checked += len(scope["claimFamilies"])
        for family in scope["claimFamilies"]:
            if family["status"] in {"differences-found", "unrepresented"}:
                failures.append(
                    f"{pair.spec.name}: {family['name']} differs from its declared direct-source scope"
                )
    extract_fidelity = check_source_extract_fidelity(ctx)
    for pair in ctx.source_extract_pairs:
        prefix = f"{pair.spec.name}:"
        pair_failures = [
            failure
            for failure in extract_fidelity.failures
            if failure.startswith(prefix)
        ]
        scope = _source_extract_claim_scope(pair.spec, pair, pair_failures)
        checked += len(scope["claimFamilies"])
        for family in scope["claimFamilies"]:
            if family["status"] in {"differences-found", "unrepresented"}:
                failures.append(
                    f"{pair.spec.name}: {family['name']} differs from its declared "
                    "checked-extract scope"
                )
    source_list_fidelity = check_source_list_fidelity(ctx)
    for pair in ctx.source_list_pairs:
        prefix = f"{pair.spec.name}:"
        pair_failures = [
            failure
            for failure in source_list_fidelity.failures
            if failure.startswith(prefix)
        ]
        scope = _source_list_claim_scope(pair.spec, pair, pair_failures)
        checked += len(scope["claimFamilies"])
        for family in scope["claimFamilies"]:
            if family["status"] in {"differences-found", "unrepresented"}:
                failures.append(
                    f"{pair.spec.name}: {family['name']} differs from its declared "
                    "publisher-row scope"
                )
    return _result(
        "claim-scope",
        f"{checked} declared source claim families checked for complete evaluation scope",
        failures,
    )


RECEIPT_LIST_LIMIT = 100


def _capped_receipt_list(
    values: Sequence[Any],
    limit: int = RECEIPT_LIST_LIMIT,
) -> tuple[list[Any], int, bool, str]:
    """Cap one receipt list, keeping its total and a digest over the whole of it.

    An unbounded receipt is not an artifact: the first full-registry run wrote
    231 MB, almost all of it the tail of four per-claim failure lists, which no
    reviewer can read and no release can carry. The head is what a reader acts
    on, the count is what they measure, and the digest is over the *complete*
    ordered list -- so re-running the verifier still proves nothing was dropped,
    reordered, or edited between the run and the receipt. The terminal report
    (``render``) stays complete; only the stored artifact is capped.
    """
    total = len(values)
    retained = list(values[:limit])
    digest = hashlib.sha256(
        json.dumps(list(values), ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return retained, total, total > len(retained), f"sha256:{digest}"


def _capped_result(result: CheckResult) -> dict[str, Any]:
    """Render one check result with both of its lists capped and accounted for."""
    failures, failure_total, failures_truncated, failure_digest = _capped_receipt_list(
        result.failures
    )
    findings, finding_total, findings_truncated, finding_digest = _capped_receipt_list(
        [finding.as_dict() for finding in result.source_findings]
    )
    return {
        "check": result.name,
        "passed": result.passed,
        "summary": result.summary,
        "failures": failures,
        "failuresTotalCount": failure_total,
        "failuresTruncated": failures_truncated,
        "failuresDigest": failure_digest,
        "sourceFindings": findings,
        "sourceFindingsTotalCount": finding_total,
        "sourceFindingsTruncated": findings_truncated,
        "sourceFindingsDigest": finding_digest,
    }


def _receipt(ctx: Context, results: Sequence[CheckResult]) -> dict[str, Any]:
    """Bind the report to exact candidate, input, pack, and verifier identities."""
    units_by_key = {unit.key: unit for unit in ctx.units}
    compared_keys = {
        key for spec in ctx.loaded_specs() for key in spec.release_keys
    } & set(units_by_key)
    declared_keys = {key for spec in ctx.specs for key in spec.release_keys} & set(units_by_key)
    scoped_out_keys = ctx.scoped_out_release_keys() & set(units_by_key)
    pairs_by_spec = {pair.spec: pair for pair in ctx.pairs}
    native_controls_by_spec = {
        pair.spec: pair for pair in ctx.native_control_pairs
    }
    source_extracts_by_spec = {
        pair.spec: pair for pair in ctx.source_extract_pairs
    }
    source_lists_by_spec = {pair.spec: pair for pair in ctx.source_list_pairs}
    atlas_by_spec = dict(ctx.atlas_views)

    def spec_failures(check_name: str, spec: SourceSpec) -> list[str]:
        result = next(
            (item for item in results if item.name == check_name),
            None,
        )
        return [
            failure
            for failure in (result.failures if result is not None else ())
            if failure.startswith(f"{spec.name}:")
        ]

    def claim_scope(spec: SourceSpec) -> dict[str, Any]:
        if spec.kind == "native-control":
            return _native_control_claim_scope(
                spec,
                native_controls_by_spec.get(spec),
                spec_failures("native-control-fidelity", spec),
            )
        if spec.kind == "source-extract":
            return _source_extract_claim_scope(
                spec,
                source_extracts_by_spec.get(spec),
                spec_failures("source-extract-fidelity", spec),
            )
        if spec.kind == "source-list":
            return _source_list_claim_scope(
                spec,
                source_lists_by_spec.get(spec),
                spec_failures("source-list-fidelity", spec),
            )
        return _cached_comparison_claim_scope(ctx, spec, pairs_by_spec.get(spec))

    scope_by_spec = {spec: claim_scope(spec) for spec in ctx.specs}
    owners_by_key: dict[str, list[SourceSpec]] = defaultdict(list)
    for spec in ctx.specs:
        for key in spec.release_keys:
            if key in units_by_key:
                owners_by_key[key].append(spec)
    result_failures = [failure for result in results for failure in result.failures]
    declared_spec_names = {spec.name for spec in ctx.specs}
    failed_spec_names = {
        failure.partition(":")[0]
        for failure in result_failures
        if failure.partition(":")[0] in declared_spec_names
    }
    loaded_specs = set(ctx.loaded_specs())

    def fidelity_status(spec: SourceSpec) -> str:
        scope_status = scope_by_spec[spec]["status"]
        if scope_status == "not-evaluated" or spec not in loaded_specs:
            return "not-evaluated"
        if scope_status != "exact":
            return "differences-found"
        if any(len(owners_by_key.get(key, ())) != 1 for key in spec.release_keys):
            return "prerequisite-failed"
        if any(pin not in ctx.verified_pins for pin in spec.inputs):
            return "prerequisite-failed"
        atlas = atlas_by_spec.get(spec)
        if atlas is None or atlas.structural_failures:
            return "prerequisite-failed"
        if spec.name in failed_spec_names:
            return "prerequisite-failed"
        return "exact"

    fidelity_by_spec = {spec: fidelity_status(spec) for spec in ctx.specs}
    fidelity_by_key = {
        key: (
            fidelity_by_spec[owners[0]]
            if len(owners) == 1
            else "prerequisite-failed"
        )
        for key, owners in owners_by_key.items()
    }
    comparison_rows: list[dict[str, Any]] = []
    for spec in ctx.specs:
        atlas = atlas_by_spec.get(spec)
        fallback_packs = tuple(
            pack
            for key in spec.release_keys
            for pack in units_by_key.get(key, DistributionUnit(key, "", (), (), {})).packs
        )
        comparison_rows.append(
            {
                "name": spec.name,
                "kind": spec.kind,
                "subset": spec.subset,
                "includedPublisherConceptIris": sorted(spec.included_concept_iris),
                "releaseKeys": list(spec.release_keys),
                "publisherLoaded": (
                    spec in native_controls_by_spec
                    if spec.kind == "native-control"
                    else spec in source_extracts_by_spec
                    if spec.kind == "source-extract"
                    else spec in source_lists_by_spec
                    if spec.kind == "source-list"
                    else spec in pairs_by_spec
                ),
                "atlasLoaded": atlas is not None,
                "policies": sorted(spec.policies),
                "atlasOnlyNativePayloadFields": sorted(
                    spec.rdf_source.atlas_only_native_payload_fields
                    if spec.rdf_source is not None
                    else ()
                ),
                "nonWaivingPredicateDeclarations": sorted(
                    spec.excluded_resource_predicates
                ),
                "claimScope": scope_by_spec[spec],
                "fidelityStatus": fidelity_by_spec[spec],
                "publisherInputs": [
                    {
                        "path": pin.path,
                        "constructionPath": pin.construction_path or pin.path,
                        "sha256": pin.sha256,
                        "byteLength": pin.byte_length,
                        "archiveMember": pin.zip_member,
                        "role": pin.role,
                        "sourceIri": pin.source_iri,
                        "evidenceClass": (
                            "secondaryNormalizedCapture"
                            if spec.kind == "native-control" and pin.fmt == "json"
                            else "directSourceBytes"
                        ),
                    }
                    for pin in spec.inputs
                ],
                "sourceExtract": (
                    {
                        "reader": spec.source_extract.reader,
                        "extractPath": spec.source_extract.extract.path,
                        "extractSha256": spec.source_extract.extract.sha256,
                        "extractByteLength": spec.source_extract.extract.byte_length,
                        "sourceReleaseIri": spec.source_extract.source_release_iri,
                        "labelLanguage": spec.source_extract.label_language,
                        "relationPredicate": spec.source_extract.relation_predicate,
                    }
                    if spec.source_extract is not None
                    else None
                ),
                "sourceList": (
                    {
                        "reader": spec.source_list.reader,
                        "extraction": spec.source_list.extraction,
                        "expectedRecordCount": spec.source_list.expected_record_count,
                        "sourceAssertion": spec.source_list.source_assertion,
                        "compareLabels": spec.source_list.compare_labels,
                        "casefoldLabels": spec.source_list.casefold_labels,
                        "compareResourceIri": spec.source_list.compare_resource_iri,
                        "nativePayloadFields": list(
                            spec.source_list.native_payload_fields
                        ),
                        "normalizeWhitespace": spec.source_list.normalize_whitespace,
                    }
                    if spec.source_list is not None
                    else None
                ),
                "nativeControl": (
                    {
                        "controlId": spec.native_control.control_id,
                        "sourceTable": spec.native_control.source_table,
                        "sourceField": spec.native_control.source_field,
                        "extraction": spec.native_control.extraction,
                        "sourceIri": spec.native_control.source_iri,
                        "constructionKey": spec.native_control.construction_key,
                    }
                    if spec.native_control is not None
                    else None
                ),
                "checkedPacks": list(atlas.checked_packs if atlas else fallback_packs),
                "checkedPackTransports": [
                    {
                        "path": path,
                        "sha256": digest,
                        "byteLength": byte_length,
                        "manifestSha256": ctx.pack_pins[path].sha256
                        if path in ctx.pack_pins
                        else None,
                        "manifestByteLength": ctx.pack_pins[path].byte_length
                        if path in ctx.pack_pins
                        else None,
                    }
                    for path, (digest, byte_length) in (
                        atlas.checked_pack_transports.items() if atlas else ()
                    )
                ],
            }
        )
    return {
        "type": "AtlasSourceFidelityReceipt",
        "verifier": VERIFIER_VERSION,
        "passed": all(result.passed for result in results),
        "manifestDigest": ctx.manifest_digest,
        "constructionSummaryDigest": ctx.construction_summary_digest,
        "expectations": {
            "minimumLabelSample": max(1, ctx.expectations.minimum_label_sample),
            "requestedMinimumLabelSample": ctx.expectations.minimum_label_sample,
            "requireCompleteCoverage": ctx.expectations.require_complete_coverage,
            "requireInputPins": ctx.expectations.require_input_pins,
            "requirePackPins": ctx.expectations.require_pack_pins,
            "requiredSources": list(ctx.expectations.required_sources),
        },
        "scope": {
            "evaluatedComparisons": sorted(spec.name for spec in ctx.specs),
            "scopedOutComparisons": sorted(
                spec.name for spec in ctx.scoped_out_specs
            ),
            "scopedOutUnits": sorted(scoped_out_keys),
            "complete": not ctx.scoped_out_specs,
        },
        "coverage": {
            "constructionUnitCount": len(ctx.units),
            "coveredUnitCount": len(compared_keys),
            "adapterLoadedUnitCount": len(compared_keys),
            "notEvaluatedScopedOutUnitCount": len(scoped_out_keys),
            "exactUnitCount": sum(
                status == "exact" for status in fidelity_by_key.values()
            ),
            "coveredUnits": sorted(compared_keys),
            "uncoveredUnits": sorted(
                set(units_by_key) - compared_keys - scoped_out_keys
            ),
            "constructionUnits": [
                {
                    "key": unit.key,
                    "kind": unit.kind,
                    "status": (
                        fidelity_by_key[unit.key]
                        if unit.key in compared_keys
                        else "loadFailed"
                        if unit.key in declared_keys
                        else "not-evaluated-scoped-out"
                        if unit.key in scoped_out_keys
                        else "uncovered"
                    ),
                    "inputCount": len(unit.inputs),
                    "packCount": len(unit.packs),
                    "resourceCount": unit.record_counts.get("resources"),
                }
                for unit in sorted(ctx.units, key=lambda item: item.key)
            ],
        },
        "comparisons": comparison_rows,
        "executablePolicies": dict(EXECUTABLE_POLICIES),
        "receiptLimits": {
            "perCheckListLimit": RECEIPT_LIST_LIMIT,
            "cappedFields": ["results[].failures", "results[].sourceFindings"],
            "completeness": (
                "each capped field carries its own totalCount, a truncated flag, "
                "and a sha256 over the complete ordered list, so a re-run proves "
                "the omitted tail"
            ),
        },
        "results": [_capped_result(result) for result in results],
    }


def render(results: Iterable[CheckResult]) -> str:
    """Render a fixed-width report, listing failures and source findings separately."""
    rows = list(results)
    lines = ["Atlas source-fidelity verification", "=" * 78]
    for result in rows:
        status = "PASS" if result.passed else "FAIL"
        lines.append(f"{status}  {result.name:28s}  {result.summary}")
    passed = sum(1 for result in rows if result.passed)
    lines.append("-" * 78)
    lines.append(f"{passed}/{len(rows)} checks passed")

    pipeline_failures = [(result.name, detail) for result in rows for detail in result.failures]
    if pipeline_failures:
        lines.extend(["", "PIPELINE FINDINGS (differences between publisher bytes and what we assert)", "-" * 78])
        for name, detail in pipeline_failures:
            lines.append(f"  [{name}] {detail}")

    source_findings = [finding for result in rows for finding in result.source_findings if finding.kind == "source"]
    if source_findings:
        lines.extend(["", "SOURCE FINDINGS (defects in publisher data; preserved, not repaired)", "-" * 78])
        for finding in source_findings:
            lines.append(f"  [{finding.source}] {finding.detail}")

    model_findings = [finding for result in rows for finding in result.source_findings if finding.kind == "model"]
    if model_findings:
        lines.extend(["", "MODEL FINDINGS (expressible-range limits of the Atlas 3.1 binding)", "-" * 78])
        for finding in model_findings:
            lines.append(f"  [{finding.source}] {finding.detail}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--distribution", type=Path, default=None)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--minimum-label-sample", type=int, default=200)
    parser.add_argument(
        "--only",
        action="append",
        default=None,
        metavar="COMPARISON",
        help=(
            "restrict the run to the named comparison; repeatable. Construction "
            "units owned by the comparisons left out are reported as not evaluated "
            "(scoped out), never as covered or failed."
        ),
    )
    args = parser.parse_args(argv)

    if args.distribution is None:
        parser.error(
            "--distribution is required; there is no default. The old default "
            "(output/atlas-3.0-full-2026-08-07-ring-audit) was retired and would "
            "audit an artifact nobody ships. Name the distribution directory that "
            "holds atlas-manifest.json, e.g.\n"
            "  uv run python tools/verify_atlas_source_fidelity.py "
            "--distribution output/atlas-3.1-federal-register-thesaurus-2025-04-01/distribution\n"
            "or go through the Makefile target, which resolves the directory for you:\n"
            "  make audit-atlas-v3-source-fidelity "
            "ATLAS_V3_AUDIT_ROOT=output/atlas-3.1-federal-register-thesaurus-2025-04-01"
        )

    try:
        selected_specs, scoped_out_specs = select_scope(args.only or (), SOURCES)
    except ValueError as error:
        parser.error(str(error))

    ctx = build_context(
        args.distribution,
        args.source_root,
        expectations=Expectations(minimum_label_sample=args.minimum_label_sample),
        specs=selected_specs,
        scoped_out_specs=scoped_out_specs,
    )
    results = run_checks(ctx)

    if args.output is not None:
        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            payload = _receipt(ctx, results)
            args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except Exception as error:  # noqa: BLE001 - retain the complete validation report
            results.append(
                _result(
                    "receipt-write",
                    "validation completed but the evidence receipt could not be written",
                    [f"{type(error).__name__}: {error}"],
                )
            )

    print(render(results))

    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
