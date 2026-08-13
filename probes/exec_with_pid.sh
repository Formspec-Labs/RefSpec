#!/bin/sh
set -eu

if [ "$#" -lt 2 ]; then
    echo "usage: exec_with_pid.sh PID_FILE COMMAND [ARG ...]" >&2
    exit 2
fi

pid_file=$1
shift
printf '%s\n' "$$" > "$pid_file"
exec "$@"
