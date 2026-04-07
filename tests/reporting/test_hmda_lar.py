from __future__ import annotations

from pathlib import Path

from reporting.hmda_lar import (
    HMDA_EXEMPT_NUMERIC,
    HMDA_EXEMPT_STRING,
    build_lar_from_audit_log,
    export_lar_pipe_delimited,
    validate_lar,
)


def test_pipe_format_no_header(tmp_path: Path) -> None:
    audit = [
        {
            "application_id": "M1",
            "product": "mortgage",
            "decision": "DENY",
            "application_date": "2026-01-02",
            "decision_date": "2026-01-10",
            "loan_amount": 250000,
            "apr_assigned": 0.0625,
            "features": {"annual_income": 120000, "dti": 0.35},
        }
    ]

    records = build_lar_from_audit_log(audit, lei="12345678901234567890")
    out = tmp_path / "hmda_lar.txt"
    n = export_lar_pipe_delimited(records, out)
    assert n == 1

    first_line = out.read_text().splitlines()[0]
    assert first_line.startswith("12345678901234567890|")


def test_lei_validation_length() -> None:
    audit = [
        {
            "application_id": "M2",
            "product": "mortgage",
            "decision": "DENY",
            "loan_amount": 100000,
            "features": {},
        }
    ]
    records = build_lar_from_audit_log(audit, lei="TOO_SHORT")
    errs = validate_lar(records)
    assert any(e["field"] == "lei" for e in errs)


def test_denial_reason_mapping_from_fcra_code() -> None:
    audit = [
        {
            "application_id": "M3",
            "product": "mortgage",
            "decision": "DENY",
            "loan_amount": 100000,
            "adverse_action_reasons": ["CREDIT_HISTORY"],
            "features": {},
        }
    ]
    records = build_lar_from_audit_log(audit, lei="12345678901234567890")
    assert records[0].denial_reason_1 == 3  # HMDA denial reason: Credit history


def test_exempt_fields_use_correct_hmda_code() -> None:
    audit = [
        {
            "application_id": "M4",
            "product": "mortgage",
            "decision": "APPROVE",
            "loan_amount": 150000,
            "features": {},
        }
    ]
    records = build_lar_from_audit_log(audit, lei="12345678901234567890")
    rec = records[0]
    assert rec.census_tract == HMDA_EXEMPT_STRING
    assert rec.county_code == HMDA_EXEMPT_STRING
    assert rec.applicant_ethnicity_1 == HMDA_EXEMPT_NUMERIC
