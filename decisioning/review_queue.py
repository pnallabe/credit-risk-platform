from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, List, Literal, Optional

import pandas as pd
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.pool import StaticPool


@dataclass(frozen=True)
class ReviewItem:
    item_id: str
    application_id: str
    created_at: datetime
    sla_deadline: datetime
    status: Literal["PENDING", "UNDER_REVIEW", "COMPLETED", "SLA_BREACHED"]
    assigned_to: Optional[str]
    review_started_at: Optional[datetime]
    completed_at: Optional[datetime]
    override_decision: Optional[str]
    override_reason_code: Optional[str]
    override_notes: Optional[str]
    original_pd_score: float
    original_features: Dict


class ReviewReasonCode(str, Enum):
    INSUFFICIENT_INCOME = "INSUFFICIENT_INCOME"
    THIN_FILE = "THIN_FILE"
    FRAUD_INDICATORS = "FRAUD_INDICATORS"
    POLICY_EXCEPTION = "POLICY_EXCEPTION"
    INCORRECT_MODEL_INPUT = "INCORRECT_MODEL_INPUT"
    DATA_QUALITY_CONCERN = "DATA_QUALITY_CONCERN"
    MANUAL_ESCALATION = "MANUAL_ESCALATION"
    OTHER = "OTHER"


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS review_queue (
    item_id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    sla_deadline TEXT NOT NULL,
    status TEXT NOT NULL,
    assigned_to TEXT,
    review_started_at TEXT,
    completed_at TEXT,
    override_decision TEXT,
    override_reason_code TEXT,
    override_notes TEXT,
    original_pd_score REAL NOT NULL,
    original_features TEXT NOT NULL
);
"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _dt_to_str(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        raise ValueError("Datetimes must be timezone-aware (UTC)")
    return dt.astimezone(timezone.utc).isoformat()


def _str_to_dt(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        # Treat legacy as UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class ReviewQueue:
    """Human-in-the-loop queue for MANUAL_REVIEW decisions."""

    def __init__(self, db_url: str = "sqlite:///./audit/review_queue.db"):
        self.db_url = db_url
        self._engine = self._create_engine(db_url)
        self._init_schema()

    @staticmethod
    def _create_engine(db_url: str) -> Engine:
        if db_url.startswith("sqlite") and ":memory:" in db_url:
            return create_engine(
                db_url,
                future=True,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
        return create_engine(db_url, future=True)

    def _init_schema(self) -> None:
        with self._engine.begin() as conn:
            conn.execute(text(_CREATE_TABLE))

    def enqueue(
        self,
        application_id: str,
        pd_score: float,
        features: Dict,
        sla_hours: int = 24,
    ) -> ReviewItem:
        created_at = _utcnow()
        sla_deadline = created_at + timedelta(hours=int(sla_hours))
        item_id = str(uuid.uuid4())

        row = {
            "item_id": item_id,
            "application_id": str(application_id),
            "created_at": _dt_to_str(created_at),
            "sla_deadline": _dt_to_str(sla_deadline),
            "status": "PENDING",
            "assigned_to": None,
            "review_started_at": None,
            "completed_at": None,
            "override_decision": None,
            "override_reason_code": None,
            "override_notes": None,
            "original_pd_score": float(pd_score),
            "original_features": json.dumps(features, sort_keys=True),
        }

        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO review_queue (
                        item_id, application_id, created_at, sla_deadline, status,
                        assigned_to, review_started_at, completed_at,
                        override_decision, override_reason_code, override_notes,
                        original_pd_score, original_features
                    ) VALUES (
                        :item_id, :application_id, :created_at, :sla_deadline, :status,
                        :assigned_to, :review_started_at, :completed_at,
                        :override_decision, :override_reason_code, :override_notes,
                        :original_pd_score, :original_features
                    )
                    """
                ),
                row,
            )

        return self._row_to_item({**row, "original_features": row["original_features"]})

    def assign(self, item_id: str, reviewer_id: str) -> ReviewItem:
        now = _utcnow()
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE review_queue
                    SET status = 'UNDER_REVIEW', assigned_to = :assigned_to,
                        review_started_at = COALESCE(review_started_at, :review_started_at)
                    WHERE item_id = :item_id
                    """
                ),
                {
                    "item_id": str(item_id),
                    "assigned_to": str(reviewer_id),
                    "review_started_at": _dt_to_str(now),
                },
            )
        return self._get_item(item_id)

    def complete(
        self,
        item_id: str,
        override_decision: str,
        override_reason_code: str,
        notes: str = "",
    ) -> ReviewItem:
        allowed = {"APPROVE", "DECLINE", "REFER_TO_SENIOR"}
        if str(override_decision).upper() not in allowed:
            raise ValueError(f"override_decision must be one of {sorted(allowed)}")

        now = _utcnow()
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE review_queue
                    SET status = 'COMPLETED',
                        completed_at = :completed_at,
                        override_decision = :override_decision,
                        override_reason_code = :override_reason_code,
                        override_notes = :override_notes
                    WHERE item_id = :item_id
                    """
                ),
                {
                    "item_id": str(item_id),
                    "completed_at": _dt_to_str(now),
                    "override_decision": str(override_decision).upper(),
                    "override_reason_code": str(override_reason_code),
                    "override_notes": str(notes or ""),
                },
            )
        return self._get_item(item_id)

    def get_pending(self, limit: int = 50) -> List[ReviewItem]:
        with self._engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT * FROM review_queue
                    WHERE status = 'PENDING'
                    ORDER BY sla_deadline ASC
                    LIMIT :limit
                    """
                ),
                {"limit": int(limit)},
            ).mappings().all()

        return [self._row_to_item(dict(r)) for r in rows]

    def check_sla_breaches(self) -> List[ReviewItem]:
        now = _utcnow()
        with self._engine.begin() as conn:
            # Identify items newly breached
            rows = conn.execute(
                text(
                    """
                    SELECT item_id FROM review_queue
                    WHERE status IN ('PENDING', 'UNDER_REVIEW')
                                            AND sla_deadline <= :now
                    """
                ),
                {"now": _dt_to_str(now)},
            ).mappings().all()
            ids = [r["item_id"] for r in rows]

            if ids:
                for item_id in ids:
                    conn.execute(
                        text(
                            """
                            UPDATE review_queue
                            SET status = 'SLA_BREACHED'
                            WHERE item_id = :item_id
                            """
                        ),
                        {"item_id": str(item_id)},
                    )

        return [self._get_item(i) for i in ids]

    def export_feedback(self, output_path: Path) -> int:
        """Export completed overrides (final decisions only) for retraining feedback."""
        with self._engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT application_id, original_features, override_decision, completed_at
                    FROM review_queue
                    WHERE status = 'COMPLETED'
                      AND override_decision IN ('APPROVE', 'DECLINE')
                    """
                )
            ).mappings().all()

        payload = []
        for r in rows:
            payload.append(
                {
                    "application_id": r["application_id"],
                    "original_features": json.loads(r["original_features"]),
                    "override_decision": r["override_decision"],
                    "completed_at": r["completed_at"],
                }
            )

        df = pd.DataFrame(payload)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(output_path, index=False)
        return int(len(df))

    def _get_item(self, item_id: str) -> ReviewItem:
        with self._engine.begin() as conn:
            row = conn.execute(
                text("SELECT * FROM review_queue WHERE item_id = :item_id"),
                {"item_id": str(item_id)},
            ).mappings().first()
        if not row:
            raise KeyError(f"Review item not found: {item_id}")
        return self._row_to_item(dict(row))

    @staticmethod
    def _row_to_item(row: Dict) -> ReviewItem:
        return ReviewItem(
            item_id=str(row["item_id"]),
            application_id=str(row["application_id"]),
            created_at=_str_to_dt(row["created_at"]) or _utcnow(),
            sla_deadline=_str_to_dt(row["sla_deadline"]) or _utcnow(),
            status=row["status"],
            assigned_to=row.get("assigned_to"),
            review_started_at=_str_to_dt(row.get("review_started_at")),
            completed_at=_str_to_dt(row.get("completed_at")),
            override_decision=row.get("override_decision"),
            override_reason_code=row.get("override_reason_code"),
            override_notes=row.get("override_notes"),
            original_pd_score=float(row["original_pd_score"]),
            original_features=json.loads(row["original_features"]) if isinstance(row["original_features"], str) else dict(row["original_features"]),
        )
