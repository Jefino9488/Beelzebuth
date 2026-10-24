"""
Injester Platform API Application.
Enterprise Multi-Tenant Ingestion, Evidence-First Process Graph & Citation-Grounded Document Engine.
"""

from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import text

from injester.config import settings
from injester.infrastructure.db import init_db
from injester.api.deps import get_db
from injester.api.routers import auth, admin, tenant, files, process_graph, jobs, beelzebuth, settings_api, console

API_DESCRIPTION = """
## Injester & Beelzebuth Community Engine API

Injester is a unified engine designed for strict factual fidelity and zero-hallucination workflow extraction:
1. **Unified Storage**: Local SQLite metadata + local FAISS vector indexing with advisory locking.
2. **Evidence-First Semantic Pipeline**: Normalizes raw inputs into immutable `[S###]` evidence spans, extracts fine-grained atomic propositions, and validates claims with System-1 NLI.
3. **Deterministic Dual-Output Contract**: Only propositions passing semantic verification enter the authoritative **Process Graph AST**. Unverified or ambiguous claims are quarantined into the **Ambiguity & Defect Register**.
4. **Multi-Format Diagram Projections**: Verified documents and graphs automatically project into BPMN 2.0 XML, Mermaid Flowcharts, Swimlanes, and State Machine diagrams.
5. **Traceable Document Digest**: Citation-grounded readable Markdown documents (.md) synthesized with typed validation badges.
"""

TAGS_METADATA = [
    {
        "name": "Beelzebuth Universal Engine",
        "description": "Universal document digestion, System-1 claim verification, real testcase samples, and interactive workflow execution.",
    },
    {
        "name": "Process Graph & Diagram Projections",
        "description": "Evidence-first procedural extraction, local Laya System-1 verification, dual-output AST generation, BPMN 2.0 XML exports, and Mermaid diagram projections.",
    },
    {
        "name": "Files & Ingestion",
        "description": "Document ingestion, hierarchical chunking with section provenance, version control, and FAISS vector indexing.",
    },
    {
        "name": "Document Digest & Citations",
        "description": "Citation-grounded readable Markdown document (.md) synthesis with Instructor BYOAI, claim verification, and traceable markdown compilation.",
    },
    {
        "name": "Developer UI",
        "description": "Enterprise management console, file explorer, Process Graph Studio, and visual workbenches.",
    },
    {
        "name": "Health",
        "description": "System operational status, service telemetry, and health readiness.",
    },
]

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database tables and bootstrap default accounts
    init_db()
    yield

def create_app() -> FastAPI:
    app = FastAPI(
        title="Injester & Beelzebuth Community Engine API",
        description=API_DESCRIPTION,
        version="0.1.0",
        openapi_tags=TAGS_METADATA,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        swagger_ui_parameters={
            "docExpansion": "list",
            "filter": True,
            "showExtensions": True,
            "syntaxHighlight.theme": "monokai",
            "persistAuthorization": True,
        }
    )

    # Restrict CORS to configured origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount REST Routers first so they take precedence
    app.include_router(settings_api.router)
    app.include_router(beelzebuth.router)
    app.include_router(process_graph.router)
    app.include_router(files.router)
    app.include_router(auth.router)
    app.include_router(admin.router)
    app.include_router(tenant.router)
    app.include_router(jobs.router)

    # Mount Console Data Router (JSON payloads backing the React console)
    app.include_router(console.router)

    @app.get("/api/health", tags=["Health"], summary="API Readiness & Telemetry")
    def health():
        return {
            "name": "Beelzebuth (Injester Community) Engine API",
            "status": "operational",
            "version": "0.1.0",
            "docs_url": "/docs",
            "redoc_url": "/redoc",
            "ui_url": "/dashboard",
            "engine": f"{settings.SYSTEM1_PROVIDER.upper()} System-1 + Deterministic AST Compiler",
        }

    @app.get("/api/health/liveness", tags=["Health"], summary="Service Liveness Probe")
    def liveness():
        return {"status": "alive"}

    @app.get("/api/health/readiness", tags=["Health"], summary="Service Readiness Probe")
    def readiness(db: Session = Depends(get_db)):
        try:
            db.execute(text("SELECT 1"))
            db_connected = True
        except Exception:
            db_connected = False
        if not db_connected:
            raise HTTPException(status_code=503, detail="Database connection unavailable")
        return {"status": "ready", "database": "connected"}

    # Determine Frontend Dist path
    candidates = [
        settings.BASE_DIR / "frontend" / "dist",
        Path(__file__).resolve().parent.parent / "_frontend_dist",
        Path(__file__).resolve().parent.parent.parent / "frontend" / "dist",
    ]
    frontend_dist: Path = next((p for p in candidates if (p / "index.html").exists()), candidates[0])

    if frontend_dist.exists() and (frontend_dist / "index.html").exists():
        # Serve static assets under /assets
        assets_dir = frontend_dist / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/favicon.svg", include_in_schema=False)
        def favicon():
            fav = frontend_dist / "favicon.svg"
            if fav.exists():
                return FileResponse(fav)
            return HTMLResponse("")

        @app.get("/icons.svg", include_in_schema=False)
        def icons():
            ico = frontend_dist / "icons.svg"
            if ico.exists():
                return FileResponse(ico)
            return HTMLResponse("")

        # Root landing page serves React SPA
        @app.get("/", include_in_schema=False)
        def root():
            return FileResponse(frontend_dist / "index.html")

        # Legacy console entry point -> React dashboard
        @app.get("/ui", include_in_schema=False)
        def legacy_ui_redirect():
            return RedirectResponse(url="/dashboard")

        @app.get("/ui/{full_path:path}", include_in_schema=False)
        def legacy_ui_route(full_path: str):
            return FileResponse(frontend_dist / "index.html")

        # Catch-all for SPA client-side routes (excluding /api, /docs, /redoc, /openapi.json)
        @app.get("/{full_path:path}", include_in_schema=False)
        def catch_all(request: Request, full_path: str):
            if full_path.startswith(("api/", "docs", "redoc", "openapi.json")):
                raise HTTPException(status_code=404, detail="Not Found")
            # If static file exists directly in frontend_dist, serve it
            target = frontend_dist / full_path
            if target.is_file():
                return FileResponse(target)
            return FileResponse(frontend_dist / "index.html")

    return app

app = create_app()
