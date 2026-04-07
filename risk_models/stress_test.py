"""Macro stress testing framework (DFAST-aligned).

This module provides a portfolio-level stress testing wrapper around the Phase 2
ECL engine (see `risk_models.ecl_engine`). Scenario multipliers below are a
*reasonable approximation* of Fed DFAST 2026 narratives and must be replaced
with official values for production use.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

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
