import asyncio
import json
import sys
from pathlib import Path

from anthropic import AsyncAnthropic
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

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

Keep responses focused and actionable. Ask clarifying questions if goals are vague.

Output format:
- Output will be consumed by a Telegram bot, so do not use any formatting that won't render in Telegram messages (e.g. no markdown, HTML, or special characters).

"""

# Cache the system prompt — it's large and constant across the whole session
CACHED_SYSTEM = [
    {
        "type": "text",
        "text": SYSTEM_PROMPT,
        "cache_control": {"type": "ephemeral"},
    }
]


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
