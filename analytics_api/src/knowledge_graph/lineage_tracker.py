"""
lineage_tracker.py — LineageTracker

Appends one JSONL record per query execution to a lineage log file.
Each record captures the full provenance: what question was asked, what
metric/entity was resolved, what SQL was generated, and the result shape.

Log location: data/lineage/lineage_log.jsonl (relative to the project root).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Resolve project root: two levels above analytics_api/src/knowledge_graph/
_PROJECT_ROOT = Path(__file__).parents[4]
_DEFAULT_LOG_PATH = _PROJECT_ROOT / "data" / "lineage" / "lineage_log.jsonl"


class LineageTracker:
    """Append-only JSONL lineage log for query audit and reproducibility.

    Example::

        tracker = LineageTracker()
        tracker.record(
            question="delinquency rate for personal loans in 2024",
            metric="DelinquencyRate",
            concept="Delinquency",
            resolved_source="credit_risk.org_balance_sheet",
            generated_sql="SELECT ...",
            row_count=12,
            execution_ms=340,
        )
    """

    def __init__(self, log_path: Optional[Path] = None) -> None:
        self._path = log_path or _DEFAULT_LOG_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        question: str,
        metric: Optional[str] = None,
        concept: Optional[str] = None,
        variant: Optional[str] = None,
        resolved_source: Optional[str] = None,
        generated_sql: Optional[str] = None,
        row_count: Optional[int] = None,
        execution_ms: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
        dimensions: Optional[List[str]] = None,
        rule_violations: Optional[List[Dict[str, Any]]] = None,
        error: Optional[str] = None,
        tenant_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> None:
        """Append a single lineage record to the JSONL log."""
        entry: Dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "question": question,
            "metric": metric,
            "concept": concept,
            "variant": variant,
            "resolved_source": resolved_source,
            "sql_length": len(generated_sql) if generated_sql else None,
            "row_count": row_count,
            "execution_ms": execution_ms,
            "filters": filters,
            "dimensions": dimensions,
            "rule_violations": rule_violations or [],
            "error": error,
            "tenant_id": tenant_id,
            "request_id": request_id,
        }
        # Strip None values to keep log compact
        entry = {k: v for k, v in entry.items() if v is not None}

        try:
            with self._path.open("a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError as exc:
            logger.warning("LineageTracker: could not write to %s — %s", self._path, exc)

    def read_recent(self, n: int = 100) -> List[Dict[str, Any]]:
        """Return the last ``n`` lineage records (most recent last)."""
        if not self._path.exists():
            return []
        lines = self._path.read_text().splitlines()
        recent = lines[-n:]
        records = []
        for line in recent:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records
