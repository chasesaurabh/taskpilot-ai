"""Opaque bearer-token authentication with stable user principals."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass


class AuthenticationError(RuntimeError):
    """Authentication credentials are missing or invalid."""


@dataclass(frozen=True, slots=True)
class Principal:
    principal_id: str
    authenticated: bool


class TokenAuthenticator:
    """Authenticate opaque tokens configured as a JSON principal-to-token mapping."""

    def __init__(self, tokens: dict[str, str] | None = None) -> None:
        self._tokens = dict(tokens or {})
        if any(not principal or not token for principal, token in self._tokens.items()):
            raise ValueError("Authentication principals and tokens must be non-empty")

    @classmethod
    def from_json(cls, value: str | None) -> TokenAuthenticator:
        if value is None or not value.strip():
            return cls()
        parsed = json.loads(value)
        if not isinstance(parsed, dict) or not all(
            isinstance(key, str) and isinstance(token, str) for key, token in parsed.items()
        ):
            raise ValueError("TASKPILOT_AUTH_TOKENS must be a JSON object of principal-to-token")
        return cls(parsed)

    @property
    def enabled(self) -> bool:
        return bool(self._tokens)

    def authenticate(self, authorization: str | None) -> Principal:
        if not self.enabled:
            return Principal(principal_id="local", authenticated=False)
        if not authorization or not authorization.startswith("Bearer "):
            raise AuthenticationError("Bearer authentication is required")
        supplied = authorization.removeprefix("Bearer ").strip()
        for principal, expected in self._tokens.items():
            if secrets.compare_digest(supplied, expected):
                return Principal(principal_id=principal, authenticated=True)
        raise AuthenticationError("Invalid bearer token")
