"""
Beelzebuth — Visual Document Intelligence & Transformation Engine.
Make documents editable through their meaning and structure, rather than only through their pages.
"""

import sys
import time
import threading
import webbrowser
from pathlib import Path
from typing import Optional, List

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from injester.config import settings
from injester.application.manager import manager
from injester.application.documents import DocumentService
from injester.application.retrieval import RetrievalService
from injester.application.digest import DigestService
from injester.application.process_graph import ProcessGraphService

console = Console()
err_console = Console(stderr=True)

app = typer.Typer(
    name="injester",
    help="Beelzebuth: Visual Document Intelligence & Transformation Engine.",
    add_completion=False,
    no_args_is_help=True,
)

documents_app = typer.Typer(help="Manage local documents.", no_args_is_help=True)
app.add_typer(documents_app, name="documents")

digest_app = typer.Typer(help="Devour information and synthesize readable Markdown (.md).", no_args_is_help=True)
app.add_typer(digest_app, name="digest")
app.add_typer(digest_app, name="md")

diagram_app = typer.Typer(help="Depict devoured documents in diagrams (flowcharts, swimlanes, BPMN).", no_args_is_help=True)
app.add_typer(diagram_app, name="diagram")
app.add_typer(diagram_app, name="graph")


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    web_flag: bool = typer.Option(False, "--web", help="Convenience alias to start the web application."),
):
    """Beelzebuth Engine (Injester Community)."""
    if web_flag:
        web_cmd()
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        console.print(Panel(
            "[bold cyan]Beelzebuth Engine (Injester Community)[/bold cyan]\n"
            "[dim]Devour any information into a readable .md file and depict them in diagrams.[/dim]\n\n"
            "• [bold]Devour[/bold]: Run [cyan]injester ingest <file>[/cyan] to ingest and index any file format\n"
            "• [bold]Synthesize[/bold]: Run [cyan]injester digest generate[/cyan] or [cyan]injester md generate[/cyan] for readable Markdown\n"
            "• [bold]Depict[/bold]: Run [cyan]injester diagram generate[/cyan] or [cyan]injester graph generate[/cyan] for diagrams\n"
            "• [bold]Web[/bold]: Run [cyan]injester web[/cyan] to launch the local visual workbench\n"
            "• [bold]MCP[/bold]: Run [cyan]injester mcp[/cyan] to expose tools over stdio to AI clients\n\n"
            "Run [bold green]injester --help[/bold green] to see all available commands.",
            title="[bold yellow]Beelzebuth Engine[/bold yellow]",
            border_style="cyan"
        ))


@app.command("init")
def init_cmd(
    workspace: Optional[Path] = typer.Option(None, "--workspace", "-w", help="Custom workspace directory."),
):
    """Create the local workspace and initialise the SQLite database."""
    if workspace:
        settings.set_workspace(workspace)

    console.print(f"[cyan]Initialising Beelzebuth workspace at:[/cyan] [bold]{settings.WORKSPACE_DIR}[/bold]")
    manager.ensure_initialized()
    console.print(Panel(
        f"[bold green]Workspace initialised successfully![/bold green]\n\n"
        f"• Workspace Directory: [cyan]{settings.WORKSPACE_DIR}[/cyan]\n"
        f"• SQLite Database: [yellow]{settings.WORKSPACE_DIR / 'injester.db'}[/yellow]\n"
        f"• Storage & Vectors: [magenta]{settings.STORAGE_DIR}[/magenta]",
        title="Beelzebuth Init",
        border_style="green",
    ))


@app.command("doctor")
def doctor_cmd():
    """Diagnose configuration, dependencies, and workspace problems."""
    console.print("[bold cyan]Running Beelzebuth diagnostics...[/bold cyan]\n")

    table = Table(title="System & Workspace Diagnostics")
    table.add_column("Component", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Details")

    # 1. Workspace
    ws_exists = settings.WORKSPACE_DIR.exists()
    table.add_row(
        "Workspace Directory",
        "[green]PASS[/green]" if ws_exists else "[yellow]UNINITIALISED[/yellow]",
        str(settings.WORKSPACE_DIR),
    )

    # 2. Database
    db_file = settings.WORKSPACE_DIR / "injester.db"
    db_exists = db_file.exists()
    table.add_row(
        "SQLite Database",
        "[green]PASS[/green]" if db_exists else "[yellow]NOT FOUND (run 'injester init')[/yellow]",
        str(db_file),
    )

    # 3. Storage Directory
    st_exists = settings.STORAGE_DIR.exists()
    table.add_row(
        "Storage & Vectorstore",
        "[green]PASS[/green]" if st_exists else "[yellow]NOT FOUND[/yellow]",
        str(settings.STORAGE_DIR),
    )

    # 4. Extraction Engine
    table.add_row(
        "Extraction Engine",
        "[green]READY[/green]",
        f"Primary: {settings.EXTRACTOR_BACKEND.title()} (TableFormer) | Fallback: Unstructured",
    )

    # 5. Embedding Model
    table.add_row(
        "Embedding Model",
        "[green]CONFIGURED[/green]",
        settings.EMBEDDING_MODEL,
    )

    # 5. LLM Provider
    llm_info = f"Model: {settings.MODEL_NAME} | Base URL: {settings.OPENAI_BASE_URL}"
    table.add_row(
        "LLM Provider (BYOAI)",
        "[green]OK[/green]" if settings.OPENAI_BASE_URL else "[yellow]NOT CONFIGURED[/yellow]",
        llm_info,
    )

    # 6. System-1 Verifier
    table.add_row(
        "System-1 Verifier",
        "[green]OK[/green]",
        f"Provider: {settings.SYSTEM1_PROVIDER}",
    )

    # 7. Frontend Build
    frontend_dist = settings.BASE_DIR / "frontend" / "dist"
    fe_ok = (frontend_dist / "index.html").exists()
    table.add_row(
        "Frontend Assets",
        "[green]BUILT[/green]" if fe_ok else "[red]NOT BUILT (run 'bun run build' in frontend/)[/red]",
        str(frontend_dist),
    )

    console.print(table)


@app.command("config")
def config_cmd(
    show: bool = typer.Option(True, "--show", help="Show current configuration."),
    set_model: Optional[str] = typer.Option(None, "--set-model", help="Set active model name."),
    set_base_url: Optional[str] = typer.Option(None, "--set-base-url", help="Set LLM Base URL."),
    set_api_key: Optional[str] = typer.Option(None, "--set-api-key", help="Set LLM API Key."),
    set_system1_provider: Optional[str] = typer.Option(
        None, "--set-system1-provider", help="Set System-1 verifier provider (laya, openjev, jev, openai)."
    ),
    set_system1_api_mode: Optional[str] = typer.Option(
        None, "--set-system1-api-mode", help="Set System-1 API mode (typesafe, openai_compatible)."
    ),
    set_system1_base_url: Optional[str] = typer.Option(
        None, "--set-system1-base-url", help="Set System-1 verifier API base URL."
    ),
    set_system1_api_key: Optional[str] = typer.Option(
        None, "--set-system1-api-key", help="Set System-1 verifier API key."
    ),
    set_system1_model: Optional[str] = typer.Option(
        None, "--set-system1-model", help="Set System-1 verifier model."
    ),
):
    """Configure and inspect local provider settings."""
    if set_model or set_base_url or set_api_key:
        if set_model:
            settings.MODEL_NAME = set_model
        if set_base_url:
            settings.OPENAI_BASE_URL = set_base_url
        if set_api_key:
            settings.OPENAI_API_KEY = set_api_key
        console.print("[green]Configuration updated for current runtime.[/green]")

    if any(
        value is not None
        for value in (
            set_system1_provider,
            set_system1_api_mode,
            set_system1_base_url,
            set_system1_api_key,
            set_system1_model,
        )
    ):
        settings.update_system1_settings(
            provider=set_system1_provider,
            api_mode=set_system1_api_mode,
            base_url=set_system1_base_url,
            api_key=set_system1_api_key,
            model=set_system1_model,
        )
        console.print("[green]System-1 grounding verifier updated for current runtime.[/green]")

    system1 = settings.system1_effective_config()

    table = Table(title="Active Beelzebuth Configuration")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="yellow")

    table.add_row("Workspace Dir", str(settings.WORKSPACE_DIR))
    table.add_row("Database URL", settings.DATABASE_URL)
    table.add_row("Storage Dir", str(settings.STORAGE_DIR))
    table.add_row("Active Model", settings.MODEL_NAME)
    table.add_row("OpenAI Base URL", settings.OPENAI_BASE_URL)
    table.add_row("API Key Configured", "Yes" if bool(settings.OPENAI_API_KEY) else "No")
    table.add_row("System-1 Provider", system1["provider"])
    table.add_row("System-1 API Mode", system1["api_mode"])
    table.add_row("System-1 Base URL", system1["base_url"] or "(default)")
    table.add_row("System-1 API Key", "Yes" if bool(system1["api_key"]) else "No")
    table.add_row("System-1 Model", system1["model"] or "(default)")
    table.add_row("Extraction Backend", f"{settings.EXTRACTOR_BACKEND} (Docling primary, Unstructured fallback)")
    table.add_row("Embedding Model", settings.EMBEDDING_MODEL)

    console.print(table)


@app.command("ingest")
def ingest_cmd(
    path: Path = typer.Argument(..., help="Path to document file (.pdf, .docx, .txt, .md, .pptx)."),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Optional output path to write digitized Markdown (.md)."),
    backend: str = typer.Option("auto", "--backend", "-b", help="Extraction backend ('auto', 'docling', 'unstructured')."),
):
    """Ingest and devour a document directly into the local workspace."""
    manager.ensure_initialized()
    if not path.exists():
        console.print(f"[bold red]Error:[/bold red] File not found: {path}")
        raise typer.Exit(code=1)

    console.print(f"[cyan]Devouring & indexing [bold]{path.name}[/bold] using backend '{backend}'...[/cyan]")
    try:
        service = DocumentService()
        result = service.ingest(path, backend=backend)

        md_saved_msg = ""
        if output:
            from injester.application.digitizer import reconstruct_digital_markdown
            from injester.ingestion.extractor import DocumentExtractor
            from injester.ingestion.chunker import HierarchicalChunker
            from injester.semantic.pipeline import GranularSpanRegistry
            doc_ext = DocumentExtractor()
            elements = doc_ext.extract(path, document_id=result.doc_id, filename=path.name, file_version_id="v1", backend=backend)
            chunks = HierarchicalChunker().chunk_elements(elements)
            reg = GranularSpanRegistry.from_chunks(chunks)
            annotated_md, _, _ = reconstruct_digital_markdown(elements, reg, document_title=path.stem)
            target_out = output.resolve()
            target_out.write_text(annotated_md, encoding="utf-8")
            md_saved_msg = f"\n• Digitized Markdown: [bold yellow]{target_out}[/bold yellow]"

        console.print(Panel(
            f"[bold green]Document Ingested and Indexed Successfully![/bold green]\n\n"
            f"• Document ID: [cyan]{result.doc_id}[/cyan]\n"
            f"• Name: [yellow]{result.name}[/yellow]\n"
            f"• Format: {result.format}\n"
            f"• Version: v{result.version}\n"
            f"• Chunks Indexed: [bold]{result.chunk_count}[/bold]\n"
            f"• File Size: {result.file_size} bytes{md_saved_msg}",
            title="Ingestion Complete",
            border_style="green",
        ))
    except Exception as e:
        console.print(f"[bold red]Ingestion failed:[/bold red] {e}")
        raise typer.Exit(code=1)


@documents_app.command("list")
def documents_list_cmd():
    """List locally stored documents."""
    manager.ensure_initialized()
    service = DocumentService()
    docs = service.list_documents()

    if not docs:
        console.print("[yellow]No documents found in local workspace. Use 'injester ingest <file>' to add one.[/yellow]")
        return

    table = Table(title="Locally Stored Documents")
    table.add_column("Document ID", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Versions", style="yellow")
    table.add_column("Indexed Chunks", style="magenta")
    table.add_column("Created At", style="dim")

    for d in docs:
        table.add_row(d.doc_id, d.name, str(d.versions_count), str(d.chunk_count), d.created_at[:19])

    console.print(table)


@app.command("search")
def search_cmd(
    query: str = typer.Argument(..., help="Search query or question."),
    top_k: int = typer.Option(5, "--top-k", "-k", help="Number of evidence chunks to retrieve."),
):
    """Search indexed evidence across all local documents."""
    manager.ensure_initialized()
    service = RetrievalService()
    results = service.search(query=query, top_k=top_k)

    if not results:
        console.print("[yellow]No relevant evidence found for the query.[/yellow]")
        return

    console.print(f"\n[bold cyan]Top {len(results)} evidence results for:[/bold cyan] [italic]'{query}'[/italic]\n")
    for idx, r in enumerate(results, start=1):
        console.print(Panel(
            f"[bold green]Match #{idx}[/bold green] (Relevance Score: [bold]{r.score:.4f}[/bold])\n"
            f"• Document ID: [cyan]{r.document_id}[/cyan]\n"
            f"• Chunk ID: [dim]{r.chunk_id}[/dim]\n"
            f"• Section: {r.section or 'N/A'} | Page: {r.location or 'N/A'}\n\n"
            f"[italic]{r.text}[/italic]",
            border_style="blue",
        ))


@digest_app.command("generate")
def digest_generate_cmd(
    topic: Optional[str] = typer.Option(None, "--topic", "-t", help="Topic or objective of the synthesized Markdown document."),
    file: Optional[Path] = typer.Option(None, "--file", "-f", help="Source document file to devour directly into Markdown (.md)."),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output Markdown file path (.md)."),
    doc_id: Optional[List[str]] = typer.Option(None, "--doc-id", "-d", help="Specific document ID(s) to constrain synthesis."),
    backend: str = typer.Option("auto", "--backend", "-b", help="Extraction backend ('auto', 'docling', 'unstructured')."),
):
    """Devour information and synthesize a readable, citation-audited Markdown document (.md)."""
    manager.ensure_initialized()

    if file:
        if not file.exists():
            console.print(f"[bold red]Error:[/bold red] File not found: {file}")
            raise typer.Exit(code=1)
        console.print(f"[cyan]Devouring [bold]{file.name}[/bold] into high-fidelity Markdown using backend '{backend}'...[/cyan]")
        try:
            from injester.application.digitizer import reconstruct_digital_markdown
            from injester.ingestion.extractor import DocumentExtractor
            from injester.ingestion.chunker import HierarchicalChunker
            from injester.semantic.pipeline import GranularSpanRegistry
            doc_ext = DocumentExtractor()
            elements = doc_ext.extract(file, document_id=file.stem, filename=file.name, file_version_id="v1", backend=backend)
            chunks = HierarchicalChunker().chunk_elements(elements)
            reg = GranularSpanRegistry.from_chunks(chunks)
            annotated_md, _, _ = reconstruct_digital_markdown(elements, reg, document_title=file.stem)

            target_out = output.resolve() if output else (Path.cwd() / f"{file.stem}.md")
            target_out.write_text(annotated_md, encoding="utf-8")
            console.print(Panel(
                f"[bold green]Document Devoured into Markdown Successfully![/bold green]\n\n"
                f"• Source File: [cyan]{file.name}[/cyan]\n"
                f"• Output Markdown: [bold yellow]{target_out}[/bold yellow]\n"
                f"• Extracted Elements: {len(elements)}\n"
                f"• Granular Spans: {len(reg.spans_by_id)}\n"
                f"• Format: Preserved Headings, Tables, Diagrams & Inline Citations",
                title="Digitization Complete",
                border_style="green",
            ))
            return
        except Exception as e:
            console.print(f"[bold red]Digitization failed:[/bold red] {e}")
            raise typer.Exit(code=1)

    if not topic:
        console.print("[bold red]Error:[/bold red] Must provide either --file <path> or --topic <objective>.")
        raise typer.Exit(code=1)

    console.print(f"[cyan]Devouring information into readable Markdown for topic:[/cyan] [bold]'{topic}'[/bold]...")

    try:
        service = DigestService()
        result = service.generate(topic=topic, file_ids=doc_id)

        target_out = output.resolve() if output else (Path.cwd() / "digest.md")
        target_out.write_text(result.markdown, encoding="utf-8")
        console.print(f"[green]Markdown written to:[/green] [bold]{target_out}[/bold]")

        status_style = "bold green" if result.is_valid else "bold red"
        console.print(Panel(
            f"[{status_style}]Markdown Document Generated & Verified![/{status_style}]\n\n"
            f"• Objective: [bold]{result.topic}[/bold]\n"
            f"• Output File: [cyan]{target_out}[/cyan]\n"
            f"• Verified Citations: [yellow]{result.verified_citations_count}[/yellow]\n"
            f"• Validation Errors: [red]{len(result.errors)}[/red]\n"
            f"• Validation Warnings: [yellow]{len(result.warnings)}[/yellow]",
            title="Document Synthesis Status",
            border_style="green" if result.is_valid else "red",
        ))
    except Exception as e:
        console.print(f"[bold red]Markdown generation failed:[/bold red] {e}")
        raise typer.Exit(code=1)


@diagram_app.command("generate")
def diagram_generate_cmd(
    file: Optional[Path] = typer.Option(None, "--file", "-f", help="Direct source file path."),
    doc_id: Optional[str] = typer.Option(None, "--doc-id", "-d", help="Existing local document ID."),
    output_dir: Path = typer.Option(Path("./output_diagrams"), "--output-dir", "-o", help="Directory for diagrams and artifacts."),
):
    """Depict devoured documents in diagrams (BPMN 2.0 XML, Mermaid flowcharts, swimlanes)."""
    manager.ensure_initialized()
    if not file and not doc_id:
        console.print("[bold red]Error:[/bold red] Must specify either --file <path> or --doc-id <id>")
        raise typer.Exit(code=1)

    target_input = file or doc_id
    console.print(f"[cyan]Depicting diagrams for:[/cyan] [bold]{target_input}[/bold]...")

    try:
        service = ProcessGraphService()
        result = service.generate(file_path_or_id=target_input, output_dir=output_dir)

        out_dir = Path(result.output_dir or output_dir).resolve()
        console.print(Panel(
            f"[bold green]Diagrams Generated Successfully![/bold green]\n\n"
            f"• Process / Workflow Name: [bold]{result.process_name}[/bold]\n"
            f"• Objective: [italic]{result.objective}[/italic]\n\n"
            f"[bold]Grounding & Verification Metrics:[/bold]\n"
            f"  • Verified Activities: [green]{result.activities_count}[/green]\n"
            f"  • Decision Gateways: [cyan]{result.gateways_count}[/cyan]\n"
            f"  • Transitions: [blue]{result.transitions_count}[/blue]\n"
            f"  • Roles / Lanes: [magenta]{result.actors_count}[/magenta]\n"
            f"  • Quarantined Defects: [yellow]{result.defects_count}[/yellow]\n\n"
            f"[bold]Diagram Artifacts written to [cyan]{out_dir}[/cyan]:[/bold]\n"
            f"  • BPMN 2.0 XML: [cyan]{out_dir / 'bpmn_2_0.xml'}[/cyan]\n"
            f"  • Mermaid Flowchart: [blue]{out_dir / 'flowchart.mmd'}[/blue]\n"
            f"  • Mermaid Swimlane: [magenta]{out_dir / 'swimlane.mmd'}[/magenta]\n"
            f"  • Defect Register: [yellow]{out_dir / 'DEFECT_REGISTER.md'}[/yellow]\n\n"
            f"Latency: [bold]{result.total_latency_sec}s[/bold]",
            title="Diagram Generation",
            border_style="green",
        ))
    except Exception as e:
        console.print(f"[bold red]Diagram generation failed:[/bold red] {e}")
        raise typer.Exit(code=1)


@app.command("web")
def web_cmd(
    port: int = typer.Option(8000, "--port", "-p", help="Port to bind the server to."),
    host: str = typer.Option("127.0.0.1", "--host", "-H", help="Host address to bind to."),
    no_browser: bool = typer.Option(False, "--no-browser", help="Do not automatically open the browser."),
):
    """Start FastAPI, serve the React frontend at '/', and open the browser."""
    manager.ensure_initialized()
    url = f"http://{host}:{port}"

    console.print(Panel(
        f"[bold green]Starting Beelzebuth Web Workbench[/bold green]\n\n"
        f"• Local URL: [bold cyan]{url}[/bold cyan]\n"
        f"• API Documentation: [cyan]{url}/docs[/cyan]\n"
        f"• Workspace: [yellow]{settings.WORKSPACE_DIR}[/yellow]\n\n"
        f"[dim]Press Ctrl+C to stop the server.[/dim]",
        border_style="green",
    ))

    if not no_browser:
        def _check_and_open():
            import httpx
            for _ in range(40):
                try:
                    r = httpx.get(f"{url}/api/health", timeout=1.0)
                    if r.status_code == 200:
                        webbrowser.open(url)
                        return
                except Exception:
                    time.sleep(0.3)

        threading.Thread(target=_check_and_open, daemon=True).start()

    import uvicorn
    uvicorn.run("injester.api.app:app", host=host, port=port, log_level="info")


@app.command("mcp")
def mcp_cmd():
    """Start the local Model Context Protocol (MCP) server using stdio."""
    from injester.mcp.server import run_stdio_server
    run_stdio_server()


if __name__ == "__main__":
    app()
