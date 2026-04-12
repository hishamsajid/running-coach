"""Reusable coaching session — wraps the MCP connection and Claude client.

One session can serve multiple chats (e.g. a Telegram bot) by maintaining
per-chat conversation history. The MCP subprocess stays alive for the
lifetime of the session.
"""
import json
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path

from anthropic import AsyncAnthropic
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import db

PROJECT_ROOT = Path(__file__).parent.parent

SYSTEM_PROMPT = """You are an expert running and fitness coach with deep knowledge of:
- Endurance training principles (aerobic base building, periodisation, progressive overload)
- Injury prevention: recognising warning signs, load management, the 10% rule
- Heart rate based training: 80/20 rule, Zone 2 aerobic development, lactate threshold work
- Speed development: strides, tempo runs, interval training (VO2max, threshold)
- Race preparation, peak weeks, and tapering
- Recovery: sleep, nutrition timing, easy day discipline
- Running form and biomechanics

You have access to the athlete's full Strava training history via tools.

When answering any question:
1. Fetch the relevant data FIRST — don't give generic advice when you can give data-driven advice.
2. Be specific: reference actual runs, dates, distances, paces from their history.
3. Look at recent trends (last 4–8 weeks) before making recommendations.
4. Flag injury risk patterns proactively: sudden volume spikes, too many hard days in a row, declining pace with rising HR, no easy days.
5. Apply the 10% rule: never suggest increasing weekly volume by more than 10% at once.
6. For building speed: only layer intensity on top of a solid aerobic base (at least 4–6 weeks of consistent easy mileage first).
7. For building endurance: emphasise consistency and keeping 80% of runs easy (Zone 1–2).
8. When suggesting workouts, give specific targets (e.g. "6×800m at 4:10/km with 90s rest" not just "do intervals").
9. Use the athlete's measurement preference (metric/imperial) from their profile.

Keep responses focused and actionable. Ask clarifying questions if goals are vague."""

CACHED_SYSTEM = [
    {
        "type": "text",
        "text": SYSTEM_PROMPT,
        "cache_control": {"type": "ephemeral"},
    }
]


def _serialize_messages(messages: list) -> list:
    """Convert Anthropic SDK content blocks to plain dicts for JSON storage."""
    result = []
    for msg in messages:
        content = msg["content"]
        if isinstance(content, list):
            content = [
                block.model_dump() if hasattr(block, "model_dump") else block
                for block in content
            ]
        result.append({"role": msg["role"], "content": content})
    return result


class CoachSession:
    def __init__(self):
        self._client = AsyncAnthropic()
        self._mcp_session: ClientSession | None = None
        self._tools: list[dict] = []
        self._histories: dict[int, list] = {}
        self._exit_stack = AsyncExitStack()

    async def start(self):
        """Start the MCP server subprocess and initialise the session."""
        server_script = str(PROJECT_ROOT / "strava_mcp" / "server.py")
        server_params = StdioServerParameters(
            command=sys.executable,
            args=[server_script],
            env=os.environ.copy(),
        )
        read, write = await self._exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        self._mcp_session = await self._exit_stack.enter_async_context(
            ClientSession(read, write)
        )
        await self._mcp_session.initialize()

        tools_result = await self._mcp_session.list_tools()
        self._tools = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema,
            }
            for tool in tools_result.tools
        ]

    async def stop(self):
        """Shut down the MCP server subprocess."""
        await self._exit_stack.aclose()

    async def chat(self, chat_id: int, user_message: str) -> str:
        """Process one user message and return the coach's reply.

        History is loaded from the database on first message per chat (falling
        back to in-memory if DB is unavailable), then persisted after each reply.
        """
        if chat_id not in self._histories:
            self._histories[chat_id] = await db.load_history(chat_id)

        messages = self._histories[chat_id]
        messages.append({"role": "user", "content": user_message})

        while True:
            response = await self._client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4096,
                system=CACHED_SYSTEM,
                tools=self._tools,
                messages=messages,
            )

            if response.stop_reason == "end_turn":
                text = next(
                    (b.text for b in response.content if b.type == "text"), ""
                )
                messages.append({"role": "assistant", "content": response.content})
                await db.save_history(chat_id, _serialize_messages(messages))
                return text

            elif response.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": response.content})
                tool_results = []

                for block in response.content:
                    if block.type == "tool_use":
                        try:
                            result = await self._mcp_session.call_tool(
                                block.name, block.input
                            )
                            content = (
                                result.content[0].text if result.content else "{}"
                            )
                        except Exception as e:
                            content = json.dumps({"error": str(e)})

                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": content,
                            }
                        )

                messages.append({"role": "user", "content": tool_results})

            else:
                messages.append({"role": "assistant", "content": response.content})
                return ""

    async def clear_history(self, chat_id: int):
        """Reset the conversation history for a chat."""
        self._histories.pop(chat_id, None)
        await db.clear_history(chat_id)
