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
  exception is a ``source-extract`` comparison, where the publisher ships no IRIs
  at all: there the join is the source-local identity the Atlas record itself
  declares in ``atlas:nativePayload``, and the comparison says so in the receipt.
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
import csv
import gzip
import hashlib
import html
import io
import json
import logging
import re
import string
import sys
import threading
import urllib.parse
import uuid
import zipfile
from collections import Counter, defaultdict
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from itertools import chain
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

VERIFIER_VERSION = "atlas-source-fidelity/13"
ASSERTED_GRAPH = "urn:ref:atlas:graph:v3:asserted"
CONSTRUCTION_SUMMARY = "atlas-construction-summary.json"
LANGUAGE_SCOPE_EXCLUSIONS = REPOSITORY_ROOT / "language-scope-exclusions.json"
ENGLISH_LANGUAGE_SCOPE = {
    "includedLanguageFamilies": ["en"],
    "selectionRule": "bcp47-primary-language-subtag",
    "unselectedPublisherContent": "notRepresented",
    "wireLanguageTag": "en",
}

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
_BCP47 = re.compile(
    r"^(?:(?:[A-Za-z]{2,3}(?:-[A-Za-z]{3}){0,3}|[A-Za-z]{4}|"
    r"[A-Za-z]{5,8})(?:-[A-Za-z]{4})?(?:-(?:[A-Za-z]{2}|[0-9]{3}))?"
    r"(?:-(?:[A-Za-z0-9]{5,8}|[0-9][A-Za-z0-9]{3}))*"
    r"(?:-[0-9A-WY-Za-wy-z](?:-[A-Za-z0-9]{2,8})+)*"
    r"(?:-[xX](?:-[A-Za-z0-9]{1,8})+)?|"
    r"[xX](?:-[A-Za-z0-9]{1,8})+|[eE][nN]-[gG][bB]-[oO][eE][dD]|"
    r"[iI]-(?:[aA][mM][iI]|[bB][nN][nN]|[dD][eE][fF][aA][uU][lL][tT]|"
    r"[eE][nN][oO][cC][hH][iI][aA][nN]|[hH][aA][kK]|"
    r"[kK][lL][iI][nN][gG][oO][nN]|[lL][uU][xX]|"
    r"[mM][iI][nN][gG][oO]|[nN][aA][vV][aA][jJ][oO]|"
    r"[pP][wW][nN]|[tT][aA][oO]|[tT][aA][yY]|[tT][sS][uU])|"
    r"[sS][gG][nN]-(?:[bB][eE]-[fF][rR]|[bB][eE]-[nN][lL]|"
    r"[cC][hH]-[dD][eE])|[aA][rR][tT]-[lL][oO][jJ][bB][aA][nN]|"
    r"[cC][eE][lL]-[gG][aA][uU][lL][iI][sS][hH]|"
    r"[nN][oO]-(?:[bB][oO][kK]|[nN][yY][nN])|"
    r"[zZ][hH]-(?:[gG][uU][oO][yY][uU]|[hH][aA][kK][kK][aA]|"
    r"[mM][iI][nN]|[mM][iI][nN]-[nN][aA][nN]|"
    r"[xX][iI][aA][nN][gG]))$"
)


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
    language_exclusion_evidence: LanguageExclusionEvidence | None = None
    # Stock non-RDF readers derive the source-record evidence address and the
    # exact native payload independently from publisher bytes. RDF readers use
    # the source IRI and the existing field-level inverse by default.
    resource_locators: Mapping[str, str] = field(default_factory=dict)
    expected_native_payloads: Mapping[str, Mapping[str, Any]] = field(
        default_factory=dict
    )
    expected_relation_payloads: Mapping[str, Mapping[str, Any]] = field(
        default_factory=dict
    )
    # High-cardinality stock readers can retain the one exact digest directly
    # instead of allocating one frozenset per publisher resource.  The boolean
    # additionally says that this digest authenticates the entire independently
    # reconstructed native payload, not merely an input file.
    resource_input_digest_values: Mapping[str, str] = field(default_factory=dict)
    source_digest_is_native_payload_digest: bool = False


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
    compact_native_payload_records: frozenset[str]
    native_payload_digest_differences: Mapping[
        str,
        tuple[str, str | None],
    ]
    native_payload_field_differences: Mapping[
        str,
        tuple[tuple[str, ...], tuple[str, ...]],
    ]
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
class DeclaredLanguageExclusion:
    """One exact claim-level declaration of Atlas's English product scope.

    Unlike ``DeclaredClaimExclusion``, this declaration never selects a subject.
    It selects only explicitly tagged semantic literal claims whose valid BCP 47
    primary language subtag is not ``en``. The authenticated payload fixes the
    source, language, and predicate-family counts that must be observed.
    """

    name: str
    reason: str
    payload_json: str
    payload_sha256: str

    def __post_init__(self) -> None:
        observed = "sha256:" + hashlib.sha256(
            self.payload_json.encode("utf-8")
        ).hexdigest()
        if observed != self.payload_sha256:
            raise ValueError(
                f"declared language exclusion {self.name!r} payload digest differs: "
                f"expected {self.payload_sha256}, observed {observed}"
            )

    def payload(self) -> Mapping[str, Any]:
        """Return the immutable declaration payload after structural checks."""
        value = json.loads(self.payload_json)
        if not isinstance(value, dict):
            raise ValueError("language exclusion payload must be an object")
        return value


@dataclass(frozen=True)
class LanguageExclusionEvidence:
    """Measured claim cells and exact selected-claim identity for one source."""

    expected_counts_by_language: Mapping[str, Mapping[str, int]]
    actual_counts_by_language: Mapping[str, Mapping[str, int]]
    excluded_claim_count: int
    excluded_claims_digest: str
    applied: bool
    failures: tuple[str, ...] = ()


@dataclass(frozen=True)
class AtlasLanguageScopeEvidence:
    """Whole-distribution evidence that the Atlas side obeys its language scope."""

    non_english_literal_count: int = 0
    non_english_literals_digest: str = "sha256:" + hashlib.sha256(b"[]").hexdigest()
    non_english_literal_examples: tuple[str, ...] = ()
    noncanonical_semantic_literal_count: int = 0
    noncanonical_semantic_literals_digest: str = (
        "sha256:" + hashlib.sha256(b"[]").hexdigest()
    )
    noncanonical_semantic_literal_examples: tuple[str, ...] = ()
    scan_failures: tuple[str, ...] = ()


@dataclass(frozen=True)
class PatternFieldNormalizer:
    """One bounded, named normalization applied to a captured row field."""

    field: str
    operations: tuple[str, ...]


@dataclass(frozen=True)
class PatternDerivedField:
    """One value derived from row fields by a fixed reader operation."""

    field: str
    operation: str
    template_json: str
    prefix: str = ""


@dataclass(frozen=True)
class PatternRowFilter:
    """Keep or reject a row by applying one declared regular expression."""

    field: str
    pattern: str
    include: bool = True


@dataclass(frozen=True)
class PatternRowPattern:
    """Select rows from an exact set of authenticated UTF-8 inputs."""

    input_pattern: str
    region_pattern: str
    row_pattern: str
    expected_input_count: int
    expected_region_count: int
    expected_row_count: int
    constants: tuple[tuple[str, Any], ...] = ()
    normalizers: tuple[PatternFieldNormalizer, ...] = ()
    row_filters: tuple[PatternRowFilter, ...] = ()


@dataclass(frozen=True)
class PatternRowSelector:
    """Declarative row, identity, locator, claim, count, and residue rules."""

    patterns: tuple[PatternRowPattern, ...]
    row_key: str
    identity_mode: str
    identity_template: str
    source_locator_template: str
    claim_map: tuple[tuple[str, str], ...]
    native_payload_template_json: str
    native_payload_fields: tuple[str, ...]
    expected_count: int
    declared_unevaluated_fields: tuple[str, ...]
    derived_fields: tuple[PatternDerivedField, ...] = ()


@dataclass(frozen=True)
class SourceSpec:
    """One source vocabulary the verifier knows how to compare end to end."""

    name: str
    kind: str  # "vocabulary", "mapping", "native-control", or "source-extract"
    release_keys: tuple[str, ...]
    inputs: tuple[SourcePin, ...]
    policies: frozenset[str] = frozenset()
    subset: str = "all"
    included_concept_iris: frozenset[str] = frozenset()
    excluded_resource_predicates: frozenset[str] = frozenset()
    declared_claim_exclusions: tuple[DeclaredClaimExclusion, ...] = ()
    declared_language_exclusion: DeclaredLanguageExclusion | None = None
    native_control: NativeControlSelector | None = None
    rdf_source: RdfSourcePolicy | None = None
    source_extract: SourceExtractSelector | None = None
    pattern_row: PatternRowSelector | None = None
    reader: str = "rdf"
    identity_policy: str = "publisher-iri"

    def has_policy(self, name: str) -> bool:
        return name in self.policies


_ENGLISH_LANGUAGE_EXCLUSION_PAYLOAD = LANGUAGE_SCOPE_EXCLUSIONS.read_text(
    encoding="utf-8"
)
_ENGLISH_LANGUAGE_EXCLUSION = DeclaredLanguageExclusion(
    name="nonEnglishPublisherLiteralClaims",
    reason=(
        "Atlas carries the BCP 47 English language family; explicitly tagged "
        "publisher literals outside that family are deliberately not represented"
    ),
    payload_json=_ENGLISH_LANGUAGE_EXCLUSION_PAYLOAD,
    payload_sha256=(
        "sha256:8c7ffd458cef9b182d86b1b3e9626cc0d38d5db6eb0d8ba1ef59e63e024082bb"
    ),
)
_ENGLISH_LANGUAGE_EXCLUSION_SOURCE_NAMES = frozenset(
    _ENGLISH_LANGUAGE_EXCLUSION.payload().get("countsBySourceAndLanguage", {})
)


def _language_exclusion_for_spec(
    spec: SourceSpec,
) -> DeclaredLanguageExclusion | None:
    """Resolve an explicit test declaration or the registry-wide owner decision."""
    if spec.declared_language_exclusion is not None:
        return spec.declared_language_exclusion
    if spec.name in _ENGLISH_LANGUAGE_EXCLUSION_SOURCE_NAMES:
        return _ENGLISH_LANGUAGE_EXCLUSION
    return None


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
    construction_language_scope: Any
    manifest_digest: str | None
    pack_pins: Mapping[str, PackPin]
    verified_pins: frozenset[SourcePin]
    pin_failures: tuple[str, ...]
    load_failures: tuple[str, ...]
    atlas_language_scope_evidence: AtlasLanguageScopeEvidence = field(
        default_factory=AtlasLanguageScopeEvidence
    )
    source_extract_pairs: tuple[SourceExtractPair, ...] = ()
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
    """Read every independently pinned input with the spec's stock parser."""
    payloads = {
        pin: read_verified_file_pin(
            _resolve_source_pin(source_root, pin),
            expected_sha256=pin.sha256,
            expected_byte_length=pin.byte_length,
            logical_path=pin.path,
        )
        for pin in spec.inputs
    }
    if spec.reader != "rdf":
        reader = _PUBLISHER_READERS.get(spec.reader)
        if reader is None:
            raise ValueError(f"unsupported publisher reader {spec.reader!r}")
        return reader(spec, payloads)
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
        resource_locators={
            resource: locator
            for resource, locator in view.resource_locators.items()
            if resource in resources
        },
        expected_native_payloads={
            resource: payload
            for resource, payload in view.expected_native_payloads.items()
            if resource in resources
        },
        expected_relation_payloads=view.expected_relation_payloads,
        resource_input_digest_values={
            resource: digest
            for resource, digest in view.resource_input_digest_values.items()
            if resource in resources
        },
        source_digest_is_native_payload_digest=(
            view.source_digest_is_native_payload_digest
        ),
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
        resource_locators={
            resource: locator
            for resource, locator in view.resource_locators.items()
            if resource in resources
        },
        expected_native_payloads={
            resource: payload
            for resource, payload in view.expected_native_payloads.items()
            if resource in resources
        },
        expected_relation_payloads=view.expected_relation_payloads,
        resource_input_digest_values={
            resource: digest
            for resource, digest in view.resource_input_digest_values.items()
            if resource in resources
        },
        source_digest_is_native_payload_digest=(
            view.source_digest_is_native_payload_digest
        ),
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


API_CAPTURE_JSON_READER = "api-capture-json-v1/1.0"
PATTERN_ROW_READER = "pattern-row-v2/2.0"


@dataclass(frozen=True)
class _ApiCaptureRecord:
    """One source row reconstructed with only stock JSON/XML operations."""

    resource: str
    preferred_label: str
    notations: tuple[str, ...]
    source_locator: str
    source_digest: str
    native_payload: Mapping[str, Any]
    is_skos_concept: bool = False
    alternate_labels: tuple[str, ...] = ()
    definition: str | None = None
    relations: tuple[tuple[str, str], ...] = ()


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty text")
    return value


def _mapping_rows(value: Any, label: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(row, Mapping) for row in value):
        raise ValueError(f"{label} must be an array of objects")
    return list(value)


def _single_pin(
    spec: SourceSpec,
    payloads: Mapping[SourcePin, bytes],
) -> tuple[SourcePin, bytes]:
    if len(spec.inputs) != 1:
        raise ValueError(f"{spec.name} requires exactly one publisher input")
    pin = spec.inputs[0]
    return pin, payloads[pin]


def _pin_with_role(
    spec: SourceSpec,
    payloads: Mapping[SourcePin, bytes],
    role: str,
) -> tuple[SourcePin, bytes]:
    matches = [(pin, payloads[pin]) for pin in spec.inputs if pin.role == role]
    if len(matches) != 1:
        raise ValueError(f"{spec.name} requires exactly one {role!r} input")
    return matches[0]


def _source_uuid7(recorded_at: str, seed: Mapping[str, Any]) -> str:
    """Reconstruct the source-local UUIDv7 from its published inputs.

    This is an independent spelling of UUIDv7 bit placement. It deliberately
    does not import the registry's source-identity helper.
    """
    instant = datetime.fromisoformat(recorded_at)
    timestamp_ms = int(instant.astimezone(UTC).timestamp() * 1000)
    random_bits = int.from_bytes(hashlib.sha256(_canonical_json_bytes(seed)).digest())
    random_bits >>= 182
    random_a = random_bits >> 62
    random_b = random_bits & ((1 << 62) - 1)
    value = (
        (timestamp_ms << 80)
        | (0x7 << 76)
        | (random_a << 64)
        | (0b10 << 62)
        | random_b
    )
    return str(uuid.UUID(int=value))


def _source_concept_iri(
    *,
    token: str,
    recorded_at: str,
    source_locator: str,
    source_path: str,
    notations: Sequence[str],
    identity_hint: str,
) -> str:
    seed = {
        "source": source_locator,
        "path": source_path,
        "notations": list(notations),
        "identityHint": identity_hint,
    }
    return f"urn:ref:source-concept:v2:{token}:{_source_uuid7(recorded_at, seed)}"


def _source_observation_id(
    *,
    resource_id: str,
    source_artifact: str,
    source_path: str,
    identifiers: Sequence[Mapping[str, Any]],
    package_version: str | None = None,
) -> str:
    identity: dict[str, Any] = {
        "resourceId": resource_id,
        "sourceArtifact": source_artifact,
        "sourcePath": source_path,
        "identifiers": [
            {
                "value": item["value"],
                "kind": item["kind"],
                "authorityUri": item["authorityUri"],
            }
            for item in identifiers
        ],
    }
    if package_version is not None:
        identity = {"packageVersion": package_version, **identity}
    digest = hashlib.sha256(_canonical_json_bytes(identity)).hexdigest()
    return f"urn:ref:source-observation:{resource_id}:{digest}"


def _api_capture_view(
    records: Sequence[_ApiCaptureRecord],
    spec: SourceSpec,
    payloads: Mapping[SourcePin, bytes],
    *,
    unevaluated_claims: Sequence[str] = (),
) -> PublisherView:
    concepts: set[str] = set()
    pref_labels: dict[str, frozenset[LiteralValue]] = {}
    alt_labels: dict[str, frozenset[LiteralValue]] = {}
    notations: dict[str, frozenset[LiteralValue]] = {}
    annotations: set[tuple[str, str, LiteralValue]] = set()
    literal_claims: set[tuple[str, str, LiteralValue]] = set()
    iri_claims: set[tuple[str, str, str]] = set()
    relations: set[tuple[str, str, str]] = set()
    predicate_counts: Counter[tuple[str, str]] = Counter()
    input_digests = {
        pin.path: "sha256:" + hashlib.sha256(payload).hexdigest()
        for pin, payload in payloads.items()
    }
    resource_digests: dict[str, frozenset[str]] = {}
    locators: dict[str, str] = {}
    native_payloads: dict[str, Mapping[str, Any]] = {}
    for record in records:
        if record.resource in concepts:
            raise ValueError(f"{spec.name} repeats resource {record.resource!r}")
        concepts.add(record.resource)
        preferred = _literal_value(record.preferred_label, "en", None)
        alternates = frozenset(
            _literal_value(value, "en", None) for value in record.alternate_labels
        )
        notation_values = frozenset(
            _literal_value(value, None, None) for value in record.notations
        )
        pref_labels[record.resource] = frozenset({preferred})
        alt_labels[record.resource] = alternates
        notations[record.resource] = notation_values
        literal_claims.add((record.resource, SKOS_PREF_LABEL, preferred))
        predicate_counts[(record.resource, SKOS_PREF_LABEL)] += 1
        if record.is_skos_concept:
            iri_claims.add((record.resource, RDF_TYPE, SKOS_CONCEPT))
            predicate_counts[(record.resource, RDF_TYPE)] += 1
        for value in alternates:
            literal_claims.add((record.resource, SKOS_ALT_LABEL, value))
            predicate_counts[(record.resource, SKOS_ALT_LABEL)] += 1
        for value in notation_values:
            literal_claims.add((record.resource, SKOS_NOTATION, value))
            predicate_counts[(record.resource, SKOS_NOTATION)] += 1
        if record.definition is not None:
            value = _literal_value(record.definition, "en", None)
            annotations.add((record.resource, SKOS_DEFINITION, value))
            literal_claims.add((record.resource, SKOS_DEFINITION, value))
            predicate_counts[(record.resource, SKOS_DEFINITION)] += 1
        for predicate, target in record.relations:
            relations.add((record.resource, predicate, target))
            iri_claims.add((record.resource, predicate, target))
            predicate_counts[(record.resource, predicate)] += 1
        resource_digests[record.resource] = frozenset({record.source_digest})
        locators[record.resource] = record.source_locator
        native_payloads[record.resource] = record.native_payload
    return PublisherView(
        concepts=frozenset(concepts),
        schemes=frozenset(),
        pref_labels=pref_labels,
        alt_labels=alt_labels,
        hidden_labels={},
        notations=notations,
        annotations=frozenset(annotations),
        resource_annotations=frozenset(),
        resource_annotation_target_claim_counts={},
        literal_claims=frozenset(literal_claims),
        iri_claims=frozenset(iri_claims),
        reified_statements=frozenset(),
        pref_label_count_all_languages=len(records),
        alt_label_count_all_languages=sum(len(row.alternate_labels) for row in records),
        hidden_label_count_all_languages=0,
        relations=frozenset(relations),
        memberships=frozenset(),
        top_concept_of=frozenset(),
        has_top_concept=frozenset(),
        resource_predicate_counts=dict(predicate_counts),
        defects=(),
        resource_input_digests=resource_digests,
        input_content_digests=input_digests,
        unevaluated_claims=tuple(unevaluated_claims),
        resource_locators=locators,
        expected_native_payloads=native_payloads,
    )


def _html_fragment_text(value: str) -> str:
    """Return exact visible text from one bounded HTML fragment."""
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()


_EXACT_PATTERN_FIELD = re.compile(r"^\{([A-Za-z_][A-Za-z0-9_]*)\}$")
_PATTERN_CLAIMS = frozenset(
    {
        "alternate_label",
        "definition",
        "identity_hint",
        "notation",
        "observed_at",
        "preferred_label",
        "source_path",
    }
)


def _pattern_template_fields(template: str) -> frozenset[str]:
    """Return the named fields referenced by one bounded format template."""
    fields: set[str] = set()
    try:
        parsed = string.Formatter().parse(template)
        for _, field_name, _, _ in parsed:
            if field_name is None:
                continue
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", field_name):
                raise ValueError(
                    f"pattern-row template field must be one plain name: {field_name!r}"
                )
            fields.add(field_name)
    except ValueError as error:
        raise ValueError(f"invalid pattern-row template {template!r}: {error}") from error
    return frozenset(fields)


def _render_pattern_text(template: str, fields: Mapping[str, Any]) -> str:
    """Render one text template and reject missing or non-scalar values."""
    try:
        value = template.format_map(fields)
    except (KeyError, ValueError) as error:
        raise ValueError(f"could not render pattern-row template {template!r}: {error}") from error
    if not isinstance(value, str):  # pragma: no cover - str.format_map promises text
        raise ValueError(f"pattern-row template did not render text: {template!r}")
    return value


def _render_pattern_value(value: Any, fields: Mapping[str, Any]) -> Any:
    """Render a JSON-shaped value while preserving whole-field JSON types."""
    if isinstance(value, str):
        exact = _EXACT_PATTERN_FIELD.fullmatch(value)
        if exact is not None:
            field_name = exact.group(1)
            if field_name not in fields:
                raise ValueError(f"pattern-row template names unknown field {field_name!r}")
            return fields[field_name]
        return _render_pattern_text(value, fields)
    if isinstance(value, list):
        return [_render_pattern_value(item, fields) for item in value]
    if isinstance(value, Mapping):
        return {
            str(key): _render_pattern_value(child, fields)
            for key, child in value.items()
        }
    return value


def _pattern_json_template_fields(template_json: str, label: str) -> frozenset[str]:
    """Parse a JSON template and return every referenced row field."""
    try:
        value = _json_without_duplicate_keys(template_json.encode("utf-8"), label)
    except (UnicodeError, ValueError) as error:
        raise ValueError(f"{label} is not valid JSON: {error}") from error
    fields: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, str):
            fields.update(_pattern_template_fields(item))
        elif isinstance(item, list):
            for child in item:
                visit(child)
        elif isinstance(item, Mapping):
            for child in item.values():
                visit(child)

    visit(value)
    return frozenset(fields)


def _normalize_pattern_field(value: Any, operation: str, label: str) -> Any:
    """Apply one stock, source-independent field normalization."""
    if operation == "none-if-empty":
        if value is None or (isinstance(value, str) and not value):
            return None
        return value
    if not isinstance(value, str):
        raise ValueError(
            f"{label} normalization {operation!r} requires text, observed "
            f"{type(value).__name__}"
        )
    if operation == "strip":
        return value.strip()
    if operation == "rstrip":
        return value.rstrip()
    if operation == "collapse-whitespace":
        return " ".join(value.split())
    if operation == "html-visible-text":
        return _html_fragment_text(value)
    if operation == "html-unescape":
        return html.unescape(value)
    if operation == "markdown-bold":
        match = re.fullmatch(r"\*\*(.+)\*\*", value.strip())
        if match is None:
            raise ValueError(f"{label} is not one bold Markdown value: {value!r}")
        return match.group(1).strip()
    if operation == "casefold":
        return value.casefold()
    if operation == "integer":
        try:
            return int(value)
        except ValueError as error:
            raise ValueError(f"{label} is not an integer: {value!r}") from error
    raise ValueError(f"{label} declares unsupported normalization {operation!r}")


def _pattern_claims(
    selector: PatternRowSelector,
    fields: Mapping[str, Any],
) -> Mapping[str, tuple[str, ...]]:
    """Render the declared claim map without accepting hidden claim kinds."""
    claims: dict[str, list[str]] = defaultdict(list)
    for claim, template in selector.claim_map:
        if claim not in _PATTERN_CLAIMS:
            raise ValueError(f"pattern-row claim map names unsupported claim {claim!r}")
        value = _render_pattern_text(template, fields)
        claims[claim].append(value)
    return {claim: tuple(values) for claim, values in claims.items()}


def _read_pattern_rows(
    spec: SourceSpec,
    payloads: Mapping[SourcePin, bytes],
) -> PublisherView:
    """Read declared UTF-8 row patterns without source-name dispatch."""
    selector = spec.pattern_row
    if selector is None:
        raise ValueError(f"{spec.name} has no pattern-row selector")
    if not selector.patterns:
        raise ValueError(f"{spec.name} pattern-row selector declares no input patterns")
    if selector.identity_mode not in {"publisher-iri", "source-local-record"}:
        raise ValueError(
            f"{spec.name} pattern-row identity mode is unsupported: "
            f"{selector.identity_mode!r}"
        )
    claim_names = [claim for claim, _ in selector.claim_map]
    required_claims = {"preferred_label", "source_path"}
    missing_claims = required_claims - set(claim_names)
    if selector.identity_mode == "source-local-record":
        missing_claims |= {"observed_at"} - set(claim_names)
    if missing_claims:
        raise ValueError(
            f"{spec.name} pattern-row claim map omits {sorted(missing_claims)}"
        )
    if claim_names.count("preferred_label") != 1:
        raise ValueError(f"{spec.name} pattern-row requires one preferred_label claim")
    if claim_names.count("source_path") != 1:
        raise ValueError(f"{spec.name} pattern-row requires one source_path claim")

    try:
        payload_template = _json_without_duplicate_keys(
            selector.native_payload_template_json.encode("utf-8"),
            f"{spec.name} native payload template",
        )
    except (UnicodeError, ValueError) as error:
        raise ValueError(f"{spec.name} native payload template is invalid: {error}") from error
    if not isinstance(payload_template, Mapping):
        raise ValueError(f"{spec.name} native payload template must be an object")
    if set(payload_template) != set(selector.native_payload_fields):
        raise ValueError(
            f"{spec.name} native payload field declaration differs from its template -- "
            f"declared {sorted(selector.native_payload_fields)}, observed "
            f"{sorted(payload_template)}"
        )

    declared_template_fields: set[str] = set()
    for template in (
        selector.row_key,
        selector.identity_template,
        selector.source_locator_template,
        *(template for _, template in selector.claim_map),
    ):
        declared_template_fields.update(_pattern_template_fields(template))
    declared_template_fields.update(
        _pattern_json_template_fields(
            selector.native_payload_template_json,
            f"{spec.name} native payload template",
        )
    )
    for derived in selector.derived_fields:
        declared_template_fields.update(
            _pattern_json_template_fields(
                derived.template_json,
                f"{spec.name} derived field {derived.field!r}",
            )
        )

    records: list[_ApiCaptureRecord] = []
    seen_keys: set[str] = set()
    for pattern_index, declaration in enumerate(selector.patterns):
        try:
            input_pattern = re.compile(declaration.input_pattern)
            region_pattern = re.compile(
                declaration.region_pattern,
                re.DOTALL | re.MULTILINE,
            )
            row_pattern = re.compile(
                declaration.row_pattern,
                re.DOTALL | re.MULTILINE,
            )
            compiled_filters = tuple(
                (row_filter, re.compile(row_filter.pattern))
                for row_filter in declaration.row_filters
            )
        except re.error as error:
            raise ValueError(
                f"{spec.name} pattern {pattern_index} has invalid regular expression: {error}"
            ) from error
        if "region" not in region_pattern.groupindex:
            raise ValueError(
                f"{spec.name} pattern {pattern_index} region must define a 'region' group"
            )
        selected_inputs = [
            (pin, match)
            for pin in spec.inputs
            if (match := input_pattern.fullmatch(pin.path)) is not None
        ]
        if len(selected_inputs) != declaration.expected_input_count:
            raise ValueError(
                f"{spec.name} pattern {pattern_index} expected "
                f"{declaration.expected_input_count} inputs, found {len(selected_inputs)}"
            )
        pattern_row_count = 0
        for pin, input_match in selected_inputs:
            if pin.source_iri is None:
                raise ValueError(f"{spec.name} publisher input has no source IRI")
            try:
                text = payloads[pin].decode("utf-8")
            except UnicodeDecodeError as error:
                raise ValueError(f"{spec.name} input {pin.path!r} is not UTF-8") from error
            regions = list(region_pattern.finditer(text))
            if len(regions) != declaration.expected_region_count:
                raise ValueError(
                    f"{spec.name} pattern {pattern_index} input {pin.path!r} expected "
                    f"{declaration.expected_region_count} regions, found {len(regions)}"
                )
            for region_ordinal, region in enumerate(regions):
                row_matches = list(row_pattern.finditer(region.group("region")))
                for match in row_matches:
                    constants = dict(declaration.constants)
                    if len(constants) != len(declaration.constants):
                        raise ValueError(
                            f"{spec.name} pattern {pattern_index} repeats a constant name"
                        )
                    fields: dict[str, Any] = {
                        "input_path": pin.path,
                        "input_role": pin.role or "",
                        "source_iri": pin.source_iri,
                        "source_digest": pin.sha256,
                        "input_ordinal": spec.inputs.index(pin),
                        "region_ordinal": region_ordinal,
                        "pattern_ordinal": pattern_row_count,
                        "ordinal": len(records),
                        **constants,
                    }
                    captured_sets = (
                        input_match.groupdict(),
                        {
                            key: value
                            for key, value in region.groupdict().items()
                            if key != "region"
                        },
                        match.groupdict(),
                    )
                    captured_names: set[str] = set()
                    for captured in captured_sets:
                        overlaps = set(fields) & set(captured)
                        if overlaps:
                            raise ValueError(
                                f"{spec.name} pattern {pattern_index} captures duplicate fields "
                                f"{sorted(overlaps)}"
                            )
                        fields.update(captured)
                        captured_names.update(captured)
                    for normalizer in declaration.normalizers:
                        if normalizer.field not in fields:
                            raise ValueError(
                                f"{spec.name} normalizes unknown field {normalizer.field!r}"
                            )
                        for operation in normalizer.operations:
                            fields[normalizer.field] = _normalize_pattern_field(
                                fields[normalizer.field],
                                operation,
                                f"{spec.name} field {normalizer.field!r}",
                            )
                    keep = True
                    for row_filter, compiled_filter in compiled_filters:
                        value = fields.get(row_filter.field)
                        matched = isinstance(value, str) and (
                            compiled_filter.fullmatch(value) is not None
                        )
                        if matched != row_filter.include:
                            keep = False
                    if not keep:
                        continue
                    for derived in selector.derived_fields:
                        if derived.field in fields:
                            raise ValueError(
                                f"{spec.name} derived field repeats {derived.field!r}"
                            )
                        template = _json_without_duplicate_keys(
                            derived.template_json.encode("utf-8"),
                            f"{spec.name} derived field {derived.field!r}",
                        )
                        rendered = _render_pattern_value(template, fields)
                        if derived.operation == "canonical-json-sha256":
                            fields[derived.field] = derived.prefix + hashlib.sha256(
                                _canonical_json_bytes(rendered)
                            ).hexdigest()
                        elif derived.operation == "template":
                            if not isinstance(rendered, str):
                                raise ValueError(
                                    f"{spec.name} template-derived field "
                                    f"{derived.field!r} is not text"
                                )
                            fields[derived.field] = derived.prefix + rendered
                        else:
                            raise ValueError(
                                f"{spec.name} derived field {derived.field!r} uses "
                                f"unsupported operation {derived.operation!r}"
                            )
                    used_fields = {
                        *declared_template_fields,
                        *(row_filter.field for row_filter in declaration.row_filters),
                    }
                    unaccounted = captured_names - used_fields - set(
                        selector.declared_unevaluated_fields
                    )
                    if unaccounted:
                        raise ValueError(
                            f"{spec.name} pattern {pattern_index} captures fields without a "
                            f"claim or explicit residue declaration: {sorted(unaccounted)}"
                        )

                    key = _render_pattern_text(selector.row_key, fields)
                    if not key:
                        raise ValueError(f"{spec.name} pattern-row key is empty")
                    if key in seen_keys:
                        raise ValueError(f"{spec.name} repeats publisher row key {key!r}")
                    seen_keys.add(key)
                    claims = _pattern_claims(selector, fields)
                    label = claims["preferred_label"][0]
                    if not label:
                        raise ValueError(f"{spec.name} row {key!r} has an empty label")
                    source_path = claims["source_path"][0]
                    source_locator = _render_pattern_text(
                        selector.source_locator_template,
                        fields,
                    )
                    notations = tuple(
                        dict.fromkeys(
                            value for value in claims.get("notation", ()) if value
                        )
                    )
                    if selector.identity_mode == "source-local-record":
                        observed_at = claims["observed_at"][0]
                        identity_hint = claims.get("identity_hint", (label,))[0]
                        seed = {
                            "source": source_locator,
                            "path": source_path,
                            "notations": list(notations),
                            "identityHint": identity_hint,
                        }
                        identity_fields = {
                            **fields,
                            "source_uuid7": _source_uuid7(observed_at, seed),
                        }
                        resource = _render_pattern_text(
                            selector.identity_template,
                            identity_fields,
                        )
                    else:
                        resource = _render_pattern_text(
                            selector.identity_template,
                            fields,
                        )
                    native_payload = _render_pattern_value(payload_template, fields)
                    if not isinstance(native_payload, Mapping):
                        raise ValueError(
                            f"{spec.name} row {key!r} native payload is not an object"
                        )
                    definitions = claims.get("definition", ())
                    if len(definitions) > 1:
                        raise ValueError(
                            f"{spec.name} row {key!r} declares multiple definitions"
                        )
                    records.append(
                        _ApiCaptureRecord(
                            resource=resource,
                            preferred_label=label,
                            alternate_labels=claims.get("alternate_label", ()),
                            notations=notations,
                            source_locator=source_locator,
                            source_digest=(
                                "sha256:"
                                + hashlib.sha256(
                                    _canonical_json_bytes(native_payload)
                                ).hexdigest()
                            ),
                            native_payload=native_payload,
                            definition=(
                                definitions[0]
                                if definitions and definitions[0]
                                else None
                            ),
                        )
                    )
                    pattern_row_count += 1
        if pattern_row_count != declaration.expected_row_count:
            raise ValueError(
                f"{spec.name} pattern {pattern_index} expected "
                f"{declaration.expected_row_count} rows, found {pattern_row_count}"
            )
    if len(records) != selector.expected_count:
        raise ValueError(
            f"{spec.name} expected {selector.expected_count} total pattern rows, "
            f"found {len(records)}"
        )
    unevaluated_claims = tuple(
        f"authenticated publisher field or region is explicitly unevaluated: {field_name}"
        for field_name in selector.declared_unevaluated_fields
    )
    return _api_capture_view(
        records,
        spec,
        payloads,
        unevaluated_claims=unevaluated_claims,
    )


def _code_identifier(
    *,
    value: str,
    kind: str,
    authority: str,
    pin: SourcePin,
    observed_at: str,
) -> dict[str, Any]:
    return {
        "value": value,
        "kind": kind,
        "authority_uri": authority,
        "source_uri": pin.source_iri,
        "observed_at": observed_at,
        "effective_at": None,
        "source_digest": pin.sha256,
    }


def _read_lda_capture(
    spec: SourceSpec,
    payloads: Mapping[SourcePin, bytes],
) -> PublisherView:
    pin, payload = _single_pin(spec, payloads)
    data = _json_without_duplicate_keys(payload, spec.name)
    rows = _mapping_rows(data, spec.name)
    if spec.name == "lda-general-issue-codes":
        token, resource_name = "lda-general-issues", "generalIssueCodes"
        identifier_kind, use = "generalIssueCode", "sourceAssignedEvidence"
    else:
        token, resource_name = "lda-filing-types", "filingTypes"
        identifier_kind, use = "filingTypeCode", "deterministicMetadata"
    recorded_at = "2026-07-30T12:45:14Z"
    records: list[_ApiCaptureRecord] = []
    for ordinal, row in enumerate(rows):
        if set(row) != {"value", "name"}:
            raise ValueError(f"{spec.name}[{ordinal}] has an unexpected field set")
        code = _required_text(row["value"], f"{spec.name}[{ordinal}].value")
        label = _required_text(row["name"], f"{spec.name}[{ordinal}].name")
        source_path = f"$.{resource_name}[{ordinal}]"
        resource = _source_concept_iri(
            token=token,
            recorded_at=recorded_at,
            source_locator=pin.source_iri or "",
            source_path=source_path,
            notations=(code,),
            identity_hint=label,
        )
        native = {
            "identifiers": [
                _code_identifier(
                    value=code,
                    kind=identifier_kind,
                    authority="https://lda.gov/",
                    pin=pin,
                    observed_at=recorded_at,
                )
            ],
            "is_general_subject_concept": False,
            "publisher_label": label,
            "resource_name": resource_name,
            "source_url": pin.source_iri,
            "use": use,
            "sourceArtifact": pin.source_iri,
        }
        records.append(
            _ApiCaptureRecord(
                resource=resource,
                preferred_label=label,
                notations=(code,),
                source_locator=pin.source_iri or "",
                source_digest=pin.sha256,
                native_payload=native,
                is_skos_concept=(spec.name == "lda-general-issue-codes"),
            )
        )
    return _api_capture_view(records, spec, payloads)


def _read_ecfr_titles_capture(
    spec: SourceSpec,
    payloads: Mapping[SourcePin, bytes],
) -> PublisherView:
    pin, payload = _single_pin(spec, payloads)
    data = _json_without_duplicate_keys(payload, spec.name)
    if not isinstance(data, Mapping):
        raise ValueError(f"{spec.name} must be a JSON object")
    rows = _mapping_rows(data.get("titles"), f"{spec.name}.titles")
    recorded_at = "2026-08-03T19:15:00Z"
    records: list[_ApiCaptureRecord] = []
    for ordinal, row in enumerate(rows):
        number = row.get("number")
        if not isinstance(number, int) or isinstance(number, bool):
            raise ValueError(f"{spec.name}.titles[{ordinal}].number must be an integer")
        label = _required_text(row.get("name"), f"{spec.name}.titles[{ordinal}].name")
        notation = str(number)
        source_path = f"$.titles[{ordinal}]"
        resource = _source_concept_iri(
            token="ecfr-cfr-titles",
            recorded_at=recorded_at,
            source_locator=pin.source_iri or "",
            source_path=source_path,
            notations=(notation,),
            identity_hint=label,
        )
        native = {
            "title_number": number,
            "name": label,
            "latest_amended_on": row.get("latest_amended_on"),
            "latest_issue_date": row.get("latest_issue_date"),
            "up_to_date_as_of": row.get("up_to_date_as_of"),
            "reserved": row.get("reserved"),
            "identifiers": [
                _code_identifier(
                    value=notation,
                    kind="ecfrCfrTitleNumber",
                    authority="https://www.ecfr.gov/developers/documentation/api/v1",
                    pin=pin,
                    observed_at=recorded_at,
                )
            ],
            "is_general_subject_concept": False,
            "sourceArtifact": pin.source_iri,
        }
        records.append(
            _ApiCaptureRecord(
                resource=resource,
                preferred_label=label,
                notations=(notation,),
                source_locator=pin.source_iri or "",
                source_digest=pin.sha256,
                native_payload=native,
            )
        )
    return _api_capture_view(
        records,
        spec,
        payloads,
        unevaluated_claims=("eCFR response-level metadata is authenticated but not represented",),
    )


def _camel_identifier(
    *,
    value: str,
    kind: str,
    authority: str,
    pin: SourcePin,
    source_path: str,
    observed_at: str,
    source_field: str,
) -> dict[str, Any]:
    return {
        "value": value,
        "kind": kind,
        "authorityUri": authority,
        "sourceUri": pin.source_iri,
        "sourcePath": f"{source_path}.{source_field}",
        "observedAt": observed_at,
        "sourceDigest": pin.sha256,
    }


def _read_govinfo_collections_capture(
    spec: SourceSpec,
    payloads: Mapping[SourcePin, bytes],
) -> PublisherView:
    pin, payload = _single_pin(spec, payloads)
    data = _json_without_duplicate_keys(payload, spec.name)
    if not isinstance(data, Mapping):
        raise ValueError(f"{spec.name} must be a JSON object")
    rows = _mapping_rows(data.get("collections"), f"{spec.name}.collections")
    observed_at = "2026-08-03T19:15:00Z"
    records: list[_ApiCaptureRecord] = []
    for ordinal, row in enumerate(rows):
        code = _required_text(
            row.get("collectionCode"),
            f"{spec.name}.collections[{ordinal}].collectionCode",
        )
        label = _required_text(
            row.get("collectionName"),
            f"{spec.name}.collections[{ordinal}].collectionName",
        )
        source_path = f"$[{ordinal}]"
        identifiers = [
            _camel_identifier(
                value=code,
                kind="govInfoCollectionCode",
                authority="https://www.govinfo.gov/developers",
                pin=pin,
                source_path=source_path,
                observed_at=observed_at,
                source_field="collectionCode",
            )
        ]
        observation_id = _source_observation_id(
            resource_id="govinfo-collections-2026-08-03",
            source_artifact=pin.source_iri or "",
            source_path=source_path,
            identifiers=identifiers,
        )
        native = {
            "id": observation_id,
            "sourceArtifact": pin.source_iri,
            "sourcePath": source_path,
            "sourceOrdinal": ordinal,
            "labels": [{"value": label, "language": "en", "role": "preferred"}],
            "identifiers": identifiers,
            "uses": ["deterministicMetadata"],
            "conceptIdentityClaimed": False,
        }
        resource = _source_concept_iri(
            token="govinfo-collections",
            recorded_at=observed_at,
            source_locator=pin.source_iri or "",
            source_path=source_path,
            notations=(code,),
            identity_hint=observation_id,
        )
        records.append(
            _ApiCaptureRecord(
                resource=resource,
                preferred_label=label,
                notations=(code,),
                source_locator=pin.source_iri or "",
                source_digest=pin.sha256,
                native_payload=native,
            )
        )
    return _api_capture_view(
        records,
        spec,
        payloads,
        unevaluated_claims=("GovInfo collection package and granule counts are not represented",),
    )


def _read_usaspending_capture(
    spec: SourceSpec,
    payloads: Mapping[SourcePin, bytes],
) -> PublisherView:
    pin, payload = _single_pin(spec, payloads)
    data = _json_without_duplicate_keys(payload, spec.name)
    if not isinstance(data, Mapping):
        raise ValueError(f"{spec.name} must be a JSON object")
    categories = {
        "contracts": "awardTypeCode",
        "idvs": "awardTypeCode",
        "grants": "assistanceTypeCode",
        "loans": "assistanceTypeCode",
        "other_financial_assistance": "assistanceTypeCode",
        "direct_payments": "assistanceTypeCode",
    }
    if set(data) != set(categories):
        raise ValueError(f"{spec.name} has an unexpected category set")
    observed_at = "2026-08-03T19:25:21Z"
    records: list[_ApiCaptureRecord] = []
    ordinal = 0
    for category, identifier_kind in categories.items():
        rows = data[category]
        if not isinstance(rows, Mapping):
            raise ValueError(f"{spec.name}.{category} must be an object")
        for raw_code, raw_label in rows.items():
            code = _required_text(raw_code, f"{spec.name}.{category} code")
            label = _required_text(raw_label, f"{spec.name}.{category}.{code}")
            source_path = f"$.awardTypes[{ordinal}]"
            resource = _source_concept_iri(
                token="usaspending-award-types",
                recorded_at=observed_at,
                source_locator=pin.source_iri or "",
                source_path=source_path,
                notations=(code,),
                identity_hint=label,
            )
            native = {
                "category": category,
                "identifiers": [
                    _code_identifier(
                        value=code,
                        kind=identifier_kind,
                        authority="https://www.usaspending.gov/",
                        pin=pin,
                        observed_at=observed_at,
                    )
                ],
                "is_general_subject_concept": False,
                "publisher_label": label,
                "resource_name": "awardTypes",
                "source_url": pin.source_iri,
                "use": "deterministicMetadata",
                "sourceArtifact": pin.source_iri,
            }
            records.append(
                _ApiCaptureRecord(
                    resource=resource,
                    preferred_label=label,
                    notations=(code,),
                    source_locator=pin.source_iri or "",
                    source_digest=pin.sha256,
                    native_payload=native,
                )
            )
            ordinal += 1
    return _api_capture_view(records, spec, payloads)


def _equals_lines(value: Any, label: str) -> list[tuple[str, str]]:
    if value is None:
        return []
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text or null")
    result: list[tuple[str, str]] = []
    for line in value.splitlines():
        if not line.strip():
            continue
        if " = " not in line:
            raise ValueError(f"{label} has a malformed domain row {line!r}")
        code, text = line.split(" = ", 1)
        result.append((_required_text(code, label), _required_text(text, label)))
    return result


def _read_gsdm_capture(
    spec: SourceSpec,
    payloads: Mapping[SourcePin, bytes],
) -> PublisherView:
    pin, payload = _single_pin(spec, payloads)
    root = _json_without_duplicate_keys(payload, spec.name)
    if not isinstance(root, Mapping) or not isinstance(root.get("document"), Mapping):
        raise ValueError(f"{spec.name} must contain one document object")
    document = root["document"]
    raw_rows = document.get("rows")
    if not isinstance(raw_rows, list) or any(not isinstance(row, list) for row in raw_rows):
        raise ValueError(f"{spec.name}.document.rows must be an array of arrays")
    rows = list(raw_rows)
    targets = {"ActionType", "AssistanceType", "ContractAwardType"}
    records: list[_ApiCaptureRecord] = []
    seen_elements: set[str] = set()
    for row_number, row in enumerate(rows):
        # The publisher represents each dictionary row as an 18-column array.
        values = list(row)
        if len(values) != 18:
            raise ValueError(f"{spec.name}.document.rows[{row_number}] has {len(values)} columns")
        element = values[0]
        if element not in targets:
            continue
        if not isinstance(element, str) or element in seen_elements:
            raise ValueError(f"{spec.name} repeats reviewed element {element!r}")
        seen_elements.add(element)
        description_by_code = dict(
            _equals_lines(values[5], f"{spec.name}.{element}.codeDescriptions")
        )
        domain_text = values[4]
        if not isinstance(domain_text, str):
            raise ValueError(f"{spec.name}.{element}.domainValues must be text")
        group = ""
        parsed: list[tuple[str, str, str]] = []
        for line in domain_text.splitlines():
            if not line.strip():
                continue
            if line.endswith(":") and " = " not in line:
                group = line[:-1].strip().lower()
                continue
            for code, label in _equals_lines(line, f"{spec.name}.{element}.domainValues"):
                parsed.append((group, code, label))
        for domain_group, code, label in parsed:
            group_token = domain_group or "default"
            resource = (
                "urn:ref:gsdm:domain-value:"
                f"{urllib.parse.quote(element, safe='')}:"
                f"{urllib.parse.quote(group_token, safe='')}:"
                f"{urllib.parse.quote(code, safe='')}"
            )
            code_description = description_by_code.get(code)
            native = {
                "gsdmElement": element,
                "domainGroup": domain_group,
                "code": code,
                "label": label,
                "codeDescription": code_description,
            }
            records.append(
                _ApiCaptureRecord(
                    resource=resource,
                    preferred_label=label,
                    notations=(code,),
                    source_locator=pin.source_iri or "",
                    source_digest=pin.sha256,
                    native_payload=native,
                    definition=code_description,
                )
            )
    if seen_elements != targets or len(records) != 40:
        raise ValueError(
            f"{spec.name} reviewed domain selection drifted: "
            f"elements={sorted(seen_elements)}, records={len(records)}"
        )
    return _api_capture_view(
        records,
        spec,
        payloads,
        unevaluated_claims=(
            "the other 454 authenticated GSDM dictionary rows are outside this reviewed release",
        ),
    )


def _read_nasa_capture(
    spec: SourceSpec,
    payloads: Mapping[SourcePin, bytes],
) -> PublisherView:
    child_matches = [
        (pin, payload)
        for pin, payload in payloads.items()
        if (pin.source_iri or "").endswith("/8817")
    ]
    root_matches = [
        (pin, payload)
        for pin, payload in payloads.items()
        if (pin.source_iri or "").endswith("/taxonomies")
    ]
    if len(child_matches) != 1 or len(root_matches) != 1:
        raise ValueError(f"{spec.name} requires one roots capture and one 8817 capture")
    child_pin, child_payload = child_matches[0]
    _, root_payload = root_matches[0]
    child = _json_without_duplicate_keys(child_payload, f"{spec.name} children")
    roots = _json_without_duplicate_keys(root_payload, f"{spec.name} roots")
    if not isinstance(child, Mapping) or not isinstance(roots, Mapping):
        raise ValueError(f"{spec.name} inputs must be JSON objects")
    root_rows = _mapping_rows(roots.get("taxonomyRoots"), f"{spec.name}.taxonomyRoots")
    selected = [row for row in root_rows if row.get("taxonomyRootId") == 8817]
    if len(selected) != 1 or child.get("taxonomyRootId") != 8817:
        raise ValueError(f"{spec.name} does not contain the declared taxonomy root 8817")
    if child.get("taxonomyRoot") != selected[0]:
        raise ValueError(f"{spec.name} root index and children capture disagree")
    rows = _mapping_rows(child.get("children"), f"{spec.name}.children")
    observed_at = "2026-08-03T19:03:22Z"
    records: list[_ApiCaptureRecord] = []
    for ordinal, wrapper in enumerate(rows):
        content = wrapper.get("content")
        if not isinstance(content, Mapping):
            raise ValueError(f"{spec.name}.children[{ordinal}].content must be an object")
        code = _required_text(content.get("code"), f"{spec.name}.children[{ordinal}].code")
        label = _required_text(content.get("title"), f"{spec.name}.children[{ordinal}].title")
        node_id = str(content.get("taxonomyNodeId"))
        source_path = f"$.children[{ordinal}].content"
        identifiers = [
            _camel_identifier(
                value=code,
                kind="taxonomyNodeCode",
                authority="https://techport.nasa.gov/",
                pin=child_pin,
                source_path=source_path.removesuffix(".content"),
                observed_at=observed_at,
                source_field="content",
            ),
            _camel_identifier(
                value=node_id,
                kind="publisherRecordId",
                authority="https://techport.nasa.gov/",
                pin=child_pin,
                source_path=source_path.removesuffix(".content"),
                observed_at=observed_at,
                source_field="content",
            ),
        ]
        observation_id = _source_observation_id(
            resource_id="nasa-technology-taxonomy-8817-top-level-2026-08-03",
            source_artifact=child_pin.source_iri or "",
            source_path=source_path,
            identifiers=identifiers,
            package_version="nasa-technology-taxonomy-package-v1",
        )
        native = {
            "id": observation_id,
            "sourceArtifact": child_pin.source_iri,
            "sourcePath": source_path,
            "sourceOrdinal": ordinal,
            "labels": [{"value": label, "language": "en", "role": "preferred"}],
            "identifiers": identifiers,
            "uses": ["deterministicMetadata", "mappingReference"],
            "conceptIdentityClaimed": False,
        }
        resource = _source_concept_iri(
            token="nasa-techport-taxonomy",
            recorded_at=observed_at,
            source_locator=child_pin.source_iri or "",
            source_path=source_path,
            notations=(code, node_id),
            identity_hint=observation_id,
        )
        records.append(
            _ApiCaptureRecord(
                resource=resource,
                preferred_label=label,
                notations=(code, node_id),
                source_locator=child_pin.source_iri or "",
                source_digest=child_pin.sha256,
                native_payload=native,
                is_skos_concept=True,
            )
        )
    if len(records) != 17:
        raise ValueError(f"{spec.name} expected 17 top-level nodes, observed {len(records)}")
    return _api_capture_view(
        records,
        spec,
        payloads,
        unevaluated_claims=(
            "NASA root release metadata is authenticated and cross-checked but not represented per node",
        ),
    )


def _fcc_identifier(
    value: Any,
    kind: str,
    pin: SourcePin,
    source_path: str,
) -> dict[str, Any]:
    return {
        "value": str(value),
        "kind": kind,
        "authorityUri": "https://www.fcc.gov/ecfs/",
        "sourceUri": pin.source_iri,
        "sourcePath": source_path,
        "observedAt": "2026-08-03T19:20:00Z",
        "sourceDigest": pin.sha256,
    }


def _read_fcc_capture(
    spec: SourceSpec,
    payloads: Mapping[SourcePin, bytes],
) -> PublisherView:
    pin, payload = _single_pin(spec, payloads)
    data = _json_without_duplicate_keys(payload, spec.name)
    if not isinstance(data, Mapping):
        raise ValueError(f"{spec.name} must be a JSON object")
    filings = _mapping_rows(data.get("filing"), f"{spec.name}.filing")
    distinct: dict[str, tuple[str, str, int, list[dict[str, Any]]]] = {}

    def retain(
        key: str,
        label: str,
        source_path: str,
        source_ordinal: int,
        identifiers: list[dict[str, Any]],
    ) -> None:
        candidate = (label, source_path, source_ordinal, identifiers)
        prior = distinct.get(key)
        if prior is None:
            distinct[key] = candidate
        elif prior[0] != label or [item["value"] for item in prior[3]] != [
            item["value"] for item in identifiers
        ]:
            raise ValueError(f"{spec.name} carries conflicting rows for {key!r}")

    for ordinal, filing in enumerate(filings):
        if spec.name == "fcc-ecfs-filing-types":
            row = filing.get("submissiontype")
            if not isinstance(row, Mapping):
                raise ValueError(f"{spec.name}.filing[{ordinal}].submissiontype is invalid")
            code = row.get("abbreviation", row.get("type"))
            code = _required_text(code, f"{spec.name}.filing[{ordinal}] abbreviation")
            label = _required_text(row.get("description"), f"{spec.name}.filing[{ordinal}] description")
            path = f"$.filing[{ordinal}].submissiontype"
            retain(
                code,
                label,
                path,
                ordinal,
                [
                    _fcc_identifier(code, "filingTypeAbbreviation", pin, path),
                    _fcc_identifier(row.get("id"), "publisherRecordId", pin, path),
                ],
            )
        elif spec.name == "fcc-ecfs-access-statuses":
            row = filing.get("viewingstatus")
            if not isinstance(row, Mapping):
                raise ValueError(f"{spec.name}.filing[{ordinal}].viewingstatus is invalid")
            key = str(row.get("id"))
            label = _required_text(row.get("description"), f"{spec.name}.filing[{ordinal}] description")
            path = f"$.filing[{ordinal}].viewingstatus"
            retain(key, label, path, ordinal, [_fcc_identifier(key, "accessStatusId", pin, path)])
        else:
            proceedings = _mapping_rows(
                filing.get("proceedings"), f"{spec.name}.filing[{ordinal}].proceedings"
            )
            for proceeding_ordinal, row in enumerate(proceedings):
                path = f"$.filing[{ordinal}].proceedings[{proceeding_ordinal}]"
                source_ordinal = ordinal * 1000 + proceeding_ordinal
                bureau_code = _required_text(row.get("bureau_code"), f"{path}.bureau_code")
                if spec.name == "fcc-ecfs-bureaus":
                    label = _required_text(row.get("bureau_name"), f"{path}.bureau_name")
                    retain(
                        bureau_code,
                        label,
                        path,
                        source_ordinal,
                        [_fcc_identifier(bureau_code, "bureauCode", pin, path)],
                    )
                else:
                    number = _required_text(row.get("name"), f"{path}.name")
                    label = _required_text(row.get("description"), f"{path}.description")
                    retain(
                        number,
                        label,
                        path,
                        source_ordinal,
                        [
                            _fcc_identifier(number, "proceedingNumber", pin, path),
                            _fcc_identifier(row.get("id_proceeding"), "publisherRecordId", pin, path),
                            _fcc_identifier(bureau_code, "bureauCode", pin, path),
                        ],
                    )
    config = {
        "fcc-ecfs-filing-types": ("fcc-ecfs-filing-types-2026-08-03", 6),
        "fcc-ecfs-access-statuses": ("fcc-ecfs-access-statuses-2026-08-03", 1),
        "fcc-ecfs-bureaus": ("fcc-ecfs-bureaus-2026-08-03", 5),
        "fcc-ecfs-proceedings": ("fcc-ecfs-proceedings-2026-08-03", 15),
    }
    resource_id, expected_count = config[spec.name]
    if len(distinct) != expected_count:
        raise ValueError(f"{spec.name} expected {expected_count} distinct rows, observed {len(distinct)}")
    records: list[_ApiCaptureRecord] = []
    for _, (label, source_path, source_ordinal, identifiers) in distinct.items():
        observation_id = _source_observation_id(
            resource_id=resource_id,
            source_artifact=pin.source_iri or "",
            source_path=source_path,
            identifiers=identifiers,
            package_version="fcc-ecfs-controlled-list-package-v1",
        )
        native = {
            "id": observation_id,
            "sourceArtifact": pin.source_iri,
            "sourcePath": source_path,
            "sourceOrdinal": source_ordinal,
            "labels": [{"value": label, "language": "en", "role": "preferred"}],
            "identifiers": identifiers,
            "uses": ["deterministicMetadata"],
            "conceptIdentityClaimed": False,
        }
        notation_values = tuple(item["value"] for item in identifiers)
        resource = _source_concept_iri(
            token=spec.name,
            recorded_at="2026-08-03T19:20:00Z",
            source_locator=pin.source_iri or "",
            source_path=source_path,
            notations=notation_values,
            identity_hint=observation_id,
        )
        records.append(
            _ApiCaptureRecord(
                resource=resource,
                preferred_label=label,
                notations=notation_values,
                source_locator=pin.source_iri or "",
                source_digest=pin.sha256,
                native_payload=native,
            )
        )
    return _api_capture_view(
        records,
        spec,
        payloads,
        unevaluated_claims=(
            "FCC filing fields outside submissiontype, viewingstatus, and proceedings are authenticated but not represented",
        ),
    )


def _read_federal_hierarchy_capture(
    spec: SourceSpec,
    payloads: Mapping[SourcePin, bytes],
) -> PublisherView:
    parsed: list[tuple[SourcePin, int, Mapping[str, Any], str]] = []
    input_totals: list[str] = []
    for pin in spec.inputs:
        data = _json_without_duplicate_keys(payloads[pin], pin.path)
        if not isinstance(data, Mapping) or set(data) != {"totalrecords", "orglist"}:
            raise ValueError(f"{pin.path} has an unexpected Federal Hierarchy shape")
        rows = _mapping_rows(data["orglist"], f"{pin.path}.orglist")
        observed_at = (
            "2026-08-03T22:19:12Z"
            if "fhorgtype=Sub-Tier" in (pin.source_iri or "")
            else "2026-08-03T22:19:03Z"
        )
        input_totals.append(
            f"{pin.path} totalrecords={data['totalrecords']!r} (bounded page returned {len(rows)})"
        )
        parsed.extend((pin, ordinal, row, observed_at) for ordinal, row in enumerate(rows))
    resource_ids = {str(row.get("fhorgid")) for _, _, row, _ in parsed}
    records: list[_ApiCaptureRecord] = []
    for pin, ordinal, row, observed_at in parsed:
        fhorgid = str(row.get("fhorgid"))
        label = _required_text(row.get("fhorgname"), f"{pin.path}.orglist[{ordinal}].fhorgname")
        parent_id = str(row.get("fhdeptindagencyorgid"))
        parent_history = _mapping_rows(
            row.get("fhorgparenthistory"),
            f"{pin.path}.orglist[{ordinal}].fhorgparenthistory",
        )
        if not parent_history:
            raise ValueError(f"{pin.path}.orglist[{ordinal}] has no parent history")
        parent = parent_history[0]
        identifiers = [
            _code_identifier(
                value=fhorgid,
                kind="fhOrgId",
                authority="https://sam.gov/",
                pin=pin,
                observed_at=observed_at,
            ),
            _code_identifier(
                value=_required_text(row.get("agencycode"), f"{pin.path}.agencycode"),
                kind="fpdsAgencyCode",
                authority="https://www.fpds.gov/",
                pin=pin,
                observed_at=observed_at,
            ),
        ]
        old_code = row.get("oldfpdsofficecode")
        if old_code is not None:
            identifiers.append(
                _code_identifier(
                    value=_required_text(old_code, f"{pin.path}.oldfpdsofficecode"),
                    kind="oldFpdsOfficeCode",
                    authority="https://www.fpds.gov/",
                    pin=pin,
                    observed_at=observed_at,
                )
            )
        cgac_rows = row.get("cgaclist")
        if not isinstance(cgac_rows, list):
            raise ValueError(f"{pin.path}.orglist[{ordinal}].cgaclist must be an array")
        if cgac_rows:
            cgac_row = cgac_rows[0]
            if not isinstance(cgac_row, Mapping):
                raise ValueError(f"{pin.path}.orglist[{ordinal}].cgaclist[0] is invalid")
            identifiers.append(
                _code_identifier(
                    value=_required_text(cgac_row.get("cgac"), f"{pin.path}.cgac"),
                    kind="cgacCode",
                    authority="https://www.fiscal.treasury.gov/",
                    pin=pin,
                    observed_at=observed_at,
                )
            )
        full_parent_path_id = _required_text(
            parent.get("fhfullparentpathid"), f"{pin.path}.fhfullparentpathid"
        )
        identifiers.append(
            _code_identifier(
                value=full_parent_path_id,
                kind="fhFullParentPathId",
                authority="https://sam.gov/",
                pin=pin,
                observed_at=observed_at,
            )
        )
        native = {
            "fhorgid": fhorgid,
            "fhorgname": label,
            "fhorgtype": row.get("fhorgtype"),
            "status": row.get("status"),
            "identifiers": identifiers,
            "parent_fhorgid": parent_id,
            "parent_org_name": row.get("fhagencyorgname"),
            "full_parent_path_id": full_parent_path_id,
            "full_parent_path_name": parent.get("fhfullparentpathname"),
            "source_ordinal": ordinal,
        }
        relations: tuple[tuple[str, str], ...] = ()
        if parent_id != fhorgid and parent_id in resource_ids:
            relations = ((f"{ATLAS}parentEntity", f"urn:ref:federal-hierarchy-org:{parent_id}"),)
        records.append(
            _ApiCaptureRecord(
                resource=f"urn:ref:federal-hierarchy-org:{fhorgid}",
                preferred_label=label,
                notations=(),
                source_locator=pin.source_iri or "",
                source_digest=pin.sha256,
                native_payload=native,
                relations=relations,
            )
        )
    if len(records) != 20:
        raise ValueError(f"{spec.name} expected 20 organizations, observed {len(records)}")
    return _api_capture_view(
        records,
        spec,
        payloads,
        unevaluated_claims=tuple(input_totals),
    )


def _element_text(element: ElementTree.Element, path: str, label: str) -> str:
    found = element.find(path)
    return _required_text(found.text if found is not None else None, label).strip()


def _read_govinfo_package_capture(
    spec: SourceSpec,
    payloads: Mapping[SourcePin, bytes],
) -> PublisherView:
    summary_pin, summary_payload = _pin_with_role(spec, payloads, "publisherPackageSummary")
    fixity_pin, fixity_payload = _pin_with_role(spec, payloads, "publisherPackageFixity")
    raw = _json_without_duplicate_keys(summary_payload, f"{spec.name} summary")
    if not isinstance(raw, Mapping):
        raise ValueError(f"{spec.name} summary must be a JSON object")
    observed_at = "2026-08-03T19:15:00Z"
    package_id = _required_text(raw.get("packageId"), f"{spec.name}.packageId")
    summary_identifiers = [
        _code_identifier(
            value=package_id,
            kind="govInfoPackageId",
            authority="https://www.govinfo.gov/developers",
            pin=summary_pin,
            observed_at=observed_at,
        ),
        _code_identifier(
            value=_required_text(raw.get("suDocClassNumber"), f"{spec.name}.suDocClassNumber"),
            kind="suDocClassNumber",
            authority="https://www.govinfo.gov/developers",
            pin=summary_pin,
            observed_at=observed_at,
        ),
    ]
    summary = {
        "package_id": package_id,
        "collection_code": raw.get("collectionCode"),
        "collection_name": raw.get("collectionName"),
        "title_number": int(_required_text(raw.get("titleNumber"), f"{spec.name}.titleNumber")),
        "date_issued": raw.get("dateIssued"),
        "last_modified": raw.get("lastModified"),
        "doc_class": raw.get("docClass"),
        "document_type": raw.get("documentType"),
        "category": raw.get("category"),
        "sudoc_class_number": raw.get("suDocClassNumber"),
        "details_link": raw.get("detailsLink"),
        "granules_link": raw.get("granulesLink"),
        "download_links": raw.get("download"),
        "identifiers": summary_identifiers,
        "is_general_subject_concept": False,
    }
    root = ElementTree.fromstring(fixity_payload)
    namespace = root.tag.removesuffix("premis")
    xsi_type = "{http://www.w3.org/2001/XMLSchema-instance}type"
    fixity_records: list[dict[str, Any]] = []
    for obj in root.findall(f"{namespace}object"):
        if obj.get(xsi_type) != "file":
            continue
        fixity = obj.find(
            f"{namespace}objectCharacteristics/{namespace}fixity"
        )
        if fixity is None:
            continue
        object_id = _element_text(
            obj,
            f"{namespace}objectIdentifier/{namespace}objectIdentifierValue",
            "PREMIS object identifier",
        )
        algorithm = _element_text(
            fixity,
            f"{namespace}messageDigestAlgorithm",
            "PREMIS digest algorithm",
        )
        digest = _element_text(
            fixity,
            f"{namespace}messageDigest",
            "PREMIS message digest",
        ).lower()
        original_name = _element_text(obj, f"{namespace}originalName", "PREMIS original name")
        location = _element_text(
            obj,
            (
                f"{namespace}storage/{namespace}contentLocation/"
                f"{namespace}contentLocationValue"
            ),
            "PREMIS content location",
        ).rsplit(" ", 1)[-1]
        fixity_records.append(
            {
                "object_identifier_value": object_id,
                "original_name": original_name,
                "content_location_uri": location,
                "algorithm": algorithm,
                "digest": digest,
                "identifiers": [
                    _code_identifier(
                        value=digest,
                        kind="govInfoPremisSha256Fixity",
                        authority="https://www.govinfo.gov/developers",
                        pin=fixity_pin,
                        observed_at=observed_at,
                    )
                ],
                "is_general_subject_concept": False,
            }
        )
    fixity_payload_value = {
        "package_id": package_id,
        "retrieved_at": observed_at,
        "source_sha256": fixity_pin.sha256,
        "source_byte_length": fixity_pin.byte_length,
        "records": fixity_records,
    }
    native = {"summary": summary, "fixity": fixity_payload_value}
    record = _ApiCaptureRecord(
        resource=f"urn:ref:govinfo-cfr-package:{package_id}",
        preferred_label=f"{raw.get('documentType')}: {package_id}",
        notations=(),
        source_locator=_required_text(raw.get("detailsLink"), f"{spec.name}.detailsLink"),
        source_digest=summary_pin.sha256,
        native_payload=native,
    )
    return _api_capture_view(
        [record],
        spec,
        payloads,
        unevaluated_claims=(
            "GovInfo summary authorship, pagination, part range, and migration fields are authenticated but not represented",
            "PREMIS characteristics other than file SHA-256 fixity and location are authenticated but not represented",
        ),
    )


def _sam_identifier(
    *,
    value: str,
    kind: str,
    authority: str,
    pin: SourcePin,
) -> dict[str, Any]:
    return {
        "value": value,
        "kind": kind,
        "authorityUri": authority,
        "sourceUri": pin.source_iri,
        "observedAt": "2026-08-03T22:19:50Z",
        "effectiveAt": None,
        "sourceDigest": pin.sha256,
    }


def _read_sam_capture(
    spec: SourceSpec,
    payloads: Mapping[SourcePin, bytes],
) -> PublisherView:
    pin, payload = _single_pin(spec, payloads)
    data = _json_without_duplicate_keys(payload, spec.name)
    if not isinstance(data, Mapping):
        raise ValueError(f"{spec.name} must be a JSON object")
    rows = _mapping_rows(data.get("entityData"), f"{spec.name}.entityData")
    if len(rows) != 1 or not isinstance(rows[0].get("entityRegistration"), Mapping):
        raise ValueError(f"{spec.name} requires one public entity registration")
    registration = rows[0]["entityRegistration"]
    uei = _required_text(registration.get("ueiSAM"), f"{spec.name}.ueiSAM")
    cage = _required_text(registration.get("cageCode"), f"{spec.name}.cageCode")
    label = _required_text(
        registration.get("legalBusinessName"), f"{spec.name}.legalBusinessName"
    )
    if spec.name.startswith("sam-uei-"):
        resource = f"urn:ref:sam-entity:uei:{uei}"
        native = {
            "identifier": _sam_identifier(
                value=uei,
                kind="samUniqueEntityId",
                authority="https://sam.gov/entity-registration",
                pin=pin,
            ),
            "legalBusinessName": label,
            "registrationStatus": str(registration.get("registrationStatus")).lower(),
            "immediateParentUei": None,
            "highestLevelOwnerUei": None,
            "accessClassification": "public",
        }
        relations: tuple[tuple[str, str], ...] = ()
    else:
        resource = f"urn:ref:dla-cage-facility:{cage}"
        native = {
            "identifier": _sam_identifier(
                value=cage,
                kind="dlaCageCode",
                authority=(
                    "https://www.dla.mil/Working-With-DLA/Applications/Details/"
                    "Article/2920893/cage-code-commercial-and-government-entity-code/"
                ),
                pin=pin,
            ),
            "facilityName": label,
            "cageStatus": "notObserved",
            "associatedUei": uei,
            "accessClassification": "public",
        }
        relations = ((f"{ATLAS}relatedEntity", f"urn:ref:sam-entity:uei:{uei}"),)
    record = _ApiCaptureRecord(
        resource=resource,
        preferred_label=label,
        notations=(),
        source_locator=pin.source_iri or "",
        source_digest=pin.sha256,
        native_payload=native,
        relations=relations,
    )
    return _api_capture_view(
        [record],
        spec,
        payloads,
        unevaluated_claims=(
            "SAM registration lifecycle and API paging fields are authenticated but outside this bounded identity record",
        ),
    )


def _read_api_capture(
    spec: SourceSpec,
    payloads: Mapping[SourcePin, bytes],
) -> PublisherView:
    readers: Mapping[
        str,
        Callable[[SourceSpec, Mapping[SourcePin, bytes]], PublisherView],
    ] = {
        "lda-general-issue-codes": _read_lda_capture,
        "lda-filing-types": _read_lda_capture,
        "ecfr-cfr-titles": _read_ecfr_titles_capture,
        "govinfo-collections": _read_govinfo_collections_capture,
        "usaspending-award-types": _read_usaspending_capture,
        "gsdm-reviewed-domain-values-2026-08-03": _read_gsdm_capture,
        "nasa-technology-taxonomy-8817": _read_nasa_capture,
        "fcc-ecfs-filing-types": _read_fcc_capture,
        "fcc-ecfs-access-statuses": _read_fcc_capture,
        "fcc-ecfs-bureaus": _read_fcc_capture,
        "fcc-ecfs-proceedings": _read_fcc_capture,
        "federal-hierarchy-orgs-bounded-2026-08-03": (
            _read_federal_hierarchy_capture
        ),
        "govinfo-cfr-package-bounded-2026-08-03": _read_govinfo_package_capture,
        "sam-uei-bounded-public-entity-2026-08-03": _read_sam_capture,
        "sam-cage-bounded-public-facility-2026-08-03": _read_sam_capture,
    }
    reader = readers.get(spec.name)
    if reader is None:
        raise ValueError(f"{API_CAPTURE_JSON_READER} does not support {spec.name!r}")
    return reader(spec, payloads)


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
    *,
    compact_normalized_claims: bool = False,
    compact_native_payload_fields: frozenset[str] | None = None,
    compact_native_payload_atlas_only_fields: frozenset[str] = frozenset(),
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
    pending_native_payload_digests: dict[str, str] = {}
    compact_native_payload_records: set[str] = set()
    native_payload_digest_differences: dict[
        str,
        tuple[str, str | None],
    ] = {}
    native_payload_field_differences: dict[
        str,
        tuple[tuple[str, ...], tuple[str, ...]],
    ] = {}
    checked_pack_transports: dict[str, tuple[str, int]] = {}
    record_targets: dict[str, str] = {}
    record_source_digests: dict[str, str] = {}
    structural_failures: list[str] = []
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
    compact_globally_parsed_predicates = frozenset(
        {
            RDF_TYPE,
            RDF_SUBJECT,
            RDF_PREDICATE,
            RDF_OBJECT,
            ATLAS_SOURCE_LOCATOR,
            ATLAS_SOURCE_DIGEST,
            ATLAS_REPRESENTS_RESOURCE,
            ATLAS_NATIVE_PAYLOAD,
        }
    )
    compact_source_parsed_predicates = frozenset(
        {
            SKOS_IN_SCHEME,
            SKOSXL_PREF_LABEL,
            SKOSXL_ALT_LABEL,
            SKOSXL_HIDDEN_LABEL,
            ATLAS_IN_SCHEME,
            ATLAS_RESOURCE_PROFILE,
            ATLAS_SEMANTIC_RING,
            ATLAS_NOTATION,
            ATLAS_DEFINITION,
            ATLAS_NOTE,
            *ATLAS_SOURCE_REPRESENTATION_STRUCTURE_PREDICATES,
        }
    )

    def retain_raw_claim(quad: Quad) -> bool:
        """Keep only claims not already retained in a parsed Atlas index."""
        if not compact_normalized_claims:
            return True
        if quad.predicate in compact_globally_parsed_predicates:
            return False
        if quad.predicate == SKOSXL_LITERAL_FORM:
            # Orphan forms are restored after every label edge is known.
            return False
        return not (
            quad.subject in source_claim_subjects
            and quad.predicate in compact_source_parsed_predicates
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
                retain_raw = retain_raw_claim(quad)
                if retain_raw and quad.is_literal:
                    all_raw_literal_claims.add(literal_claim)
                elif retain_raw:
                    all_raw_iri_claims.add(iri_claim)
                retain_source_raw = retain_raw or (
                    compact_normalized_claims
                    and quad.subject in source_claim_subjects
                    and quad.predicate == RDF_TYPE
                )
                if retain_source_raw and quad.subject in source_claim_subjects:
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
                    pending_payload_digest = pending_native_payload_digests.pop(
                        quad.subject,
                        None,
                    )
                    if pending_payload_digest is not None:
                        compact_native_payload_records.add(quad.subject)
                        if pending_payload_digest != quad.obj:
                            native_payload_digest_differences[quad.subject] = (
                                pending_payload_digest,
                                quad.obj,
                            )
                elif predicate == ATLAS_REPRESENTS_RESOURCE:
                    if quad.subject in record_targets and record_targets[quad.subject] != quad.obj:
                        structural_failures.append(
                            f"{pack}: source record <{quad.subject}> represents more than one resource"
                        )
                    record_targets[quad.subject] = quad.obj
                elif predicate == ATLAS_NATIVE_PAYLOAD:
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
                    if compact_native_payload_fields is not None:
                        payload_digest = _canonical_json_digest(payload)
                        prior_digest = pending_native_payload_digests.get(
                            quad.subject
                        )
                        if prior_digest is not None and prior_digest != payload_digest:
                            structural_failures.append(
                                f"{pack}: source record <{quad.subject}> has contradictory "
                                "atlas:nativePayload values"
                            )
                        source_digest = record_source_digests.get(quad.subject)
                        if source_digest is None:
                            pending_native_payload_digests[quad.subject] = (
                                payload_digest
                            )
                        else:
                            compact_native_payload_records.add(quad.subject)
                            if source_digest != payload_digest:
                                native_payload_digest_differences[quad.subject] = (
                                    payload_digest,
                                    source_digest,
                                )
                        unexpected_fields = tuple(
                            sorted(
                                set(payload)
                                - compact_native_payload_fields
                                - compact_native_payload_atlas_only_fields
                            )
                        )
                        missing_fields = tuple(
                            sorted(compact_native_payload_fields - set(payload))
                        )
                        if unexpected_fields or missing_fields:
                            native_payload_field_differences[quad.subject] = (
                                unexpected_fields,
                                missing_fields,
                            )
                        continue
                    prior_payload = native_payloads.get(quad.subject)
                    if prior_payload is not None and prior_payload != payload:
                        structural_failures.append(
                            f"{pack}: source record <{quad.subject}> has contradictory "
                            "atlas:nativePayload values"
                        )
                    else:
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
                            relation = _payload_relation(publisher_relation)
                            editorial_transformation = payload.get(
                                "editorialTransformation"
                            )
                            publisher_relation_digest = payload.get(
                                "publisherRelationDigest"
                            )
                            source_shaped_relation = (
                                isinstance(editorial_transformation, Mapping)
                                and isinstance(publisher_relation_digest, str)
                                and publisher_relation_digest
                                == _canonical_json_digest(publisher_relation)
                            )
                            if relation is None and not source_shaped_relation:
                                structural_failures.append(
                                    f"{pack}: source record <{quad.subject}> has invalid "
                                    "nativePayload.publisherRelation"
                                )
                            elif relation is not None:
                                native_relations.add(relation)
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

    for record, payload_digest in pending_native_payload_digests.items():
        compact_native_payload_records.add(record)
        native_payload_digest_differences[record] = (
            payload_digest,
            record_source_digests.get(record),
        )

    linked_label_nodes = {
        *(node for _, node in pref_edges),
        *(node for _, node in alt_edges),
        *(node for _, node in hidden_edges),
    }
    if compact_normalized_claims:
        for subject, forms in label_forms.items():
            if subject in linked_label_nodes:
                continue
            rows = {
                (subject, SKOSXL_LITERAL_FORM, literal)
                for literal in forms
            }
            all_raw_literal_claims.update(rows)
            if subject in source_claim_subjects:
                raw_source_literal_claims.update(rows)

        # The dedicated indexes above already retain source concepts, source
        # records, and linked label nodes. Keep their exact publisher types in
        # raw_source_iri_claims, but do not allocate the same high-cardinality
        # type map a second time. Atlas-owned resources and source-release
        # nodes remain classified here for residual-claim and release checks.
        redundant_typed_subjects = (
            set(source_claim_subjects)
            | set(source_records)
            | linked_label_nodes
        )
        rdf_types = defaultdict(
            set,
            {
                subject: types
                for subject, types in rdf_types.items()
                if subject not in redundant_typed_subjects
                or ATLAS_SOURCE_RELEASE in types
            },
        )

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
    record_claim_subjects = (
        set(record_targets)
        | set(native_payloads)
        | compact_native_payload_records
    )
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

    # Freeze each high-cardinality index and release its mutable predecessor
    # before allocating the next one. This keeps return-value construction from
    # becoming the peak-memory phase for the 441,127-record FAST comparison.
    label_links = frozenset(
        chain(
            (
                (subject, SKOSXL_PREF_LABEL, node)
                for subject, node in pref_edges
            ),
            (
                (subject, SKOSXL_ALT_LABEL, node)
                for subject, node in alt_edges
            ),
            (
                (subject, SKOSXL_HIDDEN_LABEL, node)
                for subject, node in hidden_edges
            ),
        )
    )
    label_forms.clear()
    pref_edges.clear()
    alt_edges.clear()
    hidden_edges.clear()
    native_label_claims_by_record.clear()

    relation_assertions = frozenset(reified)
    reified.clear()
    relation_rows.clear()

    frozen_rdf_types = {
        key: frozenset(value) for key, value in rdf_types.items()
    }
    rdf_types.clear()
    frozen_resource_profiles = {
        key: frozenset(value) for key, value in resource_profiles.items()
    }
    resource_profiles.clear()
    frozen_semantic_rings = {
        key: frozenset(value) for key, value in semantic_rings.items()
    }
    semantic_rings.clear()
    frozen_atlas_scheme_iris = {
        key: frozenset(value) for key, value in atlas_scheme_iris.items()
    }
    atlas_scheme_iris.clear()
    frozen_pref_labels = {
        key: frozenset(value) for key, value in pref.items()
    }
    pref.clear()
    frozen_alt_labels = {
        key: frozenset(value) for key, value in alt.items()
    }
    alt.clear()
    frozen_hidden_labels = {
        key: frozenset(value) for key, value in hidden.items()
    }
    hidden.clear()
    frozen_notations = {
        key: frozenset(value) for key, value in notations.items()
    }
    notations.clear()
    frozen_definitions = {
        key: frozenset(value) for key, value in definitions.items()
    }
    definitions.clear()
    frozen_notes = {
        key: frozenset(value) for key, value in notes.items()
    }
    notes.clear()

    frozen_resources = frozenset(resources)
    resources.clear()
    frozen_releases = frozenset(releases)
    releases.clear()
    frozen_skos_schemes = frozenset(skos_schemes)
    skos_schemes.clear()
    frozen_memberships = frozenset(memberships)
    memberships.clear()
    frozen_source_records = frozenset(source_records)
    source_records.clear()
    record_locators = frozenset(
        locator
        for subject, locator in locator_by_subject.items()
        if subject in frozen_source_records
    )
    record_locator_pairs = frozenset(
        (target, locator_by_subject[record])
        for record, target in record_targets.items()
        if record in frozen_source_records and record in locator_by_subject
    )

    return AtlasView(
        resources=frozen_resources,
        releases=frozen_releases,
        rdf_types=frozen_rdf_types,
        resource_profiles=frozen_resource_profiles,
        semantic_rings=frozen_semantic_rings,
        atlas_scheme_iris=frozen_atlas_scheme_iris,
        skos_schemes=frozen_skos_schemes,
        pref_labels=frozen_pref_labels,
        alt_labels=frozen_alt_labels,
        hidden_labels=frozen_hidden_labels,
        notations=frozen_notations,
        definitions=frozen_definitions,
        notes=frozen_notes,
        relations=relations,
        memberships=frozen_memberships,
        source_records=frozen_source_records,
        record_locators=record_locators,
        record_locator_pairs=record_locator_pairs,
        record_targets=record_targets,
        record_source_locators=locator_by_subject,
        record_source_digests=record_source_digests,
        native_payloads=dict(sorted(native_payloads.items())),
        native_scheme_iris=keyed_native,
        native_top_concept_of_iris=keyed_native_top_concepts,
        native_literal_claims=frozenset(keyed_native_literal_claims),
        native_relations=frozenset(native_relations),
        compact_native_payload_records=frozenset(compact_native_payload_records),
        native_payload_digest_differences=dict(
            sorted(native_payload_digest_differences.items())
        ),
        native_payload_field_differences=dict(
            sorted(native_payload_field_differences.items())
        ),
        raw_source_iri_claims=frozenset(raw_source_iri_claims),
        raw_source_literal_claims=frozenset(raw_source_literal_claims),
        all_raw_iri_claims=frozenset(all_raw_iri_claims),
        all_raw_literal_claims=frozenset(all_raw_literal_claims),
        label_links=label_links,
        relation_assertions=relation_assertions,
        structural_failures=tuple(structural_failures),
        checked_packs=tuple(packs),
        checked_pack_transports=dict(sorted(checked_pack_transports.items())),
    )


def _audit_atlas_language_scope(
    distribution: Path,
    packs: Collection[str],
) -> AtlasLanguageScopeEvidence:
    """Inspect every declared pack and prove the Atlas has no out-of-scope text."""
    non_english: set[tuple[str, str, LiteralValue]] = set()
    noncanonical_semantic: set[tuple[str, str, LiteralValue]] = set()
    scan_failures: list[str] = []
    semantic_predicates = frozenset(
        {
            SKOS_PREF_LABEL,
            SKOS_ALT_LABEL,
            SKOS_HIDDEN_LABEL,
            SKOSXL_LITERAL_FORM,
            ATLAS_DEFINITION,
            ATLAS_NOTE,
        }
    )
    for pack in sorted(set(packs)):
        try:
            quads = read_pack(distribution / "packs" / pack, scan_failures)
            for quad in quads:
                if not quad.is_literal:
                    continue
                literal = _literal_value(quad.obj, quad.language, quad.datatype)
                row = (quad.subject, quad.predicate, literal)
                if quad.language is not None:
                    normalized = quad.language.casefold()
                    if (
                        _BCP47.fullmatch(quad.language) is None
                        or normalized != "en"
                    ):
                        non_english.add(row)
                if quad.predicate in semantic_predicates and quad.language != "en":
                    noncanonical_semantic.add(row)
        except OSError as error:
            scan_failures.append(f"{pack}: {type(error).__name__}: {error}")

    def evidence(
        rows: Collection[tuple[str, str, LiteralValue]],
    ) -> tuple[int, str, tuple[str, ...]]:
        ordered = sorted(rows, key=_literal_claim_sort_key)
        serialized = [
            {
                "datatype": literal.datatype,
                "language": literal.language,
                "predicate": predicate,
                "subject": subject,
                "value": literal.value,
            }
            for subject, predicate, literal in ordered
        ]
        digest = "sha256:" + hashlib.sha256(
            json.dumps(
                serialized,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        examples = tuple(
            f"<{subject}> <{predicate}> {_literal_repr(literal)}"
            for subject, predicate, literal in ordered[:5]
        )
        return len(ordered), digest, examples

    non_english_count, non_english_digest, non_english_examples = evidence(
        non_english
    )
    semantic_count, semantic_digest, semantic_examples = evidence(
        noncanonical_semantic
    )
    return AtlasLanguageScopeEvidence(
        non_english_literal_count=non_english_count,
        non_english_literals_digest=non_english_digest,
        non_english_literal_examples=non_english_examples,
        noncanonical_semantic_literal_count=semantic_count,
        noncanonical_semantic_literals_digest=semantic_digest,
        noncanonical_semantic_literal_examples=semantic_examples,
        scan_failures=tuple(scan_failures),
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


@dataclass(frozen=True)
class _StockVocabularyRecord:
    """One publisher record read without importing its registry adapter."""

    resource: str
    preferred_labels: tuple[LiteralValue, ...]
    alternate_labels: tuple[LiteralValue, ...]
    notations: tuple[LiteralValue, ...]
    annotations: tuple[tuple[str, LiteralValue], ...]
    source_locator: str
    source_digest: str
    native_payload: Mapping[str, Any]
    is_skos_concept: bool = True


def _stock_vocabulary_view(
    records: Iterable[_StockVocabularyRecord],
    relations: Collection[tuple[str, str, str]],
    memberships: Collection[tuple[str, str]],
    pins: Sequence[SourcePin],
    *,
    unevaluated_claims: Sequence[str] = (),
    require_relation_members: bool = True,
    retain_predicate_counts: bool = True,
    retain_claim_sets: bool = True,
    retain_expected_native_payloads: bool = True,
    compact_resource_digests: bool = False,
    expected_relation_payloads: Mapping[str, Mapping[str, Any]] | None = None,
    source_digest_is_native_payload_digest: bool = True,
    additional_literal_claims: Collection[
        tuple[str, str, LiteralValue]
    ] = (),
) -> PublisherView:
    """Build the comparison view shared by stock XML, RDF, MARC, and JSON readers."""
    concepts: set[str] = set()
    pref_labels: dict[str, frozenset[LiteralValue]] = {}
    alt_labels: dict[str, frozenset[LiteralValue]] = {}
    notations: dict[str, frozenset[LiteralValue]] = {}
    annotation_claims: set[tuple[str, str, LiteralValue]] = set()
    literal_claims: set[tuple[str, str, LiteralValue]] = set(
        additional_literal_claims
    )
    iri_claims: set[tuple[str, str, str]] = set(relations) if retain_claim_sets else set()
    if retain_claim_sets:
        iri_claims.update(
            (resource, SKOS_IN_SCHEME, scheme) for resource, scheme in memberships
        )
    predicate_counts: dict[tuple[str, str], int] = defaultdict(int)
    resource_input_digests: dict[str, frozenset[str]] = {}
    resource_input_digest_values: dict[str, str] = {}
    resource_locators: dict[str, str] = {}
    expected_native_payloads: dict[str, Mapping[str, Any]] = {}
    for record in records:
        if record.resource in concepts:
            raise ValueError(
                f"stock source reader repeats resource {record.resource!r}"
            )
        concepts.add(record.resource)
        preferred = frozenset(record.preferred_labels)
        alternate = frozenset(record.alternate_labels)
        notation_values = frozenset(record.notations)
        if not preferred and not alternate:
            raise ValueError(
                f"stock source record {record.resource!r} has no asserted label"
            )
        pref_labels[record.resource] = preferred
        alt_labels[record.resource] = alternate
        notations[record.resource] = notation_values
        # The member-IRI comparison treats an explicit Concept type as evidence
        # distinct from concept-set identity. Entity-ring managed records do
        # not make that SKOS assertion.
        if record.is_skos_concept:
            iri_claims.add((record.resource, RDF_TYPE, SKOS_CONCEPT))
        for predicate, values in (
            (SKOS_PREF_LABEL, preferred),
            (SKOS_ALT_LABEL, alternate),
            (SKOS_NOTATION, notation_values),
        ):
            if retain_claim_sets:
                literal_claims.update(
                    (record.resource, predicate, literal) for literal in values
                )
            if retain_predicate_counts:
                predicate_counts[(record.resource, predicate)] = len(values)
        record_annotations = {
            (record.resource, predicate, literal)
            for predicate, literal in record.annotations
        }
        annotation_claims.update(record_annotations)
        if retain_claim_sets:
            literal_claims.update(record_annotations)
        if retain_predicate_counts:
            if record.is_skos_concept:
                predicate_counts[(record.resource, RDF_TYPE)] = 1
            for _, predicate, _ in record_annotations:
                predicate_counts[(record.resource, predicate)] += 1
        if compact_resource_digests:
            resource_input_digest_values[record.resource] = record.source_digest
        else:
            resource_input_digests[record.resource] = frozenset(
                {record.source_digest}
            )
        resource_locators[record.resource] = record.source_locator
        if retain_expected_native_payloads:
            expected_native_payloads[record.resource] = record.native_payload
    unknown_relation_endpoints = sorted(
        {
            endpoint
            for subject, _, obj in relations
            for endpoint in ((subject, obj) if require_relation_members else (subject,))
            if endpoint not in concepts
        }
    )
    if unknown_relation_endpoints:
        raise ValueError(
            "stock source relations name unknown required resources: "
            f"{unknown_relation_endpoints[:5]}"
        )
    if retain_predicate_counts:
        for subject, predicate, _ in relations:
            predicate_counts[(subject, predicate)] += 1
        for subject, _ in memberships:
            predicate_counts[(subject, SKOS_IN_SCHEME)] += 1
    return PublisherView(
        concepts=frozenset(concepts),
        schemes=frozenset(),
        pref_labels=pref_labels,
        alt_labels=alt_labels,
        hidden_labels={},
        notations=notations,
        annotations=frozenset(annotation_claims),
        resource_annotations=frozenset(),
        resource_annotation_target_claim_counts={},
        literal_claims=frozenset(literal_claims),
        iri_claims=frozenset(iri_claims),
        reified_statements=frozenset(),
        pref_label_count_all_languages=sum(len(values) for values in pref_labels.values()),
        alt_label_count_all_languages=sum(len(values) for values in alt_labels.values()),
        hidden_label_count_all_languages=0,
        relations=frozenset(relations),
        memberships=frozenset(memberships),
        top_concept_of=frozenset(),
        has_top_concept=frozenset(),
        resource_predicate_counts=dict(predicate_counts),
        defects=(),
        resource_input_digests=resource_input_digests,
        input_content_digests={pin.path: pin.sha256 for pin in pins},
        unevaluated_claims=tuple(unevaluated_claims),
        resource_locators=resource_locators,
        expected_native_payloads=expected_native_payloads,
        expected_relation_payloads=dict(expected_relation_payloads or {}),
        resource_input_digest_values=resource_input_digest_values,
        source_digest_is_native_payload_digest=(
            source_digest_is_native_payload_digest
        ),
    )


MESH_DESCRIPTOR_XML_READER = "mesh-descriptor-xml-2026-v1"
FEDERAL_REGISTER_TOPICS_JSON_READER = "federal-register-topics-json-v1"
GCMD_SCIENCE_KEYWORDS_CSV_READER = "gcmd-science-keywords-csv-v1"
_MESH_DESCRIPTOR_ROOT = "DescriptorRecordSet"
_MESH_DESCRIPTOR_RECORD = "DescriptorRecord"
_MESH_DESCRIPTOR_IRI_BASE = "https://id.nlm.nih.gov/mesh/"
_MESH_DESCRIPTOR_UI = re.compile(r"^D\d{6,}$")
_MESH_DESCRIPTOR_CLASSES = frozenset({"1", "2", "3", "4", "5", "6"})
_MESH_USED_XML_PATHS = frozenset(
    {
        "DescriptorRecord",
        "DescriptorRecord/DescriptorUI",
        "DescriptorRecord/DescriptorName",
        "DescriptorRecord/DescriptorName/String",
        "DescriptorRecord/TreeNumberList",
        "DescriptorRecord/TreeNumberList/TreeNumber",
        "DescriptorRecord/ConceptList",
        "DescriptorRecord/ConceptList/Concept",
        "DescriptorRecord/ConceptList/Concept/TermList",
        "DescriptorRecord/ConceptList/Concept/TermList/Term",
        "DescriptorRecord/ConceptList/Concept/TermList/Term/String",
    }
)
_FEDERAL_REGISTER_TOPICS_URL = (
    "https://www.federalregister.gov/api/v1/topics.json"
)
_FEDERAL_REGISTER_TOPIC_KEYS = frozenset(
    {"cfr_references", "name", "see", "see_also", "slug"}
)
_FEDERAL_REGISTER_LINK_KEYS = frozenset({"name", "slug"})
_GCMD_CSV_COLUMNS = (
    "Category",
    "Topic",
    "Term",
    "Variable_Level_1",
    "Variable_Level_2",
    "Variable_Level_3",
    "Detailed_Variable",
    "UUID",
)
_GCMD_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_GCMD_ALLOWED_CATEGORIES = frozenset(
    {"EARTH SCIENCE", "EARTH SCIENCE SERVICES"}
)
_GCMD_VIEWER_URL = (
    "https://gcmd.earthdata.nasa.gov/KeywordViewer/scheme/"
    "sciencekeywords/27478148-b4b6-4c89-8829-08d2ee7bfe10/"
)
_GCMD_AUTHORITY_URL = "https://gcmd.earthdata.nasa.gov/kms/"


@dataclass(frozen=True)
class _StockSourceRecord:
    """One record read without registry code from JSON, CSV, XML, or MARC."""

    resource: str
    preferred_label: str
    alternate_labels: tuple[str, ...]
    notations: tuple[str, ...]
    source_locator: str
    source_digest: str
    native_payload: Mapping[str, Any]


def _stock_source_view(
    records: Iterable[_StockSourceRecord],
    relations: Collection[tuple[str, str, str]],
    pins: Sequence[SourcePin],
    *,
    unevaluated_claims: Sequence[str] = (),
) -> PublisherView:
    """Adapt the three source readers to main's bounded stock-view indexes."""

    def stock_records() -> Iterator[_StockVocabularyRecord]:
        for record in records:
            yield _StockVocabularyRecord(
                resource=record.resource,
                preferred_labels=(
                    _literal_value(record.preferred_label, "en", None),
                ),
                alternate_labels=tuple(
                    _literal_value(value, "en", None)
                    for value in record.alternate_labels
                ),
                notations=tuple(
                    _literal_value(value, None, None) for value in record.notations
                ),
                annotations=(),
                source_locator=record.source_locator,
                source_digest=record.source_digest,
                native_payload=record.native_payload,
            )

    # These three sources use file or source-row digests, not native-payload
    # digests. Main's compact payload path therefore cannot prove field values.
    # Keep that one necessary expected-value map, while dropping duplicate claim
    # and predicate-count indexes and using the compact one-string digest map.
    return _stock_vocabulary_view(
        stock_records(),
        relations,
        (),
        pins,
        unevaluated_claims=unevaluated_claims,
        retain_predicate_counts=False,
        retain_claim_sets=False,
        retain_expected_native_payloads=True,
        compact_resource_digests=True,
        source_digest_is_native_payload_digest=False,
    )


def _canonical_json_source_digest(value: Any) -> str:
    """Hash one JSON value with the source adapters' documented spelling."""
    return _canonical_json_digest(value)


def _derive_source_uuid7(recorded_at: str, seed: bytes) -> str:
    """Independently derive the deterministic UUIDv7 used for local rows."""
    parsed = datetime.fromisoformat(
        recorded_at[:-1] + "+00:00"
        if recorded_at.endswith("Z")
        else recorded_at
    )
    if parsed.tzinfo is None:
        raise ValueError("source-local identity timestamp must include a time zone")
    timestamp_ms = int(parsed.astimezone(UTC).timestamp() * 1_000)
    if timestamp_ms < 0 or timestamp_ms >= 1 << 48:
        raise ValueError("source-local identity timestamp is outside UUIDv7 range")
    random_bits = int.from_bytes(hashlib.sha256(seed).digest(), "big") >> 182
    random_a = random_bits >> 62
    random_b = random_bits & ((1 << 62) - 1)
    value = timestamp_ms << 80
    value |= 0x7 << 76
    value |= random_a << 64
    value |= 0b10 << 62
    value |= random_b
    return str(uuid.UUID(int=value))


def _source_local_resource_iri(
    namespace: str,
    recorded_at: str,
    source_iri: str,
    source_key: str,
) -> str:
    seed = (
        "atlas-v3-registry-source-identity-v1\n"
        f"{source_iri}\n{source_key}\n"
    ).encode()
    local_id = _derive_source_uuid7(recorded_at, seed)
    return f"urn:ref:source-concept:v2:{namespace}:{local_id}"


def _source_scoped_resource_identity(
    namespace: str,
    recorded_at: str,
    source_scheme: str,
    source_key: str,
) -> tuple[str, Mapping[str, str]]:
    seed = (
        "atlas-v3-source-concept-v1\n"
        f"{source_scheme}\n{source_key}\n"
    ).encode()
    local_id = _derive_source_uuid7(recorded_at, seed)
    return (
        f"urn:ref:source-concept:v2:{namespace}:{local_id}",
        {
            "identityKind": "refspecSourceScoped",
            "localRecordId": f"urn:uuid:{local_id}",
            "namespaceToken": namespace,
            "sourceKey": source_key,
            "sourceScheme": source_scheme,
        },
    )


def _require_exact_json_keys(
    value: Mapping[str, Any],
    expected: Collection[str],
    label: str,
) -> None:
    if set(value) != set(expected):
        raise ValueError(
            f"{label} fields changed; missing={sorted(set(expected) - set(value))}, "
            f"extra={sorted(set(value) - set(expected))}"
        )


def _required_xml_text(value: str | None, label: str) -> str:
    """Return one required MeSH value without normalizing its internal text."""
    if value is None or not value.strip():
        raise ValueError(f"{label} must be non-empty text")
    return value.strip()


def _read_mesh_descriptor_xml(
    spec: SourceSpec,
    authenticated_payloads: Mapping[SourcePin, bytes],
) -> PublisherView:
    """Read MeSH descriptors with ElementTree, independent of registry ETL."""
    if len(spec.inputs) != 1:
        raise ValueError("MeSH descriptor reader requires exactly one XML input")
    pin = spec.inputs[0]
    payload = authenticated_payloads[pin]
    if b"<!ENTITY" in payload[:8192].upper():
        raise ValueError("MeSH descriptor XML must not declare custom XML entities")

    ignored_paths: Counter[str] = Counter()
    ignored_attributes: Counter[str] = Counter()
    concept_count = 0

    def records() -> Iterator[_StockSourceRecord]:
        nonlocal concept_count
        context = ElementTree.iterparse(io.BytesIO(payload), events=("start", "end"))
        try:
            event, root = next(context)
        except (StopIteration, ElementTree.ParseError) as error:
            raise ValueError("MeSH descriptor XML is empty or malformed") from error
        if event != "start" or root.tag != _MESH_DESCRIPTOR_ROOT:
            raise ValueError(
                f"MeSH XML root must be {_MESH_DESCRIPTOR_ROOT!r}, observed {root.tag!r}"
            )
        if root.get("LanguageCode") != "eng":
            raise ValueError("MeSH DescriptorRecordSet LanguageCode must be 'eng'")
        for attribute in root.attrib:
            if attribute != "LanguageCode":
                ignored_attributes[f"{_MESH_DESCRIPTOR_ROOT}@{attribute}"] += 1

        try:
            for event, element in context:
                if event != "end" or element.tag != _MESH_DESCRIPTOR_RECORD:
                    continue
                descriptor_class = element.get("DescriptorClass")
                if descriptor_class not in _MESH_DESCRIPTOR_CLASSES:
                    raise ValueError(
                        "MeSH DescriptorRecord has unsupported DescriptorClass "
                        f"{descriptor_class!r}"
                    )
                descriptor_ui = _required_xml_text(
                    element.findtext("DescriptorUI"),
                    "MeSH DescriptorUI",
                )
                if _MESH_DESCRIPTOR_UI.fullmatch(descriptor_ui) is None:
                    raise ValueError(
                        f"MeSH DescriptorUI is malformed: {descriptor_ui!r}"
                    )
                resource = _MESH_DESCRIPTOR_IRI_BASE + descriptor_ui
                heading = _required_xml_text(
                    element.findtext("DescriptorName/String"),
                    f"MeSH {descriptor_ui} DescriptorName",
                )
                tree_numbers = tuple(
                    _required_xml_text(node.text, f"MeSH {descriptor_ui} TreeNumber")
                    for node in element.findall("TreeNumberList/TreeNumber")
                )
                alternate: list[str] = []
                seen_labels = {heading}
                for term in element.findall("ConceptList/Concept/TermList/Term"):
                    permuted = term.get("IsPermutedTermYN")
                    if permuted not in {"Y", "N"}:
                        raise ValueError(
                            f"MeSH {descriptor_ui} Term has unsupported "
                            f"IsPermutedTermYN {permuted!r}"
                        )
                    if permuted == "Y":
                        continue
                    value = _required_xml_text(
                        term.findtext("String"),
                        f"MeSH {descriptor_ui} Term",
                    )
                    if value not in seen_labels:
                        seen_labels.add(value)
                        alternate.append(value)

                def account_xml(node: ElementTree.Element, path: str) -> None:
                    if path not in _MESH_USED_XML_PATHS:
                        ignored_paths[path] += 1
                    allowed_attributes = (
                        {"DescriptorClass"}
                        if path == "DescriptorRecord"
                        else {"IsPermutedTermYN"}
                        if path.endswith("/Term")
                        else set()
                    )
                    for attribute in node.attrib:
                        if attribute not in allowed_attributes:
                            ignored_attributes[f"{path}@{attribute}"] += 1
                    for child in node:
                        account_xml(child, f"{path}/{child.tag}")

                account_xml(element, _MESH_DESCRIPTOR_RECORD)
                concept_count += 1
                yield _StockSourceRecord(
                    resource=resource,
                    preferred_label=heading,
                    alternate_labels=tuple(alternate),
                    notations=tree_numbers,
                    source_locator=resource,
                    source_digest=pin.sha256,
                    native_payload={
                        "publisherConceptIri": resource,
                        "descriptorUi": descriptor_ui,
                        "descriptorClass": descriptor_class,
                        "treeNumbers": list(tree_numbers),
                    },
                )
                element.clear()
                while len(root):
                    del root[0]
        except ElementTree.ParseError as error:
            raise ValueError("MeSH descriptor XML is malformed") from error

    view = _stock_source_view(records(), (), spec.inputs)
    if not concept_count:
        raise ValueError("MeSH descriptor XML contains no DescriptorRecord elements")
    unevaluated_claims = tuple(
        [
            f"MeSH XML path {path!r} has {count} values outside the declared reader"
            for path, count in sorted(ignored_paths.items())
        ]
        + [
            f"MeSH XML attribute {path!r} has {count} values outside the declared reader"
            for path, count in sorted(ignored_attributes.items())
        ]
    )
    return replace(view, unevaluated_claims=unevaluated_claims)


def _read_federal_register_topics_json(
    spec: SourceSpec,
    authenticated_payloads: Mapping[SourcePin, bytes],
) -> PublisherView:
    """Read the captured FederalRegister.gov topics API with stdlib JSON."""
    if len(spec.inputs) != 1:
        raise ValueError("Federal Register topics reader requires one JSON input")
    pin = spec.inputs[0]
    document = _json_without_duplicate_keys(authenticated_payloads[pin], pin.path)
    if not isinstance(document, Mapping):
        raise ValueError("Federal Register topics response must be an object")
    _require_exact_json_keys(document, {"meta", "results"}, "topics response")
    meta = document["meta"]
    results = document["results"]
    if not isinstance(meta, Mapping) or set(meta) != {"count"}:
        raise ValueError("Federal Register topics meta must contain only count")
    counts = meta["count"]
    if not isinstance(counts, Mapping):
        raise ValueError("Federal Register topics meta.count must be an object")
    _require_exact_json_keys(
        counts,
        {"thesaurus", "ad_hoc", "total"},
        "topics meta.count",
    )
    if not isinstance(results, Mapping):
        raise ValueError("Federal Register topics results must be an object")
    _require_exact_json_keys(results, {"thesaurus", "ad_hoc"}, "topics results")

    parsed_rows: list[tuple[str, int, Mapping[str, Any], str]] = []
    resource_by_pair: dict[tuple[str, str, str], str] = {}
    for collection in ("thesaurus", "ad_hoc"):
        rows = results[collection]
        if not isinstance(rows, list):
            raise ValueError(f"topics results.{collection} must be an array")
        declared_count = counts.get(collection)
        if declared_count != len(rows) or isinstance(declared_count, bool):
            raise ValueError(
                f"topics meta.count.{collection} declares {declared_count!r}, "
                f"observed {len(rows)}"
            )
        for ordinal, raw_row in enumerate(rows):
            label = f"results.{collection}[{ordinal}]"
            if not isinstance(raw_row, Mapping):
                raise ValueError(f"{label} must be an object")
            _require_exact_json_keys(raw_row, _FEDERAL_REGISTER_TOPIC_KEYS, label)
            name = raw_row.get("name")
            slug = raw_row.get("slug")
            if not isinstance(name, str) or not name.strip():
                raise ValueError(f"{label}.name must be non-empty text")
            if not isinstance(slug, str):
                raise ValueError(f"{label}.slug must be text")
            for field_name in ("see", "see_also", "cfr_references"):
                if not isinstance(raw_row.get(field_name), list):
                    raise ValueError(f"{label}.{field_name} must be an array")
            for field_name in ("see", "see_also"):
                for index, link in enumerate(raw_row[field_name]):
                    if not isinstance(link, Mapping):
                        raise ValueError(
                            f"{label}.{field_name}[{index}] must be an object"
                        )
                    _require_exact_json_keys(
                        link,
                        _FEDERAL_REGISTER_LINK_KEYS,
                        f"{label}.{field_name}[{index}]",
                    )
                    if (
                        not isinstance(link.get("name"), str)
                        or not link["name"].strip()
                    ):
                        raise ValueError(
                            f"{label}.{field_name}[{index}].name must be text"
                        )
                    if not isinstance(link.get("slug"), str):
                        raise ValueError(
                            f"{label}.{field_name}[{index}].slug must be text"
                        )
            row_digest = _canonical_json_source_digest(
                {
                    "collection": collection,
                    "sourceOrdinal": ordinal,
                    "record": raw_row,
                }
            )
            resource = _source_local_resource_iri(
                "federal-register-api",
                "2026-08-03T00:00:00Z",
                _FEDERAL_REGISTER_TOPICS_URL,
                f"{collection}:{ordinal}:{row_digest}",
            )
            pair = (collection, name, slug)
            if pair in resource_by_pair:
                raise ValueError(
                    f"Federal Register topic pair is duplicated: {pair!r}"
                )
            resource_by_pair[pair] = resource
            parsed_rows.append((collection, ordinal, raw_row, resource))
    if counts.get("total") != len(parsed_rows) or isinstance(
        counts.get("total"), bool
    ):
        raise ValueError(
            f"topics meta.count.total declares {counts.get('total')!r}, "
            f"observed {len(parsed_rows)}"
        )

    records: list[_StockSourceRecord] = []
    relations: set[tuple[str, str, str]] = set()
    for collection, ordinal, row, resource in parsed_rows:
        source_path = f"results.{collection}[{ordinal}]"
        row_digest = _canonical_json_source_digest(
            {
                "collection": collection,
                "sourceOrdinal": ordinal,
                "record": row,
            }
        )
        records.append(
            _StockSourceRecord(
                resource=resource,
                preferred_label=row["name"],
                alternate_labels=(),
                notations=(row["slug"],) if row["slug"] else (),
                source_locator=(
                    _FEDERAL_REGISTER_TOPICS_URL
                    + "#"
                    + urllib.parse.quote(source_path, safe="")
                ),
                source_digest=row_digest,
                native_payload={
                    "collection": collection,
                    "record": dict(row),
                    "sourceOrdinal": ordinal,
                    "sourceRecordDigest": row_digest,
                },
            )
        )
        for field_name, predicate in (
            ("see", f"{ATLAS}thesaurusUse"),
            ("see_also", f"{SKOS}related"),
        ):
            for link in row[field_name]:
                target = resource_by_pair.get(
                    (collection, link["name"], link["slug"])
                )
                if target is None:
                    raise ValueError(
                        f"{source_path}.{field_name} has no exact same-collection "
                        f"target: {link!r}"
                    )
                relations.add((resource, predicate, target))
    return _stock_source_view(records, relations, spec.inputs)


def _read_gcmd_science_keywords_csv(
    spec: SourceSpec,
    authenticated_payloads: Mapping[SourcePin, bytes],
) -> PublisherView:
    """Read NASA GCMD Science Keywords with the stdlib CSV parser."""
    if len(spec.inputs) != 1:
        raise ValueError("GCMD Science Keywords reader requires one CSV input")
    pin = spec.inputs[0]
    try:
        text = authenticated_payloads[pin].decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("GCMD Science Keywords CSV is not UTF-8") from error
    reader = csv.reader(io.StringIO(text))
    try:
        metadata = next(reader)
        header = next(reader)
    except StopIteration as error:
        raise ValueError("GCMD CSV is missing metadata or column headers") from error
    if (
        len(metadata) < 2
        or metadata[0].strip() != "Keyword Version: 24.4"
        or metadata[1].strip() != "Revision: 2026-07-22T11:07:16.739Z"
    ):
        raise ValueError("GCMD CSV version or revision header drifted")
    if tuple(header) != _GCMD_CSV_COLUMNS:
        raise ValueError(f"GCMD CSV columns drifted: {header!r}")

    records: list[_StockSourceRecord] = []
    seen_uuids: set[str] = set()
    for ordinal, row in enumerate(reader):
        if not row:
            continue
        if len(row) != len(_GCMD_CSV_COLUMNS):
            raise ValueError(
                f"GCMD CSV row {ordinal} has {len(row)} fields, expected 8"
            )
        category, topic, term, level_1, level_2, level_3, detailed, concept_uuid = row
        if category not in _GCMD_ALLOWED_CATEGORIES:
            raise ValueError(
                f"GCMD CSV row {ordinal} has out-of-scope category {category!r}"
            )
        if _GCMD_UUID.fullmatch(concept_uuid) is None:
            raise ValueError(
                f"GCMD CSV row {ordinal} has malformed UUID {concept_uuid!r}"
            )
        if concept_uuid in seen_uuids:
            raise ValueError(f"GCMD CSV row {ordinal} repeats UUID {concept_uuid!r}")
        seen_uuids.add(concept_uuid)
        levels = (category, topic, term, level_1, level_2, level_3, detailed)
        seen_blank = False
        for level in levels:
            if not level:
                seen_blank = True
            elif seen_blank:
                raise ValueError(
                    f"GCMD CSV row {ordinal} populates a level after a blank ancestor"
                )
        preferred_label = next(level for level in reversed(levels) if level)
        resource, source_identity = _source_scoped_resource_identity(
            "gcmd-science-keywords",
            "2026-08-03T19:03:43Z",
            _GCMD_VIEWER_URL,
            concept_uuid,
        )
        source_path = f"csv:row[{ordinal}]"
        locator_digest = hashlib.sha256(
            f"{pin.source_iri}\n{source_path}\n{concept_uuid}\n".encode()
        ).hexdigest()
        records.append(
            _StockSourceRecord(
                resource=resource,
                preferred_label=preferred_label,
                alternate_labels=(),
                notations=(concept_uuid,),
                source_locator=(
                    "urn:ref:source-observation:gcmd-science-keywords-24-4:"
                    + locator_digest
                ),
                source_digest=pin.sha256,
                native_payload={
                    "publisherIdentifier": {
                        "value": concept_uuid,
                        "kind": "gcmdConceptUUID",
                        "authorityUri": _GCMD_AUTHORITY_URL,
                    },
                    "category": category,
                    "topic": topic or None,
                    "term": term or None,
                    "variableLevel1": level_1 or None,
                    "variableLevel2": level_2 or None,
                    "variableLevel3": level_3 or None,
                    "detailedVariable": detailed or None,
                    "sourceIdentity": source_identity,
                },
            )
        )
    ignored_metadata = tuple(
        f"GCMD metadata header field {index} is authenticated but not represented: {value!r}"
        for index, value in enumerate(metadata[2:], start=2)
        if value
    )
    return _stock_source_view(
        records,
        (),
        spec.inputs,
        unevaluated_claims=ignored_metadata,
    )


EPA_ENTERPRISE_VOCABULARY_XML_READER = "epa-enterprise-vocabulary-xml-v1"
_EPA_BROWSE_URL = (
    "https://ofmpub.epa.gov/sor_internet/registry/termreg/searchandretrieve/"
    "enterprisevocabulary/search.do?search=&tierTwoSelected=1005100&searchString="
)


def _read_epa_enterprise_vocabulary_xml(
    spec: SourceSpec,
    authenticated_payloads: Mapping[SourcePin, bytes],
) -> PublisherView:
    """Read EPA's positional XML label tree with ElementTree."""
    if len(spec.inputs) != 1:
        raise ValueError("EPA Enterprise Vocabulary reader requires one XML input")
    pin = spec.inputs[0]
    payload = authenticated_payloads[pin]
    if b"<!ENTITY" in payload[:8192].upper():
        raise ValueError("EPA Enterprise Vocabulary XML must not declare custom entities")
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as error:
        raise ValueError(f"EPA Enterprise Vocabulary XML is malformed: {error}") from error
    if root.tag != "EnterpriseVocabularyReport" or root.attrib:
        raise ValueError(
            "EPA Enterprise Vocabulary root must be an attribute-free "
            "<EnterpriseVocabularyReport>"
        )

    records: list[_StockVocabularyRecord] = []
    relations: set[tuple[str, str, str]] = set()
    row_by_path: dict[str, str] = {}

    def parse_row(element: ElementTree.Element, path: tuple[int, ...], depth: int) -> Mapping[str, Any]:
        source_path = "/".join(f"Row[{index}]" for index in path)
        if element.tag != "Row" or element.attrib:
            raise ValueError(f"EPA {source_path} must be an attribute-free <Row>")
        children_by_tag: dict[str, list[ElementTree.Element]] = defaultdict(list)
        for child in element:
            children_by_tag[child.tag].append(child)
        allowed = {"Term", "Definitions", "ScopeNote", "ChildTerms"}
        unexpected = sorted(set(children_by_tag) - allowed)
        repeated = sorted(tag for tag, rows in children_by_tag.items() if len(rows) > 1)
        if unexpected or repeated or len(children_by_tag.get("Term", ())) != 1:
            raise ValueError(
                f"EPA {source_path} shape differs; unexpected={unexpected}, "
                f"repeated={repeated}, termCount={len(children_by_tag.get('Term', ()))}"
            )
        term = children_by_tag["Term"][0]
        if term.attrib or not (term.text or "").strip():
            raise ValueError(f"EPA {source_path} Term must be nonblank and attribute-free")
        definition = children_by_tag.get("Definitions", [None])[0]
        scope_note = children_by_tag.get("ScopeNote", [None])[0]
        for label, node in (("Definitions", definition), ("ScopeNote", scope_note)):
            if node is not None and (node.attrib or len(node)):
                raise ValueError(f"EPA {source_path} {label} must contain only text")
        child_container = children_by_tag.get("ChildTerms", [None])[0]
        if child_container is not None and (
            child_container.attrib or (child_container.text or "").strip()
        ):
            raise ValueError(f"EPA {source_path} ChildTerms shape differs")
        child_payloads: list[Mapping[str, Any]] = []
        if child_container is not None:
            for index, child in enumerate(child_container):
                if child.tag != "Row":
                    raise ValueError(
                        f"EPA {source_path} ChildTerms contains <{child.tag}>"
                    )
                child_payloads.append(parse_row(child, (*path, index), depth + 1))
        row_payload: Mapping[str, Any] = {
            "label": term.text or "",
            "source_path": source_path,
            "definitions_text": None if definition is None else (definition.text or ""),
            "scope_note_text": None if scope_note is None else (scope_note.text or ""),
            "child_terms": child_payloads,
        }
        resource = "urn:ref:epa-enterprise-vocabulary-row:" + urllib.parse.quote(
            source_path,
            safe="",
        )
        row_by_path[source_path] = resource
        annotations: list[tuple[str, LiteralValue]] = []
        definition_text = (row_payload["definitions_text"] or "").strip()
        scope_note_text = (row_payload["scope_note_text"] or "").strip()
        if definition_text:
            annotations.append(
                (SKOS_DEFINITION, _literal_value(definition_text, None, None))
            )
        if scope_note_text and scope_note_text != "\xa0":
            annotations.append(
                (SKOS_SCOPE_NOTE, _literal_value(scope_note_text, None, None))
            )
        native_payload = {
            "depth": depth,
            "row": row_payload,
            "publisherConceptIdentityAvailable": False,
        }
        records.append(
            _StockVocabularyRecord(
                resource=resource,
                preferred_labels=(
                    _literal_value((term.text or "").strip(), None, None),
                ),
                alternate_labels=(),
                notations=(),
                annotations=tuple(annotations),
                source_locator=(
                    _EPA_BROWSE_URL
                    + "#"
                    + urllib.parse.quote(source_path, safe="/")
                ),
                source_digest=_canonical_json_digest(native_payload),
                native_payload=native_payload,
            )
        )
        for child in child_payloads:
            child_path = child["source_path"]
            child_resource = row_by_path.get(str(child_path))
            if child_resource is None:
                raise ValueError(f"EPA walk omitted child {child_path!r}")
            relations.add((child_resource, f"{SKOS}broader", resource))
        return row_payload

    for index, child in enumerate(root):
        parse_row(child, (index,), 0)
    return _stock_vocabulary_view(records, relations, (), spec.inputs)


LCSH_ALIGNMENT_ENDPOINT_JSONLD_READER = "lcsh-alignment-endpoint-jsonld-v1"
_LCSH_SCHEME = "http://id.loc.gov/authorities/subjects"
_LCSH_CONTEXT = "http://id.loc.gov/authorities/subjects/context.json"
_LCSH_ALIGNMENT_RELEASE = (
    "http://publications.europa.eu/resource/dataset/"
    "eurovoc_alignment_lcsh/20240711-0"
)
_LCSH_ALIGNMENT_PREDICATES = frozenset(
    {f"{SKOS}exactMatch", f"{SKOS}closeMatch"}
)


def _jsonld_term_set(value: object, label: str) -> frozenset[str]:
    if value is None:
        return frozenset()
    if isinstance(value, str):
        return frozenset({value})
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return frozenset(value)
    raise ValueError(f"{label} @type must be a string or string array")


def _jsonld_references(value: object, label: str) -> tuple[Mapping[str, Any], ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        return (value,)
    if isinstance(value, list) and all(isinstance(item, Mapping) for item in value):
        return tuple(value)
    raise ValueError(f"{label} must contain JSON-LD reference objects")


def _jsonld_label(value: object, label: str) -> LiteralValue:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a JSON-LD value object")
    text = value.get("@value")
    language = value.get("@language")
    if not isinstance(text, str) or not text:
        raise ValueError(f"{label} has no non-empty @value")
    if not isinstance(language, str) or not language:
        raise ValueError(f"{label} has no @language")
    return _literal_value(text, language, None)


def _read_lcsh_alignment_endpoint_jsonld(
    spec: SourceSpec,
    authenticated_payloads: Mapping[SourcePin, bytes],
) -> PublisherView:
    """Select official alignment objects, then stream their LOC JSON-LD records."""
    import rdflib

    alignment_pin = next(
        (pin for pin in spec.inputs if pin.role == "publisherAlignment"),
        None,
    )
    bulk_pin = next(
        (pin for pin in spec.inputs if pin.role == "publisherBulkSource"),
        None,
    )
    if alignment_pin is None or bulk_pin is None or len(spec.inputs) != 2:
        raise ValueError(
            "LCSH alignment endpoint reader requires one alignment and one bulk input"
        )
    alignment = rdflib.Graph()
    try:
        alignment.parse(
            data=authenticated_payloads[alignment_pin],
            format="xml",
            publicID=alignment_pin.source_iri,
        )
    except Exception as error:
        raise ValueError(f"LCSH selection alignment is malformed: {error}") from error
    align_type = rdflib.URIRef(
        "http://knowledgeweb.semanticweb.org/heterogeneity/alignment#Alignment"
    )
    onto1 = rdflib.URIRef(
        "http://knowledgeweb.semanticweb.org/heterogeneity/alignment#onto1"
    )
    onto2 = rdflib.URIRef(
        "http://knowledgeweb.semanticweb.org/heterogeneity/alignment#onto2"
    )
    headers = set(alignment.subjects(rdflib.RDF.type, align_type))
    if len(headers) != 1:
        raise ValueError(
            f"LCSH selection alignment must have one header, observed {len(headers)}"
        )
    header = next(iter(headers))
    if set(map(str, alignment.objects(header, onto1))) != {"http://eurovoc.europa.eu"}:
        raise ValueError("LCSH selection alignment onto1 is not EuroVoc")
    if set(map(str, alignment.objects(header, onto2))) != {_LCSH_SCHEME}:
        raise ValueError("LCSH selection alignment onto2 is not LCSH")
    selected_iris: set[str] = set()
    mapping_counts: Counter[str] = Counter()
    for predicate in _LCSH_ALIGNMENT_PREDICATES:
        for subject, obj in alignment.subject_objects(rdflib.URIRef(predicate)):
            if not isinstance(subject, rdflib.URIRef) or not str(subject).startswith(
                "http://eurovoc.europa.eu/"
            ):
                raise ValueError(f"LCSH selection has non-EuroVoc subject {subject!r}")
            if not isinstance(obj, rdflib.URIRef) or not str(obj).startswith(
                _LCSH_SCHEME + "/"
            ):
                raise ValueError(f"LCSH selection has non-LCSH object {obj!r}")
            selected_iris.add(str(obj))
            mapping_counts[predicate] += 1
    production_alignment = alignment_pin.sha256 == (
        "sha256:dbd6e610ff497c4a39a79924cf50dcf92d5f3e9ab316d58d83c460dba6fb4853"
    )
    expected_counts = {f"{SKOS}closeMatch": 99, f"{SKOS}exactMatch": 1_904}
    if production_alignment and dict(mapping_counts) != expected_counts:
        raise ValueError(
            "LCSH selection mapping counts differ: "
            f"expected={expected_counts}, observed={dict(mapping_counts)}"
        )
    if production_alignment and len(selected_iris) != 1_966:
        raise ValueError(
            f"LCSH selection must name 1,966 distinct endpoints, observed {len(selected_iris)}"
        )
    if not selected_iris:
        raise ValueError("LCSH selection alignment names no endpoints")
    path_to_iri = {
        "/authorities/subjects/" + iri.removeprefix(_LCSH_SCHEME + "/"): iri
        for iri in selected_iris
    }

    records: list[_StockVocabularyRecord] = []
    broader_by_resource: dict[str, tuple[str, ...]] = {}
    selected: set[str] = set()
    ignored_fields: Counter[str] = Counter()
    try:
        stream = gzip.GzipFile(
            fileobj=io.BytesIO(authenticated_payloads[bulk_pin]),
            mode="rb",
        )
        for line_number, line in enumerate(stream, start=1):
            raw = line.rstrip(b"\r\n")
            if not raw.strip():
                continue
            try:
                document = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError(
                    f"LCSH bulk line {line_number} is not UTF-8 JSON: {error}"
                ) from error
            if not isinstance(document, Mapping):
                raise ValueError(f"LCSH bulk line {line_number} is not an object")
            resource = path_to_iri.get(document.get("@id"))
            if resource is None:
                continue
            if resource in selected:
                raise ValueError(f"LCSH bulk repeats selected authority {resource}")
            if document.get("@context") != _LCSH_CONTEXT:
                raise ValueError(f"LCSH {resource} uses an unexpected @context")
            graph = document.get("@graph")
            if not isinstance(graph, list) or not graph:
                raise ValueError(f"LCSH {resource} has no non-empty @graph")
            by_id: dict[str, Mapping[str, Any]] = {}
            for node in graph:
                if not isinstance(node, Mapping) or not isinstance(node.get("@id"), str):
                    raise ValueError(f"LCSH {resource} has an invalid @graph node")
                node_id = node["@id"]
                if node_id in by_id:
                    raise ValueError(f"LCSH {resource} repeats node {node_id!r}")
                by_id[node_id] = node
            authorities = [
                node
                for node in graph
                if node.get("@id") == resource
                and "madsrdf:Authority"
                in _jsonld_term_set(node.get("@type"), f"LCSH {resource}")
            ]
            if len(authorities) != 1:
                raise ValueError(
                    f"LCSH {resource} must have one matching Authority node"
                )
            authority = authorities[0]
            authority_types = tuple(
                sorted(_jsonld_term_set(authority.get("@type"), f"LCSH {resource}"))
            )
            preferred = _jsonld_label(
                authority.get("madsrdf:authoritativeLabel"),
                f"LCSH {resource} authoritativeLabel",
            )
            if preferred.language is None or preferred.language.casefold() != "en":
                raise ValueError(f"LCSH {resource} has no English preferred label")
            broader = tuple(
                sorted(
                    {
                        str(reference.get("@id"))
                        for reference in _jsonld_references(
                            authority.get("madsrdf:hasBroaderAuthority"),
                            f"LCSH {resource} broader",
                        )
                        if isinstance(reference.get("@id"), str)
                        and str(reference["@id"]).startswith(_LCSH_SCHEME + "/")
                    }
                )
            )
            variants: list[LiteralValue] = []
            for reference in _jsonld_references(
                authority.get("madsrdf:hasVariant"),
                f"LCSH {resource} variants",
            ):
                variant_id = reference.get("@id")
                if not isinstance(variant_id, str) or variant_id not in by_id:
                    raise ValueError(
                        f"LCSH {resource} variant reference is absent from @graph"
                    )
                label = _jsonld_label(
                    by_id[variant_id].get("madsrdf:variantLabel"),
                    f"LCSH {resource} variant {variant_id}",
                )
                if label.language is not None and label.language.casefold() == "en":
                    variants.append(
                        _literal_value(label.value.strip(), "en", None)
                    )
                else:
                    ignored_fields["non-English variant label"] += 1
            alternate = tuple(
                sorted(
                    {
                        label
                        for label in variants
                        if label.value and label.value != preferred.value.strip()
                    },
                    key=lambda value: (value.language or "", value.value),
                )
            )
            lccn = authority.get("identifiers:lccn")
            if lccn is not None and (
                not isinstance(lccn, str) or not lccn.strip()
            ):
                raise ValueError(f"LCSH {resource} has an invalid LCCN")
            record_digest = "sha256:" + hashlib.sha256(raw).hexdigest()
            native_payload = {
                "authorityTypes": list(authority_types),
                "broaderIris": list(broader),
                "captureSelection": {
                    "alignmentDigest": alignment_pin.sha256,
                    "alignmentRelease": _LCSH_ALIGNMENT_RELEASE,
                },
                "lccn": lccn,
                "lineNumber": line_number,
                "recordByteLength": len(raw),
                "recordDigest": record_digest,
            }
            records.append(
                _StockVocabularyRecord(
                    resource=resource,
                    preferred_labels=(
                        _literal_value(preferred.value.strip(), "en", None),
                    ),
                    alternate_labels=alternate,
                    notations=(
                        ()
                        if lccn is None
                        else (_literal_value(lccn, None, None),)
                    ),
                    annotations=(),
                    source_locator=f"{bulk_pin.source_iri}#line-{line_number}",
                    source_digest=_canonical_json_digest(native_payload),
                    native_payload=native_payload,
                )
            )
            selected.add(resource)
            broader_by_resource[resource] = broader
            used_authority_fields = {
                "@id",
                "@type",
                "identifiers:lccn",
                "madsrdf:authoritativeLabel",
                "madsrdf:hasBroaderAuthority",
                "madsrdf:hasVariant",
            }
            for field_name in set(authority) - used_authority_fields:
                ignored_fields[f"authority field {field_name}"] += 1
            used_node_ids = {
                reference.get("@id")
                for reference in _jsonld_references(
                    authority.get("madsrdf:hasVariant"),
                    f"LCSH {resource} variants",
                )
            }
            for node_id, node in by_id.items():
                if node_id == resource:
                    continue
                if node_id not in used_node_ids:
                    ignored_fields["unrepresented JSON-LD graph node"] += len(node)
                else:
                    for field_name in set(node) - {"@id", "@type", "madsrdf:variantLabel"}:
                        ignored_fields[f"variant field {field_name}"] += 1
    except (OSError, EOFError) as error:
        raise ValueError(f"LCSH bulk gzip is malformed: {error}") from error
    missing = sorted(selected_iris - selected)
    if missing:
        raise ValueError(
            f"LCSH bulk lacks {len(missing)} aligned authorities: {missing[:5]}"
        )
    relations = {
        (resource, f"{SKOS}broader", broader)
        for resource, broader_iris in broader_by_resource.items()
        for broader in broader_iris
        if broader in selected
    }
    unevaluated = tuple(
        f"LCSH selected records contain {count} authenticated but unrepresented {field} claims"
        for field, count in sorted(ignored_fields.items())
        if count
    )
    return _stock_vocabulary_view(
        records,
        relations,
        (),
        spec.inputs,
        unevaluated_claims=unevaluated,
    )


FAST_TOPICAL_NATIVE_READER = "fast-topical-ntriples-marc-v1"
_FAST_IRI_BASE = "http://id.worldcat.org/fast/"
_FAST_PREF_LABEL = f"{SKOS}prefLabel"
_FAST_ALT_LABEL = f"{SKOS}altLabel"
_FAST_BROADER = f"{SKOS}broader"
_FAST_DEPRECATED = f"{OWL}deprecated"
_FAST_IDENTIFIER = f"{DCTERMS}identifier"
_FAST_MARC_ID = re.compile(r"^fst0*(\d+)$")
_FAST_MARC_LINK = re.compile(r"\(OCoLC\)fst0*(\d+)")
_FAST_HEADING_TAGS = frozenset(
    {"100", "110", "111", "130", "147", "148", "150", "151", "155"}
)
_FAST_ALT_TAGS = frozenset(
    {"400", "410", "411", "430", "447", "448", "450", "451", "455"}
)
_FAST_LINK_TAGS = frozenset(
    {"500", "510", "511", "530", "547", "548", "550", "551", "555"}
)
_FAST_CONTENT_CODES = frozenset("abcdefghjklmnopqrstu")
_FAST_SUBDIVISION_CODES = frozenset("vxyz")
_FAST_CHANGE_COUNTS = {
    "sha256:f53c640767cb1c4c0bce85b85a69e382780a65772d4deae30ab3a1a8fa96419a": 3_276,
    "sha256:06ae6714240ac1d8126cfeff5392feb8004f6a1d16e2bb392c854ecf47a6a011": 2_153,
    "sha256:0d505664fe5de155d58bd1c178e65112ee4b42067044b6a4cb14f516ef03f116": 4_350,
    "sha256:98c965420836f0f21aed18599f0216cc61b2f3c2b7ca06cc10f6b9cc1ad374e3": 12_633,
}


def _fast_legacy_id(numeric_id: str) -> str:
    return f"fst{int(numeric_id):08d}"


def _fast_marc_numeric_id(record: Any) -> str:
    fields = record.get_fields("001")
    if len(fields) != 1:
        raise ValueError("FAST MARC record must contain exactly one 001 field")
    match = _FAST_MARC_ID.fullmatch(fields[0].value())
    if match is None:
        raise ValueError(f"FAST MARC 001 is malformed: {fields[0].value()!r}")
    return str(int(match.group(1)))


def _fast_render_marc_heading(field: Any) -> str:
    rendered = ""
    for subfield in field.subfields:
        value = " ".join(subfield.value.split())
        if not value:
            continue
        if subfield.code in _FAST_SUBDIVISION_CODES:
            rendered += f"--{value}"
        elif subfield.code in _FAST_CONTENT_CODES:
            if rendered and not rendered.endswith((" ", "--")):
                rendered += " "
            rendered += value
    if not rendered:
        raise ValueError(f"FAST MARC {field.tag} has no heading content")
    return rendered


def _fast_marc_link_ids(field: Any) -> tuple[str, ...]:
    ids: list[str] = []
    for value in field.get_subfields("0"):
        for match in _FAST_MARC_LINK.finditer(value):
            numeric_id = str(int(match.group(1)))
            if numeric_id not in ids:
                ids.append(numeric_id)
    return tuple(ids)


def _fast_validate_marc_identity(record: Any, numeric_id: str) -> None:
    if record.leader[6] != "z":
        raise ValueError(f"FAST MARC {numeric_id} is not an authority record")
    if not any(
        value == "fast"
        for field in record.get_fields("040")
        for value in field.get_subfields("f")
    ):
        raise ValueError(f"FAST MARC {numeric_id} lacks 040 $f fast")
    headings = [field for field in record.fields if field.tag in _FAST_HEADING_TAGS]
    if len(headings) > 1:
        raise ValueError(f"FAST MARC {numeric_id} has multiple 1XX headings")
    uri_values = [
        value
        for field in record.get_fields("024")
        for value in field.get_subfields("a")
    ]
    if uri_values != [f"{_FAST_IRI_BASE}{numeric_id}"]:
        raise ValueError(f"FAST MARC {numeric_id} 024 does not match 001")


def _fast_row_from_marc(record: Any, numeric_id: str) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    topical = record.get_fields("150")
    if len(topical) != 1:
        raise ValueError(f"FAST topical MARC {numeric_id} must have one 150")
    alternate = tuple(
        dict.fromkeys(
            _fast_render_marc_heading(field)
            for field in record.fields
            if field.tag in _FAST_ALT_TAGS
        )
    )
    broader: list[str] = []
    for marc_field in record.fields:
        if marc_field.tag not in _FAST_LINK_TAGS or not any(
            value.startswith("g") for value in marc_field.get_subfields("w")
        ):
            continue
        for target in _fast_marc_link_ids(marc_field):
            if target not in broader:
                broader.append(target)
    return _fast_render_marc_heading(topical[0]), alternate, tuple(broader)


def _read_fast_topical_native(
    spec: SourceSpec,
    authenticated_payloads: Mapping[SourcePin, bytes],
) -> PublisherView:
    """Rebuild the current FAST Topical snapshot with rdflib and pymarc."""
    import rdflib
    from pymarc import MARCReader
    from rdflib.plugins.parsers.ntriples import W3CNTriplesParser

    base_pins = [pin for pin in spec.inputs if pin.role == "publisherBase"]
    change_pins = [pin for pin in spec.inputs if pin.role == "publisherChange"]
    if len(base_pins) != 1 or not change_pins:
        raise ValueError("FAST reader requires one base and chronological MARC changes")
    base_pin = base_pins[0]
    labels: dict[str, str] = {}
    alternate: dict[str, list[str]] = defaultdict(list)
    broader: dict[str, list[str]] = defaultdict(list)
    deprecated: set[str] = set()
    ignored_predicates: Counter[str] = Counter()

    class FastSink:
        def triple(self, subject: Any, predicate: Any, obj: Any) -> None:
            subject_iri = str(subject)
            if not subject_iri.startswith(_FAST_IRI_BASE):
                return
            numeric_id = subject_iri.removeprefix(_FAST_IRI_BASE)
            if not numeric_id.isdigit():
                return
            predicate_iri = str(predicate)
            if predicate_iri == _FAST_PREF_LABEL and isinstance(obj, rdflib.Literal):
                labels.setdefault(numeric_id, str(obj))
            elif predicate_iri == _FAST_ALT_LABEL and isinstance(obj, rdflib.Literal):
                value = str(obj)
                if value not in alternate[numeric_id]:
                    alternate[numeric_id].append(value)
            elif (
                predicate_iri == _FAST_BROADER
                and isinstance(obj, rdflib.URIRef)
                and str(obj).startswith(_FAST_IRI_BASE)
                and str(obj).removeprefix(_FAST_IRI_BASE).isdigit()
            ):
                target = str(int(str(obj).removeprefix(_FAST_IRI_BASE)))
                if target not in broader[numeric_id]:
                    broader[numeric_id].append(target)
            elif predicate_iri == _FAST_IDENTIFIER and isinstance(obj, rdflib.Literal):
                if str(obj) != numeric_id:
                    raise ValueError(
                        f"FAST identifier {obj!r} does not match {subject_iri}"
                    )
            elif predicate_iri == _FAST_DEPRECATED:
                deprecated.add(numeric_id)
            else:
                ignored_predicates[predicate_iri] += 1

    payload = authenticated_payloads[base_pin]
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            nt_members = [
                name for name in archive.namelist() if name.lower().endswith(".nt")
            ]
            if nt_members != ["FASTTopical.nt"]:
                raise ValueError(f"FAST base ZIP members differ: {nt_members!r}")
            with archive.open("FASTTopical.nt") as source:
                W3CNTriplesParser(FastSink()).parse(source)
    except (OSError, zipfile.BadZipFile) as error:
        raise ValueError(f"FAST base ZIP is malformed: {error}") from error
    rows: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {}
    for numeric_id, heading in labels.items():
        if numeric_id in deprecated:
            continue
        rows[numeric_id] = (
            heading,
            tuple(alternate.get(numeric_id, ())),
            tuple(broader.get(numeric_id, ())),
        )
    if base_pin.sha256.endswith("217826c90649895bfca71e81e2ed88919b2e061646ec42a185bc12d0bd3c19db") and len(rows) != 440_612:
        raise ValueError(f"FAST base active count differs: observed {len(rows)}")
    ignored_marc_tags: Counter[str] = Counter()
    for pin in change_pins:
        reader = MARCReader(
            io.BytesIO(authenticated_payloads[pin]),
            to_unicode=True,
            force_utf8=False,
            utf8_handling="strict",
            permissive=False,
        )
        record_count = 0
        for record in reader:
            record_count += 1
            if record is None:
                raise ValueError(f"{pin.path} contains an unreadable MARC record")
            numeric_id = _fast_marc_numeric_id(record)
            _fast_validate_marc_identity(record, numeric_id)
            status = record.leader[5]
            if status not in {"c", "n", "x", "d"}:
                raise ValueError(
                    f"FAST MARC {numeric_id} has unsupported status {status!r}"
                )
            is_topical = bool(record.get_fields("150"))
            if status in {"x", "d"}:
                if is_topical or numeric_id in rows:
                    rows.pop(numeric_id, None)
            elif is_topical:
                rows[numeric_id] = _fast_row_from_marc(record, numeric_id)
            elif numeric_id in rows:
                rows.pop(numeric_id)
            used_tags = {
                "001",
                "024",
                "040",
                *_FAST_HEADING_TAGS,
                *_FAST_ALT_TAGS,
                *_FAST_LINK_TAGS,
            }
            for marc_field in record.fields:
                if marc_field.tag not in used_tags:
                    ignored_marc_tags[marc_field.tag] += 1
        expected_count = _FAST_CHANGE_COUNTS.get(pin.sha256)
        if expected_count is not None and record_count != expected_count:
            raise ValueError(
                f"{pin.path} record count differs: expected {expected_count}, "
                f"observed {record_count}"
            )
    if base_pin.sha256.endswith("217826c90649895bfca71e81e2ed88919b2e061646ec42a185bc12d0bd3c19db") and len(rows) != 441_127:
        raise ValueError(f"FAST current active count differs: observed {len(rows)}")

    active_ids = frozenset(rows)
    relations = {
        (
            f"{_FAST_IRI_BASE}{numeric_id}",
            _FAST_BROADER,
            f"{_FAST_IRI_BASE}{target}",
        )
        for numeric_id, (_, _, targets) in rows.items()
        for target in targets
        if target in active_ids
    }
    labels.clear()
    alternate.clear()
    broader.clear()
    deprecated.clear()
    del active_ids

    def stock_records() -> Iterator[_StockVocabularyRecord]:
        for numeric_id, (heading, alt_labels, broader_ids) in rows.items():
            resource = f"{_FAST_IRI_BASE}{numeric_id}"
            preferred_value = heading.strip()
            seen = {preferred_value}
            output_alt: list[LiteralValue] = []
            for value in alt_labels:
                stripped = value.strip()
                if stripped and stripped not in seen:
                    seen.add(stripped)
                    output_alt.append(_literal_value(stripped, None, None))
            native_payload = {
                "altLabels": list(alt_labels),
                "broaderIds": list(broader_ids),
                "heading": heading,
                "identityStatus": "publisherIdentifierVerified",
                "legacyFstId": _fast_legacy_id(numeric_id),
                "numericId": numeric_id,
                "publisherIri": resource,
            }
            yield _StockVocabularyRecord(
                resource=resource,
                preferred_labels=(
                    _literal_value(preferred_value, None, None),
                ),
                alternate_labels=tuple(output_alt),
                notations=(
                    _literal_value(numeric_id, None, None),
                    _literal_value(_fast_legacy_id(numeric_id), None, None),
                ),
                annotations=(),
                source_locator=resource,
                source_digest=_canonical_json_digest(native_payload),
                native_payload=native_payload,
            )

    unevaluated = tuple(
        [
            f"FAST base contains {count} authenticated but unrepresented {predicate} claims"
            for predicate, count in sorted(ignored_predicates.items())
            if count
        ]
        + [
            f"FAST changes contain {count} authenticated but unrepresented MARC {tag} fields"
            for tag, count in sorted(ignored_marc_tags.items())
            if count
        ]
    )
    return _stock_vocabulary_view(
        stock_records(),
        relations,
        (),
        spec.inputs,
        unevaluated_claims=unevaluated,
        retain_predicate_counts=False,
        retain_claim_sets=False,
        retain_expected_native_payloads=False,
        compact_resource_digests=True,
    )


CRS_SOURCE_CONCEPT_RELEASE_READER = "crs-source-concept-release-json-v1"
ICPSR_MANAGED_RELEASE_READER = "icpsr-managed-release-json-v1"


def _json_without_duplicates(payload: bytes, label: str) -> Any:
    """Parse JSON while rejecting duplicate object keys."""

    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} repeats field {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(payload, object_pairs_hook=object_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not UTF-8 JSON: {error}") from error


def _canonical_json_line(value: Any) -> bytes:
    """Return the newline-terminated canonical JSON used by CRS bundles."""
    return _canonical_json_bytes(value) + b"\n"


def _read_canonical_json_lines(payload: bytes, label: str) -> list[Mapping[str, Any]]:
    """Read one CRS JSONL artifact without importing its production reader."""
    rows: list[Mapping[str, Any]] = []
    rebuilt = bytearray()
    for line_number, line in enumerate(payload.splitlines(), start=1):
        if not line:
            raise ValueError(f"{label} line {line_number} is blank")
        row = _json_without_duplicates(line, f"{label} line {line_number}")
        if not isinstance(row, Mapping):
            raise ValueError(f"{label} line {line_number} is not an object")
        rebuilt.extend(_canonical_json_line(row))
        rows.append(row)
    if bytes(rebuilt) != payload:
        raise ValueError(f"{label} bytes are not canonical newline-terminated JSONL")
    return rows


def _crs_artifact_path(root: Path, relative_path: Any, label: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path:
        raise ValueError(f"{label} has no path")
    relative = Path(relative_path)
    if (
        relative.is_absolute()
        or "\\" in relative_path
        or "://" in relative_path
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ValueError(f"{label} path is unsafe: {relative_path!r}")
    return root.joinpath(*relative.parts)


def _read_crs_source_concept_release(
    spec: SourceSpec,
    authenticated_payloads: Mapping[SourcePin, bytes],
) -> PublisherView:
    """Authenticate a CRS managed JSON bundle and reverse its selected records."""
    if len(spec.inputs) != 1:
        raise ValueError("CRS source-concept release reader requires one manifest input")
    pin = spec.inputs[0]
    manifest_payload = authenticated_payloads[pin]
    manifest = _json_without_duplicates(manifest_payload, pin.path)
    if not isinstance(manifest, Mapping):
        raise ValueError("CRS source-concept bundle manifest must be an object")
    if manifest_payload != _canonical_json_line(manifest):
        raise ValueError("CRS source-concept bundle manifest is not canonical")
    if set(manifest) != {
        "artifacts",
        "logicalDigest",
        "packageKind",
        "releaseDigest",
        "releaseId",
        "schemaVersion",
    }:
        raise ValueError("CRS source-concept bundle manifest shape differs")
    if (
        manifest.get("schemaVersion") != "1.0"
        or manifest.get("packageKind") != "sourceConceptRelease"
    ):
        raise ValueError("CRS source-concept bundle version differs")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("CRS source-concept bundle artifacts must be an array")

    root = Path(pin.path).parent
    retained_paths = {
        "concepts.jsonl",
        "lifecycle.jsonl",
        "reconciliation.json",
        "release-manifest.json",
        "rights.jsonl",
        "source/bundle-manifest.json",
        "source/observations.jsonl",
        "source/resource-manifest.json",
    }
    retained: dict[str, bytes] = {}
    roles: dict[str, str] = {}
    expected_paths = {"bundle-manifest.json"}
    descriptor_digests: dict[str, str] = {}
    descriptor_lengths: dict[str, int] = {}
    for index, descriptor in enumerate(artifacts):
        label = f"CRS artifact {index}"
        if not isinstance(descriptor, Mapping) or set(descriptor) != {
            "byteLength",
            "path",
            "role",
            "sha256",
        }:
            raise ValueError(
                f"{label} must contain byteLength, path, role, and sha256"
            )
        relative_path = descriptor.get("path")
        artifact_path = _crs_artifact_path(root, relative_path, label)
        relative_text = str(relative_path)
        if relative_text in expected_paths:
            raise ValueError(f"CRS bundle repeats artifact path {relative_text!r}")
        expected_paths.add(relative_text)
        if artifact_path.is_symlink() or not artifact_path.is_file():
            raise ValueError(f"CRS artifact is not a regular file: {relative_text}")
        payload = artifact_path.read_bytes()
        digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        if (
            descriptor.get("byteLength") != len(payload)
            or descriptor.get("sha256") != digest
        ):
            raise ValueError(f"CRS artifact pin differs for {relative_text}")
        role = descriptor.get("role")
        if not isinstance(role, str) or not role:
            raise ValueError(f"{label} has no role")
        roles[relative_text] = role
        descriptor_digests[relative_text] = digest
        descriptor_lengths[relative_text] = len(payload)
        if relative_text in retained_paths:
            retained[relative_text] = payload

    actual_paths: set[str] = set()
    for item in root.rglob("*"):
        if item.is_symlink():
            raise ValueError(f"CRS source-concept bundle contains a symlink: {item}")
        if item.is_file():
            actual_paths.add(item.relative_to(root).as_posix())
    if actual_paths != expected_paths:
        raise ValueError("CRS source-concept bundle file set differs from its manifest")
    missing = sorted(retained_paths - retained.keys())
    if missing:
        raise ValueError(f"CRS source-concept bundle lacks required artifacts: {missing}")
    expected_roles = {
        "concepts.jsonl": "concepts",
        "lifecycle.jsonl": "lifecycle",
        "reconciliation.json": "reconciliation",
        "release-manifest.json": "releaseManifest",
        "rights.jsonl": "rights",
        "source/bundle-manifest.json": "sourceCaptureArtifact",
        "source/observations.jsonl": "sourceCaptureArtifact",
        "source/resource-manifest.json": "sourceCaptureArtifact",
    }
    if any(roles.get(path) != role for path, role in expected_roles.items()):
        raise ValueError("CRS source-concept bundle core artifact roles differ")
    if any(
        role
        not in {
            "concepts",
            "lifecycle",
            "reconciliation",
            "releaseManifest",
            "rights",
            "sourceCaptureArtifact",
        }
        for role in roles.values()
    ):
        raise ValueError("CRS source-concept bundle contains an unsupported artifact role")

    release = _json_without_duplicates(
        retained["release-manifest.json"],
        "CRS source-concept release manifest",
    )
    resource_manifest = _json_without_duplicates(
        retained["source/resource-manifest.json"],
        "CRS source resource manifest",
    )
    source_bundle_manifest = _json_without_duplicates(
        retained["source/bundle-manifest.json"],
        "CRS nested source bundle manifest",
    )
    reconciliation = _json_without_duplicates(
        retained["reconciliation.json"],
        "CRS source-concept reconciliation",
    )
    if not all(
        isinstance(value, Mapping)
        for value in (release, resource_manifest, source_bundle_manifest, reconciliation)
    ):
        raise ValueError("CRS release, resource, or reconciliation manifest is not an object")
    for value, payload, label in (
        (release, retained["release-manifest.json"], "CRS release manifest"),
        (
            resource_manifest,
            retained["source/resource-manifest.json"],
            "CRS source resource manifest",
        ),
        (
            source_bundle_manifest,
            retained["source/bundle-manifest.json"],
            "CRS nested source bundle manifest",
        ),
        (
            reconciliation,
            retained["reconciliation.json"],
            "CRS reconciliation",
        ),
    ):
        if payload != _canonical_json_line(value):
            raise ValueError(f"{label} is not canonical")

    concepts = _read_canonical_json_lines(
        retained["concepts.jsonl"],
        "CRS concepts",
    )
    observations = _read_canonical_json_lines(
        retained["source/observations.jsonl"],
        "CRS observations",
    )
    rights = _read_canonical_json_lines(retained["rights.jsonl"], "CRS rights")
    lifecycle = _read_canonical_json_lines(
        retained["lifecycle.jsonl"],
        "CRS lifecycle",
    )
    if release.get("conceptCount") != len(concepts):
        raise ValueError("CRS release conceptCount differs from concepts.jsonl")
    if release.get("rightsRecordCount") != len(rights):
        raise ValueError("CRS release rightsRecordCount differs from rights.jsonl")
    if release.get("lifecycleRecordCount") != len(lifecycle):
        raise ValueError("CRS release lifecycleRecordCount differs from lifecycle.jsonl")
    for field_name, path in (
        ("conceptSetDigest", "concepts.jsonl"),
        ("rightsSetDigest", "rights.jsonl"),
        ("lifecycleSetDigest", "lifecycle.jsonl"),
    ):
        if release.get(field_name) != descriptor_digests[path]:
            raise ValueError(f"CRS release {field_name} differs from sealed artifact")
    source_capture = release.get("sourceCapture")
    if not isinstance(source_capture, Mapping):
        raise ValueError("CRS release sourceCapture must be an object")
    if source_capture.get("observationSetDigest") != descriptor_digests[
        "source/observations.jsonl"
    ]:
        raise ValueError("CRS release observationSetDigest differs from sealed observations")
    if source_capture.get("reconciliationDigest") != descriptor_digests[
        "reconciliation.json"
    ]:
        raise ValueError("CRS release reconciliationDigest differs from sealed record")
    nested_artifacts = source_bundle_manifest.get("artifacts")
    if not isinstance(nested_artifacts, list):
        raise ValueError("CRS nested source bundle artifacts must be an array")
    nested_paths: set[str] = set()
    for index, descriptor in enumerate(nested_artifacts):
        if not isinstance(descriptor, Mapping):
            raise ValueError(f"CRS nested source artifact {index} is not an object")
        relative_path = descriptor.get("path")
        _crs_artifact_path(root / "source", relative_path, f"CRS nested artifact {index}")
        outer_path = f"source/{relative_path}"
        if not isinstance(relative_path, str) or relative_path in nested_paths:
            raise ValueError("CRS nested source artifact path repeats or is missing")
        nested_paths.add(relative_path)
        if (
            descriptor.get("sha256") != descriptor_digests.get(outer_path)
            or descriptor.get("byteLength") != descriptor_lengths.get(outer_path)
            or roles.get(outer_path) != "sourceCaptureArtifact"
        ):
            raise ValueError(
                f"CRS nested source artifact differs from outer pin: {relative_path}"
            )
    outer_source_paths = {
        path.removeprefix("source/")
        for path in roles
        if path.startswith("source/") and path != "source/bundle-manifest.json"
    }
    if nested_paths != outer_source_paths:
        raise ValueError("CRS nested and outer source artifact sets differ")
    if (
        source_bundle_manifest.get("packageKind") != "sourceControlledResource"
        or source_bundle_manifest.get("schemaVersion") != "2.0"
        or source_capture.get("logicalDigest")
        != source_bundle_manifest.get("logicalDigest")
        or source_capture.get("resourceManifest") != resource_manifest.get("id")
        or source_bundle_manifest.get("resourceManifest")
        != resource_manifest.get("id")
    ):
        raise ValueError("CRS nested source bundle identity differs")
    if release.get("sourceScheme") != resource_manifest.get("sourceScheme"):
        raise ValueError("CRS release sourceScheme differs from its source capture")

    release_basis = dict(release)
    release_id = release_basis.pop("id", None)
    release_digest = release_basis.pop("releaseDigest", None)
    expected_release_digest = "sha256:" + hashlib.sha256(
        _canonical_json_line(release_basis)
    ).hexdigest()
    semantic_ring = release.get("semanticRing")
    expected_release_id = (
        f"urn:ref:source-concept-release:{semantic_ring}:"
        f"{expected_release_digest.removeprefix('sha256:')}"
    )
    if release_digest != expected_release_digest or release_id != expected_release_id:
        raise ValueError("CRS release identity differs from its canonical facts")
    if (
        manifest.get("releaseDigest") != release_digest
        or manifest.get("releaseId") != release_id
    ):
        raise ValueError("CRS bundle and release identities differ")

    observation_by_id: dict[str, Mapping[str, Any]] = {}
    for observation in observations:
        observation_id = observation.get("id")
        if not isinstance(observation_id, str) or not observation_id:
            raise ValueError("CRS observation has no id")
        if observation_id in observation_by_id:
            raise ValueError(f"CRS observations repeat id {observation_id!r}")
        observation_by_id[observation_id] = observation
    selected_ids = sorted(str(concept.get("sourceObservation")) for concept in concepts)
    selected_digest = "sha256:" + hashlib.sha256(
        _canonical_json_line(selected_ids)
    ).hexdigest()
    if release.get("selectedObservationSetDigest") != selected_digest:
        raise ValueError("CRS selectedObservationSetDigest differs from concept bindings")

    source_scheme = release.get("sourceScheme")
    scheme_iri = source_scheme.get("id") if isinstance(source_scheme, Mapping) else None
    namespace_tokens = {
        "http://id.loc.gov/vocabulary/subjectSchemes/lst": "loc-lst",
        "http://id.loc.gov/vocabulary/subjectSchemes/cgpa": "loc-cgpa",
    }
    namespace_token = namespace_tokens.get(scheme_iri)
    if namespace_token is None:
        raise ValueError(f"CRS source scheme is unsupported: {scheme_iri!r}")
    namespace_digest = hashlib.sha256(str(scheme_iri).encode("utf-8")).hexdigest()
    if [str(concept.get("id")) for concept in concepts] != sorted(
        str(concept.get("id")) for concept in concepts
    ):
        raise ValueError("CRS concepts are not sorted by id")

    def records() -> Iterator[_StockVocabularyRecord]:
        for concept in concepts:
            required_concept_fields = {
                "id",
                "identityKind",
                "issuer",
                "localRecordId",
                "semanticRing",
                "sourceObservation",
                "sourceObservationDigest",
                "sourceScheme",
                "type",
            }
            if set(concept) != required_concept_fields:
                raise ValueError("CRS source-scoped concept fields differ")
            observation_id = concept.get("sourceObservation")
            observation = observation_by_id.get(str(observation_id))
            if observation is None:
                raise ValueError(
                    f"CRS concept names unavailable observation {observation_id!r}"
                )
            observation_digest = "sha256:" + hashlib.sha256(
                _canonical_json_line(observation)
            ).hexdigest()
            if concept.get("sourceObservationDigest") != observation_digest:
                raise ValueError("CRS concept sourceObservationDigest differs")
            local_record_id = concept.get("localRecordId")
            if (
                not isinstance(local_record_id, str)
                or not local_record_id.startswith("urn:uuid:")
            ):
                raise ValueError("CRS concept localRecordId is not a UUID URN")
            try:
                local_uuid = uuid.UUID(local_record_id.removeprefix("urn:uuid:"))
            except ValueError as error:
                raise ValueError("CRS concept localRecordId is invalid") from error
            if local_uuid.version != 7 or str(local_uuid) != local_record_id.removeprefix(
                "urn:uuid:"
            ):
                raise ValueError("CRS concept localRecordId is not canonical UUIDv7")
            expected_prior_iri = (
                f"urn:ref:source-concept:v1:{namespace_digest}:{local_uuid}"
            )
            if (
                concept.get("id") != expected_prior_iri
                or concept.get("identityKind") != "refspecSourceScoped"
                or concept.get("issuer") != "https://refspec.org/"
                or concept.get("semanticRing") != semantic_ring
                or concept.get("sourceScheme") != scheme_iri
                or concept.get("type") != "SourceScopedConcept"
                or observation.get("localRecordId") != local_record_id
            ):
                raise ValueError("CRS concept identity or source binding differs")
            labels = observation.get("labels")
            if not isinstance(labels, list) or not labels:
                raise ValueError("CRS selected observation has no labels")
            preferred: list[LiteralValue] = []
            alternate: list[LiteralValue] = []
            for label in labels:
                if not isinstance(label, Mapping) or set(label) != {
                    "language",
                    "role",
                    "value",
                }:
                    raise ValueError("CRS selected observation label shape differs")
                value = label.get("value")
                language = label.get("language")
                role = label.get("role")
                if not isinstance(value, str) or not value or language != "en":
                    raise ValueError(
                        "CRS reader supports only the sealed English observation profile"
                    )
                literal = _literal_value(value, "en", None)
                if role == "preferred":
                    preferred.append(literal)
                elif role == "alternate":
                    alternate.append(literal)
                else:
                    raise ValueError(f"CRS selected label role is unsupported: {role!r}")
            definition = observation.get("definition")
            if definition is not None and not isinstance(definition, str):
                raise ValueError("CRS selected observation definition is not text")
            resource = (
                f"urn:ref:source-concept:v2:{namespace_token}:"
                f"{local_record_id.removeprefix('urn:uuid:')}"
            )
            native_payload = {
                "englishOnlyObservation": dict(observation),
                "sourceEvidence": {
                    "droppedLanguageContentDigest": _canonical_json_digest([]),
                    "droppedLanguageValueCount": 0,
                    "languageNormalizationAlgorithm": (
                        "recursiveLanguageMapsAndTaggedValuesV1"
                    ),
                    "originalObservationDigest": _canonical_json_digest(observation),
                    "sourceTextLanguage": "en",
                },
                "sourceIdentity": {
                    "identityKind": "refspecSourceScoped",
                    "localRecordId": local_record_id,
                    "namespaceToken": namespace_token,
                    "priorSourceConceptIri": expected_prior_iri,
                    "sourceScheme": scheme_iri,
                },
            }
            annotations = (
                (
                    (SKOS_DEFINITION, _literal_value(definition, "en", None)),
                )
                if definition
                else ()
            )
            yield _StockVocabularyRecord(
                resource=resource,
                preferred_labels=tuple(preferred),
                alternate_labels=tuple(alternate),
                notations=(),
                annotations=annotations,
                source_locator=str(observation_id),
                source_digest=_canonical_json_digest(native_payload),
                native_payload=native_payload,
                is_skos_concept=semantic_ring == "subject",
            )

    unselected_count = len(observations) - len(concepts)
    unevaluated = (
        *(
            (
                f"CRS managed release contains {unselected_count} authenticated source observations outside its selected concept set",
            )
            if unselected_count
            else ()
        ),
        "CRS sourceObservationDigest values are independently verified against the selected observations; Atlas sourceDigest instead seals the reconstructed native payload",
        "CRS raw Congress.gov captures are authenticated transitively through the closed bundle but are not reparsed by this managed-release reader",
        "CRS rights, lifecycle, reconciliation, and source-capture logicalDigest claims are authenticated but are not Atlas member claims",
    )
    return _stock_vocabulary_view(
        records(),
        (),
        (),
        spec.inputs,
        unevaluated_claims=unevaluated,
        additional_literal_claims=(
            (
                str(release_id),
                f"{DCTERMS}identifier",
                _literal_value(str(release_id), None, None),
            ),
        ),
    )


def _verify_canonical_json_seal(value: Mapping[str, Any], label: str) -> None:
    observed = value.get("canonicalPayloadDigest")
    unsigned = dict(value)
    unsigned.pop("canonicalPayloadDigest", None)
    expected = _canonical_json_digest(unsigned)
    if observed != expected:
        raise ValueError(
            f"{label} canonicalPayloadDigest differs: expected {expected}, "
            f"observed {observed!r}"
        )


def _icpsr_index_identifier(value: Mapping[str, Any]) -> Mapping[str, Any]:
    keys = {
        "authorityUri": "authority_uri",
        "effectiveAt": "effective_at",
        "kind": "kind",
        "observedAt": "observed_at",
        "sourceDigest": "source_digest",
        "sourceUri": "source_uri",
        "value": "value",
    }
    if set(value) != set(keys):
        raise ValueError(f"ICPSR managed identifier fields differ: {sorted(value)}")
    return {target: value[source] for source, target in keys.items()}


def _read_icpsr_managed_release(
    spec: SourceSpec,
    authenticated_payloads: Mapping[SourcePin, bytes],
) -> PublisherView:
    """Authenticate a managed release and compare its sealed concept records."""
    if len(spec.inputs) != 1:
        raise ValueError("ICPSR managed release reader requires one manifest input")
    pin = spec.inputs[0]
    manifest = _json_without_duplicates(authenticated_payloads[pin], pin.path)
    if not isinstance(manifest, Mapping):
        raise ValueError("ICPSR managed release manifest must be an object")
    _verify_canonical_json_seal(manifest, "ICPSR managed release manifest")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("ICPSR managed release artifacts must be an array")
    manifest_path = Path(pin.path)
    root = manifest_path.parent
    artifact_payloads: dict[str, bytes] = {}
    for index, descriptor in enumerate(artifacts):
        if not isinstance(descriptor, Mapping):
            raise ValueError(f"ICPSR artifact {index} must be an object")
        relative_path = descriptor.get("path")
        digest = descriptor.get("sha256")
        byte_length = descriptor.get("byteLength")
        if not isinstance(relative_path, str):
            raise ValueError(f"ICPSR artifact {index} has no path")
        path_parts = Path(relative_path).parts
        if (
            Path(relative_path).is_absolute()
            or not path_parts
            or any(part in {"", ".", ".."} for part in path_parts)
        ):
            raise ValueError(f"ICPSR artifact path is unsafe: {relative_path!r}")
        artifact_path = root / relative_path
        if artifact_path.is_symlink() or not artifact_path.is_file():
            raise ValueError(f"ICPSR artifact is not a regular file: {relative_path}")
        payload = artifact_path.read_bytes()
        observed_digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        if len(payload) != byte_length or observed_digest != digest:
            raise ValueError(
                f"ICPSR artifact pin differs for {relative_path}: "
                f"observed=({len(payload)}, {observed_digest})"
            )
        if relative_path in artifact_payloads:
            raise ValueError(f"ICPSR artifact path repeats: {relative_path}")
        artifact_payloads[relative_path] = payload
    required = {
        "records/concepts.jsonl",
        "records/coverage.json",
        "sources/index/manifest.json",
        "sources/subject.xml",
    }
    missing_artifacts = sorted(required - artifact_payloads.keys())
    if missing_artifacts:
        raise ValueError(f"ICPSR managed release lacks artifacts: {missing_artifacts}")
    coverage = _json_without_duplicates(
        artifact_payloads["records/coverage.json"],
        "ICPSR coverage",
    )
    if not isinstance(coverage, Mapping):
        raise ValueError("ICPSR coverage must be an object")
    _verify_canonical_json_seal(coverage, "ICPSR coverage")
    release = manifest.get("release")
    sources = manifest.get("sources")
    counts = manifest.get("counts")
    gaps = coverage.get("gaps")
    if not all(isinstance(value, Mapping) for value in (release, sources, counts, gaps)):
        raise ValueError("ICPSR manifest or coverage structural fields are missing")
    scheme_iri = release.get("schemeIri")
    if not isinstance(scheme_iri, str):
        raise ValueError("ICPSR managed release has no scheme IRI")
    index_manifest_digest = (
        "sha256:"
        + hashlib.sha256(artifact_payloads["sources/index/manifest.json"]).hexdigest()
    )
    subject_xml_digest = (
        "sha256:"
        + hashlib.sha256(artifact_payloads["sources/subject.xml"]).hexdigest()
    )
    if sources.get("indexManifestDigest") != index_manifest_digest:
        raise ValueError("ICPSR index manifest digest differs from authenticated artifact")
    if sources.get("xmlDigest") != subject_xml_digest:
        raise ValueError("ICPSR subject XML digest differs from authenticated artifact")

    concepts: list[Mapping[str, Any]] = []
    for line_number, line in enumerate(
        artifact_payloads["records/concepts.jsonl"].splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        row = _json_without_duplicates(line, f"ICPSR concept line {line_number}")
        if not isinstance(row, Mapping):
            raise ValueError(f"ICPSR concept line {line_number} is not an object")
        concepts.append(row)
    expected_concepts = counts.get("concepts")
    if expected_concepts != len(concepts):
        raise ValueError(
            f"ICPSR managed concept count differs: declared {expected_concepts!r}, "
            f"observed {len(concepts)}"
        )
    raw_relations: list[tuple[str, str, str, Mapping[str, Any]]] = []
    unresolved_relations = 0
    for concept in concepts:
        resource = concept.get("conceptIri")
        source_label = concept.get("officialLabel")
        local_number = concept.get("sourceLocalRecordNumber")
        rows = concept.get("relations")
        if (
            not isinstance(resource, str)
            or not isinstance(source_label, str)
            or not isinstance(local_number, str)
            or not isinstance(rows, list)
        ):
            raise ValueError("ICPSR managed concept identity or relations differ")
        for relation in rows:
            if not isinstance(relation, Mapping):
                raise ValueError(f"ICPSR {resource} relation must be an object")
            relation_name = relation.get("relation")
            target = relation.get("targetConceptIri")
            target_label = relation.get("targetLabel")
            if not isinstance(relation_name, str) or not isinstance(target_label, str):
                raise ValueError(f"ICPSR {resource} relation shape differs")
            if relation.get("resolutionStatus") != "uriVerified":
                unresolved_relations += 1
                continue
            if not isinstance(target, str):
                raise ValueError(f"ICPSR {resource} verified relation has no target IRI")
            raw_relations.append(
                (
                    resource,
                    relation_name,
                    target,
                    {
                        "relation": relation_name,
                        "sourceLabel": source_label,
                        "sourceLocalRecordNumber": local_number,
                        "sourcePath": f"subject.xml#record={local_number}",
                        "targetLabel": target_label,
                    },
                )
            )
    broader_graph: dict[str, set[str]] = defaultdict(set)
    for subject, relation_name, target, _ in raw_relations:
        if relation_name == "broader":
            broader_graph[subject].add(target)
        elif relation_name == "narrower":
            broader_graph[target].add(subject)
    ancestor_cache: dict[str, frozenset[str]] = {}

    def ancestors(start: str) -> frozenset[str]:
        cached = ancestor_cache.get(start)
        if cached is not None:
            return cached
        found: set[str] = set()
        pending = list(broader_graph.get(start, ()))
        while pending:
            target = pending.pop()
            if target in found:
                continue
            found.add(target)
            pending.extend(broader_graph.get(target, ()))
        result = frozenset(found)
        ancestor_cache[start] = result
        return result

    relation_predicates = {
        "broader": f"{SKOS}broader",
        "narrower": f"{SKOS}narrower",
        "related": f"{SKOS}related",
        "use": f"{ATLAS}thesaurusUse",
        "usedFor": f"{ATLAS}thesaurusUsedFor",
    }
    relations: set[tuple[str, str, str]] = set()
    relation_payloads: dict[str, Mapping[str, Any]] = {}
    for subject, relation_name, target, source_payload in raw_relations:
        predicate = relation_predicates.get(relation_name)
        if predicate is None:
            raise ValueError(f"ICPSR relation kind is unsupported: {relation_name!r}")
        relations.add((subject, predicate, target))
        if relation_name == "related" and (
            target in ancestors(subject) or subject in ancestors(target)
        ):
            relation_digest = _canonical_json_digest(source_payload)
            relation_payloads[relation_digest] = {
                "editorialTransformation": {
                    "fromPredicate": f"{SKOS}related",
                    "reason": "SKOS-S27-hierarchy-path",
                    "rule": "preserveAuthoredAssociationOutsideSkosProjection",
                    "toPredicate": f"{ATLAS}thesaurusRelated",
                },
                "publisherRelation": source_payload,
                "publisherRelationDigest": relation_digest,
            }
    production_manifest = pin.sha256 == (
        "sha256:f3c9f4efa7fd12b6339db9feabb029b17425672293a8fb615999c881673ac12a"
    )
    if production_manifest and len(relation_payloads) != 22:
        raise ValueError(
            f"ICPSR S27 relation count differs: observed {len(relation_payloads)}"
        )

    def records() -> Iterator[_StockVocabularyRecord]:
        for concept in concepts:
            resource = str(concept["conceptIri"])
            official_label = str(concept["officialLabel"])
            official_role = concept.get("officialLabelRole")
            xml_role = concept.get("xmlLabelRole")
            identifiers = concept.get("identifiers")
            if official_role not in {"preferred", "alternate"}:
                raise ValueError(f"ICPSR {resource} official label role differs")
            if xml_role not in {"preferred", "alternate"}:
                raise ValueError(f"ICPSR {resource} XML label role differs")
            if not isinstance(identifiers, list) or not all(
                isinstance(item, Mapping) for item in identifiers
            ):
                raise ValueError(f"ICPSR {resource} identifiers differ")
            relation_labels: dict[str, list[str]] = defaultdict(list)
            for relation in concept["relations"]:
                relation_labels[str(relation["relation"])].append(
                    str(relation["targetLabel"])
                )
            xml_term = {
                "broaderLabels": relation_labels["broader"],
                "inputTimestamp": concept.get("inputTimestamp"),
                "label": official_label,
                "narrowerLabels": relation_labels["narrower"],
                "preferred": xml_role == "preferred",
                "relatedLabels": relation_labels["related"],
                "scopeNotes": list(concept.get("scopeNotes", ())),
                "sourceLocalRecordNumber": concept.get("sourceLocalRecordNumber"),
                "updateTimestamp": concept.get("updateTimestamp"),
                "useLabels": relation_labels["use"],
                "usedForLabels": relation_labels["usedFor"],
            }
            index_term = {
                "identifiers": [
                    _icpsr_index_identifier(identifier)
                    for identifier in identifiers
                ],
                "label": official_label,
                "preferred": official_role == "preferred",
                "source_letter": concept.get("sourceLetter"),
            }
            source_path = (
                f"index/pages/{concept['sourceLetter']}#term={concept['publisherCode']}"
            )
            native_payload = {
                "identityStatus": "publisherIdentifierVerified",
                "indexTerm": index_term,
                "managedConcept": dict(concept),
                "sourceArtifactDigests": {
                    "indexManifest": index_manifest_digest,
                    "subjectXml": subject_xml_digest,
                },
                "sourcePaths": [
                    source_path,
                    f"subject.xml#record={concept['sourceLocalRecordNumber']}",
                ],
                "sourceScheme": scheme_iri,
                "xmlTerm": xml_term,
            }
            label_literal = _literal_value(official_label, None, None)
            notes = tuple(
                (SKOS_SCOPE_NOTE, _literal_value(str(note), None, None))
                for note in concept.get("scopeNotes", ())
            )
            yield _StockVocabularyRecord(
                resource=resource,
                preferred_labels=(label_literal,) if official_role == "preferred" else (),
                alternate_labels=(label_literal,) if official_role == "alternate" else (),
                notations=(),
                annotations=notes,
                source_locator=resource,
                source_digest=_canonical_json_digest(native_payload),
                native_payload=native_payload,
            )

    index_only = gaps.get("indexOnlyTerms")
    xml_only = gaps.get("xmlOnlyLabels")
    if not isinstance(index_only, list) or not isinstance(xml_only, list):
        raise ValueError("ICPSR coverage gap lists are missing")
    unevaluated = (
        f"ICPSR managed release declares {len(index_only)} index-only union members outside records/concepts.jsonl",
        f"ICPSR managed release declares {len(xml_only)} XML-only union members outside records/concepts.jsonl",
        f"ICPSR managed concepts contain {unresolved_relations} unresolved source-skew relations",
        "ICPSR raw index HTML, subject XML, and indexed-expression artifacts are authenticated transitively but not reparsed by this managed-release reader",
    )
    return _stock_vocabulary_view(
        records(),
        relations,
        (),
        spec.inputs,
        unevaluated_claims=unevaluated,
        require_relation_members=False,
        expected_relation_payloads=relation_payloads,
    )


_PUBLISHER_READERS: Mapping[
    str,
    Callable[[SourceSpec, Mapping[SourcePin, bytes]], PublisherView],
] = {
    API_CAPTURE_JSON_READER: _read_api_capture,
    CRS_SOURCE_CONCEPT_RELEASE_READER: _read_crs_source_concept_release,
    EPA_ENTERPRISE_VOCABULARY_XML_READER: _read_epa_enterprise_vocabulary_xml,
    FAST_TOPICAL_NATIVE_READER: _read_fast_topical_native,
    FEDERAL_REGISTER_TOPICS_JSON_READER: _read_federal_register_topics_json,
    GCMD_SCIENCE_KEYWORDS_CSV_READER: _read_gcmd_science_keywords_csv,
    PATTERN_ROW_READER: _read_pattern_rows,
    ICPSR_MANAGED_RELEASE_READER: _read_icpsr_managed_release,
    LCSH_ALIGNMENT_ENDPOINT_JSONLD_READER: _read_lcsh_alignment_endpoint_jsonld,
    MESH_DESCRIPTOR_XML_READER: _read_mesh_descriptor_xml,
}

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


def _fec_inline_section_pattern(column_name: str, field_label: str) -> str:
    """Build one exact FEC master-file row selector from declared labels."""
    return (
        r"<tr>\s*<td>\s*"
        + re.escape(column_name)
        + r"\s*</td>\s*<td[^>]*>\s*"
        + re.escape(field_label)
        + r"\s*</td>\s*(?:<td[^>]*>.*?</td>\s*){3}"
        + r"<td[^>]*>(?P<region>.*?)</td>\s*"
        + r"<td[^>]*>.*?</td>\s*</tr>"
    )


_FEC_MASTER_PIN = SourcePin(
    path=(
        "tests/fixtures/fec_committee_codes/"
        "fec-committee-master-file-description-2026-08-03.html"
    ),
    sha256=(
        "sha256:dda49be2e360d39bb1b7dcbc53239e627109a26fbaefe172688aca84abc4ff66"
    ),
    byte_length=29_343,
    fmt="html",
    role="publisherSource",
    source_iri=(
        "https://www.fec.gov/campaign-finance-data/"
        "committee-master-file-description/"
    ),
)
_FEC_COMMITTEE_TYPE_PIN = SourcePin(
    path=(
        "tests/fixtures/fec_committee_codes/"
        "fec-committee-type-code-descriptions-2026-08-03.html"
    ),
    sha256=(
        "sha256:84e9f16628fd2475750cd89a3947f2c737a5f66c8ced04aea6b1118ac2aecaa4"
    ),
    byte_length=28_121,
    fmt="html",
    role="publisherSource",
    source_iri=(
        "https://www.fec.gov/campaign-finance-data/"
        "committee-type-code-descriptions/"
    ),
)
_FEC_PARTY_PIN = SourcePin(
    path=(
        "tests/fixtures/fec_committee_codes/"
        "fec-party-code-descriptions-2026-08-03.html"
    ),
    sha256=(
        "sha256:e17420381df0e5709449a8c9702600fde97503ea378ef357beef4c40ed6a6b09"
    ),
    byte_length=29_578,
    fmt="html",
    role="publisherSource",
    source_iri=(
        "https://www.fec.gov/campaign-finance-data/party-code-descriptions/"
    ),
)
_FEC_INLINE_ROW_PATTERN = (
    r"(?:^|<br\s*/?>)\s*(?P<code>[A-Z])\s*=\s*"
    r"(?P<label>.*?)(?=<br\s*/?>|$)"
)
_FEC_TABLE_SECTION_PATTERN = r"<table[^>]*>(?P<region>.*?)</table>"
_FEC_TABLE_ROW_PATTERN = (
    r"<tr>\s*<td[^>]*>\s*(?P<code>[A-Z]{1,3}|[A-Z]/[A-Z])\s*</td>\s*"
    r"<td[^>]*>(?P<label>.*?)</td>\s*"
    r"<td[^>]*>(?P<description>.*?)</td>\s*</tr>"
)
_FEC_PATTERN_ROW_DECLARATIONS = (
    (
        "fec-committee-designation",
        _FEC_MASTER_PIN,
        _fec_inline_section_pattern(
                "CMTE_DSGN", "Committee designation"
            ),
        _FEC_INLINE_ROW_PATTERN,
        "committeeDesignation",
        "fec-committee-designation",
        "committeeDesignationCode",
        6,
    ),
    (
        "fec-filing-frequency",
        _FEC_MASTER_PIN,
        _fec_inline_section_pattern(
                "CMTE_FILING_FREQ", "Filing frequency"
            ),
        _FEC_INLINE_ROW_PATTERN,
        "filingFrequency",
        "fec-filing-frequency",
        "filingFrequencyCode",
        6,
    ),
    (
        "fec-organization-type",
        _FEC_MASTER_PIN,
        _fec_inline_section_pattern(
                "ORG_TP", "Interest group category"
            ),
        _FEC_INLINE_ROW_PATTERN,
        "organizationType",
        "fec-organization-type",
        "organizationTypeCode",
        6,
    ),
    (
        "fec-committee-type",
        _FEC_COMMITTEE_TYPE_PIN,
        _FEC_TABLE_SECTION_PATTERN,
        _FEC_TABLE_ROW_PATTERN,
        "committeeType",
        "fec-committee-type",
        "committeeTypeCode",
        16,
    ),
    (
        "fec-party",
        _FEC_PARTY_PIN,
        _FEC_TABLE_SECTION_PATTERN,
        _FEC_TABLE_ROW_PATTERN,
        "party",
        "fec-party",
        "partyCode",
        95,
    ),
)


def _pattern_row_source_spec(
    name: str,
    inputs: tuple[SourcePin, ...],
    selector: PatternRowSelector,
) -> SourceSpec:
    return SourceSpec(
        name=name,
        kind="vocabulary",
        release_keys=(name,),
        inputs=inputs,
        reader=PATTERN_ROW_READER,
        pattern_row=selector,
        identity_policy=selector.identity_mode,
        policies=DIRECT_SKOS_POLICIES,
        rdf_source=_rdf_source_policy(
            frozenset(selector.native_payload_fields)
        ),
    )


def _fec_pattern_row_source(
    name: str,
    pin: SourcePin,
    region_pattern: str,
    row_pattern: str,
    resource_name: str,
    source_token: str,
    identifier_kind: str,
    expected_count: int,
) -> SourceSpec:
    observed_at = "2026-08-03T19:24:00Z"
    native_payload_template = {
        "conceptIdentityClaimed": False,
        "description": "{description}",
        "id": "{observation_id}",
        "identifiers": [
            {
                "authorityUri": "https://www.fec.gov/",
                "kind": "{identifier_kind}",
                "observedAt": "{observed_at}",
                "sourceDigest": "{source_digest}",
                "sourcePath": "{source_path}",
                "sourceUri": "{source_iri}",
                "value": "{code}",
            }
        ],
        "labels": [
            {
                "language": "en",
                "role": "preferred",
                "value": "{label}",
            }
        ],
        "sourceArtifact": "{source_iri}",
        "sourceOrdinal": "{ordinal}",
        "sourcePath": "{source_path}",
        "uses": ["deterministicMetadata"],
    }
    selector = PatternRowSelector(
        patterns=(
            PatternRowPattern(
                input_pattern=re.escape(pin.path),
                region_pattern=region_pattern,
                row_pattern=row_pattern,
                expected_input_count=1,
                expected_region_count=1,
                expected_row_count=expected_count,
                constants=(
                    ("description", ""),
                    ("identifier_kind", identifier_kind),
                    ("observed_at", observed_at),
                    ("resource_name", resource_name),
                    ("source_token", source_token),
                )
                if "description" not in re.compile(row_pattern).groupindex
                else (
                    ("identifier_kind", identifier_kind),
                    ("observed_at", observed_at),
                    ("resource_name", resource_name),
                    ("source_token", source_token),
                ),
                normalizers=(
                    PatternFieldNormalizer("code", ("html-visible-text",)),
                    PatternFieldNormalizer("label", ("html-visible-text",)),
                    PatternFieldNormalizer("description", ("html-visible-text",)),
                ),
            ),
        ),
        row_key="{code}",
        identity_mode="source-local-record",
        identity_template=(
            "urn:ref:source-concept:v2:{source_token}:{source_uuid7}"
        ),
        source_locator_template="{source_iri}",
        claim_map=(
            ("preferred_label", "{label}"),
            ("notation", "{code}"),
            ("definition", "{description}"),
            ("source_path", "{source_path}"),
            ("observed_at", "{observed_at}"),
            ("identity_hint", "{observation_id}"),
        ),
        native_payload_template_json=_canonical_json_bytes(
            native_payload_template
        ).decode("utf-8"),
        native_payload_fields=tuple(sorted(native_payload_template)),
        expected_count=expected_count,
        declared_unevaluated_fields=("authenticatedHtmlOutsideSelectedRegion",),
        derived_fields=(
            PatternDerivedField(
                field="source_path",
                operation="template",
                template_json=json.dumps("$.{resource_name}.{code}"),
            ),
            PatternDerivedField(
                field="observation_id",
                operation="canonical-json-sha256",
                template_json=_canonical_json_bytes(
                    {
                        "resourceName": "{resource_name}",
                        "sourceArtifact": "{source_iri}",
                        "sourcePath": "{source_path}",
                        "value": "{code}",
                    }
                ).decode("utf-8"),
                prefix="urn:ref:source-observation:fec-committee-codes:",
            ),
        ),
    )
    return _pattern_row_source_spec(name, (pin,), selector)


FEC_PATTERN_ROW_SOURCES = tuple(
    _fec_pattern_row_source(*declaration)
    for declaration in _FEC_PATTERN_ROW_DECLARATIONS
)


_BILLSTATUS_PATTERN_PIN = SourcePin(
    path=(
        "tests/fixtures/billstatus_codes/"
        "billstatus-xml-user-guide-2026-08-03.md"
    ),
    sha256=(
        "sha256:a10909696b2ed2244d75c76e75fa32bc3e4eb926deab7e4e00592a6a01c3ad3a"
    ),
    byte_length=38_802,
    fmt="markdown",
    role="publisherSource",
    source_iri=(
        "https://raw.githubusercontent.com/usgpo/bill-status/master/"
        "BILLSTATUS-XML_User_User-Guide.md"
    ),
)


def _billstatus_identifier_template(kind: str, value: str) -> Mapping[str, Any]:
    """Declare one exact ControlledIdentifier-shaped BILLSTATUS field."""
    return {
        "authority_uri": "https://www.govinfo.gov/bulkdata/BILLSTATUS/",
        "effective_at": None,
        "kind": kind,
        "observed_at": "{observed_at}",
        "source_digest": "{source_digest}",
        "source_uri": "{source_iri}",
        "value": value,
    }


def _billstatus_pattern_source(
    *,
    name: str,
    resource_name: str,
    source_token: str,
    completeness: str,
    region_pattern: str,
    row_pattern: str,
    expected_count: int,
    identifiers: tuple[Mapping[str, Any], ...],
    row_key: str,
) -> SourceSpec:
    observed_at = "2026-08-03T19:29:08Z"
    native_payload_template = {
        "completeness": completeness,
        "identifiers": list(identifiers),
        "is_general_subject_concept": False,
        "publisher_label": "{label}",
        "resource_name": resource_name,
        "sourceArtifact": "{source_iri}",
        "source_url": "{source_iri}",
        "use": "deterministicMetadata",
    }
    notation_claims = tuple(
        ("notation", str(identifier["value"])) for identifier in identifiers
    )
    selector = PatternRowSelector(
        patterns=(
            PatternRowPattern(
                input_pattern=re.escape(_BILLSTATUS_PATTERN_PIN.path),
                region_pattern=region_pattern,
                row_pattern=row_pattern,
                expected_input_count=1,
                expected_region_count=1,
                expected_row_count=expected_count,
                constants=(
                    ("observed_at", observed_at),
                    ("resource_name", resource_name),
                    ("source_token", source_token),
                ),
                normalizers=(
                    PatternFieldNormalizer("code", ("strip",)),
                    PatternFieldNormalizer("label", ("strip",)),
                    *(
                        (PatternFieldNormalizer("chamber", ("strip",)),)
                        if "chamber" in re.compile(row_pattern).groupindex
                        else ()
                    ),
                ),
            ),
        ),
        row_key=row_key,
        identity_mode="source-local-record",
        identity_template=(
            "urn:ref:source-concept:v2:{source_token}:{source_uuid7}"
        ),
        source_locator_template="{source_iri}",
        claim_map=(
            ("preferred_label", "{label}"),
            *notation_claims,
            ("source_path", "{source_path}"),
            ("observed_at", "{observed_at}"),
            ("identity_hint", "{label}"),
        ),
        native_payload_template_json=_canonical_json_bytes(
            native_payload_template
        ).decode("utf-8"),
        native_payload_fields=tuple(sorted(native_payload_template)),
        expected_count=expected_count,
        declared_unevaluated_fields=("markdownOutsideSelectedRegion",),
        derived_fields=(
            PatternDerivedField(
                field="source_path",
                operation="template",
                template_json=json.dumps("$.{resource_name}[{ordinal}]"),
            ),
        ),
    )
    return _pattern_row_source_spec(name, (_BILLSTATUS_PATTERN_PIN,), selector)


BILLSTATUS_PATTERN_ROW_SOURCES = (
    _billstatus_pattern_source(
        name="billstatus-action-codes",
        resource_name="actionCodes",
        source_token="billstatus-action-codes",
        completeness="openCourtesyList",
        region_pattern=(
            r"^# 3\. Action Code Element Possible Values\s*$"
            r"(?P<region>.*?)(?=^# 4\. Actions Type Element Possible Values\s*$)"
        ),
        row_pattern=(
            r"^\|\s*\*\*(?P<code>[A-Z0-9]{4,6})\*\*\s*\|"
            r"\s*(?P<label>[^|\n]+?)\s*\|\s*$"
        ),
        expected_count=36,
        identifiers=(_billstatus_identifier_template("actionCode", "{code}"),),
        row_key="{code}",
    ),
    _billstatus_pattern_source(
        name="billstatus-bill-types",
        resource_name="billTypes",
        source_token="billstatus-bill-types",
        completeness="closedEnumeration",
        region_pattern=(
            r"^Bill type \(Possible values are (?P<region>[^)]+)\)\.[ \t]*$"
        ),
        row_pattern=(
            r"(?:^|,\s*(?:and\s+)?)(?P<label>(?P<code>[A-Z]{1,7}))"
            r"(?=,|$)"
        ),
        expected_count=8,
        identifiers=(_billstatus_identifier_template("billTypeCode", "{code}"),),
        row_key="{code}",
    ),
    _billstatus_pattern_source(
        name="billstatus-summary-version-codes",
        resource_name="summaryVersionCodes",
        source_token="billstatus-summary-version-codes",
        completeness="closedEnumeration",
        region_pattern=(
            r"^# 5\. Mapping of LOC Summaries Version Codes and\s+Action "
            r"Description Text\s*$"
            r"(?P<region>.*?)(?=^# 6\. Title Type Possible Values\s*$)"
        ),
        row_pattern=(
            r"^\|\s*\*\*(?P<code>[0-9]{2})\*\*\s*\|"
            r"\s*(?P<chamber>HOUSE|SENATE|BOTH)\s*\|"
            r"\s*(?P<label>[^|\n]+?)\s*\|\s*$"
        ),
        expected_count=88,
        identifiers=(
            _billstatus_identifier_template("billVersionCode", "{code}"),
            _billstatus_identifier_template("billVersionChamber", "{chamber}"),
        ),
        row_key="{code}:{chamber}",
    ),
)


_REGULATIONS_GOV_PATTERN_PIN = SourcePin(
    path=(
        "tests/fixtures/regulations_gov_codes/"
        "regulations-gov-openapi-v4-2026-08-03.yaml"
    ),
    sha256=(
        "sha256:be43c866f5ca424a456bde36ea03cb9326c454ef4e1894a13df80b6dc6e22488"
    ),
    byte_length=60_826,
    fmt="yaml",
    role="publisherSource",
    source_iri="https://open.gsa.gov/api/regulationsgov/v4/openapi.yaml",
)


def _regulations_gov_pattern_source(
    *,
    name: str,
    schema_name: str,
    resource_name: str,
    identifier_kind: str,
    expected_count: int,
) -> SourceSpec:
    observed_at = "2026-08-03T19:13:12Z"
    native_payload_template = {
        "identifiers": [
            {
                "authority_uri": "https://open.gsa.gov/api/regulationsgov/",
                "effective_at": None,
                "kind": identifier_kind,
                "observed_at": observed_at,
                "source_digest": "{source_digest}",
                "source_uri": "{source_iri}",
                "value": "{code}",
            }
        ],
        "is_general_subject_concept": False,
        "publisher_label": "{label}",
        "resource_name": resource_name,
        "sourceArtifact": "{source_iri}",
        "source_url": "{source_iri}",
        "use": "deterministicMetadata",
    }
    source_token = name
    selector = PatternRowSelector(
        patterns=(
            PatternRowPattern(
                input_pattern=re.escape(_REGULATIONS_GOV_PATTERN_PIN.path),
                region_pattern=(
                    r"\n {4}"
                    + re.escape(schema_name)
                    + r":\n {6}type: string\n"
                    r" {6}description: [^\n]+\n"
                    r" {6}enum:\n"
                    r"(?P<region>(?: {8}- [^\n]*\n)+)"
                ),
                row_pattern=(
                    r"^ {8}- (?P<label>(?P<code>[^\n]+))$"
                ),
                expected_input_count=1,
                expected_region_count=1,
                expected_row_count=expected_count,
                constants=(
                    ("observed_at", observed_at),
                    ("resource_name", resource_name),
                    ("source_token", source_token),
                ),
                normalizers=(
                    PatternFieldNormalizer("code", ("rstrip",)),
                    PatternFieldNormalizer("label", ("rstrip",)),
                ),
            ),
        ),
        row_key="{code}",
        identity_mode="source-local-record",
        identity_template=(
            "urn:ref:source-concept:v2:{source_token}:{source_uuid7}"
        ),
        source_locator_template="{source_iri}",
        claim_map=(
            ("preferred_label", "{label}"),
            ("notation", "{code}"),
            ("source_path", "{source_path}"),
            ("observed_at", "{observed_at}"),
            ("identity_hint", "{label}"),
        ),
        native_payload_template_json=_canonical_json_bytes(
            native_payload_template
        ).decode("utf-8"),
        native_payload_fields=tuple(sorted(native_payload_template)),
        expected_count=expected_count,
        declared_unevaluated_fields=("yamlOutsideSelectedEnumBlock",),
        derived_fields=(
            PatternDerivedField(
                field="source_path",
                operation="template",
                template_json=json.dumps("$.{resource_name}[{ordinal}]"),
            ),
        ),
    )
    return _pattern_row_source_spec(name, (_REGULATIONS_GOV_PATTERN_PIN,), selector)


REGULATIONS_GOV_PATTERN_ROW_SOURCES = tuple(
    _regulations_gov_pattern_source(
        name=name,
        schema_name=schema_name,
        resource_name=resource_name,
        identifier_kind=identifier_kind,
        expected_count=expected_count,
    )
    for name, schema_name, resource_name, identifier_kind, expected_count in (
        (
            "regulations-gov-docket-type",
            "DocketType",
            "docketType",
            "docketTypeCode",
            2,
        ),
        (
            "regulations-gov-document-type",
            "DocumentType",
            "documentType",
            "documentTypeCode",
            5,
        ),
        (
            "regulations-gov-submitter-type",
            "SubmitterType",
            "submitterType",
            "submitterTypeCode",
            3,
        ),
    )
)


_SAM_ASSISTANCE_PATTERN_PIN = SourcePin(
    path=(
        "tests/fixtures/sam_assistance_listing_codes/"
        "sam-assistance-listings-api-2026-08-03.html"
    ),
    sha256=(
        "sha256:6ea76d040e2190b02cad8192f50dbe00d39f01f5366f893cd24b6491dfdeeffd"
    ),
    byte_length=210_611,
    fmt="html",
    role="publisherSource",
    source_iri="https://open.gsa.gov/api/assistance-listings-api/",
)
_SAM_ASSISTANCE_TABLE_ROW_PATTERN = (
    r"<tr>\s*<td>(?P<code>.*?)</td>\s*"
    r"<td>(?P<label>.*?)</td>\s*</tr>"
)


def _sam_assistance_region_pattern(heading_id: str) -> str:
    return (
        r'<h[1-6][^>]*id="'
        + re.escape(heading_id)
        + r'"[^>]*>(?P<region>.*?)(?=<h[1-6][^>]*id=")'
    )


def _sam_assistance_pattern_source(
    *,
    name: str,
    resource_name: str,
    identifier_kind: str,
    identifier_source_iri: str,
    patterns: tuple[tuple[str, int, str | None], ...],
    expected_count: int,
) -> SourceSpec:
    observed_at = "2026-08-03T19:28:13Z"
    native_payload_template = {
        "category": "{category}",
        "conceptIdentityClaimed": False,
        "id": "{observation_id}",
        "identifiers": [
            {
                "authorityUri": "https://open.gsa.gov/",
                "kind": identifier_kind,
                "observedAt": observed_at,
                "sourceDigest": "{source_digest}",
                "sourcePath": "{source_path}",
                "sourceUri": identifier_source_iri,
                "value": "{code}",
            }
        ],
        "labels": [
            {
                "language": "en",
                "role": "preferred",
                "value": "{label}",
            }
        ],
        "sourceArtifact": "{source_iri}",
        "sourceOrdinal": "{ordinal}",
        "sourcePath": "{source_path}",
        "uses": ["deterministicMetadata"],
    }
    selector = PatternRowSelector(
        patterns=tuple(
            PatternRowPattern(
                input_pattern=re.escape(_SAM_ASSISTANCE_PATTERN_PIN.path),
                region_pattern=_sam_assistance_region_pattern(heading_id),
                row_pattern=_SAM_ASSISTANCE_TABLE_ROW_PATTERN,
                expected_input_count=1,
                expected_region_count=1,
                expected_row_count=count,
                constants=(
                    ("category", category),
                    ("observed_at", observed_at),
                    ("resource_name", resource_name),
                    ("source_token", name),
                ),
                normalizers=(
                    PatternFieldNormalizer("code", ("html-visible-text",)),
                    PatternFieldNormalizer("label", ("html-visible-text",)),
                ),
            )
            for heading_id, count, category in patterns
        ),
        row_key="{code}",
        identity_mode="source-local-record",
        identity_template="urn:ref:source-concept:v2:{source_token}:{source_uuid7}",
        source_locator_template="{source_iri}",
        claim_map=(
            ("preferred_label", "{label}"),
            ("notation", "{code}"),
            ("source_path", "{source_path}"),
            ("observed_at", "{observed_at}"),
            ("identity_hint", "{observation_id}"),
        ),
        native_payload_template_json=_canonical_json_bytes(
            native_payload_template
        ).decode("utf-8"),
        native_payload_fields=tuple(sorted(native_payload_template)),
        expected_count=expected_count,
        declared_unevaluated_fields=("htmlOutsideSelectedReferenceTables",),
        derived_fields=(
            PatternDerivedField(
                field="source_path",
                operation="template",
                template_json=json.dumps("$.{resource_name}.{code}"),
            ),
            PatternDerivedField(
                field="observation_id",
                operation="canonical-json-sha256",
                template_json=_canonical_json_bytes(
                    {
                        "resourceName": "{resource_name}",
                        "sourceArtifact": "{source_iri}",
                        "sourcePath": "{source_path}",
                        "value": "{code}",
                    }
                ).decode("utf-8"),
                prefix="urn:ref:source-observation:sam-assistance-listings:",
            ),
        ),
    )
    return _pattern_row_source_spec(name, (_SAM_ASSISTANCE_PATTERN_PIN,), selector)


SAM_ASSISTANCE_PATTERN_ROW_SOURCES = (
    _sam_assistance_pattern_source(
        name="sam-assistance-assistance-types",
        resource_name="assistanceTypes",
        identifier_kind="assistanceTypeCode",
        identifier_source_iri=(
            "https://open.gsa.gov/api/assistance-listings-api/"
            "#assistance-types-by-code"
        ),
        patterns=(
            ("financial-assistance", 10, "financial"),
            ("non-financial-assistance", 7, "nonFinancial"),
        ),
        expected_count=17,
    ),
    _sam_assistance_pattern_source(
        name="sam-assistance-eligible-applicant-types",
        resource_name="eligibleApplicantTypes",
        identifier_kind="applicantEntityTypeCode",
        identifier_source_iri=(
            "https://open.gsa.gov/api/assistance-listings-api/"
            "#eligible-award-applicant-types"
        ),
        patterns=(("eligible-award-applicant-types", 44, None),),
        expected_count=44,
    ),
    _sam_assistance_pattern_source(
        name="sam-assistance-eligible-beneficiary-types",
        resource_name="eligibleBeneficiaryTypes",
        identifier_kind="beneficiaryEntityTypeCode",
        identifier_source_iri=(
            "https://open.gsa.gov/api/assistance-listings-api/"
            "#eligible-beneficiary-types"
        ),
        patterns=(("eligible-beneficiary-types", 73, None),),
        expected_count=73,
    ),
)


_SAM_OPPORTUNITIES_PATTERN_PIN = SourcePin(
    path=(
        "tests/fixtures/sam_opportunities_codes/"
        "sam-get-opportunities-public-api-2026-08-03.html"
    ),
    sha256=(
        "sha256:448b85ab4a22e33d139295cb1d6a3a6384b685a936d8c645dd12e69ed938fa62"
    ),
    byte_length=46_217,
    fmt="html",
    role="publisherSource",
    source_iri="https://open.gsa.gov/api/get-opportunities-public-api/",
)
_SAM_OPPORTUNITIES_CODE_ROW = (
    r"(?:^|<br\s*/?>)\s*(?P<code>[a-z])\s*=\s*"
    r"(?P<label>.*?)(?=<br\s*/?>|$)"
)


def _sam_opportunities_pattern_source(
    *,
    name: str,
    resource_name: str,
    identifier_kind: str,
    identifier_source_iri: str,
    patterns: tuple[tuple[str, str, int, bool], ...],
    expected_count: int,
) -> SourceSpec:
    observed_at = "2026-08-03T19:18:48Z"
    native_payload_template = {
        "conceptIdentityClaimed": False,
        "id": "{observation_id}",
        "identifiers": [
            {
                "authorityUri": "https://open.gsa.gov/",
                "kind": identifier_kind,
                "observedAt": observed_at,
                "sourceDigest": "{source_digest}",
                "sourcePath": "{source_path}",
                "sourceUri": identifier_source_iri,
                "value": "{code}",
            }
        ],
        "labels": [
            {
                "language": "en",
                "role": "preferred",
                "value": "{label}",
            }
        ],
        "retired": "{retired}",
        "sourceArtifact": "{source_iri}",
        "sourceOrdinal": "{ordinal}",
        "sourcePath": "{source_path}",
        "uses": ["deterministicMetadata"],
    }
    selector = PatternRowSelector(
        patterns=tuple(
            PatternRowPattern(
                input_pattern=re.escape(_SAM_OPPORTUNITIES_PATTERN_PIN.path),
                region_pattern=region_pattern,
                row_pattern=row_pattern,
                expected_input_count=1,
                expected_region_count=1,
                expected_row_count=count,
                constants=(
                    ("observed_at", observed_at),
                    ("resource_name", resource_name),
                    ("retired", retired),
                    ("source_token", name),
                ),
                normalizers=(
                    PatternFieldNormalizer("code", ("html-visible-text",)),
                    PatternFieldNormalizer("label", ("html-visible-text",)),
                ),
            )
            for region_pattern, row_pattern, count, retired in patterns
        ),
        row_key="{code}",
        identity_mode="source-local-record",
        identity_template="urn:ref:source-concept:v2:{source_token}:{source_uuid7}",
        source_locator_template="{source_iri}",
        claim_map=(
            ("preferred_label", "{label}"),
            ("notation", "{code}"),
            ("source_path", "{source_path}"),
            ("observed_at", "{observed_at}"),
            ("identity_hint", "{observation_id}"),
        ),
        native_payload_template_json=_canonical_json_bytes(
            native_payload_template
        ).decode("utf-8"),
        native_payload_fields=tuple(sorted(native_payload_template)),
        expected_count=expected_count,
        declared_unevaluated_fields=("htmlOutsideSelectedControlRows",),
        derived_fields=(
            PatternDerivedField(
                field="source_path",
                operation="template",
                template_json=json.dumps("$.{resource_name}.{code}"),
            ),
            PatternDerivedField(
                field="observation_id",
                operation="canonical-json-sha256",
                template_json=_canonical_json_bytes(
                    {
                        "resourceName": "{resource_name}",
                        "sourceArtifact": "{source_iri}",
                        "sourcePath": "{source_path}",
                        "value": "{code}",
                    }
                ).decode("utf-8"),
                prefix="urn:ref:source-observation:sam-opportunities:",
            ),
        ),
    )
    return _pattern_row_source_spec(name, (_SAM_OPPORTUNITIES_PATTERN_PIN,), selector)


SAM_OPPORTUNITIES_PATTERN_ROW_SOURCES = (
    _sam_opportunities_pattern_source(
        name="sam-opportunities-notice-types",
        resource_name="noticeTypes",
        identifier_kind="noticeTypeCode",
        identifier_source_iri=(
            "https://open.gsa.gov/api/get-opportunities-public-api/"
            "#get-opportunities-request-parameters"
        ),
        patterns=(
            (
                (
                    r"<td>ptype</td>\s*<td>Procurement Type\..*?<br\s*/?>\s*"
                    r"(?P<region>.*?)(?=<br\s*/?>\s*Note: Below services are now retired)"
                ),
                _SAM_OPPORTUNITIES_CODE_ROW,
                9,
                False,
            ),
            (
                (
                    r"Note: Below services are now retired:\s*<br\s*/?>\s*"
                    r"(?P<region>.*?)(?=<br\s*/?>\s*<br\s*/?>\s*Use Justification)"
                ),
                _SAM_OPPORTUNITIES_CODE_ROW,
                2,
                True,
            ),
        ),
        expected_count=11,
    ),
    _sam_opportunities_pattern_source(
        name="sam-opportunities-opportunity-statuses",
        resource_name="opportunityStatuses",
        identifier_kind="opportunityStatusCode",
        identifier_source_iri=(
            "https://open.gsa.gov/api/get-opportunities-public-api/"
            "#get-opportunities-request-parameters"
        ),
        patterns=(
            (
                (
                    r"<td>status \(Coming Soon\)</td>\s*<td>.*?Accepts following:\s*"
                    r"(?P<region>.*?)</td>"
                ),
                r"(?:^|,\s*)(?P<label>(?P<code>[a-z]+))(?=,|$)",
                5,
                False,
            ),
        ),
        expected_count=5,
    ),
    _sam_opportunities_pattern_source(
        name="sam-opportunities-set-aside-codes",
        resource_name="setAsideCodes",
        identifier_kind="setAsideCode",
        identifier_source_iri=(
            "https://open.gsa.gov/api/get-opportunities-public-api/"
            "#set-aside-values"
        ),
        patterns=(
            (
                r'<h3 id="set-aside-values">.*?<table>(?P<region>.*?)</table>',
                (
                    r"<tr>\s*<td>(?P<code>[A-Za-z0-9]+)</td>\s*"
                    r"<td>(?P<label>.*?)</td>\s*</tr>"
                ),
                18,
                False,
            ),
        ),
        expected_count=18,
    ),
)


_FERC_SEARCH_PATTERN_PIN = SourcePin(
    path="ferc-general-search-help.html",
    sha256=(
        "sha256:1f4b2883879602530c59095cc3d33fedbbf50a2d630e7bdf0226785259dd2b45"
    ),
    byte_length=7_447,
    fmt="html",
    role="publisherSource",
    source_iri="https://elibrary.ferc.gov/eLibraryhelp/General_Search.htm",
    construction_path=(
        "output/registry-real-data-sources/ferc-general-search-help.html"
    ),
)
_FERC_ACCESSIBILITY_PATTERN_PIN = SourcePin(
    path="ferc-accessibility-tips.html",
    sha256=(
        "sha256:c9219bd08b8712e35389ff26f079a21e16d2b5fea68aaebf561bb9b203010688"
    ),
    byte_length=39_466,
    fmt="html",
    role="publisherSource",
    source_iri=(
        "https://elibrary.ferc.gov/eLibrary/assets/Accessibility_Tips.html"
    ),
    construction_path=(
        "output/registry-real-data-sources/ferc-accessibility-tips.html"
    ),
)


def _ferc_pattern_source(
    *,
    name: str,
    pin: SourcePin,
    source_token: str,
    region_pattern: str,
    row_pattern: str,
    source_path_root: str,
    label_template: str,
    native_value_field: str,
    expected_count: int,
) -> SourceSpec:
    observed_at = "2026-08-03T19:18:32Z"
    native_payload_template = {
        native_value_field: "{code}",
        "sourceArtifact": "{source_iri}",
    }
    selector = PatternRowSelector(
        patterns=(
            PatternRowPattern(
                input_pattern=re.escape(pin.path),
                region_pattern=region_pattern,
                row_pattern=row_pattern,
                expected_input_count=1,
                expected_region_count=1,
                expected_row_count=expected_count,
                constants=(
                    ("observed_at", observed_at),
                    ("source_token", source_token),
                ),
                normalizers=(
                    PatternFieldNormalizer("code", ("html-visible-text",)),
                ),
            ),
        ),
        row_key="{code}",
        identity_mode="source-local-record",
        identity_template="urn:ref:source-concept:v2:{source_token}:{source_uuid7}",
        source_locator_template="{source_iri}",
        claim_map=(
            ("preferred_label", label_template),
            ("notation", "{code}"),
            ("source_path", "{source_path}"),
            ("observed_at", "{observed_at}"),
            ("identity_hint", label_template),
        ),
        native_payload_template_json=_canonical_json_bytes(
            native_payload_template
        ).decode("utf-8"),
        native_payload_fields=tuple(sorted(native_payload_template)),
        expected_count=expected_count,
        declared_unevaluated_fields=("htmlOutsideSelectedControl",),
        derived_fields=(
            PatternDerivedField(
                field="source_path",
                operation="template",
                template_json=json.dumps(f"$.{source_path_root}[{{ordinal}}]"),
            ),
        ),
    )
    return _pattern_row_source_spec(name, (pin,), selector)


FERC_HTML_PATTERN_ROW_SOURCES = (
    _ferc_pattern_source(
        name="ferc-sectors",
        pin=_FERC_SEARCH_PATTERN_PIN,
        source_token="ferc-sectors",
        region_pattern=(
            r"<li>Industry Sector</li>\s*<ul[^>]*>(?P<region>.*?)</ul>"
        ),
        row_pattern=r"<li>(?P<code>.*?)</li>",
        source_path_root="sectors",
        label_template="{code}",
        native_value_field="value",
        expected_count=6,
    ),
    _ferc_pattern_source(
        name="ferc-security-levels",
        pin=_FERC_SEARCH_PATTERN_PIN,
        source_token="ferc-security-levels",
        region_pattern=(
            r"<li>Security Level</li>\s*<ul[^>]*>(?P<region>.*?)</ul>"
        ),
        row_pattern=r"<li>(?P<code>.*?)</li>",
        source_path_root="security-levels",
        label_template="{code}",
        native_value_field="value",
        expected_count=4,
    ),
    _ferc_pattern_source(
        name="ferc-accession-number-formats",
        pin=_FERC_ACCESSIBILITY_PATTERN_PIN,
        source_token="ferc-accession-formats",
        region_pattern=(
            r'<td scope="row">Accession</td>\s*<td>(?P<region>[^<]+)</td>'
        ),
        row_pattern=r"(?:^|, or )(?P<code>[^,]+?)(?=, or |$)",
        source_path_root="accessionFormats",
        label_template="FERC accession number format {code}",
        native_value_field="format",
        expected_count=2,
    ),
)


_GRANTS_GOV_PATTERN_PIN = SourcePin(
    path=(
        "tests/fixtures/grants_gov_codes/"
        "grants-gov-status-codes-2026-08-03.html"
    ),
    sha256=(
        "sha256:bcbe4c44f8c1743eeaa26ab9f350c53214238c31d807057f248af8dd96cd5f85"
    ),
    byte_length=46_093,
    fmt="html",
    role="publisherSource",
    source_iri="https://www.grants.gov/api/status-codes",
)


def _grants_gov_pattern_source(
    *,
    name: str,
    resource_name: str,
    heading: str,
    identifier_kind: str,
    use: str,
    expected_count: int,
) -> SourceSpec:
    observed_at = "2026-08-03T19:28:12Z"
    native_payload_template = {
        "conceptIdentityClaimed": False,
        "id": "{observation_id}",
        "identifiers": [
            {
                "authorityUri": "https://www.grants.gov/",
                "kind": identifier_kind,
                "observedAt": observed_at,
                "sourceDigest": "{source_digest}",
                "sourcePath": "{source_path}",
                "sourceUri": "{source_iri}",
                "value": "{code}",
            }
        ],
        "labels": [
            {"language": "en", "role": "preferred", "value": "{label}"}
        ],
        "sourceArtifact": "{source_iri}",
        "sourceOrdinal": "{ordinal}",
        "sourcePath": "{source_path}",
        "uses": [use],
    }
    selector = PatternRowSelector(
        patterns=(
            PatternRowPattern(
                input_pattern=re.escape(_GRANTS_GOV_PATTERN_PIN.path),
                region_pattern=(
                    re.escape(heading)
                    + r".*?<table[^>]*>.*?<tbody>(?P<region>.*?)</tbody>\s*</table>"
                ),
                row_pattern=(
                    r"<tr>\s*<td>(?P<code>.*?)</td>\s*"
                    r"<td>(?P<label>.*?)</td>\s*</tr>"
                ),
                expected_input_count=1,
                expected_region_count=1,
                expected_row_count=expected_count,
                constants=(
                    ("observed_at", observed_at),
                    ("resource_name", resource_name),
                    ("source_token", name),
                ),
                normalizers=(
                    PatternFieldNormalizer("code", ("html-visible-text",)),
                    PatternFieldNormalizer("label", ("html-visible-text",)),
                ),
            ),
        ),
        row_key="{code}",
        identity_mode="source-local-record",
        identity_template="urn:ref:source-concept:v2:{source_token}:{source_uuid7}",
        source_locator_template="{source_iri}",
        claim_map=(
            ("preferred_label", "{label}"),
            ("notation", "{code}"),
            ("source_path", "{source_path}"),
            ("observed_at", "{observed_at}"),
            ("identity_hint", "{observation_id}"),
        ),
        native_payload_template_json=_canonical_json_bytes(
            native_payload_template
        ).decode("utf-8"),
        native_payload_fields=tuple(sorted(native_payload_template)),
        expected_count=expected_count,
        declared_unevaluated_fields=("htmlOutsideSelectedCodeTable",),
        derived_fields=(
            PatternDerivedField(
                field="source_path",
                operation="template",
                template_json=json.dumps(f"$.{resource_name}.{{code}}"),
            ),
            PatternDerivedField(
                field="observation_id",
                operation="canonical-json-sha256",
                template_json=_canonical_json_bytes(
                    {
                        "resourceName": resource_name,
                        "sourceArtifact": "{source_iri}",
                        "sourcePath": "{source_path}",
                        "value": "{code}",
                    }
                ).decode("utf-8"),
                prefix="urn:ref:source-observation:grants-gov-codes:",
            ),
        ),
    )
    return _pattern_row_source_spec(name, (_GRANTS_GOV_PATTERN_PIN,), selector)


GRANTS_GOV_PATTERN_ROW_SOURCES = (
    _grants_gov_pattern_source(
        name="grants-gov-eligibilities",
        resource_name="eligibilities",
        heading="Eligibility Codes (&quot;eligibilities&quot;):",
        identifier_kind="eligibilityCode",
        use="deterministicMetadata",
        expected_count=17,
    ),
    _grants_gov_pattern_source(
        name="grants-gov-funding-categories",
        resource_name="fundingCategories",
        heading="Category Codes (&quot;fundingCategories&quot;):",
        identifier_kind="fundingCategoryCode",
        use="sourceAssignedEvidence",
        expected_count=26,
    ),
)


_OIRA_PATTERN_INPUTS = (
    _registry_source_pin(
        (
            "oira-controls/sha256/"
            "bc92190b16d9855c05700592bd957491089434bed031aff369103add47af4f76/"
            "reviewStatus.html"
        ),
        "sha256:bc92190b16d9855c05700592bd957491089434bed031aff369103add47af4f76",
        405,
        (
            "https://www.reginfo.gov/public/do/"
            "eoAdvancedSearch?eoStatusCode=CD#eoStatusCode"
        ),
        fmt="html",
        construction_path=(
            "output/registry-real-data-sources/oira-controls/sha256/"
            "bc92190b16d9855c05700592bd957491089434bed031aff369103add47af4f76/"
            "reviewStatus.html"
        ),
    ),
    _registry_source_pin(
        (
            "oira-controls/sha256/"
            "90ccba72caf4a3b98654937fd9a5297c0413b803b9e513c85b1851daf7fbb15a/"
            "ruleStage.html"
        ),
        "sha256:90ccba72caf4a3b98654937fd9a5297c0413b803b9e513c85b1851daf7fbb15a",
        1_390,
        (
            "https://www.reginfo.gov/public/do/"
            "eoAdvancedSearch?eoStatusCode=CD#ruleStages"
        ),
        fmt="html",
        construction_path=(
            "output/registry-real-data-sources/oira-controls/sha256/"
            "90ccba72caf4a3b98654937fd9a5297c0413b803b9e513c85b1851daf7fbb15a/"
            "ruleStage.html"
        ),
    ),
    _registry_source_pin(
        (
            "oira-controls/sha256/"
            "a402dfde370f0b506dc5262b6002a41983e28f1ac7a4338c1ed048ee49cadbef/"
            "concludedAction.html"
        ),
        "sha256:a402dfde370f0b506dc5262b6002a41983e28f1ac7a4338c1ed048ee49cadbef",
        570,
        (
            "https://www.reginfo.gov/public/do/"
            "eoAdvancedSearch?eoStatusCode=CD#concludedActionCode"
        ),
        fmt="html",
        construction_path=(
            "output/registry-real-data-sources/oira-controls/sha256/"
            "a402dfde370f0b506dc5262b6002a41983e28f1ac7a4338c1ed048ee49cadbef/"
            "concludedAction.html"
        ),
    ),
    _registry_source_pin(
        (
            "oira-controls/sha256/"
            "9bec2066ff2c01731b201765cad4a175a0b34230c30dfc854655341040cc9aea/"
            "meetingStatus.html"
        ),
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
)
_OIRA_PATTERN_DECLARATIONS = (
    (
        _OIRA_PATTERN_INPUTS[0],
        "reviewStatusCode",
        (
            r"(?P<region><label\b.*</label>\s*(?:&nbsp;\s*)*"
            r"<label\b.*</label>)"
        ),
        (
            r"<label\b[^>]*>\s*<input\b[^>]*name=\"eoStatusCode\"[^>]*"
            r"value=\"(?P<code>[^\"]+)\"[^>]*/>(?P<label>[^<]*)</label>"
        ),
        2,
    ),
    (
        _OIRA_PATTERN_INPUTS[1],
        "ruleStageCode",
        r"(?P<region>[\s\S]+)",
        (
            r"<label\b[^>]*>\s*<input\b[^>]*name=\"ruleStages\"[^>]*"
            r"value=\"(?P<code>[^\"]+)\"[^>]*/>"
            r"(?:<input\s+type=\"hidden\"[^>]*/>)?(?P<label>[^<]*)</label>"
        ),
        6,
    ),
    (
        _OIRA_PATTERN_INPUTS[2],
        "concludedActionCode",
        r"<select\b[^>]*>(?P<region>.*?)</select>",
        r'<option\s+value="(?P<code>[^"]*)"[^>]*>(?P<label>[^<]*)</option>',
        9,
    ),
    (
        _OIRA_PATTERN_INPUTS[3],
        "meetingStatusCode",
        r"<select\b[^>]*>(?P<region>.*?)</select>",
        r'<option\s+value="(?P<code>[^"]*)"[^>]*>(?P<label>[^<]*)</option>',
        3,
    ),
)


def _oira_pattern_source() -> SourceSpec:
    observed_at = "2026-08-03T19:13:02Z"
    resource_id = "oira-eo-12866-review-and-meeting-codes-2026-08-03"
    native_payload_template = {
        "conceptIdentityClaimed": False,
        "id": "{observation_id}",
        "identifiers": [
            {
                "authorityUri": "https://www.reginfo.gov/",
                "kind": "{identifier_kind}",
                "observedAt": observed_at,
                "sourceDigest": "{source_digest}",
                "sourcePath": "{source_path}",
                "sourceUri": "{source_iri}",
                "value": "{code}",
            }
        ],
        "labels": [
            {"language": "en", "role": "preferred", "value": "{label}"}
        ],
        "sourceArtifact": "{source_iri}",
        "sourceOrdinal": "{pattern_ordinal}",
        "sourcePath": "{source_path}",
        "uses": ["deterministicMetadata"],
    }
    selector = PatternRowSelector(
        patterns=tuple(
            PatternRowPattern(
                input_pattern=re.escape(pin.path),
                region_pattern=region_pattern,
                row_pattern=row_pattern,
                expected_input_count=1,
                expected_region_count=1,
                expected_row_count=expected_count,
                constants=(
                    ("identifier_kind", identifier_kind),
                    ("observed_at", observed_at),
                    ("source_token", "oira-review-controls"),
                ),
                normalizers=(
                    PatternFieldNormalizer("code", ("html-visible-text",)),
                    PatternFieldNormalizer("label", ("html-visible-text",)),
                ),
                row_filters=(PatternRowFilter("code", r".+", True),),
            )
            for (
                pin,
                identifier_kind,
                region_pattern,
                row_pattern,
                expected_count,
            ) in _OIRA_PATTERN_DECLARATIONS
        ),
        row_key="{source_iri}#{code}",
        identity_mode="source-local-record",
        identity_template=(
            "urn:ref:source-concept:v2:{source_token}:{source_uuid7}"
        ),
        source_locator_template="{source_iri}",
        claim_map=(
            ("preferred_label", "{label}"),
            ("notation", "{code}"),
            ("source_path", "{source_path}"),
            ("observed_at", "{observed_at}"),
            ("identity_hint", "{observation_id}"),
        ),
        native_payload_template_json=_canonical_json_bytes(
            native_payload_template
        ).decode("utf-8"),
        native_payload_fields=tuple(sorted(native_payload_template)),
        expected_count=20,
        declared_unevaluated_fields=("controlMarkupAndPlaceholderOptions",),
        derived_fields=(
            PatternDerivedField(
                field="source_path",
                operation="template",
                template_json=json.dumps("$[{pattern_ordinal}]"),
            ),
            PatternDerivedField(
                field="observation_id",
                operation="canonical-json-sha256",
                template_json=_canonical_json_bytes(
                    {
                        "identifiers": [
                            {
                                "authorityUri": "https://www.reginfo.gov/",
                                "kind": "{identifier_kind}",
                                "value": "{code}",
                            }
                        ],
                        "resourceId": resource_id,
                        "sourceArtifact": "{source_iri}",
                        "sourcePath": "{source_path}",
                    }
                ).decode("utf-8"),
                prefix=f"urn:ref:source-observation:{resource_id}:",
            ),
        ),
    )
    return _pattern_row_source_spec(
        "oira-review-controls", _OIRA_PATTERN_INPUTS, selector
    )


OIRA_PATTERN_ROW_SOURCES = (_oira_pattern_source(),)


SOURCES: tuple[SourceSpec, ...] = (
    SourceSpec(
        name="federal-register-api-topics-2026-08-03",
        kind="vocabulary",
        release_keys=("federal-register-api-topics-2026-08-03",),
        inputs=(
            _registry_source_pin(
                "federal-register-topics-zyte.json",
                "sha256:aba80a4dcacbffc7c9ec29eb88ea385ec313510fc8331d0f69078d940d1da35b",
                920_705,
                _FEDERAL_REGISTER_TOPICS_URL,
                fmt="json",
                role="publisherApiCapture",
            ),
        ),
        reader=FEDERAL_REGISTER_TOPICS_JSON_READER,
        identity_policy="source-local-record",
        policies=DIRECT_SKOS_POLICIES,
        rdf_source=_rdf_source_policy(
            frozenset(
                {
                    "collection",
                    "record",
                    "sourceOrdinal",
                    "sourceRecordDigest",
                }
            ),
            atlas_only_native_payload_fields=frozenset({"identityStatus"}),
            additional_relation_predicates=(f"{ATLAS}thesaurusUse",),
        ),
    ),
    SourceSpec(
        name="gcmd-science-keywords-24-4",
        kind="vocabulary",
        release_keys=("gcmd-science-keywords-24-4",),
        inputs=(
            _registry_source_pin(
                "gcmd-science-keywords-24.4.csv",
                "sha256:f31d8137e860e4231ff312c89e4ffe59d12f636786a47dd2c41e28273a3f02e2",
                504_190,
                (
                    "https://gcmd.earthdata.nasa.gov/kms/concepts/"
                    "concept_scheme/sciencekeywords?format=csv"
                ),
                fmt="csv",
            ),
        ),
        reader=GCMD_SCIENCE_KEYWORDS_CSV_READER,
        identity_policy="source-scoped-identifier",
        policies=DIRECT_SKOS_POLICIES,
        rdf_source=_rdf_source_policy(
            frozenset(
                {
                    "publisherIdentifier",
                    "category",
                    "topic",
                    "term",
                    "variableLevel1",
                    "variableLevel2",
                    "variableLevel3",
                    "detailedVariable",
                    "sourceIdentity",
                }
            ),
            atlas_only_native_payload_fields=frozenset(
                {"hierarchyIsDescriptiveNotInferred"}
            ),
        ),
    ),
    *BILLSTATUS_PATTERN_ROW_SOURCES,
    *FEC_PATTERN_ROW_SOURCES,
    *REGULATIONS_GOV_PATTERN_ROW_SOURCES,
    *SAM_ASSISTANCE_PATTERN_ROW_SOURCES,
    *SAM_OPPORTUNITIES_PATTERN_ROW_SOURCES,
    *FERC_HTML_PATTERN_ROW_SOURCES,
    *GRANTS_GOV_PATTERN_ROW_SOURCES,
    *OIRA_PATTERN_ROW_SOURCES,
    SourceSpec(
        name="lda-general-issue-codes",
        kind="vocabulary",
        release_keys=("lda-general-issue-codes",),
        inputs=(
            SourcePin(
                path="tests/fixtures/lda-general-issue-codes-2026-07-30.json",
                sha256="sha256:e1820ef17f3e63048ae50e526c2f56e507b2cf60d720fc227c76ee7c3610d5bf",
                byte_length=3_596,
                fmt="json",
                role="publisherSource",
                source_iri=(
                    "https://lda.gov/api/v1/constants/filing/"
                    "lobbyingactivityissues/"
                ),
            ),
        ),
        reader=API_CAPTURE_JSON_READER,
        identity_policy="source-local-record",
        policies=DIRECT_SKOS_POLICIES,
        rdf_source=_rdf_source_policy(
            frozenset(
                {
                    "identifiers",
                    "is_general_subject_concept",
                    "publisher_label",
                    "resource_name",
                    "sourceArtifact",
                    "source_url",
                    "use",
                }
            )
        ),
    ),
    SourceSpec(
        name="lda-filing-types",
        kind="vocabulary",
        release_keys=("lda-filing-types",),
        inputs=(
            SourcePin(
                path="tests/fixtures/lda-filing-types-2026-07-30.json",
                sha256="sha256:49fbd39383b0be63fb474878aa229d4e397880a30c2e0dac1a0905bc660a3149",
                byte_length=2_803,
                fmt="json",
                role="publisherSource",
                source_iri="https://lda.gov/api/v1/constants/filing/filingtypes/",
            ),
        ),
        reader=API_CAPTURE_JSON_READER,
        identity_policy="source-local-record",
        policies=DIRECT_SKOS_POLICIES,
        rdf_source=_rdf_source_policy(
            frozenset(
                {
                    "identifiers",
                    "is_general_subject_concept",
                    "publisher_label",
                    "resource_name",
                    "sourceArtifact",
                    "source_url",
                    "use",
                }
            )
        ),
    ),
    SourceSpec(
        name="ecfr-cfr-titles",
        kind="vocabulary",
        release_keys=("ecfr-cfr-titles",),
        inputs=(
            SourcePin(
                path=(
                    "tests/fixtures/govinfo_collections/"
                    "ecfr-cfr-titles-2026-08-03.json"
                ),
                sha256="sha256:a5985527fc0b07ac95d2cb5d7c867cfd0ddbc2712708e271edbe4ad742001781",
                byte_length=8_033,
                fmt="json",
                role="publisherSource",
                source_iri="https://www.ecfr.gov/api/versioner/v1/titles.json",
            ),
        ),
        reader=API_CAPTURE_JSON_READER,
        identity_policy="source-local-record",
        policies=DIRECT_SKOS_POLICIES,
        rdf_source=_rdf_source_policy(
            frozenset(
                {
                    "identifiers",
                    "is_general_subject_concept",
                    "latest_amended_on",
                    "latest_issue_date",
                    "name",
                    "reserved",
                    "sourceArtifact",
                    "title_number",
                    "up_to_date_as_of",
                }
            )
        ),
    ),
    SourceSpec(
        name="govinfo-collections",
        kind="vocabulary",
        release_keys=("govinfo-collections",),
        inputs=(
            SourcePin(
                path=(
                    "tests/fixtures/govinfo_collections/"
                    "govinfo-collections-2026-08-03.json"
                ),
                sha256="sha256:82cd4191d6abf88c0c1443284e8466a380a7841889cfe79cf19e92864b0dc347",
                byte_length=4_803,
                fmt="json",
                role="publisherSource",
                source_iri="https://api.govinfo.gov/collections",
            ),
        ),
        reader=API_CAPTURE_JSON_READER,
        identity_policy="source-local-record",
        policies=DIRECT_SKOS_POLICIES,
        rdf_source=_rdf_source_policy(
            frozenset(
                {
                    "conceptIdentityClaimed",
                    "id",
                    "identifiers",
                    "labels",
                    "sourceArtifact",
                    "sourceOrdinal",
                    "sourcePath",
                    "uses",
                }
            )
        ),
    ),
    SourceSpec(
        name="usaspending-award-types",
        kind="vocabulary",
        release_keys=("usaspending-award-types",),
        inputs=(
            SourcePin(
                path=(
                    "tests/fixtures/usaspending_gsdm_codes/"
                    "usaspending-award-types-2026-08-03.json"
                ),
                sha256="sha256:682269b46e0cf200c7002ca7d55ba3da3de8dc345958d579ec98e579fc6782e7",
                byte_length=1_271,
                fmt="json",
                role="publisherSource",
                source_iri=(
                    "https://api.usaspending.gov/api/v2/references/award_types/"
                ),
            ),
        ),
        reader=API_CAPTURE_JSON_READER,
        identity_policy="source-local-record",
        policies=DIRECT_SKOS_POLICIES,
        rdf_source=_rdf_source_policy(
            frozenset(
                {
                    "category",
                    "identifiers",
                    "is_general_subject_concept",
                    "publisher_label",
                    "resource_name",
                    "sourceArtifact",
                    "source_url",
                    "use",
                }
            )
        ),
    ),
    SourceSpec(
        name="gsdm-reviewed-domain-values-2026-08-03",
        kind="vocabulary",
        release_keys=("gsdm-reviewed-domain-values-2026-08-03",),
        inputs=(
            _registry_source_pin(
                "gsdm-data-dictionary-2026-08-03.json",
                "sha256:3d0f2e3a952297050db5c2a4addf40765460a49d499427da1b57ef3c7edea3c3",
                358_054,
                "https://api.usaspending.gov/api/v2/references/data_dictionary/",
                fmt="json",
                role="completeOnlineDataDictionary",
                construction_path=(
                    "output/registry-real-data-sources/"
                    "gsdm-data-dictionary-2026-08-03.json"
                ),
            ),
        ),
        reader=API_CAPTURE_JSON_READER,
        identity_policy="source-key-derived",
        policies=DIRECT_SKOS_POLICIES,
        rdf_source=_rdf_source_policy(
            frozenset(
                {"code", "codeDescription", "domainGroup", "gsdmElement", "label"}
            )
        ),
    ),
    SourceSpec(
        name="nasa-technology-taxonomy-8817",
        kind="vocabulary",
        release_keys=("nasa-technology-taxonomy-8817",),
        inputs=(
            SourcePin(
                path=(
                    "tests/fixtures/nasa_technology_taxonomy/"
                    "techport-taxonomy-8817-children-2026-08-03.json"
                ),
                sha256="sha256:4e0ed6f5edee5b7e80c8789e4c3ef39c337a1f27de4cddede431feb94d314932",
                byte_length=3_408,
                fmt="json",
                role="publisherSource",
                source_iri="https://techport.nasa.gov/api/taxonomies/8817",
            ),
            SourcePin(
                path=(
                    "tests/fixtures/nasa_technology_taxonomy/"
                    "techport-taxonomy-roots-2026-08-03.json"
                ),
                sha256="sha256:c0c4b8e154f337be41f59b6b61bdd3b6b673b33bd49e5904b780e640391cbb07",
                byte_length=143,
                fmt="json",
                role="publisherSource",
                source_iri="https://techport.nasa.gov/api/taxonomies",
            ),
        ),
        reader=API_CAPTURE_JSON_READER,
        identity_policy="source-local-record",
        policies=DIRECT_SKOS_POLICIES,
        rdf_source=_rdf_source_policy(
            frozenset(
                {
                    "conceptIdentityClaimed",
                    "id",
                    "identifiers",
                    "labels",
                    "sourceArtifact",
                    "sourceOrdinal",
                    "sourcePath",
                    "uses",
                }
            )
        ),
    ),
    SourceSpec(
        name="fcc-ecfs-filing-types",
        kind="vocabulary",
        release_keys=("fcc-ecfs-filing-types",),
        inputs=(
            SourcePin(
                path=(
                    "tests/fixtures/fcc_ecfs_codes/"
                    "fcc-ecfs-filings-2026-08-03.json"
                ),
                sha256="sha256:4393e9c73ab5e12e25c79a707ca85856ba1d9cc1c3eccdfdfa235223f17773da",
                byte_length=51_284,
                fmt="json",
                role="publisherSource",
                source_iri=(
                    "https://publicapi.fcc.gov/ecfs/filings?"
                    "limit=25&sort=date_disseminated,DESC"
                ),
            ),
        ),
        reader=API_CAPTURE_JSON_READER,
        identity_policy="source-local-record",
        policies=DIRECT_SKOS_POLICIES,
        rdf_source=_rdf_source_policy(
            frozenset(
                {
                    "conceptIdentityClaimed",
                    "id",
                    "identifiers",
                    "labels",
                    "sourceArtifact",
                    "sourceOrdinal",
                    "sourcePath",
                    "uses",
                }
            )
        ),
    ),
    SourceSpec(
        name="fcc-ecfs-access-statuses",
        kind="vocabulary",
        release_keys=("fcc-ecfs-access-statuses",),
        inputs=(
            SourcePin(
                path=(
                    "tests/fixtures/fcc_ecfs_codes/"
                    "fcc-ecfs-filings-2026-08-03.json"
                ),
                sha256="sha256:4393e9c73ab5e12e25c79a707ca85856ba1d9cc1c3eccdfdfa235223f17773da",
                byte_length=51_284,
                fmt="json",
                role="publisherSource",
                source_iri=(
                    "https://publicapi.fcc.gov/ecfs/filings?"
                    "limit=25&sort=date_disseminated,DESC"
                ),
            ),
        ),
        reader=API_CAPTURE_JSON_READER,
        identity_policy="source-local-record",
        policies=DIRECT_SKOS_POLICIES,
        rdf_source=_rdf_source_policy(
            frozenset(
                {
                    "conceptIdentityClaimed",
                    "id",
                    "identifiers",
                    "labels",
                    "sourceArtifact",
                    "sourceOrdinal",
                    "sourcePath",
                    "uses",
                }
            )
        ),
    ),
    SourceSpec(
        name="fcc-ecfs-bureaus",
        kind="vocabulary",
        release_keys=("fcc-ecfs-bureaus",),
        inputs=(
            SourcePin(
                path=(
                    "tests/fixtures/fcc_ecfs_codes/"
                    "fcc-ecfs-filings-2026-08-03.json"
                ),
                sha256="sha256:4393e9c73ab5e12e25c79a707ca85856ba1d9cc1c3eccdfdfa235223f17773da",
                byte_length=51_284,
                fmt="json",
                role="publisherSource",
                source_iri=(
                    "https://publicapi.fcc.gov/ecfs/filings?"
                    "limit=25&sort=date_disseminated,DESC"
                ),
            ),
        ),
        reader=API_CAPTURE_JSON_READER,
        identity_policy="source-local-record",
        policies=DIRECT_SKOS_POLICIES,
        rdf_source=_rdf_source_policy(
            frozenset(
                {
                    "conceptIdentityClaimed",
                    "id",
                    "identifiers",
                    "labels",
                    "sourceArtifact",
                    "sourceOrdinal",
                    "sourcePath",
                    "uses",
                }
            )
        ),
    ),
    SourceSpec(
        name="fcc-ecfs-proceedings",
        kind="vocabulary",
        release_keys=("fcc-ecfs-proceedings",),
        inputs=(
            SourcePin(
                path=(
                    "tests/fixtures/fcc_ecfs_codes/"
                    "fcc-ecfs-filings-2026-08-03.json"
                ),
                sha256="sha256:4393e9c73ab5e12e25c79a707ca85856ba1d9cc1c3eccdfdfa235223f17773da",
                byte_length=51_284,
                fmt="json",
                role="publisherSource",
                source_iri=(
                    "https://publicapi.fcc.gov/ecfs/filings?"
                    "limit=25&sort=date_disseminated,DESC"
                ),
            ),
        ),
        reader=API_CAPTURE_JSON_READER,
        identity_policy="source-local-record",
        policies=DIRECT_SKOS_POLICIES,
        rdf_source=_rdf_source_policy(
            frozenset(
                {
                    "conceptIdentityClaimed",
                    "id",
                    "identifiers",
                    "labels",
                    "sourceArtifact",
                    "sourceOrdinal",
                    "sourcePath",
                    "uses",
                }
            )
        ),
    ),
    SourceSpec(
        name="federal-hierarchy-orgs-bounded-2026-08-03",
        kind="vocabulary",
        release_keys=("federal-hierarchy-orgs-bounded-2026-08-03",),
        inputs=(
            _registry_source_pin(
                "fh-orgs-default-page.json",
                "sha256:582d409dd3743646dd6ec58acfa2bc8f346168f69b044cd6dd48e06f0c9cba49",
                9_270,
                "https://api.sam.gov/prod/federalorganizations/v1/orgs",
                fmt="json",
                role="boundedPublisherOrganizationPage",
                construction_path=(
                    "output/registry-real-data-sources/fh-orgs-default-page.json"
                ),
            ),
            _registry_source_pin(
                "fh-orgs-sub-tier-page.json",
                "sha256:601b9e7323cd4e6b1fbde3799533cbfb5c1f88d78039df84a24b6d60533eccd7",
                9_476,
                (
                    "https://api.sam.gov/prod/federalorganizations/v1/"
                    "orgs?fhorgtype=Sub-Tier"
                ),
                fmt="json",
                role="boundedPublisherOrganizationPage",
                construction_path=(
                    "output/registry-real-data-sources/fh-orgs-sub-tier-page.json"
                ),
            ),
        ),
        reader=API_CAPTURE_JSON_READER,
        identity_policy="source-key-derived",
        policies=DIRECT_SKOS_POLICIES,
        rdf_source=_rdf_source_policy(
            frozenset(
                {
                    "fhorgid",
                    "fhorgname",
                    "fhorgtype",
                    "full_parent_path_id",
                    "full_parent_path_name",
                    "identifiers",
                    "parent_fhorgid",
                    "parent_org_name",
                    "source_ordinal",
                    "status",
                }
            ),
            additional_relation_predicates=(f"{ATLAS}parentEntity",),
        ),
    ),
    SourceSpec(
        name="govinfo-cfr-package-bounded-2026-08-03",
        kind="vocabulary",
        release_keys=("govinfo-cfr-package-bounded-2026-08-03",),
        inputs=(
            SourcePin(
                path=(
                    "tests/fixtures/govinfo_collections/"
                    "govinfo-package-summary-cfr-2023-title1-vol1-2026-08-03.json"
                ),
                sha256="sha256:705a28865a4fba746e8deb4aff05a21bbd63534201e74c5320f56d505ca3d79e",
                byte_length=1_532,
                fmt="json",
                role="publisherPackageSummary",
                source_iri=(
                    "https://api.govinfo.gov/packages/"
                    "CFR-2023-title1-vol1/summary"
                ),
            ),
            SourcePin(
                path=(
                    "tests/fixtures/govinfo_collections/"
                    "govinfo-premis-cfr-2023-title1-vol1-mini-2026-08-03.xml"
                ),
                sha256="sha256:afeba6d9e48f502c911ef0ec1400accdbaa5cad5d7d056672dce6a54d1326417",
                byte_length=4_268,
                fmt="xml",
                role="publisherPackageFixity",
                source_iri=(
                    "https://api.govinfo.gov/packages/"
                    "CFR-2023-title1-vol1/premis"
                ),
            ),
        ),
        reader=API_CAPTURE_JSON_READER,
        identity_policy="source-key-derived",
        policies=DIRECT_SKOS_POLICIES,
        rdf_source=_rdf_source_policy(frozenset({"fixity", "summary"})),
    ),
    SourceSpec(
        name="sam-uei-bounded-public-entity-2026-08-03",
        kind="vocabulary",
        release_keys=("sam-uei-bounded-public-entity-2026-08-03",),
        inputs=(
            _registry_source_pin(
                "sam-entity-3m-public.json",
                "sha256:3d14996c9e6954af51a183f26168f9f835891f2ec5ef11e2dc6d3180ce6550a1",
                1_076,
                (
                    "https://api.sam.gov/entity-information/v4/entities?"
                    "ueiSAM=YLQMY5SGNE55&includeSections=entityRegistration"
                ),
                fmt="json",
                role="boundedPublicEntityResponse",
                construction_path=(
                    "output/registry-real-data-sources/sam-entity-3m-public.json"
                ),
            ),
        ),
        reader=API_CAPTURE_JSON_READER,
        identity_policy="source-key-derived",
        policies=DIRECT_SKOS_POLICIES,
        rdf_source=_rdf_source_policy(
            frozenset(
                {
                    "accessClassification",
                    "highestLevelOwnerUei",
                    "identifier",
                    "immediateParentUei",
                    "legalBusinessName",
                    "registrationStatus",
                }
            )
        ),
    ),
    SourceSpec(
        name="sam-cage-bounded-public-facility-2026-08-03",
        kind="vocabulary",
        release_keys=("sam-cage-bounded-public-facility-2026-08-03",),
        inputs=(
            _registry_source_pin(
                "sam-entity-3m-public.json",
                "sha256:3d14996c9e6954af51a183f26168f9f835891f2ec5ef11e2dc6d3180ce6550a1",
                1_076,
                (
                    "https://api.sam.gov/entity-information/v4/entities?"
                    "ueiSAM=YLQMY5SGNE55&includeSections=entityRegistration"
                ),
                fmt="json",
                role="boundedPublicEntityResponse",
                construction_path=(
                    "output/registry-real-data-sources/sam-entity-3m-public.json"
                ),
            ),
        ),
        reader=API_CAPTURE_JSON_READER,
        identity_policy="source-key-derived",
        policies=DIRECT_SKOS_POLICIES,
        rdf_source=_rdf_source_policy(
            frozenset(
                {
                    "accessClassification",
                    "associatedUei",
                    "cageStatus",
                    "facilityName",
                    "identifier",
                }
            ),
            additional_relation_predicates=(f"{ATLAS}relatedEntity",),
        ),
    ),
    SourceSpec(
        name="crs-legislative-entities",
        kind="vocabulary",
        release_keys=("crs-legislative-entities",),
        inputs=(
            SourcePin(
                path=(
                    "research/evidence/crs-source-concept-releases-2026-08-04/"
                    "legislative-entities/bundle-manifest.json"
                ),
                construction_path=(
                    "refspec/research/evidence/"
                    "crs-source-concept-releases-2026-08-04/"
                    "legislative-entities/bundle-manifest.json"
                ),
                sha256=(
                    "sha256:aa80aaf0495a5e74a5194374cac05075fe8bcc0f00462618"
                    "53293521544959fd"
                ),
                byte_length=2_744,
                fmt="managed-release-json",
                role="publisherSource",
                source_iri=(
                    "urn:ref:source-artifact:"
                    "aa80aaf0495a5e74a5194374cac05075fe8bcc0f0046261853293521544959fd"
                ),
            ),
        ),
        reader=CRS_SOURCE_CONCEPT_RELEASE_READER,
        identity_policy="source-scoped-identifier",
        policies=DIRECT_SKOS_POLICIES,
        rdf_source=_rdf_source_policy(
            frozenset(
                {"englishOnlyObservation", "sourceEvidence", "sourceIdentity"}
            )
        ),
    ),
    SourceSpec(
        name="crs-legislative-subjects",
        kind="vocabulary",
        release_keys=("crs-legislative-subjects",),
        inputs=(
            SourcePin(
                path=(
                    "research/evidence/crs-source-concept-releases-2026-08-04/"
                    "legislative-subjects/bundle-manifest.json"
                ),
                construction_path=(
                    "refspec/research/evidence/"
                    "crs-source-concept-releases-2026-08-04/"
                    "legislative-subjects/bundle-manifest.json"
                ),
                sha256=(
                    "sha256:f20d688f08134a8b6b1c9a6e202e84c5e051e2786c743df6"
                    "6708be27b55b12e7"
                ),
                byte_length=2_745,
                fmt="managed-release-json",
                role="publisherSource",
                source_iri=(
                    "urn:ref:source-artifact:"
                    "f20d688f08134a8b6b1c9a6e202e84c5e051e2786c743df66708be27b55b12e7"
                ),
            ),
        ),
        reader=CRS_SOURCE_CONCEPT_RELEASE_READER,
        identity_policy="source-scoped-identifier",
        policies=DIRECT_SKOS_POLICIES,
        rdf_source=_rdf_source_policy(
            frozenset(
                {"englishOnlyObservation", "sourceEvidence", "sourceIdentity"}
            )
        ),
    ),
    SourceSpec(
        name="crs-policy-areas",
        kind="vocabulary",
        release_keys=("crs-policy-areas",),
        inputs=(
            SourcePin(
                path=(
                    "research/evidence/crs-source-concept-releases-2026-08-04/"
                    "policy-areas/bundle-manifest.json"
                ),
                construction_path=(
                    "refspec/research/evidence/"
                    "crs-source-concept-releases-2026-08-04/"
                    "policy-areas/bundle-manifest.json"
                ),
                sha256=(
                    "sha256:b5966cb93cc1a28cc87ea914538f9c2f3da0b44fb37f6638"
                    "5170b56954dabeb8"
                ),
                byte_length=2_271,
                fmt="managed-release-json",
                role="publisherSource",
                source_iri=(
                    "urn:ref:source-artifact:"
                    "b5966cb93cc1a28cc87ea914538f9c2f3da0b44fb37f66385170b56954dabeb8"
                ),
            ),
        ),
        reader=CRS_SOURCE_CONCEPT_RELEASE_READER,
        identity_policy="source-scoped-identifier",
        policies=DIRECT_SKOS_POLICIES,
        rdf_source=_rdf_source_policy(
            frozenset(
                {"englishOnlyObservation", "sourceEvidence", "sourceIdentity"}
            )
        ),
    ),
    SourceSpec(
        name="epa-enterprise-vocabulary-label-tree-2026-08-03",
        kind="vocabulary",
        release_keys=("epa-enterprise-vocabulary-label-tree-2026-08-03",),
        inputs=(
            SourcePin(
                path=(
                    "tests/fixtures/epa_enterprise_vocabulary/"
                    "epa-enterprise-vocabulary-tier-1005100-with-definitions.xml"
                ),
                sha256=(
                    "sha256:beea0c4a099e07d3196903814f569ad781b081cc0b73ee47"
                    "aff60d118a786df2"
                ),
                byte_length=647,
                fmt="xml",
                role="boundedPublisherLabelTree",
                source_iri=(
                    "https://ofmpub.epa.gov/sor_internet/registry/termreg/"
                    "searchandretrieve/enterprisevocabulary/search.do?search=&"
                    "searchString=&6578706f7274=1&d-8056443-e=13&"
                    "tierTwoSelected=1005100&checkedIncludeDef=true&showDefs=true"
                ),
            ),
        ),
        policies=DIRECT_SKOS_POLICIES,
        reader=EPA_ENTERPRISE_VOCABULARY_XML_READER,
        identity_policy="source-position-observation",
        rdf_source=_rdf_source_policy(
            frozenset({"depth", "row", "publisherConceptIdentityAvailable"}),
            label_language_inverse="atlas-en-to-source-untagged",
            note_predicate_inverse=SKOS_SCOPE_NOTE,
        ),
    ),
    SourceSpec(
        name="fast-topical-current",
        kind="vocabulary",
        release_keys=("fast-topical-current",),
        inputs=(
            _registry_source_pin(
                "FASTTopical.nt.zip",
                "sha256:217826c90649895bfca71e81e2ed88919b2e061646ec42a185bc12d0bd3c19db",
                55_099_212,
                "https://researchworks.oclc.org/researchdata/fast/FASTTopical.nt.zip",
                fmt="zip-ntriples",
                role="publisherBase",
            ),
            _registry_source_pin(
                "FASTChanges2024-10-27.mrc",
                "sha256:f53c640767cb1c4c0bce85b85a69e382780a65772d4deae30ab3a1a8fa96419a",
                2_726_812,
                "https://fast.oclc.org/fastChanges/FASTChanges2024-10-27.mrc",
                fmt="marc",
                role="publisherChange",
            ),
            _registry_source_pin(
                "FASTChanges2024-12-04.mrc",
                "sha256:06ae6714240ac1d8126cfeff5392feb8004f6a1d16e2bb392c854ecf47a6a011",
                1_797_706,
                "https://fast.oclc.org/fastChanges/FASTChanges2024-12-04.mrc",
                fmt="marc",
                role="publisherChange",
            ),
            _registry_source_pin(
                "FASTChanges2025-05-01.mrc",
                "sha256:0d505664fe5de155d58bd1c178e65112ee4b42067044b6a4cb14f516ef03f116",
                3_827_847,
                "https://fast.oclc.org/fastChanges/FASTChanges2025-05-01.mrc",
                fmt="marc",
                role="publisherChange",
            ),
            _registry_source_pin(
                "FASTChanges2026-02-13.mrc",
                "sha256:98c965420836f0f21aed18599f0216cc61b2f3c2b7ca06cc10f6b9cc1ad374e3",
                10_220_096,
                "https://fast.oclc.org/fastChanges/FASTChanges2026-02-13.mrc",
                fmt="marc",
                role="publisherChange",
            ),
        ),
        policies=DIRECT_SKOS_POLICIES,
        reader=FAST_TOPICAL_NATIVE_READER,
        rdf_source=_rdf_source_policy(
            frozenset(
                {
                    "altLabels",
                    "broaderIds",
                    "heading",
                    "identityStatus",
                    "legacyFstId",
                    "numericId",
                    "publisherIri",
                }
            ),
            label_language_inverse="atlas-en-to-source-untagged",
            relation_scope="member-endpoints",
        ),
    ),
    SourceSpec(
        name="icpsr-subject-thesaurus",
        kind="vocabulary",
        release_keys=("icpsr-subject-thesaurus",),
        inputs=(
            SourcePin(
                path=(
                    "/Users/mikewolfd/Work/spicy-regs/output/"
                    "refspec-vocabulary-portfolio/icpsr/2026-07-30/"
                    "managed-release/managed-release.json"
                ),
                construction_path=(
                    "spicy-regs/output/refspec-vocabulary-portfolio/icpsr/"
                    "2026-07-30/managed-release/managed-release.json"
                ),
                sha256=(
                    "sha256:f3c9f4efa7fd12b6339db9feabb029b17425672293a8fb615"
                    "999c881673ac12a"
                ),
                byte_length=6_267,
                fmt="managed-release-json",
                role="publisherSource",
                source_iri=(
                    "urn:ref:source-artifact:"
                    "f3c9f4efa7fd12b6339db9feabb029b17425672293a8fb615999c881673ac12a"
                ),
            ),
        ),
        policies=DIRECT_SKOS_POLICIES,
        reader=ICPSR_MANAGED_RELEASE_READER,
        rdf_source=_rdf_source_policy(
            frozenset(
                {
                    "identityStatus",
                    "indexTerm",
                    "managedConcept",
                    "sourceArtifactDigests",
                    "sourcePaths",
                    "sourceScheme",
                    "xmlTerm",
                }
            ),
            additional_relation_predicates=(
                f"{ATLAS}thesaurusUse",
                f"{ATLAS}thesaurusUsedFor",
                f"{ATLAS}thesaurusRelated",
            ),
            label_language_inverse="atlas-en-to-source-untagged",
            note_predicate_inverse=SKOS_SCOPE_NOTE,
            relation_predicate_inverse=(
                (f"{ATLAS}thesaurusRelated", f"{SKOS}related"),
            ),
            relation_scope="member-subject",
        ),
    ),
    SourceSpec(
        name="lcsh-eurovoc-alignment-endpoints-2026-08-06",
        kind="vocabulary",
        release_keys=("lcsh-eurovoc-alignment-endpoints-2026-08-06",),
        inputs=(
            _registry_source_pin(
                "eurovoc-lcsh-alignment-20240711.rdf",
                "sha256:dbd6e610ff497c4a39a79924cf50dcf92d5f3e9ab316d58d83c460dba6fb4853",
                332_124,
                (
                    "https://op.europa.eu/o/opportal-service/euvoc-download-handler?"
                    "cellarURI=http%3A%2F%2Fpublications.europa.eu%2Fresource%2F"
                    "distribution%2Feurovoc_alignment_lcsh%2F20240711-0%2Frdf%2F"
                    "skos_core_alignment%2Falign_EuroVoc_LCSH.rdf&"
                    "fileName=align_EuroVoc_LCSH.rdf"
                ),
                fmt="xml",
                role="publisherAlignment",
            ),
            _registry_source_pin(
                "lcsh-subjects-madsrdf-2026-08-06.jsonld.gz",
                "sha256:b33adc284bfb98e39c1331927e9ffee3d73dd0b1b83342906b6ea52c408a5856",
                140_187_915,
                "https://id.loc.gov/download/authorities/subjects.madsrdf.jsonld.gz",
                fmt="jsonld.gz",
                role="publisherBulkSource",
            ),
        ),
        policies=DIRECT_SKOS_POLICIES,
        reader=LCSH_ALIGNMENT_ENDPOINT_JSONLD_READER,
        rdf_source=_rdf_source_policy(
            frozenset(
                {
                    "authorityTypes",
                    "broaderIris",
                    "captureSelection",
                    "lccn",
                    "lineNumber",
                    "recordByteLength",
                    "recordDigest",
                }
            ),
            relation_scope="member-endpoints",
        ),
    ),
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
        name="mesh-descriptors-2026",
        kind="vocabulary",
        release_keys=("mesh-descriptors-2026",),
        inputs=(
            _registry_source_pin(
                "desc2026.xml",
                "sha256:9b034cad8bbd4d8d1ef43816d6fd78d33fada52eddff2a0b4455b1fca35cc5ba",
                312_952_703,
                (
                    "https://nlmpubs.nlm.nih.gov/projects/mesh/"
                    "MESH_FILES/xmlmesh/desc2026.xml"
                ),
                fmt="xml",
            ),
        ),
        reader=MESH_DESCRIPTOR_XML_READER,
        policies=DIRECT_SKOS_POLICIES,
        rdf_source=_rdf_source_policy(
            frozenset(
                {
                    "publisherConceptIri",
                    "descriptorUi",
                    "descriptorClass",
                    "treeNumbers",
                }
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
    construction_language_scope: Any = None
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
            construction_language_scope = (
                payload.get("languageScope") if isinstance(payload, dict) else None
            )
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
    atlas_views: list[tuple[SourceSpec, AtlasView]] = []
    publisher_cache: dict[
        tuple[object, ...],
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
                spec.reader,
                # API captures can share bytes while selecting different lists
                # (four FCC units and two SAM units). Other readers keep main's
                # cross-spec cache sharing, including the EuroVoc partitions.
                (
                    spec.name
                    if spec.reader
                    in {API_CAPTURE_JSON_READER, PATTERN_ROW_READER}
                    else None
                ),
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
                    if spec.reader == "rdf":
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
                    else:
                        reader = _PUBLISHER_READERS.get(spec.reader)
                        if reader is None:
                            raise ValueError(
                                f"unsupported publisher reader {spec.reader!r}"
                            )
                        cached = reader(spec, authenticated_payloads)
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
            compact_native_payload = (
                publisher is not None
                and publisher.source_digest_is_native_payload_digest
                and not publisher.expected_native_payloads
                and spec.rdf_source is not None
            )
            atlas = read_atlas_source(
                distribution,
                packs,
                source_claim_subjects,
                compact_normalized_claims=(
                    publisher is not None and spec.reader != "rdf"
                ),
                compact_native_payload_fields=(
                    spec.rdf_source.evaluated_native_payload_fields
                    if compact_native_payload
                    else None
                ),
                compact_native_payload_atlas_only_fields=(
                    spec.rdf_source.atlas_only_native_payload_fields
                    if compact_native_payload
                    else frozenset()
                ),
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
        elif publisher is not None:
            pair = SourcePair(spec=spec, publisher=publisher, atlas=atlas)
            language_exclusion = _language_exclusion_for_spec(spec)
            if language_exclusion is not None:
                pair = replace(
                    pair,
                    publisher=_apply_declared_language_exclusion(
                        pair,
                        language_exclusion,
                    ),
                )
            pairs.append(pair)
    language_scope_active = any(
        _language_exclusion_for_spec(spec) is not None for spec in specs
    )
    if language_scope_active and pack_pins:
        atlas_language_scope_evidence = _audit_atlas_language_scope(
            distribution,
            pack_pins,
        )
    elif language_scope_active:
        atlas_language_scope_evidence = AtlasLanguageScopeEvidence(
            scan_failures=(
                "atlas-manifest.json declares no authenticated packs to inspect",
            )
        )
    else:
        atlas_language_scope_evidence = AtlasLanguageScopeEvidence()
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
        construction_language_scope=construction_language_scope,
        manifest_digest=manifest_digest,
        pack_pins=dict(sorted(pack_pins.items())),
        verified_pins=frozenset(verified_pins),
        pin_failures=tuple(pin_failures),
        load_failures=tuple(load_failures),
        atlas_language_scope_evidence=atlas_language_scope_evidence,
        source_extract_pairs=tuple(source_extract_pairs),
        scoped_out_specs=scoped_out_specs,
    )


# --------------------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------------------


RDF_COMPARISON_KINDS = frozenset({"vocabulary", "mapping"})
COMPARISON_KINDS = frozenset(
    {*RDF_COMPARISON_KINDS, "native-control", "source-extract"}
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


def check_language_scope(ctx: Context) -> CheckResult:
    """Prove the declared English scope against source cells and every Atlas pack."""
    declared_specs = tuple(
        spec
        for spec in ctx.specs
        if _language_exclusion_for_spec(spec) is not None
    )
    if not declared_specs:
        return _result(
            "language-scope",
            "no language-scope declaration applies to this run",
            [],
        )

    failures: list[str] = []
    if ctx.construction_language_scope != ENGLISH_LANGUAGE_SCOPE:
        failures.append(
            f"{CONSTRUCTION_SUMMARY}: languageScope differs -- expected "
            f"{ENGLISH_LANGUAGE_SCOPE}, observed {ctx.construction_language_scope!r}"
        )
    pairs_by_spec = {pair.spec: pair for pair in ctx.pairs}
    excluded = 0
    for spec in declared_specs:
        pair = pairs_by_spec.get(spec)
        if pair is None:
            failures.append(
                f"{spec.name}: language-scope declaration could not be evaluated because the publisher comparison did not load"
            )
            continue
        evidence = pair.publisher.language_exclusion_evidence
        if evidence is None:
            failures.append(
                f"{spec.name}: language-scope declaration produced no source evidence"
            )
            continue
        excluded += evidence.excluded_claim_count if evidence.applied else 0
        failures.extend(
            f"{spec.name}: {failure}" for failure in evidence.failures
        )

    atlas = ctx.atlas_language_scope_evidence
    failures.extend(
        f"Atlas language-scope scan failed: {failure}"
        for failure in atlas.scan_failures
    )
    if atlas.non_english_literal_count:
        failures.append(
            "Atlas asserts "
            f"{atlas.non_english_literal_count} explicitly tagged non-English or invalid-language literal claim(s) across the distribution; "
            f"examples {list(atlas.non_english_literal_examples)}"
        )
    if atlas.noncanonical_semantic_literal_count:
        failures.append(
            "Atlas asserts "
            f"{atlas.noncanonical_semantic_literal_count} label, definition, or note literal claim(s) without exact @en; "
            f"examples {list(atlas.noncanonical_semantic_literal_examples)}"
        )
    return _result(
        "language-scope",
        f"{excluded} non-English publisher semantic literal claims declared and itemised; "
        f"{atlas.non_english_literal_count} non-English Atlas literal claims observed",
        failures,
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
        if spec.identity_policy not in {
            "publisher-iri",
            "source-local-record",
            "source-key-derived",
            "source-scoped-identifier",
            "source-position-observation",
        }:
            failures.append(
                f"{spec.name}: unsupported identity policy {spec.identity_policy!r}"
            )
        for pin in spec.inputs:
            if not pin.role:
                failures.append(
                    f"{spec.name}: publisher pin {pin.path!r} has no construction role"
                )
            if not pin.source_iri:
                failures.append(
                    f"{spec.name}: publisher pin {pin.path!r} has no source IRI"
                )
        if (
            spec.kind in RDF_COMPARISON_KINDS
            and spec.reader != "rdf"
            and spec.reader not in _PUBLISHER_READERS
        ):
            failures.append(
                f"{spec.name}: no publisher reader is declared for {spec.reader!r}"
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
        if spec.reader == PATTERN_ROW_READER and spec.pattern_row is None:
            failures.append(
                f"{spec.name}: pattern-row reader has no declarative selector"
            )
        if spec.reader != PATTERN_ROW_READER and spec.pattern_row is not None:
            failures.append(
                f"{spec.name}: non-pattern reader must not declare a pattern-row selector"
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
        if spec.kind == "source-extract":
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
    expected_payload_fields = policy.evaluated_native_payload_fields
    reader_native_fields = frozenset(
        field_name
        for payload in pair.publisher.expected_native_payloads.values()
        for field_name in payload
    )
    if pair.publisher.source_digest_is_native_payload_digest:
        reader_native_fields |= expected_payload_fields
    supported_resource_fields = (
        per_record_resource_fields
        | aggregate_relation_fields
        | aggregate_source_evidence_fields
        | reader_native_fields
    )
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
        | set(pair.atlas.compact_native_payload_records)
    )
    for record in sorted(record_ids):
        target = pair.atlas.record_targets.get(record)
        payload = pair.atlas.native_payloads.get(record)
        compact_payload = record in pair.atlas.compact_native_payload_records
        if target is None:
            if payload is None:
                detail = (
                    "has no native payload"
                    if not compact_payload
                    else "has no represented publisher resource"
                )
                failures.append(f"{source}: targetless source record <{record}> {detail}")
                continue

            publisher_relation_digest = payload.get("publisherRelationDigest")
            expected_relation_payload = (
                pair.publisher.expected_relation_payloads.get(
                    publisher_relation_digest,
                )
                if isinstance(publisher_relation_digest, str)
                else None
            )
            if expected_relation_payload is not None:
                publisher_relation = payload.get("publisherRelation")
                if not isinstance(publisher_relation, Mapping):
                    failures.append(
                        f"{source}: source record <{record}> publisherRelation is not an object"
                    )
                    continue
                exact_relation_digest = _canonical_json_digest(publisher_relation)
                if publisher_relation_digest != exact_relation_digest:
                    failures.append(
                        f"{source}: source record <{record}> publisherRelationDigest differs "
                        "from its exact publisher relation payload"
                    )
                if payload != expected_relation_payload:
                    failures.append(
                        f"{source}: source record <{record}> transformed publisher relation "
                        "payload differs from the independent source reconstruction"
                    )
                expected_locator = (
                    "urn:ref:publisher-relation:"
                    + publisher_relation_digest.removeprefix("sha256:")
                )
                if pair.atlas.record_source_locators.get(record) != expected_locator:
                    failures.append(
                        f"{source}: source record <{record}> relation locator differs -- "
                        f"expected <{expected_locator}>"
                    )
                expected_digest = _canonical_json_digest(expected_relation_payload)
                if pair.atlas.record_source_digests.get(record) != expected_digest:
                    failures.append(
                        f"{source}: source record <{record}> transformed relation digest "
                        f"differs -- expected {expected_digest}"
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
        expected_locator = pair.publisher.resource_locators.get(
            target,
            locator_by_resource.get(target, policy.record_locator or target),
        )
        if locator != expected_locator:
            failures.append(
                f"{source}: source record <{record}> locator differs -- expected "
                f"<{expected_locator}>, observed {locator!r}"
            )

        resource_input_path = input_path_by_resource.get(target)
        compact_resource_digest = pair.publisher.resource_input_digest_values.get(
            target
        )
        if resource_input_path in pair.publisher.input_content_digests:
            expected_digests = {
                pair.publisher.input_content_digests[resource_input_path]
            }
        elif default_digests:
            expected_digests = default_digests
        elif compact_resource_digest is not None:
            expected_digests = {compact_resource_digest}
        else:
            expected_digests = set(
                pair.publisher.resource_input_digests.get(target, frozenset())
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

        if payload is None and not compact_payload:
            failures.append(f"{source}: source record <{record}> has no native payload")
            continue
        if payload is None:
            digest_difference = pair.atlas.native_payload_digest_differences.get(
                record
            )
            if digest_difference is not None:
                payload_digest, source_digest = digest_difference
                failures.append(
                    f"{source}: source record <{record}> native payload digest "
                    f"{payload_digest} differs from atlas:sourceDigest {source_digest!r}"
                )
            unexpected_fields, missing_fields = (
                pair.atlas.native_payload_field_differences.get(record, ((), ()))
            )
            for field_name in unexpected_fields:
                unexpected_payload_fields[field_name].append(record)
            if missing_fields:
                failures.append(
                    f"{source}: source record <{record}> native payload omits independently "
                    f"evaluated fields {list(missing_fields)}"
                )
            continue
        for field_name in sorted(
            set(payload)
            - expected_payload_fields
            - policy.atlas_only_native_payload_fields
        ):
            unexpected_payload_fields[field_name].append(record)
        reader_expected_payload = pair.publisher.expected_native_payloads.get(
            target,
            {},
        )
        expected_per_record_fields = per_record_resource_fields | frozenset(
            reader_expected_payload
        )
        if (
            pair.publisher.source_digest_is_native_payload_digest
            and len(expected_digests) == 1
        ):
            expected_per_record_fields |= expected_payload_fields
        missing_fields = sorted(
            (expected_payload_fields & expected_per_record_fields) - set(payload)
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
        for field_name in sorted(expected_payload_fields & reader_expected_payload.keys()):
            expected = reader_expected_payload[field_name]
            if payload.get(field_name) != expected:
                failures.append(
                    f"{source}: source record <{record}> native payload {field_name} "
                    f"differs -- expected {expected!r}, observed {payload.get(field_name)!r}"
                )
        if (
            pair.publisher.source_digest_is_native_payload_digest
            and len(expected_digests) == 1
        ):
            expected_payload_digest = next(iter(expected_digests))
            observed_payload_digest = _canonical_json_digest(payload)
            if observed_payload_digest != expected_payload_digest:
                failures.append(
                    f"{source}: source record <{record}> native payload digest differs -- "
                    f"expected {expected_payload_digest}, observed {observed_payload_digest}"
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
    """Concept identity follows each source's explicit identity policy."""
    failures = _incomplete_evaluation_failure(ctx, "identifier retention", "vocabulary")
    checked = 0
    for pair in ctx.vocabularies():
        atlas_concepts = _atlas_publisher_concepts(pair)
        checked += len(atlas_concepts)
        if pair.spec.identity_policy == "publisher-iri":
            unexpected = sorted(
                resource
                for resource in atlas_concepts
                if resource.startswith("urn:ref:")
            )
            for resource in unexpected:
                failures.append(
                    f"{pair.spec.name}: Atlas concept <{resource}> carries a minted "
                    "RefSpec identifier where the publisher supplies its own IRI"
                )
            continue
        if pair.spec.identity_policy in {
            "source-local-record",
            "source-scoped-identifier",
        }:
            unexpected = sorted(
                resource
                for resource in atlas_concepts
                if not resource.startswith("urn:ref:source-concept:v2:")
            )
        elif pair.spec.identity_policy == "source-position-observation":
            unexpected = sorted(
                resource
                for resource in atlas_concepts
                if not resource.startswith("urn:ref:epa-enterprise-vocabulary-row:")
            )
        else:
            # The stock reader derives and compares the complete resource IRI
            # from a publisher key. Traceability proves exact set equality.
            unexpected = []
        for resource in unexpected:
            failures.append(
                f"{pair.spec.name}: Atlas concept <{resource}> does not use the "
                f"declared {pair.spec.identity_policy} identity form"
            )

    return _result(
        "identifier-retention",
        f"{checked} concept identities checked against declared source identity policies",
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


_LANGUAGE_EXCLUSION_FIELDS = frozenset(
    {
        "schemaVersion",
        "exclusionType",
        "selection",
        "predicateFamilies",
        "countsBySourceAndLanguage",
        "totalExcludedClaims",
    }
)
_LANGUAGE_EXCLUSION_SELECTION = {
    "countUnit": (
        "unique auditor semantic literal claim after SourceSpec subset selection"
    ),
    "excludedClaimRule": (
        "language tag is present and primary language subtag is not en"
    ),
    "includedLanguageFamilies": ["en"],
    "selectionRule": "bcp47-primary-language-subtag",
}


def _language_exclusion_payload_parts(
    declaration: DeclaredLanguageExclusion,
    source: str,
) -> tuple[
    Mapping[str, tuple[str, ...]],
    Mapping[str, Mapping[str, int]],
    tuple[str, ...],
]:
    """Validate one authenticated count declaration without accepting drift."""
    failures: list[str] = []
    try:
        payload = declaration.payload()
    except (TypeError, ValueError) as error:
        return {}, {}, (f"declaration payload is not valid JSON: {error}",)
    if set(payload) != _LANGUAGE_EXCLUSION_FIELDS:
        failures.append(
            "declaration fields differ -- expected "
            f"{sorted(_LANGUAGE_EXCLUSION_FIELDS)}, observed {sorted(payload)}"
        )
    if payload.get("schemaVersion") != "1.0":
        failures.append("declaration schemaVersion must be '1.0'")
    if payload.get("exclusionType") != "languageFamily":
        failures.append("declaration exclusionType must be 'languageFamily'")
    if payload.get("selection") != _LANGUAGE_EXCLUSION_SELECTION:
        failures.append(
            "declaration selection differs from the executable BCP 47 rule"
        )

    raw_families = payload.get("predicateFamilies")
    predicate_families: dict[str, tuple[str, ...]] = {}
    if not isinstance(raw_families, dict):
        failures.append("declaration predicateFamilies must be an object")
    else:
        for family, predicates in raw_families.items():
            if (
                not isinstance(family, str)
                or not family
                or not isinstance(predicates, list)
                or not predicates
                or not all(isinstance(predicate, str) and predicate for predicate in predicates)
                or len(set(predicates)) != len(predicates)
            ):
                failures.append(
                    f"declaration predicate family {family!r} must contain unique IRI strings"
                )
                continue
            predicate_families[family] = tuple(predicates)

    raw_counts = payload.get("countsBySourceAndLanguage")
    counts_by_source: dict[str, dict[str, dict[str, int]]] = {}
    declared_total = 0
    if not isinstance(raw_counts, dict):
        failures.append("declaration countsBySourceAndLanguage must be an object")
    else:
        for source_name, language_rows in raw_counts.items():
            if not isinstance(source_name, str) or not isinstance(language_rows, dict):
                failures.append("declaration source count rows must be objects")
                continue
            parsed_languages: dict[str, dict[str, int]] = {}
            for language, family_rows in language_rows.items():
                if (
                    not isinstance(language, str)
                    or _BCP47.fullmatch(language) is None
                    or language.casefold() == "en"
                    or language.casefold().startswith("en-")
                ):
                    failures.append(
                        f"declaration language {language!r} is not a valid non-English BCP 47 tag"
                    )
                    continue
                if not isinstance(family_rows, dict) or not family_rows:
                    failures.append(
                        f"declaration count cell {source_name}/{language} must be a non-empty object"
                    )
                    continue
                parsed_families: dict[str, int] = {}
                for family, count in family_rows.items():
                    if family not in predicate_families:
                        failures.append(
                            f"declaration count cell {source_name}/{language} uses unknown family {family!r}"
                        )
                    if (
                        not isinstance(count, int)
                        or isinstance(count, bool)
                        or count <= 0
                    ):
                        failures.append(
                            f"declaration count cell {source_name}/{language}/{family} must be a positive integer"
                        )
                        continue
                    parsed_families[family] = count
                    declared_total += count
                parsed_languages[language] = parsed_families
            counts_by_source[source_name] = parsed_languages
    expected_total = payload.get("totalExcludedClaims")
    if (
        not isinstance(expected_total, int)
        or isinstance(expected_total, bool)
        or expected_total != declared_total
    ):
        failures.append(
            "declaration totalExcludedClaims does not equal its source/language/family cells: "
            f"expected {expected_total!r}, summed {declared_total}"
        )
    if source not in counts_by_source:
        failures.append(f"declaration has no count row for source {source!r}")
    return (
        predicate_families,
        counts_by_source.get(source, {}),
        tuple(failures),
    )


def _language_semantic_literal_claims(
    pair: SourcePair,
) -> frozenset[tuple[str, str, str, LiteralValue]]:
    """Resolve literal claims to the exact semantic families in the declaration."""
    publisher = pair.publisher
    rows: set[tuple[str, str, str, LiteralValue]] = set()
    for family, predicate, values_by_subject in (
        ("preferredLabels", SKOS_PREF_LABEL, publisher.pref_labels),
        ("alternateLabels", SKOS_ALT_LABEL, publisher.alt_labels),
        ("hiddenLabels", SKOS_HIDDEN_LABEL, publisher.hidden_labels),
        ("notations", SKOS_NOTATION, publisher.notations),
    ):
        rows.update(
            (family, subject, predicate, literal)
            for subject, values in values_by_subject.items()
            if subject in publisher.concepts
            for literal in values
        )
    note_predicates = _source_note_predicates(pair)
    rows.update(
        (
            "definitions" if predicate == SKOS_DEFINITION else "notes",
            subject,
            predicate,
            literal,
        )
        for subject, predicate, literal in publisher.annotations
        if subject in publisher.concepts
        and (predicate == SKOS_DEFINITION or predicate in note_predicates)
    )
    rows.update(
        ("memberMetadataLiterals", subject, predicate, literal)
        for subject, predicate, literal in _publisher_member_metadata_literals(pair)
    )
    rows.update(
        ("sourceSchemeLiterals", subject, predicate, literal)
        for subject, predicate, literal in _publisher_source_scheme_literal_claims(pair)
    )
    rows.update(
        ("sourceWideLiterals", subject, predicate, literal)
        for subject, predicate, literal in _publisher_source_wide_literals(pair)
    )
    return frozenset(rows)


def _normalized_language_counts(
    counts: Mapping[str, Mapping[str, int]],
) -> dict[str, dict[str, int]]:
    """Compare BCP 47 tags case-insensitively while retaining receipt spellings."""
    normalized: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for language, families in counts.items():
        for family, count in families.items():
            normalized[language.casefold()][family] += count
    return {
        language: dict(sorted(families.items()))
        for language, families in sorted(normalized.items())
    }


def _apply_declared_language_exclusion(
    pair: SourcePair,
    declaration: DeclaredLanguageExclusion,
) -> PublisherView:
    """Set aside only exactly declared non-English semantic literal claims."""
    predicate_families, expected_counts, payload_failures = (
        _language_exclusion_payload_parts(declaration, pair.spec.name)
    )
    failures = list(payload_failures)
    candidates = _language_semantic_literal_claims(pair)
    selected: set[tuple[str, str, str, LiteralValue]] = set()
    actual_counter: Counter[tuple[str, str]] = Counter()
    declared_predicates = frozenset(
        predicate
        for predicates in predicate_families.values()
        for predicate in predicates
    )
    invalid: list[str] = []
    undeclared: list[str] = []
    for family, subject, predicate, literal in sorted(
        candidates,
        key=lambda row: (
            row[0],
            row[1],
            row[2],
            row[3].language or "",
            row[3].value,
            row[3].datatype or "",
        ),
    ):
        language = literal.language
        if language is None:
            continue
        if _BCP47.fullmatch(language) is None:
            invalid.append(
                f"<{subject}> <{predicate}> {_literal_repr(literal)}"
            )
            continue
        normalized = language.casefold()
        if normalized == "en" or normalized.startswith("en-"):
            continue
        # The family is the existing auditor comparison that owns this claim.
        # The payload's predicate families also form one closed predicate
        # inventory. A publisher claim may be reached through two comparison
        # roles (for example, a label on an explicit source scheme), so require
        # both a declared role and a globally declared predicate without
        # pretending the role/predicate lists are disjoint.
        if family not in predicate_families or predicate not in declared_predicates:
            undeclared.append(
                f"{family}: <{subject}> <{predicate}> {_literal_repr(literal)}"
            )
            continue
        selected.add((family, subject, predicate, literal))
        actual_counter[(language, family)] += 1

    if invalid:
        failures.append(
            f"{len(invalid)} explicitly tagged semantic literal claim(s) have invalid BCP 47 tags; examples {invalid[:5]}"
        )
    if undeclared:
        failures.append(
            f"{len(undeclared)} non-English semantic literal claim(s) use an undeclared predicate family; examples {undeclared[:5]}"
        )
    actual_counts: dict[str, dict[str, int]] = defaultdict(dict)
    for (language, family), count in sorted(actual_counter.items()):
        actual_counts[language][family] = count
    expected_normalized = _normalized_language_counts(expected_counts)
    actual_normalized = _normalized_language_counts(actual_counts)
    if expected_normalized != actual_normalized:
        failures.append(
            "declared source/language/predicate-family cells differ from authenticated publisher bytes: "
            f"expected {expected_normalized}, observed {actual_normalized}"
        )

    identity_rows = [
        {
            "datatype": literal.datatype,
            "family": family,
            "language": literal.language,
            "predicate": predicate,
            "subject": subject,
            "value": literal.value,
        }
        for family, subject, predicate, literal in sorted(
            selected,
            key=lambda row: (
                row[0],
                row[1],
                row[2],
                row[3].language or "",
                row[3].value,
                row[3].datatype or "",
            ),
        )
    ]
    identity_digest = "sha256:" + hashlib.sha256(
        json.dumps(
            identity_rows,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    evidence = LanguageExclusionEvidence(
        expected_counts_by_language={
            language: dict(sorted(families.items()))
            for language, families in sorted(expected_counts.items())
        },
        actual_counts_by_language={
            language: dict(sorted(families.items()))
            for language, families in sorted(actual_counts.items())
        },
        excluded_claim_count=len(selected),
        excluded_claims_digest=identity_digest,
        applied=not failures,
        failures=tuple(failures),
    )
    if failures:
        return replace(pair.publisher, language_exclusion_evidence=evidence)

    excluded_labels: dict[str, set[tuple[str, LiteralValue]]] = defaultdict(set)
    excluded_annotations: set[tuple[str, str, LiteralValue]] = set()
    excluded_direct_literals: set[tuple[str, str, LiteralValue]] = set()
    for family, subject, predicate, literal in selected:
        if family in {"preferredLabels", "alternateLabels", "hiddenLabels"}:
            excluded_labels[family].add((subject, literal))
        elif family in {"definitions", "notes"}:
            excluded_annotations.add((subject, predicate, literal))
        excluded_direct_literals.add((subject, predicate, literal))

    def filtered_values(
        family: str,
        values: Mapping[str, frozenset[LiteralValue]],
    ) -> dict[str, frozenset[LiteralValue]]:
        result: dict[str, frozenset[LiteralValue]] = {}
        excluded = excluded_labels[family]
        for subject, literals in values.items():
            retained = frozenset(
                literal
                for literal in literals
                if (subject, literal) not in excluded
            )
            if retained:
                result[subject] = retained
        return result

    pref = filtered_values("preferredLabels", pair.publisher.pref_labels)
    alt = filtered_values("alternateLabels", pair.publisher.alt_labels)
    hidden = filtered_values("hiddenLabels", pair.publisher.hidden_labels)
    # Source-scheme display literals use the same maps but a different semantic
    # family, so remove their exact rows without touching English concept labels.
    scheme_selected = {
        (subject, predicate, literal)
        for family, subject, predicate, literal in selected
        if family == "sourceSchemeLiterals"
    }
    for values, predicate in (
        (pref, SKOS_PREF_LABEL),
        (alt, SKOS_ALT_LABEL),
        (hidden, SKOS_HIDDEN_LABEL),
    ):
        for subject in tuple(values):
            retained = frozenset(
                literal
                for literal in values[subject]
                if (subject, predicate, literal) not in scheme_selected
            )
            if retained:
                values[subject] = retained
            else:
                del values[subject]

    return replace(
        pair.publisher,
        pref_labels=pref,
        alt_labels=alt,
        hidden_labels=hidden,
        annotations=frozenset(
            row
            for row in pair.publisher.annotations
            if row not in excluded_annotations
        ),
        literal_claims=frozenset(
            row
            for row in pair.publisher.literal_claims
            if row not in excluded_direct_literals
        ),
        pref_label_count_all_languages=sum(len(values) for values in pref.values()),
        alt_label_count_all_languages=sum(len(values) for values in alt.values()),
        hidden_label_count_all_languages=sum(len(values) for values in hidden.values()),
        language_exclusion_evidence=evidence,
    )


def _atlas_source_targets(pair: SourcePair) -> frozenset[str]:
    """Resources explicitly linked to publisher evidence by a source record."""
    return frozenset(pair.atlas.record_targets.values())


def _atlas_publisher_concepts(pair: SourcePair) -> frozenset[str]:
    """Resources explicitly asserted in the publisher's SKOS concept shape.

    Atlas-owned resources, rings, profiles, and governed schemes are deliberately
    absent from this view. The binding validator owns those claims.
    """
    if pair.spec.reader in {
        API_CAPTURE_JSON_READER,
        CRS_SOURCE_CONCEPT_RELEASE_READER,
        PATTERN_ROW_READER,
    }:
        # Structured JSON captures also describe value, structure, entity, and
        # legal-identity resources. Their source records are the exact
        # independent join; requiring skos:Concept here would discard every
        # non-subject row.
        return _atlas_source_targets(pair)
    return frozenset(
        {
            *(
                resource
                for resource, types in pair.atlas.rdf_types.items()
                if SKOS_CONCEPT in types
            ),
            *(
                subject
                for subject, predicate, obj in pair.atlas.raw_source_iri_claims
                if predicate == RDF_TYPE and obj == SKOS_CONCEPT
            ),
        }
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


def _declared_language_exclusion_report(pair: SourcePair) -> list[dict[str, Any]]:
    """Itemise one claim-level language declaration and its paired Atlas proof."""
    declaration = _language_exclusion_for_spec(pair.spec)
    evidence = pair.publisher.language_exclusion_evidence
    if declaration is None or evidence is None:
        return []
    payload = declaration.payload()
    atlas_claims = sorted(
        (
            row
            for row in pair.atlas.all_raw_literal_claims
            if row[2].language is not None
            and (
                _BCP47.fullmatch(row[2].language) is None
                or row[2].language.casefold() != "en"
            )
        ),
        key=_literal_claim_sort_key,
    )
    holds = evidence.applied and not atlas_claims
    return [
        {
            "name": declaration.name,
            "reason": declaration.reason,
            "exclusionType": payload.get("exclusionType"),
            "schemaVersion": payload.get("schemaVersion"),
            "payloadDigest": declaration.payload_sha256,
            "selection": payload.get("selection"),
            "predicateFamilies": payload.get("predicateFamilies"),
            "expectedCountsByLanguage": evidence.expected_counts_by_language,
            "actualCountsByLanguage": evidence.actual_counts_by_language,
            "publisherClaimCount": evidence.excluded_claim_count,
            "publisherClaimsDigest": evidence.excluded_claims_digest,
            "atlasClaimCount": len(atlas_claims),
            "atlasClaimExamples": [
                [subject, predicate, _literal_repr(literal)]
                for subject, predicate, literal in atlas_claims[:5]
            ],
            "failures": list(evidence.failures),
            "status": "declared-out-of-scope" if holds else "violated",
            "meaning": (
                "only explicitly tagged publisher semantic literal claims outside "
                "the BCP 47 English family; the authenticated source bytes, exact "
                "source/language/predicate-family cells, and claim digest make the "
                "set reconstructable, while every untagged, IRI, and English claim "
                "stays in its normal comparison"
            ),
        }
    ]


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
        language_evidence = pair.publisher.language_exclusion_evidence
        if language_evidence is not None and language_evidence.applied:
            declared_out_of_scope += language_evidence.excluded_claim_count
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
    check_language_scope,
    check_claim_scope,
    check_distribution_coverage,
    check_publisher_input_pins,
    check_graph_structure,
    check_rdf_provenance_fidelity,
    check_native_control_fidelity,
    check_source_extract_fidelity,
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
        *_declared_language_exclusion_report(pair),
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
    for kind in ("native-control", "source-extract"):
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
                if family.get("exclusionType") == "languageFamily":
                    failures.append(
                        f"{pair.spec.name}: declared language exclusion {family['name']} does not "
                        f"hold -- Atlas asserts {family['atlasClaimCount']} non-English literal claim(s); examples "
                        f"{family['atlasClaimExamples'][:5]}"
                    )
                else:
                    failures.append(
                        f"{pair.spec.name}: declared exclusion {family['name']} does not "
                        f"hold -- Atlas asserts {family['atlasClaimCount']} claim(s) about "
                        f"subjects it declares out of scope; examples "
                        f"{family['atlasClaimExamples'][:5]}"
                    )
            if family.get("failures"):
                failures.extend(
                    f"{pair.spec.name}: declared language exclusion {family['name']} does not hold -- {failure}"
                    for failure in family["failures"]
                )
            if family.get("comparedSubjectOverlapCount", 0):
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
                "publisherReader": spec.reader,
                "identityPolicy": spec.identity_policy,
                "subset": spec.subset,
                "includedPublisherConceptIris": sorted(spec.included_concept_iris),
                "releaseKeys": list(spec.release_keys),
                "publisherLoaded": (
                    spec in native_controls_by_spec
                    if spec.kind == "native-control"
                    else spec in source_extracts_by_spec
                    if spec.kind == "source-extract"
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
        "languageScope": {
            "expectedConstructionStatement": ENGLISH_LANGUAGE_SCOPE,
            "observedConstructionStatement": ctx.construction_language_scope,
            "sourceDeclarationCount": sum(
                _language_exclusion_for_spec(spec) is not None
                for spec in ctx.specs
            ),
            "declaredPublisherClaimCount": sum(
                (
                    pair.publisher.language_exclusion_evidence.excluded_claim_count
                    if pair.publisher.language_exclusion_evidence is not None
                    and pair.publisher.language_exclusion_evidence.applied
                    else 0
                )
                for pair in ctx.pairs
            ),
            "atlasNonEnglishLiteralClaimCount": (
                ctx.atlas_language_scope_evidence.non_english_literal_count
            ),
            "atlasNonEnglishLiteralClaimsDigest": (
                ctx.atlas_language_scope_evidence.non_english_literals_digest
            ),
            "atlasNonEnglishLiteralClaimExamples": list(
                ctx.atlas_language_scope_evidence.non_english_literal_examples
            ),
            "atlasNoncanonicalSemanticLiteralClaimCount": (
                ctx.atlas_language_scope_evidence.noncanonical_semantic_literal_count
            ),
            "atlasNoncanonicalSemanticLiteralClaimsDigest": (
                ctx.atlas_language_scope_evidence.noncanonical_semantic_literals_digest
            ),
            "atlasNoncanonicalSemanticLiteralClaimExamples": list(
                ctx.atlas_language_scope_evidence.noncanonical_semantic_literal_examples
            ),
            "atlasScanFailures": list(
                ctx.atlas_language_scope_evidence.scan_failures
            ),
        },
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
