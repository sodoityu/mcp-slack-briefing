#!/usr/bin/env python3
"""
Post a briefing summary to Slack with header + threaded reply.
Usage: python post_summary_to_slack.py <summary_file> <start_date> <end_date> [channel_id]

CHANGED: Now saves the thread timestamp to .briefing_thread.json so
qa_listener.py knows which thread to monitor. No more searching channel
history to find the briefing post.
"""
import asyncio
import json
import os
import sys
from datetime import datetime

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except ImportError:
    print("Error: MCP SDK not installed.")
    sys.exit(1)

# ADDED: File to store the briefing thread info for qa_listener.py
THREAD_INFO_FILE = ".briefing_thread.json"


async def post_briefing(channel_id: str, start_date: str, end_date: str, summary: str):
    """Post briefing with header message + threaded summary."""
    # S7: Load Slack config from .mcp.json
    config_path = os.environ.get("MCP_CONFIG_PATH", ".mcp.json")
    with open(config_path, 'r') as f:
        config = json.load(f)

    slack_config = config['mcpServers']['slack']

    server_params = StdioServerParameters(
        command=slack_config['command'],
        args=slack_config['args'],
        env=slack_config['env']
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Create header
            header = (
                f":clipboard: *Daily Briefing* — {start_date} to {end_date}\n"
                f":white_check_mark: Summary ready! See thread for details :point_down:"
            )

            print("Posting header message...")

            # Post header message
            result = await session.call_tool(
                "post_message",
                arguments={
                    "channel_id": channel_id,
                    "message": header,
                    "skip_log": True
                }
            )

            # CHANGED: Extract thread_ts from post_message result
            thread_ts = None

            # Debug: print what the MCP server returned so we can see the format
            if result.content:
                for content_item in result.content:
                    if hasattr(content_item, 'text'):
                        print(f"DEBUG post_message result: {content_item.text[:500]}")
                        try:
                            data = json.loads(content_item.text)
                            # Try every possible format the MCP server might use
                            if isinstance(data, dict):
                                # Format: {"ts": "..."}
                                if 'ts' in data:
                                    thread_ts = data['ts']
                                # Format: {"result": {"ts": "..."}}
                                elif 'result' in data and isinstance(data['result'], dict):
                                    thread_ts = data['result'].get('ts')
                                # Format: {"ok": true, "ts": "..."}
                                elif data.get('ok') and 'ts' in data:
                                    thread_ts = data['ts']
                            # Format: plain string like "Message posted: 1773226074.264849"
                            elif isinstance(data, str) and '.' in data:
                                # Try to find a Slack timestamp pattern (digits.digits)
                                import re
                                ts_match = re.search(r'(\d{10}\.\d+)', data)
                                if ts_match:
                                    thread_ts = ts_match.group(1)
                        except json.JSONDecodeError:
                            # Not JSON — might be plain text with the timestamp
                            import re
                            ts_match = re.search(r'(\d{10}\.\d+)', content_item.text)
                            if ts_match:
                                thread_ts = ts_match.group(1)
                                print(f"Extracted ts from text: {thread_ts}")

            # Fallback: use Slack API directly via requests (bypasses MCP pydantic bug)
            if not thread_ts:
                print("Could not get ts from post_message result. Trying Slack API directly...")
                await asyncio.sleep(1)
                try:
                    import requests
                    # Use the same tokens from .mcp.json
                    xoxc = slack_config['env'].get('SLACK_XOXC_TOKEN', '')
                    resp = requests.get(
                        "https://slack.com/api/conversations.history",
                        params={"channel": channel_id, "limit": 3},
                        headers={"Authorization": f"Bearer {xoxc}"},
                        cookies={"d": slack_config['env'].get('SLACK_XOXD_TOKEN', '')},
                    )
                    if resp.ok:
                        api_data = resp.json()
                        if api_data.get("ok") and api_data.get("messages"):
                            for msg in api_data["messages"]:
                                if "Daily Briefing" in msg.get("text", ""):
                                    thread_ts = msg["ts"]
                                    print(f"Got ts from Slack API: {thread_ts}")
                                    break
                except Exception as e:
                    print(f"Slack API fallback failed: {e}")

            if thread_ts:
                print(f"Header posted (timestamp: {thread_ts})")

                # S5: Post detailed summary as threaded reply
                print("Posting detailed summary as threaded reply...")
                await session.call_tool(
                    "post_message",
                    arguments={
                        "channel_id": channel_id,
                        "message": summary,
                        "thread_ts": thread_ts,
                        "skip_log": True
                    }
                )
                print("Threaded reply posted successfully!")

                # ADDED: Save thread info so qa_listener.py can find it
                thread_info = {
                    "channel_id": channel_id,
                    "thread_ts": thread_ts,
                    "date_range": f"{start_date} to {end_date}",
                    "posted_at": datetime.now().isoformat(),
                }
                with open(THREAD_INFO_FILE, "w") as f:
                    json.dump(thread_info, f, indent=2)
                print(f"Thread info saved to {THREAD_INFO_FILE}")

            else:
                # Fallback: post as regular message if we couldn't get timestamp
                print("Warning: Could not get timestamp, posting as separate message...")
                await session.call_tool(
                    "post_message",
                    arguments={
                        "channel_id": channel_id,
                        "message": summary,
                        "skip_log": True
                    }
                )


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python post_summary_to_slack.py <summary_file> <start_date> <end_date> [channel_id]")
        print("Example: python post_summary_to_slack.py briefing_summary.txt 2026-03-10 2026-03-11 C04F0GWTD9B")
        sys.exit(1)

    summary_file = sys.argv[1]
    start_date = sys.argv[2]
    end_date = sys.argv[3]
    channel_id = sys.argv[4] if len(sys.argv) > 4 else os.environ.get("BRIEFING_CHANNEL_ID", "")

    if not channel_id:
        print("ERROR: No channel ID provided. Pass as argument or set BRIEFING_CHANNEL_ID env var.")
        sys.exit(1)

    # Read summary from file
    with open(summary_file, 'r') as f:
        summary_content = f.read()

    print(f"Posting to channel: {channel_id}")
    print(f"Date range: {start_date} to {end_date}\n")

    asyncio.run(post_briefing(channel_id, start_date, end_date, summary_content))
