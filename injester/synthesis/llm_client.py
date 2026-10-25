import instructor
from openai import OpenAI
from injester.config import settings

def get_instructor_client():
    """
    Returns an instructor-wrapped OpenAI client and model name.
    Supports OpenRouter, OpenAI, Lightning AI, and local LLMs (Ollama/vLLM)
    using the standard OpenAI-compatible interface.
    """
    api_key = settings.OPENAI_API_KEY
    base_url = settings.OPENAI_BASE_URL
    model_name = settings.MODEL_NAME

    # For local LLMs like Ollama or vLLM running on localhost, api_key isn't strictly required
    # but the openai SDK requires a non-empty string.
    effective_api_key = api_key if api_key else "byoai-token"

    raw_client = OpenAI(
        base_url=base_url if base_url else None,
        api_key=effective_api_key,
        timeout=45.0,
        max_retries=2,
    )

    client = instructor.from_openai(raw_client, mode=instructor.Mode.JSON)
    return client, model_name

