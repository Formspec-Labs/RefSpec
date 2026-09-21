"""Re-chunk the already-assembled resource-detail NDJSON shards into much smaller files.

Copies byte-identical record boundaries from resource-detail-index.parquet
(shard, offset, length per id; no JSON re-parsing or re-querying) into a
staging pair, then swaps it into the exact paths build/upload.sh walks and
public/assets/data-layer.js fetches -- nothing reads a "-small"-suffixed path,
so a run that stopped short of the final swap ships nothing. Small shards
exist because a single 238MB PUT hung under the deploy's network conditions;
the handoff invariant is that OLD_INDEX exists only while its offsets address
the shards under SRC_DIR, enforced by ordering and single renames so an
interruption can leave the index absent but never present-and-wrong, with
recover_interrupted_swap() classifying the interrupted step off the
filesystem on every start. Reaping the old pair is itself a rename-then-delete
step so a kill during the recursive delete cannot leave a layout that
_refuse() would misread as an impossible swap state.
"""

import pathlib
import shutil
import sys

import duckdb

ROOT = pathlib.Path(__file__).resolve().parent.parent
TABLES_DIR = ROOT / "precomputed" / "tables"
SRC_DIR = TABLES_DIR / "resource-detail"
OLD_INDEX = TABLES_DIR / "resource-detail-index.parquet"
# Staging only -- see the module docstring. Nothing outside this script
# should ever read these paths; main() removes them (by renaming them onto
# SRC_DIR/OLD_INDEX) before it returns on a successful run.
STAGING_DIR = TABLES_DIR / "resource-detail-small"
STAGING_INDEX = TABLES_DIR / "resource-detail-index-small.parquet"
# Where the previous, still-whole (shards, index) pair waits while the new one
# is installed. A fixed name, not a timestamped one, on purpose: it is a single
# slot, so at most one interrupted swap can ever be outstanding and
# recover_interrupted_swap() never has to guess which of several leftovers is
# the real predecessor. Its existence *is* the "a swap was in progress" marker
# -- created before the first move, removed after the last.
BACKUP_DIR = TABLES_DIR / "resource-detail.swap-backup"
BACKUP_SHARDS = BACKUP_DIR / SRC_DIR.name
BACKUP_INDEX = BACKUP_DIR / OLD_INDEX.name
# Where a slot goes to die. Nothing is ever deleted under BACKUP_DIR's own
# name: _reap() renames the slot here first, so a kill during the (long,
# non-atomic) recursive delete cannot leave a half-emptied *backup slot* for
# recover_interrupted_swap() to misread as an impossible swap state. This name
# has exactly one meaning -- "a delete was interrupted; finish it" -- and
# recovery acts on it before it looks at anything else. See the module
# docstring, "Reaping the old pair is a step too".
REAP_DIR = TABLES_DIR / "resource-detail.swap-backup.reaping"

TARGET_BYTES = int(sys.argv[1]) if len(sys.argv) > 1 else 35_000_000


def _refuse(diagnosis: str) -> None:
    """Refuse with the on-disk layout and a restore instruction; raises SystemExit."""

    raise SystemExit(
        f"reshard.py: refusing to run -- {diagnosis}\n"
        f"  shards:        {SRC_DIR} ({'present' if SRC_DIR.is_dir() else 'ABSENT'})\n"
        f"  index:         {OLD_INDEX} ({'present' if OLD_INDEX.exists() else 'ABSENT'})\n"
        f"  backup shards: {BACKUP_SHARDS} ({'present' if BACKUP_SHARDS.is_dir() else 'absent'})\n"
        f"  backup index:  {BACKUP_INDEX} ({'present' if BACKUP_INDEX.exists() else 'absent'})\n"
        f"  reap slot:     {REAP_DIR} ({'present' if REAP_DIR.exists() else 'absent'})\n"
        f"  staging:       {STAGING_DIR} / {STAGING_INDEX}\n"
        "This layout does not match any step of swap_into_place(), so it was not\n"
        "produced by an interrupted run of this script. Restore a (shards, index)\n"
        "pair that belong together -- or re-run build/precompute.py -- by hand, and\n"
        "delete the backup slot once you have."
    )


def _finish_interrupted_reap() -> None:
    """Delete whatever is left under REAP_DIR, from any point in a prior reap.

    Idempotent and order-independent: REAP_DIR holds nothing any world needs
    (it is only ever reached by _reap(), which renames a slot whose contents
    are already dead weight), so finishing the delete is always the right move
    and repeating it is free. Runs FIRST in the recovery pass, so the rest of
    the pass never has to reason about a slot and a corpse existing at once.
    """
    if REAP_DIR.is_dir():
        print(f"finishing an interrupted reap of {REAP_DIR}")
        shutil.rmtree(REAP_DIR)
    elif REAP_DIR.exists():
        # Not a directory: nothing this script writes, but it stands where a
        # rename has to land, and it is by construction not part of any pair.
        REAP_DIR.unlink()


def _reap(slot: pathlib.Path) -> None:
    """Delete a backup slot so that an interruption stays unambiguous.

    One rename, then a delete that no longer touches a name anything reads.
    See the module docstring, "Reaping the old pair is a step too", for why
    the rename is the whole point.
    """
    _finish_interrupted_reap()  # the rename below needs the target free
    slot.rename(REAP_DIR)
    shutil.rmtree(REAP_DIR)


def recover_interrupted_swap() -> None:
    """Finish or undo a swap that a previous run died in the middle of.

    Runs before anything else on every start. BACKUP_DIR exists only between
    the first and last step of swap_into_place(), so its presence means the
    previous run was interrupted, and *which* of the five steps it reached is
    readable directly off the four paths the swap moves -- no journal needed,
    because each step's effect is exactly one of them appearing or vanishing.
    """
    _finish_interrupted_reap()
    if not BACKUP_DIR.exists():
        return
    if not BACKUP_DIR.is_dir():
        _refuse(f"{BACKUP_DIR} exists but is not a directory")

    have_bi, have_bs = BACKUP_INDEX.exists(), BACKUP_SHARDS.is_dir()
    have_i, have_s = OLD_INDEX.exists(), SRC_DIR.is_dir()
    print(f"found an interrupted swap in {BACKUP_DIR} -- repairing before resharding")

    if not have_bi and not have_bs:
        # Killed between step 1 (slot created) and step 2: nothing has moved,
        # the canonical pair is untouched and old.
        if not (have_i and have_s):
            _refuse("empty backup slot, but the canonical pair is incomplete")
        print("  nothing had moved yet; dropping the empty backup slot")
    elif have_bi and not have_bs:
        # Killed between steps 2 and 3: the old index is in the slot, the old
        # shards are still canonical. Put the index back -- it is the old
        # shards' own index, so the pair is whole again.
        if have_i or not have_s:
            _refuse("the index is in the backup slot, but the canonical pair is not the old shards alone")
        BACKUP_INDEX.rename(OLD_INDEX)
        print(f"  restored the previous index to {OLD_INDEX} (old shards were never moved)")
    elif have_bi and have_bs and have_i and have_s:
        # Killed between steps 5 and 6: the new pair is already installed and
        # live; only the reaping of the old one was left.
        print("  the new pair was already fully installed; reaping the old one")
    elif have_bi and have_bs and not have_i and not have_s:
        # Killed between steps 3 and 4: both halves of the old pair are in the
        # slot and nothing is canonical. Put both back.
        BACKUP_SHARDS.rename(SRC_DIR)
        BACKUP_INDEX.rename(OLD_INDEX)
        print(f"  restored the previous pair to {SRC_DIR} and {OLD_INDEX}")
    elif have_bi and have_bs and not have_i and have_s:
        # Killed between steps 4 and 5 -- the only window where the canonical
        # shards are the NEW ones. Roll forward if their matching staged index
        # survived (STAGING_DIR gone + STAGING_INDEX present is precisely the
        # state step 4 leaves behind, so the two are a matched pair); otherwise
        # the new pair is unrecoverable and the old one goes back.
        if STAGING_INDEX.exists() and not STAGING_DIR.exists():
            STAGING_INDEX.rename(OLD_INDEX)
            print(f"  completed the interrupted swap: installed the staged index at {OLD_INDEX}")
        else:
            # Unlike the reap below, this rmtree needs no rename first: it runs
            # in the one window where there is no canonical index at all, so
            # every state it can be killed in is still "no index" -- either a
            # part-emptied SRC_DIR (this same branch again, which redoes the
            # delete) or none (the steps 3-4 branch, which restores both
            # halves). Neither reads what is left of SRC_DIR, so a partial
            # delete cannot be misclassified the way a partial reap could.
            shutil.rmtree(SRC_DIR)
            BACKUP_SHARDS.rename(SRC_DIR)
            BACKUP_INDEX.rename(OLD_INDEX)
            print(f"  the staged index did not survive; rolled back to the previous pair at {SRC_DIR}")
    else:
        _refuse("the backup slot holds shards but no index, which no step of the swap produces")

    _reap(BACKUP_DIR)


def swap_into_place() -> None:
    """Install the staged pair, keeping the old one whole until it is live.

    Five ordered steps, each a single filesystem operation, each leaving a
    state recover_interrupted_swap() can read back and finish or undo. Step 5
    is the flip: it is the one operation that moves consumers from the old
    world to the new one, and it is last precisely so that the index is never
    the odd half of a crossed pair (module docstring, "The handoff invariant").
    """
    if BACKUP_DIR.exists():
        _refuse(f"{BACKUP_DIR} still exists after the recovery pass")
    if REAP_DIR.exists():
        _refuse(f"{REAP_DIR} still exists after the recovery pass")
    BACKUP_DIR.mkdir()  # 1. open the slot; from here on a kill is detectable
    OLD_INDEX.rename(BACKUP_INDEX)  # 2. index out FIRST: readers now fail closed
    SRC_DIR.rename(BACKUP_SHARDS)  # 3. old shards out, still whole, still paired
    STAGING_DIR.rename(SRC_DIR)  # 4. new shards in (no index yet -- still closed)
    STAGING_INDEX.rename(OLD_INDEX)  # 5. THE FLIP: new index in, new world live
    print(f"replaced {SRC_DIR} and {OLD_INDEX} with the resharded output")
    # 6. The old pair is now dead weight. It is reaped rather than kept because
    # build/upload.sh walks *everything* under precomputed/ with `find -type f`
    # -- a surviving backup would be uploaded to R2 as a second, orphaned copy
    # of the entire corpus under a key prefix no consumer ever reads. Reaped
    # via _reap(), i.e. rename-then-delete, so this last step is as
    # interruptible as the five above it: see the module docstring's "Reaping
    # the old pair is a step too".
    _reap(BACKUP_DIR)


def main() -> None:
    # Repair first: a previous run killed mid-swap leaves a coherent but
    # incomplete layout, and resharding on top of one would read the wrong
    # source (or no source at all). See recover_interrupted_swap().
    recover_interrupted_swap()
    if not SRC_DIR.is_dir() or not OLD_INDEX.exists():
        _refuse("there is no (shards, index) pair to reshard -- run build/precompute.py first")

    # Stale-shard cleanup, mirroring build/precompute.py's own fix for the
    # identical failure mode (see its "Clear stale shards first" comment): a
    # previous reshard.py run -- interrupted, or run with a larger
    # TARGET_BYTES -- can leave more staging shards than this run writes.
    # Clear them before writing so an aborted run never leaves a file this
    # run's index doesn't know about sitting in the staging directory.
    if STAGING_DIR.exists():
        shutil.rmtree(STAGING_DIR)
    STAGING_DIR.mkdir(parents=True)
    STAGING_INDEX.unlink(missing_ok=True)

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
    out_f = (STAGING_DIR / f"{shard_index:03d}.ndjson").open("wb")
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
                out_f = (STAGING_DIR / f"{shard_index:03d}.ndjson").open("wb")

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

    print(f"wrote {shard_index + 1} shards, {total_bytes / 1e6:.1f} MB into {STAGING_DIR}")

    con.execute('CREATE TABLE idx (id VARCHAR, shard BIGINT, "offset" BIGINT, length BIGINT)')
    con.executemany("INSERT INTO idx VALUES (?, ?, ?, ?)", new_index)
    con.execute(
        f"""
        COPY (SELECT * FROM idx ORDER BY id)
        TO '{STAGING_INDEX.as_posix()}' (FORMAT PARQUET)
        """
    )
    print(f"wrote index to {STAGING_INDEX}")

    # Replace: every read from SRC_DIR/OLD_INDEX above is done, so it is now
    # safe to swap the staged, resharded output into their place -- the
    # paths build/upload.sh walks and public/assets/data-layer.js actually
    # fetches. The old shard directory is moved aside whole rather than
    # merged into: it can hold MORE shards than this run wrote (a larger
    # TARGET_BYTES last run, or a bigger corpus), and those extras are
    # exactly the "stale shard" failure build/precompute.py already guards
    # against for its own output -- ship them and they sit in R2 as orphaned
    # objects from a previous build's corpus, never referenced by the index
    # this run just wrote (see build/precompute.py's "Clear stale shards
    # first" comment for the incident this class of bug caused).
    swap_into_place()


if __name__ == "__main__":
    main()
