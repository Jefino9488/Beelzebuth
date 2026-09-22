from datetime import datetime, timedelta, timezone
from typing import Generator, Optional
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from injester.config import settings
from injester.infrastructure.db import SessionLocal
from injester.domain.models import User, UserRole
from injester.domain.auth import SecurityContext, AccessDeniedError

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

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

def get_current_sec_ctx(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> SecurityContext:
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

    return SecurityContext(
        user_id=user.id,
        email=user.email,
        role=user.role,
        organisation_id=user.organisation_id,
    )

def require_super_admin(sec_ctx: SecurityContext = Depends(get_current_sec_ctx)) -> SecurityContext:
    if not sec_ctx.is_super_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Developer / Super Admin privileges required")
    return sec_ctx

def require_client_admin(sec_ctx: SecurityContext = Depends(get_current_sec_ctx)) -> SecurityContext:
    if not sec_ctx.is_client_admin and not sec_ctx.is_super_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Client Admin privileges required")
    return sec_ctx
