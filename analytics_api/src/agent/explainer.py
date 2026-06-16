"""
explainer.py — Explainer

Produces deterministic, human-readable summaries of query results.

No LLM calls. All templates are string-based, driven by the ResolvedIntent,
row data, and any RuleViolations. This keeps token spend to zero in the
result-explanation phase while still producing clear, natural answers.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from analytics_api.src.agent.resolved_intent import ResolvedIntent
from analytics_api.src.domain_ontology.rule_engine import RuleViolation

logger = logging.getLogger(__name__)


def _pct(v: float) -> str:
    return f"{v * 100:.2f}%" if abs(v) < 10 else f"{v:.4f}"


def _fmt_value(v: Any) -> str:
    if isinstance(v, float):
        if abs(v) <= 1.0:
            return _pct(v)
        return f"{v:,.2f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


class Explainer:
    """Format query results as a human-readable narrative.

    Example::

        explainer = Explainer()
        answer = explainer.explain(
            intent=resolved_intent,
            rows=[{"delinquency_rate": 0.0432, "product_type": "PERSONAL"}],
            violations=[],
        )
        # "The delinquency rate for PERSONAL loans is 4.32%."
    """

    def explain(
        self,
        intent: ResolvedIntent,
        rows: List[Dict[str, Any]],
        violations: Optional[List[RuleViolation]] = None,
    ) -> str:
        violations = violations or []
        parts: List[str] = []

        if not rows:
            parts.append(self._no_results(intent))
        elif intent.is_timeseries:
            parts.append(self._timeseries_answer(intent, rows))
        elif intent.resolved_metric and len(rows) == 1 and not intent.dimensions:
            parts.append(self._single_metric_answer(intent, rows[0]))
        elif intent.resolved_metric and intent.dimensions:
            parts.append(self._breakdown_answer(intent, rows))
        else:
            parts.append(self._generic_answer(intent, rows))

        # Append filter context
        filter_context = self._filter_context(intent)
        if filter_context:
            parts.append(filter_context)

        # Append violation warnings
        if violations:
            parts.append(self._violation_summary(violations))

        return "  ".join(p for p in parts if p)

    # ------------------------------------------------------------------
    # Templates
    # ------------------------------------------------------------------

    def _no_results(self, intent: ResolvedIntent) -> str:
        metric = (
            intent.resolved_metric.metric.name
            if intent.resolved_metric
            else "the requested metric"
        )
        return (
            f"No data was found for {metric}. "
            "This may indicate that the requested time period or filter has no records."
        )

    def _single_metric_answer(
        self, intent: ResolvedIntent, row: Dict[str, Any]
    ) -> str:
        rm = intent.resolved_metric
        if rm is None:
            return self._generic_answer(intent, [row])

        metric_key = rm.metric.name.lower()
        value = row.get(metric_key) or row.get(list(row.keys())[0])
        display_name = rm.metric.name

        variant_str = f" ({rm.variant})" if rm.variant else ""
        value_str = _fmt_value(value)

        product_str = (
            f" for {intent.product_type} loans" if intent.product_type else ""
        )

        return f"The {display_name}{variant_str}{product_str} is {value_str}."

    def _breakdown_answer(
        self, intent: ResolvedIntent, rows: List[Dict[str, Any]]
    ) -> str:
        rm = intent.resolved_metric
        if rm is None:
            return self._generic_answer(intent, rows)

        display_name = rm.metric.name
        dim_names = [d.canonical_name for d in intent.dimensions]
        dim_label = " and ".join(dim_names)
        product_str = (
            f" for {intent.product_type} loans" if intent.product_type else ""
        )

        metric_key = rm.metric.name.lower()
        lines = [f"{display_name}{product_str} by {dim_label}:"]
        for row in rows[:20]:
            dim_vals = " / ".join(str(row.get(d, "?")) for d in dim_names)
            value = row.get(metric_key) or row.get(list(row.keys())[-1])
            lines.append(f"  • {dim_vals}: {_fmt_value(value)}")
        if len(rows) > 20:
            lines.append(f"  ... and {len(rows) - 20} more rows.")
        return "\n".join(lines)

    def _timeseries_answer(
        self, intent: ResolvedIntent, rows: List[Dict[str, Any]]
    ) -> str:
        rm = intent.resolved_metric
        display_name = rm.metric.name if rm else "metric"
        product_str = (
            f" for {intent.product_type} loans" if intent.product_type else ""
        )
        metric_key = rm.metric.name.lower() if rm else list(rows[0].keys())[-1]

        lines = [f"{display_name}{product_str} over time ({len(rows)} periods):"]
        for row in rows[:24]:
            period = row.get("period") or row.get("month") or row.get("quarter") or row.get("year") or "?"
            value = row.get(metric_key) or row.get(list(row.keys())[-1])
            lines.append(f"  • {period}: {_fmt_value(value)}")
        if len(rows) > 24:
            lines.append(f"  ... and {len(rows) - 24} more periods.")

        # Simple trend description
        if len(rows) >= 2:
            first_val = rows[0].get(metric_key)
            last_val = rows[-1].get(metric_key)
            if isinstance(first_val, (int, float)) and isinstance(last_val, (int, float)):
                if last_val > first_val:
                    lines.append("Trend: increasing over the period.")
                elif last_val < first_val:
                    lines.append("Trend: decreasing over the period.")
                else:
                    lines.append("Trend: stable over the period.")

        return "\n".join(lines)

    def _generic_answer(
        self, intent: ResolvedIntent, rows: List[Dict[str, Any]]
    ) -> str:
        return f"Query returned {len(rows)} row(s)."

    def _filter_context(self, intent: ResolvedIntent) -> str:
        parts: List[str] = []
        if intent.filters:
            filter_strs = [
                f"{f.field} {f.operator} {f.value}" for f in intent.filters
            ]
            parts.append("Filters applied: " + ", ".join(filter_strs) + ".")
        return "  ".join(parts)

    def _violation_summary(self, violations: List[RuleViolation]) -> str:
        errors = [v for v in violations if v.severity == "error"]
        warns = [v for v in violations if v.severity == "warning"]
        lines: List[str] = []
        if errors:
            lines.append(
                f"⚠ {len(errors)} data quality error(s): "
                + "; ".join(v.description for v in errors[:3])
                + ("..." if len(errors) > 3 else ".")
            )
        if warns:
            lines.append(
                f"ℹ {len(warns)} warning(s): "
                + "; ".join(v.description for v in warns[:3])
                + ("..." if len(warns) > 3 else ".")
            )
        return "  ".join(lines)
