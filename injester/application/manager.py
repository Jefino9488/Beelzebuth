from pathlib import Path
from typing import Optional
from sqlalchemy.orm import Session

from injester.config import settings
from injester.infrastructure.db import init_db, SessionLocal
from injester.domain.models import UserRole
from injester.domain.auth import SecurityContext
from injester.pipeline import InjesterPipeline

LOCAL_SEC_CTX = SecurityContext(
    user_id="local_admin",
    email="local@injester.internal",
    role=UserRole.SUPER_ADMIN,
    organisation_id="local",
)

class ServiceManager:
    """
    Central coordinator for local Injester application services.
    Ensures the local workspace is initialized and shares the core pipeline across
    CLI, local web UI, and MCP interfaces.
    """
    _instance: Optional["ServiceManager"] = None

    def __init__(self):
        self._pipeline: Optional[InjesterPipeline] = None
        self._session: Optional[Session] = None
        self._initialized: bool = False
        self._last_workspace: Optional[Path] = None

    @classmethod
    def get_instance(cls) -> "ServiceManager":
        if cls._instance is None:
            cls._instance = ServiceManager()
        return cls._instance

    @property
    def workspace_dir(self) -> Path:
        return settings.WORKSPACE_DIR

    @property
    def storage_dir(self) -> Path:
        return settings.STORAGE_DIR

    @property
    def db_path(self) -> Path:
        return settings.WORKSPACE_DIR / "injester.db"

    def ensure_initialized(self) -> None:
        """Idempotently initializes local workspace directories and SQLite schema."""
        if self._initialized and self._last_workspace == settings.WORKSPACE_DIR:
            return
        settings.WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
        settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        (settings.STORAGE_DIR / "vectorstore").mkdir(parents=True, exist_ok=True)
        init_db()
        self._initialized = True
        self._last_workspace = settings.WORKSPACE_DIR
        if self._pipeline:
            self._pipeline.close()
            self._pipeline = None
        if self._session:
            self._session.close()
            self._session = None

    def get_pipeline(self) -> InjesterPipeline:
        self.ensure_initialized()
        if self._pipeline is None:
            self._session = SessionLocal()
            self._pipeline = InjesterPipeline(session=self._session)
        return self._pipeline

    def sec_ctx(self) -> SecurityContext:
        return LOCAL_SEC_CTX

    def close(self) -> None:
        if self._pipeline:
            self._pipeline.close()
            self._pipeline = None
        if self._session:
            self._session.close()
            self._session = None
        self._initialized = False

manager = ServiceManager.get_instance()
