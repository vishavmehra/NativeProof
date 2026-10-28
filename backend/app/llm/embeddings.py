"""Embedding adapter (contracts/README §13, D-033, D-034). One configured model = one vector space.

Verified with real inference on 2026-10-26 (docs/15_MODEL_SELECTION.md): Nebius
`Qwen/Qwen3-Embedding-8B` returns L2-normalized vectors, 4096 dimensions natively, honors the
`dimensions` parameter (Matryoshka, e.g. 1024), accepts batches of 128 inputs, and rejects inputs
over 40,960 tokens.

There is no automatic fallback for embeddings: vectors from another provider or model live in a
different space and are never compared. Switching EMBEDDING_* re-embeds stored text instead.

This module also holds the small helpers the vision and speech adapters share: capability
endpoint resolution, OpenAI-SDK error mapping, and bounded retries (the gateway conventions).
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

import openai
from openai import AsyncOpenAI

from app.core.config import Settings
from app.llm.gateway import LLMError, ProviderError
from app.schemas.common import StepTrace, Usage

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# Bump when query instructions, input preparation, or chunking change: it is part of the space key.
EMBEDDING_CONFIG_VERSION = "emb-v1"
MAX_BATCH = 64  # verified up to 128 per request; 64 keeps each request well inside the timeout
MAX_INPUT_CHARS = 24_000  # about 6k tokens, far below the verified 40,960-token limit


# --- Shared capability helpers ---


def capability_endpoint(settings: Settings, provider: str) -> tuple[str, str] | None:
    """(base_url, api_key) for a capability provider, or None when its key is missing."""
    if provider == "nebius":
        key, base_url = settings.nebius_api_key, settings.nebius_base_url
    elif provider == "openrouter":
        key, base_url = settings.openrouter_api_key, settings.openrouter_base_url or OPENROUTER_BASE_URL
    else:
        return None
    secret = key.get_secret_value().strip() if key else ""
    return (base_url, secret) if secret and base_url else None


def provider_error(exc: openai.OpenAIError) -> ProviderError:
    """Map OpenAI-SDK errors the way the chat gateway does: transient vs. permanent."""
    if isinstance(exc, openai.APITimeoutError):
        return ProviderError("timeout", transient=True, timeout=True)
    if isinstance(exc, openai.APIConnectionError):
        return ProviderError("connection error", transient=True)
    if isinstance(exc, openai.RateLimitError):
        return ProviderError("HTTP 429", transient=True)
    if isinstance(exc, openai.InternalServerError):
        return ProviderError(f"HTTP {exc.status_code}", transient=True)
    if isinstance(exc, openai.APIStatusError):
        return ProviderError(f"HTTP {exc.status_code}", transient=False)
    return ProviderError(type(exc).__name__, transient=False)


async def with_retries[T](call: Callable[[], Awaitable[T]], *, retries: int, backoff: float) -> tuple[T, int]:
    """Run `call`, retrying transient provider errors. Returns (result, retries used)."""
    for attempt in range(retries + 1):
        try:
            return await call(), attempt
        except (openai.OpenAIError, ProviderError) as exc:
            error = exc if isinstance(exc, ProviderError) else provider_error(exc)
            if not error.transient or attempt == retries:
                if error is exc:
                    raise
                raise error from exc
            await asyncio.sleep(error.retry_after or backoff * 2**attempt)
    raise AssertionError("unreachable")


def failure_trace(stage: str, agent: str, provider: str, model: str, started: float, error_code: str) -> StepTrace:
    return StepTrace(
        stage=stage, agent=agent, status="failed", provider=provider, model_id=model,
        latency_ms=int((time.perf_counter() - started) * 1000), error_code=error_code,
    )


def llm_error(exc: ProviderError, trace: StepTrace, *, timeout_seconds: float) -> LLMError:
    if exc.timeout:
        return LLMError("PROVIDER_TIMEOUT", f"The model provider did not respond within {int(timeout_seconds)} seconds.",
                        retryable=True, trace=trace)
    if exc.transient:
        return LLMError("PROVIDER_ERROR", "The model provider is temporarily unavailable.", retryable=True, trace=trace)
    return LLMError("PROVIDER_ERROR", "The model provider rejected the request.", retryable=False, trace=trace)


# --- Embeddings ---

# Qwen3-Embedding is trained with an instruction on the query side only (documents are embedded as is).
QUERY_INSTRUCTIONS = {
    "Qwen/Qwen3-Embedding-8B": "Given a search query about a marketing research project, retrieve the most "
    "relevant evidence, brand rules, findings, or campaign copy",
}


@dataclass(frozen=True)
class EmbeddingSpace:
    """Vectors are comparable only within one space."""

    provider: str
    model: str
    dimensions: int
    config_version: str = EMBEDDING_CONFIG_VERSION

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.model}:{self.dimensions}:{self.config_version}"


@dataclass(frozen=True)
class Embeddings:
    vectors: list[list[float]]
    space: EmbeddingSpace
    trace: StepTrace


class EmbeddingClient:
    def __init__(self, settings: Settings, *, http_client: Any = None, backoff_seconds: float = 0.5) -> None:
        self._settings = settings
        self._backoff = backoff_seconds
        endpoint = capability_endpoint(settings, settings.embedding_provider)
        model = (settings.embedding_model or "").strip()
        dimensions = settings.embedding_dimensions
        self.space = (
            EmbeddingSpace(settings.embedding_provider, model, dimensions) if endpoint and model and dimensions else None
        )
        self._client = (
            AsyncOpenAI(base_url=endpoint[0], api_key=endpoint[1], timeout=settings.llm_request_timeout_seconds,
                        max_retries=0, http_client=http_client)
            if self.space and endpoint
            else None
        )

    def is_configured(self) -> bool:
        return self.space is not None

    def prepare(self, text: str, kind: Literal["query", "document"]) -> str:
        cleaned = " ".join(text.split())[:MAX_INPUT_CHARS]
        instruction = QUERY_INSTRUCTIONS.get(self.space.model) if self.space and kind == "query" else None
        return f"Instruct: {instruction}\nQuery: {cleaned}" if instruction else cleaned

    async def embed(
        self, texts: list[str], *, kind: Literal["query", "document"] = "document", stage: str = "embedding",
        agent: str = "retrieval",
    ) -> Embeddings:
        """Embed texts in the configured space. Raises LLMError (never returns vectors of another space)."""
        started = time.perf_counter()
        if self.space is None or self._client is None:
            trace = StepTrace(stage=stage, agent=agent, status="failed", error_code="PROVIDER_NOT_CONFIGURED")
            raise LLMError("PROVIDER_NOT_CONFIGURED", "No embedding model is configured.", retryable=False, trace=trace)
        space, client = self.space, self._client
        inputs = [self.prepare(text, kind) for text in texts]
        if not all(inputs):
            raise ValueError("Cannot embed empty text.")
        vectors: list[list[float]] = []
        retries = 0
        prompt_tokens: int | None = 0
        for start in range(0, len(inputs), MAX_BATCH):
            batch = inputs[start : start + MAX_BATCH]
            try:
                response, used = await with_retries(
                    lambda batch=batch: client.embeddings.create(
                        model=space.model, input=batch, dimensions=space.dimensions, encoding_format="float"
                    ),
                    retries=max(0, self._settings.llm_max_retries), backoff=self._backoff,
                )
            except ProviderError as exc:
                trace = failure_trace(stage, agent, space.provider, space.model, started, "PROVIDER_ERROR")
                raise llm_error(exc, trace, timeout_seconds=self._settings.llm_request_timeout_seconds) from exc
            retries += used
            ordered = sorted(response.data, key=lambda item: item.index)
            if len(ordered) != len(batch) or any(len(item.embedding) != space.dimensions for item in ordered):
                trace = failure_trace(stage, agent, space.provider, space.model, started, "PROVIDER_ERROR")
                raise LLMError("PROVIDER_ERROR", "The embedding provider returned vectors of an unexpected shape.",
                               retryable=False, trace=trace)
            vectors.extend(list(item.embedding) for item in ordered)
            tokens = response.usage.prompt_tokens if response.usage else None
            prompt_tokens = None if prompt_tokens is None or tokens is None else prompt_tokens + tokens
        usage = Usage(input_tokens=prompt_tokens, total_tokens=prompt_tokens) if prompt_tokens is not None else None
        trace = StepTrace(
            stage=stage, agent=agent, status="completed", provider=space.provider, model_id=space.model,
            schema_version=space.key, latency_ms=int((time.perf_counter() - started) * 1000), retries=retries,
            usage=usage,
        )
        return Embeddings(vectors=vectors, space=space, trace=trace)
