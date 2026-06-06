"""Tests for PolicyAdherenceReport (S5-B)."""

from __future__ import annotations

import tempfile
import pytest

from reporting.policy_adherence import (
    generate_policy_adherence_report,
    PolicyAdherenceReport,
    PolicyRuleStats,
    _rule_status,
)


class TestPolicyAdherence:
    def test_returns_policy_adherence_report(self, tmp_path):
        report = generate_policy_adherence_report("30d", db_path=str(tmp_path / "missing.db"))
        assert isinstance(report, PolicyAdherenceReport)

    def test_period_in_report(self, tmp_path):
        for period in ("30d", "90d", "ytd"):
            r = generate_policy_adherence_report(period, db_path=str(tmp_path / "missing.db"))
            assert r.period == period

    def test_rules_list_non_empty(self, tmp_path):
        r = generate_policy_adherence_report("30d", db_path=str(tmp_path / "missing.db"))
        assert len(r.rules) > 0

    def test_compliance_rate_in_range(self, tmp_path):
        r = generate_policy_adherence_report("30d", db_path=str(tmp_path / "missing.db"))
        assert 0.0 <= r.overall_compliance_rate <= 1.0
        for rule in r.rules:
            assert 0.0 <= rule.compliance_rate <= 1.0

    def test_rule_stats_have_required_fields(self, tmp_path):
        r = generate_policy_adherence_report("30d", db_path=str(tmp_path / "missing.db"))
        for rule in r.rules:
            assert isinstance(rule, PolicyRuleStats)
            assert rule.rule_id
            assert rule.decisions_evaluated >= 0
            assert rule.compliance_count >= 0
            assert rule.exception_count >= 0

    def test_top_exception_rules_max_3(self, tmp_path):
        r = generate_policy_adherence_report("30d", db_path=str(tmp_path / "missing.db"))
        assert len(r.top_exception_rules) <= 3

    def test_summary_non_empty(self, tmp_path):
        r = generate_policy_adherence_report("30d", db_path=str(tmp_path / "missing.db"))
        assert len(r.summary) > 20

    def test_generated_at_set(self, tmp_path):
        r = generate_policy_adherence_report("30d", db_path=str(tmp_path / "missing.db"))
        assert r.generated_at

    def test_waiver_counts_joined(self, tmp_path):
        class _MockWaiverStore:
            def list_waivers(self, **kwargs):
                class _W:
                    policy_rule_id = "RULE_DTI_LIMIT"
                    requested_at = "2026-01-01T00:00:00+00:00"
                    status = "approved"
                return [_W()]

        r = generate_policy_adherence_report(
            "90d", db_path=str(tmp_path / "missing.db"), waiver_store=_MockWaiverStore()
        )
        assert isinstance(r, PolicyAdherenceReport)


class TestRuleStatus:
    def test_healthy(self):
        assert _rule_status(0.96) == "Healthy"
        assert _rule_status(1.0) == "Healthy"

    def test_watch(self):
        assert _rule_status(0.90) == "Watch"
        assert _rule_status(0.85) == "Watch"

    def test_breach(self):
        assert _rule_status(0.80) == "Breach"
        assert _rule_status(0.50) == "Breach"

    def test_boundary_95(self):
        assert _rule_status(0.95) == "Healthy"

    def test_boundary_85(self):
        assert _rule_status(0.849) == "Breach"
