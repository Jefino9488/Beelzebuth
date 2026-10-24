from typing import Type, TypeVar, Optional, Any
from pydantic import BaseModel
import instructor
from openai import OpenAI

from injester.config import settings
from injester.providers.base import BaseLLMProvider

T = TypeVar("T", bound=BaseModel)

class OpenAICompatibleProvider(BaseLLMProvider):
    """
    OpenAI-compatible BYOAI provider.
    Works with OpenRouter, Lightning AI, Ollama, vLLM, and OpenAI.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
    ):
        self.base_url = base_url or settings.OPENAI_BASE_URL
        self.api_key = api_key or settings.OPENAI_API_KEY or "not-needed"
        self.model_name = model_name or settings.MODEL_NAME
        self._raw_client = OpenAI(base_url=self.base_url, api_key=self.api_key)
        self._instructor_client = instructor.from_openai(self._raw_client)

    @property
    def provider_name(self) -> str:
        return "openai_compatible"

    def generate_text(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> str:
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        resp = self._raw_client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        return resp.choices[0].message.content or ""

    def generate_structured(
        self,
        prompt: str,
        response_model: Type[T],
        system_instruction: Optional[str] = None,
        temperature: float = 0.1,
        **kwargs: Any,
    ) -> T:
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        return self._instructor_client.chat.completions.create(
            model=self.model_name,
            response_model=response_model,
            messages=messages,
            temperature=temperature,
            **kwargs,
        )
