"""
Fair Lending Analysis Module
============================
Computes ECOA/HMDA-compliant fair lending metrics from a decisions DataFrame
that includes a demographic group column.

Metrics computed
----------------
1. Disparate Impact Ratio (DIR)
   DIR = Approval rate (protected group) / Approval rate (control group)
   Flag if DIR < 0.80 (4/5ths rule)

2. Approval Parity
   Chi-squared test for independence between demographic_group and decision.
   Flag if p_value < 0.05.

3. Geographic Bias
   Compare approval rates by state; flag states with rate > 1.5σ from mean.

BISG Proxy Auto-Detection (P1.5)
---------------------------------
When ``decisions_df`` does NOT contain a ``demographic_group`` column (or the
requested *protected_col* is absent) but DOES contain both a ``surname`` and a
``census_tract`` column, the module automatically applies the BISG proxy
methodology (see ``monitoring.bisg``) to estimate race/ethnicity.  The
``FairLendingReport`` will include ``proxy_methodology="BISG"`` to satisfy
CFPB examination requirements for voluntary-basis or indirect lending.

Public API
----------
>>> from monitoring.fair_lending import analyze_fair_lending, FairLendingReport
>>> report = analyze_fair_lending(decisions_df, "race", "white")
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency


class _NumpyEncoder(json.JSONEncoder):
    """JSON encoder that converts numpy scalar types to native Python types."""

    def default(self, obj: object) -> object:  # type: ignore[override]
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.integer):
            return int(obj)  # type: ignore[arg-type]
        if isinstance(obj, np.floating):
            return float(obj)  # type: ignore[arg-type]
        return super().default(obj)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

DIR_THRESHOLD = 0.80         # 4/5ths rule: DIR below this → flag
PARITY_ALPHA = 0.05          # chi-squared significance level
GEO_STDDEV_MULTIPLIER = 1.5  # flag states this many σ below national rate


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class FairLendingReport:
    """Full fair lending analysis report.

    Attributes
    ----------
    dir_score:
        Disparate Impact Ratio (protected / control approval rate).
    dir_flag:
        True if dir_score < DIR_THRESHOLD (potential bias signal).
    protected_group:
        Name of the protected demographic group analysed.
    control_group:
        Name of the control demographic group.
    protected_approval_rate:
        Approval rate for the protected group (0–1).
    control_approval_rate:
        Approval rate for the control group (0–1).
    approval_parity_p_value:
        P-value from chi-squared test on group × decision contingency table.
    approval_parity_flag:
        True if p_value < PARITY_ALPHA.
    geographic_flags:
        List of state codes whose approval rates are > 1.5σ below national mean.
    state_approval_rates:
        Dict mapping state code → approval rate for all states.
    summary_text:
        Human-readable summary.
    report_timestamp:
        ISO timestamp of report generation.
    n_total:
        Total number of decisions analysed.
    n_approved:
        Total approved decisions.
    """

    dir_score: Optional[float] = None
    dir_flag: bool = False
    protected_group: str = ""
    control_group: str = ""
    protected_approval_rate: float = 0.0
    control_approval_rate: float = 0.0
    approval_parity_p_value: Optional[float] = None
    approval_parity_flag: bool = False
    geographic_flags: List[str] = field(default_factory=list)
    state_approval_rates: Dict[str, float] = field(default_factory=dict)
    summary_text: str = ""
    report_timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    n_total: int = 0
    n_approved: int = 0
    # ── P1.5: BISG proxy fields ──────────────────────────────────────────────
    proxy_methodology: Optional[str] = None  # "BISG" | "self_reported" | None
    proxy_applied: bool = False              # True when BISG was auto-applied
    weighted_dir_calculation: Optional[float] = None  # probability-weighted DIR


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compute_approval_rate(df: pd.DataFrame, decision_col: str = "decision") -> float:
    """Compute the fraction of rows with decision == 'APPROVE'."""
    if len(df) == 0:
        return 0.0
    return float((df[decision_col].str.upper() == "APPROVE").mean())


def _compute_dir(
    decisions_df: pd.DataFrame,
    protected_col: str,
    protected_group: str,
    control_group: str,
    decision_col: str = "decision",
) -> tuple[float | None, float, float]:
    """Compute DIR, protected_rate, control_rate."""
    prot = decisions_df[decisions_df[protected_col] == protected_group]
    ctrl = decisions_df[decisions_df[protected_col] == control_group]

    prot_rate = _compute_approval_rate(prot, decision_col)
    ctrl_rate = _compute_approval_rate(ctrl, decision_col)

    if ctrl_rate == 0:
        logger.warning("Control group has 0% approval rate; DIR undefined")
        return None, prot_rate, ctrl_rate

    return round(prot_rate / ctrl_rate, 4), prot_rate, ctrl_rate


def _compute_approval_parity(
    decisions_df: pd.DataFrame,
    protected_col: str,
    decision_col: str = "decision",
) -> tuple[float | None, bool]:
    """Chi-squared test: independence between demographic_group and decision."""
    try:
        contingency = pd.crosstab(
            decisions_df[protected_col],
            decisions_df[decision_col].str.upper(),
        )
        if contingency.shape[0] < 2 or contingency.shape[1] < 2:
            return None, False

        _, p_value, _, _ = chi2_contingency(contingency)
        return round(float(p_value), 6), bool(p_value < PARITY_ALPHA)
    except Exception as exc:
        logger.warning("Chi-squared test failed: %s", exc)
        return None, False


def _compute_geographic_flags(
    decisions_df: pd.DataFrame,
    state_col: str = "state",
    decision_col: str = "decision",
) -> tuple[List[str], Dict[str, float]]:
    """Flag states whose approval rate is > 1.5σ below the national mean."""
    if state_col not in decisions_df.columns:
        return [], {}

    state_rates: Dict[str, float] = {}
    for state, group in decisions_df.groupby(state_col):
        state_rates[str(state)] = _compute_approval_rate(group, decision_col)

    if not state_rates:
        return [], {}

    rates = np.array(list(state_rates.values()))
    mean_rate = float(np.mean(rates))
    std_rate = float(np.std(rates))

    if std_rate == 0:
        return [], state_rates

    flagged = [
        state for state, rate in state_rates.items()
        if (mean_rate - rate) > GEO_STDDEV_MULTIPLIER * std_rate
    ]
    return sorted(flagged), {k: round(v, 4) for k, v in state_rates.items()}


def _build_summary_text(report: FairLendingReport) -> str:
    lines = [
        f"Fair Lending Analysis — {report.report_timestamp[:10]}",
        f"Total Decisions: {report.n_total} | Approved: {report.n_approved}",
        "",
        f"Disparate Impact Ratio (DIR): {report.dir_score:.4f}" if report.dir_score else "DIR: N/A",
        f"  Protected group ({report.protected_group}): {report.protected_approval_rate:.1%}",
        f"  Control group ({report.control_group}): {report.control_approval_rate:.1%}",
        f"  Status: {'⚠ FLAG (DIR < 0.80)' if report.dir_flag else '✓ PASS'}",
        "",
        f"Approval Parity (Chi-squared p-value): {report.approval_parity_p_value}",
        f"  Status: {'⚠ FLAG (p < 0.05)' if report.approval_parity_flag else '✓ PASS'}",
        "",
    ]
    if report.geographic_flags:
        lines.append(f"Geographic flags (approval < 1.5σ below mean): {', '.join(report.geographic_flags)}")
    else:
        lines.append("Geographic analysis: No states flagged.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze_fair_lending(
    decisions_df: pd.DataFrame,
    protected_col: str,
    control_group: str,
    decision_col: str = "decision",
    state_col: str = "state",
    output_dir: Optional[str] = None,
    surname_col: str = "surname",
    tract_col: str = "census_tract",
    # GAP-12: optional persistence kwargs
    db_url: Optional[str] = None,
    tenant_id: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> FairLendingReport:
    """Run a full fair lending analysis on a decisions DataFrame.

    Parameters
    ----------
    decisions_df:
        DataFrame with at least a ``decision`` column containing
        ``"APPROVE"``, ``"REJECT"``, or ``"MANUAL_REVIEW"`` strings,
        and a column named *protected_col*.
    protected_col:
        Column name containing the demographic group label
        (e.g., ``"race"``, ``"zip_group"``, ``"income_band"``).
        If this column is absent but *surname_col* and *tract_col* are
        present, BISG proxy will be applied automatically.
    control_group:
        The value in *protected_col* that represents the reference group
        (e.g., ``"white"``, ``"high_income"``).
    decision_col:
        Column containing decision strings.  Defaults to ``"decision"``.
    state_col:
        Column containing US state codes for geographic analysis.
        Defaults to ``"state"``.
    output_dir:
        If provided, saves the report as JSON to
        ``{output_dir}/fair_lending_{date}.json``.
    surname_col:
        Column name for applicant surnames (used for BISG proxy).
    tract_col:
        Column name for census tracts (used for BISG proxy).

    Returns
    -------
    FairLendingReport
    """
    if decision_col not in decisions_df.columns:
        raise ValueError(f"Decision column '{decision_col}' not found in DataFrame.")

    # ── P1.5: Auto-apply BISG proxy when protected_col is absent ──────────
    proxy_applied = False
    proxy_methodology: Optional[str] = None
    working_df = decisions_df.copy()

    if protected_col not in working_df.columns:
        if surname_col in working_df.columns:
            logger.info(
                "Column '%s' not found; auto-applying BISG proxy using '%s' and '%s'.",
                protected_col, surname_col, tract_col,
            )
            from monitoring.bisg import add_bisg_columns
            working_df = add_bisg_columns(
                working_df,
                surname_col=surname_col,
                tract_col=tract_col if tract_col in working_df.columns else None,
            )
            # Map BISG proxy_group → protected_col
            working_df[protected_col] = working_df["proxy_group"]
            proxy_applied = True
            proxy_methodology = "BISG"
        else:
            raise ValueError(
                f"Protected column '{protected_col}' not found in DataFrame, "
                f"and no '{surname_col}' column available for BISG proxy."
            )
    else:
        proxy_methodology = "self_reported"

    # Identify protected group (all groups != control_group)
    unique_groups = working_df[protected_col].dropna().unique().tolist()
    protected_groups = [g for g in unique_groups if str(g) != control_group]
    if not protected_groups:
        raise ValueError(f"No protected groups found (all values == '{control_group}').")

    # Use first non-control group as the primary protected group for DIR
    primary_protected = str(protected_groups[0])

    n_total = len(working_df)
    n_approved = int((working_df[decision_col].str.upper() == "APPROVE").sum())

    # DIR
    dir_score, prot_rate, ctrl_rate = _compute_dir(
        working_df, protected_col, primary_protected, control_group, decision_col
    )

    # Approval parity
    p_value, parity_flag = _compute_approval_parity(working_df, protected_col, decision_col)

    # Geographic flags
    geo_flags, state_rates = _compute_geographic_flags(working_df, state_col, decision_col)

    # ── P1.5: Probability-weighted DIR (BISG only) ─────────────────────────
    weighted_dir: Optional[float] = None
    if proxy_applied:
        from monitoring.bisg import RACE_COLS
        ctrl_col = f"bisg_{control_group}" if f"bisg_{control_group}" in working_df.columns else None
        prot_col = f"bisg_{primary_protected}" if f"bisg_{primary_protected}" in working_df.columns else None
        if ctrl_col and prot_col and decision_col in working_df.columns:
            approved_mask = working_df[decision_col].str.upper() == "APPROVE"
            w_prot_approved = float(
                (working_df.loc[approved_mask, prot_col]).sum()
            )
            w_prot_total = float(working_df[prot_col].sum())
            w_ctrl_approved = float(
                (working_df.loc[approved_mask, ctrl_col]).sum()
            )
            w_ctrl_total = float(working_df[ctrl_col].sum())
            if w_ctrl_total > 0 and w_prot_total > 0 and w_ctrl_approved > 0:
                w_prot_rate = w_prot_approved / w_prot_total
                w_ctrl_rate = w_ctrl_approved / w_ctrl_total
                weighted_dir = round(w_prot_rate / w_ctrl_rate, 4) if w_ctrl_rate > 0 else None

    report = FairLendingReport(
        dir_score=dir_score,
        dir_flag=dir_score is not None and dir_score < DIR_THRESHOLD,
        protected_group=primary_protected,
        control_group=control_group,
        protected_approval_rate=prot_rate,
        control_approval_rate=ctrl_rate,
        approval_parity_p_value=p_value,
        approval_parity_flag=parity_flag,
        geographic_flags=geo_flags,
        state_approval_rates=state_rates,
        n_total=n_total,
        n_approved=n_approved,
        proxy_methodology=proxy_methodology,
        proxy_applied=proxy_applied,
        weighted_dir_calculation=weighted_dir,
    )
    report.summary_text = _build_summary_text(report)

    logger.info(
        "Fair lending analysis complete: DIR=%.4f (flag=%s), p-value=%.4f (flag=%s), proxy=%s",
        dir_score if dir_score else -1,
        report.dir_flag,
        p_value if p_value else -1,
        parity_flag,
        proxy_methodology,
    )

    if output_dir:
        _save_report(report, output_dir)

    # GAP-12: persist to time-series table when db_url is provided
    if db_url:
        import asyncio as _asyncio
        _today = date.today().isoformat()
        _tid = tenant_id or "default"
        _f = from_date or _today
        _t = to_date or _today
        try:
            _loop = _asyncio.get_running_loop()
            _loop.create_task(save_fair_lending_report(report, _tid, db_url, _f, _t))
        except RuntimeError:
            try:
                _asyncio.run(save_fair_lending_report(report, _tid, db_url, _f, _t))
            except Exception as _e:
                logger.warning("save_fair_lending_report failed (non-blocking): %s", _e)

    return report


def _save_report(report: FairLendingReport, output_dir: str) -> Path:
    """Serialise report as JSON and write to *output_dir*."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    path = out / f"fair_lending_{today}.json"
    path.write_text(json.dumps(asdict(report), indent=2, cls=_NumpyEncoder))
    logger.info("Fair lending report saved to %s", path)
    return path


# ---------------------------------------------------------------------------
# GAP-12: Time-series persistence for fair lending history
# ---------------------------------------------------------------------------

_FAIR_LENDING_HISTORY_DDL = """
CREATE TABLE IF NOT EXISTS fair_lending_history (
    report_id              TEXT PRIMARY KEY,
    tenant_id              TEXT NOT NULL,
    run_date               TEXT NOT NULL,
    from_date              TEXT NOT NULL,
    to_date                TEXT NOT NULL,
    dir_minority           REAL,
    dir_female             REAL,
    approval_rate_majority REAL,
    approval_rate_minority REAL,
    chi_sq_p_value         REAL,
    alert_triggered        INTEGER,
    report_json            TEXT NOT NULL
);
"""


async def save_fair_lending_report(
    report: FairLendingReport,
    tenant_id: str,
    db_url: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> str:
    """Persist *report* to ``fair_lending_history`` and return the new ``report_id``.

    Parameters
    ----------
    report:
        The :class:`FairLendingReport` to persist.
    tenant_id:
        Opaque tenant identifier.
    db_url:
        SQLAlchemy async connection URL.
    from_date / to_date:
        Inclusive date range the report covers (YYYY-MM-DD).
        Defaults to today's date for both if not supplied.
    """
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text

    report_id = str(uuid.uuid4())
    run_date = date.today().isoformat()
    _from = from_date or run_date
    _to = to_date or run_date
    alert = 1 if (report.dir_flag or report.approval_parity_flag) else 0
    report_json = json.dumps(asdict(report), cls=_NumpyEncoder)

    engine = create_async_engine(db_url, echo=False)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(_FAIR_LENDING_HISTORY_DDL))
            await conn.execute(
                text(
                    "INSERT OR IGNORE INTO fair_lending_history "
                    "(report_id, tenant_id, run_date, from_date, to_date, "
                    " dir_minority, dir_female, approval_rate_majority, approval_rate_minority, "
                    " chi_sq_p_value, alert_triggered, report_json) "
                    "VALUES (:report_id, :tenant_id, :run_date, :from_date, :to_date, "
                    " :dir_minority, :dir_female, :approval_rate_majority, :approval_rate_minority, "
                    " :chi_sq_p_value, :alert_triggered, :report_json)"
                ),
                {
                    "report_id": report_id,
                    "tenant_id": tenant_id,
                    "run_date": run_date,
                    "from_date": _from,
                    "to_date": _to,
                    "dir_minority": report.dir_score,
                    "dir_female": None,  # populated when gender analysis is added
                    "approval_rate_majority": report.control_approval_rate,
                    "approval_rate_minority": report.protected_approval_rate,
                    "chi_sq_p_value": report.approval_parity_p_value,
                    "alert_triggered": alert,
                    "report_json": report_json,
                },
            )
    finally:
        await engine.dispose()

    logger.info("Fair lending report persisted: report_id=%s tenant=%s", report_id, tenant_id)
    return report_id


# ---------------------------------------------------------------------------
# GAP-11: Fair Lending Scenario Simulation
# ---------------------------------------------------------------------------


@dataclass
class FairLendingSimulationResult:
    """Result of replaying historical decisions under a proposed policy config.

    Attributes
    ----------
    baseline_dir_minority:
        DIR computed on the original (stored) decisions.
    simulated_dir_minority:
        DIR computed after re-running with *new_policy_config*.
    delta_dir_minority:
        simulated_dir_minority - baseline_dir_minority.
    baseline_approval_rate:
        Overall approval rate on original decisions.
    simulated_approval_rate:
        Overall approval rate on simulated decisions.
    delta_approval_rate:
        simulated_approval_rate - baseline_approval_rate.
    alert:
        True if simulated DIR < 0.80 (4/5ths rule breach).
    applications_tested:
        Number of applications replayed.
    policy_config_used:
        The *new_policy_config* that was used.
    """

    baseline_dir_minority: float
    simulated_dir_minority: float
    delta_dir_minority: float
    baseline_approval_rate: float
    simulated_approval_rate: float
    delta_approval_rate: float
    alert: bool
    applications_tested: int
    policy_config_used: Dict[str, Any]


def simulate_fair_lending_impact(
    new_policy_config: Dict[str, Any],
    historical_decisions_df: pd.DataFrame,
    fraud_model: Any,
    risk_model: Any,
) -> FairLendingSimulationResult:
    """Replay historical decisions under *new_policy_config* and report delta DIR.

    The simulation is best-effort:
    - Rows that lack sufficient feature data to reconstruct a ``DecisionRequest``
      are skipped (counted in ``applications_tested`` only for successful replays).
    - The result is a *hypothetical* analysis only and must not substitute for a
      production override.

    Parameters
    ----------
    new_policy_config:
        Dict of policy threshold overrides, e.g. ``{"pd_threshold_low": 0.04}``.
    historical_decisions_df:
        DataFrame of audit log records (one row per decision) produced by
        ``audit.logger.get_audit_records_by_period()``.
    fraud_model:
        Pre-loaded fraud detection model (or None).
    risk_model:
        Pre-loaded credit risk model (or None).

    Returns
    -------
    FairLendingSimulationResult
    """
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).parents[1]))

    from decision_engine.engine import (
        CreditResult, DecisionRequest, FraudResult, make_decision,
    )
    from models.credit_risk.predict import predict_pd
    from models.fraud_detection.predict import predict_fraud
    from models.pricing.engine import PricingConfig, PricingResult, calculate_pricing

    # Identify columns available for demographic proxy
    # Use 'bisg_minority_proxy' if present, else fall back to 'decision' column only
    protected_col = "bisg_minority_proxy"
    control_group = "majority"
    decision_col = "decision_output"

    # ------------------------------------------------------------------ #
    # 1. Compute baseline DIR from stored decisions                        #
    # ------------------------------------------------------------------ #
    baseline_df = historical_decisions_df.copy()

    # Normalise decision column — audit records use 'decision_output'
    if "decision_output" in baseline_df.columns:
        baseline_df["decision"] = baseline_df["decision_output"]
    elif "decision" not in baseline_df.columns:
        baseline_df["decision"] = "REJECT"

    overall_approvals_baseline = int(
        (baseline_df["decision"].str.upper() == "APPROVE").sum()
    )
    n_total = len(baseline_df)
    baseline_approval_rate = overall_approvals_baseline / n_total if n_total > 0 else 0.0

    # DIR baseline — only possible if demographic column exists
    baseline_dir: float = 0.0
    if protected_col in baseline_df.columns:
        try:
            bl_report = analyze_fair_lending(
                baseline_df,
                protected_col=protected_col,
                control_group=control_group,
                decision_col="decision",
            )
            baseline_dir = bl_report.dir_score or 0.0
        except Exception as exc:
            logger.warning("Baseline DIR computation failed: %s", exc)

    # ------------------------------------------------------------------ #
    # 2. Replay each application under the proposed policy                #
    # ------------------------------------------------------------------ #
    simulated_decisions: List[str] = []
    applications_tested = 0

    for _, row in baseline_df.iterrows():
        try:
            raw_features = row.get("input_features") or {}
            if isinstance(raw_features, str):
                import json as _json  # local import avoids shadow
                raw_features = _json.loads(raw_features)
            if not isinstance(raw_features, dict) or not raw_features:
                simulated_decisions.append(str(row.get("decision", "REJECT")))
                continue

            feat_df = pd.DataFrame([raw_features])

            # Re-run models
            try:
                fraud_out = predict_fraud(feat_df, _model=fraud_model)
                f_row = fraud_out.iloc[0]
                fraud_result = FraudResult(
                    fraud_probability=float(f_row["fraud_probability"]),
                    fraud_flag=str(f_row["fraud_flag"]),
                )
            except Exception:
                fp = float(row.get("fraud_score", 0.0))
                flag = "continue" if fp < 0.30 else ("manual_review" if fp <= 0.60 else "reject")
                fraud_result = FraudResult(fraud_probability=fp, fraud_flag=flag)

            try:
                credit_out = predict_pd(feat_df, _model=risk_model)
                c_row = credit_out.iloc[0]
                pd_score = float(c_row["pd_score"])
                pd_band = str(c_row["pd_band"])
            except Exception:
                pd_score = float(row.get("risk_score", 0.10))
                pd_band = "low" if pd_score < 0.05 else ("medium" if pd_score <= 0.10 else "high")

            credit_result = CreditResult(pd_score=pd_score, pd_band=pd_band)

            # Pricing stub
            try:
                pricing_result = calculate_pricing(
                    pd_score=pd_score,
                    loan_amount=float(raw_features.get("loan_amount", 5000)),
                    loan_term_months=int(raw_features.get("loan_term_months", 36)),
                    config=PricingConfig(),
                )
            except Exception:
                pricing_result = PricingResult(
                    recommended_rate=7.5, base_rate=5.0, risk_premium=2.5,
                    expected_loss=0.0, expected_profit=0.0, profitability_flag="pass",
                )

            dr = DecisionRequest(
                application_id=str(row.get("application_id", str(uuid.uuid4()))),
                fraud_result=fraud_result,
                credit_result=credit_result,
                pricing_result=pricing_result,
                loan_amount=float(raw_features.get("loan_amount", 5000)),
                loan_term_months=int(raw_features.get("loan_term_months", 36)),
                debt_to_income_ratio=float(raw_features.get("debt_to_income_ratio", 0.2)),
                num_open_accounts=int(raw_features.get("num_open_accounts", 3)),
                annual_income=raw_features.get("annual_income"),
            )

            # Use new policy config WITHOUT four-eyes (simulation context)
            result = make_decision(dr, policy_overrides=new_policy_config if new_policy_config else None, _simulation=True)
            simulated_decisions.append(result.decision)
            applications_tested += 1

        except Exception as exc:
            logger.debug("Simulation replay skipped for a row: %s", exc)
            simulated_decisions.append(str(row.get("decision", "REJECT")))

    # ------------------------------------------------------------------ #
    # 3. Compute simulated DIR                                             #
    # ------------------------------------------------------------------ #
    sim_df = baseline_df.copy()
    sim_df["decision"] = simulated_decisions if len(simulated_decisions) == len(sim_df) else sim_df["decision"]

    simulated_approval_rate = float(
        (pd.Series(simulated_decisions).str.upper() == "APPROVE").mean()
    ) if simulated_decisions else 0.0

    simulated_dir: float = 0.0
    if protected_col in sim_df.columns:
        try:
            sim_report = analyze_fair_lending(
                sim_df,
                protected_col=protected_col,
                control_group=control_group,
                decision_col="decision",
            )
            simulated_dir = sim_report.dir_score or 0.0
        except Exception as exc:
            logger.warning("Simulated DIR computation failed: %s", exc)

    return FairLendingSimulationResult(
        baseline_dir_minority=baseline_dir,
        simulated_dir_minority=simulated_dir,
        delta_dir_minority=simulated_dir - baseline_dir,
        baseline_approval_rate=baseline_approval_rate,
        simulated_approval_rate=simulated_approval_rate,
        delta_approval_rate=simulated_approval_rate - baseline_approval_rate,
        alert=simulated_dir > 0 and simulated_dir < DIR_THRESHOLD,
        applications_tested=applications_tested,
        policy_config_used=new_policy_config,
    )
