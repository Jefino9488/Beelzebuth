import argparse
import sys
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from injester.infrastructure.db import SessionLocal, init_db, TenantRepository
from injester.domain.models import User, UserRole, Organisation
from injester.domain.auth import SecurityContext, verify_password, AccessDeniedError
from injester.pipeline import InjesterPipeline

console = Console()

def authenticate(session, email: str, password: str) -> SecurityContext:
    user = session.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.hashed_password):
        raise AccessDeniedError("Invalid email or password.")
    return SecurityContext(
        user_id=user.id,
        email=user.email,
        role=user.role,
        organisation_id=user.organisation_id,
    )

def main():
    parser = argparse.ArgumentParser(description="Injester: Multi-Tenant Ingestion & SOP Generator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # init-db
    subparsers.add_parser("init-db", help="Initialize PostgreSQL schema and bootstrap platform Super Admin")

    # onboard-org (Super Admin)
    p_org = subparsers.add_parser("onboard-org", help="Onboard a new Client Organisation (Super Admin only)")
    p_org.add_argument("--admin-email", required=True, help="Platform Super Admin email")
    p_org.add_argument("--admin-password", required=True, help="Platform Super Admin password")
    p_org.add_argument("--name", required=True, help="Name of client organisation, e.g. 'Indian Bank'")

    # add-client-admin
    p_ca = subparsers.add_parser("add-client-admin", help="Assign a Client Admin to an organisation")
    p_ca.add_argument("--admin-email", required=True, help="Super Admin or Client Admin email")
    p_ca.add_argument("--admin-password", required=True, help="Admin password")
    p_ca.add_argument("--org-id", required=True, help="Organisation UUID")
    p_ca.add_argument("--email", required=True, help="New Client Admin email")
    p_ca.add_argument("--password", required=True, help="New Client Admin password")

    # add-employee
    p_emp = subparsers.add_parser("add-employee", help="Add an employee to an organisation (Client Admin only)")
    p_emp.add_argument("--admin-email", required=True, help="Client Admin email")
    p_emp.add_argument("--admin-password", required=True, help="Client Admin password")
    p_emp.add_argument("--org-id", required=True, help="Organisation UUID")
    p_emp.add_argument("--email", required=True, help="New Employee email")
    p_emp.add_argument("--password", required=True, help="New Employee password")

    # upload-file
    p_up = subparsers.add_parser("upload", help="Ingest a file into tenant storage and FAISS vector index")
    p_up.add_argument("--email", required=True, help="User email")
    p_up.add_argument("--password", required=True, help="User password")
    p_up.add_argument("--file", required=True, help="Path to document file (PDF, DOCX, PPTX, XLSX, TXT, MD)")

    # list-files
    p_list = subparsers.add_parser("list-files", help="List accessible files with tenant-level isolation")
    p_list.add_argument("--email", required=True, help="User email")
    p_list.add_argument("--password", required=True, help="User password")

    # generate-sop
    p_sop = subparsers.add_parser("generate-sop", help="Generate an auditable, citation-grounded SOP")
    p_sop.add_argument("--email", required=True, help="User email")
    p_sop.add_argument("--password", required=True, help="User password")
    p_sop.add_argument("--topic", required=True, help="Topic/goal of the SOP")
    p_sop.add_argument("--output", default="generated_sop.md", help="Output Markdown file path")

    args = parser.parse_args()

    if args.command == "init-db":
        init_db()
        console.print("[bold green]PostgreSQL database initialized successfully and Super Admin bootstrapped![/bold green]")
        return

    session = SessionLocal()
    pipeline = InjesterPipeline(session=session)

    try:
        if args.command == "onboard-org":
            sec_ctx = authenticate(session, args.admin_email, args.admin_password)
            org = pipeline.repo.create_organisation(sec_ctx, args.name)
            console.print(Panel(f"[bold green]Organisation Onboarded Successfully[/bold green]\nID: [cyan]{org.id}[/cyan]\nName: [yellow]{org.name}[/yellow]\nStatus: {org.status.value}"))

        elif args.command == "add-client-admin":
            sec_ctx = authenticate(session, args.admin_email, args.admin_password)
            user = pipeline.repo.create_client_admin(sec_ctx, args.org_id, args.email, args.password)
            console.print(f"[bold green]Client Admin assigned successfully:[/bold green] {user.email} (Org: {user.organisation_id})")

        elif args.command == "add-employee":
            sec_ctx = authenticate(session, args.admin_email, args.admin_password)
            user = pipeline.repo.create_employee(sec_ctx, args.org_id, args.email, args.password)
            console.print(f"[bold green]Employee created successfully:[/bold green] {user.email} (Org: {user.organisation_id})")

        elif args.command == "upload":
            sec_ctx = authenticate(session, args.email, args.password)
            file_rec, ver_rec, chunks = pipeline.ingest_file(sec_ctx, args.file)
            console.print(Panel(
                f"[bold green]File Ingested and Indexed Successfully![/bold green]\n"
                f"File: [cyan]{file_rec.name}[/cyan] (ID: {file_rec.id})\n"
                f"Version: [yellow]v{ver_rec.version_number}[/yellow] ({ver_rec.file_size} bytes)\n"
                f"Tenant: [magenta]{file_rec.organisation_id}[/magenta]\n"
                f"Chunks Indexed: [bold]{len(chunks)}[/bold]"
            ))

        elif args.command == "list-files":
            sec_ctx = authenticate(session, args.email, args.password)
            files = pipeline.repo.list_files(sec_ctx)
            table = Table(title=f"Files Accessible to {sec_ctx.email} ({sec_ctx.role.value})")
            table.add_column("File ID", style="cyan")
            table.add_column("Name", style="green")
            table.add_column("Versions", style="yellow")
            table.add_column("Created By", style="magenta")
            table.add_column("Tenant ID", style="blue")
            for f in files:
                table.add_row(f.id, f.name, str(len(f.versions)), f.created_by_user_id or "Platform", f.organisation_id)
            console.print(table)

        elif args.command == "generate-sop":
            sec_ctx = authenticate(session, args.email, args.password)
            console.print(f"[bold cyan]Generating grounded SOP for topic: '{args.topic}'...[/bold cyan]")
            sop_md, val_report = pipeline.generate_sop(sec_ctx, args.topic)

            out_path = Path(args.output).resolve()
            out_path.write_text(sop_md, encoding="utf-8")

            status_style = "bold green" if val_report.is_valid else "bold red"
            console.print(Panel(
                f"[{status_style}]SOP Generated & Verified![/{status_style}]\n"
                f"Output: [cyan]{out_path}[/cyan]\n"
                f"Verified Citations: [yellow]{len(val_report.verified_citation_index)}[/yellow]\n"
                f"Validation Errors: [red]{len(val_report.errors)}[/red]\n"
                f"Validation Warnings: [yellow]{len(val_report.warnings)}[/yellow]"
            ))

    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        sys.exit(1)
    finally:
        pipeline.close()

if __name__ == "__main__":
    main()
