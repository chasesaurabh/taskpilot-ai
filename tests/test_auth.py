from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from taskpilot.auth import AuthenticationError, OidcAuthenticator, TokenAuthenticator


def test_opaque_token_config_supports_roles_and_constant_identity() -> None:
    authenticator = TokenAuthenticator.from_json(
        json.dumps(
            {
                "reviewer": {
                    "token": "long-secret",
                    "roles": ["approver", "admin"],
                }
            }
        )
    )

    principal = authenticator.authenticate("Bearer long-secret")

    assert principal.principal_id == "reviewer"
    assert principal.has_role("approver")
    assert principal.has_role("admin")


def test_oidc_authenticator_validates_signature_claims_expiry_and_roles(monkeypatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    public_jwk.update({"kid": "test-key", "use": "sig", "alg": "RS256"})
    issuer = "https://issuer.example.test"
    audience = "taskpilot-api"
    authenticator = OidcAuthenticator(
        issuer=issuer,
        audience=audience,
        jwks_url="https://issuer.example.test/.well-known/jwks.json",
        roles_claim="groups",
    )
    monkeypatch.setattr(
        authenticator._jwks,
        "fetch_data",
        lambda: {"keys": [public_jwk]},
    )
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "oidc-user",
            "iss": issuer,
            "aud": audience,
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "groups": ["approver", "admin"],
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )

    principal = authenticator.authenticate(f"Bearer {token}")

    assert principal.principal_id == "oidc-user"
    assert principal.roles == ("approver", "admin")

    expired = jwt.encode(
        {
            "sub": "oidc-user",
            "iss": issuer,
            "aud": audience,
            "iat": now - timedelta(minutes=10),
            "exp": now - timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )
    with pytest.raises(AuthenticationError, match="expired"):
        authenticator.authenticate(f"Bearer {expired}")
