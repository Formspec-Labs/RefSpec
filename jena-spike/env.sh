# Source this to get the worktree-local JVM + Jena on PATH.
# Nothing here is installed system-wide; delete the worktree and it is gone.
SPIKE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
export JAVA_HOME="$SPIKE/jdk-21.0.12+8/Contents/Home"
export JENA_HOME="$SPIKE/apache-jena-6.2.0"
export PATH="$JAVA_HOME/bin:$JENA_HOME/bin:$PATH"
# Two other agents share this machine: cap the JVM well under the 8 GB budget.
export JVM_ARGS="${JVM_ARGS:--Xmx7g}"
