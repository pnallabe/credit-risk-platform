"""
Concentration Monitor — S3-A
============================
Monitors portfolio concentration by sector, state, risk grade, and product type.
Fires alerts when configured limits are breached.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

import pandas as pd

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default concentration limits
# ---------------------------------------------------------------------------

DEFAULT_LIMITS: Dict[str, float] = {
    "sector": 0.25,
    "state": 0.20,
    "risk_grade": 0.40,
    "product_type": 0.60,
}

# Column mapping: dimension name → DataFrame column name
_DIMENSION_COL: Dict[str, str] = {
    "sector": "naics_2d",
    "state": "state",
    "risk_grade": "risk_grade",
    "product_type": "product_type",
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ConcentrationBreakdownEntry:
    count: int
    exposure: float
    pct_of_total: float


@dataclass
class ConcentrationDimension:
    dimension: str
    breakdown: Dict[str, ConcentrationBreakdownEntry]
    configured_limit_pct: float
    max_observed_pct: float
    at_risk: bool   # max_observed > 0.8 * configured_limit
    in_breach: bool  # max_observed > configured_limit


@dataclass
class ConcentrationBreach:
    dimension: str
    segment_value: str
    observed_pct: float
    limit_pct: float
    excess_pct: float
    severity: Literal["Warning", "Breach"]


@dataclass
class ConcentrationReport:
    computed_at: str
    dimensions: List[ConcentrationDimension]
    breaches: List[ConcentrationBreach]
    total_accounts: int
    total_exposure: float


# ---------------------------------------------------------------------------
# Monitor class
# ---------------------------------------------------------------------------


class ConcentrationMonitor:
    """Compute portfolio concentration reports and fire alerts on breaches."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        policy_store: Optional[Any] = None,
        alert_router: Optional[Any] = None,
    ) -> None:
        self._db_path = db_path
        self._policy_store = policy_store
        self._alert_router = alert_router
        self._limits = self._load_limits()

    # ------------------------------------------------------------------
    # Limit loading
    # ------------------------------------------------------------------

    def _load_limits(self) -> Dict[str, float]:
        limits = dict(DEFAULT_LIMITS)
        if self._policy_store is not None:
            try:
                active = self._policy_store.get_active()
                params = active.parameters if hasattr(active, "parameters") else {}
                if isinstance(params, dict):
                    cl = params.get("concentration_limits", {})
                    if isinstance(cl, dict):
                        limits.update(cl)
            except Exception as exc:
                log.warning("Could not load concentration limits from policy store: %s", exc)
        return limits

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_report(self, decisions_df: pd.DataFrame) -> ConcentrationReport:
        """Compute a ConcentrationReport from a decisions DataFrame.

        Parameters
        ----------
        decisions_df:
            Must contain columns: account_id, exposure, naics_2d, state,
            risk_grade, product_type.

        Returns
        -------
        ConcentrationReport
        """
        decisions_df = self._validate_and_fill_defaults(decisions_df)

        total_accounts = len(decisions_df)
        total_exposure = float(decisions_df["exposure"].sum())

        dimensions: List[ConcentrationDimension] = []
        breaches: List[ConcentrationBreach] = []

        for dim_name, col in _DIMENSION_COL.items():
            limit = self._limits.get(dim_name, 0.25)
            dim, dim_breaches = self._compute_dimension(
                decisions_df, dim_name, col, total_exposure, limit
            )
            dimensions.append(dim)
            breaches.extend(dim_breaches)

        # Fire alerts for breaches
        self._fire_alerts(breaches)

        return ConcentrationReport(
            computed_at=datetime.now(tz=timezone.utc).isoformat(),
            dimensions=dimensions,
            breaches=breaches,
            total_accounts=total_accounts,
            total_exposure=total_exposure,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_and_fill_defaults(self, df: pd.DataFrame) -> pd.DataFrame:
        """Fill NULL/missing dimension values with an 'Unknown' sentinel."""
        required_cols = {"account_id", "exposure", "naics_2d", "state", "risk_grade", "product_type"}
        missing = required_cols - set(df.columns)
        if missing:
            raise ValueError(f"decisions_df is missing columns: {missing}")

        df = df.copy()
        for col in ["naics_2d", "state", "risk_grade", "product_type"]:
            df[col] = df[col].fillna("Unknown")

        return df

    def _compute_dimension(
        self,
        df: pd.DataFrame,
        dim_name: str,
        col: str,
        total_exposure: float,
        limit: float,
    ) -> tuple[ConcentrationDimension, List[ConcentrationBreach]]:
        grouped = (
            df.groupby(col)
            .agg(count=("account_id", "count"), exposure=("exposure", "sum"))
            .reset_index()
        )

        breakdown: Dict[str, ConcentrationBreakdownEntry] = {}
        max_pct = 0.0

        for _, row in grouped.iterrows():
            seg = str(row[col])
            cnt = int(row["count"])
            exp = float(row["exposure"])
            pct = exp / total_exposure if total_exposure > 0 else 0.0
            breakdown[seg] = ConcentrationBreakdownEntry(
                count=cnt, exposure=exp, pct_of_total=round(pct, 6)
            )
            if pct > max_pct:
                max_pct = pct

        at_risk = max_pct > 0.8 * limit
        in_breach = max_pct > limit

        dim = ConcentrationDimension(
            dimension=dim_name,
            breakdown=breakdown,
            configured_limit_pct=limit,
            max_observed_pct=round(max_pct, 6),
            at_risk=at_risk,
            in_breach=in_breach,
        )

        dim_breaches: List[ConcentrationBreach] = []
        for seg, entry in breakdown.items():
            pct = entry.pct_of_total
            if pct > 0.8 * limit:
                severity: Literal["Warning", "Breach"] = "Breach" if pct > limit else "Warning"
                dim_breaches.append(
                    ConcentrationBreach(
                        dimension=dim_name,
                        segment_value=seg,
                        observed_pct=round(pct, 6),
                        limit_pct=limit,
                        excess_pct=round(max(0.0, pct - limit), 6),
                        severity=severity,
                    )
                )

        return dim, dim_breaches

    def _fire_alerts(self, breaches: List[ConcentrationBreach]) -> None:
        if self._alert_router is None or not breaches:
            return
        for breach in breaches:
            severity = "HIGH" if breach.severity == "Breach" else "MEDIUM"
            subject = (
                f"[Concentration {breach.severity}] {breach.dimension}:{breach.segment_value}"
            )
            body = (
                f"Segment '{breach.segment_value}' in dimension '{breach.dimension}' "
                f"represents {breach.observed_pct:.1%} of portfolio, "
                f"{'exceeding' if breach.severity == 'Breach' else 'approaching'} "
                f"the {breach.limit_pct:.1%} limit "
                f"(excess: {breach.excess_pct:.1%})."
            )
            try:
                self._alert_router.send_alert(severity=severity, title=subject, body=body)
            except Exception as exc:
                log.warning("Alert routing failed: %s", exc)
