import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from sqlalchemy import (
    Column,
    String,
    Boolean,
    DateTime,
    Integer,
    Float,
    ForeignKey,
    Enum as SQLEnum,
    Text,
    Index,
    JSON,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class UserRole(str, Enum):
    SUPER_ADMIN = "SUPER_ADMIN"     # Platform Developer / Super Admin
    CLIENT_ADMIN = "CLIENT_ADMIN"   # Organisation Super Admin (e.g., Indian Bank Admin)
    EMPLOYEE = "EMPLOYEE"           # Standard Employee / User

class OrgStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"

def generate_uuid() -> str:
    return str(uuid.uuid4())

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

class Organisation(Base):
    __tablename__ = "organisations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), unique=True, nullable=False, index=True)
    status = Column(SQLEnum(OrgStatus), default=OrgStatus.PENDING, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    users = relationship("User", back_populates="organisation", cascade="all, delete-orphan")
    folders = relationship("Folder", back_populates="organisation", cascade="all, delete-orphan")
    files = relationship("File", back_populates="organisation", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Organisation(id={self.id}, name={self.name}, status={self.status})>"

class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    # organisation_id is None for platform Developer/Super Admin
    organisation_id = Column(String(36), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(SQLEnum(UserRole), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    organisation = relationship("Organisation", back_populates="users")
    files = relationship("File", back_populates="owner")
    folders = relationship("Folder", back_populates="creator")

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email}, role={self.role}, org_id={self.organisation_id})>"

class Folder(Base):
    __tablename__ = "folders"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    organisation_id = Column(String(36), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_folder_id = Column(String(36), ForeignKey("folders.id", ondelete="CASCADE"), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    created_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    organisation = relationship("Organisation", back_populates="folders")
    parent = relationship("Folder", remote_side=[id], backref="subfolders")
    files = relationship("File", back_populates="folder")
    creator = relationship("User", back_populates="folders")

    __table_args__ = (
        Index("ix_folder_tenant", "organisation_id", "parent_folder_id"),
    )

    def __repr__(self) -> str:
        return f"<Folder(id={self.id}, name={self.name}, org_id={self.organisation_id}, parent={self.parent_folder_id})>"

class File(Base):
    __tablename__ = "files"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    organisation_id = Column(String(36), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    folder_id = Column(String(36), ForeignKey("folders.id", ondelete="SET NULL"), nullable=True, index=True)
    created_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    organisation = relationship("Organisation", back_populates="files")
    folder = relationship("Folder", back_populates="files")
    owner = relationship("User", back_populates="files")
    versions = relationship("FileVersion", back_populates="file", cascade="all, delete-orphan", order_by="FileVersion.version_number")

    __table_args__ = (
        Index("ix_file_tenant_user", "organisation_id", "created_by_user_id"),
    )

    def __repr__(self) -> str:
        return f"<File(id={self.id}, name={self.name}, org_id={self.organisation_id}, user={self.created_by_user_id})>"

class FileVersion(Base):
    __tablename__ = "file_versions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    file_id = Column(String(36), ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    storage_path = Column(String(1024), nullable=False)
    file_size = Column(Integer, nullable=False)
    mime_type = Column(String(128), nullable=False)
    file_hash = Column(String(64), nullable=False)  # SHA-256 hash for deduplication and audit integrity
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    file = relationship("File", back_populates="versions")

    __table_args__ = (
        Index("ix_file_version_unique", "file_id", "version_number", unique=True),
    )

    def __repr__(self) -> str:
        return f"<FileVersion(file_id={self.file_id}, v={self.version_number}, hash={self.file_hash[:8]})>"

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    organisation_id = Column(String(36), nullable=True, index=True)
    user_id = Column(String(36), nullable=True, index=True)
    action = Column(String(128), nullable=False, index=True)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class ProcessGraphSnapshot(Base):
    """
    Immutable multi-document snapshot of an authoritative Process Graph.
    Captures exact file versions, cryptographic source hashes, span registry state,
    model versions, validation policy, canonical AST, defect register, and projections.
    """
    __tablename__ = "process_graph_snapshots"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    organisation_id = Column(String(36), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    process_name = Column(String(255), nullable=False, index=True)
    schema_version = Column(String(32), default="1.0", nullable=False)
    
    # Multi-document provenance set
    file_version_ids = Column(JSON, default=list, nullable=False)  # List[str]
    source_hashes = Column(JSON, default=list, nullable=False)     # List[str]
    source_document_hashes = Column(JSON, default=dict, nullable=False)  # Dict[str, str]: file_id -> sha256
    span_registry_hash = Column(String(64), nullable=False)        # SHA-256 of combined span registry
    
    # Model & Verification Policy lineage
    reasoner_model = Column(String(128), nullable=False)
    laya_model_version = Column(String(128), nullable=False)
    validation_policy_version = Column(String(64), default="1.0", nullable=False)

    # Core dual-output payloads & projections
    canonical_graph = Column(JSON, nullable=False)
    defect_register = Column(JSON, nullable=False)
    projections = Column(JSON, default=dict, nullable=False)

    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    generation_runs = relationship("GenerationRun", back_populates="snapshot")

    def __repr__(self) -> str:
        return f"<ProcessGraphSnapshot(id={self.id}, process={self.process_name}, schema={self.schema_version})>"


class GenerationRun(Base):
    """
    Authoritative audit and lineage record of a Process Graph or Digest generation execution.
    Tracks exact input versions, cryptographic source hashes, model configs, and freshness keys for 100% reproducibility.
    """
    __tablename__ = "generation_runs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    organisation_id = Column(String(36), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    run_type = Column(String(32), nullable=False, index=True)  # 'process_graph' | 'digest'
    input_file_version_ids = Column(JSON, default=list, nullable=False)  # List[str]
    input_hashes = Column(JSON, default=dict, nullable=False)  # Dict[str, str] (file_id -> sha256)
    output_snapshot_id = Column(String(36), ForeignKey("process_graph_snapshots.id", ondelete="SET NULL"), nullable=True, index=True)
    output_document_id = Column(String(36), nullable=True)
    output_defect_register_id = Column(String(36), nullable=True)
    config_hash = Column(String(64), nullable=False)  # SHA-256 of configuration & prompt settings
    freshness_key = Column(String(64), nullable=False, index=True)  # hash(sorted(file_version_ids) + config_hash)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    organisation = relationship("Organisation")
    user = relationship("User")
    snapshot = relationship("ProcessGraphSnapshot", back_populates="generation_runs")

    def __repr__(self) -> str:
        return f"<GenerationRun(id={self.id}, type={self.run_type}, org={self.organisation_id}, freshness={self.freshness_key[:8]})>"


class ApprovalTokenModel(Base):
    """
    Transactional, single-use, time-expiring human approval token record.
    Stores a SHA-256 hash of the bearer token rather than raw credentials.
    Enforces atomic compare-and-set consumption across concurrent processes.
    """
    __tablename__ = "approval_tokens"

    token_hash = Column(String(64), primary_key=True)
    changeset_id = Column(String(64), nullable=False, index=True)
    document_id = Column(String(255), nullable=False)
    document_version = Column(String(64), nullable=False)
    approver_id = Column(String(255), nullable=False)
    created_at = Column(Float, nullable=False)
    expires_at = Column(Float, nullable=False, index=True)
    consumed = Column(Integer, default=0, nullable=False)
    consumed_at = Column(Float, nullable=True)

    def __repr__(self) -> str:
        return f"<ApprovalToken(hash={self.token_hash[:8]}..., cs={self.changeset_id}, consumed={self.consumed})>"


class ChangeSetModel(Base):
    """
    Transactional, versioned ChangeSet record for cross-process synchronization.
    Maintains optimistic locking version, document version, status, and payload.
    Ensures MCP, Web Workbench, and CLI share consistent, authoritative ChangeSet state.
    """
    __tablename__ = "changesets"

    changeset_id = Column(String(64), primary_key=True)
    document_id = Column(String(255), nullable=False, index=True)
    document_version = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False, index=True)
    file_path = Column(Text, nullable=True)
    payload_json = Column(Text, nullable=False)
    version = Column(Integer, default=1, nullable=False)
    created_at = Column(Float, nullable=False)
    updated_at = Column(Float, nullable=False)

    def __repr__(self) -> str:
        return f"<ChangeSetModel(id={self.changeset_id}, status={self.status}, ver={self.version})>"
