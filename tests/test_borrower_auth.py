"""Tests for GAP-13A: borrower_auth.py – borrower JWT module."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

# Ensure the env var is set before importing the module
os.environ.setdefault("BORROWER_JWT_SECRET", "test-borrower-secret")

from decision_api.src.borrower_auth import (  # noqa: E402
    BorrowerTokenPayload,
    issue_borrower_token,
    verify_borrower_token,
)


# ---------------------------------------------------------------------------
# issue_borrower_token
# ---------------------------------------------------------------------------


class TestIssueBorrowerToken:
    def test_returns_string_token(self) -> None:
        token = issue_borrower_token(
            borrower_id="b-001",
            tenant_id="t-abc",
            application_ids=["app-1", "app-2"],
        )
        assert isinstance(token, str)
        assert len(token) > 20

    def test_different_borrowers_different_tokens(self) -> None:
        t1 = issue_borrower_token("b-001", "t-abc", ["app-1"])
        t2 = issue_borrower_token("b-002", "t-abc", ["app-1"])
        assert t1 != t2

    def test_custom_ttl_respected(self) -> None:
        import jwt as pyjwt
        token = issue_borrower_token("b-001", "t-abc", ["app-1"], ttl_hours=1)
        payload = pyjwt.decode(
            token,
            os.environ["BORROWER_JWT_SECRET"],
            algorithms=["HS256"],
        )
        from datetime import datetime, timezone
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        iat = datetime.fromtimestamp(payload["iat"], tz=timezone.utc)
        delta_hours = (exp - iat).total_seconds() / 3600
        assert abs(delta_hours - 1.0) < 0.01


# ---------------------------------------------------------------------------
# verify_borrower_token — happy path
# ---------------------------------------------------------------------------


class TestVerifyBorrowerToken:
    def test_round_trip(self) -> None:
        token = issue_borrower_token("b-100", "t-xyz", ["app-10", "app-11"])
        payload = verify_borrower_token(token)
        assert isinstance(payload, BorrowerTokenPayload)
        assert payload.borrower_id == "b-100"
        assert payload.tenant_id == "t-xyz"
        assert "app-10" in payload.application_ids

    def test_application_ids_preserved(self) -> None:
        ids = ["app-1", "app-2", "app-3"]
        token = issue_borrower_token("b-200", "t-abc", ids)
        result = verify_borrower_token(token)
        assert result.application_ids == ids

    def test_expires_at_set(self) -> None:
        token = issue_borrower_token("b-300", "t-abc", ["app-x"])
        payload = verify_borrower_token(token)
        assert payload.expires_at != ""

    def test_issued_at_set(self) -> None:
        token = issue_borrower_token("b-400", "t-abc", ["app-y"])
        payload = verify_borrower_token(token)
        assert payload.issued_at != ""


# ---------------------------------------------------------------------------
# verify_borrower_token — error paths
# ---------------------------------------------------------------------------


class TestVerifyBorrowerTokenErrors:
    def test_invalid_token_raises_http_401(self) -> None:
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            verify_borrower_token("not.a.valid.token")
        assert exc_info.value.status_code == 401

    def test_wrong_secret_raises_http_401(self) -> None:
        import jwt as pyjwt
        import time
        from fastapi import HTTPException

        bad_token = pyjwt.encode(
            {
                "borrower_id": "b-999",
                "tenant_id": "t-999",
                "application_ids": [],
                "token_type": "borrower",
                "iat": int(time.time()),
                "exp": int(time.time()) + 3600,
            },
            "wrong-secret",
            algorithm="HS256",
        )
        with pytest.raises(HTTPException) as exc_info:
            verify_borrower_token(bad_token)
        assert exc_info.value.status_code == 401

    def test_tenant_token_raises_403(self) -> None:
        """A JWT with token_type != 'borrower' must be rejected with HTTP 403."""
        import jwt as pyjwt
        import time
        from fastapi import HTTPException

        tenant_token = pyjwt.encode(
            {
                "sub": "tenant_123",
                "tenant_id": "t-abc",
                "token_type": "tenant",
                "iat": int(time.time()),
                "exp": int(time.time()) + 3600,
            },
            os.environ["BORROWER_JWT_SECRET"],
            algorithm="HS256",
        )
        with pytest.raises(HTTPException) as exc_info:
            verify_borrower_token(tenant_token)
        assert exc_info.value.status_code == 403

    def test_expired_token_raises_401(self) -> None:
        import jwt as pyjwt
        import time
        from fastapi import HTTPException

        expired_token = pyjwt.encode(
            {
                "borrower_id": "b-exp",
                "tenant_id": "t-abc",
                "application_ids": [],
                "token_type": "borrower",
                "iat": int(time.time()) - 7200,
                "exp": int(time.time()) - 3600,
            },
            os.environ["BORROWER_JWT_SECRET"],
            algorithm="HS256",
        )
        with pytest.raises(HTTPException) as exc_info:
            verify_borrower_token(expired_token)
        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# Missing BORROWER_JWT_SECRET env var
# ---------------------------------------------------------------------------


def test_missing_env_var_raises() -> None:
    with patch.dict(os.environ, {}, clear=False):
        orig = os.environ.pop("BORROWER_JWT_SECRET", None)
        try:
            import importlib
            import decision_api.src.borrower_auth as ba_mod
            with pytest.raises((RuntimeError, Exception)):
                importlib.reload(ba_mod)
        finally:
            if orig is not None:
                os.environ["BORROWER_JWT_SECRET"] = orig
