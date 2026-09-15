"""Source facts and mutation verdicts against the copied PREMIS reader."""

from dataclasses import asdict, replace
from pathlib import Path

import govinfo_premis_oracle as old
import pytest

from refspec.registry import govinfo_collections as gc

SOURCE = (
    Path(__file__).parent / "fixtures/govinfo_collections/govinfo-premis-cfr-2023-title1-vol1-mini-2026-08-03.xml"
).read_bytes()
DIGEST = b"7321767f07828dc822e81e9806a33280cb2860d4281ac91f1bc79439b1cfcb33"
LOCATION = (
    b"Public Access Rendition https://www.govinfo.gov/content/pkg/CFR-2023-title1-vol1/html/CFR-2023-title1-vol1.htm"
)


def changed(before, after):
    assert before in SOURCE
    return SOURCE.replace(before, after, 1)


MUTATIONS = {
    "original": SOURCE,
    "utf16": SOURCE.decode().replace('encoding="UTF-8"', 'encoding="UTF-16"').encode("utf-16"),
    "crlf": SOURCE.replace(b"\n", b"\r\n"),
    "wrong_root": SOURCE.replace(b"<premis ", b"<other ").replace(b"</premis>", b"</other>"),
    "v3_namespace": SOURCE.replace(b"info:lc/xmlns/premis-v2", b"http://www.loc.gov/premis/v3"),
    "unknown_version": changed(b'version="2.0"', b'version="unreviewed"'),
    "non_file_object": changed(b'xsi:type="file"', b'xsi:type="representation"'),
    "prefixed_file_type": changed(b'xsi:type="file"', b'xsi:type="p:file" xmlns:p="info:lc/xmlns/premis-v2"'),
    "empty_file_type": changed(b'xsi:type="file"', b'xsi:type=""'),
    "missing_fixity": changed(b"<fixity>", b"<unselected>").replace(b"</fixity>", b"</unselected>", 1),
    "all_missing_fixity": SOURCE.replace(b"<fixity>", b"<unselected>").replace(b"</fixity>", b"</unselected>"),
    "empty_fixity_first": changed(b"<fixity>", b"<fixity/><fixity>"),
    "empty_characteristics_first": changed(
        b"<objectCharacteristics>", b"<objectCharacteristics/><objectCharacteristics>"
    ),
    "wrong_identifier_type": changed(b"FDsys ACP", b"Unknown"),
    "padded_identifier_type": changed(b"FDsys ACP", b" FDsys ACP "),
    "padded_identifier_value": changed(b"D09002ee1c7456565", b" D09002ee1c7456565 "),
    "empty_identifier_value": changed(b"D09002ee1c7456565", b""),
    "empty_identifier_first": changed(b"<objectIdentifier>", b"<objectIdentifier/><objectIdentifier>"),
    "split_identifier_fields": changed(
        b"<objectIdentifier>",
        b"<objectIdentifier><objectIdentifierType>FDsys ACP</objectIdentifierType></objectIdentifier><objectIdentifier>",
    ),
    "empty_identifier_type_first": changed(b"<objectIdentifierType>", b"<objectIdentifierType/><objectIdentifierType>"),
    "duplicate_identifier": changed(b"D09002ee1c7456569", b"D09002ee1c7456565"),
    "unknown_algorithm": changed(b"SHA-256", b"SHA-512"),
    "padded_algorithm": changed(b"SHA-256", b" SHA-256 "),
    "mixed_algorithm": changed(b"SHA-256", b"SHA-256<unselected/>tail"),
    "empty_algorithm_first": changed(b"<messageDigestAlgorithm>", b"<messageDigestAlgorithm/><messageDigestAlgorithm>"),
    "bad_digest": changed(DIGEST, b"not-hex"),
    "uppercase_digest": changed(DIGEST, DIGEST.upper()),
    "padded_digest": changed(DIGEST, b" \t" + DIGEST + b"\n"),
    "mixed_digest": changed(DIGEST, DIGEST + b"<unselected/>tail"),
    "digest_child_only": changed(DIGEST, b"<unselected>" + DIGEST + b"</unselected>"),
    "empty_digest_first": changed(b"<messageDigest>", b"<messageDigest/><messageDigest>"),
    "wrong_package_name": changed(b"<originalName>CFR-2023", b"<originalName>CFR-2024"),
    "padded_name": changed(b"<originalName>CFR-2023", b"<originalName>  CFR-2023"),
    "empty_name": changed(b"CFR-2023-title1-vol1.htm</originalName>", b"</originalName>"),
    "name_prefix_only": changed(
        b"CFR-2023-title1-vol1.htm</originalName>", b"CFR-2023-title1-vol10.htm</originalName>"
    ),
    "wrong_location_type": changed(b"<contentLocationType>URI", b"<contentLocationType>URL"),
    "empty_storage_first": changed(b"<storage>", b"<storage/><storage>"),
    "empty_location_first": changed(b"<contentLocation>", b"<contentLocation/><contentLocation>"),
    "empty_location_value": changed(LOCATION, b""),
    "unknown_location_label": changed(LOCATION, LOCATION.replace(b"Public Access Rendition", b"Other label")),
    "newline_before_uri": changed(LOCATION, LOCATION.replace(b"Rendition https", b"Rendition\nhttps")),
    "wrong_location_host": changed(LOCATION, LOCATION.replace(b"www.govinfo.gov", b"example.com")),
    "wrong_location_scheme": changed(LOCATION, LOCATION.replace(b"https://", b"http://")),
    "unknown_extension": changed(b"</premis>", b"<extra xmlns='urn:unknown'>opaque<child/>tail</extra></premis>"),
    "empty_doctype": changed(b"<premis ", b"<!DOCTYPE premis><premis "),
    "external_doctype": changed(b"<premis ", b'<!DOCTYPE premis SYSTEM "https://example.invalid/no-fetch"><premis '),
    "internal_entity": changed(b"<premis ", b'<!DOCTYPE premis [<!ENTITY label "FDsys ACP">]><premis ').replace(
        b"<objectIdentifierType>FDsys ACP", b"<objectIdentifierType>&label;", 1
    ),
    "deep_unknown_extension": changed(b"</premis>", b"<extra>" * 65 + b"opaque" + b"</extra>" * 65 + b"</premis>"),
    "truncated": SOURCE[:-30],
}

# Shared bounded XML scanning refuses DTDs and excessive nesting that the former
# ElementTree path accepted. No identifier or vocabulary decision changes.
DELIBERATE_DIVERGENCES = frozenset(
    {
        "empty_doctype",
        "external_doctype",
        "internal_entity",
        "deep_unknown_extension",
    }
)


def acquired(tmp_path, payload):
    path = tmp_path / "source.xml"
    path.write_bytes(payload)
    pin = replace(
        gc.GOVINFO_CFR_PACKAGE_PREMIS_2026_08_03,
        expected_sha256=gc.sha256_digest(payload),
        expected_byte_length=len(payload),
    )
    # Construct the capture directly so each independent parser verifies the
    # input. Running today's acquisition first would hide old XML verdicts.
    return gc.AcquiredGovInfoSource(
        pin=pin,
        path=path,
        sha256=pin.expected_sha256,
        byte_length=len(payload),
        source_url=pin.source.source_url,
        resolved_url=None,
        content_type="application/xml",
        acquisition_mode="local",
        cache_hit=False,
        local_source_path=path,
    )


def verdict(parser, source):
    try:
        result = parser(source, expected_package_id=gc.GOVINFO_CFR_PACKAGE_ID)
    except gc.GovInfoSourceDriftError:
        return "reject", None
    return "accept", asdict(result)


@pytest.mark.parametrize("name,payload", MUTATIONS.items())
def test_raw_source_and_mutations_match_frozen_reader(tmp_path, name, payload):
    source = acquired(tmp_path, payload)
    before = verdict(old.parse_govinfo_cfr_package_fixity, source)
    after = verdict(gc.parse_govinfo_cfr_package_fixity, source)
    if name in DELIBERATE_DIVERGENCES:
        assert (before[0], after[0]) == ("accept", "reject")
    else:
        assert before == after
        if name == "original":
            assert after[0] == "accept"
            assert len(after[1]["records"]) == 2


def test_frozen_divergence_names_are_exercised():
    assert DELIBERATE_DIVERGENCES <= MUTATIONS.keys()


def test_complete_captured_package_matches_old_reader(tmp_path):
    payload = (
        Path(__file__).parent / "fixtures/govinfo_collections/govinfo-premis-cfr-2023-title1-vol1-2026-09-15.xml"
    ).read_bytes()
    assert len(payload) == 179_574
    assert gc.sha256_digest(payload) == "sha256:2e6e84ab8c95f0ee904053ea6485896a88fcb81e03bfce482b6ed36fc53e80ba"
    source = acquired(tmp_path, payload)
    source = replace(source, pin=replace(source.pin, retrieved_at="2026-09-15T05:47:14.874227Z"))
    before = verdict(old.parse_govinfo_cfr_package_fixity, source)
    assert before[0] == "accept"
    assert len(before[1]["records"]) == 3
    assert verdict(gc.parse_govinfo_cfr_package_fixity, source) == before


@pytest.mark.parametrize("field,value", [("expected_sha256", "sha256:" + "0" * 64), ("expected_byte_length", 1)])
def test_pin_drift_is_checked_before_mapping(tmp_path, field, value):
    source = acquired(tmp_path, SOURCE)
    source = replace(source, pin=replace(source.pin, **{field: value}))
    for parser in (old.parse_govinfo_cfr_package_fixity, gc.parse_govinfo_cfr_package_fixity):
        assert verdict(parser, source) == ("reject", None)
