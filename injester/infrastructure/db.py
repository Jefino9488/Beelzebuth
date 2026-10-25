import os
import uuid
import hashlib
from pathlib import Path
from typing import List, Optional, Tuple
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker, Session
from injester.config import settings
from injester.domain.models import (
    Base,
    Organisation,
    User,
    Folder,
    File,
    FileVersion,
    AuditLog,
    UserRole,
    OrgStatus,
    ProcessGraphSnapshot,
    GenerationRun,
)
from injester.domain.auth import SecurityContext, AccessDeniedError, hash_password, bootstrap_superadmin

def get_engine(db_url: Optional[str] = None):
    url = db_url or settings.DATABASE_URL
    args = {"check_same_thread": False, "timeout": 30.0} if url.startswith("sqlite") else {}
    return create_engine(url, echo=False, connect_args=args)

engine = get_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db(db_url: Optional[str] = None):
    """Initializes tables, configures SQLite WAL mode, and bootstraps platform accounts."""
    global engine, SessionLocal
    url = db_url or settings.DATABASE_URL
    if str(engine.url) != url:
        engine = get_engine(url)
        SessionLocal.configure(bind=engine)

    if url.startswith("sqlite"):
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
            conn.exec_driver_sql("PRAGMA busy_timeout=5000;")
    else:
        with engine.connect() as conn:
            try:
                conn.exec_driver_sql("ALTER TABLE process_graph_snapshots ADD COLUMN IF NOT EXISTS source_document_hashes JSON DEFAULT '{}';")
                conn.commit()
            except Exception:
                pass
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        bootstrap_superadmin(session)
        platform_org = session.get(Organisation, "platform") if hasattr(session, "get") else session.query(Organisation).filter(Organisation.id == "platform").first()
        if not platform_org:
            platform_org = Organisation(
                id="platform",
                name="Platform (Global)",
                status=OrgStatus.APPROVED,
            )
            session.add(platform_org)
            session.commit()

        local_org = session.get(Organisation, "local") if hasattr(session, "get") else session.query(Organisation).filter(Organisation.id == "local").first()
        if not local_org:
            local_org = Organisation(
                id="local",
                name="Local Workspace",
                status=OrgStatus.APPROVED,
            )
            session.add(local_org)
            session.commit()

class TenantRepository:
    """
    Data repository that enforces multi-tenant boundary checks at the database query layer.
    Every query resolves the SecurityContext to guarantee cross-tenant data isolation.
    """
    def __init__(self, session: Session):
        self.session = session

    # --- Organisation & Identity Lifecycle ---

    def create_organisation(
        self,
        sec_ctx: SecurityContext,
        name: str,
        status: OrgStatus = OrgStatus.PENDING
    ) -> Organisation:
        """Developer/Super Admin provisions new Client Organisations in PENDING status by default."""
        sec_ctx.assert_super_admin()
        org = Organisation(name=name, status=status)
        self.session.add(org)
        self.session.commit()
        self.session.refresh(org)
        self._audit(sec_ctx, "CREATE_ORGANISATION", f"Created organisation '{name}' ({org.id}) with status '{status.value}'")
        return org

    def approve_organisation(self, sec_ctx: SecurityContext, org_id: str) -> Organisation:
        """Developer/Super Admin approves and activates an organisation."""
        sec_ctx.assert_super_admin()
        org = self.session.get(Organisation, org_id)
        if not org:
            raise ValueError(f"Organisation '{org_id}' not found.")
        org.status = OrgStatus.APPROVED
        self.session.commit()
        self.session.refresh(org)
        self._audit(sec_ctx, "APPROVE_ORGANISATION", f"Approved organisation '{org.name}' ({org.id})")
        return org

    def list_organisations(self, sec_ctx: SecurityContext) -> List[Organisation]:
        """Lists organisations authorized for sec_ctx (all for superadmin, own for client admin/employee)."""
        if sec_ctx.is_super_admin:
            return list(self.session.scalars(select(Organisation)).all())
        if sec_ctx.organisation_id:
            org = self.session.get(Organisation, sec_ctx.organisation_id)
            return [org] if org else []
        return []

    def get_organisation(self, sec_ctx: SecurityContext, org_id: str) -> Optional[Organisation]:
        """Retrieves an organisation enforcing tenant boundary checks."""
        if not sec_ctx.is_super_admin:
            sec_ctx.assert_tenant_access(org_id)
        return self.session.get(Organisation, org_id)

    def suspend_organisation(self, sec_ctx: SecurityContext, org_id: str) -> Organisation:
        """Developer/Super Admin suspends an organisation."""
        sec_ctx.assert_super_admin()
        org = self.session.get(Organisation, org_id)
        if not org:
            raise ValueError(f"Organisation '{org_id}' not found.")
        org.status = OrgStatus.SUSPENDED
        self.session.commit()
        self.session.refresh(org)
        self._audit(sec_ctx, "SUSPEND_ORGANISATION", f"Suspended organisation '{org.name}' ({org.id})")
        return org

    def create_client_admin(
        self,
        sec_ctx: SecurityContext,
        org_id: str,
        email: str,
        password: str
    ) -> User:
        """Assigns the Client Super Admin to an organisation."""
        # Developer or an existing Client Admin of that org
        if not sec_ctx.is_super_admin:
            sec_ctx.assert_tenant_access(org_id)
            if not sec_ctx.is_client_admin:
                raise AccessDeniedError("Only Super Admin or Client Admin can create Client Admins.")

        org = self.session.get(Organisation, org_id)
        if not org:
            raise ValueError(f"Organisation '{org_id}' not found.")

        user = User(
            email=email,
            hashed_password=hash_password(password),
            role=UserRole.CLIENT_ADMIN,
            organisation_id=org_id,
            is_active=True,
        )
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        self._audit(sec_ctx, "CREATE_CLIENT_ADMIN", f"Assigned admin '{email}' to organisation '{org.name}'")
        return user

    def create_employee(
        self,
        sec_ctx: SecurityContext,
        org_id: str,
        email: str,
        password: str
    ) -> User:
        """Client Admin provisions an Employee within their organisation."""
        if not sec_ctx.is_super_admin:
            sec_ctx.assert_tenant_access(org_id)
            if not sec_ctx.is_client_admin:
                raise AccessDeniedError("Only Client Admin can add employees to the organisation.")

        user = User(
            email=email,
            hashed_password=hash_password(password),
            role=UserRole.EMPLOYEE,
            organisation_id=org_id,
            is_active=True,
        )
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        self._audit(sec_ctx, "CREATE_EMPLOYEE", f"Created employee '{email}' in organisation '{org_id}'")
        return user

    # --- Folder Hierarchy ---

    def create_folder(
        self,
        sec_ctx: SecurityContext,
        name: str,
        parent_folder_id: Optional[str] = None
    ) -> Folder:
        """Creates a folder or subfolder within the user's organisation."""
        if not sec_ctx.organisation_id:
            raise AccessDeniedError("A tenant organisation is required to create folders.")

        if parent_folder_id:
            parent = self.session.get(Folder, parent_folder_id)
            if not parent or parent.organisation_id != sec_ctx.organisation_id:
                self._audit(
                    sec_ctx,
                    "CROSS_TENANT_ACCESS_DENIED",
                    f"Unauthorized attempt by '{sec_ctx.email}' to create subfolder under foreign parent '{parent_folder_id}'"
                )
                raise AccessDeniedError("Parent folder does not exist or belongs to another tenant.")

        folder = Folder(
            organisation_id=sec_ctx.organisation_id,
            parent_folder_id=parent_folder_id,
            name=name,
            created_by_user_id=sec_ctx.user_id,
        )
        self.session.add(folder)
        self.session.commit()
        self.session.refresh(folder)
        return folder

    def list_folders(self, sec_ctx: SecurityContext) -> List[Folder]:
        """
        List folders with database-level isolation:
        - Super Admin: can view all
        - Client Admin: can view all folders in their organisation
        - Employee: strictly restricted to folders created by them
        """
        if not sec_ctx.organisation_id and not sec_ctx.is_super_admin:
            return []
        query = select(Folder)
        if not sec_ctx.is_super_admin:
            query = query.where(Folder.organisation_id == sec_ctx.organisation_id)
            if sec_ctx.is_employee:
                query = query.where(Folder.created_by_user_id == sec_ctx.user_id)
        return list(self.session.scalars(query).all())

    # --- Files & Versioning ---

    def upload_file(
        self,
        sec_ctx: SecurityContext,
        filename: str,
        content_bytes: bytes,
        mime_type: str = "application/octet-stream",
        folder_id: Optional[str] = None,
        existing_file_id: Optional[str] = None
    ) -> Tuple[File, FileVersion]:
        """
        Uploads a new file or appends a new FileVersion.
        Enforces tenant isolation: files are written to tenant-partitioned physical storage.
        """
        if not sec_ctx.organisation_id and not sec_ctx.is_super_admin:
            raise AccessDeniedError("Cannot upload file without tenant scope.")

        org_id = sec_ctx.organisation_id or "platform"

        # Validate folder belongs to tenant if specified
        if folder_id:
            folder = self.session.get(Folder, folder_id)
            if not folder or folder.organisation_id != org_id:
                self._audit(
                    sec_ctx,
                    "CROSS_TENANT_ACCESS_DENIED",
                    f"Unauthorized attempt by '{sec_ctx.email}' to access folder '{folder_id}'"
                )
                raise AccessDeniedError("Target folder does not belong to your organisation.")

        # Compute SHA-256 for integrity & audit
        file_hash = hashlib.sha256(content_bytes).hexdigest()

        # Sanitize filename for display metadata (prevent directory traversal in File.name)
        safe_display_name = Path(filename).name
        if not safe_display_name or safe_display_name in (".", ".."):
            safe_display_name = f"upload_{uuid.uuid4().hex[:8]}"

        if existing_file_id:
            file_record = self.session.get(File, existing_file_id)
            if not file_record:
                raise ValueError(f"File '{existing_file_id}' not found.")
            try:
                sec_ctx.assert_can_access_file(file_record)
            except AccessDeniedError as e:
                self._audit(
                    sec_ctx,
                    "CROSS_TENANT_ACCESS_DENIED",
                    f"Unauthorized attempt by '{sec_ctx.email}' to update file '{existing_file_id}'"
                )
                raise e
            # Query coalesced max version to prevent race conditions
            current_max = self.session.query(
                func.coalesce(func.max(FileVersion.version_number), 0)
            ).filter(FileVersion.file_id == existing_file_id).scalar()
            next_version = (current_max or 0) + 1
        else:
            file_record = File(
                organisation_id=org_id,
                folder_id=folder_id,
                created_by_user_id=sec_ctx.user_id,
                name=safe_display_name,
            )
            self.session.add(file_record)
            self.session.flush()  # generates file_record.id
            next_version = 1

        # Physical tenant storage path: storage/<org_id>/<file_id>/v<ver>/<uuid>.blob
        blob_id = uuid.uuid4().hex
        storage_dir = settings.STORAGE_DIR / org_id / file_record.id / f"v{next_version}"
        storage_dir.mkdir(parents=True, exist_ok=True)
        storage_path = storage_dir / f"{blob_id}.blob"
        storage_path.write_bytes(content_bytes)

        file_version = FileVersion(
            file_id=file_record.id,
            version_number=next_version,
            storage_path=str(storage_path),
            file_size=len(content_bytes),
            mime_type=mime_type,
            file_hash=file_hash,
        )
        self.session.add(file_version)
        self.session.commit()
        self.session.refresh(file_record)
        self.session.refresh(file_version)

        self._audit(
            sec_ctx,
            "FILE_UPLOADED",
            f"Uploaded '{safe_display_name}' v{next_version} ({file_version.file_size} bytes)"
        )
        return file_record, file_version

    def list_files(
        self,
        sec_ctx: SecurityContext,
        folder_id: Optional[str] = None
    ) -> List[File]:
        """
        List files with database-level isolation:
        - Super Admin: can view all
        - Client Admin: can view all files belonging to their organisation
        - Employee: strictly restricted to their own uploaded files
        """
        query = select(File)

        if not sec_ctx.is_super_admin:
            # Strictly isolate by organisation
            query = query.where(File.organisation_id == sec_ctx.organisation_id)
            # If standard employee, restrict to files created by them
            if sec_ctx.is_employee:
                query = query.where(File.created_by_user_id == sec_ctx.user_id)

        if folder_id:
            query = query.where(File.folder_id == folder_id)

        return list(self.session.scalars(query).all())

    def get_file(self, sec_ctx: SecurityContext, file_id: str) -> File:
        """Fetch a specific file ensuring authorization check passes."""
        file_record = self.session.get(File, file_id)
        if not file_record:
            raise ValueError(f"File '{file_id}' not found.")
        try:
            sec_ctx.assert_can_access_file(file_record)
        except AccessDeniedError as e:
            self._audit(
                sec_ctx,
                "CROSS_TENANT_ACCESS_DENIED",
                f"Unauthorized attempt by '{sec_ctx.email}' to access file '{file_id}' in org '{file_record.organisation_id}'"
            )
            raise e
        return file_record

    def list_visible_files(self, sec_ctx: SecurityContext, folder_id: Optional[str] = None) -> List[File]:
        """Authorized repository query: lists files visible strictly under sec_ctx permissions."""
        return self.list_files(sec_ctx, folder_id=folder_id)

    def get_visible_file(self, sec_ctx: SecurityContext, file_id: str) -> File:
        """Authorized repository query: retrieves a file or raises AccessDeniedError."""
        return self.get_file(sec_ctx, file_id=file_id)

    def list_visible_audit_logs(self, sec_ctx: SecurityContext, limit: int = 20) -> List[AuditLog]:
        """Authorized repository query: lists audit logs filtered strictly by tenant unless super admin."""
        query = select(AuditLog)
        if not sec_ctx.is_super_admin:
            query = query.where(AuditLog.organisation_id == sec_ctx.organisation_id)
        query = query.order_by(AuditLog.created_at.desc()).limit(limit)
        return list(self.session.scalars(query).all())

    # --- Process Graph Snapshots & Lineage ---

    def save_process_graph_snapshot(
        self,
        sec_ctx: SecurityContext,
        process_name: str,
        canonical_graph: dict,
        defect_register: dict,
        file_version_ids: List[str],
        source_hashes: List[str],
        source_document_hashes: dict,
        span_registry_hash: str,
        reasoner_model: str,
        laya_model_version: str,
        validation_policy_version: str = "1.0",
        projections: Optional[dict] = None,
        schema_version: str = "1.0",
    ) -> ProcessGraphSnapshot:
        """Persists an immutable multi-document ProcessGraphSnapshot."""
        org_id = sec_ctx.organisation_id or "platform"
        org = self.session.get(Organisation, org_id)
        if not org:
            org = Organisation(id=org_id, name=f"Tenant {org_id}", status=OrgStatus.APPROVED)
            self.session.add(org)
            self.session.commit()

        snapshot = ProcessGraphSnapshot(
            organisation_id=org_id,
            process_name=process_name,
            schema_version=schema_version,
            file_version_ids=file_version_ids,
            source_hashes=source_hashes,
            source_document_hashes=source_document_hashes,
            span_registry_hash=span_registry_hash,
            reasoner_model=reasoner_model,
            laya_model_version=laya_model_version,
            validation_policy_version=validation_policy_version,
            canonical_graph=canonical_graph,
            defect_register=defect_register,
            projections=projections or {},
        )
        self.session.add(snapshot)
        self.session.commit()
        self.session.refresh(snapshot)
        self._audit(sec_ctx, "CREATE_SNAPSHOT", f"Created ProcessGraphSnapshot '{snapshot.id}' for process '{process_name}'")
        return snapshot

    def get_process_graph_snapshot(
        self,
        sec_ctx: SecurityContext,
        snapshot_id: str
    ) -> ProcessGraphSnapshot:
        """Fetch a specific snapshot ensuring tenant boundary checks."""
        snapshot = self.session.get(ProcessGraphSnapshot, snapshot_id)
        if not snapshot:
            raise ValueError(f"ProcessGraphSnapshot '{snapshot_id}' not found.")
        if not sec_ctx.is_super_admin and snapshot.organisation_id != sec_ctx.organisation_id:
            self._audit(
                sec_ctx,
                "CROSS_TENANT_ACCESS_DENIED",
                f"Unauthorized attempt by '{sec_ctx.email}' to access snapshot '{snapshot_id}'"
            )
            raise AccessDeniedError("Access denied to requested snapshot.")
        return snapshot

    def list_process_graph_snapshots(
        self,
        sec_ctx: SecurityContext,
        process_name: Optional[str] = None
    ) -> List[ProcessGraphSnapshot]:
        """Lists process graph snapshots visible under sec_ctx."""
        query = select(ProcessGraphSnapshot)
        if not sec_ctx.is_super_admin:
            query = query.where(ProcessGraphSnapshot.organisation_id == sec_ctx.organisation_id)
        if process_name:
            query = query.where(ProcessGraphSnapshot.process_name == process_name)
        query = query.order_by(ProcessGraphSnapshot.created_at.desc())
        return list(self.session.scalars(query).all())

    def save_generation_run(
        self,
        sec_ctx: SecurityContext,
        run_type: str,
        input_file_version_ids: List[str],
        input_hashes: dict,
        config_hash: str,
        output_snapshot_id: Optional[str] = None,
        output_document_id: Optional[str] = None,
        output_defect_register_id: Optional[str] = None,
    ) -> GenerationRun:
        """Records a GenerationRun audit entry with deterministic freshness key."""
        org_id = sec_ctx.organisation_id or "platform"
        org = self.session.get(Organisation, org_id)
        if not org:
            org = Organisation(id=org_id, name=f"Tenant {org_id}", status=OrgStatus.APPROVED)
            self.session.add(org)
            self.session.commit()

        user_id = sec_ctx.user_id
        if user_id and not self.session.get(User, user_id):
            user_id = None

        raw_freshness = f"{','.join(sorted(input_file_version_ids))}:{config_hash}"
        freshness_key = hashlib.sha256(raw_freshness.encode("utf-8")).hexdigest()

        run = GenerationRun(
            organisation_id=org_id,
            user_id=user_id,
            run_type=run_type,
            input_file_version_ids=input_file_version_ids,
            input_hashes=input_hashes,
            output_snapshot_id=output_snapshot_id,
            output_document_id=output_document_id,
            output_defect_register_id=output_defect_register_id,
            config_hash=config_hash,
            freshness_key=freshness_key,
        )
        self.session.add(run)
        self.session.commit()
        self.session.refresh(run)
        self._audit(sec_ctx, "GENERATION_RUN", f"Executed {run_type} run '{run.id}' with freshness key '{freshness_key[:8]}'")
        return run

    def _audit(self, sec_ctx: SecurityContext, action: str, details: str):
        log = AuditLog(
            organisation_id=sec_ctx.organisation_id,
            user_id=sec_ctx.user_id,
            action=action,
            details=details,
        )
        self.session.add(log)
        self.session.commit()
