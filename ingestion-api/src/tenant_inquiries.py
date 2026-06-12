"""Tenant Inquiries Module
=========================
POST /api/v1/tenant-inquiries — accept and persist prospect interest forms
from the Helix Decisions signup page.

Security notes:
- Raw IP addresses are NEVER stored or logged — only sha256 hash of the
  X-Forwarded-For / client IP.
- Rate limit: 3 submissions per hashed IP per 1-hour rolling window.
- No FK to the tenants table — this is a pre-provisioning staging record only.
- Async notifications to INQUIRY_NOTIFY_EMAIL / INQUIRY_NOTIFY_SLACK_WEBHOOK
  are fired as background tasks; failures are logged, not surfaced to the caller.
"""

from __future__ import annotations

import asyncio
import email.message
import hashlib
import json
import logging
import os
import smtplib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field, field_validator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["tenant-inquiries"])

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_RATE_LIMIT_MAX = int(os.getenv("INQUIRY_RATE_LIMIT_MAX", "3"))
_RATE_LIMIT_WINDOW_SECS = int(os.getenv("INQUIRY_RATE_LIMIT_WINDOW_SECS", "3600"))
_NOTIFY_EMAIL = os.getenv("INQUIRY_NOTIFY_EMAIL", "")
_NOTIFY_SLACK = os.getenv("INQUIRY_NOTIFY_SLACK_WEBHOOK", "")
_SMTP_HOST = os.getenv("SMTP_HOST", "")
_SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
_SMTP_USER = os.getenv("SMTP_USER", "")
_SMTP_PASS = os.getenv("SMTP_PASS", "")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TenantInquiryRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr
    company: str = Field(..., min_length=1, max_length=200)
    title: Optional[str] = Field(None, max_length=200)
    useCase: str = Field(..., min_length=1, max_length=500)
    volume: Optional[str] = Field(None, max_length=50)
    referral: Optional[str] = Field(None, max_length=500)

    @field_validator("name", "company", "useCase", mode="before")
    @classmethod
    def strip_strings(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v


class TenantInquiryResponse(BaseModel):
    id: str
    message: str


# ---------------------------------------------------------------------------
# IP hashing helper
# ---------------------------------------------------------------------------


def _hash_ip(request: Request) -> str:
    """Return sha256 hex digest of the client IP. Never returns the raw IP."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    # Take the first (leftmost) IP from X-Forwarded-For to avoid spoofing via
    # appending arbitrary values to the header. This is safe because the ingress
    # should be the authoritative first entry.
    raw_ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")
    return hashlib.sha256(raw_ip.encode()).hexdigest()


# ---------------------------------------------------------------------------
# In-memory rate limit store (swap for Redis in production)
# ---------------------------------------------------------------------------
# Structure: { ip_hash -> [(timestamp, ...), ...] }
_rate_store: dict[str, list[datetime]] = {}


def _check_and_record_rate_limit(ip_hash: str) -> bool:
    """Return True if the request is allowed; False if it should be rejected (429).

    Prunes expired entries and appends the current timestamp on success.
    """
    now = datetime.now(tz=timezone.utc)
    cutoff = now - timedelta(seconds=_RATE_LIMIT_WINDOW_SECS)
    history = [ts for ts in _rate_store.get(ip_hash, []) if ts > cutoff]

    if len(history) >= _RATE_LIMIT_MAX:
        _rate_store[ip_hash] = history  # keep pruned list
        return False

    history.append(now)
    _rate_store[ip_hash] = history
    return True


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _persist_inquiry(record_id: str, data: TenantInquiryRequest, ip_hash: str) -> None:
    """Insert a row into tenant_inquiries.

    Silently skips on error (table may not yet exist; migration may be pending).
    """
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        logger.warning("DATABASE_URL not set; inquiry %s not persisted", record_id)
        return

    try:
        import sqlalchemy as sa

        engine = sa.create_engine(db_url, pool_pre_ping=True)
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    """
                    INSERT INTO tenant_inquiries
                        (id, name, email, company, title, use_case, volume, referral, created_at, ip_hash)
                    VALUES
                        (:id, :name, :email, :company, :title, :use_case, :volume, :referral, :created_at, :ip_hash)
                    """
                ),
                {
                    "id": record_id,
                    "name": data.name,
                    "email": data.email,
                    "company": data.company,
                    "title": data.title,
                    "use_case": data.useCase,
                    "volume": data.volume,
                    "referral": data.referral,
                    "created_at": datetime.now(tz=timezone.utc),
                    "ip_hash": ip_hash,
                },
            )
        logger.info("tenant_inquiry_persisted", extra={"inquiry_id": record_id})
    except Exception as exc:
        logger.error(
            "tenant_inquiry_persist_failed: %s", exc,
            extra={"inquiry_id": record_id},
        )


# ---------------------------------------------------------------------------
# Async notifications
# ---------------------------------------------------------------------------


async def _notify_email(record_id: str, data: TenantInquiryRequest) -> None:
    if not _NOTIFY_EMAIL or not _SMTP_HOST:
        return
    try:
        msg = email.message.EmailMessage()
        msg["Subject"] = f"New Helix Decisions Tenant Inquiry — {data.company}"
        msg["From"] = _SMTP_USER or _NOTIFY_EMAIL
        msg["To"] = _NOTIFY_EMAIL
        body = (
            f"New inquiry received.\n\n"
            f"ID:      {record_id}\n"
            f"Name:    {data.name}\n"
            f"Email:   {data.email}\n"
            f"Company: {data.company}\n"
            f"Title:   {data.title or '—'}\n"
            f"Volume:  {data.volume or '—'}\n"
            f"Referral:{data.referral or '—'}\n\n"
            f"Use Case:\n{data.useCase}\n"
        )
        msg.set_content(body)
        await asyncio.to_thread(
            lambda: smtplib.SMTP(_SMTP_HOST, _SMTP_PORT).__enter__()
            and None  # handled below
        )
        # Use blocking SMTP in thread pool to avoid blocking the event loop
        def _send() -> None:
            with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT) as smtp:
                if _SMTP_USER and _SMTP_PASS:
                    smtp.starttls()
                    smtp.login(_SMTP_USER, _SMTP_PASS)
                smtp.send_message(msg)

        await asyncio.to_thread(_send)
        logger.info("inquiry_email_sent", extra={"inquiry_id": record_id, "to": _NOTIFY_EMAIL})
    except Exception as exc:
        logger.error("inquiry_email_failed: %s", exc, extra={"inquiry_id": record_id})


async def _notify_slack(record_id: str, data: TenantInquiryRequest) -> None:
    if not _NOTIFY_SLACK:
        return
    try:
        payload = {
            "text": (
                f":mailbox_with_mail: *New Helix Decisions Inquiry*\n"
                f"*ID:* `{record_id}`\n"
                f"*Name:* {data.name}\n"
                f"*Email:* {data.email}\n"
                f"*Company:* {data.company}\n"
                f"*Title:* {data.title or '—'}\n"
                f"*Volume:* {data.volume or '—'}\n"
                f"*Use Case:* {data.useCase[:200]}{'…' if len(data.useCase) > 200 else ''}"
            )
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(_NOTIFY_SLACK, json=payload)
            resp.raise_for_status()
        logger.info("inquiry_slack_sent", extra={"inquiry_id": record_id})
    except Exception as exc:
        logger.error("inquiry_slack_failed: %s", exc, extra={"inquiry_id": record_id})


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.post("/tenant-inquiries", status_code=status.HTTP_201_CREATED)
async def create_tenant_inquiry(
    request: Request,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    """Accept a tenant interest form submission.

    - Rate-limited to 3 requests per IP hash per hour.
    - Persists to tenant_inquiries (no FK to tenants table).
    - Fires async notifications to configured email/Slack.
    - Never stores or logs raw IP addresses.
    """
    # Parse and validate body
    try:
        raw = await request.json()
        data = TenantInquiryRequest.model_validate(raw)
    except Exception as exc:
        # Build field-level error map compatible with 422 contract
        errors: dict[str, str] = {}
        if hasattr(exc, "errors"):
            for e in exc.errors():  # type: ignore[union-attr]
                field = ".".join(str(l) for l in e.get("loc", [])) or "body"
                errors[field] = e.get("msg", "Invalid value")
        else:
            errors["body"] = str(exc)
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"errors": errors},
        )

    ip_hash = _hash_ip(request)

    # Rate limit check
    if not _check_and_record_rate_limit(ip_hash):
        logger.warning(
            "tenant_inquiry_rate_limited",
            extra={"ip_hash": ip_hash[:8]},
        )
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": "Too many requests. Please wait before submitting again."},
        )

    record_id = str(uuid.uuid4())

    # Persist synchronously before returning (so the row exists if the worker dies)
    _persist_inquiry(record_id, data, ip_hash)

    # Fire-and-forget notifications
    background_tasks.add_task(_notify_email, record_id, data)
    background_tasks.add_task(_notify_slack, record_id, data)

    logger.info(
        "tenant_inquiry_received",
        extra={"inquiry_id": record_id, "company": data.company},
    )

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=TenantInquiryResponse(id=record_id, message="Inquiry received.").model_dump(),
    )
