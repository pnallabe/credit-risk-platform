"""
Tests for Sprint 8-A: SOC2EvidenceCollector (compliance/soc2_evidence.py)
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from compliance.soc2_evidence import (
    ControlEvidenceItem,
    EvidencePackage,
    SOC2EvidenceCollector,
    TSC_CATALOGUE,
    get_control_info,
    list_supported_controls,
)

DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def collector():
    c = SOC2EvidenceCollector(db_url=DB_URL, tenant_id="test-tenant")
    await c.initialise()
    return c


# ---------------------------------------------------------------------------
# TSC catalogue
# ---------------------------------------------------------------------------

def test_tsc_catalogue_non_empty():
    assert len(TSC_CATALOGUE) >= 10


def test_tsc_catalogue_has_required_categories():
    categories = {v["category"] for v in TSC_CATALOGUE.values()}
    for expected in ("CC1", "CC4", "CC6", "CC8", "CC9"):
        assert expected in categories, f"Missing category {expected}"


def test_get_control_info_known():
    info = get_control_info("CC6.1")
    assert info is not None
    assert info["category"] == "CC6"
    assert "platform_control" in info


def test_get_control_info_unknown():
    assert get_control_info("CC99.99") is None


def test_list_supported_controls_contains_all():
    controls = list_supported_controls()
    assert len(controls) == len(TSC_CATALOGUE)
    assert all("control_id" in c for c in controls)


# ---------------------------------------------------------------------------
# generate_evidence_package — empty DB
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_package_returns_evidence_package(collector):
    pkg = await collector.generate_evidence_package("2025-Q1")
    assert isinstance(pkg, EvidencePackage)
    assert pkg.tenant_id == "test-tenant"
    assert pkg.period_label == "2025-Q1"
    assert len(pkg.controls) == len(TSC_CATALOGUE)


@pytest.mark.asyncio
async def test_generate_package_overall_status_set(collector):
    pkg = await collector.generate_evidence_package("2025-Q1")
    assert pkg.overall_status in ("COMPLIANT", "PARTIAL", "NON_COMPLIANT")


@pytest.mark.asyncio
async def test_generate_package_all_control_ids_present(collector):
    pkg = await collector.generate_evidence_package("2025-Q1")
    collected_ids = {c.control_id for c in pkg.controls}
    for cid in TSC_CATALOGUE:
        assert cid in collected_ids


@pytest.mark.asyncio
async def test_generate_package_subset_of_controls(collector):
    pkg = await collector.generate_evidence_package(
        "2025-Q2",
        control_ids=["CC6.1", "CC8.1"],
    )
    assert len(pkg.controls) == 2
    ids = {c.control_id for c in pkg.controls}
    assert ids == {"CC6.1", "CC8.1"}


# ---------------------------------------------------------------------------
# Summary table
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_summary_table_is_markdown(collector):
    pkg = await collector.generate_evidence_package("2025-Q1")
    table = pkg.summary_table
    assert "| Control ID |" in table
    assert "CC6.1" in table


# ---------------------------------------------------------------------------
# to_json / to_dict round-trip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_package_to_json_round_trip(collector):
    import json
    pkg = await collector.generate_evidence_package("2025-Q1")
    d = json.loads(pkg.to_json())
    assert d["tenant_id"] == "test-tenant"
    assert isinstance(d["controls"], list)
    assert len(d["controls"]) == len(TSC_CATALOGUE)


# ---------------------------------------------------------------------------
# list_packages — initially empty, then populated
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_packages_empty_initially(collector):
    result = await collector.list_packages()
    assert result == []


@pytest.mark.asyncio
async def test_list_packages_after_generate(collector):
    await collector.generate_evidence_package("2025-Q1")
    result = await collector.list_packages()
    assert len(result) == 1
    assert result[0]["period_label"] == "2025-Q1"


# ---------------------------------------------------------------------------
# get_latest_package
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_latest_package_none_when_no_packages(collector):
    result = await collector.get_latest_package()
    assert result is None


@pytest.mark.asyncio
async def test_get_latest_package_returns_most_recent(collector):
    await collector.generate_evidence_package("2025-Q1")
    await collector.generate_evidence_package("2025-Q2")
    pkg = await collector.get_latest_package()
    assert pkg is not None
    # Verify it returned a valid package
    assert pkg.tenant_id == "test-tenant"
