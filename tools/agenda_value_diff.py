"""Value-level diff of two Unified Agenda tables, ordinals ignored.

Usage: agenda_value_diff.py OLD_DIR NEW_DIR [--table legal-authorities|timetables]
Groups rows per the table's key and compares the multiset of value tuples, so
list renumbering never masquerades as change.
"""
import argparse
import collections

import pyarrow.parquet as pq

#: Per table: the file, the key one publisher reference is identified by, the
#: value columns compared, and the columns a moved value is SHAPED by in the
#: report. citation_ordinal is in no value list on purpose -- it is exactly the
#: renumbering this diff exists to see through.
#:
#: ``stated_act_name`` and ``pl_correction_evidence`` were absent until
#: 2026-08-24, and their absence was not harmless: a cycle that widened the
#: act-name walk moved 202 rows' ``stated_act_name`` and NOTHING ELSE, and this
#: diff reported the whole build unchanged. A statement column is a value a
#: consumer reads; a diff that cannot see it cannot say only the named rows
#: moved.
#:
#: ``usc_section_verdict_reason`` and ``usc_section_attested_at_edition`` joined
#: on 2026-08-24 for the same reason and against the same failure: the fence
#: over act-derived sections writes all three verdict columns, and a diff
#: holding only the first of them could not have shown that the 19 rows whose
#: edition never printed their section arrived narrowed rather than accused.
#:
#: ``eo_compilation_start``, ``eo_compilation_page`` and ``cfr_title`` joined on
#: 2026-08-24, and the first two were caught the same way the ampersand was:
#: the #46 list-tail fence fills a compilation PAGE on 17 rows over seven
#: values ("3 CFR, 1949-1953 Comp, 1002" had read the volume and dropped the
#: page), and this diff reported every one of them unchanged, because the whole
#: ``eo_compilation`` family had no column here. ``cfr_title`` is the same
#: miss found by reading rather than by being bitten: ``cfr_part`` was listed
#: without the title that says which Code the part belongs to, so a row moving
#: from 8 CFR 2 to 9 CFR 2 would have read as unchanged.
TABLES = {
    "legal-authorities": {
        "file": "unified_agenda_legal_authorities.parquet",
        "key": ("rin", "publication_id", "ordinal", "authority_text"),
        "values": (
            "authority_type", "parse_status", "usc_title", "usc_section", "usc_section_end",
            "usc_appendix", "stated_act_name", "stated_section", "public_law",
            "public_law_corrected", "pl_correction_evidence",
            "statute_volume", "statute_page_text", "cfr_title", "cfr_part", "cfr_section",
            "eo_compilation_start", "eo_compilation_page", "treaty_series",
            "usc_section_verdict", "usc_section_verdict_reason",
            "usc_section_attested_at_edition",
            "usc_section_corrected", "usc_section_span_rule",
            "usc_section_corrected_section", "usc_section_corrected_pinpoint",
            "act_key", "act_section", "act_resolution_evidence", "act_resolution_reason",
            "act_resolution_sibling_ordinal", "act_initialism_roster", "corroboration_rule",
            "authority_in_own_cfr_note", "cfr_note_part",
            "usc_disposition_verdict", "usc_disposition_successors", "usc_disposition_table",
            "usc_disposition_span_members", "usc_disposition_pinpoint", "usc_disposition_refusal",
        ),
        "shape": ("authority_type", "parse_status"),
    },
    "timetables": {
        "file": "unified_agenda_timetables.parquet",
        "key": ("rin", "publication_id", "ordinal", "fr_citation_text"),
        "values": (
            "action", "date_text", "fr_volume", "fr_page", "parse_status",
            "fr_citation_scheme", "fr_document_number", "fr_corrected_document_number",
            "fr_corrected_volume", "fr_corrected_page", "fr_correction_evidence",
        ),
        "shape": ("parse_status", "fr_correction_evidence"),
    },
}


def groups(d, spec):
    t = pq.read_table(f"{d}/{spec['file']}")
    use = [c for c in spec["values"] if c in t.column_names]
    g = collections.defaultdict(collections.Counter)
    for r in t.select(list(spec["key"]) + use).to_pylist():
        values = tuple((c, tuple(r[c]) if isinstance(r[c], list) else r[c]) for c in use)
        g[tuple(r[c] for c in spec["key"])][values] += 1
    return g, use


def arrivals_in_new_columns(new_dir, spec, columns):
    """Rows that gained a value in a column the old table does not have.

    The comparison below is on SHARED columns, so a new column cannot make an
    unchanged row read as changed -- which is right, and which also means the
    new column's own arrivals are invisible to it. A cycle that added
    ``act_initialism_roster`` resolved 92 rows and TYPED 196 more with nothing
    but that column, and the diff called those 196 unchanged. A column a
    consumer reads is a value, whether or not the old table had somewhere to
    put it.
    """

    if not columns:
        return
    table = pq.read_table(f"{new_dir}/{spec['file']}", columns=list(columns))
    for column in sorted(columns):
        counts = collections.Counter(
            # The value's own leading token, so a free-text column reports its
            # shape rather than one line per distinct string.
            str(v).split(" (", 1)[0].split("=", 1)[0].split("@", 1)[0] if " " not in str(v)
            else str(v).split(" ", 1)[1].split(" (", 1)[0]
            for v in table.column(column).to_pylist() if v is not None
        )
        print(f"ARRIVED in new column {column}: {sum(counts.values())}")
        for value, count in counts.most_common():
            print(f"   {count:6d} {value}")


def main(old_dir, new_dir, table):
    spec = TABLES[table]
    o, use_o = groups(old_dir, spec)
    n, use_n = groups(new_dir, spec)
    shared = {c for c in use_o if c in use_n}
    print(f"table {table}")
    print(f"rows old {sum(sum(c.values()) for c in o.values()):,} new {sum(sum(c.values()) for c in n.values()):,}")
    print(f"columns only in new: {sorted(set(use_n) - set(use_o))}")
    arrivals_in_new_columns(new_dir, spec, set(use_n) - set(use_o))

    # Compare on shared columns only, so a new column does not read as change --
    # but REPORT the whole value, so what arrived in the new columns is visible.
    def project(counter):
        out, source = collections.Counter(), {}
        for v, c in counter.items():
            p = tuple((k, val) for k, val in v if k in shared)
            out[p] += c
            source.setdefault(p, v)
        return out, source

    def shape(v):
        d = dict(v)
        return tuple(d.get(c) for c in spec["shape"])

    def stated(v):
        return {k: val for k, val in v if val is not None}

    van, arr = collections.Counter(), collections.Counter()
    vs, as_ = {}, {}
    for k in set(o) | set(n):
        po, from_o = project(o.get(k, collections.Counter()))
        pn, from_n = project(n.get(k, collections.Counter()))
        for v, c in (po - pn).items():
            van[shape(from_o[v])] += c
            vs.setdefault(shape(from_o[v]), (str(k[3])[:90], stated(from_o[v])))
        for v, c in (pn - po).items():
            arr[shape(from_n[v])] += c
            as_.setdefault(shape(from_n[v]), (str(k[3])[:90], stated(from_n[v])))
    print("VANISHED values:", sum(van.values()))
    for s, c in van.most_common():
        print(f"   {c:6d} {s}   e.g. {vs[s][0]!r} {vs[s][1]}")
    print("ARRIVED values:", sum(arr.values()))
    for s, c in arr.most_common():
        print(f"   {c:6d} {s}   e.g. {as_[s][0]!r} {as_[s][1]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old_dir")
    parser.add_argument("new_dir")
    parser.add_argument("--table", choices=sorted(TABLES), default="legal-authorities")
    args = parser.parse_args()
    main(args.old_dir, args.new_dir, args.table)
