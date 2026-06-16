"""
Borrower Auth Module
====================
Manages borrower-scoped JWTs that are distinct from the tenant-scoped internal
JWTs used by ``verify_bearer()`` in ``main.py``.

Borrower tokens are issued by the lender's backend and grant the holder
read-only access to a specific set of application IDs on a single tenant.

Public API
----------
>>> from borrower_auth import issue_borrower_token, verify_borrower_token, get_borrower
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JWT secret (separate from main JWT_SECRET to protect tenant credentials)
# ---------------------------------------------------------------------------

_BORROWER_JWT_ALGORITHM = "HS256"

bearer_scheme = HTTPBearer(auto_error=False)


def _get_borrower_secret() -> str:
    """Return the BORROWER_JWT_SECRET or raise RuntimeError if unset."""
    secret = os.getenv("BORROWER_JWT_SECRET", "")
    if not secret:
        raise RuntimeError(
            "[BORROWER_AUTH] BORROWER_JWT_SECRET environment variable is not set. "
            "Set a strong secret before issuing borrower tokens."
        )
    return secret


# ---------------------------------------------------------------------------
# Payload dataclass
# ---------------------------------------------------------------------------


@dataclass
class BorrowerTokenPayload:
    """Claims extracted from a borrower JWT.

    Attributes
    ----------
    borrower_id:
        Opaque per-borrower UUID.
    tenant_id:
        Which lender's portal issued this token.
    application_ids:
        List of application IDs this borrower may access.
    issued_at:
        ISO-8601 UTC timestamp.
    expires_at:
        ISO-8601 UTC timestamp.
    """

    borrower_id: str
    tenant_id: str
    application_ids: List[str]
    issued_at: str
    expires_at: str


# ---------------------------------------------------------------------------
# Token issuance
# ---------------------------------------------------------------------------


def issue_borrower_token(
    borrower_id: str,
    tenant_id: str,
    application_ids: List[str],
    ttl_hours: int = 72,
) -> str:
    """Issue a borrower-scoped JWT.

    Parameters
    ----------
    borrower_id:
        Opaque identifier for the borrower (UUID).
    tenant_id:
        Lender tenant that owns these applications.
    application_ids:
        List of application IDs the borrower is permitted to view.
    ttl_hours:
        Token lifetime in hours (default 72).

    Returns
    -------
    str
        Signed JWT string.

    Raises
    ------
    RuntimeError
        If BORROWER_JWT_SECRET is not set.
    """
    import jwt  # noqa: PLC0415

    secret = _get_borrower_secret()
    now = datetime.now(timezone.utc)
    exp = now + timedelta(hours=ttl_hours)

    payload = {
        "borrower_id": borrower_id,
        "tenant_id": tenant_id,
        "application_ids": application_ids,
        "token_type": "borrower",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "issued_at": now.isoformat(),
        "expires_at": exp.isoformat(),
    }
    return jwt.encode(payload, secret, algorithm=_BORROWER_JWT_ALGORITHM)


# ---------------------------------------------------------------------------
# Token verification
# ---------------------------------------------------------------------------


def verify_borrower_token(token: str) -> BorrowerTokenPayload:
    """Decode and validate a borrower JWT.

    Parameters
    ----------
    token:
        Raw JWT string from Authorization header.

    Returns
    -------
    BorrowerTokenPayload

    Raises
    ------
    HTTPException(401):
        If the token is invalid or expired.
    HTTPException(403):
        If ``token_type != "borrower"`` (prevents tenant JWTs from being
        used as borrower tokens).
    """
    import jwt  # noqa: PLC0415
    from jwt import ExpiredSignatureError, InvalidTokenError  # noqa: PLC0415

    try:
        secret = _get_borrower_secret()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    try:
        payload = jwt.decode(token, secret, algorithms=[_BORROWER_JWT_ALGORITHM])
    except ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Borrower token has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid borrower token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    # Enforce token_type — prevent tenant JWTs from being used here
    if payload.get("token_type") != "borrower":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Forbidden: this endpoint requires a borrower token. "
                "Tenant credentials are not accepted here."
            ),
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    return BorrowerTokenPayload(
        borrower_id=payload.get("borrower_id", ""),
        tenant_id=payload.get("tenant_id", ""),
        application_ids=payload.get("application_ids", []),
        issued_at=payload.get("issued_at", now_iso),
        expires_at=payload.get("expires_at", now_iso),
    )


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


async def get_borrower(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
) -> BorrowerTokenPayload:
    """FastAPI dependency: verify borrower JWT from Authorization header.

    Equivalent of ``verify_bearer()`` for the borrower portal.

    Raises
    ------
    HTTPException(401):
        If credential is missing or invalid.
    HTTPException(403):
        If a non-borrower token is presented.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return verify_borrower_token(credentials.credentials)
