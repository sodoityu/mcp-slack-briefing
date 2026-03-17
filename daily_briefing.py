#!/usr/bin/env python3
"""
Daily Briefing Generator - Collects important Slack messages from multiple channels.

CHANGED: Summarization is now handled by local Ollama instead of Claude Code.
This ensures no Slack data leaves the local machine (Safeguard S6).
Original collection and filtering logic is preserved.
"""
import asyncio
import json
import os
import sys
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any

# Try to import required packages
try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except ImportError:
    print("Error: MCP SDK not installed.")
    print("Install it with: poetry add mcp")
    sys.exit(1)

# CHANGED: Anthropic/Claude Code no longer needed.
# Summarization is now handled by local Ollama (see ollama_summarizer.py).
# This keeps all Slack data on the local machine (Safeguard S6).
from ollama_summarizer import summarize_briefing, check_ollama_available


class DailyBriefing:
    def __init__(self, config_path: str = '.mcp.json'):
        """Initialize the daily briefing generator."""
        with open(config_path, 'r') as f:
            config = json.load(f)

        self.slack_config = config['mcpServers']['slack']

    async def fetch_channel_history(
        self,
        channel_id: str,
        channel_name: str,
        hours_back: int = 24
    ) -> List[str]:
        """Fetch messages from a channel for the last N hours."""
        oldest_date = (datetime.now() - timedelta(hours=hours_back)).strftime("%Y-%m-%d")

        server_params = StdioServerParameters(
            command=self.slack_config['command'],
            args=self.slack_config['args'],
            env=self.slack_config['env']
        )

        messages = []

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Call get_channel_history
                result = await session.call_tool(
                    "get_channel_history",
                    arguments={
                        "channel_id": channel_id,
                        "oldest": oldest_date,
                        "limit": 1000,
                        "include_threads": False
                    }
                )

                # Parse results
                if result.content:
                    for content_item in result.content:
                        if hasattr(content_item, 'text'):
                            try:
                                data = json.loads(content_item.text)
                                if isinstance(data, dict) and 'result' in data:
                                    msgs = data['result']
                                elif isinstance(data, list):
                                    msgs = data
                                else:
                                    msgs = [content_item.text]
                            except json.JSONDecodeError:
                                # Skip log messages
                                if content_item.text.startswith(("Retrieved", "Getting")):
                                    continue
                                msgs = [content_item.text]

                            messages.extend(msgs)

        return messages

    def filter_important_messages(self, messages: List[str]) -> List[str]:
        """Filter messages based on importance indicators."""
        # Ticket/Issue patterns
        ticket_patterns = [
            r'ITN-2026-\d+',
            r'ARO-\d+',
            r'SREP-\d+',
            r'OHSS-\d+',
            r'OCPBUGS-\d+',
            r'PR #\d+',
            r'MR #\d+',
        ]

        # Important keywords
        important_keywords = [
            'BUG', 'ISSUE', 'Incidents', 'incident', 'stuck', 'upgrade',
            'Blocked', 'blocked', 'paused', 'error', 'warning',
            'ASAP', 'urgent', 'critical', 'outage', 'failed', 'failure',
            'crash', 'down', 'investigating', 'escalate', 'priority',
            'emergency', 'hotfix', 'rollback', 'degraded', 'alert'
        ]

        # Important emojis
        important_emojis = ['🔥', '⚠️', '🚨', '❌', '⛔', '🔴', '🟡', '🆘']

        filtered = []
        for msg in messages:
            msg_lower = msg.lower()

            # Check for ticket/issue references
            has_ticket = any(re.search(pattern, msg, re.IGNORECASE) for pattern in ticket_patterns)

            # Check for important keywords
            has_keyword = any(keyword.lower() in msg_lower for keyword in important_keywords)

            # Check for important emojis
            has_emoji = any(emoji in msg for emoji in important_emojis)

            if has_ticket or has_keyword or has_emoji:
                filtered.append(msg)

        return filtered

    def format_messages_for_review(
        self,
        channels_data: Dict[str, List[str]],
        start_date: str,
        end_date: str
    ) -> str:
        """Format messages for Claude Code to review and summarize."""
        output = f"# 📊 Collected Slack Messages for Review\n"
        output += f"**Period:** {start_date} to {end_date}\n\n"

        # Add channel emoji mapping
        channel_emojis = {
            'forum-rosa-support': '🔵',
            'team-rosa-hcp-platform': '🟣',
            'hcm-aro-hcp-triage': '🔴',
            'forum-aro-eng': '🟠'
        }

        total_messages = 0
        for channel_name, messages in channels_data.items():
            emoji = channel_emojis.get(channel_name, '📢')
            total_messages += len(messages)

            output += f"\n{'═' * 80}\n"
            output += f"{emoji} **Channel: #{channel_name}**\n"
            output += f"{'═' * 80}\n"
            output += f"**Important messages found:** {len(messages)}\n\n"

            if messages:
                for i, msg in enumerate(messages, 1):
                    # Add visual separator
                    output += f"───────────────────────────────────────────────────────────────\n"

                    # Extract severity if present
                    severity = ""
                    if any(x in msg for x in ['critical', 'CRITICAL', '🔴', 'blocked', 'BLOCKED']):
                        severity = "🔴 "
                    elif any(x in msg for x in ['warning', 'WARNING', '🟡', 'degraded']):
                        severity = "🟡 "
                    elif any(x in msg for x in ['incident', 'INCIDENT', 'ITN-', '🚨']):
                        severity = "🚨 "
                    elif any(x in msg for x in ['urgent', 'URGENT', 'ASAP']):
                        severity = "⚠️ "

                    output += f"{severity}**Message {i}:**\n"
                    output += f"{msg}\n\n"
            else:
                output += f"_No important messages in this period._\n\n"

        output += f"\n{'═' * 80}\n"
        output += f"**📈 Summary Statistics**\n"
        output += f"{'═' * 80}\n"
        output += f"- Total channels monitored: {len(channels_data)}\n"
        output += f"- Total important messages: {total_messages}\n"
        output += f"- Period: {start_date} to {end_date}\n\n"

        if total_messages == 0:
            output += "\n**No important messages found in the specified channels during this period.**\n"
        else:
            # CHANGED: No longer asks for Claude Code - summarization is automated via Ollama
            output += f"\n**Ready for local AI summarization.**\n"

        return output

    async def post_to_slack(
        self,
        channel_id: str,
        header_message: str,
        detailed_summary: str
    ) -> bool:
        """Post the briefing to a Slack channel with summary as threaded reply."""
        server_params = StdioServerParameters(
            command=self.slack_config['command'],
            args=self.slack_config['args'],
            env=self.slack_config['env']
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                print("  📤 Posting header message...")

                # Post header message first
                await session.call_tool(
                    "post_message",
                    arguments={
                        "channel_id": channel_id,
                        "message": header_message,
                        "skip_log": True
                    }
                )

                # Small delay to ensure message is posted
                await asyncio.sleep(1)

                # Get the latest message to extract timestamp
                history_result = await session.call_tool(
                    "get_channel_history",
                    arguments={
                        "channel_id": channel_id,
                        "limit": 5
                    }
                )

                # Extract timestamp from the most recent message
                thread_ts = None
                if history_result.content:
                    for content_item in history_result.content:
                        if hasattr(content_item, 'text'):
                            try:
                                data = json.loads(content_item.text)
                                if isinstance(data, dict) and 'result' in data:
                                    messages = data['result']
                                    if messages:
                                        # First message should be our header
                                        first_msg = messages[0]
                                        # Extract timestamp from format: [1773226074.264849] @user: message
                                        if first_msg.startswith('['):
                                            thread_ts = first_msg.split(']')[0].strip('[')
                                            print(f"  ✅ Header posted (timestamp: {thread_ts})")
                                            break
                            except:
                                pass

                # Post detailed summary as a threaded reply
                if thread_ts:
                    print("  📝 Posting detailed summary as threaded reply...")
                    await session.call_tool(
                        "post_message",
                        arguments={
                            "channel_id": channel_id,
                            "message": detailed_summary,
                            "thread_ts": thread_ts,
                            "skip_log": True
                        }
                    )
                    print("  ✅ Threaded reply posted successfully!")
                else:
                    # Fallback: post as regular message if we couldn't get timestamp
                    print("  ⚠️  Warning: Could not get timestamp, posting as separate message")
                    await session.call_tool(
                        "post_message",
                        arguments={
                            "channel_id": channel_id,
                            "message": detailed_summary,
                            "skip_log": True
                        }
                    )

                return True

    async def create_briefing(
        self,
        channels: List[Dict[str, str]],
        hours_back: int = 24,
        post_to_channel: str = None,
        output_file: str = None,
        use_friendly_dates: bool = True
    ) -> str:
        """Create the daily briefing."""
        end_date = datetime.now()
        start_date = end_date - timedelta(hours=hours_back)

        # Create friendly date strings
        if use_friendly_dates and hours_back == 24:
            # For 24-hour briefings, show as "Yesterday to Today"
            if start_date.date() == (end_date - timedelta(days=1)).date():
                date_range_str = f"{start_date.strftime('%b %d')} (yesterday) to {end_date.strftime('%b %d')} (today)"
            else:
                date_range_str = f"{start_date.strftime('%b %d')} to {end_date.strftime('%b %d')}"
        else:
            date_range_str = f"{start_date.strftime('%b %d')} to {end_date.strftime('%b %d')}"

        print(f"📊 Daily Briefing Generator")
        print(f"{'=' * 80}")
        print(f"Period: {date_range_str}")
        print(f"Time range: {start_date.strftime('%Y-%m-%d %H:%M')} to {end_date.strftime('%Y-%m-%d %H:%M')}")
        print(f"Channels: {', '.join([c['name'] for c in channels])}")
        print(f"{'=' * 80}\n")

        # Fetch messages from all channels
        all_channels_data = {}

        for channel in channels:
            print(f"📥 Fetching messages from #{channel['name']}...", end=" ")
            try:
                messages = await self.fetch_channel_history(
                    channel['id'],
                    channel['name'],
                    hours_back
                )

                # Filter for important messages
                important = self.filter_important_messages(messages)

                print(f"✅ {len(messages)} total, {len(important)} important")
                all_channels_data[channel['name']] = important
            except Exception as e:
                print(f"❌ Error: {e}")
                all_channels_data[channel['name']] = []

        print(f"\n📝 Formatting messages for review...\n")

        # Format messages for Claude Code to review
        formatted_output = self.format_messages_for_review(
            all_channels_data,
            start_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d")
        )

        full_briefing = formatted_output

        # Save to file
        if output_file:
            with open(output_file, 'w') as f:
                f.write(full_briefing)
            print(f"💾 Saved to: {output_file}\n")

        # Store formatted output for manual posting
        self._last_briefing_data = {
            'formatted_output': full_briefing,
            'start_date': start_date.strftime("%Y-%m-%d"),
            'end_date': end_date.strftime("%Y-%m-%d"),
            'date_range_str': date_range_str,
            'hours_back': hours_back,
            'channels': channels
        }

        return full_briefing

    async def post_briefing_to_slack(
        self,
        channel_id: str,
        summary_text: str,
        start_date: str,
        end_date: str
    ):
        """Post a briefing summary to Slack with header + threaded detail."""
        # Create short header message
        header = f"""📋 Daily Briefing — {start_date} to {end_date}
✅ Summary ready! See thread for details 👇"""

        # Post to Slack (header + threaded summary)
        print(f"\n📤 Posting to Slack channel {channel_id}...")
        try:
            await self.post_to_slack(channel_id, header, summary_text)
            print(f"\n✅ Posted to Slack successfully!\n")
        except Exception as e:
            print(f"\n❌ Error posting to Slack: {e}\n")


async def main():
    """Main function."""
    # CHANGED: Load channels from MONITORED_CHANNELS env var instead of hardcoding.
    # Set it in .env as a JSON array, e.g.:
    # MONITORED_CHANNELS=[{"id":"C04XXXXXX","name":"my-channel"}]
    channels_env = os.environ.get("MONITORED_CHANNELS", "")
    if channels_env:
        channels = json.loads(channels_env)
    else:
        print("ERROR: MONITORED_CHANNELS environment variable not set.")
        print('Set it as a JSON array, e.g.:')
        print('  export MONITORED_CHANNELS=\'[{"id":"C04XXXXXX","name":"my-channel"}]\'')
        print("Or add it to your .env file. See .env.example for format.")
        sys.exit(1)

    # CHANGED: Load target channel from env var instead of hardcoding
    post_channel = os.environ.get("BRIEFING_CHANNEL_ID", "")

    # Parse command line arguments
    hours_back = 24
    output_file = f"briefing_{datetime.now().strftime('%Y-%m-%d')}.txt"
    post_to_slack = True

    if len(sys.argv) > 1:
        hours_back = int(sys.argv[1])
    if len(sys.argv) > 2:
        output_file = sys.argv[2]
    if len(sys.argv) > 3:
        post_to_slack = sys.argv[3].lower() in ['true', 'yes', '1']

    # Create briefing
    briefing = DailyBriefing()
    summary = await briefing.create_briefing(
        channels=channels,
        hours_back=hours_back,
        post_to_channel=post_channel if post_to_slack else None,
        output_file=output_file
    )

    print(f"{'=' * 80}")
    print(summary)
    print(f"{'=' * 80}")

    # ADDED: Automatic summarization via local Ollama (replaces manual Claude Code step)
    # S6: All LLM processing happens locally - no data leaves the machine
    # S8: PII sanitization applied inside summarize_briefing()
    if check_ollama_available():
        date_range = f"{(datetime.now() - timedelta(hours=hours_back)).strftime('%Y-%m-%d')} to {datetime.now().strftime('%Y-%m-%d')}"
        print(f"\nSummarizing with local AI (Ollama)...")
        ai_summary = summarize_briefing(summary, date_range)

        summary_file = output_file.replace("briefing_", "briefing_summary_")
        with open(summary_file, "w") as f:
            f.write(ai_summary)
        print(f"AI summary saved to: {summary_file}")

        print(f"\n{'=' * 80}")
        print(ai_summary)
        print(f"{'=' * 80}")
    else:
        print(
            "\nOllama not available - skipping AI summarization.\n"
            "Raw messages saved. Start Ollama and run:\n"
            f"  python ollama_summarizer.py {output_file}"
        )

    print("\nDaily briefing generated successfully!")


if __name__ == "__main__":
    print(f"{'=' * 80}")
    print("Daily Briefing Generator for Slack")
    print(f"{'=' * 80}")
    print(f"Usage: {sys.argv[0]} [hours_back] [output_file] [post_to_slack]")
    print(f"Example: {sys.argv[0]} 24 briefing.txt true")
    print(f"{'=' * 80}\n")

    asyncio.run(main())
