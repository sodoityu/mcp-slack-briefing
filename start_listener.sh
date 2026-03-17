#!/bin/bash
#
# start_listener.sh - Start the Q&A listener for briefing follow-ups
#
# Usage:
#   ./start_listener.sh           # Run in foreground
#   ./start_listener.sh --bg      # Run in background (logs to logs/qa_listener.log)
#

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Activate venv
if [ -f "$SCRIPT_DIR/venv/bin/activate" ]; then
    source "$SCRIPT_DIR/venv/bin/activate"
else
    echo "ERROR: venv not found. Run ./setup.sh first."
    exit 1
fi

# Load environment
if [ -f .env ]; then
    set -a
    source .env
    set +a
else
    echo "ERROR: .env not found. Run ./setup.sh first."
    exit 1
fi

# Check Ollama
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "Starting Ollama..."
    ollama serve &>/dev/null &
    sleep 3
fi

# Create logs dir
mkdir -p logs

if [ "$1" = "--bg" ]; then
    echo "Starting Q&A listener in background..."
    nohup python qa_listener.py >> logs/qa_listener.log 2>&1 &
    LISTENER_PID=$!
    echo $LISTENER_PID > .qa_listener.pid
    echo "Listener running (PID: $LISTENER_PID)"
    echo "Logs: tail -f logs/qa_listener.log"
    echo "Stop: ./stop_listener.sh"
else
    echo "Starting Q&A listener (Ctrl+C to stop)..."
    echo ""
    python qa_listener.py
fi
