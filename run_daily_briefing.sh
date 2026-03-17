#!/bin/bash
#
# run_daily_briefing.sh - Full daily briefing pipeline
#
# Steps:
#   1. Collect messages from Slack via MCP
#   2. Summarize using local Ollama
#   3. Post summary to Slack channel
#
# Usage:
#   ./run_daily_briefing.sh              # normal run
#   ./run_daily_briefing.sh --no-post    # collect + summarize only, don't post
#

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Activate venv
if [ -f "$SCRIPT_DIR/venv/bin/activate" ]; then
    source "$SCRIPT_DIR/venv/bin/activate"
else
    echo "$(date): ERROR: venv not found. Run ./setup.sh first."
    exit 1
fi

# S7: Load environment variables from .env
if [ -f .env ]; then
    set -a
    source .env
    set +a
else
    echo "$(date): ERROR: .env not found. Run ./setup.sh first."
    exit 1
fi

# Create logs dir
mkdir -p logs

# Set date for filename
DATE=$(date +%Y-%m-%d)
YESTERDAY=$(date -v-1d +%Y-%m-%d 2>/dev/null || date -d "yesterday" +%Y-%m-%d)

BRIEFING_FILE="briefing_${DATE}.txt"
SUMMARY_FILE="briefing_summary_${DATE}.txt"

echo "$(date): ============================================="
echo "$(date): Daily Briefing Pipeline Starting"
echo "$(date): ============================================="

# -------------------------------------------------------
# Step 1: Collect messages from Slack via MCP
# -------------------------------------------------------
echo "$(date): Step 1 - Collecting messages from Slack..."

python daily_briefing.py 24 "$BRIEFING_FILE" false

if [ $? -ne 0 ]; then
    echo "$(date): ERROR: Message collection failed!"
    exit 1
fi

echo "$(date): Collection completed: $BRIEFING_FILE"

# -------------------------------------------------------
# Step 2: Summarize with local Ollama
# S6: All AI processing happens locally
# S8: PII sanitization inside ollama_summarizer.py
# -------------------------------------------------------
echo "$(date): Step 2 - Summarizing with local AI..."

# Start Ollama if not running
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "$(date): Starting Ollama..."
    ollama serve &>/dev/null &
    sleep 5
fi

# Summarize (daily_briefing.py does this automatically, but run standalone as backup)
if [ ! -f "$SUMMARY_FILE" ]; then
    python ollama_summarizer.py "$BRIEFING_FILE" "$SUMMARY_FILE"
fi

if [ ! -f "$SUMMARY_FILE" ]; then
    echo "$(date): ERROR: Summarization failed"
    echo "$(date): Raw briefing saved at $BRIEFING_FILE"
    exit 1
fi

echo "$(date): Summary generated: $SUMMARY_FILE"

# -------------------------------------------------------
# Step 3: Post to Slack
# S1: Only posts to BRIEFING_CHANNEL_ID
# S5: Summary posted as thread reply
# -------------------------------------------------------
if [ "$1" = "--no-post" ]; then
    echo "$(date): Skipping Slack posting (--no-post flag)"
elif [ -z "$BRIEFING_CHANNEL_ID" ]; then
    echo "$(date): WARNING: BRIEFING_CHANNEL_ID not set. Skipping posting."
else
    echo "$(date): Step 3 - Posting to Slack..."

    python post_summary_to_slack.py "$SUMMARY_FILE" "$YESTERDAY" "$DATE" "$BRIEFING_CHANNEL_ID"

    if [ $? -eq 0 ]; then
        echo "$(date): Briefing posted to Slack"
    else
        echo "$(date): WARNING: Posting failed (briefing saved locally)"
    fi
fi

echo "$(date): ============================================="
echo "$(date): Daily Briefing Pipeline Complete"
echo "$(date): ============================================="
