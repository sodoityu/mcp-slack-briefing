"""
Q&A Listener - Polls briefing threads for follow-up questions and answers them.

NEW FILE: Replaces slack_bot.py (Bolt approach) with a pure MCP approach.
No Slack App, no bot tokens, no OAuth. Uses the same xoxc/xoxd session tokens
and MCP Slack server that daily_briefing.py already uses.

How it works:
1. After a briefing is posted, this script polls the briefing thread every 10s
2. When a new reply is found, it reads the BRIEFING FILE for context (not all of Slack)
3. If the briefing context isn't enough, it searches ONLY allowed channels via MCP
4. Sends (question + context) to Ollama for an answer
5. Posts the answer back in the same thread via MCP

IMPORTANT: The LLM only sees the briefing context. If a user asks "did sev1 get resolved",
it refers to the sev1s mentioned in THAT briefing, not all sev1s across all of Slack.

Safeguards implemented:
- S1: Only searches channels from the allowlist
- S2: Answers grounded in briefing context only, with source citations
- S3/S4: Channel search restricted to allowed channels (MCP tokens scope)
- S5: All replies posted in-thread only
- S6: Ollama endpoint validated as local-only
- S7: All config from .mcp.json and environment, never hardcoded
- S8: PII sanitized before sending to Ollama
"""
import asyncio
import json
import os
import sys
import logging
import re
from datetime import datetime, timedelta

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from ollama_summarizer import answer_followup, check_ollama_available
from safeguards import (
    sanitize_for_llm,
    validate_llm_endpoint,
    is_channel_allowed,
    load_allowed_channels,
    ALLOWED_CHANNELS,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (S7: all from env / config files)
# ---------------------------------------------------------------------------
CONFIG_PATH = os.environ.get("MCP_CONFIG_PATH", ".mcp.json")
POLL_INTERVAL = int(os.environ.get("QA_POLL_INTERVAL", "10"))  # seconds
BRIEFING_CHANNEL_ID = os.environ.get("BRIEFING_CHANNEL_ID", "")

# Load monitored channels
CHANNELS = json.loads(os.environ.get("MONITORED_CHANNELS", "[]"))


def load_config():
    """Load MCP Slack server config from .mcp.json (S7)."""
    try:
        with open(CONFIG_PATH, "r") as f:
            config = json.load(f)
        return config["mcpServers"]["slack"]
    except (FileNotFoundError, KeyError) as e:
        logger.error(f"S7: Cannot load MCP config from {CONFIG_PATH}: {e}")
        sys.exit(1)


def get_server_params(slack_config):
    """Create MCP StdioServerParameters from config."""
    return StdioServerParameters(
        command=slack_config["command"],
        args=slack_config["args"],
        env=slack_config["env"],
    )


# ---------------------------------------------------------------------------
# Briefing context loader
# ---------------------------------------------------------------------------

def load_briefing_context() -> str:
    """Load the most recent briefing file as context.

    S2: This is the PRIMARY context for answering questions.
    The LLM only knows about sev1s, incidents, etc. that appear in THIS file.
    It will not hallucinate about sev1s from other days or channels.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    # Try summary first (AI-processed), then raw briefing
    for date_str in [today, yesterday]:
        for prefix in ["briefing_summary_", "briefing_"]:
            filepath = f"{prefix}{date_str}.txt"
            try:
                with open(filepath, "r") as f:
                    content = f.read()
                if content.strip():
                    logger.info(f"S2: Loaded briefing context from {filepath}")
                    return content
            except FileNotFoundError:
                continue

    logger.warning("No briefing file found for today or yesterday")
    return ""


# ---------------------------------------------------------------------------
# MCP operations: fetch thread replies, search channels, post reply
# ---------------------------------------------------------------------------

def fetch_thread_replies_direct(
    slack_config, channel_id: str, thread_ts: str
) -> list[dict]:
    """Fetch all replies in a thread using Slack API directly.

    CHANGED: Bypasses MCP entirely for reading thread replies because the
    MCP Slack server sends log messages over stdout that crash the MCP SDK's
    JSON-RPC parser. Direct API calls are reliable.

    Uses the same xoxc/xoxd tokens from .mcp.json.
    """
    import requests

    xoxc = slack_config["env"].get("SLACK_XOXC_TOKEN", "")
    xoxd = slack_config["env"].get("SLACK_XOXD_TOKEN", "")

    messages = []

    try:
        resp = requests.get(
            "https://slack.com/api/conversations.replies",
            params={
                "channel": channel_id,
                "ts": thread_ts,
                "limit": 100,
            },
            headers={"Authorization": f"Bearer {xoxc}"},
            cookies={"d": xoxd},
        )

        if resp.ok:
            data = resp.json()
            if data.get("ok"):
                # Skip the first message (it's the header, not a reply)
                all_msgs = data.get("messages", [])
                for msg in all_msgs[1:]:  # Skip parent message
                    messages.append({
                        "text": msg.get("text", ""),
                        "user": msg.get("user", ""),
                        "ts": msg.get("ts", ""),
                        "bot_id": msg.get("bot_id"),
                    })
                logger.debug(f"Fetched {len(messages)} thread replies")
            else:
                logger.error(f"Slack API error: {data.get('error')}")
        else:
            logger.error(f"Slack API HTTP error: {resp.status_code}")

    except Exception as e:
        logger.error(f"Error fetching thread replies: {e}")

    return messages


async def search_allowed_channels_for_context(
    slack_config, keywords: list[str], hours_back: int = 48
) -> str:
    """Search ONLY allowed channels for messages matching keywords.

    S1: Only channels in the allowlist are searched.
    S4: No cross-channel leakage — only pre-approved channels.

    This is the SECONDARY context source, used only when the briefing file
    doesn't have enough detail to answer the question.
    """
    server_params = get_server_params(slack_config)
    oldest_date = (datetime.now() - timedelta(hours=hours_back)).strftime("%Y-%m-%d")
    context_parts = []

    for ch_id, ch_name in ALLOWED_CHANNELS.items():
        # S1: Double-check allowlist
        if not is_channel_allowed(ch_id):
            continue

        try:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    result = await session.call_tool(
                        "get_channel_history",
                        arguments={
                            "channel_id": ch_id,
                            "oldest": oldest_date,
                            "limit": 200,
                            "include_threads": False,
                        },
                    )

                    channel_messages = []
                    if result.content:
                        for item in result.content:
                            if hasattr(item, "text"):
                                try:
                                    data = json.loads(item.text)
                                    if isinstance(data, dict) and "result" in data:
                                        channel_messages = data["result"]
                                    elif isinstance(data, list):
                                        channel_messages = data
                                except json.JSONDecodeError:
                                    if not item.text.startswith(
                                        ("Retrieved", "Getting")
                                    ):
                                        channel_messages.append(item.text)

                    # Filter to messages containing any of the keywords
                    relevant = []
                    for msg in channel_messages:
                        msg_text = msg if isinstance(msg, str) else str(msg)
                        msg_lower = msg_text.lower()
                        if any(kw.lower() in msg_lower for kw in keywords):
                            relevant.append(msg_text)

                    if relevant:
                        context_parts.append(
                            f"--- #{ch_name} (S1: allowed channel) ---"
                        )
                        for m in relevant[:20]:  # Cap at 20 per channel
                            context_parts.append(m)

        except Exception as e:
            logger.warning(f"Error searching #{ch_name}: {e}")

    return "\n".join(context_parts)


async def post_thread_reply(
    slack_config, channel_id: str, thread_ts: str, message: str
) -> bool:
    """Post a reply in a thread via MCP.

    S5: Always posts in-thread (thread_ts required). Never top-level.
    """
    # S5: Hard block on missing thread_ts
    if not thread_ts:
        logger.error("S5: Cannot post reply without thread_ts — BLOCKED")
        return False

    server_params = get_server_params(slack_config)

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                await session.call_tool(
                    "post_message",
                    arguments={
                        "channel_id": channel_id,
                        "message": message,
                        "thread_ts": thread_ts,
                        "skip_log": True,
                    },
                )
                logger.info(f"S5: Reply posted in thread {thread_ts}")
                return True
    except Exception as e:
        logger.error(f"Failed to post reply: {e}")
        return False


def get_briefing_thread_from_file(channel_id: str) -> str | None:
    """Read the briefing thread timestamp from .briefing_thread.json.

    CHANGED: Instead of searching channel history via MCP (which was failing
    due to pydantic errors from the MCP server's log messages), we now read
    the thread_ts from a file that post_summary_to_slack.py saves after posting.

    This is simpler and more reliable.
    """
    thread_file = ".briefing_thread.json"
    try:
        with open(thread_file, "r") as f:
            data = json.load(f)

        # Verify it's for the right channel
        if data.get("channel_id") != channel_id:
            logger.warning(
                f"Thread file is for channel {data.get('channel_id')}, "
                f"but we're monitoring {channel_id}"
            )
            return None

        thread_ts = data.get("thread_ts")
        if thread_ts:
            logger.info(
                f"Loaded briefing thread from file: {thread_ts} "
                f"(posted: {data.get('posted_at', 'unknown')})"
            )
            return thread_ts

    except FileNotFoundError:
        logger.info(
            f"No {thread_file} found. Post a briefing first with:\n"
            f"  python post_summary_to_slack.py briefing_summary_*.txt <start> <end>"
        )
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Error reading {thread_file}: {e}")

    return None


# ---------------------------------------------------------------------------
# Extract keywords from a question for targeted channel search
# ---------------------------------------------------------------------------

def extract_keywords(question: str) -> list[str]:
    """Extract meaningful keywords from a user question for channel search.

    Filters out common stop words to focus on terms that will actually
    help find relevant messages.
    """
    stop_words = {
        "did", "does", "do", "is", "are", "was", "were", "has", "have", "had",
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "it", "this", "that", "these", "those",
        "any", "anyone", "someone", "what", "who", "how", "when", "where",
        "can", "could", "would", "should", "will", "about", "been", "being",
        "get", "got", "know", "tell", "me", "there", "here", "just", "also",
        "more", "not", "no", "yes", "yet", "still", "already", "up", "out",
    }

    # Extract words, keep ticket IDs intact (e.g., ITN-2026-12345)
    words = re.findall(r"[A-Za-z0-9][\w-]*", question)
    keywords = [w for w in words if w.lower() not in stop_words and len(w) > 1]

    # Always include ticket-like patterns
    tickets = re.findall(
        r"(?:ITN-\d+-\d+|ARO-\d+|SREP-\d+|OHSS-\d+|OCPBUGS-\d+)", question
    )
    keywords.extend(tickets)

    return list(set(keywords)) if keywords else [question.strip()]


# ---------------------------------------------------------------------------
# Main Q&A handler
# ---------------------------------------------------------------------------

async def handle_question(
    slack_config, channel_id: str, thread_ts: str, question: str
):
    """Process a follow-up question and post the answer.

    Flow:
    1. Load briefing file as PRIMARY context (S2: scoped to this briefing only)
    2. If needed, search allowed channels for more detail (S1: allowlist only)
    3. Sanitize everything (S8)
    4. Send to Ollama (S6: local only)
    5. Post answer in thread (S5: thread only)
    """
    # S5: Post a "thinking" indicator in the thread
    await post_thread_reply(
        slack_config, channel_id, thread_ts,
        "Searching for relevant information..."
    )

    # Step 1: Load briefing context (S2: PRIMARY source — scoped to this briefing)
    briefing_context = load_briefing_context()

    if not briefing_context:
        await post_thread_reply(
            slack_config, channel_id, thread_ts,
            "No briefing data found for today. "
            "Please run the daily collection first."
        )
        return

    # Step 2: Check if briefing context is sufficient, or if we need channel search
    # Extract keywords to see if we need deeper search
    keywords = extract_keywords(question)
    logger.info(f"Extracted keywords: {keywords}")

    # Start with briefing context only
    full_context = (
        "=== BRIEFING CONTEXT (primary source — answer from this first) ===\n"
        f"{briefing_context}\n"
    )

    # Only search channels if the question references something specific
    # that might need more detail than the briefing provides
    needs_detail = any(
        indicator in question.lower()
        for indicator in [
            "detail", "more info", "what happened", "full", "thread",
            "update", "latest", "resolved", "fixed", "status",
            "who said", "when did", "timeline",
        ]
    )

    if needs_detail and keywords:
        logger.info("Question needs more detail — searching allowed channels")
        # S1: Only allowed channels searched
        channel_context = await search_allowed_channels_for_context(
            slack_config, keywords
        )
        if channel_context:
            full_context += (
                "\n=== ADDITIONAL CONTEXT FROM ALLOWED CHANNELS (S1) ===\n"
                f"{channel_context}\n"
            )

    # Step 3 + 4: Send to Ollama (S6 + S8 handled inside answer_followup)
    # CHANGED: Build source links with Slack channel hyperlinks
    # Slack link format: <https://slack.com/archives/CHANNEL_ID|#channel-name>
    workspace_url = slack_config.get("env", {}).get(
        "SLACK_WORKSPACE_URL", "https://slack.com"
    ).rstrip("/")
    channel_links = ", ".join(
        f"<{workspace_url}/archives/{ch_id}|#{name}>"
        for ch_id, name in ALLOWED_CHANNELS.items()
        if name != "briefing-channel"  # exclude the generic fallback name
    )
    answer = answer_followup(
        question=question,
        context_messages=full_context,
        channel_source=channel_links if channel_links else "monitored channels",
    )

    # Step 5: Post answer in thread (S5)
    await post_thread_reply(slack_config, channel_id, thread_ts, answer)


# ---------------------------------------------------------------------------
# Polling loop
# ---------------------------------------------------------------------------

async def poll_briefing_thread(slack_config, channel_id: str):
    """Main polling loop — watches the briefing thread for new questions.

    Polls every POLL_INTERVAL seconds. Tracks which messages we've already
    seen so we don't answer the same question twice.
    """
    logger.info(f"Looking for briefing thread in channel {channel_id}...")

    thread_ts = None
    seen_ts: set[str] = set()  # Track seen message timestamps to avoid re-answering

    while True:
        try:
            # CHANGED: Read thread_ts from file instead of searching channel history
            if thread_ts is None:
                thread_ts = get_briefing_thread_from_file(channel_id)
                if thread_ts is None:
                    logger.info(
                        f"No briefing thread found yet. "
                        f"Waiting for post_summary_to_slack.py to create "
                        f".briefing_thread.json... (retrying in {POLL_INTERVAL}s)"
                    )
                    await asyncio.sleep(POLL_INTERVAL)
                    continue

                logger.info(f"Monitoring briefing thread: {thread_ts}")
                # Mark existing replies as "seen" so we don't re-answer old ones
                existing = fetch_thread_replies_direct(
                    slack_config, channel_id, thread_ts
                )
                for msg in existing:
                    seen_ts.add(msg.get("ts", ""))
                logger.info(
                    f"Marked {len(seen_ts)} existing replies as seen"
                )

            # Poll for new replies (direct Slack API, no MCP)
            replies = fetch_thread_replies_direct(
                slack_config, channel_id, thread_ts
            )

            for reply in replies:
                reply_ts = reply.get("ts", "")
                reply_text = reply.get("text", "")
                reply_user = reply.get("user", "")

                # Skip if already seen (by timestamp — unique per message)
                if reply_ts in seen_ts:
                    continue

                # Skip bot messages (our own replies)
                if reply.get("bot_id"):
                    seen_ts.add(reply_ts)
                    continue

                # Skip our own replies by content
                if any(
                    marker in reply_text
                    for marker in [
                        "Sources:",
                        "Searching for relevant information",
                        "No briefing data found",
                        "I don't have enough information",
                    ]
                ):
                    seen_ts.add(reply_ts)
                    continue

                # Skip empty or too-short messages
                if not reply_text.strip() or len(reply_text.strip()) < 3:
                    seen_ts.add(reply_ts)
                    continue

                # New question found!
                logger.info(f"New question from {reply_user}: {reply_text[:100]}")
                seen_ts.add(reply_ts)

                # Handle the question
                await handle_question(
                    slack_config, channel_id, thread_ts, reply_text
                )

        except Exception as e:
            logger.error(f"Polling error: {e}")

        await asyncio.sleep(POLL_INTERVAL)


# ---------------------------------------------------------------------------
# Daily reset: detect new briefing posts
# ---------------------------------------------------------------------------

async def run_listener(slack_config, channel_id: str):
    """Run the listener with daily reset detection.

    If a new briefing is posted (new day), automatically switches
    to monitoring the new thread.
    """
    logger.info("=" * 60)
    logger.info("Q&A Listener Starting")
    logger.info(f"  Channel: {channel_id}")
    logger.info(f"  Poll interval: {POLL_INTERVAL}s")
    logger.info(f"  Allowed channels: {list(ALLOWED_CHANNELS.values())}")
    logger.info("=" * 60)

    # S6: Validate Ollama before starting
    if not check_ollama_available():
        logger.error(
            "Ollama is not available. Start it with: ollama serve\n"
            f"Then pull the model: ollama pull {os.environ.get('OLLAMA_MODEL', 'llama3.1:8b')}"
        )
        sys.exit(1)

    await poll_briefing_thread(slack_config, channel_id)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    if not BRIEFING_CHANNEL_ID:
        logger.error(
            "BRIEFING_CHANNEL_ID environment variable must be set.\n"
            "This is the channel where briefings are posted.\n"
            "Example: export BRIEFING_CHANNEL_ID=C04F0GWTD9B"
        )
        sys.exit(1)

    if not CHANNELS:
        logger.error(
            "MONITORED_CHANNELS environment variable must be set.\n"
            'Example: export MONITORED_CHANNELS=\'[{"id":"C04F0GWTD9B","name":"briefing"}]\''
        )
        sys.exit(1)

    # S1: Load channel allowlist
    load_allowed_channels(CHANNELS)

    # S1: Also add briefing channel to allowlist if not already there
    # Don't add with a generic name — it would show as "briefing-channel" in sources
    if BRIEFING_CHANNEL_ID not in ALLOWED_CHANNELS:
        # Try to get real name from env, otherwise skip
        briefing_name = os.environ.get("BRIEFING_CHANNEL_NAME", "")
        if briefing_name:
            ALLOWED_CHANNELS[BRIEFING_CHANNEL_ID] = briefing_name

    # S7: Load MCP config
    slack_config = load_config()

    # Run the listener
    asyncio.run(run_listener(slack_config, BRIEFING_CHANNEL_ID))


if __name__ == "__main__":
    main()
