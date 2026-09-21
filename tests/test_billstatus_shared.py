"""Old billstatus guide parser kept as an oracle for the shared guide-reader adoption.

Every mutation runs through both the frozen parser and the new shared reader; verdicts must agree
except for the five named DELIBERATE_DIVERGENCES, where the new reader refuses ambiguous or
malformed later blocks the old first-match parser skipped."""

from pathlib import Path

import _billstatus_parser_oracle as old
import pytest

from refspec.registry import billstatus_codes as bs

SOURCE = (Path(__file__).parent / "fixtures" / "billstatus_codes" / "billstatus-xml-user-guide-2026-08-03.md").read_bytes()
ACTION = b"| **B00100** | Sponsor introductory remarks on measure |"
SUMMARY = b"| **00** | HOUSE | Introduced in House |"

# The new source reader observes every supported table/statement and refuses
# ambiguous or malformed later blocks that the old first-match parser skipped.
DELIBERATE_DIVERGENCES = {
    "malformed_action_types": (True, False),
    "malformed_title_types": (True, False),
    "second_table_in_section": (True, False),
    "malformed_repeated_bill_type": (True, False),
    "malformed_repeated_action_section": (True, False),
}

MUTATIONS = {
    "original": SOURCE,
    "utf8_prefix": "Résumé\n".encode() + SOURCE,
    "crlf": SOURCE.replace(b"\n", b"\r\n"),
    "unknown_bill_type_shape": SOURCE.replace(b"values are H, S", b"values are lower, S", 1),
    "repinned_hr_spelling": SOURCE.replace(b"values are H, S", b"values are HR, S", 1),
    "empty_bill_type_token": SOURCE.replace(b"values are H, S", b"values are H, , S", 1),
    "first_and_not_a_conjunction": SOURCE.replace(b"values are H, S", b"values are and H, S", 1),
    "tab_after_conjunction": SOURCE.replace(b", and SCONRES", b", and\tSCONRES", 1),
    "unicode_sentence_prefix": SOURCE.replace(b"Bill type (Possible", "\u00a0Bill type (Possible".encode(), 1),
    "unicode_sentence_suffix": SOURCE.replace(b"and SCONRES).", "and SCONRES).\u00a0".encode(), 1),
    "unicode_sentence_blank_line": SOURCE.replace(b"### `<billType>`\n\n", "### `<billType>`\n\u00a0\n".encode(), 1),
    "unicode_table_prefix": SOURCE.replace(ACTION, "\u00a0".encode() + ACTION, 1),
    "unicode_table_suffix": SOURCE.replace(ACTION, ACTION + "\u00a0".encode(), 1),
    "duplicate_bill_type": SOURCE.replace(b"values are H, S", b"values are H, H", 1),
    "missing_bill_type_heading": SOURCE.replace(b"### `<billType>`", b"### `<different>`", 1),
    "bill_type_sentence_outside_old_window": SOURCE.replace(b"### `<billType>`\n", b"### `<billType>`\n\n\n\n\n\n", 1),
    "bill_type_wording": SOURCE.replace(b"Bill type (Possible values are", b"Bill type (Values include", 1),
    "action_label_unicode": SOURCE.replace(b"Sponsor introductory remarks", "Résumé remarks".encode(), 1),
    "bold_action_label": SOURCE.replace(ACTION, b"| **B00100** | **Sponsor introductory remarks on measure** |", 1),
    "new_action_code_shape_valid": SOURCE.replace(b"**B00100**", b"**Z99999**", 1),
    "action_code_shape_invalid": SOURCE.replace(b"**B00100**", b"**z?**", 1),
    "action_no_bold": SOURCE.replace(b"**B00100**", b"B00100", 1),
    "action_empty_bold": SOURCE.replace(b"**B00100**", b"****", 1),
    "action_duplicate": SOURCE.replace(ACTION, ACTION + b"\n" + ACTION, 1),
    "action_empty_label": SOURCE.replace(ACTION, b"| **B00100** | |", 1),
    "action_missing_row": SOURCE.replace(ACTION + b"\n", b"", 1),
    "action_extra_column": SOURCE.replace(ACTION, ACTION + b" extra |", 1),
    "action_escaped_pipe": SOURCE.replace(ACTION, b"| **B00100** | a\\|b |", 1),
    "action_header_label": SOURCE.replace(b"| Code | Text in the `<actionCode>` Element |", b"| Other | Other |", 1),
    "missing_action_heading": SOURCE.replace(b"# 3. Action Code Element Possible Values", b"# 3. Changed", 1),
    "action_bad_separator": SOURCE.replace(b"| --- | --- |", b"| bad | --- |", 1),
    "summary_unknown_chamber": SOURCE.replace(SUMMARY, b"| **00** | FUTURE | Introduced in House |", 1),
    "summary_duplicate_pair": SOURCE.replace(SUMMARY, b"| **00** | SENATE | Introduced in House |", 1),
    "summary_bad_code": SOURCE.replace(SUMMARY, b"| **000** | HOUSE | Introduced in House |", 1),
    "summary_empty_label": SOURCE.replace(SUMMARY, b"| **00** | HOUSE | |", 1),
    "summary_missing_row": SOURCE.replace(SUMMARY + b"\n", b"", 1),
    "missing_courtesy_prose": SOURCE.replace(b"It is provided as a courtesy; a complete, authoritative list of action codes does not exist.", b"", 1),
    "unknown_action_type": SOURCE.replace(b"| Actions by the President |", b"| UnfamiliarSourceValue |", 1),
    "unknown_title_type": SOURCE.replace(b"| **01** | Official Title as Introduced |", b"| **new?** | Strange title |", 1),
    "malformed_action_types": SOURCE.replace(b"| Actions by the President |", b"| extra | column |", 1),
    "malformed_title_types": SOURCE.replace(b"| **01** | Official Title as Introduced |", b"| extra | column | added |", 1),
    "second_table_in_section": SOURCE.replace(b"# 4. Actions Type", b"| Code | Value |\n| --- | --- |\n| extra | value |\n\n# 4. Actions Type", 1),
    "repeated_bill_type": SOURCE + b"\n### `<billType>`\nBill type (Possible values are OTHER).\n",
    "malformed_repeated_bill_type": SOURCE + b"\n### `<billType>`\nwrong sentence\n",
    "malformed_repeated_action_section": SOURCE + b"\n# 3. Action Code Element Possible Values\nno table\n",
    "invalid_utf8": SOURCE + b"\xff",
}


def acquired(tmp_path, payload):
    """Pin and acquire a mutation payload so either parser can read it as the real source."""

    pin = bs.BillStatusSnapshotPin(
        source=bs.BILLSTATUS_USER_GUIDE,
        retrieved_at=bs.BILLSTATUS_USER_GUIDE_2026_08_03.retrieved_at,
        expected_sha256=bs.sha256_digest(payload),
        expected_byte_length=len(payload),
    )
    path = tmp_path / "source.md"
    path.write_bytes(payload)
    return bs.acquire_billstatus_source(pin, tmp_path / "store", source_path=path)


@pytest.mark.parametrize("name,payload", MUTATIONS.items())
def test_real_guide_and_mutation_verdicts_match_frozen_parser_except_named_cases(tmp_path, name, payload):
    """Every mutation must agree with the frozen parser, except the five named divergences."""

    try:
        source = acquired(tmp_path, payload)
    except bs.BillStatusSourceDriftError:
        assert name == "invalid_utf8"
        return
    outcomes, results = [], []
    for parser in (old.parse_billstatus_code_sets, bs.parse_billstatus_code_sets):
        try:
            results.append(parser(source))
        except bs.BillStatusSourceDriftError:
            outcomes.append(False)
        else:
            outcomes.append(True)
    if name in DELIBERATE_DIVERGENCES:
        assert tuple(outcomes) == DELIBERATE_DIVERGENCES[name]
    else:
        assert outcomes[0] == outcomes[1], name
        if outcomes[0]:
            assert results[0] == results[1]


def test_frozen_divergence_names_are_exercised():
    assert DELIBERATE_DIVERGENCES.keys() <= MUTATIONS.keys()
