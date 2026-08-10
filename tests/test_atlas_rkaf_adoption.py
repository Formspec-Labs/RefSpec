"""The Atlas binding may not carry a second name for a concept rkaf defines.

RefSpec owns structure and taxonomy; Rulespec owns decision-making. On the
wire that boundary is concrete: ``atlas:`` legitimately mints terms for
releases, packs, digests, semantic rings, and resource profiles, and nothing
else. Everything epistemic -- evidence, review, attestation, warrant,
adoption, lifecycle -- is rkaf's, and adopting it means an ``rkaf:`` IRI in
the published ontology, shapes, and schemas rather than an ``atlas:`` alias
linked by an axiom.

WHY THIS GATE IS SCOPED AND NOT BLANKET
--------------------------------------
"No ``atlas:`` local name may equal an ``rkaf:`` local name" cannot pass and
must not be written. ``atlas:subject`` is one of the four SemanticRing
individuals -- the taxonomy half RefSpec owns outright -- while ``rkaf:subject``
is "the IRI of the object the finding concerns" (``constraints/core/finding.cue``).
They are genuine homographs, not a duplicated concept, and a blanket rule
would demand RefSpec rename its own ring.

The scope is therefore stated as a predicate, not as an exception list: a
duplicated local name is permitted only when the ``atlas:`` side is an
individual of ``atlas:SemanticRing`` or ``atlas:ResourceProfile``. Every other
duplication is a concept rkaf already defines, and the fix is to adopt rkaf's
term and delete Atlas's. An exception list would be exactly the structure
AGENTS.md interrogates: it excuses violations instead of breaking on them.
This predicate breaks on a new one -- mint ``atlas:warrant`` tomorrow and the
gate fires, because a warrant is not a ring.

WIRE ADOPTION OWES A RUNNING CHECK
----------------------------------
Adopting a term is not renaming a string. ``WIRE_ADOPTIONS`` below pairs every
rkaf term the Atlas binding puts on the wire with the invalid conformance case
whose rejection depends on it. A term with no case behind it is ceremony: it
would not break if a producer got it wrong, so it does not belong in the
published binding at all.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import RDF

from tests.test_rulespec_vocabulary_currency import (
    _extract_rkaf_terms,
    discover_rulespec_checkout,
    rulespec_vocabulary_terms,
)

REFSPEC_ROOT = Path(__file__).resolve().parents[1]
BINDING_ROOT = REFSPEC_ROOT / "bindings" / "atlas" / "3.0"
ONTOLOGY = BINDING_ROOT / "ontology" / "atlas.ttl"
SHAPES = BINDING_ROOT / "shapes" / "atlas.shacl.ttl"
SCHEMAS = BINDING_ROOT / "schemas"
CORPUS = BINDING_ROOT / "fixtures" / "corpus.json"

ATLAS = Namespace("https://refspec.org/ns/atlas/v3#")
RKAF = Namespace("https://rulespec.org/ns/v1#")

# Same shape as the rkaf extractor in test_rulespec_vocabulary_currency: the
# ``(?<!urn:)`` guard keeps RefSpec's own ``urn:...:atlas:...`` identifiers out.
_ATLAS_COMPACT_IRI = re.compile(r"(?<!urn:)\batlas:([A-Za-z][A-Za-z0-9_-]*)")
_ATLAS_FULL_IRI = re.compile(
    r"https://refspec\.org/ns/atlas/v3#([A-Za-z][A-Za-z0-9_-]*)"
)

# The published binding: the three artifacts a consumer receives and reads as
# the vocabulary. Fixtures are generated from these, so a term that survives
# only in a fixture is a generator bug the fixture builder's own check catches.
_PUBLISHED = (ONTOLOGY, SHAPES, *sorted(SCHEMAS.glob("*.json")))

# Every rkaf term the published binding puts on the wire, mapped to the
# invalid conformance case whose rejection depends on it. Delete a row and the
# term must leave the wire; add a term without a row and this file fails.
#
# Several machine-adjudication rows share one case on purpose. A record class
# adopted from rulespec must carry EVERY field its upstream definition requires
# -- a sh:closed shape that drops one both accepts records rulespec rejects and
# rejects records rulespec requires -- so for the fields whose only Atlas
# obligation is that completeness, the case that breaks is the one that removes
# a field from that closed shape: adjudication-issuer-incomplete,
# adjudication-lineage-incomplete, adjudication-comparison-incomplete. Every
# field carrying an Atlas-specific obligation beyond presence names the case
# that forges exactly that fact instead.
WIRE_ADOPTIONS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    # term: (invalid conformance cases that break without it, enum members it
    # closes). A member is enforced by the same sh:in that enforces its
    # predicate, so one out-of-enum fixture proves the whole closed set fires.
    #
    # Already landed (e2ca150) -- the working precedent for a correct adoption.
    "membershipMode": (
        ("release-membership-mode-unknown",),
        ("completeMembership", "partialMembership", "membershipNotEnumerated"),
    ),
    # Phase 4 -- evidence and review.
    "EvidenceBinding": (
        ("mapping-missing-evidence", "cross-ring-missing-evidence"),
        (),
    ),
    "bindsAssertion": (("evidence-retargeted",), ()),
    "attestor": (("evidence-reviewer-retargeted",), ()),
    "basedOnAttestation": (
        ("adoption-without-referent", "adoption-chain-cycle"),
        (),
    ),
    "attestorKind": (
        ("evidence-attestor-kind-unknown",),
        (
            "humanUser", "aiModel", "aiAgent", "automatedParser", "team",
            "organization", "community", "formalReviewer",
            "conceptMintingAuthority",
        ),
    ),
    "decision": (("evidence-decision-not-approved",), ("approved",)),
    "attestedAt": (("evidence-attested-at-not-datetime",), ()),
    "assertionOrigin": (
        ("evidence-warrant-unsanctioned",),
        ("humanAsserted", "aiSuggested", "imported", "deterministicExtraction"),
    ),
    "epistemicBasis": (
        ("evidence-warrant-unsanctioned",),
        (
            "sourceExplicit", "deterministicDerivation", "statisticalInference",
            "editorialAssertion", "userAssertion",
        ),
    ),
    "evidenceRole": (
        ("evidence-warrant-unsanctioned",),
        (
            "textualEvidence", "structuralEvidence", "retrievalSignal",
            "authorityCitation", "officialSourceMetadata",
            "reviewedAuthorityChain", "formalAdoptionEvent",
            "mappingRationale", "registrationEvent", "rescissionEvidence",
        ),
    ),
    "evidentiaryFunction": (
        ("evidence-function-unknown",),
        (
            "supports", "qualifies", "contradicts", "definesScope",
            "providesContext",
        ),
    ),
    # The two free adoptions: identical meaning on both sides, renamed because
    # the local name was already Rulespec's.
    "assertedAt": (("assertion-asserted-at-not-datetime",), ()),
    "inputDigest": (("derived-input-digest",), ()),
    # Phase 5 -- lifecycle and supersession (79eaa2a). atlas:LifecycleEvent,
    # atlas:AssertionStatus and their properties are gone; a status is now
    # derived from an incoming rkaf:supersedesAssertion edge or an applicable
    # rkaf:rescission event, matching validate.py's own derivation.
    "LifecycleEvent": (
        (
            "lifecycle-applies-to-nonassertion",
            "lifecycle-effective-date-not-datetime",
            "lifecycle-event-kind-unknown",
            "lifecycle-rescission-names-target-release",
        ),
        (),
    ),
    "appliesTo": (("lifecycle-applies-to-nonassertion",), ()),
    "lifecycleEventKind": (
        ("lifecycle-event-kind-unknown",),
        ("supersession", "rescission"),
    ),
    "effectiveDate": (("lifecycle-effective-date-not-datetime",), ()),
    "supersedesAssertion": (("supersession-without-event",), ()),
    # Phase 6 -- the machine-adjudication protocol. Atlas 1.0 carried it as
    # atlas:MachineValidation / atlas:verdictRelation / atlas:qualifiedBy /
    # atlas:inputContextDigest; rulespec's analysis package now owns every one
    # of those semantics, so v3 publishes rkaf's four record classes and mints
    # nothing at all. Each row names the case that forges exactly that fact.
    "ResolverProofRecord": (
        ("adjudication-single-proof", "adjudication-proof-record-digest"),
        (),
    ),
    "proofType": (
        ("adjudication-proof-type-not-machine",),
        ("machineAdjudicationProof",),
    ),
    # Three of the five independence axes hang off this property and the issuer
    # record it resolves to: the issuer IRI is the validator actor, and its
    # rkaf:proofResolver is the provider.
    "proofIssuer": (
        ("adjudication-same-validator-actor", "adjudication-same-provider"),
        (),
    ),
    "ResolverProofIssuer": (("adjudication-same-provider",), ()),
    "proofResolver": (("adjudication-same-provider",), ()),
    "hasAILineage": (("adjudication-same-provider-model",), ()),
    "AILineage": (("adjudication-same-provider-model",), ()),
    "modelId": (("adjudication-same-provider-model",), ()),
    "independenceGroup": (("adjudication-same-independence-group",), ()),
    "sealedResponseArtifact": (
        (
            "adjudication-same-response-artifact",
            "adjudication-response-artifact-cardinality",
        ),
        (),
    ),
    "sealedRequestDigest": (("adjudication-mismatched-sealed-request",), ()),
    "adjudicationVerdict": (
        ("adjudication-relation-not-licensed", "adjudication-verdicts-disagree"),
        (
            "verdictSame", "verdictNearSame", "verdictTargetBroader",
            "verdictTargetNarrower", "verdictRelated",
        ),
    ),
    "proofComparisonContext": (("adjudication-foreign-comparison",), ()),
    # Not pinned to rkaf:gatePass: a published refusal is an audit record, and
    # a consumer that cannot tell "never adjudicated" from "adjudicated and
    # refused" has lost the distinction rulespec keeps an outcome enum for.
    # What breaks is LICENSING a mapping on a proof whose gate did not pass.
    "proofOutcome": (
        ("adjudication-licensing-proof-refused",),
        ("gatePass", "gateFail", "gateUnknown"),
    ),
    "proofRationale": (("adjudication-proof-rationale-empty",), ()),
    # The snapshot chain: a proof reads its comparison's snapshot, and that is
    # the release the mapping targets.
    "proofSnapshot": (("adjudication-proof-snapshot-drift",), ()),
    "proofResolverVersion": (("adjudication-issuer-incomplete",), ()),
    "proofPolicy": (("adjudication-issuer-incomplete",), ()),
    "proofPolicyVersion": (("adjudication-issuer-incomplete",), ()),
    "modelVersion": (("adjudication-lineage-incomplete",), ()),
    "promptTemplateRef": (("adjudication-lineage-incomplete",), ()),
    "temperature": (("adjudication-lineage-incomplete",), ()),
    "inputContextHash": (("adjudication-input-context-hash",), ()),
    # rkaf:Artifact is what turns a sealed digest into bytes a reviewer can
    # re-read. Four per comparison: the two compared endpoints, the sealed
    # request, and one sealed response per proof.
    "Artifact": (
        (
            "adjudication-request-artifact-unbundled",
            "adjudication-response-artifact-unbundled",
        ),
        (),
    ),
    "hasArtifactIdentifier": (("adjudication-endpoint-artifact-drift",), ()),
    "artifactIdentifierScheme": (
        ("adjudication-artifact-scheme-unknown",),
        ("partner-defined",),
    ),
    "hasContentDigest": (("adjudication-request-digest-mismatch",), ()),
    "comparisonBaselineArtifact": (("adjudication-endpoint-artifact-drift",), ()),
    "comparisonObservedArtifact": (("adjudication-endpoint-artifact-drift",), ()),
    "comparisonConsumer": (("adjudication-comparison-incomplete",), ()),
    "comparisonScope": (("adjudication-comparison-incomplete",), ()),
    "comparisonEvaluationTime": (("adjudication-comparison-incomplete",), ()),
    "comparisonPolicyVersion": (("adjudication-comparison-incomplete",), ()),
    "comparisonDetector": (("adjudication-comparison-incomplete",), ()),
    "comparisonDetectorVersion": (("adjudication-comparison-incomplete",), ()),
    "comparisonSnapshot": (("adjudication-foreign-snapshot",), ()),
    "proofInput": (("adjudication-proof-input-digest",), ()),
    "proofInputDigest": (("adjudication-proof-input-digest",), ()),
    "proofEvaluatedAt": (("adjudication-evaluated-at-not-datetime",), ()),
    "proofRecordDigest": (("adjudication-proof-record-digest",), ()),
    "RelationComparisonContext": (
        ("adjudication-discarded-support", "adjudication-comparison-retargeted"),
        (),
    ),
    "comparisonProofRecord": (
        ("adjudication-discarded-support", "adjudication-single-proof"),
        (),
    ),
    "comparisonExpectedAssertion": (("adjudication-comparison-retargeted",), ()),
    # Phase 7 -- ring temporal context. A value-ring crosswalk and a legal-
    # identity equivalence are claims about a period; the registry has required
    # the dates since it had rings, and none of it reached the wire. No atlas:
    # term is minted here either -- see the ring-temporal block in
    # ontology/atlas.ttl for why the editions stay the release pins they already
    # were.
    "EffectivePeriod": (
        ("mapping-period-end-before-start", "mapping-period-start-not-datetime"),
        (),
    ),
    "hasEffectivePeriod": (
        (
            "mapping-undated-value-crosswalk",
            "mapping-undated-legal-identity",
            "mapping-subject-ring-dated",
        ),
        (),
    ),
    "effectivePeriodStart": (("mapping-period-start-not-datetime",), ()),
    "effectivePeriodEnd": (("mapping-period-end-before-start",), ()),
    # Phase 8 -- the conflict record. Two atlas:Identifier records claiming one
    # (scheme, value) pair for different resources used to refuse the whole
    # distribution and retain nothing; it now MAY be published, but only with a
    # record naming exactly the entries that disagree. rkaf:Finding is
    # deliberately absent -- see the registry-conflict block in
    # ontology/atlas.ttl for the surface it would have had and why there is not
    # one. The two cross-record cases below are validate.py's, not the SHACL's:
    # matching a record against the disagreement compares several records, which
    # per-property SHACL cannot reach.
    "RegistryConflict": (
        ("registry-conflict-single-entry", "registry-conflict-entries-mismatch"),
        (),
    ),
    "conflictingEntries": (
        ("registry-conflict-single-entry", "registry-conflict-entries-mismatch"),
        (),
    ),
    # Narrowed to two of rkaf's four: a published distribution cannot honestly
    # declare its own conflict publication-blocking or authority-critical, so
    # registry-conflict-publication-blocking is what breaks if the sh:in is ever
    # widened back to the full ladder.
    "severity": (
        (
            "registry-conflict-severity-unknown",
            "registry-conflict-publication-blocking",
        ),
        ("informational", "operationalConflict"),
    ),
    "detectedAt": (("registry-conflict-detected-at-not-datetime",), ()),
    "comparisonOutcome": (
        ("adjudication-licensed-by-conflicted-comparison",),
        (
            "comparisonSatisfied", "comparisonAffirmedDeniedDiscrepancy",
            "comparisonConflict", "comparisonNotComparable", "comparisonUnknown",
        ),
    ),
}
ADOPTED_TERMS = frozenset(WIRE_ADOPTIONS) | {
    member for _, members in WIRE_ADOPTIONS.values() for member in members
}
ADOPTED_CASES = {
    term: cases for term, (cases, _) in WIRE_ADOPTIONS.items()
}


def _rdf_local_names(namespace: str) -> set[str]:
    """Local names in one namespace that the published RDF actually asserts.

    Parsed, never scanned: an rdfs:comment that names a term is documentation,
    and a text scan cannot tell that from a term the binding puts on the wire.
    """

    names: set[str] = set()
    for path in (ONTOLOGY, SHAPES):
        graph = Graph().parse(path, format="turtle")
        for triple in graph:
            for term in triple:
                text = str(term)
                if isinstance(term, URIRef) and text.startswith(namespace):
                    names.add(text[len(namespace) :])
    return names


def _published_atlas_local_names() -> set[str]:
    names = _rdf_local_names(str(ATLAS))
    for path in sorted(SCHEMAS.glob("*.json")):
        text = path.read_text(encoding="utf-8")
        names |= set(_ATLAS_COMPACT_IRI.findall(text))
        names |= set(_ATLAS_FULL_IRI.findall(text))
    return names


def _published_rkaf_local_names() -> set[str]:
    names = _rdf_local_names(str(RKAF))
    for path in sorted(SCHEMAS.glob("*.json")):
        names |= _extract_rkaf_terms(path.read_text(encoding="utf-8"))
    return names


def _atlas_owned_taxonomy_names() -> set[str]:
    """Local names of the ring and profile individuals RefSpec owns outright."""

    graph = Graph().parse(ONTOLOGY, format="turtle")
    return {
        str(individual).rsplit("#", 1)[-1]
        for taxonomy in (ATLAS.SemanticRing, ATLAS.ResourceProfile)
        for individual in graph.subjects(RDF.type, taxonomy)
    }


def _require_rulespec() -> Path:
    rulespec_dir = discover_rulespec_checkout()
    if rulespec_dir is None:
        pytest.skip(
            "no Rulespec checkout found (set REFSPEC_RULESPEC_CHECKOUT or "
            "clone Rulespec to ~/Work/rulespec) -- skipping the Atlas/rkaf "
            "term-collision gate"
        )
    return rulespec_dir


def test_no_atlas_term_duplicates_an_rkaf_term_outside_atlas_taxonomy() -> None:
    """The collision gate. Scoped by predicate, not by an exception list."""

    rulespec_dir = _require_rulespec()
    defined_upstream = rulespec_vocabulary_terms(rulespec_dir)
    assert defined_upstream, f"{rulespec_dir} looks empty"

    published_atlas = _published_atlas_local_names()
    assert published_atlas, "the atlas: extraction regex is broken"

    owned_taxonomy = _atlas_owned_taxonomy_names()
    assert owned_taxonomy, "the ontology declares no ring or profile individuals"

    collisions = sorted((published_atlas & defined_upstream) - owned_taxonomy)
    assert not collisions, (
        f"{len(collisions)} atlas: term(s) in the published binding duplicate a "
        f"local name Rulespec already defines: {collisions}. Rulespec owns "
        "decision-making; RefSpec owns structure and taxonomy. Adopt the rkaf: "
        "term on the wire and delete the atlas: one. The only permitted "
        "duplication is a semantic-ring or resource-profile individual, which "
        "RefSpec owns outright -- and if that is what this is, the ontology must "
        "say so by typing it."
    )


def test_the_gate_stays_scoped_and_keeps_the_ring_homograph_legal() -> None:
    """Widening the gate to a blanket rule must break, visibly, right here.

    ``atlas:subject`` is a SemanticRing individual and ``rkaf:subject`` is the
    IRI a Finding concerns. Both names are correct in their own namespace. If
    this assertion ever stops holding, either RefSpec renamed a ring or the
    scoping predicate above stopped recognising one -- and in both cases the
    collision gate silently changed meaning.
    """

    rulespec_dir = _require_rulespec()
    defined_upstream = rulespec_vocabulary_terms(rulespec_dir)
    owned_taxonomy = _atlas_owned_taxonomy_names()

    homographs = sorted(
        _published_atlas_local_names() & defined_upstream & owned_taxonomy
    )
    assert homographs, (
        "the scoped and blanket rules now agree, so the predicate is no longer "
        "doing any work -- either delete it or explain why it is still needed"
    )


def test_every_wire_adoption_reaches_the_published_shapes() -> None:
    """A term Atlas claims to adopt must actually appear on the wire."""

    published = _published_rkaf_local_names()
    missing = sorted(ADOPTED_TERMS - published)
    assert not missing, (
        f"{len(missing)} adopted rkaf: term(s) never reach the published "
        f"ontology, shapes, or schemas: {missing}. An adoption enforced only "
        "inside the Python validator keeps two parallel term sets alive."
    )


def test_no_rkaf_term_reaches_the_wire_without_an_adoption_record() -> None:
    """The inverse: nothing rides along on the wire unaccounted for."""

    undeclared = sorted(_published_rkaf_local_names() - ADOPTED_TERMS)
    assert not undeclared, (
        f"{len(undeclared)} rkaf: term(s) appear in the published binding with "
        f"no adoption record: {undeclared}. Add a row naming the invalid "
        "conformance case that breaks when the term is violated, or take the "
        "term off the wire."
    )


def test_every_wire_adoption_is_enforced_by_the_published_shapes() -> None:
    """The constraint that breaks must live in the SHACL a consumer runs."""

    graph = Graph().parse(SHAPES, format="turtle")
    enforced = {
        str(term)[len(str(RKAF)) :]
        for triple in graph
        for term in triple
        if isinstance(term, URIRef) and str(term).startswith(str(RKAF))
    }
    unenforced = sorted(ADOPTED_TERMS - enforced)
    assert not unenforced, (
        f"{len(unenforced)} adopted rkaf: term(s) carry no constraint in "
        f"shapes/atlas.shacl.ttl: {unenforced}. Declaring a term in the "
        "ontology proves nothing; write the shape that rejects the bad case."
    )


def test_every_wire_adoption_names_a_rejecting_conformance_case() -> None:
    """Each adoption's negative fixture must exist and be expected to fail."""

    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    rejected = {
        case["id"] for case in corpus["cases"] if case["expected"] == "invalid"
    }
    missing = sorted(
        {
            f"{term} -> {case}"
            for term, cases in ADOPTED_CASES.items()
            for case in cases
            if case not in rejected
        }
    )
    assert not missing, (
        f"{len(missing)} adopted rkaf: term(s) name a negative fixture the "
        f"conformance corpus does not reject: {missing}. Build the fixture in "
        "bindings/atlas/3.0/tools/build_fixtures.py so the validator proves the "
        "constraint fires."
    )
