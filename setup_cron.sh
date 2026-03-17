#!/bin/bash
#
# setup_cron.sh - Set up daily automation
#
# macOS: cron + launchd service for Q&A listener
# Linux: cron + systemd user service for Q&A listener
#

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OS="$(uname)"

echo "============================================="
echo "  Daily Automation Setup"
echo "============================================="
echo ""

# -------------------------------------------------------
# Step 1: Cron job for daily briefing (both platforms)
# -------------------------------------------------------
echo "Setting up daily briefing cron job..."
echo ""

if crontab -l 2>/dev/null | grep -q "run_daily_briefing.sh"; then
    echo "  Cron job already exists:"
    crontab -l | grep "run_daily_briefing"
    echo ""
    read -p "  Replace it? (y/n): " replace
    if [ "$replace" != "y" ]; then
        echo "  Skipped"
        echo ""
    else
        crontab -l 2>/dev/null | grep -v "run_daily_briefing.sh" | crontab -
    fi
fi

if ! crontab -l 2>/dev/null | grep -q "run_daily_briefing.sh"; then
    read -p "  What hour should the briefing run? (0-23, default 9): " HOUR
    HOUR=${HOUR:-9}

    (crontab -l 2>/dev/null; echo "0 $HOUR * * * cd $SCRIPT_DIR && ./run_daily_briefing.sh >> logs/daily_briefing.log 2>&1") | crontab -

    echo "  Cron job added: runs daily at ${HOUR}:00"
    echo "  Logs: $SCRIPT_DIR/logs/daily_briefing.log"
fi

echo ""

# -------------------------------------------------------
# Step 2: Q&A listener as a persistent service
# -------------------------------------------------------

if [ "$OS" = "Darwin" ]; then
    # ---- macOS: launchd ----
    echo "Setting up Q&A listener as macOS launchd service..."
    echo ""

    PLIST_NAME="com.slack-briefing.qa-listener"
    PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"

    if [ -f "$PLIST_PATH" ]; then
        echo "  Launchd service already exists"
        read -p "  Replace it? (y/n): " replace_svc
        if [ "$replace_svc" = "y" ]; then
            launchctl unload "$PLIST_PATH" 2>/dev/null
            rm "$PLIST_PATH"
        else
            echo "  Skipped"
            echo ""
            exit 0
        fi
    fi

    read -p "  Install Q&A listener as auto-start service? (y/n): " install_service
    if [ "$install_service" = "y" ]; then
        mkdir -p "$HOME/Library/LaunchAgents"
        mkdir -p "$SCRIPT_DIR/logs"

        cat > "$PLIST_PATH" << PLIST_EOF
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
PLIST_EOF

        launchctl load "$PLIST_PATH"
        echo "  Service installed and started"
        echo ""
        echo "  Manage with:"
        echo "    launchctl stop $PLIST_NAME    # stop"
        echo "    launchctl start $PLIST_NAME   # start"
        echo "    launchctl unload $PLIST_PATH  # remove"
        echo "    tail -f logs/qa_listener.log  # logs"
    else
        echo "  Skipped. Run manually with: ./start_listener.sh --bg"
    fi

else
    # ---- Linux: systemd user service ----
    echo "Setting up Q&A listener as systemd user service..."
    echo ""

    SERVICE_NAME="slack-briefing-qa"
    SERVICE_DIR="$HOME/.config/systemd/user"
    SERVICE_PATH="$SERVICE_DIR/${SERVICE_NAME}.service"

    if [ -f "$SERVICE_PATH" ]; then
        echo "  Systemd service already exists"
        read -p "  Replace it? (y/n): " replace_svc
        if [ "$replace_svc" = "y" ]; then
            systemctl --user stop "$SERVICE_NAME" 2>/dev/null
            systemctl --user disable "$SERVICE_NAME" 2>/dev/null
            rm "$SERVICE_PATH"
        else
            echo "  Skipped"
            echo ""
            exit 0
        fi
    fi

    read -p "  Install Q&A listener as auto-start service? (y/n): " install_service
    if [ "$install_service" = "y" ]; then
        mkdir -p "$SERVICE_DIR"
        mkdir -p "$SCRIPT_DIR/logs"

        cat > "$SERVICE_PATH" << SERVICE_EOF
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
SERVICE_EOF

        # Enable lingering so user services run without login
        loginctl enable-linger "$USER" 2>/dev/null || true

        systemctl --user daemon-reload
        systemctl --user enable "$SERVICE_NAME"
        systemctl --user start "$SERVICE_NAME"

        echo "  Service installed and started"
        echo ""
        echo "  Manage with:"
        echo "    systemctl --user stop $SERVICE_NAME      # stop"
        echo "    systemctl --user start $SERVICE_NAME     # start"
        echo "    systemctl --user restart $SERVICE_NAME   # restart"
        echo "    systemctl --user status $SERVICE_NAME    # status"
        echo "    journalctl --user -u $SERVICE_NAME -f    # logs"
        echo "    tail -f logs/qa_listener.log             # logs (file)"
    else
        echo "  Skipped. Run manually with: ./start_listener.sh --bg"
    fi
fi

echo ""
echo "============================================="
echo "  Automation Setup Complete!"
echo "============================================="
echo ""
echo "  Daily briefing: cron runs at ${HOUR:-9}:00"
echo "  Q&A listener: $(systemctl --user is-active $SERVICE_NAME 2>/dev/null || launchctl list $PLIST_NAME 2>/dev/null && echo 'running as service' || echo 'run manually with ./start_listener.sh')"
echo ""
