"""
BigQuery Row-Level Access Policy Provisioner
=============================================
Creates BigQuery ROW ACCESS POLICIES for a given tenant+service-account pair,
ensuring that only the service account can read rows for that tenant.

This addresses GAP-03-D: BigQuery table schemas include `tenant_id` but no
IAM row-level access policy is provisioned by default.

Usage
-----
    # Dry run (preview DDL without executing)
    python scripts/provision_bq_tenant_policies.py \\
        --project my-gcp-project \\
        --dataset credit_risk_model_dev \\
        --tenant-id tenant-abc \\
        --service-account tenant-abc@my-gcp-project.iam.gserviceaccount.com \\
        --dry-run

    # Live provisioning
    python scripts/provision_bq_tenant_policies.py \\
        --project my-gcp-project \\
        --dataset credit_risk_model_dev \\
        --tenant-id tenant-abc \\
        --service-account tenant-abc@my-gcp-project.iam.gserviceaccount.com

Notes
-----
- Requires google-cloud-bigquery>=3.0.0 for live execution.
- In --dry-run mode, no GCP credentials are required.
- Idempotent: existing policies with the same name are skipped.
- Logs each provisioned/skipped policy as a JSON object to stdout for audit ingestion.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tables that carry tenant_id — derived from db/bigquery_schema.py
# ---------------------------------------------------------------------------

# All tables whose schema includes a 'tenant_id' REQUIRED or NULLABLE field.
_TENANT_BEARING_TABLES: List[str] = [
    "audit_log",
    "portfolio_audit_log",
    "loan_applications",
    "feature_vectors",
    "model_scores",
    "credit_decisions",
    "explanations",
    "drift_reports",
    "fair_lending_reports",
    "experiment_results",
]


def _policy_name(tenant_id: str) -> str:
    """Return a BigQuery-safe policy name for a given tenant_id."""
    return f"tenant_{tenant_id.replace('-', '_').replace('.', '_')}_policy"


def _build_ddl(
    project: str,
    dataset: str,
    table: str,
    tenant_id: str,
    service_account: str,
) -> str:
    """Build a BigQuery ROW ACCESS POLICY DDL statement.

    BigQuery syntax: https://cloud.google.com/bigquery/docs/row-level-security-intro
    """
    policy_name = _policy_name(tenant_id)
    return (
        f"CREATE ROW ACCESS POLICY IF NOT EXISTS {policy_name}\n"
        f"ON `{project}.{dataset}.{table}`\n"
        f'GRANT TO ("serviceAccount:{service_account}")\n'
        f"FILTER USING (tenant_id = '{tenant_id}');\n"
    )


def _policy_exists(client: Any, project: str, dataset: str, table: str, tenant_id: str) -> bool:
    """Check INFORMATION_SCHEMA.ROW_ACCESS_POLICIES to see if the policy already exists."""
    policy_name = _policy_name(tenant_id)
    query = (
        f"SELECT COUNT(*) AS cnt "
        f"FROM `{project}.{dataset}`.INFORMATION_SCHEMA.ROW_ACCESS_POLICIES "
        f"WHERE table_name = '{table}' AND policy_tag = '{policy_name}'"
    )
    try:
        result = client.query(query).result()
        for row in result:
            return row.cnt > 0
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not query INFORMATION_SCHEMA (%s), assuming policy absent: %s", table, exc)
    return False


def provision_tenant_policies(
    project: str,
    dataset: str,
    tenant_id: str,
    service_account: str,
    dry_run: bool = False,
    tables: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Provision row-level access policies for all tenant-bearing tables.

    Parameters
    ----------
    project :
        GCP project ID.
    dataset :
        BigQuery dataset ID.
    tenant_id :
        Tenant identifier for the policy filter.
    service_account :
        Service account email that will be granted read access via the policy.
    dry_run :
        If True, return the DDL statements without executing them.
    tables :
        If provided, only provision policies for these tables.
        Defaults to ``_TENANT_BEARING_TABLES``.

    Returns
    -------
    List[Dict[str, Any]]
        A list of audit log entries, one per table, with the following fields:
        - ``table``: table name
        - ``policy_name``: policy identifier
        - ``status``: ``"provisioned"`` | ``"skipped"`` | ``"dry_run"``
        - ``ddl``: the DDL statement (always present for audit purposes)
        - ``timestamp``: ISO-8601 UTC timestamp
    """
    target_tables = tables if tables is not None else _TENANT_BEARING_TABLES
    results: List[Dict[str, Any]] = []
    ts = datetime.now(timezone.utc).isoformat()

    # Only import the BQ client for live runs
    client = None
    if not dry_run:
        try:
            from google.cloud import bigquery
            client = bigquery.Client(project=project)
        except ImportError as exc:
            raise RuntimeError(
                "google-cloud-bigquery is required for live provisioning. "
                "Install it with: pip install google-cloud-bigquery>=3.0.0"
            ) from exc

    for table in target_tables:
        ddl = _build_ddl(project, dataset, table, tenant_id, service_account)
        policy_name = _policy_name(tenant_id)

        if dry_run:
            entry = {
                "table": table,
                "policy_name": policy_name,
                "status": "dry_run",
                "ddl": ddl,
                "timestamp": ts,
            }
            print(ddl)
        else:
            # Idempotency check
            if _policy_exists(client, project, dataset, table, tenant_id):
                entry = {
                    "table": table,
                    "policy_name": policy_name,
                    "status": "skipped",
                    "ddl": ddl,
                    "timestamp": ts,
                }
                logger.info("Policy already exists for table=%s tenant=%s — skipped", table, tenant_id)
            else:
                try:
                    client.query(ddl).result()
                    entry = {
                        "table": table,
                        "policy_name": policy_name,
                        "status": "provisioned",
                        "ddl": ddl,
                        "timestamp": ts,
                    }
                    logger.info("Provisioned policy for table=%s tenant=%s", table, tenant_id)
                except Exception as exc:  # noqa: BLE001
                    entry = {
                        "table": table,
                        "policy_name": policy_name,
                        "status": "error",
                        "ddl": ddl,
                        "error": str(exc),
                        "timestamp": ts,
                    }
                    logger.error("Failed to provision policy for table=%s: %s", table, exc)

        # Always log the entry as JSON for audit trail ingestion
        print(json.dumps(entry))
        results.append(entry)

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Provision BigQuery row-level access policies for a tenant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--project", required=True, help="GCP project ID")
    parser.add_argument("--dataset", required=True, help="BigQuery dataset ID")
    parser.add_argument("--tenant-id", required=True, help="Tenant ID to provision policy for")
    parser.add_argument(
        "--service-account",
        required=True,
        help="Service account email to grant row-level access to",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print DDL without executing",
    )
    parser.add_argument(
        "--tables",
        nargs="*",
        default=None,
        help="Specific tables to provision (defaults to all tenant-bearing tables)",
    )
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
    args = _parse_args()

    results = provision_tenant_policies(
        project=args.project,
        dataset=args.dataset,
        tenant_id=args.tenant_id,
        service_account=args.service_account,
        dry_run=args.dry_run,
        tables=args.tables,
    )

    errors = [r for r in results if r.get("status") == "error"]
    if errors:
        logger.error("%d table(s) failed policy provisioning", len(errors))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
