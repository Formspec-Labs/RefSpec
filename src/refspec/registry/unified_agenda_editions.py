"""The Unified Agenda's per-edition RIN export, read fail-closed from pinned bytes.

The Regulatory Information Service Center publishes one XML file per agenda
edition at ``XMLViewFileAction?f=REGINFO_RIN_DATA_{edition}.xml``. Each file
is a single ``<REGINFO_RIN_DATA>`` root containing one ``<RIN_INFO>`` per
regulatory action, and every record carries ``CFR_LIST`` and
``LEGAL_AUTHORITY_LIST`` -- the publisher's own structured statement of which
CFR parts an action touches and which statutes authorise it.

**Why the whole series and not the current edition.** A single edition is a
snapshot of what was pending on one date; the CFR references accumulate across
editions, and an action that appeared in 2003 and finished in 2005 states its
authorities in both. Holding one edition (202510) gave 3,954 records.
Holding all 60 gives 241,726.

**Three publisher irregularities, all recorded rather than repaired upstream:**

1. ``REGINFO_RIN_DATA_2012.xml`` breaks the ``{YYYYMM}`` naming pattern. Its
   records self-identify as ``PUBLICATION_ID`` 201210, so the file is Fall
   2012 and the filename is not authoritative. Nothing here trusts the name:
   every pin carries the content-derived ``publication_id`` and the reader
   checks it.
2. Spring 2012 (``201204``) does not exist. The twice-yearly series from Fall
   1995 implies 61 editions; 60 are published.
3. Spring and Fall 2004 each contain exactly one ``0x19`` byte where a
   possessive apostrophe belongs (``Department\x19s``, ``bureau\x19s``) -- a
   mangled ``U+2019``, which XML 1.0 forbids as a control character. Two bytes
   in 981 MB. :func:`parse_unified_agenda_edition` substitutes the character
   the publisher meant **at read time**; the pinned digests stay over the
   bytes actually served, so the capture remains exactly what the endpoint
   returned.

**On provenance.** 39 of the 60 files carry ``RUN_DATE="2015-05-18"``: the
pre-2015 archive was regenerated in one export pass, which is why a 1995 file
parses with the same call as a 2025 one. The historical series is one format,
not twenty years of drift.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from xml.etree import ElementTree as ET

__all__ = [
    "CONTINUATION_LABEL_FAMILIES",
    "UNIFIED_AGENDA_EDITION_PINS",
    "UNIFIED_AGENDA_EXPECTED_EDITION_COUNT",
    "UNIFIED_AGENDA_EXPECTED_RECORD_COUNT",
    "UNIFIED_AGENDA_MANGLED_APOSTROPHE_EDITIONS",
    "AuthorityContinuation",
    "TimetableEntry",
    "UnifiedAgendaEditionError",
    "UnifiedAgendaEditionPin",
    "UnifiedAgendaRecord",
    "legal_authority_continuations",
    "parse_unified_agenda_edition",
]

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_ROOT_TAG = "REGINFO_RIN_DATA"
_RECORD_TAG = "RIN_INFO"

#: The publisher's mangled ``U+2019``. Present exactly once in each of the two
#: 2004 editions and nowhere else in the 60-file series -- verified by
#: scanning every byte of all 60 captures for characters XML 1.0 forbids.
#: It is not systematic mojibake: no ``0x1c``/``0x1d``/``0x14`` companions from
#: curly quotes or em dashes appear, so this is two isolated defects.
_MANGLED_APOSTROPHE = b"\x19"
UNIFIED_AGENDA_MANGLED_APOSTROPHE_EDITIONS: tuple[str, ...] = ("200404", "200410")


class UnifiedAgendaEditionError(ValueError):
    """Raised when a pinned edition does not match what this module expects."""


@dataclass(frozen=True)
class UnifiedAgendaEditionPin:
    """Exact identity of one pinned Unified Agenda edition export."""

    file_stem: str
    publication_id: str
    expected_sha256: str
    expected_byte_length: int
    expected_record_count: int
    run_date: str

    def __post_init__(self) -> None:
        if _SHA256.fullmatch(self.expected_sha256) is None:
            raise UnifiedAgendaEditionError("expected_sha256 must be sha256:<64 lowercase hex>")
        if self.expected_byte_length <= 0:
            raise UnifiedAgendaEditionError("expected_byte_length must be positive")
        if self.expected_record_count <= 0:
            raise UnifiedAgendaEditionError("expected_record_count must be positive")
        if not re.fullmatch(r"(19|20)\d{2}(04|10)", self.publication_id):
            raise UnifiedAgendaEditionError(
                f"publication_id must be YYYYMM with MM in 04/10: {self.publication_id!r}"
            )


@dataclass(frozen=True)
class TimetableEntry:
    """One row of a RIN's timetable, exactly as the publisher wrote it.

    ``fr_citation`` is the raw "VV FR PPPPP" string or ``None`` when the row
    carries none — projected future actions usually don't. ``date_text`` keeps
    the publisher's MM/DD/YYYY verbatim, because a projected month is written
    with a zero day ("11/00/2026") and normalizing that would invent a date.
    """

    action: str
    date_text: str
    fr_citation: str | None


@dataclass(frozen=True)
class AuthorityContinuation:
    """One legal-authority list that outran its boxes, as the filer wrote it.

    ``label_family`` is one of :data:`CONTINUATION_LABEL_FAMILIES`; ``marker``
    is the exact label the filer typed, kept because the census counts
    spellings; ``text`` is everything from the marker's end to the boundary,
    whitespace collapsed the way a citation box's is.
    """

    label_family: str
    marker: str
    text: str


@dataclass(frozen=True)
class UnifiedAgendaRecord:
    """One regulatory action, with the publisher's own citation lists."""

    rin: str
    publication_id: str
    cfr_references: tuple[str, ...]
    legal_authorities: tuple[str, ...]
    timetable: tuple[TimetableEntry, ...] = ()
    #: ``ADDITIONAL_INFO`` as published, whitespace INTACT. The XSD declares it
    #: an unrestricted string with no documentation at all
    #: (reginfo-rin-data-ver10262011.xsd line 177), and the filers use it as a
    #: continuation sheet: when a citation list outruns its boxes the rest of
    #: it is typed here under a label. See
    #: :func:`legal_authority_continuations`.
    #:
    #: Whitespace is intact and every other field's is collapsed, deliberately:
    #: this one field carries SEVERAL of the form's fields inside it, and what
    #: separates them is a blank line or the publisher's own "^P" paragraph
    #: mark. Collapsing that erases the only thing that says where one field's
    #: continuation ends.
    additional_info: str = ""


#: What a continuation's label says about which of the form's questions it is
#: answering. Two families, both measured over all 60 pinned editions:
#:
#: * ``legal-authority-cont`` -- "LEGAL AUTHORITY CONT:" and its five other
#:   case-folded spellings ("AUTHORITIES CONT:", "AUTHORITY CONTINUED:",
#:   "Authority Continue.", "Authority (Continued)", "Authority Continued.").
#:   67 records, 17 RINs, 16 editions, 199510-200304.
#: * ``additional-legal-authority`` -- "Additional Legal Authority(ies)",
#:   "Additional legal authority information:" and the one "Continue from #8
#:   Legal Authority" spelling. 31 records, 8 RINs, 11 editions.
#:
#: "STATUTORY DEADLINE CONT:" is a THIRD field's continuation and is not one of
#: these; so is "CFR CITATION(S) CONT:". Two further shapes name the field
#: without saying they are continuing it, and are deliberately NOT read:
#:
#: * a bare "Legal Authority:" label -- 0938-AI52 199804 ("Legal Authority:
#:   PL-105-33, sec 4505 ..."), 0938-AI45 199804, 1090-AA67 199804, and
#:   0701-AA65 in 200104/200110/200204/200210, which says outright "This is the
#:   information for legal authority as it is generally listed. There is some
#:   duplication of information." Restating a field is not continuing it, and
#:   nothing in the label says which of the two a given record is doing.
#: * "Additional authority DOT Order 5660.1A" -- RIN 2125-AD78, 11 editions
#:   199604-200104. No "legal", and the boxes beside it already carry the
#:   statutes; whether an internal DOT order belongs in that field is the
#:   filer's question, not this reader's.
#:
#: Both are recorded here rather than left to be rediscovered; reading either
#: is its own unit with its own measurement.
CONTINUATION_LABEL_FAMILIES = ("legal-authority-cont", "additional-legal-authority")


UNIFIED_AGENDA_EDITION_PINS: tuple[UnifiedAgendaEditionPin, ...] = (
    UnifiedAgendaEditionPin(
        file_stem="199510",
        publication_id="199510",
        expected_sha256="sha256:863fbf2204ab12f622fc4cb7504c4a763f280c78a577edaf5d24a9c4795fc1f2",
        expected_byte_length=18605793,
        expected_record_count=4999,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="199604",
        publication_id="199604",
        expected_sha256="sha256:c216e0d6fd521f03f99c89ec921e6f99f706204a48c442f9d34ed569f828dd47",
        expected_byte_length=17646831,
        expected_record_count=4831,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="199610",
        publication_id="199610",
        expected_sha256="sha256:b6cf5052b2098e14a925458579bdcd0a3e3d33d82f9510b56d2e7caca0a60191",
        expected_byte_length=19373054,
        expected_record_count=4939,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="199704",
        publication_id="199704",
        expected_sha256="sha256:0fcd4b6a833f39ea136cdbf883cbe3475554b100bf1594f56463dc329af218e0",
        expected_byte_length=17690546,
        expected_record_count=4621,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="199710",
        publication_id="199710",
        expected_sha256="sha256:d1cad253f5aabfd400acf2617519124800509d73a7707a4f447e7385251cab87",
        expected_byte_length=18169903,
        expected_record_count=4598,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="199804",
        publication_id="199804",
        expected_sha256="sha256:2591aa51fb142d2e0ff3b7b7fb4056c813e5447d02c784df92dd8c6474e99d99",
        expected_byte_length=18164179,
        expected_record_count=4703,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="199810",
        publication_id="199810",
        expected_sha256="sha256:daa951b9b10a911a31fc5045a2e27138668f80dc8d0e6028da2fe11263245f82",
        expected_byte_length=18861330,
        expected_record_count=4726,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="199904",
        publication_id="199904",
        expected_sha256="sha256:c789e399b0871f58c8f633c782875d5cb18e407dd78992ff99f2bbbc380f45c1",
        expected_byte_length=18511917,
        expected_record_count=4694,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="199910",
        publication_id="199910",
        expected_sha256="sha256:8cf2c3b611c54a92ac2385cad8e337066f9d264a512117e1070f63b4975e00c4",
        expected_byte_length=19567343,
        expected_record_count=4746,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="200004",
        publication_id="200004",
        expected_sha256="sha256:9ff083c2e65b010466a976fdc3f1ec91a0a3681e19f4a89cdb2c8204e232c897",
        expected_byte_length=19264651,
        expected_record_count=4630,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="200010",
        publication_id="200010",
        expected_sha256="sha256:12b68dd01148bfa310b35ca3e7f1110aad8c16b36e20504adaad07263e8a12a2",
        expected_byte_length=20501083,
        expected_record_count=4895,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="200104",
        publication_id="200104",
        expected_sha256="sha256:95aa50ca09dbe1e9867087ca0b7e15b07e4f240b45d968ce9afa8858f92d23ef",
        expected_byte_length=19828602,
        expected_record_count=4723,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="200110",
        publication_id="200110",
        expected_sha256="sha256:7bd66382172fe4cd5ad4435ad1d17637586930e3b86e86edf498d9383359c796",
        expected_byte_length=19843816,
        expected_record_count=4697,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="200204",
        publication_id="200204",
        expected_sha256="sha256:67159e221eb11dc7eb98584052b192b422e2c32faeb28664224708366d654e29",
        expected_byte_length=18364653,
        expected_record_count=4423,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="200210",
        publication_id="200210",
        expected_sha256="sha256:b524ab24b2f3f7250a4ae596966dbc565954fe8c1f19cb8cdd663dd1ca2fbf7d",
        expected_byte_length=18274992,
        expected_record_count=4431,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="200304",
        publication_id="200304",
        expected_sha256="sha256:4608065bfa46e808211174dab5824ad9937bfb8531dd9a88d899aff077221ccb",
        expected_byte_length=19621612,
        expected_record_count=4727,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="200310",
        publication_id="200310",
        expected_sha256="sha256:618f87489050e147c35e0d0a3c810dfac8280c6b631dbd0a5ce633d7031eb058",
        expected_byte_length=18212085,
        expected_record_count=4330,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="200404",
        publication_id="200404",
        expected_sha256="sha256:df0cc8d24c544b3a2d9a0b025cb91973cf598e7cfa9181efa6af4494bbc24562",
        expected_byte_length=17865654,
        expected_record_count=4393,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="200410",
        publication_id="200410",
        expected_sha256="sha256:8f780d499359754ed24dc9aca9f954d7ea4e0df4f772b4e26e59d8a766a48cb5",
        expected_byte_length=17349457,
        expected_record_count=4083,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="200504",
        publication_id="200504",
        expected_sha256="sha256:78a036077a4bdfc96854dbe3a5eefeb4f7ae6e40e92939bc14a3cee26822fbc5",
        expected_byte_length=16828938,
        expected_record_count=4087,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="200510",
        publication_id="200510",
        expected_sha256="sha256:73c0e3458023adfc1b26390970cddb31c827704cec84660715d8a60aaa479439",
        expected_byte_length=17406130,
        expected_record_count=4062,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="200604",
        publication_id="200604",
        expected_sha256="sha256:bc0701d901175f844435dc1143f633f72688e40b5baa34dc4c1fe897131e06e1",
        expected_byte_length=17058632,
        expected_record_count=4095,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="200610",
        publication_id="200610",
        expected_sha256="sha256:deb669e1fa7774f7b56aa55d69d860e1e07d8d62d60c6c9e1dd6662293f65880",
        expected_byte_length=17443990,
        expected_record_count=4052,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="200704",
        publication_id="200704",
        expected_sha256="sha256:4900243457b6ae2f263a557b127eb6a7bdfc1e9bfe25caecf7485e0805a150ca",
        expected_byte_length=16040624,
        expected_record_count=3823,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="200710",
        publication_id="200710",
        expected_sha256="sha256:d8b114d189db2267e69f180dc6981d686b8a66c1819b9360d68dbc08a3161650",
        expected_byte_length=17131303,
        expected_record_count=3882,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="200804",
        publication_id="200804",
        expected_sha256="sha256:d9a89d50d2278400b79aad22303171639655d6167128e9358939d31fcac5e311",
        expected_byte_length=16541463,
        expected_record_count=3885,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="200810",
        publication_id="200810",
        expected_sha256="sha256:18e13a307ed8f32ca18edd23dd4b464eb5408f9c2eda498a21e7471f04a761e6",
        expected_byte_length=17393874,
        expected_record_count=4004,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="200904",
        publication_id="200904",
        expected_sha256="sha256:37d11a26f7172672502e4f2b2a41d428aabbcdfa26f0b8d2f50276fd11f0a0b8",
        expected_byte_length=16830245,
        expected_record_count=3989,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="200910",
        publication_id="200910",
        expected_sha256="sha256:244e2e349b96b303d43322844194b2d1b4bcd6910ff6e063c7b9782c21b03c9a",
        expected_byte_length=17736175,
        expected_record_count=4043,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="201004",
        publication_id="201004",
        expected_sha256="sha256:458218d69d476ec4d593b0d4ff3488a95de37aea4e5e3d970b3ca0a57f235550",
        expected_byte_length=16821798,
        expected_record_count=3943,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="201010",
        publication_id="201010",
        expected_sha256="sha256:672a103b5d6f4c2c257be73348e4fbf5606ff5e442357d36c06485a565cfeca8",
        expected_byte_length=18601532,
        expected_record_count=4225,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="201104",
        publication_id="201104",
        expected_sha256="sha256:1a9d5e31cfcc8fbc50333f869a9d009845e70be16d72fe7d105d0f460fc34d42",
        expected_byte_length=18478688,
        expected_record_count=4257,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="201110",
        publication_id="201110",
        expected_sha256="sha256:d41426f61a976254b4a609285ed354b7e141046fbcda2dd19c80018fc5abc0ec",
        expected_byte_length=18469467,
        expected_record_count=4128,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="2012",
        publication_id="201210",
        expected_sha256="sha256:0ab997af123ea09702b4d2f765da907b1f91590243c9d1f51df54f7095049019",
        expected_byte_length=17985053,
        expected_record_count=4063,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="201304",
        publication_id="201304",
        expected_sha256="sha256:19926aa5f1ddf14e326e2943bc9ddbef1d2995c4e04b2f8e7202199429b64852",
        expected_byte_length=15181631,
        expected_record_count=3503,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="201310",
        publication_id="201310",
        expected_sha256="sha256:5906a44598f57e953bb44d5d4abda5adae19d46af39223f1544c38b95a62615f",
        expected_byte_length=14868452,
        expected_record_count=3305,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="201404",
        publication_id="201404",
        expected_sha256="sha256:dc741b4e3d1b5ddcd727f88ac16bc94667c2b8967ce6043c311b04add5ec1c4d",
        expected_byte_length=14521530,
        expected_record_count=3348,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="201410",
        publication_id="201410",
        expected_sha256="sha256:7de7c580fa701f2020db70ee0b249ccde7cee5d2a02cde78ab302871cc784395",
        expected_byte_length=15410066,
        expected_record_count=3415,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="201504",
        publication_id="201504",
        expected_sha256="sha256:73a1837d7633490de0e16842a3fc538a4bb2702da9afb57319e4da7a45e98df5",
        expected_byte_length=14455923,
        expected_record_count=3260,
        run_date="2015-05-18-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="201510",
        publication_id="201510",
        expected_sha256="sha256:6a1938c7d28033edc77845b4e1ee23d963de2d009f03d3ab4a578a565c0f1709",
        expected_byte_length=15163972,
        expected_record_count=3297,
        run_date="2015-11-17-05:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="201604",
        publication_id="201604",
        expected_sha256="sha256:fb3edbeb36d7e8dd00a909ce960389a172cb0dfacb4f56db85d532c2565275fb",
        expected_byte_length=14649197,
        expected_record_count=3306,
        run_date="2016-05-24-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="201610",
        publication_id="201610",
        expected_sha256="sha256:55a0447eff0f19e8a974f8679686633fe00b39afac5ea0206291b3ccd5123372",
        expected_byte_length=15227427,
        expected_record_count=3318,
        run_date="2016-11-12-05:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="201704",
        publication_id="201704",
        expected_sha256="sha256:c88626bace7b83e599236b775e75f95e776a57813fe782092032e3f5766fa3fb",
        expected_byte_length=15531975,
        expected_record_count=3519,
        run_date="2017-07-15-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="201710",
        publication_id="201710",
        expected_sha256="sha256:75ee0120eb486611a4a4578182ae61d3202ea844aeee36b26fd7ba06b4bcea99",
        expected_byte_length=14678586,
        expected_record_count=3209,
        run_date="2018-01-05-05:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="201804",
        publication_id="201804",
        expected_sha256="sha256:bd10e0047c08080133a54e476b61f580ca2cbcb4dc546a5fe2562bba62a78f2c",
        expected_byte_length=14592116,
        expected_record_count=3350,
        run_date="2018-09-17-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="201810",
        publication_id="201810",
        expected_sha256="sha256:2631bbad45f5578045e20b460a7e4036623ca173fb870a43c7c138dd04d04438",
        expected_byte_length=15789629,
        expected_record_count=3534,
        run_date="2018-10-14-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="201904",
        publication_id="201904",
        expected_sha256="sha256:4b2d9912d0fbac2c48bd2b3135a5bd1df9cd68d237d4a15d3f234d6ec3c58616",
        expected_byte_length=16322877,
        expected_record_count=3791,
        run_date="2019-05-22-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="201910",
        publication_id="201910",
        expected_sha256="sha256:a96c08f7edd127a4f2e0694398f3f040980a0f2984dca8cc004014eee10dd9d2",
        expected_byte_length=16843863,
        expected_record_count=3752,
        run_date="2019-11-16-05:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="202004",
        publication_id="202004",
        expected_sha256="sha256:f779d0805f3b3d58a98f2992cf711cbc8b338156eb3080f99b6bd44a8c21afb9",
        expected_byte_length=17014639,
        expected_record_count=3939,
        run_date="2020-06-30-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="202010",
        publication_id="202010",
        expected_sha256="sha256:8ef71f90d00a8ba072230a5b58608dfa6f98ec769f794e9ebb05d191a71db29a",
        expected_byte_length=17256946,
        expected_record_count=3853,
        run_date="2020-12-14-05:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="202104",
        publication_id="202104",
        expected_sha256="sha256:00d7c2947366853c5969a81db8017d161cde4535a3611bd3db3ae86873eab2ad",
        expected_byte_length=16885239,
        expected_record_count=3961,
        run_date="2021-06-14-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="202110",
        publication_id="202110",
        expected_sha256="sha256:ac3be957e4e11fabe96af7305df12fc05845f7adcba59be9a20c7b3e1f7bf43f",
        expected_byte_length=16646675,
        expected_record_count=3777,
        run_date="2021-12-08-05:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="202204",
        publication_id="202204",
        expected_sha256="sha256:976153a81b4a531e3abce9bfb3fd68d9d5e945a9ba48cf5b5b925afb21f1de2e",
        expected_byte_length=16271986,
        expected_record_count=3803,
        run_date="2022-07-01-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="202210",
        publication_id="202210",
        expected_sha256="sha256:a10d26254a7d322a96df0d498c50ab68d6e876d54e26976804567c3ea2cd579a",
        expected_byte_length=16581014,
        expected_record_count=3690,
        run_date="2023-01-04-05:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="202304",
        publication_id="202304",
        expected_sha256="sha256:52ee2e6d9931cc22d2e23cba1252189fba691df2cc95a858e1cf3545bd084780",
        expected_byte_length=15893193,
        expected_record_count=3666,
        run_date="2023-07-19-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="202310",
        publication_id="202310",
        expected_sha256="sha256:670d88321814a8785a9a2128df7bfa0260dc0b60e4cacd88facaf10240ef5081",
        expected_byte_length=16432211,
        expected_record_count=3599,
        run_date="2023-12-05-05:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="202404",
        publication_id="202404",
        expected_sha256="sha256:9152592ada59b07e3904ebc350847e15ad5c6f0a73fd43f086f8ee6949e55510",
        expected_byte_length=16335809,
        expected_record_count=3698,
        run_date="2024-07-03-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="202410",
        publication_id="202410",
        expected_sha256="sha256:4144f0d7655e28ac4097deab390440b705114da94269c846872966c29dde8620",
        expected_byte_length=15217730,
        expected_record_count=3331,
        run_date="2024-12-12-05:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="202504",
        publication_id="202504",
        expected_sha256="sha256:b37f2aa0a464a572160621cd154e789db834c75b0ed9fcc948dbca3b99b9ba06",
        expected_byte_length=16586837,
        expected_record_count=3821,
        run_date="2025-09-06-04:00",
    ),
    UnifiedAgendaEditionPin(
        file_stem="202510",
        publication_id="202510",
        expected_sha256="sha256:4dc85fe08251eed1499dee5f2a2f7e3fcf4717baf468409c1f884dd68782b75f",
        expected_byte_length=17624465,
        expected_record_count=3954,
        run_date="2026-07-03-04:00",
    ),
)

UNIFIED_AGENDA_EXPECTED_EDITION_COUNT = 60
UNIFIED_AGENDA_EXPECTED_RECORD_COUNT = 241726


def _text(element: ET.Element | None) -> str:
    return "" if element is None else " ".join((element.text or "").split())


def _raw_text(element: ET.Element | None) -> str:
    """Everything an element holds, whitespace intact.

    ``itertext`` rather than ``.text`` so that a child element could never take
    its tail text away with it. Measured over all 241,726 records of the 60
    pinned editions: no ``ADDITIONAL_INFO`` element has a child, so today the
    two spellings agree -- and if one ever grows one, nothing vanishes.
    """

    return "" if element is None else "".join(element.itertext())


#: The labels a filer writes above a continued legal-authority list, each
#: paired with the family it belongs to. Every spelling below is one the 60
#: pinned editions actually contain; the patterns are no wider than the corpus.
#:
#: The first swallows the optional "LEGAL", both singular and plural, the
#: parenthesised form, every truncation of "CONTINUED" the filers type, and the
#: run of dots or colons behind it ("Legal Authority Continue........."). The
#: second is the "Additional Legal Authority" family, whose one outlier spells
#: the label "Additional legal authority information:". The third is the single
#: "Continue from #8 Legal Authority..........." in RIN 3235-AE11, Spring 1997.
_CONTINUATION_MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "legal-authority-cont",
        re.compile(r"(?:LEGAL\s+)?AUTHORIT(?:Y|IES)\s*\(?\s*CONT(?:INUED|INUES|INUE)?\)?\s*[.:]*", re.IGNORECASE),
    ),
    (
        "additional-legal-authority",
        re.compile(r"ADDITIONAL\s+LEGAL\s+AUTHORIT(?:Y|IES)(?:\s+INFORMATION)?\s*[.:]*", re.IGNORECASE),
    ),
    (
        "additional-legal-authority",
        re.compile(r"CONTINUE[DS]?\s+FROM\s*#?\s*\d+\s*LEGAL\s+AUTHORIT(?:Y|IES)\s*[.:]*", re.IGNORECASE),
    ),
)

#: Where a continuation ENDS. Two shapes carry the whole corpus: the
#: publisher's own paragraph mark, a literal "^" (it is written "^P" and starts
#: the next field or paragraph -- "^PRFA: N", "^PANALYSIS: Regulatory
#: Evaluation"), and a blank line, which is how the same boundary is written in
#: the editions that carry real newlines.
_CONTINUATION_BOUNDARY = re.compile(r"\^|\n[ \t]*\n")

#: And the third boundary, which FIRES ON NOTHING in the pinned corpus: another
#: of the form's fields continuing under its own label. Measured over all 98
#: continuations, no extraction cut by the two boundaries above contains one --
#: every "CFR CITATIONS CONT:" and "STATUTORY DEADLINE CONT:" in the series is
#: already behind a paragraph mark or a blank line. It is kept because a
#: regression there is silent by construction: a filer who separates two field
#: continuations with a semicolon instead would otherwise hand the CFR list to
#: the authority parser, and a rule measuring zero is the only thing that can
#: say it did not happen. A label ends in a colon; the word "continued" inside
#: prose does not, which is what keeps this from cutting a citation list in
#: half.
_ANOTHER_FIELD_CONTINUES = re.compile(
    r"[A-Za-z][A-Za-z ']*\s*\(?\s*CONT(?:INUED|INUES|INUE)?\)?\s*:", re.IGNORECASE
)


def legal_authority_continuations(additional_info: str) -> tuple[AuthorityContinuation, ...]:
    """Every continued legal-authority list inside one ``ADDITIONAL_INFO``.

    The Agenda's form gives a filer a fixed number of legal-authority boxes.
    Filers who need more type the rest into ``ADDITIONAL_INFO`` under a label,
    and 98 records of the 241,726 in the 60 pinned editions do -- 1,325
    citations that the ``LEGAL_AUTHORITY_LIST`` element does not contain.

    A continuation runs from its label's END to the first boundary: the
    publisher's "^" paragraph mark, a blank line, or another of the form's
    fields continuing under its own label (see
    :data:`_ANOTHER_FIELD_CONTINUES`, which fires on nothing here). What comes
    back is whitespace-collapsed exactly as :func:`_text` collapses a citation
    box, because it is the same kind of string and a caller must not have to
    know which of the two it holds.

    The whole string is returned, never pre-split on its separators. That is
    not a nicety: RIN 1115-AE47's Spring 1997 continuation is a bare comma list
    under one title ("8 USC 1186b, 1187, 1201, ... 1447; 28 USC 509, 510,
    1746; ..."), which the citation grammar reads to 41 citations whole and to
    7 if a caller splits it first.
    """

    found: list[AuthorityContinuation] = []
    marks = sorted(
        (match.start(), match.end(), family, match.group(0))
        for family, pattern in _CONTINUATION_MARKERS
        for match in pattern.finditer(additional_info)
    )
    # Two patterns can only overlap by matching the same label two ways; the
    # first one wins, so a label is never read twice.
    consumed = 0
    for start, end, family, marker in marks:
        if start < consumed:
            continue
        consumed = end
        rest = additional_info[end:]
        stop = min(
            (match.start() for match in (
                _CONTINUATION_BOUNDARY.search(rest), _ANOTHER_FIELD_CONTINUES.search(rest)
            ) if match is not None),
            default=len(rest),
        )
        text = " ".join(rest[:stop].split())
        if text:
            found.append(AuthorityContinuation(label_family=family, marker=marker.strip(), text=text))
    return tuple(found)


def parse_unified_agenda_edition(
    payload: bytes,
    *,
    pin: UnifiedAgendaEditionPin,
) -> tuple[UnifiedAgendaRecord, ...]:
    """Read one pinned edition, refusing anything that is not exactly it.

    The digest is taken over the bytes as served, before the apostrophe
    repair, so a capture can always be re-verified against what the endpoint
    returned. The repair is applied only to the in-memory copy handed to the
    parser.
    """

    if len(payload) != pin.expected_byte_length:
        raise UnifiedAgendaEditionError(
            f"{pin.file_stem} byte length drifted: expected {pin.expected_byte_length}, got {len(payload)}"
        )
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    if digest != pin.expected_sha256:
        raise UnifiedAgendaEditionError(
            f"{pin.file_stem} digest drifted: expected {pin.expected_sha256}, got {digest}"
        )

    repaired = payload.replace(_MANGLED_APOSTROPHE, "\u2019".encode())
    if (repaired is not payload and repaired != payload) != (
        pin.publication_id in UNIFIED_AGENDA_MANGLED_APOSTROPHE_EDITIONS
    ):
        raise UnifiedAgendaEditionError(
            f"{pin.file_stem} mangled-apostrophe presence does not match the recorded roster"
        )

    root = ET.fromstring(repaired)
    if root.tag != _ROOT_TAG:
        raise UnifiedAgendaEditionError(f"{pin.file_stem} root element is {root.tag!r}, not {_ROOT_TAG!r}")

    records: list[UnifiedAgendaRecord] = []
    for element in root.findall(f".//{_RECORD_TAG}"):
        publication_id = _text(element.find("PUBLICATION/PUBLICATION_ID"))
        if publication_id != pin.publication_id:
            raise UnifiedAgendaEditionError(
                f"{pin.file_stem} record declares publication {publication_id!r}, "
                f"not the pinned {pin.publication_id!r}"
            )
        cfr_list = element.find("CFR_LIST")
        authority_list = element.find("LEGAL_AUTHORITY_LIST")
        timetable_list = element.find("TIMETABLE_LIST")
        timetable = tuple(
            TimetableEntry(
                action=_text(entry.find("TTBL_ACTION")),
                date_text=_text(entry.find("TTBL_DATE")),
                fr_citation=_text(entry.find("FR_CITATION")) or None,
            )
            for entry in ([] if timetable_list is None else timetable_list.findall("TIMETABLE"))
        )
        records.append(
            UnifiedAgendaRecord(
                rin=_text(element.find("RIN")),
                publication_id=publication_id,
                # `if element:` on an ElementTree node tests child count, not
                # presence, and is deprecated for exactly that ambiguity -- an
                # empty <CFR_LIST> is falsy while being perfectly present.
                cfr_references=tuple(
                    text
                    for child in (() if cfr_list is None else cfr_list)
                    if (text := _text(child))
                ),
                legal_authorities=tuple(
                    text
                    for child in (() if authority_list is None else authority_list)
                    if (text := _text(child))
                ),
                timetable=timetable,
                # Whitespace INTACT -- see the field's own comment on
                # UnifiedAgendaRecord for why this one field is not collapsed.
                additional_info=_raw_text(element.find("ADDITIONAL_INFO")),
            )
        )

    if len(records) != pin.expected_record_count:
        raise UnifiedAgendaEditionError(
            f"{pin.file_stem} record count drifted: expected {pin.expected_record_count}, got {len(records)}"
        )
    return tuple(records)
