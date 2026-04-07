"""
MRM Lifecycle CLI — Section 21.4.1
=====================================
Command-line tool for the Model Risk Management team to manage SR 11-7
lifecycle transitions across all registered models (CC PD, CC Origination
Valuation, CC Portfolio Action, Mortgage Valuation).

Usage
-----
  python scripts/mrm_lifecycle.py submit-for-validation \\
      --model cc_portfolio_action --version 3

  python scripts/mrm_lifecycle.py record-validation \\
      --model cc_portfolio_action --version 3 \\
      --outcome PASS --validator mrm@example.com \\
      --type INITIAL

  python scripts/mrm_lifecycle.py promote \\
      --model cc_portfolio_action --version 3 \\
      --stage Production --approved-by cro@example.com \\
      --performed-by mrm@example.com

  python scripts/mrm_lifecycle.py archive \\
      --model cc_portfolio_action --version 2 \\
      --performed-by mrm@example.com

  python scripts/mrm_lifecycle.py list-models

  python scripts/mrm_lifecycle.py model-status \\
      --model cc_portfolio_action

Environment Variables
---------------------
  MLFLOW_TRACKING_URI   — MLflow server URI (default: sqlite:///./mlflow/mlruns.db)
  MRM_DB_URL            — SQLAlchemy async DB URL for audit tables
                          (default: sqlite+aiosqlite:///./audit/mrm_audit.db)
  MRM_PERFORMED_BY      — Default email for --performed-by if not supplied
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from audit.logger import (
    log_governance_action,
    log_model_validation,
    check_validation_independence,
    get_governance_audit_log,
    get_model_validations,
)
from mlflow_config.mlflow_config import (
    ModelRegistry,
    ALL_REGISTERED_MODELS,
    MODEL_GOVERNANCE,
    SR117_STAGES,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("mrm_lifecycle")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_DB_URL = os.getenv(
    "MRM_DB_URL", f"sqlite+aiosqlite:///{_ROOT / 'audit' / 'mrm_audit.db'}"
)
DEFAULT_PERFORMED_BY = os.getenv("MRM_PERFORMED_BY", "mrm-system@example.com")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_mlflow_client():
    """Return an MlflowClient, configuring the tracking URI first."""
    from mlflow_config.mlflow_config import configure_mlflow
    from mlflow.tracking import MlflowClient

    configure_mlflow()
    return MlflowClient()


def _get_run_metrics(run_id: str) -> Dict[str, Any]:
    """Fetch MLflow run metrics for a given run_id."""
    try:
        import mlflow

        run = mlflow.get_run(run_id)
        return dict(run.data.metrics)
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not fetch metrics for run_id=%s: %s", run_id, exc)
        return {}


def _print_table(rows: List[Dict[str, Any]], cols: Optional[List[str]] = None) -> None:
    """Simple ASCII table printer."""
    if not rows:
        print("  (no records found)")
        return
    keys = cols or list(rows[0].keys())
    widths = {k: max(len(str(k)), max(len(str(r.get(k, ""))) for r in rows)) for k in keys}
    header = "  ".join(str(k).ljust(widths[k]) for k in keys)
    sep = "  ".join("-" * widths[k] for k in keys)
    print(header)
    print(sep)
    for row in rows:
        print("  ".join(str(row.get(k, "")).ljust(widths[k]) for k in keys))


# ---------------------------------------------------------------------------
# Sub-commands
# ---------------------------------------------------------------------------


def cmd_list_models(args: argparse.Namespace) -> int:
    """List all registered models with current stage, version, and next review."""
    client = _get_mlflow_client()
    rows = []
    for model_name in ALL_REGISTERED_MODELS:
        try:
            versions = client.search_model_versions(f"name='{model_name}'")
        except Exception:
            versions = []

        if not versions:
            rows.append({
                "model_name": model_name,
                "version": "—",
                "stage": "not_registered",
                "review_cycle_months": MODEL_GOVERNANCE.get(model_name, {}).get("review_cycle_months", "?"),
                "sr11_7_stage": "—",
            })
            continue

        for mv in versions:
            tags = mv.tags or {}
            rows.append({
                "model_name":          model_name,
                "version":             mv.version,
                "stage":               mv.current_stage,
                "run_id":              (mv.run_id or "")[:12],
                "sr11_7_stage":        tags.get("sr11_7_stage", "—"),
                "review_cycle_months": MODEL_GOVERNANCE.get(model_name, {}).get("review_cycle_months", "?"),
            })

    print(f"\n{'='*80}")
    print(" REGISTERED MODELS — MRM Registry Overview")
    print(f"{'='*80}")
    _print_table(rows, ["model_name", "version", "stage", "sr11_7_stage", "review_cycle_months", "run_id"])
    print()
    return 0


def cmd_model_status(args: argparse.Namespace) -> int:
    """Show full status for a single model — all versions + governance thresholds."""
    client = _get_mlflow_client()
    model_name = args.model

    try:
        versions = client.search_model_versions(f"name='{model_name}'")
    except Exception as exc:
        log.error("Could not query model '%s': %s", model_name, exc)
        return 1

    print(f"\n{'='*80}")
    print(f" Model: {model_name}")
    print(f"{'='*80}")

    # Governance thresholds
    gov = MODEL_GOVERNANCE.get(model_name, {})
    if gov:
        print("\nGovernance Thresholds:")
        for k, v in gov.items():
            print(f"  {k}: {v}")

    # Version history
    print("\nVersion History:")
    _print_table(
        [
            {
                "version": mv.version,
                "stage": mv.current_stage,
                "run_id": (mv.run_id or "")[:16],
                "status": mv.status,
                "sr11_7_stage": (mv.tags or {}).get("sr11_7_stage", "—"),
            }
            for mv in versions
        ]
    )

    # Governance audit log (last 10 entries)
    audit_log = asyncio.run(
        get_governance_audit_log(model_name, DEFAULT_DB_URL, limit=10)
    )
    if audit_log:
        print("\nGovernance Audit Log (last 10):")
        _print_table(audit_log, ["action", "model_version", "performed_by", "approved_by", "performed_at", "notes"])

    # Validation log
    validations = asyncio.run(get_model_validations(model_name, DEFAULT_DB_URL))
    if validations:
        print("\nValidation Log:")
        _print_table(
            validations,
            ["validation_type", "outcome", "validator_email", "approved_for_prod", "validation_date"],
        )

    print()
    return 0


def cmd_submit_for_validation(args: argparse.Namespace) -> int:
    """Tag model version as needing independent validation (SR 11-7 step 1)."""
    client = _get_mlflow_client()
    model_name = args.model
    version = str(args.version)
    performed_by = args.performed_by or DEFAULT_PERFORMED_BY

    # Set MLflow tag
    try:
        client.set_model_version_tag(model_name, version, "sr11_7_stage", "independent_validation")
        log.info("Tagged %s v%s as independent_validation", model_name, version)
    except Exception as exc:
        log.error("Could not tag model version: %s", exc)
        return 1

    # Write governance record
    mv = client.get_model_version(model_name, version)
    metrics = _get_run_metrics(mv.run_id) if mv.run_id else {}
    approval_id = asyncio.run(
        log_governance_action(
            model_name=model_name,
            model_version=version,
            action="PROMOTE_STAGING",
            from_stage=mv.current_stage,
            to_stage="independent_validation",
            performed_by=performed_by,
            approved_by=None,
            governance_metrics=metrics,
            notes=f"Submitted for independent validation by {performed_by}",
            mlflow_run_id=mv.run_id,
            db_url=DEFAULT_DB_URL,
        )
    )
    print(f"✓ Submitted {model_name} v{version} for independent validation.")
    print(f"  Governance record: approval_id={approval_id}")
    return 0


def cmd_record_validation(args: argparse.Namespace) -> int:
    """Record an independent validation outcome (PASS / PASS_WITH_CONDITIONS / FAIL)."""
    model_name = args.model
    version = str(args.version)
    outcome = args.outcome.upper()
    validator_email = args.validator
    validation_type = (args.type or "INITIAL").upper()
    conditions_raw = args.conditions or "[]"
    notes = args.notes or ""
    test_scripts_ref = args.test_scripts_ref

    if outcome not in ("PASS", "PASS_WITH_CONDITIONS", "FAIL"):
        log.error("--outcome must be PASS | PASS_WITH_CONDITIONS | FAIL")
        return 1

    # Validate independence
    independent = asyncio.run(
        check_validation_independence(model_name, version, validator_email, DEFAULT_DB_URL)
    )
    if not independent:
        log.error(
            "Independence violation: validator_email matches developer_email. "
            "SR 11-7 requires independent validation. Aborting."
        )
        return 2

    # Parse conditions
    try:
        conditions = json.loads(conditions_raw) if conditions_raw != "[]" else []
    except json.JSONDecodeError:
        conditions = [conditions_raw]

    approved_for_prod = outcome in ("PASS", "PASS_WITH_CONDITIONS")

    validation_id = asyncio.run(
        log_model_validation(
            model_name=model_name,
            model_version=version,
            validator_email=validator_email,
            validation_type=validation_type,
            outcome=outcome,
            conditions=conditions,
            findings=None,
            test_scripts_ref=test_scripts_ref,
            approved_for_prod=approved_for_prod,
            notes=notes,
            db_url=DEFAULT_DB_URL,
        )
    )

    # Update MLflow tag
    client = _get_mlflow_client()
    try:
        client.set_model_version_tag(model_name, version, "validation_outcome", outcome)
        client.set_model_version_tag(model_name, version, "validator", validator_email)
    except Exception as exc:
        log.warning("Could not update MLflow tags: %s", exc)

    # Write governance record
    action = "VALIDATION_PASS" if outcome == "PASS" else (
        "VALIDATION_PASS" if outcome == "PASS_WITH_CONDITIONS" else "VALIDATION_FAIL"
    )
    asyncio.run(
        log_governance_action(
            model_name=model_name,
            model_version=version,
            action=action,
            from_stage="independent_validation",
            to_stage="mrm_approval" if approved_for_prod else "development",
            performed_by=validator_email,
            approved_by=None,
            governance_metrics={},
            notes=f"Validation {outcome}. Conditions: {conditions}",
            mlflow_run_id=None,
            db_url=DEFAULT_DB_URL,
        )
    )

    print(f"✓ Validation recorded: {model_name} v{version} → {outcome}")
    print(f"  validation_id={validation_id}")
    if conditions:
        print(f"  Conditions: {conditions}")
    return 0


def cmd_promote(args: argparse.Namespace) -> int:
    """Promote a model version to a new MLflow stage with governance checks."""
    model_name = args.model
    version = str(args.version)
    stage = args.stage
    approved_by = args.approved_by
    performed_by = args.performed_by or DEFAULT_PERFORMED_BY
    notes = args.notes or ""

    if stage == "Production" and not approved_by:
        log.error("--approved-by is required for Production promotion. Aborting.")
        return 1

    client = _get_mlflow_client()
    mv = client.get_model_version(model_name, version)

    # P3.5: Block Production promotion without a passing automated MVR.
    if stage == "Production":
        tags = mv.tags or {}
        mvr_ok = str(tags.get("mvr_all_gates_passed", "")).lower() == "true"
        mvr_path = str(tags.get("mvr_report_path", ""))
        if not mvr_ok:
            log.error(
                "Production promotion blocked: no passing MVR found for %s v%s. "
                "Run: python scripts/mrm_lifecycle.py validate --model-name %s --version %s ...",
                model_name,
                version,
                model_name,
                version,
            )
            raise SystemExit(1)
        if not mvr_path:
            log.error("Production promotion blocked: mvr_report_path tag missing for %s v%s", model_name, version)
            raise SystemExit(1)

    # Check that a passing validation exists before Production promotion
    if stage == "Production":
        validations = asyncio.run(get_model_validations(model_name, DEFAULT_DB_URL))
        valid_validations = [
            v for v in validations
            if str(v.get("model_version")) == version
            and v.get("outcome") in ("PASS", "PASS_WITH_CONDITIONS")
            and v.get("approved_for_prod")
        ]
        if not valid_validations:
            log.error(
                "No passing validation record found for %s v%s. "
                "SR 11-7 requires independent validation before Production promotion.",
                model_name, version,
            )
            return 2

    from_stage = mv.current_stage
    metrics = _get_run_metrics(mv.run_id) if mv.run_id else {}

    # Run governance check + MLflow stage transition
    registry = ModelRegistry()
    try:
        registry.promote_model(model_name, version, stage)
    except Exception as exc:
        log.error("Governance check or promotion failed: %s", exc)
        # Log as governance override attempt
        asyncio.run(
            log_governance_action(
                model_name=model_name,
                model_version=version,
                action="GOVERNANCE_OVERRIDE",
                from_stage=from_stage,
                to_stage=stage,
                performed_by=performed_by,
                approved_by=approved_by,
                governance_metrics=metrics,
                notes=f"FAILED governance check: {exc}",
                mlflow_run_id=mv.run_id,
                db_url=DEFAULT_DB_URL,
            )
        )
        return 3

    # Write governance approval record
    action = f"PROMOTE_{stage.upper()}"
    approval_id = asyncio.run(
        log_governance_action(
            model_name=model_name,
            model_version=version,
            action=action,
            from_stage=from_stage,
            to_stage=stage,
            performed_by=performed_by,
            approved_by=approved_by,
            governance_metrics=metrics,
            notes=notes or f"Promoted to {stage} by {performed_by}, approved by {approved_by}",
            mlflow_run_id=mv.run_id,
            db_url=DEFAULT_DB_URL,
        )
    )

    print(f"✓ Promoted {model_name} v{version}: {from_stage} → {stage}")
    print(f"  Governance record: approval_id={approval_id}")
    return 0


def cmd_archive(args: argparse.Namespace) -> int:
    """Archive (sunset) a model version."""
    model_name = args.model
    version = str(args.version)
    performed_by = args.performed_by or DEFAULT_PERFORMED_BY
    notes = args.notes or f"Archived by {performed_by}"

    client = _get_mlflow_client()
    mv = client.get_model_version(model_name, version)
    from_stage = mv.current_stage

    registry = ModelRegistry()
    try:
        registry.promote_model(model_name, version, "Archived")
    except Exception as exc:
        log.error("Archive failed: %s", exc)
        return 1

    approval_id = asyncio.run(
        log_governance_action(
            model_name=model_name,
            model_version=version,
            action="ARCHIVE",
            from_stage=from_stage,
            to_stage="sunset",
            performed_by=performed_by,
            approved_by=None,
            governance_metrics={},
            notes=notes,
            mlflow_run_id=mv.run_id,
            db_url=DEFAULT_DB_URL,
        )
    )

    print(f"✓ Archived {model_name} v{version} (sr11_7_stage=sunset)")
    print(f"  Governance record: approval_id={approval_id}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Run automated validation suite and write an evidentiary MVR report."""
    model_name = str(args.model_name)
    version = str(args.version)
    holdout = Path(str(args.holdout))
    output_dir = Path(str(args.output))

    if not holdout.exists():
        log.error("Holdout path not found: %s", holdout)
        return 2

    mlflow_tracking_uri = os.getenv(
        "MLFLOW_TRACKING_URI",
        os.getenv("MLFLOW_URI", f"sqlite:///{_ROOT / 'mlruns' / 'mlflow.db'}"),
    )

    # Infer feature columns from holdout if not provided.
    import pandas as pd  # noqa: PLC0415

    if holdout.suffix.lower() in {".parquet", ".pq"}:
        df = pd.read_parquet(holdout)
    else:
        df = pd.read_csv(holdout)

    target_col = str(getattr(args, "target_col", "default_flag"))
    if target_col not in df.columns:
        log.error("Target column '%s' not found in holdout.", target_col)
        return 3

    feature_cols = [c for c in df.columns if c != target_col]
    demographic_col = getattr(args, "demographic_col", None)

    # Resolve run_id from MLflow model version.
    client = _get_mlflow_client()
    mv = client.get_model_version(model_name, version)
    mlflow_run_id = mv.run_id or ""

    from validation.automated_suite import ValidationConfig, run_validation_suite, save_validation_report

    cfg = ValidationConfig(
        model_registry_name=model_name,
        model_version=version,
        mlflow_run_id=mlflow_run_id,
        holdout_data_path=holdout,
        feature_cols=feature_cols,
        target_col=target_col,
        demographic_col=demographic_col,
    )

    report = run_validation_suite(cfg, mlflow_tracking_uri=mlflow_tracking_uri)
    out_path = save_validation_report(
        report,
        output_dir=output_dir,
        commit_to_mlflow=True,
        mlflow_tracking_uri=mlflow_tracking_uri,
        model_registry_name=model_name,
    )

    print(f"✓ MVR saved: {out_path}")
    if not report.all_gates_passed:
        print("✗ Automated validation gates failed:")
        for s in report.gate_failures:
            print(f"  - {s}")
        return 1

    print("✓ All automated validation gates passed.")
    return 0


def cmd_promote_challenger(args: argparse.Namespace) -> int:
    """Champion/Challenger go/no-go promotion gate (Phase 2)."""
    try:
        from decisioning.champion_challenger import CCDecisionStore
    except Exception as exc:  # noqa: BLE001
        log.error("decisioning.champion_challenger not available: %s", exc)
        return 1

    store = CCDecisionStore(db_url=args.cc_db_url)
    report = store.generate_comparison_report(lookback_days=int(args.lookback_days))

    print("\n" + "=" * 80)
    print(" CHAMPION/CHALLENGER — PROMOTION GATE")
    print("=" * 80)
    print(f"Period: {report.period_start} → {report.period_end}")
    print(f"Champion approval rate:   {report.champion_approval_rate:.3f}")
    print(f"Challenger approval rate: {report.challenger_approval_rate:.3f}")
    print(f"Approval delta:           {report.approval_rate_delta:+.3f}")
    print(f"Champion mean PD:         {report.champion_mean_pd:.4f}")
    print(f"Challenger mean PD:       {report.challenger_mean_pd:.4f}")
    print(f"Sample sizes: champion={report.sample_size_champion}, challenger={report.sample_size_challenger}")
    print(f"Recommendation: {report.recommendation}")
    print()

    if report.recommendation == "PROMOTE":
        log.info("Auto-approved challenger promotion (PROMOTE)")
        print("✓ Auto-approved (PROMOTE)")
        return 0

    if report.recommendation == "HOLD":
        print("Manual four-eyes approval required (HOLD).")
        ans = input("Type 'PROMOTE' to approve, anything else to abort: ").strip().upper()
        if ans == "PROMOTE":
            log.info("Manual approval granted for challenger promotion")
            print("✓ Approved manually")
            return 0
        log.warning("Manual approval not granted; promotion aborted")
        print("✗ Aborted")
        return 1

    # REJECT
    log.error("Promotion blocked (REJECT)")
    print("✗ Blocked (REJECT)")
    return 2


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MRM Lifecycle CLI — SR 11-7 model governance for credit-risk-platform",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # list-models
    sub.add_parser("list-models", help="List all registered models with current stage")

    # model-status
    p_status = sub.add_parser("model-status", help="Show full status for a model")
    p_status.add_argument("--model", required=True, help="Registered model name")

    # submit-for-validation
    p_submit = sub.add_parser("submit-for-validation", help="Tag model for independent validation")
    p_submit.add_argument("--model", required=True)
    p_submit.add_argument("--version", required=True)
    p_submit.add_argument("--performed-by", default=None)

    # record-validation
    p_val = sub.add_parser("record-validation", help="Record independent validation outcome")
    p_val.add_argument("--model", required=True)
    p_val.add_argument("--version", required=True)
    p_val.add_argument("--outcome", required=True, choices=["PASS", "PASS_WITH_CONDITIONS", "FAIL"])
    p_val.add_argument("--validator", required=True, help="Validator email (must differ from developer)")
    p_val.add_argument("--type", default="INITIAL", choices=["INITIAL", "ANNUAL", "TRIGGERED"])
    p_val.add_argument("--conditions", default="[]", help="JSON list of remediation conditions")
    p_val.add_argument("--notes", default="")
    p_val.add_argument("--test-scripts-ref", default=None, help="Git SHA of validation test scripts")

    # promote
    p_promote = sub.add_parser("promote", help="Promote a model version to a new stage")
    p_promote.add_argument("--model", required=True)
    p_promote.add_argument("--version", required=True)
    p_promote.add_argument("--stage", required=True, choices=["Staging", "Production"])
    p_promote.add_argument("--approved-by", default=None, help="Required for Production")
    p_promote.add_argument("--performed-by", default=None)
    p_promote.add_argument("--notes", default="")

    # archive
    p_archive = sub.add_parser("archive", help="Archive (sunset) a model version")
    p_archive.add_argument("--model", required=True)
    p_archive.add_argument("--version", required=True)
    p_archive.add_argument("--performed-by", default=None)
    p_archive.add_argument("--notes", default="")

    # validate (P3.5)
    p_validate = sub.add_parser("validate", help="Run automated model validation suite (MVR)")
    p_validate.add_argument("--model-name", required=True)
    p_validate.add_argument("--version", required=True)
    p_validate.add_argument("--holdout", required=True)
    p_validate.add_argument("--output", required=True)
    p_validate.add_argument("--target-col", default="default_flag")
    p_validate.add_argument("--demographic-col", default=None)

    # promote-challenger
    p_cc = sub.add_parser("promote-challenger", help="Run champion/challenger go/no-go promotion gate")
    p_cc.add_argument(
        "--cc-db-url",
        default=os.getenv("CC_DECISIONS_DB_URL", f"sqlite:///{_ROOT / 'audit' / 'cc_decisions.db'}"),
        help="SQLAlchemy DB URL for cc_decisions store",
    )
    p_cc.add_argument("--lookback-days", type=int, default=7)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    dispatch = {
        "list-models":            cmd_list_models,
        "model-status":           cmd_model_status,
        "submit-for-validation":  cmd_submit_for_validation,
        "record-validation":      cmd_record_validation,
        "promote":                cmd_promote,
        "archive":                cmd_archive,
        "validate":               cmd_validate,
        "promote-challenger":     cmd_promote_challenger,
    }

    handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        return 1

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
