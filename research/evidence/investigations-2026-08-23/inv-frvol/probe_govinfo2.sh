#!/bin/bash
paths=(
  "https://www.govinfo.gov/metadata/pkg/FR-2020-12-31/mods.xml"
  "https://www.govinfo.gov/metadata/granule/FR-2020-12-31/mods.xml"
  "https://www.govinfo.gov/content/pkg/FR-2020-12-31/mods/FR-2020-12-31.xml"
  "https://www.govinfo.gov/content/pkg/FR-2020-12-31/FR-2020-12-31-mods.xml"
  "https://www.govinfo.gov/content/pkg/FR-2020-12-31/html/FR-2020-12-31.htm"
  "https://www.govinfo.gov/link/fr/2020/vol85/page89283"
)
for p in "${paths[@]}"; do
  echo "--- $p ---"
  curl -sL --max-time 20 "$p" -o /tmp/probe_body.txt -w "HTTP %{http_code} bytes %{size_download} content-type %{content_type}\n"
  head -c 200 /tmp/probe_body.txt
  echo ""
done
