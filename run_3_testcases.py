import time
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from injester.infrastructure.db import SessionLocal, init_db
from injester.domain.auth import SecurityContext
from injester.domain.models import UserRole
from injester.pipeline import InjesterPipeline

console = Console()

def run_test_cases():
    init_db()
    session = SessionLocal()
    pipeline = InjesterPipeline(session=session)

    dev_ctx = SecurityContext(user_id="dev_platform", email="admin@injester.platform", role=UserRole.SUPER_ADMIN)

    test_cases = [
        {
            "id": 1,
            "name": "Test Case 1: Easy - Employee Leave Approval",
            "org_name": "Test Org 1 - HR Department",
            "file_path": Path("/home/jefino9488/Downloads/test/SOP_Easy_LeaveApproval.docx"),
            "topic": "Standard Operating Procedure for Employee Leave Request and Manager Approval Workflow",
            "output_file": "sop_testcase_1_leave_approval.md",
        },
        {
            "id": 2,
            "name": "Test Case 2: Medium - Personal Loan Processing",
            "org_name": "Test Org 2 - Retail Lending",
            "file_path": Path("/home/jefino9488/Downloads/test/SOP_Medium_PersonalLoanProcessing.docx"),
            "topic": "Standard Operating Procedure for Personal Loan Application Ingestion, KYC & Credit Verification, and Loan Sanction",
            "output_file": "sop_testcase_2_personal_loan.md",
        },
        {
            "id": 3,
            "name": "Test Case 3: Hard - Commercial Loan Underwriting",
            "org_name": "Test Org 3 - Commercial Banking",
            "file_path": Path("/home/jefino9488/Downloads/test/SOP_Hard_CommercialLoanUnderwriting.docx"),
            "topic": "Standard Operating Procedure for Commercial Loan Underwriting, Multi-Tier Financial Risk Assessment, and Credit Committee Approval",
            "output_file": "sop_testcase_3_commercial_loan.md",
        },
    ]

    results_summary = []

    for tc in test_cases:
        console.print(Panel(f"[bold cyan]Running {tc['name']}[/bold cyan]\nFile: {tc['file_path'].name}"))

        # 1. Create Isolated Tenant
        org = pipeline.repo.create_organisation(dev_ctx, name=f"{tc['org_name']} {int(time.time())}")
        admin_user = pipeline.repo.create_client_admin(
            dev_ctx,
            org_id=org.id,
            email=f"admin_tc{tc['id']}_{int(time.time())}@domain.local",
            password="Password2026!"
        )
        tenant_ctx = SecurityContext(
            user_id=admin_user.id,
            email=admin_user.email,
            role=UserRole.CLIENT_ADMIN,
            organisation_id=org.id
        )

        # 2. Ingest Document
        console.print(f"[yellow]Ingesting {tc['file_path'].name} into tenant '{org.name}'...[/yellow]")
        file_rec, ver_rec, chunks = pipeline.ingest_file(
            sec_ctx=tenant_ctx,
            file_path=tc['file_path'],
            filename=tc['file_path'].name
        )
        console.print(f"[green]✓ Ingested successfully into PostgreSQL and FAISS ({len(chunks)} chunks).[/green]")

        # 3. Generate Grounded SOP via BYOAI LLM
        console.print(f"[yellow]Generating Claim-to-Span Grounded SOP for: '{tc['topic']}'...[/yellow]")
        sop_markdown, val_report = pipeline.generate_sop(
            sec_ctx=tenant_ctx,
            topic_goal=tc['topic']
        )

        # 4. Save SOP file
        out_path = Path(tc['output_file']).resolve()
        out_path.write_text(sop_markdown, encoding="utf-8")
        console.print(f"[green]✓ SOP compiled to: {out_path}[/green]")

        results_summary.append({
            "test_case": tc["name"],
            "source_doc": tc["file_path"].name,
            "chunks": len(chunks),
            "output_file": tc["output_file"],
            "is_valid": val_report.is_valid,
            "chunk_cov": f"{val_report.chunk_coverage_score * 100:.1f}%",
            "rule_cov": f"{val_report.rule_coverage_score * 100:.1f}%",
            "claim_entail": f"{val_report.claim_entailment_score * 100:.1f}%",
            "cit_correct": f"{val_report.citation_correctness_score * 100:.1f}%",
            "unsupported_count": val_report.unsupported_claims_count,
            "unsupported_claims": val_report.unsupported_claims,
            "unrepresented_rules": val_report.unrepresented_rules,
            "citations_count": len(val_report.verified_citation_index),
            "errors": len(val_report.errors),
            "warnings": len(val_report.warnings),
        })

    console.print("\n")
    table = Table(title="Auditable Claim-to-Span SOP Pipeline — Benchmark Results")
    table.add_column("Test Case", style="cyan")
    table.add_column("Source", style="yellow")
    table.add_column("Chunks", style="blue")
    table.add_column("Chunk Cov", style="green")
    table.add_column("Rule Cov", style="green")
    table.add_column("Entailment", style="magenta")
    table.add_column("Cit Correct", style="cyan")
    table.add_column("Unsup Claims", style="red")
    table.add_column("Status", style="bold")

    for r in results_summary:
        status_str = "[bold green]PASSED[/bold green]" if r["is_valid"] else "[bold red]FAILED[/bold red]"
        table.add_row(
            r["test_case"].split(":")[0],
            r["source_doc"],
            str(r["chunks"]),
            r["chunk_cov"],
            r["rule_cov"],
            r["claim_entail"],
            r["cit_correct"],
            str(r["unsupported_count"]),
            status_str,
        )

    console.print(table)

    for r in results_summary:
        if r["errors"]:
            console.print(f"[red]Errors in {r['test_case']}:[/red] {r['errors']}")
        if r["unsupported_claims"]:
            console.print(f"[yellow]Unsupported Claims in {r['test_case']}:[/yellow] {r['unsupported_claims']}")
        if r["unrepresented_rules"]:
            console.print(f"[yellow]Unrepresented Rules in {r['test_case']}:[/yellow] {r['unrepresented_rules']}")

    pipeline.close()

if __name__ == "__main__":
    run_test_cases()
