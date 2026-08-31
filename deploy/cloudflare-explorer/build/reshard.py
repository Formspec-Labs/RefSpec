"""Re-chunk the already-assembled resource-detail NDJSON shards into much
smaller files, without touching the source Parquet view at all.

Why: the first cut used ~250MB shards (safe under wrangler's 300MiB upload
ceiling). Under the network conditions seen during this deploy (RTT
oscillating 30ms-850ms, occasional packet loss, and -- worse -- multi-minute
full stalls with 0% CPU on the wrangler process, i.e. a hung TCP connection,
not just a slow one), a single 238MB PUT essentially never completes: any
attempt takes the failure with it. Small shards make each individual PUT
fast enough to either succeed or fail quickly, so retries are cheap and a
transient good window is enough to get a shard through.

This reuses byte-identical record boundaries from the existing
resource-detail-index.parquet (shard, offset, length per resource id) --
no JSON re-parsing, no re-querying the compact view. It just re-copies each
record's exact bytes into new, smaller shard files and re-derives a new
index with the same schema (id, shard, offset, length).
"""

import pathlib
import sys

import duckdb

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "precomputed" / "tables" / "resource-detail"
OLD_INDEX = ROOT / "precomputed" / "tables" / "resource-detail-index.parquet"
DST_DIR = ROOT / "precomputed" / "tables" / "resource-detail-small"
NEW_INDEX = ROOT / "precomputed" / "tables" / "resource-detail-index-small.parquet"

TARGET_BYTES = int(sys.argv[1]) if len(sys.argv) > 1 else 35_000_000


def main() -> None:
    DST_DIR.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    rows = con.execute(
        f"""
        SELECT id, shard, "offset", length
        FROM read_parquet('{OLD_INDEX.as_posix()}')
        ORDER BY shard, "offset"
        """
    ).fetchall()
    print(f"read {len(rows):,} index rows from {OLD_INDEX}")

    new_index: list[tuple[str, int, int, int]] = []
    shard_index = 0
    new_offset = 0
    out_f = (DST_DIR / f"{shard_index:03d}.ndjson").open("wb")
    cur_old_shard = None
    in_f = None
    total_bytes = 0

    try:
        for i, (rid, old_shard, old_offset, length) in enumerate(rows):
            if old_shard != cur_old_shard:
                if in_f is not None:
                    in_f.close()
                in_f = (SRC_DIR / f"{old_shard:03d}.ndjson").open("rb")
                cur_old_shard = old_shard
            in_f.seek(old_offset)
            data = in_f.read(length)
            if len(data) != length:
                raise RuntimeError(
                    f"short read for {rid}: expected {length}, got {len(data)}"
                )

            if new_offset + length > TARGET_BYTES and new_offset > 0:
                out_f.close()
                shard_index += 1
                new_offset = 0
                out_f = (DST_DIR / f"{shard_index:03d}.ndjson").open("wb")

            new_index.append((rid, shard_index, new_offset, length))
            out_f.write(data)
            new_offset += length
            total_bytes += length

            if (i + 1) % 300_000 == 0:
                print(f"  {i + 1:,}/{len(rows):,}")
    finally:
        out_f.close()
        if in_f is not None:
            in_f.close()

    print(f"wrote {shard_index + 1} shards, {total_bytes / 1e6:.1f} MB into {DST_DIR}")

    con.execute('CREATE TABLE idx (id VARCHAR, shard BIGINT, "offset" BIGINT, length BIGINT)')
    con.executemany("INSERT INTO idx VALUES (?, ?, ?, ?)", new_index)
    con.execute(
        f"""
        COPY (SELECT * FROM idx ORDER BY id)
        TO '{NEW_INDEX.as_posix()}' (FORMAT PARQUET)
        """
    )
    print(f"wrote index to {NEW_INDEX}")


if __name__ == "__main__":
    main()
