"""Opaque bearer-token authentication with stable user principals."""

from __future__ import annotations

import importlib
import json
import secrets
from dataclasses import dataclass
from typing import Any, Protocol


class AuthenticationError(RuntimeError):
    """Authentication credentials are missing or invalid."""


@dataclass(frozen=True, slots=True)
class Principal:
    principal_id: str
    authenticated: bool
    roles: tuple[str, ...] = ()

    def has_role(self, role: str) -> bool:
        return role in self.roles


class Authenticator(Protocol):
    @property
    def enabled(self) -> bool: ...

    def authenticate(self, authorization: str | None) -> Principal: ...


class TokenAuthenticator:
    """Authenticate opaque tokens configured as a JSON principal-to-token mapping."""

    def __init__(
        self,
        tokens: dict[str, str | tuple[str, tuple[str, ...]]] | None = None,
    ) -> None:
        self._tokens: dict[str, tuple[str, tuple[str, ...]]] = {}
        for principal, value in (tokens or {}).items():
            token, roles = (value, ()) if isinstance(value, str) else value
            self._tokens[principal] = (token, roles)
        if any(not principal or not token for principal, (token, _) in self._tokens.items()):
            raise ValueError("Authentication principals and tokens must be non-empty")

    @classmethod
    def from_json(cls, value: str | None) -> TokenAuthenticator:
        if value is None or not value.strip():
            return cls()
        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise ValueError("TASKPILOT_AUTH_TOKENS must be a JSON object")
        configured: dict[str, str | tuple[str, tuple[str, ...]]] = {}
        for principal, entry in parsed.items():
            if not isinstance(principal, str):
                raise ValueError("Authentication principal IDs must be strings")
            if isinstance(entry, str):
                configured[principal] = entry
                continue
            if not isinstance(entry, dict) or not isinstance(entry.get("token"), str):
                raise ValueError("Token entries must be strings or objects containing token")
            roles = entry.get("roles", [])
            if not isinstance(roles, list) or not all(isinstance(role, str) for role in roles):
                raise ValueError("Token roles must be a list of strings")
            configured[principal] = (entry["token"], tuple(roles))
        return cls(configured)

    @property
    def enabled(self) -> bool:
        return bool(self._tokens)

    def authenticate(self, authorization: str | None) -> Principal:
        if not self.enabled:
            return Principal(principal_id="local", authenticated=False)
        if not authorization or not authorization.startswith("Bearer "):
            raise AuthenticationError("Bearer authentication is required")
        supplied = authorization.removeprefix("Bearer ").strip()
        for principal, (expected, roles) in self._tokens.items():
            if secrets.compare_digest(supplied, expected):
                return Principal(principal_id=principal, authenticated=True, roles=roles)
        raise AuthenticationError("Invalid bearer token")


class OidcAuthenticator:
    """Validate issuer-signed JWTs through a rotation-aware JWKS client."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks_url: str,
        roles_claim: str = "roles",
    ) -> None:
        try:
            jwt = importlib.import_module("jwt")
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("Install taskpilot-ai[auth] for OIDC authentication") from exc
        self._jwt = jwt
        self._issuer = issuer
        self._audience = audience
        self._roles_claim = roles_claim
        self._jwks = jwt.PyJWKClient(jwks_url)

    @property
    def enabled(self) -> bool:
        return True

    def authenticate(self, authorization: str | None) -> Principal:
        if not authorization or not authorization.startswith("Bearer "):
            raise AuthenticationError("Bearer authentication is required")
        token = authorization.removeprefix("Bearer ").strip()
        try:
            signing_key = self._jwks.get_signing_key_from_jwt(token)
            claims: dict[str, Any] = self._jwt.decode(
                token,
                signing_key.key,
                algorithms=("RS256", "ES256"),
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ("exp", "iat", "sub")},
            )
        except Exception as exc:
            raise AuthenticationError("Invalid or expired OIDC token") from exc
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise AuthenticationError("OIDC token does not contain a valid subject")
        raw_roles = claims.get(self._roles_claim, ())
        roles: tuple[str, ...]
        if isinstance(raw_roles, str):
            roles = (raw_roles,)
        elif isinstance(raw_roles, list) and all(isinstance(role, str) for role in raw_roles):
            roles = tuple(raw_roles)
        else:
            roles = ()
        return Principal(principal_id=subject, authenticated=True, roles=roles)
