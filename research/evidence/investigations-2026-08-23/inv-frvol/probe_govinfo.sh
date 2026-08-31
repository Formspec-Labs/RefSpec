#!/bin/bash
set -e
echo "=== modern issue 2020-12-31 ==="
for path in \
  "https://www.govinfo.gov/content/pkg/FR-2020-12-31/mods.xml" \
  "https://www.govinfo.gov/content/pkg/FR-2020-12-31/pdf/FR-2020-12-31.pdf" \
  "https://www.govinfo.gov/content/pkg/FR-2020-12-31/premis.xml" \
  "https://www.govinfo.gov/content/pkg/FR-2020-12-31/summary.xml"
do
  code=$(curl -sL -o /dev/null -w "%{http_code}" --max-time 20 "$path")
  echo "$code   $path"
done
echo "=== 1993-12-30 ==="
for path in \
  "https://www.govinfo.gov/content/pkg/FR-1993-12-30/mods.xml" \
  "https://www.govinfo.gov/content/pkg/FR-1993-12-30/pdf/FR-1993-12-30.pdf" \
  "https://www.govinfo.gov/content/pkg/FR-1993-12-30/premis.xml" \
  "https://www.govinfo.gov/content/pkg/FR-1993-12-30/summary.xml"
do
  code=$(curl -sL -o /dev/null -w "%{http_code}" --max-time 20 "$path")
  echo "$code   $path"
done
