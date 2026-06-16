"""
Tests for compliance/regulatory_horizon.py — BQ-mocked paths.

Strategy: monkeypatch _bq_lib and _BQ_AVAILABLE so all BQ-gated code paths
run with a controlled mock client, covering scan_horizon, update_days_remaining,
get_horizon_items, and flag_overdue_horizon_items.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import compliance.regulatory_horizon as rh_mod


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def _make_row(**attrs):
    """Return a MagicMock with explicit attribute values for a BigQuery row."""
    row = MagicMock()
    for k, v in attrs.items():
        setattr(row, k, v)
    # Support dict-like .items() for get_horizon_items / flag_overdue paths
    row.items.return_value = attrs.items()
    return row


def _make_bq_client_returning(rows):
    """BQ client whose .query().result() returns the given list of rows."""
    mock_query = MagicMock()
    mock_query.result.return_value = rows
    mock_client = MagicMock()
    mock_client.query.return_value = mock_query
    return mock_client


# ---------------------------------------------------------------------------
# scan_horizon — BQ path
# ---------------------------------------------------------------------------

def test_scan_horizon_bq_no_rows(monkeypatch):
    """When BQ returns no rows, scan_horizon returns empty list."""
    client = _make_bq_client_returning([])
    mock_lib = MagicMock()
    mock_lib.Client.return_value = client

    monkeypatch.setattr(rh_mod, "_bq_lib", mock_lib)
    monkeypatch.setattr(rh_mod, "_BQ_AVAILABLE", True)

    result = rh_mod.scan_horizon()
    assert result == []


def test_scan_horizon_bq_row_within_7_days(monkeypatch):
    """Row with 5 days left triggers an alert (ALERT_DAYS=[180,..] fires on first match)."""
    row = _make_row(
        days_until_effective=5,
        horizon_id="H-001",
        regulation="CFPB Rule 2026-01",
        jurisdiction="Federal",
        change_summary="New disclosure requirement",
        effective_date="2026-05-01",
        owner_email="compliance@example.com",
        tracking_status="IN_REVIEW",
    )
    client = _make_bq_client_returning([row])
    mock_lib = MagicMock()
    mock_lib.Client.return_value = client

    monkeypatch.setattr(rh_mod, "_bq_lib", mock_lib)
    monkeypatch.setattr(rh_mod, "_BQ_AVAILABLE", True)

    alerts = rh_mod.scan_horizon()

    assert len(alerts) == 1
    assert alerts[0]["horizon_id"] == "H-001"
    # ALERT_DAYS=[180,90,60,30,7]: 5<=180 fires first → severity from SEVERITY_ESCALATION[180]
    assert alerts[0]["severity"] in rh_mod.SEVERITY_ESCALATION.values()
    assert alerts[0]["days_until_effective"] == 5


def test_scan_horizon_bq_row_within_30_days(monkeypatch):
    """Row with 25 days left triggers an alert."""
    row = _make_row(
        days_until_effective=25,
        horizon_id="H-002",
        regulation="OCC Guidance",
        jurisdiction="Federal",
        change_summary="Model risk update",
        effective_date="2026-05-20",
        owner_email="mrm@example.com",
        tracking_status="APPROVED",
    )
    client = _make_bq_client_returning([row])
    mock_lib = MagicMock()
    mock_lib.Client.return_value = client

    monkeypatch.setattr(rh_mod, "_bq_lib", mock_lib)
    monkeypatch.setattr(rh_mod, "_BQ_AVAILABLE", True)

    alerts = rh_mod.scan_horizon()

    assert len(alerts) == 1
    assert alerts[0]["horizon_id"] == "H-002"
    assert "severity" in alerts[0]


def test_scan_horizon_bq_row_within_90_days(monkeypatch):
    """Row with 65 days left → alert with all expected keys."""
    row = _make_row(
        days_until_effective=65,
        horizon_id="H-003",
        regulation="State Law AB123",
        jurisdiction="California",
        change_summary="Fee cap adjustment",
        effective_date="2026-06-29",
        owner_email="legal@example.com",
        tracking_status="IN_REVIEW",
    )
    client = _make_bq_client_returning([row])
    mock_lib = MagicMock()
    mock_lib.Client.return_value = client

    monkeypatch.setattr(rh_mod, "_bq_lib", mock_lib)
    monkeypatch.setattr(rh_mod, "_BQ_AVAILABLE", True)

    alerts = rh_mod.scan_horizon()

    assert len(alerts) == 1
    assert alerts[0]["horizon_id"] == "H-003"
    expected_keys = {"horizon_id", "regulation", "jurisdiction", "severity",
                     "days_until_effective", "effective_date", "owner_email"}
    assert expected_keys.issubset(set(alerts[0].keys()))


def test_scan_horizon_bq_row_within_180_days(monkeypatch):
    """Row with 150 days left → alert generated."""
    row = _make_row(
        days_until_effective=150,
        horizon_id="H-004",
        regulation="Dodd-Frank Amendment",
        jurisdiction="Federal",
        change_summary="Stress testing revision",
        effective_date="2026-09-22",
        owner_email="risk@example.com",
        tracking_status="BACKLOG",
    )
    client = _make_bq_client_returning([row])
    mock_lib = MagicMock()
    mock_lib.Client.return_value = client

    monkeypatch.setattr(rh_mod, "_bq_lib", mock_lib)
    monkeypatch.setattr(rh_mod, "_BQ_AVAILABLE", True)

    alerts = rh_mod.scan_horizon()

    assert len(alerts) == 1
    assert alerts[0]["horizon_id"] == "H-004"


def test_scan_horizon_bq_row_beyond_180_days_no_alert(monkeypatch):
    """Row with 200 days left → no alert (beyond all thresholds)."""
    row = _make_row(days_until_effective=200, horizon_id="H-005",
                    regulation="Future Reg", jurisdiction="Federal",
                    change_summary="TBD", effective_date="2026-11-11",
                    owner_email="x@example.com", tracking_status="BACKLOG")
    client = _make_bq_client_returning([row])
    mock_lib = MagicMock()
    mock_lib.Client.return_value = client

    monkeypatch.setattr(rh_mod, "_bq_lib", mock_lib)
    monkeypatch.setattr(rh_mod, "_BQ_AVAILABLE", True)

    alerts = rh_mod.scan_horizon()

    assert alerts == []


def test_scan_horizon_bq_multiple_rows(monkeypatch):
    """Multiple rows — each fires at most one alert (break after first threshold)."""
    rows = [
        _make_row(days_until_effective=5, horizon_id="H-A",
                  regulation="R1", jurisdiction="Federal",
                  change_summary="S1", effective_date="2026-05-01",
                  owner_email="a@x.com", tracking_status="IN_REVIEW"),
        _make_row(days_until_effective=100, horizon_id="H-B",
                  regulation="R2", jurisdiction="State",
                  change_summary="S2", effective_date="2026-08-03",
                  owner_email="b@x.com", tracking_status="APPROVED"),
    ]
    client = _make_bq_client_returning(rows)
    mock_lib = MagicMock()
    mock_lib.Client.return_value = client

    monkeypatch.setattr(rh_mod, "_bq_lib", mock_lib)
    monkeypatch.setattr(rh_mod, "_BQ_AVAILABLE", True)

    alerts = rh_mod.scan_horizon()

    # H-A fires (≤7 days), H-B fires (≤180 days) — one alert each
    assert len(alerts) == 2
    horizon_ids = {a["horizon_id"] for a in alerts}
    assert "H-A" in horizon_ids
    assert "H-B" in horizon_ids


# ---------------------------------------------------------------------------
# update_days_remaining — BQ path
# ---------------------------------------------------------------------------

def test_update_days_remaining_bq_calls_query(monkeypatch):
    client = _make_bq_client_returning([])
    mock_lib = MagicMock()
    mock_lib.Client.return_value = client

    monkeypatch.setattr(rh_mod, "_bq_lib", mock_lib)
    monkeypatch.setattr(rh_mod, "_BQ_AVAILABLE", True)

    rh_mod.update_days_remaining()  # should not raise

    mock_lib.Client.assert_called_once()
    client.query.assert_called_once()


def test_update_days_remaining_bq_disabled_is_noop(monkeypatch):
    """When _BQ_AVAILABLE=False, no BQ call is made."""
    mock_lib = MagicMock()
    monkeypatch.setattr(rh_mod, "_bq_lib", mock_lib)
    monkeypatch.setattr(rh_mod, "_BQ_AVAILABLE", False)

    rh_mod.update_days_remaining()

    mock_lib.Client.assert_not_called()


# ---------------------------------------------------------------------------
# get_horizon_items — BQ path
# ---------------------------------------------------------------------------

def test_get_horizon_items_bq_returns_dicts(monkeypatch):
    row = _make_row(horizon_id="H-X", regulation="Reg-X", jurisdiction="Federal",
                    change_summary="Summary", effective_date="2026-06-01",
                    days_until_effective=37, tracking_status="IN_REVIEW",
                    owner_email="x@x.com")
    client = _make_bq_client_returning([row])
    mock_lib = MagicMock()
    mock_lib.Client.return_value = client

    monkeypatch.setattr(rh_mod, "_bq_lib", mock_lib)
    monkeypatch.setattr(rh_mod, "_BQ_AVAILABLE", True)

    items = rh_mod.get_horizon_items(max_days=60)

    assert len(items) == 1
    assert items[0]["horizon_id"] == "H-X"


def test_get_horizon_items_bq_default_max_days(monkeypatch):
    client = _make_bq_client_returning([])
    mock_lib = MagicMock()
    mock_lib.Client.return_value = client

    monkeypatch.setattr(rh_mod, "_bq_lib", mock_lib)
    monkeypatch.setattr(rh_mod, "_BQ_AVAILABLE", True)

    items = rh_mod.get_horizon_items()  # default max_days=180

    assert items == []
    # Verify the query SQL contained the max_days value
    call_sql = client.query.call_args[0][0]
    assert "180" in call_sql


# ---------------------------------------------------------------------------
# flag_overdue_horizon_items — BQ path
# ---------------------------------------------------------------------------

def test_flag_overdue_horizon_items_bq_no_rows(monkeypatch):
    client = _make_bq_client_returning([])
    mock_lib = MagicMock()
    mock_lib.Client.return_value = client

    monkeypatch.setattr(rh_mod, "_bq_lib", mock_lib)
    monkeypatch.setattr(rh_mod, "_BQ_AVAILABLE", True)

    result = rh_mod.flag_overdue_horizon_items()

    assert result == []


def test_flag_overdue_horizon_items_bq_has_overdue(monkeypatch):
    row = _make_row(horizon_id="H-OLD", regulation="OldReg",
                    jurisdiction="Federal", change_summary="Expired",
                    effective_date="2026-03-01", days_until_effective=-55,
                    tracking_status="IN_REVIEW", owner_email="x@x.com")
    client = _make_bq_client_returning([row])
    mock_lib = MagicMock()
    mock_lib.Client.return_value = client

    monkeypatch.setattr(rh_mod, "_bq_lib", mock_lib)
    monkeypatch.setattr(rh_mod, "_BQ_AVAILABLE", True)

    result = rh_mod.flag_overdue_horizon_items()

    assert len(result) == 1
    assert result[0]["horizon_id"] == "H-OLD"
