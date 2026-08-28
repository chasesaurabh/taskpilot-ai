"""Visible, deterministic model selection policy."""

from __future__ import annotations

from dataclasses import dataclass

from taskpilot.models.config import ModelConfig, ModelRole, ModelRoutingPolicy, RoutingContext
from taskpilot.models.errors import ModelConfigurationError


@dataclass(frozen=True, slots=True)
class ModelSelection:
    key: str
    config: ModelConfig
    reason: str


class ModelRouter:
    def __init__(self, policy: ModelRoutingPolicy) -> None:
        self._policy = policy

    def select(self, role: ModelRole, context: RoutingContext) -> ModelSelection:
        """Apply ordered rules and then the configured role assignment."""

        for rule in self._policy.rules:
            if rule.role != role:
                continue
            if rule.complexity is not None and rule.complexity != context.complexity:
                continue
            if (
                rule.privacy_required is not None
                and rule.privacy_required != context.privacy_required
            ):
                continue
            if (
                rule.max_repository_files is not None
                and context.repository_file_count > rule.max_repository_files
            ):
                continue
            config = self._policy.models[rule.model_key]
            if context.privacy_required and not config.local:
                continue
            return ModelSelection(
                key=rule.model_key,
                config=config,
                reason=f"matched routing rule '{rule.name}'",
            )

        model_key = self._policy.assignments.get(role)
        if model_key is None:
            raise ModelConfigurationError(f"No model assignment exists for role '{role}'")
        config = self._policy.models[model_key]
        if context.privacy_required and not config.local:
            raise ModelConfigurationError(
                f"Role '{role}' has no local model for privacy-required execution"
            )
        return ModelSelection(
            key=model_key,
            config=config,
            reason=f"used default assignment for role '{role}'",
        )
