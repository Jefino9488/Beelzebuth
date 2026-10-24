from typing import Optional
from injester.config import settings
from injester.providers.base import BaseLLMProvider
from injester.providers.openai_compatible import OpenAICompatibleProvider
from injester.providers.gemini import GeminiProvider

def get_provider(provider_type: Optional[str] = None) -> BaseLLMProvider:
    """
    Factory resolving active LLM provider.
    Defaults to Gemini if GEMINI_API_KEY is configured, else OpenAICompatibleProvider.
    """
    target = (provider_type or "").lower().strip()

    if target in ("gemini", "google") or (not target and settings.GEMINI_API_KEY):
        return GeminiProvider()

    return OpenAICompatibleProvider()
