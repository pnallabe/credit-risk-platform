"""
Tests for ABTestingFramework (decision_engine/ab_testing.py)
"""
from __future__ import annotations

import math
import pytest

from decision_engine.ab_testing import (
    ABTestingFramework,
    Experiment,
    ExperimentOutcomeRecord,
    _required_sample_size,
    _z_score_two_proportions,
    _p_value_from_z,
)

DB_URL = "sqlite:///:memory:"


def _make_experiment(**kwargs) -> Experiment:
    defaults = dict(
        name="Test Experiment",
        description="desc",
        tenant_id="t-test",
        control_version_tag="v1.0",
        treatment_version_tag="v2.0",
        traffic_pct=0.5,
    )
    defaults.update(kwargs)
    return Experiment(**defaults)


@pytest.fixture
def framework():
    return ABTestingFramework(db_url=DB_URL)


# ---------------------------------------------------------------------------
# _required_sample_size
# ---------------------------------------------------------------------------

def test_required_sample_size_reasonable():
    n = _required_sample_size(p_baseline=0.65, mde=0.02, alpha=0.05, power=0.80)
    assert 1_000 < n < 100_000, f"Unexpected sample size: {n}"


def test_required_sample_size_larger_mde_smaller_n():
    n_small_mde = _required_sample_size(p_baseline=0.65, mde=0.01, alpha=0.05, power=0.80)
    n_large_mde = _required_sample_size(p_baseline=0.65, mde=0.05, alpha=0.05, power=0.80)
    assert n_small_mde > n_large_mde


# ---------------------------------------------------------------------------
# _z_score_two_proportions / _p_value_from_z
# ---------------------------------------------------------------------------

def test_z_score_equal_proportions_near_zero():
    z = _z_score_two_proportions(0.5, 1000, 0.5, 1000)
    assert abs(z) < 0.01


def test_p_value_large_z_is_small():
    p = _p_value_from_z(4.0)
    assert p < 0.001


# ---------------------------------------------------------------------------
# create_experiment
# ---------------------------------------------------------------------------

def test_create_experiment_returns_draft(framework):
    exp = _make_experiment()
    result = framework.create_experiment(exp)
    assert result.experiment_id
    assert result.status == "DRAFT"
    assert result.tenant_id == "t-test"
    assert result.control_version_tag == "v1.0"
    assert result.treatment_version_tag == "v2.0"


# ---------------------------------------------------------------------------
# start_experiment
# ---------------------------------------------------------------------------

def test_start_experiment_transitions_to_running(framework):
    exp = framework.create_experiment(_make_experiment())
    framework.start_experiment(exp.experiment_id)
    started = framework.get_experiment(exp.experiment_id)
    assert started.status == "RUNNING"
    assert started.started_at is not None


def test_start_already_running_experiment_raises(framework):
    exp = framework.create_experiment(_make_experiment())
    framework.start_experiment(exp.experiment_id)
    with pytest.raises(ValueError):
        framework.start_experiment(exp.experiment_id)


# ---------------------------------------------------------------------------
# halt / complete
# ---------------------------------------------------------------------------

def test_halt_experiment(framework):
    exp = framework.create_experiment(_make_experiment())
    framework.start_experiment(exp.experiment_id)
    framework.halt_experiment(exp.experiment_id, reason="guardrail")
    halted = framework.get_experiment(exp.experiment_id)
    assert halted.status == "HALTED"


def test_complete_experiment(framework):
    exp = framework.create_experiment(_make_experiment())
    framework.start_experiment(exp.experiment_id)
    framework.complete_experiment(exp.experiment_id, {"approval_rate_delta": 0.03})
    completed = framework.get_experiment(exp.experiment_id)
    assert completed.status == "COMPLETED"



# ---------------------------------------------------------------------------
# record_outcome
# ---------------------------------------------------------------------------

def test_record_outcome_stored(framework):
    exp = framework.create_experiment(_make_experiment())
    framework.start_experiment(exp.experiment_id)
    outcome = ExperimentOutcomeRecord(
        experiment_id=exp.experiment_id,
        application_id="app-001",
        arm="CONTROL",
        decision="APPROVE",
        tenant_id="t-test",
    )
    framework.record_outcome(outcome)  # No exception = pass


# ---------------------------------------------------------------------------
# get_significance_report — insufficient data
# ---------------------------------------------------------------------------

def test_significance_report_insufficient_data(framework):
    exp = framework.create_experiment(_make_experiment())
    framework.start_experiment(exp.experiment_id)
    report = framework.get_significance_report(exp.experiment_id)
    assert report.recommendation == "INSUFFICIENT_DATA"
    assert report.control_n == 0
    assert report.treatment_n == 0


# ---------------------------------------------------------------------------
# get_significance_report — with enough outcomes
# ---------------------------------------------------------------------------

def test_significance_report_with_data(framework):
    exp = framework.create_experiment(_make_experiment())
    framework.start_experiment(exp.experiment_id)

    for i in range(20):
        framework.record_outcome(ExperimentOutcomeRecord(
            experiment_id=exp.experiment_id,
            application_id=f"ctrl-{i}",
            arm="CONTROL",
            decision="APPROVE" if i < 10 else "DECLINE",
            tenant_id="t-test",
        ))
    for i in range(20):
        framework.record_outcome(ExperimentOutcomeRecord(
            experiment_id=exp.experiment_id,
            application_id=f"trt-{i}",
            arm="TREATMENT",
            decision="APPROVE" if i < 15 else "DECLINE",
            tenant_id="t-test",
        ))

    report = framework.get_significance_report(exp.experiment_id)
    assert report.control_n == 20
    assert report.treatment_n == 20
    assert report.control_approval_rate == pytest.approx(0.50)
    assert report.treatment_approval_rate == pytest.approx(0.75)
    assert isinstance(report.z_score, float)
    assert 0.0 <= report.p_value <= 1.0


# ---------------------------------------------------------------------------
# list_experiments
# ---------------------------------------------------------------------------

def test_list_experiments_empty(framework):
    result = framework.list_experiments(tenant_id="t-test")
    assert result == []


def test_list_experiments_returns_created(framework):
    framework.create_experiment(_make_experiment())
    result = framework.list_experiments(tenant_id="t-test")
    assert len(result) == 1
    assert result[0].name == "Test Experiment"


# ---------------------------------------------------------------------------
# export_results_as_evidence
# ---------------------------------------------------------------------------

def test_export_evidence_returns_bundle(framework):
    exp = framework.create_experiment(_make_experiment())
    framework.start_experiment(exp.experiment_id)
    bundle = framework.export_results_as_evidence(exp.experiment_id)
    assert bundle["evidence_type"] == "AB_EXPERIMENT_RESULTS"
    assert "experiment" in bundle
    assert bundle["experiment"]["experiment_id"] == exp.experiment_id
