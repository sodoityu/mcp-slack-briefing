#!/bin/bash
#
# stop_listener.sh - Stop ALL Q&A listener processes
#

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$SCRIPT_DIR/.qa_listener.pid"

# Kill via PID file
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    kill "$PID" 2>/dev/null && echo "Stopped listener (PID: $PID)" || true
    rm -f "$PID_FILE"
fi

# Kill any orphaned processes
KILLED=$(pkill -f "python.*qa_listener.py" 2>/dev/null && echo "yes" || echo "no")
if [ "$KILLED" = "yes" ]; then
    echo "Stopped orphaned listener process(es)"
fi

if [ "$KILLED" = "no" ] && [ ! -f "$PID_FILE" ]; then
    echo "No listener running"
fi
