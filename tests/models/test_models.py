from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from taskpilot.domain.models import TaskAnalysis
from taskpilot.models.config import (
    ModelConfig,
    ModelRole,
    ModelRoutingPolicy,
    RoutingContext,
    RoutingRule,
    TaskComplexity,
)
from taskpilot.models.demo import DeterministicModel, DeterministicModelFactory
from taskpilot.models.errors import ModelConfigurationError, ModelResponseError
from taskpilot.models.factory import LangChainModelFactory
from taskpilot.models.gateway import ModelGateway
from taskpilot.models.routing import ModelRouter
from taskpilot.prompts.catalog import TASK_ANALYSIS_PROMPT


def _policy() -> ModelRoutingPolicy:
    return ModelRoutingPolicy(
        models={
            "cheap": ModelConfig(provider="openai", model="small"),
            "strong": ModelConfig(provider="anthropic", model="reasoner"),
            "private": ModelConfig(
                provider="local",
                model="coder",
                base_url="http://localhost:11434/v1",
                local=True,
            ),
        },
        assignments={ModelRole.ANALYST: "strong", ModelRole.CODER: "strong"},
        rules=(
            RoutingRule(
                name="cheap-simple-analysis",
                role=ModelRole.ANALYST,
                model_key="cheap",
                complexity=TaskComplexity.SIMPLE,
                max_repository_files=20,
            ),
            RoutingRule(
                name="private-coding",
                role=ModelRole.CODER,
                model_key="private",
                privacy_required=True,
            ),
        ),
    )


def test_router_applies_visible_ordered_rules_and_defaults() -> None:
    router = ModelRouter(_policy())

    simple = router.select(
        ModelRole.ANALYST,
        RoutingContext(complexity=TaskComplexity.SIMPLE, repository_file_count=10),
    )
    complex_task = router.select(
        ModelRole.ANALYST,
        RoutingContext(complexity=TaskComplexity.COMPLEX, repository_file_count=100),
    )
    private = router.select(
        ModelRole.CODER,
        RoutingContext(privacy_required=True),
    )

    assert simple.key == "cheap"
    assert "cheap-simple-analysis" in simple.reason
    assert complex_task.key == "strong"
    assert private.config.local is True


def test_router_rejects_missing_or_non_local_private_assignment() -> None:
    router = ModelRouter(_policy())

    with pytest.raises(ModelConfigurationError, match="No model assignment"):
        router.select(ModelRole.REPORTER, RoutingContext())
    with pytest.raises(ModelConfigurationError, match="no local model"):
        router.select(ModelRole.ANALYST, RoutingContext(privacy_required=True))


def test_routing_policy_rejects_unknown_model_keys() -> None:
    with pytest.raises(ValueError, match="Unknown routed model keys"):
        ModelRoutingPolicy(
            models={"known": ModelConfig(provider="openai", model="small")},
            assignments={ModelRole.PLANNER: "missing"},
        )


def test_compatible_provider_requires_base_url() -> None:
    with pytest.raises(ValueError, match="requires base_url"):
        ModelConfig(provider="openai-compatible", model="coder")


def test_factory_normalizes_local_provider_and_custom_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def initializer(**kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setenv("LOCAL_MODEL_KEY", "test-key")
    factory = LangChainModelFactory(initializer)
    factory.create(
        ModelConfig(
            provider="local",
            model="coder",
            base_url="http://local/v1",
            api_key_env="LOCAL_MODEL_KEY",
            local=True,
        )
    )

    assert captured["model_provider"] == "openai"
    assert captured["base_url"] == "http://local/v1"
    assert captured["api_key"] == "test-key"


def test_factory_reports_missing_provider_credentials() -> None:
    factory = LangChainModelFactory()
    with pytest.raises(ModelConfigurationError, match="environment variable is unset"):
        factory.create(
            ModelConfig(
                provider="openai",
                model="planner",
                api_key_env="DEFINITELY_UNSET_TASKPILOT_KEY",
            )
        )


def test_gateway_runs_prompt_and_structured_demo_through_same_contract() -> None:
    model = DeterministicModel(
        {
            TaskAnalysis: lambda prompt: TaskAnalysis(
                objective="analyze pagination" if "pagination" in prompt else "unexpected",
                acceptance_criteria=("returns a bounded page",),
                risk_level="low",
            )
        }
    )
    gateway = ModelGateway(
        ModelRouter(_policy()),
        DeterministicModelFactory(model),
    )

    call = gateway.invoke_structured(
        role=ModelRole.ANALYST,
        routing_context=RoutingContext(
            complexity=TaskComplexity.SIMPLE,
            repository_file_count=3,
        ),
        prompt=TASK_ANALYSIS_PROMPT,
        variables={"task": "Add pagination", "context": "api.py"},
        output_schema=TaskAnalysis,
    )

    assert call.output.objective == "analyze pagination"
    assert call.decision.model == "small"
    assert call.decision.input_tokens is not None


class UnexpectedResponseModel:
    def with_structured_output(self, _: type[BaseModel], *, include_raw: bool = False) -> Any:
        from langchain_core.runnables import RunnableLambda

        return RunnableLambda(lambda _: "not a structured envelope")


def test_gateway_rejects_invalid_structured_envelope() -> None:
    gateway = ModelGateway(
        ModelRouter(_policy()),
        DeterministicModelFactory(UnexpectedResponseModel()),
    )

    with pytest.raises(ModelResponseError, match="unexpected response"):
        gateway.invoke_structured(
            role=ModelRole.ANALYST,
            routing_context=RoutingContext(),
            prompt=TASK_ANALYSIS_PROMPT,
            variables={"task": "Task", "context": "Context"},
            output_schema=TaskAnalysis,
        )
