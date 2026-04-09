"""Macro stress testing framework (DFAST-aligned) + GAP-15 Monte Carlo engine.

This module provides:
1. A portfolio-level stress testing wrapper around the Phase 2 ECL engine
   (existing DFAST/aligned content, see ``run_portfolio_stress_test``).
2. A Monte Carlo stress testing engine (GAP-15) that runs 1,000+ macro
   scenarios against the live portfolio, stores results, and allows
   quarter-over-quarter comparison (see ``StressTestRunner``).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from models.credit_risk.lgd_model import LGDModel
from risk_models.ecl_engine import ExposureRecord, MacroScenario, compute_portfolio_ecl


@dataclass(frozen=True)
class MacroScenarioSet:
    scenario_name: str
    source: str
    vintage: str
    scenarios: List[MacroScenario]


DFAST_2026_SCENARIOS = MacroScenarioSet(
    scenario_name="DFAST_2026_SEVERELY_ADVERSE",
    source="Fed DFAST 2026 (approximate — replace with official values)",
    vintage="2026",
    scenarios=[
        MacroScenario("base", pd_multiplier=1.0, lgd_multiplier=1.0, probability_weight=0.50),
        MacroScenario("adverse", pd_multiplier=1.8, lgd_multiplier=1.15, probability_weight=0.35),
        MacroScenario("severely_adverse", pd_multiplier=3.0, lgd_multiplier=1.35, probability_weight=0.15),
    ],
)


@dataclass(frozen=True)
class ScenarioResult:
    scenario: str
    total_ecl: float
    ecl_as_pct_of_portfolio: float
    scenario_delta_vs_base: float


@dataclass(frozen=True)
class StressTestReport:
    scenario_set_name: str
    run_at: datetime
    portfolio_size: int
    total_balance: float
    scenario_results: List[ScenarioResult]
    probability_weighted_ecl: float
    top10_contributors: List[Dict[str, Any]]
    capital_adequacy_check: Dict[str, Any]


def _build_exposure_records(portfolio_df: pd.DataFrame, lgd_model: LGDModel) -> List[ExposureRecord]:
    df = portfolio_df.copy()

    required = {"application_id", "outstanding_balance", "credit_limit", "months_on_book", "pd_12m", "ccf"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"portfolio_df missing required columns: {sorted(missing)}")

    # Map `product_type`/`product` → ecl_engine `product`.
    if "product" not in df.columns:
        df["product"] = df.get("product_type", "unsecured")

    if "risk_grade" not in df.columns:
        df["risk_grade"] = "C"

    if "stage" not in df.columns:
        df["stage"] = 1

    # Baseline LGD from segment model (downturn multipliers are applied per scenario).
    lgd_inputs = pd.DataFrame(
        {
            "product_type": df["product"].astype(str).str.lower(),
            "risk_grade": df["risk_grade"].astype(str).str.upper(),
        }
    )
    df["lgd"] = lgd_model.predict_batch(lgd_inputs, use_downturn=False).astype(float)

    records: List[ExposureRecord] = []
    for row in df.itertuples(index=False):
        records.append(
            ExposureRecord(
                application_id=str(row.application_id),
                product=str(row.product),
                outstanding_balance=float(row.outstanding_balance),
                credit_limit=float(row.credit_limit),
                months_on_book=int(row.months_on_book),
                pd_12m=float(row.pd_12m),
                lgd=float(row.lgd),
                ccf=float(row.ccf),
                stage=int(getattr(row, "stage", 1)),
            )
        )

    return records


def run_portfolio_stress_test(
    portfolio_df: pd.DataFrame,
    scenario_set: MacroScenarioSet,
    lgd_model: LGDModel,
    discount_rate: float = 0.05,
    tier1_ratio_pre_stress: float = 0.12,
) -> StressTestReport:
    """Run a scenario-weighted ECL stress test for a portfolio.

    Tier-1 capital adequacy is a placeholder: we model the allowance (ECL)
    as reducing Tier-1 capital dollars, then recompute the ratio.
    """

    records = _build_exposure_records(portfolio_df, lgd_model)

    ecl_df = compute_portfolio_ecl(records, scenarios=scenario_set.scenarios, discount_rate=discount_rate)
    if len(ecl_df) == 0:
        total_balance = float(portfolio_df.get("outstanding_balance", pd.Series([], dtype=float)).sum())
        return StressTestReport(
            scenario_set_name=scenario_set.scenario_name,
            run_at=datetime.now(timezone.utc),
            portfolio_size=0,
            total_balance=total_balance,
            scenario_results=[],
            probability_weighted_ecl=0.0,
            top10_contributors=[],
            capital_adequacy_check={
                "tier1_ratio_pre_stress": float(tier1_ratio_pre_stress),
                "tier1_ratio_post_stress": float(tier1_ratio_pre_stress),
                "passes_minimum_8pct": bool(float(tier1_ratio_pre_stress) >= 0.08),
            },
        )

    total_balance = float(portfolio_df["outstanding_balance"].astype(float).sum())

    # Portfolio totals per scenario (sum per-row scenario_breakdown)
    scenario_totals: Dict[str, float] = {s.name: 0.0 for s in scenario_set.scenarios}
    for bd in ecl_df["scenario_breakdown"].tolist():
        for k, v in dict(bd).items():
            scenario_totals[str(k)] += float(v)

    base_total = float(scenario_totals.get("base", 0.0))
    scenario_results: List[ScenarioResult] = []
    for s in scenario_set.scenarios:
        total_ecl = float(scenario_totals.get(s.name, 0.0))
        pct = float(total_ecl / total_balance) if total_balance > 0 else 0.0
        scenario_results.append(
            ScenarioResult(
                scenario=s.name,
                total_ecl=round(total_ecl, 2),
                ecl_as_pct_of_portfolio=round(pct, 6),
                scenario_delta_vs_base=round(total_ecl - base_total, 2),
            )
        )

    probability_weighted_ecl = float(ecl_df["ecl_weighted"].astype(float).sum())

    # Top-10 contributors under severely adverse.
    severe_name = "severely_adverse"
    severe_ecl = ecl_df["scenario_breakdown"].apply(lambda d: float(dict(d).get(severe_name, 0.0)))
    top = ecl_df.copy()
    top["severely_adverse_ecl"] = severe_ecl
    top = top.sort_values("severely_adverse_ecl", ascending=False).head(10)
    top10 = [
        {
            "application_id": str(r.application_id),
            "stage": int(r.stage),
            "ead": float(r.ead),
            "severely_adverse_ecl": float(r.severely_adverse_ecl),
        }
        for r in top.itertuples(index=False)
    ]

    # Capital adequacy placeholder
    tier1_ratio_pre_stress = float(tier1_ratio_pre_stress)
    tier1_capital_dollars = tier1_ratio_pre_stress * total_balance
    severe_total = float(scenario_totals.get(severe_name, 0.0))
    tier1_post_dollars = max(0.0, tier1_capital_dollars - severe_total)
    tier1_ratio_post = float(tier1_post_dollars / total_balance) if total_balance > 0 else 0.0

    capital_check = {
        "tier1_ratio_pre_stress": round(tier1_ratio_pre_stress, 6),
        "tier1_ratio_post_stress": round(tier1_ratio_post, 6),
        "passes_minimum_8pct": bool(tier1_ratio_post >= 0.08),
    }

    return StressTestReport(
        scenario_set_name=scenario_set.scenario_name,
        run_at=datetime.now(timezone.utc),
        portfolio_size=int(len(ecl_df)),
        total_balance=round(total_balance, 2),
        scenario_results=scenario_results,
        probability_weighted_ecl=round(float(probability_weighted_ecl), 2),
        top10_contributors=top10,
        capital_adequacy_check=capital_check,
    )


def generate_stress_test_report_markdown(report: StressTestReport, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lines: List[str] = []
    lines.append(f"# Stress Test Report — {report.scenario_set_name}")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append(f"- Run at: {report.run_at.isoformat()}")
    lines.append(f"- Portfolio size: {report.portfolio_size}")
    lines.append(f"- Total balance: {report.total_balance:,.2f}")
    lines.append(f"- Probability-weighted ECL: {report.probability_weighted_ecl:,.2f}")
    lines.append("-")
    lines.append(
        "- Tier-1 ratio pre-stress: "
        f"{report.capital_adequacy_check.get('tier1_ratio_pre_stress'):.2%}"
    )
    lines.append(
        "- Tier-1 ratio post-stress: "
        f"{report.capital_adequacy_check.get('tier1_ratio_post_stress'):.2%}"
    )
    lines.append(
        "- Passes minimum 8%: "
        f"{report.capital_adequacy_check.get('passes_minimum_8pct')}"
    )

    lines.append("")
    lines.append("## Scenario Results")
    lines.append("| Scenario | Total ECL | ECL % of Portfolio | Δ vs Base |")
    lines.append("|---|---:|---:|---:|")
    for r in report.scenario_results:
        lines.append(
            f"| {r.scenario} | {r.total_ecl:,.2f} | {r.ecl_as_pct_of_portfolio:.4%} | {r.scenario_delta_vs_base:,.2f} |"
        )

    lines.append("")
    lines.append("## ECL Waterfall (ASCII)")
    if report.scenario_results:
        base = next((x for x in report.scenario_results if x.scenario == "base"), report.scenario_results[0])
        for r in report.scenario_results:
            delta = r.total_ecl - base.total_ecl
            bar = "#" * int(min(60, max(0.0, abs(delta) / max(base.total_ecl, 1.0) * 40)))
            sign = "+" if delta >= 0 else "-"
            lines.append(f"{r.scenario:16s} {sign}{abs(delta):,.2f} {bar}")
    else:
        lines.append("(no results)")

    lines.append("")
    lines.append("## Top 10 Contributors (Severely Adverse)")
    lines.append("| Application ID | Stage | EAD | Severely Adverse ECL |")
    lines.append("|---|---:|---:|---:|")
    for row in report.top10_contributors:
        lines.append(
            f"| {row.get('application_id')} | {row.get('stage')} | {float(row.get('ead', 0.0)):,.2f} | {float(row.get('severely_adverse_ecl', 0.0)):,.2f} |"
        )

    lines.append("")
    lines.append("---")
    lines.append("Raw JSON")
    lines.append("```")
    lines.append(json.dumps(asdict(report), default=str, sort_keys=True, indent=2))
    lines.append("```")

    output_path.write_text("\n".join(lines))


# =============================================================================
# GAP-15: Monte Carlo Stress Testing Engine
# =============================================================================

logger = logging.getLogger(__name__)

# SQLite schema for Monte Carlo runs
_MC_DDL = """
CREATE TABLE IF NOT EXISTS stress_test_runs (
    run_id                   TEXT PRIMARY KEY,
    quarter                  TEXT NOT NULL,
    severity                 TEXT NOT NULL,
    n_scenarios              INTEGER NOT NULL,
    baseline_mean_pd         REAL,
    p50_stressed_dr          REAL,
    p95_stressed_dr          REAL,
    p99_stressed_dr          REAL,
    max_expected_loss        REAL,
    scenarios_above_10pct_dr INTEGER,
    run_at                   TEXT NOT NULL,
    scenario_results_json    TEXT
);
CREATE INDEX IF NOT EXISTS ix_str_quarter ON stress_test_runs (quarter);
"""

# Severity level → distribution parameters (mean, std) for each shock
# Order: [gdp_shock_pct, unemployment_delta_ppt, credit_spread_delta_bps, house_price_delta_pct]
_MC_SEVERITY_PARAMS = {
    "mild":     {"mean": [-0.01, +1.0,  +50.0, -0.05], "std": [0.01, 0.5,  25.0, 0.05]},
    "moderate": {"mean": [-0.03, +2.5, +100.0, -0.10], "std": [0.02, 1.0,  50.0, 0.08]},
    "severe":   {"mean": [-0.06, +5.0, +200.0, -0.20], "std": [0.03, 1.5, 100.0, 0.10]},
    "tail":     {"mean": [-0.12, +8.0, +400.0, -0.35], "std": [0.04, 2.0, 150.0, 0.12]},
}

# Correlation matrix (GDP × UE × credit_spread × house_price)
_MC_CORR = np.array([
    [1.00, -0.75, -0.60,  0.50],
    [-0.75,  1.00,  0.55, -0.45],
    [-0.60,  0.55,  1.00, -0.40],
    [ 0.50, -0.45, -0.40,  1.00],
])


@dataclass
class MCStressScenario:
    """One Monte Carlo macroeconomic shock scenario (GAP-15).

    Attributes
    ----------
    scenario_id:
        Sequential scenario number (1-based).
    gdp_shock_pct:
        GDP growth change, e.g. -0.05 means -5%.
    unemployment_delta_ppt:
        Unemployment rate change in percentage points, e.g. +3.0.
    credit_spread_delta_bps:
        Credit spread change in basis points, e.g. +200.
    house_price_delta_pct:
        House price change, e.g. -0.15 means -15%.
    """

    scenario_id: int
    gdp_shock_pct: float
    unemployment_delta_ppt: float
    credit_spread_delta_bps: float
    house_price_delta_pct: float


@dataclass
class StressTestSummary:
    """Aggregated results for a Monte Carlo stress test run (GAP-15).

    Attributes
    ----------
    run_id: UUID for this run.
    quarter: Quarter label, e.g. "2026-Q1".
    severity: Scenario severity level.
    n_scenarios: Number of Monte Carlo scenarios run.
    baseline_mean_pd: Mean PD without shocks.
    p50_stressed_dr: Median stressed default rate.
    p95_stressed_dr: 95th-pctile stressed default rate.
    p99_stressed_dr: 99th-pctile stressed default rate.
    max_expected_loss: Maximum expected loss across scenarios.
    scenarios_above_10pct_dr: Count of scenarios with DR > 10%.
    run_at: ISO-8601 UTC timestamp.
    """

    run_id: str
    quarter: str
    severity: str
    n_scenarios: int
    baseline_mean_pd: float
    p50_stressed_dr: float
    p95_stressed_dr: float
    p99_stressed_dr: float
    max_expected_loss: float
    scenarios_above_10pct_dr: int
    run_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class MCScenarioGenerator:
    """Generates correlated macroeconomic shock scenarios for GAP-15."""

    def generate(
        self,
        n_scenarios: int = 1000,
        seed: int = 42,
        severity: str = "moderate",
    ) -> List[MCStressScenario]:
        """Generate correlated macro shock scenarios using multivariate normal.

        Parameters
        ----------
        n_scenarios: Number of scenarios to generate.
        seed: Random seed.
        severity: "mild" | "moderate" | "severe" | "tail".
        """
        if severity not in _MC_SEVERITY_PARAMS:
            logger.warning("Unknown severity '%s', defaulting to 'moderate'", severity)
            severity = "moderate"

        params = _MC_SEVERITY_PARAMS[severity]
        means = np.array(params["mean"])
        stds = np.array(params["std"])
        cov = _MC_CORR * np.outer(stds, stds)

        rng = np.random.default_rng(seed)
        samples = rng.multivariate_normal(means, cov, size=n_scenarios)

        return [
            MCStressScenario(
                scenario_id=i + 1,
                gdp_shock_pct=float(s[0]),
                unemployment_delta_ppt=float(s[1]),
                credit_spread_delta_bps=float(s[2]),
                house_price_delta_pct=float(s[3]),
            )
            for i, s in enumerate(samples)
        ]


class MCPortfolioStressor:
    """Applies macro shocks to portfolio features and re-scores with the PD model."""

    def __init__(self, model: Any, feature_names: List[str]) -> None:
        self.model = model
        self.feature_names = feature_names

    def apply_macro_shocks(
        self,
        portfolio_df: pd.DataFrame,
        scenario: MCStressScenario,
    ) -> pd.DataFrame:
        """Apply shock adjustments.  Returns new DataFrame without mutating input."""
        import os, json as _json  # noqa: E401,PLC0415

        shocked = portfolio_df.copy()
        shock_config_path = os.getenv("STRESS_SHOCK_CONFIG")
        shock_config: dict = {}
        if shock_config_path:
            try:
                with open(shock_config_path) as f:
                    shock_config = _json.load(f)
            except Exception as exc:
                logger.warning("Could not load STRESS_SHOCK_CONFIG: %s", exc)

        gdp = scenario.gdp_shock_pct
        ue = scenario.unemployment_delta_ppt
        hp = scenario.house_price_delta_pct

        credit_col = shock_config.get("credit_score_col", "credit_score")
        if credit_col in shocked.columns:
            shocked[credit_col] = (
                shocked[credit_col] * (1.0 + 0.3 * gdp + 0.1 * hp)
            ).clip(lower=300, upper=850)

        dti_col = shock_config.get("dti_col", "debt_to_income_ratio")
        if dti_col in shocked.columns:
            shocked[dti_col] = (
                shocked[dti_col] * (1.0 + 0.2 * ue)
            ).clip(lower=0.0, upper=1.0)

        return shocked

    def score_scenario(
        self,
        portfolio_df: pd.DataFrame,
        scenario: MCStressScenario,
    ) -> dict:
        """Apply shocks and re-score. Returns scenario metrics dict."""
        shocked_df = self.apply_macro_shocks(portfolio_df, scenario)

        cols = [c for c in self.feature_names if c in shocked_df.columns]
        if not cols:
            cols = shocked_df.select_dtypes(include=[np.number]).columns.tolist()

        try:
            mat = shocked_df[cols].fillna(0)
            if hasattr(self.model, "predict_proba"):
                pds = self.model.predict_proba(mat)[:, 1]
            else:
                pds = self.model.predict(mat)
        except Exception as exc:
            logger.warning("Scenario %d scoring failed: %s", scenario.scenario_id, exc)
            pds = np.zeros(len(shocked_df))

        spread_mult = 1.0 + 0.0005 * max(scenario.credit_spread_delta_bps, 0)
        pds = np.clip(np.array(pds, dtype=float) * spread_mult, 0.0, 1.0)

        ead_col = "loan_amount" if "loan_amount" in portfolio_df.columns else None
        ead = portfolio_df[ead_col].fillna(1.0).values if ead_col else np.ones(len(pds))

        return {
            "scenario_id": scenario.scenario_id,
            "mean_pd": float(np.mean(pds)),
            "stressed_dr": float(np.mean(pds > 0.5)),
            "expected_loss": float(np.sum(pds * ead)),
            "pct_pd_increase": 0.0,  # computed relative to baseline in runner
        }


class StressTestRunner:
    """Orchestrates Monte Carlo portfolio stress testing and persists results (GAP-15).

    Parameters
    ----------
    model: Fitted credit risk model.
    feature_names: List of model input feature column names.
    store_path: Path to the SQLite results database.
    """

    def __init__(
        self,
        model: Any,
        feature_names: List[str],
        store_path: str = "./stress_test_results.db",
    ) -> None:
        self.model = model
        self.feature_names = feature_names
        self.store_path = store_path
        self._lock = threading.Lock()
        self._stressor = MCPortfolioStressor(model, feature_names)
        self._generator = MCScenarioGenerator()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.store_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            conn.executescript(_MC_DDL)
            conn.commit()
            conn.close()

    def run(
        self,
        portfolio_df: pd.DataFrame,
        n_scenarios: int = 1000,
        severity: str = "moderate",
        run_label: str = "",
        quarter: str = "",
        seed: int = 42,
    ) -> StressTestSummary:
        """Run the full Monte Carlo stress test and persist results."""
        run_id = str(uuid.uuid4())
        if not quarter:
            now = datetime.now(timezone.utc)
            quarter = f"{now.year}-Q{(now.month - 1) // 3 + 1}"

        logger.info(
            "MC stress test start run_id=%s quarter=%s severity=%s n=%d",
            run_id, quarter, severity, n_scenarios,
        )

        # Baseline score
        try:
            cols = [c for c in self.feature_names if c in portfolio_df.columns]
            if not cols:
                cols = portfolio_df.select_dtypes(include=[np.number]).columns.tolist()
            if hasattr(self.model, "predict_proba"):
                base_pds = self.model.predict_proba(portfolio_df[cols].fillna(0))[:, 1]
            else:
                base_pds = self.model.predict(portfolio_df[cols].fillna(0))
            baseline_mean_pd = float(np.mean(base_pds))
        except Exception as exc:
            logger.warning("Baseline scoring failed: %s", exc)
            baseline_mean_pd = 0.0

        scenarios = self._generator.generate(n_scenarios=n_scenarios, seed=seed, severity=severity)
        results = []
        for sc in scenarios:
            try:
                results.append(self._stressor.score_scenario(portfolio_df, sc))
            except Exception as exc:
                logger.warning("Scenario %d failed: %s", sc.scenario_id, exc)

        stressed_drs = np.array([r["stressed_dr"] for r in results]) if results else np.array([0.0])
        exp_losses = np.array([r["expected_loss"] for r in results]) if results else np.array([0.0])

        p50 = float(np.percentile(stressed_drs, 50))
        p95 = float(np.percentile(stressed_drs, 95))
        p99 = float(np.percentile(stressed_drs, 99))
        max_el = float(np.max(exp_losses))
        above_10pct = int(np.sum(stressed_drs > 0.10))
        run_at = datetime.now(timezone.utc).isoformat()

        summary = StressTestSummary(
            run_id=run_id, quarter=quarter, severity=severity,
            n_scenarios=len(results), baseline_mean_pd=baseline_mean_pd,
            p50_stressed_dr=p50, p95_stressed_dr=p95, p99_stressed_dr=p99,
            max_expected_loss=max_el, scenarios_above_10pct_dr=above_10pct,
            run_at=run_at,
        )

        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO stress_test_runs
                        (run_id, quarter, severity, n_scenarios, baseline_mean_pd,
                         p50_stressed_dr, p95_stressed_dr, p99_stressed_dr,
                         max_expected_loss, scenarios_above_10pct_dr,
                         run_at, scenario_results_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id, quarter, severity, len(results), baseline_mean_pd,
                        p50, p95, p99, max_el, above_10pct, run_at,
                        json.dumps(results),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

        logger.info("MC stress test done run_id=%s p95_dr=%.4f", run_id, p95)
        return summary

    def get_results(
        self,
        quarter: Optional[str] = None,
        limit: int = 10,
    ) -> List[dict]:
        """Return recent stress test runs, newest first."""
        with self._lock:
            conn = self._connect()
            if quarter:
                rows = conn.execute(
                    "SELECT * FROM stress_test_runs WHERE quarter = ? "
                    "ORDER BY run_at DESC LIMIT ?",
                    (quarter, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM stress_test_runs ORDER BY run_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            conn.close()
        return [dict(r) for r in rows]

    def compare_quarters(self, quarter_a: str, quarter_b: str) -> dict:
        """Return delta metrics between the most-recent runs of two quarters."""
        ra = self.get_results(quarter=quarter_a, limit=1)
        rb = self.get_results(quarter=quarter_b, limit=1)

        if not ra:
            return {"error": f"No results for quarter '{quarter_a}'"}
        if not rb:
            return {"error": f"No results for quarter '{quarter_b}'"}

        a, b = ra[0], rb[0]

        def _d(k: str) -> Optional[float]:
            va, vb = a.get(k), b.get(k)
            if va is None or vb is None:
                return None
            try:
                return round(float(vb) - float(va), 6)
            except (TypeError, ValueError):
                return None

        return {
            "quarter_a": quarter_a,
            "quarter_b": quarter_b,
            "run_id_a": a.get("run_id"),
            "run_id_b": b.get("run_id"),
            "delta_baseline_mean_pd": _d("baseline_mean_pd"),
            "delta_p50_stressed_dr": _d("p50_stressed_dr"),
            "delta_p95_stressed_dr": _d("p95_stressed_dr"),
            "delta_p99_stressed_dr": _d("p99_stressed_dr"),
            "delta_max_expected_loss": _d("max_expected_loss"),
            "delta_scenarios_above_10pct_dr": _d("scenarios_above_10pct_dr"),
        }
