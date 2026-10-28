"""EmbeddingClient with a mocked HTTP transport: batching, space checks, retries, configuration."""

import json

import httpx
import pytest

from app.core.config import Settings
from app.llm.embeddings import MAX_BATCH, QUERY_INSTRUCTIONS, EmbeddingClient, capability_endpoint
from app.llm.gateway import LLMError

QWEN = "Qwen/Qwen3-Embedding-8B"


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {"nebius_api_key": "test-key", "embedding_provider": "nebius", "embedding_model": QWEN,
                                 "embedding_dimensions": 3, "llm_max_retries": 1}
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def client_for(handler, **overrides: object) -> tuple[EmbeddingClient, list[dict]]:
    requests: list[dict] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return handler(requests[-1])

    http = httpx.AsyncClient(transport=httpx.MockTransport(record))
    return EmbeddingClient(settings(**overrides), http_client=http, backoff_seconds=0), requests


def vectors_response(body: dict, dims: int = 3) -> httpx.Response:
    data = [{"object": "embedding", "index": i, "embedding": [float(i)] * dims} for i in range(len(body["input"]))]
    return httpx.Response(200, json={"object": "list", "model": body["model"], "data": list(reversed(data)),
                                     "usage": {"prompt_tokens": len(body["input"]), "total_tokens": len(body["input"])}})


async def test_batches_preserve_order_and_record_the_space() -> None:
    client, requests = client_for(vectors_response)
    texts = [f"text {i}" for i in range(MAX_BATCH + 6)]
    result = await client.embed(texts)

    assert [len(r["input"]) for r in requests] == [MAX_BATCH, 6]
    assert requests[0]["model"] == QWEN and requests[0]["dimensions"] == 3 and requests[0]["encoding_format"] == "float"
    assert result.vectors[:2] == [[0.0] * 3, [1.0] * 3]  # sorted by index, not response order
    assert result.vectors[MAX_BATCH] == [0.0] * 3
    assert result.space.key == f"nebius:{QWEN}:3:emb-v1"
    assert result.trace.status == "completed" and result.trace.usage.input_tokens == MAX_BATCH + 6


async def test_queries_get_the_model_instruction_and_documents_do_not() -> None:
    client, requests = client_for(vectors_response)
    await client.embed(["  weekend   hikers "], kind="query")
    await client.embed(["weekend hikers"], kind="document")
    assert requests[0]["input"] == [f"Instruct: {QUERY_INSTRUCTIONS[QWEN]}\nQuery: weekend hikers"]
    assert requests[1]["input"] == ["weekend hikers"]


async def test_vectors_of_another_dimension_are_rejected() -> None:
    client, _ = client_for(lambda body: vectors_response(body, dims=5))
    with pytest.raises(LLMError) as caught:
        await client.embed(["hiking"])
    assert caught.value.code == "PROVIDER_ERROR" and not caught.value.retryable


async def test_transient_errors_are_retried_and_permanent_ones_are_not() -> None:
    statuses = iter([500, 200])
    client, requests = client_for(lambda body: vectors_response(body) if next(statuses) == 200 else httpx.Response(500))
    result = await client.embed(["hiking"])
    assert len(requests) == 2 and result.trace.retries == 1

    client, requests = client_for(lambda body: httpx.Response(400, json={"error": {"message": "bad"}}))
    with pytest.raises(LLMError) as caught:
        await client.embed(["hiking"])
    assert len(requests) == 1
    assert (caught.value.code, caught.value.retryable, caught.value.trace.status) == ("PROVIDER_ERROR", False, "failed")


@pytest.mark.parametrize(
    "overrides",
    [{"embedding_model": None}, {"embedding_dimensions": None}, {"nebius_api_key": None},
     {"embedding_provider": "openrouter", "openrouter_api_key": None}],
)
async def test_unconfigured_client_raises_provider_not_configured(overrides: dict) -> None:
    client = EmbeddingClient(settings(**overrides))
    assert not client.is_configured()
    with pytest.raises(LLMError) as caught:
        await client.embed(["hiking"])
    assert caught.value.code == "PROVIDER_NOT_CONFIGURED"


def test_openrouter_endpoint_defaults_to_the_public_base_url() -> None:
    endpoint = capability_endpoint(settings(openrouter_api_key="or-key", openrouter_base_url=None), "openrouter")
    assert endpoint == ("https://openrouter.ai/api/v1", "or-key")
