"""Fault-injection tests for the Atlas source-fidelity verifier.

Every check gets two tests: one proving it passes on a faithful synthetic pair of
publisher bytes and Atlas pack, and one proving it *fires* on a pair where a
specific infidelity has been injected. A verifier that never fails is
indistinguishable from no verifier at all, so the broken cases carry the weight.

The fixtures are synthetic on purpose. Binding these tests to the real pinned
distribution would make them slow, would couple them to one release of the
publisher data, and -- decisively -- would stop them exercising the failure paths,
because the real distribution passes some of these checks.

Each broken case asserts on the *failure text*, not merely on ``passed is False``,
so a check that fires for an unrelated reason does not count as caught.

These tests draw a hard boundary around source fidelity. Publisher identifiers,
literal values, relations, counts, locators, digests, and reversible native fields
must survive exactly. Atlas-only rings, profiles, releases, resource classes, and
governed scheme identities are deliberately outside this verifier.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from tools.verify_atlas_source_fidelity import (
    CHECK_NAMES,
    CheckResult,
    DeclaredClaimExclusion,
    Expectations,
    Finding,
    LiteralValue,
    NativeControlSelector,
    RdfSourcePolicy,
    SourcePin,
    SourceSpec,
    check_source_defects,
    main,
    parse_nquads_line,
    render,
    run_checks,
    unescape_literal,
    verify,
)

try:
    from compression import zstd
except ImportError:  # pragma: no cover - exercised by the older interpreter
    from backports import zstd

EX = "http://example.org/vocab/"
SCHEME = "http://example.org/scheme/main"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
SKOS = "http://www.w3.org/2004/02/skos/core#"
SKOSXL = "http://www.w3.org/2008/05/skos-xl#"
ATLAS = "https://refspec.org/ns/atlas/v3#"
GRAPH = "urn:ref:atlas:graph:v3:asserted"

# Three concepts is the minimum that exercises hierarchy, association and labels
# without making the fixtures unreadable. The diacritic and the mixed case in
# "Café Society" are load-bearing: they are what a normaliser is tempted to eat.
CONCEPTS = {
    f"{EX}c1": {"pref": "Café Society", "alt": "CAFÉ SOCIETY", "broader": None, "related": f"{EX}c2"},
    f"{EX}c2": {"pref": "Public Houses", "alt": "Pubs", "broader": f"{EX}c1", "related": None},
    f"{EX}c3": {"pref": "Tea Rooms", "alt": None, "broader": f"{EX}c1", "related": None},
}


def publisher_turtle(
    *,
    labels: dict[str, str] | None = None,
    extra_triples: str = "",
    drop_relation: tuple[str, str, str] | None = None,
) -> str:
    """Render the synthetic publisher distribution as Turtle."""
    overrides = labels or {}
    lines = [
        f"@prefix skos: <{SKOS}> .",
        "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
        "",
        # The scheme deliberately carries no label: label counts compare concept labels,
        # and giving the scheme one would make the faithful baseline differ by construction.
        f"<{SCHEME}> a skos:ConceptScheme .",
        "",
    ]
    for iri, spec in CONCEPTS.items():
        pref = overrides.get(iri, spec["pref"])
        parts = [f"<{iri}> a skos:Concept ;", f"  skos:inScheme <{SCHEME}> ;", f'  skos:prefLabel "{pref}"@en']
        if spec["alt"]:
            parts.append(f'  skos:altLabel "{spec["alt"]}"@en')
        if spec["broader"] and drop_relation != (iri, f"{SKOS}broader", spec["broader"]):
            parts.append(f'  skos:broader <{spec["broader"]}>')
        if spec["related"] and drop_relation != (iri, f"{SKOS}related", spec["related"]):
            parts.append(f'  skos:related <{spec["related"]}>')
        lines.append(" ;\n".join(parts) + " .")
        lines.append("")
    lines.append(extra_triples)
    return "\n".join(lines)


def _quad(subject: str, predicate: str, obj: str, *, literal: bool = False, lang: str = "en") -> str:
    if literal:
        escaped = obj.replace("\\", "\\\\").replace('"', '\\"')
        return f'<{subject}> <{predicate}> "{escaped}"@{lang} <{GRAPH}> .'
    return f"<{subject}> <{predicate}> <{obj}> <{GRAPH}> ."


def atlas_pack_lines(
    *,
    labels: dict[str, str] | None = None,
    minted_ids: bool = False,
    extra_relations: Sequence[tuple[str, str, str]] = (),
    drop_relation: tuple[str, str, str] | None = None,
    drop_concept: str | None = None,
    drop_label: str | None = None,
    drop_alt_label: str | None = None,
    scheme_target: str = SCHEME,
    top_concepts: dict[str, Sequence[str]] | None = None,
    native_literal_evidence: dict[str, Sequence[dict[str, str]]] | None = None,
    native_scheme_iris: dict[str, Sequence[str]] | None = None,
    extra_native_payload: dict[str, object] | None = None,
    extra_native_payload_by_resource: dict[str, dict[str, object]] | None = None,
    source_digest: str | None = None,
    include_source_digest: bool = True,
    source_locators: dict[str, str] | None = None,
) -> list[str]:
    """Render what the Atlas asserts about the synthetic source, as N-Quads."""
    overrides = labels or {}
    top_concepts = top_concepts or {}
    native_literal_evidence = native_literal_evidence or {}
    native_scheme_iris = native_scheme_iris or {}
    extra_native_payload = extra_native_payload or {}
    extra_native_payload_by_resource = extra_native_payload_by_resource or {}
    source_locators = source_locators or {}
    if source_digest is None:
        source_digest = "sha256:" + hashlib.sha256(
            publisher_turtle().encode("utf-8")
        ).hexdigest()
    lines: list[str] = [
        _quad(
            scheme_target,
            "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
            f"{SKOS}ConceptScheme",
        )
    ]
    relations: list[tuple[str, str, str]] = []

    for iri, spec in CONCEPTS.items():
        if iri == drop_concept:
            continue
        resource = f"urn:ref:atlas-resource:{iri.rsplit('/', 1)[-1]}" if minted_ids else iri
        lines.append(_quad(resource, "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", f"{SKOS}Concept"))
        lines.append(_quad(resource, f"{SKOS}inScheme", scheme_target))

        record = f"urn:ref:atlas-source-record:{iri.rsplit('/', 1)[-1]}"
        lines.append(_quad(record, "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", f"{ATLAS}SourceRecord"))
        lines.append(
            _quad(
                record,
                f"{ATLAS}sourceLocator",
                source_locators.get(iri, resource),
            )
        )
        if include_source_digest:
            lines.append(_plain_literal_quad(record, f"{ATLAS}sourceDigest", source_digest))
        lines.append(_quad(record, f"{ATLAS}representsResource", resource))
        native_payload: dict[str, object] = {
            "schemeIris": list(native_scheme_iris.get(iri, (SCHEME,)))
        }
        if iri in top_concepts:
            native_payload["topConceptOfIris"] = list(top_concepts[iri])
        if iri in native_literal_evidence:
            native_payload["sourceAnnotations"] = list(native_literal_evidence[iri])
        native_payload.update(extra_native_payload)
        native_payload.update(extra_native_payload_by_resource.get(iri, {}))
        lines.append(
            _quad(
                record,
                f"{ATLAS}nativePayload",
                json.dumps(native_payload, separators=(",", ":")),
                literal=True,
            )
        )

        pref = overrides.get(iri, spec["pref"])
        if iri != drop_label:
            node = f"urn:ref:atlas-label:{iri.rsplit('/', 1)[-1]}-pref"
            lines.append(_quad(resource, f"{SKOSXL}prefLabel", node))
            lines.append(_quad(node, f"{SKOSXL}literalForm", pref, literal=True))
        if spec["alt"] and iri != drop_alt_label:
            alt_node = f"urn:ref:atlas-label:{iri.rsplit('/', 1)[-1]}-alt"
            lines.append(_quad(resource, f"{SKOSXL}altLabel", alt_node))
            lines.append(_quad(alt_node, f"{SKOSXL}literalForm", spec["alt"], literal=True))

        if spec["broader"]:
            relations.append((resource, f"{SKOS}broader", spec["broader"]))
        if spec["related"]:
            relations.append((resource, f"{SKOS}related", spec["related"]))

    relations.extend(extra_relations)
    for index, (subject, predicate, obj) in enumerate(relations):
        if (subject, predicate, obj) == drop_relation:
            continue
        assertion = f"urn:ref:atlas-assertion:{index}"
        lines.append(_quad(assertion, "http://www.w3.org/1999/02/22-rdf-syntax-ns#subject", subject))
        lines.append(_quad(assertion, "http://www.w3.org/1999/02/22-rdf-syntax-ns#predicate", predicate))
        lines.append(_quad(assertion, "http://www.w3.org/1999/02/22-rdf-syntax-ns#object", obj))
    return lines


class Fixture:
    """A synthetic publisher file and Atlas pack that can be selectively broken."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.distribution = root / "distribution"
        self.source_root = root / "sources"
        (self.distribution / "packs" / "sources" / "example").mkdir(parents=True)
        self.source_root.mkdir(parents=True)
        self.spec = SourceSpec(
            name="example",
            kind="vocabulary",
            release_keys=("example",),
            inputs=(
                SourcePin(
                    "example.ttl",
                    "sha256:" + "0" * 64,
                    0,
                    role="publisherSource",
                    source_iri="urn:example:publisher:example.ttl",
                ),
            ),
            policies=frozenset(
                {
                    "english-label-selection",
                    "english-annotation-selection",
                    "skos-note-to-atlas-note",
                    "top-concept-source-shape-inverse",
                }
            ),
            rdf_source=RdfSourcePolicy(
                evaluated_native_payload_fields=frozenset({"schemeIris"})
            ),
        )

    @property
    def pack_path(self) -> Path:
        return self.distribution / "packs" / "sources" / "example" / "all.nq.zst"

    @property
    def publisher_path(self) -> Path:
        return self.source_root / "example.ttl"

    def publisher_content_digest(self) -> str:
        """Hash the publisher bytes represented by source records, not zip transport."""
        pin = self.spec.inputs[0]
        source_path = self.source_root / pin.path
        if source_path.is_file():
            source_payload = source_path.read_bytes()
            if pin.zip_member is not None:
                with zipfile.ZipFile(source_path) as archive:
                    source_payload = archive.read(pin.zip_member)
        else:
            source_payload = publisher_turtle().encode("utf-8")
        return "sha256:" + hashlib.sha256(source_payload).hexdigest()

    def write_publisher(self, **kwargs: object) -> None:
        self.publisher_path.write_text(publisher_turtle(**kwargs), encoding="utf-8")  # type: ignore[arg-type]
        self.pin_input("example.ttl")

    def pin_input(self, filename: str, *, fmt: str = "turtle", zip_member: str | None = None) -> None:
        path = self.source_root / filename
        payload = path.read_bytes()
        pin = SourcePin(
            path=filename,
            sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
            byte_length=len(payload),
            fmt=fmt,
            zip_member=zip_member,
            role="publisherSource",
            source_iri="urn:example:publisher:example.ttl",
        )
        self.spec = replace(self.spec, inputs=(pin,))
        summary = {
            "releases": [
                {
                    "key": "example",
                    "kind": "sourceRelease",
                    "inputs": [
                        {
                            "path": filename,
                            "sha256": pin.sha256,
                            "byteLength": pin.byte_length,
                            "role": "publisherSource",
                            "sourceIri": pin.source_iri,
                        }
                    ],
                    "rdfPacks": [{"path": "packs/sources/example/all.nq.zst"}],
                    "recordCounts": {"resources": 3, "labels": 5, "statements": 3},
                }
            ]
        }
        (self.distribution / "atlas-construction-summary.json").write_text(json.dumps(summary), encoding="utf-8")

    def write_pack(self, **kwargs: object) -> None:
        if "source_digest" not in kwargs:
            kwargs["source_digest"] = self.publisher_content_digest()
        lines = atlas_pack_lines(**kwargs)  # type: ignore[arg-type]
        self.write_pack_lines(lines)

    def write_pack_lines(self, lines: Sequence[str]) -> None:
        """Write an injected pack and keep its transport authentication current."""
        payload = ("\n".join(lines) + "\n").encode("utf-8")
        transport = zstd.compress(payload)
        self.pack_path.write_bytes(transport)
        manifest = {
            "packs": [
                {
                    "path": "packs/sources/example/all.nq.zst",
                    "transport": {
                        "byteLength": len(transport),
                        "digest": "sha256:" + hashlib.sha256(transport).hexdigest(),
                    },
                }
            ]
        }
        (self.distribution / "atlas-manifest.json").write_text(
            json.dumps(manifest),
            encoding="utf-8",
        )

    def run(self, expectations: Expectations | None = None, spec: SourceSpec | None = None) -> list:
        return verify(
            self.distribution,
            self.source_root,
            expectations or Expectations(minimum_label_sample=1),
            (spec or self.spec,),
        )


@pytest.fixture
def suite(tmp_path: Path) -> Fixture:
    """A fully faithful pair: the Atlas says exactly what the publisher published."""
    fixture = Fixture(tmp_path)
    fixture.write_publisher()
    fixture.write_pack()
    return fixture


def result(results: Sequence, name: str):
    for item in results:
        if item.name == name:
            return item
    raise AssertionError(f"no check named {name!r} in {[item.name for item in results]}")


def failed(results: Sequence) -> set[str]:
    return {item.name for item in results if not item.passed}


def _plain_literal_quad(subject: str, predicate: str, value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'<{subject}> <{predicate}> "{escaped}" <{GRAPH}> .'


def _add_native_control(
    suite: Fixture,
    *,
    capture_counts: dict[str, int] | None = None,
    atlas_counts: dict[str, int] | None = None,
    atlas_profile: str = "codeScheme",
    add_skos_concept_type: bool = False,
    control_use: str = "deterministicCodeOrClassification",
    emit_members: bool = True,
    capture_policy_overrides: dict[str, object] | None = None,
) -> SourceSpec:
    """Add one tiny direct-Parquet control comparison to the faithful RDF fixture."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    control_id = "tiny-code-control"
    release_key = "tiny-code-release"
    source_table = "tiny"
    source_field = "code"
    source_iri = "urn:example:source:tiny.parquet"
    resource_id = "tiny-native-controls"
    scheme_iri = f"urn:ref:atlas-resource-scheme:{control_id}"
    release_iri = "urn:example:atlas-release:tiny"
    raw_counts = {"Alpha": 2, "Beta": 1}
    capture_counts = capture_counts or raw_counts
    atlas_counts = atlas_counts or capture_counts
    parquet_path = suite.source_root / "tiny.parquet"
    pq.write_table(
        pa.table({source_field: pa.array(["Alpha", "Beta", "Alpha", None], type=pa.string())}),
        parquet_path,
    )
    parquet_payload = parquet_path.read_bytes()
    parquet_pin = SourcePin(
        path=parquet_path.name,
        sha256="sha256:" + hashlib.sha256(parquet_payload).hexdigest(),
        byte_length=len(parquet_payload),
        fmt="parquet",
        role="publisherSource",
        source_iri=source_iri,
    )

    control = {
        "conceptIdentityPolicy": "notAConcept",
        "controlId": control_id,
        "extraction": "scalar",
        "facet": "urn:ref:facet:code-list-value",
        "profileIds": ["tiny-record-v1"],
        "resourceId": resource_id,
        "sourceField": source_field,
        "sourceRowCount": 4,
        "sourceFieldMissingRowCount": 1,
        "sourceTable": source_table,
        "subjectUse": "forbidden",
        "unresolvedValueCount": 0,
        "use": control_use,
        "valueOccurrenceCount": sum(capture_counts.values()),
        "values": [
            {"count": count, "value": value}
            for value, count in sorted(capture_counts.items())
        ],
    }
    control.update(capture_policy_overrides or {})
    capture_path = suite.source_root / "tiny-controls.json"
    capture_path.write_text(
        json.dumps(
            {
                "controls": [control],
                "sourcePins": [
                    {
                        "byteLength": parquet_pin.byte_length,
                        "columns": [source_field],
                        "profileIds": ["tiny-record-v1"],
                        "rowCount": 4,
                        "sha256": parquet_pin.sha256,
                        "table": source_table,
                        "uri": source_iri,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    capture_payload = capture_path.read_bytes()
    capture_pin = SourcePin(
        path=capture_path.name,
        sha256="sha256:" + hashlib.sha256(capture_payload).hexdigest(),
        byte_length=len(capture_payload),
        fmt="json",
        role="normalizedCapture",
        source_iri="urn:example:source:tiny-controls",
    )

    spec = SourceSpec(
        name="tiny-native-control",
        kind="native-control",
        release_keys=(release_key,) if emit_members else (),
        inputs=(parquet_pin, capture_pin),
        native_control=NativeControlSelector(
            control_id=control_id,
            source_table=source_table,
            source_field=source_field,
            extraction="scalar",
            source_iri=source_iri,
            expected_row_count=4,
            expected_columns=(source_field,),
            construction_key=release_key,
        ),
    )

    control_metadata = {key: value for key, value in control.items() if key != "values"}
    lines: list[str] = [
        _quad(release_iri, f"{RDF}type", f"{ATLAS}AtlasRelease"),
        _quad(release_iri, f"{ATLAS}inScheme", scheme_iri),
        _quad(release_iri, f"{ATLAS}resourceProfile", f"{ATLAS}{atlas_profile}"),
        _quad(release_iri, f"{ATLAS}semanticRing", f"{ATLAS}value"),
    ]
    for index, (value, count) in enumerate(sorted(atlas_counts.items())):
        resource = f"urn:example:control:{value.lower()}"
        record = f"urn:example:source-record:{index}"
        label = f"urn:example:label:{index}"
        native_payload = json.dumps(
            {
                "control": control_metadata,
                "sourceArtifact": source_iri,
                "value": {"count": count, "value": value},
            },
            separators=(",", ":"),
        )
        lines.extend(
            [
                _quad(resource, f"{RDF}type", f"{ATLAS}AtlasResource"),
                _quad(resource, f"{RDF}type", f"{ATLAS}ValueResource"),
                *(
                    [_quad(resource, f"{RDF}type", f"{SKOS}Concept")]
                    if add_skos_concept_type
                    else []
                ),
                _quad(resource, f"{ATLAS}inScheme", scheme_iri),
                _quad(resource, f"{ATLAS}resourceProfile", f"{ATLAS}{atlas_profile}"),
                _quad(resource, f"{ATLAS}semanticRing", f"{ATLAS}value"),
                _quad(record, f"{RDF}type", f"{ATLAS}SourceRecord"),
                _quad(record, f"{ATLAS}sourceLocator", source_iri),
                _plain_literal_quad(record, f"{ATLAS}sourceDigest", parquet_pin.sha256),
                _quad(record, f"{ATLAS}representsResource", resource),
                _plain_literal_quad(record, f"{ATLAS}nativePayload", native_payload),
                _quad(resource, f"{SKOSXL}prefLabel", label),
                _quad(label, f"{SKOSXL}literalForm", value, literal=True),
                _plain_literal_quad(resource, f"{ATLAS}notation", value),
            ]
        )

    if emit_members:
        pack_relative = "sources/tiny-native-control/all.nq.zst"
        pack_path = suite.distribution / "packs" / pack_relative
        pack_path.parent.mkdir(parents=True)
        transport = zstd.compress(("\n".join(lines) + "\n").encode("utf-8"))
        pack_path.write_bytes(transport)

        summary_path = suite.distribution / "atlas-construction-summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["releases"].append(
            {
                "key": release_key,
                "kind": "sourceRelease",
                "inputs": [
                    {
                        "path": pin.path,
                        "sha256": pin.sha256,
                        "byteLength": pin.byte_length,
                        "role": role,
                        "sourceIri": pin.source_iri,
                    }
                    for pin, role in (
                        (parquet_pin, "publisherSource"),
                        (capture_pin, "normalizedCapture"),
                    )
                ],
                "rdfPacks": [{"path": f"packs/{pack_relative}"}],
                "recordCounts": {
                    "resources": len(atlas_counts),
                    "labels": len(atlas_counts),
                },
            }
        )
        summary_path.write_text(json.dumps(summary), encoding="utf-8")

        manifest_path = suite.distribution / "atlas-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["packs"].append(
            {
                "path": f"packs/{pack_relative}",
                "transport": {
                    "byteLength": len(transport),
                    "digest": "sha256:" + hashlib.sha256(transport).hexdigest(),
                },
            }
        )
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return spec


def _repin_native_capture(suite: Fixture, spec: SourceSpec) -> SourceSpec:
    """Update independent and construction pins after a capture fault injection."""
    capture_path = suite.source_root / "tiny-controls.json"
    capture_payload = capture_path.read_bytes()
    old_capture_pin = next(pin for pin in spec.inputs if pin.fmt == "json")
    new_capture_pin = replace(
        old_capture_pin,
        sha256="sha256:" + hashlib.sha256(capture_payload).hexdigest(),
        byte_length=len(capture_payload),
    )
    new_inputs = tuple(
        new_capture_pin if pin == old_capture_pin else pin for pin in spec.inputs
    )

    summary_path = suite.distribution / "atlas-construction-summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    native_release = next(
        row for row in summary["releases"] if row["key"] == "tiny-code-release"
    )
    capture_row = next(
        row
        for row in native_release["inputs"]
        if row["path"] == old_capture_pin.path
    )
    capture_row["sha256"] = new_capture_pin.sha256
    capture_row["byteLength"] = new_capture_pin.byte_length
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    return replace(spec, inputs=new_inputs)


# --------------------------------------------------------------------------------------
# Baseline
# --------------------------------------------------------------------------------------


def test_faithful_pair_passes_every_check(suite: Fixture) -> None:
    results = suite.run()
    assert len(results) == len(CHECK_NAMES)
    assert failed(results) == set(), [item.failures for item in results if not item.passed]


def test_native_control_matches_raw_parquet_capture_and_atlas(suite: Fixture) -> None:
    native_spec = _add_native_control(suite)

    results = verify(
        suite.distribution,
        suite.source_root,
        Expectations(minimum_label_sample=1),
        (suite.spec, native_spec),
    )

    assert failed(results) == set(), [item.failures for item in results if not item.passed]
    native_check = result(results, "native-control-fidelity")
    assert native_check.summary == "2 controlled values compared directly with pinned Parquet rows"


def test_native_control_raw_parquet_catches_colluding_capture_and_atlas(
    suite: Fixture,
) -> None:
    native_spec = _add_native_control(
        suite,
        capture_counts={"Alpha": 1, "Beta": 1},
        atlas_counts={"Alpha": 1, "Beta": 1},
    )

    results = verify(
        suite.distribution,
        suite.source_root,
        Expectations(minimum_label_sample=1),
        (suite.spec, native_spec),
    )

    native_check = result(results, "native-control-fidelity")
    assert not native_check.passed
    assert any(
        "normalized control capture valueOccurrenceCount differs from direct Parquet scan"
        in failure
        and "expected 3, observed 2" in failure
        for failure in native_check.failures
    )
    assert any(
        "normalized control capture count for 'Alpha' differs -- publisher 2, observed 1"
        in failure
        for failure in native_check.failures
    )
    assert any(
        "Atlas native value count for 'Alpha' differs -- publisher 2, observed 1" in failure
        for failure in native_check.failures
    )


def test_native_control_ignores_atlas_only_concept_type_and_profile(
    suite: Fixture,
) -> None:
    native_spec = _add_native_control(
        suite,
        atlas_profile="conceptScheme",
        add_skos_concept_type=True,
    )

    results = verify(
        suite.distribution,
        suite.source_root,
        Expectations(minimum_label_sample=1),
        (suite.spec, native_spec),
    )

    assert failed(results) == set(), [item.failures for item in results if not item.passed]


def test_native_control_ignores_normalized_atlas_classification_metadata(
    suite: Fixture,
) -> None:
    native_spec = _add_native_control(
        suite,
        atlas_profile="identifierScheme",
        capture_policy_overrides={
            "conceptIdentityPolicy": "concept",
            "facet": "urn:example:unrelated-facet",
            "profileIds": ["unrelated-profile"],
            "subjectUse": "required",
            "use": "identifierAuthority",
        },
    )

    results = verify(
        suite.distribution,
        suite.source_root,
        Expectations(minimum_label_sample=1),
        (suite.spec, native_spec),
    )

    assert failed(results) == set(), [item.failures for item in results if not item.passed]


def test_native_source_values_are_compared_regardless_of_atlas_control_use(
    suite: Fixture,
) -> None:
    native_spec = _add_native_control(
        suite,
        control_use="sourceAssignedEvidence",
    )

    results = verify(
        suite.distribution,
        suite.source_root,
        Expectations(minimum_label_sample=1),
        (suite.spec, native_spec),
    )

    assert failed(results) == set(), [item.failures for item in results if not item.passed]


def test_native_control_reconciles_construction_input_role_and_source_iri(
    suite: Fixture,
) -> None:
    native_spec = _add_native_control(suite)
    summary_path = suite.distribution / "atlas-construction-summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    native_release = next(row for row in summary["releases"] if row["key"] == "tiny-code-release")
    native_release["inputs"][0]["role"] = "normalizedCapture"
    native_release["inputs"][0]["sourceIri"] = "urn:wrong:source"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    pin_check = result(
        verify(
            suite.distribution,
            suite.source_root,
            Expectations(minimum_label_sample=1),
            (suite.spec, native_spec),
        ),
        "publisher-input-pins",
    )

    assert not pin_check.passed
    assert any("same path, digest, length, role, and source IRI" in failure for failure in pin_check.failures)


def test_publisher_pin_uses_an_explicit_construction_path_without_changing_local_lookup(
    suite: Fixture,
) -> None:
    pin = replace(
        suite.spec.inputs[0],
        construction_path="refspec/output/registry-real-data-sources/example.ttl",
    )
    suite.spec = replace(suite.spec, inputs=(pin,))
    summary_path = suite.distribution / "atlas-construction-summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["releases"][0]["inputs"][0]["path"] = pin.construction_path
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    check = result(suite.run(), "publisher-input-pins")

    assert check.passed
    assert "1/1 construction input rows matched exactly" in check.summary


def test_publisher_pin_does_not_suffix_match_a_wrong_construction_path(
    suite: Fixture,
) -> None:
    suite.spec = replace(
        suite.spec,
        inputs=(
            replace(
                suite.spec.inputs[0],
                construction_path="wrong/prefix/example.ttl",
            ),
        ),
    )

    check = result(suite.run(), "publisher-input-pins")

    assert not check.passed
    assert "0/1 construction input rows matched exactly" in check.summary


def test_builtin_source_pins_never_wildcard_construction_metadata() -> None:
    from tools.verify_atlas_source_fidelity import SOURCES

    assert all(pin.role and pin.source_iri for spec in SOURCES for pin in spec.inputs)


def test_rdf_public_id_resolves_relative_publisher_identifiers() -> None:
    import rdflib

    import tools.verify_atlas_source_fidelity as verifier

    source_iri = "https://publisher.example/vocabulary/source.rdf"
    payload = f'''<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="{RDF}" xmlns:skos="{SKOS}">
  <skos:Concept rdf:about="#c1">
    <skos:prefLabel xml:lang="en">One</skos:prefLabel>
  </skos:Concept>
</rdf:RDF>
'''.encode()

    graph = verifier._load_graph_payload(payload, "xml", public_id=source_iri)

    assert (
        rdflib.URIRef(f"{source_iri}#c1"),
        rdflib.RDF.type,
        rdflib.SKOS.Concept,
    ) in graph


def test_malformed_capture_does_not_prevent_direct_parquet_scan(suite: Fixture) -> None:
    native_spec = _add_native_control(suite)
    capture_path = suite.source_root / "tiny-controls.json"
    capture_path.write_text('{"controls":[', encoding="utf-8")
    native_spec = _repin_native_capture(suite, native_spec)

    native_check = result(
        verify(
            suite.distribution,
            suite.source_root,
            Expectations(minimum_label_sample=1),
            (suite.spec, native_spec),
        ),
        "native-control-fidelity",
    )

    assert not native_check.passed
    assert native_check.summary == "2 controlled values compared directly with pinned Parquet rows"
    assert any("normalized control capture could not be read" in failure for failure in native_check.failures)


def test_shared_capture_requires_exact_declared_control_closure(
    suite: Fixture,
) -> None:
    native_spec = _add_native_control(suite)
    capture_path = suite.source_root / "tiny-controls.json"
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    undeclared = dict(capture["controls"][0])
    undeclared["controlId"] = "undeclared-control"
    capture["controls"].append(undeclared)
    capture_path.write_text(json.dumps(capture), encoding="utf-8")
    native_spec = _repin_native_capture(suite, native_spec)

    results = verify(
        suite.distribution,
        suite.source_root,
        Expectations(minimum_label_sample=1),
        (suite.spec, native_spec),
    )

    native_check = result(results, "native-control-fidelity")
    assert not native_check.passed
    assert any(
        "normalized control capture has undeclared controls: ['undeclared-control']"
        in failure
        for failure in native_check.failures
    )
    assert result(results, "label-fidelity").passed


def test_native_reader_exception_does_not_stop_rdf_source_checks(
    suite: Fixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tools.verify_atlas_source_fidelity as verifier

    native_spec = _add_native_control(suite)

    def broken_native_reader(*_args: object) -> object:
        raise RuntimeError("deliberate native reader failure")

    monkeypatch.setattr(
        verifier,
        "_read_native_control_publishers",
        broken_native_reader,
    )
    results = verifier.verify(
        suite.distribution,
        suite.source_root,
        Expectations(minimum_label_sample=1),
        (suite.spec, native_spec),
    )

    load = result(results, "load-errors")
    assert not load.passed
    assert any("deliberate native reader failure" in failure for failure in load.failures)
    assert result(results, "label-fidelity").passed
    assert result(results, "rdf-provenance-fidelity").passed
    assert not result(results, "native-control-fidelity").passed


def test_duplicate_construction_key_fails_without_hiding_source_checks(
    suite: Fixture,
) -> None:
    summary_path = suite.distribution / "atlas-construction-summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["releases"].append(dict(summary["releases"][0]))
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    results = suite.run()

    load = result(results, "load-errors")
    assert not load.passed
    assert any("duplicate construction unit key 'example'" in failure for failure in load.failures)
    assert result(results, "label-fidelity").passed
    assert result(results, "rdf-provenance-fidelity").passed


def test_check_names_are_stable(suite: Fixture) -> None:
    assert tuple(item.name for item in suite.run()) == CHECK_NAMES


def test_mapping_adapter_has_no_irrelevant_vocabulary_policy() -> None:
    from tools.verify_atlas_source_fidelity import SOURCES

    mapping = next(spec for spec in SOURCES if spec.kind == "mapping")
    assert mapping.policies == frozenset()


def test_invalid_zero_label_floor_fails_closed_but_other_checks_continue(suite: Fixture) -> None:
    results = suite.run(Expectations(minimum_label_sample=0))
    check = result(results, "configuration")
    assert not check.passed
    assert any("at least 1" in text for text in check.failures)
    assert result(results, "relation-fidelity").passed


def test_weakened_coverage_setting_is_a_failed_configuration(suite: Fixture) -> None:
    results = suite.run(
        Expectations(minimum_label_sample=1, require_complete_coverage=False)
    )
    check = result(results, "configuration")
    assert not check.passed
    assert any("cannot produce a source-fidelity verdict" in text for text in check.failures)
    assert result(results, "label-fidelity").passed


def test_coverage_fails_when_a_construction_unit_has_no_adapter(suite: Fixture) -> None:
    summary_path = suite.distribution / "atlas-construction-summary.json"
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    payload["releases"].append(
        {
            "key": "uncovered",
            "kind": "sourceRelease",
            "inputs": [],
            "rdfPacks": [],
            "recordCounts": {"resources": 1},
        }
    )
    summary_path.write_text(json.dumps(payload), encoding="utf-8")
    check = result(suite.run(), "distribution-coverage")
    assert not check.passed
    assert any("no independent publisher adapter" in text and "uncovered" in text for text in check.failures)


def test_coverage_fails_when_adapter_kind_disagrees_with_construction_unit(
    suite: Fixture,
) -> None:
    summary_path = suite.distribution / "atlas-construction-summary.json"
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    payload["releases"][0]["kind"] = "mapping"
    summary_path.write_text(json.dumps(payload), encoding="utf-8")

    results = suite.run()

    check = result(results, "distribution-coverage")
    assert not check.passed
    assert any(
        "comparison kind 'vocabulary' requires construction kind 'sourceRelease'" in text
        for text in check.failures
    )
    assert result(results, "relation-fidelity").passed


def test_required_source_is_enforced(suite: Fixture) -> None:
    expectations = Expectations(minimum_label_sample=1, required_sources=("absent",))
    check = result(suite.run(expectations), "distribution-coverage")
    assert not check.passed
    assert any("required comparison sources are absent" in text for text in check.failures)


def test_manifest_pack_without_a_construction_owner_fails_closed(
    suite: Fixture,
) -> None:
    extra_relative = "sources/unowned/all.nq.zst"
    extra_path = suite.distribution / "packs" / extra_relative
    extra_path.parent.mkdir(parents=True)
    transport = zstd.compress(
        (_quad(f"{EX}c1", f"{SKOS}related", f"{EX}ghost") + "\n").encode(
            "utf-8"
        )
    )
    extra_path.write_bytes(transport)
    manifest_path = suite.distribution / "atlas-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["packs"].append(
        {
            "path": f"packs/{extra_relative}",
            "transport": {
                "byteLength": len(transport),
                "digest": "sha256:" + hashlib.sha256(transport).hexdigest(),
            },
        }
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    check = result(suite.run(), "distribution-coverage")

    assert not check.passed
    assert any(
        "not owned by any construction unit" in failure
        and extra_relative in failure
        for failure in check.failures
    )


def test_claim_scope_fails_when_generic_member_literal_is_unrepresented(
    suite: Fixture,
) -> None:
    predicate = "http://example.org/vocab/unhandled"
    suite.write_publisher(
        extra_triples=f'<{EX}c1> <{predicate}> "This claim must not disappear."@en .'
    )

    check = result(suite.run(), "claim-scope")

    assert not check.passed
    assert any(
        "memberMetadataLiterals source claims are unrepresented" in text
        for text in check.failures
    )


def test_source_claim_coverage_fails_on_an_unowned_publisher_resource(
    suite: Fixture,
) -> None:
    predicate = "http://purl.org/dc/terms/title"
    suite.write_publisher(
        extra_triples=f'<{EX}dataset> <{predicate}> "Publisher dataset"@en .'
    )
    suite.write_pack()

    check = result(suite.run(), "source-claim-coverage")

    assert not check.passed
    assert any(
        predicate in failure
        and "outside every executable comparison" in failure
        for failure in check.failures
    )
    assert not result(suite.run(), "claim-scope").passed


def test_source_claim_coverage_rejects_a_label_on_an_unknown_atlas_subject(
    suite: Fixture,
) -> None:
    lines = atlas_pack_lines()
    lines.append(
        _quad(
            f"{EX}ghost",
            f"{SKOS}prefLabel",
            "Manufactured ghost label",
            literal=True,
        )
    )
    suite.write_pack_lines(lines)

    results = suite.run()
    check = result(results, "source-claim-coverage")

    assert not check.passed
    assert any(
        "Atlas literal claim" in failure
        and f"{SKOS}prefLabel" in failure
        and f"{EX}ghost" in failure
        for failure in check.failures
    )
    assert not result(results, "claim-scope").passed


@pytest.mark.parametrize(
    "predicate",
    (
        f"{ATLAS}notation",
        f"{ATLAS}definition",
        f"{ATLAS}note",
        f"{ATLAS}recordStatus",
    ),
)
def test_source_claim_coverage_rejects_common_source_fields_on_unknown_subjects(
    suite: Fixture,
    predicate: str,
) -> None:
    lines = atlas_pack_lines()
    lines.append(
        _quad(
            f"{EX}ghost",
            predicate,
            "Manufactured source value",
            literal=True,
        )
    )
    suite.write_pack_lines(lines)

    check = result(suite.run(), "source-claim-coverage")

    assert not check.passed
    assert any(
        predicate in failure
        and f"{EX}ghost" in failure
        and "Atlas literal claim" in failure
        for failure in check.failures
    )


def test_source_claim_coverage_rejects_an_uncompared_common_field_on_a_source(
    suite: Fixture,
) -> None:
    lines = atlas_pack_lines()
    lines.extend(
        (
            _quad(
                f"{EX}c1",
                f"{ATLAS}collectionMember",
                f"{EX}ghost-member",
            ),
            _quad(
                f"{EX}c1",
                f"{ATLAS}validationRule",
                "manufactured",
                literal=True,
            ),
        )
    )
    suite.write_pack_lines(lines)

    check = result(suite.run(), "source-claim-coverage")

    assert not check.passed
    assert any(f"{ATLAS}collectionMember" in failure for failure in check.failures)
    assert any(f"{ATLAS}validationRule" in failure for failure in check.failures)


def test_record_status_on_a_known_source_subject_is_atlas_minted_structure(
    suite: Fixture,
) -> None:
    """atlas:recordStatus is the builder's own lifecycle field, not a source claim.

    It sits with atlas:inRelease and atlas:semanticRing: no publisher ships a
    field of that shape, so there is nothing to compare it against on a subject
    the comparison already knows. The companion test below proves it is still a
    failure anywhere else, which is what keeps this a classification and not a
    hole.
    """
    lines = atlas_pack_lines()
    lines.append(
        _quad(f"{EX}c1", f"{ATLAS}recordStatus", "active", literal=True)
    )
    suite.write_pack_lines(lines)

    results = suite.run()

    assert result(results, "source-claim-coverage").passed
    assert result(results, "claim-scope").passed


def test_record_status_is_declared_in_the_receipt_not_silently_dropped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tools.verify_atlas_source_fidelity as verifier

    fixture = Fixture(tmp_path)
    fixture.write_publisher()
    fixture.write_pack()
    monkeypatch.setattr(verifier, "SOURCES", (fixture.spec,))
    output = tmp_path / "receipt.json"
    verifier.main(
        [
            "--distribution",
            str(fixture.distribution),
            "--source-root",
            str(fixture.source_root),
            "--output",
            str(output),
            "--minimum-label-sample",
            "1",
        ]
    )

    receipt = json.loads(output.read_text(encoding="utf-8"))
    excluded = receipt["comparisons"][0]["claimScope"]["intentionallyExcludedFamilies"]
    structure = next(
        row for row in excluded if row["name"] == "atlasRepresentationStructure"
    )
    assert f"{ATLAS}recordStatus" in structure["predicates"]
    assert "Atlas-minted" in structure["reason"]


# --------------------------------------------------------------------------------------
# Declared claim exclusions: a publisher entity layer Atlas does not model
# --------------------------------------------------------------------------------------

RDFS = "http://www.w3.org/2000/01/rdf-schema#"
GROUP = f"{EX}group/1"
GROUP_TYPE = f"{EX}Group"
GROUP_TRIPLES = (
    f"<{GROUP}> a <{GROUP_TYPE}> ;\n"
    f'  <{RDFS}label> "Browsing group"@en ;\n'
    f"  <{SKOS}member> <{EX}c1>, <{EX}c2> ."
)
GROUP_EXCLUSION = DeclaredClaimExclusion(
    name="publisherBrowsingGroups",
    reason="the publisher's browsing collections are not terms and Atlas models none of them",
    subject_types=frozenset({GROUP_TYPE}),
)


def _with_group(suite: Fixture) -> None:
    suite.write_publisher(extra_triples=GROUP_TRIPLES)
    suite.write_pack(source_digest=suite.publisher_content_digest())


def test_an_undeclared_publisher_entity_layer_stays_uncovered(suite: Fixture) -> None:
    _with_group(suite)

    check = result(suite.run(), "source-claim-coverage")

    assert not check.passed
    assert any(f"{SKOS}member" in failure and GROUP in failure for failure in check.failures)


def test_a_declared_exclusion_accounts_for_the_layer_instead_of_hiding_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tools.verify_atlas_source_fidelity as verifier

    fixture = Fixture(tmp_path)
    _with_group(fixture)
    fixture.spec = replace(
        fixture.spec, declared_claim_exclusions=(GROUP_EXCLUSION,)
    )
    monkeypatch.setattr(verifier, "SOURCES", (fixture.spec,))
    output = tmp_path / "receipt.json"
    verifier.main(
        [
            "--distribution",
            str(fixture.distribution),
            "--source-root",
            str(fixture.source_root),
            "--output",
            str(output),
            "--minimum-label-sample",
            "1",
        ]
    )

    receipt = json.loads(output.read_text(encoding="utf-8"))
    coverage = next(
        row for row in receipt["results"] if row["check"] == "source-claim-coverage"
    )
    assert coverage["passed"]
    assert "declared out of scope" in coverage["summary"]

    family = next(
        row
        for row in receipt["comparisons"][0]["claimScope"][
            "intentionallyExcludedFamilies"
        ]
        if row["name"] == "publisherBrowsingGroups"
    )
    assert family["status"] == "declared-out-of-scope"
    assert family["subjectCount"] == 1
    assert family["publisherClaimCount"] == 4
    assert family["publisherClaimCountsByPredicate"][f"{SKOS}member"] == 2
    assert family["publisherClaimCountsByPredicate"][f"{RDFS}label"] == 1
    assert family["atlasClaimCount"] == 0


def test_a_declared_exclusion_fails_closed_when_atlas_asserts_the_layer(
    suite: Fixture,
) -> None:
    """The exclusion only ever removes publisher claims; the Atlas side stays live."""
    suite.write_publisher(extra_triples=GROUP_TRIPLES)
    lines = atlas_pack_lines(source_digest=suite.publisher_content_digest())
    lines.append(_quad(GROUP, f"{SKOS}prefLabel", "Manufactured group", literal=True))
    suite.write_pack_lines(lines)
    spec = replace(suite.spec, declared_claim_exclusions=(GROUP_EXCLUSION,))

    results = suite.run(spec=spec)

    coverage = result(results, "source-claim-coverage")
    assert not coverage.passed
    assert any(
        "Atlas literal claim" in failure and GROUP in failure
        for failure in coverage.failures
    )
    scope = result(results, "claim-scope")
    assert not scope.passed
    assert any(
        "publisherBrowsingGroups does not hold" in failure for failure in scope.failures
    )


def test_a_declared_exclusion_reaches_its_own_blank_nodes_and_no_others(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Publishers describe excluded entities with blank nodes; the scheme's are not.

    void:classPartition is the real case: a declared dataset hangs its per-class
    counts off blank nodes that never reach the IRI-subject claim sets. The
    closure follows blank nodes out of an excluded subject and stops there, so
    the identical shape on a compared subject stays in the uncovered report.
    """
    import tools.verify_atlas_source_fidelity as verifier

    fixture = Fixture(tmp_path)
    fixture.write_publisher(
        extra_triples=(
            f"{GROUP_TRIPLES[:-2]};\n"
            f'  <{EX}partition> [ <{EX}entities> "4" ] .\n'
            f'<{SCHEME}> <{EX}partition> [ <{EX}entities> "9" ] .'
        )
    )
    fixture.write_pack(source_digest=fixture.publisher_content_digest())
    fixture.spec = replace(
        fixture.spec, declared_claim_exclusions=(GROUP_EXCLUSION,)
    )
    monkeypatch.setattr(verifier, "SOURCES", (fixture.spec,))
    output = tmp_path / "receipt.json"
    verifier.main(
        [
            "--distribution",
            str(fixture.distribution),
            "--source-root",
            str(fixture.source_root),
            "--output",
            str(output),
            "--minimum-label-sample",
            "1",
        ]
    )

    receipt = json.loads(output.read_text(encoding="utf-8"))
    coverage = next(
        row for row in receipt["results"] if row["check"] == "source-claim-coverage"
    )
    assert not coverage["passed"]
    assert any(SCHEME in failure for failure in coverage["failures"])
    assert not any(GROUP in failure for failure in coverage["failures"])

    family = next(
        row
        for row in receipt["comparisons"][0]["claimScope"][
            "intentionallyExcludedFamilies"
        ]
        if row["name"] == "publisherBrowsingGroups"
    )
    assert family["publisherBlankNodeClaimCount"] == 2
    assert family["status"] == "declared-out-of-scope"


RELEASE = f"{EX}release/2026-01-01"


def _with_adopted_release(suite: Fixture, *, atlas_asserts: Sequence[str] = ()) -> None:
    """Publisher describes a release; Atlas adopts that IRI as its source release."""
    suite.write_publisher(
        extra_triples=(
            f"<{RELEASE}> a <{EX}Work> ;\n"
            f'  <http://purl.org/dc/terms/title> "Example release"@en ;\n'
            f'  <http://purl.org/dc/terms/version> "1.0" .'
        )
    )
    lines = atlas_pack_lines(source_digest=suite.publisher_content_digest())
    lines.append(_quad(RELEASE, f"{RDF}type", f"{ATLAS}SourceRelease"))
    lines.extend(atlas_asserts)
    suite.write_pack_lines(lines)


def test_release_metadata_reports_publisher_fields_atlas_drops_by_family(
    suite: Fixture,
) -> None:
    """A release Atlas adopts is compared field for field, named compactly."""
    _with_adopted_release(suite)

    check = result(suite.run(), "source-release-metadata")

    assert not check.passed
    assert any(
        "title family are missing from Atlas" in failure for failure in check.failures
    )
    assert any(
        "version family are missing from Atlas" in failure for failure in check.failures
    )


def test_release_metadata_fires_when_atlas_states_an_unsupported_release_field(
    suite: Fixture,
) -> None:
    """The direction that matters most: Atlas asserting what the publisher did not."""
    _with_adopted_release(
        suite,
        atlas_asserts=(
            _quad(
                RELEASE,
                "http://purl.org/dc/terms/issued",
                "2026-01-01",
                literal=True,
            ),
        ),
    )

    check = result(suite.run(), "source-release-metadata")

    assert not check.passed
    assert any(
        "Atlas adds" in failure and "dates family" in failure
        for failure in check.failures
    )


def test_an_adopted_release_iri_can_never_be_declared_out_of_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Adoption beats any declaration, and the routing is stated, not silent.

    A declaration worded broadly enough to reach a release Atlas adopted does
    not get to cover it: those claims stay in source-release-metadata, and the
    receipt names the subject it routed away rather than quietly dropping it.
    """
    import tools.verify_atlas_source_fidelity as verifier

    fixture = Fixture(tmp_path)
    _with_adopted_release(fixture)
    overreaching = DeclaredClaimExclusion(
        name="allPublisherWorks",
        reason="an exclusion worded broadly enough to reach the adopted release",
        subject_types=frozenset({f"{EX}Work"}),
    )
    fixture.spec = replace(
        fixture.spec, declared_claim_exclusions=(overreaching,)
    )
    monkeypatch.setattr(verifier, "SOURCES", (fixture.spec,))
    output = tmp_path / "receipt.json"
    verifier.main(
        [
            "--distribution",
            str(fixture.distribution),
            "--source-root",
            str(fixture.source_root),
            "--output",
            str(output),
            "--minimum-label-sample",
            "1",
        ]
    )

    receipt = json.loads(output.read_text(encoding="utf-8"))
    family = next(
        row
        for row in receipt["comparisons"][0]["claimScope"][
            "intentionallyExcludedFamilies"
        ]
        if row["name"] == "allPublisherWorks"
    )
    assert family["routedToReleaseComparison"] == [RELEASE]
    assert family["publisherClaimCount"] == 0
    release = next(
        row for row in receipt["results"] if row["check"] == "source-release-metadata"
    )
    assert any(
        "title family are missing from Atlas" in failure
        for failure in release["failures"]
    )


def test_release_metadata_ignores_atlas_minted_provenance(suite: Fixture) -> None:
    """Atlas structure on the adopted IRI is declared elsewhere, not a difference."""
    _with_adopted_release(
        suite,
        atlas_asserts=(
            _quad(RELEASE, f"{ATLAS}semanticRing", f"{ATLAS}SourceRing"),
            _plain_literal_quad(RELEASE, f"{ATLAS}contentDigest", "sha256:" + "a" * 64),
        ),
    )

    check = result(suite.run(), "source-release-metadata")

    assert not any("Atlas adds" in failure for failure in check.failures)


def test_a_declared_exclusion_may_not_cover_a_subject_the_comparison_compares(
    suite: Fixture,
) -> None:
    """A scope declaration is not a way to un-compare something already compared."""
    overreaching = DeclaredClaimExclusion(
        name="everyConcept",
        reason="an exclusion that reaches the compared terms themselves",
        subject_types=frozenset({f"{SKOS}Concept"}),
    )
    spec = replace(suite.spec, declared_claim_exclusions=(overreaching,))

    results = suite.run(spec=spec)

    scope = result(results, "claim-scope")
    assert not scope.passed
    assert any(
        "everyConcept covers" in failure and "also compares" in failure
        for failure in scope.failures
    )


def test_a_declared_exclusion_must_name_the_subjects_it_covers() -> None:
    with pytest.raises(ValueError, match="selects no subjects"):
        DeclaredClaimExclusion(name="everything", reason="no selector at all")


@pytest.mark.parametrize(
    "predicate,value,literal",
    (
        (f"{ATLAS}sourceLocator", "urn:example:orphan-source", False),
        (f"{ATLAS}sourceDigest", "sha256:" + "f" * 64, True),
    ),
)
def test_source_claim_coverage_rejects_orphan_source_record_evidence(
    suite: Fixture,
    predicate: str,
    value: str,
    literal: bool,
) -> None:
    lines = atlas_pack_lines()
    lines.append(
        _quad(
            "urn:ref:atlas-source-record:orphan",
            predicate,
            value,
            literal=literal,
        )
    )
    suite.write_pack_lines(lines)

    check = result(suite.run(), "source-claim-coverage")

    assert not check.passed
    assert any(predicate in failure for failure in check.failures)


@pytest.mark.parametrize(
    "predicate,obj",
    (
        (f"{SKOS}broader", f"{EX}c1"),
        (f"{SKOS}topConceptOf", SCHEME),
        (f"{SKOS}inScheme", SCHEME),
    ),
)
def test_source_claim_coverage_rejects_source_relations_on_unknown_subjects(
    suite: Fixture,
    predicate: str,
    obj: str,
) -> None:
    lines = atlas_pack_lines()
    lines.append(_quad(f"{EX}ghost", predicate, obj))
    suite.write_pack_lines(lines)

    check = result(suite.run(), "source-claim-coverage")

    assert not check.passed
    assert any(
        "Atlas IRI claim" in failure
        and predicate in failure
        and f"{EX}ghost" in failure
        for failure in check.failures
    )


def test_source_claim_coverage_rejects_an_unknown_skosxl_label_closure(
    suite: Fixture,
) -> None:
    lines = atlas_pack_lines()
    label_node = "urn:ref:atlas-label:ghost"
    lines.extend(
        (
            _quad(f"{EX}ghost", f"{SKOSXL}prefLabel", label_node),
            _quad(
                label_node,
                f"{SKOSXL}literalForm",
                "Manufactured ghost label",
                literal=True,
            ),
        )
    )
    suite.write_pack_lines(lines)

    check = result(suite.run(), "source-claim-coverage")

    assert not check.passed
    assert any(f"{SKOSXL}prefLabel" in failure for failure in check.failures)
    assert any(f"{SKOSXL}literalForm" in failure for failure in check.failures)


def test_source_claim_coverage_rejects_an_orphan_literal_form_on_a_source_concept(
    suite: Fixture,
) -> None:
    lines = atlas_pack_lines()
    lines.append(
        _quad(
            f"{EX}c1",
            f"{SKOSXL}literalForm",
            "Manufactured orphan form",
            literal=True,
        )
    )
    suite.write_pack_lines(lines)

    check = result(suite.run(), "source-claim-coverage")

    assert not check.passed
    assert any(
        f"{SKOSXL}literalForm" in failure
        and "Manufactured orphan form" in failure
        for failure in check.failures
    )


def test_source_claim_coverage_ignores_a_complete_atlas_owned_resource(
    suite: Fixture,
) -> None:
    lines = atlas_pack_lines()
    atlas_subject = f"{EX}atlas-only"
    label_node = "urn:ref:atlas-label:atlas-only"
    internal_graph = "urn:ref:atlas:graph:v3:classification"
    lines.extend(
        line.replace(f"<{GRAPH}>", f"<{internal_graph}>")
        for line in (
            _quad(atlas_subject, f"{RDF}type", f"{ATLAS}AtlasResource"),
            _quad(atlas_subject, f"{ATLAS}semanticRing", f"{ATLAS}value"),
            _quad(
                atlas_subject,
                f"{ATLAS}resourceProfile",
                f"{ATLAS}codeScheme",
            ),
            _quad(atlas_subject, f"{SKOSXL}prefLabel", label_node),
            _quad(
                label_node,
                f"{SKOSXL}literalForm",
                "Atlas internal",
                literal=True,
            ),
        )
    )
    suite.write_pack_lines(lines)

    results = suite.run()

    assert result(results, "source-claim-coverage").passed
    assert result(results, "graph-structure").passed
    assert result(results, "claim-scope").passed


def test_adapter_exclusion_cannot_waive_missing_publisher_data(
    suite: Fixture,
) -> None:
    predicate = "http://example.org/vocab/intentionally-out-of-scope"
    suite.write_publisher(extra_triples=f'<{EX}c1> <{predicate}> "Metadata only."@en .')
    suite.write_pack()
    excluded = replace(
        suite.spec,
        excluded_resource_predicates=frozenset({predicate}),
    )

    check = result(suite.run(spec=excluded), "claim-scope")

    assert not check.passed
    assert any(
        "memberMetadataLiterals source claims are unrepresented" in text
        for text in check.failures
    )


def test_explicit_bounded_capture_compares_only_its_named_publisher_concepts(
    suite: Fixture,
) -> None:
    bounded = replace(
        suite.spec,
        included_concept_iris=frozenset({f"{EX}c1", f"{EX}c2"}),
    )
    suite.write_pack(drop_concept=f"{EX}c3")

    results = suite.run(spec=bounded)

    assert failed(results) == set(), [item.failures for item in results if not item.passed]


def test_bounded_capture_fails_closed_when_a_named_concept_is_absent(
    suite: Fixture,
) -> None:
    bounded = replace(
        suite.spec,
        included_concept_iris=frozenset({f"{EX}does-not-exist"}),
    )

    results = suite.run(spec=bounded)

    load = result(results, "load-errors")
    assert not load.passed
    assert any("included publisher concepts are absent" in text for text in load.failures)
    assert not result(results, "relation-fidelity").passed


def test_publisher_pin_fails_even_when_tampered_atlas_matches(suite: Fixture) -> None:
    suite.publisher_path.write_text(
        publisher_turtle(labels={f"{EX}c1": "Source was tampered"}),
        encoding="utf-8",
    )
    suite.write_pack(labels={f"{EX}c1": "Source was tampered"})
    check = result(suite.run(), "publisher-input-pins")
    assert not check.passed
    assert any("pinned input differs" in text for text in check.failures)


def test_graph_structure_ignores_named_graph_placement(suite: Fixture) -> None:
    lines = atlas_pack_lines(source_digest=suite.publisher_content_digest())
    lines[0] = lines[0].replace(f"<{GRAPH}>", "<urn:ref:atlas:graph:v3:derived>")
    suite.write_pack_lines(lines)
    check = result(suite.run(), "graph-structure")
    assert check.passed


def test_graph_structure_ignores_atlas_only_ring_graph_placement(
    suite: Fixture,
) -> None:
    lines = atlas_pack_lines()
    lines.append(
        _quad(f"{EX}c1", f"{ATLAS}semanticRing", f"{ATLAS}subject").replace(
            f"<{GRAPH}>",
            "<urn:ref:atlas:graph:v3:derived>",
        )
    )
    suite.write_pack_lines(lines)

    assert result(suite.run(), "graph-structure").passed


def test_graph_structure_fires_on_duplicate_literal_forms(suite: Fixture) -> None:
    lines = atlas_pack_lines()
    node = "urn:ref:atlas-label:c1-pref"
    lines.append(_quad(node, f"{SKOSXL}literalForm", "Contradictory", literal=True))
    suite.write_pack_lines(lines)
    check = result(suite.run(), "graph-structure")
    assert not check.passed
    assert any("has 2 literal forms" in text for text in check.failures)


def test_graph_structure_reports_a_pack_that_differs_from_its_manifest_pin(
    suite: Fixture,
) -> None:
    lines = atlas_pack_lines(labels={f"{EX}c1": "Changed after the manifest was written"})
    suite.pack_path.write_bytes(
        zstd.compress(("\n".join(lines) + "\n").encode("utf-8"))
    )

    check = result(suite.run(), "graph-structure")

    assert not check.passed
    assert any(
        "transport differs from atlas-manifest.json" in text
        and "sources/example/all.nq.zst" in text
        for text in check.failures
    )


# --------------------------------------------------------------------------------------
# rdf-provenance-fidelity
# --------------------------------------------------------------------------------------


def test_rdf_provenance_fails_when_source_digest_is_missing(suite: Fixture) -> None:
    suite.write_pack(include_source_digest=False)

    check = result(suite.run(), "rdf-provenance-fidelity")

    assert not check.passed
    assert sum("digest differs" in text for text in check.failures) == len(CONCEPTS)
    assert all("observed None" in text for text in check.failures)


def test_rdf_provenance_collects_every_independent_source_mismatch(
    suite: Fixture,
) -> None:
    wrong_digest = "sha256:" + "f" * 64
    suite.write_pack(
        source_digest=wrong_digest,
        source_locators={f"{EX}c1": f"{EX}c2"},
        native_scheme_iris={f"{EX}c1": ()},
        extra_native_payload={"opaqueTransform": "not independently reversible"},
    )

    results = suite.run()
    check = result(results, "rdf-provenance-fidelity")

    assert not check.passed
    assert sum("digest differs" in text for text in check.failures) == len(CONCEPTS)
    assert any("locator differs" in text and f"<{EX}c1>" in text for text in check.failures)
    assert any("schemeIris differs" in text and "observed []" in text for text in check.failures)
    assert any(
        "nativePayload field 'opaqueTransform' is not independently evaluated"
        in text
        and "3 source records" in text
        for text in check.failures
    )
    assert not result(results, "claim-scope").passed


def test_rdf_provenance_fails_closed_on_an_unevaluated_native_field(
    suite: Fixture,
) -> None:
    suite.write_pack(extra_native_payload={"publisherRepair": "trimmed whitespace"})

    check = result(suite.run(), "rdf-provenance-fidelity")

    assert not check.passed
    assert any(
        "nativePayload field 'publisherRepair' is not independently evaluated" in text
        for text in check.failures
    )


# --------------------------------------------------------------------------------------
# concept-traceability
# --------------------------------------------------------------------------------------


def test_traceability_fires_on_a_concept_absent_from_the_publisher(suite: Fixture) -> None:
    suite.write_pack(extra_relations=())
    lines = atlas_pack_lines()
    lines.append(_quad(f"{EX}ghost", "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", f"{SKOS}Concept"))
    suite.write_pack_lines(lines)
    check = result(suite.run(), "concept-traceability")
    assert not check.passed
    assert any("appears in no rdf:type record of the pinned publisher bytes" in text for text in check.failures)
    assert any(f"{EX}ghost" in text for text in check.failures)


def test_traceability_ignores_an_atlas_only_resource_class(suite: Fixture) -> None:
    lines = atlas_pack_lines()
    label_node = "urn:ref:atlas-label:atlas-only"
    lines.extend(
        [
            _quad(f"{EX}atlas-only", f"{RDF}type", f"{ATLAS}AtlasResource"),
            _quad(f"{EX}atlas-only", f"{ATLAS}semanticRing", f"{ATLAS}value"),
            _quad(
                f"{EX}atlas-only",
                f"{ATLAS}resourceProfile",
                f"{ATLAS}codeScheme",
            ),
            _quad(f"{EX}atlas-only", f"{SKOSXL}prefLabel", label_node),
            _quad(label_node, f"{SKOSXL}literalForm", "Atlas internal", literal=True),
        ]
    )
    suite.write_pack_lines(lines)

    results = suite.run()
    assert result(results, "concept-traceability").passed
    assert result(results, "label-fidelity").passed
    assert result(results, "count-reconciliation").passed
    assert result(results, "claim-scope").passed


def test_traceability_refuses_to_pass_with_no_sources_compared(suite: Fixture) -> None:
    results = verify(suite.distribution, suite.source_root, Expectations(minimum_label_sample=0), ())
    check = result(results, "concept-traceability")
    assert not check.passed
    assert any("traceability is unproven" in text for text in check.failures)


# --------------------------------------------------------------------------------------
# identifier-retention
# --------------------------------------------------------------------------------------


def test_identifier_retention_fires_when_the_publisher_iri_is_replaced_by_a_minted_one(suite: Fixture) -> None:
    suite.write_pack(minted_ids=True)
    check = result(suite.run(), "identifier-retention")
    assert not check.passed
    assert any("carries a minted RefSpec identifier" in text for text in check.failures)


def test_rdf_provenance_fires_on_a_source_locator_that_resolves_nowhere(
    suite: Fixture,
) -> None:
    lines = atlas_pack_lines()
    expected = _quad(
        "urn:ref:atlas-source-record:c1",
        f"{ATLAS}sourceLocator",
        f"{EX}c1",
    )
    lines[lines.index(expected)] = _quad(
        "urn:ref:atlas-source-record:c1",
        f"{ATLAS}sourceLocator",
        f"{EX}not-published",
    )
    suite.write_pack_lines(lines)
    check = result(suite.run(), "rdf-provenance-fidelity")
    assert not check.passed
    assert any("locator differs" in text and f"{EX}not-published" in text for text in check.failures)


def test_rdf_provenance_ignores_release_level_locators(suite: Fixture) -> None:
    """A locator on a node that is not a SourceRecord names an artifact set, not a record."""
    lines = atlas_pack_lines()
    lines.append(_quad("urn:ref:atlas-release:example", f"{ATLAS}sourceLocator", "urn:ref:source-artifact-set:abc"))
    suite.write_pack_lines(lines)
    assert result(suite.run(), "rdf-provenance-fidelity").passed


def test_rdf_provenance_rejects_swapped_valid_source_locators(suite: Fixture) -> None:
    lines = atlas_pack_lines()
    first = _quad("urn:ref:atlas-source-record:c1", f"{ATLAS}sourceLocator", f"{EX}c1")
    second = _quad("urn:ref:atlas-source-record:c2", f"{ATLAS}sourceLocator", f"{EX}c2")
    lines = [
        _quad("urn:ref:atlas-source-record:c1", f"{ATLAS}sourceLocator", f"{EX}c2")
        if line == first
        else _quad("urn:ref:atlas-source-record:c2", f"{ATLAS}sourceLocator", f"{EX}c1")
        if line == second
        else line
        for line in lines
    ]
    suite.write_pack_lines(lines)
    check = result(suite.run(), "rdf-provenance-fidelity")
    assert not check.passed
    assert sum("locator differs" in text for text in check.failures) == 2


def test_rdf_provenance_rejects_an_untyped_fabricated_record_target(
    suite: Fixture,
) -> None:
    ghost = f"{EX}ghost"
    record = "urn:ref:atlas-source-record:ghost"
    lines = atlas_pack_lines()
    lines.extend(
        [
            _quad(record, f"{RDF}type", f"{ATLAS}SourceRecord"),
            _quad(record, f"{ATLAS}sourceLocator", ghost),
            _plain_literal_quad(
                record,
                f"{ATLAS}sourceDigest",
                suite.publisher_content_digest(),
            ),
            _quad(record, f"{ATLAS}representsResource", ghost),
            _plain_literal_quad(
                record,
                f"{ATLAS}nativePayload",
                json.dumps({"schemeIris": []}, separators=(",", ":")),
            ),
        ]
    )
    suite.write_pack_lines(lines)

    check = result(suite.run(), "rdf-provenance-fidelity")

    assert not check.passed
    assert any(
        ghost in failure and "not a publisher concept" in failure
        for failure in check.failures
    )


# --------------------------------------------------------------------------------------
# label-fidelity
# --------------------------------------------------------------------------------------


def test_label_fidelity_fires_when_a_diacritic_is_stripped(suite: Fixture) -> None:
    suite.write_pack(labels={f"{EX}c1": "Cafe Society"})
    check = result(suite.run(), "label-fidelity")
    assert not check.passed
    assert any("absent from publisher bytes" in text for text in check.failures)
    assert any("Cafe Society" in text for text in check.failures)


def test_label_fidelity_fires_when_case_is_folded(suite: Fixture) -> None:
    suite.write_pack(labels={f"{EX}c2": "public houses"})
    check = result(suite.run(), "label-fidelity")
    assert not check.passed
    assert any("public houses" in text for text in check.failures)


def test_label_fidelity_reports_silent_whitespace_repair_separately(suite: Fixture) -> None:
    """A publisher label with trailing whitespace that we quietly trim is a repair, not a mismatch."""
    suite.write_publisher(labels={f"{EX}c3": "Tea Rooms\\u00A0"})
    check = result(suite.run(), "label-fidelity")
    assert not check.passed
    assert any("silently repairs surrounding whitespace" in text for text in check.failures)
    assert any(finding.kind == "source" for finding in check.source_findings)
    assert any("NO-BREAK SPACE" in finding.detail for finding in check.source_findings)


def test_every_whitespace_repair_names_its_resource(suite: Fixture) -> None:
    suite.write_publisher(
        labels={
            f"{EX}c2": "Public Houses\\u00A0",
            f"{EX}c3": "Tea Rooms\\u00A0",
        }
    )
    check = result(suite.run(), "label-fidelity")
    repair_failures = [failure for failure in check.failures if "silently repairs" in failure]
    assert len(repair_failures) == 2
    assert any(f"<{EX}c2>" in failure for failure in repair_failures)
    assert any(f"<{EX}c3>" in failure for failure in repair_failures)


def test_label_fidelity_fires_when_a_published_label_is_never_asserted(suite: Fixture) -> None:
    """The concept survives ingestion but the label the publisher gave it does not."""
    suite.write_pack(drop_label=f"{EX}c3")
    check = result(suite.run(), "label-fidelity")
    assert not check.passed
    assert any("is missing from Atlas" in text for text in check.failures)
    assert any("Tea Rooms" in text for text in check.failures)


def test_label_fidelity_fires_when_one_alternate_label_is_omitted(suite: Fixture) -> None:
    suite.write_pack(drop_alt_label=f"{EX}c2")
    check = result(suite.run(), "label-fidelity")
    assert not check.passed
    assert any("publisher altLabel" in text and "Pubs" in text and "missing from Atlas" in text for text in check.failures)


def test_label_fidelity_rejects_a_direct_manufactured_source_label(
    suite: Fixture,
) -> None:
    lines = atlas_pack_lines()
    lines.append(
        _quad(
            f"{EX}c1",
            f"{SKOS}prefLabel",
            "Manufactured direct label",
            literal=True,
        )
    )
    suite.write_pack_lines(lines)

    check = result(suite.run(), "label-fidelity")

    assert not check.passed
    assert any(
        "Manufactured direct label" in failure
        and "absent from publisher bytes" in failure
        for failure in check.failures
    )


def test_label_fidelity_does_not_waive_a_non_english_source_label(
    suite: Fixture,
) -> None:
    suite.write_publisher(
        extra_triples=f'<{EX}c1> <{SKOS}prefLabel> "Societe du cafe"@fr .'
    )
    suite.write_pack()

    check = result(suite.run(), "label-fidelity")

    assert not check.passed
    assert any(
        "Societe du cafe" in failure and "@fr" in failure
        for failure in check.failures
    )


def test_label_fidelity_fires_when_a_hidden_label_is_omitted(suite: Fixture) -> None:
    suite.write_publisher(extra_triples=f'<{EX}c1> <{SKOS}hiddenLabel> "internal term"@en .')
    check = result(suite.run(), "label-fidelity")
    assert not check.passed
    assert any("publisher hiddenLabel" in text and "internal term" in text for text in check.failures)


def test_publisher_skosxl_label_is_compared_through_its_literal_form(suite: Fixture) -> None:
    label_node = f"{EX}label/private-c1"
    suite.write_publisher(
        extra_triples=(
            f"<{EX}c1> <{SKOSXL}hiddenLabel> <{label_node}> .\n"
            f'<{label_node}> <{SKOSXL}literalForm> "Private source label"@en .'
        )
    )
    lines = atlas_pack_lines(source_digest=suite.publisher_content_digest())
    lines.append(_quad(f"{EX}c1", f"{SKOSXL}hiddenLabel", label_node))
    lines.append(_quad(label_node, f"{SKOSXL}literalForm", "Private source label", literal=True))
    suite.write_pack_lines(lines)

    assert result(suite.run(), "label-fidelity").passed
    assert result(suite.run(), "claim-scope").passed


def test_empty_publisher_label_node_is_a_defect_not_an_uncovered_claim(
    suite: Fixture,
) -> None:
    """A label node with no literalForm asserts nothing, so nothing escapes.

    The publisher's own bytes are broken here -- an skosxl:prefLabel edge that
    points at a node carrying no literal. That is worth reporting and worth
    preserving unrepaired, which is what check-source-defects is for. It is not
    a claim that fell outside comparison: there is no literal to compare, and
    the edge itself is compared as an IRI claim on its concept.
    """
    empty_node = f"{EX}label/empty-c1"
    suite.write_publisher(
        extra_triples=f"<{EX}c1> <{SKOSXL}prefLabel> <{empty_node}> ."
    )
    suite.write_pack(source_digest=suite.publisher_content_digest())

    results = suite.run()

    assert result(results, "source-claim-coverage").passed
    defects = result(results, "source-defects")
    assert defects.passed
    assert any(
        "0 skosxl:literalForm values" in finding.detail
        and empty_node in finding.detail
        for finding in defects.source_findings
    )


def test_publisher_label_node_with_two_literal_forms_stays_uncovered(
    suite: Fixture,
) -> None:
    """Two forms on one node is different: the node's multiplicity is lost."""
    node = f"{EX}label/doubled-c1"
    suite.write_publisher(
        extra_triples=(
            f"<{EX}c1> <{SKOSXL}hiddenLabel> <{node}> .\n"
            f'<{node}> <{SKOSXL}literalForm> "First form"@en, "Second form"@en .'
        )
    )
    suite.write_pack(source_digest=suite.publisher_content_digest())

    check = result(suite.run(), "source-claim-coverage")

    assert not check.passed
    assert any(
        "2 skosxl:literalForm values" in failure and node in failure
        for failure in check.failures
    )


def test_label_fidelity_fires_when_language_changes(suite: Fixture) -> None:
    lines = [line.replace('"Café Society"@en', '"Café Society"@fr') for line in atlas_pack_lines()]
    suite.write_pack_lines(lines)
    check = result(suite.run(), "label-fidelity")
    assert not check.passed
    assert any("Café Society" in text and "@fr" in text for text in check.failures)


def test_label_fidelity_fires_when_datatype_replaces_language(suite: Fixture) -> None:
    datatype = "http://www.w3.org/2001/XMLSchema#string"
    lines = [
        line.replace('"Café Society"@en', f'"Café Society"^^<{datatype}>')
        for line in atlas_pack_lines()
    ]
    suite.write_pack_lines(lines)
    check = result(suite.run(), "label-fidelity")
    assert not check.passed
    assert any(datatype in text for text in check.failures)


def test_untagged_source_labels_round_trip_through_declared_atlas_en_inverse(
    suite: Fixture,
) -> None:
    suite.publisher_path.write_text(
        publisher_turtle().replace("@en", ""),
        encoding="utf-8",
    )
    suite.pin_input("example.ttl")
    suite.write_pack()
    policy = replace(
        suite.spec.rdf_source,
        label_language_inverse="atlas-en-to-source-untagged",
    )

    assert result(
        suite.run(spec=replace(suite.spec, rdf_source=policy)),
        "label-fidelity",
    ).passed


def test_untagged_label_inverse_fails_closed_if_source_adds_a_language_tag(
    suite: Fixture,
) -> None:
    publisher = publisher_turtle().replace("@en", "")
    publisher = publisher.replace('"Café Society"', '"Café Society"@en')
    suite.publisher_path.write_text(publisher, encoding="utf-8")
    suite.pin_input("example.ttl")
    suite.write_pack(drop_label=f"{EX}c1")
    policy = replace(
        suite.spec.rdf_source,
        label_language_inverse="atlas-en-to-source-untagged",
    )

    check = result(
        suite.run(spec=replace(suite.spec, rdf_source=policy)),
        "label-fidelity",
    )

    assert not check.passed
    assert any(
        "atlas-en-to-source-untagged cannot be applied" in failure
        and "language-tagged" in failure
        for failure in check.failures
    )


def test_label_fidelity_refuses_to_pass_when_it_inspected_nothing(suite: Fixture) -> None:
    check = result(suite.run(Expectations(minimum_label_sample=10_000)), "label-fidelity")
    assert not check.passed
    assert any("cannot pass" in text for text in check.failures)


# --------------------------------------------------------------------------------------
# notation-fidelity
# --------------------------------------------------------------------------------------


def test_notation_fidelity_fires_when_a_publisher_notation_is_omitted(suite: Fixture) -> None:
    suite.write_publisher(extra_triples=f'<{EX}c1> <{SKOS}notation> "C-001" .')
    check = result(suite.run(), "notation-fidelity")
    assert not check.passed
    assert any("publisher notation" in text and "C-001" in text and "missing from Atlas" in text for text in check.failures)


def test_plain_rdf_notation_matches_explicit_xsd_string(suite: Fixture) -> None:
    suite.write_publisher(extra_triples=f'<{EX}c1> <{SKOS}notation> "C-001" .')
    lines = atlas_pack_lines()
    lines.append(
        f'<{EX}c1> <{ATLAS}notation> "C-001"^^<http://www.w3.org/2001/XMLSchema#string> <{GRAPH}> .'
    )
    suite.write_pack_lines(lines)
    assert result(suite.run(), "notation-fidelity").passed


def test_typed_notation_lexical_form_is_not_normalized(suite: Fixture) -> None:
    datatype = "http://www.w3.org/2001/XMLSchema#integer"
    suite.write_publisher(
        extra_triples=f'<{EX}c1> <{SKOS}notation> "01"^^<{datatype}> .'
    )
    lines = atlas_pack_lines()
    lines.append(f'<{EX}c1> <{ATLAS}notation> "1"^^<{datatype}> <{GRAPH}> .')
    suite.write_pack_lines(lines)
    check = result(suite.run(), "notation-fidelity")
    assert not check.passed
    assert any("'01'" in text and "missing from Atlas" in text for text in check.failures)
    assert any("'1'" in text and "absent from publisher bytes" in text for text in check.failures)


def test_iri_notation_cannot_match_an_atlas_literal_with_the_same_text(suite: Fixture) -> None:
    notation_iri = "http://example.org/notation/C-001"
    suite.write_publisher(extra_triples=f"<{EX}c1> <{SKOS}notation> <{notation_iri}> .")
    lines = atlas_pack_lines()
    lines.append(
        f'<{EX}c1> <{ATLAS}notation> "{notation_iri}"'
        f'^^<http://www.w3.org/2001/XMLSchema#string> <{GRAPH}> .'
    )
    suite.write_pack_lines(lines)
    check = result(suite.run(), "notation-fidelity")
    assert not check.passed
    assert any("absent from publisher bytes" in text for text in check.failures)
    defects = result(suite.run(), "source-defects")
    assert any("wrong RDF term kind" in finding.detail for finding in defects.source_findings)


# --------------------------------------------------------------------------------------
# annotation-fidelity
# --------------------------------------------------------------------------------------


def test_annotation_fidelity_fires_when_a_definition_is_omitted(suite: Fixture) -> None:
    suite.write_publisher(
        extra_triples=f'<{EX}c1> <{SKOS}definition> "An exact source definition."@en .'
    )
    check = result(suite.run(), "annotation-fidelity")
    assert not check.passed
    assert any(
        "publisher definition" in text
        and "An exact source definition." in text
        and "missing from Atlas" in text
        for text in check.failures
    )


def test_malformed_publisher_annotation_cannot_receive_an_exact_verdict(
    suite: Fixture,
) -> None:
    suite.write_publisher(
        extra_triples=(
            f"<{EX}c1> <{SKOS}definition> "
            f'[ <{RDF}value> "Blank-node definition"@en ] .'
        )
    )
    suite.write_pack()

    coverage = result(suite.run(), "source-claim-coverage")

    assert not coverage.passed
    assert any(
        "could not enter an exact comparison" in failure
        and "wrong RDF term kind" in failure
        for failure in coverage.failures
    )
    assert result(suite.run(), "source-defects").passed


def test_exact_definition_and_generic_note_mapping_pass(suite: Fixture) -> None:
    suite.write_publisher(
        extra_triples=(
            f'<{EX}c1> <{SKOS}definition> "An exact source definition."@en .\n'
            f'<{EX}c1> <{SKOS}scopeNote> "Use only for the exact scope."@en .'
        )
    )
    lines = atlas_pack_lines(
        native_literal_evidence={
            f"{EX}c1": (
                {
                    "propertyIri": f"{SKOS}scopeNote",
                    "value": "Use only for the exact scope.",
                    "language": "en",
                },
            )
        }
    )
    lines.append(
        _quad(f"{EX}c1", f"{ATLAS}definition", "An exact source definition.", literal=True)
    )
    lines.append(
        _quad(f"{EX}c1", f"{ATLAS}note", "Use only for the exact scope.", literal=True)
    )
    suite.write_pack_lines(lines)
    assert result(suite.run(), "annotation-fidelity").passed


def test_definition_cannot_be_demoted_to_a_generic_note(suite: Fixture) -> None:
    suite.write_publisher(
        extra_triples=f'<{EX}c1> <{SKOS}definition> "Definition role matters."@en .'
    )
    lines = atlas_pack_lines()
    lines.append(_quad(f"{EX}c1", f"{ATLAS}note", "Definition role matters.", literal=True))
    suite.write_pack_lines(lines)
    check = result(suite.run(), "annotation-fidelity")
    assert any("publisher definition" in text and "missing from Atlas" in text for text in check.failures)
    assert any("Atlas note" in text and "absent from publisher bytes in that role" in text for text in check.failures)


def test_generic_note_without_source_predicate_evidence_is_lossy(suite: Fixture) -> None:
    suite.write_publisher(
        extra_triples=f'<{EX}c1> <{SKOS}historyNote> "Role must survive."@en .'
    )
    lines = atlas_pack_lines()
    lines.append(_quad(f"{EX}c1", f"{ATLAS}note", "Role must survive.", literal=True))
    suite.write_pack_lines(lines)
    check = result(suite.run(), "annotation-fidelity")
    assert not check.passed
    assert any("source predicate is not retained" in text for text in check.failures)
    scope = result(suite.run(), "claim-scope")
    assert not scope.passed
    assert any("notes is represented with known semantic loss" in text for text in scope.failures)


def test_single_declared_note_predicate_round_trips_generic_atlas_note(
    suite: Fixture,
) -> None:
    suite.write_publisher(
        extra_triples=f'<{EX}c1> <{SKOS}historyNote> "Role is source-wide."@en .'
    )
    lines = atlas_pack_lines(source_digest=suite.publisher_content_digest())
    lines.append(
        _quad(
            f"{EX}c1",
            f"{ATLAS}note",
            "Role is source-wide.",
            literal=True,
        )
    )
    suite.write_pack_lines(lines)
    policy = replace(
        suite.spec.rdf_source,
        note_predicate_inverse=f"{SKOS}historyNote",
    )
    spec = replace(suite.spec, rdf_source=policy)

    assert result(suite.run(spec=spec), "annotation-fidelity").passed
    assert result(suite.run(spec=spec), "claim-scope").passed


def test_distinct_source_note_roles_cannot_collapse_to_one_claim(suite: Fixture) -> None:
    suite.write_publisher(
        extra_triples=(
            f'<{EX}c1> <{SKOS}scopeNote> "Same lexical note."@en .\n'
            f'<{EX}c1> <{SKOS}historyNote> "Same lexical note."@en .'
        )
    )
    lines = atlas_pack_lines()
    lines.append(_quad(f"{EX}c1", f"{ATLAS}note", "Same lexical note.", literal=True))
    suite.write_pack_lines(lines)
    check = result(suite.run(), "annotation-fidelity")
    assert any("would collapse those source claims" in text for text in check.failures)


def test_resource_valued_definition_is_not_misclassified_as_a_source_defect(
    suite: Fixture,
) -> None:
    definition = f"{EX}c1-definition"
    suite.write_publisher(
        extra_triples=(
            f"<{EX}c1> <{SKOS}definition> <{definition}> .\n"
            f'<{definition}> <{RDF}value> "Exact reified definition."@en .'
        )
    )

    results = suite.run()
    check = result(results, "annotation-fidelity")

    assert not check.passed
    assert any(
        "publisher resource-valued annotation" in text
        and "1 additional direct claims" in text
        for text in check.failures
    )
    assert not any(
        "wrong RDF term kind" in finding.detail
        and f"<{SKOS}definition>" in finding.detail
        for finding in result(results, "source-defects").source_findings
    )


def test_resource_annotation_target_closure_is_compared_after_edge_survives(
    suite: Fixture,
) -> None:
    definition = f"{EX}c1-definition"
    suite.write_publisher(
        extra_triples=(
            f"<{EX}c1> <{SKOS}definition> <{definition}> .\n"
            f'<{definition}> <{RDF}value> "Exact reified definition."@en .'
        )
    )
    suite.write_pack(
        extra_relations=((f"{EX}c1", f"{SKOS}definition", definition),)
    )

    check = result(suite.run(), "annotation-fidelity")

    assert not check.passed
    assert not any("resource-valued annotation" in text for text in check.failures)
    assert any(
        "publisher annotation-target literal" in text
        and "Exact reified definition." in text
        for text in check.failures
    )


def test_resource_annotation_target_closure_round_trips_exactly(
    suite: Fixture,
) -> None:
    definition = f"{EX}c1-definition"
    suite.write_publisher(
        extra_triples=(
            f"<{EX}c1> <{SKOS}definition> <{definition}> .\n"
            f'<{definition}> <{RDF}value> "Exact reified definition."@en .'
        )
    )
    lines = atlas_pack_lines(
        extra_relations=((f"{EX}c1", f"{SKOS}definition", definition),),
        source_digest=suite.publisher_content_digest(),
    )
    lines.append(
        _quad(
            definition,
            f"{RDF}value",
            "Exact reified definition.",
            literal=True,
        )
    )
    suite.write_pack_lines(lines)

    assert result(suite.run(), "annotation-fidelity").passed


def test_resource_annotation_target_closure_rejects_a_novel_atlas_predicate(
    suite: Fixture,
) -> None:
    definition = f"{EX}c1-definition"
    novel = "http://example.org/source/novel"
    suite.write_publisher(
        extra_triples=(
            f"<{EX}c1> <{SKOS}definition> <{definition}> .\n"
            f'<{definition}> <{RDF}value> "Exact reified definition."@en .'
        )
    )
    lines = atlas_pack_lines(
        extra_relations=((f"{EX}c1", f"{SKOS}definition", definition),),
        extra_native_payload_by_resource={
            f"{EX}c1": {
                "sourceAnnotations": [
                    {
                        "subjectIri": definition,
                        "propertyIri": novel,
                        "value": "Invented",
                    }
                ]
            }
        },
        source_digest=suite.publisher_content_digest(),
    )
    lines.append(
        _quad(
            definition,
            f"{RDF}value",
            "Exact reified definition.",
            literal=True,
        )
    )
    suite.write_pack_lines(lines)

    check = result(suite.run(), "annotation-fidelity")

    assert not check.passed
    assert any(
        novel in failure and "absent from publisher bytes" in failure
        for failure in check.failures
    )


def test_resource_annotation_target_closure_ignores_a_direct_atlas_classification(
    suite: Fixture,
) -> None:
    definition = f"{EX}c1-definition"
    fabricated_class = "http://example.org/source/FabricatedClass"
    suite.write_publisher(
        extra_triples=(
            f"<{EX}c1> <{SKOS}definition> <{definition}> .\n"
            f'<{definition}> <{RDF}value> "Exact reified definition."@en .'
        )
    )
    lines = atlas_pack_lines(
        extra_relations=((f"{EX}c1", f"{SKOS}definition", definition),),
        source_digest=suite.publisher_content_digest(),
    )
    lines.extend(
        [
            _quad(
                definition,
                f"{RDF}value",
                "Exact reified definition.",
                literal=True,
            ),
            _quad(definition, f"{RDF}type", fabricated_class),
        ]
    )
    suite.write_pack_lines(lines)

    assert result(suite.run(), "annotation-fidelity").passed


def test_resource_annotation_target_closure_rejects_a_native_source_type(
    suite: Fixture,
) -> None:
    definition = f"{EX}c1-definition"
    fabricated_class = "http://example.org/source/FabricatedClass"
    suite.write_publisher(
        extra_triples=(
            f"<{EX}c1> <{SKOS}definition> <{definition}> .\n"
            f'<{definition}> <{RDF}value> "Exact reified definition."@en .'
        )
    )
    lines = atlas_pack_lines(
        extra_relations=((f"{EX}c1", f"{SKOS}definition", definition),),
        extra_native_payload_by_resource={
            f"{EX}c1": {
                "semanticRelations": [
                    {
                        "subjectIri": definition,
                        "predicateIri": f"{RDF}type",
                        "objectIri": fabricated_class,
                    }
                ]
            }
        },
        source_digest=suite.publisher_content_digest(),
    )
    lines.append(
        _quad(
            definition,
            f"{RDF}value",
            "Exact reified definition.",
            literal=True,
        )
    )
    suite.write_pack_lines(lines)

    check = result(suite.run(), "annotation-fidelity")

    assert not check.passed
    assert any(
        fabricated_class in failure and "absent from publisher bytes" in failure
        for failure in check.failures
    )


# --------------------------------------------------------------------------------------
# member-literal-fidelity
# --------------------------------------------------------------------------------------


def test_member_iri_metadata_fires_when_source_claim_is_dropped(
    suite: Fixture,
) -> None:
    predicate = "http://purl.org/dc/terms/isVersionOf"
    suite.write_publisher(
        extra_triples=f"<{EX}c1> <{predicate}> <{EX}c2> ."
    )

    check = result(suite.run(), "member-iri-fidelity")

    assert not check.passed
    assert any(
        predicate in failure and "absent from reversible Atlas" in failure
        for failure in check.failures
    )


def test_member_iri_metadata_round_trips_without_interpretation(
    suite: Fixture,
) -> None:
    predicate = "http://purl.org/dc/terms/isVersionOf"
    relation = (f"{EX}c1", predicate, f"{EX}c2")
    suite.write_publisher(
        extra_triples=f"<{relation[0]}> <{relation[1]}> <{relation[2]}> ."
    )
    suite.write_pack(extra_relations=(relation,))

    assert result(suite.run(), "member-iri-fidelity").passed


def test_member_iri_metadata_rejects_a_novel_atlas_predicate(
    suite: Fixture,
) -> None:
    predicate = "http://example.org/source/novel"
    suite.write_pack(
        extra_relations=((f"{EX}c1", predicate, f"{EX}c2"),)
    )

    check = result(suite.run(), "member-iri-fidelity")

    assert not check.passed
    assert any(
        predicate in failure and "absent from publisher bytes" in failure
        for failure in check.failures
    )


def test_member_iri_metadata_ignores_a_direct_atlas_classification(
    suite: Fixture,
) -> None:
    fabricated_class = "http://example.org/source/FabricatedClass"
    lines = atlas_pack_lines()
    lines.append(_quad(f"{EX}c1", f"{RDF}type", fabricated_class))
    suite.write_pack_lines(lines)

    assert result(suite.run(), "member-iri-fidelity").passed


def test_member_iri_metadata_rejects_a_native_source_type(
    suite: Fixture,
) -> None:
    fabricated_class = "http://example.org/source/FabricatedClass"
    suite.write_pack(
        extra_native_payload_by_resource={
            f"{EX}c1": {
                "semanticRelations": [
                    {
                        "subjectIri": f"{EX}c1",
                        "predicateIri": f"{RDF}type",
                        "objectIri": fabricated_class,
                    }
                ]
            }
        }
    )

    check = result(suite.run(), "member-iri-fidelity")

    assert not check.passed
    assert any(
        fabricated_class in failure and "absent from publisher bytes" in failure
        for failure in check.failures
    )


def test_member_iri_metadata_ignores_an_atlas_owned_type(
    suite: Fixture,
) -> None:
    lines = atlas_pack_lines()
    lines.append(_quad(f"{EX}c1", f"{RDF}type", f"{ATLAS}AtlasResource"))
    suite.write_pack_lines(lines)

    assert result(suite.run(), "member-iri-fidelity").passed


def test_member_metadata_literal_round_trips_datatype_iri(suite: Fixture) -> None:
    predicate = "http://purl.org/dc/terms/created"
    datatype = "http://www.w3.org/2001/XMLSchema#date"
    suite.write_publisher(
        extra_triples=f'<{EX}c1> <{predicate}> "2026-08-07"^^<{datatype}> .'
    )
    suite.write_pack(
        extra_native_payload_by_resource={
            f"{EX}c1": {
                "metadata": [
                    {
                        "propertyIri": predicate,
                        "value": "2026-08-07",
                        "datatypeIri": datatype,
                    }
                ]
            }
        }
    )
    policy = replace(
        suite.spec.rdf_source,
        evaluated_native_payload_fields=(
            suite.spec.rdf_source.evaluated_native_payload_fields | {"metadata"}
        ),
    )
    spec = replace(suite.spec, rdf_source=policy)

    results = suite.run(spec=spec)

    assert result(results, "member-literal-fidelity").passed
    assert result(results, "rdf-provenance-fidelity").passed


def test_member_metadata_literal_fires_when_source_claim_is_dropped(
    suite: Fixture,
) -> None:
    predicate = "http://purl.org/dc/terms/created"
    suite.write_publisher(
        extra_triples=f'<{EX}c1> <{predicate}> "2026-08-07" .'
    )

    check = result(suite.run(), "member-literal-fidelity")

    assert not check.passed
    assert any(predicate in text and "absent from reversible Atlas" in text for text in check.failures)


# --------------------------------------------------------------------------------------
# top-concept-fidelity
# --------------------------------------------------------------------------------------


def test_top_concept_fidelity_fires_when_native_evidence_is_omitted(suite: Fixture) -> None:
    suite.write_publisher(extra_triples=f"<{EX}c1> <{SKOS}topConceptOf> <{SCHEME}> .")
    check = result(suite.run(), "top-concept-fidelity")
    assert not check.passed
    assert any(f"<{EX}c1> -> <{SCHEME}>" in text and "is missing" in text for text in check.failures)


def test_top_concept_fidelity_accepts_exact_native_evidence(suite: Fixture) -> None:
    suite.write_publisher(
        extra_triples=f"<{EX}c1> <{SKOS}topConceptOf> <{SCHEME}> ."
    )
    lines = atlas_pack_lines(top_concepts={f"{EX}c1": (SCHEME,)})
    suite.write_pack_lines(lines)
    assert result(suite.run(), "top-concept-fidelity").passed


def test_top_concept_fidelity_reconstructs_both_publisher_directions(
    suite: Fixture,
) -> None:
    suite.write_publisher(
        extra_triples=(
            f"<{EX}c1> <{SKOS}topConceptOf> <{SCHEME}> .\n"
            f"<{SCHEME}> <{SKOS}hasTopConcept> <{EX}c1> ."
        )
    )
    suite.write_pack_lines(atlas_pack_lines(top_concepts={f"{EX}c1": (SCHEME,)}))

    check = result(suite.run(), "top-concept-fidelity")

    assert check.passed


@pytest.mark.parametrize("subject", (SCHEME, f"{EX}c1"))
def test_top_concept_fidelity_rejects_an_inverse_assignment_to_a_ghost(
    suite: Fixture,
    subject: str,
) -> None:
    ghost = f"{EX}ghost-top-concept"
    lines = atlas_pack_lines()
    lines.append(_quad(subject, f"{SKOS}hasTopConcept", ghost))
    suite.write_pack_lines(lines)

    check = result(suite.run(), "top-concept-fidelity")

    assert not check.passed
    assert any(
        ghost in failure and "absent from publisher bytes" in failure
        for failure in check.failures
    )


def test_dangling_publisher_has_top_concept_is_reported_and_not_waived(
    suite: Fixture,
) -> None:
    dangling = f"{EX}missing-top-concept"
    suite.write_publisher(
        extra_triples=f"<{SCHEME}> <{SKOS}hasTopConcept> <{dangling}> ."
    )

    results = suite.run()

    top_check = result(results, "top-concept-fidelity")
    assert not top_check.passed
    assert any(dangling in failure for failure in top_check.failures)
    defects = result(results, "source-defects")
    assert any(
        "not declared skos:Concept" in finding.detail
        and dangling in finding.detail
        for finding in defects.source_findings
    )


def test_non_array_top_concept_payload_is_a_structural_error(suite: Fixture) -> None:
    lines = atlas_pack_lines()
    original = _quad(
        "urn:ref:atlas-source-record:c1",
        f"{ATLAS}nativePayload",
        json.dumps({"schemeIris": [SCHEME]}, separators=(",", ":")),
        literal=True,
    )
    replacement = _quad(
        "urn:ref:atlas-source-record:c1",
        f"{ATLAS}nativePayload",
        json.dumps(
            {"schemeIris": [SCHEME], "topConceptOfIris": SCHEME},
            separators=(",", ":"),
        ),
        literal=True,
    )
    lines = [replacement if line == original else line for line in lines]
    suite.write_pack_lines(lines)
    check = result(suite.run(), "graph-structure")
    assert any("non-array nativePayload.topConceptOfIris" in text for text in check.failures)


# --------------------------------------------------------------------------------------
# relation-fidelity
# --------------------------------------------------------------------------------------


def test_relation_fidelity_fires_on_an_inverted_relation(suite: Fixture) -> None:
    """Asserting narrower where the publisher said broader inverts the publisher's claim."""
    suite.write_pack(
        extra_relations=((f"{EX}c1", f"{SKOS}broader", f"{EX}c2"),),
        drop_relation=(f"{EX}c2", f"{SKOS}broader", f"{EX}c1"),
    )
    check = result(suite.run(), "relation-fidelity")
    assert not check.passed
    assert any("the publisher states the reverse direction only" in text for text in check.failures)


def test_relation_fidelity_fires_when_the_predicate_is_swapped(suite: Fixture) -> None:
    """c3/c1 is a hierarchy pair in the source; asserting association over it is not the same claim."""
    suite.write_pack(
        extra_relations=((f"{EX}c3", f"{SKOS}related", f"{EX}c1"),),
        drop_relation=(f"{EX}c3", f"{SKOS}broader", f"{EX}c1"),
    )
    check = result(suite.run(), "relation-fidelity")
    assert not check.passed
    assert any("but the publisher asserts ['skos:broader']" in text for text in check.failures)


def test_relation_fidelity_fires_on_a_manufactured_relation(suite: Fixture) -> None:
    suite.write_pack(extra_relations=((f"{EX}c2", f"{SKOS}related", f"{EX}c3"),))
    check = result(suite.run(), "relation-fidelity")
    assert not check.passed
    assert any("has no counterpart in the pinned publisher bytes" in text for text in check.failures)


def test_relation_fidelity_rejects_a_direct_manufactured_source_relation(
    suite: Fixture,
) -> None:
    ghost = f"{EX}ghost"
    lines = atlas_pack_lines()
    lines.append(_quad(f"{EX}c2", f"{SKOS}broader", ghost))
    suite.write_pack_lines(lines)

    check = result(suite.run(), "relation-fidelity")

    assert not check.passed
    assert any(
        ghost in failure and "no counterpart in the pinned publisher bytes" in failure
        for failure in check.failures
    )


def test_relation_fidelity_fires_when_a_publisher_relation_is_dropped(suite: Fixture) -> None:
    missing = (f"{EX}c2", f"{SKOS}broader", f"{EX}c1")
    suite.write_pack(drop_relation=missing)
    check = result(suite.run(), "relation-fidelity")
    assert not check.passed
    assert any("publisher asserts" in text and "missing from Atlas" in text for text in check.failures)


def test_relation_round_trips_from_native_payload_source_shape(suite: Fixture) -> None:
    relation = (f"{EX}c1", f"{SKOS}related", f"{EX}c2")
    suite.write_pack(
        drop_relation=relation,
        extra_native_payload_by_resource={
            f"{EX}c1": {
                "semanticRelations": [
                    {
                        "subjectIri": relation[0],
                        "predicateIri": relation[1],
                        "objectIri": relation[2],
                    }
                ]
            }
        },
    )
    spec = replace(
        suite.spec,
        rdf_source=RdfSourcePolicy(
            evaluated_native_payload_fields=frozenset(
                {"schemeIris", "semanticRelations"}
            )
        ),
    )

    results = suite.run(spec=spec)

    assert result(results, "relation-fidelity").passed
    assert result(results, "no-manufactured-relations").passed
    assert result(results, "rdf-provenance-fidelity").passed


def test_relation_round_trips_through_a_declared_predicate_inverse(
    suite: Fixture,
) -> None:
    source_predicate = "http://example.org/source/use"
    atlas_predicate = f"{ATLAS}sourceUse"
    relation = (f"{EX}c1", source_predicate, f"{EX}c2")
    suite.write_publisher(
        extra_triples=f"<{relation[0]}> <{relation[1]}> <{relation[2]}> ."
    )
    suite.write_pack(
        extra_relations=((relation[0], atlas_predicate, relation[2]),)
    )
    policy = replace(
        suite.spec.rdf_source,
        additional_relation_predicates=(source_predicate,),
        relation_predicate_inverse=((atlas_predicate, source_predicate),),
    )
    spec = replace(suite.spec, rdf_source=policy)

    results = suite.run(spec=spec)

    assert result(results, "relation-fidelity").passed
    assert result(results, "no-manufactured-relations").passed


def test_reification_round_trips_from_a_declared_source_id_rule(
    suite: Fixture,
) -> None:
    base = "https://example.org/source.xml"
    subject = f"{base}#c1"
    obj = f"{base}#c2"
    predicate = "http://example.org/source/relation"
    atlas_predicate = f"{ATLAS}sourceRelation"
    statement = f"{base}#rc1-c2"
    weight_predicate = "http://example.org/source/weight"
    suite.write_publisher(
        extra_triples=(
            f"<{subject}> <{predicate}> <{obj}> .\n"
            f"<{statement}> a <{RDF}Statement> ;\n"
            f"  <{RDF}subject> <{subject}> ;\n"
            f"  <{RDF}predicate> <{predicate}> ;\n"
            f"  <{RDF}object> <{obj}> .\n"
            f'<https://example.org/rc1-c2> <{weight_predicate}> "100" .'
        )
    )
    suite.write_pack(extra_relations=((subject, atlas_predicate, obj),))
    policy = replace(
        suite.spec.rdf_source,
        additional_relation_predicates=(predicate,),
        reification_base_iri=base,
        reification_predicates=(predicate,),
        reification_weight_predicate=weight_predicate,
        reification_weight_value=LiteralValue(
            "100",
            None,
            "http://www.w3.org/2001/XMLSchema#string",
        ),
        relation_predicate_inverse=((atlas_predicate, predicate),),
        relation_scope="all",
    )
    spec = replace(suite.spec, rdf_source=policy)

    check = result(suite.run(spec=spec), "reification-fidelity")

    assert check.passed
    assert check.summary == "1 relation statement reifications reconstructed from Atlas"
    assert result(suite.run(spec=spec), "relation-fidelity").passed


@pytest.mark.parametrize(
    ("marker", "prefix"),
    (
        ("Definition", "Definition-"),
        ("Definition Source", "DefinitionSource-"),
        ("Scope Note", "ScopeNote-"),
    ),
)
def test_literal_reification_round_trips_from_exact_native_literal_evidence(
    suite: Fixture,
    marker: str,
    prefix: str,
) -> None:
    base = "https://example.org/source.xml"
    subject = f"{base}#c1"
    predicate = "http://example.org/source/termNote"
    statement = f"{base}#{prefix}c1"
    suite.write_publisher(
        extra_triples=(
            f'<{subject}> <{predicate}> "{marker}" .\n'
            f"<{statement}> a <{RDF}Statement> ;\n"
            f"  <{RDF}subject> <{subject}> ;\n"
            f"  <{RDF}predicate> <{predicate}> ;\n"
            f'  <{RDF}object> "{marker}" .'
        )
    )
    suite.write_pack(
        extra_native_payload_by_resource={
            f"{EX}c1": {
                "sourceAnnotations": [
                    {
                        "subjectIri": subject,
                        "propertyIri": predicate,
                        "value": marker,
                    }
                ]
            }
        }
    )
    policy = replace(
        suite.spec.rdf_source,
        additional_annotation_predicates=(predicate,),
        literal_reification_id_rules=((predicate, marker, prefix),),
        reification_base_iri=base,
        reification_predicates=(predicate,),
    )
    spec = replace(suite.spec, rdf_source=policy)

    check = result(suite.run(spec=spec), "reification-fidelity")

    assert check.passed
    assert check.summary == "1 relation statement reifications reconstructed from Atlas"


def test_literal_relation_object_cannot_match_an_atlas_iri_with_the_same_text(suite: Fixture) -> None:
    suite.write_publisher(
        drop_relation=(f"{EX}c1", f"{SKOS}related", f"{EX}c2"),
        extra_triples=f'<{EX}c1> <{SKOS}related> "{EX}c2" .',
    )
    check = result(suite.run(), "relation-fidelity")
    assert not check.passed
    assert any("has no counterpart" in text and f"{EX}c2" in text for text in check.failures)
    defects = result(suite.run(), "source-defects")
    assert any("wrong RDF term kind" in finding.detail for finding in defects.source_findings)


# --------------------------------------------------------------------------------------
# no-manufactured-relations
# --------------------------------------------------------------------------------------


def test_strengthening_close_match_to_exact_match_fires(suite: Fixture) -> None:
    """closeMatch must never become exactMatch; the publisher's strength is the assertion."""
    suite.write_publisher(extra_triples=f"<{EX}c1> <{SKOS}closeMatch> <http://other.example/x> .")
    suite.write_pack(extra_relations=((f"{EX}c1", f"{SKOS}exactMatch", "http://other.example/x"),))
    check = result(suite.run(), "no-manufactured-relations")
    assert not check.passed
    assert any("strengthens" in text and "skos:closeMatch to skos:exactMatch" in text for text in check.failures)


def test_preserving_close_match_does_not_fire(suite: Fixture) -> None:
    """A negative control: carrying the publisher's own weaker predicate is correct."""
    suite.write_publisher(extra_triples=f"<{EX}c1> <{SKOS}closeMatch> <http://other.example/x> .")
    suite.write_pack(extra_relations=((f"{EX}c1", f"{SKOS}closeMatch", "http://other.example/x"),))
    assert result(suite.run(), "no-manufactured-relations").passed


# --------------------------------------------------------------------------------------
# count-reconciliation
# --------------------------------------------------------------------------------------


def test_count_reconciliation_fires_on_an_unexplained_drop(suite: Fixture) -> None:
    suite.write_pack(drop_concept=f"{EX}c3")
    check = result(suite.run(), "count-reconciliation")
    assert not check.passed
    assert any("concepts do not reconcile" in text and "cannot waive" in text for text in check.failures)


def test_unknown_policy_fails_coverage(suite: Fixture) -> None:
    spec = replace(suite.spec, policies=suite.spec.policies | {"invented-policy"})
    suite.write_pack(drop_concept=f"{EX}c3")
    check = result(suite.run(spec=spec), "distribution-coverage")
    assert not check.passed
    assert any("unknown executable policies" in text for text in check.failures)


def test_valid_policy_cannot_waive_an_unrelated_drop(suite: Fixture) -> None:
    suite.write_pack(drop_concept=f"{EX}c3")
    assert not result(suite.run(), "count-reconciliation").passed


# --------------------------------------------------------------------------------------
# scheme-organisation
# --------------------------------------------------------------------------------------


def test_source_scheme_memberships_round_trip_through_native_payload(
    suite: Fixture,
) -> None:
    lines = atlas_pack_lines(
        scheme_target="urn:ref:atlas-resource-scheme:example"
    )
    lines.append(_quad(SCHEME, f"{RDF}type", f"{SKOS}ConceptScheme"))
    suite.write_pack_lines(lines)
    check = result(suite.run(), "scheme-organisation")

    assert check.passed


def test_source_scheme_membership_fails_when_native_payload_omits_it(
    suite: Fixture,
) -> None:
    lines = atlas_pack_lines(
        scheme_target="urn:ref:atlas-resource-scheme:example",
        native_scheme_iris=dict.fromkeys(CONCEPTS, ()),
    )
    lines.append(_quad(SCHEME, f"{RDF}type", f"{SKOS}ConceptScheme"))
    suite.write_pack_lines(lines)
    check = result(suite.run(), "scheme-organisation")

    assert not check.passed
    assert any("nativePayload.schemeIris" in text for text in check.failures)


def test_source_scheme_identity_does_not_leak_from_membership_strings(
    suite: Fixture,
) -> None:
    lines = [
        line
        for line in atlas_pack_lines()
        if line != _quad(SCHEME, f"{RDF}type", f"{SKOS}ConceptScheme")
    ]
    suite.write_pack_lines(lines)

    check = result(suite.run(), "scheme-organisation")

    assert not check.passed
    assert any(
        f"publisher scheme <{SCHEME}> cannot be reconstructed" in failure
        for failure in check.failures
    )


def test_scheme_organisation_ignores_an_added_atlas_only_scheme_type(
    suite: Fixture,
) -> None:
    lines = atlas_pack_lines(scheme_target=SCHEME)
    lines.append(
        _quad(
            f"{EX}invented-scheme",
            "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
            f"{SKOS}ConceptScheme",
        )
    )
    suite.write_pack_lines(lines)
    check = result(suite.run(), "scheme-organisation")

    assert check.passed


def test_source_scheme_membership_fails_when_native_payload_adds_an_edge(
    suite: Fixture,
) -> None:
    suite.write_pack(
        native_scheme_iris={
            f"{EX}c1": (SCHEME, "http://example.org/scheme/not-published")
        }
    )

    check = result(suite.run(), "scheme-organisation")

    assert not check.passed
    assert any("nativePayload.schemeIris" in text for text in check.failures)


def test_source_scheme_literal_fails_when_it_is_not_reversible(
    suite: Fixture,
) -> None:
    suite.write_publisher(
        extra_triples=f'<{SCHEME}> <{SKOS}prefLabel> "Publisher scheme"@en .'
    )
    suite.write_pack()

    check = result(suite.run(), "scheme-organisation")

    assert not check.passed
    assert any(
        "publisher scheme literal" in failure
        and "Publisher scheme" in failure
        for failure in check.failures
    )


def test_source_scheme_literal_round_trips_from_normalized_atlas_label(
    suite: Fixture,
) -> None:
    suite.write_publisher(
        extra_triples=f'<{SCHEME}> <{SKOS}prefLabel> "Publisher scheme"@en .'
    )
    label = f"{EX}scheme-label"
    lines = atlas_pack_lines(source_digest=suite.publisher_content_digest())
    lines.extend(
        [
            _quad(SCHEME, f"{SKOSXL}prefLabel", label),
            _quad(label, f"{SKOSXL}literalForm", "Publisher scheme", literal=True),
        ]
    )
    suite.write_pack_lines(lines)

    assert result(suite.run(), "scheme-organisation").passed


def test_source_scheme_rejects_an_invented_normalized_atlas_label(
    suite: Fixture,
) -> None:
    label = f"{EX}invented-scheme-label"
    lines = atlas_pack_lines()
    lines.extend(
        [
            _quad(SCHEME, f"{SKOSXL}prefLabel", label),
            _quad(label, f"{SKOSXL}literalForm", "Invented scheme label", literal=True),
        ]
    )
    suite.write_pack_lines(lines)

    check = result(suite.run(), "scheme-organisation")

    assert not check.passed
    assert any(
        "Invented scheme label" in failure
        and "absent from publisher bytes" in failure
        for failure in check.failures
    )


def test_source_scheme_skosxl_label_value_is_compared_after_normalization(
    suite: Fixture,
) -> None:
    source_label = f"{EX}publisher-scheme-label"
    suite.write_publisher(
        extra_triples=(
            f"<{SCHEME}> <{SKOSXL}prefLabel> <{source_label}> .\n"
            f'<{source_label}> <{SKOSXL}literalForm> "Publisher scheme"@en .'
        )
    )
    atlas_label = f"{EX}atlas-scheme-label"
    lines = atlas_pack_lines(source_digest=suite.publisher_content_digest())
    lines.extend(
        [
            _quad(SCHEME, f"{SKOSXL}prefLabel", atlas_label),
            _quad(atlas_label, f"{SKOSXL}literalForm", "Changed scheme", literal=True),
        ]
    )
    suite.write_pack_lines(lines)

    check = result(suite.run(), "scheme-organisation")

    assert not check.passed
    assert any("Publisher scheme" in failure for failure in check.failures)
    assert any("Changed scheme" in failure for failure in check.failures)


def test_source_scheme_ignores_type_added_as_atlas_classification(
    suite: Fixture,
) -> None:
    publisher = publisher_turtle().replace(
        f"<{SCHEME}> a skos:ConceptScheme .\n\n",
        "",
    )
    suite.publisher_path.write_text(publisher, encoding="utf-8")
    suite.pin_input("example.ttl")
    suite.write_pack()

    assert result(suite.run(), "scheme-organisation").passed


def test_source_scheme_iri_metadata_fails_when_it_is_not_reversible(
    suite: Fixture,
) -> None:
    predicate = "http://www.w3.org/2002/07/owl#versionIRI"
    value = "http://example.org/scheme/version/1"
    suite.write_publisher(
        extra_triples=f"<{SCHEME}> <{predicate}> <{value}> ."
    )
    suite.write_pack()

    check = result(suite.run(), "scheme-organisation")

    assert not check.passed
    assert any(
        predicate in failure
        and value in failure
        and "missing from reversible Atlas" in failure
        for failure in check.failures
    )


def test_source_scheme_ignores_a_direct_atlas_classification(
    suite: Fixture,
) -> None:
    fabricated_class = "http://example.org/source/FabricatedSchemeClass"
    lines = atlas_pack_lines()
    lines.append(_quad(SCHEME, f"{RDF}type", fabricated_class))
    suite.write_pack_lines(lines)

    assert result(suite.run(), "scheme-organisation").passed


def test_source_scheme_rejects_a_native_source_type(suite: Fixture) -> None:
    fabricated_class = "http://example.org/source/FabricatedSchemeClass"
    suite.write_pack(
        extra_native_payload_by_resource={
            f"{EX}c1": {
                "semanticRelations": [
                    {
                        "subjectIri": SCHEME,
                        "predicateIri": f"{RDF}type",
                        "objectIri": fabricated_class,
                    }
                ]
            }
        }
    )

    check = result(suite.run(), "scheme-organisation")

    assert not check.passed
    assert any(
        fabricated_class in failure and "absent from publisher bytes" in failure
        for failure in check.failures
    )


def test_source_scheme_ignores_an_atlas_owned_type(suite: Fixture) -> None:
    lines = atlas_pack_lines()
    lines.append(_quad(SCHEME, f"{RDF}type", f"{ATLAS}AtlasResourceScheme"))
    suite.write_pack_lines(lines)

    assert result(suite.run(), "scheme-organisation").passed


# --------------------------------------------------------------------------------------
# source-defects
# --------------------------------------------------------------------------------------


def test_source_defects_reports_a_class_used_as_a_predicate(suite: Fixture) -> None:
    suite.write_publisher(extra_triples=f'<{EX}c1> <http://www.w3.org/ns/dcat#CatalogRecord> "<a href=\'x\'>y</a>" .')
    check = result(suite.run(), "source-defects")
    assert check.passed, "a publisher defect must never fail our pipeline"
    assert any("as a predicate on" in finding.detail for finding in check.source_findings)
    assert all(finding.kind == "source" for finding in check.source_findings)


def test_source_defects_detects_an_explicitly_declared_lowercase_class_predicate(suite: Fixture) -> None:
    predicate = f"{EX}catalogRecord"
    suite.write_publisher(
        extra_triples=(
            f"<{predicate}> a <http://www.w3.org/2000/01/rdf-schema#Class> .\n"
            f'<{EX}c1> <{predicate}> "bad predicate use" .'
        )
    )
    check = result(suite.run(), "source-defects")
    assert any(predicate in finding.detail and "explicitly declared" in finding.detail for finding in check.source_findings)


def test_source_defects_reports_whitespace_in_a_namespace_iri(suite: Fixture) -> None:
    text = publisher_turtle()
    text = (
        f"@prefix terms: <http://purl.org/dc/terms/%20#> .\n{text}\n"
        f'<{EX}c1> terms:bad "publisher value" .\n'
    )
    suite.publisher_path.write_text(text, encoding="utf-8")
    suite.pin_input("example.ttl")
    check = result(suite.run(), "source-defects")
    assert any("whitespace in its namespace IRI" in finding.detail for finding in check.source_findings)


def test_source_defects_reports_a_concept_with_no_preferred_label(suite: Fixture) -> None:
    suite.write_publisher(extra_triples=f"<{EX}c9> a <{SKOS}Concept> .")
    check = result(suite.run(), "source-defects")
    assert any("with no skos:prefLabel in any language" in finding.detail for finding in check.source_findings)


def test_source_defects_aggregates_ill_typed_literals_without_rdflib_tracebacks(
    suite: Fixture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    suite.write_publisher(
        extra_triples=(
            f'<{EX}c1> <{EX}modified> ""^^'
            '<http://www.w3.org/2001/XMLSchema#dateTime> .\n'
            f'<{EX}c2> <{EX}modified> ""^^'
            '<http://www.w3.org/2001/XMLSchema#dateTime> .'
        )
    )
    check = result(suite.run(), "source-defects")
    assert check.passed
    assert any(
        "2 ill-typed literal occurrence(s)" in finding.detail
        and "XMLSchema#dateTime" in finding.detail
        for finding in check.source_findings
    )
    assert not any(
        "Failed to convert Literal lexical form" in record.getMessage()
        for record in caplog.records
    )


def test_source_findings_never_fail_the_check() -> None:
    """Structural guarantee: a source finding carries no failure weight."""

    class _Pair:
        publisher = type("_P", (), {"defects": (Finding("source", "s", "d"),)})()

    ctx = type("_Ctx", (), {"pairs": (_Pair(),)})()
    outcome = check_source_defects(ctx)  # type: ignore[arg-type]
    assert outcome.passed
    assert outcome.source_findings


# --------------------------------------------------------------------------------------
# Literal decoding
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (r"plain", "plain"),
        (r"line\nbreak", "line\nbreak"),
        (r"quote\"inside", 'quote"inside'),
        (r"back\\slash", "back\\slash"),
        (r"é", "é"),
        (r"\U0001F600", "\U0001f600"),
        (r"en–dash", "en–dash"),
        (r"nbsp tail", "nbsp tail"),
    ],
)
def test_unescape_literal_is_exact(raw: str, expected: str) -> None:
    assert unescape_literal(raw) == expected


def test_en_dash_survives_the_nquads_round_trip() -> None:
    """USC section identifiers carry U+2013; ASCII-normalising one severs the join."""
    line = '<urn:s> <urn:p> "/us/usc/t26/s1400Z\\u2013 1"@en <urn:g> .'
    quad = parse_nquads_line(line)
    assert quad is not None
    assert quad.obj == "/us/usc/t26/s1400Z– 1"
    assert "–" in quad.obj


def test_literal_with_a_graph_term_parses() -> None:
    quad = parse_nquads_line('<urn:s> <urn:p> "value"@en <urn:g> .')
    assert quad is not None
    assert (quad.obj, quad.language, quad.is_literal) == ("value", "en", True)


def test_iri_object_parses() -> None:
    quad = parse_nquads_line("<urn:s> <urn:p> <urn:o> <urn:g> .")
    assert quad is not None
    assert (quad.obj, quad.is_literal) == ("urn:o", False)


def test_malformed_line_is_rejected() -> None:
    with pytest.raises(ValueError, match="terminate"):
        parse_nquads_line("<urn:s> <urn:p> <urn:o>")


# --------------------------------------------------------------------------------------
# Rendering and exit codes
# --------------------------------------------------------------------------------------


def test_render_separates_source_findings_from_pipeline_findings(suite: Fixture) -> None:
    suite.write_publisher(extra_triples=f'<{EX}c1> <http://www.w3.org/ns/dcat#CatalogRecord> "x" .')
    suite.write_pack(labels={f"{EX}c1": "Cafe Society"})
    text = render(suite.run())
    assert "PIPELINE FINDINGS" in text
    assert "SOURCE FINDINGS" in text
    assert text.index("PIPELINE FINDINGS") < text.index("SOURCE FINDINGS")
    assert "FAIL  label-fidelity" in text


def test_main_collects_errors_when_the_distribution_is_absent(
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    code = main(["--distribution", str(tmp_path / "nope"), "--source-root", str(tmp_path)])
    assert code == 1
    output = capsys.readouterr().out
    assert "missing atlas-construction-summary.json" in output
    assert "pinned input is missing or unsafe" in output


def test_main_collects_errors_when_the_source_root_is_absent(
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    distribution = tmp_path / "distribution"
    distribution.mkdir()
    code = main(["--distribution", str(distribution), "--source-root", str(tmp_path / "nope")])
    assert code == 1
    output = capsys.readouterr().out
    assert "FAIL  load-errors" in output
    assert "ELSST_R6.ttl" in output


def test_main_collects_all_missing_pinned_inputs(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    distribution = tmp_path / "distribution"
    distribution.mkdir()
    empty_sources = tmp_path / "sources"
    empty_sources.mkdir()
    code = main(["--distribution", str(distribution), "--source-root", str(empty_sources)])
    assert code == 1
    output = capsys.readouterr().out
    assert "ELSST_R6.ttl" in output
    assert "eurovoc-4.24-skos-core.zip" in output
    assert "eurovoc-lcsh-alignment-20240711.rdf" in output


def test_main_writes_its_findings_as_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import tools.verify_atlas_source_fidelity as verifier

    fixture = Fixture(tmp_path)
    fixture.write_publisher()
    fixture.write_pack(labels={f"{EX}c1": "Cafe Society"})
    monkeypatch.setattr(verifier, "SOURCES", (fixture.spec,))

    out = tmp_path / "findings.json"
    code = verifier.main(
        [
            "--distribution",
            str(fixture.distribution),
            "--source-root",
            str(fixture.source_root),
            "--output",
            str(out),
        ]
    )
    assert code == 1
    payload = json.loads(out.read_text(encoding="utf-8"))
    label_result = next(row for row in payload["results"] if row["check"] == "label-fidelity")
    assert "bindingValidation" not in payload
    assert all(row["check"] != "binding-validation" for row in payload["results"])
    assert label_result["passed"] is False
    assert payload["coverage"]["coveredUnitCount"] == 1
    assert payload["coverage"]["constructionUnits"] == [
        {
            "inputCount": 1,
            "key": "example",
            "kind": "sourceRelease",
            "packCount": 1,
            "resourceCount": 3,
            "status": "differences-found",
        }
    ]
    comparison = payload["comparisons"][0]
    assert comparison["kind"] == "vocabulary"
    assert comparison["subset"] == "all"
    assert comparison["includedPublisherConceptIris"] == []
    assert comparison["publisherInputs"]
    assert comparison["claimScope"]["status"] == "differences-found"
    assert {family["name"] for family in comparison["claimScope"]["claimFamilies"]} >= {
        "preferredLabels",
        "conceptIdentities",
        "semanticRelations",
    }
    transport = comparison["checkedPackTransports"][0]
    pack_bytes = fixture.pack_path.read_bytes()
    assert transport == {
        "path": "sources/example/all.nq.zst",
        "sha256": "sha256:" + hashlib.sha256(pack_bytes).hexdigest(),
        "byteLength": len(pack_bytes),
        "manifestSha256": "sha256:" + hashlib.sha256(pack_bytes).hexdigest(),
        "manifestByteLength": len(pack_bytes),
    }
    assert payload["expectations"]["requireCompleteCoverage"] is True
    assert payload["expectations"]["requireInputPins"] is True
    assert payload["expectations"]["requirePackPins"] is True
    assert payload["verifier"].startswith("atlas-source-fidelity/")
    assert "english-label-selection" in payload["executablePolicies"]


def test_receipt_never_marks_a_source_exact_when_its_input_pin_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tools.verify_atlas_source_fidelity as verifier

    fixture = Fixture(tmp_path)
    fixture.write_publisher()
    fixture.write_pack()
    fixture.publisher_path.write_text(
        publisher_turtle(labels={f"{EX}c1": "Tampered source"}),
        encoding="utf-8",
    )
    fixture.write_pack(labels={f"{EX}c1": "Tampered source"})
    monkeypatch.setattr(verifier, "SOURCES", (fixture.spec,))

    output = tmp_path / "receipt.json"
    code = verifier.main(
        [
            "--distribution",
            str(fixture.distribution),
            "--source-root",
            str(fixture.source_root),
            "--output",
            str(output),
        ]
    )

    assert code == 1
    receipt = json.loads(output.read_text(encoding="utf-8"))
    comparison = receipt["comparisons"][0]
    assert comparison["claimScope"]["status"] != "exact"
    assert receipt["coverage"]["constructionUnits"][0]["status"] != "exact"


def test_receipt_never_uses_last_write_wins_for_duplicate_adapter_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tools.verify_atlas_source_fidelity as verifier

    fixture = Fixture(tmp_path)
    fixture.write_publisher()
    fixture.write_pack()
    duplicate = replace(fixture.spec, name="duplicate-example")
    monkeypatch.setattr(verifier, "SOURCES", (fixture.spec, duplicate))

    output = tmp_path / "receipt.json"
    code = verifier.main(
        [
            "--distribution",
            str(fixture.distribution),
            "--source-root",
            str(fixture.source_root),
            "--output",
            str(output),
        ]
    )

    assert code == 1
    receipt = json.loads(output.read_text(encoding="utf-8"))
    configuration = next(
        row for row in receipt["results"] if row["check"] == "configuration"
    )
    assert any(
        "construction-unit comparison ownership must be unique" in failure
        for failure in configuration["failures"]
    )
    assert receipt["coverage"]["constructionUnits"][0]["status"] != "exact"


def test_main_returns_zero_when_every_check_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import tools.verify_atlas_source_fidelity as verifier

    fixture = Fixture(tmp_path)
    fixture.write_publisher()
    fixture.write_pack()
    monkeypatch.setattr(verifier, "SOURCES", (fixture.spec,))
    assert (
        verifier.main(
            [
                "--distribution",
                str(fixture.distribution),
                "--source-root",
                str(fixture.source_root),
                "--minimum-label-sample",
                "1",
            ]
        )
        == 0
    )


def test_receipt_write_failure_is_reported_without_a_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    import tools.verify_atlas_source_fidelity as verifier

    fixture = Fixture(tmp_path)
    fixture.write_publisher()
    fixture.write_pack()
    monkeypatch.setattr(verifier, "SOURCES", (fixture.spec,))
    blocking_file = tmp_path / "not-a-directory"
    blocking_file.write_text("blocks mkdir", encoding="utf-8")

    code = verifier.main(
        [
            "--distribution",
            str(fixture.distribution),
            "--source-root",
            str(fixture.source_root),
            "--output",
            str(blocking_file / "receipt.json"),
            "--minimum-label-sample",
            "1",
        ]
    )

    assert code == 1
    output = capsys.readouterr().out
    assert "FAIL  receipt-write" in output
    assert "FileExistsError" in output


def test_render_does_not_truncate_failure_details() -> None:
    failures = [f"failure-{index}" for index in range(25)]
    output = render([CheckResult("many-errors", False, "all retained", failures)])
    assert all(failure in output for failure in failures)


def test_receipt_caps_a_long_failure_list_but_still_proves_the_whole_of_it() -> None:
    """A capped list keeps the head, the count, and a digest over every entry."""
    import tools.verify_atlas_source_fidelity as verifier

    limit = verifier.RECEIPT_LIST_LIMIT
    failures = [f"failure-{index}" for index in range(limit + 137)]
    findings = [
        Finding(kind="source", source="example", detail=f"defect-{index}")
        for index in range(limit + 5)
    ]

    row = verifier._capped_result(
        CheckResult("many-errors", False, "capped", failures, findings)
    )

    assert row["failures"] == failures[:limit]
    assert row["failuresTotalCount"] == len(failures)
    assert row["failuresTruncated"] is True
    assert row["failuresDigest"] == "sha256:" + hashlib.sha256(
        json.dumps(failures, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert row["sourceFindingsTotalCount"] == len(findings)
    assert row["sourceFindingsTruncated"] is True
    assert len(row["sourceFindings"]) == limit


def test_receipt_marks_a_short_list_untruncated_and_declares_the_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tools.verify_atlas_source_fidelity as verifier

    fixture = Fixture(tmp_path)
    fixture.write_publisher()
    fixture.write_pack()
    monkeypatch.setattr(verifier, "SOURCES", (fixture.spec,))
    output = tmp_path / "receipt.json"
    verifier.main(
        [
            "--distribution",
            str(fixture.distribution),
            "--source-root",
            str(fixture.source_root),
            "--output",
            str(output),
            "--minimum-label-sample",
            "1",
        ]
    )

    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert receipt["receiptLimits"]["perCheckListLimit"] == verifier.RECEIPT_LIST_LIMIT
    for row in receipt["results"]:
        assert row["failuresTruncated"] is False
        assert row["failuresTotalCount"] == len(row["failures"])
        assert row["failuresDigest"].startswith("sha256:")


# --------------------------------------------------------------------------------------
# Reading a zipped publisher distribution
# --------------------------------------------------------------------------------------


def test_a_zipped_publisher_distribution_is_read_from_the_archive(tmp_path: Path) -> None:
    """EuroVoc ships its SKOS core inside a zip; the reader must not require extraction."""
    fixture = Fixture(tmp_path)
    fixture.write_pack()
    archive = fixture.source_root / "example.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("inner.ttl", publisher_turtle())
    fixture.pin_input("example.zip", zip_member="inner.ttl")
    assert failed(fixture.run()) == set()


def test_checks_are_pure_functions_of_one_context() -> None:
    """The registry must stay a flat tuple of uniform callables, so order is report order."""
    from tools.verify_atlas_source_fidelity import _CHECKS

    assert len(_CHECKS) == len(CHECK_NAMES)
    assert all(isinstance(check, Callable) for check in _CHECKS)


def test_one_malformed_source_does_not_stop_a_valid_source(suite: Fixture) -> None:
    bad_path = suite.source_root / "bad.ttl"
    bad_path.write_text("this is not Turtle {", encoding="utf-8")
    payload = bad_path.read_bytes()
    bad_spec = replace(
        suite.spec,
        name="bad-source",
        inputs=(
            SourcePin(
                "bad.ttl",
                "sha256:" + hashlib.sha256(payload).hexdigest(),
                len(payload),
            ),
        ),
    )

    results = verify(
        suite.distribution,
        suite.source_root,
        Expectations(minimum_label_sample=1),
        (bad_spec, suite.spec),
    )

    load_errors = result(results, "load-errors")
    assert not load_errors.passed
    assert any("bad-source" in failure and "bad.ttl" in failure for failure in load_errors.failures)
    label_check = result(results, "label-fidelity")
    assert not label_check.passed
    assert label_check.summary.startswith("5 Atlas labels compared")
    assert any("not evaluated" in failure and "bad-source" in failure for failure in label_check.failures)


def test_invalid_subset_does_not_stop_a_later_source(suite: Fixture) -> None:
    invalid = replace(suite.spec, name="invalid-subset", subset="not-supported")
    results = verify(
        suite.distribution,
        suite.source_root,
        Expectations(minimum_label_sample=1),
        (invalid, suite.spec),
    )
    load_errors = result(results, "load-errors")
    assert any("invalid-subset" in failure and "not-supported" in failure for failure in load_errors.failures)
    label_check = result(results, "label-fidelity")
    assert not label_check.passed
    assert label_check.summary.startswith("5 Atlas labels compared")
    assert any("not evaluated" in failure and "invalid-subset" in failure for failure in label_check.failures)


def test_all_malformed_publisher_inputs_are_reported(suite: Fixture) -> None:
    pins: list[SourcePin] = []
    for filename in ("bad-one.ttl", "bad-two.ttl"):
        path = suite.source_root / filename
        path.write_text("@prefix broken", encoding="utf-8")
        payload = path.read_bytes()
        pins.append(SourcePin(filename, "sha256:" + hashlib.sha256(payload).hexdigest(), len(payload)))
    spec = replace(suite.spec, name="two-bad-inputs", inputs=tuple(pins))

    load_errors = result(
        verify(
            suite.distribution,
            suite.source_root,
            Expectations(minimum_label_sample=1),
            (spec,),
        ),
        "load-errors",
    )

    assert any("bad-one.ttl" in failure and "bad-two.ttl" in failure for failure in load_errors.failures)


def test_one_malformed_atlas_pack_does_not_stop_the_other_packs(suite: Fixture) -> None:
    bad_pack = suite.distribution / "packs" / "sources" / "example" / "bad.nq.zst"
    bad_pack.write_bytes(b"not zstandard data")
    summary_path = suite.distribution / "atlas-construction-summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["releases"][0]["rdfPacks"].insert(0, {"path": "packs/sources/example/bad.nq.zst"})
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    results = suite.run()

    graph = result(results, "graph-structure")
    assert not graph.passed
    assert any("bad.nq.zst" in failure and "could not be read" in failure for failure in graph.failures)
    assert result(results, "concept-traceability").passed


def test_publisher_failure_does_not_hide_atlas_pack_failure(suite: Fixture) -> None:
    suite.publisher_path.write_text("@prefix broken", encoding="utf-8")
    suite.pin_input("example.ttl")
    suite.pack_path.write_bytes(b"not zstandard data")

    results = suite.run()

    load_errors = result(results, "load-errors")
    graph = result(results, "graph-structure")
    assert any("publisher inputs could not be read" in failure for failure in load_errors.failures)
    assert any("could not be read" in failure for failure in graph.failures)


def test_all_malformed_lines_in_one_pack_are_reported(suite: Fixture) -> None:
    lines = ["<urn:first> <urn:p> <urn:o>", "<urn:second> <urn:p> <urn:o>", *atlas_pack_lines()]
    suite.write_pack_lines(lines)

    graph = result(suite.run(), "graph-structure")

    assert any("all.nq.zst:1" in failure for failure in graph.failures)
    assert any("all.nq.zst:2" in failure for failure in graph.failures)


def test_invalid_native_payload_is_a_structural_error(suite: Fixture) -> None:
    lines = atlas_pack_lines()
    lines.append(_quad("urn:ref:atlas-source-record:c1", f"{ATLAS}nativePayload", "{broken", literal=True))
    suite.write_pack_lines(lines)
    graph = result(suite.run(), "graph-structure")
    assert any("invalid atlas:nativePayload JSON" in failure for failure in graph.failures)


def test_incomplete_reification_is_a_structural_error(suite: Fixture) -> None:
    lines = atlas_pack_lines()
    lines.append(
        _quad(
            "urn:ref:atlas-assertion:incomplete",
            "http://www.w3.org/1999/02/22-rdf-syntax-ns#subject",
            f"{EX}c1",
        )
    )
    suite.write_pack_lines(lines)
    graph = result(suite.run(), "graph-structure")
    assert any("incomplete" in failure and "rdf:predicate" in failure for failure in graph.failures)


def test_duplicate_serialized_quad_does_not_change_the_rdf_graph(suite: Fixture) -> None:
    lines = atlas_pack_lines()
    lines.append(lines[0])
    suite.write_pack_lines(lines)
    graph = result(suite.run(), "graph-structure")
    assert graph.passed


def test_run_checks_converts_an_exception_and_continues() -> None:
    calls: list[str] = []

    def broken(_context: object) -> CheckResult:
        calls.append("broken")
        raise RuntimeError("deliberate check failure")

    def later(_context: object) -> CheckResult:
        calls.append("later")
        return CheckResult("later", True, "continued")

    results = run_checks(object(), (broken, later))  # type: ignore[arg-type]

    assert calls == ["broken", "later"]
    assert results[0].name == "broken"
    assert not results[0].passed
    assert results[0].failures == ["RuntimeError: deliberate check failure"]
    assert results[1].passed


# --------------------------------------------------------------------------------------
# rkaf evidence bindings: Atlas representation structure, not publisher claims
# --------------------------------------------------------------------------------------

RKAF = "https://rulespec.org/ns/v1#"


def _evidence_binding_lines(node: str = "urn:ref:atlas-evidence:1") -> list[str]:
    """Render one Atlas-minted evidence record exactly as the builder writes it."""
    return [
        _quad(node, f"{RDF}type", f"{RKAF}EvidenceBinding"),
        _quad(node, f"{RKAF}bindsAssertion", "urn:ref:atlas-assertion:0"),
        _quad(node, f"{RKAF}attestor", "urn:ref:actor:atlas-3-source-native-import"),
        _quad(node, f"{RKAF}attestorKind", f"{RKAF}automatedParser"),
        _quad(node, f"{RKAF}decision", f"{RKAF}approved"),
        _quad(node, f"{RKAF}epistemicBasis", f"{RKAF}sourceExplicit"),
        _quad(node, f"{ATLAS}contentDigest", "sha256:" + "a" * 64, literal=True),
        _plain_literal_quad(node, f"{RKAF}attestedAt", "2025-04-01T00:00:00+00:00"),
    ]


def test_source_claim_coverage_ignores_an_rkaf_evidence_binding(suite: Fixture) -> None:
    lines = atlas_pack_lines()
    lines.extend(_evidence_binding_lines())
    suite.write_pack_lines(lines)

    coverage = result(suite.run(), "source-claim-coverage")

    assert coverage.passed, coverage.failures


def test_source_claim_coverage_still_reports_an_rkaf_claim_on_an_unknown_subject(
    suite: Fixture,
) -> None:
    lines = atlas_pack_lines()
    lines.append(_quad("urn:ref:atlas-evidence:ghost", f"{RKAF}decision", f"{RKAF}approved"))
    suite.write_pack_lines(lines)

    coverage = result(suite.run(), "source-claim-coverage")

    assert not coverage.passed
    assert any(
        "urn:ref:atlas-evidence:ghost" in failure and f"{RKAF}decision" in failure
        for failure in coverage.failures
    )


def test_source_claim_coverage_reports_an_rkaf_claim_planted_on_a_publisher_concept(
    suite: Fixture,
) -> None:
    lines = atlas_pack_lines()
    lines.append(_quad(f"{EX}c1", f"{RKAF}decision", f"{RKAF}approved"))
    suite.write_pack_lines(lines)

    coverage = result(suite.run(), "source-claim-coverage")

    assert not coverage.passed
    assert any(
        f"{EX}c1" in failure and f"{RKAF}decision" in failure
        for failure in coverage.failures
    )


# --------------------------------------------------------------------------------------
# --only: a scoped run reports what it did not evaluate, and never counts it proven
# --------------------------------------------------------------------------------------


def _declare_second_unit(suite: Fixture) -> SourceSpec:
    """Add one more construction unit, its pack, and the comparison that owns it."""
    relative = "sources/second/all.nq.zst"
    pack_path = suite.distribution / "packs" / relative
    pack_path.parent.mkdir(parents=True, exist_ok=True)
    payload = ("\n".join(atlas_pack_lines()) + "\n").encode("utf-8")
    transport = zstd.compress(payload)
    pack_path.write_bytes(transport)

    manifest_path = suite.distribution / "atlas-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["packs"].append(
        {
            "path": f"packs/{relative}",
            "transport": {
                "byteLength": len(transport),
                "digest": "sha256:" + hashlib.sha256(transport).hexdigest(),
            },
        }
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    summary_path = suite.distribution / "atlas-construction-summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    pin = suite.spec.inputs[0]
    summary["releases"].append(
        {
            "key": "second",
            "kind": "sourceRelease",
            "inputs": [
                {
                    "path": pin.path,
                    "sha256": pin.sha256,
                    "byteLength": pin.byte_length,
                    "role": "publisherSource",
                    "sourceIri": pin.source_iri,
                }
            ],
            "rdfPacks": [{"path": f"packs/{relative}"}],
            "recordCounts": {"resources": 3},
        }
    )
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    return replace(suite.spec, name="second", release_keys=("second",))


def test_scoped_out_unit_is_reported_as_not_evaluated_rather_than_uncovered(
    suite: Fixture,
) -> None:
    second = _declare_second_unit(suite)

    results = verify(
        suite.distribution,
        suite.source_root,
        Expectations(minimum_label_sample=1),
        (suite.spec,),
        (second,),
    )
    coverage = result(results, "distribution-coverage")

    assert coverage.passed, coverage.failures
    assert "not evaluated (scoped out)" in coverage.summary


def test_scoped_run_still_fails_on_a_unit_no_declared_comparison_owns(
    suite: Fixture,
) -> None:
    second = _declare_second_unit(suite)
    orphan = replace(second, name="unowned", release_keys=("unowned",))

    results = verify(
        suite.distribution,
        suite.source_root,
        Expectations(minimum_label_sample=1),
        (suite.spec,),
        (orphan,),
    )
    coverage = result(results, "distribution-coverage")

    assert not coverage.passed
    assert any(
        "second: no independent publisher comparison was performed" in failure
        for failure in coverage.failures
    )


def test_scoped_run_keeps_source_claim_coverage_failing_closed(suite: Fixture) -> None:
    second = _declare_second_unit(suite)
    lines = atlas_pack_lines()
    lines.append(_quad(f"{EX}ghost", f"{SKOS}related", f"{EX}c1"))
    suite.write_pack_lines(lines)
    # write_pack_lines rewrites the manifest, so re-declare the second unit's pack.
    second = _declare_second_unit(suite)

    results = verify(
        suite.distribution,
        suite.source_root,
        Expectations(minimum_label_sample=1),
        (suite.spec,),
        (second,),
    )
    coverage = result(results, "source-claim-coverage")

    assert not coverage.passed
    assert any(f"{EX}ghost" in failure for failure in coverage.failures)


def test_scoped_configuration_review_still_sees_every_declared_comparison(
    suite: Fixture,
) -> None:
    clash = replace(suite.spec, name="second")

    results = verify(
        suite.distribution,
        suite.source_root,
        Expectations(minimum_label_sample=1),
        (suite.spec,),
        (clash,),
    )
    configuration = result(results, "configuration")

    assert not configuration.passed
    assert any(
        "comparison ownership must be unique" in failure
        for failure in configuration.failures
    )


def test_only_selection_rejects_an_undeclared_comparison_name() -> None:
    from tools.verify_atlas_source_fidelity import SOURCES, select_scope

    with pytest.raises(ValueError, match="unknown comparison name"):
        select_scope(("no-such-source",), SOURCES)


def test_only_selection_splits_the_registry_without_losing_a_comparison() -> None:
    from tools.verify_atlas_source_fidelity import SOURCES, select_scope

    selected, scoped_out = select_scope(("elsst-r6",), SOURCES)

    assert [spec.name for spec in selected] == ["elsst-r6"]
    assert len(selected) + len(scoped_out) == len(SOURCES)
    assert "elsst-r6" not in {spec.name for spec in scoped_out}


def test_empty_only_selection_runs_the_whole_registry() -> None:
    from tools.verify_atlas_source_fidelity import SOURCES, select_scope

    selected, scoped_out = select_scope((), SOURCES)

    assert selected == SOURCES
    assert scoped_out == ()


# --------------------------------------------------------------------------------------
# source-extract: a non-RDF publisher artifact compared through its checked extract
# --------------------------------------------------------------------------------------

EXTRACT_SOURCE_IRI = "https://example.gov/thesaurus-2025.pdf"
EXTRACT_READER = "federal-register-thesaurus-2025-styled-pdf-v1/1.0"
EXTRACT_TERMS = {
    "ex-concept-0001": ("ex-entry-0001", "Airspace", ("Air space",)),
    "ex-concept-0002": ("ex-entry-0002", "Migratory birds", ()),
}


def _extract_payload(
    *,
    publisher_digest: str,
    labels: dict[str, str] | None = None,
    drop_relation: bool = False,
) -> bytes:
    """Render a checked source extract in the exact shape the reader accepts."""
    overrides = labels or {}
    official = []
    variants = []
    for ordinal, (concept_id, (entry_id, label, alts)) in enumerate(
        EXTRACT_TERMS.items(), start=1
    ):
        official.append(
            {
                "concept_id": concept_id,
                "entry_id": entry_id,
                "label": overrides.get(concept_id, label),
                "locator": {
                    "pdf_page": 4 + ordinal,
                    "printed_page": 1 + ordinal,
                    "source_ordinal": ordinal,
                },
            }
        )
        for alt_ordinal, alt in enumerate(alts, start=1):
            variants.append(
                {
                    "variant_id": f"ex-variant-{ordinal}{alt_ordinal}",
                    "label": alt,
                    "resolution_status": "recognizedVariant",
                    "target_concept_ids": [concept_id],
                    "redirect_ids": [],
                    "locator": {
                        "pdf_page": 4 + ordinal,
                        "printed_page": 1 + ordinal,
                        "source_ordinal": 100 + ordinal,
                    },
                }
            )
    variants.append(
        {
            "variant_id": "ex-variant-99",
            "label": "Birds",
            "resolution_status": "ambiguous",
            "target_concept_ids": ["ex-concept-0001", "ex-concept-0002"],
            "redirect_ids": [],
            "locator": {"pdf_page": 9, "printed_page": 6, "source_ordinal": 200},
        }
    )
    related = [
        {
            "relation_id": "ex-related-0002",
            "source_concept_id": "ex-concept-0001",
            "raw_target_label": "Ghosts",
            "target_concept_id": None,
            "resolution_status": "unresolved",
            "locator": {"pdf_page": 6, "printed_page": 3, "source_ordinal": 301},
        }
    ]
    if not drop_relation:
        related.insert(
            0,
            {
                "relation_id": "ex-related-0001",
                "source_concept_id": "ex-concept-0001",
                "raw_target_label": "Migratory birds",
                "target_concept_id": "ex-concept-0002",
                "resolution_status": "resolved",
                "locator": {"pdf_page": 5, "printed_page": 2, "source_ordinal": 300},
            },
        )
    payload = {
        "schemaVersion": "1.0",
        "parserVersion": "federal-register-thesaurus-2025-styled-pdf-v1",
        "source": {
            "id": EXTRACT_SOURCE_IRI,
            "issued": "2025-04-01",
            "sha256": publisher_digest,
            "byteLength": len(b"styled pdf bytes"),
            "pageCount": 180,
        },
        "counts": {"official_terms": len(official)},
        "officialTerms": official,
        "variants": variants,
        "variantRedirects": [],
        "relatedReferences": related,
        "suggestedOpenTermPatterns": [],
        "unresolvedReferences": [],
        "indexAnomalies": [],
    }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def _extract_pack_lines(
    *,
    labels: dict[str, str] | None = None,
    publisher_digest: str,
    extra_relations: Sequence[tuple[str, str, str]] = (),
    locator_override: dict[str, dict[str, int]] | None = None,
) -> list[str]:
    """Render what the Atlas asserts about the synthetic non-RDF release."""
    overrides = labels or {}
    locator_override = locator_override or {}
    lines = [
        _quad(EXTRACT_SOURCE_IRI, f"{RDF}type", f"{ATLAS}SourceRelease"),
        _plain_literal_quad(EXTRACT_SOURCE_IRI, f"{ATLAS}sourceDigest", publisher_digest),
    ]
    relations: list[tuple[str, str, str]] = [
        (
            "urn:ref:source-concept:v2:example:1",
            f"{SKOS}related",
            "urn:ref:source-concept:v2:example:2",
        ),
        *extra_relations,
    ]
    for ordinal, (concept_id, (entry_id, label, alts)) in enumerate(
        EXTRACT_TERMS.items(), start=1
    ):
        resource = f"urn:ref:source-concept:v2:example:{ordinal}"
        record = f"urn:ref:atlas-source-record:{ordinal}"
        lines.extend(
            [
                _quad(resource, f"{RDF}type", f"{SKOS}Concept"),
                _quad(resource, f"{RDF}type", f"{ATLAS}SubjectConcept"),
                _quad(record, f"{RDF}type", f"{ATLAS}SourceRecord"),
                _quad(record, f"{ATLAS}representsResource", resource),
                _quad(
                    record,
                    f"{ATLAS}nativePayload",
                    json.dumps(
                        {
                            "pdfLocator": locator_override.get(
                                concept_id,
                                {
                                    "pdf_page": 4 + ordinal,
                                    "printed_page": 1 + ordinal,
                                    "source_ordinal": ordinal,
                                },
                            ),
                            "sourceLocalConceptId": concept_id,
                            "sourceLocalEntryId": entry_id,
                        },
                        separators=(",", ":"),
                    ),
                    literal=True,
                ),
            ]
        )
        pref_node = f"urn:ref:atlas-label:{ordinal}-pref"
        lines.append(_quad(resource, f"{SKOSXL}prefLabel", pref_node))
        lines.append(
            _quad(
                pref_node,
                f"{SKOSXL}literalForm",
                overrides.get(concept_id, label),
                literal=True,
            )
        )
        for alt_ordinal, alt in enumerate(alts, start=1):
            alt_node = f"urn:ref:atlas-label:{ordinal}-alt-{alt_ordinal}"
            lines.append(_quad(resource, f"{SKOSXL}altLabel", alt_node))
            lines.append(_quad(alt_node, f"{SKOSXL}literalForm", alt, literal=True))
    for index, (subject, predicate, obj) in enumerate(relations):
        assertion = f"urn:ref:atlas-assertion:{index}"
        lines.append(_quad(assertion, f"{RDF}type", f"{ATLAS}RelationAssertion"))
        lines.append(_quad(assertion, f"{RDF}subject", subject))
        lines.append(_quad(assertion, f"{RDF}predicate", predicate))
        lines.append(_quad(assertion, f"{RDF}object", obj))
    return lines


class ExtractFixture:
    """A pinned non-RDF artifact, its checked extract, and the Atlas pack for both."""

    def __init__(self, root: Path) -> None:
        from tools.verify_atlas_source_fidelity import SourceExtractSelector

        self.selector_type = SourceExtractSelector
        self.root = root
        self.distribution = root / "distribution"
        self.source_root = root / "sources"
        (self.distribution / "packs" / "sources" / "extract-example").mkdir(parents=True)
        self.source_root.mkdir(parents=True)
        artifact = b"styled pdf bytes"
        (self.source_root / "thesaurus.pdf").write_bytes(artifact)
        self.publisher_digest = "sha256:" + hashlib.sha256(artifact).hexdigest()
        self.publisher_pin = SourcePin(
            path="thesaurus.pdf",
            sha256=self.publisher_digest,
            byte_length=len(artifact),
            fmt="pdf",
            role="publisherSource",
            source_iri=EXTRACT_SOURCE_IRI,
        )
        self.write_extract(_extract_payload(publisher_digest=self.publisher_digest))
        self.write_pack_lines(
            _extract_pack_lines(publisher_digest=self.publisher_digest)
        )
        (self.distribution / "atlas-construction-summary.json").write_text(
            json.dumps(
                {
                    "releases": [
                        {
                            "key": "extract-example",
                            "kind": "sourceRelease",
                            "inputs": [
                                {
                                    "path": "thesaurus.pdf",
                                    "sha256": self.publisher_digest,
                                    "byteLength": len(artifact),
                                    "role": "publisherSource",
                                    "sourceIri": EXTRACT_SOURCE_IRI,
                                }
                            ],
                            "rdfPacks": [
                                {"path": "packs/sources/extract-example/all.nq.zst"}
                            ],
                            "recordCounts": {"resources": 2},
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

    def write_extract(self, payload: bytes) -> None:
        (self.source_root / "extract.json").write_bytes(payload)
        self.extract_pin = SourcePin(
            path="extract.json",
            sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
            byte_length=len(payload),
            fmt="json",
            role="repositoryCheckedSourceExtract",
            source_iri=EXTRACT_SOURCE_IRI,
        )

    def write_pack_lines(self, lines: Sequence[str]) -> None:
        payload = ("\n".join(lines) + "\n").encode("utf-8")
        transport = zstd.compress(payload)
        pack = self.distribution / "packs" / "sources" / "extract-example" / "all.nq.zst"
        pack.write_bytes(transport)
        (self.distribution / "atlas-manifest.json").write_text(
            json.dumps(
                {
                    "packs": [
                        {
                            "path": "packs/sources/extract-example/all.nq.zst",
                            "transport": {
                                "byteLength": len(transport),
                                "digest": "sha256:"
                                + hashlib.sha256(transport).hexdigest(),
                            },
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

    @property
    def spec(self) -> SourceSpec:
        return SourceSpec(
            name="extract-example",
            kind="source-extract",
            release_keys=("extract-example",),
            inputs=(self.publisher_pin,),
            source_extract=self.selector_type(
                reader=EXTRACT_READER,
                extract=self.extract_pin,
                source_release_iri=EXTRACT_SOURCE_IRI,
                label_language="en",
                relation_predicate=f"{SKOS}related",
            ),
        )

    def run(self) -> list:
        return verify(
            self.distribution,
            self.source_root,
            Expectations(minimum_label_sample=1),
            (self.spec,),
        )


@pytest.fixture
def extract_suite(tmp_path: Path) -> ExtractFixture:
    """A faithful pair: the Atlas says exactly what the checked extract records."""
    return ExtractFixture(tmp_path)


def test_source_extract_pair_passes_every_check(extract_suite: ExtractFixture) -> None:
    results = extract_suite.run()
    assert failed(results) == set(), [
        (item.name, item.failures) for item in results if not item.passed
    ]


def test_source_extract_fires_when_a_preferred_label_is_rewritten(
    extract_suite: ExtractFixture,
) -> None:
    extract_suite.write_pack_lines(
        _extract_pack_lines(
            publisher_digest=extract_suite.publisher_digest,
            labels={"ex-concept-0001": "airspace"},
        )
    )

    check = result(extract_suite.run(), "source-extract-fidelity")

    assert not check.passed
    assert any(
        "ex-concept-0001 preferred label differs" in failure for failure in check.failures
    )


def test_source_extract_fires_when_an_unresolved_relation_is_asserted(
    extract_suite: ExtractFixture,
) -> None:
    extract_suite.write_extract(
        _extract_payload(
            publisher_digest=extract_suite.publisher_digest,
            drop_relation=True,
        )
    )

    check = result(extract_suite.run(), "source-extract-fidelity")

    assert not check.passed
    assert any(
        "does not record as resolved" in failure for failure in check.failures
    )


def test_source_extract_fires_when_a_recorded_relation_is_dropped(
    extract_suite: ExtractFixture,
) -> None:
    lines = [
        line
        for line in _extract_pack_lines(
            publisher_digest=extract_suite.publisher_digest
        )
        if "urn:ref:atlas-assertion:0" not in line
    ]
    extract_suite.write_pack_lines(lines)

    check = result(extract_suite.run(), "source-extract-fidelity")

    assert not check.passed
    assert any("is not asserted by Atlas" in failure for failure in check.failures)


def test_source_extract_fires_when_the_source_locator_is_rewritten(
    extract_suite: ExtractFixture,
) -> None:
    extract_suite.write_pack_lines(
        _extract_pack_lines(
            publisher_digest=extract_suite.publisher_digest,
            locator_override={
                "ex-concept-0001": {
                    "pdf_page": 999,
                    "printed_page": 2,
                    "source_ordinal": 1,
                }
            },
        )
    )

    check = result(extract_suite.run(), "source-extract-fidelity")

    assert not check.passed
    assert any("source locator differs" in failure for failure in check.failures)


def test_source_extract_fires_when_the_release_digest_is_not_the_pinned_artifact(
    extract_suite: ExtractFixture,
) -> None:
    extract_suite.write_pack_lines(
        _extract_pack_lines(publisher_digest="sha256:" + "b" * 64)
    )

    check = result(extract_suite.run(), "source-extract-fidelity")

    assert not check.passed
    assert any(
        "not the authenticated publisher bytes" in failure for failure in check.failures
    )


def test_source_extract_fires_when_the_extract_binds_other_publisher_bytes(
    extract_suite: ExtractFixture,
) -> None:
    extract_suite.write_extract(
        _extract_payload(publisher_digest="sha256:" + "c" * 64)
    )

    check = result(extract_suite.run(), "source-extract-fidelity")

    assert not check.passed
    assert any(
        "binds a different publisher artifact sha256" in failure
        for failure in check.failures
    )


def test_source_extract_fails_closed_when_the_extract_is_not_authenticated(
    extract_suite: ExtractFixture,
) -> None:
    spec = extract_suite.spec
    assert spec.source_extract is not None
    tampered = replace(
        spec,
        source_extract=replace(
            spec.source_extract,
            extract=replace(spec.source_extract.extract, sha256="sha256:" + "d" * 64),
        ),
    )
    results = verify(
        extract_suite.distribution,
        extract_suite.source_root,
        Expectations(minimum_label_sample=1),
        (tampered,),
    )
    check = result(results, "source-extract-fidelity")

    assert not check.passed
    assert any("was not authenticated" in failure for failure in check.failures)


def test_source_extract_fails_closed_on_an_atlas_concept_the_extract_lacks(
    extract_suite: ExtractFixture,
) -> None:
    lines = _extract_pack_lines(publisher_digest=extract_suite.publisher_digest)
    lines.extend(
        [
            _quad("urn:ref:source-concept:v2:example:9", f"{RDF}type", f"{SKOS}Concept"),
            _quad("urn:ref:atlas-source-record:9", f"{RDF}type", f"{ATLAS}SourceRecord"),
            _quad(
                "urn:ref:atlas-source-record:9",
                f"{ATLAS}representsResource",
                "urn:ref:source-concept:v2:example:9",
            ),
            _quad(
                "urn:ref:atlas-source-record:9",
                f"{ATLAS}nativePayload",
                json.dumps(
                    {
                        "pdfLocator": {
                            "pdf_page": 9,
                            "printed_page": 6,
                            "source_ordinal": 9,
                        },
                        "sourceLocalConceptId": "ex-concept-9999",
                        "sourceLocalEntryId": "ex-entry-9999",
                    },
                    separators=(",", ":"),
                ),
                literal=True,
            ),
        ]
    )
    extract_suite.write_pack_lines(lines)

    check = result(extract_suite.run(), "source-extract-fidelity")

    assert not check.passed
    assert any(
        "which the checked source extract does not contain" in failure
        for failure in check.failures
    )
