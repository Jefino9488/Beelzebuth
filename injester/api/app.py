from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from injester.infrastructure.db import init_db
from injester.api.routers import auth, admin, tenant, files, sop, ui

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database tables and bootstrap platform Super Admin
    init_db()
    yield

def create_app() -> FastAPI:
    app = FastAPI(
        title="Injester Platform API",
        description=(
            "Enterprise Multi-Tenant Ingestion & Citation-Grounded SOP Generation Engine. "
            "Ingest anything → normalize → understand → index → retrieve → generate → verify → produce traceable SOPs."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    # Enable CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount UI Router (FastAPI + Jinja2 Dev UI)
    app.include_router(ui.router)

    # Mount REST Routers
    app.include_router(auth.router)
    app.include_router(admin.router)
    app.include_router(tenant.router)
    app.include_router(files.router)
    app.include_router(sop.router)

    @app.get("/api/health", tags=["Health"])
    def health():
        return {
            "name": "Injester Platform API",
            "status": "operational",
            "version": "0.1.0",
            "docs_url": "/docs",
            "ui_url": "/ui",
        }

    return app

app = create_app()
