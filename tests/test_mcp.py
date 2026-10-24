import json
import subprocess
import sys

def test_mcp_initialize_and_tools():
    proc = subprocess.Popen(
        [sys.executable, "-m", "injester.cli", "mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    try:
        # Send initialize
        init_msg = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0"}
            }
        }
        proc.stdin.write(json.dumps(init_msg) + "\n")
        proc.stdin.flush()

        resp_line = proc.stdout.readline()
        assert resp_line, "Expected JSON-RPC response from MCP stdio"
        resp = json.loads(resp_line)
        assert resp["id"] == 1
        assert "serverInfo" in resp["result"]
        assert resp["result"]["serverInfo"]["name"] == "injester"

        # Initialized notification
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}) + "\n")
        proc.stdin.flush()

        # Tools list
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}) + "\n")
        proc.stdin.flush()

        tools_line = proc.stdout.readline()
        tools_resp = json.loads(tools_line)
        assert tools_resp["id"] == 2
        tool_names = [t["name"] for t in tools_resp["result"]["tools"]]
        assert "list_documents" in tool_names
        assert "ingest_document" in tool_names
        assert "search_evidence" in tool_names
        assert "generate_digest" in tool_names
        assert "generate_diagram" in tool_names

    finally:
        proc.terminate()
        proc.wait(timeout=5)
