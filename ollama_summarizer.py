"""
Ollama LLM integration for briefing summarization and Q&A.

NEW FILE: Replaces the manual Claude Code summarization step with local Ollama.

All communication with the LLM happens via localhost. No data leaves the machine.

Safeguards implemented:
- S2: LLM answers grounded in provided context, instructed to cite sources
- S6: Endpoint validated as local-only before any call
- S8: Input sanitized for PII before sending to LLM
"""
import os
import sys
import logging

import ollama as ollama_client

from safeguards import sanitize_for_llm, validate_llm_endpoint

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# S6: Default to localhost. Can be overridden for OpenShift migration,
# but validate_llm_endpoint() will block non-local URLs.
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

# Model selection: llama3.1:8b for speed, mistral-small for quality
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")

# Summarization model can be different (larger) since it runs once daily
OLLAMA_SUMMARY_MODEL = os.environ.get("OLLAMA_SUMMARY_MODEL", OLLAMA_MODEL)


def check_ollama_available() -> bool:
    """Check if Ollama is running and the model is available.
    S6: Also validates the endpoint is local.
    """
    # S6: Validate endpoint before any communication
    if not validate_llm_endpoint(OLLAMA_BASE_URL):
        return False

    try:
        client = ollama_client.Client(host=OLLAMA_BASE_URL)
        models = client.list()
        available = [m.get("name", m.get("model", "")) for m in models.get("models", [])]
        logger.info(f"Ollama is running. Available models: {available}")

        if OLLAMA_MODEL not in available and not any(OLLAMA_MODEL in m for m in available):
            logger.warning(
                f"Model '{OLLAMA_MODEL}' not found. "
                f"Pull it with: ollama pull {OLLAMA_MODEL}"
            )
            return False
        return True
    except Exception as e:
        logger.error(f"Ollama not available at {OLLAMA_BASE_URL}: {e}")
        return False


# ---------------------------------------------------------------------------
# Summarization prompt
# ---------------------------------------------------------------------------

SUMMARIZE_SYSTEM_PROMPT = """You are an SRE daily briefing summarizer. Your job is to take collected
Slack messages from multiple channels and produce a clear, actionable daily briefing
formatted for Slack using mrkdwn syntax.

Rules:
- Be concise and factual. Do not invent information not present in the messages.
- ALWAYS extract ticket/issue IDs from messages. Look for these patterns:
  - OHSS-XXXXX (in URLs like redhat.atlassian.net/browse/OHSS-51750)
  - OCPBUGS-XXXXX
  - OSD-XXXXX
  - PagerDuty incident IDs (in URLs like pagerduty.com/incidents/Q2B1D0W6TLAWFG)
  - SREP-XXXXX, ARO-XXXXX, ITN-XXXXX
  If a ticket ID exists in the message, you MUST include it. Never write "TICKET-ID NOT FOUND".
  If genuinely no ticket exists, omit the ticket reference entirely.
- Categorize by severity using these exact emoji:
  :red_circle: = Critical (immediate action needed)
  :large_yellow_circle: = Warning (needs monitoring)
  :large_green_circle: = Info / Resolved (awareness only)
- Always mention which channel (#channel-name) each item came from.
- Do NOT include any email addresses, phone numbers, or personal contact information.
- If something is unclear from the messages, say so rather than guessing.
- Keep each bullet point to 1-2 lines max. Be specific about the actual error/symptom, not just "investigating".
- Preserve any ticket URLs from the original messages.
- Include cluster IDs and customer names when mentioned (e.g., "State Farm cluster", "Delta Airlines").

EXAMPLE of a good critical issue entry:
:red_circle: *etcd quota critical — DB at 7.3GB* — `OHSS-51804`
> ROSA Classic cluster `248ca8f0` has etcdDatabaseQuotaLowSpace alert. DB size 7.3GB, defrag failing with timeout. cc @Mitali. (#forum-rosa-support)

EXAMPLE of a bad entry (DO NOT do this):
:red_circle: *etcd issue* — `[TICKET-ID NOT FOUND]`
> SREs are investigating.

You MUST follow this EXACT output format:

:clipboard: *Daily Briefing* — [DATE RANGE]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

:mag: *Executive Summary*
• [Specific event — which #channel, what actually happened, customer if known]
• [Specific event — which #channel, actual error/symptom, current status]
• [Specific event — which #channel, what happened]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

:rotating_light: *Critical Issues*
:red_circle: *[Specific title with actual error]* — `TICKET-ID`
> [What happened. Cluster ID if available. Customer impact. Which #channel. What's been tried.]

_(If no critical issues: :large_green_circle: No critical issues in this period.)_

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

:warning: *Warnings*
:large_yellow_circle: *[Specific title]* — `TICKET-ID`
> [What's the concern. Which #channel. Current status.]

_(If no warnings: :large_green_circle: No warnings in this period.)_

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

:speech_balloon: *Channel Updates*

*#channel-name-1*
• [Specific update with details]
• [Specific update with details]

*#channel-name-2*
• [Specific update] or _No notable activity._

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

:bar_chart: *Statistics*
• Messages reviewed: *[N]*
• :red_circle: Critical: *[N]* | :large_yellow_circle: Warnings: *[N]* | :large_green_circle: Info: *[N]*"""


def _fix_slack_emoji(text: str) -> str:
    """Fix LLM emoji inconsistencies before posting to Slack.

    LLMs sometimes write (red_circle) or **text** instead of the
    correct Slack mrkdwn :red_circle: or *text*. This fixes those.
    """
    import re

    # Fix (emoji_name) -> :emoji_name:
    emoji_names = [
        "red_circle", "large_yellow_circle", "large_green_circle",
        "warning", "rotating_light", "clipboard", "mag",
        "speech_balloon", "bar_chart", "white_check_mark",
        "point_down", "file_folder", "thinking_face",
    ]
    for name in emoji_names:
        # (red_circle) -> :red_circle:
        text = text.replace(f"({name})", f":{name}:")
        # Also fix cases like (🔴) that some models produce
        # And fix doubled colons like ::red_circle::
        text = text.replace(f"::{name}::", f":{name}:")

    # Fix **bold** (markdown) -> *bold* (Slack mrkdwn)
    text = re.sub(r'\*\*(.+?)\*\*', r'*\1*', text)

    return text


def summarize_briefing(raw_messages: str, date_range: str) -> str:
    """Summarize collected Slack messages into a daily briefing.

    S2: LLM is instructed to only use information from the provided messages.
    S6: Endpoint validated before call.
    S8: Messages sanitized before sending to LLM.

    Args:
        raw_messages: The collected messages text (from briefing_*.txt)
        date_range: Human-readable date range string

    Returns:
        Formatted briefing summary string
    """
    # S6: Validate endpoint
    if not validate_llm_endpoint(OLLAMA_BASE_URL):
        return "ERROR: LLM endpoint validation failed. Cannot summarize."

    # S8: Sanitize PII before sending to LLM
    sanitized_messages = sanitize_for_llm(raw_messages)

    user_prompt = f"""Here are the collected Slack messages for the period {date_range}.
Please create a daily briefing summary following the format specified.

--- BEGIN MESSAGES ---
{sanitized_messages}
--- END MESSAGES ---"""

    logger.info(
        f"Sending {len(sanitized_messages)} chars to Ollama "
        f"(model: {OLLAMA_SUMMARY_MODEL}) for summarization"
    )

    try:
        client = ollama_client.Client(host=OLLAMA_BASE_URL)
        response = client.chat(
            model=OLLAMA_SUMMARY_MODEL,
            messages=[
                {"role": "system", "content": SUMMARIZE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            options={
                "temperature": 0.3,  # Low temperature for factual summarization
                "num_ctx": 16384,     # Context window for longer message sets
            },
        )

        summary = response["message"]["content"]
        # Fix LLM emoji inconsistencies — it sometimes writes (emoji) instead of :emoji:
        summary = _fix_slack_emoji(summary)
        logger.info(f"Summarization complete: {len(summary)} chars generated")
        return summary

    except Exception as e:
        logger.error(f"Ollama summarization failed: {e}")
        return f"ERROR: Summarization failed - {e}"


# ---------------------------------------------------------------------------
# Follow-up Q&A
# ---------------------------------------------------------------------------

QA_SYSTEM_PROMPT = """You are an SRE assistant that answers follow-up questions about a daily briefing.
Your answers are posted in Slack, so use Slack mrkdwn formatting.

Rules:
- ONLY use information from the provided context messages. Do not make up information.
- Always cite which channel (*#channel-name*) your answer is based on.
- If the answer is not in the provided context, say:
  ":thinking_face: I don't have enough information from the monitored channels to answer that. You may want to check the channel directly."
- Be concise and direct. Use bullet points for multiple items.
- Do NOT include any email addresses, phone numbers, or personal contact information.
- Format ticket/issue IDs in backticks like `OHSS-51750`.
- Use severity emoji where relevant:
  :red_circle: = Critical | :large_yellow_circle: = Warning | :large_green_circle: = Resolved/OK
- Bold key terms with *asterisks*.
- Use > block quotes for direct references from messages."""


def answer_followup(question: str, context_messages: str, channel_source: str) -> str:
    """Answer a follow-up question using context from Slack messages.

    S2: Answer grounded in context, LLM instructed to cite sources.
    S6: Endpoint validated before call.
    S8: Both question and context sanitized before sending to LLM.

    Args:
        question: The user's follow-up question
        context_messages: Retrieved Slack messages for context
        channel_source: Names of channels that were searched

    Returns:
        Answer string to post in Slack thread
    """
    # S6: Validate endpoint
    if not validate_llm_endpoint(OLLAMA_BASE_URL):
        return "I can't process your question right now (LLM endpoint validation failed)."

    # S8: Sanitize both question and context
    sanitized_question = sanitize_for_llm(question)
    sanitized_context = sanitize_for_llm(context_messages)

    user_prompt = f"""The user is asking about information from these Slack channels: {channel_source}

Context from collected messages:
--- BEGIN CONTEXT ---
{sanitized_context}
--- END CONTEXT ---

User's question: {sanitized_question}

Answer based ONLY on the context above. Cite which channel the information comes from."""

    logger.info(f"Q&A request: '{question[:80]}...' with {len(sanitized_context)} chars context")

    try:
        client = ollama_client.Client(host=OLLAMA_BASE_URL)
        response = client.chat(
            model=OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": QA_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            options={
                "temperature": 0.2,  # Very low temp for factual Q&A
                "num_ctx": 16384,
            },
        )

        answer = response["message"]["content"]
        answer = _fix_slack_emoji(answer)
        logger.info(f"Q&A answer generated: {len(answer)} chars")

        # S2: Append source attribution (channel_source may contain Slack hyperlinks)
        answer += f"\n\n━━━━━━━━━━━━━━━━━━━━\n:file_folder: _Sources: {channel_source}_"

        return answer

    except Exception as e:
        logger.error(f"Ollama Q&A failed: {e}")
        return (
            "Sorry, I couldn't generate an answer right now. "
            "Please make sure Ollama is running (`ollama serve`)."
        )


# ---------------------------------------------------------------------------
# CLI: standalone summarization (can be called from run_daily_briefing.sh)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) < 2:
        print("Usage: python ollama_summarizer.py <briefing_file> [output_file]")
        print("Example: python ollama_summarizer.py briefing_2026-03-17.txt")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    # Read input
    with open(input_file, "r") as f:
        raw = f.read()

    if not raw.strip():
        print("ERROR: Input file is empty")
        sys.exit(1)

    # Extract date range from filename or content
    import re
    date_match = re.search(r"(\d{4}-\d{2}-\d{2})", input_file)
    date_str = date_match.group(1) if date_match else "unknown"

    print(f"Summarizing {input_file} with Ollama ({OLLAMA_SUMMARY_MODEL})...")

    summary = summarize_briefing(raw, date_str)

    if summary.startswith("ERROR"):
        print(summary)
        sys.exit(1)

    # Output
    if output_file:
        with open(output_file, "w") as f:
            f.write(summary)
        print(f"Summary saved to {output_file}")
    else:
        # Default output file
        default_output = input_file.replace("briefing_", "briefing_summary_")
        with open(default_output, "w") as f:
            f.write(summary)
        print(f"Summary saved to {default_output}")

    print("\n" + "=" * 60)
    print(summary)
    print("=" * 60)
