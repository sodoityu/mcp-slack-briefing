# Slack Daily Briefing Agent

An agentic daily briefing system that monitors Slack channels, generates AI-powered summaries using a **local LLM**, and answers follow-up questions — all without sending any data to external AI services.

Fork of [sodoityu/mcp-slack-briefing](https://github.com/sodoityu/mcp-slack-briefing), transformed into a fully automated, privacy-safe agentic system.

## What it does

1. **Collects** messages from your Slack channels via MCP (Model Context Protocol)
2. **Filters** for important messages (incidents, tickets, keywords, emojis)
3. **Summarizes** using a local Ollama LLM — no data leaves your machine
4. **Posts** the briefing to a Slack channel (header + threaded summary)
5. **Answers follow-up questions** in the briefing thread using the local LLM

## Quick Start (one command)

```bash
git clone https://github.com/archith-kadannapalli/mcp-slack-briefing.git
cd mcp-slack-briefing
chmod +x install.sh && ./install.sh
```

That's it. The installer handles everything:

1. Installs dependencies (Python, Podman, Ollama) based on your platform
2. Sets up Python venv and packages
3. Starts Podman and pulls the Slack MCP container
4. Starts Ollama and pulls the AI model
5. **Prompts you for all config** (Slack tokens, channel IDs) — no file editing
6. **Runs your first briefing immediately** and posts it to Slack
7. Sets up a daily cron job (you pick the hour)
8. Starts the Q&A listener in the background
9. Installs auto-start service (launchd on macOS, systemd on Linux)

### What you need before running

Before you run `install.sh`, have these ready:

1. **Slack tokens** — open Slack in your **browser** (not desktop app), open DevTools (F12):
   - `xoxc-*` token: Network tab > click any channel > find request to `api.slack.com` > `token` in request body
   - `xoxd-*` token: Application tab > Cookies > cookie named `d`

2. **Channel IDs** — right-click a channel in Slack > "View channel details" > ID at bottom
   - The channel where briefings should be posted
   - The channels to monitor for messages

### After install

Go to Slack, find the briefing post, reply in the thread with a question — answered within 10 seconds.

### Manual commands (if needed)

```bash
./run_daily_briefing.sh          # run briefing manually
./start_listener.sh              # restart Q&A listener
./stop_listener.sh               # stop Q&A listener
tail -f logs/qa_listener.log     # Q&A listener logs
tail -f logs/daily_briefing.log  # daily briefing logs
```

### Advanced setup (separate steps)

If you prefer to run setup steps individually instead of the all-in-one installer:

```bash
./setup.sh          # install deps + create config templates
# edit .mcp.json and .env manually
./run_daily_briefing.sh    # run pipeline
./start_listener.sh        # start Q&A
./setup_cron.sh            # set up automation
```

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
