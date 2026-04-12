"""Reusable coaching session — wraps the MCP connection and Claude client.

One session can serve multiple chats (e.g. a Telegram bot) by maintaining
per-chat conversation history. The MCP subprocess stays alive for the
lifetime of the session.
"""
import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path

from anthropic import AsyncAnthropic, RateLimitError
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import db
from coach.prompts import SYSTEM_PROMPT, build_cached_system

PROJECT_ROOT = Path(__file__).parent.parent

_MEMORY_EXTRACT_PROMPT = """You are analyzing a conversation between a running coach AI and an athlete.

Extract any NEW facts about the athlete from this exchange that are worth remembering long-term.
Focus on: goals, race targets, injury history, training preferences, current fitness level, schedule constraints, preferred units (metric/imperial), personal bests, weekly mileage targets.

Existing known facts:
{existing}

New exchange to analyze:
{exchange}

Return ONLY a JSON array of new fact strings not already captured in the existing list.
If nothing new, return [].
Example: ["Training for Berlin Marathon in September 2026", "Has a history of IT band issues on right leg"]"""


# Keep at most this many messages in history to avoid token bloat.
# Tool call pairs (assistant + user) are always kept together, so this
# should be an even number. ~10 messages ≈ 5 back-and-forth exchanges.
_MAX_HISTORY = 10

# Only run memory extraction every N turns to reduce API call frequency.
_EXTRACT_EVERY_N_TURNS = 5

# Truncate large tool results to keep token counts under control.
# Strava API responses can be very large JSON blobs.
_MAX_TOOL_RESULT_CHARS = 3000


def _truncate(messages: list) -> list:
    """Drop oldest messages when history exceeds _MAX_HISTORY, keeping pairs intact."""
    if len(messages) <= _MAX_HISTORY:
        return messages
    # Always drop from the front in pairs to avoid orphaned tool results
    excess = len(messages) - _MAX_HISTORY
    return messages[excess:]


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
        self._memories: dict[int, list[str]] = {}
        self._turn_counts: dict[int, int] = {}
        self._exit_stack = AsyncExitStack()

    def _build_system(self, chat_id: int) -> list:
        """Build the system prompt, injecting known facts about the athlete."""
        facts = self._memories.get(chat_id, [])
        extra = ""
        if facts:
            facts_text = "\n".join(f"- {f}" for f in facts)
            extra = f"\n\nWhat you already know about this athlete:\n{facts_text}"
        return build_cached_system(extra)

    async def _extract_facts(self, chat_id: int, last_exchange: list) -> None:
        """Extract new facts from the latest exchange and persist them."""
        existing = self._memories.get(chat_id, [])
        prompt = _MEMORY_EXTRACT_PROMPT.format(
            existing=json.dumps(existing, indent=2),
            exchange=json.dumps(last_exchange, indent=2),
        )
        try:
            response = await self._client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            new_facts = json.loads(response.content[0].text)
            if new_facts:
                updated = existing + new_facts
                self._memories[chat_id] = updated
                await db.save_memory(chat_id, updated)
        except Exception:
            pass  # memory extraction is best-effort

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
            self._histories[chat_id], self._memories[chat_id] = await asyncio.gather(
                db.load_history(chat_id),
                db.load_memory(chat_id),
            )

        messages = self._histories[chat_id]
        messages.append({"role": "user", "content": user_message})
        self._histories[chat_id] = _truncate(messages)
        messages = self._histories[chat_id]

        self._turn_counts[chat_id] = self._turn_counts.get(chat_id, 0) + 1

        while True:
            for attempt in range(3):
                try:
                    response = await self._client.messages.create(
                        model="claude-sonnet-4-6",
                        max_tokens=4096,
                        system=self._build_system(chat_id),
                        tools=self._tools,
                        messages=messages,
                    )
                    break
                except RateLimitError:
                    if attempt == 2:
                        raise
                    await asyncio.sleep(30 * (attempt + 1))
            else:
                raise RuntimeError("Exhausted retries")

            if response.stop_reason == "end_turn":
                text = next(
                    (b.text for b in response.content if b.type == "text"), ""
                )
                messages.append({"role": "assistant", "content": response.content})
                last_exchange = messages[-2:]  # user message + assistant reply
                should_extract = (self._turn_counts.get(chat_id, 0) % _EXTRACT_EVERY_N_TURNS == 0)
                tasks = [db.save_history(chat_id, _serialize_messages(messages))]
                if should_extract:
                    tasks.append(self._extract_facts(chat_id, _serialize_messages(last_exchange)))
                await asyncio.gather(*tasks)
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
                            content = result.content[0].text if result.content else "{}"
                            if len(content) > _MAX_TOOL_RESULT_CHARS:
                                content = content[:_MAX_TOOL_RESULT_CHARS] + "\n... [truncated]"
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

    def get_memory(self, chat_id: int) -> list[str]:
        """Return the current in-memory facts for a chat."""
        return self._memories.get(chat_id, [])

    async def clear_memory(self, chat_id: int):
        """Wipe all stored facts for a chat."""
        self._memories.pop(chat_id, None)
        await db.clear_memory(chat_id)
