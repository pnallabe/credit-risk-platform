"""Policy-Level Champion/Challenger A/B Testing — data layer.

This module provides:
- PolicyChallengerConfig   — config dataclass for a CHAMPION or CHALLENGER policy version
- PolicyDecisionRecord     — immutable record written after each policy decision
- PolicyComparisonReport   — aggregate comparison between champion and challenger
- PolicySplitStore         — synchronous SQLAlchemy store (SQLite / Postgres)
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, Literal, Optional, Tuple

_log = logging.getLogger(__name__)

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.pool import StaticPool


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PolicyChallengerConfig:
    """Configuration for one side of a policy A/B split."""

    role: Literal["CHAMPION", "CHALLENGER"]
    version_id: int
    version_tag: str
    traffic_pct: float
    tenant_id: str
    active: bool = True


@dataclass(frozen=True)
class PolicyDecisionRecord:
    """Immutable outcome record for a single policy-routed decision."""

    application_id: str
    timestamp: datetime
    tenant_id: str
    role: str
    version_id: int
    version_tag: str
    decision: str
    apr: Optional[float]
    credit_limit: Optional[float]
    is_shadow: bool


@dataclass
class PolicyComparisonReport:
    """Aggregate comparison summary for a champion/challenger policy split."""

    period_start: date
    period_end: date
    tenant_id: str
    champion_version_tag: str
    challenger_version_tag: str
    champion_approval_rate: float
    challenger_approval_rate: float
    approval_rate_delta: float
    sample_size_champion: int
    sample_size_challenger: int
    recommendation: Literal["PROMOTE", "HOLD", "REJECT"]


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_CREATE_POLICY_DECISIONS_TABLE = """
CREATE TABLE IF NOT EXISTS policy_decisions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id   TEXT    NOT NULL,
    timestamp        TEXT    NOT NULL,
    tenant_id        TEXT    NOT NULL,
    role             TEXT    NOT NULL,
    version_id       INTEGER NOT NULL,
    version_tag      TEXT    NOT NULL,
    decision         TEXT    NOT NULL,
    apr              REAL,
    credit_limit     REAL,
    is_shadow        INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pd_tenant_ts
    ON policy_decisions (tenant_id, timestamp);
"""

_CREATE_POLICY_SPLITS_TABLE = """
CREATE TABLE IF NOT EXISTS policy_splits (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       TEXT    NOT NULL,
    role            TEXT    NOT NULL,
    version_id      INTEGER NOT NULL,
    version_tag     TEXT    NOT NULL,
    traffic_pct     REAL    NOT NULL,
    active          INTEGER NOT NULL DEFAULT 1
);
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _dt_to_str(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return dt.astimezone(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# PolicySplitStore
# ---------------------------------------------------------------------------


class PolicySplitStore:
    """Persist PolicyDecisionRecord and PolicyChallengerConfig to SQLite/Postgres (sync)."""

    def __init__(self, db_url: str = "sqlite:///./policy_challenger.db"):
        self.db_url = db_url
        self._engine = self._create_engine(db_url)
        self._init_schema()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

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
            # Execute each statement separately because some drivers don't
            # support multiple statements in a single execute() call.
            for stmt in _CREATE_POLICY_DECISIONS_TABLE.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    conn.execute(text(stmt))
            for stmt in _CREATE_POLICY_SPLITS_TABLE.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    conn.execute(text(stmt))

    # ------------------------------------------------------------------
    # Write decision record
    # ------------------------------------------------------------------

    def add(self, record: PolicyDecisionRecord) -> None:
        """Persist a policy decision record."""
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO policy_decisions (
                        application_id, timestamp, tenant_id, role,
                        version_id, version_tag, decision, apr,
                        credit_limit, is_shadow
                    ) VALUES (
                        :application_id, :timestamp, :tenant_id, :role,
                        :version_id, :version_tag, :decision, :apr,
                        :credit_limit, :is_shadow
                    )
                    """
                ),
                {
                    "application_id": str(record.application_id),
                    "timestamp": _dt_to_str(record.timestamp),
                    "tenant_id": str(record.tenant_id),
                    "role": str(record.role),
                    "version_id": int(record.version_id),
                    "version_tag": str(record.version_tag),
                    "decision": str(record.decision),
                    "apr": None if record.apr is None else float(record.apr),
                    "credit_limit": None if record.credit_limit is None else float(record.credit_limit),
                    "is_shadow": 1 if record.is_shadow else 0,
                },
            )

    # ------------------------------------------------------------------
    # Comparison report
    # ------------------------------------------------------------------

    def generate_comparison_report(
        self, tenant_id: str, lookback_days: int = 7
    ) -> PolicyComparisonReport:
        """Compute approval-rate comparison for the active split of *tenant_id*."""
        end = _utcnow().date()
        start = end - timedelta(days=int(lookback_days))
        start_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)

        with self._engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT role, version_tag, decision
                    FROM policy_decisions
                    WHERE tenant_id = :tenant_id
                      AND timestamp >= :start_ts
                    """
                ),
                {"tenant_id": tenant_id, "start_ts": _dt_to_str(start_dt)},
            ).mappings().all()

        champ = [r for r in rows if str(r["role"]).upper() == "CHAMPION"]
        chall = [r for r in rows if str(r["role"]).upper() == "CHALLENGER"]

        def _approval_rate(rs) -> float:
            if not rs:
                return 0.0
            return sum(1 for r in rs if str(r["decision"]).upper() == "APPROVE") / len(rs)

        champ_ar = _approval_rate(champ)
        chall_ar = _approval_rate(chall)
        approval_delta = chall_ar - champ_ar

        # Recommendation: promote if challenger roughly matches champion (±3 pp)
        # and no significant uplift risk; reject if challenger degrades approval
        # by more than 10 pp; otherwise hold.
        if abs(approval_delta) <= 0.03:
            rec: Literal["PROMOTE", "HOLD", "REJECT"] = "PROMOTE"
        elif approval_delta < -0.10:
            rec = "REJECT"
        else:
            rec = "HOLD"

        # Derive version tags from split config if available
        champ_tag = champ[0]["version_tag"] if champ else ""
        chall_tag = chall[0]["version_tag"] if chall else ""

        return PolicyComparisonReport(
            period_start=start,
            period_end=end,
            tenant_id=tenant_id,
            champion_version_tag=champ_tag,
            challenger_version_tag=chall_tag,
            champion_approval_rate=float(champ_ar),
            challenger_approval_rate=float(chall_ar),
            approval_rate_delta=float(approval_delta),
            sample_size_champion=int(len(champ)),
            sample_size_challenger=int(len(chall)),
            recommendation=rec,
        )

    # ------------------------------------------------------------------
    # Split management
    # ------------------------------------------------------------------

    def get_active_split(
        self, tenant_id: str
    ) -> Optional[Tuple[PolicyChallengerConfig, PolicyChallengerConfig]]:
        """Return (champion, challenger) for *tenant_id*, or None if not configured."""
        with self._engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT role, version_id, version_tag, traffic_pct
                    FROM policy_splits
                    WHERE tenant_id = :tenant_id AND active = 1
                    ORDER BY role
                    """
                ),
                {"tenant_id": tenant_id},
            ).mappings().all()

        champion: Optional[PolicyChallengerConfig] = None
        challenger: Optional[PolicyChallengerConfig] = None

        for row in rows:
            cfg = PolicyChallengerConfig(
                role=str(row["role"]).upper(),  # type: ignore[arg-type]
                version_id=int(row["version_id"]),
                version_tag=str(row["version_tag"]),
                traffic_pct=float(row["traffic_pct"]),
                tenant_id=tenant_id,
                active=True,
            )
            if cfg.role == "CHAMPION":
                champion = cfg
            elif cfg.role == "CHALLENGER":
                challenger = cfg

        if champion is None or challenger is None:
            return None
        return (champion, challenger)

    def set_split(
        self,
        champion: PolicyChallengerConfig,
        challenger: PolicyChallengerConfig,
    ) -> None:
        """Activate a new champion/challenger split.

        Deactivates any existing active split for *tenant_id* before inserting
        the new pair.

        Raises:
            ValueError: if champion and challenger belong to different tenants,
                        or if roles are incorrect.
        """
        if champion.tenant_id != challenger.tenant_id:
            raise ValueError(
                f"champion.tenant_id ({champion.tenant_id!r}) != "
                f"challenger.tenant_id ({challenger.tenant_id!r})"
            )
        if str(champion.role).upper() != "CHAMPION":
            raise ValueError(f"Expected role CHAMPION, got {champion.role!r}")
        if str(challenger.role).upper() != "CHALLENGER":
            raise ValueError(f"Expected role CHALLENGER, got {challenger.role!r}")

        tenant_id = champion.tenant_id

        with self._engine.begin() as conn:
            # Deactivate previous split for this tenant
            conn.execute(
                text(
                    "UPDATE policy_splits SET active = 0 WHERE tenant_id = :tenant_id AND active = 1"
                ),
                {"tenant_id": tenant_id},
            )

            # Insert champion
            conn.execute(
                text(
                    """
                    INSERT INTO policy_splits (tenant_id, role, version_id, version_tag, traffic_pct, active)
                    VALUES (:tenant_id, :role, :version_id, :version_tag, :traffic_pct, 1)
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "role": "CHAMPION",
                    "version_id": int(champion.version_id),
                    "version_tag": str(champion.version_tag),
                    "traffic_pct": float(champion.traffic_pct),
                },
            )

            # Insert challenger
            conn.execute(
                text(
                    """
                    INSERT INTO policy_splits (tenant_id, role, version_id, version_tag, traffic_pct, active)
                    VALUES (:tenant_id, :role, :version_id, :version_tag, :traffic_pct, 1)
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "role": "CHALLENGER",
                    "version_id": int(challenger.version_id),
                    "version_tag": str(challenger.version_tag),
                    "traffic_pct": float(challenger.traffic_pct),
                },
            )

# ---------------------------------------------------------------------------
# PolicyChallengerRouter
# ---------------------------------------------------------------------------


class PolicyChallengerRouter:
    """SHA-256-based deterministic router for policy-level A/B splits.

    Uses namespace ``"policy"`` in the hash pre-image to avoid collision with
    the model-level ``ChampionChallengerRouter`` which uses ``":default"`` /
    ``":<seed>"``.

    Parameters
    ----------
    store:
        A ``PolicySplitStore`` instance for persistence.
    random_seed:
        Optional integer seed.  When provided, used as the salt string so that
        routing is reproducible in tests.
    """

    def __init__(
        self,
        store: PolicySplitStore,
        random_seed: Optional[int] = None,
    ) -> None:
        self.store = store
        self.salt = "default" if random_seed is None else str(int(random_seed))

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def _bucket(self, application_id: str) -> int:
        """Return a deterministic bucket [0..99] for *application_id*."""
        h = hashlib.sha256(
            f"{application_id}:policy:{self.salt}".encode("utf-8")
        ).digest()
        return int.from_bytes(h[:8], "big") % 100

    def route(self, application_id: str, tenant_id: str) -> Literal["CHAMPION", "CHALLENGER"]:
        """Return which side of the split *application_id* is routed to.

        Falls back to CHAMPION when no active split is configured or when the
        challenger traffic percentage is zero.
        """
        split = self.store.get_active_split(tenant_id)
        if split is None:
            return "CHAMPION"
        _, chall = split
        if not chall.active or chall.traffic_pct <= 0.0:
            return "CHAMPION"

        traffic = max(0.0, min(1.0, float(chall.traffic_pct)))
        bucket = self._bucket(application_id)
        return "CHALLENGER" if bucket < int(traffic * 100) else "CHAMPION"

    # ------------------------------------------------------------------
    # Policy parameter lookup
    # ------------------------------------------------------------------

    def get_policy_params(
        self,
        tenant_id: str,
        role: Literal["CHAMPION", "CHALLENGER"],
    ) -> Optional[PolicyChallengerConfig]:
        """Return the active ``PolicyChallengerConfig`` for *role*."""
        split = self.store.get_active_split(tenant_id)
        if split is None:
            return None
        champ, chall = split
        return champ if role == "CHAMPION" else chall

    # ------------------------------------------------------------------
    # Outcome recording
    # ------------------------------------------------------------------

    def record_outcome(
        self,
        application_id: str,
        tenant_id: str,
        role: str,
        version_id: int,
        version_tag: str,
        outcome: Dict[str, Any],
        is_shadow: bool = False,
    ) -> PolicyDecisionRecord:
        """Build and persist a ``PolicyDecisionRecord`` from a raw outcome dict.

        *outcome* keys recognised: ``decision``, ``apr``, ``credit_limit``.
        """
        record = PolicyDecisionRecord(
            application_id=str(application_id),
            timestamp=_utcnow(),
            tenant_id=str(tenant_id),
            role=str(role),
            version_id=int(version_id),
            version_tag=str(version_tag),
            decision=str(outcome.get("decision", "UNKNOWN")),
            apr=None if outcome.get("apr") is None else float(outcome["apr"]),
            credit_limit=(
                None
                if outcome.get("credit_limit") is None
                else float(outcome["credit_limit"])
            ),
            is_shadow=bool(is_shadow),
        )
        self.store.add(record)
        return record

    # ------------------------------------------------------------------
    # Split management helpers
    # ------------------------------------------------------------------

    def promote_challenger(self, tenant_id: str) -> Tuple[PolicyChallengerConfig, PolicyChallengerConfig]:
        """Promote the current challenger to champion.

        Builds a new split where:
        - the old challenger becomes the new champion (traffic_pct = 1.0)
        - a placeholder challenger entry with 0% traffic is created so the
          schema invariant (always two rows) is preserved.

        Returns the newly activated ``(new_champion, placeholder_challenger)``.

        Raises:
            ValueError: if no active split exists for *tenant_id*.
        """
        split = self.store.get_active_split(tenant_id)
        if split is None:
            raise ValueError(f"No active split found for tenant {tenant_id!r}")

        _, old_chall = split

        new_champ = PolicyChallengerConfig(
            role="CHAMPION",
            version_id=old_chall.version_id,
            version_tag=old_chall.version_tag,
            traffic_pct=1.0,
            tenant_id=tenant_id,
            active=True,
        )
        placeholder_chall = PolicyChallengerConfig(
            role="CHALLENGER",
            version_id=old_chall.version_id,
            version_tag=old_chall.version_tag + "-placeholder",
            traffic_pct=0.0,
            tenant_id=tenant_id,
            active=True,
        )
        self.store.set_split(new_champ, placeholder_chall)
        _log.info(
            "Promoted challenger %s to champion for tenant %s",
            old_chall.version_tag,
            tenant_id,
        )
        return (new_champ, placeholder_chall)

    def auto_rollback_if_regressed(
        self,
        tenant_id: str,
        lookback_days: int = 7,
    ) -> Dict[str, Any]:
        """Generate a comparison report; roll back to champion-only if REJECT.

        Returns a dict with keys ``rolled_back: bool`` and ``report``.
        """
        report = self.store.generate_comparison_report(tenant_id, lookback_days)
        rolled_back = False

        if report.recommendation == "REJECT":
            split = self.store.get_active_split(tenant_id)
            if split is not None:
                old_champ, _ = split
                # Re-activate champion at 100% traffic with zero-traffic challenger
                rollback_champ = PolicyChallengerConfig(
                    role="CHAMPION",
                    version_id=old_champ.version_id,
                    version_tag=old_champ.version_tag,
                    traffic_pct=1.0,
                    tenant_id=tenant_id,
                    active=True,
                )
                rollback_chall = PolicyChallengerConfig(
                    role="CHALLENGER",
                    version_id=old_champ.version_id,
                    version_tag=old_champ.version_tag + "-rollback",
                    traffic_pct=0.0,
                    tenant_id=tenant_id,
                    active=True,
                )
                self.store.set_split(rollback_champ, rollback_chall)
                rolled_back = True
                _log.warning(
                    "Auto-rollback triggered for tenant %s (challenger regressed)",
                    tenant_id,
                )

        return {"rolled_back": rolled_back, "report": report}
