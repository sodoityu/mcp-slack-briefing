#!/bin/bash
#
# install.sh - Single-command installer for Slack Daily Briefing Agent
#
# Usage: chmod +x install.sh && ./install.sh
#
# This script does EVERYTHING:
#   1. Installs system dependencies (Ollama, Podman)
#   2. Sets up Python environment
#   3. Prompts for all configuration (tokens, channels)
#   4. Creates .env and .mcp.json
#   5. Runs the first briefing immediately
#   6. Sets up daily cron job
#   7. Starts the Q&A listener
#

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Detect OS
OS="$(uname)"
if [ "$OS" = "Darwin" ]; then
    PLATFORM="macOS"
elif [ -f /etc/fedora-release ]; then
    PLATFORM="Fedora"
elif [ -f /etc/redhat-release ]; then
    PLATFORM="RHEL"
else
    PLATFORM="Linux"
fi

clear
echo "============================================="
echo "  Slack Daily Briefing Agent"
echo "  One-command installer ($PLATFORM)"
echo "============================================="
echo ""
echo "This will set up everything and run your first briefing."
echo ""
read -p "Press Enter to continue (Ctrl+C to abort)..."
echo ""

# =============================================================
# PHASE 1: Install system dependencies
# =============================================================
echo "============================================="
echo "  Phase 1: Installing dependencies"
echo "============================================="
echo ""

# --- Python ---
if ! command -v python3 &>/dev/null; then
    echo "Installing Python 3..."
    if [ "$OS" = "Darwin" ]; then
        brew install python
    else
        sudo dnf install -y python3 python3-pip
    fi
else
    echo "[ok] Python: $(python3 --version)"
fi

# --- Podman ---
if ! command -v podman &>/dev/null; then
    echo "Installing Podman..."
    if [ "$OS" = "Darwin" ]; then
        brew install podman
    else
        sudo dnf install -y podman
    fi
else
    echo "[ok] Podman: $(podman --version)"
fi

# --- Ollama ---
if ! command -v ollama &>/dev/null; then
    echo "Installing Ollama..."
    if [ "$OS" = "Darwin" ]; then
        brew install ollama
    else
        curl -fsSL https://ollama.com/install.sh | sh
    fi
else
    echo "[ok] Ollama: $(ollama --version 2>&1 | head -1)"
fi

echo ""

# =============================================================
# PHASE 2: Set up Python environment
# =============================================================
echo "============================================="
echo "  Phase 2: Python environment"
echo "============================================="
echo ""

if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi
source venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
echo "[ok] Python venv ready with dependencies"
echo ""

# =============================================================
# PHASE 3: Start Podman
# =============================================================
echo "============================================="
echo "  Phase 3: Starting Podman"
echo "============================================="
echo ""

if [ "$OS" = "Darwin" ]; then
    if ! podman machine inspect 2>/dev/null | grep -q '"Running"'; then
        if ! podman machine inspect 2>/dev/null | grep -q '"State"'; then
            echo "Initializing Podman machine (first time, may take a minute)..."
            podman machine init
        fi
        echo "Starting Podman machine..."
        podman machine start 2>/dev/null || true
    fi
    echo "[ok] Podman machine running"
else
    echo "[ok] Podman runs natively on Linux"
fi

# Pull Slack MCP container
if ! podman image exists quay.io/redhat-ai-tools/slack-mcp 2>/dev/null; then
    echo "Pulling Slack MCP container (first time)..."
    podman pull quay.io/redhat-ai-tools/slack-mcp:latest
else
    echo "[ok] Slack MCP container ready"
fi
echo ""

# =============================================================
# PHASE 4: Start Ollama and pull model
# =============================================================
echo "============================================="
echo "  Phase 4: Starting Ollama"
echo "============================================="
echo ""

if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "Starting Ollama..."
    if [ "$OS" = "Linux" ]; then
        sudo systemctl start ollama 2>/dev/null || ollama serve &>/dev/null &
        sudo systemctl enable ollama 2>/dev/null || true
    else
        ollama serve &>/dev/null &
    fi
    sleep 3
fi
echo "[ok] Ollama running"

if ! ollama list 2>/dev/null | grep -q "llama3.1:8b"; then
    echo "Pulling llama3.1:8b model (4.7GB, first time only)..."
    ollama pull llama3.1:8b
else
    echo "[ok] Model llama3.1:8b ready"
fi
echo ""

# =============================================================
# PHASE 5: Configuration (interactive prompts)
# =============================================================
echo "============================================="
echo "  Phase 5: Configuration"
echo "============================================="
echo ""
echo "You need two things from Slack. Open Slack in your BROWSER"
echo "(not the desktop app) and open DevTools (F12)."
echo ""

# --- Check if already configured ---
if [ -f ".mcp.json" ] && [ -f ".env" ]; then
    echo "Existing configuration found."
    read -p "Reconfigure? (y/n, default n): " reconfig
    if [ "$reconfig" != "y" ]; then
        echo "Keeping existing configuration."
        SKIP_CONFIG=true
    fi
fi

if [ "$SKIP_CONFIG" != "true" ]; then

    # --- Slack tokens ---
    echo ""
    echo "--- Slack Tokens ---"
    echo ""
    echo "1. XOXC token: DevTools > Network tab > click any channel >"
    echo "   find request to api.slack.com > look for 'token' in request body"
    echo "   (starts with xoxc-)"
    echo ""
    read -p "Enter your xoxc token: " XOXC_TOKEN

    echo ""
    echo "2. XOXD token: DevTools > Application tab > Cookies >"
    echo "   find cookie named 'd' (starts with xoxd-)"
    echo ""
    read -p "Enter your xoxd token: " XOXD_TOKEN

    echo ""
    echo "3. Workspace URL (e.g., https://mycompany.slack.com)"
    echo ""
    read -p "Enter workspace URL: " WORKSPACE_URL
    WORKSPACE_URL=${WORKSPACE_URL%/}  # Remove trailing slash

    # --- Channel configuration ---
    echo ""
    echo "--- Channel Configuration ---"
    echo ""
    echo "Get channel IDs by right-clicking a channel in Slack >"
    echo "'View channel details' > ID is at the bottom (starts with C)"
    echo ""

    read -p "Briefing channel ID (where summaries get posted): " BRIEFING_CHANNEL_ID

    echo ""
    echo "Now enter the channels to MONITOR for messages."
    echo "Enter one at a time. Type 'done' when finished."
    echo ""

    CHANNELS_JSON="["
    CHANNEL_COUNT=0
    while true; do
        read -p "Channel ID (or 'done'): " CH_ID
        if [ "$CH_ID" = "done" ] || [ -z "$CH_ID" ]; then
            break
        fi
        read -p "Channel name (e.g., team-platform): " CH_NAME

        if [ $CHANNEL_COUNT -gt 0 ]; then
            CHANNELS_JSON+=","
        fi
        CHANNELS_JSON+="{\"id\":\"$CH_ID\",\"name\":\"$CH_NAME\"}"
        CHANNEL_COUNT=$((CHANNEL_COUNT + 1))
        echo "  Added #$CH_NAME ($CH_ID) - $CHANNEL_COUNT channel(s) total"
        echo ""
    done
    CHANNELS_JSON+="]"

    if [ $CHANNEL_COUNT -eq 0 ]; then
        echo "ERROR: You must add at least one channel to monitor."
        exit 1
    fi

    # --- Logs channel (for MCP server) ---
    LOGS_CHANNEL_ID="$BRIEFING_CHANNEL_ID"  # Reuse briefing channel

    # --- Write .mcp.json ---
    cat > .mcp.json << MCPEOF
{
  "mcpServers": {
    "slack": {
      "command": "podman",
      "args": [
        "run",
        "-i",
        "--rm",
        "-e",
        "SLACK_XOXC_TOKEN",
        "-e",
        "SLACK_XOXD_TOKEN",
        "-e",
        "LOGS_CHANNEL_ID",
        "-e",
        "MCP_TRANSPORT",
        "quay.io/redhat-ai-tools/slack-mcp"
      ],
      "env": {
        "SLACK_XOXC_TOKEN": "$XOXC_TOKEN",
        "SLACK_XOXD_TOKEN": "$XOXD_TOKEN",
        "SLACK_WORKSPACE_URL": "$WORKSPACE_URL",
        "LOGS_CHANNEL_ID": "$LOGS_CHANNEL_ID",
        "MCP_TRANSPORT": "stdio"
      }
    }
  }
}
MCPEOF
    echo ""
    echo "[ok] .mcp.json created"

    # --- Write .env ---
    cat > .env << ENVEOF
BRIEFING_CHANNEL_ID=$BRIEFING_CHANNEL_ID
MONITORED_CHANNELS='$CHANNELS_JSON'
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b
QA_POLL_INTERVAL=10
MCP_CONFIG_PATH=.mcp.json
ENVEOF
    echo "[ok] .env created"
    echo ""
fi

# Make scripts executable
chmod +x run_daily_briefing.sh start_listener.sh stop_listener.sh setup_cron.sh 2>/dev/null || true

# Create logs directory
mkdir -p logs

# =============================================================
# PHASE 6: Run first briefing
# =============================================================
echo "============================================="
echo "  Phase 6: Running first briefing"
echo "============================================="
echo ""

# Load env
set -a
source .env
set +a

echo "Collecting messages from $CHANNEL_COUNT channel(s)..."
echo ""

# Run the full pipeline
./run_daily_briefing.sh

echo ""

# =============================================================
# PHASE 7: Set up daily cron
# =============================================================
echo "============================================="
echo "  Phase 7: Daily automation"
echo "============================================="
echo ""

read -p "What hour should the briefing run daily? (0-23, default 9): " CRON_HOUR
CRON_HOUR=${CRON_HOUR:-9}

# Remove old cron entry if exists
crontab -l 2>/dev/null | grep -v "run_daily_briefing.sh" | crontab - 2>/dev/null

# Add new cron entry
(crontab -l 2>/dev/null; echo "0 $CRON_HOUR * * * cd $SCRIPT_DIR && ./run_daily_briefing.sh >> logs/daily_briefing.log 2>&1") | crontab -

echo "[ok] Cron job set: daily at ${CRON_HOUR}:00"
echo ""

# =============================================================
# PHASE 8: Start Q&A listener
# =============================================================
echo "============================================="
echo "  Phase 8: Starting Q&A listener"
echo "============================================="
echo ""

# Stop any existing listener
if [ -f .qa_listener.pid ]; then
    OLD_PID=$(cat .qa_listener.pid)
    kill "$OLD_PID" 2>/dev/null || true
    rm -f .qa_listener.pid
fi

# Start listener in background
source venv/bin/activate
set -a; source .env; set +a
nohup python qa_listener.py >> logs/qa_listener.log 2>&1 &
LISTENER_PID=$!
echo $LISTENER_PID > .qa_listener.pid
echo "[ok] Q&A listener running (PID: $LISTENER_PID)"
echo ""

# Set up persistent service (optional, non-blocking)
if [ "$OS" = "Darwin" ]; then
    PLIST_NAME="com.slack-briefing.qa-listener"
    PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"
    if [ ! -f "$PLIST_PATH" ]; then
        mkdir -p "$HOME/Library/LaunchAgents"
        cat > "$PLIST_PATH" << PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_NAME}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${SCRIPT_DIR}/start_listener.sh</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${SCRIPT_DIR}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${SCRIPT_DIR}/logs/qa_listener.log</string>
    <key>StandardErrorPath</key>
    <string>${SCRIPT_DIR}/logs/qa_listener.log</string>
</dict>
</plist>
PLISTEOF
        launchctl load "$PLIST_PATH" 2>/dev/null || true
        echo "[ok] Auto-start service installed (launchd)"
    fi
elif [ "$OS" = "Linux" ]; then
    SERVICE_NAME="slack-briefing-qa"
    SERVICE_DIR="$HOME/.config/systemd/user"
    SERVICE_PATH="$SERVICE_DIR/${SERVICE_NAME}.service"
    if [ ! -f "$SERVICE_PATH" ]; then
        mkdir -p "$SERVICE_DIR"
        cat > "$SERVICE_PATH" << SVCEOF
[Unit]
Description=Slack Briefing Q&A Listener
After=network.target ollama.service

[Service]
Type=simple
WorkingDirectory=${SCRIPT_DIR}
ExecStart=${SCRIPT_DIR}/start_listener.sh
Restart=on-failure
RestartSec=10
StandardOutput=append:${SCRIPT_DIR}/logs/qa_listener.log
StandardError=append:${SCRIPT_DIR}/logs/qa_listener.log

[Install]
WantedBy=default.target
SVCEOF
        loginctl enable-linger "$USER" 2>/dev/null || true
        systemctl --user daemon-reload
        systemctl --user enable "$SERVICE_NAME" 2>/dev/null || true
        systemctl --user start "$SERVICE_NAME" 2>/dev/null || true
        echo "[ok] Auto-start service installed (systemd)"
    fi
fi

# =============================================================
# DONE
# =============================================================
echo ""
echo "============================================="
echo "  Setup Complete!"
echo "============================================="
echo ""
echo "  What just happened:"
echo "    - Installed all dependencies"
echo "    - Configured Slack connection"
echo "    - Ran your first briefing and posted it"
echo "    - Cron job runs daily at ${CRON_HOUR}:00"
echo "    - Q&A listener is running in background"
echo ""
echo "  Go to Slack now:"
echo "    1. Find the briefing post in your channel"
echo "    2. Reply in the thread with a question"
echo "    3. Get an AI-powered answer within 10 seconds"
echo ""
echo "  Useful commands:"
echo "    tail -f logs/qa_listener.log     # Q&A listener logs"
echo "    tail -f logs/daily_briefing.log  # daily briefing logs"
echo "    ./stop_listener.sh               # stop Q&A listener"
echo "    ./start_listener.sh              # restart Q&A listener"
echo "    ./run_daily_briefing.sh          # run briefing manually"
echo ""
