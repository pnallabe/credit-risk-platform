"""
Portfolio Snapshot — S3-B
=========================
Computes portfolio-level summary statistics including WA-PD, WA-LGD, EL,
risk rating distribution, and delinquency rates.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional

import pandas as pd

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rating band thresholds
# ---------------------------------------------------------------------------

def _pd_to_rating(pd_score: float) -> str:
    if pd_score < 0.03:
        return "Prime"
    if pd_score < 0.08:
        return "Near-Prime"
    if pd_score < 0.15:
        return "Subprime"
    return "Deep-Subprime"


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class PortfolioSnapshot:
    computed_at: str
    total_accounts: int
    total_exposure: float
    wa_pd: float
    wa_lgd: float
    wa_el: float
    expected_loss_dollars: float
    risk_rating_distribution: Dict[str, float]   # { rating: pct }
    delinquency_rates: Dict[str, float]           # { "30dpd": pct, ... }
    approval_rate_mtd: float
    approval_rate_qtd: float


# ---------------------------------------------------------------------------
# Computation
# ---------------------------------------------------------------------------


def compute_snapshot(decisions_df: pd.DataFrame) -> PortfolioSnapshot:
    """Compute a PortfolioSnapshot from a decisions DataFrame.

    Parameters
    ----------
    decisions_df:
        Required columns: account_id, decision, pd_score, lgd_score, exposure,
        originated_at, dpd_30, dpd_60, dpd_90.
        Optional: lgd_score (defaults to 0.40 if absent).

    Returns
    -------
    PortfolioSnapshot
    """
    required = {"account_id", "decision", "pd_score", "exposure", "originated_at"}
    missing = required - set(decisions_df.columns)
    if missing:
        raise ValueError(f"decisions_df is missing columns: {missing}")

    df = decisions_df.copy()

    # Default lgd_score if absent
    if "lgd_score" not in df.columns:
        df["lgd_score"] = 0.40

    # Ensure numeric types
    df["pd_score"] = pd.to_numeric(df["pd_score"], errors="coerce").fillna(0.0)
    df["lgd_score"] = pd.to_numeric(df["lgd_score"], errors="coerce").fillna(0.40)
    df["exposure"] = pd.to_numeric(df["exposure"], errors="coerce").fillna(0.0)

    total_accounts = len(df)
    total_exposure = float(df["exposure"].sum())

    # Weighted average PD and LGD
    if total_exposure > 0:
        wa_pd = float((df["pd_score"] * df["exposure"]).sum() / total_exposure)
        wa_lgd = float((df["lgd_score"] * df["exposure"]).sum() / total_exposure)
    else:
        wa_pd = 0.0
        wa_lgd = 0.0

    wa_el = wa_pd * wa_lgd

    # Per-account EL summed
    df["el"] = df["pd_score"] * df["lgd_score"] * df["exposure"]
    expected_loss_dollars = float(df["el"].sum())

    # Risk rating distribution
    df["rating"] = df["pd_score"].apply(_pd_to_rating)
    rating_counts = df.groupby("rating")["exposure"].sum()
    all_ratings = ["Prime", "Near-Prime", "Subprime", "Deep-Subprime"]
    risk_rating_distribution: Dict[str, float] = {}
    for r in all_ratings:
        exp = float(rating_counts.get(r, 0.0))
        risk_rating_distribution[r] = round(exp / total_exposure, 6) if total_exposure > 0 else 0.0

    # Delinquency rates
    delinquency_rates: Dict[str, float] = {}
    for dpd_col, key in [("dpd_30", "30dpd"), ("dpd_60", "60dpd"), ("dpd_90", "90dpd")]:
        if dpd_col in df.columns:
            rate = float(df[dpd_col].astype(bool).mean()) if total_accounts > 0 else 0.0
        else:
            rate = 0.0
        delinquency_rates[key] = round(rate, 6)

    # Approval rates
    now = pd.Timestamp.utcnow()
    df["originated_at_ts"] = pd.to_datetime(df["originated_at"], utc=True, errors="coerce")
    is_approved = df["decision"].str.upper().isin({"APPROVE", "APPROVED", "CONDITIONAL"})

    # MTD: same calendar month
    mtd_mask = (
        (df["originated_at_ts"].dt.year == now.year) &
        (df["originated_at_ts"].dt.month == now.month)
    )
    mtd_df = df[mtd_mask]
    approval_rate_mtd = float(is_approved[mtd_mask].mean()) if len(mtd_df) > 0 else 0.0

    # QTD: current quarter
    current_quarter = (now.month - 1) // 3 + 1
    quarter_months = {1: [1,2,3], 2: [4,5,6], 3: [7,8,9], 4: [10,11,12]}[current_quarter]
    qtd_mask = (
        (df["originated_at_ts"].dt.year == now.year) &
        (df["originated_at_ts"].dt.month.isin(quarter_months))
    )
    qtd_df = df[qtd_mask]
    approval_rate_qtd = float(is_approved[qtd_mask].mean()) if len(qtd_df) > 0 else 0.0

    return PortfolioSnapshot(
        computed_at=datetime.now(tz=timezone.utc).isoformat(),
        total_accounts=total_accounts,
        total_exposure=round(total_exposure, 2),
        wa_pd=round(wa_pd, 6),
        wa_lgd=round(wa_lgd, 6),
        wa_el=round(wa_el, 6),
        expected_loss_dollars=round(expected_loss_dollars, 2),
        risk_rating_distribution=risk_rating_distribution,
        delinquency_rates=delinquency_rates,
        approval_rate_mtd=round(approval_rate_mtd, 6),
        approval_rate_qtd=round(approval_rate_qtd, 6),
    )
