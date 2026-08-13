"""Independent validator for the RefSpec Atlas 3.1 binding.

The validator deliberately imports no RefSpec package code.  A consumer can
copy this binding directory, install ``requirements.txt``, and verify an Atlas
distribution offline.

Three entry points, and only one of them is acceptance:

``validate_distribution`` (``--distribution``)
    The verdict.  Every gate, whole distribution, nothing sampled.

``validate_binding`` (no arguments)
    The binding's own corpus: schemas, ontology, shapes, and every fixture.

``smoke_check`` (``--smoke``)
    A bounded sample, in seconds, that proves nothing about the distribution
    as a whole.  See its docstring for exactly what it does and does not
    check.  It never reads or writes the validation receipt cache.

SHACL, and why red builds are fast.  Data conformance runs through a batched
fast path (``_batched_shacl_plan``) whose conformance verdict is equivalent to
the normative shapes.  Until 2026-08-11 a *failing* graph then re-ran the full
normative engine over the whole graph purely to phrase the report: measured on
a 32M-quad non-conforming distribution, that report cost **94 minutes**, 78%
of a two-hour run, on the exact path a developer iterates on.  So the default
red path now reports from the focus nodes the fast path already named,
re-validated under the unmodified normative shapes over the unmodified data
graph (``_focused_shacl_report``) -- the same engine, the same ``shacl.data``
code, the same constraint-component list.  Setting
``REFSPEC_ATLAS_VALIDATION_MODE=audit`` restores the whole-graph normative run
for release and audit use; anything else, including unset, fails fast.  Both
decisions, the measurement behind them, and the smoke tier are recorded in
``plans/validation-cost-reset-plan.md`` ("What the 2h instrumented run
changes", items 1-2).
"""

from __future__ import annotations

import argparse
import contextlib
import gc
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import stat
import sys
import time
from collections import Counter, defaultdict, deque
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, datetime
from decimal import Decimal
from functools import lru_cache
from itertools import chain, combinations
from pathlib import Path
from types import MappingProxyType
from typing import Any, NoReturn, TextIO

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from jsonschema import _utils as jsonschema_utils
from jsonschema import validators as jsonschema_validators
from owlrl import DeductiveClosure, OWLRL_Semantics
from parse_substrate import (
    MEMORY_STORE,
    RDF_STORE_ENV,
    TWO_INDEX_STORE,
    TermPool,
    TwoIndexStore,
)
from pyshacl import validate as shacl_validate
from pyshacl.rdfutil import inoculate
from rdf_canonical import (
    ABSOLUTE_IRI_RE,
    RdfCanonicalError,
    canonical_line_issue,
    canonical_line_issue_and_terms,
)
from rdf_canonical import ntriples_term as _canonical_ntriples_term
from rdflib import BNode, Dataset, Graph, Literal, Namespace, URIRef
from rdflib.graph import ReadOnlyGraphAggregate
from rdflib.namespace import DCTERMS, OWL, PROV, RDF, RDFS, SH, SKOS, XSD
from rdflib.parser import create_input_source
from rdflib.plugins.parsers.nquads import NQuadsParser
from rdflib.plugins.parsers.ntriples import (
    URI,
    ParseError,
    r_literal,
    r_tail,
    r_uriref,
    r_wspace,
    unquote,
    uriquote,
)
from referencing import Registry, Resource

try:  # Python 3.14+
    from compression import zstd
except ImportError:  # Python 3.10-3.13
    from backports import zstd

BINDING_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BINDING_ROOT.parents[2]
SCHEMA_ROOT = BINDING_ROOT / "schemas"
ONTOLOGY_PATH = BINDING_ROOT / "ontology" / "atlas.ttl"
SHAPES_PATH = BINDING_ROOT / "shapes" / "atlas.shacl.ttl"
FIXTURE_ROOT = BINDING_ROOT / "fixtures"
CORPUS_PATH = FIXTURE_ROOT / "corpus.json"
PROFILE_MAP_PATH = BINDING_ROOT / "registry-resource-profiles.json"
REGISTRY_COVERAGE_PATH = BINDING_ROOT / "tests" / "registry-coverage.json"
REGISTRY_DESCRIPTOR_PROOF_PATH = BINDING_ROOT / "tests" / "registry-descriptors.json"
REGISTRY_DESCRIPTOR_DATASET_PATH = BINDING_ROOT / "tests" / "registry-descriptors.nq"
# The semantic contract: the RULES a distribution is validated *against*.
# Changing any of these changes what conformance means, so every fixture must
# be reissued against the new meaning -- that is the point of pinning them into
# each manifest and acceptance record as `contractDigest`.
#
# `fixtures/corpus.json` is deliberately NOT here, and that is the whole
# distinction this list now draws. The corpus is the PROOF that this validator
# behaves as the rules say; it is not one of the rules. While it sat in this
# list, adding a single conformance case moved the contract digest, which moved
# every manifest, acceptance record and construction summary on disk, which
# broke the external manifest pins and invalidated a signed release -- for a
# contract that had not moved a byte. Proof identity lives where the proof is
# described instead: `corpus_digest()` is recorded in each acceptance record,
# beside the validator identity it qualifies. See REF-029.
CONTRACT_PATHS = (
    Path("ontology/atlas.ttl"),
    Path("registry-resource-profiles.json"),
    Path("shapes/atlas.shacl.ttl"),
    Path("tests/registry-coverage.json"),
    Path("tests/registry-descriptors.json"),
    Path("tests/registry-descriptors.nq"),
)

# The programs that read that contract, and the versions they run against.
# These decide the exact bytes the builder emits, which is why the fixture
# receipt hashes them, but they do not decide what conformance *means* -- and
# which validator produced a verdict is already declared, by name and number,
# through VALIDATOR_ID/VALIDATOR_VERSION in every manifest and acceptance
# record and checked by _check_binding_pins. Folding their source into
# contractDigest said the same thing a second way and made every edit to
# a tool reissue the whole corpus for a contract that had not moved. README.md
# is in neither list: it is prose, and prose settles nothing.
#
# Conformance identity must not move when a program changes, but a *cached
# verdict* is only as good as the program that computed it: a new refusal added
# here would otherwise be answered from a receipt the old validator wrote, and
# the cache returns before the procedural checks ever run. So the validation
# cache key covers this list and the runtime below as well as the contract --
# identity is contract-only, cache validity is contract plus tools.
BINDING_TOOL_PATHS = (
    Path("requirements.txt"),
    Path("tools/build_fixtures.py"),
    Path("tools/parse_substrate.py"),
    Path("tools/rdf_canonical.py"),
    Path("tools/validate.py"),
)

ATLAS = Namespace("https://refspec.org/ns/atlas/v3#")
# Rulespec's namespace. Atlas references it; it never mints inside it.
RKAF = Namespace("https://rulespec.org/ns/v1#")
SKOSXL = Namespace("http://www.w3.org/2008/05/skos-xl#")

VALIDATOR_ID = "refspec-atlas-conformance"
VALIDATOR_VERSION = "3.1"
EXACT_MATCH_TRANSITIVITY_RULE = URIRef("urn:ref:rule:skos-exact-match-closure-path")
DERIVATION_ENGINE = URIRef("https://pypi.org/project/owlrl/7.1.4/")
DERIVATION_ENGINE_VERSION = "7.1.4"

SCHEMAS = {
    "manifest": "atlas-manifest.schema.json",
    "sourceAccounting": "atlas-source-accounting.schema.json",
    "acceptance": "atlas-acceptance.schema.json",
    "producerValidation": "atlas-producer-validation.schema.json",
    "constructionSummary": "atlas-construction-summary.schema.json",
    "corpus": "conformance-corpus.schema.json",
    "registryCoverage": "registry-coverage.schema.json",
    "registryDescriptors": "registry-descriptors.schema.json",
    "registryProfiles": "registry-resource-profiles.schema.json",
}
MANIFEST_FILE = "atlas-manifest.json"
PRODUCER_VALIDATION_FILE = "atlas-producer-validation.json"
CONSTRUCTION_SUMMARY_FILE = "atlas-construction-summary.json"
CACHE_FORMAT = "refspec-atlas-validation-receipt-cache/1"
CACHE_SECRET_BYTES = 32
CACHE_RECEIPT_MAX_BYTES = 4 * 1024 * 1024
SAFE_INTEGER = 9_007_199_254_740_991
NQUADS_MAX_LINE_BYTES = 16 * 1024 * 1024
# RDF packs were bounded per line only, so a manifest could declare a pack
# whose decompressed content was unbounded -- decompression-bomb shaped, on
# the path an offline third-party consumer runs. They are the same class of
# resource as a compact pack: bytes a self-declared manifest field would
# otherwise authorize without limit, so they take the same per-pack content
# ceiling, and they share the compact path's per-pack transport ceiling
# (COMPACT_PACK_MAX_TRANSPORT_BYTES) for the same reason. One manifest can
# list many packs, so an aggregate ceiling bounds the sum across a single
# distribution independently of any one pack's size.
#
# Measured against the largest real Atlas builds under output/ (126 RDF packs
# each): the largest single pack declares 1,010,406,706 content bytes
# (0.94 GiB) and the largest aggregate is 7,302,404,152 (6.80 GiB), against a
# largest transport of 55,991,749 (53.4 MiB). The ceilings leave 4.2x, 4.5x
# and 19x headroom respectively -- room for the registry to several times
# outgrow today's build before a legitimate distribution meets a limit, while
# still refusing the 504 GiB that 126 unbounded packs would otherwise
# authorize.
NQUADS_MAX_CONTENT_BYTES = 4 * 1024 * 1024 * 1024
NQUADS_MAX_TRANSPORT_BYTES = 1 * 1024 * 1024 * 1024
NQUADS_DATASET_MAX_CONTENT_BYTES = 32 * 1024 * 1024 * 1024
COMPACT_RDF_SAMPLE_SIZE = 5
# The smoke tier's sample. See `smoke_check`: up to three packs per pack kind,
# each taken with its declared dependency closure, while the whole sample stays
# under a content budget a laptop parses in about a minute. Neither number
# means anything about conformance -- they only bound how long an obviously
# broken build takes to find.
SMOKE_SAMPLE_PACK_COUNT = 3
SMOKE_SAMPLE_MAX_CONTENT_BYTES = 320 * 1024 * 1024
HIERARCHY_REACHABILITY_BATCH_BITS = 2_048
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
# The compact projection carries rkaf:lifecycleEventKind as a full IRI,
# exactly like rkaf:attestorKind and rkaf:decision on an evidence binding, and
# exactly like those it is closed by the sh:in on atlas:LifecycleEventShape
# rather than by a second copy of the value set here.
COMPACT_SCHEMA_VERSION = "1.0"
COMPACT_ROLES = (
    "Resource",
    "Label",
    "Statement",
    "EvidenceBinding",
    "SourceRecord",
    "Release",
    "Identifier",
    "LifecycleEvent",
)
COMPACT_RECORD_FIELDS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "Resource": (
        frozenset({"id", "release", "scheme", "semanticRing", "resourceProfile", "sourceRecord"}),
        frozenset({"definition", "notes", "notations", "recordStatus"}),
    ),
    "Label": (
        frozenset({"id", "resource", "labelRole", "value", "language", "release", "sourceRecord"}),
        frozenset(),
    ),
    "Statement": (
        frozenset(
            {
                "id",
                "statementType",
                "subject",
                "predicate",
                "object",
                "sourceRelease",
                "targetRelease",
                "policy",
                "assertedAt",
                "assertionIdentityDigest",
            }
        ),
        frozenset({"semanticRing", "sourceRing", "targetRing", "supersedesAssertion"}),
    ),
    "EvidenceBinding": (
        frozenset(
            {
                "id",
                "statement",
                "sourceRecord",
                "evidenceSourceDigest",
                "attestor",
                "attestorKind",
                "assertionOrigin",
                "epistemicBasis",
                "evidenceRole",
                "evidentiaryFunction",
                "decision",
                "attestedAt",
            }
        ),
        frozenset({"basedOnAttestation"}),
    ),
    "SourceRecord": (
        frozenset({"id", "sourceRelease", "sourceDigest", "sourceLocator", "nativePayload"}),
        frozenset({"representsResource"}),
    ),
    "Release": (
        frozenset({"id", "releaseType", "identifier", "issued"}),
        frozenset(
            {
                "sourceDigest",
                "sourceLocator",
                "resourceProfile",
                "semanticRing",
                "scheme",
                "membershipMode",
            }
        ),
    ),
    "Identifier": (
        frozenset({"id", "identifierValue", "identifierScheme", "identifies", "sourceRecord"}),
        frozenset(),
    ),
    "LifecycleEvent": (
        frozenset({"id", "appliesTo", "lifecycleEventKind", "effectiveDate", "sourceRecords"}),
        frozenset({"fromRelease", "toRelease"}),
    ),
}
# Which per-release count field each logical record role is tallied into. The
# construction summary publishes these; `_check_construction_record_ownership`
# recomputes them from the asserted graph.
COMPACT_ROLE_COUNT_FIELDS = {
    "Resource": "resources",
    "Label": "labels",
    "Statement": "statements",
    "EvidenceBinding": "evidenceBindings",
    "SourceRecord": "sourceRecords",
    "Release": "releases",
    "Identifier": "identifiers",
    "LifecycleEvent": "lifecycleEvents",
}
# Fields large enough (native payloads, notes/notations) or internal enough
# (assertion-identity digests) that a lightweight summary row omits them even
# though the full compact record carries them. Every other required-or-optional
# field for a role is projected through.
# The IRI-typed fields for each role -- always a subset of that role's
# *required* fields in this schema, never of its optional fields. Independent
# metadata (field name alone does not say IRI-vs-literal), so it cannot be
# mechanically derived from COMPACT_RECORD_FIELDS; the assertion below instead
# verifies it stays a true projection of it, so a renamed or removed field
# fails loudly here instead of silently going stale.
COMPACT_IRI_FIELDS: dict[str, tuple[str, ...]] = {
    "Resource": ("id", "release", "scheme", "sourceRecord"),
    "Label": ("id", "resource", "release", "sourceRecord"),
    "Statement": (
        "id",
        "subject",
        "predicate",
        "object",
        "sourceRelease",
        "targetRelease",
        "policy",
    ),
    "EvidenceBinding": ("id", "statement", "sourceRecord", "attestor"),
    "SourceRecord": ("id", "sourceRelease", "sourceLocator"),
    "Release": ("id",),
    "Identifier": ("id", "identifierScheme", "identifies", "sourceRecord"),
    "LifecycleEvent": ("id", "appliesTo", "lifecycleEventKind"),
}
assert COMPACT_IRI_FIELDS.keys() == COMPACT_RECORD_FIELDS.keys()
assert all(
    set(COMPACT_IRI_FIELDS[role]) <= COMPACT_RECORD_FIELDS[role][0] for role in COMPACT_IRI_FIELDS
), "COMPACT_IRI_FIELDS must stay a subset of each role's required fields"


class _StatusReporter:
    """Write rate-limited validation progress outside canonical result data."""

    def __init__(
        self,
        *,
        enabled: bool,
        stream: TextIO = sys.stderr,
        interval_seconds: float = 15.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.enabled = enabled
        self.stream = stream
        self.interval_seconds = interval_seconds
        self.clock = clock
        self.started_at = clock()
        self.last_emitted_at: float | None = None

    def _write(
        self,
        phase: str,
        *,
        current: str | None = None,
        progress: tuple[int, int] | None = None,
        force: bool = False,
    ) -> None:
        if not self.enabled:
            return
        now = self.clock()
        if (
            not force
            and self.last_emitted_at is not None
            and now - self.last_emitted_at < self.interval_seconds
        ):
            return
        fields = [
            "atlas-validate",
            f"elapsed={max(0.0, now - self.started_at):.1f}s",
            f"phase={json.dumps(phase, ensure_ascii=True)}",
        ]
        if progress is not None:
            fields.append(f"progress={progress[0]}/{progress[1]}")
        if current is not None:
            fields.append(f"current={json.dumps(current, ensure_ascii=True)}")
        print(" ".join(fields), file=self.stream, flush=True)
        self.last_emitted_at = now

    def phase(self, phase: str, *, current: str | None = None) -> None:
        self._write(phase, current=current, force=True)

    def progress(
        self,
        phase: str,
        completed: int,
        total: int,
        *,
        current: str | None = None,
    ) -> None:
        self._write(
            phase,
            current=current,
            progress=(completed, total),
            force=completed == total,
        )


_STATUS = _StatusReporter(enabled=False)
ASSERTION_TYPES = frozenset(
    {
        ATLAS.CrossRingRelationAssertion,
        ATLAS.MappingAssertion,
        ATLAS.NativeRelationAssertion,
        ATLAS.SourceAssignment,
    }
)
RESOURCE_TYPES = frozenset(
    {
        ATLAS.SubjectConcept,
        ATLAS.EntityResource,
        ATLAS.ValueResource,
        ATLAS.LegalIdentityResource,
    }
)
SKOS_MAPPING_PREDICATES = frozenset(
    {SKOS.exactMatch, SKOS.closeMatch, SKOS.broadMatch, SKOS.narrowMatch, SKOS.relatedMatch}
)
SKOS_NATIVE_RELATION_PREDICATES = frozenset({SKOS.broader, SKOS.narrower, SKOS.related})
# A record's own content digest never covers itself. Atlas spells that digest
# atlas:contentDigest on every carrier it names; on a machine-adjudication proof
# record Rulespec already names it rkaf:proofRecordDigest, so the rkaf term is
# what rides on the wire and both are excluded by the one digest algorithm.
_SELF_DIGEST_PREDICATES = frozenset({ATLAS.contentDigest, RKAF.proofRecordDigest})
# The same three terms as canonical bytes, for the node-digest pass that reads
# quads before any RDF term is built (`_AssertedNodeDigests`). A retained node
# is one whose digest a distribution-scale gate compares: an IRI-bearing
# carrier publishes its own, and an atlas:SourceRecord's is what every evidence
# binding pins. Everything else falls back to the graph.
_SELF_DIGEST_TERMS = frozenset(f"<{term}>".encode() for term in _SELF_DIGEST_PREDICATES)
_RDF_TYPE_TERM = f"<{RDF.type}>".encode()
_NODE_DIGEST_RETAINED_TYPE_TERMS = frozenset({f"<{ATLAS.SourceRecord}>".encode()})
# rkaf's #MachineAdjudicationVerdict, five closed values. v1's seven-value
# atlas:verdictRelation lost "unrelated" and "insufficient_evidence" on the way
# here: a verdict names a RELATION, and those two name a refusal, which is a
# #ResolverProofOutcome (rkaf:gateFail / rkaf:gateUnknown). See the machine-
# adjudication block in ontology/atlas.ttl.
MACHINE_ADJUDICATION_VERDICTS = frozenset(
    {
        RKAF.verdictSame,
        RKAF.verdictNearSame,
        RKAF.verdictTargetBroader,
        RKAF.verdictTargetNarrower,
        RKAF.verdictRelated,
    }
)
# The five independence axes, each named by how it is reached from one proof
# record. Two proofs are independent witnesses of one sealed question only when
# they differ on ALL five: distinct actors, groups, providers, and model IDs
# still describe one witnessed answer if that answer is the identical sealed
# response artifact (rulespec spec/rkaf-refspec.md, corrected 2026-08-09;
# rkaf:MachineAdjudicationIndependentPairShape).
# The three #GateStatus values a machine adjudication may return. Published,
# never pinned: a consumer that cannot tell "never adjudicated" from
# "adjudicated and refused" has lost the distinction rulespec keeps an outcome
# enum to preserve. Only rkaf:gatePass proofs can license a mapping.
MACHINE_ADJUDICATION_OUTCOMES = frozenset(
    {RKAF.gatePass, RKAF.gateFail, RKAF.gateUnknown}
)
# rkaf's #RelationComparisonOutcome, all five. Only rkaf:comparisonSatisfied
# licenses; the other four are the audit record of a comparison that was run
# and did not.
RELATION_COMPARISON_OUTCOMES = frozenset(
    {
        RKAF.comparisonSatisfied,
        RKAF.comparisonAffirmedDeniedDiscrepancy,
        RKAF.comparisonConflict,
        RKAF.comparisonNotComparable,
        RKAF.comparisonUnknown,
    }
)
MACHINE_ADJUDICATION_INDEPENDENCE_AXES = (
    "validator actor",
    "independence group",
    "provider",
    "provider model id",
    "response artifact",
)
# The four independent Rulespec axes that atlas:reviewMethod used to conflate
# into one six-value enum, plus the attestor kind. Rulespec keeps them apart on
# purpose: #EvidenceRole's comment says the split "prevents a consumer from
# treating retrieval evidence as authority evidence merely because both point
# at the same fragment", and #EpistemicBasis is "deliberately independent of
# rkaf:assertionOrigin, which records what CONSTRUCTED the record".
#
# Splitting a closed enum into independent axes would ordinarily lose the
# closure, so the admissible COMBINATIONS are closed by the `sh:xone` on
# atlas:EvidenceBindingShape -- and that shape is the ONLY statement of them.
# `evidence_warrant_axis_values` reads it; nothing below restates it.
EVIDENCE_WARRANT_AXES = (
    RKAF.assertionOrigin,
    RKAF.epistemicBasis,
    RKAF.evidenceRole,
    RKAF.attestorKind,
)
# The warrant NAME each `sh:xone` branch replaced -- the atlas:ReviewMethod
# individual it stands for -- keyed by the `rkaf:evidenceRole` that
# discriminates it. A name is a label for a combination, never a term on the
# wire, and the branches carry no identifier of their own, so this map is the
# one thing tying a name to a branch. `rkaf:evidenceRole` can carry that anchor
# because it alone separates the six branches; `evidence_warrant_axis_values`
# asserts that it still does, so an amended table that made two branches share
# a role fails loudly instead of silently aliasing them.
EVIDENCE_WARRANT_NAMES: dict[URIRef, str] = {
    RKAF.officialSourceMetadata: "publisherAssertion",
    RKAF.structuralEvidence: "deterministicTransformation",
    RKAF.textualEvidence: "humanReview",
    RKAF.formalAdoptionEvent: "operatorAdoption",
    RKAF.reviewedAuthorityChain: "twoMachineAdjudication",
    RKAF.authorityCitation: "trustedPipelineReview",
}
# The `rkaf:attestorKind` this producer mints per warrant.
#
# Not a copy of the shapes: exactly one branch (humanReview) pins the axis, and
# the shape otherwise admits all nine #AttestorKind values, so what kind of
# party attested is a producer choice the binding deliberately leaves open.
# Stating it once here keeps every minting site -- the full builder and the
# fixture builder -- emitting the same kind per warrant instead of each
# choosing, and `evidence_warrant_facts` proves the one value the shapes DO pin
# still agrees with what this table mints.
EVIDENCE_WARRANT_ATTESTOR_KINDS: dict[str, URIRef] = {
    "publisherAssertion": RKAF.automatedParser,
    "deterministicTransformation": RKAF.automatedParser,
    "humanReview": RKAF.humanUser,
    "operatorAdoption": RKAF.organization,
    "twoMachineAdjudication": RKAF.aiModel,
    "trustedPipelineReview": RKAF.automatedParser,
}
# How the bound evidence bears on the assertion. Atlas only ever supports, but
# the axis is constrained to the upstream enum rather than pinned to one value,
# so a producer that means "qualifies" has somewhere to put it.
EVIDENTIARY_FUNCTIONS = frozenset(
    {
        RKAF.supports,
        RKAF.qualifies,
        RKAF.contradicts,
        RKAF.definesScope,
        RKAF.providesContext,
    }
)
EXPECTED_PROFILE_NAMES = frozenset(
    {"codeScheme", "conceptScheme", "identifierScheme", "resourceCollection", "structureScheme"}
)
MEMBER_DISPOSITIONS = frozenset(
    {
        "assignmentEvidenceOnly",
        "childReleaseOnly",
        "definitionOnly",
        "historicalEvidenceOnly",
        "mappingAssertionsOnly",
        "memberRelease",
        "noPublisherRecord",
        "resourceFamily",
        "reviewWithheld",
    }
)
RING_RESOURCE_CLASSES = {
    ATLAS.entity: ATLAS.EntityResource,
    ATLAS.legalIdentity: ATLAS.LegalIdentityResource,
    ATLAS.subject: ATLAS.SubjectConcept,
    ATLAS.value: ATLAS.ValueResource,
}
RELATION_POLICY_TYPE_NAMES = {
    "MappingAssertion": ATLAS.MappingAssertion,
    "NativeRelationAssertion": ATLAS.NativeRelationAssertion,
    "SourceAssignment": ATLAS.SourceAssignment,
}
ALLOWED_ASSERTED_TYPES = frozenset(
    {
        ATLAS.Release,
        ATLAS.AtlasRelease,
        ATLAS.SourceRelease,
        ATLAS.RegistrySource,
        ATLAS.ResourceScheme,
        ATLAS.AtlasResource,
        *RESOURCE_TYPES,
        ATLAS.Identifier,
        ATLAS.SourceRecord,
        RKAF.EvidenceBinding,
        ATLAS.EditorialPolicy,
        RKAF.LifecycleEvent,
        RKAF.ResolverProofRecord,
        RKAF.ResolverProofIssuer,
        RKAF.AILineage,
        RKAF.Artifact,
        RKAF.RelationComparisonContext,
        RKAF.EffectivePeriod,
        RKAF.RegistryConflict,
        ATLAS.RelationAssertion,
        *ASSERTION_TYPES,
        ATLAS.SkosMappingAssertion,
        SKOS.Concept,
        SKOS.ConceptScheme,
        SKOSXL.Label,
    }
)
ASSERTED_CARRIER_TYPES = frozenset(
    {
        ATLAS.AtlasRelease,
        ATLAS.SourceRelease,
        ATLAS.RegistrySource,
        ATLAS.ResourceScheme,
        *RESOURCE_TYPES,
        ATLAS.Identifier,
        ATLAS.SourceRecord,
        RKAF.EvidenceBinding,
        ATLAS.EditorialPolicy,
        RKAF.LifecycleEvent,
        RKAF.ResolverProofRecord,
        RKAF.ResolverProofIssuer,
        RKAF.AILineage,
        RKAF.Artifact,
        RKAF.RelationComparisonContext,
        RKAF.EffectivePeriod,
        RKAF.RegistryConflict,
        *ASSERTION_TYPES,
        SKOSXL.Label,
    }
)
ALLOWED_ASSERTED_PREDICATES = frozenset(
    {
        RDF.type,
        RDF.subject,
        RDF.predicate,
        RDF.object,
        RDFS.label,
        DCTERMS.identifier,
        DCTERMS.title,
        DCTERMS.issued,
        DCTERMS.description,
        PROV.hadMember,
        PROV.wasDerivedFrom,
        SKOS.inScheme,
        SKOSXL.prefLabel,
        SKOSXL.altLabel,
        SKOSXL.hiddenLabel,
        SKOSXL.literalForm,
        ATLAS.inRelease,
        ATLAS.inSourceRelease,
        ATLAS.inScheme,
        ATLAS.semanticRing,
        ATLAS.sourceRing,
        ATLAS.targetRing,
        ATLAS.supportedRing,
        ATLAS.resourceProfile,
        ATLAS.sourceRecord,
        ATLAS.representsResource,
        ATLAS.collectionMember,
        ATLAS.sourceDescriptor,
        ATLAS.sourceLocator,
        ATLAS.identifierScheme,
        ATLAS.identifies,
        RKAF.membershipMode,
        ATLAS.sourceRelease,
        ATLAS.targetRelease,
        ATLAS.governedByPolicy,
        RKAF.supersedesAssertion,
        ATLAS.evidenceSourceRecord,
        ATLAS.evidenceSourceDigest,
        RKAF.attestor,
        RKAF.decision,
        RKAF.basedOnAttestation,
        RKAF.assertionOrigin,
        RKAF.epistemicBasis,
        RKAF.evidenceRole,
        RKAF.evidentiaryFunction,
        RKAF.attestorKind,
        RKAF.bindsAssertion,
        RKAF.appliesTo,
        RKAF.lifecycleEventKind,
        RKAF.proofType,
        RKAF.proofIssuer,
        RKAF.proofComparisonContext,
        RKAF.proofOutcome,
        RKAF.proofInput,
        RKAF.proofInputDigest,
        RKAF.proofEvaluatedAt,
        RKAF.proofRecordDigest,
        RKAF.hasAILineage,
        RKAF.independenceGroup,
        RKAF.adjudicationVerdict,
        RKAF.sealedRequestDigest,
        RKAF.sealedResponseArtifact,
        RKAF.proofRationale,
        RKAF.proofSnapshot,
        RKAF.proofResolver,
        RKAF.proofResolverVersion,
        RKAF.proofPolicy,
        RKAF.proofPolicyVersion,
        RKAF.modelId,
        RKAF.modelVersion,
        RKAF.promptTemplateRef,
        RKAF.temperature,
        RKAF.inputContextHash,
        RKAF.hasArtifactIdentifier,
        RKAF.artifactIdentifierScheme,
        RKAF.hasContentDigest,
        RKAF.comparisonBaselineArtifact,
        RKAF.comparisonObservedArtifact,
        RKAF.comparisonExpectedAssertion,
        RKAF.comparisonConsumer,
        RKAF.comparisonScope,
        RKAF.comparisonEvaluationTime,
        RKAF.comparisonPolicyVersion,
        RKAF.comparisonDetector,
        RKAF.comparisonDetectorVersion,
        RKAF.comparisonSnapshot,
        RKAF.comparisonOutcome,
        RKAF.comparisonProofRecord,
        ATLAS.fromRelease,
        ATLAS.toRelease,
        ATLAS.sourceDigest,
        ATLAS.nativePayload,
        ATLAS.descriptorPayload,
        ATLAS.memberDisposition,
        ATLAS.policyPayload,
        ATLAS.notation,
        ATLAS.definition,
        ATLAS.note,
        ATLAS.recordStatus,
        ATLAS.validationRule,
        ATLAS.componentPosition,
        ATLAS.validFrom,
        ATLAS.validUntil,
        ATLAS.identifierValue,
        RKAF.assertedAt,
        ATLAS.assertionIdentityDigest,
        RKAF.attestedAt,
        RKAF.effectiveDate,
        RKAF.hasEffectivePeriod,
        RKAF.effectivePeriodStart,
        RKAF.effectivePeriodEnd,
        RKAF.conflictingEntries,
        RKAF.severity,
        RKAF.detectedAt,
        ATLAS.contentDigest,
    }
)
XL_TO_SKOS = {
    SKOSXL.prefLabel: SKOS.prefLabel,
    SKOSXL.altLabel: SKOS.altLabel,
    SKOSXL.hiddenLabel: SKOS.hiddenLabel,
}
SKOS_TO_XL = {plain: xl for xl, plain in XL_TO_SKOS.items()}
# Every asserted predicate whose objects a bucket-2 semantic gate reads back
# per carrier node, and nothing else. `_AssertedFacts` keeps exactly these as
# the packs are parsed, so the gates read a prepared index instead of asking
# the 29M-quad store one subject at a time. Adding a predicate here costs one
# retained reference per occurrence in the asserted graph, so the list is the
# read set, not the vocabulary: `atlas:nativePayload`, `atlas:notation` and the
# other bulk literals are deliberately absent because no folded gate reads them
# through this index. A gate asking for a predicate that is NOT here raises
# rather than silently answering from the store, so the list cannot drift out
# from under a check without failing loudly.
#
# Machine-adjudication records are structurally absent from the staging
# distribution. Keeping their complete read set separate makes that zero and
# its memory consequence measurable without weakening the shared allowlist.
_MACHINE_ADJUDICATION_INDEXED_PREDICATES = frozenset(
    {
        RKAF.hasArtifactIdentifier,
        RKAF.hasContentDigest,
        RKAF.proofRecordDigest,
        RKAF.proofIssuer,
        RKAF.hasAILineage,
        RKAF.proofComparisonContext,
        RKAF.proofEvaluatedAt,
        RKAF.adjudicationVerdict,
        RKAF.proofOutcome,
        RKAF.proofSnapshot,
        RKAF.sealedRequestDigest,
        RKAF.inputContextHash,
        RKAF.independenceGroup,
        RKAF.proofResolver,
        RKAF.modelId,
        RKAF.sealedResponseArtifact,
        RKAF.proofInput,
        RKAF.proofInputDigest,
        RKAF.comparisonExpectedAssertion,
        RKAF.comparisonOutcome,
        RKAF.comparisonSnapshot,
        RKAF.comparisonBaselineArtifact,
        RKAF.comparisonObservedArtifact,
        RKAF.comparisonProofRecord,
    }
)
_INDEXED_ASSERTED_PREDICATES = frozenset(
    {
        RDF.subject,
        RDF.predicate,
        RDF.object,
        PROV.hadMember,
        SKOSXL.prefLabel,
        SKOSXL.altLabel,
        SKOSXL.hiddenLabel,
        SKOSXL.literalForm,
        ATLAS.inRelease,
        ATLAS.inSourceRelease,
        ATLAS.inScheme,
        ATLAS.semanticRing,
        ATLAS.sourceRing,
        ATLAS.targetRing,
        ATLAS.supportedRing,
        ATLAS.resourceProfile,
        ATLAS.sourceRecord,
        ATLAS.representsResource,
        ATLAS.identifierScheme,
        ATLAS.identifierValue,
        ATLAS.identifies,
        ATLAS.sourceRelease,
        ATLAS.targetRelease,
        ATLAS.governedByPolicy,
        ATLAS.assertionIdentityDigest,
        ATLAS.evidenceSourceRecord,
        ATLAS.evidenceSourceDigest,
        ATLAS.contentDigest,
        RKAF.assertedAt,
        RKAF.attestedAt,
        RKAF.attestor,
        RKAF.decision,
        RKAF.assertionOrigin,
        RKAF.epistemicBasis,
        RKAF.evidenceRole,
        RKAF.attestorKind,
        RKAF.evidentiaryFunction,
        RKAF.bindsAssertion,
        RKAF.basedOnAttestation,
        RKAF.supersedesAssertion,
        RKAF.appliesTo,
        RKAF.lifecycleEventKind,
        RKAF.conflictingEntries,
    }
) | _MACHINE_ADJUDICATION_INDEXED_PREDICATES
# The assertion-shaped `rdf:type` objects, and the two of them the shared
# carrier inventory cannot answer. `_check_graph_roles` already hands every
# gate a set per concrete carrier type, so `atlas:RelationAssertion` and
# `atlas:SkosMappingAssertion` -- which are abstract and carried BESIDE a
# concrete type -- are the only type facts left to index, and they are indexed
# as two membership sets rather than a per-subject type map.
_ASSERTION_TYPE_TERMS = frozenset(
    {ATLAS.RelationAssertion, ATLAS.SkosMappingAssertion, *ASSERTION_TYPES}
)
_INDEXED_ASSERTED_TYPES = _ASSERTION_TYPE_TERMS - ASSERTED_CARRIER_TYPES
REQUIRED_GATES = frozenset(
    {
        "canonical-json",
        "json-schema",
        "rdf-syntax",
        "ontology-profile",
        "shacl-meta",
        "shacl-data",
        "dataset-closure",
        "record-ownership",
        "machine-adjudication",
        "source-accounting",
        "projection-parity",
        "reasoning-isolation",
        "profile-conformance",
    }
)
ATLAS_LANGUAGE_SCOPE = {
    "includedLanguageFamilies": ["en"],
    "selectionRule": "bcp47-primary-language-subtag",
    "unselectedPublisherContent": "notRepresented",
    "wireLanguageTag": "en",
}
REQUIRED_CORPUS_CASES = frozenset(
    {
        "acceptance-missing-gate",
        "adjudication-artifact-scheme-unknown",
        "adjudication-comparison-incomplete",
        "adjudication-comparison-retargeted",
        "adjudication-discarded-support",
        "adjudication-endpoint-artifact-drift",
        "adjudication-evaluated-at-not-datetime",
        "adjudication-foreign-comparison",
        "adjudication-foreign-snapshot",
        "adjudication-input-context-hash",
        "adjudication-issuer-incomplete",
        "adjudication-licensed-by-conflicted-comparison",
        "adjudication-licensing-proof-refused",
        "adjudication-lineage-incomplete",
        "adjudication-mismatched-sealed-request",
        "adjudication-proof-input-digest",
        "adjudication-proof-rationale-empty",
        "adjudication-proof-record-digest",
        "adjudication-proof-snapshot-drift",
        "adjudication-proof-type-not-machine",
        "adjudication-refused-comparison-record",
        "adjudication-relation-not-licensed",
        "adjudication-request-artifact-unbundled",
        "adjudication-request-digest-mismatch",
        "adjudication-response-artifact-cardinality",
        "adjudication-response-artifact-unbundled",
        "adjudication-same-independence-group",
        "adjudication-same-provider",
        "adjudication-same-provider-model",
        "adjudication-same-response-artifact",
        "adjudication-same-validator-actor",
        "adjudication-single-proof",
        "adjudication-verdicts-disagree",
        "adjudication-warrant-without-comparison",
        "adoption-chain-cycle",
        "adoption-without-referent",
        "all-resource-profiles",
        "asserted-naked-mapping",
        "asserted-auxiliary-type-only",
        "asserted-untyped-statement",
        "assertion-asserted-at-not-datetime",
        "assertion-extra-property",
        "blank-node",
        "cross-ring-disallowed-pair",
        "cross-ring-disallowed-predicate",
        "cross-ring-endpoint-ring-reversal",
        "cross-ring-missing-evidence",
        "cross-role-identity",
        "construction-language-scope-missing",
        "dataset-digest-mismatch",
        "derived-input-digest",
        "derived-asserted-scheme-collision",
        "derived-is-authoritative",
        "derived-extra-type",
        "derived-extra-branch",
        "derived-naked-mapping",
        "derived-nonresource-endpoint",
        "derived-reflexive-output",
        "derived-rescinded-input",
        "duplicate-preferred-language",
        "evidence-attested-at-not-datetime",
        "evidence-attestor-kind-unknown",
        "evidence-decision-not-approved",
        "evidence-function-unknown",
        "evidence-retargeted",
        "evidence-reviewer-retargeted",
        "evidence-warrant-unsanctioned",
        "identifier-conflict-recorded",
        "identifier-missing-value",
        "identifier-pair-conflict",
        "iri-credentials",
        "iri-forbidden-character",
        "label-missing-literal",
        "literal-explicit-string-datatype",
        "literal-uppercase-language-tag",
        "label-extra-skos-type",
        "manifest-count-mismatch",
        "manifest-unknown-field",
        "mapping-missing-evidence",
        "mapping-period-end-before-start",
        "mapping-period-end-not-utc-day-end",
        "mapping-period-start-not-datetime",
        "mapping-period-start-not-utc-midnight",
        "mapping-subject-ring-dated",
        "mapping-undated-legal-identity",
        "mapping-undated-value-crosswalk",
        "mapping-wrong-endpoint-release",
        "native-payload-digest-mismatch",
        "native-payload-noncanonical",
        "naked-projected-mapping",
        "no-derived",
        "non-english-label",
        "non-english-definition",
        "partitioned-packs",
        "profile-ring-mismatch",
        "qualified-lattice-branches",
        "qualified-three-machine-support",
        "release-membership-mode-unknown",
        "policy-payload-changed",
        "rdf-literal-escaping",
        "rdf-pack-over-limit",
        "registry-conflict-detected-at-not-datetime",
        "registry-conflict-entries-mismatch",
        "registry-conflict-publication-blocking",
        "registry-conflict-severity-unknown",
        "registry-conflict-single-entry",
        "scheme-assertion-property",
        "source-native-thesaurus",
        "skos-hierarchy-conflict",
        "skos-mapping-conflict",
        "skos-mapping-hierarchy-conflict",
        "skos-mapping-reverse-conflict",
        "skos-mapping-transitive-conflict",
        "skosxl-hidden-label",
        "skosxl-label-role-overlap",
        "source-accounting-false-inverse",
        "source-accounting-missing-disposition",
        "source-accounting-resource-swap",
        "source-accounting-unaccounted-assertion",
        "subject-scheme-disagreement",
        "superseded-policy-revision",
        "lifecycle-applies-to-nonassertion",
        "lifecycle-effective-date-not-datetime",
        "lifecycle-event-kind-unknown",
        "lifecycle-rescission-names-target-release",
        "supersession-dangling-predecessor",
        "supersession-without-event",
        "unjustified-thesaurus-related",
        "validator-identity-mismatch",
        "rescission-lifecycle",
        "wrong-ring-relation",
        "zstd-packs",
    }
)


@dataclass(slots=True)
class AtlasValidationError(ValueError):
    """One deterministic Atlas validation failure."""

    code: str
    detail: str

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


@dataclass(frozen=True, slots=True)
class ExactMatchIndex:
    """Linear-space index for the pinned symmetric-transitive semantics."""

    component_by_node: Mapping[URIRef, int]
    component_sizes: tuple[int, ...]
    directed_direct_counts: tuple[int, ...]
    direct_triples: frozenset[tuple[URIRef, URIRef, URIRef]]

    def same_component(self, subject: URIRef, obj: URIRef) -> bool:
        component = self.component_by_node.get(subject)
        return component is not None and component == self.component_by_node.get(obj)

    @property
    def inferred_count(self) -> int:
        return sum(size**2 - self.directed_direct_counts[index] for index, size in enumerate(self.component_sizes))


@dataclass(frozen=True, slots=True)
class SemanticInventory:
    """Reusable carrier inventory built during graph-placement validation.

    `facts` is the parse-observed read index for the asserted graph, when the
    inventory was built from one (`_AssertedFacts`). It travels with the
    inventory because every gate that reads asserted objects back per carrier
    already takes the inventory; a gate handed no inventory, or one built
    without an index, reads the store instead and behaves identically.
    """

    asserted_by_carrier: Mapping[URIRef, AbstractSet[URIRef]]
    derived_nodes: AbstractSet[URIRef]
    projection_nodes: AbstractSet[URIRef]
    facts: _AssertedFacts | None = None

    def nodes(self, carrier_type: URIRef) -> AbstractSet[URIRef]:
        return self.asserted_by_carrier.get(carrier_type, frozenset())

    def assertions(self) -> Iterable[URIRef]:
        for assertion_type in ASSERTION_TYPES:
            yield from self.nodes(assertion_type)

    def is_assertion(self, node: Any) -> bool:
        return any(node in self.nodes(assertion_type) for assertion_type in ASSERTION_TYPES)

    def resources(self) -> Iterable[URIRef]:
        for resource_type in RESOURCE_TYPES:
            yield from self.nodes(resource_type)

    def is_resource(self, node: Any) -> bool:
        return any(node in self.nodes(resource_type) for resource_type in RESOURCE_TYPES)

    @property
    def resource_count(self) -> int:
        return sum(len(self.nodes(resource_type)) for resource_type in RESOURCE_TYPES)




AssertionTriple = tuple[URIRef, URIRef, URIRef]
AssertionSupport = Collection[URIRef]
NodePair = tuple[URIRef, URIRef]
HierarchyComponentPair = tuple[int, int]


@dataclass(frozen=True, slots=True)
class _HierarchyReachabilityIndex:
    """Cycle-safe DAG index for the hierarchy nodes relevant to SKOS S27."""

    component_by_node: Mapping[URIRef, int]
    component_is_cyclic: tuple[bool, ...]
    dag: tuple[tuple[int, ...], ...]
    topological_order: tuple[int, ...]
    topological_rank: tuple[int, ...]
    weak_component: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _AssertionState:
    """Compact state retained while assertion lineages are reconciled."""

    triple: AssertionTriple
    assertion_type: URIRef
    source_release: URIRef
    ring_context: URIRef | tuple[URIRef, URIRef]
    asserted_at: datetime
    predecessor: URIRef | None


class _ShaclDataView(ReadOnlyGraphAggregate):
    """Read-only data-plus-ontology view that pySHACL can key in reports."""

    def __hash__(self) -> int:
        return hash(self.identifier)

    def __bool__(self) -> bool:
        """Test non-emptiness without counting every triple in the view."""

        cached = getattr(self, "_atlas_has_triples", None)
        if cached is None:
            cached = any(
                next(graph.triples((None, None, None)), None) is not None
                for graph in self.graphs
            )
            self._atlas_has_triples = cached
        return cached


@dataclass(frozen=True, slots=True)
class _ClosedShapePlan:
    """One closed-shape check lifted out of pySHACL's per-node call path."""

    shape: URIRef
    allowed_paths: frozenset[Any]
    ignored_paths: frozenset[Any]


@dataclass(frozen=True, slots=True)
class _BatchedShaclPlan:
    """Conformance-equivalent shapes optimized for Atlas's valid-data path."""

    shapes: Graph
    closed_shapes: tuple[_ClosedShapePlan, ...]
    checks_relation_ring_context: bool
    # The parsed atlas:EvidenceBindingShape warrant `sh:xone`, one frozenset of
    # `(path, hasValue, minCount, maxCount)` rows per branch, or None when the
    # shape drifted from the pinned signature and the engine keeps the xone.
    warrant_branches: tuple[frozenset[tuple[Any, Any, int | None, int | None]], ...] | None = None


# How `_AssertedPlacementObservation` classifies one asserted predicate, once.
_PLACEMENT_ALLOWED = 0
_PLACEMENT_TYPE = 1
_PLACEMENT_PROJECTED = 2
_PLACEMENT_UNSUPPORTED = 3
# `_AssertedFacts` distinguishes "this subject carries no such object" from a
# stored `None`, which no RDF term ever is; a module-level sentinel keeps the
# hot lookup to one `dict.get`.
_FACT_ABSENT: Any = object()
# Above this many objects for one (subject, predicate), `_AssertedFacts.contains`
# builds a set once instead of scanning the list on every call. One release's
# `prov:hadMember` is ~588K objects and every resource asks whether it is in
# there, so the linear scan is the difference between one pass and a quadratic
# one; below the threshold the list scan is cheaper than the set it would build.
_FACT_MEMBERSHIP_THRESHOLD = 8


class _AssertedFacts:
    """The asserted objects the semantic gates read back, indexed while parsing.

    The gates below are per-carrier loops: for every resource, label,
    assertion, evidence binding and source record, ask the store for the same
    handful of predicates. Measured on the 1M-quad staging distribution: 1.4M
    `Graph.triples` calls across four phases costing 5.8s, and the same loops
    at full scale run over 20-60x the carriers. The parser already holds every
    one of those objects as it builds the store, so they ride along into a
    columnar index (`predicate -> subject -> object`) and the gates read that.
    The original four phases then issued 150 store calls and cost 2.5s. After
    construction ownership and machine adjudication joined them, the 67-row
    allowlist retained the same 826,127 staging occurrences: its median parse
    RSS cost was 41 MiB (~1.16 GiB projected at 29M quads), because the 24 new
    machine predicates have no occurrences in that artifact.

    This is the `_AssertedPlacementObservation` pattern, applied to reads
    rather than to placement: nothing here fails, the gates still raise, in the
    same order, with the same codes and messages. Semantics are preserved by
    construction rather than by argument -- the index answers exactly "the
    objects of `predicate` on `subject` in the asserted graph", which is what
    `Graph.objects` answers, and the gates' control flow is untouched.

    Two modes, one API. The parser fills the index; `from_graph` recreates it
    for `validate_preparsed_distribution`, which has resident graphs but no
    parse observer. Bound directly to a graph (`for_graph`), it answers from
    the store for helper calls that have neither observation. `one` in graph
    mode is literally `_one`, so a caller counting `_one` still counts it.

    Duplicate objects are impossible on the indexed path and so are not
    filtered: canonical packs are strictly increasing (`_NQuadsProfileReader`),
    which forbids a repeated quad inside one pack, and `pack.co-location` --
    proved by `observe_subject`, which runs BEFORE this observer on the same
    line -- forbids one subject's outgoing facts from appearing in two packs.
    That is the same invariant `_AssertedNodeDigests` already stands on.
    """

    __slots__ = ("_graph", "_membership", "_reorder", "_rows", "_types", "graph_id")

    def __init__(
        self,
        graph_id: URIRef,
        *,
        graph: Graph | None = None,
        from_walk: bool = False,
    ) -> None:
        self.graph_id = graph_id
        self._graph = graph
        # Filled only when the index is built by walking a finished store: that
        # walk yields a context's triples in set order, so a subject carrying
        # two objects for one predicate can arrive in an order `Graph.objects`
        # would never produce -- and two folded gates iterate those objects and
        # raise on the first offender. Single-valued rows cannot disagree, so
        # only the transitions are remembered and only they are re-read.
        self._reorder: list[tuple[URIRef, URIRef]] | None = [] if from_walk else None
        self._rows: dict[URIRef, dict[URIRef, Any]] | None = (
            None
            if graph is not None
            else {predicate: {} for predicate in _INDEXED_ASSERTED_PREDICATES}
        )
        self._types: dict[URIRef, set[URIRef]] | None = (
            None
            if graph is not None
            else {asserted_type: set() for asserted_type in _INDEXED_ASSERTED_TYPES}
        )
        self._membership: dict[tuple[URIRef, URIRef], frozenset[Any]] = {}

    @classmethod
    def for_graph(cls, asserted: Graph) -> _AssertedFacts:
        """Answer from an already-parsed graph, for callers that did not parse here."""

        return cls(asserted.identifier, graph=asserted)

    @property
    def indexed(self) -> bool:
        return self._rows is not None

    def observe(self, subject: URIRef, predicate: URIRef, obj: Any) -> None:
        """Record one asserted quad's object, if any gate reads that predicate.

        One `dict.get` for every quad in the asserted graph, and nothing else
        for the ~30% of them no gate reads back. Only reachable on an indexed
        instance: a graph-backed one has nothing to observe.
        """

        rows = self._rows
        if rows is None:
            return
        row = rows.get(predicate)
        if row is None:
            if predicate == RDF.type:
                subjects = self._types.get(obj)  # type: ignore[union-attr]
                if subjects is not None:
                    subjects.add(subject)
            return
        existing = row.get(subject, _FACT_ABSENT)
        if existing is _FACT_ABSENT:
            row[subject] = obj
        elif type(existing) is list:
            existing.append(obj)
        else:
            row[subject] = [existing, obj]
            if self._reorder is not None:
                self._reorder.append((predicate, subject))

    def align_to_graph(self, asserted: Graph) -> None:
        """Put the multi-valued rows a store walk filled back in the store's order."""

        if not self._reorder:
            return
        for predicate, subject in self._reorder:
            self._rows[predicate][subject] = list(  # type: ignore[index]
                asserted.objects(subject, predicate)
            )
        self._reorder.clear()

    def _row(self, predicate: URIRef) -> dict[URIRef, Any]:
        row = self._rows.get(predicate)  # type: ignore[union-attr]
        if row is None:
            raise AssertionError(f"{predicate} is not an indexed asserted predicate")
        return row

    def objects(self, subject: URIRef, predicate: URIRef) -> tuple[Any, ...]:
        """Every object of `predicate` on `subject`, in the graph's own order."""

        if self._rows is None:
            return tuple(self._graph.objects(subject, predicate))  # type: ignore[union-attr]
        value = self._row(predicate).get(subject, _FACT_ABSENT)
        if value is _FACT_ABSENT:
            return ()
        if type(value) is list:
            return tuple(value)
        return (value,)

    def one(self, subject: URIRef, predicate: URIRef, *, code: str) -> Any:
        """`_one`, answered from the index; identical refusal either way."""

        if self._rows is None:
            return _one(self._graph, subject, predicate, code=code)  # type: ignore[arg-type]
        value = self._row(predicate).get(subject, _FACT_ABSENT)
        if value is _FACT_ABSENT:
            _fail(code, f"{subject} must have exactly one {predicate}; found 0")
        if type(value) is list:
            _fail(code, f"{subject} must have exactly one {predicate}; found {len(value)}")
        return value

    def value(self, subject: URIRef, predicate: URIRef) -> Any:
        """`Graph.value`: the first object, or None when there is none."""

        if self._rows is None:
            return self._graph.value(subject, predicate)  # type: ignore[union-attr]
        value = self._row(predicate).get(subject, _FACT_ABSENT)
        if value is _FACT_ABSENT:
            return None
        if type(value) is list:
            return value[0]
        return value

    def contains(self, subject: URIRef, predicate: URIRef, obj: Any) -> bool:
        """Whether the asserted graph carries this exact triple."""

        if self._rows is None:
            return (subject, predicate, obj) in self._graph  # type: ignore[operator]
        value = self._row(predicate).get(subject, _FACT_ABSENT)
        if value is _FACT_ABSENT:
            return False
        if type(value) is not list:
            return bool(value == obj)
        if len(value) < _FACT_MEMBERSHIP_THRESHOLD:
            return obj in value
        key = (subject, predicate)
        members = self._membership.get(key)
        if members is None:
            members = self._membership[key] = frozenset(value)
        return obj in members

    def subject_objects(self, predicate: URIRef) -> Iterable[tuple[URIRef, Any]]:
        """Every (subject, object) pair for one predicate across the asserted graph."""

        if self._rows is None:
            yield from self._graph.subject_objects(predicate)  # type: ignore[union-attr]
            return
        for subject, value in self._row(predicate).items():
            if type(value) is list:
                for obj in value:
                    yield subject, obj
            else:
                yield subject, value

    def has_type(self, subject: URIRef, asserted_type: URIRef) -> bool:
        """Whether `subject` declares one of the indexed abstract carrier types."""

        if self._types is None:
            return (subject, RDF.type, asserted_type) in self._graph  # type: ignore[operator]
        subjects = self._types.get(asserted_type)
        if subjects is None:
            raise AssertionError(f"{asserted_type} is not an indexed asserted type")
        return subject in subjects


@dataclass(slots=True)
class _AssertedPlacementObservation:
    """Asserted-graph placement facts accumulated while the packs are parsed.

    `_check_graph_roles` used to learn these by iterating the whole asserted
    store a second time: one pass over every quad for the predicate allowlist
    and to collect the subjects, then one `rdf:type` lookup per subject. At
    32M quads that is the CPU-bound half of the check's measured 570s
    (`plans/validation-cost-reset-plan.md`, "Inside-the-phases trace"). The
    parser already touches every quad, so the same facts ride along for one
    memoized dict lookup per quad and the check keeps only the per-subject
    type-set equality pass it exists for.

    Semantics are unchanged, deliberately. Nothing here fails: a bad predicate
    is *recorded*, and `_check_graph_roles` still raises it, in the same order,
    with the same code and the same message -- so no failure moves phase and
    no corpus first issue can move with it. `types` holds every asserted
    subject, including subjects that carry no `rdf:type` at all, because "has
    exactly one concrete carrier type" is one of the things being checked.

    It carries `_AssertedFacts` for the same reason and on the same terms: one
    walk of the asserted quads, whoever does the walking, serves both the
    placement pass and the per-carrier reads the later gates would otherwise
    take one store query at a time. `types` is drained by `_check_graph_roles`;
    `facts` outlives it and is handed on through `SemanticInventory`.
    """

    graph_id: URIRef
    projection_only_predicates: frozenset[URIRef]
    types: dict[URIRef, tuple[Any, ...]] = dataclass_field(default_factory=dict)
    verdicts: dict[URIRef, int] = dataclass_field(default_factory=dict)
    first_violation: tuple[int, URIRef, URIRef] | None = None
    consumed: bool = False
    facts: _AssertedFacts | None = None

    def __post_init__(self) -> None:
        if self.facts is None:
            self.facts = _AssertedFacts(self.graph_id)

    def consume_types(self) -> dict[URIRef, tuple[Any, ...]]:
        """Hand the subject/type map over, once, so the reader can drain it.

        The map is the largest thing the check holds at full scale, so the
        placement pass frees it entry by entry rather than at the end. Handing
        it over marks the observation spent: a second `_check_graph_roles` over
        the same object re-derives from the store instead of reading an
        emptied map.
        """

        types, self.types, self.consumed = self.types, {}, True
        return types

    def _classify(self, predicate: URIRef) -> int:
        """Rank one predicate the way the placement loop used to, per quad."""

        if predicate == RDF.type:
            verdict = _PLACEMENT_TYPE
        elif predicate in self.projection_only_predicates:
            verdict = _PLACEMENT_PROJECTED
        elif predicate not in ALLOWED_ASSERTED_PREDICATES:
            verdict = _PLACEMENT_UNSUPPORTED
        else:
            verdict = _PLACEMENT_ALLOWED
        self.verdicts[predicate] = verdict
        return verdict

    def observe(self, subject: URIRef, predicate: URIRef, obj: Any) -> None:
        self.facts.observe(subject, predicate, obj)  # type: ignore[union-attr]
        types = self.types
        verdict = self.verdicts.get(predicate)
        if verdict is None:
            verdict = self._classify(predicate)
        if verdict == _PLACEMENT_TYPE:
            types[subject] = (*types.get(subject, ()), obj)
            return
        if subject not in types:
            types[subject] = ()
        if verdict and self.first_violation is None:
            self.first_violation = (verdict, subject, predicate)

    @classmethod
    def from_graph(cls, asserted: Graph) -> _AssertedPlacementObservation:
        """Observe an already-parsed graph, for callers that did not parse here.

        `validate_preparsed_distribution` hands over a resident graph and the
        tests call `_check_graph_roles` directly, so the check keeps a way to
        compute what the parser would have handed it. One code path decides
        placement either way; only who walked the quads differs.
        """

        observation = cls(
            graph_id=asserted.identifier,
            projection_only_predicates=_projection_only_predicates(),
            facts=_AssertedFacts(asserted.identifier, from_walk=True),
        )
        for subject, predicate, obj in asserted:
            observation.observe(subject, predicate, obj)
        observation.facts.align_to_graph(asserted)  # type: ignore[union-attr]
        return observation


class _AssertedNodeDigests:
    """Node digests taken off the canonical pack bytes, in the pass that reads them.

    `rdf_node_digest` renders a node's outgoing facts back into N-Triples and
    hashes the sorted lines. On a full distribution that is ~1.15M nodes
    re-rendered from an rdflib store that was itself built by parsing the
    exact lines the render reproduces -- measured at ~150s of a 75-minute
    acceptance run, spent turning bytes into terms and back into the same
    bytes.

    The canonical packs are already the index that makes the render
    unnecessary: lines are sorted, so one subject's quads are contiguous, and
    `pack.co-location` proves a subject's outgoing facts in one graph role live
    in exactly one pack. So the digest can be accumulated line by line as the
    profile reader validates them, with no store and no term model. Proven at
    parity against `rdf_node_digest` node for node
    (`tests/test_atlas_v3_node_digest_byte_pass.py`, and 104,898/104,898 in the
    substrate spike this ports).

    This is an ACCELERATOR, never an authority: every consumer reads it through
    `_node_digest`, which recomputes from the graph for any node the pass did
    not retain. Retention is deliberately narrow -- a node carrying a
    self-digest predicate (which is what an IRI-bearing carrier publishes) or
    an atlas:SourceRecord (whose digest is what an evidence binding pins) --
    because those are the two checks that run at distribution scale, and
    keeping every node's digest would hold ~1 GB to serve a handful more.

    The terms are the ones `canonical_line_issue_and_terms` matched, so this
    never re-splits a line, and it only ever sees lines already proved
    canonical.
    """

    __slots__ = ("_digests", "_graph_term", "_retain", "_rows", "_subject")

    def __init__(self, asserted_graph_id: URIRef) -> None:
        self._graph_term = f"<{asserted_graph_id}>".encode()
        self._digests: dict[str, str] = {}
        self._subject: bytes | None = None
        self._rows: list[bytes] = []
        self._retain = False

    def observe(self, terms: tuple[bytes, bytes, bytes, bytes]) -> None:
        subject, predicate, obj, graph = terms
        if graph != self._graph_term:
            return
        if subject != self._subject:
            self.finish()
            self._subject = subject
        if predicate in _SELF_DIGEST_TERMS:
            self._retain = True
            return
        if predicate == _RDF_TYPE_TERM and obj in _NODE_DIGEST_RETAINED_TYPE_TERMS:
            self._retain = True
        self._rows.append(predicate + b" " + obj + b" .")

    def finish(self) -> None:
        """Close the open subject. Called between packs and at end of stream."""

        if self._subject is not None and self._rows and self._retain:
            self._rows.sort()
            digest = hashlib.sha256(b"\n".join(self._rows) + b"\n").hexdigest()
            self._digests[self._subject[1:-1].decode("utf-8")] = "sha256:" + digest
        self._subject = None
        self._rows = []
        self._retain = False

    def get(self, node: URIRef) -> str | None:
        return self._digests.get(str(node))

    def __len__(self) -> int:
        return len(self._digests)


def _node_digest(
    graph: Graph,
    node: URIRef,
    digests: _AssertedNodeDigests | None = None,
) -> str:
    """One node's digest, from the byte pass when it has it, else the graph."""

    if digests is not None:
        precomputed = digests.get(node)
        if precomputed is not None:
            return precomputed
    return rdf_node_digest(graph, node)


class _DigestingReader:
    """Hash and count transport bytes as a downstream reader consumes them."""

    def __init__(self, stream: Any, *, label: str) -> None:
        self.stream = stream
        self.label = label
        self.digest = hashlib.sha256()
        self.byte_length = 0
        self.saw_eof = False

    def read(self, size: int = -1) -> bytes:
        try:
            chunk = self.stream.read(size)
        except Exception as exc:  # noqa: BLE001 - normalize transport failures
            _fail("pack.transport", f"cannot read {self.label}: {exc}")
        if not isinstance(chunk, bytes):
            _fail("pack.transport", f"{self.label} did not produce binary bytes")
        if chunk:
            self.digest.update(chunk)
            self.byte_length += len(chunk)
        else:
            self.saw_eof = True
        return chunk

    def readable(self) -> bool:
        return True

    def finish(self, expected: Mapping[str, Any], *, require_consumed: bool) -> None:
        trailing = self.read(1024 * 1024)
        if trailing and require_consumed:
            _fail("pack.transport", f"{self.label} contains bytes not consumed by its decoder")
        while trailing:
            trailing = self.read(1024 * 1024)
        if self.byte_length != expected["byteLength"]:
            _fail("pack.transport", f"{self.label} transport byteLength differs")
        actual = "sha256:" + self.digest.hexdigest()
        if actual != expected["digest"]:
            _fail("pack.transport", f"{self.label} transport digest differs")


class _NQuadsProfileReader:
    """Validate and receipt canonical uncompressed N-Quads during parsing."""

    def __init__(
        self,
        stream: Any,
        *,
        label: str,
        expected: Mapping[str, Any],
        node_digests: _AssertedNodeDigests | None = None,
    ) -> None:
        self.stream = stream
        self.label = label
        self.expected = expected
        self.digest = hashlib.sha256()
        self.byte_length = 0
        self.line_count = 0
        self.previous: bytes | None = None
        self.pending = bytearray()
        self.finished = False
        self.node_digests = node_digests

    def _accept_line(self, line: bytes) -> None:
        self.line_count += 1
        if self.line_count > self.expected["quadCount"]:
            _fail("pack.content", f"{self.label} exceeds its declared content quadCount")
        if len(line) > NQUADS_MAX_LINE_BYTES:
            _fail(
                "rdf.resource-limit",
                f"{self.label} line {self.line_count} exceeds {NQUADS_MAX_LINE_BYTES} bytes",
            )
        if b"\r" in line:
            _fail("rdf.canonical", f"{self.label} contains a CR line ending")
        try:
            line.decode("utf-8")
        except UnicodeDecodeError as exc:
            _fail("rdf.syntax", f"{self.label} is not UTF-8: {exc}")
        content = line[:-1]
        if not content or content != content.strip():
            _fail("rdf.canonical", f"{self.label} contains a blank or padded line")
        if self.previous is not None and line <= self.previous:
            _fail("rdf.canonical", f"{self.label} lines must be sorted and unique")
        self.previous = line
        # The canonical term form, proved on the bytes before any RDF term is
        # built. This is the whole of the old per-term render-and-compare
        # (`_LexicalNQuadsParser`) restated as a grammar, and it runs here
        # because this layer already holds the line.
        issue, terms = canonical_line_issue_and_terms(content)
        if issue is not None:
            code, reason = issue
            _fail(code, f"{self.label} line {self.line_count} {reason}")
        # Node digests ride the same line, off the terms the grammar just
        # matched. See `_AssertedNodeDigests`.
        if self.node_digests is not None and terms is not None:
            self.node_digests.observe(terms)

    def _consume(self, chunk: bytes) -> None:
        self.digest.update(chunk)
        self.byte_length += len(chunk)
        if self.byte_length > self.expected["byteLength"]:
            _fail("pack.content", f"{self.label} exceeds its declared content byteLength")
        self.pending.extend(chunk)
        while True:
            newline = self.pending.find(b"\n")
            if newline < 0:
                if len(self.pending) > NQUADS_MAX_LINE_BYTES:
                    _fail(
                        "rdf.resource-limit",
                        f"{self.label} line {self.line_count + 1} exceeds {NQUADS_MAX_LINE_BYTES} bytes",
                    )
                return
            line = bytes(self.pending[: newline + 1])
            del self.pending[: newline + 1]
            self._accept_line(line)

    def read(self, size: int = -1) -> bytes:
        try:
            chunk = self.stream.read(size)
        except AtlasValidationError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalize decompression failures
            _fail("pack.compression", f"cannot decode {self.label}: {exc}")
        if not isinstance(chunk, bytes):
            _fail("pack.content", f"{self.label} did not produce binary bytes")
        if chunk:
            self._consume(chunk)
        else:
            self.finished = True
        return chunk

    def readable(self) -> bool:
        return True

    def finish(self, expected: Mapping[str, Any]) -> None:
        while self.read():
            pass
        if self.pending or self.line_count == 0:
            _fail("rdf.canonical", f"{self.label} must be nonempty LF text with one terminal LF")
        if self.byte_length != expected["byteLength"]:
            _fail("pack.content", f"{self.label} content byteLength differs")
        if self.line_count != expected["quadCount"]:
            _fail("pack.content", f"{self.label} content quadCount differs")
        actual = "sha256:" + self.digest.hexdigest()
        if actual != expected["digest"]:
            _fail("pack.content", f"{self.label} content digest differs")


def _fail(code: str, detail: str) -> NoReturn:
    raise AtlasValidationError(code, detail)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("json.duplicate-key", f"duplicate object key {key!r}")
        result[key] = value
    return result


def _reject_float(value: str) -> NoReturn:
    _fail("json.number", f"floating-point value {value!r} is forbidden")


def _reject_constant(value: str) -> NoReturn:
    _fail("json.number", f"non-finite value {value!r} is forbidden")


def _parse_int(value: str) -> int:
    parsed = int(value)
    if abs(parsed) > SAFE_INTEGER:
        _fail("json.number", f"integer {value!r} exceeds the safe range")
    return parsed


def _reject_nulls_and_numbers(value: Any, location: str = "$") -> None:
    if value is None:
        _fail("json.null", f"{location} contains null")
    if isinstance(value, bool):
        return
    if isinstance(value, int):
        if abs(value) > SAFE_INTEGER:
            _fail("json.number", f"{location} exceeds the safe integer range")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail("json.number", f"{location} contains a non-finite number")
        _fail("json.number", f"{location} contains a floating-point number")
    if isinstance(value, Mapping):
        for key, child in value.items():
            _reject_nulls_and_numbers(child, f"{location}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            _reject_nulls_and_numbers(child, f"{location}[{index}]")


def canonical_json_bytes(value: Any, *, terminal_lf: bool = True) -> bytes:
    """Return REF canonical JSON bytes for an already parsed value."""

    _reject_nulls_and_numbers(value)
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return payload + (b"\n" if terminal_lf else b"")


def canonical_native_json_bytes(value: Any) -> bytes:
    """Return canonical source JSON while preserving publisher null values."""

    def reject_numbers(child: Any, location: str = "$") -> None:
        if child is None or isinstance(child, bool):
            return
        if isinstance(child, int):
            if abs(child) > SAFE_INTEGER:
                _fail("json.number", f"{location} exceeds the safe integer range")
            return
        if isinstance(child, float):
            if not math.isfinite(child):
                _fail("json.number", f"{location} contains a non-finite number")
            _fail("json.number", f"{location} contains a floating-point number")
        if isinstance(child, Mapping):
            for key, grandchild in child.items():
                reject_numbers(grandchild, f"{location}.{key}")
        elif isinstance(child, Sequence) and not isinstance(child, (str, bytes, bytearray)):
            for index, grandchild in enumerate(child):
                reject_numbers(grandchild, f"{location}[{index}]")

    reject_numbers(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha256(value: Any, *, terminal_lf: bool = True) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value, terminal_lf=terminal_lf)).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


@lru_cache(maxsize=4_096)
def _cached_iri_term(term: URIRef) -> str:
    """Render frequently repeated IRIs without retaining unbounded source data."""

    return _canonical_ntriples_term(term)


def ntriples_term(term: Any) -> str:
    """Render one RDF term in one deterministic RDF 1.1 N-Triples form."""

    try:
        return _cached_iri_term(term) if isinstance(term, URIRef) else _canonical_ntriples_term(term)
    except RdfCanonicalError as exc:
        code = "rdf.blank-node" if isinstance(term, BNode) else "rdf.term"
        _fail(code, str(exc))


def nquads_line(
    subject: URIRef,
    predicate: URIRef,
    obj: URIRef | Literal,
    graph_id: URIRef,
) -> str:
    """Render one canonical named-graph RDF 1.1 N-Quads statement."""

    return " ".join(
        (
            ntriples_term(subject),
            ntriples_term(predicate),
            ntriples_term(obj),
            ntriples_term(graph_id),
            ".",
        )
    )


def _canonical_dataset_lines(
    dataset: Dataset,
    *,
    blank_node_code: str,
    blank_node_detail: str,
) -> list[str]:
    """Render parsed quads canonically while rejecting actual blank-node terms."""

    lines: list[str] = []
    for subject, predicate, obj, graph_id in dataset.quads((None, None, None, None)):
        if any(isinstance(term, BNode) for term in (subject, predicate, obj, graph_id)):
            _fail(blank_node_code, blank_node_detail)
        lines.append(nquads_line(subject, predicate, obj, graph_id))
    return sorted(lines)


class _LexicalNQuadsParser(NQuadsParser):
    """Pinned parser that preserves every literal's exact lexical form.

    `normalize=False` is load-bearing, not a preference: rdflib's default
    normalization rewrites `rdf:JSON` and `xsd:dateTime` lexemes, and every
    node digest is taken over the rendered term, so a normalizing parse would
    move digests the distribution publishes.

    The canonical TERM form is no longer proved here. It is a property of the
    bytes, and `_NQuadsProfileReader` -- which sees them first -- now proves it
    with `canonical_line_issue`. The blank-node and term-kind guards below are
    kept as cheap depth for any future caller that reaches this parser without
    going through that reader.
    """

    def __init__(
        self,
        *args: Any,
        subject_observer: Callable[[URIRef, URIRef], None] | None = None,
        asserted_placement: _AssertedPlacementObservation | None = None,
        term_pool: TermPool | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.graph_counts: Counter[URIRef] = Counter()
        self.subject_observer = subject_observer
        self.asserted_placement = asserted_placement
        self.term_pool = term_pool
        self.observed_subject: URIRef | None = None
        self.observed_subject_graphs: set[URIRef] = set()

    def uriref(self) -> URIRef | bool:
        if not self.peek("<"):
            return False
        lexical = uriquote(unquote(self.eat(r_uriref).group(1)))
        if self.term_pool is None:
            return URI(lexical)
        return self.term_pool.iri(lexical)

    def literal(self) -> Literal | bool:
        if not self.peek('"'):
            return False
        lexical, language, datatype = self.eat(r_literal).groups()
        if language and datatype:
            raise ParseError("Can't have both a language and a datatype")
        datatype_node = self.uriref_from_lexical(datatype) if datatype else None
        lexical = unquote(lexical)
        language = language or None
        if self.term_pool is None:
            return Literal(
                lexical,
                lang=language,
                datatype=datatype_node,
                normalize=False,
            )
        return self.term_pool.literal(
            lexical,
            lang=language,
            datatype=datatype_node,
        )

    def uriref_from_lexical(self, lexical: str) -> URIRef:
        value = uriquote(unquote(lexical))
        if self.term_pool is None:
            return URI(value)
        return self.term_pool.iri(value)

    def parseline(self, bnode_context: Any = None) -> None:
        """Parse one statement into the sink, observing subjects and placement."""

        if not isinstance(self.line, str):
            raise ParseError("N-Quads parser has no current line")
        self.eat(r_wspace)
        if not self.line or self.line.startswith("#"):
            return

        subject = self.subject(bnode_context)
        self.eat(r_wspace)
        predicate = self.predicate()
        self.eat(r_wspace)
        obj = self.object(bnode_context)
        self.eat(r_wspace)
        context = self.uriref() or self.nodeid(bnode_context)
        self.eat(r_tail)
        if self.line:
            raise ParseError("Trailing garbage")
        if any(isinstance(term, BNode) for term in (subject, predicate, obj, context)):
            _fail("rdf.blank-node", "atlas.nq contains a blank node term")
        if not all(isinstance(term, URIRef) for term in (subject, predicate, context)) or not isinstance(
            obj, (URIRef, Literal)
        ):
            _fail("rdf.term", "atlas.nq contains an unsupported RDF term")

        if subject != self.observed_subject:
            self.observed_subject = subject
            self.observed_subject_graphs.clear()
        if context not in self.observed_subject_graphs:
            self.observed_subject_graphs.add(context)
            if self.subject_observer is not None:
                self.subject_observer(context, subject)
        # Graph-role placement rides the quad the parser is already holding.
        placement = self.asserted_placement
        if placement is not None and context == placement.graph_id:
            placement.observe(subject, predicate, obj)
        self.sink.get_context(context).add((subject, predicate, obj))
        self.graph_counts[context] += 1


def _parse_nquads_preserving_lexical_forms(
    dataset: Dataset,
    source: Any,
    *,
    subject_observer: Callable[[URIRef, URIRef], None] | None = None,
    asserted_placement: _AssertedPlacementObservation | None = None,
) -> Counter[URIRef]:
    """Parse and count canonical N-Quads without global literal normalization."""

    input_source = create_input_source(source=source, format="nquads")
    parser = _LexicalNQuadsParser(
        subject_observer=subject_observer,
        asserted_placement=asserted_placement,
        term_pool=getattr(dataset, "_refspec_term_pool", None),
    )
    try:
        parser.parse(input_source, dataset)
    finally:
        if input_source.auto_close:
            input_source.close()
        if parser.term_pool is not None:
            parser.term_pool.clear()
    return parser.graph_counts


def _check_serialized_nquads_profile(path: Path, *, expected_digest: str | None = None) -> int:
    """Check line-level canonical rules and, when supplied, the member digest."""

    previous: bytes | None = None
    line_count = 0
    digest = hashlib.sha256()
    has_line_ending_error = False
    has_blank_or_padded_line = False
    has_ordering_error = False
    noncanonical: tuple[str, str] | None = None
    try:
        with path.open("rb") as stream:
            while line := stream.readline(NQUADS_MAX_LINE_BYTES + 1):
                line_count += 1
                digest.update(line)
                if len(line) > NQUADS_MAX_LINE_BYTES:
                    _fail(
                        "rdf.resource-limit",
                        f"atlas.nq line {line_count} exceeds {NQUADS_MAX_LINE_BYTES} bytes",
                    )
                try:
                    line.decode("utf-8")
                except UnicodeDecodeError as exc:
                    _fail("rdf.syntax", f"atlas.nq is not UTF-8: {exc}")
                has_terminal_lf = line.endswith(b"\n")
                has_line_ending_error |= not has_terminal_lf or b"\r" in line
                content = line[:-1] if has_terminal_lf else line
                has_blank_or_padded_line |= not content or content != content.strip()
                if previous is not None and line <= previous:
                    has_ordering_error = True
                previous = line
                if noncanonical is None:
                    issue = canonical_line_issue(content)
                    if issue is not None:
                        code, reason = issue
                        noncanonical = (code, f"atlas.nq line {line_count} {reason}")
    except OSError as exc:
        _fail("distribution.file", f"cannot read {path}: {exc}")
    if line_count == 0 or has_line_ending_error:
        _fail("rdf.canonical", "atlas.nq must be nonempty LF text with one terminal LF")
    if has_blank_or_padded_line:
        _fail("rdf.canonical", "atlas.nq contains a blank or padded line")
    if has_ordering_error:
        _fail("rdf.canonical", "atlas.nq lines must be sorted and unique")
    if noncanonical is not None:
        _fail(*noncanonical)
    if expected_digest is not None and "sha256:" + digest.hexdigest() != expected_digest:
        _fail("distribution.digest", "atlas.nq digest differs")
    return line_count


def rdf_node_digest(graph: Graph, node: URIRef) -> str:
    """Digest one node's sorted outgoing RDF facts, excluding the digest itself."""

    return _outgoing_facts_digest(graph.predicate_objects(node), node=node)


def _load_json(path: Path, *, require_canonical: bool, expected_digest: str | None = None) -> Any:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        _fail("distribution.file", f"cannot read {path}: {exc}")
    if expected_digest is not None and "sha256:" + hashlib.sha256(raw).hexdigest() != expected_digest:
        _fail("distribution.digest", f"{path.name} digest differs")
    try:
        text = raw.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=_reject_float,
            parse_int=_parse_int,
            parse_constant=_reject_constant,
        )
    except UnicodeDecodeError as exc:
        _fail("json.encoding", f"{path.name} is not UTF-8: {exc}")
    except json.JSONDecodeError as exc:
        _fail("json.syntax", f"{path.name} is not valid JSON: {exc}")
    _reject_nulls_and_numbers(value)
    if require_canonical and raw != canonical_json_bytes(value):
        _fail("json.canonical", f"{path.name} is not canonical REF JSON")
    return value


def _schema_registry() -> tuple[dict[str, Mapping[str, Any]], Registry]:
    schemas: dict[str, Mapping[str, Any]] = {}
    registry = Registry()
    for path in sorted(SCHEMA_ROOT.glob("*.schema.json")):
        value = _load_json(path, require_canonical=False)
        if not isinstance(value, Mapping):
            _fail("schema.meta", f"{path.name} root is not an object")
        try:
            Draft202012Validator.check_schema(value)
            resource = Resource.from_contents(value)
        except Exception as exc:  # noqa: BLE001 - normalize validator-library failures
            _fail("schema.meta", f"{path.name} is not a valid Draft 2020-12 schema: {exc}")
        schema_id = value.get("$id")
        if not isinstance(schema_id, str):
            _fail("schema.meta", f"{path.name} has no string $id")
        if schema_id in schemas:
            _fail("schema.meta", f"duplicate schema $id {schema_id!r}")
        schemas[schema_id] = value
        registry = registry.with_resource(schema_id, resource)
    return schemas, registry


def _schema_by_name(name: str, schemas: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Any]:
    filename = SCHEMAS[name]
    matches = [schema for schema in schemas.values() if str(schema.get("$id", "")).endswith("/" + filename)]
    if len(matches) != 1:
        _fail("schema.meta", f"cannot resolve exactly one {filename}")
    return matches[0]


def _json_equality_fingerprint(value: Any) -> bytes:
    """Hash one JSON value under jsonschema's equality rules.

    In particular, JSON objects are independent of member order, arrays retain
    their order, booleans differ from the integers 0 and 1, and numerically
    equal integer/decimal/float values share one fingerprint.
    """

    digest = hashlib.sha256()

    def add_sized(marker: bytes, payload: bytes) -> None:
        digest.update(marker)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)

    def add(child: Any) -> None:
        if child is None:
            digest.update(b"N")
        elif child is True:
            digest.update(b"B1")
        elif child is False:
            digest.update(b"B0")
        elif isinstance(child, str):
            add_sized(b"S", child.encode("utf-8"))
        elif isinstance(child, Mapping):
            digest.update(b"O")
            digest.update(len(child).to_bytes(8, "big"))
            for key in sorted(child):
                add(key)
                add(child[key])
        elif isinstance(child, Sequence) and not isinstance(
            child,
            (str, bytes, bytearray),
        ):
            digest.update(b"A")
            digest.update(len(child).to_bytes(8, "big"))
            for item in child:
                add(item)
        elif isinstance(child, (int, float, Decimal)):
            try:
                numerator, denominator = child.as_integer_ratio()
            except (AttributeError, OverflowError, ValueError):
                add_sized(b"X", repr(child).encode("ascii", errors="backslashreplace"))
            else:
                add_sized(b"Q", f"{numerator}/{denominator}".encode("ascii"))
        else:
            add_sized(
                b"X",
                (
                    f"{type(child).__module__}.{type(child).__qualname__}:"
                    f"{child!r}"
                ).encode("utf-8", errors="backslashreplace"),
            )

    add(value)
    return digest.digest()


def _json_items_are_unique(instance: Sequence[Any]) -> bool:
    """Check JSON-array uniqueness in expected linear time and bounded keys.

    SHA-256 fingerprints keep the index compact.  Equality is still checked
    within a matching bucket, so even a fingerprint collision cannot change a
    validation verdict.
    """

    seen: dict[bytes, int | list[int]] = {}
    for index, item in enumerate(instance):
        fingerprint = _json_equality_fingerprint(item)
        previous = seen.get(fingerprint)
        if previous is None:
            seen[fingerprint] = index
            continue
        candidates = previous if isinstance(previous, list) else [previous]
        if any(jsonschema_utils.equal(instance[candidate], item) for candidate in candidates):
            return False
        if isinstance(previous, list):
            previous.append(index)
        else:
            seen[fingerprint] = [previous, index]
    return True


def _validate_unique_items_linear(
    validator: Any,
    unique_items: Any,
    instance: Any,
    _schema: Mapping[str, Any],
) -> Iterable[ValidationError]:
    """Draft 2020-12 uniqueItems without quadratic object comparisons."""

    if (
        unique_items
        and validator.is_type(instance, "array")
        and not _json_items_are_unique(instance)
    ):
        yield ValidationError(f"{instance!r} has non-unique elements")


_AtlasDraft202012Validator = jsonschema_validators.extend(
    Draft202012Validator,
    {"uniqueItems": _validate_unique_items_linear},
)


def _validate_json_schema(
    value: Any,
    schema_name: str,
    *,
    schemas: Mapping[str, Mapping[str, Any]],
    registry: Registry,
    label: str,
) -> None:
    schema = _schema_by_name(schema_name, schemas)
    validator = _AtlasDraft202012Validator(
        schema,
        registry=registry,
        format_checker=FormatChecker(),
    )
    errors = sorted(validator.iter_errors(value), key=lambda error: (list(error.absolute_path), error.message))
    if errors:
        error = errors[0]
        location = "$" + "".join(f"[{part}]" if isinstance(part, int) else f".{part}" for part in error.absolute_path)
        _fail("json.schema", f"{label}{location}: {error.message}")


def _one(graph: Graph, subject: URIRef, predicate: URIRef, *, code: str) -> Any:
    values = list(graph.objects(subject, predicate))
    if len(values) != 1:
        _fail(code, f"{subject} must have exactly one {predicate}; found {len(values)}")
    return values[0]


def _iri(value: Any, *, code: str, label: str) -> URIRef:
    if not isinstance(value, URIRef):
        _fail(code, f"{label} must be an IRI")
    return value


def _literal_text(value: Any, *, code: str, label: str) -> str:
    if not isinstance(value, Literal):
        _fail(code, f"{label} must be a literal")
    return str(value)


def _date_time(value: Any, *, code: str, label: str) -> datetime:
    if not isinstance(value, Literal) or value.datatype != XSD.dateTime:
        _fail(code, f"{label} must be an xsd:dateTime literal")
    lexical = str(value)
    try:
        parsed = datetime.fromisoformat(lexical)
    except ValueError:
        _fail(code, f"{label} is not a valid dateTime")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(code, f"{label} must include an explicit timezone")
    return parsed.astimezone(UTC)


def _binding_digests(
    *,
    content_overrides: Mapping[Path, bytes] | None = None,
) -> dict[str, str]:
    contract_paths = [
        *CONTRACT_PATHS,
        *(path.relative_to(BINDING_ROOT) for path in sorted(SCHEMA_ROOT.glob("*.schema.json"))),
    ]
    overrides = dict(content_overrides or {})
    unknown_overrides = set(overrides) - set(contract_paths)
    if unknown_overrides:
        _fail("binding.digest", f"binding content override is not in the contract: {min(unknown_overrides)}")
    contract_payloads = {
        relative: overrides.get(relative, (BINDING_ROOT / relative).read_bytes())
        for relative in sorted(set(contract_paths), key=lambda path: path.as_posix())
    }
    contract_rows = [
        {
            "byteLength": len(payload),
            "digest": "sha256:" + hashlib.sha256(payload).hexdigest(),
            "path": relative.as_posix(),
        }
        for relative, payload in contract_payloads.items()
    ]
    return {
        "contractDigest": canonical_sha256(contract_rows, terminal_lf=False),
        "ontologyDigest": file_sha256(ONTOLOGY_PATH),
        "shapesDigest": file_sha256(SHAPES_PATH),
        "manifestSchemaDigest": file_sha256(SCHEMA_ROOT / SCHEMAS["manifest"]),
        "sourceAccountingSchemaDigest": file_sha256(SCHEMA_ROOT / SCHEMAS["sourceAccounting"]),
        "acceptanceSchemaDigest": file_sha256(SCHEMA_ROOT / SCHEMAS["acceptance"]),
    }


def corpus_digest() -> str:
    """Digest the conformance corpus that proves this validator's behaviour.

    Proof identity, not contract identity. An acceptance record says which
    validator ran; this says which corpus that validator was answerable to when
    it ran. It is RECORDED into the acceptance record and deliberately not
    re-derived by `_check_binding_pins`: growing the corpus must leave every
    artifact on disk valid, because nothing a new test case says changes what
    those artifacts were validated against.
    """

    return file_sha256(CORPUS_PATH)


def _binding_tool_paths() -> tuple[Path, ...]:
    """Resolve BINDING_TOOL_PATHS against this binding.

    A function rather than a constant so a caller can point the tool inventory
    at a different copy of these files -- which is how the cache test
    proves that an edited validator cannot be answered from the old
    validator's receipt without editing the installed validator itself.
    """

    return tuple(BINDING_ROOT / relative for relative in BINDING_TOOL_PATHS)


def _binding_tool_digest() -> str:
    """Digest the programs that read the contract, in the bundle's own form."""

    rows = [
        {
            "byteLength": path.stat().st_size,
            "digest": file_sha256(path),
            "path": path.relative_to(BINDING_ROOT).as_posix()
            if path.is_relative_to(BINDING_ROOT)
            else path.name,
        }
        for path in _binding_tool_paths()
    ]
    return canonical_sha256(sorted(rows, key=lambda row: row["path"]), terminal_lf=False)


def _binding_runtime_distributions() -> list[str]:
    """The binding's declared dependencies, read from the file that declares them.

    A verdict depends on these implementations and not merely on the version
    pins beside them: pyshacl and owlrl decide conformance, rdflib parses and
    serializes, and the zstd transports come from ``backports.zstd`` below 3.14
    and the standard library at and above it. Requirements are parsed rather
    than restated so nothing here has to remember a new dependency.
    """

    names = []
    for line in (BINDING_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        requirement = line.split("#", 1)[0].split(";", 1)[0].strip()
        if requirement:
            names.append(re.split(r"[=<>!~\[]", requirement, maxsplit=1)[0].strip())
    return sorted(names)


def binding_runtime() -> dict[str, str]:
    """Return the interpreter and dependency versions this process is running.

    One notion, two readers: ``fixtures-receipt.json`` records it to decide
    whether the committed corpus still describes its inputs, and the validation
    cache key records it so a library bump cannot be answered from a receipt an
    older library wrote.
    """

    from importlib.metadata import PackageNotFoundError, version

    runtime = {"python": f"{sys.version_info.major}.{sys.version_info.minor}"}
    for name in _binding_runtime_distributions():
        try:
            runtime[name] = version(name)
        except PackageNotFoundError:
            runtime[name] = "absent"
    return runtime


def _check_binding_pins(manifest: Mapping[str, Any], acceptance: Mapping[str, Any]) -> None:
    expected = _binding_digests()
    manifest_binding = manifest["binding"]
    for field, digest in expected.items():
        if manifest_binding[field] != digest:
            _fail("binding.digest", f"manifest binding.{field} does not match the binding asset")
        if acceptance["inputs"][field] != digest:
            _fail("binding.digest", f"acceptance inputs.{field} does not match the binding asset")
    if manifest_binding["validatorVersion"] != VALIDATOR_VERSION:
        _fail("binding.validator", "manifest validatorVersion does not match this validator")
    if acceptance["validator"] != {"name": VALIDATOR_ID, "version": VALIDATOR_VERSION}:
        _fail("binding.validator", "acceptance validator identity does not match this validator")


def _check_manifest_digest(manifest: Mapping[str, Any]) -> None:
    payload = dict(manifest)
    actual = payload.pop("canonicalPayloadDigest")
    expected = canonical_sha256(payload, terminal_lf=False)
    if actual != expected:
        _fail("manifest.identity", "canonicalPayloadDigest does not match the canonical manifest payload")


def _graph_inventory_digest(
    packs: Iterable[Mapping[str, Any]],
    role: str,
) -> str:
    rows = [
        {
            "contentDigest": pack["content"]["digest"],
            "packId": pack["packId"],
            "quadCount": pack["graphCounts"][role],
        }
        for pack in packs
        if pack["graphCounts"][role] > 0
    ]
    rows.sort(key=lambda row: row["packId"])
    return canonical_sha256(rows, terminal_lf=False)


def _check_pack_manifest(manifest: Mapping[str, Any]) -> dict[str, URIRef]:
    """Reconcile pack inventories, dependencies, ordering, and partition metadata."""

    packs = manifest["packs"]
    pack_ids = [pack["packId"] for pack in packs]
    if pack_ids != sorted(pack_ids) or len(pack_ids) != len(set(pack_ids)):
        _fail("pack.manifest", "packs must have unique packId values in lexicographic order")
    paths = [pack["path"] for pack in packs]
    if len(paths) != len(set(paths)):
        _fail("pack.manifest", "pack paths must be unique")

    known_pack_ids = set(pack_ids)
    for pack in packs:
        pack_id = pack["packId"]
        expected_pack_id = (
            "urn:ref:atlas:pack:"
            + pack["content"]["digest"].removeprefix("sha256:")
        )
        if pack_id != expected_pack_id:
            _fail("pack.manifest", f"{pack_id} does not derive from its content digest")
        for field in ("dependencies", "rings", "sourceReleases"):
            values = pack[field]
            if values != sorted(values) or len(values) != len(set(values)):
                _fail("pack.manifest", f"{pack_id} {field} must be unique and sorted")
        dependencies = pack["dependencies"]
        if pack_id in dependencies or not set(dependencies) <= known_pack_ids:
            _fail("pack.dependency", f"{pack_id} has a self or unknown dependency")
        graph_count = sum(pack["graphCounts"].values())
        if graph_count != pack["content"]["quadCount"]:
            _fail("pack.inventory", f"{pack_id} graph counts differ from content quadCount")

    graphs = manifest["graphs"]
    graph_roles = [row["role"] for row in graphs]
    if graph_roles != ["asserted", "projection", "derived"]:
        _fail("pack.inventory", "graph inventories must occur in asserted, projection, derived order")
    graph_ids = {row["role"]: URIRef(row["id"]) for row in graphs}
    if len(set(graph_ids.values())) != len(graph_ids):
        _fail("pack.inventory", "named graph IDs must be unique")
    for graph_row in graphs:
        role = graph_row["role"]
        role_packs = [pack for pack in packs if pack["graphCounts"][role] > 0]
        if graph_row["packCount"] != len(role_packs):
            _fail("pack.inventory", f"{role} graph packCount differs")
        if graph_row["quadCount"] != sum(pack["graphCounts"][role] for pack in role_packs):
            _fail("pack.inventory", f"{role} graph quadCount differs")
        if graph_row["inventoryDigest"] != _graph_inventory_digest(packs, role):
            _fail("pack.inventory", f"{role} graph inventoryDigest differs")

    asserted_digest = graphs[0]["inventoryDigest"]
    asserted_pack_ids = {
        pack["packId"] for pack in packs if pack["graphCounts"]["asserted"] > 0
    }
    for pack in packs:
        has_view = pack["graphCounts"]["projection"] > 0 or pack["graphCounts"]["derived"] > 0
        if has_view:
            if pack.get("inputAssertedDigest") != asserted_digest:
                _fail("pack.dependency", f"{pack['packId']} does not pin the asserted inventory")
            expected_dependencies = asserted_pack_ids - {pack["packId"]}
            if set(pack["dependencies"]) != expected_dependencies:
                _fail("pack.dependency", f"{pack['packId']} does not depend on every external asserted pack")
        elif "inputAssertedDigest" in pack:
            _fail("pack.dependency", f"{pack['packId']} has an inapplicable inputAssertedDigest")

    partitions_by_release: dict[str, list[tuple[str, str]]] = defaultdict(list)
    source_release_counts: Counter[str] = Counter(
        release
        for pack in packs
        if pack["kind"] == "sourceRelease"
        for release in pack["sourceReleases"]
    )
    for pack in packs:
        if pack["kind"] != "sourceRelease":
            continue
        release = pack["sourceReleases"][0]
        partition = pack.get("partition")
        if source_release_counts[release] > 1 and partition is None:
            _fail("pack.co-location", f"partitioned source release {release} lacks stable bucket metadata")
        if partition is not None:
            partitions_by_release[release].append((partition["prefix"], pack["packId"]))
    for release, partitions in partitions_by_release.items():
        for index, (prefix, pack_id) in enumerate(partitions):
            for other_prefix, other_id in partitions[index + 1 :]:
                if prefix.startswith(other_prefix) or other_prefix.startswith(prefix):
                    _fail(
                        "pack.co-location",
                        f"{release} has overlapping subject buckets {pack_id} and {other_id}",
                    )
    return graph_ids


def _safe_distribution_path(root: Path, relative: str) -> Path:
    path = root / relative
    try:
        if not path.resolve().is_relative_to(root.resolve()):
            _fail("distribution.path", f"distribution member escapes its root: {relative}")
    except OSError as exc:
        _fail("distribution.path", f"cannot resolve distribution member {relative}: {exc}")
    return path


def _compact_canonical_json_bytes(value: Any) -> bytes:
    """Return the compact codec's newline-terminated canonical JSON."""

    return canonical_native_json_bytes(value) + b"\n"


def _compact_nonempty(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value:
        _fail("construction.compact", f"{path}: expected a non-empty string")
    return value


def _compact_iri(value: Any, path: str) -> str:
    iri = _compact_nonempty(value, path)
    if ABSOLUTE_IRI_RE.fullmatch(iri) is None:
        _fail("construction.compact", f"{path}: expected an absolute IRI")
    return iri


def _compact_digest(value: Any, path: str) -> str:
    digest = _compact_nonempty(value, path)
    if DIGEST_RE.fullmatch(digest) is None:
        _fail("construction.compact", f"{path}: expected a lowercase sha256 digest")
    return digest


def _compact_token(value: Any, choices: Collection[str], path: str) -> str:
    token = _compact_nonempty(value, path)
    if token not in choices:
        _fail(
            "construction.compact",
            f"{path}: expected one of {', '.join(sorted(choices))}",
        )
    return token


def _compact_sorted_unique_strings(value: Any, path: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        _fail("construction.compact", f"{path}: expected an array")
    strings = [
        _compact_nonempty(child, f"{path}[{index}]")
        for index, child in enumerate(value)
    ]
    if strings != sorted(strings) or len(strings) != len(set(strings)):
        _fail("construction.compact", f"{path}: values must be unique and sorted")
    return strings


def _compact_reject_non_native_nulls(record: Mapping[str, Any], path: str) -> None:
    for field, value in record.items():
        if field == "nativePayload":
            canonical_native_json_bytes(value)
        else:
            _reject_nulls_and_numbers(value, f"{path}.{field}")


def _normalize_compact_record(
    role: str,
    raw_record: Mapping[str, Any],
    *,
    path: str,
) -> dict[str, Any]:
    """Independently normalize one closed logical row and verify its digest."""

    if role not in COMPACT_RECORD_FIELDS:
        _fail("construction.compact", f"{path}: unsupported record role {role!r}")
    if not isinstance(raw_record, Mapping):
        _fail("construction.compact", f"{path}: expected an object")
    value = dict(raw_record)
    _compact_reject_non_native_nulls(value, path)
    supplied_digest = value.pop("canonicalPayloadDigest", None)
    required, optional = COMPACT_RECORD_FIELDS[role]
    allowed = required | optional | {"contentDigest"}
    missing = sorted(required - value.keys())
    unknown = sorted(value.keys() - allowed)
    if missing:
        _fail("construction.compact", f"{path}: missing fields: {', '.join(missing)}")
    if unknown:
        _fail("construction.compact", f"{path}: unknown fields: {', '.join(unknown)}")

    for field in COMPACT_IRI_FIELDS[role]:
        value[field] = _compact_iri(value[field], f"{path}.{field}")
    for field in allowed - {
        "id",
        "nativePayload",
        "contentDigest",
        "notes",
        "notations",
        "sourceRecords",
    }:
        if field in value:
            value[field] = _compact_nonempty(value[field], f"{path}.{field}")
    if "contentDigest" in value:
        value["contentDigest"] = _compact_digest(
            value["contentDigest"],
            f"{path}.contentDigest",
        )

    if role == "Resource":
        _compact_token(
            value["semanticRing"],
            {"subject", "entity", "value", "legalIdentity"},
            f"{path}.semanticRing",
        )
        _compact_token(
            value["resourceProfile"],
            EXPECTED_PROFILE_NAMES,
            f"{path}.resourceProfile",
        )
        for field in ("notes", "notations"):
            if field in value:
                value[field] = _compact_sorted_unique_strings(value[field], f"{path}.{field}")
    elif role == "Label":
        _compact_token(
            value["labelRole"],
            {"preferred", "alternate", "hidden"},
            f"{path}.labelRole",
        )
        if value["language"] != "en":
            _fail("construction.compact", f"{path}.language: Atlas labels must be English")
        if value["value"] != value["value"].strip():
            _fail("construction.compact", f"{path}.value: expected trimmed text")
    elif role == "Statement":
        _compact_token(
            value["statementType"],
            {
                "NativeRelationAssertion",
                "MappingAssertion",
                "SourceAssignment",
                "CrossRingRelationAssertion",
            },
            f"{path}.statementType",
        )
        value["assertionIdentityDigest"] = _compact_digest(
            value["assertionIdentityDigest"],
            f"{path}.assertionIdentityDigest",
        )
        if "supersedesAssertion" in value:
            value["supersedesAssertion"] = _compact_iri(
                value["supersedesAssertion"],
                f"{path}.supersedesAssertion",
            )
        if value["statementType"] == "CrossRingRelationAssertion":
            if "semanticRing" in value or not {"sourceRing", "targetRing"} <= value.keys():
                _fail(
                    "construction.compact",
                    f"{path}: cross-ring statements require sourceRing and targetRing only",
                )
            for field in ("sourceRing", "targetRing"):
                _compact_token(
                    value[field],
                    {"subject", "entity", "value", "legalIdentity"},
                    f"{path}.{field}",
                )
            if value["sourceRing"] == value["targetRing"]:
                _fail("construction.compact", f"{path}: cross-ring statement rings must differ")
        elif "semanticRing" not in value or {"sourceRing", "targetRing"} & value.keys():
            _fail(
                "construction.compact",
                f"{path}: same-ring statements require semanticRing only",
            )
        else:
            _compact_token(
                value["semanticRing"],
                {"subject", "entity", "value", "legalIdentity"},
                f"{path}.semanticRing",
            )
    elif role == "EvidenceBinding":
        value["evidenceSourceDigest"] = _compact_digest(
            value["evidenceSourceDigest"],
            f"{path}.evidenceSourceDigest",
        )
    elif role == "SourceRecord":
        value["sourceDigest"] = _compact_digest(
            value["sourceDigest"],
            f"{path}.sourceDigest",
        )
        if "representsResource" in value:
            value["representsResource"] = _compact_iri(
                value["representsResource"],
                f"{path}.representsResource",
            )
    elif role == "Release":
        release_type = _compact_token(
            value["releaseType"],
            {"AtlasRelease", "SourceRelease"},
            f"{path}.releaseType",
        )
        source_fields = {"sourceDigest", "sourceLocator"}
        atlas_fields = {"resourceProfile", "semanticRing", "scheme", "membershipMode"}
        required_fields = source_fields if release_type == "SourceRelease" else atlas_fields
        forbidden_fields = atlas_fields if release_type == "SourceRelease" else source_fields
        if not required_fields <= value.keys() or forbidden_fields & value.keys():
            _fail("construction.compact", f"{path}: {release_type} fields differ")
        if release_type == "SourceRelease":
            value["sourceDigest"] = _compact_digest(
                value["sourceDigest"],
                f"{path}.sourceDigest",
            )
            value["sourceLocator"] = _compact_iri(
                value["sourceLocator"],
                f"{path}.sourceLocator",
            )
        else:
            _compact_token(
                value["resourceProfile"],
                EXPECTED_PROFILE_NAMES,
                f"{path}.resourceProfile",
            )
            _compact_token(
                value["semanticRing"],
                {"subject", "entity", "value", "legalIdentity"},
                f"{path}.semanticRing",
            )
            value["scheme"] = _compact_iri(value["scheme"], f"{path}.scheme")
    elif role == "LifecycleEvent":
        source_records = _compact_sorted_unique_strings(
            value["sourceRecords"],
            f"{path}.sourceRecords",
        )
        if not source_records:
            _fail("construction.compact", f"{path}.sourceRecords: expected at least one IRI")
        value["sourceRecords"] = [
            _compact_iri(source_record, f"{path}.sourceRecords[{index}]")
            for index, source_record in enumerate(source_records)
        ]
        for field in ("fromRelease", "toRelease"):
            if field in value:
                value[field] = _compact_iri(value[field], f"{path}.{field}")

    expected_digest = "sha256:" + hashlib.sha256(
        _compact_canonical_json_bytes({"recordRole": role, "record": value})
    ).hexdigest()
    if supplied_digest is not None and _compact_digest(
        supplied_digest,
        f"{path}.canonicalPayloadDigest",
    ) != expected_digest:
        _fail(
            "construction.compact",
            f"{path}.canonicalPayloadDigest: digest differs from the normalized row",
        )
    value["canonicalPayloadDigest"] = expected_digest
    return value














def _check_distribution_files(
    root: Path,
    manifest: Mapping[str, Any],
) -> dict[str, str]:
    """Check closed membership and lengths; return digests for each required read to verify."""

    if root.is_symlink() or not root.is_dir():
        _fail("distribution.path", f"distribution is not a regular directory: {root}")
    expected_lengths: dict[str, int] = {MANIFEST_FILE: (root / MANIFEST_FILE).stat().st_size}
    member_digests: dict[str, str] = {}
    for member in manifest["members"]:
        relative = member["path"]
        if relative in expected_lengths:
            _fail("distribution.members", f"duplicate distribution path {relative}")
        expected_lengths[relative] = member["byteLength"]
        member_digests[relative] = member["digest"]
    for pack in manifest["packs"]:
        relative = pack["path"]
        if relative in expected_lengths:
            _fail("distribution.members", f"duplicate distribution path {relative}")
        expected_lengths[relative] = pack["transport"]["byteLength"]
        member_digests[relative] = pack["transport"]["digest"]
    expected_directories = {
        parent.as_posix()
        for relative in expected_lengths
        for parent in Path(relative).parents
        if parent != Path(".")
    }
    actual_files: set[str] = set()
    actual_directories: set[str] = set()
    for entry in root.rglob("*"):
        relative = entry.relative_to(root).as_posix()
        if entry.is_symlink():
            _fail("distribution.path", f"unsafe symlink in distribution: {relative}")
        if entry.is_dir():
            actual_directories.add(relative)
        elif entry.is_file():
            actual_files.add(relative)
        else:
            _fail("distribution.path", f"unsafe distribution member: {relative}")
    if actual_files != set(expected_lengths) or actual_directories != expected_directories:
        _fail(
            "distribution.members",
            "distribution members differ; "
            f"missingFiles={sorted(set(expected_lengths) - actual_files)}, "
            f"extraFiles={sorted(actual_files - set(expected_lengths))}, "
            f"missingDirectories={sorted(expected_directories - actual_directories)}, "
            f"extraDirectories={sorted(actual_directories - expected_directories)}",
        )
    for relative, expected_length in expected_lengths.items():
        path = _safe_distribution_path(root, relative)
        if path.stat().st_size != expected_length:
            _fail("distribution.length", f"{relative} byteLength differs")
    return member_digests


def _new_dataset() -> Dataset:
    """Create the selected RDF store and its matching term-construction path.

    ``two-index`` is the production default. Setting
    ``REFSPEC_ATLAS_RDF_STORE=memory`` restores stock rdflib ``Memory`` and
    stock RDF terms for immediate mitigation and differential checks.
    """

    selected = os.environ.get(RDF_STORE_ENV, TWO_INDEX_STORE)
    if selected == MEMORY_STORE:
        return Dataset()
    if selected == TWO_INDEX_STORE:
        dataset = Dataset(store=TwoIndexStore())
        dataset._refspec_term_pool = TermPool()
        return dataset
    _fail(
        "configuration.rdf-store",
        f"{RDF_STORE_ENV} must be {TWO_INDEX_STORE!r} or {MEMORY_STORE!r}",
    )


def _parse_dataset(
    path: Path,
    manifest: Mapping[str, Any],
    *,
    expected_digest: str | None = None,
) -> tuple[Dataset, dict[str, Graph]]:
    line_count = _check_serialized_nquads_profile(path, expected_digest=expected_digest)
    dataset = _new_dataset()
    try:
        counts = _parse_nquads_preserving_lexical_forms(dataset, path)
    except AtlasValidationError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalize RDF parser failures
        _fail("rdf.syntax", f"atlas.nq cannot be parsed as N-Quads: {exc}")
    if sum(counts.values()) != line_count:
        _fail("rdf.canonical", "parsed quad count differs from serialized line count")

    declared = {row["role"]: URIRef(row["id"]) for row in manifest["graphs"]}
    allowed_ids = set(declared.values())
    for graph_id in counts:
        if graph_id not in allowed_ids:
            _fail("dataset.graph", f"statement occurs in undeclared graph {graph_id}")
    for row in manifest["graphs"]:
        graph_id = URIRef(row["id"])
        if counts[graph_id] != row["quadCount"]:
            _fail("dataset.graph-count", f"{row['role']} graph quadCount differs")
    if counts[declared["asserted"]] == 0:
        _fail("dataset.graph", "asserted graph is empty")
    graphs = {role: dataset.graph(graph_id) for role, graph_id in declared.items()}
    return dataset, graphs


def _parse_pack_into_dataset(
    dataset: Dataset,
    root: Path,
    pack: Mapping[str, Any],
    graph_ids: Mapping[str, URIRef],
    subject_owners: Mapping[str, dict[URIRef, str]],
    *,
    asserted_placement: _AssertedPlacementObservation | None = None,
    node_digests: _AssertedNodeDigests | None = None,
) -> Counter[URIRef]:
    """Stream, receipt, and parse one independently addressable pack."""

    pack_id = pack["packId"]
    # Refuse the declaration before opening anything it describes. The
    # streaming content reader already stops a pack whose real bytes exceed
    # what the manifest declared (`pack.content`), so bounding the declaration
    # bounds the decompressed bytes this call can be made to produce.
    if pack["transport"]["byteLength"] > NQUADS_MAX_TRANSPORT_BYTES:
        _fail("rdf.resource-limit", f"{pack['path']} exceeds the RDF pack transport limit")
    if pack["content"]["byteLength"] > NQUADS_MAX_CONTENT_BYTES:
        _fail("rdf.resource-limit", f"{pack['path']} exceeds the RDF pack content limit")
    path = _safe_distribution_path(root, pack["path"])
    role_by_graph = {graph_id: role for role, graph_id in graph_ids.items()}
    partition_prefix = pack.get("partition", {}).get("prefix")

    def observe_subject(graph_id: URIRef, subject: URIRef) -> None:
        role = role_by_graph.get(graph_id)
        if role is None:
            _fail("dataset.graph", f"{pack_id} contains undeclared graph {graph_id}")
        previous = subject_owners[role].get(subject)
        if previous is not None and previous != pack_id:
            _fail(
                "pack.co-location",
                f"{subject} has {role} outgoing facts in both {previous} and {pack_id}",
            )
        subject_owners[role][subject] = pack_id
        if partition_prefix is not None:
            actual_prefix = hashlib.sha256(str(subject).encode("utf-8")).hexdigest()
            if not actual_prefix.startswith(partition_prefix):
                _fail("pack.partition", f"{subject} does not belong in {pack_id} bucket {partition_prefix}")

    with path.open("rb") as stored_stream:
        transport_reader = _DigestingReader(stored_stream, label=pack["path"])
        compression = pack["transport"]["compression"]
        decoded_stream: Any = transport_reader
        if compression == "zstd":
            try:
                decoded_stream = zstd.open(transport_reader, "rb")
            except Exception as exc:  # noqa: BLE001 - normalize decoder setup failures
                _fail("pack.compression", f"cannot open {pack['path']} as Zstandard: {exc}")
        content_reader = _NQuadsProfileReader(
            decoded_stream,
            label=pack["path"],
            expected=pack["content"],
            node_digests=node_digests,
        )
        try:
            counts = _parse_nquads_preserving_lexical_forms(
                dataset,
                content_reader,
                subject_observer=observe_subject,
                asserted_placement=asserted_placement,
            )
            content_reader.finish(pack["content"])
            transport_reader.finish(
                pack["transport"],
                require_consumed=compression == "zstd",
            )
        except AtlasValidationError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalize RDF and compression failures
            _fail("rdf.syntax", f"{pack['path']} cannot be parsed as N-Quads: {exc}")
        finally:
            if decoded_stream is not transport_reader:
                decoded_stream.close()

    expected_counts = {
        graph_ids[role]: count for role, count in pack["graphCounts"].items()
    }
    undeclared = set(counts) - set(expected_counts)
    if undeclared:
        _fail("dataset.graph", f"{pack_id} contains undeclared graph {min(undeclared, key=str)}")
    for graph_id, expected in expected_counts.items():
        if counts[graph_id] != expected:
            _fail("pack.inventory", f"{pack_id} graph count differs for {graph_id}")
    return counts


def _parse_packed_dataset(
    root: Path,
    manifest: Mapping[str, Any],
    graph_ids: Mapping[str, URIRef],
    *,
    asserted_placement: _AssertedPlacementObservation | None = None,
    node_digests: _AssertedNodeDigests | None = None,
) -> tuple[Dataset, dict[str, Graph]]:
    """Parse verified packs into one graph store for global Atlas invariants.

    An optional `asserted_placement` accumulates the graph-role facts
    `_check_graph_roles` would otherwise re-derive by walking the whole store
    again, and an optional `node_digests` accumulates per-node content digests
    off the same bytes; see each observation's own docstring.
    """

    dataset = _new_dataset()
    subject_owners: dict[str, dict[URIRef, str]] = {
        role: {} for role in graph_ids
    }
    aggregate_counts: Counter[URIRef] = Counter()
    packs = manifest["packs"]
    total_content_bytes = sum(pack["content"]["byteLength"] for pack in packs)
    if total_content_bytes > NQUADS_DATASET_MAX_CONTENT_BYTES:
        _fail("rdf.resource-limit", "RDF packs exceed the aggregate dataset content limit")
    for pack_position, pack in enumerate(packs, start=1):
        _STATUS.progress(
            "parse-rdf-packs",
            pack_position - 1,
            len(packs),
            current=pack["path"],
        )
        counts = _parse_pack_into_dataset(
            dataset,
            root,
            pack,
            graph_ids,
            subject_owners,
            asserted_placement=asserted_placement,
            node_digests=node_digests,
        )
        # A pack is an independently addressable stream, so no subject
        # continues into the next one: close the open node here rather than
        # let two packs' rows meet.
        if node_digests is not None:
            node_digests.finish()
        aggregate_counts.update(counts)
        _STATUS.progress(
            "parse-rdf-packs",
            pack_position,
            len(packs),
            current=pack["path"],
        )
    for graph_row in manifest["graphs"]:
        graph_id = graph_ids[graph_row["role"]]
        if aggregate_counts[graph_id] != graph_row["quadCount"]:
            _fail("pack.inventory", f"{graph_row['role']} aggregate graph count differs")
    _check_asserted_pack_dependencies(
        dataset.graph(graph_ids["asserted"]),
        manifest,
        subject_owners["asserted"],
    )
    graphs = {
        role: dataset.graph(graph_id) for role, graph_id in graph_ids.items()
    }
    return dataset, graphs


def _check_asserted_pack_dependencies(
    asserted: Graph,
    manifest: Mapping[str, Any],
    subject_owners: Mapping[URIRef, str],
) -> None:
    """Require exact dependencies for asserted references crossing pack boundaries."""

    expected: dict[str, set[str]] = {
        pack["packId"]: set() for pack in manifest["packs"]
    }
    for subject, _, obj in asserted:
        if not isinstance(obj, URIRef):
            continue
        source_pack = subject_owners[subject]
        target_pack = subject_owners.get(obj)
        if target_pack is not None and target_pack != source_pack:
            expected[source_pack].add(target_pack)

    for pack in manifest["packs"]:
        if pack["graphCounts"]["projection"] or pack["graphCounts"]["derived"]:
            continue
        pack_id = pack["packId"]
        declared = set(pack["dependencies"])
        if declared != expected[pack_id]:
            _fail(
                "pack.dependency",
                f"{pack_id} dependencies differ; "
                f"missing={sorted(expected[pack_id] - declared)}, "
                f"extra={sorted(declared - expected[pack_id])}",
            )


def _parse_binding_graphs() -> tuple[Graph, Graph]:
    ontology = Graph()
    shapes = Graph()
    try:
        ontology.parse(ONTOLOGY_PATH, format="turtle")
    except Exception as exc:  # noqa: BLE001 - normalize RDF parser failures
        _fail("ontology.syntax", f"cannot parse atlas.ttl: {exc}")
    try:
        shapes.parse(SHAPES_PATH, format="turtle")
    except Exception as exc:  # noqa: BLE001 - normalize RDF parser failures
        _fail("shacl.syntax", f"cannot parse atlas.shacl.ttl: {exc}")
    return ontology, shapes


def _lint_ontology(ontology: Graph) -> None:
    allowed_predicates = {
        RDF.type,
        RDFS.comment,
        RDFS.domain,
        RDFS.label,
        RDFS.range,
        RDFS.subClassOf,
        OWL.disjointWith,
        OWL.versionInfo,
    }
    allowed_declaration_types = {
        OWL.Ontology,
        OWL.Class,
        OWL.ObjectProperty,
        OWL.DatatypeProperty,
        ATLAS.SemanticRing,
        ATLAS.ResourceProfile,
    }
    allowed_datatype_ranges = {
        RDFS.Literal,
        XSD.dateTime,
        XSD.decimal,
        XSD.integer,
        XSD.string,
    }
    ontology_iri = URIRef("https://refspec.org/ns/atlas/v3")
    for subject, predicate, obj in ontology:
        if isinstance(subject, BNode) or isinstance(obj, BNode):
            _fail("ontology.profile", "Atlas ontology MUST contain no blank nodes")
        if not isinstance(subject, URIRef) or not (subject == ontology_iri or str(subject).startswith(str(ATLAS))):
            _fail("ontology.profile", f"Atlas ontology defines an external subject {subject}")
        if predicate not in allowed_predicates:
            _fail("ontology.profile", f"Atlas ontology uses non-allowlisted predicate {predicate}")
        if predicate == RDF.type and obj not in allowed_declaration_types:
            _fail("ontology.profile", f"Atlas ontology uses non-allowlisted rdf:type {obj}")
        if (
            predicate == RDFS.range
            and (subject, RDF.type, OWL.DatatypeProperty) in ontology
            and obj not in allowed_datatype_ranges
        ):
            _fail("ontology.profile", f"Atlas datatype property uses non-RL range {obj}")

    declared_terms = {
        subject
        for subject, _, declaration_type in ontology.triples((None, RDF.type, None))
        if declaration_type in allowed_declaration_types and subject != ontology_iri
    }
    for subject in declared_terms:
        if not list(ontology.objects(subject, RDFS.label)):
            _fail("ontology.term", f"Atlas term has no rdfs:label: {subject}")


_SHACL_TARGET_PREDICATES = (
    SH.targetClass,
    SH.targetNode,
    SH.targetObjectsOf,
    SH.targetSubjectsOf,
)
_INLINE_VALUE_SHAPES = frozenset(
    {
        ATLAS.DateTimeValueShape,
        ATLAS.DigestValueShape,
        ATLAS.NonEmptyStringValueShape,
        ATLAS.ResourceProfileValueShape,
        ATLAS.SemanticRingValueShape,
        ATLAS.TextLiteralValueShape,
    }
)
_INLINE_VALUE_CONSTRAINTS = frozenset(
    {
        SH.datatype,
        SH.minLength,
        SH.nodeKind,
        SH["or"],
        SH.pattern,
    }
)
_SHAPE_EXPECTING_PREDICATES = (
    SH.node,
    SH["not"],
    SH.property,
    SH.qualifiedValueShape,
)
_SHAPE_LIST_PREDICATES = (SH["and"], SH["or"], SH.xone)

# atlas:EvidenceBindingShape's warrant `sh:xone`, as this validator last proved
# it liftable: one frozenset of `(path, sh:hasValue, sh:minCount, sh:maxCount)`
# rows per branch, in no particular order.
#
# This is a PIN, not the semantics. The conditions the precheck evaluates are
# parsed out of the shapes graph at plan-build time
# (`_evidence_warrant_branch_table`), so the warrant table is read off the wire
# rather than restated in Python; this literal answers only "is the shape still
# the one the lift was proved equivalent to?". Any drift -- an amended warrant
# table, a seventh branch, a branch carrying a SHACL form the precheck cannot
# evaluate -- refuses the lift and hands the `sh:xone` back to the engine,
# exactly as `_can_lift_relation_ring_context` refuses. The refusal is silent
# but not unnoticed: `test_batched_shacl_plan_keeps_normative_shapes_and_lifts_
# direct_properties` asserts the lift engaged, so drift fails a test rather
# than quietly costing the acceptance hour back.
_EVIDENCE_WARRANT_BRANCH_SIGNATURES = frozenset(
    {
        frozenset(  # publisherAssertion
            {
                (RKAF.epistemicBasis, RKAF.sourceExplicit, None, None),
                (RKAF.evidenceRole, RKAF.officialSourceMetadata, None, None),
                (RKAF.assertionOrigin, RKAF.imported, None, None),
                (RKAF.basedOnAttestation, None, None, 0),
            }
        ),
        frozenset(  # deterministicTransformation
            {
                (RKAF.epistemicBasis, RKAF.deterministicDerivation, None, None),
                (RKAF.evidenceRole, RKAF.structuralEvidence, None, None),
                (RKAF.assertionOrigin, RKAF.deterministicExtraction, None, None),
                (RKAF.basedOnAttestation, None, None, 0),
            }
        ),
        frozenset(  # humanReview
            {
                (RKAF.assertionOrigin, RKAF.humanAsserted, None, None),
                (RKAF.attestorKind, RKAF.humanUser, None, None),
                (RKAF.epistemicBasis, RKAF.editorialAssertion, None, None),
                (RKAF.evidenceRole, RKAF.textualEvidence, None, None),
                (RKAF.basedOnAttestation, None, None, 0),
            }
        ),
        frozenset(  # operatorAdoption -- the only branch that MAY name what it adopted
            {
                (RKAF.epistemicBasis, RKAF.editorialAssertion, None, None),
                (RKAF.evidenceRole, RKAF.formalAdoptionEvent, None, None),
                (RKAF.assertionOrigin, RKAF.imported, None, None),
            }
        ),
        frozenset(  # twoMachineAdjudication
            {
                (RKAF.assertionOrigin, RKAF.aiSuggested, None, None),
                (RKAF.epistemicBasis, RKAF.statisticalInference, None, None),
                (RKAF.evidenceRole, RKAF.reviewedAuthorityChain, None, None),
                (RKAF.basedOnAttestation, None, None, 0),
            }
        ),
        frozenset(  # trustedPipelineReview
            {
                (RKAF.epistemicBasis, RKAF.deterministicDerivation, None, None),
                (RKAF.evidenceRole, RKAF.authorityCitation, None, None),
                (RKAF.assertionOrigin, RKAF.imported, None, None),
                (RKAF.basedOnAttestation, None, None, 0),
            }
        ),
    }
)

# Which SHACL report a refused distribution gets. See `_run_shacl`.
VALIDATION_MODE_ENV = "REFSPEC_ATLAS_VALIDATION_MODE"
AUDIT_VALIDATION_MODE = "audit"
# How many distinct violated constraints the focused red path reproduces. The
# number of distinct (shape, component, path) signatures a graph can violate is
# bounded by the shapes file, so this only binds on a distribution that
# violates nearly all of the binding at once -- and when it binds, the
# whole-graph report is used rather than risk naming fewer components than the
# audit run would.
SHACL_FOCUS_SAMPLE_LIMIT = 256
_FOCUS_NODE_SCHEMES = ("http:", "https:", "urn:", "file:")


def _copy_graph(graph: Graph) -> Graph:
    copied = Graph(identifier=graph.identifier)
    for prefix, namespace in graph.namespaces():
        copied.bind(prefix, namespace)
    for triple in graph:
        copied.add(triple)
    return copied


def _referenced_shapes(shapes: Graph) -> set[Any]:
    referenced = {
        obj
        for predicate in _SHAPE_EXPECTING_PREDICATES
        for obj in shapes.objects(None, predicate)
    }
    for predicate in _SHAPE_LIST_PREDICATES:
        for head in shapes.objects(None, predicate):
            referenced.update(shapes.items(head))
    return referenced


def _closed_shape_plan(
    shapes: Graph,
    shape: URIRef,
    property_shapes: Sequence[Any],
) -> _ClosedShapePlan | None:
    closed_values = list(shapes.objects(shape, SH.closed))
    if not closed_values or not all(isinstance(value, Literal) and bool(value.value) for value in closed_values):
        return None
    allowed_paths = frozenset(
        path
        for property_shape in property_shapes
        for path in shapes.objects(property_shape, SH.path)
    )
    ignored_paths = frozenset(
        item
        for head in shapes.objects(shape, SH.ignoredProperties)
        for item in shapes.items(head)
    )
    return _ClosedShapePlan(
        shape=shape,
        allowed_paths=allowed_paths,
        ignored_paths=ignored_paths,
    )


def _ring_context_branch_signature(shapes: Graph, branch: Any) -> frozenset[tuple[Any, int | None, int | None]] | None:
    if set(shapes.predicates(branch, None)) - {SH.property}:
        return None
    signature: set[tuple[Any, int | None, int | None]] = set()
    for property_shape in shapes.objects(branch, SH.property):
        if set(shapes.predicates(property_shape, None)) - {SH.path, SH.minCount, SH.maxCount}:
            return None
        paths = list(shapes.objects(property_shape, SH.path))
        minimums = list(shapes.objects(property_shape, SH.minCount))
        maximums = list(shapes.objects(property_shape, SH.maxCount))
        if len(paths) != 1 or len(minimums) > 1 or len(maximums) > 1:
            return None
        minimum = int(minimums[0]) if minimums else None
        maximum = int(maximums[0]) if maximums else None
        signature.add((paths[0], minimum, maximum))
    return frozenset(signature)


def _can_lift_relation_ring_context(shapes: Graph) -> bool:
    heads = list(shapes.objects(ATLAS.RelationAssertionShape, SH.xone))
    if len(heads) != 1:
        return False
    signatures = {
        _ring_context_branch_signature(shapes, branch)
        for branch in shapes.items(heads[0])
    }
    return signatures == {
        frozenset(
            {
                (ATLAS.semanticRing, 1, None),
                (ATLAS.sourceRing, None, 0),
                (ATLAS.targetRing, None, 0),
            }
        ),
        frozenset(
            {
                (ATLAS.semanticRing, None, 0),
                (ATLAS.sourceRing, 1, None),
                (ATLAS.targetRing, 1, None),
            }
        ),
    }


def _warrant_branch_signature(
    shapes: Graph,
    branch: Any,
) -> frozenset[tuple[Any, Any, int | None, int | None]] | None:
    """Parse one `sh:xone` branch into `(path, hasValue, minCount, maxCount)` rows.

    Returns None for any branch that is not a plain conjunction of property
    shapes over single IRI paths carrying only those three constraints. Every
    other SHACL form -- a node constraint on the branch itself, a property path
    expression, a second constraint kind -- stays with the engine, because this
    is the only form the precheck below knows how to evaluate exactly.
    """

    if set(shapes.predicates(branch, None)) - {SH.property}:
        return None
    rows: set[tuple[Any, Any, int | None, int | None]] = set()
    for property_shape in shapes.objects(branch, SH.property):
        if set(shapes.predicates(property_shape, None)) - {
            SH.path,
            SH.hasValue,
            SH.minCount,
            SH.maxCount,
        }:
            return None
        paths = list(shapes.objects(property_shape, SH.path))
        values = list(shapes.objects(property_shape, SH.hasValue))
        minimums = list(shapes.objects(property_shape, SH.minCount))
        maximums = list(shapes.objects(property_shape, SH.maxCount))
        if len(paths) != 1 or not isinstance(paths[0], URIRef):
            return None
        if len(values) > 1 or len(minimums) > 1 or len(maximums) > 1:
            return None
        rows.add(
            (
                paths[0],
                values[0] if values else None,
                int(minimums[0]) if minimums else None,
                int(maximums[0]) if maximums else None,
            )
        )
    return frozenset(rows) if rows else None


def _evidence_warrant_branch_table(
    shapes: Graph,
) -> tuple[frozenset[tuple[Any, Any, int | None, int | None]], ...] | None:
    """Read the warrant `sh:xone` off the shapes graph, or refuse to lift it.

    Measured 2026-08-12 (`plans/validation-cost-reset-plan.md`, "Inside-the-
    phases trace"): ~67% of the SHACL phase of a 62-minute acceptance run --
    about 21 minutes -- was this one constraint evaluated by engine trial. Six
    branches are dispatched per evidence binding, five of them fail by design,
    and each failure mints a pretty-printed validation report the engine then
    discards. The guarantee behind all of that is a six-entry table, so it is
    lifted into the batched prechecks the way the relation ring context is.

    Verified here, from the shapes graph, before anything is lifted: exactly
    one `sh:xone` on atlas:EvidenceBindingShape; every member parses into the
    restricted `(path, hasValue, minCount, maxCount)` form above; and the set
    of parsed branch signatures is *exactly* the pinned six, with six members
    (so a duplicated branch cannot pass by set equality). The returned table is
    the parsed one -- the precheck evaluates the shapes' own conditions, not a
    second Python copy of the warrant semantics.
    """

    heads = list(shapes.objects(ATLAS.EvidenceBindingShape, SH.xone))
    if len(heads) != 1:
        return None
    branches = [_warrant_branch_signature(shapes, branch) for branch in shapes.items(heads[0])]
    if any(branch is None for branch in branches):
        return None
    if len(branches) != len(_EVIDENCE_WARRANT_BRANCH_SIGNATURES):
        return None
    if frozenset(branches) != _EVIDENCE_WARRANT_BRANCH_SIGNATURES:
        return None
    return tuple(branches)  # type: ignore[arg-type]


@lru_cache(maxsize=1)
def evidence_warrant_axis_values() -> Mapping[str, Mapping[URIRef, URIRef]]:
    """Warrant name -> the evidence axes that warrant's `sh:xone` branch pins.

    THE warrant table. It is read off atlas:EvidenceBindingShape rather than
    restated in Python, because a second statement of it is a second thing to
    drift: the Python copy this replaced pinned `rkaf:attestorKind` on all six
    warrants while the shapes pinned it on one, and nothing failed.

    What comes back is only what the shapes PIN. Five of the six branches say
    nothing about `rkaf:attestorKind`, so five entries carry three axes and
    humanReview carries four -- and the axis is still closed, by that shape's
    own `sh:in` over the nine #AttestorKind values. `evidence_warrant_facts`
    adds the kind a producer mints; enforcement uses this table alone, so the
    validator constrains exactly what the binding constrains.

    The binding files are immutable for the life of a process, so this is
    derived once. A shapes graph that no longer carries the sanctioned branch
    table, or whose branches are not one per named warrant, fails here rather
    than silently admitting a combination no warrant sanctions.
    """

    branches = _evidence_warrant_branch_table(_parse_binding_graphs()[1])
    if branches is None:
        _fail(
            "shacl.meta",
            "atlas:EvidenceBindingShape does not carry the sanctioned warrant sh:xone",
        )
    table: dict[str, Mapping[URIRef, URIRef]] = {}
    for branch in branches:
        pinned = {
            path: value
            for path, value, _minimum, _maximum in branch
            if value is not None and path in EVIDENCE_WARRANT_AXES
        }
        name = EVIDENCE_WARRANT_NAMES.get(pinned.get(RKAF.evidenceRole))  # type: ignore[arg-type]
        if name is None or name in table:
            _fail(
                "shacl.meta",
                "the warrant sh:xone branches are not one per named review warrant",
            )
        table[name] = MappingProxyType(pinned)
    if set(table) != set(EVIDENCE_WARRANT_ATTESTOR_KINDS):
        _fail("shacl.meta", "the warrant sh:xone does not carry every named review warrant")
    return MappingProxyType(table)


def evidence_warrant_facts(warrant: str) -> tuple[tuple[URIRef, URIRef], ...]:
    """The four axis facts one evidence binding minted under `warrant` carries.

    The shapes' pinned axes plus the `rkaf:attestorKind` this producer mints
    for the axis they leave open. When the shapes DO pin the kind -- they do,
    for humanReview -- the two must agree, and disagreeing fails here rather
    than at the engine after a build.
    """

    pinned = evidence_warrant_axis_values()[warrant]
    kind = EVIDENCE_WARRANT_ATTESTOR_KINDS[warrant]
    if pinned.get(RKAF.attestorKind, kind) != kind:
        _fail("shacl.meta", f"{warrant} pins an attestorKind this producer does not mint")
    facts = {**pinned, RKAF.attestorKind: kind}
    return tuple((axis, facts[axis]) for axis in EVIDENCE_WARRANT_AXES)


def declared_evidence_warrants(values: Mapping[URIRef, Any]) -> list[str]:
    """Every sanctioned warrant whose pinned axes one binding's values satisfy.

    Exactly one, for a binding the shapes admit: every branch pins a distinct
    `rkaf:evidenceRole` and the shape allows one value for it, so the roles
    partition the table. An empty list is a combination no warrant sanctions.
    """

    return sorted(
        name
        for name, pinned in evidence_warrant_axis_values().items()
        if all(values.get(axis) == value for axis, value in pinned.items())
    )


def _warrant_branch_holds(
    values: Mapping[Any, AbstractSet[Any]],
    branch: AbstractSet[tuple[Any, Any, int | None, int | None]],
) -> bool:
    """Evaluate one parsed branch against a focus node's value sets.

    SHACL semantics for the three constraints this form admits, and nothing
    else: `sh:hasValue` holds when the value set contains that node,
    `sh:minCount`/`sh:maxCount` bound the number of distinct value nodes.
    """

    for path, has_value, minimum, maximum in branch:
        node_values = values[path]
        if has_value is not None and has_value not in node_values:
            return False
        if minimum is not None and len(node_values) < minimum:
            return False
        if maximum is not None and len(node_values) > maximum:
            return False
    return True


def _batched_shacl_plan(shapes: Graph) -> _BatchedShaclPlan:
    """Build a valid-data execution graph without changing normative shapes.

    pySHACL 0.31 evaluates every ``sh:property`` shape once per focus node.
    Atlas property constraints are direct children of targeted node shapes, so
    targeting those property shapes directly preserves conformance while
    batching all focus nodes into one constraint evaluation. Closed-shape
    checks and the two high-volume `sh:xone` guarantees -- the relation ring
    context and the evidence warrant -- are lifted into the prechecks below,
    each only after the shapes graph is proved to still carry the exact
    signature the lift was written against. Any failure falls back to the
    untouched shapes for the original report.
    """

    execution = _copy_graph(shapes)
    referenced = _referenced_shapes(shapes)
    closed_plans: list[_ClosedShapePlan] = []
    targeted_shapes = {
        subject
        for predicate in _SHACL_TARGET_PREDICATES
        for subject in shapes.subjects(predicate, None)
    }
    for shape in targeted_shapes:
        property_shapes = list(shapes.objects(shape, SH.property))
        if (
            not property_shapes
            or shape in referenced
            or list(shapes.objects(shape, SH.path))
            or (shape, RDF.type, SH.NodeShape) not in shapes
        ):
            continue
        targets = [
            (predicate, obj)
            for predicate in _SHACL_TARGET_PREDICATES
            for obj in shapes.objects(shape, predicate)
        ]
        for property_shape in property_shapes:
            for predicate, obj in targets:
                execution.add((property_shape, predicate, obj))
            execution.remove((shape, SH.property, property_shape))

        closed_plan = _closed_shape_plan(shapes, shape, property_shapes)
        if closed_plan is not None:
            closed_plans.append(closed_plan)
            execution.remove((shape, SH.closed, None))
            execution.remove((shape, SH.ignoredProperties, None))

    for property_shape, value_shape in list(execution.subject_objects(SH.node)):
        if value_shape not in _INLINE_VALUE_SHAPES:
            continue
        value_predicates = set(shapes.predicates(value_shape, None))
        supported_predicates = {RDF.type, SH.message, *_INLINE_VALUE_CONSTRAINTS}
        if value_predicates - supported_predicates:
            continue
        for predicate, obj in shapes.predicate_objects(value_shape):
            if predicate in _INLINE_VALUE_CONSTRAINTS:
                execution.add((property_shape, predicate, obj))
        execution.remove((property_shape, SH.node, value_shape))

    checks_relation_ring_context = _can_lift_relation_ring_context(shapes)
    if checks_relation_ring_context:
        execution.remove((ATLAS.RelationAssertionShape, SH.xone, None))

    warrant_branches = _evidence_warrant_branch_table(shapes)
    if warrant_branches is not None:
        execution.remove((ATLAS.EvidenceBindingShape, SH.xone, None))

    return _BatchedShaclPlan(
        shapes=execution,
        closed_shapes=tuple(sorted(closed_plans, key=lambda plan: str(plan.shape))),
        checks_relation_ring_context=checks_relation_ring_context,
        warrant_branches=warrant_branches,
    )


def _core_shacl_targets(data_graph: Graph, shapes: Graph, shape: Any) -> set[Any]:
    """Resolve the four SHACL Core target forms used by the Atlas shapes."""

    targets = set(shapes.objects(shape, SH.targetNode))
    for target_class in shapes.objects(shape, SH.targetClass):
        targets.update(data_graph.subjects(RDF.type, target_class))
        for subclass in data_graph.transitive_subjects(RDFS.subClassOf, target_class):
            if subclass != target_class:
                targets.update(data_graph.subjects(RDF.type, subclass))
    for predicate in shapes.objects(shape, SH.targetSubjectsOf):
        targets.update(data_graph.subjects(predicate, None))
    for predicate in shapes.objects(shape, SH.targetObjectsOf):
        targets.update(data_graph.objects(None, predicate))
    return targets


def _batched_shacl_precheck_misses(
    data_graph: Graph,
    normative_shapes: Graph,
    plan: _BatchedShaclPlan,
    *,
    first_only: bool,
) -> list[Any]:
    """Return one focus node per lifted constraint that the fast path refuses.

    Each lifted constraint (one closed shape, the relation ring context, or
    the evidence warrant) can only ever produce its own constraint component,
    so one violating focus node per lifted constraint is enough to reproduce
    that component under the normative shapes.  `first_only` stops at the
    first miss for the plain conformance question, which is all the audit path
    needs.
    """

    misses: list[Any] = []
    for closed in plan.closed_shapes:
        miss: Any = None
        for focus in _core_shacl_targets(data_graph, normative_shapes, closed.shape):
            if any(
                (predicate, obj) != (RDF.type, RDFS.Resource)
                and predicate not in closed.ignored_paths
                and predicate not in closed.allowed_paths
                for predicate, obj in data_graph.predicate_objects(focus)
            ):
                if first_only:
                    return [focus]
                # Keep the lexicographically least violating node so the
                # red-path sample -- and the report built from it -- is
                # stable across runs; set iteration order is not.
                if miss is None or str(focus) < str(miss):
                    miss = focus
        if miss is not None:
            misses.append(miss)

    if plan.checks_relation_ring_context:
        miss = None
        for focus in _core_shacl_targets(data_graph, normative_shapes, ATLAS.RelationAssertionShape):
            semantic_count = sum(1 for _ in data_graph.objects(focus, ATLAS.semanticRing))
            source_count = sum(1 for _ in data_graph.objects(focus, ATLAS.sourceRing))
            target_count = sum(1 for _ in data_graph.objects(focus, ATLAS.targetRing))
            same_ring = semantic_count >= 1 and source_count == 0 and target_count == 0
            cross_ring = semantic_count == 0 and source_count >= 1 and target_count >= 1
            if same_ring == cross_ring:
                if first_only:
                    return [focus]
                if miss is None or str(focus) < str(miss):
                    miss = focus
        if miss is not None:
            misses.append(miss)

    if plan.warrant_branches is not None:
        # One indexed read per constrained path per binding, then the parsed
        # table decides. `sh:xone` conforms for exactly one satisfied branch,
        # so both zero and two are misses and both hand the same
        # XoneConstraintComponent back through focused re-validation.
        warrant_paths = tuple({row[0] for branch in plan.warrant_branches for row in branch})
        miss = None
        for focus in _core_shacl_targets(data_graph, normative_shapes, ATLAS.EvidenceBindingShape):
            values = {path: set(data_graph.objects(focus, path)) for path in warrant_paths}
            matched = 0
            for branch in plan.warrant_branches:
                if _warrant_branch_holds(values, branch):
                    matched += 1
                    if matched > 1:
                        break
            if matched != 1:
                if first_only:
                    return [focus]
                if miss is None or str(focus) < str(miss):
                    miss = focus
        if miss is not None:
            misses.append(miss)
    return misses


def _batched_shacl_prechecks(data_graph: Graph, normative_shapes: Graph, plan: _BatchedShaclPlan) -> bool:
    """Return false when a lifted constraint needs the original SHACL report."""

    return not _batched_shacl_precheck_misses(
        data_graph,
        normative_shapes,
        plan,
        first_only=True,
    )


def _validate_shacl_data(data_graph: Graph, shapes: Graph) -> tuple[bool, Any, str]:
    return shacl_validate(
        data_graph,
        shacl_graph=shapes,
        inference="none",
        inplace=True,
        advanced=False,
        abort_on_first=False,
        allow_infos=False,
        allow_warnings=False,
        meta_shacl=False,
    )


def _shacl_focus_samples(precheck_misses: Sequence[Any], report: Any) -> list[URIRef] | None:
    """Name focus nodes that reproduce every violation the fast path found.

    The fast path knows more than "no". Its precheck misses arrive as focus
    nodes already, and its batched report carries one `sh:focusNode` per
    violation. Two violations of the same `(sourceShape, component, path)` can
    only ever produce the same constraint component, so one focus node per
    distinct signature reproduces the whole component list -- 2,003 identical
    evidence-binding violations become one node to re-validate.

    Returns None whenever the sample cannot be trusted to be complete or
    usable, which sends the caller back to the whole-graph normative report.
    """

    sampled: list[Any] = list(precheck_misses)
    if isinstance(report, Graph):
        by_signature: dict[tuple[str, str], Any] = {}
        for result in report.subjects(RDF.type, SH.ValidationResult):
            focus = next(report.objects(result, SH.focusNode), None)
            component = next(report.objects(result, SH.sourceConstraintComponent), None)
            if focus is None or component is None:
                return None
            signature = (
                str(next(report.objects(result, SH.resultPath), "")),
                str(component),
            )
            # Keep the lexicographically least focus node per signature so
            # the red-path sample is run-stable (graph iteration order is
            # not). The signature is `(resultPath, component)` and NOT
            # `sh:sourceShape`: an engine may leave the source shape an
            # anonymous node -- Jena does -- and a sample keyed on a blank
            # node id would be stable for one processor only. Nothing is lost
            # by dropping it, because the component the sample exists to
            # reproduce is still part of the key; `_root_shape_focus_groups`
            # then re-derives every shape that targets the sampled node from
            # the shapes graph, not from the report.
            previous = by_signature.get(signature)
            if previous is None or str(focus) < str(previous):
                by_signature[signature] = focus
        # Emitted in the canonical report order, `(focusNode, resultPath,
        # component)`. The focus node is carried as the term the report named,
        # never re-minted from its string: a non-IRI focus must stay non-IRI so
        # the guard below still sends it back to the whole-graph run.
        sampled.extend(
            focus
            for _key, focus in sorted(
                (
                    ((str(focus), path, component), focus)
                    for (path, component), focus in by_signature.items()
                ),
                key=lambda row: row[0],
            )
        )

    if not sampled or len(sampled) > SHACL_FOCUS_SAMPLE_LIMIT:
        return None
    unique: list[URIRef] = []
    seen: set[Any] = set()
    for focus in sampled:
        # pySHACL resolves anything else through its CURIE expander, which
        # would hand the engine a different node than the one that failed.
        if not isinstance(focus, URIRef) or not str(focus).lower().startswith(_FOCUS_NODE_SCHEMES):
            return None
        if focus not in seen:
            seen.add(focus)
            unique.append(focus)
    return unique


def _report_violations(report: Any) -> list[tuple[str, str, str]]:
    """Every violation a SHACL report graph carries, canonically ordered.

    `(focusNode, resultPath, sourceConstraintComponent)`, sorted -- the
    report-canonicalization rule from the engine comparison
    (`plans/validation-cost-reset-plan.md`), and the reason this reads the
    report GRAPH pySHACL already returns rather than regexing its text
    rendering. The text rendering is one processor's presentation choice;
    `sh:sourceConstraintComponent` is the SHACL specification's own answer to
    "which constraint failed", so it is what an engine swap can be held to.

    `sh:sourceShape` is deliberately not in the key: Jena leaves it an
    anonymous node, so ordering by it is only stable for one engine. Nothing
    here digests the report -- a report graph is a diagnosis, never an
    identity.
    """

    if not isinstance(report, Graph):
        return []
    violations: set[tuple[str, str, str]] = set()
    for result in report.subjects(RDF.type, SH.ValidationResult):
        component = next(report.objects(result, SH.sourceConstraintComponent), None)
        if component is None:
            continue
        violations.add(
            (
                str(next(report.objects(result, SH.focusNode), "")),
                str(next(report.objects(result, SH.resultPath), "")),
                str(component).rpartition("#")[2] or str(component),
            )
        )
    return sorted(violations)


def _root_shape_focus_groups(
    data_graph: Graph,
    shapes: Graph,
    focus_nodes: Sequence[URIRef],
) -> dict[URIRef, list[URIRef]] | None:
    """Group sampled focus nodes under the normative shapes that target them.

    This is `_core_shacl_targets` read backwards: instead of resolving one
    shape's targets over the whole graph, it asks of one node which shapes
    target it, which costs a handful of indexed lookups per node instead of a
    scan per shape. Returns None if any node is targeted by nothing, because
    that would mean this resolution and the engine's disagree.

    Invariant this rides on: resolution reads the four SHACL Core target
    predicates only, which is complete for today's shapes file (39
    `sh:targetClass`, 1 `sh:targetObjectsOf`; no implicit class targets, no
    `sh:sparql`, no `sh:deactivated`). A shape acquiring any other target
    form must extend this resolution -- a node targeted by *nothing* falls
    back to the whole-graph run, but a node this resolution groups under
    only *some* of its targeting shapes would silently shrink the component
    list, which is contractual.
    """

    targeting: dict[URIRef, dict[Any, list[URIRef]]] = {
        predicate: defaultdict(list) for predicate in _SHACL_TARGET_PREDICATES
    }
    for predicate in _SHACL_TARGET_PREDICATES:
        for shape, value in shapes.subject_objects(predicate):
            if not isinstance(shape, URIRef):
                return None
            targeting[predicate][value].append(shape)

    groups: dict[URIRef, list[URIRef]] = defaultdict(list)
    for focus in focus_nodes:
        matched: set[URIRef] = set(targeting[SH.targetNode].get(focus, ()))
        for node_type in data_graph.objects(focus, RDF.type):
            for target_class in data_graph.transitive_objects(node_type, RDFS.subClassOf):
                matched.update(targeting[SH.targetClass].get(target_class, ()))
        for predicate, shapes_of in targeting[SH.targetSubjectsOf].items():
            if next(data_graph.objects(focus, predicate), None) is not None:
                matched.update(shapes_of)
        for predicate, shapes_of in targeting[SH.targetObjectsOf].items():
            if next(data_graph.subjects(predicate, focus), None) is not None:
                matched.update(shapes_of)
        if not matched:
            return None
        for shape in matched:
            groups[shape].append(focus)
    return groups


def _focused_shacl_report(
    data_graph: Graph,
    shapes: Graph,
    focus_nodes: Sequence[URIRef],
) -> tuple[str, list[tuple[str, str, str]]] | None:
    """Report the sampled focus nodes under the unmodified normative shapes.

    pySHACL's `use_shapes` plus `focus_nodes` skips target resolution
    entirely: each named shape is evaluated against exactly the sampled nodes
    it targets, over the same full data graph, so every value-side constraint
    (`sh:class`, sequence paths, inverse paths) still sees the whole
    distribution and the components are the engine's own. Returns None when
    nothing was reproduced, which sends the caller back to the whole-graph run.

    One report is assembled from several runs, so the assembly needs an order.
    It is the canonical one -- each run's least
    `(focusNode, resultPath, component)` -- rather than the shape IRI it used
    to be. The shape IRIs here are the binding's own and would have been
    stable, but ordering a report by a shape identity is the habit the engine
    comparison ruled out, and this is the only place the validator had one.
    """

    groups = _root_shape_focus_groups(data_graph, shapes, focus_nodes)
    if not groups:
        return None
    reports: list[tuple[tuple[str, str, str], str, list[tuple[str, str, str]]]] = []
    for shape in sorted(groups, key=str):
        try:
            conforms, results, report = shacl_validate(
                data_graph,
                shacl_graph=shapes,
                use_shapes=[shape],
                focus_nodes=groups[shape],
                inference="none",
                inplace=True,
                advanced=False,
                abort_on_first=False,
                allow_infos=False,
                allow_warnings=False,
                meta_shacl=False,
            )
        except Exception:  # noqa: BLE001 - fall back to the whole-graph report
            return None
        if conforms:
            continue
        violations = _report_violations(results)
        if not violations:
            return None
        reports.append((violations[0], " ".join(str(report).split()), violations))
    if not reports:
        return None
    reports.sort(key=lambda row: row[0])
    return (
        " ".join(row[1] for row in reports),
        sorted({violation for row in reports for violation in row[2]}),
    )


@lru_cache(maxsize=1)
def _prove_shape_graph_conforms(ontology_digest: str, shapes_digest: str) -> None:
    """Prove the shape graph is well-formed SHACL and the ontology conforms to it.

    This asks a question about two immutable binding files -- `atlas.ttl` and
    `atlas.shacl.ttl` -- and nothing else. It is a property of the binding, not
    of any distribution being validated, so it is derived once per process
    instead of once per distribution.

    That distinction is not a micro-optimization. Measured on this binding, the
    meta-conformance derivation costs ~1.880s while the data conformance it
    used to accompany costs ~0.070s, so validating the 110-case corpus spent
    roughly 170s of its ~204s re-deriving one unchanging fact 110 times.

    Nothing is trusted that was not proven. The cache key is the pair of file
    digests, recomputed from disk by the caller on every call, so editing
    either file re-derives instead of reusing the proof. `_fail` raises, and
    `lru_cache` never stores a result for a call that raised, so a shape graph
    that does not conform is re-derived and re-refused every single time --
    the failure can never be cached as a pass.
    """

    ontology, shapes = _parse_binding_graphs()
    ontology_view = inoculate(Graph(), ontology)
    try:
        meta_view = _ShaclDataView([Graph(), ontology_view])
        meta_conforms, _, meta_report = shacl_validate(
            meta_view,
            shacl_graph=shapes,
            inference="none",
            inplace=True,
            advanced=False,
            abort_on_first=False,
            allow_infos=False,
            allow_warnings=False,
            meta_shacl=True,
        )
    except Exception as exc:  # noqa: BLE001 - normalize SHACL processor failures
        _fail("shacl.meta", f"SHACL processor failed for asserted: {exc}")
    if not meta_conforms:
        compact = " ".join(str(meta_report).split())
        _fail("shacl.meta", f"shape graph does not conform: {compact[:900]}")


def _run_shacl(graphs: Mapping[str, Graph], ontology: Graph, shapes: Graph) -> None:
    """Validate authoritative inputs; exact regeneration validates the projection.

    Red builds fail fast. Measured on a 32M-quad non-conforming distribution
    (2026-08-11, `plans/validation-cost-reset-plan.md`), the batched fast path
    detected the miss in minutes and the whole-graph normative run then took
    **94 minutes solely to phrase the failure report** -- 78% of a two-hour
    run, on the path a developer iterates on. So the default red path
    re-validates only the focus nodes the fast path already named, under the
    unmodified normative shapes over the unmodified data graph
    (`_focused_shacl_report`): the same engine, the same constraint
    components, seconds instead of hours.

    `REFSPEC_ATLAS_VALIDATION_MODE=audit` restores the whole-graph normative
    run -- read once, here, so one distribution is never validated half in
    each mode. Anything else, including unset, fails fast. The failure code is
    `shacl.data` and the message names every violated constraint component in
    both modes; the focused path only narrows which nodes the engine is asked
    about, and falls back to the whole-graph report whenever the sample cannot
    be trusted to reproduce the same components.
    """

    _prove_shape_graph_conforms(file_sha256(ONTOLOGY_PATH), file_sha256(SHAPES_PATH))

    audit = os.environ.get(VALIDATION_MODE_ENV) == AUDIT_VALIDATION_MODE
    ontology_view = inoculate(Graph(), ontology)
    plan = _batched_shacl_plan(shapes)
    for role in ("asserted", "derived"):
        validation_view = _ShaclDataView([graphs[role], ontology_view])
        for prefix, namespace in ontology.namespaces():
            validation_view.namespace_manager.bind(prefix, namespace)
        conforms = False
        report: Any = ""
        focus_samples: list[URIRef] | None = None
        try:
            if audit:
                if _batched_shacl_prechecks(validation_view, shapes, plan):
                    conforms, _, report = _validate_shacl_data(validation_view, plan.shapes)
            else:
                # Both halves of the fast path run before reporting: the
                # prechecks answer for the lifted closed, ring-context and
                # warrant constraints, the batched shapes answer for every
                # other one, and only their union is a complete sample of what
                # failed.
                misses = _batched_shacl_precheck_misses(
                    validation_view,
                    shapes,
                    plan,
                    first_only=False,
                )
                conforms, results, report = _validate_shacl_data(validation_view, plan.shapes)
                conforms = conforms and not misses
                if not conforms:
                    focus_samples = _shacl_focus_samples(misses, results)
        except Exception as exc:  # noqa: BLE001 - normalize SHACL processor failures
            conforms = False
            report = str(exc)
            focus_samples = None
        if conforms:
            continue

        focused = _focused_shacl_report(validation_view, shapes, focus_samples) if focus_samples else None
        if focused is None:
            # Keep the normative processor's exact report and error behavior
            # for audit mode, for every unsupported fast-path condition, and
            # for any sample the focused run could not reproduce.
            try:
                conforms, results, report = _validate_shacl_data(validation_view, shapes)
            except Exception as exc:  # noqa: BLE001 - normalize SHACL processor failures
                _fail("shacl.data", f"SHACL processor failed for {role}: {exc}")
            if conforms:
                continue
            compact = " ".join(str(report).split())
            violations = _report_violations(results)
        else:
            compact, violations = focused
        # Name every violated constraint component before the detail. A
        # multi-violation report runs past the length cap below, so which
        # constraint actually fired used to depend on graph iteration order
        # -- unreadable for an operator and unpinnable for a regression
        # test. The component list is short, complete, and order-stable, and
        # it is read off the report GRAPH's `sh:sourceConstraintComponent`
        # rather than scraped from one processor's text rendering.
        components = ", ".join(sorted({component for _focus, _path, component in violations}))
        hint = (
            ""
            if audit
            else " (rerun with REFSPEC_ATLAS_VALIDATION_MODE=audit for the whole-graph normative report)"
        )
        _fail(
            "shacl.data",
            f"{role} graph does not conform [{components}]: {compact[:900]}{hint}",
        )


def _check_graph_roles(
    graphs: Mapping[str, Graph],
    *,
    asserted_placement: _AssertedPlacementObservation | None = None,
) -> SemanticInventory:
    asserted = graphs["asserted"]
    projection = graphs["projection"]
    derived = graphs["derived"]
    projection_only_predicates = _projection_only_predicates()
    mutable_carriers: dict[URIRef, set[URIRef]] = {
        carrier_type: set() for carrier_type in ASSERTED_CARRIER_TYPES
    }
    # The predicate scan and the subject/type collection are the parser's, when
    # the parser ran here; otherwise they are taken now, off the same quads.
    placement = asserted_placement
    if placement is None or placement.consumed or placement.graph_id != asserted.identifier:
        placement = _AssertedPlacementObservation.from_graph(asserted)

    if placement.first_violation is not None:
        verdict, subject, predicate = placement.first_violation
        if verdict == _PLACEMENT_PROJECTED:
            _fail("dataset.graph-placement", f"bare projected predicate {predicate} occurs in asserted graph")
        _fail("dataset.graph-placement", f"unsupported asserted predicate {predicate} on {subject}")
    # Drained rather than iterated, as the subject set it replaces was: the map
    # carries one entry per asserted subject, and at full scale that is the
    # largest thing this check holds.
    asserted_types = placement.consume_types()
    while asserted_types:
        subject, declared_types = asserted_types.popitem()
        types = set(declared_types)
        unsupported_types = types - ALLOWED_ASSERTED_TYPES
        if unsupported_types:
            _fail(
                "dataset.graph-placement",
                f"asserted subject {subject} has unsupported type {min(unsupported_types, key=str)}",
            )
        carrier_types = types & ASSERTED_CARRIER_TYPES
        if len(carrier_types) != 1:
            _fail(
                "dataset.graph-placement",
                f"asserted subject {subject} must have exactly one concrete Atlas carrier type",
            )
        carrier_type = next(iter(carrier_types))
        mutable_carriers[carrier_type].add(subject)
        expected_types = {carrier_type}
        if carrier_type in RESOURCE_TYPES:
            expected_types.add(ATLAS.AtlasResource)
            if carrier_type == ATLAS.SubjectConcept or (carrier_type == ATLAS.ValueResource and SKOS.Concept in types):
                expected_types.add(SKOS.Concept)
        elif carrier_type == ATLAS.ResourceScheme:
            if set(asserted.objects(subject, ATLAS.resourceProfile)) == {ATLAS.conceptScheme} or any(
                asserted.subjects(SKOS.inScheme, subject)
            ):
                expected_types.add(SKOS.ConceptScheme)
        elif carrier_type == ATLAS.RegistrySource:
            pass
        elif carrier_type in ASSERTION_TYPES:
            expected_types.add(ATLAS.RelationAssertion)
            if carrier_type == ATLAS.MappingAssertion and set(asserted.objects(subject, ATLAS.semanticRing)) == {
                ATLAS.subject
            }:
                expected_types.add(ATLAS.SkosMappingAssertion)
        if types != expected_types:
            _fail(
                "dataset.graph-placement",
                f"asserted subject {subject} type set differs from its concrete carrier",
            )
        if ATLAS.ProjectedRelation in types or ATLAS.DerivedRelation in types:
            _fail("dataset.graph-placement", f"{subject} has a non-asserted carrier type in the asserted graph")

    derived_nodes = set(derived.subjects(RDF.type, ATLAS.DerivedRelation))
    for subject in derived_nodes:
        if set(derived.objects(subject, RDF.type)) != {ATLAS.DerivedRelation}:
            _fail("dataset.graph-placement", f"derived subject {subject} has an extra carrier type")
    for subject, predicate, _ in derived:
        if subject not in derived_nodes:
            _fail("dataset.graph-placement", f"derived graph has non-DerivedRelation subject {subject}")
        if predicate in projection_only_predicates:
            _fail("dataset.graph-placement", f"bare projected predicate {predicate} occurs in derived graph")

    asserted_by_carrier = mutable_carriers
    projection_nodes = set(projection.subjects(RDF.type, ATLAS.ProjectedRelation))
    for label, nodes in (
        ("asserted/projection", projection_nodes),
        ("asserted/derived", derived_nodes),
    ):
        overlap = min(
            (
                node
                for node in nodes
                if any(node in carrier_nodes for carrier_nodes in asserted_by_carrier.values())
            ),
            key=str,
            default=None,
        )
        if overlap is not None:
            _fail("dataset.graph-placement", f"record identity crosses {label} roles: {overlap}")
    projection_derived_overlap = projection_nodes & derived_nodes
    if projection_derived_overlap:
        _fail(
            "dataset.graph-placement",
            "record identity crosses projection/derived roles: "
            f"{min(projection_derived_overlap, key=str)}",
        )
    return SemanticInventory(
        asserted_by_carrier=asserted_by_carrier,
        derived_nodes=derived_nodes,
        projection_nodes=projection_nodes,
        facts=placement.facts,
    )


def _semantic_inventory_from_graphs(graphs: Mapping[str, Graph]) -> SemanticInventory:
    """Build an inventory for direct helper calls that did not run placement first."""

    asserted = graphs["asserted"]
    asserted_by_carrier = {
        carrier_type: frozenset(
            node
            for node in asserted.subjects(RDF.type, carrier_type)
            if isinstance(node, URIRef)
        )
        for carrier_type in ASSERTED_CARRIER_TYPES
    }
    return SemanticInventory(
        asserted_by_carrier=asserted_by_carrier,
        derived_nodes=frozenset(graphs["derived"].subjects(RDF.type, ATLAS.DerivedRelation)),
        projection_nodes=frozenset(
            graphs["projection"].subjects(RDF.type, ATLAS.ProjectedRelation)
        ),
    )


def _carrier_nodes(
    asserted: Graph,
    carrier_type: URIRef,
    inventory: SemanticInventory | None,
) -> AbstractSet[URIRef]:
    if inventory is not None:
        return inventory.nodes(carrier_type)
    return frozenset(
        node
        for node in asserted.subjects(RDF.type, carrier_type)
        if isinstance(node, URIRef)
    )


def _resource_nodes(
    asserted: Graph,
    inventory: SemanticInventory | None,
) -> Iterable[URIRef]:
    if inventory is not None:
        return inventory.resources()
    return (
        node
        for resource_type in RESOURCE_TYPES
        for node in _carrier_nodes(asserted, resource_type, None)
    )


def _is_resource_node(
    asserted: Graph,
    node: Any,
    inventory: SemanticInventory | None,
) -> bool:
    if inventory is not None:
        return inventory.is_resource(node)
    return any((node, RDF.type, resource_type) in asserted for resource_type in RESOURCE_TYPES)


def _has_carrier_type(
    asserted: Graph,
    node: Any,
    carrier_type: URIRef,
    inventory: SemanticInventory | None,
) -> bool:
    """Whether one node declares a concrete carrier type, inventory-first."""

    if inventory is not None:
        return node in inventory.nodes(carrier_type)
    return (node, RDF.type, carrier_type) in asserted


def _asserted_facts(
    asserted: Graph,
    inventory: SemanticInventory | None,
) -> _AssertedFacts:
    """The parse-observed read index for this graph, or the graph itself.

    The guard on `graph_id` is what keeps an index from answering for a graph
    it did not observe: a helper called with a different graph and a stale
    inventory reads the store, as it always did.
    """

    if inventory is not None:
        facts = inventory.facts
        if facts is not None and facts.graph_id == asserted.identifier:
            return facts
    return _AssertedFacts.for_graph(asserted)


def _profile_policy_document() -> Mapping[str, Any]:
    profile_map = _load_json(PROFILE_MAP_PATH, require_canonical=True)
    expected_keys = {
        "crossRingRelationPolicies",
        "format",
        "namespace",
        "profileDigest",
        "profiles",
        "relationPolicies",
        "schemaVersion",
    }
    if not isinstance(profile_map, Mapping) or set(profile_map) != expected_keys:
        _fail("profile.policy", "profile policy fields are incomplete or unknown")
    if profile_map.get("format") != "refspec-atlas-registry-resource-profiles/3.1":
        _fail("profile.policy", "profile policy format is not Atlas 3.1")
    if profile_map.get("namespace") != str(ATLAS):
        _fail("profile.policy", "profile policy namespace is not the Atlas 3.1 namespace")
    if profile_map.get("schemaVersion") != "3.1":
        _fail("profile.policy", "profile policy schemaVersion is not 3.1")
    expected_digest = canonical_sha256(
        {key: value for key, value in profile_map.items() if key != "profileDigest"},
        terminal_lf=False,
    )
    if profile_map.get("profileDigest") != expected_digest:
        _fail("profile.policy", "profileDigest does not match the canonical profile policy")
    return profile_map


def _profile_policies() -> dict[URIRef, Mapping[str, Any]]:
    profile_map = _profile_policy_document()
    policies: dict[URIRef, Mapping[str, Any]] = {}
    rows = profile_map.get("profiles")
    if not isinstance(rows, list):
        _fail("profile.policy", "profiles must be a list")
    observed_names: list[str] = []
    for position, row in enumerate(rows):
        location = f"profiles[{position}]"
        if not isinstance(row, Mapping) or set(row) != {
            "applicableEntryClasses",
            "applicableSemanticRings",
            "descriptorBehavior",
            "profile",
            "resourceKinds",
        }:
            _fail("profile.policy", f"{location} fields are incomplete or unknown")
        name = row.get("profile")
        if not isinstance(name, str) or name not in EXPECTED_PROFILE_NAMES:
            _fail("profile.policy", f"{location}.profile is unsupported")
        observed_names.append(name)
        for field, allow_empty in (
            ("applicableEntryClasses", False),
            ("applicableSemanticRings", True),
            ("resourceKinds", False),
        ):
            values = row.get(field)
            if (
                not isinstance(values, list)
                or (not allow_empty and not values)
                or not all(isinstance(value, str) and value for value in values)
                or values != sorted(values)
                or len(values) != len(set(values))
            ):
                _fail("profile.policy", f"{location}.{field} must be a unique sorted string list")
        ring_names = row["applicableSemanticRings"]
        if any(URIRef(str(ATLAS) + value) not in RING_RESOURCE_CLASSES for value in ring_names):
            _fail("profile.policy", f"{location}.applicableSemanticRings contains an unknown ring")
        if any(not ABSOLUTE_IRI_RE.fullmatch(value) for value in row["applicableEntryClasses"]):
            _fail("profile.policy", f"{location}.applicableEntryClasses contains a non-absolute IRI")
        behavior = row.get("descriptorBehavior")
        expected_behavior = (
            "alwaysDescriptorOnly" if name == "resourceCollection" else "descriptorOnlyUntilExactRelease"
        )
        if behavior != expected_behavior or (name == "resourceCollection" and ring_names):
            _fail("profile.policy", f"{location}.descriptorBehavior or rings are inconsistent")
        profile = URIRef(str(ATLAS) + name)
        if profile in policies:
            _fail("profile.policy", f"duplicate profile policy {profile}")
        policies[profile] = row
    if observed_names != sorted(EXPECTED_PROFILE_NAMES):
        _fail("profile.policy", "profiles must contain the five profiles once in sorted order")
    return policies


def _relation_policies() -> dict[URIRef, dict[URIRef, frozenset[URIRef]]]:
    """Load the one canonical ring/type/predicate policy matrix."""

    profile_map = _profile_policy_document()
    rows = profile_map.get("relationPolicies")
    if not isinstance(rows, list) or len(rows) != len(RING_RESOURCE_CLASSES):
        _fail("profile.policy", "relationPolicies must contain exactly four rows")
    expected_ring_names = sorted(str(ring).removeprefix(str(ATLAS)) for ring in RING_RESOURCE_CLASSES)
    observed_ring_names: list[str] = []
    policies: dict[URIRef, dict[URIRef, frozenset[URIRef]]] = {}
    seen_predicates: set[URIRef] = set()
    for position, row in enumerate(rows):
        location = f"relationPolicies[{position}]"
        if not isinstance(row, Mapping) or set(row) != {
            "assertionPredicates",
            "resourceClass",
            "semanticRing",
        }:
            _fail("profile.policy", f"{location} fields are incomplete or unknown")
        ring_name = row.get("semanticRing")
        if not isinstance(ring_name, str):
            _fail("profile.policy", f"{location}.semanticRing must be a string")
        observed_ring_names.append(ring_name)
        ring = URIRef(str(ATLAS) + ring_name)
        expected_resource_class = RING_RESOURCE_CLASSES.get(ring)
        if expected_resource_class is None or row.get("resourceClass") != str(expected_resource_class):
            _fail("profile.policy", f"{location}.resourceClass does not match its ring")
        raw_predicates = row.get("assertionPredicates")
        if not isinstance(raw_predicates, Mapping) or set(raw_predicates) != set(RELATION_POLICY_TYPE_NAMES):
            _fail("profile.policy", f"{location}.assertionPredicates has the wrong type cells")
        ring_policy: dict[URIRef, frozenset[URIRef]] = {}
        for type_name, assertion_type in RELATION_POLICY_TYPE_NAMES.items():
            values = raw_predicates[type_name]
            if (
                not isinstance(values, list)
                or not values
                or not all(isinstance(value, str) and ABSOLUTE_IRI_RE.fullmatch(value) for value in values)
                or values != sorted(values)
                or len(values) != len(set(values))
            ):
                _fail(
                    "profile.policy",
                    f"{location}.{type_name} predicates must be nonempty, unique, sorted absolute IRIs",
                )
            predicates = frozenset(URIRef(value) for value in values)
            allowed_skos = (
                SKOS_MAPPING_PREDICATES
                if assertion_type == ATLAS.MappingAssertion
                else SKOS_NATIVE_RELATION_PREDICATES
                if assertion_type == ATLAS.NativeRelationAssertion
                else frozenset()
            )
            for predicate in predicates:
                if not str(predicate).startswith(str(ATLAS)) and not (
                    ring == ATLAS.subject and predicate in allowed_skos
                ):
                    _fail("profile.policy", f"{location}.{type_name} contains unsupported predicate {predicate}")
            overlap = seen_predicates & predicates
            if overlap:
                _fail(
                    "profile.policy", f"relation predicate occurs in more than one policy cell: {min(overlap, key=str)}"
                )
            seen_predicates.update(predicates)
            ring_policy[assertion_type] = predicates
        policies[ring] = ring_policy
    if observed_ring_names != expected_ring_names or set(policies) != set(RING_RESOURCE_CLASSES):
        _fail("profile.policy", "relationPolicies rings must occur once in sorted order")
    return policies


def _cross_ring_relation_policies() -> dict[tuple[URIRef, URIRef], frozenset[URIRef]]:
    """Load the closed source-ring/target-ring predicate policy matrix."""

    expected = {
        (ATLAS.entity, ATLAS.legalIdentity): frozenset({ATLAS.referencesLegalIdentity}),
        (ATLAS.entity, ATLAS.subject): frozenset({ATLAS.hasIndexedSubject}),
        (ATLAS.legalIdentity, ATLAS.subject): frozenset({ATLAS.hasIndexedSubject}),
    }
    profile_map = _profile_policy_document()
    rows = profile_map.get("crossRingRelationPolicies")
    if not isinstance(rows, list) or len(rows) != 3:
        _fail("profile.policy", "crossRingRelationPolicies must contain exactly three rows")
    observed_pairs: list[tuple[str, str]] = []
    policies: dict[tuple[URIRef, URIRef], frozenset[URIRef]] = {}
    same_ring_predicates = frozenset().union(
        *(predicates for ring_policy in _relation_policies().values() for predicates in ring_policy.values())
    )
    for position, row in enumerate(rows):
        location = f"crossRingRelationPolicies[{position}]"
        if not isinstance(row, Mapping) or set(row) != {
            "predicates",
            "sourceResourceClass",
            "sourceRing",
            "targetResourceClass",
            "targetRing",
        }:
            _fail("profile.policy", f"{location} fields are incomplete or unknown")
        source_name = row.get("sourceRing")
        target_name = row.get("targetRing")
        if not isinstance(source_name, str) or not isinstance(target_name, str):
            _fail("profile.policy", f"{location} rings must be strings")
        observed_pairs.append((source_name, target_name))
        source_ring = URIRef(str(ATLAS) + source_name)
        target_ring = URIRef(str(ATLAS) + target_name)
        source_class = RING_RESOURCE_CLASSES.get(source_ring)
        target_class = RING_RESOURCE_CLASSES.get(target_ring)
        if source_class is None or row.get("sourceResourceClass") != str(source_class):
            _fail("profile.policy", f"{location}.sourceResourceClass does not match its ring")
        if target_class is None or row.get("targetResourceClass") != str(target_class):
            _fail("profile.policy", f"{location}.targetResourceClass does not match its ring")
        if source_ring == target_ring:
            _fail("profile.policy", f"{location} does not cross semantic rings")
        pair = (source_ring, target_ring)
        if pair in policies:
            _fail("profile.policy", f"duplicate cross-ring policy pair {source_name}->{target_name}")
        values = row.get("predicates")
        if (
            not isinstance(values, list)
            or len(values) != 1
            or not all(isinstance(value, str) and ABSOLUTE_IRI_RE.fullmatch(value) for value in values)
            or values != sorted(values)
            or len(values) != len(set(values))
        ):
            _fail(
                "profile.policy",
                f"{location}.predicates must contain one unique sorted absolute IRI",
            )
        predicates = frozenset(URIRef(value) for value in values)
        if any(not str(predicate).startswith(str(ATLAS)) for predicate in predicates):
            _fail("profile.policy", f"{location} contains a non-Atlas cross-ring predicate")
        overlap = predicates & same_ring_predicates
        if overlap:
            _fail(
                "profile.policy",
                f"cross-ring predicate also occurs in a same-ring policy cell: {min(overlap, key=str)}",
            )
        policies[pair] = predicates
    if observed_pairs != sorted(observed_pairs):
        _fail("profile.policy", "crossRingRelationPolicies must be sorted by source and target ring")
    if policies != expected:
        _fail(
            "profile.policy",
            "crossRingRelationPolicies differ from the closed Atlas 3.1 matrix",
        )
    return policies


def _projection_only_predicates() -> frozenset[URIRef]:
    same_ring_predicates = frozenset().union(
        *(predicates for ring_policy in _relation_policies().values() for predicates in ring_policy.values())
    )
    cross_ring_predicates = frozenset().union(*_cross_ring_relation_policies().values())
    return same_ring_predicates | cross_ring_predicates | frozenset({SKOS.prefLabel, SKOS.altLabel, SKOS.hiddenLabel})


def _check_profile_conformance(
    asserted: Graph,
    inventory: SemanticInventory | None = None,
) -> None:
    facts = _asserted_facts(asserted, inventory)
    policies = _profile_policies()
    constraints = {
        profile: (
            frozenset(URIRef(str(ATLAS) + value) for value in policy["applicableSemanticRings"]),
            frozenset(URIRef(value) for value in policy["applicableEntryClasses"]),
        )
        for profile, policy in policies.items()
    }
    for subject_type in (ATLAS.ResourceScheme, ATLAS.AtlasRelease, *RESOURCE_TYPES):
        for subject in _carrier_nodes(asserted, subject_type, inventory):
            profile = _iri(
                facts.one(subject, ATLAS.resourceProfile, code="profile.conformance"),
                code="profile.conformance",
                label="resource profile",
            )
            constraint = constraints.get(profile)
            if constraint is None:
                _fail("profile.conformance", f"{subject} uses unknown profile {profile}")
            allowed_rings, allowed_classes = constraint
            rings = set(facts.objects(subject, ATLAS.semanticRing))
            if rings - allowed_rings:
                _fail("profile.conformance", f"{subject} ring is not allowed by {profile}")
            if subject_type == ATLAS.ResourceScheme:
                if rings:
                    _fail(
                        "profile.conformance",
                        f"{subject} must declare supportedRing, not one singular semanticRing",
                    )
                supported_rings = set(facts.objects(subject, ATLAS.supportedRing))
                if supported_rings - allowed_rings:
                    _fail("profile.conformance", f"{subject} supported ring is not allowed by {profile}")
            if subject_type != ATLAS.ResourceScheme and len(rings) != 1:
                _fail("profile.conformance", f"{subject} must have exactly one allowed semantic ring")
            if subject_type in RESOURCE_TYPES and subject_type not in allowed_classes:
                _fail("profile.conformance", f"{subject_type} is not allowed by {profile}")

    scheme_profiles: dict[URIRef, URIRef] = {}
    for identifier in _carrier_nodes(asserted, ATLAS.Identifier, inventory):
        scheme = _iri(
            facts.one(identifier, ATLAS.identifierScheme, code="profile.conformance"),
            code="profile.conformance",
            label="identifier scheme",
        )
        profile = scheme_profiles.get(scheme)
        if profile is None:
            profile = _iri(
                facts.one(scheme, ATLAS.resourceProfile, code="profile.conformance"),
                code="profile.conformance",
                label="identifier profile",
            )
            scheme_profiles[scheme] = profile
        constraint = constraints.get(profile)
        if constraint is None or ATLAS.Identifier not in constraint[1]:
            _fail("profile.conformance", f"{identifier} is not allowed by {profile}")


def _conflicting_entry_order(entries: AbstractSet[URIRef]) -> list[str]:
    """A total order over conflict groups, used only on a failure path."""

    return sorted(map(str, entries))


def _check_identifier_uniqueness(
    asserted: Graph,
    inventory: SemanticInventory | None = None,
) -> None:
    """Require each authority-scoped identifier pair to name one resource, or a
    published rkaf:RegistryConflict naming exactly the entries that disagree.

    Two atlas:Identifier records claiming one (scheme, value) pair for different
    resources is the one contradiction between registry entries this binding
    detects, and it is exactly what rulespec's #RegistryConflict describes. Both
    halves of the rule below are load-bearing: a contradiction with no record
    still fails the build, as it always has, so nothing collapses silently; and
    a record whose rkaf:conflictingEntries are not precisely the disagreeing
    entries fails too, so the record cannot become a rubber stamp that licenses
    whatever a producer happens to have written. A distribution that publishes
    the matching record is accepted, and the disagreement survives as an
    IRI-addressable record instead of being deleted along with the artifact.

    The SKOS integrity conflicts (dataset.skos-integrity) are deliberately NOT
    licensable this way; see the registry-conflict block in ontology/atlas.ttl.
    """

    facts = _asserted_facts(asserted, inventory)
    entries_by_pair: dict[tuple[URIRef, str], dict[URIRef, URIRef]] = {}
    for identifier in _carrier_nodes(asserted, ATLAS.Identifier, inventory):
        scheme = _iri(
            facts.one(
                identifier,
                ATLAS.identifierScheme,
                code="dataset.identifier-uniqueness",
            ),
            code="dataset.identifier-uniqueness",
            label="identifier scheme",
        )
        value = _literal_text(
            facts.one(
                identifier,
                ATLAS.identifierValue,
                code="dataset.identifier-uniqueness",
            ),
            code="dataset.identifier-uniqueness",
            label="identifier value",
        )
        resource = _iri(
            facts.one(
                identifier,
                ATLAS.identifies,
                code="dataset.identifier-uniqueness",
            ),
            code="dataset.identifier-uniqueness",
            label="identified resource",
        )
        entries_by_pair.setdefault((scheme, value), {})[identifier] = resource

    # Every entry carrying a pair that names more than one resource, not just
    # the two whose disagreement was noticed first: a third record agreeing with
    # the first is still an entry in the disagreement, and a group defined by
    # iteration order would let a producer's record match or miss by accident.
    conflicts = {
        frozenset(entries): (pair, frozenset(entries.values()))
        for pair, entries in entries_by_pair.items()
        if len(set(entries.values())) > 1
    }

    recorded: dict[frozenset[URIRef], set[URIRef]] = {}
    for record in _carrier_nodes(asserted, RKAF.RegistryConflict, inventory):
        entries = frozenset(facts.objects(record, RKAF.conflictingEntries))
        recorded.setdefault(entries, set()).add(record)

    unmatched = recorded.keys() - conflicts.keys()
    if unmatched:
        entries = min(unmatched, key=_conflicting_entry_order)
        rendered = ", ".join(_conflicting_entry_order(entries))
        _fail(
            "dataset.identifier-uniqueness",
            f"{min(recorded[entries], key=str)} names conflicting entries that do "
            f"not disagree on one identifier pair: {rendered}",
        )
    unrecorded = conflicts.keys() - recorded.keys()
    if unrecorded:
        entries = min(unrecorded, key=_conflicting_entry_order)
        (scheme, value), resources = conflicts[entries]
        rendered = ", ".join(sorted(map(str, resources)))
        _fail(
            "dataset.identifier-uniqueness",
            f"identifier pair ({scheme}, {value!r}) identifies multiple Atlas "
            f"resources: {rendered}; no rkaf:RegistryConflict names exactly "
            f"{', '.join(_conflicting_entry_order(entries))}",
        )


def _declared_assertion_types(
    graph: Graph,
    assertion: URIRef,
    facts: _AssertedFacts,
    inventory: SemanticInventory | None,
) -> set[URIRef]:
    """The assertion-shaped `rdf:type` objects on one node.

    Exactly `set(graph.objects(assertion, RDF.type)) & _ASSERTION_TYPE_TERMS`.
    With an inventory the concrete carrier types are already partitioned into
    per-type sets and the two abstract ones are in the parse-observed type
    index, so the same answer costs six membership tests instead of a store
    query. Without one, the store answers, as it always did.
    """

    if inventory is None:
        return set(graph.objects(assertion, RDF.type)) & _ASSERTION_TYPE_TERMS
    declared = {
        assertion_type
        for assertion_type in ASSERTION_TYPES
        if assertion in inventory.nodes(assertion_type)
    }
    declared.update(
        asserted_type
        for asserted_type in _INDEXED_ASSERTED_TYPES
        if facts.has_type(assertion, asserted_type)
    )
    return declared


def _assertion_type(
    graph: Graph,
    assertion: URIRef,
    *,
    facts: _AssertedFacts | None = None,
    inventory: SemanticInventory | None = None,
) -> URIRef:
    facts = facts if facts is not None else _asserted_facts(graph, inventory)
    declared_types = _declared_assertion_types(graph, assertion, facts, inventory)
    types = ASSERTION_TYPES & declared_types
    if len(types) != 1:
        _fail("dataset.assertion", f"{assertion} must have exactly one concrete assertion type")
    assertion_type = next(iter(types))
    expected_types = {ATLAS.RelationAssertion, assertion_type}
    if assertion_type == ATLAS.MappingAssertion:
        ring = set(facts.objects(assertion, ATLAS.semanticRing))
        if ring == {ATLAS.subject}:
            expected_types.add(ATLAS.SkosMappingAssertion)
    if declared_types != expected_types:
        _fail("dataset.assertion", f"{assertion} assertion types differ from {sorted(map(str, expected_types))}")
    return assertion_type


def _resource_type(
    graph: Graph,
    resource: URIRef,
    *,
    inventory: SemanticInventory | None = None,
) -> URIRef:
    if inventory is None:
        types = RESOURCE_TYPES & set(graph.objects(resource, RDF.type))
    else:
        types = {
            resource_type
            for resource_type in RESOURCE_TYPES
            if resource in inventory.nodes(resource_type)
        }
    if len(types) != 1:
        _fail("dataset.resource", f"{resource} must have exactly one Atlas resource type")
    return next(iter(types))


def _assertion_basis(
    graph: Graph,
    assertion: URIRef,
    *,
    facts: _AssertedFacts | None = None,
    inventory: SemanticInventory | None = None,
    policy_digests: dict[URIRef, str] | None = None,
) -> tuple[dict[str, Any], tuple[URIRef, URIRef, URIRef]]:
    facts = facts if facts is not None else _asserted_facts(graph, inventory)
    assertion_type = _assertion_type(graph, assertion, facts=facts, inventory=inventory)
    subject = _iri(
        facts.one(assertion, RDF.subject, code="dataset.assertion"),
        code="dataset.assertion",
        label="assertion subject",
    )
    predicate = _iri(
        facts.one(assertion, RDF.predicate, code="dataset.assertion"),
        code="dataset.assertion",
        label="assertion predicate",
    )
    obj = _iri(
        facts.one(assertion, RDF.object, code="dataset.assertion"), code="dataset.assertion", label="assertion object"
    )
    source_release = _iri(
        facts.one(assertion, ATLAS.sourceRelease, code="dataset.assertion"),
        code="dataset.assertion",
        label="source release",
    )
    target_release = _iri(
        facts.one(assertion, ATLAS.targetRelease, code="dataset.assertion"),
        code="dataset.assertion",
        label="target release",
    )
    policy = _iri(
        facts.one(assertion, ATLAS.governedByPolicy, code="dataset.assertion"),
        code="dataset.assertion",
        label="policy",
    )
    if not _has_carrier_type(graph, policy, ATLAS.EditorialPolicy, inventory):
        _fail("dataset.assertion", f"{assertion} names unknown editorial policy {policy}")
    # Recomputed, not read: the policy IRI is the digest, so a triple restating
    # it would be the node saying its own name back, and the assertion identity
    # this basis feeds must bind the policy's actual content either way.
    # A distribution has a handful of editorial policies and ~560K assertions
    # governed by them, so the caller may hand over a memo: the digest is a
    # function of the graph and the policy node, and re-deriving it once per
    # assertion re-renders and re-hashes the same policy payload 560K times.
    if policy_digests is None:
        policy_digest = rdf_node_digest(graph, policy)
    else:
        policy_digest = policy_digests.get(policy)
        if policy_digest is None:
            policy_digest = policy_digests[policy] = rdf_node_digest(graph, policy)
    basis = {
        "object": str(obj),
        "policy": str(policy),
        "policyContentDigest": policy_digest,
        "predicate": str(predicate),
        "sourceRelease": str(source_release),
        "subject": str(subject),
        "targetRelease": str(target_release),
        "type": str(assertion_type),
    }
    if assertion_type == ATLAS.CrossRingRelationAssertion:
        source_ring = _iri(
            facts.one(assertion, ATLAS.sourceRing, code="dataset.assertion"),
            code="dataset.assertion",
            label="source ring",
        )
        target_ring = _iri(
            facts.one(assertion, ATLAS.targetRing, code="dataset.assertion"),
            code="dataset.assertion",
            label="target ring",
        )
        basis["sourceRing"] = str(source_ring)
        basis["targetRing"] = str(target_ring)
    else:
        ring = _iri(
            facts.one(assertion, ATLAS.semanticRing, code="dataset.assertion"),
            code="dataset.assertion",
            label="semantic ring",
        )
        basis["semanticRing"] = str(ring)
    return basis, (subject, predicate, obj)


def _validate_assertions(
    asserted: Graph,
    inventory: SemanticInventory | None = None,
) -> dict[AssertionTriple, tuple[URIRef, ...]]:
    facts = _asserted_facts(asserted, inventory)
    policy_digests: dict[URIRef, str] = {}
    relation_policies = _relation_policies()
    cross_ring_policies = _cross_ring_relation_policies()
    assertions: Iterable[URIRef] = (
        inventory.assertions()
        if inventory is not None
        else frozenset(
            subject
            for assertion_type in ASSERTION_TYPES
            for subject in asserted.subjects(RDF.type, assertion_type)
            if isinstance(subject, URIRef)
        )
    )
    states: dict[URIRef, _AssertionState] = {}
    for assertion in sorted(assertions):
        basis, triple = _assertion_basis(
            asserted,
            assertion,
            facts=facts,
            inventory=inventory,
            policy_digests=policy_digests,
        )
        identity_digest = canonical_sha256(basis)
        stored_identity_digest = _literal_text(
            facts.one(
                assertion,
                ATLAS.assertionIdentityDigest,
                code="dataset.assertion-identity",
            ),
            code="dataset.assertion-identity",
            label="assertionIdentityDigest",
        )
        if stored_identity_digest != identity_digest:
            _fail("dataset.assertion-identity", f"{assertion} identity digest differs")
        expected_id = URIRef("urn:ref:atlas-assertion:" + identity_digest.removeprefix("sha256:"))
        if assertion != expected_id:
            _fail("dataset.assertion-identity", f"{assertion} is not its stable claim IRI")

        asserted_at = _date_time(
            facts.one(assertion, RKAF.assertedAt, code="dataset.assertion"),
            code="dataset.assertion",
            label="assertedAt",
        )
        predecessors = list(facts.objects(assertion, RKAF.supersedesAssertion))
        if len(predecessors) > 1 or any(not isinstance(value, URIRef) for value in predecessors):
            _fail("dataset.supersession", f"{assertion} has an invalid supersedes value")
        predecessor = predecessors[0] if predecessors else None
        assertion_type = URIRef(basis["type"])
        predicate = triple[1]
        source_release = URIRef(basis["sourceRelease"])
        target_release = URIRef(basis["targetRelease"])
        subject, _, obj = triple
        if assertion_type == ATLAS.CrossRingRelationAssertion:
            source_ring = URIRef(basis["sourceRing"])
            target_ring = URIRef(basis["targetRing"])
            ring_context: URIRef | tuple[URIRef, URIRef] = (source_ring, target_ring)
            source_type = _resource_type(asserted, subject, inventory=inventory)
            target_type = _resource_type(asserted, obj, inventory=inventory)
            if source_ring == target_ring:
                _fail("dataset.release", f"{assertion} does not cross semantic rings")
            if RING_RESOURCE_CLASSES.get(source_ring) != source_type or set(
                facts.objects(subject, ATLAS.semanticRing)
            ) != {source_ring}:
                _fail("dataset.release", f"{assertion} source endpoint ring differs")
            if RING_RESOURCE_CLASSES.get(target_ring) != target_type or set(
                facts.objects(obj, ATLAS.semanticRing)
            ) != {target_ring}:
                _fail("dataset.release", f"{assertion} target endpoint ring differs")
            if not facts.contains(subject, ATLAS.inRelease, source_release):
                _fail("dataset.release", f"{assertion} source release does not contain its subject")
            if not facts.contains(obj, ATLAS.inRelease, target_release):
                _fail("dataset.release", f"{assertion} target release does not contain its object")
            allowed = cross_ring_policies.get((source_ring, target_ring), frozenset())
            if predicate not in allowed:
                _fail(
                    "dataset.relation",
                    f"{assertion} predicate {predicate} is not allowed for {source_ring}->{target_ring}",
                )
        else:
            ring = URIRef(basis["semanticRing"])
            ring_context = ring
            allowed = relation_policies.get(ring, {}).get(assertion_type, frozenset())
            if predicate not in allowed:
                _fail(
                    "dataset.relation",
                    f"{assertion} predicate {predicate} is not allowed for its ring and type",
                )

        if assertion_type == ATLAS.SourceAssignment:
            ring = URIRef(basis["semanticRing"])
            if not _has_carrier_type(asserted, subject, ATLAS.SourceRecord, inventory):
                _fail("dataset.assignment", f"{assertion} subject is not a SourceRecord")
            if not facts.contains(subject, ATLAS.inSourceRelease, source_release):
                _fail("dataset.assignment", f"{assertion} source release does not match its SourceRecord")
            if not facts.contains(obj, ATLAS.inRelease, target_release):
                _fail("dataset.assignment", f"{assertion} target release does not contain its object")
            if set(facts.objects(obj, ATLAS.semanticRing)) != {ring}:
                _fail("dataset.assignment", f"{assertion} target ring differs from its assertion ring")
        elif assertion_type != ATLAS.CrossRingRelationAssertion:
            ring = URIRef(basis["semanticRing"])
            _resource_type(asserted, subject, inventory=inventory)
            _resource_type(asserted, obj, inventory=inventory)
            if not facts.contains(subject, ATLAS.inRelease, source_release):
                _fail("dataset.release", f"{assertion} source release does not contain its subject")
            if not facts.contains(obj, ATLAS.inRelease, target_release):
                _fail("dataset.release", f"{assertion} target release does not contain its object")
            if set(facts.objects(subject, ATLAS.semanticRing)) != {ring} or set(
                facts.objects(obj, ATLAS.semanticRing)
            ) != {ring}:
                _fail("dataset.release", f"{assertion} endpoint ring differs from its assertion ring")
            if assertion_type == ATLAS.MappingAssertion and source_release == target_release:
                _fail("dataset.release", f"{assertion} mapping endpoints use one release")

        states[assertion] = _AssertionState(
            triple=triple,
            assertion_type=assertion_type,
            source_release=source_release,
            ring_context=ring_context,
            asserted_at=asserted_at,
            predecessor=predecessor,
        )

    successors: dict[URIRef, set[URIRef]] = defaultdict(set)
    for assertion, state in states.items():
        predecessor = state.predecessor
        if predecessor is None:
            continue
        if predecessor == assertion or predecessor not in states:
            _fail("dataset.supersession", f"{assertion} supersedes itself or an unknown assertion")
        predecessor_state = states[predecessor]
        lineage_values: tuple[tuple[str, Any, Any], ...] = (
            ("type", state.assertion_type, predecessor_state.assertion_type),
            ("subject", state.triple[0], predecessor_state.triple[0]),
            ("sourceRelease", state.source_release, predecessor_state.source_release),
        )
        for field, value, predecessor_value in lineage_values:
            if value != predecessor_value:
                _fail(
                    "dataset.supersession",
                    f"{assertion} and {predecessor} disagree on lineage field {field}",
                )
        if state.assertion_type == ATLAS.CrossRingRelationAssertion:
            if not isinstance(state.ring_context, tuple) or not isinstance(
                predecessor_state.ring_context, tuple
            ):
                raise AssertionError("validated cross-ring assertions require paired ring context")
            source_ring, target_ring = state.ring_context
            predecessor_source_ring, predecessor_target_ring = predecessor_state.ring_context
            ring_values: tuple[tuple[str, URIRef, URIRef], ...] = (
                ("sourceRing", source_ring, predecessor_source_ring),
                ("targetRing", target_ring, predecessor_target_ring),
            )
        else:
            if isinstance(state.ring_context, tuple) or isinstance(predecessor_state.ring_context, tuple):
                raise AssertionError("validated same-ring assertions require one ring context")
            ring_values = (("semanticRing", state.ring_context, predecessor_state.ring_context),)
        for field, value, predecessor_value in ring_values:
            if value != predecessor_value:
                _fail(
                    "dataset.supersession",
                    f"{assertion} and {predecessor} disagree on lineage field {field}",
                )
        if state.asserted_at <= predecessor_state.asserted_at:
            _fail("dataset.supersession", f"{assertion} is not later than {predecessor}")
        successors[predecessor].add(assertion)

    for predecessor, rows in successors.items():
        if len(rows) != 1:
            _fail("dataset.supersession", f"{predecessor} has more than one direct successor")

    # Lifecycle state is not stored on the assertion: it is read off the
    # supersession edge and the rkaf:LifecycleEvent records that announce the
    # transition. An unrecognised event kind is not decided here -- the sh:in
    # on atlas:LifecycleEventShape rejects it -- so this pass only reads the
    # two kinds Atlas acts on.
    event_kinds: dict[URIRef, set[URIRef]] = defaultdict(set)
    lifecycle_events: Iterable[URIRef] = (
        inventory.nodes(RKAF.LifecycleEvent)
        if inventory is not None
        else frozenset(
            subject
            for subject in asserted.subjects(RDF.type, RKAF.LifecycleEvent)
            if isinstance(subject, URIRef)
        )
    )
    for event in lifecycle_events:
        targets = list(facts.objects(event, RKAF.appliesTo))
        kinds = list(facts.objects(event, RKAF.lifecycleEventKind))
        if len(targets) != 1 or len(kinds) != 1:
            _fail("dataset.lifecycle", f"{event} must name one subject and one kind")
        target, kind = targets[0], kinds[0]
        if not isinstance(target, URIRef) or not isinstance(kind, URIRef):
            _fail("dataset.lifecycle", f"{event} subject and kind must be IRIs")
        if kind in event_kinds[target]:
            _fail("dataset.lifecycle", f"{target} carries two {kind} events")
        event_kinds[target].add(kind)

    projected: dict[AssertionTriple, URIRef | list[URIRef]] = {}
    for assertion, state in states.items():
        has_successor = bool(successors.get(assertion))
        kinds = event_kinds.get(assertion, set())
        announced = RKAF.supersession in kinds
        rescinded = RKAF.rescission in kinds
        if has_successor and not announced:
            _fail(
                "dataset.supersession",
                f"superseded {assertion} has no rkaf:supersession lifecycle event",
            )
        if announced and not has_successor:
            _fail(
                "dataset.supersession",
                f"{assertion} announces a supersession no assertion carries out",
            )
        if rescinded and has_successor:
            _fail("dataset.supersession", f"{assertion} is both rescinded and superseded")
        if not has_successor and not rescinded:
            existing = projected.get(state.triple)
            if existing is None:
                projected[state.triple] = assertion
            elif isinstance(existing, list):
                existing.append(assertion)
            else:
                projected[state.triple] = [existing, assertion]
    return {
        triple: tuple(assertions) if isinstance(assertions, list) else (assertions,)
        for triple, assertions in projected.items()
    }


def _check_evidence_bindings(
    asserted: Graph,
    inventory: SemanticInventory | None = None,
    *,
    node_digests: _AssertedNodeDigests | None = None,
) -> None:
    facts = _asserted_facts(asserted, inventory)
    assertions = (
        None
        if inventory is not None
        else frozenset(
            subject
            for assertion_type in ASSERTION_TYPES
            for subject in asserted.subjects(RDF.type, assertion_type)
        )
    )
    source_records = _carrier_nodes(asserted, ATLAS.SourceRecord, inventory)
    bindings = _carrier_nodes(asserted, RKAF.EvidenceBinding, inventory)

    # Only an operatorAdoption binding may name a prior attestation, and when it
    # names one, the chain it starts must resolve to a non-adoption terminal
    # without cycling. Naming one is OPTIONAL: Atlas adopts pinned external
    # publisher artifacts it never minted a binding for (REF-016), so most
    # adoptions name no referent and are complete without one -- what they
    # adopted is named by atlas:evidenceSourceRecord and its digest. See the
    # operatorAdoption branch on atlas:EvidenceBindingShape for the whole
    # argument; this check and that branch have to agree, and this is the pair
    # that disagreed with the producer for three builds running.
    # This is purely a property of the warrant/basedOnAttestation graph, so it
    # is resolved before any content-identity check below: a cycle or a dangling
    # reference is diagnosed on its own terms rather than masked by an unrelated
    # stale-digest failure on one of the bindings it touches.
    adopted_evidence_by_binding: dict[URIRef, URIRef] = {}
    for binding in sorted(bindings):
        declares_adoption = "operatorAdoption" in declared_evidence_warrants(
            {axis: facts.value(binding, axis) for axis in EVIDENCE_WARRANT_AXES}
        )
        adopted_values = list(facts.objects(binding, RKAF.basedOnAttestation))
        if len(adopted_values) > 1:
            _fail(
                "dataset.evidence-adoption",
                f"{binding} has more than one basedOnAttestation",
            )
        adopted_evidence = adopted_values[0] if adopted_values else None
        if declares_adoption:
            if adopted_evidence is not None:
                adopted_evidence_by_binding[binding] = _iri(
                    adopted_evidence,
                    code="dataset.evidence-adoption",
                    label="basedOnAttestation",
                )
        elif adopted_evidence is not None:
            _fail(
                "dataset.evidence-adoption",
                f"{binding} names basedOnAttestation but does not declare a "
                "formal adoption event",
            )
    # Rulespec's #LocalAdoption carries rkaf:basedOnAttestation but states no
    # obligation on a CHAIN of adoptions. Atlas requires one: an adoption chain
    # must reach a binding that adopted nothing -- some binding must actually
    # have looked at the source -- and it must not cycle. Chained adoption with
    # no terminal is a real defect class, so the obligation is enforced here
    # rather than dropped on adoption. See the report note on amending rkaf.
    for start in sorted(adopted_evidence_by_binding):
        chain = [start]
        current = start
        while current in adopted_evidence_by_binding:
            target = adopted_evidence_by_binding[current]
            if target not in bindings:
                _fail(
                    "dataset.evidence-adoption",
                    f"{start} basedOnAttestation chain cites unknown evidence "
                    f"binding {target}",
                )
            if target in chain:
                _fail(
                    "dataset.evidence-adoption",
                    f"{start} basedOnAttestation chain cycles back to {target}",
                )
            chain.append(target)
            current = target

    bound_assertions: set[URIRef] = set()
    source_digests: dict[URIRef, str] = {}
    for binding in sorted(bindings):
        assertion = _iri(
            facts.one(binding, RKAF.bindsAssertion, code="dataset.evidence"),
            code="dataset.evidence",
            label="bound assertion",
        )
        source_record = _iri(
            facts.one(binding, ATLAS.evidenceSourceRecord, code="dataset.evidence"),
            code="dataset.evidence",
            label="evidence source record",
        )
        if (
            not inventory.is_assertion(assertion)
            if inventory is not None
            else assertion not in assertions
        ):
            _fail("dataset.evidence", f"{binding} binds unknown assertion {assertion}")
        if source_record not in source_records:
            _fail("dataset.evidence", f"{binding} names unknown source record {source_record}")
        _iri(
            facts.one(binding, RKAF.attestor, code="dataset.evidence"),
            code="dataset.evidence",
            label="reviewer",
        )
        if facts.one(binding, RKAF.decision, code="dataset.evidence") != RKAF.approved:
            _fail("dataset.evidence", f"{binding} is not an approved editorial decision")
        warrant = {
            axis: facts.one(binding, axis, code="dataset.evidence")
            for axis in EVIDENCE_WARRANT_AXES
        }
        if len(declared_evidence_warrants(warrant)) != 1:
            _fail(
                "dataset.evidence",
                f"{binding} combines evidence axes no review warrant sanctions",
            )
        if (
            facts.one(binding, RKAF.evidentiaryFunction, code="dataset.evidence")
            not in EVIDENTIARY_FUNCTIONS
        ):
            _fail("dataset.evidence", f"{binding} uses an unsupported evidentiary function")
        _date_time(
            facts.one(binding, RKAF.attestedAt, code="dataset.evidence"),
            code="dataset.evidence",
            label="attestedAt",
        )
        pinned_source_digest = _literal_text(
            facts.one(binding, ATLAS.evidenceSourceDigest, code="dataset.evidence-identity"),
            code="dataset.evidence-identity",
            label="evidenceSourceDigest",
        )
        actual_source_digest = source_digests.get(source_record)
        if actual_source_digest is None:
            # The source record no longer publishes its own digest, so the
            # comparand for the pin is recomputed from the record's facts.
            actual_source_digest = _node_digest(asserted, source_record, node_digests)
            source_digests[source_record] = actual_source_digest
        if pinned_source_digest != actual_source_digest:
            _fail("dataset.evidence-identity", f"{binding} does not pin its exact SourceRecord")
        stored = _literal_text(
            facts.one(binding, ATLAS.contentDigest, code="dataset.evidence-identity"),
            code="dataset.evidence-identity",
            label="contentDigest",
        )
        expected = _node_digest(asserted, binding, node_digests)
        if stored != expected:
            _fail("dataset.evidence-identity", f"{binding} contentDigest differs")
        expected_id = URIRef("urn:ref:atlas-evidence:" + expected.removeprefix("sha256:"))
        if binding != expected_id:
            _fail("dataset.evidence-identity", f"{binding} is not its content-derived IRI")
        bound_assertions.add(assertion)
    missing = min(
        (
            assertion
            for assertion in (
                inventory.assertions() if inventory is not None else assertions
            )
            if assertion not in bound_assertions
        ),
        key=str,
        default=None,
    )
    if missing is not None:
        _fail("dataset.evidence", f"assertion has no immutable evidence binding: {missing}")


def _adjudicated_relation(verdicts: AbstractSet[URIRef]) -> URIRef | None:
    """Fold a complete verdict set onto the one relation it licenses, if any.

    The lattice is UNIVERSAL, not existential: it folds *every* verdict cited
    for one sealed question, so a third machine cannot outvote a direction
    disagreement and a set mixing ``verdictNearSame`` with a directional
    verdict licenses nothing. A mapping is emitted at the weakest claim any
    machine made, which is why ``same`` together with ``nearSame`` yields
    ``skos:closeMatch`` -- one machine declined to claim identity, and
    ``skos:exactMatch`` is the only mapping relation whose transitivity this
    binding lets a consumer rely on (``_check_reasoning_isolation``).

    Ported verbatim from ``src/refspec/atlas/model.py``'s qualification-path
    lattice, with rkaf's verdict IRIs in place of v1's seven literals; the two
    values rkaf drops are refusals rather than relations and never reach a
    verdict slot at all (see ontology/atlas.ttl).
    """

    if not verdicts:
        return None
    if verdicts == {RKAF.verdictSame}:
        return SKOS.exactMatch
    if verdicts <= {RKAF.verdictSame, RKAF.verdictNearSame}:
        return SKOS.closeMatch
    if verdicts == {RKAF.verdictTargetBroader}:
        return SKOS.broadMatch
    if verdicts == {RKAF.verdictTargetNarrower}:
        return SKOS.narrowMatch
    if verdicts == {RKAF.verdictRelated}:
        return SKOS.relatedMatch
    return None


def _machine_adjudication_artifact_facts(
    artifacts: AbstractSet[URIRef],
    *,
    asserted_facts: _AssertedFacts,
) -> dict[URIRef, dict[str, Any]]:
    """Resolve every bundled artifact to its identifiers and its exact bytes."""

    facts: dict[URIRef, dict[str, Any]] = {}
    for artifact in sorted(artifacts):
        facts[artifact] = {
            "identifiers": frozenset(
                _literal_text(
                    value,
                    code="dataset.adjudication-input",
                    label="hasArtifactIdentifier",
                )
                for value in asserted_facts.objects(artifact, RKAF.hasArtifactIdentifier)
            ),
            "digest": _literal_text(
                asserted_facts.one(
                    artifact,
                    RKAF.hasContentDigest,
                    code="dataset.adjudication-input",
                ),
                code="dataset.adjudication-input",
                label="hasContentDigest",
            ),
        }
    return facts


def _machine_adjudication_proof_facts(
    asserted: Graph,
    proof: URIRef,
    *,
    asserted_facts: _AssertedFacts,
    issuers: AbstractSet[URIRef],
    lineages: AbstractSet[URIRef],
    comparisons: AbstractSet[URIRef],
    node_digests: _AssertedNodeDigests | None = None,
) -> dict[str, Any]:
    """Resolve one proof record, including both dereferenced axes."""

    stored_digest = _literal_text(
        asserted_facts.one(
            proof,
            RKAF.proofRecordDigest,
            code="dataset.adjudication-identity",
        ),
        code="dataset.adjudication-identity",
        label="proofRecordDigest",
    )
    if stored_digest != _node_digest(asserted, proof, node_digests):
        _fail("dataset.adjudication-identity", f"{proof} proofRecordDigest differs")
    issuer = _iri(
        asserted_facts.one(proof, RKAF.proofIssuer, code="dataset.adjudication"),
        code="dataset.adjudication",
        label="proofIssuer",
    )
    if issuer not in issuers:
        _fail("dataset.adjudication", f"{proof} names unknown proof issuer {issuer}")
    lineage = _iri(
        asserted_facts.one(proof, RKAF.hasAILineage, code="dataset.adjudication"),
        code="dataset.adjudication",
        label="hasAILineage",
    )
    if lineage not in lineages:
        _fail("dataset.adjudication", f"{proof} names unknown AI lineage {lineage}")
    comparison = _iri(
        asserted_facts.one(
            proof,
            RKAF.proofComparisonContext,
            code="dataset.adjudication",
        ),
        code="dataset.adjudication",
        label="proofComparisonContext",
    )
    if comparison not in comparisons:
        _fail("dataset.adjudication", f"{proof} names unknown comparison {comparison}")
    _date_time(
        asserted_facts.one(
            proof,
            RKAF.proofEvaluatedAt,
            code="dataset.adjudication",
        ),
        code="dataset.adjudication",
        label="proofEvaluatedAt",
    )
    verdict = _iri(
        asserted_facts.one(
            proof,
            RKAF.adjudicationVerdict,
            code="dataset.adjudication",
        ),
        code="dataset.adjudication",
        label="adjudicationVerdict",
    )
    if verdict not in MACHINE_ADJUDICATION_VERDICTS:
        _fail("dataset.adjudication", f"{proof} states an unsupported verdict {verdict}")
    outcome = _iri(
        asserted_facts.one(proof, RKAF.proofOutcome, code="dataset.adjudication"),
        code="dataset.adjudication",
        label="proofOutcome",
    )
    if outcome not in MACHINE_ADJUDICATION_OUTCOMES:
        _fail("dataset.adjudication", f"{proof} states an unsupported gate status {outcome}")
    return {
        "comparison": comparison,
        "verdict": verdict,
        "outcome": outcome,
        "snapshot": _literal_text(
            asserted_facts.one(
                proof,
                RKAF.proofSnapshot,
                code="dataset.adjudication",
            ),
            code="dataset.adjudication",
            label="proofSnapshot",
        ),
        "sealedRequestDigest": _literal_text(
            asserted_facts.one(
                proof,
                RKAF.sealedRequestDigest,
                code="dataset.adjudication",
            ),
            code="dataset.adjudication",
            label="sealedRequestDigest",
        ),
        "inputContextHash": _literal_text(
            asserted_facts.one(
                lineage,
                RKAF.inputContextHash,
                code="dataset.adjudication-input",
            ),
            code="dataset.adjudication-input",
            label="inputContextHash",
        ),
        # The five independence axes, in the order
        # MACHINE_ADJUDICATION_INDEPENDENCE_AXES names them. Two of the five are
        # reached through a referenced record rather than read off the proof, so
        # a resolver upgrade or a model swap changes one node instead of every
        # proof that cites it.
        "axes": (
            issuer,
            _iri(
                asserted_facts.one(
                    proof,
                    RKAF.independenceGroup,
                    code="dataset.adjudication",
                ),
                code="dataset.adjudication",
                label="independenceGroup",
            ),
            _iri(
                asserted_facts.one(
                    issuer,
                    RKAF.proofResolver,
                    code="dataset.adjudication",
                ),
                code="dataset.adjudication",
                label="proofResolver",
            ),
            _literal_text(
                asserted_facts.one(
                    lineage,
                    RKAF.modelId,
                    code="dataset.adjudication",
                ),
                code="dataset.adjudication",
                label="modelId",
            ),
            _iri(
                asserted_facts.one(
                    proof,
                    RKAF.sealedResponseArtifact,
                    code="dataset.adjudication",
                ),
                code="dataset.adjudication",
                label="sealedResponseArtifact",
            ),
        ),
        "inputs": frozenset(asserted_facts.objects(proof, RKAF.proofInput)),
        "inputDigests": frozenset(
            _literal_text(value, code="dataset.adjudication-input", label="proofInputDigest")
            for value in asserted_facts.objects(proof, RKAF.proofInputDigest)
        ),
    }


def _check_machine_adjudication(
    asserted: Graph,
    inventory: SemanticInventory | None = None,
    *,
    node_digests: _AssertedNodeDigests | None = None,
) -> None:
    """Close the machine-adjudication protocol over proofs and comparisons.

    Everything here spans several records, which is why none of it is SHACL:
    per-property constraints reach one node, and every rule below relates a
    comparison to the proofs citing it, to the artifacts they read, and to the
    assertion it licensed.

    LICENSING IS THE AXIS EVERYTHING TURNS ON. A comparison whose
    ``rkaf:comparisonOutcome`` is ``rkaf:comparisonSatisfied`` and whose cited
    proofs all passed their gate LICENSES the mapping it names. Any other
    outcome is an audit record: the comparison was run, it did not license
    anything, and publishing it is how a consumer tells "checked, nothing
    found" from "never checked" -- the distinction rulespec keeps five outcome
    values to preserve. Structural rules below hold for every comparison;
    independence and the lattice are asked only of a comparison that licenses,
    because they exist to protect a claim and a refusal makes none.

    The five normative rules Atlas 1.0's README carried in prose, restated over
    rkaf's records:

    * **Independence.** At least one PAIR of cited proofs must answer the
      identical sealed question while differing on all five axes. A single
      proof, or a set that collapses onto one axis, is one opinion wearing a
      proof record. This is rulespec's
      ``rkaf:MachineAdjudicationIndependentPairShape``, widened from its four
      axes to the five ``spec/rkaf-refspec.md`` states -- and it is "at least
      one pair", never "exactly two", so three corroborating machines are valid.
    * **One sealed question.** Every cited proof must read the same sealed
      request artifact. Two machines answering two questions are not a
      corroboration of one (v1: "both validations resolve the same
      atlas:requestArtifact").
    * **Complete support.** Every proof record in the dataset must be cited by
      the comparison it was issued for. This is strictly stronger than
      rulespec's ``rkaf:MachineAdjudicationCompleteSupportShape``, which only
      catches a dropped proof that shares a sealed request with a kept one:
      Atlas pins one comparison to one question, so ANY uncited proof is a
      discarded corroborator. It replaces v1's ``atlas:qualifiedBy``.
    * **Everything resolves to bundled bytes.** The two compared endpoints, the
      sealed request, and every sealed response are ``rkaf:Artifact`` records
      in the distribution; a proof's ``rkaf:sealedRequestDigest`` must equal the
      content digest of the request artifact it names, its
      ``rkaf:proofInputDigest`` must pin every input it read, its lineage's
      ``rkaf:inputContextHash`` must be that same sealed request, and the
      endpoint artifacts must carry the recorded content of the two resources
      under comparison. This is v1's ``atlas:inputContextArtifact`` /
      ``atlas:inputContextDigest`` rule, and v1 gave the reason it cannot be
      dropped: without it every record can agree on a digest whose bytes exist
      nowhere. The snapshot chain is the same idea in time -- a proof reads the
      comparison's snapshot, and that snapshot is the release the mapping
      targets, so a proof run against an older release cannot license a mapping
      into a newer one.
    * **The lattice.** The relation the complete verdict set licenses must be
      the relation the mapping states.
    """

    asserted_facts = _asserted_facts(asserted, inventory)
    comparisons = _carrier_nodes(asserted, RKAF.RelationComparisonContext, inventory)
    proofs = _carrier_nodes(asserted, RKAF.ResolverProofRecord, inventory)
    issuers = _carrier_nodes(asserted, RKAF.ResolverProofIssuer, inventory)
    lineages = _carrier_nodes(asserted, RKAF.AILineage, inventory)
    artifacts = _carrier_nodes(asserted, RKAF.Artifact, inventory)
    bindings = _carrier_nodes(asserted, RKAF.EvidenceBinding, inventory)
    # Which assertions owe a licensing proof set. The warrant is the trigger: an
    # evidence binding declaring aiSuggested + statisticalInference +
    # reviewedAuthorityChain is claiming two machines adjudicated the mapping,
    # and until this gate existed nothing made that claim mean anything.
    adjudicated: set[URIRef] = set()
    for binding in bindings:
        if "twoMachineAdjudication" in declared_evidence_warrants(
            {axis: asserted_facts.value(binding, axis) for axis in EVIDENCE_WARRANT_AXES}
        ):
            adjudicated.update(asserted_facts.objects(binding, RKAF.bindsAssertion))

    artifact_facts = _machine_adjudication_artifact_facts(
        artifacts,
        asserted_facts=asserted_facts,
    )
    facts = {
        proof: _machine_adjudication_proof_facts(
            asserted,
            proof,
            asserted_facts=asserted_facts,
            issuers=issuers,
            lineages=lineages,
            comparisons=comparisons,
            node_digests=node_digests,
        )
        for proof in sorted(proofs)
    }

    cited_by_comparison: dict[URIRef, list[URIRef]] = {}
    licensing_comparisons: list[URIRef] = []
    licensed_assertion: dict[URIRef, URIRef] = {}
    comparison_by_assertion: dict[URIRef, URIRef] = {}
    for comparison in sorted(comparisons):
        assertion = _iri(
            asserted_facts.one(
                comparison,
                RKAF.comparisonExpectedAssertion,
                code="dataset.adjudication",
            ),
            code="dataset.adjudication",
            label="comparisonExpectedAssertion",
        )
        if (
            not inventory.is_assertion(assertion)
            if inventory is not None
            else not any(
                (assertion, RDF.type, assertion_type) in asserted
                for assertion_type in ASSERTION_TYPES
            )
        ):
            _fail("dataset.adjudication", f"{comparison} names unknown assertion {assertion}")
        if assertion in comparison_by_assertion:
            _fail(
                "dataset.adjudication",
                f"{assertion} is named by two comparisons; one claim answers one "
                "sealed question",
            )
        comparison_by_assertion[assertion] = comparison
        outcome = _iri(
            asserted_facts.one(
                comparison,
                RKAF.comparisonOutcome,
                code="dataset.adjudication",
            ),
            code="dataset.adjudication",
            label="comparisonOutcome",
        )
        if outcome not in RELATION_COMPARISON_OUTCOMES:
            _fail("dataset.adjudication", f"{comparison} states an unsupported outcome {outcome}")
        licensing = outcome == RKAF.comparisonSatisfied
        if licensing:
            if assertion not in adjudicated:
                _fail(
                    "dataset.adjudication",
                    f"{comparison} licenses {assertion}, whose evidence declares no "
                    "machine adjudication",
                )
            licensing_comparisons.append(comparison)
            licensed_assertion[comparison] = assertion
        snapshot = _literal_text(
            asserted_facts.one(
                comparison,
                RKAF.comparisonSnapshot,
                code="dataset.adjudication",
            ),
            code="dataset.adjudication",
            label="comparisonSnapshot",
        )
        target_release = _iri(
            asserted_facts.one(
                assertion,
                ATLAS.targetRelease,
                code="dataset.adjudication",
            ),
            code="dataset.adjudication",
            label="targetRelease",
        )
        if snapshot != str(target_release):
            _fail(
                "dataset.adjudication",
                f"{comparison} read snapshot {snapshot}, which is not the release "
                f"{assertion} targets",
            )
        endpoints = (
            (
                RKAF.comparisonBaselineArtifact,
                _iri(
                    asserted_facts.one(
                        assertion,
                        RDF.subject,
                        code="dataset.adjudication",
                    ),
                    code="dataset.adjudication",
                    label="assertion subject",
                ),
            ),
            (
                RKAF.comparisonObservedArtifact,
                _iri(
                    asserted_facts.one(
                        assertion,
                        RDF.object,
                        code="dataset.adjudication",
                    ),
                    code="dataset.adjudication",
                    label="assertion object",
                ),
            ),
        )
        endpoint_artifacts: set[URIRef] = set()
        for predicate, endpoint in endpoints:
            artifact = _iri(
                asserted_facts.one(
                    comparison,
                    predicate,
                    code="dataset.adjudication-input",
                ),
                code="dataset.adjudication-input",
                label=str(predicate),
            )
            if artifact not in artifact_facts:
                _fail(
                    "dataset.adjudication-input",
                    f"{comparison} names {artifact}, which is not a bundled artifact",
                )
            if artifact_facts[artifact]["identifiers"] != frozenset({str(endpoint)}):
                _fail(
                    "dataset.adjudication-input",
                    f"{artifact} does not identify {endpoint}, the endpoint "
                    f"{comparison} claims it captured",
                )
            # The endpoint resource no longer publishes its digest, so what the
            # artifact pins is checked against the endpoint's recomputed facts.
            recorded = rdf_node_digest(asserted, endpoint)
            if artifact_facts[artifact]["digest"] != recorded:
                _fail(
                    "dataset.adjudication-input",
                    f"{artifact} pins content {endpoint} does not have",
                )
            endpoint_artifacts.add(artifact)
        cited = sorted(
            set(asserted_facts.objects(comparison, RKAF.comparisonProofRecord))
        )
        request_artifacts: set[URIRef] = set()
        for proof in cited:
            if proof not in facts:
                _fail("dataset.adjudication", f"{comparison} cites unknown proof record {proof}")
            if facts[proof]["comparison"] != comparison:
                _fail(
                    "dataset.adjudication-support",
                    f"{comparison} cites {proof}, which was issued for "
                    f"{facts[proof]['comparison']}: a proof replayed against another "
                    "comparison is a stale pass",
                )
            if licensing and facts[proof]["outcome"] != RKAF.gatePass:
                _fail(
                    "dataset.adjudication",
                    f"{comparison} licenses a mapping on {proof}, whose gate returned "
                    f"{facts[proof]['outcome']}",
                )
            if facts[proof]["snapshot"] != snapshot:
                _fail(
                    "dataset.adjudication",
                    f"{proof} read snapshot {facts[proof]['snapshot']}, not the "
                    f"{snapshot} its comparison did",
                )
            inputs = facts[proof]["inputs"]
            missing = endpoint_artifacts - inputs
            if missing:
                _fail(
                    "dataset.adjudication-input",
                    f"{proof} did not read {min(missing, key=str)}, an endpoint of the "
                    "comparison it answers",
                )
            requests = inputs - endpoint_artifacts
            if len(requests) != 1:
                _fail(
                    "dataset.adjudication-input",
                    f"{proof} reads {len(requests)} sealed request artifacts beyond the "
                    "two compared endpoints; a sealed question is one artifact",
                )
            request = next(iter(requests))
            if request not in artifact_facts:
                _fail(
                    "dataset.adjudication-input",
                    f"{proof} names {request}, which is not a bundled artifact",
                )
            if facts[proof]["sealedRequestDigest"] != artifact_facts[request]["digest"]:
                _fail(
                    "dataset.adjudication-input",
                    f"{proof} sealedRequestDigest does not match {request}, the request "
                    "artifact it read: the sealed question resolves to no bundled bytes",
                )
            if facts[proof]["inputContextHash"] != facts[proof]["sealedRequestDigest"]:
                _fail(
                    "dataset.adjudication-input",
                    f"{proof} model lineage ran over an input context that is not the "
                    "sealed request the proof answers",
                )
            expected_digests = frozenset(
                artifact_facts[value]["digest"]
                for value in inputs
                if value in artifact_facts
            )
            if facts[proof]["inputDigests"] != expected_digests:
                _fail(
                    "dataset.adjudication-input",
                    f"{proof} proofInputDigest does not pin the exact content of the "
                    "artifacts it names",
                )
            response = facts[proof]["axes"][4]
            if response not in artifact_facts:
                _fail(
                    "dataset.adjudication-input",
                    f"{proof} sealed response {response} is not a bundled artifact: the "
                    "verdict resolves to nothing a reviewer can re-read",
                )
            request_artifacts.add(request)
        if len(request_artifacts) > 1:
            _fail(
                "dataset.adjudication-independence",
                f"{comparison} cites proofs answering {len(request_artifacts)} sealed "
                "questions; two machines answering two questions corroborate nothing",
            )
        cited_by_comparison[comparison] = cited

    # Complete support: a proof the dataset carries but no comparison cites is
    # evidence thrown away after it was produced.
    for proof in sorted(proofs):
        comparison = facts[proof]["comparison"]
        if proof not in cited_by_comparison.get(comparison, ()):
            _fail(
                "dataset.adjudication-support",
                f"{comparison} does not cite {proof}, which was issued for it; a "
                "mapping cites the complete support set, not the first pair found",
            )

    for comparison in licensing_comparisons:
        cited = cited_by_comparison[comparison]
        witness = next(
            (
                pair
                for pair in combinations(cited, 2)
                if all(
                    facts[pair[0]]["axes"][axis] != facts[pair[1]]["axes"][axis]
                    for axis in range(len(MACHINE_ADJUDICATION_INDEPENDENCE_AXES))
                )
            ),
            None,
        )
        if witness is None:
            collapsed = sorted(
                {
                    MACHINE_ADJUDICATION_INDEPENDENCE_AXES[axis]
                    for first, second in combinations(cited, 2)
                    for axis in range(len(MACHINE_ADJUDICATION_INDEPENDENCE_AXES))
                    if facts[first]["axes"][axis] == facts[second]["axes"][axis]
                }
            )
            _fail(
                "dataset.adjudication-independence",
                f"{comparison} cites no independent pair of machine adjudications "
                f"({len(cited)} proof(s); shared: {collapsed or ['no pair exists']})",
            )
        assertion = licensed_assertion[comparison]
        stated = _iri(
            asserted_facts.one(
                assertion,
                RDF.predicate,
                code="dataset.adjudication-lattice",
            ),
            code="dataset.adjudication-lattice",
            label="assertion predicate",
        )
        licensed = _adjudicated_relation({facts[proof]["verdict"] for proof in cited})
        if licensed is None:
            _fail(
                "dataset.adjudication-lattice",
                f"{comparison} folds its verdicts onto no relation, so {assertion} "
                "states one the machines did not agree on",
            )
        if licensed != stated:
            _fail(
                "dataset.adjudication-lattice",
                f"{assertion} states {stated}, but its verdicts license {licensed}",
            )

    licensed_assertions = set(licensed_assertion.values())
    unlicensed = min(
        (assertion for assertion in adjudicated if assertion not in licensed_assertions),
        key=str,
        default=None,
    )
    if unlicensed is not None:
        _fail(
            "dataset.adjudication",
            f"{unlicensed} declares a machine-adjudication warrant but no satisfied "
            "comparison licenses it; the warrant is the protocol's trigger, not a label",
        )


def _hierarchy_connected_pairs(
    hierarchy: Mapping[URIRef, URIRef | AbstractSet[URIRef]],
    pairs: Iterable[NodePair],
) -> set[NodePair]:
    """Find positive-path hierarchy connections without per-endpoint traversals."""

    canonical_pairs = frozenset(_canonical_pair(*pair) for pair in pairs)
    if not hierarchy or not canonical_pairs:
        return set()

    index = _build_hierarchy_reachability_index(hierarchy)
    connected: set[NodePair] = set()
    component_queries: dict[int, set[HierarchyComponentPair]] = defaultdict(set)
    original_queries: list[tuple[HierarchyComponentPair, NodePair]] = []

    for pair in sorted(canonical_pairs):
        subject, obj = pair
        subject_component = index.component_by_node.get(subject)
        object_component = index.component_by_node.get(obj)
        if subject_component is None or object_component is None:
            continue
        if subject_component == object_component:
            if subject != obj or index.component_is_cyclic[subject_component]:
                connected.add(pair)
            continue
        subject_weak = index.weak_component[subject_component]
        if subject_weak != index.weak_component[object_component]:
            continue
        if index.topological_rank[subject_component] < index.topological_rank[object_component]:
            query = (subject_component, object_component)
        else:
            query = (object_component, subject_component)
        component_queries[subject_weak].add(query)
        original_queries.append((query, pair))

    if not component_queries:
        return connected

    topological_orders = {weak: [] for weak in component_queries}
    for component in index.topological_order:
        weak = index.weak_component[component]
        if weak in topological_orders:
            topological_orders[weak].append(component)

    reachable_queries: set[HierarchyComponentPair] = set()
    reachability_masks = [0] * len(index.dag)
    for weak in sorted(component_queries):
        reachable_queries.update(
            _batched_dag_reachable_pairs(
                index.dag,
                tuple(topological_orders[weak]),
                component_queries[weak],
                reachability_masks,
            )
        )
    connected.update(pair for query, pair in original_queries if query in reachable_queries)
    return connected


def _build_hierarchy_reachability_index(
    hierarchy: Mapping[URIRef, URIRef | AbstractSet[URIRef]],
) -> _HierarchyReachabilityIndex:
    """Collapse hierarchy cycles into a deterministic directed acyclic graph."""

    node_set: set[URIRef] = set(hierarchy)
    for targets in hierarchy.values():
        if isinstance(targets, AbstractSet):
            node_set.update(targets)
        else:
            node_set.add(targets)
    nodes = tuple(sorted(node_set))
    node_index = {node: index for index, node in enumerate(nodes)}

    self_loops = bytearray(len(nodes))
    adjacency_rows: list[tuple[int, ...]] = []
    for node in nodes:
        targets = hierarchy.get(node)
        if targets is None:
            target_nodes: Iterable[URIRef] = ()
        elif isinstance(targets, AbstractSet):
            target_nodes = sorted(targets)
        else:
            target_nodes = (targets,)
        row = tuple(node_index[target] for target in target_nodes)
        adjacency_rows.append(row)
        if node_index[node] in row:
            self_loops[node_index[node]] = 1
    adjacency = tuple(adjacency_rows)

    component_by_vertex, component_is_cyclic = _hierarchy_strong_components(
        adjacency,
        self_loops,
    )
    component_count = len(component_is_cyclic)
    outgoing: list[set[int] | None] = [None] * component_count
    for source, targets in enumerate(adjacency):
        source_component = component_by_vertex[source]
        for target in targets:
            target_component = component_by_vertex[target]
            if source_component == target_component:
                continue
            row = outgoing[source_component]
            if row is None:
                row = set()
                outgoing[source_component] = row
            row.add(target_component)
    dag = tuple(tuple(sorted(row)) if row is not None else () for row in outgoing)

    indegree = [0] * component_count
    weak_parent = list(range(component_count))
    weak_size = [1] * component_count

    def find(component: int) -> int:
        while weak_parent[component] != component:
            weak_parent[component] = weak_parent[weak_parent[component]]
            component = weak_parent[component]
        return component

    def union(left: int, right: int) -> None:
        left = find(left)
        right = find(right)
        if left == right:
            return
        if weak_size[left] < weak_size[right] or (
            weak_size[left] == weak_size[right] and left > right
        ):
            left, right = right, left
        weak_parent[right] = left
        weak_size[left] += weak_size[right]

    for source, targets in enumerate(dag):
        for target in targets:
            indegree[target] += 1
            union(source, target)

    ready = deque(sorted(component for component, count in enumerate(indegree) if count == 0))
    topological_order: list[int] = []
    while ready:
        component = ready.popleft()
        topological_order.append(component)
        for target in dag[component]:
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    if len(topological_order) != component_count:
        raise AssertionError("strong-component condensation must be acyclic")

    topological_rank = [0] * component_count
    for rank, component in enumerate(topological_order):
        topological_rank[component] = rank
    component_by_node = {
        node: component_by_vertex[vertex]
        for vertex, node in enumerate(nodes)
    }
    return _HierarchyReachabilityIndex(
        component_by_node=component_by_node,
        component_is_cyclic=component_is_cyclic,
        dag=dag,
        topological_order=tuple(topological_order),
        topological_rank=tuple(topological_rank),
        weak_component=tuple(find(component) for component in range(component_count)),
    )


def _hierarchy_strong_components(
    adjacency: Sequence[Sequence[int]],
    self_loops: Sequence[int],
) -> tuple[tuple[int, ...], tuple[bool, ...]]:
    """Return iterative Tarjan components and their positive-cycle flags."""

    vertex_count = len(adjacency)
    discovery = [-1] * vertex_count
    lowlink = [0] * vertex_count
    parent = [-1] * vertex_count
    active = bytearray(vertex_count)
    active_stack: list[int] = []
    component_by_vertex = [-1] * vertex_count
    component_is_cyclic: list[bool] = []
    serial = 0

    for root in range(vertex_count):
        if discovery[root] >= 0:
            continue
        discovery[root] = serial
        lowlink[root] = serial
        serial += 1
        active[root] = 1
        active_stack.append(root)
        frame_nodes = [root]
        frame_offsets = [0]

        while frame_nodes:
            vertex = frame_nodes[-1]
            offset = frame_offsets[-1]
            if offset < len(adjacency[vertex]):
                target = adjacency[vertex][offset]
                frame_offsets[-1] += 1
                if discovery[target] < 0:
                    parent[target] = vertex
                    discovery[target] = serial
                    lowlink[target] = serial
                    serial += 1
                    active[target] = 1
                    active_stack.append(target)
                    frame_nodes.append(target)
                    frame_offsets.append(0)
                elif active[target] and discovery[target] < lowlink[vertex]:
                    lowlink[vertex] = discovery[target]
                continue

            frame_nodes.pop()
            frame_offsets.pop()
            parent_vertex = parent[vertex]
            if parent_vertex >= 0 and lowlink[vertex] < lowlink[parent_vertex]:
                lowlink[parent_vertex] = lowlink[vertex]
            if lowlink[vertex] != discovery[vertex]:
                continue

            component = len(component_is_cyclic)
            member_count = 0
            has_self_loop = False
            while True:
                member = active_stack.pop()
                active[member] = 0
                component_by_vertex[member] = component
                member_count += 1
                has_self_loop = has_self_loop or bool(self_loops[member])
                if member == vertex:
                    break
            component_is_cyclic.append(member_count > 1 or has_self_loop)

    return tuple(component_by_vertex), tuple(component_is_cyclic)


def _batched_dag_reachable_pairs(
    dag: Sequence[Sequence[int]],
    topological_order: Sequence[int],
    queries: AbstractSet[HierarchyComponentPair],
    reachability_masks: list[int],
) -> set[HierarchyComponentPair]:
    """Answer exact DAG reachability queries with bounded Python-int bitsets."""

    sources = sorted({source for source, _ in queries})
    targets = sorted({target for _, target in queries})
    connected: set[HierarchyComponentPair] = set()

    if len(targets) <= len(sources):
        queries_by_target: dict[int, list[int]] = defaultdict(list)
        for source, target in sorted(queries):
            queries_by_target[target].append(source)
        for offset in range(0, len(targets), HIERARCHY_REACHABILITY_BATCH_BITS):
            batch = targets[offset : offset + HIERARCHY_REACHABILITY_BATCH_BITS]
            bit_by_target = {target: 1 << bit for bit, target in enumerate(batch)}
            for component in reversed(topological_order):
                mask = bit_by_target.get(component, 0)
                for successor in dag[component]:
                    mask |= reachability_masks[successor]
                reachability_masks[component] = mask
            for target in batch:
                bit = bit_by_target[target]
                for source in queries_by_target[target]:
                    if reachability_masks[source] & bit:
                        connected.add((source, target))
            for component in topological_order:
                reachability_masks[component] = 0
        return connected

    queries_by_source: dict[int, list[int]] = defaultdict(list)
    for source, target in sorted(queries):
        queries_by_source[source].append(target)
    for offset in range(0, len(sources), HIERARCHY_REACHABILITY_BATCH_BITS):
        batch = sources[offset : offset + HIERARCHY_REACHABILITY_BATCH_BITS]
        bit_by_source = {source: 1 << bit for bit, source in enumerate(batch)}
        for component in topological_order:
            mask = reachability_masks[component] | bit_by_source.get(component, 0)
            reachability_masks[component] = mask
            if mask:
                for successor in dag[component]:
                    reachability_masks[successor] |= mask
        for source in batch:
            bit = bit_by_source[source]
            for target in queries_by_source[source]:
                if reachability_masks[target] & bit:
                    connected.add((source, target))
        for component in topological_order:
            reachability_masks[component] = 0
    return connected


def _canonical_pair(subject: URIRef, obj: URIRef) -> NodePair:
    return (subject, obj) if subject <= obj else (obj, subject)


def _add_compact_target(
    targets: dict[URIRef, URIRef | set[URIRef]],
    source: URIRef,
    target: URIRef,
) -> None:
    existing = targets.get(source)
    if existing is None:
        targets[source] = target
    elif isinstance(existing, set):
        existing.add(target)
    elif existing != target:
        targets[source] = {existing, target}


def _build_exact_match_index(
    current: Mapping[AssertionTriple, AssertionSupport],
) -> ExactMatchIndex:
    """Index exactMatch components without retaining their Cartesian closure."""

    direct_triples = frozenset(triple for triple in current if triple[1] == SKOS.exactMatch)
    return _build_exact_match_index_from_triples(direct_triples)


def _build_exact_match_index_from_triples(
    direct_triples: frozenset[AssertionTriple],
) -> ExactMatchIndex:
    """Build the exactMatch index from triples collected by another graph pass."""

    adjacency: dict[URIRef, set[URIRef]] = defaultdict(set)
    for subject, _, obj in direct_triples:
        adjacency[subject].add(obj)
        adjacency[obj].add(subject)

    component_by_node: dict[URIRef, int] = {}
    component_sizes: list[int] = []
    for start in sorted(adjacency):
        if start in component_by_node:
            continue
        frontier = [start]
        visited = {start}
        while frontier:
            current_node = frontier.pop()
            for neighbor in adjacency[current_node] - visited:
                visited.add(neighbor)
                frontier.append(neighbor)
        component = len(component_sizes)
        component_sizes.append(len(visited))
        for node in visited:
            component_by_node[node] = component

    directed_direct_counts = [0] * len(component_sizes)
    for subject, _, _ in direct_triples:
        directed_direct_counts[component_by_node[subject]] += 1
    return ExactMatchIndex(
        component_by_node=component_by_node,
        component_sizes=tuple(component_sizes),
        directed_direct_counts=tuple(directed_direct_counts),
        direct_triples=direct_triples,
    )


def _check_skos_integrity(
    current: Mapping[AssertionTriple, AssertionSupport],
    exact_index: ExactMatchIndex | None = None,
) -> ExactMatchIndex:
    hierarchy: dict[URIRef, URIRef | set[URIRef]] = {}
    related_pairs: set[NodePair] = set()
    thesaurus_related_pairs: set[NodePair] = set()
    mapping_relations: list[tuple[URIRef, URIRef, URIRef]] = []
    exact_triples: set[AssertionTriple] | None = set() if exact_index is None else None
    for subject, predicate, obj in current:
        if exact_triples is not None and predicate == SKOS.exactMatch:
            exact_triples.add((subject, predicate, obj))
        if predicate in {SKOS.broadMatch, SKOS.narrowMatch, SKOS.relatedMatch}:
            mapping_relations.append((subject, predicate, obj))
        if predicate == SKOS.broader:
            _add_compact_target(hierarchy, subject, obj)
        elif predicate == SKOS.narrower or predicate == SKOS.narrowMatch:
            _add_compact_target(hierarchy, obj, subject)
        elif predicate == SKOS.broadMatch:
            _add_compact_target(hierarchy, subject, obj)
        elif predicate == SKOS.related or predicate == SKOS.relatedMatch:
            related_pairs.add(_canonical_pair(subject, obj))
        elif predicate == ATLAS.thesaurusRelated:
            thesaurus_related_pairs.add(_canonical_pair(subject, obj))

    if exact_index is None:
        if exact_triples is None:
            raise AssertionError("exactMatch collection was not initialized")
        exact_index = _build_exact_match_index_from_triples(frozenset(exact_triples))

    for subject, predicate, obj in sorted(mapping_relations):
        if exact_index.same_component(subject, obj):
            _fail(
                "dataset.skos-integrity",
                f"SKOS S46 exactMatch-component conflict for {(subject, predicate, obj)}",
            )

    hierarchy_connected = _hierarchy_connected_pairs(
        hierarchy,
        chain(related_pairs, thesaurus_related_pairs),
    )
    for pair in sorted(related_pairs):
        source, target = pair
        if pair in hierarchy_connected:
            _fail("dataset.skos-integrity", f"SKOS S27 transitive hierarchy conflict for {(source, target)}")

    for pair in sorted(thesaurus_related_pairs):
        source, target = pair
        if pair not in hierarchy_connected:
            _fail(
                "dataset.skos-integrity",
                "atlas:thesaurusRelated is allowed only for an authored associative "
                f"link with a transitive hierarchy conflict: {(source, target)}",
            )
    return exact_index


def _outgoing_facts_digest(
    facts: Iterable[tuple[URIRef, URIRef | Literal]],
    *,
    node: URIRef | None = None,
) -> str:
    rows = sorted(
        f"{ntriples_term(predicate)} {ntriples_term(obj)} ."
        for predicate, obj in facts
        if predicate not in _SELF_DIGEST_PREDICATES
    )
    if not rows:
        detail = f"{node} has no digestible RDF facts" if node is not None else "node has no digestible RDF facts"
        _fail("dataset.node-identity", detail)
    return "sha256:" + hashlib.sha256(("\n".join(rows) + "\n").encode("utf-8")).hexdigest()


def _projection_record_iri(triple: tuple[URIRef, URIRef, URIRef]) -> URIRef:
    subject, predicate, obj = triple
    digest = hashlib.sha256(
        canonical_json_bytes(
            {"object": str(obj), "predicate": str(predicate), "subject": str(subject)},
            terminal_lf=False,
        )
    ).hexdigest()
    return URIRef("urn:ref:atlas-projection:" + digest)


def _projection_ring_facts(
    asserted: Graph,
    triple: AssertionTriple,
    assertions: AssertionSupport,
) -> tuple[tuple[URIRef, URIRef], ...]:
    contexts: set[tuple[URIRef, ...]] = set()
    for assertion in assertions:
        assertion_type = _assertion_type(asserted, assertion)
        if assertion_type == ATLAS.CrossRingRelationAssertion:
            source_ring = _iri(
                _one(asserted, assertion, ATLAS.sourceRing, code="dataset.projection"),
                code="dataset.projection",
                label="projection source ring",
            )
            target_ring = _iri(
                _one(asserted, assertion, ATLAS.targetRing, code="dataset.projection"),
                code="dataset.projection",
                label="projection target ring",
            )
            contexts.add((ATLAS.sourceRing, source_ring, ATLAS.targetRing, target_ring))
        else:
            ring = _iri(
                _one(asserted, assertion, ATLAS.semanticRing, code="dataset.projection"),
                code="dataset.projection",
                label="projection semantic ring",
            )
            contexts.add((ATLAS.semanticRing, ring))
    if len(contexts) != 1:
        _fail("dataset.projection", f"projection support for {triple} disagrees on ring context")
    context = next(iter(contexts))
    if len(context) == 2:
        return ((context[0], context[1]),)
    return ((context[0], context[1]), (context[2], context[3]))


def _projection_record_facts(
    asserted: Graph,
    triple: AssertionTriple,
    assertions: AssertionSupport,
) -> tuple[URIRef, list[tuple[URIRef, URIRef | Literal]]]:
    subject, predicate, obj = triple
    projection = _projection_record_iri(triple)
    facts: list[tuple[URIRef, URIRef | Literal]] = [
        (RDF.type, ATLAS.ProjectedRelation),
        (ATLAS.relationSubject, subject),
        (ATLAS.relationPredicate, predicate),
        (ATLAS.relationObject, obj),
    ]
    facts.extend(_projection_ring_facts(asserted, triple, assertions))
    facts.extend((ATLAS.supportingAssertion, assertion) for assertion in sorted(assertions))
    return projection, facts


def _expected_projection_triples(
    asserted: Graph,
    supported: Mapping[AssertionTriple, AssertionSupport],
) -> Iterable[tuple[URIRef, URIRef, URIRef | Literal]]:
    emitted_label_triples: set[tuple[URIRef, URIRef, Literal]] = set()
    for xl_predicate, plain_predicate in XL_TO_SKOS.items():
        for resource, _, label in asserted.triples((None, xl_predicate, None)):
            literal = _one(
                asserted, _iri(label, code="dataset.label", label="label"), SKOSXL.literalForm, code="dataset.label"
            )
            if not isinstance(literal, Literal):
                _fail("dataset.label", f"{label} literalForm must be a literal")
            triple = (resource, plain_predicate, literal)
            if triple not in emitted_label_triples:
                emitted_label_triples.add(triple)
                yield triple

    for triple, assertions in sorted(supported.items(), key=lambda row: row[0]):
        yield triple
        projection, facts = _projection_record_facts(asserted, triple, assertions)
        for fact_predicate, fact_object in facts:
            yield projection, fact_predicate, fact_object


def _expected_projection(
    asserted: Graph,
    supported: Mapping[AssertionTriple, AssertionSupport] | None = None,
) -> Graph:
    expected = Graph()
    analysis = supported if supported is not None else _validate_assertions(asserted)
    for triple in _expected_projection_triples(asserted, analysis):
        expected.add(triple)
    return expected


def _check_projection(
    asserted: Graph,
    projection: Graph,
    supported: Mapping[AssertionTriple, AssertionSupport],
) -> None:
    projection_records: dict[
        URIRef,
        tuple[AssertionTriple, AssertionSupport],
    ] = {}
    for triple, assertions in supported.items():
        record_iri = _projection_record_iri(triple)
        previous = projection_records.get(record_iri)
        if previous is not None and previous[0] != triple:
            _fail("dataset.projection", f"projection record identity collision for {record_iri}")
        projection_records[record_iri] = (triple, assertions)

    def triple_key(triple: tuple[Any, Any, Any]) -> tuple[str, str, str]:
        return tuple(ntriples_term(term) for term in triple)  # type: ignore[return-value]

    def is_expected(triple: tuple[Any, Any, Any]) -> bool:
        subject, predicate, obj = triple
        if triple in supported:
            return True
        xl_predicate = SKOS_TO_XL.get(predicate)
        if xl_predicate is not None and isinstance(obj, Literal):
            return any(
                (label, SKOSXL.literalForm, obj) in asserted for label in asserted.objects(subject, xl_predicate)
            )
        record = projection_records.get(subject)
        if record is None:
            return False
        relation, assertions = record
        relation_subject, relation_predicate, relation_object = relation
        if predicate == RDF.type:
            return obj == ATLAS.ProjectedRelation
        if predicate == ATLAS.relationSubject:
            return obj == relation_subject
        if predicate == ATLAS.relationPredicate:
            return obj == relation_predicate
        if predicate == ATLAS.relationObject:
            return obj == relation_object
        if predicate in {ATLAS.semanticRing, ATLAS.sourceRing, ATLAS.targetRing}:
            return (predicate, obj) in _projection_ring_facts(asserted, relation, assertions)
        if predicate == ATLAS.supportingAssertion:
            return obj in assertions
        return False

    missing_count = 0
    first_missing: tuple[URIRef, URIRef, URIRef | Literal] | None = None
    for triple in _expected_projection_triples(asserted, supported):
        if triple not in projection:
            missing_count += 1
            if first_missing is None or triple_key(triple) < triple_key(first_missing):
                first_missing = triple

    extra_count = 0
    first_extra: tuple[Any, Any, Any] | None = None
    for triple in projection:
        if not is_expected(triple):
            extra_count += 1
            if first_extra is None or triple_key(triple) < triple_key(first_extra):
                first_extra = triple

    if missing_count or extra_count:
        detail = f"projection differs; missing={missing_count}, extra={extra_count}"
        if first_missing is not None:
            detail += f", firstMissing={first_missing}"
        if first_extra is not None:
            detail += f", firstExtra={first_extra}"
        _fail("dataset.projection", detail)


def _check_release_membership(
    asserted: Graph,
    inventory: SemanticInventory | None = None,
) -> None:
    facts = _asserted_facts(asserted, inventory)
    releases = _carrier_nodes(asserted, ATLAS.AtlasRelease, inventory)
    release_metadata: dict[URIRef, tuple[Any, Any, URIRef]] = {}
    for release in releases:
        release_ring = facts.one(release, ATLAS.semanticRing, code="dataset.release")
        release_profile = facts.one(release, ATLAS.resourceProfile, code="dataset.release")
        scheme = _iri(
            facts.one(release, ATLAS.inScheme, code="dataset.release"),
            code="dataset.release",
            label="release scheme",
        )
        if not _has_carrier_type(asserted, scheme, ATLAS.ResourceScheme, inventory):
            _fail("dataset.release", f"{release} names an unknown ResourceScheme")
        if not facts.contains(scheme, ATLAS.resourceProfile, release_profile):
            _fail("dataset.release", f"{release} profile differs from {scheme}")
        if not facts.contains(scheme, ATLAS.supportedRing, release_ring):
            _fail("dataset.release", f"{release} ring is not supported by {scheme}")
        release_metadata[release] = (release_ring, release_profile, scheme)
        has_member = False
        for member in facts.objects(release, PROV.hadMember):
            has_member = True
            if not _is_resource_node(asserted, member, inventory):
                _fail("dataset.release", f"{release} contains non-resource {member}")
            if not facts.contains(member, ATLAS.inRelease, release):
                _fail("dataset.release", f"{member} lacks inverse inRelease for {release}")
        if not has_member:
            _fail("dataset.release", f"{release} has no prov:hadMember")
    for resource in _resource_nodes(asserted, inventory):
        release = _iri(
            facts.one(resource, ATLAS.inRelease, code="dataset.release"), code="dataset.release", label="inRelease"
        )
        declared = release_metadata.get(release)
        if declared is None or not facts.contains(release, PROV.hadMember, resource):
            _fail("dataset.release", f"{resource} is not a closed member of {release}")
        release_ring, release_profile, release_scheme = declared
        resource_ring = facts.one(resource, ATLAS.semanticRing, code="dataset.release")
        if resource_ring != release_ring:
            _fail("dataset.release", f"{resource} ring differs from {release}")
        resource_scheme = facts.one(resource, ATLAS.inScheme, code="dataset.release")
        if resource_scheme != release_scheme:
            _fail("dataset.release", f"{resource} scheme differs from {release}")
        resource_profile = facts.one(resource, ATLAS.resourceProfile, code="dataset.release")
        if resource_profile != release_profile:
            _fail("dataset.release", f"{resource} profile differs from {release}")


def _check_label_integrity(
    asserted: Graph,
    inventory: SemanticInventory | None = None,
) -> None:
    """Enforce cross-record SKOS-XL invariants without per-node SPARQL queries."""

    facts = _asserted_facts(asserted, inventory)
    role_predicates = tuple(XL_TO_SKOS)
    for resource in _resource_nodes(asserted, inventory):
        release = _iri(
            facts.one(resource, ATLAS.inRelease, code="dataset.label-integrity"),
            code="dataset.label-integrity",
            label="resource release",
        )
        source_records = set(facts.objects(resource, ATLAS.sourceRecord))
        labels_by_role: dict[URIRef, set[URIRef]] = {}
        literals_by_role: dict[URIRef, set[Literal]] = {}
        for role in role_predicates:
            labels: set[URIRef] = set()
            literals: set[Literal] = set()
            for raw_label in facts.objects(resource, role):
                label = _iri(
                    raw_label,
                    code="dataset.label-integrity",
                    label="SKOS-XL label",
                )
                labels.add(label)
                if set(facts.objects(label, ATLAS.inRelease)) != {release}:
                    _fail(
                        "dataset.label-integrity",
                        f"{label} release differs from its resource {resource}",
                    )
                label_records = set(facts.objects(label, ATLAS.sourceRecord))
                if not source_records.intersection(label_records):
                    _fail(
                        "dataset.label-integrity",
                        f"{label} shares no SourceRecord with its resource {resource}",
                    )
                literal = facts.one(
                    label,
                    SKOSXL.literalForm,
                    code="dataset.label-integrity",
                )
                if not isinstance(literal, Literal):
                    _fail("dataset.label-integrity", f"{label} literalForm is not a literal")
                literals.add(literal)
            labels_by_role[role] = labels
            literals_by_role[role] = literals

        preferred_languages = [(literal.language or "").lower() for literal in literals_by_role[SKOSXL.prefLabel]]
        if len(preferred_languages) != len(set(preferred_languages)):
            _fail(
                "dataset.label-integrity",
                f"{resource} has more than one preferred label in a language",
            )
        for index, first_role in enumerate(role_predicates):
            for second_role in role_predicates[index + 1 :]:
                if labels_by_role[first_role] & labels_by_role[second_role] or (
                    literals_by_role[first_role] & literals_by_role[second_role]
                ):
                    _fail(
                        "dataset.label-integrity",
                        f"{resource} reuses a label node or literal across SKOS-XL roles",
                    )


def _check_rdf_json_payload(
    literal: Any,
    *,
    node: URIRef,
    label: str,
    source_native: bool = False,
) -> bytes:
    """Prove one rdf:JSON literal canonical, and hand back the canonical bytes.

    Returning them is not a convenience. The proof already parsed the literal
    and re-encoded it; the caller that then needs a digest OVER those bytes
    would otherwise parse and re-encode the identical literal a second time,
    which at 590,561 source records is the whole check run twice.
    """

    if not isinstance(literal, Literal) or literal.datatype != RDF.JSON:
        _fail("dataset.native-payload", f"{node} {label} is not rdf:JSON")
    try:
        value = json.loads(
            str(literal),
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=_reject_float,
            parse_int=_parse_int,
            parse_constant=_reject_constant,
        )
        expected = (
            canonical_native_json_bytes(value) if source_native else canonical_json_bytes(value, terminal_lf=False)
        )
    except (json.JSONDecodeError, AtlasValidationError) as exc:
        _fail("dataset.native-payload", f"{node} {label} is invalid: {exc}")
    if str(literal).encode("utf-8") != expected:
        _fail("dataset.native-payload", f"{node} {label} is not canonical REF JSON")
    return expected


def _check_native_payloads(
    asserted: Graph,
    inventory: SemanticInventory | None = None,
    *,
    node_digests: _AssertedNodeDigests | None = None,
) -> None:
    for record in _carrier_nodes(asserted, ATLAS.SourceRecord, inventory):
        literal = _one(asserted, record, ATLAS.nativePayload, code="dataset.native-payload")
        canonical_payload = _check_rdf_json_payload(
            literal,
            node=record,
            label="nativePayload",
            source_native=True,
        )
        # atlas:sourceDigest ties a SourceRecord to the exact source bytes it
        # claims to represent: it must equal sha256 over this record's own
        # canonical nativePayload. Without this check, a record could carry a
        # payload copied from a different source record while still passing
        # every other gate. The canonical bytes are the ones the line above
        # just proved -- the digest is taken over the proof's own output, not
        # over a second encoding of the same literal.
        expected_source_digest = (
            "sha256:" + hashlib.sha256(canonical_payload).hexdigest()
        )
        stored_source_digest = _literal_text(
            _one(asserted, record, ATLAS.sourceDigest, code="dataset.native-payload"),
            code="dataset.native-payload",
            label="sourceDigest",
        )
        if stored_source_digest != expected_source_digest:
            _fail(
                "dataset.native-payload-digest",
                f"{record} sourceDigest does not match the sha256 of its nativePayload",
            )
    for scheme in _carrier_nodes(asserted, ATLAS.ResourceScheme, inventory):
        payloads = list(asserted.objects(scheme, ATLAS.descriptorPayload))
        if len(payloads) > 1:
            _fail("dataset.native-payload", f"{scheme} has more than one descriptorPayload")
        if payloads:
            _check_rdf_json_payload(payloads[0], node=scheme, label="descriptorPayload")
    for source in _carrier_nodes(asserted, ATLAS.RegistrySource, inventory):
        literal = _one(asserted, source, ATLAS.descriptorPayload, code="dataset.native-payload")
        _check_rdf_json_payload(literal, node=source, label="descriptorPayload")
    for policy in _carrier_nodes(asserted, ATLAS.EditorialPolicy, inventory):
        literal = _one(asserted, policy, ATLAS.policyPayload, code="dataset.native-payload")
        _check_rdf_json_payload(literal, node=policy, label="policyPayload")
        expected_digest = _node_digest(asserted, policy, node_digests)
        expected_id = URIRef("urn:ref:atlas-policy:" + expected_digest.removeprefix("sha256:"))
        if policy != expected_id:
            _fail("dataset.policy-identity", f"{policy} is not its content-derived IRI")


def _check_source_accounting(
    asserted: Graph,
    accounting: Mapping[str, Any],
    inventory: SemanticInventory | None = None,
) -> None:
    facts = _asserted_facts(asserted, inventory)
    graph_records = _carrier_nodes(asserted, ATLAS.SourceRecord, inventory)
    graph_releases = _carrier_nodes(asserted, ATLAS.SourceRelease, inventory)
    # One pass over the evidence bindings' own `atlas:evidenceSourceRecord`
    # replaces one reverse store lookup per disposition -- 590K of them at full
    # scale. Same pairs, same sets: the map is keyed on every subject carrying
    # the predicate, which is what `Graph.subjects(evidenceSourceRecord, record)`
    # enumerated, and each entry is consumed as an unordered set.
    bindings_by_record: dict[URIRef, set[URIRef]] = defaultdict(set)
    for binding, evidence_record in facts.subject_objects(ATLAS.evidenceSourceRecord):
        bindings_by_record[evidence_record].add(binding)
    inverse_balance: dict[URIRef, int] = {}
    input_releases: set[URIRef] = set()
    represented = excluded = unresolved = 0
    for source in accounting["inputs"]:
        source_release = URIRef(source["sourceRelease"])
        if source_release in input_releases:
            _fail("source.accounting", f"duplicate source release input {source_release}")
        input_releases.add(source_release)
        if source_release not in graph_releases:
            _fail("source.accounting", f"unknown source release input {source_release}")
        for disposition in source["dispositions"]:
            record = URIRef(disposition["sourceRecord"])
            if record in inverse_balance:
                _fail("source.accounting", f"duplicate disposition for {record}")
            inverse_balance[record] = 0
            if not _has_carrier_type(asserted, record, ATLAS.SourceRecord, inventory):
                _fail("source.accounting", f"disposition names unknown source record {record}")
            if not facts.contains(record, ATLAS.inSourceRelease, source_release):
                _fail("source.accounting", f"{record} is assigned to the wrong source release")
            status = disposition["status"]
            represented += status == "represented"
            excluded += status == "excluded"
            unresolved += status == "unresolved"
            ledger_resources = {
                URIRef(value) for value in disposition.get("atlasResources", [])
            }
            graph_resources = set(facts.objects(record, ATLAS.representsResource))
            if ledger_resources != graph_resources:
                _fail(
                    "source.accounting",
                    f"{record} represented resources differ across its ledger and bidirectional RDF links",
                )
            inverse_balance[record] = -len(ledger_resources)
            if status != "represented" and graph_resources:
                _fail("source.accounting", f"{record} is {status} but links a represented resource")
            for resource in ledger_resources:
                if not _is_resource_node(asserted, resource, inventory):
                    _fail("source.accounting", f"{record} names unknown Atlas resource {resource}")
            evidence_bindings = bindings_by_record.get(record, frozenset())
            graph_assertions = {
                assertion
                for evidence in evidence_bindings
                for assertion in facts.objects(evidence, RKAF.bindsAssertion)
            }
            ledger_assertions = {
                URIRef(value) for value in disposition.get("atlasAssertions", [])
            }
            if status == "represented" and not (
                ledger_resources or ledger_assertions
            ):
                _fail(
                    "source.accounting",
                    f"{record} is represented but names no Atlas resource or assertion",
                )
            mapping_assertions = {
                assertion
                for assertion in graph_assertions
                if _has_carrier_type(asserted, assertion, ATLAS.MappingAssertion, inventory)
            }
            # Volunteering `atlasAssertions` is not what makes the comparison
            # happen. Omitting the key used to skip it outright, so a record
            # that also represented a resource -- which the mapping rule below
            # exempts -- could carry mapping evidence that no ledger anywhere
            # accounted for, and nothing noticed. The comparison now runs
            # whenever there is something to account for: assertions the
            # ledger already names, or a mapping the record's evidence
            # supports. A record whose evidence backs only source assignments
            # or native relations and whose ledger claims no assertion stays
            # silent, which is what most source records in a real distribution
            # look like.
            if (ledger_assertions or mapping_assertions) and ledger_assertions != graph_assertions:
                _fail(
                    "source.accounting",
                    f"{record} represented assertions differ across its ledger and evidence bindings",
                )
            if (
                mapping_assertions
                and not ledger_resources
                and ledger_assertions != mapping_assertions
            ):
                _fail(
                    "source.accounting",
                    f"{record} mapping assertions are not exactly source-accounted",
                )
            if status != "represented" and ledger_assertions:
                _fail(
                    "source.accounting",
                    f"{record} is {status} but names a represented assertion",
                )
            for assertion in ledger_assertions:
                if not facts.has_type(assertion, ATLAS.RelationAssertion):
                    _fail(
                        "source.accounting",
                        f"{record} names unknown Atlas assertion {assertion}",
                    )
    disposition_records = inverse_balance.keys()
    if disposition_records != graph_records:
        missing = sorted(map(str, graph_records - disposition_records))
        extra = sorted(map(str, disposition_records - graph_records))
        _fail(
            "source.accounting",
            f"source-record dispositions differ; missing={missing}, extra={extra}",
        )
    if input_releases != graph_releases:
        missing = sorted(map(str, graph_releases - input_releases))
        extra = sorted(map(str, input_releases - graph_releases))
        _fail(
            "source.accounting",
            f"source releases differ; missing={missing}, extra={extra}",
        )
    # Left on the store deliberately: this sweep raises on its FIRST unreconciled
    # pair, so the order rdflib's predicate index yields them in is part of the
    # observed failure and reproducing it from a parse-ordered index would be a
    # coincidence, not a guarantee. Only the containment test below is folded.
    for resource, record in asserted.subject_objects(ATLAS.sourceRecord):
        if not _is_resource_node(asserted, resource, inventory):
            continue
        if not facts.contains(record, ATLAS.representsResource, resource):
            _fail(
                "source.accounting",
                f"{resource} sourceRecord link is not reconciled by {record}",
            )
        if record in inverse_balance:
            inverse_balance[record] += 1
    unbalanced_record = next(
        (record for record, balance in inverse_balance.items() if balance),
        None,
    )
    if unbalanced_record is not None:
        _fail(
            "source.accounting",
            f"{unbalanced_record} represented resources differ across its ledger and bidirectional RDF links",
        )
    expected_totals = {
        "sourceReleases": len(accounting["inputs"]),
        "sourceRecords": len(inverse_balance),
        "represented": represented,
        "excluded": excluded,
        "unresolved": unresolved,
    }
    if accounting["totals"] != expected_totals:
        _fail("source.accounting", "source-accounting totals do not reconcile")


def _check_counts(
    manifest: Mapping[str, Any],
    graphs: Mapping[str, Graph],
    inventory: SemanticInventory | None = None,
) -> None:
    inventory = inventory or _semantic_inventory_from_graphs(graphs)
    expected = {
        "crossRingRelationAssertions": len(inventory.nodes(ATLAS.CrossRingRelationAssertion)),
        "releases": len(inventory.nodes(ATLAS.AtlasRelease)),
        "resources": inventory.resource_count,
        "identifiers": len(inventory.nodes(ATLAS.Identifier)),
        "labels": len(inventory.nodes(SKOSXL.Label)),
        "sourceRecords": len(inventory.nodes(ATLAS.SourceRecord)),
        "relationAssertions": sum(
            len(inventory.nodes(assertion_type)) for assertion_type in ASSERTION_TYPES
        ),
        "mappingAssertions": len(inventory.nodes(ATLAS.MappingAssertion)),
        "nativeRelationAssertions": len(inventory.nodes(ATLAS.NativeRelationAssertion)),
        "sourceAssignments": len(inventory.nodes(ATLAS.SourceAssignment)),
        "projectedRelations": len(inventory.projection_nodes),
        "derivedRelations": len(inventory.derived_nodes),
    }
    if manifest["counts"] != expected:
        _fail("dataset.counts", f"manifest counts differ; expected={expected}, actual={manifest['counts']}")


def derived_input_digest(
    asserted: Graph,
    inputs: Iterable[URIRef],
    node_digests: _AssertedNodeDigests | None = None,
) -> str:
    """Pin the exact content of the assertions one derived row was drawn from.

    The input assertions no longer publish their own digest, so it is
    recomputed from each one's asserted facts; `rdf_node_digest` excludes the
    self-digest predicates, so the value is what the removed triple carried.
    """

    rows = []
    for assertion in sorted(set(inputs)):
        if (assertion, RDF.type, None) not in asserted:
            _fail(
                "dataset.derived-input",
                f"derived input {assertion} is not an asserted node",
            )
        rows.append(
            {
                "assertion": str(assertion),
                "contentDigest": _node_digest(asserted, assertion, node_digests),
            }
        )
    return canonical_sha256({"assertions": rows}, terminal_lf=False)


def _check_derived(
    asserted: Graph,
    projection: Graph,
    derived: Graph,
    current: Mapping[AssertionTriple, AssertionSupport],
    derived_nodes: AbstractSet[URIRef] | None = None,
    *,
    node_digests: _AssertedNodeDigests | None = None,
) -> None:
    if derived_nodes is None:
        derived_nodes = set(derived.subjects(RDF.type, ATLAS.DerivedRelation))
    if not derived_nodes:
        return
    relation_policies = _relation_policies()
    active_assertions = {assertion for assertions in current.values() for assertion in assertions}
    direct_relations = set(current)
    for node in derived_nodes:
        if (node, RDF.type, ATLAS.RelationAssertion) in derived or any(
            (node, RDF.type, assertion_type) in derived for assertion_type in ASSERTION_TYPES
        ):
            _fail("dataset.derived-authority", f"{node} is both derived and authoritative")
        inputs = set(derived.objects(node, ATLAS.derivedFromAssertion))
        if not inputs or not inputs <= active_assertions:
            _fail(
                "dataset.derived",
                f"{node} has missing, unknown, withdrawn, or superseded input assertions",
            )
        stored_input_digest = _literal_text(
            _one(derived, node, RKAF.inputDigest, code="dataset.derived-input"),
            code="dataset.derived-input",
            label="inputDigest",
        )
        expected_input_digest = derived_input_digest(asserted, inputs, node_digests)
        if stored_input_digest != expected_input_digest:
            _fail("dataset.derived-input", f"{node} inputDigest differs from its assertion inputs")
        subject = _iri(
            _one(derived, node, ATLAS.relationSubject, code="dataset.derived"),
            code="dataset.derived",
            label="derived subject",
        )
        predicate = _iri(
            _one(derived, node, ATLAS.relationPredicate, code="dataset.derived"),
            code="dataset.derived",
            label="derived predicate",
        )
        obj = _iri(
            _one(derived, node, ATLAS.relationObject, code="dataset.derived"),
            code="dataset.derived",
            label="derived object",
        )
        ring = _iri(
            _one(derived, node, ATLAS.semanticRing, code="dataset.derived"),
            code="dataset.derived",
            label="derived ring",
        )
        if not any((subject, RDF.type, resource_type) in asserted for resource_type in RESOURCE_TYPES):
            _fail("dataset.derived", f"{node} subject is not an asserted Atlas resource")
        if not any((obj, RDF.type, resource_type) in asserted for resource_type in RESOURCE_TYPES):
            _fail("dataset.derived", f"{node} object is not an asserted Atlas resource")
        if ring not in asserted.objects(subject, ATLAS.semanticRing) or ring not in asserted.objects(
            obj, ATLAS.semanticRing
        ):
            _fail("dataset.derived", f"{node} endpoint ring differs")
        allowed = relation_policies.get(ring, {}).get(ATLAS.MappingAssertion, frozenset()) | relation_policies.get(
            ring, {}
        ).get(ATLAS.NativeRelationAssertion, frozenset())
        if predicate not in allowed:
            _fail("dataset.derived", f"{node} predicate is not allowed for its ring")

        rule = _iri(
            _one(derived, node, ATLAS.derivationRule, code="dataset.derived-rule"),
            code="dataset.derived-rule",
            label="derivation rule",
        )
        engine = _iri(
            _one(derived, node, ATLAS.engine, code="dataset.derived-rule"),
            code="dataset.derived-rule",
            label="derivation engine",
        )
        engine_version = _literal_text(
            _one(derived, node, ATLAS.engineVersion, code="dataset.derived-rule"),
            code="dataset.derived-rule",
            label="engineVersion",
        )
        if (rule, engine, engine_version) != (
            EXACT_MATCH_TRANSITIVITY_RULE,
            DERIVATION_ENGINE,
            DERIVATION_ENGINE_VERSION,
        ):
            _fail("dataset.derived-rule", f"{node} uses an unallowlisted rule or engine")
        if ring != ATLAS.subject or predicate != SKOS.exactMatch or subject == obj or len(inputs) < 2:
            _fail("dataset.derived-rule", f"{node} does not match the exactMatch transitivity rule")
        adjacency: dict[URIRef, set[URIRef]] = defaultdict(set)
        edges: set[frozenset[URIRef]] = set()
        for assertion in inputs:
            assertion_type = _assertion_type(asserted, assertion)
            _, triple = _assertion_basis(asserted, assertion)
            if assertion_type != ATLAS.MappingAssertion or triple[1] != SKOS.exactMatch:
                _fail("dataset.derived-rule", f"{node} cites a non-exactMatch input")
            if triple[0] == triple[2]:
                _fail("dataset.derived-rule", f"{node} cites a reflexive exactMatch input")
            edge = frozenset((triple[0], triple[2]))
            if edge in edges:
                _fail("dataset.derived-rule", f"{node} cites a duplicate exactMatch edge")
            edges.add(edge)
            adjacency[triple[0]].add(triple[2])
            adjacency[triple[2]].add(triple[0])
        frontier = [subject]
        visited = {subject}
        while frontier:
            current = frontier.pop()
            for target in adjacency[current] - visited:
                visited.add(target)
                frontier.append(target)
        graph_nodes = set(adjacency)
        if (
            obj not in visited
            or visited != graph_nodes
            or len(edges) != len(graph_nodes) - 1
            or adjacency[subject] == set()
            or len(adjacency[subject]) != 1
            or len(adjacency[obj]) != 1
            or any(len(adjacency[path_node]) != 2 for path_node in graph_nodes - {subject, obj})
        ):
            _fail(
                "dataset.derived-rule",
                f"{node} inputs are not one exact simple path between its endpoints",
            )

        stored_node_digest = _literal_text(
            _one(derived, node, ATLAS.contentDigest, code="dataset.derived-identity"),
            code="dataset.derived-identity",
            label="contentDigest",
        )
        expected_id = URIRef("urn:ref:atlas-derived:" + stored_node_digest.removeprefix("sha256:"))
        if node != expected_id:
            _fail("dataset.derived-identity", f"{node} is not its content-derived IRI")
        if (
            (subject, predicate, obj) in direct_relations
            or (subject, predicate, obj) in projection
            or (
                predicate == SKOS.exactMatch
                and (
                    (obj, predicate, subject) in direct_relations
                    or (obj, predicate, subject) in projection
                )
            )
        ):
            _fail(
                "dataset.derived-authority",
                f"{node} duplicates a directly asserted projection relation",
            )


def _check_reasoning_isolation(
    derived: Graph,
    current: Mapping[AssertionTriple, AssertionSupport],
    exact_index: ExactMatchIndex | None = None,
    derived_nodes: AbstractSet[URIRef] | None = None,
) -> int:
    exact_index = exact_index or _build_exact_match_index(current)
    if derived_nodes is None:
        derived_nodes = set(derived.subjects(RDF.type, ATLAS.DerivedRelation))
    if not derived_nodes:
        return exact_index.inferred_count
    direct_mappings = {triple for triple in current if triple[1] in SKOS_MAPPING_PREDICATES}
    assertion_triples = {assertion: triple for triple, assertions in current.items() for assertion in assertions}
    for node in sorted(derived_nodes):
        output = (
            _iri(
                _one(derived, node, ATLAS.relationSubject, code="reasoning.authority"),
                code="reasoning.authority",
                label="derived subject",
            ),
            _iri(
                _one(derived, node, ATLAS.relationPredicate, code="reasoning.authority"),
                code="reasoning.authority",
                label="derived predicate",
            ),
            _iri(
                _one(derived, node, ATLAS.relationObject, code="reasoning.authority"),
                code="reasoning.authority",
                label="derived object",
            ),
        )
        replay = Graph()
        for assertion in derived.objects(node, ATLAS.derivedFromAssertion):
            input_triple = assertion_triples.get(assertion)
            if input_triple is not None:
                replay.add(input_triple)
        replay.add((SKOS.exactMatch, RDF.type, OWL.TransitiveProperty))
        replay.add((SKOS.exactMatch, RDF.type, OWL.SymmetricProperty))
        DeductiveClosure(
            OWLRL_Semantics,
            axiomatic_triples=False,
            datatype_axioms=False,
        ).expand(replay)
        if output in direct_mappings or output not in replay:
            _fail(
                "reasoning.authority",
                f"{node} is not a newly inferred mapping under the pinned reasoner",
            )
    return exact_index.inferred_count


def acceptance_gate_evidence_digest(
    name: str,
    *,
    inputs: Mapping[str, Any],
    validator: Mapping[str, Any],
) -> str:
    """Bind one passed gate receipt to the validator and exact evaluated inputs."""

    return canonical_sha256(
        {
            "inputs": dict(inputs),
            "name": name,
            "status": "passed",
            "validator": dict(validator),
        },
        terminal_lf=False,
    )


def _construction_digest(value: Any) -> str:
    """Use the producer-independent digest domain for construction receipts."""

    return canonical_sha256(value)


def _rdf_pack_ownership_receipt(pack: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "contentDigest": pack["content"]["digest"],
        "packId": pack["packId"],
        "path": pack["path"],
    }


def _check_construction_input_path_identities(
    releases: Iterable[Mapping[str, Any]],
    catalog_inputs: Iterable[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Close reused input paths over one identity and return the exact global pins."""

    identities_by_path: dict[str, tuple[str, int]] = {}
    pins = chain(
        catalog_inputs,
        *(release["inputs"] for release in releases),
    )
    for pin in pins:
        path = pin["path"]
        identity = (pin["sha256"], pin["byteLength"])
        previous = identities_by_path.setdefault(path, identity)
        if previous != identity:
            _fail(
                "construction.release",
                f"input path {path} has conflicting pinned identities",
            )
    return [
        {
            "byteLength": byte_length,
            "path": path,
            "sha256": digest,
        }
        for path, (digest, byte_length) in sorted(identities_by_path.items())
    ]


def _check_adapter_recipe_input_path_identities(
    releases: Iterable[Mapping[str, Any]],
) -> None:
    """Require every reused adapter module path to pin the same file bytes."""

    identities_by_path: dict[str, tuple[str, int]] = {}
    for release in releases:
        for pin in release["adapterRecipeInputs"]:
            path = pin["path"]
            identity = (pin["sha256"], pin["byteLength"])
            previous = identities_by_path.setdefault(path, identity)
            if previous != identity:
                _fail(
                    "construction.release",
                    f"adapter recipe path {path} has conflicting pinned identities",
                )


def _check_construction_summary_identity(
    manifest: Mapping[str, Any],
    producer_validation: Mapping[str, Any],
    construction_summary: Mapping[str, Any],
    member_digests: Mapping[str, str],
) -> None:
    """Recompute every construction claim available without source bytes or RDF."""

    payload = dict(construction_summary)
    actual_payload_digest = payload.pop("canonicalPayloadDigest")
    if actual_payload_digest != canonical_sha256(payload, terminal_lf=False):
        _fail(
            "construction.identity",
            "construction summary canonicalPayloadDigest differs",
        )
    asserted_inventory_digest = next(
        row["inventoryDigest"]
        for row in manifest["graphs"]
        if row["role"] == "asserted"
    )
    expected_envelope = {
        "assertedInventoryDigest": asserted_inventory_digest,
        "contractDigest": manifest["binding"]["contractDigest"],
        "distributionId": manifest["distributionId"],
        "sourceAccountingDigest": member_digests["atlas-source-accounting.json"],
    }
    for field, expected in expected_envelope.items():
        if construction_summary[field] != expected:
            _fail("construction.identity", f"construction summary {field} differs")
    if construction_summary["languageScope"] != ATLAS_LANGUAGE_SCOPE:
        _fail(
            "construction.language-scope",
            "construction summary language scope differs from the Atlas build",
        )

    releases = construction_summary["releases"]
    release_keys = [row["key"] for row in releases]
    if release_keys != sorted(release_keys) or len(release_keys) != len(set(release_keys)):
        _fail("construction.release", "construction releases must have unique sorted keys")
    if construction_summary["releaseCount"] != len(releases):
        _fail("construction.release", "construction release count differs")
    if construction_summary["releaseInventoryDigest"] != _construction_digest(releases):
        _fail("construction.release", "construction release inventory digest differs")
    semantic_input_pins = _check_construction_input_path_identities(
        releases,
        construction_summary["catalog"]["inputs"],
    )
    _check_adapter_recipe_input_path_identities(releases)

    releases_by_key = {row["key"]: row for row in releases}
    source_release_keys: dict[str, str] = {}
    owned_rdf_paths: list[str] = []
    aggregate_record_counts: Counter[str] = Counter()
    for release in releases:
        key = release["key"]
        source_release = release["sourceRelease"]
        if source_release in source_release_keys:
            _fail("construction.release", f"source release {source_release} has multiple units")
        source_release_keys[source_release] = key
        inputs = release["inputs"]
        input_sort_keys = [
            (row["path"], row["role"], row["sha256"])
            for row in inputs
        ]
        if input_sort_keys != sorted(input_sort_keys) or len(input_sort_keys) != len(set(input_sort_keys)):
            _fail("construction.release", f"{key} input pins are not unique and sorted")
        if release["inputFileCount"] != len(inputs):
            _fail("construction.release", f"{key} input file count differs")
        if release["inputInventoryDigest"] != _construction_digest(inputs):
            _fail("construction.release", f"{key} input inventory digest differs")
        adapter_recipe_inputs = release["adapterRecipeInputs"]
        adapter_paths = [row["path"] for row in adapter_recipe_inputs]
        if adapter_paths != sorted(adapter_paths) or len(adapter_paths) != len(
            set(adapter_paths)
        ):
            _fail(
                "construction.release",
                f"{key} adapter recipe inputs are not unique and sorted",
            )
        if release["adapterRecipeInputCount"] != len(adapter_recipe_inputs):
            _fail("construction.release", f"{key} adapter recipe input count differs")
        expected_adapter_recipe = _construction_digest(
            {
                "constructionProfile": construction_summary["profile"],
                "inputs": adapter_recipe_inputs,
                "kind": release["kind"],
            }
        )
        if release["adapterRecipeDigest"] != expected_adapter_recipe:
            _fail("construction.release", f"{key} adapter recipe digest differs")
        base_payload = {
            "adapterRecipeDigest": release["adapterRecipeDigest"],
            **(
                {"atlasRelease": release["atlasRelease"]}
                if "atlasRelease" in release
                else {}
            ),
            "contractDigest": construction_summary["contractDigest"],
            "constructionProfile": construction_summary["profile"],
            "inputInventoryDigest": release["inputInventoryDigest"],
            "key": key,
            "kind": release["kind"],
            "languageScope": construction_summary["languageScope"],
            **(
                {"registrySource": release["registrySource"]}
                if "registrySource" in release
                else {}
            ),
            **(
                {"resourceProfile": release["resourceProfile"]}
                if "resourceProfile" in release
                else {}
            ),
            **({"scheme": release["scheme"]} if "scheme" in release else {}),
            "semanticRing": release["semanticRing"],
            "sourceRelease": source_release,
        }
        if release["baseBuildKey"] != _construction_digest(base_payload):
            _fail("construction.release", f"{key} base build key differs")

        endpoint_dependencies = release["endpointDependencies"]
        dependency_keys = [dependency["releaseKey"] for dependency in endpoint_dependencies]
        if dependency_keys != sorted(dependency_keys) or len(dependency_keys) != len(set(dependency_keys)):
            _fail("construction.release", f"{key} endpoint dependencies are not unique and sorted")
        for dependency in endpoint_dependencies:
            dependency_key = dependency["releaseKey"]
            target = releases_by_key.get(dependency_key)
            if target is None or dependency_key == key:
                _fail("construction.release", f"{key} has a self or unknown endpoint dependency")
            if (
                dependency["sourceRelease"] != target["sourceRelease"]
                or dependency["baseBuildKey"] != target["baseBuildKey"]
            ):
                _fail("construction.release", f"{key} endpoint dependency {dependency_key} differs")
        expected_build_key = _construction_digest(
            {
                "baseBuildKey": release["baseBuildKey"],
                "constructionProfile": construction_summary["profile"],
                "endpointDependencies": endpoint_dependencies,
            }
        )
        if release["buildKey"] != expected_build_key:
            _fail("construction.release", f"{key} build key differs")

        if set(release["recordCounts"]) != set(COMPACT_ROLE_COUNT_FIELDS.values()):
            _fail("construction.counts", f"{key} record count fields differ")
        if not any(release["recordCounts"].values()):
            _fail("construction.counts", f"{key} owns no logical records")
        aggregate_record_counts.update(release["recordCounts"])

        expected_rdf_packs = sorted(
            (
                _rdf_pack_ownership_receipt(pack)
                for pack in manifest["packs"]
                if pack["kind"] == release["kind"]
                and pack["sourceReleases"] == [source_release]
            ),
            key=lambda pack: pack["path"],
        )
        if release["rdfPacks"] != expected_rdf_packs:
            _fail("construction.rdf", f"{key} RDF pack ownership differs")
        owned_rdf_paths.extend(pack["path"] for pack in release["rdfPacks"])

    if len(owned_rdf_paths) != len(set(owned_rdf_paths)):
        _fail("construction.rdf", "release RDF pack ownership overlaps")
    expected_owned_rdf_paths = {
        pack["path"]
        for pack in manifest["packs"]
        if pack["kind"] in {"sourceRelease", "mapping"}
    }
    if set(owned_rdf_paths) != expected_owned_rdf_paths:
        _fail("construction.rdf", "release RDF pack ownership is incomplete")

    catalog_packs = [pack for pack in manifest["packs"] if pack["kind"] == "catalog"]
    if len(catalog_packs) != 1:
        _fail("construction.rdf", "construction summary requires one catalog RDF pack")
    if construction_summary["catalog"]["rdfPack"] != _rdf_pack_ownership_receipt(catalog_packs[0]):
        _fail("construction.rdf", "catalog RDF pack ownership differs")
    asserted_paths = {
        pack["path"]
        for pack in manifest["packs"]
        if pack["graphCounts"]["asserted"]
    }
    if asserted_paths != expected_owned_rdf_paths | {catalog_packs[0]["path"]}:
        _fail("construction.rdf", "asserted RDF packs are not exactly construction-owned")

    catalog = construction_summary["catalog"]
    catalog_inputs = catalog["inputs"]
    catalog_input_sort_keys = [
        (row["path"], row["role"], row["sha256"])
        for row in catalog_inputs
    ]
    if catalog_input_sort_keys != sorted(catalog_input_sort_keys) or len(
        catalog_input_sort_keys
    ) != len(set(catalog_input_sort_keys)):
        _fail("construction.release", "catalog input pins are not unique and sorted")
    catalog_input_digest = _construction_digest(catalog_inputs)
    if catalog["inputInventoryDigest"] != catalog_input_digest:
        _fail("construction.release", "catalog input inventory digest differs")
    scheme_inventory = [
        {
            "atlasRelease": release["atlasRelease"],
            "key": release["key"],
            "resourceProfile": release["resourceProfile"],
            **(
                {"registrySource": release["registrySource"]}
                if "registrySource" in release
                else {}
            ),
            "semanticRing": release["semanticRing"],
            "scheme": release["scheme"],
        }
        for release in releases
        if release["kind"] == "sourceRelease"
    ]
    release_scheme_inventory_digest = _construction_digest(scheme_inventory)
    if catalog["releaseSchemeInventoryDigest"] != release_scheme_inventory_digest:
        _fail("construction.release", "catalog release-scheme inventory digest differs")
    expected_catalog_key = _construction_digest(
        {
            "contractDigest": construction_summary["contractDigest"],
            "catalogInputInventoryDigest": catalog_input_digest,
            "constructionProfile": construction_summary["profile"],
            "languageScope": construction_summary["languageScope"],
            "releaseSchemeInventoryDigest": release_scheme_inventory_digest,
        }
    )
    if catalog["buildKey"] != expected_catalog_key:
        _fail("construction.release", "catalog build key differs")

    expected_counts = {
        "resources": manifest["counts"]["resources"],
        "labels": manifest["counts"]["labels"],
        "statements": manifest["counts"]["relationAssertions"],
        "sourceRecords": manifest["counts"]["sourceRecords"],
        # The compact Release role is intentionally generic: it carries both
        # AtlasRelease and SourceRelease records.  The manifest counts only
        # AtlasRelease instances, while the producer proof independently
        # receipts the source-release cardinality.
        "releases": (
            manifest["counts"]["releases"]
            + producer_validation["sourceReleaseCount"]
        ),
        "identifiers": manifest["counts"]["identifiers"],
        "evidenceBindings": manifest["counts"]["relationAssertions"],
    }
    for field, expected in expected_counts.items():
        if aggregate_record_counts[field] != expected:
            _fail("construction.counts", f"construction aggregate {field} count differs")

    expected_producer_receipt = {
        "digest": member_digests[CONSTRUCTION_SUMMARY_FILE],
        "path": CONSTRUCTION_SUMMARY_FILE,
        "profile": "atlas-3-authenticated-construction-summary-v1",
        "releaseCount": construction_summary["releaseCount"],
        "releaseInventoryDigest": construction_summary["releaseInventoryDigest"],
    }
    if producer_validation["constructionSummary"] != expected_producer_receipt:
        _fail("construction.identity", "producer construction-summary receipt differs")
    semantic_construction = producer_validation.get("semanticConstruction")
    if semantic_construction is not None and (
        semantic_construction["inputFileCount"] != len(semantic_input_pins)
        or semantic_construction["inputInventoryDigest"]
        != _construction_digest(semantic_input_pins)
    ):
        _fail(
            "construction.identity",
            "producer construction input inventory differs",
        )


def _check_construction_accounting(
    construction_summary: Mapping[str, Any],
    accounting: Mapping[str, Any],
) -> None:
    accounting_rows = {
        row["sourceRelease"]: row for row in accounting["inputs"]
    }
    if len(accounting_rows) != len(accounting["inputs"]):
        _fail("construction.accounting", "source accounting has duplicate release rows")
    release_sources = {release["sourceRelease"] for release in construction_summary["releases"]}
    if set(accounting_rows) != release_sources:
        _fail("construction.accounting", "construction releases and accounting rows differ")
    for release in construction_summary["releases"]:
        expected = _construction_digest(accounting_rows[release["sourceRelease"]])
        if release["accountingRowDigest"] != expected:
            _fail(
                "construction.accounting",
                f"{release['key']} source-accounting row digest differs",
            )


def _construction_rdf_one(
    graph: Graph,
    subject: URIRef,
    predicate: URIRef,
    *,
    term_type: type[URIRef | Literal],
    asserted_facts: _AssertedFacts | None = None,
) -> Any:
    values = list(
        asserted_facts.objects(subject, predicate)
        if asserted_facts is not None
        else graph.objects(subject, predicate)
    )
    if len(values) != 1 or not isinstance(values[0], term_type):
        _fail(
            "construction.sample",
            f"{subject} must have one {predicate} of type {term_type.__name__}",
        )
    return values[0]


def _construction_atlas_name(value: Any, *, label: str) -> str:
    iri = str(value)
    namespace = str(ATLAS)
    if not iri.startswith(namespace) or len(iri) == len(namespace):
        _fail("construction.sample", f"{label} is not an Atlas vocabulary term")
    return iri[len(namespace) :]


def _construction_rkaf_name(value: Any, *, label: str) -> str:
    """Shorten a Rulespec term the same way an Atlas term is shortened.

    The compact projection carries local names, so a term Atlas adopted from
    Rulespec projects identically -- but it must still be read out of
    Rulespec's namespace, not minted in Atlas's.
    """

    iri = str(value)
    namespace = str(RKAF)
    if not iri.startswith(namespace) or len(iri) == len(namespace):
        _fail("construction.sample", f"{label} is not a Rulespec vocabulary term")
    return iri[len(namespace) :]


def _construction_record_role_or_none(
    graph: Graph,
    subject: URIRef,
) -> str | None:
    types = set(graph.objects(subject, RDF.type))
    candidates = {
        role
        for role, marker in (
            ("Resource", ATLAS.AtlasResource),
            ("Label", SKOSXL.Label),
            ("Statement", ATLAS.RelationAssertion),
            ("EvidenceBinding", RKAF.EvidenceBinding),
            ("SourceRecord", ATLAS.SourceRecord),
            ("Release", ATLAS.AtlasRelease),
            ("Release", ATLAS.SourceRelease),
            ("Identifier", ATLAS.Identifier),
            ("LifecycleEvent", RKAF.LifecycleEvent),
        )
        if marker in types
    }
    if not candidates:
        return None
    if len(candidates) != 1:
        _fail(
            "construction.sample",
            f"release-owned subject {subject} does not map to one compact role",
        )
    return candidates.pop()


def _construction_record_role(graph: Graph, subject: URIRef) -> str:
    role = _construction_record_role_or_none(graph, subject)
    if role is None:
        _fail(
            "construction.sample",
            f"release-owned subject {subject} does not map to one compact role",
        )
    return role


_SHACL_COMPONENTS_RE = re.compile(r"does not conform \[([^\]]*)\]")


def shacl_constraint_components(error: AtlasValidationError) -> list[str]:
    """Return the sorted constraint components one `shacl.data` verdict names.

    The component list is the contractual part of a SHACL rejection message:
    the corpus pins the code, this pins what an operator reads under it, and
    both validation modes must produce the same list (the release-tier
    cross-mode sweep is what proves that). Extracting it here rather than in a
    test keeps one definition of where the list lives in the message.
    """

    match = _SHACL_COMPONENTS_RE.search(error.detail)
    if match is None:
        _fail(
            "corpus.shacl-components",
            f"a {error.code} verdict named no constraint components: {error.detail[:200]}",
        )
    body = match.group(1)
    return body.split(", ") if body else []


def _construction_record_from_rdf(
    graph: Graph,
    subject: URIRef,
    role: str,
) -> dict[str, Any]:
    """Independently encode the RDF facts represented by one compact row."""

    # `atlas:contentDigest` is off the wire for every carrier whose IRI is not
    # derived from it, so the record's digest is recomputed from the node's own
    # facts. `rdf_node_digest` excludes the self-digest predicates, so this is
    # the same value the two IRI-bearing carriers still publish -- the retained
    # Parquet column never becomes comparand-less.
    record: dict[str, Any] = {
        "id": str(subject),
        "contentDigest": rdf_node_digest(graph, subject),
    }
    if role == "Resource":
        record.update(
            {
                "release": str(
                    _construction_rdf_one(
                        graph, subject, ATLAS.inRelease, term_type=URIRef
                    )
                ),
                "scheme": str(
                    _construction_rdf_one(
                        graph, subject, ATLAS.inScheme, term_type=URIRef
                    )
                ),
                "semanticRing": _construction_atlas_name(
                    _construction_rdf_one(
                        graph, subject, ATLAS.semanticRing, term_type=URIRef
                    ),
                    label=f"{subject} semantic ring",
                ),
                "resourceProfile": _construction_atlas_name(
                    _construction_rdf_one(
                        graph, subject, ATLAS.resourceProfile, term_type=URIRef
                    ),
                    label=f"{subject} resource profile",
                ),
                "sourceRecord": str(
                    _construction_rdf_one(
                        graph, subject, ATLAS.sourceRecord, term_type=URIRef
                    )
                ),
            }
        )
        definitions = [str(value) for value in graph.objects(subject, ATLAS.definition)]
        if len(definitions) > 1:
            _fail("construction.sample", f"{subject} has multiple definitions")
        if definitions:
            record["definition"] = definitions[0]
        notes = sorted(str(value) for value in graph.objects(subject, ATLAS.note))
        if notes:
            record["notes"] = notes
        notations = sorted(str(value) for value in graph.objects(subject, ATLAS.notation))
        if notations:
            record["notations"] = notations
        statuses = [str(value) for value in graph.objects(subject, ATLAS.recordStatus)]
        if len(statuses) > 1:
            _fail("construction.sample", f"{subject} has multiple record statuses")
        if statuses:
            record["recordStatus"] = statuses[0]
    elif role == "Label":
        claims: list[tuple[str, URIRef]] = []
        for predicate, label_role in (
            (SKOSXL.prefLabel, "preferred"),
            (SKOSXL.altLabel, "alternate"),
            (SKOSXL.hiddenLabel, "hidden"),
        ):
            claims.extend(
                (label_role, resource)
                for resource in graph.subjects(predicate, subject)
                if isinstance(resource, URIRef)
            )
        if len(claims) != 1:
            _fail("construction.sample", f"label {subject} does not have one role claim")
        literal = _construction_rdf_one(
            graph,
            subject,
            SKOSXL.literalForm,
            term_type=Literal,
        )
        if literal.language != "en":
            _fail("construction.sample", f"label {subject} is not English")
        record.update(
            {
                "resource": str(claims[0][1]),
                "labelRole": claims[0][0],
                "value": str(literal),
                "language": "en",
                "release": str(
                    _construction_rdf_one(
                        graph, subject, ATLAS.inRelease, term_type=URIRef
                    )
                ),
                "sourceRecord": str(
                    _construction_rdf_one(
                        graph, subject, ATLAS.sourceRecord, term_type=URIRef
                    )
                ),
            }
        )
    elif role == "Statement":
        types = set(graph.objects(subject, RDF.type))
        concrete_types = [
            marker
            for marker in (
                ATLAS.NativeRelationAssertion,
                ATLAS.MappingAssertion,
                ATLAS.SourceAssignment,
                ATLAS.CrossRingRelationAssertion,
            )
            if marker in types
        ]
        if len(concrete_types) != 1:
            _fail("construction.sample", f"statement {subject} has no unique concrete type")
        statement_type = concrete_types[0]
        record.update(
            {
                "statementType": _construction_atlas_name(
                    statement_type,
                    label=f"{subject} statement type",
                ),
                "subject": str(
                    _construction_rdf_one(graph, subject, RDF.subject, term_type=URIRef)
                ),
                "predicate": str(
                    _construction_rdf_one(graph, subject, RDF.predicate, term_type=URIRef)
                ),
                "object": str(
                    _construction_rdf_one(graph, subject, RDF.object, term_type=URIRef)
                ),
                "sourceRelease": str(
                    _construction_rdf_one(
                        graph, subject, ATLAS.sourceRelease, term_type=URIRef
                    )
                ),
                "targetRelease": str(
                    _construction_rdf_one(
                        graph, subject, ATLAS.targetRelease, term_type=URIRef
                    )
                ),
                "policy": str(
                    _construction_rdf_one(
                        graph, subject, ATLAS.governedByPolicy, term_type=URIRef
                    )
                ),
                "assertedAt": str(
                    _construction_rdf_one(
                        graph, subject, RKAF.assertedAt, term_type=Literal
                    )
                ),
                "assertionIdentityDigest": str(
                    _construction_rdf_one(
                        graph,
                        subject,
                        ATLAS.assertionIdentityDigest,
                        term_type=Literal,
                    )
                ),
            }
        )
        if statement_type == ATLAS.CrossRingRelationAssertion:
            for field, predicate in (
                ("sourceRing", ATLAS.sourceRing),
                ("targetRing", ATLAS.targetRing),
            ):
                record[field] = _construction_atlas_name(
                    _construction_rdf_one(
                        graph, subject, predicate, term_type=URIRef
                    ),
                    label=f"{subject} {field}",
                )
        else:
            record["semanticRing"] = _construction_atlas_name(
                _construction_rdf_one(
                    graph, subject, ATLAS.semanticRing, term_type=URIRef
                ),
                label=f"{subject} semantic ring",
            )
        supersedes = list(graph.objects(subject, RKAF.supersedesAssertion))
        if len(supersedes) > 1 or (supersedes and not isinstance(supersedes[0], URIRef)):
            _fail("construction.sample", f"statement {subject} has invalid supersession")
        if supersedes:
            record["supersedesAssertion"] = str(supersedes[0])
    elif role == "EvidenceBinding":
        record.update(
            {
                "statement": str(
                    _construction_rdf_one(
                        graph, subject, RKAF.bindsAssertion, term_type=URIRef
                    )
                ),
                "sourceRecord": str(
                    _construction_rdf_one(
                        graph,
                        subject,
                        ATLAS.evidenceSourceRecord,
                        term_type=URIRef,
                    )
                ),
                "evidenceSourceDigest": str(
                    _construction_rdf_one(
                        graph,
                        subject,
                        ATLAS.evidenceSourceDigest,
                        term_type=Literal,
                    )
                ),
                "attestor": str(
                    _construction_rdf_one(
                        graph, subject, RKAF.attestor, term_type=URIRef
                    )
                ),
                "attestorKind": str(
                    _construction_rdf_one(
                        graph, subject, RKAF.attestorKind, term_type=URIRef
                    )
                ),
                "assertionOrigin": str(
                    _construction_rdf_one(
                        graph, subject, RKAF.assertionOrigin, term_type=URIRef
                    )
                ),
                "epistemicBasis": str(
                    _construction_rdf_one(
                        graph, subject, RKAF.epistemicBasis, term_type=URIRef
                    )
                ),
                "evidenceRole": str(
                    _construction_rdf_one(
                        graph, subject, RKAF.evidenceRole, term_type=URIRef
                    )
                ),
                "evidentiaryFunction": str(
                    _construction_rdf_one(
                        graph, subject, RKAF.evidentiaryFunction, term_type=URIRef
                    )
                ),
                "decision": str(
                    _construction_rdf_one(
                        graph, subject, RKAF.decision, term_type=URIRef
                    )
                ),
                "attestedAt": str(
                    _construction_rdf_one(
                        graph, subject, RKAF.attestedAt, term_type=Literal
                    )
                ),
            }
        )
    elif role == "SourceRecord":
        payload_literal = _construction_rdf_one(
            graph,
            subject,
            ATLAS.nativePayload,
            term_type=Literal,
        )
        try:
            native_payload = json.loads(
                str(payload_literal),
                object_pairs_hook=_reject_duplicate_keys,
                parse_float=_reject_float,
                parse_int=_parse_int,
                parse_constant=_reject_constant,
            )
        except json.JSONDecodeError as exc:
            _fail("construction.sample", f"source record {subject} has invalid native JSON: {exc}")
        record.update(
            {
                "sourceRelease": str(
                    _construction_rdf_one(
                        graph, subject, ATLAS.inSourceRelease, term_type=URIRef
                    )
                ),
                "sourceDigest": str(
                    _construction_rdf_one(
                        graph, subject, ATLAS.sourceDigest, term_type=Literal
                    )
                ),
                "sourceLocator": str(
                    _construction_rdf_one(
                        graph, subject, ATLAS.sourceLocator, term_type=URIRef
                    )
                ),
                "nativePayload": native_payload,
            }
        )
        represented = list(graph.objects(subject, ATLAS.representsResource))
        if len(represented) > 1 or (represented and not isinstance(represented[0], URIRef)):
            _fail("construction.sample", f"source record {subject} has invalid resource ownership")
        if represented:
            record["representsResource"] = str(represented[0])
    elif role == "Release":
        types = set(graph.objects(subject, RDF.type))
        is_source = ATLAS.SourceRelease in types
        is_atlas = ATLAS.AtlasRelease in types
        if is_source == is_atlas:
            _fail("construction.sample", f"release {subject} has an ambiguous concrete type")
        record.update(
            {
                "releaseType": "SourceRelease" if is_source else "AtlasRelease",
                "identifier": str(
                    _construction_rdf_one(
                        graph, subject, DCTERMS.identifier, term_type=Literal
                    )
                ),
                "issued": str(
                    _construction_rdf_one(
                        graph, subject, DCTERMS.issued, term_type=Literal
                    )
                ),
            }
        )
        if is_source:
            record.update(
                {
                    "sourceDigest": str(
                        _construction_rdf_one(
                            graph, subject, ATLAS.sourceDigest, term_type=Literal
                        )
                    ),
                    "sourceLocator": str(
                        _construction_rdf_one(
                            graph, subject, ATLAS.sourceLocator, term_type=URIRef
                        )
                    ),
                }
            )
        else:
            record.update(
                {
                    "resourceProfile": _construction_atlas_name(
                        _construction_rdf_one(
                            graph, subject, ATLAS.resourceProfile, term_type=URIRef
                        ),
                        label=f"{subject} resource profile",
                    ),
                    "semanticRing": _construction_atlas_name(
                        _construction_rdf_one(
                            graph, subject, ATLAS.semanticRing, term_type=URIRef
                        ),
                        label=f"{subject} semantic ring",
                    ),
                    "scheme": str(
                        _construction_rdf_one(
                            graph, subject, ATLAS.inScheme, term_type=URIRef
                        )
                    ),
                    "membershipMode": _construction_rkaf_name(
                        _construction_rdf_one(
                            graph, subject, RKAF.membershipMode, term_type=URIRef
                        ),
                        label=f"{subject} membership mode",
                    ),
                }
            )
    elif role == "Identifier":
        record.update(
            {
                "identifierValue": str(
                    _construction_rdf_one(
                        graph, subject, ATLAS.identifierValue, term_type=Literal
                    )
                ),
                "identifierScheme": str(
                    _construction_rdf_one(
                        graph, subject, ATLAS.identifierScheme, term_type=URIRef
                    )
                ),
                "identifies": str(
                    _construction_rdf_one(
                        graph, subject, ATLAS.identifies, term_type=URIRef
                    )
                ),
                "sourceRecord": str(
                    _construction_rdf_one(
                        graph, subject, ATLAS.sourceRecord, term_type=URIRef
                    )
                ),
            }
        )
    elif role == "LifecycleEvent":
        source_records = sorted(
            str(value)
            for value in graph.objects(subject, ATLAS.sourceRecord)
            if isinstance(value, URIRef)
        )
        if not source_records or len(source_records) != len(
            list(graph.objects(subject, ATLAS.sourceRecord))
        ):
            _fail("construction.sample", f"lifecycle event {subject} has invalid source records")
        record.update(
            {
                "appliesTo": str(
                    _construction_rdf_one(
                        graph, subject, RKAF.appliesTo, term_type=URIRef
                    )
                ),
                "lifecycleEventKind": str(
                    _construction_rdf_one(
                        graph, subject, RKAF.lifecycleEventKind, term_type=URIRef
                    )
                ),
                "effectiveDate": str(
                    _construction_rdf_one(
                        graph, subject, RKAF.effectiveDate, term_type=Literal
                    )
                ),
                "sourceRecords": source_records,
            }
        )
        for field, predicate in (
            ("fromRelease", ATLAS.fromRelease),
            ("toRelease", ATLAS.toRelease),
        ):
            values = list(graph.objects(subject, predicate))
            if len(values) > 1 or (values and not isinstance(values[0], URIRef)):
                _fail("construction.sample", f"lifecycle event {subject} has invalid {field}")
            if values:
                record[field] = str(values[0])
    else:
        _fail("construction.sample", f"unsupported RDF sample role {role}")
    return _normalize_compact_record(role, record, path=f"rdf:{subject}")


# The derived Parquet view's column contract, restated here rather than
# imported. A parity check whose expected row comes from the same projection
# that wrote the row proves the projection is self-consistent and nothing
# else; the point of this list is that it is a second, independent statement
# of what each table must contain, next to a second, independent re-encoding
# of the RDF (`_construction_record_from_rdf`). If the emitter drops a column
# or renames one, this refuses; if this list drifts from the real schema, the
# caller's schema check refuses. The four `rkaf` warrant axes and
# `basedOnAttestation` are here for the reason the view carries them at all:
# the warrant defect that shipped in 2026-08 was a combination of axis values
# matching no sanctioned branch, and a comparison blind to four of the five
# axes cannot see it.
PARQUET_VIEW_COLUMNS: Mapping[str, tuple[str, ...]] = {
    "Resource": (
        "id",
        "release",
        "scheme",
        "semantic_ring",
        "resource_profile",
        "source_record",
        "definition",
        "notes",
        "notations",
        "record_status",
        "content_digest",
    ),
    "Label": (
        "id",
        "resource",
        "label_role",
        "value",
        "language",
        "release",
        "source_record",
        "content_digest",
    ),
    "Statement": (
        "id",
        "statement_type",
        "subject",
        "predicate",
        "object",
        "source_release",
        "target_release",
        "policy",
        "asserted_at",
        "assertion_identity_digest",
        "semantic_ring",
        "source_ring",
        "target_ring",
        "supersedes_assertion",
        "content_digest",
    ),
    "EvidenceBinding": (
        "id",
        "statement",
        "source_record",
        "evidence_source_digest",
        "attestor",
        "attestor_kind",
        "assertion_origin",
        "epistemic_basis",
        "evidence_role",
        "evidentiary_function",
        "based_on_attestation",
        "decision",
        "attested_at",
        "content_digest",
    ),
    "SourceRecord": (
        "id",
        "source_release",
        "source_digest",
        "source_locator",
        "native_payload",
        "represents_resource",
        "content_digest",
    ),
    "Release": (
        "id",
        "release_type",
        "identifier",
        "issued",
        "source_digest",
        "source_locator",
        "resource_profile",
        "semantic_ring",
        "scheme",
        "membership_mode",
        "content_digest",
    ),
    "Identifier": (
        "id",
        "identifier_value",
        "identifier_scheme",
        "identifies",
        "source_record",
        "content_digest",
    ),
    "LifecycleEvent": (
        "id",
        "applies_to",
        "lifecycle_event_kind",
        "effective_date",
        "source_records",
        "from_release",
        "to_release",
        "content_digest",
    ),
}
#: Columns carried as the digest's 32 raw bytes rather than its `sha256:` text.
PARQUET_VIEW_DIGEST_COLUMNS = frozenset(
    {
        "assertion_identity_digest",
        "content_digest",
        "evidence_source_digest",
        "source_digest",
    }
)


def parquet_view_column(field: str) -> str:
    """Return the Parquet column one compact record field is carried in."""

    return re.sub(r"(?<!^)(?=[A-Z])", "_", field).lower()


def parquet_row_from_rdf(
    graph: Graph,
    subject: URIRef,
    role: str,
) -> dict[str, Any]:
    """Independently re-encode one RDF record as its derived Parquet row.

    The comparand for the RDF<->Parquet parity check, and deliberately on this
    side of the boundary: the producer writes the tables, and nothing the
    producer computed is allowed to stand on both sides of the comparison.

    ``native_payload`` is taken as the ``atlas:nativePayload`` literal's exact
    lexical bytes rather than re-encoded from the parsed value, so the column
    is proven against the RDF by byte equality instead of by two encoders
    agreeing -- two encoders that could agree by sharing a bug.
    """

    columns = PARQUET_VIEW_COLUMNS.get(role)
    if columns is None:
        _fail("construction.parquet", f"unsupported Parquet view role {role!r}")
    record = _construction_record_from_rdf(graph, subject, role)
    row: dict[str, Any] = dict.fromkeys(columns)
    for field, value in record.items():
        if field == "canonicalPayloadDigest":
            continue
        column = parquet_view_column(field)
        if column not in row:
            _fail(
                "construction.parquet",
                f"{subject} carries {field} but the {role} table has no {column} column",
            )
        row[column] = value
    for column in columns:
        if column in PARQUET_VIEW_DIGEST_COLUMNS and row[column] is not None:
            row[column] = bytes.fromhex(_digest_text_value(row[column], column))
    if role == "SourceRecord":
        row["native_payload"] = str(
            _construction_rdf_one(graph, subject, ATLAS.nativePayload, term_type=Literal)
        ).encode("utf-8")
    return row


def _digest_text_value(value: Any, label: str) -> str:
    if not isinstance(value, str) or DIGEST_RE.fullmatch(value) is None:
        _fail("construction.parquet", f"{label} is not a lowercase sha256 digest")
    return value.removeprefix("sha256:")


def check_parquet_row_against_rdf(
    graph: Graph,
    subject: URIRef,
    role: str,
    row: Mapping[str, Any],
) -> None:
    """Refuse one Parquet row that the asserted RDF does not say.

    Two byte comparisons carry the source-record payload: the column against
    the literal, and its SHA-256 against the ``source_digest`` column the same
    row publishes.  ``atlas:sourceDigest`` is what a citation resolves
    through, so a payload column that drifted from it would be a silent
    mis-citation rather than a loud failure.
    """

    expected = parquet_row_from_rdf(graph, subject, role)
    observed = dict(row)
    if observed != expected:
        differing = sorted(
            column
            for column in set(expected) | set(observed)
            if expected.get(column) != observed.get(column)
        )
        _fail(
            "construction.parquet",
            f"{subject} Parquet row differs from its RDF facts in {differing}",
        )
    if role == "SourceRecord" and hashlib.sha256(observed["native_payload"]).digest() != observed["source_digest"]:
        _fail(
            "construction.parquet",
            f"{subject} Parquet native_payload does not hash to its source_digest column",
        )


def _construction_source_record_owner(
    asserted: Graph,
    source_record: URIRef,
    source_owner: Mapping[str, str],
    *,
    asserted_facts: _AssertedFacts | None = None,
) -> str | None:
    source_release = _construction_rdf_one(
        asserted,
        source_record,
        ATLAS.inSourceRelease,
        term_type=URIRef,
        asserted_facts=asserted_facts,
    )
    return source_owner.get(str(source_release))


def _construction_statement_source_record(
    asserted: Graph,
    statement: URIRef,
    *,
    asserted_facts: _AssertedFacts | None = None,
    bindings_by_statement: Mapping[URIRef, Sequence[URIRef]] | None = None,
) -> URIRef:
    bindings = list(
        bindings_by_statement.get(statement, ())
        if bindings_by_statement is not None
        else asserted.subjects(RKAF.bindsAssertion, statement)
    )
    if len(bindings) != 1 or not isinstance(bindings[0], URIRef):
        _fail(
            "construction.sample",
            f"statement {statement} has no unique RDF evidence binding",
        )
    return _construction_rdf_one(
        asserted,
        bindings[0],
        ATLAS.evidenceSourceRecord,
        term_type=URIRef,
        asserted_facts=asserted_facts,
    )


def _construction_compact_owner(
    asserted: Graph,
    subject: URIRef,
    role: str,
    *,
    source_owner: Mapping[str, str],
    atlas_owner: Mapping[str, str],
    asserted_facts: _AssertedFacts | None = None,
    bindings_by_statement: Mapping[URIRef, Sequence[URIRef]] | None = None,
) -> str | None:
    """Resolve one logical RDF record to its construction release."""

    if role in {"Resource", "Label"}:
        release = _construction_rdf_one(
            asserted,
            subject,
            ATLAS.inRelease,
            term_type=URIRef,
            asserted_facts=asserted_facts,
        )
        return atlas_owner.get(str(release))
    if role == "SourceRecord":
        return _construction_source_record_owner(
            asserted,
            subject,
            source_owner,
            asserted_facts=asserted_facts,
        )
    if role == "Release":
        if (subject, RDF.type, ATLAS.SourceRelease) in asserted:
            return source_owner.get(str(subject))
        return atlas_owner.get(str(subject))
    if role == "Identifier":
        resource = _construction_rdf_one(
            asserted,
            subject,
            ATLAS.identifies,
            term_type=URIRef,
            asserted_facts=asserted_facts,
        )
        release = _construction_rdf_one(
            asserted,
            resource,
            ATLAS.inRelease,
            term_type=URIRef,
            asserted_facts=asserted_facts,
        )
        return atlas_owner.get(str(release))
    if role == "LifecycleEvent":
        records = list(
            asserted_facts.objects(subject, ATLAS.sourceRecord)
            if asserted_facts is not None
            else asserted.objects(subject, ATLAS.sourceRecord)
        )
        if not records or any(not isinstance(record, URIRef) for record in records):
            _fail(
                "construction.sample",
                f"lifecycle event {subject} has invalid RDF source records",
            )
        owners = {
            _construction_source_record_owner(
                asserted,
                record,
                source_owner,
                asserted_facts=asserted_facts,
            )
            for record in records
        }
        return next(iter(owners)) if len(owners) == 1 else None
    if role == "EvidenceBinding":
        source_record = _construction_rdf_one(
            asserted,
            subject,
            ATLAS.evidenceSourceRecord,
            term_type=URIRef,
            asserted_facts=asserted_facts,
        )
        return _construction_source_record_owner(
            asserted,
            source_record,
            source_owner,
            asserted_facts=asserted_facts,
        )
    if role == "Statement":
        return _construction_source_record_owner(
            asserted,
            _construction_statement_source_record(
                asserted,
                subject,
                asserted_facts=asserted_facts,
                bindings_by_statement=bindings_by_statement,
            ),
            source_owner,
            asserted_facts=asserted_facts,
        )
    _fail("construction.record-ownership", f"unsupported logical record role {role}")


def _compact_sample_indices(record_count: int) -> frozenset[int]:
    """Select up to five stable positions spread across one Parquet table."""

    if record_count <= 0:
        return frozenset()
    sample_count = min(COMPACT_RDF_SAMPLE_SIZE, record_count)
    if sample_count == 1:
        return frozenset({0})
    return frozenset(
        index * (record_count - 1) // (sample_count - 1)
        for index in range(sample_count)
    )




def _rdf_record_ids_by_role(asserted: Graph) -> dict[str, set[str]]:
    """Return the asserted graph's logical record identity, role by role."""

    return {
        "Resource": {str(value) for value in asserted.subjects(RDF.type, ATLAS.AtlasResource)},
        "Label": {str(value) for value in asserted.subjects(RDF.type, SKOSXL.Label)},
        "Statement": {str(value) for value in asserted.subjects(RDF.type, ATLAS.RelationAssertion)},
        "EvidenceBinding": {str(value) for value in asserted.subjects(RDF.type, RKAF.EvidenceBinding)},
        "SourceRecord": {str(value) for value in asserted.subjects(RDF.type, ATLAS.SourceRecord)},
        "Release": {str(value) for value in asserted.subjects(RDF.type, ATLAS.AtlasRelease)}
        | {str(value) for value in asserted.subjects(RDF.type, ATLAS.SourceRelease)},
        "Identifier": {str(value) for value in asserted.subjects(RDF.type, ATLAS.Identifier)},
        "LifecycleEvent": {str(value) for value in asserted.subjects(RDF.type, RKAF.LifecycleEvent)},
    }


def _check_explorer_reachability(
    served_ids_by_role: Mapping[str, Sequence[str]],
    rdf_ids_by_role: Mapping[str, AbstractSet[str]],
) -> None:
    """Prove the served projection carries exactly the asserted records.

    The typed Parquet tables are the substrate the Parquet search view, its
    DuckDB session, and the explorer are all built from. A record missing from
    them is one that no filter, no search, and neither concept endpoint can
    ever reach; a record present only in them is one the distribution never
    asserted; a duplicated `id` is both at once. Role counts cannot see any of
    the three -- each keeps every count equal -- and the row sample reads a
    fixed few positions per table, so at real table sizes it reads none of the
    rows involved. Comparing the two identities refuses all three.

    The comparand lives here, and the caller is the builder: the tables are
    Parquet, the binding validator carries no pyarrow, and a check whose
    expected set came from the same projection that produced the observed set
    would prove only that the projection agrees with itself. What the builder
    supplies is the `id` column of each table; what this states is what the
    asserted RDF says those ids must be, both directions, exhaustively.
    """

    if set(served_ids_by_role) != set(rdf_ids_by_role):
        _fail(
            "construction.reachability",
            "served and asserted record roles differ; "
            f"served={sorted(served_ids_by_role)}, asserted={sorted(rdf_ids_by_role)}",
        )
    for role in sorted(served_ids_by_role):
        served_rows = list(served_ids_by_role[role])
        served = set(served_rows)
        if len(served_rows) != len(served):
            _fail(
                "construction.reachability",
                f"the served {role} table repeats a record identity",
            )
        asserted_ids = set(rdf_ids_by_role[role])
        if served == asserted_ids:
            continue
        unreachable = sorted(asserted_ids - served)
        invented = sorted(served - asserted_ids)
        _fail(
            "construction.reachability",
            f"served {role} records are not the asserted {role} records; "
            f"unreachable={unreachable[:3]}, unasserted={invented[:3]}",
        )


def _check_cached_pack_transports(
    root: Path,
    manifest: Mapping[str, Any],
) -> None:
    """Stream-check every stored pack before trusting a cached semantic result."""

    for pack in manifest["packs"]:
        path = _safe_distribution_path(root, pack["path"])
        if file_sha256(path) != pack["transport"]["digest"]:
            _fail("pack.transport", f"{pack['path']} transport digest differs")


def _check_construction_record_ownership(
    asserted: Graph,
    construction_summary: Mapping[str, Any],
    *,
    asserted_facts: _AssertedFacts | None = None,
) -> None:
    """Recompute each release's logical record counts from the asserted RDF.

    The summary used to publish counts read back off the compact pack
    inventory the same producer had just written -- the producer counting its
    own output. With the packs gone the comparand is the graph: every carrier
    is resolved to the construction unit that owns it and tallied, and the
    published counts must equal that tally exactly, per release and per role.
    A parse-observed fact index answers the per-record ownership reads when
    available; direct callers retain the graph-backed path.
    """

    source_owner: dict[str, str] = {}
    atlas_owner: dict[str, str] = {}
    for release in construction_summary["releases"]:
        source_owner[release["sourceRelease"]] = release["key"]
        if "atlasRelease" in release:
            atlas_owner[release["atlasRelease"]] = release["key"]

    facts = asserted_facts or _AssertedFacts.for_graph(asserted)
    bindings_by_statement: dict[URIRef, list[URIRef]] = defaultdict(list)
    for binding, statement in facts.subject_objects(RKAF.bindsAssertion):
        if isinstance(binding, URIRef) and isinstance(statement, URIRef):
            bindings_by_statement[statement].append(binding)

    observed: dict[str, Counter[str]] = {
        release["key"]: Counter() for release in construction_summary["releases"]
    }
    for role, ids in _rdf_record_ids_by_role(asserted).items():
        count_field = COMPACT_ROLE_COUNT_FIELDS[role]
        for identity in ids:
            subject = URIRef(identity)
            owner = _construction_compact_owner(
                asserted,
                subject,
                role,
                source_owner=source_owner,
                atlas_owner=atlas_owner,
                asserted_facts=facts,
                bindings_by_statement=bindings_by_statement,
            )
            if owner is None:
                _fail(
                    "construction.record-ownership",
                    f"{role} record {subject} belongs to no construction unit",
                )
            observed[owner][count_field] += 1

    for release in construction_summary["releases"]:
        key = release["key"]
        published = {
            field: count for field, count in release["recordCounts"].items() if count
        }
        if published != dict(observed[key]):
            _fail(
                "construction.counts",
                f"{key} logical record counts differ from the asserted graph; "
                f"published={published}, rdf={dict(observed[key])}",
            )






def _check_producer_validation(
    manifest: Mapping[str, Any],
    acceptance: Mapping[str, Any],
    producer_validation: Mapping[str, Any],
    construction_summary: Mapping[str, Any],
    member_digests: Mapping[str, str],
    accounting: Mapping[str, Any],
) -> None:
    """Bind the required producer receipt without treating it as validation authority.

    It is a receipt, not a proof. The 3.0 wire also carried
    ``shaclDataProof: compiledAgainstPinnedOntologyAndShapes``,
    ``shaclMetaValidation``, an ``implementationDigest`` the producer compared
    against its own constant, and an eight-line ``checks`` prose list. The
    first passed while these shapes rejected 2,003 evidence bindings, and none
    of the four were checkable from here. They left the wire with 3.1.
    """

    producer_members = [
        member
        for member in manifest["members"]
        if member["role"] == "producerValidation"
    ]
    producer_input_digest = acceptance["inputs"].get(
        "producerValidationDigest"
    )
    has_member = bool(producer_members)
    has_input = producer_input_digest is not None
    has_proof = producer_validation is not None
    if not (has_member == has_input == has_proof):
        _fail(
            "producer.validation",
            "producer validation member, acceptance input, and proof presence differ",
        )
    if not has_proof:
        _fail("producer.validation", "producer validation proof is required")
    if len(producer_members) != 1:
        _fail("producer.validation", "producer validation member is not unique")
    member = producer_members[0]
    if (
        member["path"] != PRODUCER_VALIDATION_FILE
        or member_digests.get(PRODUCER_VALIDATION_FILE) != producer_input_digest
        or canonical_sha256(producer_validation) != producer_input_digest
    ):
        _fail(
            "producer.validation",
            "producer validation digest differs from the declared member",
        )

    if producer_validation["binding"] != manifest["binding"]:
        _fail("producer.validation", "producer validation binding differs")
    asserted_inventory_digest = next(
        row["inventoryDigest"]
        for row in manifest["graphs"]
        if row["role"] == "asserted"
    )
    if producer_validation["assertedInventoryDigest"] != asserted_inventory_digest:
        _fail("producer.validation", "producer asserted inventory digest differs")
    if (
        producer_validation["sourceAccountingDigest"]
        != member_digests["atlas-source-accounting.json"]
    ):
        _fail("producer.validation", "producer source accounting digest differs")
    if producer_validation["counts"] != manifest["counts"]:
        _fail("producer.validation", "producer aggregate counts differ")
    if (
        producer_validation["sourceReleaseCount"]
        != accounting["totals"]["sourceReleases"]
    ):
        _fail("producer.validation", "producer source release count differs")
    expected_identity = {
        "constructorProfile": "atlas-3-source-and-evidence-backed-mapping-v1",
        "mode": "compiledSourceAndEvidenceBackedMappingProducerValidation",
        "status": "passed",
        "type": "AtlasProducerValidation",
        "version": "3.1",
    }
    if any(
        producer_validation[field] != value
        for field, value in expected_identity.items()
    ):
        _fail("producer.validation", "producer validation identity differs")
    _check_construction_accounting(construction_summary, accounting)


def _check_acceptance_metadata(
    manifest: Mapping[str, Any],
    acceptance: Mapping[str, Any],
    member_digests: Mapping[str, str],
) -> None:
    if acceptance["distributionId"] != manifest["distributionId"]:
        _fail("distribution.identity", "distributionId differs across JSON artifacts")
    asserted_inventory_digest = next(
        row["inventoryDigest"] for row in manifest["graphs"] if row["role"] == "asserted"
    )
    if acceptance["inputs"]["atlasDigest"] != asserted_inventory_digest:
        _fail("acceptance.inputs", "acceptance atlasDigest differs")
    if acceptance["inputs"]["sourceAccountingDigest"] != member_digests["atlas-source-accounting.json"]:
        _fail("acceptance.inputs", "acceptance sourceAccountingDigest differs")
    names = [gate["name"] for gate in acceptance["gates"]]
    if len(names) != len(set(names)) or set(names) != REQUIRED_GATES:
        _fail(
            "acceptance.gates",
            f"acceptance gates differ; missing={sorted(REQUIRED_GATES - set(names))}, extra={sorted(set(names) - REQUIRED_GATES)}",
        )
    for gate in acceptance["gates"]:
        expected_digest = acceptance_gate_evidence_digest(
            gate["name"],
            inputs=acceptance["inputs"],
            validator=acceptance["validator"],
        )
        if gate["evidenceDigest"] != expected_digest:
            _fail("acceptance.evidence", f"gate {gate['name']} evidenceDigest differs")


def _check_acceptance(
    manifest: Mapping[str, Any],
    accounting: Mapping[str, Any],
    acceptance: Mapping[str, Any],
    member_digests: Mapping[str, str],
) -> None:
    if accounting["distributionId"] != manifest["distributionId"]:
        _fail("distribution.identity", "distributionId differs across JSON artifacts")
    _check_acceptance_metadata(manifest, acceptance, member_digests)


def _validation_cache_identity(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Return the immutable identity of one complete semantic validation.

    Everything a verdict depends on, which is strictly more than what
    conformance *means*. The contract half is the manifest and its contract
    digest. The program half is ``toolsDigest`` and ``runtime``: a cache hit
    returns before the procedural checks -- supersession lineage, cardinality,
    every ``dataset.*`` gate -- have run even once, so a validator that grew a
    refusal, or a pyshacl that changed a verdict, must not be able to answer
    from the receipt its predecessor wrote. ``VALIDATOR_VERSION`` alone cannot
    carry this: it is the binding's version, "3.1", and it does not move when
    the program does.
    """

    return {
        "contractDigest": manifest["binding"]["contractDigest"],
        "format": CACHE_FORMAT,
        "manifestDigest": manifest["canonicalPayloadDigest"],
        "runtime": binding_runtime(),
        "toolsDigest": _binding_tool_digest(),
        "validator": {"name": VALIDATOR_ID, "version": VALIDATOR_VERSION},
    }


def _validation_cache_key(manifest: Mapping[str, Any]) -> str:
    return canonical_sha256(
        _validation_cache_identity(manifest),
        terminal_lf=False,
    )


def _validation_cache_pack_rows(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "contentDigest": pack["content"]["digest"],
            "dependencyDigest": canonical_sha256(
                pack["dependencies"],
                terminal_lf=False,
            ),
            "graphCountsDigest": canonical_sha256(
                pack["graphCounts"],
                terminal_lf=False,
            ),
            "packId": pack["packId"],
            "transportDigest": pack["transport"]["digest"],
        }
        for pack in manifest["packs"]
    ]


def _validation_receipt_payload(
    manifest: Mapping[str, Any],
    result: Mapping[str, Any],
) -> dict[str, Any]:
    key = _validation_cache_key(manifest)
    return {
        **_validation_cache_identity(manifest),
        "cacheKey": key,
        "packs": _validation_cache_pack_rows(manifest),
        "result": dict(result),
    }


def _cache_location(root: Path, cache_dir: Path) -> Path:
    """Reject a cache that would make the closed distribution self-modifying."""

    try:
        distribution = root.resolve()
        cache = cache_dir.resolve()
    except OSError as exc:
        _fail("cache.path", f"cannot resolve validation cache path: {exc}")
    if cache == distribution or cache.is_relative_to(distribution):
        _fail("cache.path", "validation cache must be outside the closed distribution")
    return cache_dir


def _private_cache_directory(path: Path, *, create: bool) -> bool:
    try:
        if create:
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = path.lstat()
    except OSError:
        return False
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        return False
    getuid = getattr(os, "getuid", None)
    if getuid is not None and metadata.st_uid != getuid():
        return False
    return metadata.st_mode & 0o022 == 0


def _private_cache_file(path: Path) -> bytes | None:
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            return None
        getuid = getattr(os, "getuid", None)
        if getuid is not None and metadata.st_uid != getuid():
            return None
        if metadata.st_mode & 0o077:
            return None
        return path.read_bytes()
    except OSError:
        return None


def _cache_secret(cache_dir: Path, *, create: bool) -> bytes | None:
    if not _private_cache_directory(cache_dir, create=create):
        return None
    secret_path = cache_dir / "authentication-key"
    secret = _private_cache_file(secret_path)
    if secret is not None:
        return secret if len(secret) == CACHE_SECRET_BYTES else None
    if not create:
        return None

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    secret = secrets.token_bytes(CACHE_SECRET_BYTES)
    try:
        descriptor = os.open(secret_path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(secret)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        return _private_cache_file(secret_path)
    return secret


def _receipt_authentication_tag(secret: bytes, payload: Mapping[str, Any]) -> str:
    digest = hmac.new(
        secret,
        canonical_json_bytes(payload, terminal_lf=False),
        hashlib.sha256,
    ).hexdigest()
    return "hmac-sha256:" + digest


def _cache_receipt_path(cache_dir: Path, cache_key: str) -> Path:
    return cache_dir / "receipts" / (cache_key.removeprefix("sha256:") + ".json")


def _read_validation_receipt(
    cache_dir: Path,
    manifest: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Return one authenticated exact-input cache hit, otherwise fail closed to a miss."""

    secret = _cache_secret(cache_dir, create=False)
    receipts_dir = cache_dir / "receipts"
    if secret is None or not _private_cache_directory(receipts_dir, create=False):
        return None
    path = _cache_receipt_path(cache_dir, _validation_cache_key(manifest))
    try:
        metadata = path.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size > CACHE_RECEIPT_MAX_BYTES
        ):
            return None
        raw = path.read_bytes()
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
            parse_int=_parse_int,
        )
        if raw != canonical_json_bytes(value):
            return None
    except (AtlasValidationError, json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None
    if not isinstance(value, Mapping) or set(value) != {"authenticationTag", "payload"}:
        return None
    payload = value["payload"]
    tag = value["authenticationTag"]
    if not isinstance(payload, Mapping) or not isinstance(tag, str):
        return None
    try:
        expected_tag = _receipt_authentication_tag(secret, payload)
    except AtlasValidationError:
        return None
    if not hmac.compare_digest(tag, expected_tag):
        return None

    cached_result = payload.get("result")
    if not isinstance(cached_result, Mapping):
        return None
    expected = _validation_receipt_payload(manifest, cached_result)
    if payload != expected:
        return None
    result = cached_result
    expected_result_keys = {
        "counts",
        "distributionId",
        "inferredMappingCount",
        "quadCount",
    }
    if (
        not isinstance(result, Mapping)
        or set(result) != expected_result_keys
        or result["counts"] != manifest["counts"]
        or result["distributionId"] != manifest["distributionId"]
        or result["quadCount"] != sum(row["quadCount"] for row in manifest["graphs"])
        or not isinstance(result["inferredMappingCount"], int)
        or isinstance(result["inferredMappingCount"], bool)
        or result["inferredMappingCount"] < 0
    ):
        return None
    return dict(result)


def _write_validation_receipt(
    cache_dir: Path,
    manifest: Mapping[str, Any],
    result: Mapping[str, Any],
) -> None:
    """Best-effort atomic write of one private authenticated cache receipt."""

    secret = _cache_secret(cache_dir, create=True)
    receipts_dir = cache_dir / "receipts"
    if secret is None or not _private_cache_directory(receipts_dir, create=True):
        return
    payload = _validation_receipt_payload(manifest, result)
    receipt = {
        "authenticationTag": _receipt_authentication_tag(secret, payload),
        "payload": payload,
    }
    raw = canonical_json_bytes(receipt)
    if len(raw) > CACHE_RECEIPT_MAX_BYTES:
        return
    target = _cache_receipt_path(cache_dir, payload["cacheKey"])
    temporary = receipts_dir / f".{target.stem}.{secrets.token_hex(8)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(temporary, flags, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except OSError:
        with contextlib.suppress(OSError):
            temporary.unlink(missing_ok=True)




def _validate_semantic_graphs(
    manifest: Mapping[str, Any],
    accounting: Mapping[str, Any],
    acceptance: Mapping[str, Any],
    graphs: Mapping[str, Graph],
    *,
    member_digests: Mapping[str, str],
    asserted_placement: _AssertedPlacementObservation | None = None,
    node_digests: _AssertedNodeDigests | None = None,
) -> dict[str, Any]:
    """Run every graph-level semantic gate against three parsed graph roles."""

    if set(graphs) != {"asserted", "projection", "derived"} or not all(
        isinstance(graph, Graph) for graph in graphs.values()
    ):
        _fail("dataset.graph", "preparsed validation requires the three Atlas graph roles")
    _STATUS.phase("load-binding-graphs")
    ontology, shapes = _parse_binding_graphs()
    _lint_ontology(ontology)
    _STATUS.phase("run-shacl")
    _run_shacl(graphs, ontology, shapes)
    _STATUS.phase("check-graph-roles")
    inventory = _check_graph_roles(graphs, asserted_placement=asserted_placement)
    _STATUS.phase("check-profile-and-identifier-semantics")
    _check_profile_conformance(graphs["asserted"], inventory)
    _check_identifier_uniqueness(graphs["asserted"], inventory)
    _STATUS.phase("check-release-and-label-semantics")
    _check_release_membership(graphs["asserted"], inventory)
    _check_label_integrity(graphs["asserted"], inventory)
    _STATUS.phase("check-evidence-and-assertions")
    _check_evidence_bindings(graphs["asserted"], inventory, node_digests=node_digests)
    current_assertions = _validate_assertions(graphs["asserted"], inventory)
    _STATUS.phase("check-machine-adjudication")
    _check_machine_adjudication(
        graphs["asserted"],
        inventory,
        node_digests=node_digests,
    )
    _STATUS.phase("check-skos-semantics")
    exact_index = _check_skos_integrity(current_assertions)
    projection_quad_count = next(
        row["quadCount"] for row in manifest["graphs"] if row["role"] == "projection"
    )
    if projection_quad_count:
        _STATUS.phase("check-projection")
        _check_projection(graphs["asserted"], graphs["projection"], current_assertions)
    _STATUS.phase("check-derived-graph")
    _check_derived(
        graphs["asserted"],
        graphs["projection"],
        graphs["derived"],
        current_assertions,
        inventory.derived_nodes,
        node_digests=node_digests,
    )
    _STATUS.phase("check-payload-and-node-digests")
    _check_native_payloads(graphs["asserted"], inventory, node_digests=node_digests)
    _STATUS.phase("check-accounting-and-counts")
    _check_source_accounting(graphs["asserted"], accounting, inventory)
    _check_counts(manifest, graphs, inventory)
    _STATUS.phase("check-reasoning-isolation")
    inferred_mapping_count = _check_reasoning_isolation(
        graphs["derived"],
        current_assertions,
        exact_index,
        inventory.derived_nodes,
    )
    _STATUS.phase("check-acceptance")
    _check_acceptance(manifest, accounting, acceptance, member_digests)
    return {
        "counts": manifest["counts"],
        "distributionId": manifest["distributionId"],
        "inferredMappingCount": inferred_mapping_count,
        "quadCount": sum(row["quadCount"] for row in manifest["graphs"]),
    }


def validate_preparsed_distribution(
    manifest: Mapping[str, Any],
    accounting: Mapping[str, Any],
    acceptance: Mapping[str, Any],
    graphs: Mapping[str, Graph],
    *,
    member_digests: Mapping[str, str],
    producer_validation: Mapping[str, Any],
    construction_summary: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate exact graphs retained by a trusted Atlas pack writer.

    This avoids reparsing a publisher's already-resident graph. The writer must
    separately verify closed serialized files plus every transport and content
    pin. Consumers that have only files call :func:`validate_distribution`.
    """

    schemas, registry = _schema_registry()
    _validate_json_schema(manifest, "manifest", schemas=schemas, registry=registry, label="manifest")
    _validate_json_schema(accounting, "sourceAccounting", schemas=schemas, registry=registry, label="source accounting")
    _validate_json_schema(acceptance, "acceptance", schemas=schemas, registry=registry, label="acceptance")
    _validate_json_schema(
        producer_validation,
        "producerValidation",
        schemas=schemas,
        registry=registry,
        label="producer validation",
    )
    _validate_json_schema(
        construction_summary,
        "constructionSummary",
        schemas=schemas,
        registry=registry,
        label="construction summary",
    )
    _check_manifest_digest(manifest)
    _check_pack_manifest(manifest)
    _check_binding_pins(manifest, acceptance)
    _check_construction_summary_identity(
        manifest,
        producer_validation,
        construction_summary,
        member_digests,
    )
    _check_producer_validation(
        manifest,
        acceptance,
        producer_validation,
        construction_summary,
        member_digests,
        accounting,
    )
    return _validate_semantic_graphs(
        manifest,
        accounting,
        acceptance,
        graphs,
        member_digests=member_digests,
    )


def _validate_semantics_then_record_ownership(
    manifest: Mapping[str, Any],
    accounting: Mapping[str, Any],
    acceptance: Mapping[str, Any],
    graphs: Mapping[str, Graph],
    construction_summary: Mapping[str, Any],
    *,
    member_digests: Mapping[str, str],
    asserted_placement: _AssertedPlacementObservation | None = None,
    node_digests: _AssertedNodeDigests | None = None,
) -> dict[str, Any]:
    """Preserve semantic first issues before reconciling record ownership."""

    result = _validate_semantic_graphs(
        manifest,
        accounting,
        acceptance,
        graphs,
        member_digests=member_digests,
        asserted_placement=asserted_placement,
        node_digests=node_digests,
    )
    _STATUS.phase("check-construction-record-ownership")
    asserted = graphs["asserted"]
    asserted_facts = (
        asserted_placement.facts
        if asserted_placement is not None
        and asserted_placement.facts is not None
        and asserted_placement.facts.graph_id == asserted.identifier
        else None
    )
    _check_construction_record_ownership(
        asserted,
        construction_summary,
        asserted_facts=asserted_facts,
    )
    return result


def validate_distribution(
    root: Path,
    *,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    """Validate one closed Atlas 3.1 distribution and return proof counts.

    An optional private cache can reuse a complete semantic result only when
    the canonical manifest, binding, validator, JSON members, and exact stored
    pack bytes are unchanged.
    """

    _STATUS.phase("load-manifest")
    if cache_dir is not None:
        cache_dir = _cache_location(root, cache_dir)
    schemas, registry = _schema_registry()
    manifest_path = root / MANIFEST_FILE
    if not manifest_path.is_file() or manifest_path.is_symlink():
        _fail("distribution.file", "atlas-manifest.json is missing or unsafe")
    manifest = _load_json(manifest_path, require_canonical=True)
    _validate_json_schema(manifest, "manifest", schemas=schemas, registry=registry, label="manifest")
    _check_manifest_digest(manifest)
    graph_ids = _check_pack_manifest(manifest)

    members_by_role = {member["role"]: member for member in manifest["members"]}
    accounting_member = members_by_role["sourceAccounting"]
    acceptance_member = members_by_role["acceptance"]
    producer_member = members_by_role["producerValidation"]
    construction_member = members_by_role["constructionSummary"]

    construction_summary = _load_json(
        _safe_distribution_path(root, construction_member["path"]),
        require_canonical=True,
        expected_digest=construction_member["digest"],
    )
    _validate_json_schema(
        construction_summary,
        "constructionSummary",
        schemas=schemas,
        registry=registry,
        label="construction summary",
    )
    _STATUS.phase("check-closed-distribution")
    member_digests = _check_distribution_files(root, manifest)

    accounting_path = _safe_distribution_path(root, accounting_member["path"])
    acceptance = _load_json(
        _safe_distribution_path(root, acceptance_member["path"]),
        require_canonical=True,
        expected_digest=member_digests[acceptance_member["path"]],
    )
    _validate_json_schema(acceptance, "acceptance", schemas=schemas, registry=registry, label="acceptance")
    producer_validation = _load_json(
        _safe_distribution_path(root, producer_member["path"]),
        require_canonical=True,
        expected_digest=member_digests[producer_member["path"]],
    )
    _validate_json_schema(
        producer_validation,
        "producerValidation",
        schemas=schemas,
        registry=registry,
        label="producer validation",
    )
    _check_binding_pins(manifest, acceptance)
    _check_construction_summary_identity(
        manifest,
        producer_validation,
        construction_summary,
        member_digests,
    )
    if cache_dir is not None:
        _STATUS.phase("check-validation-cache")
        cached_result = _read_validation_receipt(cache_dir, manifest)
        if cached_result is not None:
            if file_sha256(accounting_path) != member_digests[accounting_member["path"]]:
                _fail("distribution.digest", f"{accounting_path.name} digest differs")
            _check_cached_pack_transports(root, manifest)
            _check_acceptance_metadata(manifest, acceptance, member_digests)
            _STATUS.phase("complete-from-cache")
            return cached_result

    _STATUS.phase("check-source-accounting")
    accounting = _load_json(
        accounting_path,
        require_canonical=True,
        expected_digest=member_digests[accounting_member["path"]],
    )
    _validate_json_schema(
        accounting,
        "sourceAccounting",
        schemas=schemas,
        registry=registry,
        label="source accounting",
    )
    _check_producer_validation(
        manifest,
        acceptance,
        producer_validation,
        construction_summary,
        member_digests,
        accounting,
    )
    _STATUS.phase("parse-rdf-packs")
    placement = _AssertedPlacementObservation(
        graph_id=graph_ids["asserted"],
        projection_only_predicates=_projection_only_predicates(),
    )
    node_digests = _AssertedNodeDigests(graph_ids["asserted"])
    dataset, graphs = _parse_packed_dataset(
        root,
        manifest,
        graph_ids,
        asserted_placement=placement,
        node_digests=node_digests,
    )
    # The packs are parsed and the three role graphs are final. Nothing after
    # this point adds to the store, so what it holds -- tens of millions of
    # indexed RDF terms in cycles between the graph views and their shared
    # in-memory store -- is a stable heap that CPython's cyclic collector
    # re-walks on every full collection and can never free. The 2026-08-12
    # trace measured those bursts over a 22 GB heap at 1-2 minutes of the
    # acceptance hour, buying nothing (`plans/validation-cost-reset-plan.md`,
    # "Inside-the-phases trace"). So: one collection to settle what parse left
    # behind, then freeze what survives out of the collector's reach.
    #
    # Freezing is not disabling. Objects allocated after this -- everything
    # SHACL and the semantic checks build -- are still tracked and still
    # collected, and frozen objects keep ordinary reference counting; only
    # cycle *detection* skips them. Nothing downstream depends on cycle
    # collection for correctness: neither this module nor rdflib 7.5 nor
    # pyshacl 0.31 registers a weakref callback or a gc-dependent finalizer.
    # Unfrozen again below so a library caller's heap is left as it was found;
    # the standalone CLI re-freezes at exit (`_prepare_cli_heap_for_exit`).
    gc.collect()
    gc.freeze()
    try:
        _STATUS.phase("validate-semantic-graphs")
        result = _validate_semantics_then_record_ownership(
            manifest,
            accounting,
            acceptance,
            graphs,
            construction_summary,
            member_digests=member_digests,
            asserted_placement=placement,
            node_digests=node_digests,
        )
    finally:
        gc.unfreeze()
    # Keep the shared Dataset store alive for every graph view through the last check.
    del dataset
    if cache_dir is not None:
        _STATUS.phase("write-validation-cache")
        _write_validation_receipt(cache_dir, manifest, result)
    return result


def _smoke_sample_packs(manifest: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Choose the packs a smoke run parses: every kind first, then size.

    Up to `SMOKE_SAMPLE_PACK_COUNT` packs of each declared pack kind, taken in
    manifest order, round-robin across kinds so no kind is crowded out, and
    only while the accumulated content stays under
    `SMOKE_SAMPLE_MAX_CONTENT_BYTES`.  Kind coverage is the point: the defect
    this tier exists to catch lived in the mapping packs, and a purely
    size-ordered sample skips every one of them, because a mapping pack drags
    both endpoint vocabularies in behind it.

    Each pack is taken with its declared dependency closure, which is not
    optional: packs are partitioned by subject, so a sampled pack's
    `sh:class` and sequence-path values live in the packs it declares as
    dependencies, and a sample without them reports violations the
    distribution does not have.
    """

    packs_by_id = {pack["packId"]: pack for pack in manifest["packs"]}

    def closure(pack: Mapping[str, Any]) -> dict[str, Mapping[str, Any]] | None:
        selected: dict[str, Mapping[str, Any]] = {}
        pending = [pack["packId"]]
        while pending:
            pack_id = pending.pop()
            if pack_id in selected:
                continue
            member = packs_by_id.get(pack_id)
            if member is None:
                return None
            selected[pack_id] = member
            pending.extend(member["dependencies"])
        return selected

    by_kind: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for pack in manifest["packs"]:
        by_kind[pack["kind"]].append(pack)
    cursors = dict.fromkeys(by_kind, 0)
    sampled: dict[str, Mapping[str, Any]] = {}
    budget = SMOKE_SAMPLE_MAX_CONTENT_BYTES
    for _ in range(SMOKE_SAMPLE_PACK_COUNT):
        for kind in sorted(by_kind):
            candidates = by_kind[kind]
            index = cursors[kind]
            while index < len(candidates):
                members = closure(candidates[index])
                index += 1
                if members is None:
                    continue
                cost = sum(
                    member["content"]["byteLength"]
                    for pack_id, member in members.items()
                    if pack_id not in sampled
                )
                if cost > budget:
                    continue
                sampled.update(members)
                budget -= cost
                break
            cursors[kind] = index
    return [pack for pack in manifest["packs"] if pack["packId"] in sampled]


def smoke_check(root: Path) -> dict[str, Any]:
    """Sample one distribution in seconds. This is NOT acceptance.

    A smoke run answers one question -- "is this build obviously broken?" --
    and answers it from a bounded sample, so a green result proves nothing
    about the distribution as a whole. It exists because all 2,003 evidence
    bindings in the 2026-08-11 full build carried the same defect, and one
    binding checked at fixture scale would have caught it in milliseconds
    instead of two hours (`plans/validation-cost-reset-plan.md`).

    Checked: the manifest against its JSON Schema, the manifest's canonical
    payload digest, the binding pins in the manifest and the acceptance
    record, and SHACL data conformance of the sampled packs against the full
    normative shapes (which verifies those packs' transport and content
    receipts on the way in).

    Not checked: every other pack, the closed-distribution digest walk, source
    accounting, producer validation, the acceptance record's own contents,
    graph-role placement, node identity, projection and derivation, SKOS
    integrity, adjudication, and the compact layer. `validate_distribution`
    is the only function that answers acceptance, and a smoke run never
    reads or writes its receipt cache.
    """

    _STATUS.phase("smoke-load-manifest")
    schemas, registry = _schema_registry()
    manifest_path = root / MANIFEST_FILE
    if not manifest_path.is_file() or manifest_path.is_symlink():
        _fail("distribution.file", "atlas-manifest.json is missing or unsafe")
    manifest = _load_json(manifest_path, require_canonical=True)
    _validate_json_schema(manifest, "manifest", schemas=schemas, registry=registry, label="manifest")
    _check_manifest_digest(manifest)

    members_by_role = {member["role"]: member for member in manifest["members"]}
    acceptance = _load_json(
        _safe_distribution_path(root, members_by_role["acceptance"]["path"]),
        require_canonical=True,
    )
    _validate_json_schema(acceptance, "acceptance", schemas=schemas, registry=registry, label="acceptance")
    _check_binding_pins(manifest, acceptance)

    graph_ids = {row["role"]: URIRef(row["id"]) for row in manifest["graphs"]}
    sample = _smoke_sample_packs(manifest)
    if not sample:
        _fail("smoke.sample", "no pack and dependency closure fits the smoke sample budget")

    _STATUS.phase("smoke-parse-sampled-packs")
    dataset = _new_dataset()
    subject_owners: dict[str, dict[URIRef, str]] = {role: {} for role in graph_ids}
    sampled_quads = 0
    for position, pack in enumerate(sample, start=1):
        _STATUS.progress("smoke-parse-sampled-packs", position - 1, len(sample), current=pack["path"])
        _parse_pack_into_dataset(dataset, root, pack, graph_ids, subject_owners)
        sampled_quads += pack["content"]["quadCount"]
        _STATUS.progress("smoke-parse-sampled-packs", position, len(sample), current=pack["path"])

    _STATUS.phase("smoke-run-shacl")
    ontology, shapes = _parse_binding_graphs()
    graphs = {role: dataset.graph(graph_id) for role, graph_id in graph_ids.items()}
    _run_shacl(graphs, ontology, shapes)
    del dataset
    return {
        "smoke": {
            "checked": [
                "manifest-schema",
                "manifest-digest",
                "binding-pins",
                "sampled-pack-receipts",
                "sampled-shacl-data",
            ],
            "distributionId": manifest["distributionId"],
            "notChecked": [
                "closed-distribution",
                "source-accounting",
                "producer-validation",
                "acceptance-record",
                "graph-roles",
                "projection",
                "derivation",
                "skos-integrity",
                "adjudication",
                "record-ownership",
                "unsampled-packs",
            ],
            "packCount": len(manifest["packs"]),
            "sampledPackCount": len(sample),
            "sampledPacks": sorted(pack["path"] for pack in sample),
            "sampledQuadCount": sampled_quads,
            "totalQuadCount": sum(pack["content"]["quadCount"] for pack in manifest["packs"]),
            "warning": (
                "smoke sampling is not acceptance and proves nothing about the "
                "distribution as a whole; run validate_distribution for a verdict"
            ),
        }
    }


def _check_registry_descriptors(
    profile_map: Mapping[str, Any],
    coverage: Mapping[str, Any],
    *,
    schemas: Mapping[str, Mapping[str, Any]],
    registry: Registry,
) -> dict[str, int]:
    """Verify the checked RDF export of every real registry descriptor."""

    for path in (REGISTRY_DESCRIPTOR_PROOF_PATH, REGISTRY_DESCRIPTOR_DATASET_PATH):
        if not path.is_file() or path.is_symlink():
            _fail("registry.descriptors", f"registry descriptor artifact is missing or unsafe: {path.name}")
    proof = _load_json(REGISTRY_DESCRIPTOR_PROOF_PATH, require_canonical=True)
    _validate_json_schema(
        proof,
        "registryDescriptors",
        schemas=schemas,
        registry=registry,
        label="registry descriptor proof",
    )
    expected_proof_keys = {
        "artifact",
        "counts",
        "format",
        "graphIri",
        "inputs",
        "proofDigest",
        "resourceIdSetDigest",
        "schemaVersion",
    }
    if not isinstance(proof, Mapping) or set(proof) != expected_proof_keys:
        _fail("registry.descriptors", "registry descriptor proof fields are incomplete or unknown")
    if proof.get("format") != "refspec-atlas-registry-descriptors/3.1" or proof.get("schemaVersion") != "3.1":
        _fail("registry.descriptors", "registry descriptor proof is not Atlas 3.1")
    expected_proof_digest = canonical_sha256(
        {key: value for key, value in proof.items() if key != "proofDigest"},
        terminal_lf=False,
    )
    if proof.get("proofDigest") != expected_proof_digest:
        _fail("registry.descriptors", "registry descriptor proofDigest differs")
    proof_inputs = proof.get("inputs")
    if not isinstance(proof_inputs, Mapping) or set(proof_inputs) != {
        "atlasIndexDigest",
        "registryResourceProfilesDigest",
        "resourceCatalogDigest",
    }:
        _fail("registry.descriptors", "registry descriptor input receipt is malformed")
    if proof_inputs != coverage.get("inputs"):
        _fail("registry.descriptors", "registry descriptor and coverage inputs differ")
    if proof_inputs.get("registryResourceProfilesDigest") != profile_map.get("profileDigest"):
        _fail("registry.descriptors", "registry descriptor proof does not pin the profile policy")

    artifact = proof.get("artifact")
    if not isinstance(artifact, Mapping) or set(artifact) != {"byteLength", "path", "sha256"}:
        _fail("registry.descriptors", "registry descriptor artifact receipt is malformed")
    if artifact.get("path") != REGISTRY_DESCRIPTOR_DATASET_PATH.name:
        _fail("registry.descriptors", "registry descriptor artifact path differs")
    raw = REGISTRY_DESCRIPTOR_DATASET_PATH.read_bytes()
    if artifact.get("byteLength") != len(raw) or artifact.get("sha256") != file_sha256(
        REGISTRY_DESCRIPTOR_DATASET_PATH
    ):
        _fail("registry.descriptors", "registry descriptor artifact receipt differs")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        _fail("registry.descriptors", f"registry descriptor N-Quads are not UTF-8: {exc}")
    if not text or not text.endswith("\n") or "\r" in text:
        _fail("registry.descriptors", "registry descriptor N-Quads must be LF text")
    lines = text.splitlines()
    if (
        lines != sorted(lines)
        or len(lines) != len(set(lines))
        or any(not line or line != line.strip() for line in lines)
    ):
        _fail("registry.descriptors", "registry descriptor N-Quads are not sorted and unique")
    dataset = _new_dataset()
    try:
        _parse_nquads_preserving_lexical_forms(dataset, REGISTRY_DESCRIPTOR_DATASET_PATH)
    except Exception as exc:  # noqa: BLE001 - normalize RDF parser failures
        _fail("registry.descriptors", f"registry descriptor N-Quads cannot be parsed: {exc}")
    canonical_lines = _canonical_dataset_lines(
        dataset,
        blank_node_code="registry.descriptors",
        blank_node_detail="registry descriptor N-Quads contain a blank node term",
    )
    if canonical_lines != lines:
        _fail("registry.descriptors", "registry descriptor N-Quads are not canonical")
    graph_iri = proof.get("graphIri")
    if not isinstance(graph_iri, str) or not ABSOLUTE_IRI_RE.fullmatch(graph_iri):
        _fail("registry.descriptors", "registry descriptor graphIri is not an absolute IRI")
    graph_id = URIRef(graph_iri)
    graph_ids = {quad_graph for _, _, _, quad_graph in dataset.quads((None, None, None, None))}
    if graph_ids != {graph_id}:
        _fail("registry.descriptors", "registry descriptor statements use unexpected graph IRIs")
    graph = Graph(identifier=graph_id)
    for subject, predicate, obj, _ in dataset.quads((None, None, None, graph_id)):
        graph.add((subject, predicate, obj))

    counts = proof.get("counts")
    expected_count_keys = {
        "atlasIndexPlacementCount",
        "conceptSchemeCount",
        "memberDispositionCounts",
        "quadCount",
        "registrySourceCount",
        "resourceSchemeCount",
        "supportedRingStatementCount",
    }
    if not isinstance(counts, Mapping) or set(counts) != expected_count_keys:
        _fail("registry.descriptors", "registry descriptor counts are missing or vacuous")
    scalar_counts = {name: value for name, value in counts.items() if name != "memberDispositionCounts"}
    disposition_counts = counts["memberDispositionCounts"]
    if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in scalar_counts.values()) or (
        not isinstance(disposition_counts, Mapping)
        or set(disposition_counts) != MEMBER_DISPOSITIONS
        or any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in disposition_counts.values()
        )
    ):
        _fail("registry.descriptors", "registry descriptor counts are missing or vacuous")
    if counts["atlasIndexPlacementCount"] != coverage["summary"]["atlasIndexRowCount"]:
        _fail("registry.descriptors", "registry descriptor index count does not reconcile")
    expected_scheme_count = (
        coverage["summary"]["catalogResourceCount"]
        - disposition_counts["mappingAssertionsOnly"]
    )
    if counts["resourceSchemeCount"] != expected_scheme_count:
        _fail("registry.descriptors", "registry descriptor scheme count does not reconcile")
    if counts["registrySourceCount"] != coverage["summary"]["catalogResourceCount"]:
        _fail("registry.descriptors", "registry descriptor source count does not reconcile")

    schemes = set(graph.subjects(RDF.type, ATLAS.ResourceScheme))
    sources = set(graph.subjects(RDF.type, ATLAS.RegistrySource))
    if set(graph.subjects()) != schemes | sources:
        _fail("registry.descriptors", "registry descriptor graph has an unexpected subject")
    if schemes & sources:
        _fail("registry.descriptors", "registry sources and schemes do not reconcile")
    policies = _profile_policies()
    resource_ids: list[str] = []
    concept_scheme_count = 0
    observed_dispositions: Counter[str] = Counter()
    source_identities: dict[URIRef, tuple[str, str]] = {}
    for source in sorted(sources):
        if not isinstance(source, URIRef):
            _fail("registry.descriptors", "registry source identity is not an IRI")
        source_identifier = _literal_text(
            _one(graph, source, DCTERMS.identifier, code="registry.descriptors"),
            code="registry.descriptors",
            label="registry source identifier",
        )
        source_title = _literal_text(
            _one(graph, source, DCTERMS.title, code="registry.descriptors"),
            code="registry.descriptors",
            label="registry source title",
        )
        disposition = _literal_text(
            _one(graph, source, ATLAS.memberDisposition, code="registry.descriptors"),
            code="registry.descriptors",
            label="registry source member disposition",
        )
        if disposition not in MEMBER_DISPOSITIONS:
            _fail(
                "registry.descriptors",
                f"registry source {source} has an unsupported member disposition",
            )
        source_schemes = set(graph.subjects(ATLAS.sourceDescriptor, source))
        if disposition == "mappingAssertionsOnly":
            if source_schemes:
                _fail(
                    "registry.descriptors",
                    f"mapping-only registry source {source} unexpectedly has a scheme",
                )
        elif len(source_schemes) != 1:
            _fail(
                "registry.descriptors",
                f"registry source {source} does not have one primary scheme",
            )
        observed_dispositions[disposition] += 1
        payload_literal = _one(
            graph,
            source,
            ATLAS.descriptorPayload,
            code="registry.descriptors",
        )
        if not isinstance(payload_literal, Literal) or payload_literal.datatype != RDF.JSON:
            _fail(
                "registry.descriptors",
                f"registry source {source} payload is not rdf:JSON",
            )
        try:
            payload = json.loads(
                str(payload_literal),
                object_pairs_hook=_reject_duplicate_keys,
                parse_float=_reject_float,
                parse_constant=_reject_constant,
                parse_int=_parse_int,
            )
        except (AtlasValidationError, json.JSONDecodeError) as exc:
            _fail(
                "registry.descriptors",
                f"registry source {source} payload is invalid: {exc}",
            )
        if (
            not isinstance(payload, Mapping)
            or canonical_json_bytes(payload, terminal_lf=False).decode("utf-8")
            != str(payload_literal)
            or payload.get("resourceId") != source_identifier
            or payload.get("title") != source_title
        ):
            _fail(
                "registry.descriptors",
                f"registry source {source} payload is not a lossless canonical row",
            )
        source_identities[source] = (source_identifier, source_title)
        resource_ids.append(source_identifier)

    for scheme in sorted(schemes):
        if not isinstance(scheme, URIRef):
            _fail("registry.descriptors", "registry descriptor scheme identity is not an IRI")
        profile = _iri(
            _one(graph, scheme, ATLAS.resourceProfile, code="registry.descriptors"),
            code="registry.descriptors",
            label="registry descriptor profile",
        )
        policy = policies.get(profile)
        if policy is None:
            _fail("registry.descriptors", f"registry descriptor uses unknown profile {profile}")
        allowed_rings = {URIRef(str(ATLAS) + value) for value in policy["applicableSemanticRings"]}
        supported_rings = set(graph.objects(scheme, ATLAS.supportedRing))
        if supported_rings - allowed_rings:
            _fail("registry.descriptors", f"registry descriptor {scheme} has an unsupported ring")
        is_concept_scheme = (scheme, RDF.type, SKOS.ConceptScheme) in graph
        hosts_subject_concepts = ATLAS.subject in supported_rings
        if is_concept_scheme != (
            profile == ATLAS.conceptScheme or hosts_subject_concepts
        ):
            _fail("registry.descriptors", f"registry descriptor {scheme} has inconsistent SKOS typing")
        concept_scheme_count += int(is_concept_scheme)

        identifier = _literal_text(
            _one(graph, scheme, DCTERMS.identifier, code="registry.descriptors"),
            code="registry.descriptors",
            label="registry descriptor identifier",
        )
        title = _literal_text(
            _one(graph, scheme, DCTERMS.title, code="registry.descriptors"),
            code="registry.descriptors",
            label="registry descriptor title",
        )
        source = _iri(
            _one(graph, scheme, ATLAS.sourceDescriptor, code="registry.descriptors"),
            code="registry.descriptors",
            label="registry source descriptor",
        )
        if source not in sources:
            _fail("registry.descriptors", f"registry descriptor {scheme} names an unknown source")
        source_identifier, source_title = source_identities[source]
        if (source_identifier, source_title) != (identifier, title):
            _fail("registry.descriptors", f"registry descriptor {scheme} differs from its source")

    actual_counts = {
        "conceptSchemeCount": concept_scheme_count,
        "quadCount": len(graph),
        "registrySourceCount": len(sources),
        "resourceSchemeCount": len(schemes),
        "supportedRingStatementCount": len(list(graph.triples((None, ATLAS.supportedRing, None)))),
    }
    for name, value in actual_counts.items():
        if counts[name] != value:
            _fail("registry.descriptors", f"registry descriptor {name} differs")
    if dict(sorted(observed_dispositions.items())) != dict(disposition_counts):
        _fail("registry.descriptors", "registry descriptor member dispositions differ")
    if len(resource_ids) != len(set(resource_ids)) or proof.get("resourceIdSetDigest") != canonical_sha256(
        sorted(resource_ids), terminal_lf=False
    ):
        _fail("registry.descriptors", "registry descriptor resource identity set differs")
    return {name: int(value) for name, value in scalar_counts.items()}


def validate_binding() -> dict[str, Any]:
    """Validate schemas, ontology, shapes, registry proof, and corpus."""

    schemas, registry = _schema_registry()
    ontology, shapes = _parse_binding_graphs()
    _lint_ontology(ontology)

    # Meta-SHACL runs before any fixture can claim data conformance.
    empty = {role: Graph() for role in ("asserted", "projection", "derived")}
    try:
        meta_conforms, _, meta_report = shacl_validate(
            empty["asserted"],
            shacl_graph=shapes,
            ont_graph=ontology,
            inference="none",
            advanced=False,
            meta_shacl=True,
        )
    except Exception as exc:  # noqa: BLE001 - normalize SHACL processor failures
        _fail("shacl.meta", f"shape graph is not well formed: {exc}")
    if not meta_conforms:
        compact = " ".join(str(meta_report).split())
        _fail("shacl.meta", f"shape graph does not conform to SHACL-SHACL: {compact[:900]}")

    corpus = _load_json(CORPUS_PATH, require_canonical=True)
    _validate_json_schema(corpus, "corpus", schemas=schemas, registry=registry, label="corpus")
    case_ids = {case["id"] for case in corpus["cases"]}
    if case_ids != REQUIRED_CORPUS_CASES:
        _fail(
            "corpus.coverage",
            f"corpus cases differ; missing={sorted(REQUIRED_CORPUS_CASES - case_ids)}, extra={sorted(case_ids - REQUIRED_CORPUS_CASES)}",
        )
    declared_paths = {case["path"] for case in corpus["cases"]}
    # The case tree is generated and not committed, so in a fresh checkout it
    # is legitimately absent. Say so instead of raising FileNotFoundError out
    # of the directory walk below: the fix is one command, and the validator
    # stays a validator -- it never builds anything itself.
    for role in ("valid", "invalid"):
        if not (FIXTURE_ROOT / role).is_dir():
            _fail(
                "corpus.coverage",
                f"fixture case tree is missing at {FIXTURE_ROOT / role}; it is generated, "
                "not committed -- run tools/build_fixtures.py (or make check-generated)",
            )
    fixture_paths = {
        f"{role}/{path.name}"
        for role in ("valid", "invalid")
        for path in (FIXTURE_ROOT / role).iterdir()
        if path.is_dir() and not path.is_symlink()
    }
    if declared_paths != fixture_paths:
        _fail(
            "corpus.coverage",
            f"corpus paths differ from fixture directories; missing={sorted(fixture_paths - declared_paths)}, extra={sorted(declared_paths - fixture_paths)}",
        )
    results: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for case in corpus["cases"]:
        relative = case["path"]
        if relative in seen_paths or relative.startswith("/") or ".." in Path(relative).parts:
            _fail("corpus.path", f"unsafe or duplicate corpus path {relative!r}")
        seen_paths.add(relative)
        case_path = (FIXTURE_ROOT / relative).resolve()
        try:
            case_path.relative_to(FIXTURE_ROOT.resolve())
        except ValueError:
            _fail("corpus.path", f"case escapes fixture root: {relative}")
        try:
            validate_distribution(case_path)
        except AtlasValidationError as exc:
            if case["expected"] == "valid":
                _fail("corpus.verdict", f"valid case {case['id']} failed with {exc}")
            expected_issue = case["firstIssue"]
            if exc.code != expected_issue:
                _fail(
                    "corpus.first-issue",
                    f"case {case['id']} expected {expected_issue}, observed {exc.code}: {exc.detail}",
                )
            # `firstIssue` is a golden observation of a fail-closed order the
            # binding does not promise; the constraint components are not.
            # They are what the operator acts on, so the 46 `shacl.data` cases
            # that used to pin nothing but the code now pin the component list
            # as well. Checked in whichever mode is running -- the extraction
            # is a regex over a verdict already raised, so there is no cost to
            # gate behind a tier, and the release-tier cross-mode sweep is what
            # proves the two modes cannot name different components.
            expected_components = case.get("shaclComponents")
            if expected_components is not None:
                observed_components = shacl_constraint_components(exc)
                if observed_components != list(expected_components):
                    _fail(
                        "corpus.shacl-components",
                        f"case {case['id']} expected components {list(expected_components)}, "
                        f"observed {observed_components}",
                    )
                if observed_components != sorted(set(observed_components)):
                    _fail(
                        "corpus.shacl-components",
                        f"case {case['id']} components are not sorted and unique: {observed_components}",
                    )
            results.append({"id": case["id"], "result": "rejected", "issue": exc.code})
        else:
            if case["expected"] == "invalid":
                _fail("corpus.verdict", f"invalid case {case['id']} passed")
            results.append({"id": case["id"], "result": "accepted"})

    if not PROFILE_MAP_PATH.is_file() or not REGISTRY_COVERAGE_PATH.is_file():
        _fail("registry.coverage", "registry profile map or coverage report is missing")
    profile_map = _load_json(PROFILE_MAP_PATH, require_canonical=True)
    coverage = _load_json(REGISTRY_COVERAGE_PATH, require_canonical=True)
    _validate_json_schema(
        profile_map,
        "registryProfiles",
        schemas=schemas,
        registry=registry,
        label="registry profile policy",
    )
    _validate_json_schema(
        coverage,
        "registryCoverage",
        schemas=schemas,
        registry=registry,
        label="registry coverage proof",
    )
    policies = _profile_policies()
    expected_coverage_keys = {
        "coverageDigest",
        "format",
        "inputs",
        "profiles",
        "schemaVersion",
        "setDigests",
        "summary",
        "unsupported",
    }
    if set(coverage) != expected_coverage_keys:
        _fail("registry.coverage", "registry coverage fields are incomplete or unknown")
    if profile_map.get("schemaVersion") != "3.1" or coverage.get("schemaVersion") != "3.1":
        _fail("registry.coverage", "registry proof uses another Atlas version")
    if coverage.get("format") != "refspec-atlas-registry-coverage/3.1":
        _fail("registry.coverage", "registry coverage format is not Atlas 3.1")
    claimed_coverage_digest = coverage["coverageDigest"]
    expected_coverage_digest = canonical_sha256(
        {key: value for key, value in coverage.items() if key != "coverageDigest"},
        terminal_lf=False,
    )
    if claimed_coverage_digest != expected_coverage_digest:
        _fail("registry.coverage", "coverageDigest does not match the canonical report")
    inputs = coverage.get("inputs")
    if not isinstance(inputs, Mapping) or set(inputs) != {
        "atlasIndexDigest",
        "registryResourceProfilesDigest",
        "resourceCatalogDigest",
    }:
        _fail("registry.coverage", "registry report input receipt is malformed")
    set_digests = coverage.get("setDigests")
    if not isinstance(set_digests, Mapping) or set(set_digests) != {
        "catalogOnlyDescriptorIds",
        "catalogResourceIds",
        "implementationModules",
        "indexedPlacementIdentities",
        "indexedResourceIds",
        "indexedSemanticRings",
        "indexedWithoutExactReleaseIds",
        "registryModules",
        "releaseReadyIndexedResourceIds",
        "sourceModules",
    }:
        _fail("registry.coverage", "registry report set-digest receipt is malformed")
    if inputs.get("registryResourceProfilesDigest") != profile_map["profileDigest"]:
        _fail("registry.coverage", "registry report does not pin the profile policy")
    for digest in [*inputs.values(), *set_digests.values()]:
        if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
            _fail("registry.coverage", "registry report contains a malformed digest")
    if coverage.get("unsupported") != {"modules": [], "resourceKinds": [], "resources": []}:
        _fail("registry.coverage", "registry coverage report contains unsupported items")
    expected_profiles = {str(profile).removeprefix(str(ATLAS)) for profile in policies}
    profile_rows = coverage.get("profiles")
    if not isinstance(profile_rows, Mapping) or set(profile_rows) != expected_profiles:
        _fail("registry.coverage", "registry report profile rows differ from profile policy")
    summary = coverage.get("summary")
    expected_summary_keys = {
        "atlasIndexRowCount",
        "catalogOnlyDescriptorCount",
        "catalogResourceCount",
        "implementationModuleCount",
        "indexedResourceCount",
        "indexedWithoutExactReleaseCount",
        "registryModuleCount",
        "releaseReadyIndexedResourceCount",
        "resourceKindCounts",
        "sourceModuleCount",
    }
    if not isinstance(summary, Mapping) or set(summary) != expected_summary_keys:
        _fail("registry.coverage", "registry report summary fields are incomplete or unknown")
    integer_summary = {name: value for name, value in summary.items() if name != "resourceKindCounts"}
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in integer_summary.values()):
        _fail("registry.coverage", "registry report summary counts must be non-negative integers")
    resource_kind_counts = summary.get("resourceKindCounts")
    if (
        not isinstance(resource_kind_counts, Mapping)
        or not resource_kind_counts
        or any(
            not isinstance(name, str) or not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for name, value in resource_kind_counts.items()
        )
    ):
        _fail("registry.coverage", "registry resource-kind counts are malformed or vacuous")
    expected_profile_row_keys = {
        "catalogOnlyDescriptorCount",
        "catalogResourceCount",
        "indexedResourceCount",
        "indexedRowCount",
        "indexedWithoutExactReleaseCount",
        "releaseReadyIndexedResourceCount",
        "semanticRingCounts",
    }
    for profile_name, row in profile_rows.items():
        if not isinstance(row, Mapping) or set(row) != expected_profile_row_keys:
            _fail("registry.coverage", f"registry profile row {profile_name} is malformed")
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for name, value in row.items()
            if name != "semanticRingCounts"
        ):
            _fail("registry.coverage", f"registry profile row {profile_name} has invalid counts")
        ring_counts = row.get("semanticRingCounts")
        if not isinstance(ring_counts, Mapping) or any(
            URIRef(str(ATLAS) + ring) not in RING_RESOURCE_CLASSES
            or not isinstance(value, int)
            or isinstance(value, bool)
            or value <= 0
            for ring, value in ring_counts.items()
        ):
            _fail("registry.coverage", f"registry profile row {profile_name} has invalid ring counts")
        if row["catalogResourceCount"] != row["indexedResourceCount"] + row["catalogOnlyDescriptorCount"]:
            _fail("registry.coverage", f"registry profile row {profile_name} resource counts do not reconcile")
        if row["indexedResourceCount"] != (
            row["releaseReadyIndexedResourceCount"] + row["indexedWithoutExactReleaseCount"]
        ):
            _fail("registry.coverage", f"registry profile row {profile_name} release counts do not reconcile")
        if sum(ring_counts.values()) != row["indexedRowCount"]:
            _fail("registry.coverage", f"registry profile row {profile_name} ring counts do not reconcile")
    required_positive_counts = {
        "atlasIndexRowCount",
        "catalogResourceCount",
        "indexedResourceCount",
        "registryModuleCount",
        "sourceModuleCount",
    }
    if any(not isinstance(summary.get(name), int) or summary[name] <= 0 for name in required_positive_counts):
        _fail("registry.coverage", "registry report has missing or vacuous summary counts")
    if summary["registryModuleCount"] != summary["sourceModuleCount"] + summary["implementationModuleCount"]:
        _fail("registry.coverage", "registry module counts do not reconcile")
    if summary["catalogResourceCount"] != summary["indexedResourceCount"] + summary["catalogOnlyDescriptorCount"]:
        _fail("registry.coverage", "catalog resource counts do not reconcile")
    if summary["indexedResourceCount"] != (
        summary["releaseReadyIndexedResourceCount"] + summary["indexedWithoutExactReleaseCount"]
    ):
        _fail("registry.coverage", "indexed resource counts do not reconcile")
    if sum(resource_kind_counts.values()) != summary["catalogResourceCount"]:
        _fail("registry.coverage", "registry resource-kind counts do not reconcile")
    if sum(row["catalogResourceCount"] for row in profile_rows.values()) != summary["catalogResourceCount"]:
        _fail("registry.coverage", "profile resource counts do not reconcile")
    if sum(row["indexedRowCount"] for row in profile_rows.values()) != summary["atlasIndexRowCount"]:
        _fail("registry.coverage", "profile index counts do not reconcile")
    descriptor_counts = _check_registry_descriptors(
        profile_map,
        coverage,
        schemas=schemas,
        registry=registry,
    )
    return {
        "caseCount": len(results),
        "invalidCount": sum(row["result"] == "rejected" for row in results),
        "registryDescriptorCount": descriptor_counts["resourceSchemeCount"],
        "registryDescriptorQuadCount": descriptor_counts["quadCount"],
        "schemaCount": len(schemas),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--distribution",
        type=Path,
        help="validate one distribution instead of the complete binding corpus",
    )
    parser.add_argument(
        "--smoke",
        type=Path,
        help=(
            "NOT ACCEPTANCE: sample one distribution in seconds -- manifest "
            "schema, manifest digest, binding pins, and SHACL data "
            "conformance over a bounded pack sample. A green smoke run "
            "proves nothing about the distribution as a whole; use "
            "--distribution for a verdict"
        ),
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        help="private local receipt cache for repeated --distribution validation",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="suppress human-facing status lines on stderr",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    global _STATUS

    args = _parser().parse_args(list(argv) if argv is not None else None)
    _STATUS = _StatusReporter(
        enabled=not args.quiet and (args.distribution is not None or args.smoke is not None),
    )
    if args.distribution is not None:
        _STATUS.phase("validate-distribution")
    elif args.smoke is not None:
        _STATUS.phase("smoke-check")
    try:
        if args.smoke is not None and args.distribution is not None:
            _fail("smoke.mode", "--smoke and --distribution answer different questions; pass one")
        # A smoke result is a sample, never a verdict, so it must never be
        # able to reach the receipt cache -- neither to read one nor to leave
        # one that a later acceptance run could be answered from.
        if args.cache_dir is not None and args.distribution is None:
            _fail("cache.path", "--cache-dir requires --distribution")
        result = (
            validate_distribution(args.distribution, cache_dir=args.cache_dir)
            if args.distribution
            else smoke_check(args.smoke)
            if args.smoke
            else validate_binding()
        )
    except AtlasValidationError as exc:
        _STATUS.phase("failed", current=exc.code)
        print(str(exc), file=sys.stderr)
        return 1
    _STATUS.phase("complete")
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


def _prepare_cli_heap_for_exit() -> None:
    """Leave RDFLib cycles to the OS after the standalone CLI has finished.

    A full Atlas keeps tens of millions of indexed RDF terms in cycles between
    RDFLib graph views and their shared in-memory store.  CPython otherwise
    walks and finalizes those unreachable cycles during interpreter shutdown,
    after the validator has already emitted its result.  At this actual process
    boundary there is no later Python consumer, so freezing the tracked heap is
    equivalent semantically and lets normal process teardown reclaim it in one
    operation.  Library callers retain ordinary garbage-collection behavior.
    """

    sys.stdout.flush()
    sys.stderr.flush()
    gc.freeze()


def _run_cli() -> int:
    """Run the standalone command and prepare its completed heap for exit."""

    exit_status = main()
    _prepare_cli_heap_for_exit()
    return exit_status


if __name__ == "__main__":
    raise SystemExit(_run_cli())
