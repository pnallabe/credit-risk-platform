"""Tests for GAP-12B: canary_decision_api.py controller script."""

from __future__ import annotations

import argparse
from unittest.mock import MagicMock, call, patch

import pytest

from scripts.canary_decision_api import (
    fetch_metrics,
    rollback,
    run_canary,
    set_cloud_run_traffic,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_args(**kwargs) -> argparse.Namespace:
    defaults = dict(
        service="svc",
        region="us-central1",
        project="proj",
        canary_revision="rev-new",
        stable_revision="rev-old",
        metrics_url_canary="https://canary.example.com/v1/metrics",
        metrics_url_stable="https://stable.example.com/v1/metrics",
        auth_token="tok",
        p99_threshold=500.0,
        error_threshold=0.01,
        poll_interval=1,
        step_wait=2,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _healthy_metrics() -> dict:
    return {
        "p99_latency_ms": 120.0,
        "error_rate_5xx": 0.002,
        "canary_healthy": True,
    }


def _breach_p99() -> dict:
    return {"p99_latency_ms": 999.0, "error_rate_5xx": 0.0, "canary_healthy": True}


def _breach_err() -> dict:
    return {"p99_latency_ms": 100.0, "error_rate_5xx": 0.05, "canary_healthy": True}


# ---------------------------------------------------------------------------
# fetch_metrics
# ---------------------------------------------------------------------------


class TestFetchMetrics:
    def test_returns_parsed_json_on_success(self) -> None:
        resp_mock = MagicMock()
        resp_mock.read.return_value = b'{"p99_latency_ms": 120}'
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=resp_mock)
        ctx.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=ctx):
            result = fetch_metrics("https://example.com/v1/metrics", "tok")
        assert result == {"p99_latency_ms": 120}

    def test_returns_none_on_request_error(self) -> None:
        with patch("urllib.request.urlopen", side_effect=ConnectionError("refused")):
            result = fetch_metrics("https://bad.example.com", "tok")
        assert result is None


# ---------------------------------------------------------------------------
# set_cloud_run_traffic
# ---------------------------------------------------------------------------


class TestSetCloudRunTraffic:
    def test_returns_true_on_success(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            ok = set_cloud_run_traffic("proj", "us-central1", "svc", "new", "old", 10)
        assert ok is True

    def test_returns_false_on_gcloud_error(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "permission denied"
        with patch("subprocess.run", return_value=mock_result):
            ok = set_cloud_run_traffic("proj", "us-central1", "svc", "new", "old", 10)
        assert ok is False

    def test_cmd_contains_correct_percentages(self) -> None:
        mock_result = MagicMock(returncode=0)
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            set_cloud_run_traffic("p", "r", "svc", "new", "old", 25)
        cmd = mock_run.call_args[0][0]
        assert "--to-revisions=new=25,old=75" in cmd


# ---------------------------------------------------------------------------
# run_canary — success path
# ---------------------------------------------------------------------------


class TestRunCanarySuccess:
    def test_returns_0_on_healthy_metrics(self) -> None:
        args = _make_args()
        with patch(
            "scripts.canary_decision_api.set_cloud_run_traffic", return_value=True
        ), patch(
            "scripts.canary_decision_api.fetch_metrics", return_value=_healthy_metrics()
        ), patch(
            "time.sleep"
        ), patch(
            "time.monotonic", side_effect=[0.0, 0.0, 3.0] * 20
        ):
            rc = run_canary(args)
        assert rc == 0

    def test_all_ramp_steps_applied(self) -> None:
        args = _make_args()
        traffic_calls = []

        def _fake_traffic(project, region, service, canary, stable, pct):
            traffic_calls.append(pct)
            return True

        with patch(
            "scripts.canary_decision_api.set_cloud_run_traffic", side_effect=_fake_traffic
        ), patch(
            "scripts.canary_decision_api.fetch_metrics", return_value=_healthy_metrics()
        ), patch(
            "time.sleep"
        ), patch(
            "time.monotonic", side_effect=[0.0, 0.0, 3.0] * 20
        ):
            run_canary(args)
        assert 100 in traffic_calls


# ---------------------------------------------------------------------------
# run_canary — rollback paths
# ---------------------------------------------------------------------------


class TestRunCanaryRollback:
    def test_returns_2_on_p99_breach(self) -> None:
        args = _make_args()
        rb_called = []

        def _fake_rb(*a, **k):
            rb_called.append(True)

        with patch(
            "scripts.canary_decision_api.set_cloud_run_traffic", return_value=True
        ), patch(
            "scripts.canary_decision_api.fetch_metrics", return_value=_breach_p99()
        ), patch(
            "scripts.canary_decision_api.rollback", side_effect=_fake_rb
        ), patch(
            "time.sleep"
        ), patch(
            "time.monotonic", side_effect=[0.0, 0.0, 0.0] * 20
        ):
            rc = run_canary(args)
        assert rc == 2
        assert rb_called

    def test_returns_2_on_error_rate_breach(self) -> None:
        args = _make_args()
        with patch(
            "scripts.canary_decision_api.set_cloud_run_traffic", return_value=True
        ), patch(
            "scripts.canary_decision_api.fetch_metrics", return_value=_breach_err()
        ), patch(
            "scripts.canary_decision_api.rollback"
        ) as mock_rb, patch(
            "time.sleep"
        ), patch(
            "time.monotonic", side_effect=[0.0, 0.0, 0.0] * 20
        ):
            rc = run_canary(args)
        assert rc == 2
        mock_rb.assert_called_once()

    def test_returns_1_on_gcloud_error(self) -> None:
        args = _make_args()
        with patch(
            "scripts.canary_decision_api.set_cloud_run_traffic", return_value=False
        ), patch(
            "scripts.canary_decision_api.rollback"
        ) as mock_rb:
            rc = run_canary(args)
        assert rc == 1
        mock_rb.assert_called_once()

    def test_rollback_routes_to_stable(self) -> None:
        mock_result = MagicMock(returncode=0)
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            rollback("proj", "us-central1", "svc", "rev-old")
        cmd = mock_run.call_args[0][0]
        assert "--to-revisions=rev-old=100" in cmd
