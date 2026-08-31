"""Value-level diff of two Unified Agenda tables, ordinals ignored.

Usage: agenda_value_diff.py OLD_DIR NEW_DIR [--table legal-authorities|timetables]
Groups rows per the table's key and compares the multiset of value tuples, so
list renumbering never masquerades as change.
"""
import argparse
import collections
import hashlib

import pyarrow.parquet as pq

from refspec.registry.unified_agenda_parquet import LEGAL_AUTHORITIES_SCHEMA, TIMETABLES_SCHEMA

#: Per table: the file, the producer's own schema, the key one publisher
#: reference is identified by, the columns EXCLUDED from the value comparison
#: on purpose, and the columns a moved value is SHAPED by in the report.
#:
#: The value columns are no longer hand-listed here -- they are every schema
#: column that is not the key and not in ``ignore``, computed below. A
#: hand-list goes stale the moment the schema gains a column, silently: the
#: list this replaced covered 41 of ``LEGAL_AUTHORITIES_SCHEMA``'s 86 value
#: columns and was blind to the other 45, the whole join/carry family
#: (``authority_source``, ``authority_join_rule``,
#: ``usc_title_carried_from_ordinal``, ...) included, because each one landed
#: in the schema without a matching entry here. ``stated_act_name`` and
#: ``pl_correction_evidence`` were two more, absent until 2026-08-24, and
#: their absence was not harmless: a cycle that widened the act-name walk
#: moved 202 rows' ``stated_act_name`` and NOTHING ELSE, and this diff
#: reported the whole build unchanged. A hand-list cannot fail closed; a
#: derivation from the schema that minted the column can, and does --
#: test_agenda_value_diff.py's ``test_every_schema_column_is_diffed_or_named_ignored``
#: is the check that breaks the day a new column arrives without a decision
#: about it.
#:
#: ``citation_ordinal`` is the one column named in ``ignore`` on purpose, in
#: both tables: it is exactly the renumbering this diff exists to see
#: through. Groups are keyed on the publisher reference and compared as a
#: MULTISET of value tuples, so several citations parsed out of one
#: ``authority_text`` (or one ``fr_citation_text``) moving to different
#: ``citation_ordinal`` positions between builds is not itself a change.
TABLES = {
    "legal-authorities": {
        "file": "unified_agenda_legal_authorities.parquet",
        "schema": LEGAL_AUTHORITIES_SCHEMA,
        "key": ("rin", "publication_id", "ordinal", "authority_text"),
        "ignore": frozenset({"citation_ordinal"}),
        "shape": ("authority_type", "parse_status"),
    },
    "timetables": {
        "file": "unified_agenda_timetables.parquet",
        "schema": TIMETABLES_SCHEMA,
        "key": ("rin", "publication_id", "ordinal", "fr_citation_text"),
        "ignore": frozenset({"citation_ordinal"}),
        "shape": ("parse_status", "fr_correction_evidence"),
    },
}

for _spec in TABLES.values():
    _excluded = set(_spec["key"]) | set(_spec["ignore"])
    _spec["values"] = tuple(name for name in _spec["schema"].names if name not in _excluded)
del _spec, _excluded

#: Rows decoded out of Parquet per step. The whole point of the streaming
#: rework below is that the Python-object working set is this many rows wide,
#: not the whole table: materialising 800,573 rows x 91 columns as Python
#: objects (which ``read_table(...).to_pylist()`` did, on both sides at once)
#: measured 14.428 GiB resident on the real self-diff, and could OOM an
#: 8-16 GiB host when `make test`'s `pytest -n auto` overlapped it with the
#: rest of the slow tier (2026-08-31 review finding 5). The same self-diff
#: now peaks at 0.414 GiB in 46.6 s, against 105.6 s before; timetables goes
#: 2.573 GiB / 20.5 s to 0.284 GiB / 10.5 s. The report is unchanged -- see
#: tests/test_agenda_value_diff.py's oracle agreement test.
BATCH_ROWS = 8192


def _physical_columns(directory, spec):
    """The columns the FILE has, read from Parquet metadata alone."""

    return pq.ParquetFile(f"{directory}/{spec['file']}").schema_arrow.names


def _present_value_columns(physical, spec):
    """The spec's value columns this file carries, in the spec's own order."""

    present = set(physical)
    return tuple(name for name in spec["values"] if name in present)


def _encode(value, parts):
    """Append an unambiguous byte encoding of one cell to ``parts``.

    Length-prefixed and type-tagged, so no two distinct cell values can encode
    to the same bytes: ``"1"`` is not ``1``, ``None`` is not ``"None"``,
    ``True`` is not ``1``, and a string containing the separator cannot forge
    a column boundary. That is what makes the digest below safe to compare
    instead of the tuple it stands for.
    """

    if value is None:
        parts.append(b"n;")
    elif value is True:
        parts.append(b"t;")
    elif value is False:
        parts.append(b"f;")
    elif isinstance(value, int):
        parts.append(b"i%d;" % value)
    elif isinstance(value, str):
        encoded = value.encode("utf-8")
        parts.append(b"s%d:" % len(encoded))
        parts.append(encoded)
    elif isinstance(value, bytes):
        parts.append(b"b%d:" % len(value))
        parts.append(value)
    elif isinstance(value, (list, tuple)):
        parts.append(b"l%d:" % len(value))
        for item in value:
            _encode(item, parts)
    else:
        # float, decimal, date/datetime, anything a future schema type decodes
        # to: repr is injective for these and the tag keeps it out of the
        # string namespace.
        encoded = repr(value).encode("utf-8")
        parts.append(b"o%d:" % len(encoded))
        parts.append(encoded)


def _digest(cells):
    """A 16-byte stand-in for one (key + compared values) row.

    The comparison is a multiset difference over composite (key, values)
    items; carrying the items themselves costs a Python tuple of ~90 objects
    per row on each side, which is where the 14.428 GiB went. A 128-bit digest
    of the same bytes carries the same equivalence classes at ~150 bytes a
    row, and the rows a difference lands on are re-read from the file to
    report them, so nothing but the equality test rides on the digest.
    """

    parts = []
    for cell in cells:
        _encode(cell, parts)
    return hashlib.blake2b(b"".join(parts), digest_size=16).digest()


def _rows(directory, spec, columns):
    """Stream the named columns as Python row tuples, ``BATCH_ROWS`` at a time."""

    columns = list(columns)
    handle = pq.ParquetFile(f"{directory}/{spec['file']}")
    for batch in handle.iter_batches(batch_size=BATCH_ROWS, columns=columns):
        names = batch.schema.names
        pulled = [batch.column(names.index(name)).to_pylist() for name in columns]
        yield from zip(*pulled, strict=True)


def _valued(cells, columns):
    """One row's compared values, as the (column, value) tuple the report shows."""

    return tuple(
        (name, tuple(cell) if isinstance(cell, list) else cell)
        for name, cell in zip(columns, cells, strict=True)
    )


def _digest_counts(directory, spec, key, shared):
    """Multiset of (key, shared values) digests for one side, and its row count."""

    counts = collections.Counter()
    rows = 0
    for row in _rows(directory, spec, tuple(key) + tuple(shared)):
        rows += 1
        counts[_digest(row)] += 1
    return counts, rows


def _attribute(directory, spec, key, shared, use, outstanding):
    """Charge each outstanding digest to the shape of the row that carries it.

    One more streaming pass over the side the difference came from, reading
    the FULL value columns this time so the report can name what moved --
    but only the rows a difference actually landed on are ever turned into a
    value tuple, and the walk stops as soon as every outstanding digest has
    been charged.
    """

    shaped, examples = collections.Counter(), {}
    remaining = dict(outstanding)
    if not remaining:
        return shaped, examples

    key = tuple(key)
    use = tuple(use)
    positions = [len(key) + use.index(name) for name in shared]
    for row in _rows(directory, spec, key + use):
        digest = _digest(row[: len(key)] + tuple(row[p] for p in positions))
        count = remaining.pop(digest, 0)
        if not count:
            continue
        values = _valued(row[len(key):], use)
        shape = tuple(dict(values).get(name) for name in spec["shape"])
        shaped[shape] += count
        # ``row[3]`` is the publisher text both tables key on fourth.
        examples.setdefault(shape, (str(row[3])[:90], {k: v for k, v in values if v is not None}))
        if not remaining:
            break
    return shaped, examples


def _report_unshared_column(directory, spec, column, headline):
    """Summarise one column only one side has, by the value's leading token.

    The comparison itself is on SHARED columns, so a column only one side has
    cannot make an unchanged row read as changed -- which is right, and which
    also means that column's own contents are invisible to it. A cycle that
    added ``act_initialism_roster`` resolved 92 rows and TYPED 196 more with
    nothing but that column, and the diff called those 196 unchanged. A
    column a consumer reads is a value, whether or not the other side had
    somewhere to put it -- in either direction: a column DELETED from the new
    build takes every value in it with it, and used to leave no trace here at
    all (2026-08-31 review finding 11).
    """

    counts = collections.Counter(
        # The value's own leading token, so a free-text column reports its
        # shape rather than one line per distinct string.
        str(v).split(" (", 1)[0].split("=", 1)[0].split("@", 1)[0] if " " not in str(v)
        else str(v).split(" ", 1)[1].split(" (", 1)[0]
        for (v,) in _rows(directory, spec, [column]) if v is not None
    )
    print(f"{headline} {column}: {sum(counts.values())}")
    for value, count in counts.most_common():
        print(f"   {count:6d} {value}")


def main(old_dir, new_dir, table):
    spec = TABLES[table]
    key = tuple(spec["key"])
    physical_o = _physical_columns(old_dir, spec)
    physical_n = _physical_columns(new_dir, spec)
    use_o = _present_value_columns(physical_o, spec)
    use_n = _present_value_columns(physical_n, spec)
    both = set(use_o) & set(use_n)
    # Compare on shared columns only, so a column only one side has does not
    # read as change -- but REPORT the whole value, so what is in the columns
    # only one side has is visible.
    shared = tuple(name for name in spec["values"] if name in both)

    old_counts, rows_old = _digest_counts(old_dir, spec, key, shared)
    new_counts, rows_new = _digest_counts(new_dir, spec, key, shared)

    only_new = sorted(set(use_n) - set(use_o))
    only_old = sorted(set(use_o) - set(use_n))
    # A column the schema declares that NEITHER file has is not a difference
    # between the builds, so neither list above can say it -- and both sides
    # intersecting it away is exactly how it stays quiet. Say it out loud:
    # every row's value in it is uncompared, on both sides.
    missing = sorted(set(spec["values"]) - both - set(only_new) - set(only_old))
    # The mirror of ``missing``, and the last direction that could stay quiet:
    # both physical schemas above are filtered through the CURRENT spec's
    # expected set, so a column a file carries that the schema no longer
    # declares is dropped before any of the four lines above can see it. That
    # is exactly what a RETIRED column looks like from here -- the old file
    # still has it, the producer stopped minting it, and the diff of the build
    # that retired it said nothing at all. Reporting only, per side: the
    # schema owns what is compared, and a column it does not declare has no
    # place in the value comparison. Naming it is the whole fix -- it turns a
    # silent disappearance into a line an operator can go and check.
    declared = set(spec["schema"].names)
    undeclared_old = sorted(set(physical_o) - declared)
    undeclared_new = sorted(set(physical_n) - declared)
    print(f"table {table}")
    print(f"rows old {rows_old:,} new {rows_new:,}")
    print(f"columns only in new: {only_new}")
    print(f"columns only in old: {only_old}")
    print(f"columns in NEITHER file that the schema declares: {missing}")
    print(f"columns in old the schema does not declare (named, never compared): {undeclared_old}")
    print(f"columns in new the schema does not declare (named, never compared): {undeclared_new}")
    for column in only_new:
        _report_unshared_column(new_dir, spec, column, "ARRIVED in new column")
    for column in only_old:
        _report_unshared_column(old_dir, spec, column, "DEPARTED from old column")

    vanished, arrived = old_counts - new_counts, new_counts - old_counts
    del old_counts, new_counts
    van, vs = _attribute(old_dir, spec, key, shared, use_o, vanished)
    arr, as_ = _attribute(new_dir, spec, key, shared, use_n, arrived)

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
