from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Literal, Optional

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.pool import StaticPool

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelConfig:
    role: Literal["CHAMPION", "CHALLENGER"]
    model_registry_name: str
    model_version: str
    traffic_pct: float
    active: bool = True


@dataclass(frozen=True)
class CCDecisionRecord:
    application_id: str
    timestamp: datetime
    role: str
    model_version: str
    pd_score: float
    decision: str
    credit_limit: Optional[float]
    apr: Optional[float]
    is_shadow: bool


@dataclass(frozen=True)
class ChallengerComparisonReport:
    period_start: date
    period_end: date
    champion_approval_rate: float
    challenger_approval_rate: float
    approval_rate_delta: float
    champion_mean_pd: float
    challenger_mean_pd: float
    sample_size_champion: int
    sample_size_challenger: int
    recommendation: Literal["PROMOTE", "HOLD", "REJECT"]


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS cc_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    role TEXT NOT NULL,
    model_version TEXT NOT NULL,
    pd_score REAL NOT NULL,
    decision TEXT NOT NULL,
    credit_limit REAL,
    apr REAL,
    is_shadow INTEGER NOT NULL
);
"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _dt_to_str(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return dt.astimezone(timezone.utc).isoformat()


def _str_to_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class CCDecisionStore:
    """Persist CCDecisionRecord to SQLite/Postgres via SQLAlchemy (sync)."""

    def __init__(self, db_url: str = "sqlite:///./audit/cc_decisions.db"):
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

    def add(self, record: CCDecisionRecord) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO cc_decisions (
                        application_id, timestamp, role, model_version,
                        pd_score, decision, credit_limit, apr, is_shadow
                    ) VALUES (
                        :application_id, :timestamp, :role, :model_version,
                        :pd_score, :decision, :credit_limit, :apr, :is_shadow
                    )
                    """
                ),
                {
                    "application_id": record.application_id,
                    "timestamp": _dt_to_str(record.timestamp),
                    "role": record.role,
                    "model_version": record.model_version,
                    "pd_score": float(record.pd_score),
                    "decision": str(record.decision),
                    "credit_limit": None if record.credit_limit is None else float(record.credit_limit),
                    "apr": None if record.apr is None else float(record.apr),
                    "is_shadow": 1 if record.is_shadow else 0,
                },
            )

    def generate_comparison_report(self, lookback_days: int = 7) -> ChallengerComparisonReport:
        end = _utcnow().date()
        start = end - timedelta(days=int(lookback_days))
        start_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)

        with self._engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT role, pd_score, decision
                    FROM cc_decisions
                    WHERE timestamp >= :start_ts
                    """
                ),
                {"start_ts": _dt_to_str(start_dt)},
            ).mappings().all()

        champ = [r for r in rows if str(r["role"]).upper() == "CHAMPION"]
        chall = [r for r in rows if str(r["role"]).upper() == "CHALLENGER"]

        def _approval_rate(rs) -> float:
            if not rs:
                return 0.0
            return sum(1 for r in rs if str(r["decision"]).upper() == "APPROVE") / len(rs)

        def _mean_pd(rs) -> float:
            if not rs:
                return 0.0
            return sum(float(r["pd_score"]) for r in rs) / len(rs)

        champ_ar = _approval_rate(champ)
        chall_ar = _approval_rate(chall)
        champ_pd = _mean_pd(champ)
        chall_pd = _mean_pd(chall)

        approval_delta = chall_ar - champ_ar

        # Recommendation logic per prompt + explicit risk-reject guard.
        if (abs(approval_delta) <= 0.03) and (champ_pd == 0.0 or chall_pd <= champ_pd * 1.05):
            rec: Literal["PROMOTE", "HOLD", "REJECT"] = "PROMOTE"
        elif (chall_pd > champ_pd * 1.10) and (approval_delta >= 0.05):
            rec = "REJECT"
        else:
            rec = "HOLD"

        return ChallengerComparisonReport(
            period_start=start,
            period_end=end,
            champion_approval_rate=float(champ_ar),
            challenger_approval_rate=float(chall_ar),
            approval_rate_delta=float(approval_delta),
            champion_mean_pd=float(champ_pd),
            challenger_mean_pd=float(chall_pd),
            sample_size_champion=int(len(champ)),
            sample_size_challenger=int(len(chall)),
            recommendation=rec,
        )


class ChampionChallengerRouter:
    def __init__(
        self,
        champion: ModelConfig,
        challenger: Optional[ModelConfig],
        store: CCDecisionStore,
        random_seed: Optional[int] = None,
    ):
        if champion.role != "CHAMPION":
            raise ValueError("champion.role must be CHAMPION")
        if challenger is not None and challenger.role != "CHALLENGER":
            raise ValueError("challenger.role must be CHALLENGER")

        self.champion = champion
        self.challenger = challenger
        self.store = store
        self.salt = "default" if random_seed is None else str(int(random_seed))

    def route(self, application_id: str) -> Literal["CHAMPION", "CHALLENGER"]:
        if not self.challenger or not self.challenger.active or self.challenger.traffic_pct <= 0.0:
            return "CHAMPION"

        traffic = float(self.challenger.traffic_pct)
        traffic = max(0.0, min(1.0, traffic))

        h = hashlib.sha256(f"{application_id}:{self.salt}".encode("utf-8")).digest()
        bucket = int.from_bytes(h[:8], "big") % 100
        return "CHALLENGER" if bucket < int(traffic * 100) else "CHAMPION"

    def _score_to_record(
        self,
        application_id: str,
        role: str,
        model_version: str,
        score: Dict,
        is_shadow: bool,
    ) -> CCDecisionRecord:
        pd_score = float(score.get("pd_score", score.get("risk_score", 0.0)))
        decision = str(score.get("decision", "UNKNOWN"))
        credit_limit = score.get("credit_limit")
        apr = score.get("apr")

        return CCDecisionRecord(
            application_id=str(application_id),
            timestamp=_utcnow(),
            role=str(role),
            model_version=str(model_version),
            pd_score=float(pd_score),
            decision=decision,
            credit_limit=None if credit_limit is None else float(credit_limit),
            apr=None if apr is None else float(apr),
            is_shadow=bool(is_shadow),
        )

    def run_both_shadow(
        self,
        application_id: str,
        features: Dict,
        score_fn: Callable[[Dict, str], Dict],
    ) -> CCDecisionRecord:
        champ_score = score_fn(features, self.champion.model_version)
        champ_rec = self._score_to_record(
            application_id,
            role="CHAMPION",
            model_version=self.champion.model_version,
            score=champ_score,
            is_shadow=False,
        )
        self.store.add(champ_rec)

        if self.challenger and self.challenger.active:
            chall_score = score_fn(features, self.challenger.model_version)
            chall_rec = self._score_to_record(
                application_id,
                role="CHALLENGER",
                model_version=self.challenger.model_version,
                score=chall_score,
                is_shadow=True,
            )
            self.store.add(chall_rec)

        return champ_rec

    def run_live_split(
        self,
        application_id: str,
        features: Dict,
        score_fn: Callable[[Dict, str], Dict],
    ) -> CCDecisionRecord:
        routed = self.route(application_id)

        if routed == "CHALLENGER" and self.challenger and self.challenger.active:
            score = score_fn(features, self.challenger.model_version)
            rec = self._score_to_record(
                application_id,
                role="CHALLENGER",
                model_version=self.challenger.model_version,
                score=score,
                is_shadow=False,
            )
            self.store.add(rec)
            return rec

        score = score_fn(features, self.champion.model_version)
        rec = self._score_to_record(
            application_id,
            role="CHAMPION",
            model_version=self.champion.model_version,
            score=score,
            is_shadow=False,
        )
        self.store.add(rec)
        return rec

    def promote_champion(
        self,
        new_champion_run_id: str,
        model_doc_config: "Optional[object]" = None,
        docs_output_dir: str = "docs/mdr",
        audit_logger=None,
    ) -> Dict:
        """Promote the challenger model identified by *new_champion_run_id* to champion.

        Steps
        -----
        1. Validate *new_champion_run_id* exists in the MLflow registry.
           If ``mlflow`` is not available, skip validation with a warning.
        2. Call ``generate_mdr()`` to produce an SR 11-7–compliant MDR.
        3. Validate MDR via ``validate_mdr_completeness()`` — warn if incomplete
           but do not block promotion.
        4. Write MDR markdown + JSON files to *docs_output_dir*.
        5. Update internal champion state so *new_champion_run_id* is active.
        6. Build a promotion audit record dict.
        7. Call ``audit_logger.log_portfolio_action()`` when provided.
        8. Return the promotion audit record.

        Parameters
        ----------
        new_champion_run_id:
            MLflow run ID (or unique model identifier) of the model to promote.
        model_doc_config:
            Optional pre-built ``ModelDocumentationConfig``. If None, a minimal
            config is constructed automatically.
        docs_output_dir:
            Directory path where MDR files are written.
        audit_logger:
            Optional audit logger instance with ``log_portfolio_action()`` or
            ``log_decision()`` method.

        Returns
        -------
        dict
            Promotion audit record.
        """
        # ── 1. Validate against MLflow (best-effort) ──────────────────────
        try:
            import mlflow  # noqa: PLC0415
            client = mlflow.tracking.MlflowClient()
            _run = client.get_run(new_champion_run_id)
            logger.info("MLflow run validated: %s", new_champion_run_id)
        except ImportError:
            logger.warning("mlflow not installed — skipping run_id validation for %s", new_champion_run_id)
        except Exception as exc:
            logger.warning("MLflow validation failed for %s (non-blocking): %s", new_champion_run_id, exc)

        # ── 2. Build config if not provided ────────────────────────────────
        from compliance.generate_model_doc import (  # noqa: PLC0415
            ModelDocumentationConfig,
            generate_mdr,
            validate_mdr_completeness,
            MDRValidationError,
            mdr_to_markdown,
            mdr_to_json,
        )

        if model_doc_config is None:
            model_doc_config = ModelDocumentationConfig(
                model_name="cc_pd_model",
                version=new_champion_run_id[:8],
                use_case="Credit Card Probability of Default",
                owner="Risk Analytics",
                reviewer="Model Risk Management",
                approver="Chief Risk Officer",
                intended_population="US credit card applicants",
            )

        # ── 3. Generate MDR ────────────────────────────────────────────────
        mdr = None
        completeness_ok = False
        mdr_write_error: Optional[str] = None

        try:
            mdr = generate_mdr(config=model_doc_config, run_id=new_champion_run_id)
            try:
                validate_mdr_completeness(mdr)
                completeness_ok = True
            except MDRValidationError as ve:
                logger.warning("MDR completeness check failed (non-blocking): %s", ve)
        except Exception as exc:
            logger.error("generate_mdr() failed: %s", exc)
            mdr_write_error = str(exc)

        # ── 4. Write MDR files ─────────────────────────────────────────────
        md_path: Optional[Path] = None
        json_path: Optional[Path] = None

        if mdr is not None:
            try:
                out_dir = Path(docs_output_dir)
                out_dir.mkdir(parents=True, exist_ok=True)
                slug = new_champion_run_id[:8]
                md_path   = out_dir / f"mdr_{slug}.md"
                json_path = out_dir / f"mdr_{slug}.json"
                md_path.write_text(mdr_to_markdown(mdr),  encoding="utf-8")
                json_path.write_text(mdr_to_json(mdr),    encoding="utf-8")
                logger.info("MDR written: %s, %s", md_path, json_path)
            except Exception as exc:
                logger.error("MDR write failed: %s", exc)
                mdr_write_error = str(exc)
                md_path = None
                json_path = None

        # ── 5. Update champion state ───────────────────────────────────────
        try:
            new_model_config = ModelConfig(
                role="CHAMPION",
                model_registry_name=self.champion.model_registry_name,
                model_version=new_champion_run_id,
                traffic_pct=self.champion.traffic_pct,
                active=True,
            )
            object.__setattr__(self, "champion", new_model_config)
        except Exception as exc:
            logger.warning("Could not update champion state in-memory: %s", exc)

        # ── 6. Build promotion audit record ───────────────────────────────
        promotion_record: Dict = {
            "event": "CHAMPION_PROMOTED",
            "promoted_run_id": new_champion_run_id,
            "mdr_md_path": str(md_path) if md_path else None,
            "mdr_json_path": str(json_path) if json_path else None,
            "mdr_completeness_passed": completeness_ok,
            "promoted_at": datetime.utcnow().isoformat() + "Z",
        }
        if mdr_write_error:
            promotion_record["mdr_write_error"] = mdr_write_error

        # ── 7. Audit log ───────────────────────────────────────────────────
        if audit_logger is not None:
            try:
                if hasattr(audit_logger, "log_portfolio_action"):
                    audit_logger.log_portfolio_action(promotion_record)
                elif hasattr(audit_logger, "log_decision"):
                    audit_logger.log_decision(promotion_record)
                else:
                    logger.warning(
                        "audit_logger has no recognised log method; record not persisted"
                    )
            except Exception as exc:
                logger.warning("audit_logger call failed: %s", exc)

        return promotion_record
