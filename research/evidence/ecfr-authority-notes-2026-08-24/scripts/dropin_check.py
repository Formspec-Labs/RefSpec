#!/usr/bin/env python3
"""Point the real reader at generation 2 and ask it the suite's own questions.

The schema check in ``validate.py`` proves the fields are there. This proves the
reader *works*: :class:`refspec.registry.cfr_authority_notes.CfrAuthorityNotes`
is loaded unmodified except for its three pin constants -- digest, byte length
and record count, the only things that can possibly still say 287 -- and then
asked the specimens ``tests/test_cfr_authority_notes.py`` asks.

**Nothing here repoints the oracle.** The constants are patched on the module
object inside this process and the file on disk is not touched; that edit is
unit 2's, and this is the evidence for it.

    python3 dropin_check.py REPOSITORY_ROOT NOTES_JSONL
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

TWENTY_ONE_CFR_310 = (
    "Authority: 21 U.S.C. 321, 331, 351, 352, 353, 355, 360b-360f, 360j, 360hh-360ss, "
    "361(a), 371, 374, 375, 379e, 379k-l; 42 U.S.C. 216, 241, 242(a), 262."
)


def main() -> int:
    root = Path(sys.argv[1]).resolve()
    notes_path = Path(sys.argv[2]).resolve()
    sys.path.insert(0, str(root / "src"))
    from refspec.registry import cfr_authority_notes as module

    payload = notes_path.read_bytes()
    module.NOTES_SHA256 = "sha256:" + hashlib.sha256(payload).hexdigest()
    module.NOTES_BYTE_LENGTH = len(payload)
    module.NOTES_EXPECTED_RECORDS = sum(1 for line in payload.decode("utf-8").splitlines() if line.strip())

    notes = module.CfrAuthorityNotes.from_file(notes_path)
    usc = module.usc_citation

    results = [
        ("records read", len(notes.records)),
        ("coverage pairs", len(notes.coverage())),
        ("distinct titles", len({title for title, _ in notes.coverage()})),
        ("citations read across every note", sum(len(one.citations) for one in notes.records)),
        # The opening specimen generation 1 could not hold.
        ("holds 45 CFR 12a", notes.holds(45, "12a")),
        ("40 U.S.C. 550 against 45 CFR 12a", notes.judge(usc(40, "550"), [(45, "12a")]).verdict),
        # test_the_reader_reads_the_publishers_own_words_on_21_cfr_310
        ("21 CFR 310's note is the pinned string", notes.note(21, "310").authority_note == TWENTY_ONE_CFR_310),
        ("21 U.S.C. 361 against 21 CFR 310", notes.judge(usc(21, "361"), [(21, "310")]).verdict),
        ("21 U.S.C. 321p against 21 CFR 310", notes.judge(usc(21, "321p"), [(21, "310")]).verdict),
        # test_the_reader_reads_49_cfr_192_as_the_publisher_writes_it_today
        ("49 U.S.C. 60101 against 49 CFR 192", notes.judge(usc(49, "60101"), [(49, "192")]).verdict),
        ("49 U.S.C. 60137 against 49 CFR 192", notes.judge(usc(49, "60137"), [(49, "192")]).verdict),
        ("49 U.S.C. 60102 against 49 CFR 192", notes.judge(usc(49, "60102"), [(49, "192")]).verdict),
        # test_near_miss_is_one_edit_on_the_identity_including_the_title
        ("17 U.S.C. 12a against 17 CFR 1", notes.judge(usc(17, "12a"), [(17, "1")]).verdict),
        # test_a_note_range_covers_the_sections_between_its_endpoints
        ("42 U.S.C. 6295 against 10 CFR 430", notes.judge(usc(42, "6295"), [(10, "430")]).verdict),
        # test_the_publishers_elided_title_carries_across_its_own_semicolon
        ("16 U.S.C. 1531 against 50 CFR 17", notes.judge(usc(16, "1531"), [(50, "17")]).verdict),
        # A part whose note generation 2 takes from Subpart A.
        ("20 CFR 404 is held", notes.holds(20, "404")),
        ("42 U.S.C. 405 against 20 CFR 404", notes.judge(usc(42, "405"), [(20, "404")]).verdict),
    ]
    for label, value in results:
        print(f"{label:44s} {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
