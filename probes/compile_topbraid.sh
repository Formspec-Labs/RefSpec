#!/bin/zsh
# Compile the tested TopBraid source and the compact probe runner.
#
# The source directory must contain the v1.5.0 tag. JENA_HOME must identify a
# local Jena distribution, and JAVA_HOME must identify JDK 21 or newer.
set -eu

if [[ $# -ne 2 ]]; then
  print -u2 "usage: $0 TOPBRAID_SOURCE OUTPUT_DIRECTORY"
  exit 2
fi
: "${JAVA_HOME:?set JAVA_HOME to JDK 21 or newer}"
: "${JENA_HOME:?set JENA_HOME to an Apache Jena distribution}"

topbraid_source=$1
output_directory=$2
repo_root=${0:A:h:h}
mkdir -p "$output_directory/classes"

# TopBraid's optional CLI tool imports the Jelly parser added by its Maven
# build. The validation API under test does not depend on that tools package.
find "$topbraid_source/src/main/java" -name '*.java' ! -path '*/tools/*' -print0 \
  | xargs -0 "$JAVA_HOME/bin/javac" -proc:none -cp "$JENA_HOME/lib/*" \
      -d "$output_directory/classes"
cp -R "$topbraid_source/src/main/resources/." "$output_directory/classes/"

"$JAVA_HOME/bin/javac" -proc:none \
  -cp "$output_directory/classes:$JENA_HOME/lib/*" \
  -d "$output_directory/classes" \
  "$repo_root/probes/TopBraidValidate.java"
