"""Structured model invocation with routing, prompts, and usage normalization."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel

from taskpilot.domain.models import ModelDecision
from taskpilot.models.config import ModelRole, RoutingContext
from taskpilot.models.errors import ModelConfigurationError, ModelResponseError
from taskpilot.models.factory import ModelFactory, StructuredChatModel
from taskpilot.models.routing import ModelRouter
from taskpilot.prompts.catalog import PromptSpec

_JSON_MODE_SCHEMA_PROMPT = ChatPromptTemplate.from_messages(
    (
        (
            "system",
            "Return exactly one JSON object matching this JSON Schema. Do not rename fields, "
            "add wrapper keys, or include prose outside the object.\n{taskpilot_output_schema}",
        ),
    )
)


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

    def validate_configuration(self) -> None:
        """Fail startup for incomplete profiles, missing extras, or missing secret inputs."""

        self._router.validate_profiles()
        for key, config in self._router.referenced_models.items():
            try:
                model = self._factory.create(config)
            except ModelConfigurationError:
                raise
            except Exception as exc:
                raise ModelConfigurationError(
                    f"Could not validate model '{key}' using provider '{config.provider}'"
                ) from exc
            if not callable(getattr(model, "with_structured_output", None)):
                raise ModelConfigurationError(
                    f"Model '{key}' does not expose structured-output capability"
                )
            self._models[key] = model

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
            method = selection.config.structured_output_method
            schema: type[BaseModel] | dict[str, Any] = output_schema
            validate_parsed_dict = False
            if method == "json_schema" and selection.config.structured_output_strict is not None:
                schema = {
                    "name": output_schema.__name__,
                    "strict": selection.config.structured_output_strict,
                    "schema": output_schema.model_json_schema(),
                }
                validate_parsed_dict = True
            if method is None:
                structured_model = model.with_structured_output(
                    schema,
                    include_raw=True,
                )
            else:
                structured_model = model.with_structured_output(
                    schema,
                    include_raw=True,
                    method=method,
                )
            effective_prompt = prompt.template
            invocation_variables = variables
            if method == "json_mode":
                effective_prompt = prompt.template + _JSON_MODE_SCHEMA_PROMPT
                invocation_variables = {
                    **variables,
                    "taskpilot_output_schema": json.dumps(
                        output_schema.model_json_schema(),
                        separators=(",", ":"),
                    ),
                }
            chain = effective_prompt | structured_model
            response = chain.invoke(invocation_variables)
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
        parsed_response = response.get("parsed")
        if validate_parsed_dict:
            try:
                parsed = output_schema.model_validate(parsed_response)
            except ValueError as exc:
                raise ModelResponseError(
                    f"Structured response did not match {output_schema.__name__}"
                ) from exc
        elif isinstance(parsed_response, output_schema):
            parsed = parsed_response
        else:
            raise ModelResponseError(
                f"Expected {output_schema.__name__}, received {type(parsed_response).__name__}"
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
            profile=selection.profile,
            reason=selection.reason,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        return ModelCall(output=parsed, decision=decision)
