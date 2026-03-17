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
Slack messages from multiple channels and produce a clear, actionable daily briefing.

Rules:
- Be concise and factual. Do not invent information not present in the messages.
- Structure the output with clear sections.
- Highlight critical incidents and blockers prominently.
- Include ticket/issue IDs when referenced in messages.
- Categorize by severity: Critical (immediate action), Warning (monitor), Info (awareness).
- Do NOT include any email addresses, phone numbers, or personal contact information.
- If something is unclear from the messages, say so rather than guessing.

Output format:
---
Daily Briefing -- [DATE RANGE]

EXECUTIVE SUMMARY
[2-3 sentence overview of the day's key events]

CRITICAL ISSUES (if any)
- [Issue]: [Status] [Ticket ID if available]

WARNINGS (if any)
- [Issue]: [Status]

CHANNEL UPDATES
[Channel Name]:
- [Key point 1]
- [Key point 2]

STATISTICS
- Total messages reviewed: [N]
- Critical: [N] | Warnings: [N] | Info: [N]
---"""


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
                "num_ctx": 8192,     # Context window for longer message sets
            },
        )

        summary = response["message"]["content"]
        logger.info(f"Summarization complete: {len(summary)} chars generated")
        return summary

    except Exception as e:
        logger.error(f"Ollama summarization failed: {e}")
        return f"ERROR: Summarization failed - {e}"


# ---------------------------------------------------------------------------
# Follow-up Q&A
# ---------------------------------------------------------------------------

QA_SYSTEM_PROMPT = """You are an SRE assistant that answers follow-up questions about a daily briefing.

Rules:
- ONLY use information from the provided context messages. Do not make up information.
- S2: Always cite which channel or message your answer is based on.
- If the answer is not in the provided context, say "I don't have enough information
  from the monitored channels to answer that. You may want to check the channel directly."
- Be concise and direct.
- Do NOT include any email addresses, phone numbers, or personal contact information
  even if they appear in the context.
- Format ticket/issue IDs clearly so they're easy to reference."""


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
                "num_ctx": 8192,
            },
        )

        answer = response["message"]["content"]
        logger.info(f"Q&A answer generated: {len(answer)} chars")

        # S2: Append source attribution (channel_source may contain Slack hyperlinks)
        answer += f"\n\nSources: {channel_source}"

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
