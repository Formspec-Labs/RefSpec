"""Derived-graph rule: Federal Register thesaurus compound-heading broader.

``federal-register-thesaurus-2025`` is a deliberately flat vocabulary: 705
preferred terms, 1,451 ``skos:related`` assertions, and no broader or
narrower statement of any kind.  56 preferred labels contain a hyphen, and
in 48 of those the text before the first hyphen is itself an authorized
preferred term of the same release (``Grant programs-agriculture`` ->
``Grant programs``).  The remaining 8 are hyphenated words, not compound
subjects, and the rule refuses them for exactly one reason: their head
segment is not an authorized preferred term.  There is no denylist, so a
future release that minted a preferred term ``X`` would immediately admit
``X-rays`` -> ``X`` -- that self-exclusion is the running check, and the
tests prove it by minting exactly such a term.

This module is the rule, its wire shape, and its reproduction check.  It is
deliberately standalone.  The Atlas 3.1 validator allowlists exactly one
derivation rule today (``urn:ref:rule:skos-exact-match-closure-path`` with
owlrl 7.1.4), so populating these rows into a distribution requires a
binding revision that (a) allowlists this rule IRI with its engine pin,
(b) admits label-shaped evidence for ``atlas:derivedFromAssertion`` -- the
rule reads preferred-label text, and a label row is not a relation
assertion -- and (c) replays this rule's semantics instead of the
exactMatch simple-path replay.  Until that revision lands, nothing here is
wired into ``tools/generate_atlas_v3_full.py``; the derived graph stays at
zero quads and the producer keeps refusing to populate it.

Rows follow the binding's ``atlas:DerivedRelationShape`` exactly: one
content-derived ``urn:ref:atlas-derived:<hex>`` node per edge, carrying the
rule IRI, engine pin, the two cited label rows as evidence, an input digest
over that evidence, and a generation time.  The reproduction check
regenerates the identical set -- node IRIs and digests included -- from the
asserted graph alone.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

BINDING_ROOT = Path(__file__).resolve().parents[1] / "bindings" / "atlas" / "3.1"

RULE_IRI = URIRef("urn:ref:rule:fr-thesaurus-compound-head-broader")
DERIVATION_ENGINE = URIRef("https://refspec.org/code/atlas-v3-derived-fr-compound")
DERIVATION_ENGINE_VERSION = "1"
SCHEME_IRI = URIRef("urn:ref:atlas-resource-scheme:federal-register-thesaurus-2025")
ATLAS_RELEASE_IRI = URIRef("urn:ref:atlas-release:3:federal-register-thesaurus:2025-04-01")
DERIVED_NODE_PREFIX = "urn:ref:atlas-derived:"
GENERATED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")


def _load_validator() -> Any:
    path = BINDING_ROOT / "tools" / "validate.py"
    spec = importlib.util.spec_from_file_location("refspec_atlas_v3_validate", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import Atlas 3 validator from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ATLAS_VALIDATE = _load_validator()
ATLAS = ATLAS_VALIDATE.ATLAS
RKAF = ATLAS_VALIDATE.RKAF
SKOS = ATLAS_VALIDATE.SKOS
SKOSXL = ATLAS_VALIDATE.SKOSXL


@dataclass(frozen=True, slots=True)
class LabelEvidence:
    """One asserted preferred-label row the derivation read."""

    resource: URIRef
    label: URIRef
    language: str
    literal_form: str

    def digest_row(self) -> dict[str, str]:
        return {
            "iri": str(self.label),
            "language": self.language,
            "literalForm": self.literal_form,
            "resource": str(self.resource),
        }


@dataclass(frozen=True, slots=True)
class CompoundBroaderRow:
    """One derived ``skos:broader`` edge from a compound heading to its head."""

    node: URIRef
    subject: URIRef
    predicate: URIRef
    obj: URIRef
    ring: URIRef
    rule: URIRef
    engine: URIRef
    engine_version: str
    generated_at: str
    content_digest: str
    input_digest: str
    evidence: tuple[LabelEvidence, ...]


def compound_head(label: str) -> str:
    """Return the text before the first hyphen, or the whole label."""

    return label.split("-", 1)[0]


def label_node_iri(resource: str, *, value: str, role: str, language: str, source_path: str) -> URIRef:
    """Mint the producer's ``urn:ref:atlas-label:<hex>`` IRI for one label row."""

    digest = ATLAS_VALIDATE.canonical_sha256(
        {
            "language": language,
            "resource": resource,
            "role": role,
            "sourcePath": source_path,
            "value": value,
        }
    )
    return URIRef(f"urn:ref:atlas-label:{digest.removeprefix('sha256:')}")


def _one_iri(graph: Graph, subject: URIRef, predicate: URIRef, *, context: str) -> URIRef:
    values = sorted(str(value) for value in graph.objects(subject, predicate))
    if len(values) != 1:
        raise ValueError(f"{context} must have exactly one {predicate}: {values}")
    return URIRef(values[0])


def _preferred_labels(
    asserted: Graph,
) -> tuple[dict[URIRef, LabelEvidence], dict[str, URIRef]]:
    """Read every preferred label in the Federal Register thesaurus scheme."""

    evidence_by_resource: dict[URIRef, LabelEvidence] = {}
    resource_by_text: dict[str, URIRef] = {}
    for resource in sorted(asserted.subjects(ATLAS.inScheme, SCHEME_IRI), key=str):
        ring = _one_iri(asserted, resource, ATLAS.semanticRing, context=f"{resource}")
        if ring != ATLAS.subject:
            raise ValueError(f"{resource} is not in the subject ring: {ring}")
        labels = sorted(asserted.objects(resource, SKOSXL.prefLabel), key=str)
        if len(labels) != 1:
            raise ValueError(f"{resource} must have exactly one preferred label: {labels}")
        label = labels[0]
        forms = sorted(asserted.objects(label, SKOSXL.literalForm), key=str)
        if len(forms) != 1 or not isinstance(forms[0], Literal):
            raise ValueError(f"{label} must have exactly one literal form: {forms}")
        literal = forms[0]
        text = str(literal)
        if not text or text != text.strip():
            raise ValueError(f"{label} literal form must be non-empty trimmed text: {text!r}")
        if text in resource_by_text:
            raise ValueError(f"preferred label is ambiguous between two terms: {text!r}")
        language = literal.language if isinstance(literal.language, str) else ""
        row = LabelEvidence(
            resource=resource,
            label=label,
            language=language,
            literal_form=text,
        )
        evidence_by_resource[resource] = row
        resource_by_text[text] = resource
    return evidence_by_resource, resource_by_text


def _asserted_relation_triples(asserted: Graph) -> set[tuple[URIRef, URIRef, URIRef]]:
    """Collect every relation triple an asserted relation assertion carries."""

    triples: set[tuple[URIRef, URIRef, URIRef]] = set()
    for assertion_type in ATLAS_VALIDATE.ASSERTION_TYPES:
        for node in asserted.subjects(RDF.type, assertion_type):
            subject = asserted.value(node, RDF.subject)
            predicate = asserted.value(node, RDF.predicate)
            obj = asserted.value(node, RDF.object)
            if (
                isinstance(subject, URIRef)
                and isinstance(predicate, URIRef)
                and isinstance(obj, URIRef)
            ):
                triples.add((subject, predicate, obj))
    return triples


def _build_row(
    compound: LabelEvidence,
    head: LabelEvidence,
    *,
    generated_at: str,
) -> CompoundBroaderRow:
    evidence = tuple(sorted((compound, head), key=lambda item: str(item.resource)))
    input_digest = ATLAS_VALIDATE.canonical_sha256(
        {"labels": [item.digest_row() for item in evidence]},
        terminal_lf=False,
    )
    scratch = Graph()
    node = URIRef(DERIVED_NODE_PREFIX + "pending")
    scratch.add((node, RDF.type, ATLAS.DerivedRelation))
    scratch.add((node, ATLAS.relationSubject, compound.resource))
    scratch.add((node, ATLAS.relationPredicate, SKOS.broader))
    scratch.add((node, ATLAS.relationObject, head.resource))
    scratch.add((node, ATLAS.semanticRing, ATLAS.subject))
    for item in evidence:
        scratch.add((node, ATLAS.derivedFromAssertion, item.label))
    scratch.add((node, ATLAS.derivationRule, RULE_IRI))
    scratch.add((node, ATLAS.engine, DERIVATION_ENGINE))
    scratch.add((node, ATLAS.engineVersion, Literal(DERIVATION_ENGINE_VERSION)))
    scratch.add((node, RKAF.inputDigest, Literal(input_digest)))
    scratch.add((node, ATLAS.generatedAt, Literal(generated_at, datatype=XSD.dateTime, normalize=False)))
    content_digest = ATLAS_VALIDATE.rdf_node_digest(scratch, node)
    scratch.close()
    return CompoundBroaderRow(
        node=URIRef(DERIVED_NODE_PREFIX + content_digest.removeprefix("sha256:")),
        subject=compound.resource,
        predicate=SKOS.broader,
        obj=head.resource,
        ring=ATLAS.subject,
        rule=RULE_IRI,
        engine=DERIVATION_ENGINE,
        engine_version=DERIVATION_ENGINE_VERSION,
        generated_at=generated_at,
        content_digest=content_digest,
        input_digest=input_digest,
        evidence=evidence,
    )


def derive_compound_heading_broader(asserted: Graph, *, generated_at: str) -> tuple[CompoundBroaderRow, ...]:
    """Derive every compound-heading ``skos:broader`` edge from the asserted graph.

    A row is emitted only when the compound's head segment -- the text before
    the first hyphen -- is itself the preferred label of a different resource
    in the same scheme.  Hyphenated words whose head is not a term therefore
    exclude themselves.  A derived edge that would duplicate an asserted
    relation, including its inverse ``skos:narrower`` form, fails closed.
    """

    if GENERATED_AT_RE.fullmatch(generated_at) is None:
        raise ValueError(f"generated_at must be a timezone-qualified ISO datetime: {generated_at!r}")
    evidence_by_resource, resource_by_text = _preferred_labels(asserted)
    asserted_triples = _asserted_relation_triples(asserted)
    rows: list[CompoundBroaderRow] = []
    for text in sorted(resource_by_text):
        if "-" not in text:
            continue
        compound = evidence_by_resource[resource_by_text[text]]
        head_resource = resource_by_text.get(compound_head(text))
        if head_resource is None or head_resource == compound.resource:
            continue
        head = evidence_by_resource[head_resource]
        if (compound.resource, SKOS.broader, head.resource) in asserted_triples or (
            head.resource,
            SKOS.narrower,
            compound.resource,
        ) in asserted_triples:
            raise ValueError(
                "derived compound-heading broader edge duplicates an asserted relation: "
                f"{compound.resource} -> {head.resource}"
            )
        rows.append(_build_row(compound, head, generated_at=generated_at))
    return tuple(rows)


def reproduce_compound_heading_broader(
    asserted: Graph,
    rows: tuple[CompoundBroaderRow, ...] | list[CompoundBroaderRow],
    *,
    generated_at: str,
) -> None:
    """Regenerate the exact row set from the asserted graph and compare.

    This is the rule's running check: node IRIs, content digests, input
    digests, and evidence must all be a pure function of the asserted graph
    and the generation time.  Any drift fails closed.
    """

    fresh = derive_compound_heading_broader(asserted, generated_at=generated_at)
    expected = tuple(sorted(rows, key=lambda row: str(row.node)))
    if fresh != expected:
        fresh_by_node = {row.node: row for row in fresh}
        expected_by_node = {row.node: row for row in expected}
        missing = sorted(set(expected_by_node) - set(fresh_by_node), key=str)
        extra = sorted(set(fresh_by_node) - set(expected_by_node), key=str)
        detail = f"expected {len(expected)} rows, regenerated {len(fresh)}"
        if missing:
            detail += f"; not re-derivable: {missing[0]}"
        if extra:
            detail += f"; unexpected: {extra[0]}"
        shared = sorted(set(fresh_by_node) & set(expected_by_node), key=str)
        for node in shared:
            if fresh_by_node[node] != expected_by_node[node]:
                detail += f"; content drift on {node}"
                break
        raise ValueError(f"compound-heading broader reproduction failed: {detail}")


def derived_quads(rows: tuple[CompoundBroaderRow, ...] | list[CompoundBroaderRow], graph_id: URIRef) -> tuple[str, ...]:
    """Render the rows as canonical N-Quads lines for the derived graph."""

    lines: list[str] = []
    for row in sorted(rows, key=lambda item: str(item.node)):
        scratch = Graph()
        scratch.add((row.node, RDF.type, ATLAS.DerivedRelation))
        scratch.add((row.node, ATLAS.relationSubject, row.subject))
        scratch.add((row.node, ATLAS.relationPredicate, row.predicate))
        scratch.add((row.node, ATLAS.relationObject, row.obj))
        scratch.add((row.node, ATLAS.semanticRing, row.ring))
        for item in row.evidence:
            scratch.add((row.node, ATLAS.derivedFromAssertion, item.label))
        scratch.add((row.node, ATLAS.derivationRule, row.rule))
        scratch.add((row.node, ATLAS.engine, row.engine))
        scratch.add((row.node, ATLAS.engineVersion, Literal(row.engine_version)))
        scratch.add((row.node, RKAF.inputDigest, Literal(row.input_digest)))
        scratch.add((row.node, ATLAS.generatedAt, Literal(row.generated_at, datatype=XSD.dateTime, normalize=False)))
        scratch.add((row.node, ATLAS.contentDigest, Literal(row.content_digest)))
        for _, predicate, obj in sorted(scratch, key=lambda triple: (str(triple[1]), str(triple[2]))):
            lines.append(ATLAS_VALIDATE.nquads_line(row.node, predicate, obj, graph_id))
        scratch.close()
    return tuple(lines)


def build_fr_thesaurus_asserted_graph(release: Any) -> Graph:
    """Project one Federal Register thesaurus release into asserted-graph shape.

    The builder emits exactly the facts the rule reads -- scheme membership,
    semantic ring, preferred labels with their SKOS-XL nodes, and the
    release's direct relations as native relation assertions -- using the
    producer's own shapes and label node IRIs, so the real-data tests run the
    rule over the same facts a full distribution would carry.
    """

    if release.scheme_iri != str(SCHEME_IRI):
        raise ValueError(f"release is not the Federal Register thesaurus scheme: {release.scheme_iri}")
    if release.ring != "subject":
        raise ValueError(f"release is not in the subject ring: {release.ring}")
    graph = Graph()
    scheme = URIRef(release.scheme_iri)
    atlas_release = URIRef(release.atlas_release_iri)
    for resource_row in release.resources:
        resource = URIRef(resource_row.iri)
        graph.add((resource, RDF.type, ATLAS.AtlasResource))
        graph.add((resource, RDF.type, ATLAS.SubjectConcept))
        graph.add((resource, SKOS.inScheme, scheme))
        graph.add((resource, ATLAS.inScheme, scheme))
        graph.add((resource, ATLAS.semanticRing, ATLAS.subject))
        graph.add((resource, ATLAS.inRelease, atlas_release))
        for label_row in resource_row.labels:
            label = label_node_iri(
                resource_row.iri,
                value=label_row.value,
                role=label_row.role,
                language=label_row.language,
                source_path=label_row.source_path,
            )
            if label_row.role == "preferred":
                graph.add((resource, SKOSXL.prefLabel, label))
            elif label_row.role == "alternate":
                graph.add((resource, SKOSXL.altLabel, label))
            else:
                graph.add((resource, SKOSXL.hiddenLabel, label))
            graph.add((label, RDF.type, SKOSXL.Label))
            graph.add((label, SKOSXL.literalForm, Literal(label_row.value, lang=label_row.language)))
            graph.add((label, ATLAS.inRelease, atlas_release))
    for index, relation in enumerate(release.relations):
        assertion = URIRef(f"urn:ref:atlas-assertion:fr-test-{index:06d}")
        graph.add((assertion, RDF.type, ATLAS.RelationAssertion))
        graph.add((assertion, RDF.type, ATLAS.NativeRelationAssertion))
        graph.add((assertion, RDF.subject, URIRef(relation.subject)))
        graph.add((assertion, RDF.predicate, URIRef(relation.predicate)))
        graph.add((assertion, RDF.object, URIRef(relation.object)))
        graph.add((assertion, ATLAS.semanticRing, ATLAS.subject))
    return graph


def main() -> None:
    """Print the derived row set over the real pinned Federal Register release."""

    from refspec.atlas.v3_registry_vocabularies import load_federal_register_2025_release

    release = load_federal_register_2025_release()
    asserted = build_fr_thesaurus_asserted_graph(release)
    rows = derive_compound_heading_broader(asserted, generated_at="2026-08-18T00:00:00+00:00")
    reproduce_compound_heading_broader(asserted, rows, generated_at="2026-08-18T00:00:00+00:00")
    evidence_by_resource = {row.subject: row for row in rows}
    for row in rows:
        compound_label = next(
            item.literal_form for item in row.evidence if item.resource == row.subject
        )
        head_label = next(item.literal_form for item in row.evidence if item.resource == row.obj)
        print(f"{compound_label} -> {head_label}  <{row.node}>")
    hyphenated = sum(
        1 for resource, item in _preferred_labels(asserted)[0].items() if "-" in item.literal_form
    )
    print(f"terms={len(_preferred_labels(asserted)[0])} hyphenated={hyphenated} rows={len(rows)}")
    print(f"subjects-with-rows={len(evidence_by_resource)}")
    print(f"quads={len(derived_quads(rows, URIRef('urn:ref:atlas:graph:v3:derived')))}")


if __name__ == "__main__":
    main()
