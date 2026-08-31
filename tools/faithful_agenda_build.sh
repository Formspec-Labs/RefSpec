#!/bin/zsh
# Faithful scratch build of the Unified Agenda Parquet from a given commit, for
# attributing a rebuild value by value. Usage: tools/faithful_agenda_build.sh <commit> <scratch-dir>
# The builder finds its pinned oracles (Public Law roster, OFR part index, the
# section oracle under research/, the act indexes and source credits under
# output/) relative to its own file, so an unpacked tree must see them: each is
# linked READ-ONLY into the scratch root. Writes go only to <scratch-dir>/out.
# Six rebuilds on 2026-08-22/23 were attributed this way; the receipt of the
# faithful build matched the artifact byte for byte every time.
set -e
set -u
if [[ $# -lt 2 ]]; then
  echo "usage: tools/faithful_agenda_build.sh <commit> <scratch-dir>" >&2
  exit 1
fi
COMMIT="$1"; S="$2"
REPO=/Users/mikewolfd/Work/RefSpec
cd "$REPO"
rm -rf "$S"; mkdir -p "$S/src" "$S/out" "$S/output/registry-real-data-sources"
git archive "$COMMIT" src | tar -x -C "$S"
ln -sfn "$REPO/output/registry-real-data-sources/public-law-roster" "$S/output/registry-real-data-sources/public-law-roster"
ln -sfn "$REPO/research" "$S/research"
for d in usc-act-index-2026-08-02 usc-act-index-2026-08-22 usc-source-credit-index-2026-08-02; do
  ln -sfn "$REPO/output/$d" "$S/output/$d"
done
test -f "$S/output/registry-real-data-sources/public-law-roster/public-law-roster.csv"
test -f "$S/research/evidence/cfr-subject-index-2026-08-20/part-subjects.csv"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$S/src" uv run python -m refspec.registry.unified_agenda_parquet \
  --source-root output/registry-real-data-sources/unified-agenda-editions \
  --output-root "$S/out" > "$S/build.log" 2>&1
echo "faithful build of $COMMIT: exit $? -> $S/out"
grep -o '"legalAuthorities": *[0-9]*\|"to-separator-roster-existence": *[0-9]*\|"uscTitleOutOfSeriesRows": *[0-9]*' "$S/out/receipt.json"
