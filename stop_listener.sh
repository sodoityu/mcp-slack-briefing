#!/bin/bash
#
# stop_listener.sh - Stop the background Q&A listener
#

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$SCRIPT_DIR/.qa_listener.pid"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        rm "$PID_FILE"
        echo "Q&A listener stopped (PID: $PID)"
    else
        rm "$PID_FILE"
        echo "Listener was not running (stale PID file removed)"
    fi
else
    echo "No listener PID file found. It may not be running."
    echo "Check manually: ps aux | grep qa_listener"
fi
