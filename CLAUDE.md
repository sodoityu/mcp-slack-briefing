# CLAUDE.md - Project Instructions for Claude Code

## Project: MCP Slack Briefing Agent (Agentic AI Fork)

### What this project is
A fork of `sodoityu/mcp-slack-briefing` extended with:
1. **Agentic AI implementation** - Fully automated summarization using local Ollama LLM
2. **Local AI for privacy** - No Slack data leaves the user's machine via external AI APIs
3. **MCP-only Q&A** - Users ask follow-up questions in Slack threads, answered via MCP + Ollama

### Architecture: Pure MCP (no Slack Bot)
- No Slack App, no bot tokens, no OAuth needed
- Uses the SAME xoxc/xoxd session tokens and MCP Slack server as the original project
- Q&A works by POLLING the briefing thread every 10s via MCP
- All Slack reads and writes go through the existing Podman MCP container

### Core Principles

#### BUILD ON TOP OF EXISTING CODE
- Do NOT rewrite from scratch. Modify existing files where possible.
- Comment clearly what was changed and why (use `# CHANGED:` or `# ADDED:` prefixes).
- Keep original logic intact unless it conflicts with the new architecture.

#### SAFEGUARD TABLE (MUST be applied in every code change)

| ID | Concern | Safeguard | How to implement |
|----|---------|-----------|------------------|
| S1 | Script can read any channel | Restrict to monitored channels only | Check channel ID against allowlist before searching |
| S2 | LLM might hallucinate | Ground answers in BRIEFING CONTEXT ONLY, cite sources | Pass briefing file as primary context, instruct LLM to only use provided info |
| S3 | Cross-channel access | Only search allowed channels | Channel allowlist enforced in safeguards.py |
| S4 | LLM output leaks data cross-channel | Only search channels in allowlist | Filter search scope to ALLOWED_CHANNELS only |
| S5 | Answers get posted publicly | All replies in-thread only, never top-level | Enforce thread_ts on every post_message call |
| S6 | No Slack data to external AI APIs | All LLM calls go to localhost Ollama only | validate_llm_endpoint() blocks non-local URLs |
| S7 | Sensitive tokens in code | Never hardcode tokens, use env vars or .mcp.json | Load from environment, .gitignore sensitive files |
| S8 | Raw messages contain PII | Sanitize before LLM processing | Strip emails, phone numbers, IPs before sending to LLM |

#### CRITICAL: Q&A CONTEXT SCOPING
When a user asks a follow-up (e.g., "did sev1 get resolved?"), the answer MUST come from:
1. PRIMARY: The briefing file for that day (briefing_summary_*.txt or briefing_*.txt)
2. SECONDARY (only if more detail needed): Messages from ALLOWED channels only
NEVER search all of Slack. NEVER answer about sev1s not in the briefing.

#### AFTER EVERY PROMPT COMPLETION
Report which safeguards (S1-S8) were implemented in that change.

### Tech Stack
- Python 3.12+
- Ollama (local LLM - llama3.1:8b or mistral-small)
- MCP SDK (reuse existing Slack MCP server — NO Slack Bot/Bolt)
- Podman (containerized Slack MCP server)

### File Structure
- `daily_briefing.py` - Original collection script (MODIFIED: adds Ollama summarization)
- `post_summary_to_slack.py` - Original posting script (unchanged)
- `qa_listener.py` - NEW: Polls briefing thread for questions, answers via MCP + Ollama
- `ollama_summarizer.py` - NEW: Ollama integration layer
- `safeguards.py` - NEW: PII sanitization and access control utilities
- `run_daily_briefing.sh` - Original automation script (MODIFIED: triggers new pipeline)
- `.env.example` - NEW: Environment variable template
- `AGENTIC_DESIGN.md` - NEW: Documentation explaining the agentic transformation

### Model Configuration
- Default model: `llama3.1:8b` (fast, fits 16GB Mac)
- Summarization model: configurable via OLLAMA_SUMMARY_MODEL env var
- Ollama endpoint: `http://localhost:11434` (NEVER change to external URL - S6)

### Migration Path
When moving to OpenShift:
- Change `OLLAMA_BASE_URL` from `localhost:11434` to OpenShift route
- Change `OLLAMA_MODEL` to whatever is deployed
- Everything else stays the same
