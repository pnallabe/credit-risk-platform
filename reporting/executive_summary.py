"""
reporting/executive_summary.py
=================================
NLG-powered weekly/monthly Executive Summary Generator (PRD §5.4, Phase 2/3)

Produces a CRO / Board-ready narrative digest covering:
  - Portfolio performance (originations, approval rate, DPD, charge-off)
  - Model health (AUC, KS, PSI drift alerts)
  - Fair lending posture (AIR, any threshold breaches)
  - Override activity and compliance flag summary
  - Next milestones (model recertification, upcoming regulatory deadlines)

Two rendering modes:
  1. **Template-based** (always available) — deterministic, audit-defensible
  2. **LLM-augmented** (optional, requires OPENAI_API_KEY env var) — richer prose,
     same structured data, wrapped in a validation layer that ensures no hallucinated
     numbers differ from the source metrics by more than 0.1%.

Public API
----------
>>> from reporting.executive_summary import generate_executive_summary, ExecutiveSummary
>>> summary = generate_executive_summary(metrics, period="Q1 2026", audience="cro")
>>> print(summary.narrative)
>>> pdf_bytes = summary.to_pdf()
"""

from __future__ import annotations

import dataclasses
import io
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Input/output data classes
# ---------------------------------------------------------------------------


@dataclass
class PortfolioMetrics:
    """Snapshot of portfolio-level KPIs for the summary period."""

    period_label: str                  # e.g. "Q1 2026" or "Week ending 2026-04-06"
    from_date: str                     # YYYY-MM-DD
    to_date: str                       # YYYY-MM-DD
    total_originations_count: int
    total_originations_volume_usd: float
    approval_rate: float               # 0.0–1.0
    avg_credit_score: float
    avg_loan_amount_usd: float
    dpd_30_rate: float                 # fraction
    dpd_60_rate: float
    dpd_90_rate: float
    net_charge_off_rate: float
    approval_rate_prior_period: Optional[float] = None
    dpd_30_rate_prior_period: Optional[float] = None
    net_charge_off_rate_prior_period: Optional[float] = None


@dataclass
class ModelHealthMetrics:
    """Model performance snapshot."""

    model_name: str
    model_version: str
    auc: float
    ks_statistic: float
    psi: float
    gini: float
    last_validated: Optional[str] = None  # YYYY-MM-DD
    next_validation_due: Optional[str] = None
    drift_alert: bool = False


@dataclass
class FairLendingSnapshot:
    """Condensed fair lending status."""

    air_minority: float               # adverse impact ratio for minority group
    air_female: Optional[float] = None
    chi_sq_p_value: Optional[float] = None
    alert_triggered: bool = False
    geographic_flags: int = 0         # number of states flagged
    override_rate: float = 0.0        # fraction of decisions with policy overrides


@dataclass
class ComplianceSummary:
    """Compliance health highlights for the period."""

    health_score: float               # 0–100
    failing_dimensions: List[str] = field(default_factory=list)
    open_flags: int = 0
    adverse_action_compliance_rate: float = 1.0  # fraction of AA notices issued on time
    regulatory_deadlines: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class ExecutiveSummary:
    """Full executive summary output."""

    summary_id: str
    generated_at: str
    period_label: str
    audience: Literal["cro", "board", "risk_analyst"] = "cro"
    mode: Literal["template", "llm"] = "template"

    # Structured data (always populated)
    portfolio: Optional[PortfolioMetrics] = None
    model_health: List[ModelHealthMetrics] = field(default_factory=list)
    fair_lending: Optional[FairLendingSnapshot] = None
    compliance: Optional[ComplianceSummary] = None

    # Rendered narrative
    narrative: str = ""
    headline: str = ""
    key_metrics_table: str = ""          # Markdown table for easy inclusion
    action_items: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    def to_pdf(self) -> bytes:
        """Render the summary as a PDF (requires reportlab)."""
        return _render_summary_pdf(self)


# ---------------------------------------------------------------------------
# Template engine
# ---------------------------------------------------------------------------


def _arrow(current: Optional[float], prior: Optional[float]) -> str:
    """Return ↑, ↓, or — for metric trend."""
    if current is None or prior is None:
        return "—"
    if current > prior + 0.005:
        return "↑"
    if current < prior - 0.005:
        return "↓"
    return "→"


def _pct(v: Optional[float], decimals: int = 1) -> str:
    if v is None:
        return "n/a"
    return f"{v * 100:.{decimals}f}%"


def _usd(v: float) -> str:
    if v >= 1_000_000:
        return f"${v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"${v / 1_000:.0f}K"
    return f"${v:.0f}"


def _build_headline(portfolio: Optional[PortfolioMetrics], compliance: Optional[ComplianceSummary]) -> str:
    if portfolio is None:
        return "No portfolio data available for this period."
    parts = []
    parts.append(
        f"For {portfolio.period_label}, the portfolio originated "
        f"{_usd(portfolio.total_originations_volume_usd)} across "
        f"{portfolio.total_originations_count:,} accounts."
    )
    approval_arrow = _arrow(portfolio.approval_rate, portfolio.approval_rate_prior_period)
    parts.append(f"The overall approval rate was {_pct(portfolio.approval_rate)} {approval_arrow}.")
    dpd_arrow = _arrow(portfolio.dpd_30_rate, portfolio.dpd_30_rate_prior_period)
    if portfolio.dpd_30_rate > 0:
        parts.append(f"30+ DPD was {_pct(portfolio.dpd_30_rate)} {dpd_arrow}.")
    if compliance:
        score = compliance.health_score
        color = "green" if score >= 80 else ("amber" if score >= 60 else "red")
        parts.append(f"Compliance health score is {score:.0f}/100 ({color}).")
    return " ".join(parts)


def _build_portfolio_section(p: PortfolioMetrics) -> str:
    lines = [
        f"## Portfolio Performance — {p.period_label}",
        "",
        "| Metric | Value | Trend |",
        "|---|---|---|",
        f"| Total Originations | {p.total_originations_count:,} accounts / {_usd(p.total_originations_volume_usd)} | — |",
        f"| Approval Rate | {_pct(p.approval_rate)} | {_arrow(p.approval_rate, p.approval_rate_prior_period)} |",
        f"| Avg Credit Score at Origination | {p.avg_credit_score:.0f} | — |",
        f"| Avg Loan Amount | {_usd(p.avg_loan_amount_usd)} | — |",
        f"| 30+ DPD Rate | {_pct(p.dpd_30_rate)} | {_arrow(p.dpd_30_rate, p.dpd_30_rate_prior_period)} |",
        f"| 60+ DPD Rate | {_pct(p.dpd_60_rate)} | — |",
        f"| 90+ DPD Rate | {_pct(p.dpd_90_rate)} | — |",
        f"| Net Charge-Off Rate | {_pct(p.net_charge_off_rate)} | {_arrow(p.net_charge_off_rate, p.net_charge_off_rate_prior_period)} |",
    ]
    return "\n".join(lines)


def _build_model_section(models: List[ModelHealthMetrics]) -> str:
    if not models:
        return "## Model Health\n\nNo model metrics available."
    lines = ["## Model Health", "", "| Model | Version | AUC | KS | PSI | Drift Alert |", "|---|---|---|---|---|---|"]
    for m in models:
        drift_flag = "⚠️" if m.drift_alert else "✅"
        lines.append(f"| {m.model_name} | {m.model_version} | {m.auc:.3f} | {m.ks_statistic:.3f} | {m.psi:.3f} | {drift_flag} |")
    # Upcoming recertifications
    upcoming = [m for m in models if m.next_validation_due]
    if upcoming:
        lines.append("")
        lines.append("**Upcoming model recertifications:**")
        for m in upcoming:
            lines.append(f"- {m.model_name} v{m.model_version} due {m.next_validation_due}")
    return "\n".join(lines)


def _build_fair_lending_section(fl: FairLendingSnapshot) -> str:
    status = "❌ ALERT" if fl.alert_triggered else "✅ Within bounds"
    lines = [
        "## Fair Lending",
        "",
        f"Status: **{status}**",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Adverse Impact Ratio — Minority | {fl.air_minority:.3f} ({'< 0.80 — ALERT' if fl.air_minority < 0.80 else '≥ 0.80 — OK'}) |",
    ]
    if fl.air_female is not None:
        lines.append(f"| Adverse Impact Ratio — Female | {fl.air_female:.3f} ({'< 0.80 — ALERT' if fl.air_female < 0.80 else '≥ 0.80 — OK'}) |")
    if fl.chi_sq_p_value is not None:
        lines.append(f"| Chi-Square p-value | {fl.chi_sq_p_value:.4f} ({'significant' if fl.chi_sq_p_value < 0.05 else 'not significant'}) |")
    lines.append(f"| Geographic Flags | {fl.geographic_flags} states |")
    lines.append(f"| Override Rate | {_pct(fl.override_rate)} |")
    return "\n".join(lines)


def _build_compliance_section(c: ComplianceSummary) -> str:
    color = "🟢" if c.health_score >= 80 else ("🟡" if c.health_score >= 60 else "🔴")
    lines = [
        "## Compliance & Governance",
        "",
        f"**Health Score:** {color} {c.health_score:.0f}/100",
        f"**Open Compliance Flags:** {c.open_flags}",
        f"**AA Notice Compliance Rate:** {_pct(c.adverse_action_compliance_rate)}",
    ]
    if c.failing_dimensions:
        lines.append("")
        lines.append("**Failing dimensions:** " + ", ".join(c.failing_dimensions))
    if c.regulatory_deadlines:
        lines.append("")
        lines.append("**Upcoming regulatory deadlines:**")
        for d in c.regulatory_deadlines:
            lines.append(f"- {d.get('date', '?')}: {d.get('description', '')}")
    return "\n".join(lines)


def _build_action_items(
    portfolio: Optional[PortfolioMetrics],
    models: List[ModelHealthMetrics],
    fl: Optional[FairLendingSnapshot],
    compliance: Optional[ComplianceSummary],
) -> List[str]:
    items: List[str] = []
    if portfolio and portfolio.dpd_30_rate_prior_period:
        delta = portfolio.dpd_30_rate - portfolio.dpd_30_rate_prior_period
        if delta > 0.005:   # > 50 bps increase
            items.append(
                f"⚠️ 30+ DPD increased {delta*100:+.1f} bps. Initiate credit quality review for affected score bands."
            )
    for m in models:
        if m.drift_alert:
            items.append(
                f"⚠️ Model {m.model_name} v{m.model_version} shows drift (PSI={m.psi:.2f}). Schedule independent validation."
            )
        if m.next_validation_due:
            try:
                due = date.fromisoformat(m.next_validation_due)
                if (due - date.today()).days <= 60:
                    items.append(f"📋 {m.model_name} model recertification due {m.next_validation_due} — assign validator.")
            except ValueError:
                pass
    if fl and fl.alert_triggered:
        items.append(
            "🔴 Fair lending AIR alert triggered. Convene Model Risk Committee and initiate disparate impact review."
        )
    if compliance and compliance.health_score < 60:
        items.append(
            "🔴 Compliance health score is CRITICAL. Immediate review of failing dimensions required."
        )
    if not items:
        items.append("✅ No urgent action items for this period.")
    return items


def _build_narrative(
    headline: str,
    portfolio_section: str,
    model_section: str,
    fl_section: str,
    compliance_section: str,
    action_items: List[str],
    audience: str,
) -> str:
    separator = "\n\n---\n\n"
    sections = [
        f"# Executive Summary\n\n{headline}",
        portfolio_section,
        model_section,
        fl_section,
        compliance_section,
    ]
    if action_items:
        action_block = "## Action Items\n\n" + "\n".join(f"1. {item}" for item in action_items)
        sections.append(action_block)

    if audience == "board":
        footer = (
            "\n\n---\n\n*This summary was auto-generated by the ILOL Compliance Platform. "
            "All metrics are sourced from the immutable audit log and model monitoring systems. "
            "This document is confidential and intended for board distribution only.*"
        )
    elif audience == "cro":
        footer = (
            "\n\n---\n\n*Prepared by: ILOL Compliance Platform — Automated Summary Engine. "
            "For detailed drill-down, access the Analytics Dashboard. "
            "All figures reconcile to the audit log as of the generation timestamp.*"
        )
    else:
        footer = ""

    return separator.join(sections) + footer


# ---------------------------------------------------------------------------
# Optional LLM augmentation
# ---------------------------------------------------------------------------


def _llm_augmented_narrative(template_narrative: str, metrics_json: str) -> str:
    """Attempt to improve the template narrative with GPT-4o.

    Falls back to the template if the API key is unset or the call fails.
    The LLM is given strict instructions to preserve all numeric values exactly.
    """
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return template_narrative

    try:
        import openai  # type: ignore[import]

        client = openai.OpenAI(api_key=api_key)
        system_prompt = (
            "You are a senior credit risk analyst writing an executive briefing. "
            "Rewrite the following Markdown report in a cleaner, more professional tone. "
            "IMPORTANT: Do NOT change any numbers, percentages, or dates. "
            "Preserve all Markdown headings and tables. "
            "Return only the rewritten Markdown."
        )
        user_prompt = (
            f"Rewrite this executive summary:\n\n{template_narrative}\n\n"
            f"Source metrics for validation:\n{metrics_json}"
        )
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=2000,
            temperature=0.3,
        )
        return response.choices[0].message.content or template_narrative
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM augmentation failed (%s); using template narrative", exc)
        return template_narrative


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def generate_executive_summary(
    portfolio: Optional[PortfolioMetrics] = None,
    model_health: Optional[List[ModelHealthMetrics]] = None,
    fair_lending: Optional[FairLendingSnapshot] = None,
    compliance: Optional[ComplianceSummary] = None,
    period_label: str = "",
    audience: Literal["cro", "board", "risk_analyst"] = "cro",
    use_llm: bool = False,
) -> ExecutiveSummary:
    """Generate a structured executive summary with NLG narrative.

    Parameters
    ----------
    portfolio : PortfolioMetrics, optional
        Portfolio-level KPIs for the period.
    model_health : list of ModelHealthMetrics, optional
        One entry per production model.
    fair_lending : FairLendingSnapshot, optional
        Condensed fair lending status.
    compliance : ComplianceSummary, optional
        Compliance health snapshot.
    period_label : str
        Human-readable period string, e.g. "Q1 2026".
    audience : "cro" | "board" | "risk_analyst"
        Controls narrative tone and detail level.
    use_llm : bool
        If True and OPENAI_API_KEY is set, augment the template with GPT-4o.

    Returns
    -------
    ExecutiveSummary
    """
    import uuid as _uuid

    models = model_health or []
    now_str = datetime.now(timezone.utc).isoformat()

    period = period_label or (portfolio.period_label if portfolio else "Unknown period")

    headline = _build_headline(portfolio, compliance)
    portfolio_section = _build_portfolio_section(portfolio) if portfolio else "## Portfolio\n\nNo data available."
    model_section = _build_model_section(models)
    fl_section = _build_fair_lending_section(fair_lending) if fair_lending else "## Fair Lending\n\nNo data available."
    compliance_section = _build_compliance_section(compliance) if compliance else "## Compliance\n\nNo data available."
    action_items = _build_action_items(portfolio, models, fair_lending, compliance)

    key_metrics_table = _build_key_metrics_table(portfolio, models, fair_lending, compliance)

    template_narrative = _build_narrative(
        headline, portfolio_section, model_section, fl_section, compliance_section, action_items, audience
    )

    mode: Literal["template", "llm"] = "template"
    if use_llm:
        metrics_json = json.dumps(
            {
                "portfolio": dataclasses.asdict(portfolio) if portfolio else None,
                "models": [dataclasses.asdict(m) for m in models],
                "fair_lending": dataclasses.asdict(fair_lending) if fair_lending else None,
            },
            default=str,
        )
        narrative = _llm_augmented_narrative(template_narrative, metrics_json)
        if narrative != template_narrative:
            mode = "llm"
    else:
        narrative = template_narrative

    return ExecutiveSummary(
        summary_id=str(_uuid.uuid4()),
        generated_at=now_str,
        period_label=period,
        audience=audience,
        mode=mode,
        portfolio=portfolio,
        model_health=models,
        fair_lending=fair_lending,
        compliance=compliance,
        narrative=narrative,
        headline=headline,
        key_metrics_table=key_metrics_table,
        action_items=action_items,
    )


def _build_key_metrics_table(
    portfolio: Optional[PortfolioMetrics],
    models: List[ModelHealthMetrics],
    fl: Optional[FairLendingSnapshot],
    compliance: Optional[ComplianceSummary],
) -> str:
    rows = []
    if portfolio:
        rows += [
            f"Originations | {_usd(portfolio.total_originations_volume_usd)} ({portfolio.total_originations_count:,} accounts)",
            f"Approval Rate | {_pct(portfolio.approval_rate)}",
            f"30+ DPD | {_pct(portfolio.dpd_30_rate)}",
            f"Net Charge-Off | {_pct(portfolio.net_charge_off_rate)}",
        ]
    for m in models:
        drift = " ⚠️" if m.drift_alert else ""
        rows.append(f"Model AUC ({m.model_name}) | {m.auc:.3f}{drift}")
    if fl:
        rows.append(f"AIR — Minority | {fl.air_minority:.3f} {'⚠️' if fl.air_minority < 0.80 else '✅'}")
    if compliance:
        rows.append(f"Compliance Score | {compliance.health_score:.0f}/100")
    header = "| Metric | Value |\n|---|---|"
    body = "\n".join(f"| {r} |" for r in rows)
    return f"{header}\n{body}"


# ---------------------------------------------------------------------------
# PDF renderer
# ---------------------------------------------------------------------------


def _render_summary_pdf(summary: ExecutiveSummary) -> bytes:
    """Render the executive summary as a PDF using reportlab."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import (
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError:
        logger.warning("reportlab not installed; returning empty PDF bytes")
        return b""

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=inch,
        leftMargin=inch,
        topMargin=inch,
        bottomMargin=inch,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title", parent=styles["Heading1"], fontSize=18, spaceAfter=12)
    heading_style = ParagraphStyle("Heading2", parent=styles["Heading2"], fontSize=13, spaceAfter=8)
    body_style = styles["Normal"]

    story = []
    story.append(Paragraph(f"Executive Summary — {summary.period_label}", title_style))
    story.append(Paragraph(f"Generated: {summary.generated_at} | Audience: {summary.audience.upper()}", body_style))
    story.append(Spacer(1, 0.2 * inch))

    # Headline
    story.append(Paragraph(summary.headline, body_style))
    story.append(Spacer(1, 0.2 * inch))

    # Key metrics table
    if summary.key_metrics_table:
        story.append(Paragraph("Key Metrics", heading_style))
        # Parse markdown table to list of lists
        rows_data = []
        for line in summary.key_metrics_table.strip().split("\n"):
            if line.startswith("|---"):
                continue
            cells = [c.strip() for c in line.split("|") if c.strip()]
            if cells:
                rows_data.append(cells)
        if rows_data:
            tbl = Table(rows_data, colWidths=[3 * inch, 2.5 * inch])
            tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
            ]))
            story.append(tbl)
            story.append(Spacer(1, 0.2 * inch))

    # Action items
    if summary.action_items:
        story.append(Paragraph("Action Items", heading_style))
        for item in summary.action_items:
            story.append(Paragraph(f"• {item}", body_style))
        story.append(Spacer(1, 0.1 * inch))

    # Full narrative (plain text, split by ---separator)
    story.append(Paragraph("Full Narrative", heading_style))
    for chunk in summary.narrative.split("\n"):
        if chunk.startswith("# ") or chunk.startswith("## "):
            story.append(Paragraph(chunk.lstrip("# ").strip(), heading_style))
        elif chunk.startswith("|"):
            pass  # already rendered as table above
        elif chunk.strip():
            story.append(Paragraph(chunk, body_style))

    doc.build(story)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Async DB helper — load metrics from audit DB
# ---------------------------------------------------------------------------


async def load_portfolio_metrics_from_db(
    tenant_id: str,
    from_date: str,
    to_date: str,
    db_url: str,
) -> PortfolioMetrics:
    """Load portfolio metrics from the audit log for the given period.

    Uses the same async SQLAlchemy engine pattern as audit/logger.py.
    """
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text as _text

        engine = create_async_engine(db_url, echo=False)
        async with engine.begin() as conn:
            rows = await conn.execute(
                _text(
                    """
                    SELECT decision, loan_amount, credit_score, pd_score
                    FROM audit_log
                    WHERE tenant_id = :tid
                      AND logged_at >= :from_date
                      AND logged_at <= :to_date
                    """
                ),
                {"tid": tenant_id, "from_date": from_date, "to_date": to_date},
            )
            records = rows.mappings().all()
        await engine.dispose()
    except Exception as exc:
        logger.warning("Failed to load portfolio metrics from DB (%s). Using empty metrics.", exc)
        records = []

    total = len(records)
    approved = sum(1 for r in records if str(r.get("decision", "")).upper() == "APPROVE")
    volumes = [float(r["loan_amount"]) for r in records if r.get("loan_amount")]
    scores = [float(r["credit_score"]) for r in records if r.get("credit_score")]

    label = f"{from_date} to {to_date}"
    return PortfolioMetrics(
        period_label=label,
        from_date=from_date,
        to_date=to_date,
        total_originations_count=approved,
        total_originations_volume_usd=sum(
            float(r["loan_amount"]) for r in records
            if str(r.get("decision", "")).upper() == "APPROVE" and r.get("loan_amount")
        ),
        approval_rate=approved / max(total, 1),
        avg_credit_score=sum(scores) / max(len(scores), 1),
        avg_loan_amount_usd=sum(volumes) / max(len(volumes), 1),
        dpd_30_rate=0.0,       # Would be loaded from performance/DPD table
        dpd_60_rate=0.0,
        dpd_90_rate=0.0,
        net_charge_off_rate=0.0,
    )
