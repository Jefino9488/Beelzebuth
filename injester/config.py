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

    # Primary Document Extractor Backend ("docling" by default, with "unstructured" fallback)
    EXTRACTOR_BACKEND: str = os.getenv("INJESTER_EXTRACTOR_BACKEND", "docling")

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
    OPENJEV_MODEL_NAME: str = os.getenv("OPENJEV_MODEL_NAME", "AlexWortega/openjev:qwen3.5-0.8b-nli-v2s-long")
    SYSTEM1_POLICY_ACTOR_THRESHOLD: float = float(os.getenv("SYSTEM1_POLICY_ACTOR_THRESHOLD", "0.50"))
    SYSTEM1_POLICY_ACTION_THRESHOLD: float = float(os.getenv("SYSTEM1_POLICY_ACTION_THRESHOLD", "0.50"))
    SYSTEM1_POLICY_OUTCOME_THRESHOLD: float = float(os.getenv("SYSTEM1_POLICY_OUTCOME_THRESHOLD", "0.40"))
    SYSTEM1_POLICY_UNCERTAIN_THRESHOLD: float = float(os.getenv("SYSTEM1_POLICY_UNCERTAIN_THRESHOLD", "0.35"))

    # API & JWT Auth
    JWT_SECRET: str = os.getenv("JWT_SECRET", "super-secret-jwt-platform-key-change-in-prod-2026")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_MINUTES: int = 60 * 24

    # Dedicated Cryptographic ChangeSet Approval Secret (HS256 HMAC)
    # Must be kept strictly distinct from JWT_SECRET to ensure cryptographic domain separation.
    APPROVAL_SIGNING_KEY: str = os.getenv("APPROVAL_SIGNING_KEY", "")

    def get_or_create_approval_signing_key(self) -> str:
        """
        Resolves or initializes the cryptographic approval signing key:
        1. If APPROVAL_SIGNING_KEY is set in the environment, use it directly.
        2. If running in production or multi-user mode without an explicit key, fail closed (returns "").
        3. If running in local single-user mode, automatically generate a cryptographically
           secure random 256-bit key on first launch, persist it in the local workspace directory
           with restricted file permissions (0600), and reuse it across restarts.
        """
        env_key = os.getenv("APPROVAL_SIGNING_KEY", "").strip()
        if env_key:
            return env_key

        is_prod = self.APP_ENV in ("production", "prod")
        is_multi_user = not self.COMMUNITY_MODE and not os.getenv("TESTING")
        if is_prod or is_multi_user:
            return ""

        key_file = self.WORKSPACE_DIR / ".approval_signing_key"
        if key_file.exists():
            try:
                existing_key = key_file.read_text(encoding="utf-8").strip()
                if len(existing_key) >= 32:
                    return existing_key
            except Exception:
                pass

        import secrets
        generated_key = secrets.token_hex(32)
        try:
            self.WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            fd = os.open(str(key_file), flags, 0o600)
            with open(fd, "w", encoding="utf-8") as f:
                f.write(generated_key)
            try:
                os.chmod(str(key_file), 0o600)
            except Exception:
                pass
        except Exception as e:
            raise RuntimeError(
                f"Failed to persist generated approval signing key to '{key_file}': {e}. "
                "Set APPROVAL_SIGNING_KEY explicitly in the environment or ensure the workspace directory is writable."
            ) from e
        return generated_key

    # Environment & Security
    APP_ENV: str = os.getenv("APP_ENV", os.getenv("ENV", "development")).lower()
    ENABLE_DEV_LOGIN: bool = True
    ALLOWED_ORIGINS: list = [
        orig.strip()
        for orig in os.getenv("ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000,http://localhost:5173,http://127.0.0.1:5173").split(",")
        if orig.strip()
    ]

    def validate_security(self) -> None:
        """Enforces fail-fast startup checks in production and multi-user environments."""
        is_prod = self.APP_ENV in ("production", "prod")
        is_multi_user = not self.COMMUNITY_MODE

        if is_prod:
            if self.COMMUNITY_MODE:
                raise ValueError(
                    "FATAL SECURITY CONFIGURATION: COMMUNITY_MODE authentication bypass cannot be enabled in production! "
                    "Set COMMUNITY_MODE=false and configure proper authentication credentials."
                )
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

        # Enforce dedicated APPROVAL_SIGNING_KEY whenever production or multi-user mode is active
        if is_prod or is_multi_user:
            mode_desc = "production" if is_prod else "multi-user (COMMUNITY_MODE=false)"
            if not self.APPROVAL_SIGNING_KEY or len(self.APPROVAL_SIGNING_KEY.strip()) < 32:
                raise ValueError(
                    f"FATAL SECURITY CONFIGURATION: Dedicated APPROVAL_SIGNING_KEY is missing or too short (minimum 32 characters) in {mode_desc}! "
                    "Cryptographic approval signing must have an independent, secure secret provisioned via APPROVAL_SIGNING_KEY."
                )
            if self.APPROVAL_SIGNING_KEY == self.JWT_SECRET:
                raise ValueError(
                    "FATAL SECURITY CONFIGURATION: APPROVAL_SIGNING_KEY must not reuse JWT_SECRET! "
                    "Use separate, dedicated cryptographic secrets for token authentication and document change approvals."
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
settings.APPROVAL_SIGNING_KEY = settings.get_or_create_approval_signing_key()
settings.validate_security()
settings.WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
