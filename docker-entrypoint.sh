#!/bin/bash
set -e

# Fix ownership of /app/data if mounted from host
if [ -d "/app/data" ]; then
    chown -R appuser:appuser /app/data
fi

# Drop to non-root user and run CMD
exec gosu appuser "$@"
