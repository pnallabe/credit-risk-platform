"""Tests for FFIEC Call Report generator (S6-B)."""

from __future__ import annotations

import pandas as pd
import numpy as np
import pytest

from reporting.ffiec_call_report import (
    FFIECScheduleRCC,
    FFIECLoanRow,
    generate_schedule_rcc,
    _round_to_thousands,
    _FFIEC_CATEGORY,
)


def _make_df(seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    products = ["mortgage", "credit_card", "personal_loan", "commercial_loan", "smb_loan", "auto_loan"]
    n = 120
    return pd.DataFrame({
        "account_id": [f"ACC-{i:04d}" for i in range(n)],
        "product_type": list(rng.choice(products, size=n)),
        "exposure": rng.lognormal(10, 1.5, size=n),
        "dpd_30": rng.choice([True, False], size=n, p=[0.05, 0.95]),
        "dpd_90": rng.choice([True, False], size=n, p=[0.01, 0.99]),
        "loan_purpose": list(rng.choice(["purchase", "refinance", "construction"], size=n)),
    })


class TestFFIECCallReport:
    def test_returns_schedule_rcc(self):
        df = _make_df()
        schedule = generate_schedule_rcc("2026-01-01", "2026-03-31", df, "Test Bank")
        assert isinstance(schedule, FFIECScheduleRCC)

    def test_institution_name_and_date(self):
        df = _make_df()
        schedule = generate_schedule_rcc("2026-01-01", "2026-03-31", df, "Test Bank", rssd_id="123456")
        assert schedule.institution_name == "Test Bank"
        assert schedule.report_date == "2026-03-31"
        assert schedule.rssd_id == "123456"

    def test_rows_are_ffiec_loan_rows(self):
        df = _make_df()
        schedule = generate_schedule_rcc("2026-01-01", "2026-03-31", df, "Test Bank")
        for row in schedule.rows:
            assert isinstance(row, FFIECLoanRow)

    def test_category_codes_are_valid(self):
        valid_codes = {"1a", "1c", "4", "6a", "6b", "6c", "6d"}
        df = _make_df()
        schedule = generate_schedule_rcc("2026-01-01", "2026-03-31", df, "Test Bank")
        for row in schedule.rows:
            assert row.category_code in valid_codes, f"Unexpected code: {row.category_code}"

    def test_amounts_rounded_to_nearest_thousand(self):
        df = _make_df()
        schedule = generate_schedule_rcc("2026-01-01", "2026-03-31", df, "Test Bank")
        for row in schedule.rows:
            # amounts should be round numbers (multiples of 1.0 representing thousands)
            for amt in [row.domestic_offices_amount, row.memo_past_due_30_89, row.memo_past_due_90_plus]:
                assert amt == round(amt), f"Amount {amt} not rounded"

    def test_delinquency_buckets_correct(self):
        # Create controlled df: 10 accounts each at $100k
        df = pd.DataFrame({
            "product_type": ["personal_loan"] * 10,
            "exposure": [100_000.0] * 10,
            "dpd_30": [True] * 3 + [False] * 7,  # 3 in 30+ dpd
            "dpd_90": [True] * 1 + [False] * 9,   # 1 in 90+ dpd
        })
        schedule = generate_schedule_rcc("2026-01-01", "2026-03-31", df, "Test")
        row = next(r for r in schedule.rows if r.category_code == "6d")
        # dpd_30_89 = dpd_30 & ~dpd_90 = 2 accounts = $200k = 200 thousands
        assert row.memo_past_due_30_89 == 200.0
        # dpd_90 = 1 account = $100k = 100 thousands
        assert row.memo_past_due_90_plus == 100.0

    def test_excluded_products_not_in_report(self):
        df = pd.DataFrame({
            "product_type": ["deposit", "savings", "checking"],
            "exposure": [50_000.0] * 3,
            "dpd_30": [False] * 3,
            "dpd_90": [False] * 3,
        })
        schedule = generate_schedule_rcc("2026-01-01", "2026-03-31", df, "Test")
        assert len(schedule.rows) == 0

    def test_foreign_offices_amount_is_zero(self):
        df = _make_df()
        schedule = generate_schedule_rcc("2026-01-01", "2026-03-31", df, "Test Bank")
        for row in schedule.rows:
            assert row.foreign_offices_amount == 0.0

    def test_to_csv_format(self):
        df = _make_df()
        schedule = generate_schedule_rcc("2026-01-01", "2026-03-31", df, "Test Bank")
        csv_str = schedule.to_csv()
        assert "institution_name" in csv_str
        assert "|" in csv_str  # pipe-delimited
        lines = csv_str.strip().split("\n")
        assert len(lines) == len(schedule.rows) + 1  # header + data

    def test_to_xml_format(self):
        df = _make_df()
        schedule = generate_schedule_rcc("2026-01-01", "2026-03-31", df, "Test Bank")
        xml_str = schedule.to_xml()
        assert "<?xml" in xml_str
        assert "FFIECCallReport" in xml_str
        assert "ScheduleRCC" in xml_str

    def test_to_dict_format(self):
        df = _make_df()
        schedule = generate_schedule_rcc("2026-01-01", "2026-03-31", df, "Test Bank")
        d = schedule.to_dict()
        assert "rows" in d
        assert isinstance(d["rows"], list)

    def test_construction_loan_mapped_to_1a(self):
        df = pd.DataFrame({
            "product_type": ["mortgage"],
            "exposure": [500_000.0],
            "dpd_30": [False],
            "dpd_90": [False],
            "loan_purpose": ["construction"],
        })
        schedule = generate_schedule_rcc("2026-01-01", "2026-03-31", df, "Test")
        row = schedule.rows[0]
        assert row.category_code == "1a"

    def test_commercial_and_smb_both_map_to_4(self):
        df = pd.DataFrame({
            "product_type": ["commercial_loan", "smb_loan"],
            "exposure": [1_000_000.0, 500_000.0],
            "dpd_30": [False, False],
            "dpd_90": [False, False],
        })
        schedule = generate_schedule_rcc("2026-01-01", "2026-03-31", df, "Test")
        assert len(schedule.rows) == 1  # merged into same category
        assert schedule.rows[0].category_code == "4"
        assert schedule.rows[0].domestic_offices_amount == 1500.0  # $1.5M = 1500 thousands


class TestRoundToThousands:
    def test_rounds_up(self):
        assert _round_to_thousands(1_500_001) == 1500.0

    def test_rounds_down(self):
        assert _round_to_thousands(1_499_000) == 1499.0

    def test_exact(self):
        assert _round_to_thousands(250_000) == 250.0

    def test_zero(self):
        assert _round_to_thousands(0) == 0.0
