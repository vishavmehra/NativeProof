"""Deterministic demo-mode provider: answers from app/fixtures/demo_llm.py, never calls the network.

Its output goes through the same JSON parsing, schema validation, and cross-reference checks as a
live model's, so demo projects exercise the real pipeline (contracts/README §5).
"""

import json
from collections.abc import Callable, Mapping
from typing import Any

from app.llm.gateway import ChatRequest, Completion, ProviderError

Responder = Callable[[Mapping[str, Any]], dict[str, Any]]


class FixtureLLMProvider:
    name = "fixture"

    def __init__(self, responders: Mapping[str, Responder] | None = None) -> None:
        if responders is None:
            from app.fixtures.demo_llm import RESPONDERS

            responders = RESPONDERS
        self._responders = responders

    async def complete(self, request: ChatRequest) -> Completion:
        responder = self._responders.get(request.prompt_version)
        if responder is None:
            raise ProviderError(f"No demo fixture for {request.prompt_version}.", transient=False)
        output = responder(request.fixture_context or {})
        if output is None:  # the fixtures do not cover this input: report it, never invent output
            raise ProviderError("No demo fixture for this input.", transient=False)
        return Completion(text=json.dumps(output))
