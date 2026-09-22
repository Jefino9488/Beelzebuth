import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
load_dotenv(override=True)

class Settings:
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres@127.0.0.1:5432/injester")
    
    # Platform Developer Super Admin bootstrap credentials
    SUPERADMIN_EMAIL: str = os.getenv("SUPERADMIN_EMAIL", "admin@injester.platform")
    SUPERADMIN_INITIAL_PASSWORD: str = os.getenv("SUPERADMIN_INITIAL_PASSWORD", "ChangeMeDeveloperPlatform2026!")
    
    # Active BYOAI configuration (runtime configurable by Developer Admin)
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://lightning.ai/api/v1/")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    MODEL_NAME: str = os.getenv("MODEL_NAME", "google/gemini-2.5-flash-lite-preview-06-17")

    # Provider Credentials
    LIGHTNING_API_KEY: str = os.getenv("LIGHTNING_API_KEY", "")
    LIGHTNING_BASE_URL: str = os.getenv("LIGHTNING_BASE_URL", "https://lightning.ai/api/v1/")
    LIGHTNING_MODEL: str = os.getenv("LIGHTNING_MODEL", "google/gemini-2.5-flash-lite-preview-06-17")

    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_BASE_URL: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    OPENROUTER_FREE_MODEL: str = os.getenv("OPENROUTER_FREE_MODEL", "qwen/qwen3.8-27b:free")
    
    # Storage and Embeddings
    STORAGE_DIR: Path = Path(os.getenv("STORAGE_DIR", "./storage")).resolve()
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

    # API & JWT Auth
    JWT_SECRET: str = os.getenv("JWT_SECRET", "super-secret-jwt-platform-key-change-in-prod-2026")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_MINUTES: int = 60 * 24  # 24 hours

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

settings = Settings()
settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
