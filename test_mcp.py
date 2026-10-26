"""Start the MCP server, list its tools, and call one end to end."""

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent

# Windows consoles cannot print some characters the model returns.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


async def main():
    # Run this venv's Python on our server script; .env is read from cwd.
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "mcp_server.py")],
        cwd=str(ROOT),
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("Tools:", [tool.name for tool in tools.tools])
            for tool in tools.tools:
                print(f"- {tool.name}: {(tool.description or '').splitlines()[0]}")

            print("\nCalling ask_repo_history...")
            result = await session.call_tool(
                "ask_repo_history",
                {"question": "When did I test watch mode?"},
            )
            print("isError:", result.isError)

            for block in result.content:
                text = getattr(block, "text", None)
                if text is None:
                    print(block)
                    continue
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    print(text)
                    continue
                print("\nAnswer:", payload.get("answer"))
                print("Rewritten query:", payload.get("rewritten_query"))
                print("Commits used:")
                for commit in payload.get("commits", []):
                    print(f"  {commit['sha']}  {commit['date']}  {commit['message']}")
                    print(f"    {commit['url']}")


if __name__ == "__main__":
    asyncio.run(main())