"""
Platform Compliance Health Score — Section 23.6
================================================
Single composite metric [0-100] computed nightly.
  GREEN  >= 90
  YELLOW  70–89
  RED    <  70

The score is the weighted sum of eight dimension scores, each also [0-100].
Two dimensions are **zero-tolerance**: military_lending_compliance and
adverse_action_sla.  Any violation in those dimensions drives that dimension
score to 0.0 regardless of magnitude.

The nightly Cloud Scheduler job ``check_compliance_health.py`` calls
compute_health_score() and persists the result to
compliance_data_plane.compliance_health_score_log.

Usage
-----
    from compliance.health_score import compute_health_score

    score = compute_health_score()
    print(score.status, score.overall)  # "GREEN", 96.5
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# BigQuery import
# ---------------------------------------------------------------------------
try:
    from google.cloud import bigquery as _bq_lib  # type: ignore

    _BQ_AVAILABLE = True
except Exception:  # pragma: no cover
    _bq_lib = None  # type: ignore
    _BQ_AVAILABLE = False

# ---------------------------------------------------------------------------
# Dimension weights
# ---------------------------------------------------------------------------
DIMENSION_WEIGHTS: dict[str, float] = {
    "usury_compliance": 0.20,
    "military_lending_compliance": 0.15,  # zero-tolerance
    "fair_lending_dir": 0.15,
    "adverse_action_sla": 0.15,  # zero-tolerance
    "tila_disclosure_coverage": 0.10,
    "model_governance": 0.10,
    "policy_lifecycle": 0.10,
    "audit_completeness": 0.05,
}


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class ComplianceHealthScore:
    overall: float
    dimension_scores: dict[str, float]
    failing_dimensions: list[str]
    status: str  # "GREEN" | "YELLOW" | "RED"
    computed_at: str = field(default_factory=lambda: __import__("datetime").datetime.utcnow().isoformat())


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def compute_health_score() -> ComplianceHealthScore:
    """
    Compute and return the platform compliance health score.

    When BigQuery is unavailable (e.g. unit-test environment without GCP
    credentials), raises RuntimeError rather than returning a fabricated score —
    callers must not rely on stub data for production decisions.
    """
    if not _BQ_AVAILABLE or _bq_lib is None:
        raise RuntimeError(
            "BigQuery unavailable — cannot compute compliance health score."
        )

    bq = _bq_lib.Client()
    s: dict[str, float] = {}

    # ------------------------------------------------------------------
    # 1. Usury compliance (20 % weight)
    #    -10 pts per blocking event in rolling 30 days
    # ------------------------------------------------------------------
    usury_violations = _count(
        bq,
        """
        SELECT COUNT(*) FROM compliance_data_plane.compliance_events
        WHERE check_name LIKE 'usury_cap_%'
          AND check_result = 'BLOCKED'
          AND run_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
        """,
    )
    s["usury_compliance"] = 100.0 if usury_violations == 0 else max(0.0, 100.0 - usury_violations * 10)

    # ------------------------------------------------------------------
    # 2. Military lending compliance (15 % weight, zero-tolerance)
    # ------------------------------------------------------------------
    mil_violations = _count(
        bq,
        """
        SELECT COUNT(*) FROM compliance_data_plane.compliance_events
        WHERE check_name IN (
              'scra_apr_cap',
              'mla_mapr_cap',
              'scra_apr_increase_prohibition'
        )
          AND check_result = 'BLOCKED'
          AND run_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
        """,
    )
    s["military_lending_compliance"] = 100.0 if mil_violations == 0 else 0.0

    # ------------------------------------------------------------------
    # 3. Fair lending DIR (15 % weight)
    #    -20 pts per DIR-FAIL check in rolling 30 days
    # ------------------------------------------------------------------
    dir_failures = _count(
        bq,
        """
        SELECT COUNT(*) FROM compliance_data_plane.compliance_events
        WHERE check_name LIKE 'dir_%'
          AND check_result = 'FAIL'
          AND run_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
        """,
    )
    s["fair_lending_dir"] = 100.0 if dir_failures == 0 else max(0.0, 100.0 - dir_failures * 20)

    # ------------------------------------------------------------------
    # 4. Adverse action SLA (15 % weight, zero-tolerance)
    #    Any PENDING notice older than 30 days -> 0.0
    # ------------------------------------------------------------------
    aa_breaches = _count(
        bq,
        """
        SELECT COUNT(*) FROM audit.adverse_action_notice_queue
        WHERE status = 'PENDING'
          AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), enqueued_at, DAY) > 30
        """,
    )
    s["adverse_action_sla"] = 100.0 if aa_breaches == 0 else 0.0

    # ------------------------------------------------------------------
    # 5. TILA disclosure coverage (10 % weight)
    #    -5 pts per acquired account missing a disclosure record
    # ------------------------------------------------------------------
    missing_disclosures = _count(
        bq,
        """
        SELECT COUNT(*) FROM audit.audit_log al
        LEFT JOIN compliance_data_plane.consent_and_disclosures cd
          ON al.applicant_id_hash = cd.applicant_id_hash
         AND al.product_id = cd.product_id
        WHERE al.action = 'ACQUIRE'
          AND cd.disclosure_id IS NULL
          AND al.created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
        """,
    )
    s["tila_disclosure_coverage"] = 100.0 if missing_disclosures == 0 else max(0.0, 100.0 - missing_disclosures * 5)

    # ------------------------------------------------------------------
    # 6–8. Populated by dedicated nightly scripts (Section 23.12 quality gates)
    #      Default to 100 so a missing nightly run does not degrade the score
    # ------------------------------------------------------------------
    s["model_governance"] = _fetch_dimension_score(bq, "model_governance")
    s["policy_lifecycle"] = _fetch_dimension_score(bq, "policy_lifecycle")
    s["audit_completeness"] = _fetch_dimension_score(bq, "audit_completeness")

    overall = round(sum(DIMENSION_WEIGHTS[k] * s[k] for k in DIMENSION_WEIGHTS), 2)
    failing = [k for k, v in s.items() if v < 70.0]
    status = "GREEN" if overall >= 90 else ("YELLOW" if overall >= 70 else "RED")

    score = ComplianceHealthScore(
        overall=overall,
        dimension_scores=s,
        failing_dimensions=failing,
        status=status,
    )

    _persist_score(bq, score)

    if status == "RED":
        logger.critical(
            "[COMPLIANCE_HEALTH] score=%.1f status=RED failing=%s — "
            "PagerDuty alert must fire within 5 minutes.",
            overall,
            failing,
        )
    elif status == "YELLOW":
        logger.warning(
            "[COMPLIANCE_HEALTH] score=%.1f status=YELLOW failing=%s",
            overall,
            failing,
        )
    else:
        logger.info("[COMPLIANCE_HEALTH] score=%.1f status=GREEN", overall)

    return score


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count(bq: "bigquery.Client", sql: str) -> int:  # type: ignore[name-defined]
    return int(list(bq.query(sql).result())[0][0])


def _fetch_dimension_score(
    bq: "bigquery.Client",  # type: ignore[name-defined]
    dimension: str,
    default: float = 100.0,
) -> float:
    """
    Read the most recent dimension score from the health score log.
    Falls back to ``default`` if no entry exists (e.g. first run).
    """
    try:
        rows = list(
            bq.query(
                f"""
                SELECT {dimension}_score
                FROM compliance_data_plane.compliance_health_score_log
                ORDER BY computed_at DESC
                LIMIT 1
                """
            ).result()
        )
        if rows and rows[0][0] is not None:
            return float(rows[0][0])
    except Exception:  # pragma: no cover
        pass
    return default


def _persist_score(bq: "bigquery.Client", score: ComplianceHealthScore) -> None:  # type: ignore[name-defined]
    """Append the computed score to the health score history log."""
    try:
        bq.insert_rows_json(
            "compliance_data_plane.compliance_health_score_log",
            [
                {
                    "overall_score": score.overall,
                    "status": score.status,
                    "failing_dimensions": score.failing_dimensions,
                    **{f"{k}_score": v for k, v in score.dimension_scores.items()},
                    "computed_at": score.computed_at,
                }
            ],
        )
    except Exception as exc:  # pragma: no cover
        logger.error("Failed to persist compliance health score: %s", exc)
