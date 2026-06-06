"""
FFIEC Call Report — S6-B
=========================
Generates FFIEC Schedule RC-C Part I loan category data.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

import pandas as pd

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FFIEC Loan Category Mapping
# ---------------------------------------------------------------------------

# Internal product_type → (category_code, category_description)
_FFIEC_CATEGORY: Dict[str, tuple[str, str]] = {
    "mortgage":         ("1c", "1c. Secured by 1-4 family residential properties"),
    "construction":     ("1a", "1a. Construction and land development"),
    "commercial_loan":  ("4",  "4. Commercial and industrial loans"),
    "smb_loan":         ("4",  "4. Commercial and industrial loans"),
    "credit_card":      ("6c", "6c. Other revolving credit plans"),
    "personal_loan":    ("6d", "6d. Other consumer loans"),
    "auto_loan":        ("6a", "6a. Automobile loans"),
    "student_loan":     ("6d", "6d. Other consumer loans"),
}

# Products excluded from RC-C
_EXCLUDED_PRODUCTS = {"deposit", "savings", "checking"}


@dataclass
class FFIECLoanRow:
    category_code: str
    category_description: str
    domestic_offices_amount: float    # in thousands USD
    foreign_offices_amount: float
    memo_past_due_30_89: float
    memo_past_due_90_plus: float


@dataclass
class FFIECScheduleRCC:
    institution_name: str
    report_date: str
    rssd_id: Optional[str]
    rows: List[FFIECLoanRow]

    def to_csv(self) -> str:
        """Return pipe-delimited CSV in FFIEC standard layout."""
        buf = io.StringIO()
        writer = csv.writer(buf, delimiter="|")
        writer.writerow([
            "institution_name", "report_date", "rssd_id",
            "category_code", "category_description",
            "domestic_offices_amount_thousands", "foreign_offices_amount_thousands",
            "memo_past_due_30_89_thousands", "memo_past_due_90_plus_thousands",
        ])
        for row in self.rows:
            writer.writerow([
                self.institution_name,
                self.report_date,
                self.rssd_id or "",
                row.category_code,
                row.category_description,
                row.domestic_offices_amount,
                row.foreign_offices_amount,
                row.memo_past_due_30_89,
                row.memo_past_due_90_plus,
            ])
        return buf.getvalue()

    def to_xml(self) -> str:
        """Return basic XBRL-compatible XML (no taxonomy validation)."""
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<FFIECCallReport xmlns:rc="http://www.ffiec.gov/call-report">',
            f'  <InstitutionName>{self.institution_name}</InstitutionName>',
            f'  <ReportDate>{self.report_date}</ReportDate>',
            f'  <RSSDID>{self.rssd_id or ""}</RSSDID>',
            "  <ScheduleRCC>",
        ]
        for row in self.rows:
            lines += [
                "    <LoanCategory>",
                f"      <CategoryCode>{row.category_code}</CategoryCode>",
                f"      <CategoryDescription>{row.category_description}</CategoryDescription>",
                f"      <DomesticOfficesAmount>{row.domestic_offices_amount}</DomesticOfficesAmount>",
                f"      <ForeignOfficesAmount>{row.foreign_offices_amount}</ForeignOfficesAmount>",
                f"      <MemoPastDue3089>{row.memo_past_due_30_89}</MemoPastDue3089>",
                f"      <MemoPastDue90Plus>{row.memo_past_due_90_plus}</MemoPastDue90Plus>",
                "    </LoanCategory>",
            ]
        lines += ["  </ScheduleRCC>", "</FFIECCallReport>"]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "institution_name": self.institution_name,
            "report_date": self.report_date,
            "rssd_id": self.rssd_id,
            "rows": [
                {
                    "category_code": r.category_code,
                    "category_description": r.category_description,
                    "domestic_offices_amount": r.domestic_offices_amount,
                    "foreign_offices_amount": r.foreign_offices_amount,
                    "memo_past_due_30_89": r.memo_past_due_30_89,
                    "memo_past_due_90_plus": r.memo_past_due_90_plus,
                }
                for r in self.rows
            ],
        }


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


def generate_schedule_rcc(
    period_start: str,
    period_end: str,
    decisions_df: pd.DataFrame,
    institution_name: str,
    rssd_id: Optional[str] = None,
) -> FFIECScheduleRCC:
    """Generate FFIEC Schedule RC-C from portfolio decisions DataFrame.

    Parameters
    ----------
    period_start, period_end:
        ISO-8601 date strings (YYYY-MM-DD).
    decisions_df:
        Must contain: product_type, exposure (USD), dpd_30 (bool), dpd_90 (bool).
        Optional: loan_purpose.
    institution_name:
        Legal name of the institution.
    rssd_id:
        Federal Reserve RSSD charter ID (optional).

    Returns
    -------
    FFIECScheduleRCC
    """
    df = decisions_df.copy()

    # Filter excluded products
    if "product_type" in df.columns:
        df = df[~df["product_type"].isin(_EXCLUDED_PRODUCTS)]
    else:
        return FFIECScheduleRCC(
            institution_name=institution_name,
            report_date=period_end,
            rssd_id=rssd_id,
            rows=[],
        )

    # Resolve FFIEC category
    df["_ffiec_code"] = df["product_type"].map(
        lambda p: _FFIEC_CATEGORY.get(str(p).lower(), ("6d", "6d. Other consumer loans"))[0]
    )
    df["_ffiec_desc"] = df["product_type"].map(
        lambda p: _FFIEC_CATEGORY.get(str(p).lower(), ("6d", "6d. Other consumer loans"))[1]
    )

    # For mortgages: use loan_purpose to distinguish construction vs residential
    if "loan_purpose" in df.columns:
        construction_mask = df["loan_purpose"].str.lower().str.contains(
            "construct|land", na=False
        )
        df.loc[construction_mask & (df["product_type"] == "mortgage"), "_ffiec_code"] = "1a"
        df.loc[construction_mask & (df["product_type"] == "mortgage"), "_ffiec_desc"] = (
            "1a. Construction and land development"
        )

    # Ensure numeric
    df["exposure"] = pd.to_numeric(df.get("exposure", 0), errors="coerce").fillna(0.0)
    dpd_30 = pd.to_numeric(df.get("dpd_30", 0), errors="coerce").fillna(0).astype(bool)
    dpd_90 = pd.to_numeric(df.get("dpd_90", 0), errors="coerce").fillna(0).astype(bool)

    # Delinquency windows:
    #   30-89 dpd: dpd_30 but NOT dpd_90
    #   90+  dpd: dpd_90
    dpd_30_89 = dpd_30 & ~dpd_90

    df["_dpd_30_89_exp"] = df["exposure"].where(dpd_30_89, 0.0)
    df["_dpd_90_exp"] = df["exposure"].where(dpd_90, 0.0)

    # Aggregate by FFIEC category
    grouped = df.groupby(["_ffiec_code", "_ffiec_desc"]).agg(
        total_exposure=("exposure", "sum"),
        dpd_30_89_total=("_dpd_30_89_exp", "sum"),
        dpd_90_total=("_dpd_90_exp", "sum"),
    ).reset_index()

    rows: List[FFIECLoanRow] = []
    for _, g in grouped.iterrows():
        # Convert to thousands, round to nearest thousand
        domestic = _round_to_thousands(float(g["total_exposure"]))
        memo_30 = _round_to_thousands(float(g["dpd_30_89_total"]))
        memo_90 = _round_to_thousands(float(g["dpd_90_total"]))
        rows.append(
            FFIECLoanRow(
                category_code=str(g["_ffiec_code"]),
                category_description=str(g["_ffiec_desc"]),
                domestic_offices_amount=domestic,
                foreign_offices_amount=0.0,
                memo_past_due_30_89=memo_30,
                memo_past_due_90_plus=memo_90,
            )
        )

    # Sort by category code for deterministic output
    rows.sort(key=lambda r: r.category_code)

    return FFIECScheduleRCC(
        institution_name=institution_name,
        report_date=period_end,
        rssd_id=rssd_id,
        rows=rows,
    )


def _round_to_thousands(amount: float) -> float:
    """Round dollar amount to nearest thousand."""
    return round(amount / 1000.0) * 1.0
