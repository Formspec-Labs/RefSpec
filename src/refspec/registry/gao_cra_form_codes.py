"""GAO's numbered CRA submission form: the documented rule types and the
retired revision's Priority of Regulation levels.

REF-032 removed the observed GAO CRA facet inventory: six radio-button
widgets scraped out of the CRA *database search page*. What GAO actually
publishes is a numbered form -- GAO Form 41217, "Submission of Federal Rules
Under the Congressional Review Act" -- whose printed option lists are
publisher-written statements, not search-widget mechanics. This module reads
two pinned revisions of that form:

* the current **Rev. 12/24** revision, whose item 6 documents five rule
  types (Draft Rule, Final Rule, Draft Guideline, Final Guideline, Other);
* the retired **Rev. 11/17/23** revision, whose item 8 documents the five
  Priority of Regulation levels the current revision DROPPED. The retired
  revision is the last publisher statement of that list, and the current
  form's bytes are checked to still omit it.

The module also reads pinned report GAO-09-205. That report ties GAO's
CRA-form-backed Federal Rules Database to the Unified Agenda priority
categories used by the mapping release. It supplies institutional evidence;
it does not add another form vocabulary.

The current revision's download URL carries the publisher's own typo
("Sumission"); it is preserved exactly because it is the publisher's URL.

PDF is not a data format: both parses fold the text layer's presentation
forms (``fold_pdf_text``), normalize whitespace, and then require the exact
reviewed option runs verbatim -- any wording drift refuses to parse rather
than guessing. The printed option text (including list joiners such as
``"; or"`` and the ``"(specify)"`` fill-in instruction) is retained beside
each parsed value.

Both captures were fetched through the shared Zyte transport because gao.gov
refuses plain clients (HTTP 403). Importing this module performs no network
access.
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from typing import Literal

from refspec.pdf_text import fold_pdf_text

GAO_PUBLISHER = "U.S. Government Accountability Office"
GAO_FORM_NUMBER = "GAO Form 41217"

# The publisher's own URL for the current revision misspells "Submission" as
# "Sumission". The typo is the publisher's; correcting it would break the URL.
GAO_CRA_CURRENT_FORM_URL = (
    "https://www.gao.gov/assets/2025-01/"
    "Sumission%20of%20Federal%20Rules%20Under%20the%20Congressional%20Review"
    "%20Act%20-%202025.pdf"
)
GAO_CRA_RETIRED_FORM_URL = "https://www.gao.gov/assets/2023-11/Blank%20CRA%20Form-Updated.pdf"
GAO_CRA_INSTITUTIONAL_BRIDGE_URL = "https://www.gao.gov/assets/gao-09-205.pdf"

GAO_CRA_CURRENT_REVISION = "Rev. 12/24"
GAO_CRA_RETIRED_REVISION = "11/17/23"

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")

FormRevisionKind = Literal["currentForm", "retiredForm"]


class GaoCraFormError(ValueError):
    """Base class for GAO CRA submission-form failures."""


class GaoCraFormSourceDriftError(GaoCraFormError):
    """A pinned form revision no longer matches the reviewed bytes or wording."""


@dataclass(frozen=True, slots=True)
class GaoCraInstitutionalEvidencePin:
    """Exact identity of the GAO report used as institutional evidence."""

    report_number: str
    source_url: str
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int

    def __post_init__(self) -> None:
        if not self.source_url.startswith("https://www.gao.gov/"):
            raise GaoCraFormError("source_url must be an official HTTPS gao.gov URL")
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise GaoCraFormError(
                "expected_sha256 must be a lowercase sha256:<64 hex> digest"
            )
        if self.expected_byte_length <= 0:
            raise GaoCraFormError("expected_byte_length must be positive")
        if not self.retrieved_at or not self.report_number:
            raise GaoCraFormError("retrieved_at and report_number must not be empty")


@dataclass(frozen=True, slots=True)
class GaoCraFormPin:
    """Exact identity of one captured gao.gov form revision."""

    form_kind: FormRevisionKind
    source_url: str
    revision: str
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int

    def __post_init__(self) -> None:
        if not self.source_url.startswith("https://www.gao.gov/"):
            raise GaoCraFormError("source_url must be an official HTTPS gao.gov URL")
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise GaoCraFormError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise GaoCraFormError("expected_byte_length must be positive")
        if not self.retrieved_at or not self.revision:
            raise GaoCraFormError("retrieved_at and revision must not be empty")


# Exact bytes fetched 2026-08-15 through the shared Zyte transport (gao.gov
# returns HTTP 403 to plain HTTPS clients).
GAO_CRA_CURRENT_FORM_2026_08_15 = GaoCraFormPin(
    form_kind="currentForm",
    source_url=GAO_CRA_CURRENT_FORM_URL,
    revision=GAO_CRA_CURRENT_REVISION,
    retrieved_at="2026-08-15T13:56:56Z",
    expected_sha256="sha256:400be25fbd9d426472118af1aafd830aee16d40248a4a89da4465ef69f18bafa",
    expected_byte_length=354_320,
)
GAO_CRA_RETIRED_FORM_2026_08_15 = GaoCraFormPin(
    form_kind="retiredForm",
    source_url=GAO_CRA_RETIRED_FORM_URL,
    revision=GAO_CRA_RETIRED_REVISION,
    retrieved_at="2026-08-15T13:57:12Z",
    expected_sha256="sha256:4dc381d7305111a92c9cc1334e6e523fa0c3f719518f6784145b91e83a591d9d",
    expected_byte_length=111_887,
)
GAO_CRA_INSTITUTIONAL_BRIDGE_2026_08_15 = GaoCraInstitutionalEvidencePin(
    report_number="GAO-09-205",
    source_url=GAO_CRA_INSTITUTIONAL_BRIDGE_URL,
    retrieved_at="2026-08-15",
    expected_sha256=(
        "sha256:7cb03a0114456ccfaf4d4071f92ea7a6b1a3d286ec2da4de58a1ba9d0ed63277"
    ),
    expected_byte_length=1_869_486,
)


@dataclass(frozen=True, slots=True)
class GaoCraFormOption:
    """One documented option exactly as the form's numbered item states it."""

    value: str
    option_text: str
    form_item: str
    source_ordinal: int


# Item 6 of the current Rev. 12/24 form: "Indicate whether this rule is one of
# the following". The printed option "Other (specify)" names the type "Other";
# "(specify)" is the form's fill-in instruction and travels in option_text.
GAO_CRA_RULE_TYPE_OPTIONS: tuple[GaoCraFormOption, ...] = (
    GaoCraFormOption("Draft Rule", "Draft Rule", "6", 1),
    GaoCraFormOption("Final Rule", "Final Rule", "6", 2),
    GaoCraFormOption("Draft Guideline", "Draft Guideline", "6", 3),
    GaoCraFormOption("Final Guideline", "Final Guideline", "6", 4),
    GaoCraFormOption("Other", "Other (specify)", "6", 5),
)
_RULE_TYPE_RUN = (
    "6. Indicate whether this rule is one of the following: "
    "Draft Rule Final Rule Draft Guideline Final Guideline Other (specify)"
)

# Item 8 of the retired Rev. 11/17/23 form: "Priority of Regulation (fill in
# one)". The "; or" / "or" joiners are the form's list syntax and travel in
# option_text; the parenthetical instruction after the final pair is the
# form's own routing note, retained on the capture.
GAO_CRA_PRIORITY_OPTIONS: tuple[GaoCraFormOption, ...] = (
    GaoCraFormOption("Economically Significant", "Economically Significant; or", "8", 1),
    GaoCraFormOption("Significant", "Significant; or", "8", 2),
    GaoCraFormOption("Substantive, Nonsignificant", "Substantive, Nonsignificant", "8", 3),
    GaoCraFormOption("Routine and Frequent", "Routine and Frequent or", "8", 4),
    GaoCraFormOption(
        "Informational/Administrative/Other",
        "Informational/Administrative/Other",
        "8",
        5,
    ),
)
_PRIORITY_RUN = (
    "8. Priority of Regulation (fill in one) "
    "Economically Significant; or Significant; or Substantive, Nonsignificant "
    "Routine and Frequent or Informational/Administrative/Other "
    "(Do not complete the other side of this form if filled in above.)"
)
GAO_CRA_PRIORITY_ROUTING_NOTE = "(Do not complete the other side of this form if filled in above.)"

# Reviewed anchors that back the release metadata's claims about each
# revision. "Priority of Regulation" must stay absent from the current bytes
# for the dropped-item claim to hold; the major/non-major dichotomy is
# present on both revisions and deliberately not emitted (the major-rule
# definition belongs to 5 U.S.C. 804(2), not to GAO's form).
_CURRENT_MAJOR_RUN = "Major* Non-Major"
_RETIRED_MAJOR_RUN = "Major Rule Non-major Rule"
_PRIORITY_ANCHOR = "Priority of Regulation"


@dataclass(frozen=True, slots=True)
class GaoCraCurrentFormCapture:
    """The parsed, digest-pinned current Rev. 12/24 submission form."""

    rule_types: tuple[GaoCraFormOption, ...]
    priority_item_absent: bool
    major_dichotomy_text: str
    source_url: str
    revision: str
    retrieved_at: str
    source_sha256: str
    source_byte_length: int


@dataclass(frozen=True, slots=True)
class GaoCraRetiredFormCapture:
    """The parsed, digest-pinned retired Rev. 11/17/23 submission form."""

    priority_levels: tuple[GaoCraFormOption, ...]
    priority_routing_note: str
    major_dichotomy_text: str
    source_url: str
    revision: str
    retrieved_at: str
    source_sha256: str
    source_byte_length: int


@dataclass(frozen=True, slots=True)
class GaoCraInstitutionalBridgeCapture:
    """The verified GAO statements that connect CRA data to Agenda priority."""

    report_number: str
    records: tuple[str, ...]
    source_url: str
    retrieved_at: str
    source_sha256: str
    source_byte_length: int


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec SHA-256 spelling."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _verified_normalized_text(payload: bytes, pin: GaoCraFormPin) -> str:
    if len(payload) != pin.expected_byte_length:
        raise GaoCraFormSourceDriftError(
            f"GAO CRA {pin.form_kind} byte length drift: "
            f"expected {pin.expected_byte_length}, got {len(payload)}"
        )
    actual = sha256_digest(payload)
    if actual != pin.expected_sha256:
        raise GaoCraFormSourceDriftError(
            f"GAO CRA {pin.form_kind} digest drift: expected {pin.expected_sha256}, got {actual}"
        )
    if payload[:5] != b"%PDF-":
        raise GaoCraFormSourceDriftError(f"GAO CRA {pin.form_kind} no longer starts with a PDF header")
    try:
        from pypdf import PdfReader
    except ImportError as error:  # pragma: no cover - dependency gate
        raise GaoCraFormSourceDriftError("pypdf is required to read the GAO CRA form text layer") from error
    try:
        reader = PdfReader(io.BytesIO(payload))
        text = " ".join(
            " ".join(fold_pdf_text(page.extract_text() or "").split()) for page in reader.pages
        )
    except Exception as error:  # pragma: no cover - unreadable pinned source
        raise GaoCraFormSourceDriftError(f"GAO CRA {pin.form_kind} text layer is unreadable") from error
    if pin.revision not in text:
        raise GaoCraFormSourceDriftError(
            f"GAO CRA {pin.form_kind} no longer states revision {pin.revision!r}"
        )
    return text


def _require_run(text: str, run: str, *, form_kind: str, what: str) -> None:
    if run not in text:
        raise GaoCraFormSourceDriftError(
            f"GAO CRA {form_kind} no longer states the reviewed {what}: {run!r}"
        )


def _current_form_capture_from_text(text: str, *, pin: GaoCraFormPin) -> GaoCraCurrentFormCapture:
    """Build the current-form capture from already-verified normalized text.

    ``priority_item_absent`` is derived from the text itself -- the parse
    measures the anchor's absence and refuses when it reappears -- so the
    dropped-item claim on the retired revision's release is re-verified from
    the bytes on every parse, never restated as a literal.
    """

    _require_run(text, f"{GAO_FORM_NUMBER} ({pin.revision})", form_kind=pin.form_kind, what="form number")
    _require_run(text, _RULE_TYPE_RUN, form_kind=pin.form_kind, what="item 6 rule-type option list")
    _require_run(text, _CURRENT_MAJOR_RUN, form_kind=pin.form_kind, what="major/non-major dichotomy")
    priority_item_absent = _PRIORITY_ANCHOR not in text
    if not priority_item_absent:
        raise GaoCraFormSourceDriftError(
            "GAO CRA currentForm states a Priority of Regulation item again; the "
            "dropped-item claim on the retired revision's release no longer holds"
        )
    return GaoCraCurrentFormCapture(
        rule_types=GAO_CRA_RULE_TYPE_OPTIONS,
        priority_item_absent=priority_item_absent,
        major_dichotomy_text=_CURRENT_MAJOR_RUN,
        source_url=pin.source_url,
        revision=pin.revision,
        retrieved_at=pin.retrieved_at,
        source_sha256=pin.expected_sha256,
        source_byte_length=pin.expected_byte_length,
    )


def parse_gao_cra_current_form(
    payload: bytes,
    *,
    pin: GaoCraFormPin = GAO_CRA_CURRENT_FORM_2026_08_15,
) -> GaoCraCurrentFormCapture:
    """Parse the current revision's documented rule types from exact bytes."""

    if pin.form_kind != "currentForm":
        raise GaoCraFormError("parse_gao_cra_current_form requires a currentForm pin")
    text = _verified_normalized_text(payload, pin)
    return _current_form_capture_from_text(text, pin=pin)


def parse_gao_cra_retired_form(
    payload: bytes,
    *,
    pin: GaoCraFormPin = GAO_CRA_RETIRED_FORM_2026_08_15,
) -> GaoCraRetiredFormCapture:
    """Parse the retired revision's documented Priority of Regulation levels."""

    if pin.form_kind != "retiredForm":
        raise GaoCraFormError("parse_gao_cra_retired_form requires a retiredForm pin")
    text = _verified_normalized_text(payload, pin)
    _require_run(
        text,
        "Submission of Federal Rules Under the Congressional Review Act",
        form_kind=pin.form_kind,
        what="form title",
    )
    _require_run(text, _PRIORITY_RUN, form_kind=pin.form_kind, what="item 8 priority option list")
    _require_run(text, _RETIRED_MAJOR_RUN, form_kind=pin.form_kind, what="major/non-major dichotomy")
    return GaoCraRetiredFormCapture(
        priority_levels=GAO_CRA_PRIORITY_OPTIONS,
        priority_routing_note=GAO_CRA_PRIORITY_ROUTING_NOTE,
        major_dichotomy_text=_RETIRED_MAJOR_RUN,
        source_url=pin.source_url,
        revision=pin.revision,
        retrieved_at=pin.retrieved_at,
        source_sha256=pin.expected_sha256,
        source_byte_length=pin.expected_byte_length,
    )


def parse_gao_cra_institutional_bridge(
    payload: bytes,
    *,
    pin: GaoCraInstitutionalEvidencePin = (
        GAO_CRA_INSTITUTIONAL_BRIDGE_2026_08_15
    ),
) -> GaoCraInstitutionalBridgeCapture:
    """Parse the report statements that license the institutional bridge."""

    if len(payload) != pin.expected_byte_length:
        raise GaoCraFormSourceDriftError(
            "GAO CRA institutional evidence byte length drift: "
            f"expected {pin.expected_byte_length}, got {len(payload)}"
        )
    actual = sha256_digest(payload)
    if actual != pin.expected_sha256:
        raise GaoCraFormSourceDriftError(
            "GAO CRA institutional evidence digest drift: "
            f"expected {pin.expected_sha256}, got {actual}"
        )
    if payload[:5] != b"%PDF-":
        raise GaoCraFormSourceDriftError(
            "GAO CRA institutional evidence no longer starts with a PDF header"
        )
    try:
        from pypdf import PdfReader
    except ImportError as error:  # pragma: no cover - dependency gate
        raise GaoCraFormSourceDriftError(
            "pypdf is required to read the GAO institutional evidence"
        ) from error
    try:
        reader = PdfReader(io.BytesIO(payload))
        text = " ".join(
            " ".join(fold_pdf_text(page.extract_text() or "").split())
            for page in reader.pages
        )
    except Exception as error:  # pragma: no cover - unreadable pinned source
        raise GaoCraFormSourceDriftError(
            "GAO CRA institutional evidence text layer is unreadable"
        ) from error
    records = (
        "GAO established a database and created a standardized submission form",
        "priority of the rule (for example, whether it is a significant rule)",
        "We randomly selected 16 major or other significant final rules",
        (
            "As defined in the Introduction to The Regulatory Plan and the "
            "Unified Agenda of Federal Regulatory and Deregulatory Actions"
        ),
    )
    missing = [record for record in records if record not in text]
    if missing:
        raise GaoCraFormSourceDriftError(
            "GAO institutional evidence no longer states the reviewed CRA-form "
            f"and Unified Agenda link: {missing!r}"
        )
    return GaoCraInstitutionalBridgeCapture(
        report_number=pin.report_number,
        records=records,
        source_url=pin.source_url,
        retrieved_at=pin.retrieved_at,
        source_sha256=pin.expected_sha256,
        source_byte_length=pin.expected_byte_length,
    )


__all__ = [
    "GAO_CRA_CURRENT_FORM_2026_08_15",
    "GAO_CRA_CURRENT_FORM_URL",
    "GAO_CRA_CURRENT_REVISION",
    "GAO_CRA_INSTITUTIONAL_BRIDGE_2026_08_15",
    "GAO_CRA_INSTITUTIONAL_BRIDGE_URL",
    "GAO_CRA_PRIORITY_OPTIONS",
    "GAO_CRA_PRIORITY_ROUTING_NOTE",
    "GAO_CRA_RETIRED_FORM_2026_08_15",
    "GAO_CRA_RETIRED_FORM_URL",
    "GAO_CRA_RETIRED_REVISION",
    "GAO_CRA_RULE_TYPE_OPTIONS",
    "GAO_FORM_NUMBER",
    "GAO_PUBLISHER",
    "GaoCraCurrentFormCapture",
    "GaoCraFormError",
    "GaoCraFormOption",
    "GaoCraFormPin",
    "GaoCraFormSourceDriftError",
    "GaoCraInstitutionalBridgeCapture",
    "GaoCraInstitutionalEvidencePin",
    "GaoCraRetiredFormCapture",
    "parse_gao_cra_current_form",
    "parse_gao_cra_institutional_bridge",
    "parse_gao_cra_retired_form",
    "sha256_digest",
]
