"""GAO CRA submission-form tests: two pinned revisions of GAO Form 41217.

The current Rev. 12/24 revision documents the rule types; the retired
Rev. 11/17/23 revision is the last publisher statement of the Priority of
Regulation levels the current revision dropped. Neither parse ever guesses:
option wording is verified verbatim against the folded text layer, and any
drift refuses.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from refspec.registry import gao_cra_form_codes as gao

FIXTURES = Path(__file__).parent / "fixtures" / "gao_cra_form_codes"
CURRENT_FIXTURE = FIXTURES / "gao-cra-submission-form-rev-12-24-2026-08-15.pdf"
RETIRED_FIXTURE = FIXTURES / "gao-cra-blank-form-rev-11-17-23-2026-08-15.pdf"


def test_pins_match_the_exact_captured_bytes() -> None:
    current = CURRENT_FIXTURE.read_bytes()
    retired = RETIRED_FIXTURE.read_bytes()

    assert len(current) == 354_320
    assert gao.sha256_digest(current) == (
        "sha256:400be25fbd9d426472118af1aafd830aee16d40248a4a89da4465ef69f18bafa"
    )
    assert len(retired) == 111_887
    assert gao.sha256_digest(retired) == (
        "sha256:4dc381d7305111a92c9cc1334e6e523fa0c3f719518f6784145b91e83a591d9d"
    )


def test_current_form_url_preserves_the_publishers_own_typo() -> None:
    """The publisher's download URL misspells "Submission" as "Sumission".
    Correcting the spelling would break the URL, so it is pinned as-is."""

    assert "Sumission" in gao.GAO_CRA_CURRENT_FORM_URL
    assert gao.GAO_CRA_CURRENT_FORM_URL.startswith("https://www.gao.gov/assets/2025-01/")
    assert gao.GAO_CRA_CURRENT_FORM_URL.endswith(".pdf")


def test_current_form_documents_five_rule_types_and_no_priority_item() -> None:
    capture = gao.parse_gao_cra_current_form(CURRENT_FIXTURE.read_bytes())

    assert [option.value for option in capture.rule_types] == [
        "Draft Rule",
        "Final Rule",
        "Draft Guideline",
        "Final Guideline",
        "Other",
    ]
    # The printed option text keeps the form's fill-in instruction.
    assert capture.rule_types[-1].option_text == "Other (specify)"
    assert {option.form_item for option in capture.rule_types} == {"6"}
    assert capture.revision == "Rev. 12/24"
    # The dropped-item claim on the retired revision's release rests on this.
    assert capture.priority_item_absent is True
    assert capture.source_url == gao.GAO_CRA_CURRENT_FORM_URL
    assert capture.source_sha256.startswith("sha256:")


def test_retired_form_documents_the_five_priority_levels_verbatim() -> None:
    capture = gao.parse_gao_cra_retired_form(RETIRED_FIXTURE.read_bytes())

    assert [option.value for option in capture.priority_levels] == [
        "Economically Significant",
        "Significant",
        "Substantive, Nonsignificant",
        "Routine and Frequent",
        "Informational/Administrative/Other",
    ]
    # The "; or" / "or" joiners are the form's printed list syntax and are
    # retained beside the values, never folded into them.
    assert [option.option_text for option in capture.priority_levels] == [
        "Economically Significant; or",
        "Significant; or",
        "Substantive, Nonsignificant",
        "Routine and Frequent or",
        "Informational/Administrative/Other",
    ]
    assert {option.form_item for option in capture.priority_levels} == {"8"}
    assert capture.revision == "11/17/23"
    assert capture.priority_routing_note == (
        "(Do not complete the other side of this form if filled in above.)"
    )
    assert capture.major_dichotomy_text == "Major Rule Non-major Rule"


def test_current_form_refuses_if_priority_of_regulation_reappears() -> None:
    """The dropped-item claim is re-verified from the text, not restated.

    The reviewer's recipe: merge a retired-form page (which states the
    Priority of Regulation item) into a copy of the current form's text and
    assert the current-form parse refuses. ``priority_item_absent`` is
    derived from that same measurement, so the flag can never say "absent"
    over text where the item is present.
    """

    current_text = gao._verified_normalized_text(
        CURRENT_FIXTURE.read_bytes(), gao.GAO_CRA_CURRENT_FORM_2026_08_15
    )
    retired_text = gao._verified_normalized_text(
        RETIRED_FIXTURE.read_bytes(), gao.GAO_CRA_RETIRED_FORM_2026_08_15
    )
    # The retired revision really does state the item this test re-imports.
    assert "Priority of Regulation" in retired_text
    assert "Priority of Regulation" not in current_text

    merged = f"{current_text} {retired_text}"
    with pytest.raises(gao.GaoCraFormSourceDriftError, match="Priority of Regulation item again"):
        gao._current_form_capture_from_text(merged, pin=gao.GAO_CRA_CURRENT_FORM_2026_08_15)

    # On the real current text the flag is the measured absence, not a literal.
    capture = gao._current_form_capture_from_text(
        current_text, pin=gao.GAO_CRA_CURRENT_FORM_2026_08_15
    )
    assert capture.priority_item_absent is True


def test_byte_drift_is_refused_before_any_text_is_parsed() -> None:
    payload = bytearray(CURRENT_FIXTURE.read_bytes())
    payload[1000] ^= 0xFF

    with pytest.raises(gao.GaoCraFormSourceDriftError, match="digest drift"):
        gao.parse_gao_cra_current_form(bytes(payload))

    with pytest.raises(gao.GaoCraFormSourceDriftError, match="byte length drift"):
        gao.parse_gao_cra_retired_form(RETIRED_FIXTURE.read_bytes() + b"x")


def test_wording_drift_in_a_repinned_revision_is_refused() -> None:
    """A re-pinned capture whose bytes verify but whose text no longer states
    the reviewed option run must refuse, not emit a guessed list."""

    retired = RETIRED_FIXTURE.read_bytes()
    fake_current_pin = replace(
        gao.GAO_CRA_CURRENT_FORM_2026_08_15,
        expected_sha256=gao.sha256_digest(retired),
        expected_byte_length=len(retired),
        revision="11/17/23",
    )
    # The retired bytes carry no Rev. 12/24 rule-type run.
    with pytest.raises(gao.GaoCraFormSourceDriftError, match="form number"):
        gao.parse_gao_cra_current_form(retired, pin=fake_current_pin)

    current = CURRENT_FIXTURE.read_bytes()
    fake_retired_pin = replace(
        gao.GAO_CRA_RETIRED_FORM_2026_08_15,
        expected_sha256=gao.sha256_digest(current),
        expected_byte_length=len(current),
        revision="Rev. 12/24",
    )
    # The current bytes carry no Priority of Regulation item.
    with pytest.raises(gao.GaoCraFormSourceDriftError, match="priority option list"):
        gao.parse_gao_cra_retired_form(current, pin=fake_retired_pin)


def test_non_pdf_bytes_are_refused() -> None:
    fake = b"not a pdf" + b"x" * (354_320 - 9)
    pin = replace(
        gao.GAO_CRA_CURRENT_FORM_2026_08_15,
        expected_sha256=gao.sha256_digest(fake),
        expected_byte_length=len(fake),
    )

    with pytest.raises(gao.GaoCraFormSourceDriftError, match="PDF header"):
        gao.parse_gao_cra_current_form(fake, pin=pin)


def test_pin_shape_is_validated() -> None:
    with pytest.raises(gao.GaoCraFormError, match="gao.gov"):
        replace(gao.GAO_CRA_CURRENT_FORM_2026_08_15, source_url="https://example.com/form.pdf")
    with pytest.raises(gao.GaoCraFormError, match="sha256"):
        replace(gao.GAO_CRA_CURRENT_FORM_2026_08_15, expected_sha256="sha256:short")
    with pytest.raises(gao.GaoCraFormError, match="requires a currentForm pin"):
        gao.parse_gao_cra_current_form(b"%PDF-", pin=gao.GAO_CRA_RETIRED_FORM_2026_08_15)
    with pytest.raises(gao.GaoCraFormError, match="requires a retiredForm pin"):
        gao.parse_gao_cra_retired_form(b"%PDF-", pin=gao.GAO_CRA_CURRENT_FORM_2026_08_15)


def test_module_never_imports_a_network_transport() -> None:
    """The captures were fetched once through the shared Zyte transport; the
    reader itself must stay import-safe with no transport dependency."""

    source = Path(gao.__file__).read_text(encoding="utf-8")
    assert "zyte" not in source.lower().replace("the shared zyte transport", "")
    assert "urllib.request" not in source
    assert "import requests" not in source
