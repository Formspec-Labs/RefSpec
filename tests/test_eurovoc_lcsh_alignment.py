"""Exact-source tests for the official EuroVoc--LCSH alignment."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest
from rdflib.namespace import SKOS

from refspec.atlas import v3_registry_alignments as alignments
from refspec.registry.eurovoc_lcsh_alignment import (
    EUROVOC_4_20_METADATA_BYTE_LENGTH,
    EUROVOC_4_20_METADATA_FILENAME,
    EUROVOC_4_20_METADATA_SHA256,
    EUROVOC_4_24_METADATA_BYTE_LENGTH,
    EUROVOC_4_24_METADATA_FILENAME,
    EUROVOC_4_24_METADATA_SHA256,
    EUROVOC_LCSH_ALIGNMENT_BYTE_LENGTH,
    EUROVOC_LCSH_ALIGNMENT_FILENAME,
    EUROVOC_LCSH_ALIGNMENT_METADATA_BYTE_LENGTH,
    EUROVOC_LCSH_ALIGNMENT_METADATA_FILENAME,
    EUROVOC_LCSH_ALIGNMENT_METADATA_SHA256,
    EUROVOC_LCSH_ALIGNMENT_SHA256,
    EXPECTED_PREDICATE_COUNTS,
    EuroVocLcshAlignmentError,
    parse_eurovoc_lcsh_alignment,
    parse_eurovoc_lcsh_alignment_file,
    verify_eurovoc_4_24_metadata,
    verify_eurovoc_lcsh_release_metadata,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "output" / "registry-real-data-sources"
ALIGNMENT_PATH = SOURCE_ROOT / EUROVOC_LCSH_ALIGNMENT_FILENAME
METADATA_PATH = SOURCE_ROOT / EUROVOC_4_24_METADATA_FILENAME
ALIGNMENT_METADATA_PATH = SOURCE_ROOT / EUROVOC_LCSH_ALIGNMENT_METADATA_FILENAME
EUROVOC_4_20_METADATA_PATH = SOURCE_ROOT / EUROVOC_4_20_METADATA_FILENAME
HAS_OFFICIAL_SOURCES = all(
    path.is_file()
    for path in (
        ALIGNMENT_PATH,
        ALIGNMENT_METADATA_PATH,
        EUROVOC_4_20_METADATA_PATH,
        METADATA_PATH,
    )
)


def test_official_source_pins_are_fixed() -> None:
    assert EUROVOC_LCSH_ALIGNMENT_BYTE_LENGTH == 332_124
    assert EUROVOC_LCSH_ALIGNMENT_SHA256 == (
        "sha256:dbd6e610ff497c4a39a79924cf50dcf92d5f3e9ab316d58d83c460dba6fb4853"
    )
    assert EUROVOC_LCSH_ALIGNMENT_METADATA_BYTE_LENGTH == 8_157
    assert EUROVOC_LCSH_ALIGNMENT_METADATA_SHA256 == (
        "sha256:3792ef3e3ebb18a01c97aa9d7a34f177ed947dd68496b7497a5693f06257faa6"
    )
    assert EUROVOC_4_20_METADATA_BYTE_LENGTH == 14_093
    assert EUROVOC_4_20_METADATA_SHA256 == (
        "sha256:ee86254e0635b9e3ea51ae365153eecd81f0040cb4580d28401986639b0b895d"
    )
    assert EUROVOC_4_24_METADATA_BYTE_LENGTH == 36_011
    assert EUROVOC_4_24_METADATA_SHA256 == (
        "sha256:2c58402422f8588aada476f3516051e7fc980182130557a0d8c67497ffd8731d"
    )
    assert EXPECTED_PREDICATE_COUNTS == {
        str(SKOS.exactMatch): 1_904,
        str(SKOS.closeMatch): 99,
    }


@pytest.mark.skipif(not HAS_OFFICIAL_SOURCES, reason="official EuroVoc alignment sources are not cached")
def test_official_alignment_retains_every_direct_mapping_exactly_once() -> None:
    alignment = parse_eurovoc_lcsh_alignment_file(ALIGNMENT_PATH)

    assert alignment.source_sha256 == EUROVOC_LCSH_ALIGNMENT_SHA256
    assert alignment.source_bytes == EUROVOC_LCSH_ALIGNMENT_BYTE_LENGTH
    assert alignment.triple_count == 2_008
    assert len(alignment.mappings) == 2_003
    assert len(set(alignment.mappings)) == 2_003
    assert Counter(row.predicate_iri for row in alignment.mappings) == (
        EXPECTED_PREDICATE_COUNTS
    )
    assert len(alignment.eurovoc_concept_iris) == 1_829
    assert len(alignment.lcsh_concept_iris) == 1_966
    assert "http://eurovoc.europa.eu/100162" in alignment.eurovoc_concept_iris
    assert all(
        row.subject_iri.startswith("http://eurovoc.europa.eu/")
        and row.object_iri.startswith("http://id.loc.gov/authorities/subjects/")
        for row in alignment.mappings
    )


@pytest.mark.skipif(not HAS_OFFICIAL_SOURCES, reason="official EuroVoc alignment sources are not cached")
def test_current_eurovoc_metadata_confirms_both_lcsh_linksets() -> None:
    assert verify_eurovoc_4_24_metadata(METADATA_PATH) is None


@pytest.mark.skipif(not HAS_OFFICIAL_SOURCES, reason="official EuroVoc alignment sources are not cached")
def test_release_metadata_pins_alignment_to_eurovoc_4_20() -> None:
    assert (
        verify_eurovoc_lcsh_release_metadata(
            ALIGNMENT_METADATA_PATH,
            EUROVOC_4_20_METADATA_PATH,
        )
        is None
    )


@pytest.mark.skipif(not HAS_OFFICIAL_SOURCES, reason="official EuroVoc alignment sources are not cached")
@pytest.mark.parametrize("predicate", [b"skos:broadMatch", b"owl:sameAs"])
def test_pinned_alignment_reader_refuses_an_unexpected_cross_system_predicate(
    predicate: bytes,
) -> None:
    payload = ALIGNMENT_PATH.read_bytes()
    extra = b"""
<rdf:Description rdf:about="http://eurovoc.europa.eu/1">
  <%s rdf:resource="http://id.loc.gov/authorities/subjects/sh85000001"/>
</rdf:Description>
""" % predicate
    mutated = payload.replace(b"</rdf:RDF>", extra + b"</rdf:RDF>")

    with pytest.raises(EuroVocLcshAlignmentError, match="unsupported EuroVoc-to-LCSH"):
        parse_eurovoc_lcsh_alignment(mutated)


@pytest.mark.skipif(not HAS_OFFICIAL_SOURCES, reason="official EuroVoc alignment sources are not cached")
def test_pinned_file_reader_rejects_tampered_alignment_bytes(tmp_path: Path) -> None:
    tampered = tmp_path / EUROVOC_LCSH_ALIGNMENT_FILENAME
    payload = bytearray(ALIGNMENT_PATH.read_bytes())
    payload[-2] = ord("X")
    tampered.write_bytes(payload)

    with pytest.raises(EuroVocLcshAlignmentError, match="pin differs"):
        parse_eurovoc_lcsh_alignment_file(tampered)


@pytest.mark.skipif(not HAS_OFFICIAL_SOURCES, reason="official EuroVoc alignment sources are not cached")
def test_declared_domain_subjects_match_the_publisher_scheme() -> None:
    """The domain-subject set must be derived from the source, not remembered.

    Atlas loads EuroVoc domains as a separate release, so an aligned subject
    that is a domain needs its endpoint pinned to that release. The set is
    hard-declared because both inputs are digest-pinned, which makes it fixed --
    but only as long as this check proves it still matches the publisher.
    """

    import re
    import zipfile

    alignment_text = ALIGNMENT_PATH.read_text(encoding="utf-8", errors="replace")
    aligned = set(re.findall(r"http://eurovoc\.europa\.eu/\d+", alignment_text))
    assert aligned, "no EuroVoc subjects parsed from the alignment"

    archive = SOURCE_ROOT / "eurovoc-4.24-skos-core.zip"
    if not archive.is_file():
        pytest.skip("the EuroVoc SKOS core archive is not cached")

    domains: set[str] = set()
    with zipfile.ZipFile(archive) as bundle:
        member = next(name for name in bundle.namelist() if name.endswith(".rdf"))
        with bundle.open(member) as handle:
            current: str | None = None
            for raw in handle:
                line = raw.decode("utf-8", "replace")
                match = re.search(r'rdf:about="(http://eurovoc\.europa\.eu/\d+)"', line)
                if match:
                    current = match.group(1)
                elif current and 'resource="http://eurovoc.europa.eu/domains"' in line:
                    domains.add(current)
                    current = None

    assert domains, "no domain memberships parsed from the EuroVoc archive"
    assert aligned & domains == set(alignments.EUROVOC_DOMAIN_SUBJECT_IRIS)
