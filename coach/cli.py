import asyncio
import json
import sys
from pathlib import Path

from anthropic import AsyncAnthropic
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from coach.prompts import build_cached_system

PROJECT_ROOT = Path(__file__).parent.parent

CACHED_SYSTEM = build_cached_system()


async def run_agent():
    server_script = str(PROJECT_ROOT / "strava_mcp" / "server.py")

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[server_script],
    )

    client = AsyncAnthropic()

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as mcp_session:
            await mcp_session.initialize()

            tools_result = await mcp_session.list_tools()
            anthropic_tools = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.inputSchema,
                }
                for tool in tools_result.tools
            ]

            messages = []
            event_loop = asyncio.get_event_loop()

            print("Running Coach is ready. Ask me anything about your training.")
            print("Type 'quit' to exit.\n")

            while True:
                try:
                    user_input = await event_loop.run_in_executor(
                        None, lambda: input("You: ").strip()
                    )
                except (EOFError, KeyboardInterrupt):
                    print("\nGoodbye! Keep running!")
                    break

                if not user_input:
                    continue
                if user_input.lower() in ("quit", "exit", "q"):
                    print("Goodbye! Keep running!")
                    break

                messages.append({"role": "user", "content": user_input})

                # Inner agentic loop — runs until Claude stops calling tools
                while True:
                    response = await client.messages.create(
                        model="claude-sonnet-4-6",
                        max_tokens=4096,
                        system=CACHED_SYSTEM,
                        tools=anthropic_tools,
                        messages=messages,
                    )

                    if response.stop_reason == "end_turn":
                        text = next(
                            (b.text for b in response.content if b.type == "text"),
                            "",
                        )
                        if text:
                            print(f"\nCoach: {text}\n")
                        messages.append(
                            {"role": "assistant", "content": response.content}
                        )
                        break

                    elif response.stop_reason == "tool_use":
                        messages.append(
                            {"role": "assistant", "content": response.content}
                        )
                        tool_results = []

                        for block in response.content:
                            if block.type == "tool_use":
                                print(f"  [{block.name}...]", flush=True)
                                try:
                                    result = await mcp_session.call_tool(
                                        block.name, block.input
                                    )
                                    content = (
                                        result.content[0].text
                                        if result.content
                                        else "{}"
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
                        # Unexpected stop reason — surface it and exit inner loop
                        messages.append(
                            {"role": "assistant", "content": response.content}
                        )
                        break
