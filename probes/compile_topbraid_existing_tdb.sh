#!/bin/sh
set -eu

if [ "$#" -ne 3 ]; then
    echo "usage: compile_topbraid_existing_tdb.sh TOPBRAID_CLASSES JENA_HOME OUTPUT_DIRECTORY" >&2
    exit 2
fi
: "${JAVA_HOME:?set JAVA_HOME to JDK 21 or newer}"

topbraid_classes=$1
jena_home=$2
output_directory=$3
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

test -f "$topbraid_classes/TopBraidValidateTdb.class"
test -d "$jena_home/lib"
mkdir -p "$output_directory"
"$JAVA_HOME/bin/javac" -proc:none \
    -cp "$topbraid_classes:$jena_home/lib/*" \
    -d "$output_directory" \
    "$repo_root/probes/TopBraidValidateExistingTdb.java"
