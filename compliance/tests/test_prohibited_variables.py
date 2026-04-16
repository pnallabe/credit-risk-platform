"""
Tests for compliance/prohibited_variables.py
=============================================
Verifies that the registry correctly blocks prohibited and proxy variables,
and that the ComplianceEngine gate integrates the PV001 check.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))

from compliance.prohibited_variables import (
    ProhibitedVariableViolation,
    check_for_prohibited_variables,
)


# ---------------------------------------------------------------------------
# Direct-registry tests
# ---------------------------------------------------------------------------


def test_direct_prohibited_variable():
    """A feature dict containing 'race' raises ProhibitedVariableViolation."""
    with pytest.raises(ProhibitedVariableViolation) as exc_info:
        check_for_prohibited_variables({"race": "white", "credit_score": 720})
    assert exc_info.value.variable == "race"
    assert "race" in exc_info.value.basis


def test_proxy_variable():
    """A feature dict containing 'zip_code' raises ProhibitedVariableViolation."""
    with pytest.raises(ProhibitedVariableViolation) as exc_info:
        check_for_prohibited_variables({"zip_code": "90210", "dti": 0.3})
    assert exc_info.value.variable == "zip_code"
    assert "national_origin" in exc_info.value.basis or "race" in exc_info.value.basis


def test_case_insensitive():
    """Keys are compared case-insensitively ('RACE' is blocked like 'race')."""
    with pytest.raises(ProhibitedVariableViolation) as exc_info:
        check_for_prohibited_variables({"RACE": "hispanic", "credit_score": 600})
    assert exc_info.value.variable == "RACE"


def test_clean_features():
    """Standard credit features (no protected-class variables) do not raise."""
    check_for_prohibited_variables(
        {
            "credit_score": 720,
            "debt_to_income_ratio": 0.28,
            "annual_income": 95_000.0,
            "num_open_accounts": 4,
            "loan_amount": 15_000.0,
        }
    )  # must not raise


def test_gender_proxy():
    """'gender' is directly listed as a prohibited variable."""
    with pytest.raises(ProhibitedVariableViolation):
        check_for_prohibited_variables({"gender": "female", "credit_score": 680})


def test_proxy_census_tract():
    """'census_tract' is a proxy variable for race / national_origin."""
    with pytest.raises(ProhibitedVariableViolation) as exc_info:
        check_for_prohibited_variables({"census_tract": "123456", "credit_score": 700})
    assert "race" in exc_info.value.basis or "national_origin" in exc_info.value.basis


def test_empty_features():
    """An empty feature dict does not raise."""
    check_for_prohibited_variables({})  # must not raise


# ---------------------------------------------------------------------------
# ComplianceEngine integration test
# ---------------------------------------------------------------------------


def test_compliance_gate_blocks_on_prohibited():
    """ComplianceEngine.gate() with input_features={'gender': 'female'} returns
    passed=False with rule_code 'PV001' in flags."""
    from compliance.engine import ComplianceEngine

    engine = ComplianceEngine()
    result = engine.gate(
        source_system="test",
        apr_assigned=12.0,
        state="CA",
        is_active_military=False,
        is_covered_borrower=False,
        proposed_action="ACQUIRE",
        applicant_id_hash="abc123",
        decision_id="decision-test-001",
        policy_version_id="v1",
        input_features={"gender": "female", "credit_score": 680},
    )

    assert result.passed is False
    assert result.override == "DECLINE"
    assert any(f.rule_code == "PV001" for f in result.flags)
    blocked_codes = [f.rule_code for f in result.flags if f.severity == "BLOCK"]
    assert "PV001" in blocked_codes


def test_compliance_gate_passes_clean_features():
    """ComplianceEngine.gate() passes when input_features has no prohibited vars."""
    from compliance.engine import ComplianceEngine

    engine = ComplianceEngine()
    result = engine.gate(
        source_system="test",
        apr_assigned=12.0,
        state="CA",
        is_active_military=False,
        is_covered_borrower=False,
        proposed_action="ACQUIRE",
        applicant_id_hash="abc123",
        decision_id="decision-test-002",
        policy_version_id="v1",
        input_features={"credit_score": 720, "dti": 0.28},
    )

    # PV001 must NOT be present (other checks may still fire, but not prohibited vars)
    assert not any(f.rule_code == "PV001" for f in result.flags)
