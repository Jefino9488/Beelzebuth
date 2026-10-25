"""CLI entrypoint for running the Injester & Beelzebuth MCP Server via python -m injester.mcp."""
from injester.mcp.server import run_stdio_server

if __name__ == "__main__":
    run_stdio_server()
