"""One-pass sample selection agrees with the copied per-subject scanner."""
from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from rdflib import Dataset, URIRef
from rdflib.exceptions import ParserError

from tools import generate_atlas_v3_full as generator

ATLAS_VALIDATE = generator.ATLAS_VALIDATE
CompactRecordRole = generator.CompactRecordRole
_json_restore_binary = generator._json_restore_binary
_json_safe_binary = generator._json_safe_binary

# Copied from the replaced production method; never import the old scanner.
def old_independent_row_for_subject(
    self,
    subject_id: str,
    role: CompactRecordRole,
) -> dict[str, Any]:
    """Re-derive one subject's Parquet row from its own asserted quads.

    The binding's `parquet_row_from_rdf` stays the comparand -- this only
    changes WHEN it runs, not what computes the expected side. Called for
    the at-most-five sampled positions per role, never per subject.
    `_construction_record_from_rdf` reads only (subject, predicate, ?), so
    a graph holding this subject's own quads is a sufficient input; a
    subject whose lines are absent is itself a finding, not a skip.
    """

    # Not only lines where this subject is the SUBJECT: a Label's role is
    # proved by its INBOUND triple (resource skosxl:prefLabel label), so
    # `_construction_record_from_rdf` calls graph.subjects(predicate,
    # subject) for that role. Match either position.
    needle = f"<{subject_id}>"
    lines: list[str] = []
    for path in self.sorted_rdf_paths.values():
        with path.open("r", encoding="utf-8", newline="") as rdf:
            for line in rdf:
                if needle in line:
                    lines.append(line)
    if not lines:
        raise ValueError(
            f"sampled {role.value} record {subject_id} has no asserted quads to re-derive from"
        )
    dataset = Dataset(default_union=True)
    try:
        ATLAS_VALIDATE._parse_nquads_preserving_lexical_forms(
            dataset,
            io.StringIO("".join(lines)),
        )
        # A subject's quads span role graphs -- a Label's type claim sits
        # in the projection graph, not the asserted one -- and the original
        # per-subject call received the whole constructed graph. Narrowing
        # to one role graph drops facts the row needs, so read the union.
        return _json_restore_binary(
            _json_safe_binary(
                ATLAS_VALIDATE.parquet_row_from_rdf(
                    dataset,
                    URIRef(subject_id),
                    role.value,
                )
            )
        )
    finally:
        dataset.close()



def outcome(call):
    try:
        return ("row", call())
    except (ValueError, ATLAS_VALIDATE.AtlasValidationError, ParserError) as error:
        return (type(error).__name__, str(error))


def spool_at(path):
    return SimpleNamespace(root=path.parent, sorted_rdf_paths={(None, None): path})


def new_rows(spool, subjects):
    return list(generator._StreamingGraphSpool._independent_rows_for_subjects(spool, subjects))


@pytest.mark.parametrize("mutation", [
    "clean", "missing-inbound", "duplicate-inbound", "missing-release",
    "uppercase-language", "nested-literal-needle", "predicate-needle",
    "graph-needle", "missing-subject", "unselected-malformed", "repeated-needle",
    "selected-malformed",
])
def test_selector_matches_old_rows_and_refusals(tmp_path, mutation):
    label = "urn:test:label"
    atlas = "https://refspec.org/ns/atlas/v3#"
    xl = "http://www.w3.org/2008/05/skos-xl#"
    lines = [
        f'<urn:test:resource> <{xl}prefLabel> <{label}> <urn:test:asserted> .\n',
        f'<{label}> <{xl}literalForm> "Real label"@en <urn:test:projection> .\n',
        f'<{label}> <{atlas}inRelease> <urn:test:release> <urn:test:asserted> .\n',
        f'<{label}> <{atlas}sourceRecord> <urn:test:record> <urn:test:asserted> .\n',
    ]
    if mutation == "missing-inbound":
        lines.pop(0)
    elif mutation == "duplicate-inbound":
        lines.append(lines[0].replace("urn:test:resource", "urn:test:other"))
    elif mutation == "missing-release":
        lines.pop(2)
    elif mutation == "uppercase-language":
        lines[1] = lines[1].replace("@en", "@EN")
    elif mutation == "nested-literal-needle":
        lines.append(f'<urn:test:other> <urn:test:note> "<<{label}>>" <urn:test:g> .\n')
    elif mutation == "predicate-needle":
        lines.append(f'<urn:test:other> <{label}> "value" <urn:test:g> .\n')
    elif mutation == "graph-needle":
        lines.append(f'<urn:test:other> <urn:test:note> "value" <{label}> .\n')
    elif mutation == "missing-subject":
        label = "urn:test:absent"
    elif mutation == "unselected-malformed":
        lines.append("not RDF and not selected\n")
    elif mutation == "selected-malformed":
        lines.append(f'<urn:test:other> <urn:test:note> "<<{label}>>" <urn:test:g> broken\n')
    elif mutation == "repeated-needle":
        lines.append(f'<urn:test:other> <urn:test:note> "<{label}> <{label}>" <urn:test:g> .\n')
    path = tmp_path / "sample.nq"
    path.write_text("".join(lines[::2]))
    other = tmp_path / "other.nq"
    other.write_text("".join(lines[1::2]))
    spool = SimpleNamespace(root=tmp_path, sorted_rdf_paths={0: path, 1: other})
    subjects = [(label, CompactRecordRole.LABEL)]
    old = outcome(lambda: [old_independent_row_for_subject(spool, *item) for item in subjects])
    new = outcome(lambda: new_rows(spool, subjects))
    assert new == old  # Frozen intentional divergences: none.
    assert (new[0] == "row") == (mutation not in {
        "missing-inbound", "duplicate-inbound", "missing-release", "uppercase-language", "missing-subject",
        "selected-malformed",
    })


@pytest.mark.reads_built_artifact
def test_retained_umthes_rows_agree_and_read_each_pack_once(tmp_path, monkeypatch):
    pack = Path(__file__).parents[1] / (
        "output/atlas-3.1-umthes-2026-09-27/distribution/packs/sources/"
        "umthes-gemet-endpoints-2026-08-15/all.nq.zst"
    )
    assert pack.is_file(), "required retained UMTHES pack is unavailable"
    # Keep complete subject groups from the beginning of the retained pack.
    # Raw context shows resource type, scheme, label links and provenance;
    # these are actual constructed resource rows, not publisher-only SKOS.
    lines, ids = [], []
    with generator.zstd.open(pack, "rt") as stream:
        for line in stream:
            subject = line.partition(" ")[0][1:-1]
            if not ids or subject != ids[-1]:
                if len(ids) == 45:
                    break
                ids.append(subject)
            lines.append(line)
    path = tmp_path / "retained.nq"
    path.write_text("".join(lines))
    spool = spool_at(path)
    subjects = [(identity, CompactRecordRole.RESOURCE) for identity in ids]
    expected = [old_independent_row_for_subject(spool, *item) for item in subjects]
    opened = []
    original = Path.open

    def counted_open(self, *args, **kwargs):
        if self == path:
            opened.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counted_open)
    assert new_rows(spool, subjects) == expected
    assert opened == [path]
    assert len(expected) == 45


def test_empty_samples_do_not_scan():
    assert new_rows(spool_at(Path("does-not-exist")), []) == []


@pytest.fixture
def high_fanout_releases(tmp_path):
    atlas = "https://refspec.org/ns/atlas/v3#"
    rdf_type = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
    subjects = [(f"urn:test:release:{i}", CompactRecordRole.RELEASE) for i in range(2)]
    path = tmp_path / "fanout.nq"
    with path.open("w") as stream:
        for subject, _role in subjects:
            for predicate, obj in (
                (rdf_type, f"<{atlas}SourceRelease>"),
                (atlas + "sourceIssued", '"2026-09-27"'),
                (atlas + "sourceDigest", '"sha256:' + "a" * 64 + '"'),
                (atlas + "sourceLocator", "<https://example.test/source>"),
            ):
                stream.write(f'<{subject}> <{predicate}> {obj} <urn:test:asserted> .\n')
            for index in range(1000):
                stream.write(f'<urn:test:member:{index}> <{atlas}inSourceRelease> <{subject}> <urn:test:asserted> .\n')
                stream.write(f'<{subject}> <http://www.w3.org/ns/prov#hadMember> <urn:test:member:{index}> <urn:test:asserted> .\n')
    return spool_at(path), subjects


def test_high_fanout_release_parity_uses_files_and_removes_scratch(high_fanout_releases, monkeypatch):
    spool, subjects = high_fanout_releases
    expected = [old_independent_row_for_subject(spool, *item) for item in subjects]
    original = ATLAS_VALIDATE._parse_nquads_preserving_lexical_forms
    streams = []

    def parse(dataset, source):
        assert not isinstance(source, io.StringIO)
        assert Path(source.name).is_file()
        streams.append(source)
        return original(dataset, source)

    monkeypatch.setattr(ATLAS_VALIDATE, "_parse_nquads_preserving_lexical_forms", parse)
    assert new_rows(spool, subjects) == expected
    assert len(streams) == len(subjects)
    assert all(stream.closed and not Path(stream.name).exists() for stream in streams)
    assert not list(spool.root.glob("parquet-samples-*"))


@pytest.mark.parametrize("failure", ["parser", "comparator", "consumer"])
def test_sample_scratch_cleanup_on_failure(high_fanout_releases, monkeypatch, failure):
    spool, subjects = high_fanout_releases
    streams = []
    original = ATLAS_VALIDATE._parse_nquads_preserving_lexical_forms

    def parse(dataset, source):
        streams.append(source)
        if failure == "parser":
            raise RuntimeError("injected parser failure")
        return original(dataset, source)

    def compare(*args):
        raise RuntimeError("injected comparator failure")

    monkeypatch.setattr(ATLAS_VALIDATE, "_parse_nquads_preserving_lexical_forms", parse)
    if failure == "comparator":
        monkeypatch.setattr(ATLAS_VALIDATE, "parquet_row_from_rdf", compare)
    with pytest.raises(RuntimeError, match="injected"):
        rows = new_rows(spool, subjects)
        assert rows
        # The caller can stop or fail without leaving live scratch resources.
        assert not list(spool.root.glob("parquet-samples-*"))
        raise RuntimeError("injected consumer failure")
    assert streams and all(stream.closed for stream in streams)
    assert not list(spool.root.glob("parquet-samples-*"))
