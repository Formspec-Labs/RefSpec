"""Accepted FR data and mutation verdicts against the frozen pre-port reader."""

import dataclasses
import hashlib
import json
from pathlib import Path

import federal_register_native_controls_oracle as old
import pytest

from refspec.registry import federal_register_native_controls as current

FIXTURES = Path(__file__).parent / "fixtures/federal_register_native_controls"
AGENCIES = (FIXTURES / "fr-agencies-2026-08-15.json").read_bytes()
DOCUMENTATION = (FIXTURES / "fr-api-documentation-2026-08-15.json").read_bytes()
FACETS = (FIXTURES / "fr-documents-facets-type-2026-08-15.json").read_bytes()


def _pin(module, payload, url):
    return module.FRSnapshotPin(
        url, "2026-08-15T07:50:47Z", "sha256:" + hashlib.sha256(payload).hexdigest(), len(payload)
    )


def _verdict(module, family, payload):
    try:
        if family == "agencies":
            result = module.parse_agencies_roster(payload, agencies_pin=_pin(module, payload, module.FR_AGENCIES_URL))
        else:
            documentation = payload if family == "documentation" else DOCUMENTATION
            facets = payload if family == "facets" else FACETS
            doc_pin = _pin(module, documentation, module.FR_API_DOCUMENTATION_URL)
            result = module.parse_documented_document_types(
                documentation,
                facets,
                documentation_pin=doc_pin,
                facets_pin=_pin(module, facets, module.FR_DOCUMENT_TYPE_FACETS_URL),
            )
        return "accept", dataclasses.asdict(result)
    except ValueError:
        return "reject", None


def test_all_retained_accepted_fields_match_old_reader():
    for family, payload in (("agencies", AGENCIES), ("documentation", DOCUMENTATION), ("facets", FACETS)):
        before = _verdict(old, family, payload)
        assert before[0] == "accept"
        assert _verdict(current, family, payload) == before
    assert current.parse_documented_presidential_document_types(
        DOCUMENTATION
    ) == old.parse_documented_presidential_document_types(DOCUMENTATION)
    roster = current.parse_agencies_roster(AGENCIES)
    assert current.crosscheck_documented_agency_slugs(DOCUMENTATION, roster) == 472


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", True),
        ("id", -1),
        ("id", "557"),
        ("slug", ""),
        ("slug", "UPPER"),
        ("name", ""),
        ("name", "  "),
        ("name", " literal "),
        ("parent_id", 99999),
        ("parent_id", True),
        ("child_ids", [99999]),
        ("child_ids", [True]),
        ("child_ids", []),
        ("child_slugs", [None]),
        ("child_slugs", ["unmatched"]),
        ("description", None),
        ("description", 1),
        ("short_name", None),
        ("short_name", ""),
        ("url", "http://www.federalregister.gov/x"),
        ("url", "https://example.com/x"),
        ("agency_url", None),
        ("agency_url", ""),
        ("agency_url", "relative"),
        ("recent_articles_url", 1.5),
        ("logo", {"unreviewed": [1, 0.25]}),
    ],
)
def test_agency_field_mutations_preserve_verdicts_and_accepted_values(field, value):
    rows = json.loads(AGENCIES)
    rows[0][field] = value
    payload = json.dumps(rows).encode()
    assert _verdict(current, "agencies", payload) == _verdict(old, "agencies", payload)


@pytest.mark.parametrize(
    "mutation", ["missing", "extra", "duplicate-id", "duplicate-slug", "parent-mismatch", "empty", "nonobject"]
)
def test_agency_roster_mutations_preserve_refusal(mutation):
    rows = json.loads(AGENCIES)
    if mutation == "missing":
        rows[0].pop("id")
    elif mutation == "extra":
        rows[0]["unknown"] = "preserved upstream but unreviewed downstream"
    elif mutation == "duplicate-id":
        rows[1]["id"] = rows[0]["id"]
    elif mutation == "duplicate-slug":
        rows[1]["slug"] = rows[0]["slug"]
    elif mutation == "parent-mismatch":
        rows[0]["child_ids"] = [rows[1]["id"]]
    elif mutation == "empty":
        rows = []
    else:
        rows[0] = None
    payload = json.dumps(rows).encode()
    assert _verdict(current, "agencies", payload) == _verdict(old, "agencies", payload) == ("reject", None)


@pytest.mark.parametrize(
    "field,value",
    [("count", True), ("count", -1), ("count", 2.5), ("name", ""), ("name", " padded "), ("name", "Literal")],
)
def test_facet_field_mutations_preserve_verdicts(field, value):
    facets = json.loads(FACETS)
    facets["RULE"][field] = value
    payload = json.dumps(facets).encode()
    assert _verdict(current, "facets", payload) == _verdict(old, "facets", payload)


@pytest.mark.parametrize(
    "mutation", ["duplicate", "empty", "unknown", "bad-code", "direct", "missing-items", "version-type"]
)
def test_documented_enum_mutations_preserve_verdicts(mutation):
    document = json.loads(DOCUMENTATION)
    schema = document["components"]["schemas"]["DocumentType"]
    if mutation == "duplicate":
        schema["items"]["enum"].append("RULE")
    elif mutation == "empty":
        schema["items"]["enum"] = []
    elif mutation == "unknown":
        schema["items"]["enum"].append("UNKNOWN")
    elif mutation == "bad-code":
        schema["items"]["enum"][0] = "Rule"
    elif mutation == "direct":
        schema["enum"] = schema.pop("items")["enum"]
    elif mutation == "missing-items":
        schema.pop("items")
    else:
        document["info"]["version"] = None
    payload = json.dumps(document).encode()
    assert _verdict(current, "documentation", payload) == _verdict(old, "documentation", payload) == ("reject", None)


def test_cross_source_agency_mismatch_still_refuses():
    roster = current.parse_agencies_roster(AGENCIES)
    document = json.loads(DOCUMENTATION)
    document["components"]["schemas"]["Agency"]["items"]["enum"].pop()
    payload = json.dumps(document).encode()
    for module in (current, old):
        with pytest.raises(module.FRSourceDriftError):
            module.crosscheck_documented_agency_slugs(
                payload, roster, documentation_pin=_pin(module, payload, module.FR_API_DOCUMENTATION_URL)
            )


# Decoder ambiguity and unsupported enum shapes now refuse explicitly; they are
# not changes to a receiver's vocabulary or graph acceptance policy.
INTENTIONAL_DIVERGENCES = (
    "duplicate-json-field",
    "utf16-json",
    "nonfinite-json",
    "overflow-json",
    "malformed-unselected-enum",
)


@pytest.mark.parametrize("name", INTENTIONAL_DIVERGENCES)
def test_named_decoder_divergences(name):
    family = "documentation"
    if name == "duplicate-json-field":
        payload = DOCUMENTATION.replace(b'"openapi":', b'"openapi":"ignored","openapi":', 1)
        assert payload != DOCUMENTATION
    elif name == "utf16-json":
        payload = DOCUMENTATION.decode().encode("utf-16")
    elif name == "nonfinite-json":
        payload = DOCUMENTATION[:-1] + b',"unknown":NaN}'
    elif name == "overflow-json":
        payload = DOCUMENTATION[:-1] + b',"unknown":1e9999}'
    else:
        document = json.loads(DOCUMENTATION)
        document["components"]["schemas"]["Unused"] = {"enum": "not-an-array"}
        payload = json.dumps(document).encode()
    assert _verdict(old, family, payload)[0] == "accept"
    assert _verdict(current, family, payload) == ("reject", None)
