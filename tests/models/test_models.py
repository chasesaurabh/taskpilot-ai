from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from taskpilot.domain.models import ImplementationProposal, ProposedFileChange, TaskAnalysis
from taskpilot.models.config import (
    ModelConfig,
    ModelProfile,
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
        profiles={
            "default": ModelProfile(
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
            ),
        },
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


def test_router_selects_an_explicit_profile_and_rejects_unknown_profiles() -> None:
    config = ModelConfig(provider="openai", model="balanced")
    private = ModelConfig(
        provider="local",
        model="private",
        base_url="http://local/v1",
        local=True,
    )
    assignments = {role: "balanced" for role in ModelRole}
    private_assignments = {role: "private" for role in ModelRole}
    router = ModelRouter(
        ModelRoutingPolicy(
            models={"balanced": config, "private": private},
            profiles={
                "balanced": ModelProfile(assignments=assignments),
                "private": ModelProfile(assignments=private_assignments),
            },
            default_profile="balanced",
        )
    )

    selected = router.select(ModelRole.CODER, RoutingContext(profile="private"))

    assert selected.profile == "private"
    assert selected.key == "private"
    with pytest.raises(ModelConfigurationError, match="Available profiles: balanced, private"):
        router.select(ModelRole.CODER, RoutingContext(profile="missing"))


def test_router_rejects_missing_or_non_local_private_assignment() -> None:
    router = ModelRouter(_policy())

    with pytest.raises(ModelConfigurationError, match="has no assignment"):
        router.select(ModelRole.REPORTER, RoutingContext())
    with pytest.raises(ModelConfigurationError, match="no local model"):
        router.select(ModelRole.ANALYST, RoutingContext(privacy_required=True))


def test_startup_validation_requires_every_role_and_structured_model_contract() -> None:
    incomplete = ModelRouter(_policy())
    with pytest.raises(ModelConfigurationError, match="missing"):
        incomplete.validate_profiles()

    config = ModelConfig(provider="demo", model="valid")
    complete = ModelRouter(
        ModelRoutingPolicy(
            models={"valid": config},
            profiles={"default": ModelProfile(assignments={role: "valid" for role in ModelRole})},
        )
    )
    gateway = ModelGateway(complete, DeterministicModelFactory(object()))  # type: ignore[arg-type]
    with pytest.raises(ModelConfigurationError, match="structured-output capability"):
        gateway.validate_configuration()


def test_routing_policy_rejects_unknown_model_keys() -> None:
    with pytest.raises(ValueError, match="Unknown routed model keys"):
        ModelRoutingPolicy(
            models={"known": ModelConfig(provider="openai", model="small")},
            profiles={"default": ModelProfile(assignments={ModelRole.PLANNER: "missing"})},
        )


def test_compatible_provider_requires_base_url() -> None:
    with pytest.raises(ValueError, match="requires base_url"):
        ModelConfig(provider="openai-compatible", model="coder")
    with pytest.raises(ValueError, match="absolute HTTP"):
        ModelConfig(provider="openai-compatible", model="coder", base_url="provider/v1")


def test_structured_output_strict_requires_json_schema_method() -> None:
    with pytest.raises(ValueError, match="requires structured_output_method=json_schema"):
        ModelConfig(
            provider="openai",
            model="planner",
            structured_output_strict=True,
        )


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


def test_factory_resolves_safe_provider_options_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def initializer(**kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setenv("COMPATIBLE_KEY", "test-key")
    monkeypatch.setenv("COMPATIBLE_ORGANIZATION", "test-organization")
    monkeypatch.setenv("COMPATIBLE_TENANT", "tenant-value")
    factory = LangChainModelFactory(initializer)
    factory.create(
        ModelConfig(
            provider="openai-compatible",
            model="coder",
            base_url="https://provider.example/v1",
            api_key_env="COMPATIBLE_KEY",
            organization_env="COMPATIBLE_ORGANIZATION",
            headers_from_env={"X-Tenant": "COMPATIBLE_TENANT"},
            max_tokens=4096,
            extra_body={"reasoning_effort": "high"},
        )
    )

    assert captured["model_provider"] == "openai"
    assert captured["base_url"] == "https://provider.example/v1"
    assert captured["organization"] == "test-organization"
    assert captured["default_headers"] == {"X-Tenant": "tenant-value"}
    assert captured["max_tokens"] == 4096
    assert captured["extra_body"] == {"reasoning_effort": "high"}


def test_model_config_rejects_unsafe_header_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="Invalid HTTP header name"):
        ModelConfig(
            provider="openai-compatible",
            model="coder",
            base_url="http://provider/v1",
            headers_from_env={"Bad Header": "HEADER_VALUE"},
        )

    monkeypatch.setenv("HEADER_VALUE", "value\r\ninjected: true")
    with pytest.raises(ModelConfigurationError, match="invalid HTTP header value"):
        LangChainModelFactory(lambda **_: object()).create(
            ModelConfig(
                provider="openai-compatible",
                model="coder",
                base_url="http://provider/v1",
                headers_from_env={"X-Safe": "HEADER_VALUE"},
            )
        )


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
    assert call.decision.profile == "default"
    assert call.decision.input_tokens is not None


class UnexpectedResponseModel:
    def with_structured_output(self, _: type[BaseModel], *, include_raw: bool = False) -> Any:
        from langchain_core.runnables import RunnableLambda

        return RunnableLambda(lambda _: "not a structured envelope")


class ParsingErrorModel:
    def with_structured_output(self, _: type[BaseModel], *, include_raw: bool = False) -> Any:
        from langchain_core.runnables import RunnableLambda

        return RunnableLambda(
            lambda _: {"parsed": None, "raw": None, "parsing_error": ValueError("bad JSON")}
        )


class FailingProviderModel:
    def with_structured_output(self, _: type[BaseModel], *, include_raw: bool = False) -> Any:
        from langchain_core.runnables import RunnableLambda

        return RunnableLambda(lambda _: (_ for _ in ()).throw(RuntimeError("secret detail")))


class MethodCapturingModel:
    def __init__(self) -> None:
        self.method: str | None = None
        self.schema: type[BaseModel] | dict[str, Any] | None = None

    def with_structured_output(
        self,
        schema: type[BaseModel] | dict[str, Any],
        *,
        include_raw: bool = False,
        method: str | None = None,
    ) -> Any:
        from langchain_core.runnables import RunnableLambda

        self.method = method
        self.schema = schema
        return RunnableLambda(
            lambda _: {
                "parsed": {"objective": "Captured structured output method"},
                "raw": None,
                "parsing_error": None,
            }
        )


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


def test_gateway_forwards_configured_structured_output_method() -> None:
    model = MethodCapturingModel()
    config = ModelConfig(
        provider="openai-compatible",
        model="compatible",
        base_url="https://provider.example/v1",
        structured_output_method="json_schema",
        structured_output_strict=False,
    )
    gateway = ModelGateway(
        ModelRouter(
            ModelRoutingPolicy(
                models={"compatible": config},
                profiles={"default": ModelProfile(assignments={ModelRole.ANALYST: "compatible"})},
            )
        ),
        DeterministicModelFactory(model),
    )

    call = gateway.invoke_structured(
        role=ModelRole.ANALYST,
        routing_context=RoutingContext(),
        prompt=TASK_ANALYSIS_PROMPT,
        variables={"task": "Task", "context": "Context"},
        output_schema=TaskAnalysis,
    )

    assert call.output.objective == "Captured structured output method"
    assert model.method == "json_schema"
    assert isinstance(model.schema, dict)
    assert model.schema["strict"] is False


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        (ParsingErrorModel(), "Structured response parsing failed"),
        (FailingProviderModel(), "Model invocation failed"),
    ],
)
def test_gateway_normalizes_malformed_and_failed_provider_responses(
    model: Any,
    expected: str,
) -> None:
    gateway = ModelGateway(ModelRouter(_policy()), DeterministicModelFactory(model))

    with pytest.raises(ModelResponseError, match=expected) as failure:
        gateway.invoke_structured(
            role=ModelRole.ANALYST,
            routing_context=RoutingContext(),
            prompt=TASK_ANALYSIS_PROMPT,
            variables={"task": "Task", "context": "Context"},
            output_schema=TaskAnalysis,
        )

    if isinstance(model, FailingProviderModel):
        assert "secret detail" not in str(failure.value)


def test_model_proposals_describe_intent_without_owning_write_hashes() -> None:
    schema = ProposedFileChange.model_json_schema()

    assert "expected_sha256" not in schema["properties"]
    with pytest.raises(ValueError, match="at most 25"):
        ImplementationProposal(
            summary="Too many changes",
            changes=tuple(
                ProposedFileChange(
                    path=f"file-{index}.txt",
                    operation="create",
                    content="value",
                )
                for index in range(26)
            ),
        )
