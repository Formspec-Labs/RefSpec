#!/bin/zsh
# Compile the verified Jena 5.6 SHACL Core source over a local Jena 6 base.
#
# This is a deliberately qualified regression probe, not an exact Jena 5.6
# distribution build. See measurements/jena-5.6-source-verification.txt.
set -eu

if [[ $# -ne 2 ]]; then
  print -u2 "usage: $0 JENA_5_SOURCE OUTPUT_DIRECTORY"
  exit 2
fi
: "${JAVA_HOME:?set JAVA_HOME to JDK 21 or newer}"
: "${JENA_HOME:?set JENA_HOME to the local Jena 6.2 distribution}"

source_directory=$1
output_directory=$2
repo_root=${0:A:h:h}
mkdir -p "$output_directory/classes"

# Compact syntax is not part of the Atlas workload. Imports.java and these two
# SHACL-SPARQL files use Jena 5 ARQ builder methods removed in Jena 6. The Atlas
# shapes use SHACL Core only; the base Jena jar supplies unreachable classes for
# those optional paths while the 5.6 Core parser and engine shadow the base jar.
find "$source_directory/jena-shacl/src/main/java" -name '*.java' \
  ! -path '*/compact/*' \
  ! -name 'Imports.java' \
  ! -name 'SparqlValidation.java' \
  ! -name 'EvalSparql.java' \
  -print0 \
  | xargs -0 "$JAVA_HOME/bin/javac" -proc:none -cp "$JENA_HOME/lib/*" \
      -d "$output_directory/classes"
cp -R "$source_directory/jena-shacl/src/main/resources/." \
  "$output_directory/classes/"

"$JAVA_HOME/bin/javac" -proc:none \
  -cp "$output_directory/classes:$JENA_HOME/lib/*" \
  -d "$output_directory/classes" \
  "$repo_root/probes/JenaValidate.java"
