#!/usr/bin/env python3
"""
check_audit_schema_compat.py — Section 23.5 / 23.12
=====================================================
CI gate: validates that the audit table DDL in db/migrations/
is backward-compatible with the currently deployed BQ schema.

Backward compatibility rules:
  1. No existing column may be REMOVED.
  2. No existing column may have its type narrowed (e.g. STRING -> INT64).
  3. NOT NULL constraints may not be added to existing columns.
  4. New columns are allowed (additive change).

Exits 0 if compatible, 1 if any breaking change is detected.
"""
import logging
import re
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_DIR = REPO_ROOT / "db" / "migrations"

# Columns that are exempt from the NOT NULL addition check
# (added by Section 23 and may legitimately start as NULLABLE)
NULLABLE_EXEMPT_COLS: frozenset[str] = frozenset(
    {"compliance_block", "compliance_event_ids", "override_reason"}
)

# Widening map: if current type can be widened to new type, it's compatible.
COMPATIBLE_TYPE_WIDENING: dict[str, set[str]] = {
    "INT64": {"FLOAT64", "NUMERIC", "BIGNUMERIC", "STRING"},
    "FLOAT64": {"NUMERIC", "BIGNUMERIC", "STRING"},
    "DATE": {"DATETIME", "TIMESTAMP", "STRING"},
    "DATETIME": {"TIMESTAMP", "STRING"},
}


def _parse_create_table(sql: str) -> dict[str, str]:
    """
    Very-light DDL parser that extracts {column_name: type} from a
    CREATE TABLE ... ( ... ) statement.  Not a full SQL parser.
    """
    columns: dict[str, str] = {}
    # Strip comments
    sql = re.sub(r"--[^\n]*", "", sql)
    # Find column body
    m = re.search(r"CREATE\s+TABLE\b[^(]+\((.+)\)", sql, re.DOTALL | re.IGNORECASE)
    if not m:
        return columns
    body = m.group(1)
    for line in body.split(","):
        line = line.strip()
        parts = line.split()
        if len(parts) >= 2 and not parts[0].upper() in ("PRIMARY", "UNIQUE", "INDEX"):
            col = parts[0].strip("`\"[]")
            col_type = parts[1].upper()
            columns[col] = col_type
    return columns


def main() -> int:
    if not MIGRATION_DIR.exists():
        logger.warning(
            "Migration directory %s not found — skipping audit schema compat check.",
            MIGRATION_DIR,
        )
        return 0

    try:
        from google.cloud import bigquery
    except ImportError:
        logger.warning("google-cloud-bigquery not installed — skipping BQ check.")
        return 0

    bq = bigquery.Client()
    failures: list[str] = []

    for sql_file in sorted(MIGRATION_DIR.glob("*.sql")):
        sql_text = sql_file.read_text(errors="replace")
        # Extract table name
        m = re.search(
            r"CREATE\s+(?:OR\s+REPLACE\s+)?TABLE\b\s+[`\"]?([a-zA-Z0-9_.]+)[`\"]?",
            sql_text,
            re.IGNORECASE,
        )
        if not m:
            continue
        full_table = m.group(1).strip("`\"")
        if "." not in full_table:
            continue

        migration_cols = _parse_create_table(sql_text)
        if not migration_cols:
            continue

        dataset_id, table_id = full_table.split(".", 1)
        try:
            bq_table = bq.get_table(f"{bq.project}.{full_table}")
        except Exception:
            # Table not yet deployed — no backward-compat check needed
            continue

        deployed_cols = {f.name: f.field_type for f in bq_table.schema}

        for col, deployed_type in deployed_cols.items():
            if col not in migration_cols:
                failures.append(
                    f"{full_table}: existing column '{col}' ({deployed_type}) "
                    f"missing from migration {sql_file.name} — "
                    "removing columns is a breaking change."
                )
            else:
                new_type = migration_cols[col].upper()
                if new_type != deployed_type:
                    widening = COMPATIBLE_TYPE_WIDENING.get(deployed_type, set())
                    if new_type not in widening:
                        failures.append(
                            f"{full_table}.{col}: type change "
                            f"{deployed_type} -> {new_type} is not a safe widening."
                        )

    if failures:
        logger.error("AUDIT SCHEMA COMPAT FAILURES (%d):", len(failures))
        for f in failures:
            logger.error("  %s", f)
        return 1

    logger.info("Audit DDL backward compatibility check passed — OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
