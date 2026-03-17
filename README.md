# Slack Daily Briefing Agent

An agentic daily briefing system that monitors Slack channels, generates AI-powered summaries using a **local LLM**, and answers follow-up questions — all without sending any data to external AI services.

Fork of [sodoityu/mcp-slack-briefing](https://github.com/sodoityu/mcp-slack-briefing), transformed into a fully automated, privacy-safe agentic system.

## What it does

1. **Collects** messages from your Slack channels via MCP (Model Context Protocol)
2. **Filters** for important messages (incidents, tickets, keywords, emojis)
3. **Summarizes** using a local Ollama LLM — no data leaves your machine
4. **Posts** the briefing to a Slack channel (header + threaded summary)
5. **Answers follow-up questions** in the briefing thread using the local LLM

## Quick Start

### Prerequisites

Choose your platform:

**macOS (Apple Silicon M1/M2/M3, 16GB RAM)**
```bash
brew install python podman ollama
```

**Linux (Fedora / RHEL)**
```bash
sudo dnf install python3 python3-pip podman
curl -fsSL https://ollama.com/install.sh | sh
```

### 1. Clone and setup

```bash
git clone https://github.com/archith-kadannapalli/mcp-slack-briefing.git
cd mcp-slack-briefing
chmod +x setup.sh && ./setup.sh
```

The setup script auto-detects your platform (macOS or Linux) and:
- Creates a Python virtual environment
- Installs Python dependencies
- Pulls the `llama3.1:8b` AI model (~4.7GB, one-time)
- Sets up Podman (initializes VM on macOS, native on Linux)
- Pulls the Slack MCP container
- Creates `.env` and `.mcp.json` config templates

### 2. Get your Slack tokens

Open **Slack in your browser** (not the desktop app), then open DevTools (F12):

| Token | Where to find it |
|-------|-----------------|
| `xoxc-*` | Network tab > click any channel > find request to `api.slack.com` > look for `token` in request body |
| `xoxd-*` | Application tab > Cookies > cookie named `d` |

### 3. Configure

**Edit `.mcp.json`** — add your Slack tokens:
```json
{
  "mcpServers": {
    "slack": {
      "env": {
        "SLACK_XOXC_TOKEN": "xoxc-YOUR-ACTUAL-TOKEN",
        "SLACK_XOXD_TOKEN": "xoxd-YOUR-ACTUAL-TOKEN",
        "SLACK_WORKSPACE_URL": "https://your-workspace.slack.com"
      }
    }
  }
}
```

**Edit `.env`** — add your channel IDs:
```bash
# Right-click channel in Slack > "View channel details" > ID at bottom
BRIEFING_CHANNEL_ID=C04XXXXXXXX
MONITORED_CHANNELS='[{"id":"C04XXXXXXXX","name":"your-channel"},{"id":"C01XXXXXXXX","name":"another-channel"}]'
```

### 4. Start Podman (platform-specific)

**macOS:**
```bash
podman machine init    # first time only
podman machine start
```

**Linux (Fedora/RHEL):**
```bash
# Podman runs natively, no setup needed
# Verify with:
podman info
```

### 5. Start Ollama

**macOS:**
```bash
ollama serve &
ollama pull llama3.1:8b    # first time only
```

**Linux:**
```bash
sudo systemctl start ollama
sudo systemctl enable ollama    # auto-start on boot
ollama pull llama3.1:8b         # first time only
```

### 6. Test

```bash
source venv/bin/activate
set -a; source .env; set +a

# Test collection (fetches messages from your channels)
python daily_briefing.py 24 briefing_test.txt false

# Test full pipeline (collect + summarize + post to Slack)
./run_daily_briefing.sh
```

### 7. Start Q&A listener

After a briefing is posted, start the listener to answer follow-up questions:

```bash
./start_listener.sh          # foreground (Ctrl+C to stop)
./start_listener.sh --bg     # background (logs to logs/qa_listener.log)
./stop_listener.sh           # stop background listener
```

Reply in the briefing thread in Slack with any question — answered within 10 seconds.

### 8. Automate (optional)

```bash
./setup_cron.sh
```

This sets up:
- A **cron job** to run the daily briefing at your chosen time
- A persistent service for the Q&A listener:
  - **macOS:** launchd (auto-starts on login)
  - **Linux:** systemd user service (auto-starts on boot, survives logout)

## Architecture

```
Cron (daily)                    Your Machine
     |                    (everything runs locally)
     v
daily_briefing.py -----> Slack MCP (Podman) -----> Slack API
     |                                              |
     v                                              v
briefing_YYYY-MM-DD.txt              Monitored Channels
     |
     v
ollama_summarizer.py --> Ollama (localhost:11434)
     |
     v
briefing_summary_YYYY-MM-DD.txt
     |
     v
post_summary_to_slack.py ---------> Slack Channel
     |                               |
     v                               v
qa_listener.py (polls every 10s)   User replies in thread
     |                               |
     v                               v
Ollama (generates answer) -------> Reply posted in thread
```

## Privacy and Security

No Slack data ever leaves your machine. All AI processing happens locally via Ollama.

| Safeguard | What it does |
|-----------|-------------|
| S1 - Channel allowlist | Only monitors channels you explicitly list in `.env` |
| S2 - Context scoping | Q&A answers only reference the current briefing, not all of Slack |
| S3/S4 - Access control | Channel search restricted to the allowlist |
| S5 - Thread-only replies | Bot never posts top-level messages, only in-thread |
| S6 - Local LLM only | Endpoint validated as localhost — external URLs blocked |
| S7 - No hardcoded tokens | All credentials in `.env` / `.mcp.json`, both gitignored |
| S8 - PII sanitization | Emails, phone numbers, IPs stripped before LLM sees them |

## File Structure

```
mcp-slack-briefing/
├── setup.sh                  # One-time setup (run first)
├── run_daily_briefing.sh     # Full pipeline: collect + summarize + post
├── start_listener.sh         # Start Q&A listener
├── stop_listener.sh          # Stop Q&A listener
├── setup_cron.sh             # Set up daily cron + persistent service
├── daily_briefing.py         # Message collection from Slack via MCP
├── ollama_summarizer.py      # Local Ollama summarization + Q&A
├── post_summary_to_slack.py  # Post briefing to Slack channel
├── qa_listener.py            # Poll briefing thread, answer questions
├── safeguards.py             # Security checks (S1-S8)
├── .env.example              # Environment config template
├── .mcp.json.example         # MCP/Slack config template
├── requirements.txt          # Python dependencies
├── CLAUDE.md                 # AI assistant instructions
├── AGENTIC_DESIGN.md         # Architecture and design document
└── README.md                 # This file
```

## Platform Differences

| Feature | macOS | Linux (Fedora/RHEL) |
|---------|-------|---------------------|
| Python install | `brew install python` | `sudo dnf install python3 python3-pip` |
| Podman install | `brew install podman` | `sudo dnf install podman` (often pre-installed) |
| Podman startup | `podman machine init && podman machine start` | Not needed (runs natively) |
| Ollama install | `brew install ollama` | `curl -fsSL https://ollama.com/install.sh \| sh` |
| Ollama startup | `ollama serve &` | `sudo systemctl start ollama` |
| Q&A service | launchd (auto-start on login) | systemd user service (survives logout) |
| Container arch | May show `linux/amd64` warning on ARM | Native architecture match |

## Upgrading to OpenShift

When ready to move from local Ollama to a shared OpenShift deployment:

1. Deploy Ollama/vLLM/RHOAI on your cluster
2. Update two env vars in `.env`:
   ```bash
   OLLAMA_BASE_URL=https://llm.apps.your-cluster.internal
   OLLAMA_MODEL=your-deployed-model
   ```
3. Update `ALLOWED_LLM_HOSTS` in `safeguards.py` to include your cluster hostname
4. Everything else stays the same

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `externally-managed-environment` error | Use the venv: `source venv/bin/activate` |
| `json.decoder.JSONDecodeError` on `.env` | Wrap `MONITORED_CHANNELS` value in single quotes |
| `json.decoder.JSONDecodeError` on `.mcp.json` | Check for double-double quotes around tokens |
| `pydantic ValidationError` in output | Harmless warning from MCP server — pipeline continues |
| `Ollama not available` | macOS: `ollama serve &` / Linux: `sudo systemctl start ollama` |
| `Podman machine not running` (macOS) | `podman machine start` |
| `No briefing thread found` | Run `./run_daily_briefing.sh` first, then start listener |
| Q&A not detecting replies | Reply **in the briefing thread**, not as a new channel message |
| `Poetry could not find pyproject.toml` | Use venv, not poetry: `source venv/bin/activate` |
| Linux: `permission denied` on scripts | `chmod +x *.sh` |
| Linux: Ollama won't start | `sudo systemctl enable --now ollama` |

## License

MIT License — based on [sodoityu/mcp-slack-briefing](https://github.com/sodoityu/mcp-slack-briefing)
