"""Model gateway (docs/05). Agents call LLMGateway.generate_structured; nothing else builds provider clients."""

from app.llm.gateway import LLMError, LLMGateway, LLMResult, TaskClass

__all__ = ["LLMError", "LLMGateway", "LLMResult", "TaskClass"]
