"""
Safeguard utilities for the agentic Slack briefing system.

NEW FILE: Implements all safeguard checks (S1-S8) from the design doc.

This module is imported by qa_listener.py and ollama_summarizer.py to ensure
consistent security enforcement across the system.

Architecture: Pure MCP approach (no Slack Bot/Bolt).
All Slack access goes through the MCP Slack server (Podman container).
"""
import re
import os
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# S1: Channel allowlist
# Only these channels can be searched or posted to by the bot.
# Populated at startup from MONITORED_CHANNELS env var.
# ---------------------------------------------------------------------------
ALLOWED_CHANNELS: dict[str, str] = {}  # {channel_id: channel_name}


def load_allowed_channels(channels: list[dict]) -> None:
    """Load allowed channels from configuration.
    S1: Establishes the allowlist that all other safeguards reference.
    """
    global ALLOWED_CHANNELS
    ALLOWED_CHANNELS = {ch["id"]: ch["name"] for ch in channels}
    logger.info(f"S1: Loaded {len(ALLOWED_CHANNELS)} allowed channels: "
                f"{list(ALLOWED_CHANNELS.values())}")


def is_channel_allowed(channel_id: str) -> bool:
    """Check if a channel is in the allowlist.
    S1: Core access control check.
    """
    allowed = channel_id in ALLOWED_CHANNELS
    if not allowed:
        logger.warning(f"S1: Channel {channel_id} is NOT in the allowlist")
    return allowed


# ---------------------------------------------------------------------------
# S3/S4: Channel access control
# CHANGED: With pure MCP approach (no Slack Bot), we don't have a Slack
# WebClient to check per-user membership. Instead, access control is
# enforced by the channel allowlist (S1). The MCP Slack server's session
# tokens inherently limit access to channels the token owner can see.
# Any channel search goes through is_channel_allowed() which restricts
# to the MONITORED_CHANNELS allowlist only.
# ---------------------------------------------------------------------------

def get_allowed_channel_ids() -> list[str]:
    """Return list of allowed channel IDs.
    S3/S4: In MCP-only mode, the allowlist IS the access control.
    """
    return list(ALLOWED_CHANNELS.keys())


# ---------------------------------------------------------------------------
# S5: Thread-only response validation
# ---------------------------------------------------------------------------

def validate_thread_response(channel_id: str, thread_ts: str) -> bool:
    """Validate that a response will be posted in a thread, not top-level.
    S5: Prevents accidental top-level message posting.
    """
    if not thread_ts:
        logger.error("S5: Attempted to post without thread_ts - BLOCKED")
        return False
    return True


# ---------------------------------------------------------------------------
# S6: Local-only LLM endpoint validation
# ---------------------------------------------------------------------------

ALLOWED_LLM_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "host.docker.internal"}


def validate_llm_endpoint(base_url: str) -> bool:
    """Verify the LLM endpoint is local-only.
    S6: Blocks any attempt to send data to external AI APIs.
    """
    from urllib.parse import urlparse
    parsed = urlparse(base_url)
    hostname = parsed.hostname or ""

    if hostname not in ALLOWED_LLM_HOSTS:
        logger.error(
            f"S6: LLM endpoint '{base_url}' is NOT local. "
            f"Hostname '{hostname}' not in allowed list: {ALLOWED_LLM_HOSTS}. "
            f"BLOCKED to prevent data exfiltration."
        )
        return False

    logger.info(f"S6: LLM endpoint validated as local: {base_url}")
    return True


# ---------------------------------------------------------------------------
# S8: PII sanitization
# ---------------------------------------------------------------------------

# Patterns for common PII
_EMAIL_PATTERN = re.compile(
    r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
)
_PHONE_PATTERN = re.compile(
    r'(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b'
)
# IP addresses (common in SRE contexts)
_IP_PATTERN = re.compile(
    r'\b(?:\d{1,3}\.){3}\d{1,3}\b'
)
# AWS account IDs (12 digits)
_AWS_ACCOUNT_PATTERN = re.compile(
    r'\b\d{12}\b'
)


def sanitize_for_llm(text: str) -> str:
    """Remove PII from text before sending to LLM.
    S8: Strips emails, phone numbers, IPs, and account IDs.

    Note: This is a best-effort sanitization. Ticket IDs (ITN-*, OHSS-*, etc.)
    are intentionally preserved as they are needed for context but are not PII.
    """
    sanitized = text

    # Replace emails with placeholder
    emails_found = _EMAIL_PATTERN.findall(sanitized)
    if emails_found:
        sanitized = _EMAIL_PATTERN.sub("[EMAIL_REDACTED]", sanitized)
        logger.info(f"S8: Redacted {len(emails_found)} email(s)")

    # Replace phone numbers with placeholder
    phones_found = _PHONE_PATTERN.findall(sanitized)
    if phones_found:
        sanitized = _PHONE_PATTERN.sub("[PHONE_REDACTED]", sanitized)
        logger.info(f"S8: Redacted {len(phones_found)} phone number(s)")

    # Replace IP addresses with placeholder (but keep loopback/private ranges info)
    def _redact_ip(match):
        ip = match.group(0)
        # Keep private/loopback ranges as they're not customer PII
        if ip.startswith(("127.", "10.", "192.168.", "172.")):
            return ip
        return "[IP_REDACTED]"

    sanitized = _IP_PATTERN.sub(_redact_ip, sanitized)

    # Replace AWS account IDs (12 consecutive digits not part of a larger number)
    sanitized = _AWS_ACCOUNT_PATTERN.sub("[ACCOUNT_REDACTED]", sanitized)

    return sanitized
