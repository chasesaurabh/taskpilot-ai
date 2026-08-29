"""Structured model invocation with routing, prompts, and usage normalization."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage
from pydantic import BaseModel

from taskpilot.domain.models import ModelDecision
from taskpilot.models.config import ModelRole, RoutingContext
from taskpilot.models.errors import ModelResponseError
from taskpilot.models.factory import ModelFactory, StructuredChatModel
from taskpilot.models.routing import ModelRouter
from taskpilot.prompts.catalog import PromptSpec


@dataclass(frozen=True, slots=True)
class ModelCall[OutputT: BaseModel]:
    output: OutputT
    decision: ModelDecision


class ModelGateway:
    """The only model-facing API used by workflow nodes."""

    def __init__(self, router: ModelRouter, factory: ModelFactory) -> None:
        self._router = router
        self._factory = factory
        self._models: dict[str, StructuredChatModel] = {}

    def invoke_structured[OutputT: BaseModel](
        self,
        *,
        role: ModelRole,
        routing_context: RoutingContext,
        prompt: PromptSpec,
        variables: dict[str, Any],
        output_schema: type[OutputT],
    ) -> ModelCall[OutputT]:
        selection = self._router.select(role, routing_context)
        model = self._models.get(selection.key)
        if model is None:
            model = self._factory.create(selection.config)
            self._models[selection.key] = model

        started = time.monotonic()
        try:
            chain = prompt.template | model.with_structured_output(
                output_schema,
                include_raw=True,
            )
            response = chain.invoke(variables)
        except ModelResponseError:
            raise
        except Exception as exc:
            raise ModelResponseError(
                f"Model invocation failed for role '{role}' using provider "
                f"'{selection.config.provider}'"
            ) from exc
        latency_ms = round((time.monotonic() - started) * 1_000)
        if not isinstance(response, dict):
            raise ModelResponseError("Structured model wrapper returned an unexpected response")
        parsing_error = response.get("parsing_error")
        if parsing_error is not None:
            raise ModelResponseError(f"Structured response parsing failed: {parsing_error}")
        parsed = response.get("parsed")
        if not isinstance(parsed, output_schema):
            raise ModelResponseError(
                f"Expected {output_schema.__name__}, received {type(parsed).__name__}"
            )

        input_tokens: int | None = None
        output_tokens: int | None = None
        raw = response.get("raw")
        if isinstance(raw, AIMessage) and raw.usage_metadata:
            input_tokens = raw.usage_metadata.get("input_tokens")
            output_tokens = raw.usage_metadata.get("output_tokens")
        decision = ModelDecision(
            role=role,
            provider=selection.config.provider,
            model=selection.config.model,
            reason=selection.reason,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        return ModelCall(output=parsed, decision=decision)
