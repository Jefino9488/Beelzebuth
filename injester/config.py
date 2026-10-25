import os
from pathlib import Path
from typing import Optional, List, Union, Set
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
        os.environ["INJESTER_WORKSPACE"] = str(self.WORKSPACE_DIR)
        os.environ["STORAGE_DIR"] = str(self.STORAGE_DIR)
        os.environ["DATABASE_URL"] = self.DATABASE_URL
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

    # Approval Authorization Modes:
    # "manual" (default): Requires explicit human authorization via Workbench, CLI, or approval_token.
    # "unattended": Explicit opt-in allowing autonomous AI clients to self-authorize changesets.
    APPROVAL_MODE: str = os.getenv("APPROVAL_MODE", "manual").lower()
    ALLOW_UNATTENDED_MCP_APPROVAL: bool = os.getenv("ALLOW_UNATTENDED_MCP_APPROVAL", "false").lower() in ("true", "1", "yes")

    # Filesystem Containment Boundaries:
    # Restricts file inspection, editing, and output generation to authorized document roots.
    ALLOW_ARBITRARY_FILESYSTEM_ACCESS: bool = os.getenv("ALLOW_ARBITRARY_FILESYSTEM_ACCESS", "false").lower() in ("true", "1", "yes")
    ALLOWED_DOCUMENT_ROOTS_CONFIG: str = os.getenv("ALLOWED_DOCUMENT_ROOTS", "")

    DENIED_SENSITIVE_NAMES: set = {
        ".env",
        "config.env",
        ".approval_signing_key",
        "injester.db",
        ".git",
        ".gitignore",
        "id_rsa",
        "id_ed25519",
        "known_hosts",
    }

    DENIED_SENSITIVE_EXTENSIONS: set = {
        ".env",
        ".key",
        ".pem",
        ".crt",
        ".db",
        ".sqlite",
        ".sqlite3",
        ".py",
        ".pyc",
        ".sh",
        ".bash",
        ".zsh",
        ".so",
        ".dylib",
        ".dll",
    }

    def is_sensitive_path(self, target: Path) -> bool:
        """
        Checks whether a target path refers to an environment secret, private key,
        application database, git internal directory, or executable/code asset.
        """
        for part in target.parts:
            if part in (".git", ".venv", "venv", "__pycache__"):
                return True
            if part.startswith(".") and len(part) > 1 and part not in (".", ".."):
                if part in (".injester",):
                    continue
                return True

        filename = target.name.lower()
        if filename in self.DENIED_SENSITIVE_NAMES:
            return True

        if filename.startswith(".env") or filename.endswith(".env"):
            return True

        for secret_token in ("secret", "credential", "password", "token", "signing_key"):
            if secret_token in filename:
                return True

        suffix = target.suffix.lower()
        if suffix in self.DENIED_SENSITIVE_EXTENSIONS:
            return True

        return False

    def get_allowed_roots(self) -> List[Path]:
        """
        Returns the canonical set of authorized directories for reading and writing documents.
        Strictly limits default roots to the dedicated workspace directory, storage directory,
        and designated sample documents directory. Repository root is explicitly excluded to prevent
        unintended credential, source, and configuration leaks.
        """
        roots: List[Path] = [
            self.WORKSPACE_DIR.resolve(),
            self.STORAGE_DIR.resolve(),
        ]
        sample_dir = (self.BASE_DIR / "sample_docs").resolve()
        if sample_dir.exists():
            roots.append(sample_dir)
        elif (Path.cwd() / "sample_docs").exists():
            roots.append((Path.cwd() / "sample_docs").resolve())

        if self.ALLOWED_DOCUMENT_ROOTS_CONFIG:
            for entry in self.ALLOWED_DOCUMENT_ROOTS_CONFIG.split(","):
                entry = entry.strip()
                if entry:
                    try:
                        p = Path(entry).expanduser().resolve()
                        roots.append(p)
                    except Exception:
                        pass
        return list(dict.fromkeys(roots))

    def is_path_allowed(self, path: Union[str, Path], operation: str = "read") -> bool:
        """
        Validates whether a candidate path falls strictly within authorized document roots
        and does not reference sensitive credentials or environment secrets.
        Resolves symlinks completely before boundary checking to prevent directory escaping.
        """
        try:
            target = Path(path).expanduser().resolve()
        except Exception:
            return False

        # SECURITY: Strictly deny access to sensitive files (secrets, keys, db, .env)
        if self.is_sensitive_path(target):
            return False

        if self.ALLOW_ARBITRARY_FILESYSTEM_ACCESS:
            return True

        allowed_roots = self.get_allowed_roots()
        for root in allowed_roots:
            try:
                if target == root or target.is_relative_to(root):
                    return True
            except (ValueError, AttributeError):
                pass

        # For write destinations where the target file may not yet exist on disk,
        # verify that the parent directory resides inside an allowed root.
        if operation == "write":
            for root in allowed_roots:
                try:
                    if target.parent == root or target.parent.is_relative_to(root):
                        return True
                except (ValueError, AttributeError):
                    pass

        return False

    def assert_path_allowed(self, path: Union[str, Path], operation: str = "read") -> Path:
        """
        Asserts that the resolved path is within authorized boundaries, raising
        AccessDeniedError if outside authorized document roots or if sensitive.
        """
        from injester.domain.auth import AccessDeniedError

        target = Path(path).expanduser().resolve()
        if self.is_sensitive_path(target):
            raise AccessDeniedError(
                f"Filesystem access violation: Sensitive file access denied for '{target.name}'. "
                "Access to configuration secrets, environment files, private keys, and application databases is strictly forbidden."
            )

        if not self.is_path_allowed(target, operation=operation):
            roots_str = ", ".join(str(r) for r in self.get_allowed_roots())
            raise AccessDeniedError(
                f"Filesystem access violation: '{target}' lies outside authorized document roots: [{roots_str}]. "
                f"Configure ALLOWED_DOCUMENT_ROOTS or set ALLOW_ARBITRARY_FILESYSTEM_ACCESS=true to expand boundaries."
            )
        return target

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

    def update_llm_settings(self, base_url: str, api_key: str, model_name: str, persist: bool = False) -> None:
        """Dynamically update LLM BYOAI settings without code changes."""
        self.OPENAI_BASE_URL = base_url.strip()
        self.OPENAI_API_KEY = api_key.strip()
        self.MODEL_NAME = model_name.strip()
        if persist:
            self.persist_to_disk()
        try:
            from injester.application.manager import manager
            manager.reset_pipeline()
        except Exception:
            pass

    def switch_to_lightning(self, persist: bool = False) -> None:
        """Switch active configuration to Lightning AI with Gemini 2.5 Flash-Lite."""
        self.update_llm_settings(
            base_url=self.LIGHTNING_BASE_URL,
            api_key=self.LIGHTNING_API_KEY,
            model_name=self.LIGHTNING_MODEL,
            persist=persist,
        )

    def switch_to_openrouter_free(self, persist: bool = False) -> None:
        """Switch active configuration to OpenRouter using free models."""
        self.update_llm_settings(
            base_url=self.OPENROUTER_BASE_URL,
            api_key=self.OPENROUTER_API_KEY,
            model_name=self.OPENROUTER_FREE_MODEL,
            persist=persist,
        )

    def persist_to_disk(self, target_file: Optional[Path] = None) -> Path:
        """
        Persists active LLM BYOAI, System-1, and security configuration to config.env on disk.
        Defaults to WORKSPACE_DIR / 'config.env'.
        """
        cfg_file = target_file or (self.WORKSPACE_DIR / "config.env")
        cfg_file.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            f"OPENAI_BASE_URL={self.OPENAI_BASE_URL}\n",
            f"OPENAI_API_KEY={self.OPENAI_API_KEY}\n",
            f"MODEL_NAME={self.MODEL_NAME}\n",
        ]
        if self.GEMINI_API_KEY:
            lines.append(f"GEMINI_API_KEY={self.GEMINI_API_KEY}\n")
        if self.LIGHTNING_API_KEY:
            lines.append(f"LIGHTNING_API_KEY={self.LIGHTNING_API_KEY}\n")
        if self.OPENROUTER_API_KEY:
            lines.append(f"OPENROUTER_API_KEY={self.OPENROUTER_API_KEY}\n")
        lines.append(f"SYSTEM1_PROVIDER={self.SYSTEM1_PROVIDER}\n")
        lines.append(f"SYSTEM1_API_MODE={self.SYSTEM1_API_MODE}\n")
        if self.SYSTEM1_API_BASE_URL:
            lines.append(f"SYSTEM1_API_BASE_URL={self.SYSTEM1_API_BASE_URL}\n")
        if self.SYSTEM1_API_KEY:
            lines.append(f"SYSTEM1_API_KEY={self.SYSTEM1_API_KEY}\n")
        if self.SYSTEM1_MODEL:
            lines.append(f"SYSTEM1_MODEL={self.SYSTEM1_MODEL}\n")
        if self.APPROVAL_SIGNING_KEY:
            lines.append(f"APPROVAL_SIGNING_KEY={self.APPROVAL_SIGNING_KEY}\n")
        if hasattr(self, "APPROVAL_MODE"):
            lines.append(f"APPROVAL_MODE={self.APPROVAL_MODE}\n")
        if hasattr(self, "ALLOW_UNATTENDED_MCP_APPROVAL"):
            lines.append(f"ALLOW_UNATTENDED_MCP_APPROVAL={str(self.ALLOW_UNATTENDED_MCP_APPROVAL).lower()}\n")
        if hasattr(self, "ALLOWED_DOCUMENT_ROOTS") and self.ALLOWED_DOCUMENT_ROOTS:
            lines.append(f"ALLOWED_DOCUMENT_ROOTS={self.ALLOWED_DOCUMENT_ROOTS}\n")

        cfg_file.write_text("".join(lines), encoding="utf-8")
        return cfg_file

    def reload_from_disk(self, source_file: Optional[Path] = None) -> None:
        """Reloads settings from workspace config.env (or provided path) if it exists."""
        env_file = source_file or (self.WORKSPACE_DIR / "config.env")
        if env_file.exists():
            load_dotenv(env_file, override=True)
            if os.getenv("OPENAI_BASE_URL") is not None:
                self.OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
            if os.getenv("OPENAI_API_KEY") is not None:
                self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
            if os.getenv("MODEL_NAME") is not None:
                self.MODEL_NAME = os.getenv("MODEL_NAME")
            if os.getenv("GEMINI_API_KEY") is not None:
                self.GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
            if os.getenv("LIGHTNING_API_KEY") is not None:
                self.LIGHTNING_API_KEY = os.getenv("LIGHTNING_API_KEY")
            if os.getenv("OPENROUTER_API_KEY") is not None:
                self.OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
            if os.getenv("SYSTEM1_PROVIDER") is not None:
                self.SYSTEM1_PROVIDER = os.getenv("SYSTEM1_PROVIDER")
            if os.getenv("SYSTEM1_API_MODE") is not None:
                self.SYSTEM1_API_MODE = os.getenv("SYSTEM1_API_MODE")
            if os.getenv("SYSTEM1_API_BASE_URL") is not None:
                self.SYSTEM1_API_BASE_URL = os.getenv("SYSTEM1_API_BASE_URL")
            if os.getenv("SYSTEM1_API_KEY") is not None:
                self.SYSTEM1_API_KEY = os.getenv("SYSTEM1_API_KEY")
            if os.getenv("SYSTEM1_MODEL") is not None:
                self.SYSTEM1_MODEL = os.getenv("SYSTEM1_MODEL")
            if os.getenv("APPROVAL_SIGNING_KEY") is not None:
                self.APPROVAL_SIGNING_KEY = os.getenv("APPROVAL_SIGNING_KEY")
            if os.getenv("APPROVAL_MODE") is not None:
                self.APPROVAL_MODE = os.getenv("APPROVAL_MODE")
            if os.getenv("ALLOW_UNATTENDED_MCP_APPROVAL") is not None:
                self.ALLOW_UNATTENDED_MCP_APPROVAL = os.getenv("ALLOW_UNATTENDED_MCP_APPROVAL", "").lower() in ("true", "1")
            if os.getenv("ALLOWED_DOCUMENT_ROOTS") is not None:
                self.ALLOWED_DOCUMENT_ROOTS = os.getenv("ALLOWED_DOCUMENT_ROOTS")

    def validate_credentials(
        self,
        provider: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 10.0,
    ) -> dict:
        """
        Validates connectivity and credentials against the specified or currently configured LLM provider.
        Returns a dict with {"valid": bool, "status": str, "message": str, "model_count": Optional[int]}.
        """
        from injester.providers.model_catalog import fetch_models, ModelCatalogError

        target_provider = (provider or "openai_compatible").strip().lower()
        if base_url is not None:
            target_base_url = base_url.strip()
        else:
            target_base_url = (self.OPENAI_BASE_URL or "").strip()

        if api_key is not None:
            target_api_key = api_key.strip()
        else:
            target_api_key = (self.OPENAI_API_KEY or "").strip()

        if target_provider == "openrouter" and not target_base_url and base_url is None:
            target_base_url = self.OPENROUTER_BASE_URL or "https://openrouter.ai/api/v1"
            if api_key is None and not target_api_key:
                target_api_key = self.OPENROUTER_API_KEY

        if not target_base_url:
            return {
                "valid": False,
                "status": "error",
                "message": "Base URL is required to validate provider credentials.",
                "model_count": None,
            }

        try:
            models = fetch_models(
                provider=target_provider,
                base_url=target_base_url,
                api_key=target_api_key,
                timeout=timeout,
            )
            return {
                "valid": True,
                "status": "ok",
                "message": f"Successfully authenticated and discovered {len(models)} models.",
                "model_count": len(models),
            }
        except ModelCatalogError as exc:
            return {
                "valid": False,
                "status": "error",
                "message": str(exc),
                "model_count": None,
            }
        except Exception as exc:
            return {
                "valid": False,
                "status": "error",
                "message": f"Connection error: {exc}",
                "model_count": None,
            }

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
        try:
            from injester.application.manager import manager
            manager.reset_pipeline()
        except Exception:
            pass

settings = Settings()
settings.APPROVAL_SIGNING_KEY = settings.get_or_create_approval_signing_key()
settings.validate_security()
settings.WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
