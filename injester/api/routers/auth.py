from typing import Optional
from pydantic import BaseModel, EmailStr
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from injester.infrastructure.db import SessionLocal
from injester.domain.models import User
from injester.domain.auth import verify_password, SecurityContext
from injester.api.deps import get_db, create_access_token, get_current_sec_ctx

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: str
    role: str
    organisation_id: Optional[str] = None

class UserProfileResponse(BaseModel):
    user_id: str
    email: str
    role: str
    organisation_id: Optional[str] = None

@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email).first()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    token = create_access_token(user)
    return TokenResponse(
        access_token=token,
        user_id=user.id,
        email=user.email,
        role=user.role.value,
        organisation_id=user.organisation_id,
    )

@router.post("/token", response_model=TokenResponse)
def login_for_swagger(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """OAuth2 password form compatible endpoint for Swagger UI."""
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(user)
    return TokenResponse(
        access_token=token,
        user_id=user.id,
        email=user.email,
        role=user.role.value,
        organisation_id=user.organisation_id,
    )

@router.get("/me", response_model=UserProfileResponse)
def get_current_profile(sec_ctx: SecurityContext = Depends(get_current_sec_ctx)):
    return UserProfileResponse(
        user_id=sec_ctx.user_id,
        email=sec_ctx.email,
        role=sec_ctx.role.value,
        organisation_id=sec_ctx.organisation_id,
    )
