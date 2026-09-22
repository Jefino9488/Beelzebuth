import os
import hashlib
from pathlib import Path
from typing import List, Optional, Tuple
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker, Session
from injester.config import settings
from injester.domain.models import Base, Organisation, User, Folder, File, FileVersion, AuditLog, UserRole, OrgStatus
from injester.domain.auth import SecurityContext, AccessDeniedError, hash_password, bootstrap_superadmin

engine = create_engine(settings.DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    """Initializes tables and bootstraps the developer superadmin account."""
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        bootstrap_superadmin(session)

class TenantRepository:
    """
    Data repository that enforces multi-tenant boundary checks at the database query layer.
    Every query resolves the SecurityContext to guarantee cross-tenant data isolation.
    """
    def __init__(self, session: Session):
        self.session = session

    # --- Organisation & Identity Lifecycle ---

    def create_organisation(self, sec_ctx: SecurityContext, name: str) -> Organisation:
        """Developer/Super Admin approves and provisions new Client Organisations."""
        sec_ctx.assert_super_admin()
        org = Organisation(name=name, status=OrgStatus.APPROVED)
        self.session.add(org)
        self.session.commit()
        self.session.refresh(org)
        self._audit(sec_ctx, "CREATE_ORGANISATION", f"Created organisation '{name}' ({org.id})")
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
                raise AccessDeniedError("Target folder does not belong to your organisation.")

        # Compute SHA-256 for integrity & audit
        file_hash = hashlib.sha256(content_bytes).hexdigest()

        if existing_file_id:
            file_record = self.session.get(File, existing_file_id)
            if not file_record:
                raise ValueError(f"File '{existing_file_id}' not found.")
            sec_ctx.assert_can_access_file(file_record)
            next_version = len(file_record.versions) + 1
        else:
            file_record = File(
                organisation_id=org_id,
                folder_id=folder_id,
                created_by_user_id=sec_ctx.user_id,
                name=filename,
            )
            self.session.add(file_record)
            self.session.flush()  # generates file_record.id
            next_version = 1

        # Physical tenant storage path: storage/<org_id>/<file_id>/v<ver>_<filename>
        storage_dir = settings.STORAGE_DIR / org_id / file_record.id
        storage_dir.mkdir(parents=True, exist_ok=True)
        storage_path = storage_dir / f"v{next_version}_{filename}"
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
            f"Uploaded '{filename}' v{next_version} ({file_version.file_size} bytes)"
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
        sec_ctx.assert_can_access_file(file_record)
        return file_record

    def _audit(self, sec_ctx: SecurityContext, action: str, details: str):
        log = AuditLog(
            organisation_id=sec_ctx.organisation_id,
            user_id=sec_ctx.user_id,
            action=action,
            details=details,
        )
        self.session.add(log)
        self.session.commit()
