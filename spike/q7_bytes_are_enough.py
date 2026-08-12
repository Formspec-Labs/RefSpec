"""Q7 -- how much of the "un-portable" surface is really just the bytes?

Hypothesis: the canonical pack stream is already a sorted, subject-contiguous
index, so the two subsystems that look most store-entangled -- per-node digests
and the JSON payload checks -- can be computed in the parse-time byte pass with
no RDF store and no term model at all.

  digests   compute every node digest from raw bytes; compare, node by node,
            with validate.py's own `rdf_node_digest` over an rdflib graph
  full      time the byte-level node-digest pass over all 29,283,283 quads
  payloads  time the nativePayload canonical-JSON check straight off the bytes

    .venv/bin/python spike/q7_bytes_are_enough.py <digests|full|payloads> [n]
"""

from __future__ import annotations

import gc
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "pinned-binding-3.1" / "tools"))

import common  # noqa: E402

ASSERTED = b"<urn:ref:atlas:graph:v3:asserted>"
FULL_ROOT = Path("/Users/mikewolfd/Work/spicy-regs/RefSpec/output/atlas-3.1-full-2026-08-12")
# validate.py's `_SELF_DIGEST_PREDICATES`, as bytes.
SELF_DIGEST = {
    b"<https://refspec.org/ns/atlas/v3#contentDigest>",
    b"<https://rulespec.org/ns/rkaf/v1#proofRecordDigest>",
}
NATIVE_PAYLOAD = b"<https://refspec.org/ns/atlas/v3#nativePayload>"


def split_quad(line: bytes) -> tuple[bytes, bytes, bytes, bytes]:
    """Split one canonical N-Quads line into its four terms.

    Exact for the Atlas profile: `ntriples_term` escapes `<`, `>` and `"` inside
    IRIs and `"` inside literals, so a left-to-right scan never ambiguates.
    """

    end = line.rindex(b" .")
    i = line.index(b">") + 1
    subject = line[:i]
    j = line.index(b">", i + 1) + 1
    predicate = line[i + 1 : j]
    k = j + 1
    if line[k] == 0x3C:  # '<' -> IRI object
        m = line.index(b">", k) + 1
    else:  # '"' -> literal, find the closing unescaped quote
        m = k + 1
        while True:
            m = line.index(b'"', m)
            back = m - 1
            while line[back] == 0x5C:
                back -= 1
            if (m - 1 - back) % 2 == 0:
                break
            m += 1
        m += 1
        if m < len(line) and line[m] == 0x40:  # '@lang
            m = line.index(b" ", m)
        elif line[m : m + 2] == b"^^":
            m = line.index(b">", m) + 1
    obj = line[k:m]
    graph = line[m + 1 : end]
    return subject, predicate, obj, graph


def _zstd():
    try:
        from compression import zstd
    except ImportError:
        from backports import zstd
    return zstd


def _streams(full: bool, n: int | None):
    if full:
        zstd = _zstd()
        packs = json.loads((FULL_ROOT / "atlas-manifest.json").read_bytes())["packs"]
        for pack in packs:
            yield zstd.open(FULL_ROOT / pack["path"], "rb")
    else:
        paths = sorted(common.decompressed(), key=lambda p: p.stat().st_size)
        for path in paths if n is None else paths[:n]:
            yield path.open("rb")


def byte_digests(full: bool = False, n: int | None = None, collect: bool = True):
    """Every asserted node's digest, in one streaming pass over the packs.

    `collect=False` keeps only a count, so the full-scale run stays flat in
    memory -- a real validator would compare each digest against the stored
    one as it is produced and keep nothing.
    """

    out: dict[bytes, str] = {}
    count = 0
    current: bytes | None = None
    rows: list[bytes] = []

    def flush() -> None:
        nonlocal count
        rows.sort()
        digest = "sha256:" + hashlib.sha256(b"\n".join(rows) + b"\n").hexdigest()
        count += 1
        if collect:
            out[current] = digest

    for stream in _streams(full, n):
        with stream:
            for line in stream:
                subject, predicate, obj, graph = split_quad(line[:-1])
                if graph != ASSERTED:
                    continue
                if subject != current:
                    if current is not None and rows:
                        flush()
                    current, rows = subject, []
                if predicate not in SELF_DIGEST:
                    rows.append(predicate + b" " + obj + b" .")
    if current is not None and rows:
        flush()
    return out if collect else count


def digests(n: int) -> None:
    """Byte digests vs validate.py's rdf_node_digest, node by node."""

    import validate as V
    from rdflib import Dataset, URIRef

    with common.Timer("bytes") as tb:
        computed = byte_digests(full=False, n=n)

    ds = Dataset()
    paths = sorted(common.decompressed(), key=lambda p: p.stat().st_size)[:n]
    for p in paths:
        with p.open("rb") as fh:
            V._parse_nquads_preserving_lexical_forms(ds, fh)
    asserted = ds.graph(URIRef("urn:ref:atlas:graph:v3:asserted"))
    subjects = list(asserted.subjects(unique=True))
    gc.collect()
    with common.Timer("rdflib") as tr:
        reference = {}
        for node in subjects:
            try:
                reference[node] = V.rdf_node_digest(asserted, node)
            except V.AtlasValidationError:
                pass

    same = diff = missing = 0
    shown = 0
    for node, want in reference.items():
        got = computed.get(f"<{node}>".encode("utf-8"))
        if got is None:
            missing += 1
        elif got == want:
            same += 1
        else:
            diff += 1
            if shown < 3:
                shown += 1
                print(f"  MISMATCH {node}\n    rdflib {want}\n    bytes  {got}")
    common.emit(
        {
            "q": 7,
            "probe": "node-digest-from-bytes",
            "packs": n,
            "nodes_compared": len(reference),
            "identical": same,
            "different": diff,
            "missing": missing,
            "bytes_wall_s": round(tb.wall, 3),
            "rdflib_wall_s": round(tr.wall, 3),
            "peak_rss_gb": round(common.peak_rss_gb(), 3),
        }
    )


def full(_n: int | None = None) -> None:
    """The same pass over the whole 29,283,283-quad distribution."""

    gc.collect()
    with common.Timer("full") as t:
        count = byte_digests(full=True, collect=False)
    common.emit(
        {
            "q": 7,
            "probe": "node-digest-from-bytes",
            "scope": "full",
            "nodes_digested": count,
            "wall_s": round(t.wall, 2),
            "peak_rss_gb": round(common.peak_rss_gb(), 3),
        }
    )


def payloads(_n: int | None = None) -> None:
    """`_check_native_payloads`' canonical-JSON half, straight off the bytes."""

    import validate as V

    checked = bad = 0
    gc.collect()
    with common.Timer("payloads") as t:
        for stream in _streams(True, None):
            with stream:
                for line in stream:
                    if NATIVE_PAYLOAD not in line:
                        continue
                    _s, predicate, obj, _g = split_quad(line[:-1])
                    if predicate != NATIVE_PAYLOAD:
                        continue
                    lexical = obj[1 : obj.rindex(b'"')]
                    text = lexical.decode("unicode_escape").encode("latin-1").decode("utf-8")
                    value = json.loads(
                        text,
                        object_pairs_hook=V._reject_duplicate_keys,
                        parse_float=V._reject_float,
                        parse_int=V._parse_int,
                        parse_constant=V._reject_constant,
                    )
                    if text.encode("utf-8") != V.canonical_native_json_bytes(value):
                        bad += 1
                    checked += 1
    common.emit(
        {
            "q": 7,
            "probe": "native-payload-from-bytes",
            "scope": "full",
            "payloads_checked": checked,
            "noncanonical": bad,
            "wall_s": round(t.wall, 2),
            "peak_rss_gb": round(common.peak_rss_gb(), 3),
        }
    )


def main() -> None:
    probe = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    {"digests": digests, "full": full, "payloads": payloads}[probe](n)


if __name__ == "__main__":
    main()
