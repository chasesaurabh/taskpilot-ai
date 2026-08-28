"""Lazy provider construction through LangChain's common chat-model interface."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any, Protocol, cast

from langchain.chat_models import init_chat_model
from langchain_core.runnables import Runnable
from pydantic import BaseModel

from taskpilot.models.config import ModelConfig
from taskpilot.models.errors import ModelConfigurationError


class StructuredChatModel(Protocol):
    def with_structured_output(
        self,
        schema: type[BaseModel],
        *,
        include_raw: bool = False,
    ) -> Runnable[Any, Any]: ...


class ModelFactory(Protocol):
    def create(self, config: ModelConfig) -> StructuredChatModel: ...


ModelInitializer = Callable[..., Any]


class LangChainModelFactory:
    """Build models only when selected, keeping provider extras optional."""

    def __init__(self, initializer: ModelInitializer = init_chat_model) -> None:
        self._initializer = initializer

    def create(self, config: ModelConfig) -> StructuredChatModel:
        if not config.supports_structured_output:
            raise ModelConfigurationError(
                f"Model '{config.model}' does not declare structured-output support"
            )
        provider = config.provider
        kwargs: dict[str, Any] = {
            "model": config.model,
            "temperature": config.temperature,
            "timeout": config.timeout_seconds,
        }
        if provider in {"openai-compatible", "local"}:
            provider = "openai"
            kwargs["base_url"] = config.base_url
        kwargs["model_provider"] = provider
        if config.api_key_env:
            api_key = os.getenv(config.api_key_env)
            if not api_key:
                raise ModelConfigurationError(
                    f"Required API key environment variable is unset: {config.api_key_env}"
                )
            kwargs["api_key"] = api_key
        elif config.provider == "local":
            kwargs["api_key"] = "local-not-required"

        try:
            model = self._initializer(**kwargs)
        except (ImportError, ValueError) as exc:
            raise ModelConfigurationError(
                f"Could not initialize provider '{config.provider}': {exc}"
            ) from exc
        return cast(StructuredChatModel, model)
