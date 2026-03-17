#!/bin/bash
#
# setup.sh - One-time setup for the Slack Daily Briefing Agent
#
# Works on both macOS (Apple Silicon) and Linux (Fedora/RHEL)
#
# Run this after cloning the repo:
#   chmod +x setup.sh && ./setup.sh
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

echo "============================================="
echo "  Slack Daily Briefing Agent - Setup"
echo "  Platform: $PLATFORM"
echo "============================================="
echo ""

# -------------------------------------------------------
# Step 1: Check prerequisites
# -------------------------------------------------------
echo "[1/6] Checking prerequisites..."

# Check Python
if ! command -v python3 &>/dev/null; then
    if [ "$OS" = "Darwin" ]; then
        echo "ERROR: Python 3 not found. Install with: brew install python"
    else
        echo "ERROR: Python 3 not found. Install with: sudo dnf install python3"
    fi
    exit 1
fi
PYTHON_VERSION=$(python3 --version 2>&1)
echo "  Python: $PYTHON_VERSION"

# Check python3-venv on Linux (needed for venv creation)
if [ "$OS" = "Linux" ]; then
    if ! python3 -m venv --help &>/dev/null 2>&1; then
        echo "  Installing python3-venv..."
        sudo dnf install -y python3-pip 2>/dev/null || sudo apt install -y python3-venv 2>/dev/null || true
    fi
fi

# Check Podman
if ! command -v podman &>/dev/null; then
    if [ "$OS" = "Darwin" ]; then
        echo "ERROR: Podman not found. Install with: brew install podman"
    else
        echo "ERROR: Podman not found. Install with: sudo dnf install podman"
    fi
    exit 1
fi
echo "  Podman: $(podman --version)"

# Check Ollama
if ! command -v ollama &>/dev/null; then
    echo "  Ollama: NOT INSTALLED"
    echo ""
    read -p "  Install Ollama now? (y/n): " install_ollama
    if [ "$install_ollama" = "y" ]; then
        if [ "$OS" = "Darwin" ]; then
            brew install ollama
        else
            # Linux: use the official install script
            curl -fsSL https://ollama.com/install.sh | sh
        fi
    else
        if [ "$OS" = "Darwin" ]; then
            echo "  Install later with: brew install ollama"
        else
            echo "  Install later with: curl -fsSL https://ollama.com/install.sh | sh"
        fi
    fi
else
    echo "  Ollama: $(ollama --version 2>&1 | head -1)"
fi

echo ""

# -------------------------------------------------------
# Step 2: Create Python virtual environment
# -------------------------------------------------------
echo "[2/6] Setting up Python virtual environment..."

if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "  Created venv/"
else
    echo "  venv/ already exists"
fi

source venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
echo "  Dependencies installed"
echo ""

# -------------------------------------------------------
# Step 3: Pull Ollama model
# -------------------------------------------------------
echo "[3/6] Setting up Ollama model..."

if command -v ollama &>/dev/null; then
    # Start Ollama if not running
    if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo "  Starting Ollama..."
        if [ "$OS" = "Linux" ]; then
            # On Linux, Ollama runs as a systemd service
            sudo systemctl start ollama 2>/dev/null || ollama serve &>/dev/null &
        else
            ollama serve &>/dev/null &
        fi
        sleep 3
    fi

    # Check if model exists
    if ollama list 2>/dev/null | grep -q "llama3.1:8b"; then
        echo "  Model llama3.1:8b already pulled"
    else
        echo "  Pulling llama3.1:8b (this may take a few minutes)..."
        ollama pull llama3.1:8b
    fi
else
    echo "  Skipped (Ollama not installed)"
fi
echo ""

# -------------------------------------------------------
# Step 4: Pull Slack MCP container
# -------------------------------------------------------
echo "[4/6] Setting up Slack MCP container..."

# macOS needs a Podman machine (VM). Linux runs containers natively.
if [ "$OS" = "Darwin" ]; then
    if ! podman machine inspect 2>/dev/null | grep -q '"State"'; then
        echo "  Initializing Podman machine..."
        podman machine init
    fi
    if ! podman machine inspect 2>/dev/null | grep -q '"Running"'; then
        echo "  Starting Podman machine..."
        podman machine start 2>/dev/null || true
    fi
fi
# Linux: no machine needed, Podman runs natively

if podman image exists quay.io/redhat-ai-tools/slack-mcp 2>/dev/null; then
    echo "  Slack MCP image already pulled"
else
    echo "  Pulling Slack MCP container..."
    podman pull quay.io/redhat-ai-tools/slack-mcp:latest
fi
echo ""

# -------------------------------------------------------
# Step 5: Create config files from templates
# -------------------------------------------------------
echo "[5/6] Setting up configuration files..."

if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "  Created .env from template"
    echo "  >>> EDIT .env with your channel IDs <<<"
else
    echo "  .env already exists"
fi

if [ ! -f ".mcp.json" ]; then
    cp .mcp.json.example .mcp.json
    echo "  Created .mcp.json from template"
    echo "  >>> EDIT .mcp.json with your Slack tokens (xoxc/xoxd) <<<"
else
    echo "  .mcp.json already exists"
fi

# Create logs directory
mkdir -p logs
echo ""

# -------------------------------------------------------
# Step 6: Make scripts executable
# -------------------------------------------------------
echo "[6/6] Setting file permissions..."
chmod +x run_daily_briefing.sh
chmod +x setup.sh
chmod +x start_listener.sh 2>/dev/null || true
chmod +x stop_listener.sh 2>/dev/null || true
chmod +x setup_cron.sh 2>/dev/null || true
echo "  Done"
echo ""

# -------------------------------------------------------
# Summary
# -------------------------------------------------------
echo "============================================="
echo "  Setup Complete!"
echo "============================================="
echo ""
echo "Next steps:"
echo ""
echo "  1. Edit .mcp.json with your Slack tokens:"
echo "     - SLACK_XOXC_TOKEN (from browser cookies)"
echo "     - SLACK_XOXD_TOKEN (from browser localStorage)"
echo "     - SLACK_WORKSPACE_URL (your workspace URL)"
echo ""
echo "  2. Edit .env with your channel IDs:"
echo "     - BRIEFING_CHANNEL_ID (where briefings are posted)"
echo "     - MONITORED_CHANNELS (channels to collect from)"
echo "     How to get channel ID: right-click channel > View channel details > ID at bottom"
echo ""
echo "  3. Test the pipeline:"
echo "     source venv/bin/activate"
echo "     set -a; source .env; set +a"
echo "     python daily_briefing.py 24 briefing_test.txt false"
echo ""
echo "  4. Run full pipeline (collect + summarize + post):"
echo "     ./run_daily_briefing.sh"
echo ""
echo "  5. Start Q&A listener:"
echo "     ./start_listener.sh"
echo ""
echo "  6. Set up daily automation (optional):"
echo "     ./setup_cron.sh"
echo ""
