import logging

from openai import AsyncOpenAI
from core.config import settings
from core.exceptions import LLMServiceError
from pydantic import BaseModel, Field
from services.llm_provider_urls import build_llm_provider_http_client

logger = logging.getLogger(__name__)


class ExtractionResult(BaseModel):
    summary: str
    todos: list[str]
    provenance: str | None = None
    confidence: int | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Optional confidence score from 0 to 100",
    )


async def extract_todos_and_summary(
    email_body: str,
    openai_api_key: str,
    base_url: str | None = None,
    provider_name: str = "OpenAI",
    model: str | None = None,
) -> ExtractionResult:
    if not openai_api_key:
        raise ValueError("API Key is not set")

    configured_base_url = base_url if base_url is not None else settings.OPENAI_BASE_URL
    validated_base_url, http_client = await build_llm_provider_http_client(
        configured_base_url
    )
    client = AsyncOpenAI(
        api_key=openai_api_key,
        base_url=validated_base_url,
        http_client=http_client,
    )
    selected_model = model or settings.OPENAI_MODEL
    try:
        response = await client.beta.chat.completions.parse(
            model=selected_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a helpful assistant. Summarize the email, "
                        "extract action items, and include a confidence score "
                        "from 0 to 100 when enough evidence is available."
                    ),
                },
                {"role": "user", "content": email_body},
            ],
            response_format=ExtractionResult,
        )
    except Exception as e:
        logger.error(f"Error calling LLM API for extraction: {e}")
        raise LLMServiceError(f"LLM API error during extraction: {e}") from e
    finally:
        await client.close()

    parsed = response.choices[0].message.parsed
    if not parsed:
        raise RuntimeError("Failed to parse LLM response")

    parsed.provenance = f"{provider_name} ({selected_model})"
    return parsed


async def draft_reply(
    email_body: str,
    instruction: str,
    openai_api_key: str,
    base_url: str | None = None,
    model: str | None = None,
) -> str:
    if not openai_api_key:
        raise ValueError("API Key is not set")

    configured_base_url = base_url if base_url is not None else settings.OPENAI_BASE_URL
    validated_base_url, http_client = await build_llm_provider_http_client(
        configured_base_url
    )
    client = AsyncOpenAI(
        api_key=openai_api_key,
        base_url=validated_base_url,
        http_client=http_client,
    )
    selected_model = model or settings.OPENAI_MODEL
    try:
        response = await client.chat.completions.create(
            model=selected_model,
            messages=[
                {
                    "role": "system",
                    "content": f"You are drafting a professional reply. Instruction: {instruction}",
                },
                {"role": "user", "content": email_body},
            ],
        )
    except Exception as e:
        logger.error(f"Error calling LLM API for drafting: {e}")
        raise LLMServiceError(f"LLM API error during drafting: {e}") from e
    finally:
        await client.close()

    content = response.choices[0].message.content
    return content if content is not None else ""
