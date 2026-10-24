import json
import logging
from typing import Type, TypeVar, Optional, Any
from pydantic import BaseModel
from google import genai
from google.genai import types

from injester.config import settings
from injester.providers.base import BaseLLMProvider

logger = logging.getLogger("injester.providers.gemini")
T = TypeVar("T", bound=BaseModel)

class GeminiProvider(BaseLLMProvider):
    """
    Native Google Gemini provider using the official google-genai SDK.
    Supports native JSON schema enforcement via response_schema and zero-hallucination structured responses.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
    ):
        self.api_key = api_key or settings.GEMINI_API_KEY or settings.OPENAI_API_KEY
        self.model_name = model_name or "gemini-2.5-flash-lite"
        self._client = genai.Client(api_key=self.api_key) if self.api_key else None

    @property
    def provider_name(self) -> str:
        return "gemini"

    def _get_client(self) -> genai.Client:
        if not self._client:
            key = settings.GEMINI_API_KEY or settings.OPENAI_API_KEY
            if not key:
                raise ValueError("GEMINI_API_KEY not configured. Set GEMINI_API_KEY in environment or .env.")
            self._client = genai.Client(api_key=key)
        return self._client

    def generate_text(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> str:
        client = self._get_client()
        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            system_instruction=system_instruction,
        )
        response = client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=config,
        )
        return response.text or ""

    def generate_structured(
        self,
        prompt: str,
        response_model: Type[T],
        system_instruction: Optional[str] = None,
        temperature: float = 0.1,
        **kwargs: Any,
    ) -> T:
        client = self._get_client()
        config = types.GenerateContentConfig(
            temperature=temperature,
            response_mime_type="application/json",
            response_schema=response_model,
            system_instruction=system_instruction,
        )
        response = client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=config,
        )
        raw_text = response.text or "{}"
        try:
            parsed = json.loads(raw_text)
            return response_model.model_validate(parsed)
        except Exception:
            # Fallback direct validate
            return response_model.model_validate_json(raw_text)
