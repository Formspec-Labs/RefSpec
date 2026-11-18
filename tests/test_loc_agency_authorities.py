"""Offline fast-tier verification for id.loc.gov Corporate Name Authority (LCNAF) federal agency alignment."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from refspec.loc_agency_authorities import (
    BFLC_MARC_KEY,
    EVIDENCE_RELATIVE_DIR,
    LCNAF_ALIGNMENT_BYTE_LENGTH,
    LCNAF_ALIGNMENT_FILENAME,
    LCNAF_ALIGNMENT_SHA256,
    LCNAF_AUTHORITY_PREFIX,
    MADS_BROADER_AUTHORITY,
    MADS_EARLIER_FORM,
    MADS_HAS_VARIANT,
    MADS_IDENTIFIES_RWO,
    MADS_LATER_FORM,
    MADS_RELATED_AUTHORITY,
    MADS_VARIANT_LABEL,
    LcnafAlignmentError,
    build_lcnaf_corporate_queries,
    load_lcnaf_alignment_manifest,
    load_verified_lcnaf_records,
    lookup_verified_lcnaf_for_code,
    parse_lcnaf_external_links_statements,
    parse_lcnaf_madsrdf_graph,
    select_verified_lcnaf_hit,
)
from refspec.registry import agency_crosswalk as cw
from refspec.registry import lc_external_links as lc

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_pinned_lcnaf_alignment_manifest_summary_and_crosswalk_parity() -> None:
    """Pins all 54 verified federal corporate records, summary counts, and AGENCY_CROSSWALK parity."""

    doc = load_lcnaf_alignment_manifest(REPO_ROOT)
    records = load_verified_lcnaf_records(REPO_ROOT)
    assert len(records) == 54

    baseline = doc["pinned_lc_external_links_baseline"]
    assert baseline["lcsh_assertions_currently_read"] == 802_592
    assert baseline["lcnaf_assertions_present_in_same_zip"] == 2_018_402
    assert baseline["lcnaf_to_fast_assertions"] == 1_418_942
    assert baseline["lcnaf_to_wikidata_assertions"] == 425_540
    assert baseline["oclc_fast_topical_corporate_assertions"] == 0

    summary = doc["summary"]
    assert summary == {
        "evaluated_entity_count": 54,
        "crosswalk_agency_count": 47,
        "historical_predecessor_count": 7,
        "four_rung_exact_match_count": 54,
        "rung1_united_states_prefixed_top1_exact_count": 52,
        "bare_natural_name_top1_exact_count": 13,
        "bare_natural_name_zero_hit_count": 14,
        "bare_natural_name_false_friend_top1_count": 27,
        "fr_inverted_name_probe_exact_count": 0,
        "bare_acronym_probe_top3_exact_count": 0,
        "present_in_pinned_externallinks_zip_count": 54,
        "with_wikidata_link_count": 50,
        "with_fast_link_count": 53,
    }

    # Recompute summary metrics directly from records & negative probes.
    raw_rows = doc["agencies"]
    assert sum(1 for r in records if r.crosswalk_code is not None) == 47
    assert sum(1 for r in records if r.crosswalk_code is None) == 7
    assert sum(1 for r in records if r.us_prefixed_top1_exact) == 52
    assert sum(1 for r in records if r.bare_name_top1_exact) == 13
    assert sum(1 for r in raw_rows if r["bare_name_hits_count"] == 0) == 14
    assert sum(1 for r in raw_rows if r["bare_name_hits_count"] > 0 and not r["bare_name_top1_exact"]) == 27
    assert sum(1 for r in records if r.in_pinned_lc_externallinks_zip) == 54
    assert sum(1 for r in records if r.wikidata_iris) == 50
    assert sum(1 for r in records if r.fast_iris) == 53
    assert len({r.lccn for r in records}) == 54

    # Every crosswalk_code must exist in AGENCY_CROSSWALK_BY_CODE with matching tier.
    for rec in records:
        assert rec.authority_iri == LCNAF_AUTHORITY_PREFIX + rec.lccn
        assert rec.madsrdf_sha256.startswith("sha256:") and len(rec.madsrdf_sha256) == 71
        if rec.crosswalk_code is not None:
            cw_entry = cw.AGENCY_CROSSWALK_BY_CODE[rec.crosswalk_code]
            assert rec.crosswalk_tier == cw_entry.tier


def test_lookup_verified_lcnaf_for_code_surfaces_parent_collapse_and_defunct_flags() -> None:
    """Sub-agency parent collapse (CDC, CISA, USCBP, BOEM) and defunct codes (MMS, OTS) are explicit."""

    cdc = lookup_verified_lcnaf_for_code("CDC", repo_root=REPO_ROOT)
    assert cdc is not None
    assert cdc.lccn == "no93011529"
    assert cdc.authoritative_label == "Centers for Disease Control and Prevention (U.S.)"
    assert cdc.crosswalk_parent_collapsed is True
    assert cw.AGENCY_CROSSWALK_BY_CODE["CDC"].primary_slug == "health-and-human-services-department"

    for collapsed_code in ("CISA", "USCBP", "BOEM"):
        rec = lookup_verified_lcnaf_for_code(collapsed_code, repo_root=REPO_ROOT)
        assert rec is not None and rec.crosswalk_parent_collapsed is True

    for defunct_code, expected_lccn in (("MMS", "n82104764"), ("OTS", "no89013654")):
        rec = lookup_verified_lcnaf_for_code(defunct_code, repo_root=REPO_ROOT)
        assert rec is not None
        assert rec.lccn == expected_lccn
        assert rec.crosswalk_defunct_code is True

    cms = lookup_verified_lcnaf_for_code("CMS", repo_root=REPO_ROOT)
    assert cms is not None
    assert cms.lccn == "no2001093385"
    assert cms.us_prefixed_top1_exact is False
    assert cms.resolution_rung == "rung2_bare_direct_entry_with_us_qualifier"

    eoir = lookup_verified_lcnaf_for_code("EOIR", repo_root=REPO_ROOT)
    assert eoir is not None
    assert eoir.lccn == "n89643262"
    assert eoir.resolution_rung == "rung3_parent_department_subordinate"

    assert lookup_verified_lcnaf_for_code("NOT_A_CODE", repo_root=REPO_ROOT) is None


def test_three_heterogeneous_lcnaf_succession_modes_are_pinned_in_manifest() -> None:
    """Pins Mode A (explicit earlier/later), Mode B (flattened related), and Mode C (zero RDF link)."""

    by_key = {r.key_id: r for r in load_verified_lcnaf_records(REPO_ROOT)}

    # Mode A: explicit hasEarlierEstablishedForm / hasLaterEstablishedForm
    assert by_key["HIST_AEC"].succession_encoding_mode == "explicit_earlier_or_later_established_form"
    assert set(by_key["HIST_AEC"].later_lccns) == {"n78034875", "n78034864"}  # NRC + ERDA
    assert by_key["HIST_HCFA"].later_lccns == ("no2001093385",)  # CMS
    assert set(by_key["HIST_INS"].later_lccns) == {"no2003104838", "no2003052379", "no2003065384"}  # USCIS, CBP, ICE
    assert by_key["MMS"].later_lccns == ("no2010108932",)  # BOEMRE -> BOEM
    assert by_key["BOEM"].earlier_lccns == ("no2010108932",)

    # Mode B: flattened into untyped hasRelatedAuthority without earlier/later established-form triples
    for key in ("HIST_HEW", "HHS", "HIST_WAR", "GPO"):
        assert by_key[key].succession_encoding_mode == "flattened_into_untyped_related_authority"
        assert by_key[key].earlier_lccns == ()
        assert by_key[key].later_lccns == ()
        assert by_key[key].related_authority_count > 0

    # Mode C: abolished predecessors unlinked in RDF (ICC vs STB; CAB vs DOT)
    for key in ("HIST_ICC", "HIST_CAB"):
        assert by_key[key].succession_encoding_mode == "unlinked_in_rdf_prose_only"
        assert by_key[key].earlier_lccns == ()
        assert by_key[key].later_lccns == ()


def test_lcnaf_manifest_loader_refuses_missing_tampered_or_symlinked_file(tmp_path: Path) -> None:
    """Negative gate: missing, tampered, or symlinked LCNAF manifest raises LcnafAlignmentError."""

    ev_dir = tmp_path / EVIDENCE_RELATIVE_DIR
    ev_dir.mkdir(parents=True)

    with pytest.raises(LcnafAlignmentError, match="missing or unsafe"):
        load_lcnaf_alignment_manifest(tmp_path)

    src = REPO_ROOT / EVIDENCE_RELATIVE_DIR / LCNAF_ALIGNMENT_FILENAME
    assert src.stat().st_size == LCNAF_ALIGNMENT_BYTE_LENGTH
    dst = ev_dir / LCNAF_ALIGNMENT_FILENAME
    tampered = bytearray(src.read_bytes())
    tampered[-3] ^= 0x01
    dst.write_bytes(bytes(tampered))
    with pytest.raises(LcnafAlignmentError, match=LCNAF_ALIGNMENT_SHA256):
        load_lcnaf_alignment_manifest(tmp_path)

    dst.unlink()
    dst.symlink_to(src)
    with pytest.raises(LcnafAlignmentError, match="missing or unsafe"):
        load_lcnaf_alignment_manifest(tmp_path)


def test_corporate_query_ladder_and_false_friend_rejection() -> None:
    """Refuses foreign/state jurisdictions, acronym collisions, and sub-program variant traps."""

    assert build_lcnaf_corporate_queries("Environmental Protection Agency") == (
        "United States. Environmental Protection Agency",
        "Environmental Protection Agency",
    )
    assert build_lcnaf_corporate_queries(
        "Executive Office for Immigration Review",
        parent_department_natural_name="Department of Justice",
    ) == (
        "United States. Executive Office for Immigration Review",
        "Executive Office for Immigration Review",
        "United States. Department of Justice. Executive Office for Immigration Review",
    )
    with pytest.raises(LcnafAlignmentError, match="must not be empty"):
        build_lcnaf_corporate_queries("   ")

    # Foreign/state jurisdictions + sub-divisions must all be rejected; only exact U.S. body wins.
    epa_hits = [
        {"aLabel": "Liberia. Environmental Protection Agency", "uri": "http://id.loc.gov/authorities/names/no2009128816"},
        {"aLabel": "Alaska. Environmental Protection Agency", "uri": "http://id.loc.gov/authorities/names/n83028922"},
        {
            "aLabel": "United States. Environmental Protection Agency. Acid Rain Division",
            "uri": "http://id.loc.gov/authorities/names/no94012345",
        },
        {"aLabel": "Eglise protestante africaine (Cameroon)", "uri": "http://id.loc.gov/authorities/names/n2012004205"},
        {"aLabel": "United States. Environmental Protection Agency", "uri": "http://id.loc.gov/authorities/names/n79079597"},
    ]
    picked = select_verified_lcnaf_hit(epa_hits, natural_name="Environmental Protection Agency")
    assert picked is not None and picked["uri"].endswith("/n79079597")

    # CMS trap: Rung 1 returns Medicare Recovery Audit Contractor Program (U.S.); selector must refuse it.
    cms_trap = [
        {"aLabel": "Medicare Recovery Audit Contractor Program (U.S.)", "uri": "http://id.loc.gov/authorities/names/n2013184550"}
    ]
    assert select_verified_lcnaf_hit(cms_trap, natural_name="Centers for Medicare & Medicaid Services") is None

    cms_direct = [
        {"aLabel": "Centers for Medicare & Medicaid Services (U.S.)", "uri": "http://id.loc.gov/authorities/names/no2001093385"}
    ]
    picked_cms = select_verified_lcnaf_hit(cms_direct, natural_name="Centers for Medicare & Medicaid Services")
    assert picked_cms is not None and picked_cms["uri"].endswith("/no2001093385")

    # Parent-qualified EOIR requires parent_department_natural_name to accept DOJ-subordinate heading.
    eoir_hits = [
        {
            "aLabel": "United States. Department of Justice. Executive Office for Immigration Review",
            "uri": "http://id.loc.gov/authorities/names/n89643262",
        }
    ]
    assert select_verified_lcnaf_hit(eoir_hits, natural_name="Executive Office for Immigration Review") is None
    picked_eoir = select_verified_lcnaf_hit(
        eoir_hits,
        natural_name="Executive Office for Immigration Review",
        parent_department_natural_name="Department of Justice",
    )
    assert picked_eoir is not None and picked_eoir["uri"].endswith("/n89643262")

    # Non-LCNAF URIs and malformed LCCNs are refused.
    bad_uri_hits = [
        {"aLabel": "United States. Environmental Protection Agency", "uri": "http://id.loc.gov/authorities/subjects/sh85000001"},
        {"aLabel": "United States. Environmental Protection Agency", "uri": "http://id.loc.gov/authorities/names/bad-id"},
    ]
    assert select_verified_lcnaf_hit(bad_uri_hits, natural_name="Environmental Protection Agency") is None


def test_parse_lcnaf_madsrdf_graph_positive_and_negative() -> None:
    """Extracts labels, MARC 110, variants, linked/unlinked succession, and Wikidata/FAST/VIAF/ISNI IRIs."""

    iri = LCNAF_AUTHORITY_PREFIX + "n78034868"
    graph = [
        {
            "@id": iri,
            lc.MADS_AUTHORITATIVE_LABEL: [{"@value": "United States. Department of Energy"}],
            BFLC_MARC_KEY: [
                {"@value": "4102 $aNon-Latin 410 cross-reference"},
                {"@value": "1101 $aUnited States.$bDepartment of Energy"},
            ],
            MADS_HAS_VARIANT: [{"@id": "_:v1"}],
            MADS_EARLIER_FORM: [
                {"@id": LCNAF_AUTHORITY_PREFIX + "n78034863"},
                {"@id": "_:unlinked_feo"},
            ],
            MADS_LATER_FORM: [{"@id": LCNAF_AUTHORITY_PREFIX + "no2099000001"}],
            MADS_RELATED_AUTHORITY: [{"@id": LCNAF_AUTHORITY_PREFIX + "n78087181"}],
            MADS_BROADER_AUTHORITY: [{"@id": LCNAF_AUTHORITY_PREFIX + "n78095330"}],
            lc.MADS_CLOSE_EXTERNAL_AUTHORITY: [
                {"@id": "http://www.wikidata.org/entity/Q217810"},
                {"@id": "http://id.worldcat.org/fast/527579"},
            ],
            MADS_IDENTIFIES_RWO: [
                {"@id": "http://viaf.org/viaf/127149066573065601696"},
                {"@id": "https://isni.org/isni/0000000404786514"},
            ],
        },
        {"@id": "_:v1", MADS_VARIANT_LABEL: [{"@value": "DOE"}]},
        {"@id": "_:unlinked_feo", lc.MADS_AUTHORITATIVE_LABEL: [{"@value": "United States. Federal Energy Office"}]},
    ]
    parsed = parse_lcnaf_madsrdf_graph(json.dumps(graph), expected_lccn="n78034868")
    assert parsed.lccn == "n78034868"
    assert parsed.authoritative_label == "United States. Department of Energy"
    assert parsed.marc_key == "1101 $aUnited States.$bDepartment of Energy"
    assert parsed.variant_labels == ("DOE",)
    assert parsed.earlier_lccns == ("n78034863",)
    assert parsed.earlier_unlinked_labels == ("United States. Federal Energy Office",)
    assert parsed.later_lccns == ("no2099000001",)
    assert parsed.related_lccns == ("n78087181",)
    assert parsed.broader_lccns == ("n78095330",)
    assert parsed.wikidata_iris == ("http://www.wikidata.org/entity/Q217810",)
    assert parsed.fast_iris == ("http://id.worldcat.org/fast/527579",)
    assert parsed.viaf_iris == ("http://viaf.org/viaf/127149066573065601696",)
    assert parsed.isni_iris == ("https://isni.org/isni/0000000404786514",)

    with pytest.raises(LcnafAlignmentError, match="invalid LCCN"):
        parse_lcnaf_madsrdf_graph(graph, expected_lccn="invalid")
    with pytest.raises(LcnafAlignmentError, match="must be a list"):
        parse_lcnaf_madsrdf_graph("{}", expected_lccn="n78034868")
    with pytest.raises(LcnafAlignmentError, match="missing primary authority node"):
        parse_lcnaf_madsrdf_graph([], expected_lccn="n78034868")
    with pytest.raises(LcnafAlignmentError, match="no authoritativeLabel"):
        parse_lcnaf_madsrdf_graph([{"@id": iri}], expected_lccn="n78034868")


def test_parse_lcnaf_external_links_statements_reuses_lc_external_links_invariants() -> None:
    """Parses id.loc.gov/authorities/names/ N-Triples while ignoring LCSH and enforcing lc_external_links gates."""

    epa = "http://id.loc.gov/authorities/names/n79079597"
    wd = "http://www.wikidata.org/entity/Q460173"
    fast = "http://id.worldcat.org/fast/531214"
    lines = [
        b'<http://id.loc.gov/authorities/subjects/sh85000001> <http://www.loc.gov/mads/rdf/v1#closeExternalAuthority> <http://www.wikidata.org/entity/Q1> .\n',
        f"<{epa}> <{lc.MADS_CLOSE_EXTERNAL_AUTHORITY}> <{wd}> .\n".encode("ascii"),
        f"<{epa}> <{lc.MADS_CLOSE_EXTERNAL_AUTHORITY}> <{fast}> .\n".encode("ascii"),
        f'<{wd}> <http://www.loc.gov/mads/rdf/v1#authoritativeLabel> "United States Environmental Protection Agency" .\n'.encode(
            "ascii"
        ),
        f'<{fast}> <{lc.MADS_AUTHORITATIVE_LABEL}> "United States. Environmental Protection Agency" .\n'.encode(
            "ascii"
        ),
    ]
    assertions, labels = parse_lcnaf_external_links_statements(lines)
    assert len(assertions) == 2
    assert [a.target_vocabulary for a in assertions] == ["wikidata", "fast"]
    assert labels[wd][0].language is None
    assert labels[wd][0].determined_language == "en"
    assert labels[wd][0].language_determined_by == "sourceConvention:lc-external-links-selects-English-wikidata-labels"
    assert labels[fast][0].determined_language == "en"

    # Retained-subject filter narrows cleanly.
    filtered, _ = parse_lcnaf_external_links_statements(lines, retained_subject_iris=frozenset())
    assert filtered == ()

    # Duplicate LCNAF claims, unknown target vocabularies, unsupported *ExternalAuthority predicates, and non-bytes lines fail loudly.
    with pytest.raises(lc.LcExternalLinksError, match="repeats an LCNAF mapping claim"):
        parse_lcnaf_external_links_statements([lines[1], lines[1]])

    unknown_vocab = f"<{epa}> <{lc.MADS_CLOSE_EXTERNAL_AUTHORITY}> <https://example.org/unknown/1> .\n".encode("ascii")
    with pytest.raises(lc.LcExternalLinksError):
        parse_lcnaf_external_links_statements([unknown_vocab])

    bad_pred = f"<{epa}> <http://www.loc.gov/mads/rdf/v1#broadExternalAuthority> <{wd}> .\n".encode("ascii")
    with pytest.raises(lc.LcExternalLinksError, match="unsupported LCNAF external-authority predicate"):
        parse_lcnaf_external_links_statements([bad_pred])

    with pytest.raises(TypeError, match="must be bytes"):
        parse_lcnaf_external_links_statements(["not bytes"])  # type: ignore[list-item]
