import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from injester.config import settings
from injester.domain.models import Base, User, Organisation, UserRole, OrgStatus
from injester.domain.auth import SecurityContext, hash_password
from injester.infrastructure.db import init_db, SessionLocal

@pytest.fixture(scope="session")
def setup_db():
    init_db()

@pytest.fixture
def db_session(setup_db):
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()

@pytest.fixture
def superadmin_ctx():
    return SecurityContext(
        user_id="superadmin_test_id",
        email=settings.SUPERADMIN_EMAIL,
        role=UserRole.SUPER_ADMIN,
        organisation_id=None,
    )
