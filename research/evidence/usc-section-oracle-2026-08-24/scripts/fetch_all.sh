#!/bin/zsh
# Re-fetch the OLRC sources for generation 2 of the U.S.C. section oracle.
# Keyless. sleep 1 between fetches. Logs URL, bytes, sha256, fetch time per file.
set -uo pipefail
W=/Users/mikewolfd/Work/RefSpec/output/usc-annual-2026-08-24
LOG=$W/fetch_log.tsv
[[ -f $LOG ]] || print -r -- "file\turl\tbytes\tsha256\tstarted_local\tfinished_local\tseconds\thttp" > $LOG

fetch() {
  local out=$1 url=$2
  if [[ -s $W/$out ]] && grep -q "^$out	" $LOG; then
    print -r -- "skip $out (already fetched)"
    return 0
  fi
  local t0=$(date +%s) start=$(date '+%Y-%m-%dT%H:%M:%S')
  local code
  code=$(curl -sS -L --http1.1 --retry 3 -w '%{http_code}' -o $W/$out "$url")
  local t1=$(date +%s) fin=$(date '+%Y-%m-%dT%H:%M:%S')
  local bytes=$(stat -f %z $W/$out)
  local sha=$(shasum -a 256 $W/$out | awk '{print $1}')
  print -r -- "$out\t$url\t$bytes\t$sha\t$start\t$fin\t$((t1-t0))\t$code" >> $LOG
  print -r -- "done $out $bytes $code $((t1-t0))s"
  sleep 1
}

fetch xml_uscAll_119-102.zip "https://uscode.house.gov/download/releasepoints/us/pl/119/102/xml_uscAll@119-102.zip"
for y in {1994..2024}; do
  fetch $y.zip "https://uscode.house.gov/download/annualhistoricalarchives/XHTML/$y.zip"
done
print -r -- "ALL FETCHES COMPLETE"
