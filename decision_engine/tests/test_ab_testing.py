"""
Tests for Sprint 6-A: ABTestingFramework (decision_engine/ab_testing.py)
"""
from __future__ import annotations

import math
import pytest
import pytest_asyncio

from decision_engine.ab_testing import (
    ABTestingFramework,
    ExperimentConfig,
    ExperimentOutcomeRecord,
    required_sample_size,
)

DB_URL = "sqlite+aiosqlite:///:memory:"


def _make_config(**kwargs) -> ExperimentConfig:
    defaults = dict(
        name="Test Experiment",
        description="desc",
        champion_policy_version="v1.0",
        challenger_policy_version="v2.0",
        traffic_split=0.5,
        min_sample_size_per_arm=100,
        alpha=0.05,
        mde=0.02,
        power=0.80,
    )
    defaults.update(kwargs)
    return ExperimentConfig(**defaults)


@pytest.fixture
async def framework():
    fw = ABTestingFramework(db_url=DB_URL, tenant_id="test-tenant")
    await fw.initialise()
    return fw


# ---------------------------------------------------------------------------
# required_sample_size
# ---------------------------------------------------------------------------

def test_required_sample_size_reasonable():
    n = required_sample_size(baseline_rate=0.65, mde=0.02, alpha=0.05, power=0.80)
    assert 1_000 < n < 100_000, f"Unexpected sample size: {n}"


def test_required_sample_size_larger_mde_smaller_n():
    n_small_mde = required_sample_size(0.65, mde=0.01)
    n_large_mde = required_sample_size(0.65, mde=0.05)
    assert n_small_mde > n_large_mde


# ---------------------------------------------------------------------------
# create_experiment
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_experiment_returns_draft(framework):
    cfg = _make_config()
    exp = await framework.create_experiment(cfg)
    assert exp.experiment_id
    assert exp.status == "DRAFT"
    assert exp.tenant_id == "test-tenant"
    assert exp.champion_policy_version == "v1.0"
    assert exp.challenger_policy_version == "v2.0"


@pytest.mark.asyncio
async def test_create_duplicate_experiment_raises(framework):
    cfg = _make_config(champion_policy_version="v1.0", challenger_policy_version="v2.0")
    await framework.create_experiment(cfg)
    with pytest.raises(ValueError, match="conflict"):
        await framework.create_experiment(cfg)


# ---------------------------------------------------------------------------
# start_experiment
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_experiment_transitions_to_running(framework):
    exp = await framework.create_experiment(_make_config())
    started = await framework.start_experiment(exp.experiment_id)
    assert started.status == "RUNNING"
    assert started.started_at is not None


@pytest.mark.asyncio
async def test_start_already_running_experiment_raises(framework):
    exp = await framework.create_experiment(_make_config())
    await framework.start_experiment(exp.experiment_id)
    with pytest.raises(ValueError):
        await framework.start_experiment(exp.experiment_id)


# ---------------------------------------------------------------------------
# record_outcome
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_record_outcome_stored(framework):
    exp = await framework.create_experiment(_make_config())
    await framework.start_experiment(exp.experiment_id)
    outcome = ExperimentOutcomeRecord(
        experiment_id=exp.experiment_id,
        application_id="app-001",
        arm="CONTROL",
        decision="APPROVE",
        tenant_id="test-tenant",
        pd_score=0.05,
    )
    await framework.record_outcome(outcome)
    # No exception = pass


# ---------------------------------------------------------------------------
# get_significance_report — insufficient data
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_significance_report_insufficient_data(framework):
    exp = await framework.create_experiment(_make_config())
    await framework.start_experiment(exp.experiment_id)
    report = await framework.get_significance_report(exp.experiment_id)
    assert report.recommendation == "INSUFFICIENT_DATA"
    assert report.n_control == 0
    assert report.n_treatment == 0


# ---------------------------------------------------------------------------
# get_significance_report — with enough outcomes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_significance_report_with_data(framework):
    exp = await framework.create_experiment(_make_config(min_sample_size_per_arm=5))
    await framework.start_experiment(exp.experiment_id)

    # Simulate 10 CONTROL approvals out of 20
    for i in range(20):
        await framework.record_outcome(
            ExperimentOutcomeRecord(
                experiment_id=exp.experiment_id,
                application_id=f"ctrl-{i}",
                arm="CONTROL",
                decision="APPROVE" if i < 10 else "DECLINE",
                tenant_id="test-tenant",
                pd_score=0.05,
            )
        )
    # Simulate 15 TREATMENT approvals out of 20 (higher approval rate)
    for i in range(20):
        await framework.record_outcome(
            ExperimentOutcomeRecord(
                experiment_id=exp.experiment_id,
                application_id=f"trt-{i}",
                arm="TREATMENT",
                decision="APPROVE" if i < 15 else "DECLINE",
                tenant_id="test-tenant",
                pd_score=0.05,
            )
        )

    report = await framework.get_significance_report(exp.experiment_id)
    assert report.n_control == 20
    assert report.n_treatment == 20
    assert report.approval_rate_control == pytest.approx(0.50)
    assert report.approval_rate_treatment == pytest.approx(0.75)
    assert isinstance(report.z_score, float)
    assert isinstance(report.p_value, float)
    assert 0.0 <= report.p_value <= 1.0
    assert report.recommendation in {"PROMOTE", "HOLD", "REJECT", "INSUFFICIENT_DATA"}


# ---------------------------------------------------------------------------
# list_experiments
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_experiments_empty(framework):
    result = await framework.list_experiments()
    assert result == []


@pytest.mark.asyncio
async def test_list_experiments_returns_created(framework):
    await framework.create_experiment(_make_config())
    result = await framework.list_experiments()
    assert len(result) == 1
    assert result[0]["name"] == "Test Experiment"


# ---------------------------------------------------------------------------
# export_results_as_evidence
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_export_evidence_returns_bundle(framework):
    exp = await framework.create_experiment(_make_config())
    await framework.start_experiment(exp.experiment_id)
    bundle = await framework.export_results_as_evidence(exp.experiment_id)
    assert "experiment_id" in bundle
    assert "report" in bundle
    assert bundle["experiment_id"] == exp.experiment_id
