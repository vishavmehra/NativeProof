"""Defect #4: every provider call is bounded by a per-request timeout and an overall deadline."""

import asyncio
import time
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.llm.gateway import CAPABILITY_LIMITS, Completion, DeadlinedCapability, LLMError, LLMGateway
from app.llm.smoke import SmokeOut
from app.workflows import RiskScanInput, WorkflowDeps, run_risk_scan
from app.llm.fixture import FixtureLLMProvider
from tests.unit.workflows.scenario import CONTENT, JP, context, demo_deps, offline_settings


class Slow:
    name = "slow"

    def __init__(self, seconds: float):
        self.seconds = seconds
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        await asyncio.sleep(self.seconds)
        return Completion(text='{"sentiment": "positive", "confusion_level": 0.1, "summary": "ok"}')


async def test_chat_call_has_an_overall_deadline():
    settings = Settings(_env_file=None, nebius_api_key=None, nebius_default_model="m")
    gateway = LLMGateway(settings, provider=Slow(1.0), deadline_seconds=0.1)
    started = time.perf_counter()
    with pytest.raises(LLMError) as caught:
        await gateway.generate_structured(task="extraction", stage="s", agent="a", system="s", user="u",
                                          schema=SmokeOut, prompt_version="p")
    assert time.perf_counter() - started < 0.6
    assert caught.value.code == "PROVIDER_TIMEOUT" and caught.value.retryable
    assert caught.value.trace.status == "failed" and caught.value.trace.error_code == "PROVIDER_TIMEOUT"


def test_default_chat_deadline_is_bounded():
    gateway = LLMGateway(offline_settings())
    assert gateway._deadline == offline_settings().llm_request_timeout_seconds * 2.5


class SlowEmbedder:
    space = "space-1"

    def is_configured(self) -> bool:
        return True

    async def embed(self, texts, *, kind="document", stage="embedding", agent="retrieval"):
        await asyncio.sleep(0.3)
        return len(texts)


async def test_capability_deadline_scales_with_batches_and_raises_typed_error():
    wrapper = DeadlinedCapability("embeddings", SlowEmbedder(), request_timeout=30, deadline=0.05, provider="nebius",
                                  model="emb", batch_size=64)
    assert wrapper.space == "space-1" and wrapper.is_configured()  # plain attributes pass through
    with pytest.raises(LLMError) as caught:
        await wrapper.embed(["text"] * 130, kind="document", stage="indexing", agent="retrieval")  # 3 batches: 0.15 s
    error = caught.value
    assert error.code == "PROVIDER_TIMEOUT" and error.retryable
    assert (error.trace.stage, error.trace.provider, error.trace.model_id) == ("indexing", "nebius", "emb")
    roomy = DeadlinedCapability("embeddings", SlowEmbedder(), request_timeout=30, deadline=1.0, provider="nebius",
                                model="emb", batch_size=64)
    assert await roomy.embed(["text"] * 2) == 2


def test_capabilities_get_their_own_request_timeout():
    settings = Settings(_env_file=None, nebius_api_key="test-key", embedding_provider="nebius",
                        embedding_model="Qwen/Qwen3-Embedding-8B", embedding_dimensions=4096)
    wrapper = LLMGateway(settings).capability("embeddings")
    assert isinstance(wrapper, DeadlinedCapability)
    assert (wrapper.request_timeout, wrapper.deadline) == CAPABILITY_LIMITS["embeddings"] == (30.0, 40.0)
    assert wrapper.client._settings.llm_request_timeout_seconds == 30.0  # the adapter's SDK timeout
    assert LLMGateway(settings, fixture=True).capability("embeddings") is None  # demo never reaches a provider
    assert LLMGateway(offline_settings()).capability("vision") is None  # not configured: reported, never substituted


class HangingVision:
    def is_configured(self) -> bool:
        return True

    async def observe(self, asset_id, image, content_type, *, stage, agent):
        await asyncio.sleep(1)


async def test_vision_deadline_fails_vision_but_keeps_the_text_analysis():
    from app.workflows import AssetBlob

    slow = DeadlinedCapability("vision", HangingVision(), request_timeout=20, deadline=0.01, provider="nebius", model="vl")
    deps = WorkflowDeps(qloo=demo_deps().qloo, llm=LLMGateway(offline_settings(), provider=FixtureLLMProvider()), vision=slow)
    inp = RiskScanInput(context=context("live"), scan_id=uuid4(), market=JP, source_kind="content_version", content=CONTENT,
                        assets=[AssetBlob(asset_id=uuid4(), media_type="image/png", data=b"\x89PNG")])
    out = await run_risk_scan(inp, deps)
    assert out.vision.status == "failed" and "did not finish" in out.vision.message
    assert out.findings and out.visual_observations == []
