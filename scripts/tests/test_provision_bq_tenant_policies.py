"""
Tests for GAP-03-D: BigQuery Row-Level Access Policy Provisioner.

Uses mocked BigQuery client to avoid requiring live GCP credentials.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).parents[3]
sys.path.insert(0, str(ROOT))

from scripts.provision_bq_tenant_policies import (
    _build_ddl,
    _policy_name,
    provision_tenant_policies,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bq_client(policy_exists: bool = False) -> MagicMock:
    """Return a mocked BigQuery client."""
    client = MagicMock()

    # Mock INFORMATION_SCHEMA query result
    count_row = MagicMock()
    count_row.cnt = 1 if policy_exists else 0
    query_result = MagicMock()
    query_result.__iter__ = MagicMock(return_value=iter([count_row]))
    query_job = MagicMock()
    query_job.result.return_value = query_result
    client.query.return_value = query_job

    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDryRunMode:
    """--dry-run generates DDL without calling any BigQuery API methods."""

    def test_dry_run_does_not_call_bq_client(self, capsys: pytest.CaptureFixture) -> None:
        """In --dry-run mode, no BQ client calls are made."""
        with patch("scripts.provision_bq_tenant_policies._policy_exists") as mock_exists:
            results = provision_tenant_policies(
                project="my-project",
                dataset="my-dataset",
                tenant_id="tenant-abc",
                service_account="sa@my-project.iam.gserviceaccount.com",
                dry_run=True,
                tables=["audit_log"],
            )
        # _policy_exists should NOT be called in dry_run mode
        mock_exists.assert_not_called()
        assert len(results) == 1
        assert results[0]["status"] == "dry_run"

    def test_dry_run_ddl_contains_filter_using(self) -> None:
        """DDL uses FILTER USING, not WHERE."""
        results = provision_tenant_policies(
            project="proj",
            dataset="ds",
            tenant_id="tenant-abc",
            service_account="sa@proj.iam.gserviceaccount.com",
            dry_run=True,
            tables=["audit_log"],
        )
        assert "FILTER USING" in results[0]["ddl"]
        assert "WHERE" not in results[0]["ddl"]

    def test_dry_run_contains_correct_tenant_id(self) -> None:
        """DDL filter references the correct tenant_id."""
        results = provision_tenant_policies(
            project="proj",
            dataset="ds",
            tenant_id="tenant-xyz",
            service_account="sa@proj.iam.gserviceaccount.com",
            dry_run=True,
            tables=["audit_log"],
        )
        assert "tenant-xyz" in results[0]["ddl"]

    def test_dry_run_does_not_require_gcp_credentials(self) -> None:
        """Dry run must not import or use google-cloud-bigquery."""
        # Temporarily hide google.cloud.bigquery by patching the import
        import builtins
        original_import = builtins.__import__

        def mock_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name in ("google.cloud.bigquery", "google.cloud"):
                raise ImportError("GCP not available")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            # Should NOT raise even without GCP
            results = provision_tenant_policies(
                project="proj",
                dataset="ds",
                tenant_id="t1",
                service_account="sa@proj.iam.gserviceaccount.com",
                dry_run=True,
                tables=["audit_log"],
            )
        assert results[0]["status"] == "dry_run"


class TestIdempotency:
    """When policy already exists, CREATE is skipped."""

    def test_existing_policy_is_skipped(self) -> None:
        """When INFORMATION_SCHEMA shows the policy exists → status='skipped'."""
        mock_client = _make_bq_client(policy_exists=True)

        with patch(
            "scripts.provision_bq_tenant_policies._policy_exists",
            return_value=True,
        ), patch(
            "scripts.provision_bq_tenant_policies.bigquery",
            create=True,
        ) as mock_bq_module, patch(
            "google.cloud.bigquery.Client",
            return_value=mock_client,
        ):
            mock_bq_module.Client.return_value = mock_client

            results = provision_tenant_policies(
                project="proj",
                dataset="ds",
                tenant_id="tenant-abc",
                service_account="sa@proj.iam.gserviceaccount.com",
                dry_run=False,
                tables=["audit_log"],
            )

        assert results[0]["status"] == "skipped"
        # client.query should NOT have been called with CREATE DDL
        # (only INFORMATION_SCHEMA check calls are allowed, but those are mocked away)
        for call in mock_client.query.call_args_list:
            assert "CREATE" not in str(call), "CREATE DDL called despite policy existing"

    def test_missing_policy_is_provisioned(self) -> None:
        """When policy does not exist → provision_tenant_policies returns status='provisioned'."""
        # Build a mock module that properly handles 'from google.cloud import bigquery'
        mock_query_job = MagicMock()
        mock_query_job.result.return_value = None

        mock_client = MagicMock()
        mock_client.query.return_value = mock_query_job

        mock_bigquery_module = MagicMock()
        mock_bigquery_module.Client.return_value = mock_client

        mock_google_cloud = MagicMock()
        mock_google_cloud.bigquery = mock_bigquery_module

        mock_google = MagicMock()
        mock_google.cloud = mock_google_cloud

        with patch(
            "scripts.provision_bq_tenant_policies._policy_exists",
            return_value=False,
        ), patch.dict(
            sys.modules,
            {
                "google": mock_google,
                "google.cloud": mock_google_cloud,
                "google.cloud.bigquery": mock_bigquery_module,
            },
        ):
            results = provision_tenant_policies(
                project="proj",
                dataset="ds",
                tenant_id="tenant-abc",
                service_account="sa@proj.iam.gserviceaccount.com",
                dry_run=False,
                tables=["audit_log"],
            )

        # The result must show the policy was provisioned
        assert results[0]["status"] == "provisioned"
        # The DDL string in the result must contain CREATE
        assert "CREATE" in results[0]["ddl"]
        assert "tenant-abc" in results[0]["ddl"]


class TestPolicyNameGeneration:
    """Policy name sanitises tenant_id."""

    def test_hyphens_replaced_with_underscores(self) -> None:
        assert _policy_name("tenant-abc") == "tenant_tenant_abc_policy"

    def test_dots_replaced_with_underscores(self) -> None:
        assert _policy_name("tenant.abc") == "tenant_tenant_abc_policy"


class TestDDLFormat:
    """BigQuery DDL must use correct syntax."""

    def test_filter_using_not_where(self) -> None:
        ddl = _build_ddl("proj", "ds", "audit_log", "t1", "sa@proj.iam.gserviceaccount.com")
        assert "FILTER USING" in ddl
        assert "WHERE" not in ddl

    def test_service_account_in_grant_to(self) -> None:
        ddl = _build_ddl("proj", "ds", "audit_log", "t1", "sa@proj.iam.gserviceaccount.com")
        assert "serviceAccount:sa@proj.iam.gserviceaccount.com" in ddl

    def test_full_table_reference(self) -> None:
        ddl = _build_ddl("my-proj", "my-ds", "audit_log", "t1", "sa@p.com")
        assert "`my-proj.my-ds.audit_log`" in ddl
