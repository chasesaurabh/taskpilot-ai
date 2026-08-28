"""Deterministic, no-credential model for tests and product exploration."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.prompt_values import PromptValue
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel

from taskpilot.models.config import ModelConfig
from taskpilot.models.factory import StructuredChatModel

DemoHandler = Callable[[str], BaseModel]


class DeterministicModel:
    """A structured LangChain-compatible model backed by explicit handlers."""

    def __init__(self, handlers: dict[type[BaseModel], DemoHandler]) -> None:
        self._handlers = handlers

    def with_structured_output(
        self,
        schema: type[BaseModel],
        *,
        include_raw: bool = False,
    ) -> Runnable[Any, Any]:
        if schema not in self._handlers:
            raise ValueError(f"No deterministic handler for {schema.__name__}")

        def invoke(prompt: PromptValue) -> dict[str, object]:
            output = self._handlers[schema](prompt.to_string())
            response: dict[str, object] = {"parsed": output, "parsing_error": None}
            if include_raw:
                response["raw"] = AIMessage(
                    content="deterministic structured response",
                    usage_metadata={
                        "input_tokens": len(prompt.to_string().split()),
                        "output_tokens": len(output.model_dump_json().split()),
                        "total_tokens": len(prompt.to_string().split())
                        + len(output.model_dump_json().split()),
                    },
                )
            return response

        return RunnableLambda(invoke)


class DeterministicModelFactory:
    """Factory adapter that allows the demo model to use the production gateway."""

    def __init__(self, model: StructuredChatModel) -> None:
        self._model = model

    def create(self, _: ModelConfig) -> StructuredChatModel:
        return self._model
