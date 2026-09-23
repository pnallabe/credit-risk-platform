from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class CommercialFinancialSpreading:
    entity_name: str
    tax_id: str
    tax_form_type: str  # "1120-S", "1040-Schedule-C", "1065"
    fiscal_year: int
    gross_receipts_sales: float
    cost_of_goods_sold: float
    gross_profit: float
    officer_compensation: float
    operating_expenses: float
    net_taxable_income: float
    ebitda: float
    total_assets: float
    current_assets: float
    cash_and_equivalents: float
    current_liabilities: float
    total_debt: float
    annual_debt_service: float
    dscr: float
    debt_to_ebitda: float
    current_ratio: float
    parsed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CommercialDocumentParser:
    """Parses commercial tax returns (IRS 1120-S, 1040 Schedule C) and bank statements into standard financial spreading metrics."""

    def parse_tax_return(
        self,
        raw_document_dict: Dict[str, Any],
        form_type: str = "1120-S",
    ) -> CommercialFinancialSpreading:
        """Parse structured dictionary representing OCR-extracted tax return fields."""
        entity_name = str(raw_document_dict.get("entity_name", "Unknown Business Entity"))
        tax_id = str(raw_document_dict.get("tax_id", "00-0000000"))
        fiscal_year = int(raw_document_dict.get("fiscal_year", datetime.now().year - 1))

        gross_sales = float(raw_document_dict.get("gross_receipts_sales", 0.0))
        cogs = float(raw_document_dict.get("cost_of_goods_sold", 0.0))
        gross_profit = gross_sales - cogs if gross_sales > 0 else float(raw_document_dict.get("gross_profit", 0.0))

        officer_comp = float(raw_document_dict.get("officer_compensation", 0.0))
        opex = float(raw_document_dict.get("operating_expenses", 0.0))
        net_income = float(raw_document_dict.get("net_taxable_income", 0.0))
        depreciation = float(raw_document_dict.get("depreciation", 0.0))
        interest_exp = float(raw_document_dict.get("interest_expense", 0.0))

        # Compute EBITDA: Net Income + Interest + Depreciation
        ebitda = net_income + interest_exp + depreciation if net_income != 0 else gross_profit - opex

        total_assets = float(raw_document_dict.get("total_assets", 0.0))
        current_assets = float(raw_document_dict.get("current_assets", total_assets * 0.4))
        cash = float(raw_document_dict.get("cash_and_equivalents", current_assets * 0.5))

        total_debt = float(raw_document_dict.get("total_debt", 0.0))
        current_liab = float(raw_document_dict.get("current_liabilities", total_debt * 0.3))
        annual_debt_service = float(raw_document_dict.get("annual_debt_service", interest_exp + total_debt * 0.15))

        # Financial Ratios
        dscr = round(ebitda / annual_debt_service, 2) if annual_debt_service > 0 else 99.0
        debt_to_ebitda = round(total_debt / ebitda, 2) if ebitda > 0 else 99.0
        current_ratio = round(current_assets / current_liab, 2) if current_liab > 0 else 99.0

        return CommercialFinancialSpreading(
            entity_name=entity_name,
            tax_id=tax_id,
            tax_form_type=form_type,
            fiscal_year=fiscal_year,
            gross_receipts_sales=gross_sales,
            cost_of_goods_sold=cogs,
            gross_profit=gross_profit,
            officer_compensation=officer_comp,
            operating_expenses=opex,
            net_taxable_income=net_income,
            ebitda=ebitda,
            total_assets=total_assets,
            current_assets=current_assets,
            cash_and_equivalents=cash,
            current_liabilities=current_liab,
            total_debt=total_debt,
            annual_debt_service=annual_debt_service,
            dscr=dscr,
            debt_to_ebitda=debt_to_ebitda,
            current_ratio=current_ratio,
        )
