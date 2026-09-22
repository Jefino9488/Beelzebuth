"""FastAPI layer for Injester multi-tenant platform."""
from injester.api.app import app, create_app

__all__ = ["app", "create_app"]
