"""Live smoke check: one structured Nebius call through the gateway. Never prints the API key.

Run from backend/:  uv run python -m app.llm.smoke [task_class]   (default: research_synthesis)
"""

import asyncio
import sys
from typing import ClassVar, Literal

from pydantic import Field

from app.agents._common import Strict, untrusted
from app.core.config import get_settings
from app.llm.gateway import LLMError, LLMGateway
from app.llm.registry import TASK_TIERS


class SmokeOut(Strict):
    schema_version: ClassVar[str] = "smoke-v1"
    sentiment: Literal["positive", "neutral", "negative", "mixed"]
    confusion_level: float = Field(ge=0, le=1)
    summary: str = Field(max_length=200)


async def main(task: str) -> int:
    if task not in TASK_TIERS:
        print(f"Unknown task class {task!r}. Choose one of: {', '.join(TASK_TIERS)}")
        return 2
    gateway = LLMGateway(get_settings())
    if not gateway.is_configured():
        print("NOT CONFIGURED: set NEBIUS_API_KEY and NEBIUS_DEFAULT_MODEL in backend/.env")
        return 2
    try:
        result = await gateway.generate_structured(
            task=task, stage="smoke", agent="smoke", schema=SmokeOut, prompt_version="smoke-v1", temperature=0.0,
            system="Classify how a reader in Japan might react to an outdoor-apparel headline. Keep the summary short.",
            user=untrusted("headline", "Find your next great escape"),
        )
    except LLMError as exc:
        t = exc.trace
        print(f"FAILED {exc.code}: {exc.message} provider={t.provider} model={t.model_id} retries={t.retries}")
        return 1
    t = result.trace
    usage = t.usage.model_dump(exclude_none=True) if t.usage else "not reported"
    print(f"OK provider={t.provider} model={t.model_id} task={task} latency_ms={t.latency_ms} retries={t.retries} "
          f"usage={usage} validation=passed schema={t.schema_version}")
    print(f"value={result.value.model_dump()}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "research_synthesis")))
