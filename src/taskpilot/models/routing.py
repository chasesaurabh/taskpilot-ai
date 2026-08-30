"""Visible, deterministic model selection policy."""

from __future__ import annotations

from dataclasses import dataclass

from taskpilot.models.config import ModelConfig, ModelRole, ModelRoutingPolicy, RoutingContext
from taskpilot.models.errors import ModelConfigurationError


@dataclass(frozen=True, slots=True)
class ModelSelection:
    key: str
    config: ModelConfig
    profile: str
    reason: str


class ModelRouter:
    def __init__(self, policy: ModelRoutingPolicy) -> None:
        self._policy = policy

    def select(self, role: ModelRole, context: RoutingContext) -> ModelSelection:
        """Apply ordered rules and then the configured role assignment."""

        profile_name = context.profile or self._policy.default_profile
        profile = self._policy.profiles.get(profile_name)
        if profile is None:
            available = ", ".join(sorted(self._policy.profiles))
            raise ModelConfigurationError(
                f"Unknown model profile '{profile_name}'. Available profiles: {available}"
            )

        for rule in profile.rules:
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
                profile=profile_name,
                reason=f"profile '{profile_name}' matched routing rule '{rule.name}'",
            )

        model_key = profile.assignments.get(role)
        if model_key is None:
            raise ModelConfigurationError(
                f"Model profile '{profile_name}' has no assignment for role '{role}'"
            )
        config = self._policy.models[model_key]
        if context.privacy_required and not config.local:
            raise ModelConfigurationError(
                f"Role '{role}' has no local model for privacy-required execution"
            )
        return ModelSelection(
            key=model_key,
            config=config,
            profile=profile_name,
            reason=f"profile '{profile_name}' used its assignment for role '{role}'",
        )

    @property
    def profiles(self) -> tuple[str, ...]:
        return tuple(sorted(self._policy.profiles))

    @property
    def default_profile(self) -> str:
        return self._policy.default_profile

    @property
    def referenced_models(self) -> dict[str, ModelConfig]:
        return self._policy.referenced_models

    def validate_profiles(self) -> None:
        missing: list[str] = []
        for profile_name, profile in self._policy.profiles.items():
            for role in ModelRole:
                if role not in profile.assignments:
                    missing.append(f"{profile_name}:{role}")
        if missing:
            raise ModelConfigurationError(
                "Model profiles require assignments for every role; missing: "
                + ", ".join(sorted(missing))
            )
