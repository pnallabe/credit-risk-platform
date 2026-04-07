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
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

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
