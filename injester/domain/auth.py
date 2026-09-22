import bcrypt
from typing import Optional
from injester.config import settings
from injester.domain.models import User, UserRole, File, Organisation

class AccessDeniedError(Exception):
    """Raised when an operation violates tenant isolation or role permissions."""
    pass

def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))

class SecurityContext:
    """
    Represents the authenticated identity and permission scope for a request.
    Enforces backend/database layer tenant isolation.
    """
    def __init__(
        self,
        user_id: str,
        email: str,
        role: UserRole,
        organisation_id: Optional[str] = None
    ):
        self.user_id = user_id
        self.email = email
        self.role = role
        self.organisation_id = organisation_id

    @property
    def is_super_admin(self) -> bool:
        return self.role == UserRole.SUPER_ADMIN

    @property
    def is_client_admin(self) -> bool:
        return self.role == UserRole.CLIENT_ADMIN

    @property
    def is_employee(self) -> bool:
        return self.role == UserRole.EMPLOYEE

    def assert_super_admin(self) -> None:
        if not self.is_super_admin:
            raise AccessDeniedError("Platform Developer / Super Admin privileges required.")

    def assert_tenant_access(self, target_org_id: str) -> None:
        """
        Enforce tenant boundary:
        - Super Admin has platform-wide access.
        - Client Admin and Employee can only access their own organisation.
        """
        if self.is_super_admin:
            return
        if not self.organisation_id or self.organisation_id != target_org_id:
            raise AccessDeniedError(f"Access denied: cannot access tenant '{target_org_id}'.")

    def can_access_file(self, file: File) -> bool:
        """
        Evaluates whether this security context can access the given file:
        - Super Admin: Yes
        - Client Admin: Yes, if file belongs to the admin's organisation
        - Employee: Yes, only if file belongs to their organisation AND they created/own it
        """
        if self.is_super_admin:
            return True
        if self.organisation_id != file.organisation_id:
            return False
        if self.is_client_admin:
            return True
        if self.is_employee:
            return file.created_by_user_id == self.user_id
        return False

    def assert_can_access_file(self, file: File) -> None:
        if not self.can_access_file(file):
            raise AccessDeniedError(
                f"User '{self.email}' ({self.role.value}) is unauthorized to access file '{file.id}' ('{file.name}')."
            )

    def __repr__(self) -> str:
        return f"<SecurityContext(user_id={self.user_id}, role={self.role.value}, org_id={self.organisation_id})>"

def bootstrap_superadmin(session) -> User:
    """
    Bootstrap the permanently privileged Developer / Super Admin platform account
    using environment secrets. Never hardcode passwords.
    """
    admin_email = settings.SUPERADMIN_EMAIL
    existing = session.query(User).filter_map({"email": admin_email}).first() if hasattr(session.query(User), "filter_map") else session.query(User).filter(User.email == admin_email).first()
    
    if existing:
        return existing
    
    admin_user = User(
        email=admin_email,
        hashed_password=hash_password(settings.SUPERADMIN_INITIAL_PASSWORD),
        role=UserRole.SUPER_ADMIN,
        organisation_id=None,
        is_active=True,
    )
    session.add(admin_user)
    session.commit()
    session.refresh(admin_user)
    return admin_user
