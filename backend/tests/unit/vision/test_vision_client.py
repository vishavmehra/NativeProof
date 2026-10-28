"""VisionClient with a mocked HTTP transport: verified-model gate, observation parsing, failure statuses."""

import json
from uuid import uuid4

import httpx

from app.core.config import Settings
from app.llm.vision import VERIFIED_VISION_MODELS, VisionClient

MODEL = "openbmb/MiniCPM-V-4_5"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
ASSET = uuid4()


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {"nebius_api_key": "test-key", "vision_provider": "nebius", "vision_model": MODEL,
                                 "llm_max_retries": 1}
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def chat(content: str) -> httpx.Response:
    return httpx.Response(200, json={
        "id": "c1", "object": "chat.completion", "created": 0, "model": MODEL,
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 600, "completion_tokens": 60, "total_tokens": 660},
    })


def client_for(handler, **overrides: object) -> tuple[VisionClient, list[dict]]:
    requests: list[dict] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return handler(requests[-1])

    return VisionClient(settings(**overrides), http_client=httpx.AsyncClient(transport=httpx.MockTransport(record)),
                        backoff_seconds=0), requests


async def test_visible_elements_become_observations() -> None:
    output = {"observations": [
        {"kind": "text_in_image", "description": "Find your next great escape", "location": "top"},
        {"kind": "text", "description": "Explore the collection", "location": "bottom-right"},
        {"kind": "mood", "description": "orange   circle", "location": None},
    ]}
    client, requests = client_for(lambda body: chat(json.dumps(output)))
    result = await client.observe(ASSET, PNG, "image/png")

    assert (result.status.status, result.status.provider, result.status.model_id) == ("analyzed", "nebius", MODEL)
    assert [(o.id, o.kind) for o in result.observations] == [
        ("vis-1", "text_in_image"), ("vis-2", "text_in_image"), ("vis-3", "other")]
    assert result.observations[2].description == "orange circle" and result.observations[0].asset_id == ASSET
    body = requests[0]
    assert body["model"] == MODEL and body["response_format"] == {"type": "json_object"} and body["temperature"] == 0
    parts = body["messages"][1]["content"]
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert result.trace.status == "completed" and result.trace.prompt_version == "vision-observe-v1"


async def test_unverified_or_missing_models_never_receive_images() -> None:
    def must_not_call(body: dict) -> httpx.Response:
        raise AssertionError("an image was sent")

    for overrides, message in (
        ({"vision_model": "some/text-only-model"}, "has not been verified with real image inference"),
        ({"vision_model": None}, "No vision model is configured."),
        ({"nebius_api_key": None}, "API key is not configured"),
        ({"vision_provider": "openrouter", "openrouter_api_key": "k"}, "has not been verified"),
    ):
        client, _ = client_for(must_not_call, **overrides)
        result = await client.observe(ASSET, PNG, "image/png")
        assert not client.is_configured()
        assert result.status.status == "unavailable" and message in (result.status.message or "")
        assert result.observations == [] and result.trace is None


async def test_unsupported_images_fail_without_a_request() -> None:
    client, requests = client_for(lambda body: chat("{}"))
    for image, content_type in ((PNG, "image/gif"), (b"", "image/png"), (b"0" * (5 * 1024 * 1024 + 1), "image/png")):
        result = await client.observe(ASSET, image, content_type)
        assert result.status.status == "failed"
    assert requests == []


async def test_invalid_output_and_provider_errors_fail_with_a_message() -> None:
    client, _ = client_for(lambda body: chat("I see a mountain."))
    result = await client.observe(ASSET, PNG, "image/png")
    assert result.status.status == "failed" and "did not match" in result.status.message
    assert result.trace.error_code == "RUN_FAILED"

    client, requests = client_for(lambda body: httpx.Response(503))
    result = await client.observe(ASSET, PNG, "image/png")
    assert len(requests) == 2  # one retry for a transient error
    assert result.status.status == "failed" and "text analysis continues" in result.status.message
    assert result.trace.error_code == "PROVIDER_ERROR"


def test_verified_models_are_vision_models_from_real_inference() -> None:
    assert set(VERIFIED_VISION_MODELS) == {"openbmb/MiniCPM-V-4_5", "nvidia/Nemotron-3.5-Super-VL", "google/gemma-3-27b-it"}
