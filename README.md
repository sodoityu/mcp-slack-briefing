# MCP Slack Daily Briefing System

An intelligent daily briefing system that automatically monitors multiple Slack channels, extracts critical messages, and generates AI-powered summaries for SRE teams.

## 🌟 Overview

This system uses the **Model Context Protocol (MCP)** to connect Claude AI with Slack, enabling automated collection and AI-powered summarization of important messages from multiple channels.

### Key Features

- ✅ **MCP-based Architecture**: Uses standardized MCP protocol for AI-to-Slack communication
- ✅ **Multi-Channel Monitoring**: Aggregates messages from multiple Slack channels
- ✅ **Intelligent Filtering**: Automatically detects important messages using patterns and keywords
- ✅ **AI-Powered Summarization**: Claude generates structured daily briefings
- ✅ **Automated Scheduling**: Runs daily via systemd timers (or cron)
- ✅ **Containerized Slack Server**: Uses Podman for secure, isolated execution
- ✅ **Threaded Slack Posts**: Clean channel organization with header + threaded detail

## 📚 Documentation

- **[SLACK_BRIEFING_SHOWCASE.md](SLACK_BRIEFING_SHOWCASE.md)** - Complete technical showcase and architecture
- **[SLACK_BRIEFING_SOURCE_CODE.md](SLACK_BRIEFING_SOURCE_CODE.md)** - Full source code documentation (51KB+)
- **[podmanlearn.md](podmanlearn.md)** - Podman container workflow explanation
- **[cronlearn.md](cronlearn.md)** - Systemd timers vs cron comparison

## 🚀 Quick Start

### Prerequisites

- **Python 3.12+** with Poetry
- **Podman** (container runtime)
- **Slack workspace** with appropriate permissions
- **Anthropic Claude API access** (via Claude Code)

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/sodoityu/mcp-slack-briefing.git
   cd mcp-slack-briefing
   ```

2. **Install Python dependencies**
   ```bash
   poetry install
   # or
   pip install mcp anthropic requests python-dotenv
   ```

3. **Pull the Slack MCP container**
   ```bash
   podman pull quay.io/redhat-ai-tools/slack-mcp:latest
   ```

4. **Configure Slack credentials**
   - Copy `.mcp.json.example` to `.mcp.json`
   - Add your Slack session tokens (xoxc/xoxd)
   - Update channel IDs in `daily_briefing.py`

5. **Set up automation** (optional)
   ```bash
   # Copy systemd timer files (see cronlearn.md for details)
   cp systemd/* ~/.config/systemd/user/
   systemctl --user enable --now daily-briefing.timer
   ```

## 📖 Usage

### Manual Collection

```bash
# Collect messages from the last 24 hours
poetry run python daily_briefing.py

# Custom time range (48 hours)
poetry run python daily_briefing.py 48 briefing_custom.txt
```

### Generate Summary with Claude

1. Run the collection script (or wait for automated run)
2. Open Claude Code
3. Say: "Create today's daily briefing"
4. Review the AI-generated summary
5. Approve posting to your target Slack channel

### Post to Slack

```bash
# Post summary to Slack
poetry run python post_summary_to_slack.py briefing_summary.txt 2026-03-16 2026-03-17 C04F0GWTD9B
```

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  Daily Briefing System                  │
└─────────────────────────────────────────────────────────┘

Systemd Timer/Cron
       │
       ▼
run_daily_briefing.sh
       │
       ▼
daily_briefing.py ──► Slack MCP Server (Podman)
       │                      │
       │                      ▼
       │               Slack API (4 channels)
       ▼
  briefing_YYYY-MM-DD.txt
       │
       ▼
  Claude Code (Manual Review)
       │
       ▼
  Claude API (Summarization)
       │
       ▼
post_summary_to_slack.py ──► Slack Channel
       │
       ▼
  📋 Daily Briefing Posted
```

## 🛠️ Technology Stack

- **MCP Protocol**: Standardized AI-to-service communication
- **Python 3.12**: Core scripting language
- **Poetry**: Dependency management
- **Podman**: Containerized Slack MCP server
- **Anthropic Claude**: AI-powered summarization
- **Systemd Timers**: Modern scheduling (alternative: cron)
- **Bash**: Automation scripts

## 📂 File Structure

```
mcp-slack-briefing/
├── README.md                          # This file
├── SLACK_BRIEFING_SHOWCASE.md         # Technical showcase
├── SLACK_BRIEFING_SOURCE_CODE.md      # Complete source code docs
├── podmanlearn.md                     # Podman workflow guide
├── cronlearn.md                       # Systemd timers guide
├── .mcp.json.example                  # MCP configuration template
├── daily_briefing.py                  # Main collection script
├── post_summary_to_slack.py           # Slack posting script
└── run_daily_briefing.sh              # Automation wrapper
```

## ⚙️ Configuration

### Channel Configuration

Edit `daily_briefing.py` to customize monitored channels:

```python
channels = [
    {"id": "CXXXXXXXXXX", "name": "your-channel-1"},
    {"id": "CYYYYYYYYYY", "name": "your-channel-2"},
    # Add more channels...
]
```

### Filtering Patterns

Customize the `filter_important_messages()` function:

```python
ticket_patterns = [
    r'TICKET-\d+',      # Add your ticket patterns
    r'PR #\d+',         # Pull requests
]

important_keywords = [
    'urgent', 'critical', 'incident',  # Add keywords
]

important_emojis = ['🔥', '⚠️', '🚨']  # Add emojis
```

### Scheduling

**Systemd Timer** (recommended):
```bash
# Edit timer schedule
systemctl --user edit --full daily-briefing.timer

# Change this line:
OnCalendar=*-*-* 09:00:00  # Daily at 9:00 AM
```

**Cron** (alternative):
```cron
# Add to crontab
0 9 * * * /path/to/run_daily_briefing.sh >> /path/to/logs/daily_briefing.log 2>&1
```

## 🔒 Security Notes

- **Never commit `.mcp.json`** with real tokens (use `.mcp.json.example` as template)
- Store tokens in environment variables or secure vault
- Use `.gitignore` to exclude sensitive files
- Rotate Slack tokens periodically
- Review and sanitize messages before posting to public channels

## 📊 Example Output

```
📋 Daily Briefing — 2026-03-16 to 2026-03-17

:small_orange_diamond: Executive Summary
System health stable with 3 critical incidents resolved. One ongoing upgrade
issue requires monitoring. ARO HCP experiencing intermittent DNS delays.

:small_orange_diamond: :fire: Hot Threads
🔴 ITN-2026-xxxx: Customer cluster stuck in upgrading state (OHSS-xxxx)
   Status: Engineering investigating CVO logs, RCA in progress

:small_orange_diamond: 🔵 ROSA Support
- 12 new support cases opened (8 upgrades, 3 networking, 1 authentication)
- Case escalation: SREP-xxxx (P1 cluster unavailable)

📊 Statistics: 47 messages | 3 Critical | 8 Warnings
```

## 🤝 Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Test thoroughly
4. Submit a pull request

## 📝 License

MIT License - feel free to use and modify for your own teams!

## 🙏 Acknowledgments

- **Red Hat AI Tools** - For the Slack MCP server container
- **Anthropic** - For Claude AI and MCP protocol
- **Podman Project** - For secure container runtime

## 📧 Contact

For questions or feedback, please open an issue on GitHub.

---

**Built with ❤️ for SRE teams managing ROSA/ARO/HCP platforms**
