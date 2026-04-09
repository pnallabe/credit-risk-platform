"""Tests that run_monitoring() fires AlertRouter.send_alert when drift thresholds
are exceeded (GAP-07 acceptance criteria)."""
from __future__ import annotations

from unittest import mock

import numpy as np
import pandas as pd

from monitoring.alert_router import AlertRecord, AlertRouter, LogOnlyChannel
from monitoring.cc_pd_monitor import (
    AUROC_MIN_THRESHOLD,
    KS_MIN_THRESHOLD,
    PSI_CRITICAL_THRESHOLD,
    DR_MAX_THRESHOLD,
    compute_psi,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_router_with_spy() -> tuple[AlertRouter, list[dict]]:
    """Return an AlertRouter backed by LogOnlyChannel plus a call-record list."""
    calls: list[dict] = []

    class SpyChannel(LogOnlyChannel):
        def send(self, subject: str, body: str, severity: str) -> bool:
            calls.append({"subject": subject, "body": body, "severity": severity})
            return True

    router = AlertRouter(
        channels={sev: [SpyChannel()] for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW")}
    )
    return router, calls


# ---------------------------------------------------------------------------
# Unit: AlertRouter.send_alert is a real sync method
# ---------------------------------------------------------------------------

def test_send_alert_is_synchronous() -> None:
    """send_alert must be a regular (non-async) method."""
    import inspect
    router = AlertRouter()
    # get the unbound method
    assert not inspect.iscoroutinefunction(AlertRouter.send_alert)


def test_send_alert_returns_alert_record() -> None:
    router, calls = _make_router_with_spy()
    rec = router.send_alert("HIGH", "Test Title", "Test body")
    assert isinstance(rec, AlertRecord)
    assert rec.severity == "HIGH"
    assert rec.subject == "Test Title"
    assert len(calls) == 1
    assert calls[0]["severity"] == "HIGH"


# ---------------------------------------------------------------------------
# Unit: compute_psi returns a value > PSI_CRITICAL_THRESHOLD when data differs
# ---------------------------------------------------------------------------

def test_compute_psi_detects_shift() -> None:
    rng = np.random.default_rng(0)
    reference = rng.normal(0.2, 0.05, 5000)
    shifted   = rng.normal(0.6, 0.10, 5000)
    psi_val, _ = compute_psi(reference, shifted)
    assert psi_val > PSI_CRITICAL_THRESHOLD, (
        f"Expected PSI > {PSI_CRITICAL_THRESHOLD}, got {psi_val}"
    )


# ---------------------------------------------------------------------------
# Integration: run_monitoring fires send_alert on PSI breach
# ---------------------------------------------------------------------------

def _build_synthetic_df(size: int = 2000) -> pd.DataFrame:
    """Build a minimal synthetic DataFrame that cc_pd_monitor.run_monitoring() accepts."""
    rng = np.random.default_rng(42)
    n = size
    # Two cohorts with very different score distributions → high PSI
    dates_first  = pd.date_range("2022-01-01", periods=n // 2, freq="D")
    dates_second = pd.date_range("2023-07-01", periods=n // 2, freq="D")
    orig_dates = list(dates_first) + list(dates_second)

    # Scores for cohort 1 cluster near 0.15, cohort 2 near 0.75 → PSI >> 0.20
    scores_first  = rng.normal(0.15, 0.03, n // 2).clip(0.01, 0.99)
    scores_second = rng.normal(0.75, 0.08, n // 2).clip(0.01, 0.99)
    scores = np.concatenate([scores_first, scores_second])

    # default_flag — keep DR under threshold so only PSI alert fires
    default_flags = (rng.random(n) < 0.05).astype(int)

    df = pd.DataFrame({
        "orig_date":             orig_dates,
        "true_pd":               scores,
        "pd_score":              scores,
        "default_flag":          default_flags,
        # Extra columns consumed by portfolio_concentration, vintage curves, etc.
        "risk_grade":            rng.choice(["A", "B", "C", "D", "F"], n),
        "state":                 rng.choice(["CA", "TX", "NY", "FL"], n),
        "product":               rng.choice(["Classic", "Platinum"], n),
        "credit_limit":          rng.uniform(1000, 20000, n),
        "balance":               rng.uniform(0, 15000, n),
        "dpd_30":                (rng.random(n) < 0.05).astype(int),
        "dpd_60":                (rng.random(n) < 0.02).astype(int),
        "dpd_90":                (rng.random(n) < 0.01).astype(int),
        "months_on_book":        rng.uniform(1, 60, n),
        "fico_score":            rng.uniform(500, 850, n),
        "num_missed_pmts_12m":   rng.integers(0, 5, n).astype(float),
        "avg_utilization_12m":   rng.uniform(0.0, 1.0, n),
    })
    return df


def test_run_monitoring_fires_send_alert_on_psi_breach() -> None:
    """run_monitoring with shifted data must call router.send_alert at least once."""
    import tempfile, os
    router, calls = _make_router_with_spy()
    df = _build_synthetic_df()

    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir   = tmpdir
        train_path = os.path.join(tmpdir, "pd_training_5m.parquet")
        cost_path  = os.path.join(tmpdir, "cost_assumptions.parquet")
        df.to_parquet(train_path, index=False)

        import monitoring.cc_pd_monitor as _mod
        from pathlib import Path as _Path

        with (
            mock.patch.object(_mod, "DATA_DIR", new=_Path(tmpdir)),
            mock.patch.object(_mod, "REPORT_DIR", new=_Path(tmpdir)),
            mock.patch("monitoring.cc_pd_monitor.plot_vintage_curves"),
            mock.patch("monitoring.cc_pd_monitor.plot_score_distribution"),
            mock.patch("monitoring.cc_pd_monitor.plot_rolling_perf"),
        ):
            result = _mod.run_monitoring(sample=len(df), alert_router=router)

    assert result.get("alerts"), "Expected at least one alert for high-PSI data"
    assert len(calls) > 0, "router.send_alert was never called"
    severities = {c["severity"] for c in calls}
    assert "CRITICAL" in severities or "HIGH" in severities


# ---------------------------------------------------------------------------
# Test: no exception when alert_router=None (uses DEFAULT_ALERT_ROUTER)
# ---------------------------------------------------------------------------

def test_run_monitoring_default_router_no_exception() -> None:
    """Passing alert_router=None must not raise."""
    import tempfile, os
    df = _build_synthetic_df(size=500)

    with tempfile.TemporaryDirectory() as tmpdir:
        train_path = os.path.join(tmpdir, "pd_training_5m.parquet")
        df.to_parquet(train_path, index=False)

        import monitoring.cc_pd_monitor as _mod
        from pathlib import Path as _Path

        with (
            mock.patch.object(_mod, "DATA_DIR", new=_Path(tmpdir)),
            mock.patch.object(_mod, "REPORT_DIR", new=_Path(tmpdir)),
            mock.patch("monitoring.cc_pd_monitor.plot_vintage_curves"),
            mock.patch("monitoring.cc_pd_monitor.plot_score_distribution"),
            mock.patch("monitoring.cc_pd_monitor.plot_rolling_perf"),
        ):
            result = _mod.run_monitoring(sample=len(df), alert_router=None)

    # Should return at least the structural keys
    assert "psi" in result
    assert "alerts" in result


# ---------------------------------------------------------------------------
# Test: returned alerts list is non-empty for high-PSI data
# ---------------------------------------------------------------------------

def test_alerts_list_non_empty_for_high_psi() -> None:
    import tempfile, os
    df = _build_synthetic_df()
    import monitoring.cc_pd_monitor as _mod
    from pathlib import Path as _Path
    router, _ = _make_router_with_spy()

    with tempfile.TemporaryDirectory() as tmpdir:
        train_path = os.path.join(tmpdir, "pd_training_5m.parquet")
        df.to_parquet(train_path, index=False)

        with (
            mock.patch.object(_mod, "DATA_DIR", new=_Path(tmpdir)),
            mock.patch.object(_mod, "REPORT_DIR", new=_Path(tmpdir)),
            mock.patch("monitoring.cc_pd_monitor.plot_vintage_curves"),
            mock.patch("monitoring.cc_pd_monitor.plot_score_distribution"),
            mock.patch("monitoring.cc_pd_monitor.plot_rolling_perf"),
        ):
            result = _mod.run_monitoring(sample=len(df), alert_router=router)

    assert isinstance(result["alerts"], list)
    assert len(result["alerts"]) >= 1
