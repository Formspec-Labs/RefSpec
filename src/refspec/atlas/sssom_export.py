"""Deterministic SSSOM TSV export for a sealed crosswalk bundle.

The bundle is the evidence record; this module is a projection of it into the
one interchange format other mapping tools already read.  Nothing here decides
which mappings are real — :meth:`CrosswalkBundle.qualified` does that, and this
module only renders what it returns.

Three requirements come from measured behaviour of two external tools, not from
taste (``output/oak-fast-spike-2026-08-03`` and
``output/semra-fast-spike-2026-08-03``):

Row-level ``mapping_source``
    SeMRA fused two mapping sets that differed only in set-level metadata down
    to a single evidence record.  Provenance that lives in the header is
    provenance a consumer can lose, so every row carries the bundle identifier
    in full.  A reader that keeps only the TSV body still knows which sealed
    bundle each mapping came from, which a header-dependent CURIE could not
    survive.

Compact CURIEs with declared prefixes
    A strict SSSOM reader returned zero mappings for a file that used full IRIs
    with no ``curie_map``, and treated RefSpec's multi-colon ``urn:ref:...``
    identifiers as malformed CURIEs.  Every concept, predicate, justification,
    and release this module writes is therefore a single-colon CURIE whose
    prefix is declared in the header.  The two columns that name a sealed
    RefSpec record — ``mapping_source`` and ``see_also`` — stay in full, and the
    header declares their URI scheme (``urn: "urn:"``) so that a reader which
    splits on the first colon still expands them, byte for byte, to what they
    already say.  Every cell in the file resolves through the header alone.

Byte-determinism
    OAK's exporter minted a random ``mapping_set_id``, so two runs over one
    input differed.  Here the set identifier is derived from the bundle digest,
    rows are sorted, and prefixes are assigned in sorted order, so the same
    bundle and the same ``qualified_only`` always produce the same bytes.

Prefix names are edition-scoped on purpose.  The Bioregistry publishes an
``elsst`` prefix whose primary expansion is edition 3, so a downstream tool that
normalises through it would silently re-expand our R6 concepts to R5-era IRIs.
``elsst6`` cannot be mistaken for another edition, and ``frt25`` already carried
its edition.  Prefixes RefSpec mints for its own sealed records are compound
names rather than vocabulary short names, so a reader without our ``curie_map``
fails to resolve them instead of resolving them to something else.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from refspec import binding

from .model import CrosswalkBundle, VocabularyAtlasError

FORMAT_ID = "refspec-vocabulary-atlas-crosswalk-sssom-tsv-1.0"

#: Where a mapping set exported from a bundle is named.  The bundle digest is
#: the only variable part, which is what makes repeat exports byte-identical.
MAPPING_SET_NAMESPACE = "https://refspec.org/id/vocabulary-atlas-crosswalk/"

#: SSSOM's own value for "the license was not stated", which is the honest
#: answer for a bundle that does not carry one.
UNSPECIFIED_LICENSE = "https://w3id.org/sssom/license/unspecified"

_SEMAPV = "https://w3id.org/semapv/vocab/"

#: A qualified candidate passed the two-independent-machine gate, which is a
#: review of a proposed mapping and nothing narrower.  How the candidate was
#: generated is a separate fact and is reported in ``mapping_tool`` and
#: ``comment``.
REVIEWED_JUSTIFICATION = _SEMAPV + "MappingReview"

#: An unqualified candidate is a proposal.  Naming its generation method here
#: would assert a justification the bundle does not support.
UNREVIEWED_JUSTIFICATION = _SEMAPV + "UnspecifiedMatching"

#: Namespaces that get a stable, readable, edition-scoped name.  Every other
#: namespace is named ``ns1``, ``ns2``, ... in sorted order, so a bundle over
#: vocabularies this table has never heard of still exports compact CURIEs.
WELL_KNOWN_PREFIXES: Mapping[str, str] = {
    "http://www.w3.org/2004/02/skos/core#": "skos",
    "https://elsst.cessda.eu/id/": "elsstedition",
    "https://elsst.cessda.eu/id/6/": "elsst6",
    "https://w3id.org/semapv/vocab/": "semapv",
    "urn:ref:federal-register-thesaurus:2025-04-01:concept:": "frt25",
    "urn:ref:federal-register-thesaurus:2025-04-01:reference-resource-release:": "frt25release",
}

#: ``confidence`` is deliberately absent.  Both spikes flagged a fabricated
#: ``0.5`` default as an anti-pattern, and a bundle records verdicts, not
#: scores, so there is no honest number to write.
COLUMNS = (
    "subject_id",
    "subject_label",
    "predicate_id",
    "object_id",
    "object_label",
    "mapping_justification",
    "mapping_source",
    "subject_source",
    "object_source",
    "mapping_tool",
    "mapping_tool_version",
    "see_also",
    "comment",
)

#: Columns naming something a consumer resolves — a concept, a predicate, a
#: justification, a release.  These are compacted against ``curie_map``.
_ENTITY_COLUMNS = frozenset(
    {
        "subject_id",
        "predicate_id",
        "object_id",
        "mapping_justification",
        "subject_source",
        "object_source",
    }
)

#: Columns naming a sealed RefSpec record.  These carry the identifier in full
#: so a consumer that reads only the TSV body keeps the provenance, and the
#: header declares their scheme so they still expand as CURIEs.
_RECORD_COLUMNS = frozenset({"mapping_source", "see_also"})

_FORBIDDEN_CELL_CHARACTERS = ("\t", "\n", "\r")


class SssomExportError(VocabularyAtlasError):
    """The bundle cannot be projected into a lossless SSSOM table."""


def _split_iri(iri: str) -> tuple[str, str]:
    """Split an absolute IRI at its last separator into namespace and local name.

    A CURIE has exactly one colon, so the local name may not contain one.  An
    IRI that cannot be split that way is refused rather than written out as a
    malformed CURIE, which is the failure both spikes observed.
    """

    if "#" in iri:
        namespace, _, local = iri.rpartition("#")
        namespace += "#"
    elif iri.startswith("urn:"):
        namespace, _, local = iri.rpartition(":")
        namespace += ":"
    else:
        namespace, _, local = iri.rpartition("/")
        namespace += "/"
    if not local or namespace in {"#", ":", "/"}:
        raise SssomExportError(f"{iri!r} has no local name to compact")
    if ":" in local:
        raise SssomExportError(f"{iri!r} would compact to a multi-colon CURIE")
    return namespace, local


def _scheme(iri: str) -> tuple[str, str]:
    """Return the URI scheme of an identifier written out in full.

    Splitting a CURIE at its first colon makes ``urn:`` a prefix whose
    expansion returns the identifier unchanged, so declaring the scheme lets a
    strict reader resolve a full identifier without shortening it.
    """

    prefix, separator, _ = iri.partition(":")
    if not separator or not prefix:
        raise SssomExportError(f"{iri!r} has no URI scheme to declare")
    return prefix, prefix + ":"


@dataclass(frozen=True, slots=True)
class _Compactor:
    """A closed prefix map that resolves every identifier one export writes."""

    prefixes: Mapping[str, str]

    @classmethod
    def over(cls, compacted: Iterable[str], verbatim: Iterable[str] = ()) -> _Compactor:
        namespaces = {_split_iri(iri)[0] for iri in compacted}
        named = {
            namespace: WELL_KNOWN_PREFIXES[namespace]
            for namespace in namespaces
            if namespace in WELL_KNOWN_PREFIXES
        }
        unnamed = sorted(namespace for namespace in namespaces if namespace not in named)
        generated = {namespace: f"ns{index}" for index, namespace in enumerate(unnamed, start=1)}
        schemes = {expansion: prefix for prefix, expansion in map(_scheme, verbatim)}
        prefixes = {**named, **generated, **schemes}
        if len(set(prefixes.values())) != len(prefixes):
            raise SssomExportError("two namespaces claim one prefix")
        return cls(prefixes)

    def curie(self, iri: str) -> str:
        namespace, local = _split_iri(iri)
        return f"{self.prefixes[namespace]}:{local}"

    def curie_map(self) -> dict[str, str]:
        return {prefix: namespace for namespace, prefix in self.prefixes.items()}


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _label_index(content: Mapping[str, Any]) -> dict[str, str]:
    """Map a member IRI to its preferred label from one sealed input context.

    Two shapes are read because two producers write them: the qualification
    runner nests ``payload.source`` / ``payload.target`` concept blocks, and
    smaller sealed contexts carry flat ``sourceMember`` / ``sourceLabel`` pairs.
    A context that carries neither yields no label, and the row is written with
    an empty label rather than an invented one.
    """

    index: dict[str, str] = {}
    payload = content.get("payload")
    if isinstance(payload, Mapping):
        for side in ("source", "target"):
            block = payload.get(side)
            if isinstance(block, Mapping):
                member, label = _text(block.get("member")), _text(block.get("prefLabel"))
                if member and label:
                    index[member] = label
    for side in ("source", "target"):
        member, label = _text(content.get(f"{side}Member")), _text(content.get(f"{side}Label"))
        if member and label:
            index.setdefault(member, label)
    return index


def _generation_methods(
    candidate: Mapping[str, Any],
    artifacts: Mapping[str, Mapping[str, Any]],
) -> str:
    """Report how the candidate was proposed, from its own evidence artifacts."""

    methods = {
        _text(artifacts[reference["id"]]["content"].get("method"))
        for reference in candidate["evidence"]
        if reference["id"] in artifacts
    }
    return "; ".join(sorted(method for method in methods if method))


def _rows(bundle: CrosswalkBundle, *, qualified_only: bool) -> list[dict[str, str]]:
    # ``qualified`` verifies the bundle before it reads it, so a bundle that
    # does not close never reaches the table.
    qualified = frozenset(bundle.qualified())
    # Under v1 the proposal and the verdict are the same claim, so the proposal
    # is the honest predicate. Under v2 the judge answers a richer question, and
    # writing the proposal would publish `closeMatch` for a pair two machines
    # typed as `broadMatch` — a false predicate in an interoperability format.
    adjudicated = bundle.adjudicated_relations()
    record = bundle.to_dict()
    artifacts = {str(item["id"]): item for item in record["artifacts"]}
    contexts = {
        binding.canonical_sha256(item["content"]): item["content"]
        for item in record["artifacts"]
        if item["role"] == "inputContext"
    }

    rows: list[dict[str, str]] = []
    for candidate in record["mappingCandidates"]:
        identifier = str(candidate["id"])
        if qualified_only and identifier not in qualified:
            continue
        labels = _label_index(contexts.get(candidate["inputContextDigest"], {}))
        relation = adjudicated.get(identifier, candidate["proposedRelation"])
        # An adjudicated relation is a reviewed one whether or not the gate went
        # on to publish a mapping from it: `skos:relatedMatch` is what two
        # independent machines agreed the pair is. Deliberately no
        # `predicate_modifier` — SSSOM's only modifier negates the predicate
        # ("subject is NOT a predicate match to object"), which would assert the
        # opposite of the finding. The predicate itself carries the distinction,
        # and eligibility for search is a RefSpec fact SSSOM has no column for.
        reviewed = identifier in qualified or identifier in adjudicated
        rows.append(
            {
                "subject_id": candidate["sourceMember"],
                "subject_label": labels.get(candidate["sourceMember"], ""),
                "predicate_id": relation,
                "object_id": candidate["targetMember"],
                "object_label": labels.get(candidate["targetMember"], ""),
                "mapping_justification": (
                    REVIEWED_JUSTIFICATION if reviewed else UNREVIEWED_JUSTIFICATION
                ),
                "mapping_source": bundle.identifier,
                "subject_source": candidate["sourceRelease"],
                "object_source": candidate["targetRelease"],
                "mapping_tool": candidate["modelId"],
                "mapping_tool_version": candidate["modelVersion"],
                "see_also": identifier,
                "comment": _generation_methods(candidate, artifacts),
            }
        )
    return rows


def _cell(value: str, column: str) -> str:
    """Refuse a value that a tab-separated line cannot carry losslessly."""

    if any(character in value for character in _FORBIDDEN_CELL_CHARACTERS):
        raise SssomExportError(f"{column} value contains a tab, newline, or carriage return")
    return value


def _metadata_lines(metadata: Mapping[str, Any]) -> list[str]:
    """Render the commented YAML header with sorted keys and quoted scalars.

    JSON scalars are valid YAML, so quoting every value keeps a colon or a
    leading character inside a label from changing how the header parses.
    """

    lines: list[str] = []
    for key in sorted(metadata):
        value = metadata[key]
        if isinstance(value, Mapping):
            lines.append(f"# {key}:")
            lines.extend(f"#   {name}: {json.dumps(value[name])}" for name in sorted(value))
        else:
            lines.append(f"# {key}: {json.dumps(value)}")
    return lines


def _mapping_set_id(bundle: CrosswalkBundle, *, qualified_only: bool) -> str:
    digest = bundle.digest.removeprefix("sha256:")
    return MAPPING_SET_NAMESPACE + digest + ("/qualified" if qualified_only else "/all-candidates")


def sssom_text(bundle: CrosswalkBundle, *, qualified_only: bool = True) -> str:
    """Return the SSSOM TSV for one bundle, as the same bytes every time.

    With ``qualified_only`` the table holds exactly the candidates that passed
    the two-independent-machine gate.  Without it every candidate is exported,
    and the ones that did not qualify say so in ``mapping_justification``.
    """

    rows = _rows(bundle, qualified_only=qualified_only)
    compactor = _Compactor.over(
        (value for row in rows for column, value in row.items() if column in _ENTITY_COLUMNS),
        (value for row in rows for column, value in row.items() if column in _RECORD_COLUMNS),
    )
    rendered = sorted(
        (
            {
                column: _cell(compactor.curie(value) if column in _ENTITY_COLUMNS else value, column)
                for column, value in row.items()
            }
            for row in rows
        ),
        key=lambda row: (row["subject_id"], row["object_id"], row["see_also"]),
    )
    metadata = {
        "comment": (
            f"Exported from RefSpec vocabulary-atlas crosswalk bundle {bundle.identifier}, "
            f"sealed at {bundle.digest}."
        ),
        "curie_map": compactor.curie_map(),
        "license": UNSPECIFIED_LICENSE,
        "mapping_set_id": _mapping_set_id(bundle, qualified_only=qualified_only),
        "mapping_set_title": (
            "RefSpec vocabulary-atlas crosswalk"
            + (" (qualified mappings)" if qualified_only else " (all candidates)")
        ),
    }
    lines: Sequence[str] = [
        *_metadata_lines(metadata),
        "\t".join(COLUMNS),
        *("\t".join(row[column] for column in COLUMNS) for row in rendered),
    ]
    return "\n".join(lines) + "\n"


def write_sssom(bundle: CrosswalkBundle, path: Path | str, *, qualified_only: bool = True) -> Path:
    """Write :func:`sssom_text` to ``path`` and return it."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(sssom_text(bundle, qualified_only=qualified_only).encode("utf-8"))
    return target
