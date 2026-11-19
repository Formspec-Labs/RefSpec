"""Offline fast-tier verification for id.loc.gov Corporate Name Authority (LCNAF) federal agency alignment."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from refspec.loc_agency_authorities import (
    BFLC_MARC_KEY,
    EVIDENCE_RELATIVE_DIR,
    LCNAF_ALIGNMENT_BYTE_LENGTH,
    LCNAF_ALIGNMENT_FILENAME,
    LCNAF_ALIGNMENT_SHA256,
    LCNAF_AUTHORITY_PREFIX,
    MADS_BROADER_AUTHORITY,
    MADS_CORPORATE_NAME,
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


def _load_polite_loc_client_module() -> Any:
    script = REPO_ROOT / EVIDENCE_RELATIVE_DIR / "scripts" / "polite_loc_client.py"
    spec = importlib.util.spec_from_file_location("polite_loc_client", script)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_pinned_lcnaf_alignment_manifest_marc110_immutability_and_crosswalk_parity() -> None:
    """Pins all 54 corporate records, MARC 110 headings, Aug-vs-Nov Wikidata counts, and crosswalk parity."""

    doc = load_lcnaf_alignment_manifest(REPO_ROOT)
    with pytest.raises(TypeError):
        doc["summary"] = {}  # type: ignore[index]

    records = load_verified_lcnaf_records(REPO_ROOT)
    assert len(records) == 54

    summary = dict(doc["summary"])
    assert summary == {
        "evaluated_entity_count": 54,
        "crosswalk_agency_count": 47,
        "historical_predecessor_count": 7,
        "crosswalk_parent_collapsed_count": 6,
        "crosswalk_defunct_code_count": 2,
        "four_rung_exact_match_count": 54,
        "rung1_united_states_prefixed_top1_exact_count": 52,
        "bare_natural_name_top1_exact_count": 13,
        "bare_natural_name_zero_hit_count": 14,
        "bare_natural_name_false_friend_top1_count": 27,
        "fr_inverted_name_probe_exact_count": 0,
        "bare_acronym_probe_top3_exact_count": 0,
        "present_in_pinned_externallinks_zip_count": 54,
        "with_pinned_zip_wikidata_link_count": 23,
        "with_pinned_zip_fast_link_count": 53,
        "with_madsrdf_wikidata_link_count": 50,
        "with_madsrdf_fast_link_count": 53,
    }

    # Every single verified corporate authority MUST carry an authorized MARC 110 corporate heading (never a 410 variant).
    by_key = {r.key_id: r for r in records}
    for rec in records:
        assert rec.marc_key.startswith("110"), (rec.key_id, rec.marc_key)
        assert rec.authority_iri == LCNAF_AUTHORITY_PREFIX + rec.lccn
        if rec.crosswalk_code is not None:
            cw_entry = cw.AGENCY_CROSSWALK_BY_CODE[rec.crosswalk_code]
            assert rec.crosswalk_tier == cw_entry.tier

    assert by_key["DOD"].marc_key == "1101 $aUnited States.$bDepartment of Defense"
    assert by_key["DOS"].marc_key == "1101 $aUnited States.$bDepartment of State"
    assert by_key["GAO"].marc_key == "1101 $aUnited States.$bGovernment Accountability Office"
    assert by_key["HIST_HEW"].marc_key == "1101 $aUnited States.$bDepartment of Health, Education, and Welfare"
    assert by_key["HIST_AEC"].marc_key == "1102 $aU.S. Atomic Energy Commission"

    # Verify all 5 pinned false-friend IDs cited in README match raw manifest rows verbatim
    raw_by_key = {r["key_id"]: r for r in doc["agencies"]}
    assert str(raw_by_key["CMS"]["us_prefixed_top1_uri"]).endswith("/n2009184264")
    assert str(raw_by_key["EPA"]["bare_name_top1_uri"]).endswith("/no2025010917")
    assert str(raw_by_key["SEC"]["bare_name_top1_uri"]).endswith("/no2001015215")
    assert str(raw_by_key["OMB"]["bare_name_top1_uri"]).endswith("/n84065964")
    assert str(raw_by_key["USDA"]["bare_name_top1_uri"]).endswith("/no2002077088")


def test_lookup_verified_lcnaf_for_code_surfaces_independent_parent_collapse_and_defunct_flags() -> None:
    """MMS and OTS set BOTH crosswalk_parent_collapsed=True AND crosswalk_defunct_code=True."""

    collapsed_codes = {r.crosswalk_code for r in load_verified_lcnaf_records(REPO_ROOT) if r.crosswalk_parent_collapsed}
    assert collapsed_codes == {"CDC", "CISA", "USCBP", "BOEM", "MMS", "OTS"}

    for defunct_code, expected_lccn, expected_parent in (
        ("MMS", "n82104764", "interior-department"),
        ("OTS", "no89013654", "treasury-department"),
    ):
        rec = lookup_verified_lcnaf_for_code(defunct_code, repo_root=REPO_ROOT)
        assert rec is not None
        assert rec.lccn == expected_lccn
        assert rec.crosswalk_defunct_code is True
        assert rec.crosswalk_parent_collapsed is True
        assert cw.AGENCY_CROSSWALK_BY_CODE[defunct_code].primary_slug == expected_parent

    assert lookup_verified_lcnaf_for_code("NOT_A_CODE", repo_root=REPO_ROOT) is None


def test_three_heterogeneous_lcnaf_succession_modes_and_unlinked_blank_nodes() -> None:
    """Pins Mode A (explicit earlier/later), Mode B (flattened related + blank-node Dept. forms), and Mode C."""

    by_key = {r.key_id: r for r in load_verified_lcnaf_records(REPO_ROOT)}

    # Mode A: explicit LCCN-linked hasEarlierEstablishedForm / hasLaterEstablishedForm + DOE pre-AACR2 blank node
    assert set(by_key["HIST_AEC"].later_lccns) == {"n78034875", "n78034864"}
    assert set(by_key["DOE"].earlier_lccns) == {"n78034864", "n78034871"}
    assert by_key["DOE"].earlier_unlinked_labels == ("United States. Dept. of Energy",)
    assert by_key["HIST_HCFA"].later_lccns == ("no2001093385",)
    assert set(by_key["HIST_INS"].later_lccns) == {"no2003104838", "no2003052379", "no2003065384"}

    # Mode B: empty earlier_lccns/later_lccns, corporate succession in hasRelatedAuthority, pre-AACR2 blank nodes preserved
    assert by_key["HIST_HEW"].earlier_lccns == ()
    assert by_key["HIST_HEW"].earlier_unlinked_labels == ("United States. Dept. of Health, Education, and Welfare",)
    assert by_key["HHS"].earlier_unlinked_labels == ("United States. Dept. of Health and Human Services",)
    assert by_key["HIST_WAR"].earlier_unlinked_labels == ("United States. War Dept.",)

    # Mode C: abolished predecessors unlinked in RDF predicates
    for key in ("HIST_ICC", "HIST_CAB"):
        assert by_key[key].succession_encoding_mode == "unlinked_in_rdf_prose_only"
        assert by_key[key].earlier_lccns == ()
        assert by_key[key].later_lccns == ()


def test_lcnaf_manifest_loader_refuses_missing_tampered_or_symlinked_file(tmp_path: Path) -> None:
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


def test_corporate_selector_requires_us_or_parent_jurisdiction_evidence() -> None:
    """Refuses foreign/state bodies, sub-programs, AND unqualified generic headings lacking U.S./parent evidence."""

    assert build_lcnaf_corporate_queries(
        "Executive Office for Immigration Review",
        parent_department_natural_name="Department of Justice",
    ) == (
        "United States. Executive Office for Immigration Review",
        "Executive Office for Immigration Review",
        "United States. Department of Justice. Executive Office for Immigration Review",
    )

    # Unqualified generic label with NO U.S. or parent evidence MUST be refused (both with and without parent supplied).
    unqualified_eoir = [
        {"aLabel": "Executive Office for Immigration Review", "uri": "http://id.loc.gov/authorities/names/n99999999"}
    ]
    assert select_verified_lcnaf_hit(unqualified_eoir, natural_name="Executive Office for Immigration Review") is None
    assert (
        select_verified_lcnaf_hit(
            unqualified_eoir,
            natural_name="Executive Office for Immigration Review",
            parent_department_natural_name="Department of Justice",
        )
        is None
    )

    unqualified_epa = [
        {"aLabel": "Environmental Protection Agency", "uri": "http://id.loc.gov/authorities/names/n99999998"}
    ]
    assert select_verified_lcnaf_hit(unqualified_epa, natural_name="Environmental Protection Agency") is None

    # Explicitly allowlisted statutory corporation (FDIC) passes, whereas other "Federal ..." names stripped of "United States." fail!
    fdic_hits = [
        {"aLabel": "Federal Deposit Insurance Corporation", "uri": "http://id.loc.gov/authorities/names/n81013186"}
    ]
    picked_fdic = select_verified_lcnaf_hit(fdic_hits, natural_name="Federal Deposit Insurance Corporation")
    assert picked_fdic is not None and picked_fdic["uri"].endswith("/n81013186")

    stripped_ftc = [
        {"aLabel": "Federal Trade Commission", "uri": "http://id.loc.gov/authorities/names/n79066322"}
    ]
    assert select_verified_lcnaf_hit(stripped_ftc, natural_name="Federal Trade Commission") is None

    # Foreign/state jurisdictions and CMS trap are refused; U.S.-qualified CMS and DOJ-subordinate EOIR succeed.
    epa_hits = [
        {"aLabel": "Liberia. Environmental Protection Agency", "uri": "http://id.loc.gov/authorities/names/no2025010917"},
        {"aLabel": "United States. Environmental Protection Agency", "uri": "http://id.loc.gov/authorities/names/n79079597"},
    ]
    picked_epa = select_verified_lcnaf_hit(epa_hits, natural_name="Environmental Protection Agency")
    assert picked_epa is not None and picked_epa["uri"].endswith("/n79079597")

    cms_trap = [
        {"aLabel": "Medicare Recovery Audit Contractor Program (U.S.)", "uri": "http://id.loc.gov/authorities/names/n2009184264"}
    ]
    assert select_verified_lcnaf_hit(cms_trap, natural_name="Centers for Medicare & Medicaid Services") is None

    cms_direct = [
        {"aLabel": "Centers for Medicare & Medicaid Services (U.S.)", "uri": "http://id.loc.gov/authorities/names/no2001093385"}
    ]
    picked_cms = select_verified_lcnaf_hit(cms_direct, natural_name="Centers for Medicare & Medicaid Services")
    assert picked_cms is not None and picked_cms["uri"].endswith("/no2001093385")


def test_parse_lcnaf_madsrdf_graph_enforces_corporate_type_and_marc_110() -> None:
    """Selects MARC 110 over 410 variants and rejects PersonalName / MARC 100 graphs."""

    iri = LCNAF_AUTHORITY_PREFIX + "n78034868"
    graph = [
        {
            "@id": iri,
            "@type": [MADS_CORPORATE_NAME, lc.MADS_NAMESPACE + "Authority"],
            lc.MADS_AUTHORITATIVE_LABEL: [{"@value": "United States. Department of Energy"}],
            BFLC_MARC_KEY: [
                {"@value": "4102 $aNon-Latin 410 cross-reference"},
                {"@value": "1101 $aUnited States.$bDepartment of Energy"},
            ],
            MADS_HAS_VARIANT: [{"@id": "_:v1"}],
            MADS_EARLIER_FORM: [
                {"@id": LCNAF_AUTHORITY_PREFIX + "n78034864"},
                {"@id": "_:unlinked_feo"},
            ],
            MADS_LATER_FORM: [{"@id": LCNAF_AUTHORITY_PREFIX + "no2099000001"}],
            MADS_RELATED_AUTHORITY: [{"@id": LCNAF_AUTHORITY_PREFIX + "n78034875"}],
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
    assert parsed.marc_key == "1101 $aUnited States.$bDepartment of Energy"
    assert parsed.earlier_unlinked_labels == ("United States. Federal Energy Office",)

    # PersonalName @type and MARC 100 personal headings MUST be rejected!
    personal_type_graph = [
        {
            "@id": iri,
            "@type": [lc.MADS_NAMESPACE + "PersonalName"],
            lc.MADS_AUTHORITATIVE_LABEL: [{"@value": "Smith, John, 1900-1980"}],
            BFLC_MARC_KEY: [{"@value": "1001 $aSmith, John,$d1900-1980"}],
        }
    ]
    with pytest.raises(LcnafAlignmentError, match="non-corporate MADS @type"):
        parse_lcnaf_madsrdf_graph(personal_type_graph, expected_lccn="n78034868")

    marc_100_without_type = [
        {
            "@id": iri,
            lc.MADS_AUTHORITATIVE_LABEL: [{"@value": "Smith, John, 1900-1980"}],
            BFLC_MARC_KEY: [{"@value": "1001 $aSmith, John,$d1900-1980"}],
        }
    ]
    with pytest.raises(LcnafAlignmentError, match="lacks madsrdf:CorporateName in @type"):
        parse_lcnaf_madsrdf_graph(marc_100_without_type, expected_lccn="n78034868")

    corp_without_type = [
        {
            "@id": iri,
            lc.MADS_AUTHORITATIVE_LABEL: [{"@value": "United States. Department of Defense"}],
            BFLC_MARC_KEY: [{"@value": "1101 $aUnited States.$bDepartment of Defense"}],
        }
    ]
    with pytest.raises(LcnafAlignmentError, match="lacks madsrdf:CorporateName in @type"):
        parse_lcnaf_madsrdf_graph(corp_without_type, expected_lccn="n78034868")


def test_parse_lcnaf_external_links_streams_factory_and_sequence_and_refuses_single_pass_iterator() -> None:
    """Factory and re-iterable sequence stream in O(retained) memory; single-pass Iterator is refused."""

    epa = "http://id.loc.gov/authorities/names/n79079597"
    wd = "http://www.wikidata.org/entity/Q460173"
    fast = "http://id.worldcat.org/fast/531214"
    lines = [
        b'<http://id.loc.gov/authorities/subjects/sh85000001> <http://www.loc.gov/mads/rdf/v1#closeExternalAuthority> <http://www.wikidata.org/entity/Q1> .\n',
        f"<{epa}> <{lc.MADS_CLOSE_EXTERNAL_AUTHORITY}> <{wd}> .\n".encode("ascii"),
        f"<{epa}> <{lc.MADS_CLOSE_EXTERNAL_AUTHORITY}> <{fast}> .\n".encode("ascii"),
        f'<{wd}> <{lc.MADS_AUTHORITATIVE_LABEL}> "United States Environmental Protection Agency" .\n'.encode("ascii"),
        f'<{fast}> <{lc.MADS_AUTHORITATIVE_LABEL}> "United States. Environmental Protection Agency" .\n'.encode("ascii"),
    ]

    from_seq = parse_lcnaf_external_links_statements(lines)
    from_factory = parse_lcnaf_external_links_statements(lambda: iter(lines))
    assert from_seq == from_factory

    assertions, labels = from_factory
    assert len(assertions) == 2
    assert [a.target_vocabulary for a in assertions] == ["wikidata", "fast"]
    assert labels[wd][0].line_number == 4
    assert labels[fast][0].line_number == 5
    assert labels[wd][0].determined_language == "en"

    with pytest.raises(TypeError, match="single-pass Iterator"):
        parse_lcnaf_external_links_statements(iter(lines))


def test_polite_loc_client_validates_expect_kind_and_stops_before_reading_blocked_body() -> None:
    """Verifies expect_kind validation and pre-body-read abort on 429/403/cf-mitigated/Retry-After."""

    plc = _load_polite_loc_client_module()
    client = plc.PoliteLocClient()

    with pytest.raises(plc.LocClientError, match="Unsupported expect_kind"):
        client._validate_url("https://tile.loc.gov/storage-services/service/ll/llsl/llsl-c5/llsl-c5.pdf", expect_kind="html")

    with pytest.raises(plc.LocClientError, match="Forbidden host"):
        client._validate_url("https://webarchive.loc.gov/all/2020/https://house.gov/a.pdf", expect_kind="pdf")

    with pytest.raises(plc.LocClientError, match="missing fo=json"):
        client._validate_url("https://www.loc.gov/collections/united-states-statutes-at-large/", expect_kind="json")

    # Cache-hit payload validator must reject JSON bytes when expect_kind="pdf"
    with pytest.raises(plc.LocClientError, match="lacks %PDF- magic bytes"):
        client._validate_payload_bytes(
            b'[{"@id": "http://id.loc.gov/authorities/names/n79021946"}]',
            current_url="https://id.loc.gov/authorities/names/n79021946.madsrdf.json",
            current_host="id.loc.gov",
            ctype="application/json",
            expect_kind="pdf",
        )

    # Fake-clock check: _paced_single_get updates post-request timestamp so a slow/paused first request
    # never permits a second request to start 0s after the first finishes!
    clock = [1000.0]
    request_starts: list[float] = []
    orig_time, orig_sleep = plc.time.time, plc.time.sleep
    try:
        plc.time.time = lambda: clock[0]
        plc.time.sleep = lambda dt: clock.__setitem__(0, clock[0] + dt)
        paced_client = plc.PoliteLocClient()

        def _slow_get(_url: str, _hdrs: dict[str, str], _timeout: float) -> tuple[int, dict[str, str], dict[str, str], bytes]:
            clock[0] += 3.0  # Simulate 3s pause/transfer before actual wire completion
            request_starts.append(clock[0])
            return 200, {"Content-Type": "application/json"}, {"content-type": "application/json"}, b"{}"

        paced_client._single_get = _slow_get  # type: ignore[method-assign]
        paced_client._paced_single_get("id.loc.gov", "https://id.loc.gov/a", {}, 10.0)
        paced_client._paced_single_get("id.loc.gov", "https://id.loc.gov/b", {}, 10.0)
        assert request_starts[1] - request_starts[0] >= 2.2
    finally:
        plc.time.time = orig_time
        plc.time.sleep = orig_sleep

    class _FakeResponse:
        def __init__(self, status: int, headers: dict[str, str]) -> None:
            self.status = status
            self.headers = headers
            self.body_read_called = False

        def read(self) -> bytes:
            self.body_read_called = True
            return b"{}"

        def __enter__(self) -> _FakeResponse:
            return self

        def __exit__(self, *_: object) -> None:
            return None

    class _FakeOpener:
        def __init__(self, resp: _FakeResponse) -> None:
            self.resp = resp

        def open(self, _req: object, timeout: float = 0.0) -> _FakeResponse:
            assert timeout > 0
            return self.resp

    for status, hdrs in [
        (200, {"cf-mitigated": "challenge"}),
        (200, {"Retry-After": "120"}),
        (200, {"Content-Range": "bytes 0-100/500"}),
        (429, {}),
        (403, {}),
    ]:
        fake_resp = _FakeResponse(status, hdrs)
        client._opener = _FakeOpener(fake_resp)
        with pytest.raises(plc.LocClientError):
            client._single_get("https://id.loc.gov/authorities/names/n79079597.madsrdf.json", {}, 10.0)
        assert fake_resp.body_read_called is False
