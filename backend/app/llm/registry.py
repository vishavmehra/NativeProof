"""Verified Nebius models and task routing.

Only capabilities observed on 2026-10-25 are recorded here (evidence: docs/05_MODEL_ROUTING.md,
appendix "Verified models (2026-10-25)"). A configured model that is not listed is still callable,
but the gateway sends it no response_format and relies on prompt instructions plus validation.
"""

from dataclasses import dataclass
from typing import Literal

from app.core.config import Settings

Tier = Literal["fast", "default", "reasoning"]
TaskClass = Literal[
    "extraction",
    "research_synthesis",
    "study_design",
    "synthetic_generation",
    "sentiment_analysis",
    "risk_analysis",
    "creative_adaptation",
    "comparative_judgment",
    "report_generation",
]

ROUTING_POLICY_VERSION = "routing-v1"

# docs/05 §6.3: small, deterministic task -> tier table.
TASK_TIERS: dict[TaskClass, Tier] = {
    "extraction": "fast",
    "sentiment_analysis": "fast",
    "research_synthesis": "default",
    "study_design": "default",
    "synthetic_generation": "default",
    "creative_adaptation": "default",
    "comparative_judgment": "default",
    "report_generation": "default",
    "risk_analysis": "reasoning",
}


@dataclass(frozen=True)
class ModelInfo:
    model_id: str
    json_schema: bool  # response_format json_schema accepted and the schema was enforced or followed
    json_object: bool  # response_format json_object returned schema-valid JSON
    reasoning_tokens: bool  # spends hidden reasoning tokens (slower, larger budget needed)
    observed_latency_ms: tuple[int, int]  # min, max over the probe requests


VERIFIED_MODELS: dict[str, ModelInfo] = {
    m.model_id: m
    for m in (
        ModelInfo("Qwen/Qwen3-30B-A3B-Instruct-2507", True, True, False, (903, 1854)),
        ModelInfo("Qwen/Qwen3-235B-A22B-Instruct-2507", True, True, False, (1488, 4085)),
        ModelInfo("deepseek-ai/DeepSeek-V4-Pro", True, True, False, (1949, 3395)),
        # Kimi-K3 stopped responding on 2026-10-28 (3 x 60 s timeouts); the reasoning tier moved to DeepSeek-V4-Pro.
        ModelInfo("moonshotai/Kimi-K3", True, True, True, (1798, 1904)),
        ModelInfo("zai-org/GLM-5.3", True, True, True, (3433, 7742)),
        # OpenRouter free tier (D-033): json_object observed valid once each; json_schema not verified (rate-limited).
        ModelInfo("xingchen-agi/xing4.0-29b-a4b:free", False, True, False, (1121, 1121)),
        ModelInfo("nvidia/nemotron-3.5-super-vl:free", False, True, True, (3867, 3867)),
    )
}


def tier_model(settings: Settings, tier: Tier) -> str | None:
    """Configured Nebius model for a tier; fast and reasoning fall back to the default model."""
    chosen = {
        "fast": settings.nebius_fast_model,
        "default": settings.nebius_default_model,
        "reasoning": settings.nebius_reasoning_model,
    }[tier]
    return chosen or settings.nebius_default_model


def response_format_for(model_id: str, schema_name: str, json_schema: dict) -> dict | None:
    info = VERIFIED_MODELS.get(model_id)
    if info is None:
        return None
    if info.json_schema:
        return {"type": "json_schema", "json_schema": {"name": schema_name, "schema": json_schema}}
    return {"type": "json_object"} if info.json_object else None
