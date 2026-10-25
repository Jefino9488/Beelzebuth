"""
MCP Client Protocol-Level Integration Test Suite.

Validates the Beelzebuth / Injester MCP Server over real JSON-RPC stdio transport:
- Real ClientSession connection using mcp.client.stdio.
- Protocol handshake and tool discovery (schema validation, parameter definitions).
- End-to-end 3-stage document editing workflow over the wire.
- Enforcement of human authorization boundaries over MCP JSON-RPC.
- Enforcement of filesystem containment over MCP JSON-RPC.
"""

import sys
import os
import json
import asyncio
import pytest

from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession
from injester.config import settings


def test_mcp_protocol_client_initialization_and_tool_discovery():
    """Validates real stdio client handshake, tool schema declarations, and capability advertisements."""
    async def _run():
        server_params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "injester.mcp"],
            env={**os.environ, "ALLOW_UNATTENDED_MCP_APPROVAL": "false"},
        )

        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                # 1. Protocol initialization
                init_res = await session.initialize()
                assert init_res.server_info.name == "injester"

                # 2. Tool discovery and schema inspection
                tools_result = await session.list_tools()
                tools_map = {t.name: t for t in tools_result.tools}

                # Check that all 3 stages of editing tools are registered
                expected_tools = [
                    "list_documents",
                    "inspect_document",
                    "get_document_structure",
                    "find_blocks",
                    "get_block_content",
                    "propose_text_edit",
                    "propose_section_reorder",
                    "propose_block_move",
                    "get_changeset",
                    "preview_changeset",
                    "approve_changeset",
                    "apply_changeset",
                    "verify_document",
                    "get_change_report",
                ]
                for t_name in expected_tools:
                    assert t_name in tools_map, f"Missing expected tool: '{t_name}'"
                    # Validate input schema
                    schema = tools_map[t_name].input_schema
                    assert schema.get("type") == "object"
                    assert "properties" in schema

    asyncio.run(_run())


def test_mcp_protocol_full_editing_workflow():
    """Tests the full 3-stage editing lifecycle over stdio JSON-RPC transport with human token approval."""
    async def _run():
        server_params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "injester.mcp"],
            env={**os.environ, "ALLOW_UNATTENDED_MCP_APPROVAL": "false", "APPROVAL_MODE": "manual"},
        )

        doc_path = "sample_docs/Workstation_Deployment_Guide.docx"
        out_dir = settings.STORAGE_DIR / "recompiled"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_docx = str(out_dir / "mcp_protocol_workflow_output.docx")

        try:
            async with stdio_client(server_params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    # Stage 1: Inspect Document
                    inspect_res = await session.call_tool("inspect_document", {"document_id_or_path": doc_path})
                    assert len(inspect_res.content) >= 1
                    inspect_data = json.loads(inspect_res.content[0].text)
                    assert inspect_data["document_type"] == "MANUAL"
                    assert inspect_data["step_count"] == 6

                    # Find target block
                    find_res = await session.call_tool("find_blocks", {"document_id_or_path": doc_path, "query": "DisplayPort"})
                    find_blocks_list = [json.loads(c.text) for c in find_res.content]
                    assert len(find_blocks_list) >= 1
                    target_bid = find_blocks_list[0]["block_id"]

                    # Stage 2: Propose Edit
                    new_text = "Step 1: Connect verified 4K DisplayPort workstation monitor."
                    prop_res = await session.call_tool("propose_text_edit", {
                        "document_id_or_path": doc_path,
                        "block_id": target_bid,
                        "new_text": new_text,
                        "rationale": "Stdio protocol verification",
                    })
                    prop_data = json.loads(prop_res.content[0].text)
                    cs_id = prop_data["changeset_id"]
                    assert prop_data["status"] == "PROPOSED"

                    # Preview and obtain human approval token
                    prev_res = await session.call_tool("preview_changeset", {"changeset_id": cs_id})
                    prev_data = json.loads(prev_res.content[0].text)
                    assert prev_data["is_valid"] is True
                    assert prev_data["diff_summary"]["after"] == new_text
                    token = prev_data["approval_token"]
                    assert token is not None

                    # Stage 3: Approve with Human Token
                    appr_res = await session.call_tool("approve_changeset", {
                        "changeset_id": cs_id,
                        "rationale": "Human reviewer approved via MCP client",
                        "approval_token": token,
                    })
                    appr_data = json.loads(appr_res.content[0].text)
                    assert appr_data["status"] == "APPROVED"
                    assert len(appr_data["approval_signature"]) == 64

                    # Apply ChangeSet
                    apply_res = await session.call_tool("apply_changeset", {
                        "changeset_id": cs_id,
                        "output_path": out_docx,
                    })
                    apply_data = json.loads(apply_res.content[0].text)
                    assert apply_data["is_successful"] is True
                    assert apply_data["unmodified_blocks_intact"] is True
                    assert os.path.exists(out_docx)

                    # Verify Document over protocol
                    ver_res = await session.call_tool("verify_document", {
                        "source_path": doc_path,
                        "recompiled_path": out_docx,
                        "changeset_id": cs_id,
                    })
                    ver_data = json.loads(ver_res.content[0].text)
                    assert ver_data["is_verified"] is True
                    assert ver_data["operation_correctness"] is True
                    assert ver_data["content_preservation"] is True
                    assert ver_data["formatting_preservation"] is True

                    # Retrieve Report over protocol
                    report_res = await session.call_tool("get_change_report", {"changeset_id": cs_id})
                    report_data = json.loads(report_res.content[0].text)
                    assert report_data["changeset_id"] == cs_id
                    assert report_data["is_successful"] is True
        finally:
            if os.path.exists(out_docx):
                os.remove(out_docx)

    asyncio.run(_run())


def test_mcp_protocol_unauthorized_approval_rejected():
    """Security Boundary: Self-approval attempt without token over stdio protocol returns error/rejection."""
    async def _run():
        server_params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "injester.mcp"],
            env={**os.environ, "ALLOW_UNATTENDED_MCP_APPROVAL": "false", "APPROVAL_MODE": "manual"},
        )

        doc_path = "sample_docs/Workstation_Deployment_Guide.docx"
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                prop_res = await session.call_tool("propose_text_edit", {
                    "document_id_or_path": doc_path,
                    "block_id": "block-003",
                    "new_text": "Unattended exploit test",
                })
                prop_data = json.loads(prop_res.content[0].text)
                cs_id = prop_data["changeset_id"]

                # Attempt self-approval without token
                appr_res = await session.call_tool("approve_changeset", {
                    "changeset_id": cs_id,
                    "rationale": "I am self-approving",
                })
                # When tool raises AccessDeniedError, MCP server returns tool error
                assert appr_res.is_error is True or "error" in appr_res.content[0].text.lower()

    asyncio.run(_run())


def test_mcp_protocol_filesystem_boundary_rejection():
    """Security Boundary: Accessing files outside authorized roots over stdio protocol returns error."""
    async def _run():
        server_params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "injester.mcp"],
            env={**os.environ, "ALLOW_ARBITRARY_FILESYSTEM_ACCESS": "false"},
        )

        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                # Attempt to inspect /etc/passwd over MCP protocol
                res = await session.call_tool("inspect_document", {"document_id_or_path": "/etc/passwd"})
                assert res.is_error is True or "violation" in res.content[0].text.lower()

    asyncio.run(_run())
