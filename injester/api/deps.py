from datetime import datetime, timedelta, timezone
from typing import Generator, Optional
import jwt
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from injester.config import settings
from injester.infrastructure.db import SessionLocal
from injester.domain.models import User, UserRole, Organisation, OrgStatus
from injester.domain.auth import SecurityContext, AccessDeniedError
from injester.application.manager import LOCAL_SEC_CTX

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)

def create_access_token(user: User) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRATION_MINUTES)
    payload = {
        "sub": user.id,
        "email": user.email,
        "role": user.role.value,
        "org_id": user.organisation_id,
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def _validate_user_token(token: str, db: Session) -> SecurityContext:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception

    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User inactive or not found")

    if user.organisation_id:
        org = db.get(Organisation, user.organisation_id)
        if not org or org.status != OrgStatus.APPROVED:
            status_val = org.status.value if org else "UNKNOWN"
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Organisation access forbidden: status is '{status_val}'. Access is permitted only when APPROVED."
            )

    return SecurityContext(
        user_id=user.id,
        email=user.email,
        role=user.role,
        organisation_id=user.organisation_id,
    )

def get_current_sec_ctx(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> SecurityContext:
    if settings.COMMUNITY_MODE:
        return LOCAL_SEC_CTX

    if not token:
        # Check authorization header
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1].strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _validate_user_token(token, db)

def require_super_admin(sec_ctx: SecurityContext = Depends(get_current_sec_ctx)) -> SecurityContext:
    if settings.COMMUNITY_MODE:
        return LOCAL_SEC_CTX
    if not sec_ctx.is_super_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Developer / Super Admin privileges required")
    return sec_ctx

def require_client_admin(sec_ctx: SecurityContext = Depends(get_current_sec_ctx)) -> SecurityContext:
    if settings.COMMUNITY_MODE:
        return LOCAL_SEC_CTX
    if not sec_ctx.is_client_admin and not sec_ctx.is_super_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Client Admin privileges required")
    return sec_ctx
