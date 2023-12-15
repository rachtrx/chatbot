#!/bin/bash

set -e

host="$1"
shift
cmd=("$@")  # Store command and arguments in an array

until curl -s "$host" > /dev/null; do
  >&2 echo "Gunicorn is unavailable - sleeping"
  sleep 10
done

>&2 echo "Gunicorn is up - executing command"
exec "${cmd[@]}"  # Execute the command using array expansion