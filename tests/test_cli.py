import tempfile
from pathlib import Path
from typer.testing import CliRunner
from injester.cli import app
from injester.config import settings

runner = CliRunner()

def test_cli_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Beelzebuth" in result.output or "injester" in result.output
    assert "init" in result.output
    assert "web" in result.output
    assert "mcp" in result.output
    assert "ingest" in result.output
    assert "documents" in result.output
    assert "search" in result.output
    assert "doctor" in result.output
    assert "digest" in result.output
    assert "diagram" in result.output
    assert "sop" not in result.output.lower()

def test_cli_doctor():
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "Workspace Directory" in result.output
    assert "SQLite Database" in result.output

def test_cli_init_custom_workspace(tmp_path):
    ws = tmp_path / "custom_ws"
    result = runner.invoke(app, ["init", "--workspace", str(ws)])
    assert result.exit_code == 0
    assert (ws / "injester.db").exists()

def test_cli_config():
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 0
    assert "Workspace Dir" in result.output
