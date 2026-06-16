"""
tests/compliance/test_erasure_request.py — Section 23.12
=========================================================
Unit tests for compliance.erasure_request module.

Contracts verified:
  - process_erasure_request() returns dict of tables -> row counts.
  - process_erasure_request() raises RuntimeError when BQ unavailable.
  - ERASURE_EXEMPT_TABLES are never targeted by DELETE.
  - Every call logs to audit.erasure_request_log.
  - SHA-256 of applicant_id is used (not plaintext).
"""
from __future__ import annotations

import hashlib
from unittest.mock import MagicMock, call, patch

import pytest

from compliance.erasure_request import (
    ERASABLE_TABLES,
    ERASURE_EXEMPT_TABLES,
    process_erasure_request,
)


class TestErasureRequestExemptTables:
    def test_audit_log_is_exempt(self):
        assert "audit.audit_log" in ERASURE_EXEMPT_TABLES

    def test_policy_version_log_is_exempt(self):
        assert "audit.policy_version_log" in ERASURE_EXEMPT_TABLES

    def test_compliance_events_is_exempt(self):
        assert "compliance_data_plane.compliance_events" in ERASURE_EXEMPT_TABLES

    def test_no_erasable_table_is_also_exempt(self):
        """Erasable and exempt sets must be disjoint."""
        overlap = set(ERASABLE_TABLES.keys()) & ERASURE_EXEMPT_TABLES
        assert not overlap, f"Tables in both ERASABLE and EXEMPT: {overlap}"


class TestProcessErasureRequest:
    @pytest.fixture
    def mock_bq_client(self):
        client = MagicMock()
        # Simulate 1 row deleted per table
        mock_result = MagicMock()
        mock_result.num_dml_affected_rows = 1
        client.query.return_value.result.return_value = mock_result
        client.insert_rows_json.return_value = []
        return client

    def test_raises_when_bq_unavailable(self, monkeypatch):
        monkeypatch.setattr("compliance.erasure_request._BQ_AVAILABLE", False)
        monkeypatch.setattr("compliance.erasure_request._bq_lib", None)

        with pytest.raises(RuntimeError, match="unavailable"):
            process_erasure_request("applicant-123", "test@bank.com")

    def test_returns_dict_of_row_counts(self, monkeypatch, mock_bq_client):
        mock_bq_lib = MagicMock()
        mock_bq_lib.Client.return_value = mock_bq_client
        mock_bq_lib.QueryJobConfig = MagicMock(return_value=MagicMock())
        mock_bq_lib.ScalarQueryParameter = MagicMock(return_value=MagicMock())

        monkeypatch.setattr("compliance.erasure_request._BQ_AVAILABLE", True)
        monkeypatch.setattr("compliance.erasure_request._bq_lib", mock_bq_lib)

        results = process_erasure_request("applicant-123", "privacy@bank.com")

        assert isinstance(results, dict)
        assert set(results.keys()) == set(ERASABLE_TABLES.keys())

    def test_uses_sha256_not_plaintext(self, monkeypatch, mock_bq_client):
        """Plaintext applicant_id must never reach the BQ query."""
        mock_bq_lib = MagicMock()
        mock_bq_lib.Client.return_value = mock_bq_client
        mock_bq_lib.QueryJobConfig = MagicMock(return_value=MagicMock())

        # Capture ScalarQueryParameter calls to inspect the hash value
        param_values: list[str] = []
        def _capture_param(name, type_, value):
            param_values.append((name, value))
            return MagicMock()

        mock_bq_lib.ScalarQueryParameter.side_effect = _capture_param

        monkeypatch.setattr("compliance.erasure_request._BQ_AVAILABLE", True)
        monkeypatch.setattr("compliance.erasure_request._bq_lib", mock_bq_lib)

        applicant_id = "applicant-secret-123"
        expected_hash = hashlib.sha256(applicant_id.encode()).hexdigest()

        process_erasure_request(applicant_id, "privacy@bank.com")

        hash_params = [v for name, v in param_values if name == "hash"]
        assert hash_params, "No 'hash' parameter sent to BQ"
        for h in hash_params:
            assert h == expected_hash, (
                f"Expected SHA-256 hash {expected_hash[:16]}... "
                f"but got {str(h)[:16]}..."
            )
        # Plaintext applicant_id must never appear in any query call
        for q_call in mock_bq_client.query.call_args_list:
            q_str = str(q_call)
            assert applicant_id not in q_str, (
                "Plaintext applicant_id found in BQ query — PII leak!"
            )

    def test_erasure_request_logged(self, monkeypatch, mock_bq_client):
        """audit.erasure_request_log must be written exactly once."""
        mock_bq_lib = MagicMock()
        mock_bq_lib.Client.return_value = mock_bq_client
        mock_bq_lib.QueryJobConfig = MagicMock(return_value=MagicMock())
        mock_bq_lib.ScalarQueryParameter = MagicMock(return_value=MagicMock())

        monkeypatch.setattr("compliance.erasure_request._BQ_AVAILABLE", True)
        monkeypatch.setattr("compliance.erasure_request._bq_lib", mock_bq_lib)

        process_erasure_request("app-456", "privacy@bank.com")

        insert_calls = mock_bq_client.insert_rows_json.call_args_list
        log_calls = [c for c in insert_calls if "erasure_request_log" in str(c)]
        assert len(log_calls) == 1, "erasure_request_log must be written exactly once"

    def test_exempt_tables_not_queried(self, monkeypatch, mock_bq_client):
        """No DELETE statement should target any ERASURE_EXEMPT_TABLE."""
        mock_bq_lib = MagicMock()
        mock_bq_lib.Client.return_value = mock_bq_client
        mock_bq_lib.QueryJobConfig = MagicMock(return_value=MagicMock())
        mock_bq_lib.ScalarQueryParameter = MagicMock(return_value=MagicMock())

        monkeypatch.setattr("compliance.erasure_request._BQ_AVAILABLE", True)
        monkeypatch.setattr("compliance.erasure_request._bq_lib", mock_bq_lib)

        process_erasure_request("app-789", "privacy@bank.com")

        delete_queries = [
            str(c) for c in mock_bq_client.query.call_args_list
            if "DELETE" in str(c).upper()
        ]
        for exempt_table in ERASURE_EXEMPT_TABLES:
            for q in delete_queries:
                assert exempt_table not in q, (
                    f"Exempt table {exempt_table} targeted by DELETE statement!"
                )
