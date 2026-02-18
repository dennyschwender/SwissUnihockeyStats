#!/bin/bash
set -e

# Ensure cache directory exists and is writable
mkdir -p /app/data/cache

# If running as root, fix ownership then switch to appuser
if [ "$(id -u)" = "0" ]; then
    chown -R appuser:appuser /app/data
    # Execute command as appuser using gosu
    exec gosu appuser "$@"
else
    # Already running as appuser, just execute command
    exec "$@"
fi
