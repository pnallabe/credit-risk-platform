"""
decision_engine/ab_testing.py
==============================
Statistical A/B Experimentation Framework (PRD §4.2.3, Phase 3)

Extends the basic champion/challenger PolicySplitStore with:

* Full Experiment lifecycle: DRAFT → RUNNING → PAUSED → COMPLETED
* Statistical significance (two-proportion z-test, configurable α)
* Guardrails: auto-halt when approval-rate or AIR diverges beyond threshold
* Multiple concurrent experiments with slot-conflict detection
* Experiment results exportable as model-validation evidence JSON/PDF
* Minimum detectable effect (MDE) and required sample-size calculator

Public API
----------
>>> from decision_engine.ab_testing import ABTestingFramework, Experiment
>>> fw = ABTestingFramework(db_url="sqlite:///./ab_tests.db")
>>> exp = fw.create_experiment(Experiment(name="pd_threshold_v3",  ...))
>>> fw.start_experiment(exp.experiment_id)
>>> result = fw.get_significance_report(exp.experiment_id)
>>> result.significant          # True/False
>>> result.p_value              # float
>>> result.recommendation       # "PROMOTE" | "HOLD" | "REJECT"
"""

from __future__ import annotations

import dataclasses
import json
import logging
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SIGNIFICANCE_ALPHA = 0.05        # default α for z-test
GUARDRAIL_APPROVAL_DELTA = 0.10  # halt if challenger approval drops > 10 pp
GUARDRAIL_AIR_DELTA = 0.05       # halt if challenger AIR drops > 5 pp below champion
MIN_SAMPLE_PER_ARM = 50          # require at least 50 decisions per arm before evaluating


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Experiment:
    """Describes one A/B experiment comparing two policy or model variants."""

    experiment_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    tenant_id: str = ""
    description: str = ""

    # Arm definitions
    control_version_tag: str = ""     # champion version
    treatment_version_tag: str = ""   # challenger version
    traffic_pct: float = 0.10         # fraction of traffic routed to treatment

    # Guardrail thresholds (overrides module-level defaults)
    guardrail_approval_delta: float = GUARDRAIL_APPROVAL_DELTA
    guardrail_air_delta: float = GUARDRAIL_AIR_DELTA

    # Statistical config
    significance_alpha: float = SIGNIFICANCE_ALPHA
    mde: float = 0.02                 # minimum detectable effect (approval rate pp)
    power: float = 0.80               # desired statistical power

    # Lifecycle
    status: Literal["DRAFT", "RUNNING", "PAUSED", "COMPLETED", "HALTED"] = "DRAFT"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: Optional[str] = None
    ended_at: Optional[str] = None

    # Metadata
    created_by: str = ""
    hypothesis: str = ""              # free-text scientific hypothesis
    primary_metric: str = "approval_rate"  # "approval_rate" | "air" | "apr"

    # Results snapshot (filled when experiment is concluded)
    results_snapshot: Optional[str] = None  # JSON


@dataclass
class ExperimentOutcomeRecord:
    """Single decision outcome attributed to an experiment arm."""

    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    experiment_id: str = ""
    application_id: str = ""
    tenant_id: str = ""
    arm: Literal["CONTROL", "TREATMENT"] = "CONTROL"
    decision: str = ""          # APPROVE | REJECT | MANUAL_REVIEW
    apr: Optional[float] = None
    credit_limit: Optional[float] = None
    # For AIR guardrail — optional demographic proxy
    is_minority_proxy: Optional[bool] = None
    recorded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class StatisticalSignificanceReport:
    """Result of a two-proportion z-test for one experiment."""

    experiment_id: str
    evaluated_at: str
    control_n: int
    treatment_n: int
    control_approval_rate: float
    treatment_approval_rate: float
    approval_rate_delta: float        # treatment - control
    z_score: float
    p_value: float
    confidence_interval_low: float   # 95% CI lower bound on delta
    confidence_interval_high: float  # 95% CI upper bound on delta
    significant: bool
    power_achieved: float            # estimated power given current n
    required_sample_size: int        # per arm to achieve desired power
    guardrail_triggered: bool
    guardrail_reason: str            # "" if not triggered
    recommendation: Literal["PROMOTE", "HOLD", "REJECT", "INSUFFICIENT_DATA"]

    # Fairness guardrail
    control_air: Optional[float] = None
    treatment_air: Optional[float] = None
    air_delta: Optional[float] = None

    # For evidence export
    export_evidence: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS ab_experiments (
    experiment_id          TEXT PRIMARY KEY,
    name                   TEXT NOT NULL,
    tenant_id              TEXT NOT NULL,
    description            TEXT,
    control_version_tag    TEXT NOT NULL,
    treatment_version_tag  TEXT NOT NULL,
    traffic_pct            REAL NOT NULL DEFAULT 0.10,
    guardrail_approval_delta REAL NOT NULL DEFAULT 0.10,
    guardrail_air_delta    REAL NOT NULL DEFAULT 0.05,
    significance_alpha     REAL NOT NULL DEFAULT 0.05,
    mde                    REAL NOT NULL DEFAULT 0.02,
    power                  REAL NOT NULL DEFAULT 0.80,
    status                 TEXT NOT NULL DEFAULT 'DRAFT',
    created_at             TEXT NOT NULL,
    started_at             TEXT,
    ended_at               TEXT,
    created_by             TEXT,
    hypothesis             TEXT,
    primary_metric         TEXT NOT NULL DEFAULT 'approval_rate',
    results_snapshot       TEXT
);

CREATE TABLE IF NOT EXISTS ab_experiment_outcomes (
    record_id          TEXT PRIMARY KEY,
    experiment_id      TEXT NOT NULL,
    application_id     TEXT NOT NULL,
    tenant_id          TEXT NOT NULL,
    arm                TEXT NOT NULL,
    decision           TEXT NOT NULL,
    apr                REAL,
    credit_limit       REAL,
    is_minority_proxy  INTEGER,
    recorded_at        TEXT NOT NULL,
    FOREIGN KEY (experiment_id) REFERENCES ab_experiments (experiment_id)
);

CREATE INDEX IF NOT EXISTS idx_ab_outcomes_exp
    ON ab_experiment_outcomes (experiment_id, arm);

CREATE INDEX IF NOT EXISTS idx_ab_experiments_tenant
    ON ab_experiments (tenant_id, status);
"""


# ---------------------------------------------------------------------------
# Statistical helpers
# ---------------------------------------------------------------------------


def _z_score_two_proportions(p1: float, n1: int, p2: float, n2: int) -> float:
    """Two-proportion z-score.  p1 = control, p2 = treatment."""
    if n1 == 0 or n2 == 0:
        return 0.0
    pooled_p = (p1 * n1 + p2 * n2) / (n1 + n2)
    se = math.sqrt(pooled_p * (1 - pooled_p) * (1 / n1 + 1 / n2))
    if se == 0.0:
        return 0.0
    return (p2 - p1) / se


def _p_value_from_z(z: float) -> float:
    """Two-tailed p-value from z-score using the error function."""
    from math import erfc, fabs
    return erfc(fabs(z) / math.sqrt(2))


def _confidence_interval(p1: float, n1: int, p2: float, n2: int, alpha: float = 0.05) -> Tuple[float, float]:
    """95% CI for the difference p2 - p1."""
    if n1 == 0 or n2 == 0:
        return (0.0, 0.0)
    from math import sqrt
    # z_crit for (1 - alpha/2) — using Φ^-1 approximation
    z_crit = _z_crit_from_alpha(alpha)
    se = sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    delta = p2 - p1
    return (delta - z_crit * se, delta + z_crit * se)


def _z_crit_from_alpha(alpha: float) -> float:
    """Return z-critical value for two-tailed test at *alpha* (no scipy dependency)."""
    # Common lookup table; fall back to 1.96 for 0.05
    _table = {0.10: 1.645, 0.05: 1.960, 0.02: 2.326, 0.01: 2.576}
    return _table.get(round(alpha, 3), 1.960)


def _required_sample_size(p_baseline: float, mde: float, alpha: float, power: float) -> int:
    """Sample size per arm (two-proportion z-test, two-tailed)."""
    p_alt = p_baseline + mde
    z_alpha = _z_crit_from_alpha(alpha)
    z_beta = _z_crit_from_alpha(1 - power)  # CDF inverse of beta; approximation only
    # Cohen's formula
    p_avg = (p_baseline + p_alt) / 2
    se_h0 = math.sqrt(2 * p_avg * (1 - p_avg))
    se_h1 = math.sqrt(p_baseline * (1 - p_baseline) + p_alt * (1 - p_alt))
    n = ((z_alpha * se_h0 + z_beta * se_h1) / mde) ** 2
    return max(int(math.ceil(n)), MIN_SAMPLE_PER_ARM)


def _achieved_power(p1: float, p2: float, n: int, alpha: float) -> float:
    """Estimate observed power given current sample size *n* per arm."""
    if n < 2:
        return 0.0
    z_crit = _z_crit_from_alpha(alpha)
    p_avg = (p1 + p2) / 2
    if p_avg == 0 or p_avg == 1:
        return 0.0
    se = math.sqrt(2 * p_avg * (1 - p_avg) / n)
    if se == 0:
        return 0.0
    delta = abs(p2 - p1)
    z_power = delta / se - z_crit
    # Φ(z_power) as a rough approximation
    return max(0.0, min(1.0, 0.5 * (1 + math.erf(z_power / math.sqrt(2)))))


# ---------------------------------------------------------------------------
# ABTestingFramework
# ---------------------------------------------------------------------------


class ABTestingFramework:
    """Manages the full lifecycle of A/B experiments for policy/model variants.

    Parameters
    ----------
    db_url : str
        SQLAlchemy-compatible database URL (SQLite or PostgreSQL).
    """

    def __init__(self, db_url: str = "sqlite:///./ab_tests.db") -> None:
        self.db_url = db_url
        self._engine = self._make_engine(db_url)
        self._init_schema()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_engine(db_url: str) -> Engine:
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
            for stmt in _DDL.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    conn.execute(text(stmt))

    @staticmethod
    def _utcnow() -> str:
        return datetime.now(timezone.utc).isoformat()

    # ------------------------------------------------------------------
    # Experiment CRUD
    # ------------------------------------------------------------------

    def create_experiment(self, exp: Experiment) -> Experiment:
        """Persist a new experiment in DRAFT state and return it."""
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO ab_experiments (
                        experiment_id, name, tenant_id, description,
                        control_version_tag, treatment_version_tag, traffic_pct,
                        guardrail_approval_delta, guardrail_air_delta,
                        significance_alpha, mde, power, status, created_at,
                        created_by, hypothesis, primary_metric
                    ) VALUES (
                        :experiment_id, :name, :tenant_id, :description,
                        :control_version_tag, :treatment_version_tag, :traffic_pct,
                        :guardrail_approval_delta, :guardrail_air_delta,
                        :significance_alpha, :mde, :power, 'DRAFT', :created_at,
                        :created_by, :hypothesis, :primary_metric
                    )
                    """
                ),
                {
                    "experiment_id": exp.experiment_id,
                    "name": exp.name,
                    "tenant_id": exp.tenant_id,
                    "description": exp.description,
                    "control_version_tag": exp.control_version_tag,
                    "treatment_version_tag": exp.treatment_version_tag,
                    "traffic_pct": exp.traffic_pct,
                    "guardrail_approval_delta": exp.guardrail_approval_delta,
                    "guardrail_air_delta": exp.guardrail_air_delta,
                    "significance_alpha": exp.significance_alpha,
                    "mde": exp.mde,
                    "power": exp.power,
                    "created_at": exp.created_at,
                    "created_by": exp.created_by,
                    "hypothesis": exp.hypothesis,
                    "primary_metric": exp.primary_metric,
                },
            )
        logger.info("Created experiment %s ('%s') for tenant %s", exp.experiment_id, exp.name, exp.tenant_id)
        return exp

    def start_experiment(self, experiment_id: str) -> None:
        """Transition DRAFT → RUNNING.  Raises ValueError if wrong state or slot conflict."""
        exp = self.get_experiment(experiment_id)
        if exp is None:
            raise ValueError(f"Experiment {experiment_id!r} not found")
        if exp.status not in ("DRAFT", "PAUSED"):
            raise ValueError(f"Cannot start experiment in status {exp.status!r}")

        # Slot conflict check: no other RUNNING experiment for same tenant + version tags
        self._check_no_conflict(exp)

        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE ab_experiments SET status='RUNNING', started_at=:ts WHERE experiment_id=:eid"
                ),
                {"ts": self._utcnow(), "eid": experiment_id},
            )
        logger.info("Started experiment %s", experiment_id)

    def pause_experiment(self, experiment_id: str) -> None:
        """Transition RUNNING → PAUSED."""
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE ab_experiments SET status='PAUSED' WHERE experiment_id=:eid AND status='RUNNING'"
                ),
                {"eid": experiment_id},
            )

    def halt_experiment(self, experiment_id: str, reason: str = "") -> None:
        """Transition any active status → HALTED (guardrail-triggered)."""
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE ab_experiments SET status='HALTED', ended_at=:ts WHERE experiment_id=:eid"
                ),
                {"ts": self._utcnow(), "eid": experiment_id},
            )
        logger.warning("Halted experiment %s — %s", experiment_id, reason)

    def complete_experiment(self, experiment_id: str, results_snapshot: Dict[str, Any]) -> None:
        """Transition RUNNING/PAUSED → COMPLETED, store results snapshot."""
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """UPDATE ab_experiments SET status='COMPLETED', ended_at=:ts,
                       results_snapshot=:snap WHERE experiment_id=:eid"""
                ),
                {
                    "ts": self._utcnow(),
                    "snap": json.dumps(results_snapshot, default=str),
                    "eid": experiment_id,
                },
            )
        logger.info("Completed experiment %s", experiment_id)

    def get_experiment(self, experiment_id: str) -> Optional[Experiment]:
        """Fetch experiment by ID, or None if not found."""
        with self._engine.begin() as conn:
            row = conn.execute(
                text("SELECT * FROM ab_experiments WHERE experiment_id=:eid"),
                {"eid": experiment_id},
            ).mappings().first()
        if row is None:
            return None
        return self._row_to_experiment(row)

    def list_experiments(
        self,
        tenant_id: str,
        status: Optional[str] = None,
    ) -> List[Experiment]:
        """Return experiments for a tenant, optionally filtered by status."""
        with self._engine.begin() as conn:
            if status:
                rows = conn.execute(
                    text(
                        "SELECT * FROM ab_experiments WHERE tenant_id=:tid AND status=:st ORDER BY created_at DESC"
                    ),
                    {"tid": tenant_id, "st": status},
                ).mappings().all()
            else:
                rows = conn.execute(
                    text(
                        "SELECT * FROM ab_experiments WHERE tenant_id=:tid ORDER BY created_at DESC"
                    ),
                    {"tid": tenant_id},
                ).mappings().all()
        return [self._row_to_experiment(r) for r in rows]

    # ------------------------------------------------------------------
    # Outcome recording
    # ------------------------------------------------------------------

    def record_outcome(self, outcome: ExperimentOutcomeRecord) -> None:
        """Append a decision outcome for an experiment arm."""
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO ab_experiment_outcomes (
                        record_id, experiment_id, application_id, tenant_id,
                        arm, decision, apr, credit_limit, is_minority_proxy, recorded_at
                    ) VALUES (
                        :record_id, :experiment_id, :application_id, :tenant_id,
                        :arm, :decision, :apr, :credit_limit, :is_minority_proxy, :recorded_at
                    )
                    """
                ),
                {
                    "record_id": outcome.record_id,
                    "experiment_id": outcome.experiment_id,
                    "application_id": outcome.application_id,
                    "tenant_id": outcome.tenant_id,
                    "arm": outcome.arm,
                    "decision": outcome.decision,
                    "apr": outcome.apr,
                    "credit_limit": outcome.credit_limit,
                    "is_minority_proxy": (
                        None if outcome.is_minority_proxy is None
                        else (1 if outcome.is_minority_proxy else 0)
                    ),
                    "recorded_at": outcome.recorded_at,
                },
            )

    # ------------------------------------------------------------------
    # Statistical analysis
    # ------------------------------------------------------------------

    def get_significance_report(
        self,
        experiment_id: str,
        auto_halt_on_guardrail: bool = True,
    ) -> StatisticalSignificanceReport:
        """Compute a full statistical significance report for the experiment.

        Optionally halts the experiment automatically if guardrails are breached.
        """
        exp = self.get_experiment(experiment_id)
        if exp is None:
            raise ValueError(f"Experiment {experiment_id!r} not found")

        with self._engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT arm, decision, is_minority_proxy
                    FROM ab_experiment_outcomes
                    WHERE experiment_id=:eid
                    """
                ),
                {"eid": experiment_id},
            ).mappings().all()

        control_rows = [r for r in rows if r["arm"] == "CONTROL"]
        treatment_rows = [r for r in rows if r["arm"] == "TREATMENT"]

        control_n = len(control_rows)
        treatment_n = len(treatment_rows)

        def _approval_rate(rs: list) -> float:
            if not rs:
                return 0.0
            return sum(1 for r in rs if str(r["decision"]).upper() == "APPROVE") / len(rs)

        control_ar = _approval_rate(control_rows)
        treatment_ar = _approval_rate(treatment_rows)
        delta = treatment_ar - control_ar

        # Require minimum sample before evaluating
        if control_n < MIN_SAMPLE_PER_ARM or treatment_n < MIN_SAMPLE_PER_ARM:
            req_n = _required_sample_size(max(control_ar, 0.01), exp.mde, exp.significance_alpha, exp.power)
            return StatisticalSignificanceReport(
                experiment_id=experiment_id,
                evaluated_at=self._utcnow(),
                control_n=control_n,
                treatment_n=treatment_n,
                control_approval_rate=control_ar,
                treatment_approval_rate=treatment_ar,
                approval_rate_delta=delta,
                z_score=0.0,
                p_value=1.0,
                confidence_interval_low=0.0,
                confidence_interval_high=0.0,
                significant=False,
                power_achieved=0.0,
                required_sample_size=req_n,
                guardrail_triggered=False,
                guardrail_reason="",
                recommendation="INSUFFICIENT_DATA",
            )

        z = _z_score_two_proportions(control_ar, control_n, treatment_ar, treatment_n)
        p = _p_value_from_z(z)
        ci_lo, ci_hi = _confidence_interval(control_ar, control_n, treatment_ar, treatment_n, exp.significance_alpha)
        significant = p < exp.significance_alpha
        power_achieved = _achieved_power(control_ar, treatment_ar, min(control_n, treatment_n), exp.significance_alpha)
        req_n = _required_sample_size(max(control_ar, 0.01), exp.mde, exp.significance_alpha, exp.power)

        # AIR computation (if demographic proxy data available)
        control_air: Optional[float] = None
        treatment_air: Optional[float] = None
        air_delta: Optional[float] = None

        def _air(rs: list) -> Optional[float]:
            """DIR = approval rate minority / approval rate non-minority."""
            minority_rows = [r for r in rs if r["is_minority_proxy"] == 1]
            majority_rows = [r for r in rs if r["is_minority_proxy"] == 0]
            if not minority_rows or not majority_rows:
                return None
            return _approval_rate(minority_rows) / max(_approval_rate(majority_rows), 1e-9)

        control_air = _air(control_rows)
        treatment_air = _air(treatment_rows)
        if control_air is not None and treatment_air is not None:
            air_delta = treatment_air - control_air

        # Guardrail check
        guardrail_triggered = False
        guardrail_reason = ""

        if delta < -exp.guardrail_approval_delta:
            guardrail_triggered = True
            guardrail_reason = (
                f"Challenger approval rate dropped {abs(delta):.1%} below control "
                f"(threshold {exp.guardrail_approval_delta:.1%})"
            )
        elif air_delta is not None and air_delta < -exp.guardrail_air_delta:
            guardrail_triggered = True
            guardrail_reason = (
                f"Challenger AIR dropped {abs(air_delta):.3f} below control "
                f"(threshold {exp.guardrail_air_delta:.3f})"
            )

        if guardrail_triggered and auto_halt_on_guardrail and exp.status == "RUNNING":
            self.halt_experiment(experiment_id, guardrail_reason)

        # Recommendation
        if guardrail_triggered:
            rec: Literal["PROMOTE", "HOLD", "REJECT", "INSUFFICIENT_DATA"] = "REJECT"
        elif significant and delta > 0:
            rec = "PROMOTE"
        elif significant and delta < -0.03:
            rec = "REJECT"
        else:
            rec = "HOLD"

        evidence = self._build_evidence_export(exp, {
            "control_n": control_n,
            "treatment_n": treatment_n,
            "control_approval_rate": control_ar,
            "treatment_approval_rate": treatment_ar,
            "approval_rate_delta": delta,
            "z_score": z,
            "p_value": p,
            "significant": significant,
            "recommendation": rec,
        })

        return StatisticalSignificanceReport(
            experiment_id=experiment_id,
            evaluated_at=self._utcnow(),
            control_n=control_n,
            treatment_n=treatment_n,
            control_approval_rate=control_ar,
            treatment_approval_rate=treatment_ar,
            approval_rate_delta=delta,
            z_score=z,
            p_value=p,
            confidence_interval_low=ci_lo,
            confidence_interval_high=ci_hi,
            significant=significant,
            power_achieved=power_achieved,
            required_sample_size=req_n,
            guardrail_triggered=guardrail_triggered,
            guardrail_reason=guardrail_reason,
            recommendation=rec,
            control_air=control_air,
            treatment_air=treatment_air,
            air_delta=air_delta,
            export_evidence=evidence,
        )

    def export_results_as_evidence(self, experiment_id: str) -> Dict[str, Any]:
        """Return a model-validation-ready evidence JSON for the experiment."""
        report = self.get_significance_report(experiment_id, auto_halt_on_guardrail=False)
        exp = self.get_experiment(experiment_id)
        return {
            "evidence_type": "AB_EXPERIMENT_RESULTS",
            "generated_at": self._utcnow(),
            "experiment": dataclasses.asdict(exp) if exp else {},
            "statistical_report": dataclasses.asdict(report),
            "validation_criteria": {
                "significance_alpha": exp.significance_alpha if exp else SIGNIFICANCE_ALPHA,
                "mde": exp.mde if exp else 0.02,
                "power": exp.power if exp else 0.80,
            },
        }

    def required_sample_size(self, experiment_id: str) -> int:
        """Return required sample size per arm for the experiment's MDE/power config."""
        exp = self.get_experiment(experiment_id)
        if exp is None:
            return MIN_SAMPLE_PER_ARM
        # Fetch current control approval rate as baseline
        with self._engine.begin() as conn:
            rows = conn.execute(
                text(
                    "SELECT decision FROM ab_experiment_outcomes WHERE experiment_id=:eid AND arm='CONTROL'"
                ),
                {"eid": experiment_id},
            ).mappings().all()
        n = len(rows)
        baseline = (
            sum(1 for r in rows if str(r["decision"]).upper() == "APPROVE") / max(n, 1)
        )
        return _required_sample_size(max(baseline, 0.01), exp.mde, exp.significance_alpha, exp.power)

    # ------------------------------------------------------------------
    # Conflict detection
    # ------------------------------------------------------------------

    def _check_no_conflict(self, exp: Experiment) -> None:
        """Raise ValueError if another RUNNING experiment overlaps on the same version tags."""
        running = self.list_experiments(exp.tenant_id, status="RUNNING")
        for other in running:
            if other.experiment_id == exp.experiment_id:
                continue
            overlap = (
                other.control_version_tag == exp.control_version_tag
                or other.treatment_version_tag == exp.treatment_version_tag
                or other.control_version_tag == exp.treatment_version_tag
                or other.treatment_version_tag == exp.control_version_tag
            )
            if overlap:
                raise ValueError(
                    f"Conflict: experiment {other.experiment_id!r} ('{other.name}') already "
                    f"uses version tags that overlap with this experiment for tenant {exp.tenant_id!r}. "
                    "Only one experiment per version-tag slot may run concurrently."
                )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_experiment(row: Any) -> Experiment:
        return Experiment(
            experiment_id=row["experiment_id"],
            name=row["name"],
            tenant_id=row["tenant_id"],
            description=row["description"] or "",
            control_version_tag=row["control_version_tag"],
            treatment_version_tag=row["treatment_version_tag"],
            traffic_pct=float(row["traffic_pct"]),
            guardrail_approval_delta=float(row["guardrail_approval_delta"]),
            guardrail_air_delta=float(row["guardrail_air_delta"]),
            significance_alpha=float(row["significance_alpha"]),
            mde=float(row["mde"]),
            power=float(row["power"]),
            status=row["status"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            created_by=row["created_by"] or "",
            hypothesis=row["hypothesis"] or "",
            primary_metric=row["primary_metric"],
            results_snapshot=row["results_snapshot"],
        )

    @staticmethod
    def _build_evidence_export(exp: Experiment, metrics: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "experiment_id": exp.experiment_id,
            "experiment_name": exp.name,
            "tenant_id": exp.tenant_id,
            "control_version": exp.control_version_tag,
            "treatment_version": exp.treatment_version_tag,
            "hypothesis": exp.hypothesis,
            "primary_metric": exp.primary_metric,
            "statistical_config": {
                "alpha": exp.significance_alpha,
                "mde": exp.mde,
                "desired_power": exp.power,
            },
            "results": metrics,
            "sr_11_7_aligned": True,
            "evidence_category": "model_validation",
        }
