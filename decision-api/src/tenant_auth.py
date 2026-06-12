"""Tenant Auth Module
===================
Provides GET /api/v1/tenants/me — returns the list of tenant memberships
for the authenticated Firebase user.

Firebase ID tokens are validated via the firebase-admin SDK. The decoded
UID is used to look up the tenant_members table.

Security:
- Token must be passed as `Authorization: Bearer <firebase-id-token>`.
- Raw UIDs are never exposed in error responses.
- Returns 200 with empty list (not 404) when no memberships are found.
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])

_bearer = HTTPBearer(auto_error=False)

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TenantMembership(BaseModel):
    tenantSlug: str
    status: str
    role: str


# ---------------------------------------------------------------------------
# Firebase token verification (optional dependency — graceful if not installed)
# ---------------------------------------------------------------------------


def _verify_firebase_token(token: str) -> dict:
    """Verify a Firebase ID token. Raises ValueError on failure."""
    try:
        import firebase_admin
        from firebase_admin import auth, credentials

        if not firebase_admin._apps:
            creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
            if creds_path and os.path.isfile(creds_path):
                cred = credentials.Certificate(creds_path)
                firebase_admin.initialize_app(cred)
            else:
                firebase_admin.initialize_app()

        return auth.verify_id_token(token)  # type: ignore[return-value]
    except ImportError:
        logger.error("firebase-admin not installed; cannot verify Firebase token")
        raise ValueError("firebase-admin package not available")
    except Exception as exc:
        logger.warning("Firebase token verification failed: %s", exc)
        raise ValueError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Tenant membership lookup
# ---------------------------------------------------------------------------


def _lookup_tenant_memberships(firebase_uid: str) -> List[TenantMembership]:
    """Look up tenant_members rows for the given Firebase UID.

    Uses a direct SQLite/Postgres connection via DATABASE_URL env var.
    Falls back to an empty list if the table does not yet exist (safe
    during initial deployment before migration is applied).
    """
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        logger.warning(
            "DATABASE_URL not set; returning empty membership list",
            extra={"uid_hash": hashlib.sha256(firebase_uid.encode()).hexdigest()[:8]},
        )
        return []

    try:
        import sqlalchemy as sa

        engine = sa.create_engine(db_url, pool_pre_ping=True)
        with engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    """
                    SELECT t.slug AS tenant_slug, tm.status, tm.role
                    FROM tenant_members tm
                    JOIN tenants t ON tm.tenant_id = t.id
                    WHERE tm.firebase_uid = :uid
                    ORDER BY tm.created_at ASC
                    """
                ),
                {"uid": firebase_uid},
            ).fetchall()
        return [
            TenantMembership(tenantSlug=row[0], status=row[1], role=row[2])
            for row in rows
        ]
    except Exception as exc:
        # Table may not yet exist during initial deploy; treat as empty membership.
        logger.warning(
            "tenant_members lookup failed (table may not exist yet): %s", exc,
            extra={"uid_hash": hashlib.sha256(firebase_uid.encode()).hexdigest()[:8]},
        )
        return []


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.get("/me", response_model=List[TenantMembership])
async def get_tenant_memberships(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(_bearer),
) -> List[TenantMembership]:
    """Return the list of tenant memberships for the authenticated Firebase user.

    Authentication:
        ``Authorization: Bearer <firebase-id-token>``

    Returns:
        200 with ``[]`` when the user has no memberships (never 404).
        401 when the token is missing or invalid.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    try:
        claims = _verify_firebase_token(token)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired Firebase token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    firebase_uid: str = claims.get("uid") or claims.get("user_id", "")
    if not firebase_uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing uid claim",
        )

    memberships = _lookup_tenant_memberships(firebase_uid)
    logger.info(
        "tenant_memberships_fetched",
        extra={
            "uid_hash": hashlib.sha256(firebase_uid.encode()).hexdigest()[:8],
            "count": len(memberships),
        },
    )
    return memberships
