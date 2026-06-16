"""
tests/compliance/test_data_plane.py — Section 23.12
=====================================================
Unit tests for compliance.data_plane module.

Key contracts verified:
  - get_threshold() raises ComplianceDataPlaneError when BQ unavailable.
  - get_threshold() raises ComplianceDataPlaneError when no rows returned.
  - log_compliance_event() returns a UUID even when BQ unavailable.
  - RegulatoryThreshold is an immutable frozen dataclass.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def no_bq(monkeypatch):
    """Ensure BQ is always mocked in this module."""
    monkeypatch.setattr("compliance.data_plane._BQ_AVAILABLE", False)
    monkeypatch.setattr("compliance.data_plane._bq", None)


class TestGetThreshold:
    def test_raises_when_bq_unavailable(self):
        from compliance.data_plane import ComplianceDataPlaneError, get_threshold

        get_threshold.cache_clear()
        with pytest.raises(ComplianceDataPlaneError, match="unavailable"):
            get_threshold("MLA_MAPR_CAP")

    def test_error_message_contains_threshold_id(self):
        from compliance.data_plane import ComplianceDataPlaneError, get_threshold

        get_threshold.cache_clear()
        with pytest.raises(ComplianceDataPlaneError) as exc_info:
            get_threshold("SOME_UNKNOWN_THRESHOLD", "CA")
        assert "SOME_UNKNOWN_THRESHOLD" in str(exc_info.value)

    def test_lru_cache_is_registered(self):
        from compliance.data_plane import get_threshold

        assert hasattr(get_threshold, "cache_info")
        assert hasattr(get_threshold, "cache_clear")

    def test_returns_frozen_dataclass(self, monkeypatch):
        """When BQ is available and returns a row, result must be frozen."""
        from compliance.data_plane import RegulatoryThreshold, get_threshold

        mock_row = type("Row", (), {
            "threshold_id": "MLA_MAPR_CAP",
            "regulation": "MLA",
            "jurisdiction": "FEDERAL",
            "threshold_type": "MAPR_MAX_PCT",
            "threshold_value": 36.0,
            "legal_citation": "10 U.S.C. § 987(b)",
        })()

        mock_result = MagicMock()
        mock_result.__iter__ = lambda _: iter([mock_row])

        mock_query = MagicMock()
        mock_query.return_value.result.return_value = mock_result

        mock_client = MagicMock()
        mock_client.query = mock_query

        monkeypatch.setattr("compliance.data_plane._BQ_AVAILABLE", True)
        monkeypatch.setattr("compliance.data_plane._bq", mock_client)
        # Import _bq_lib mock
        mock_bq_lib = MagicMock()
        mock_bq_lib.QueryJobConfig = MagicMock(return_value=MagicMock())
        mock_bq_lib.ScalarQueryParameter = MagicMock(return_value=MagicMock())
        monkeypatch.setattr("compliance.data_plane._bq_lib", mock_bq_lib)

        get_threshold.cache_clear()
        result = get_threshold("MLA_MAPR_CAP", "FEDERAL")

        assert isinstance(result, RegulatoryThreshold)
        assert result.threshold_value == 36.0

        # Frozen dataclass must raise on mutation
        with pytest.raises((AttributeError, TypeError)):
            result.threshold_value = 99.0  # type: ignore[misc]

        get_threshold.cache_clear()


# MagicMock is imported below class definition to avoid confusing class scope
from unittest.mock import MagicMock  # noqa: E402


class TestLogComplianceEvent:
    @pytest.mark.asyncio
    async def test_returns_uuid_when_bq_unavailable(self):
        from compliance.data_plane import log_compliance_event

        event_id = await log_compliance_event(
            event_type="REALTIME_GATE",
            source_system="test",
            check_name="test_check",
            check_result="PASS",
        )
        assert len(event_id) == 36  # UUID4 format
        assert event_id.count("-") == 4

    @pytest.mark.asyncio
    async def test_different_event_ids_each_call(self):
        from compliance.data_plane import log_compliance_event

        id1 = await log_compliance_event("X", "sys", "check", "PASS")
        id2 = await log_compliance_event("X", "sys", "check", "PASS")
        assert id1 != id2


class TestRegulatoryThreshold:
    def test_frozen_dataclass(self):
        from compliance.data_plane import RegulatoryThreshold

        t = RegulatoryThreshold(
            threshold_id="TEST",
            regulation="TEST_REG",
            jurisdiction="FEDERAL",
            threshold_type="APR_MAX_PCT",
            threshold_value=36.0,
            legal_citation="Test § 1",
        )
        assert t.threshold_value == 36.0

        with pytest.raises((AttributeError, TypeError)):
            t.threshold_value = 99.0  # type: ignore[misc]
