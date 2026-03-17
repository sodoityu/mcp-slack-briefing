# Agentic AI Transformation - Design Document

## Why This Fork Exists

This is a modified version of [sodoityu/mcp-slack-briefing](https://github.com/sodoityu/mcp-slack-briefing) with three goals:

### 1. Agentic AI Implementation

The original system required a **manual human step**: after collecting Slack messages, a user
had to open Claude Code, paste the messages, ask for a summary, review it, and then post it.

This fork **removes the manual step entirely**. The system now:
- Collects messages automatically (same as before)
- Summarizes them using a **local LLM** via Ollama (new)
- Posts the briefing to Slack via **MCP** (same mechanism, now automated)
- Accepts **follow-up questions** in Slack threads and answers them using Ollama + MCP (new)

### 2. Local AI for Data Privacy

The original workflow sent all collected Slack messages to **Anthropic's cloud API** via Claude Code.
This means internal messages -- including incident details, customer names, ticket IDs, escalation
discussions, and engineering notes -- all left the organization's network.

This fork uses **Ollama running locally** on the user's machine. No Slack data is sent to any
external AI service. The LLM runs at `localhost:11434` and all inference happens on-device.

For production deployment, the Ollama instance can be moved to an **OpenShift cluster** within
the organization's network, maintaining the same privacy guarantee at scale.

### 3. Safeguard Implementation

Since we're giving an automated system access to Slack channels, we implement strict safeguards:

| ID | Concern | Safeguard |
|----|---------|-----------|
| S1 | Script can read any channel | Channel allowlist -- only pre-approved channels are searched |
| S2 | LLM hallucination | Answers grounded in briefing context only, with source citations |
| S3 | Cross-channel access | Only allowed channels searched, no cross-channel data leakage |
| S4 | Data leakage across channels | Search scope restricted to ALLOWED_CHANNELS dict |
| S5 | Public posting of answers | All replies in-thread only, never top-level messages |
| S6 | Data exfiltration via external AI | LLM endpoint validated as localhost, non-local URLs blocked |
| S7 | Token exposure | All credentials in env vars / .mcp.json, never in code |
| S8 | PII in LLM input | Emails, phone numbers, IPs sanitized before LLM processing |

## Architecture (Pure MCP -- No Slack Bot)

This system uses NO Slack App, NO bot tokens, NO OAuth. It reuses the exact same
MCP Slack server (Podman container) and session tokens (xoxc/xoxd) from the original project.

```
                    Your Machine (everything runs here)
+-----------------------------------------------------------------------+
|                                                                         |
|  launchd/cron (9 AM daily)                                             |
|       |                                                                 |
|       v                                                                 |
|  daily_briefing.py -------> Slack MCP Server (Podman) -----> Slack API |
|       |                     [get_channel_history]                       |
|       v                                                                 |
|  briefing_YYYY-MM-DD.txt   (raw collected messages)                    |
|       |                                                                 |
|       v                                                                 |
|  ollama_summarizer.py ----> Ollama (localhost:11434)                   |
|       |                     [S6: local only] [S8: PII stripped]         |
|       v                                                                 |
|  briefing_summary_YYYY-MM-DD.txt  (AI summary)                        |
|       |                                                                 |
|       v                                                                 |
|  post_summary_to_slack.py -> Slack MCP Server -> Slack channel         |
|       |                      [post_message]    [S5: header + thread]    |
|       v                                                                 |
|  qa_listener.py  (runs in background, polls every 10s)                 |
|       |                                                                 |
|       +---> MCP: poll briefing thread for new replies                  |
|       |                                                                 |
|       +---> New question found?                                        |
|       |       |                                                         |
|       |       v                                                         |
|       |     Load briefing file as PRIMARY context (S2)                 |
|       |       |                                                         |
|       |       v                                                         |
|       |     Need more detail? Search ALLOWED channels via MCP (S1,S4)  |
|       |       |                                                         |
|       |       v                                                         |
|       |     safeguards.py: sanitize PII (S8)                           |
|       |       |                                                         |
|       |       v                                                         |
|       |     Ollama: generate answer (S6: localhost only)                |
|       |       |                                                         |
|       |       v                                                         |
|       +---> MCP: post answer in thread (S5: never top-level)           |
|                                                                         |
+-----------------------------------------------------------------------+
```

## Q&A Context Scoping (Critical Design Decision)

When a user asks a follow-up question like "did sev1 get resolved?":

1. The system answers based on the **briefing file for that day** -- not all of Slack
2. If the briefing mentions 2 sev1 incidents, the answer covers those 2 -- not the 100 other sev1s across Slack history
3. If more detail is needed, it searches **only the allowed channels** (S1 allowlist)
4. It **never** searches channels outside the allowlist, regardless of what the user asks

This is enforced at multiple levels:
- `load_briefing_context()` reads only today's/yesterday's briefing file
- `search_allowed_channels_for_context()` checks `is_channel_allowed()` for every channel
- The LLM system prompt explicitly says "answer based ONLY on the context provided"

## Setup

### Prerequisites
- macOS with Apple Silicon (M1/M2/M3)
- Ollama installed (`brew install ollama`)
- Podman installed (`brew install podman`)
- Python 3.12+ with pip/poetry
- Slack session tokens (xoxc/xoxd) -- same as original project

### Quick Start

1. Install Ollama and pull the model:
   ```bash
   brew install ollama
   ollama pull llama3.1:8b
   ```

2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Configure:
   - Copy `.mcp.json.example` to `.mcp.json` and fill in Slack session tokens
   - Copy `.env.example` to `.env` and fill in channel IDs

4. Run the daily pipeline (or wait for cron):
   ```bash
   ./run_daily_briefing.sh
   ```

5. Start the Q&A listener:
   ```bash
   python qa_listener.py
   ```

6. Set up daily automation:
   ```bash
   crontab -e
   # Add: 0 9 * * * cd /path/to/project && ./run_daily_briefing.sh
   ```

## Migration to OpenShift

When ready to move from local Ollama to OpenShift:

1. Deploy Ollama/vLLM/RHOAI on OpenShift
2. Change two environment variables:
   ```bash
   OLLAMA_BASE_URL=https://llm.apps.your-cluster.internal
   OLLAMA_MODEL=your-deployed-model
   ```
3. Update `safeguards.py` ALLOWED_LLM_HOSTS to include the OpenShift hostname
4. Everything else stays the same -- the code uses these env vars everywhere
