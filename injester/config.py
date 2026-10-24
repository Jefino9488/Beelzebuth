import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Load .env file
load_dotenv(override=True)

class Settings:
    BASE_DIR: Path = Path(__file__).resolve().parent.parent

    # Global Workspace configuration
    _default_ws = Path.home() / ".injester"
    _raw_ws = os.getenv("INJESTER_WORKSPACE") or os.getenv("BEELZEBUTH_WORKSPACE")
    WORKSPACE_DIR: Path = Path(_raw_ws).expanduser().resolve() if _raw_ws else _default_ws.resolve()
    if (WORKSPACE_DIR / "config.env").exists():
        load_dotenv(WORKSPACE_DIR / "config.env", override=True)

    # Community Mode (no multi-tenant auth or login required for local operations)
    COMMUNITY_MODE: bool = os.getenv("COMMUNITY_MODE", "true").lower() in ("true", "1")

    # Local Storage Directory for Files and FAISS vector indices
    _raw_storage = os.getenv("STORAGE_DIR")
    if _raw_storage and not _raw_storage.startswith("./") and not _raw_storage == "storage":
        STORAGE_DIR: Path = Path(_raw_storage).expanduser().resolve()
    else:
        STORAGE_DIR: Path = (WORKSPACE_DIR / "storage").resolve()

    # Database URL
    _raw_db = os.getenv("DATABASE_URL")
    if not _raw_db or _raw_db in ("sqlite:///storage/injester.db", "sqlite:///./storage/injester.db", "sqlite:///injester.db"):
        DATABASE_URL: str = f"sqlite:///{WORKSPACE_DIR / 'injester.db'}"
    else:
        DATABASE_URL: str = _raw_db

    def set_workspace(self, path: Path) -> None:
        """Update active workspace directory and derive paths."""
        self.WORKSPACE_DIR = Path(path).expanduser().resolve()
        self.STORAGE_DIR = (self.WORKSPACE_DIR / "storage").resolve()
        self.DATABASE_URL = f"sqlite:///{self.WORKSPACE_DIR / 'injester.db'}"
        self.WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
        self.STORAGE_DIR.mkdir(parents=True, exist_ok=True)

    # Super Admin / Bootstrap Credentials
    SUPERADMIN_EMAIL: str = os.getenv("SUPERADMIN_EMAIL", "admin@injester.platform")
    SUPERADMIN_INITIAL_PASSWORD: str = os.getenv("SUPERADMIN_INITIAL_PASSWORD", "ChangeMeDeveloperPlatform2026!")

    # Active LLM BYOAI Configuration
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    MODEL_NAME: str = os.getenv("MODEL_NAME", "google/gemini-2.5-flash-lite-preview-06-17")
    LLM_TIMEOUT: float = float(os.getenv("LLM_TIMEOUT", "600.0"))

    # Native Gemini Provider
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

    # Provider Credentials
    LIGHTNING_API_KEY: str = os.getenv("LIGHTNING_API_KEY", "")
    LIGHTNING_BASE_URL: str = os.getenv("LIGHTNING_BASE_URL", "https://lightning.ai/api/v1/")
    LIGHTNING_MODEL: str = os.getenv("LIGHTNING_MODEL", "google/gemini-2.5-flash-lite-preview-06-17")

    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_BASE_URL: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    OPENROUTER_FREE_MODEL: str = os.getenv("OPENROUTER_FREE_MODEL", "qwen/qwen3.8-27b:free")

    # Embedding Model (SentenceTransformers local model)
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

    # System-1 Grounding Verifier Configuration
    # `SYSTEM1_PROVIDER` selects the verification engine:
    #   'laya'   -> local Laya checkpoint (offline, no API)
    #   'openjev' -> local OpenJev NLI cross-encoder (offline, no API)
    #   'jev'    -> TypeSafe Jev System-1 API (BYOAI: base_url / api_key / model)
    #   'openai' -> any OpenAI-compatible System-1 endpoint (BYOAI)
    SYSTEM1_PROVIDER: str = os.getenv("SYSTEM1_PROVIDER", "openjev").lower()
    TYPESAFE_API_KEY: str = os.getenv("TYPESAFE_API_KEY", "")
    JEV_MODEL: str = os.getenv("JEV_MODEL", "jev-latest")

    # System-1 BYOAI configuration (mirrors the main LLM BYOAI contract).
    # `SYSTEM1_API_MODE` selects the wire protocol for API-based verifiers:
    #   'typesafe'          -> official TypeSafe Jev SDK (Noul/Choice primitives)
    #   'openai_compatible' -> generic OpenAI-compatible chat endpoint
    SYSTEM1_API_MODE: str = os.getenv("SYSTEM1_API_MODE", "typesafe").lower()
    SYSTEM1_API_BASE_URL: str = os.getenv("SYSTEM1_API_BASE_URL", "")
    SYSTEM1_API_KEY: str = os.getenv("SYSTEM1_API_KEY", "")
    SYSTEM1_MODEL: str = os.getenv("SYSTEM1_MODEL", "")
    SYSTEM1_POLICY_ACTOR_THRESHOLD: float = float(os.getenv("SYSTEM1_POLICY_ACTOR_THRESHOLD", "0.50"))
    SYSTEM1_POLICY_ACTION_THRESHOLD: float = float(os.getenv("SYSTEM1_POLICY_ACTION_THRESHOLD", "0.50"))
    SYSTEM1_POLICY_OUTCOME_THRESHOLD: float = float(os.getenv("SYSTEM1_POLICY_OUTCOME_THRESHOLD", "0.40"))
    SYSTEM1_POLICY_UNCERTAIN_THRESHOLD: float = float(os.getenv("SYSTEM1_POLICY_UNCERTAIN_THRESHOLD", "0.35"))

    # API & JWT Auth
    JWT_SECRET: str = os.getenv("JWT_SECRET", "super-secret-jwt-platform-key-change-in-prod-2026")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_MINUTES: int = 60 * 24

    # Environment & Security
    APP_ENV: str = os.getenv("APP_ENV", os.getenv("ENV", "development")).lower()
    ENABLE_DEV_LOGIN: bool = True
    ALLOWED_ORIGINS: list = [
        orig.strip()
        for orig in os.getenv("ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000,http://localhost:5173,http://127.0.0.1:5173").split(",")
        if orig.strip()
    ]

    def validate_security(self) -> None:
        """Enforces fail-fast startup checks in production when community mode is disabled."""
        if not self.COMMUNITY_MODE and self.APP_ENV in ("production", "prod"):
            default_secrets = [
                "super-secret-jwt-platform-key-change-in-prod-2026",
                "secret",
                "changeme",
            ]
            if self.JWT_SECRET in default_secrets:
                raise ValueError(
                    "FATAL SECURITY CONFIGURATION: Insecure default JWT_SECRET detected in production environment! "
                    "Set a secure JWT_SECRET environment variable."
                )
            if self.SUPERADMIN_INITIAL_PASSWORD == "ChangeMeDeveloperPlatform2026!":
                raise ValueError(
                    "FATAL SECURITY CONFIGURATION: Insecure default SUPERADMIN_INITIAL_PASSWORD detected in production environment! "
                    "Set a unique SUPERADMIN_INITIAL_PASSWORD environment variable."
                )

    def update_llm_settings(self, base_url: str, api_key: str, model_name: str) -> None:
        """Dynamically update LLM BYOAI settings without code changes."""
        self.OPENAI_BASE_URL = base_url.strip()
        self.OPENAI_API_KEY = api_key.strip()
        self.MODEL_NAME = model_name.strip()

    def switch_to_lightning(self) -> None:
        """Switch active configuration to Lightning AI with Gemini 2.5 Flash-Lite."""
        self.update_llm_settings(
            base_url=self.LIGHTNING_BASE_URL,
            api_key=self.LIGHTNING_API_KEY,
            model_name=self.LIGHTNING_MODEL
        )

    def switch_to_openrouter_free(self) -> None:
        """Switch active configuration to OpenRouter using free models."""
        self.update_llm_settings(
            base_url=self.OPENROUTER_BASE_URL,
            api_key=self.OPENROUTER_API_KEY,
            model_name=self.OPENROUTER_FREE_MODEL
        )

    def system1_effective_config(self) -> dict:
        """
        Resolves the effective System-1 verifier configuration.
        Explicit System-1 settings win; otherwise fall back to the legacy
        TYPESAFE_* env values and, for OpenAI-compatible endpoints, to the
        main LLM BYOAI configuration.
        """
        api_mode = (self.SYSTEM1_API_MODE or "typesafe").strip().lower()
        base_url = (self.SYSTEM1_API_BASE_URL or "").strip()
        api_key = (self.SYSTEM1_API_KEY or "").strip()
        model = (self.SYSTEM1_MODEL or "").strip()

        if api_mode == "openai_compatible":
            if not base_url:
                base_url = (self.OPENAI_BASE_URL or "").strip()
            if not api_key:
                api_key = (self.OPENAI_API_KEY or "").strip()
            if not model:
                model = (self.MODEL_NAME or "").strip()
        else:
            if not api_key:
                api_key = (self.TYPESAFE_API_KEY or "").strip()
            if not model:
                model = (self.JEV_MODEL or "").strip()

        return {
            "provider": (self.SYSTEM1_PROVIDER or "openjev").lower(),
            "api_mode": api_mode,
            "base_url": base_url,
            "api_key": api_key,
            "model": model,
        }

    def update_system1_settings(
        self,
        provider: Optional[str] = None,
        api_mode: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        """Dynamically update the System-1 grounding verifier configuration without code changes."""
        if provider is not None:
            self.SYSTEM1_PROVIDER = provider.strip().lower()
        if api_mode is not None:
            self.SYSTEM1_API_MODE = api_mode.strip().lower()
        elif self.SYSTEM1_PROVIDER in ("openai", "openai_compatible"):
            # The generic OpenAI-compatible engine cannot speak the TypeSafe protocol.
            self.SYSTEM1_API_MODE = "openai_compatible"
        if base_url is not None:
            self.SYSTEM1_API_BASE_URL = base_url.strip()
        if api_key is not None:
            self.SYSTEM1_API_KEY = api_key.strip()
        if model is not None:
            self.SYSTEM1_MODEL = model.strip()

settings = Settings()
settings.validate_security()
settings.WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
