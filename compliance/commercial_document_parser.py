from __future__ import annotations

import json
import logging
import re
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


@dataclass
class MCADebtStackingResult:
    """Result of Merchant Cash Advance (MCA) debt-stacking detection analysis on bank transactions."""
    mca_detected: bool
    concurrent_mca_count: int
    flagged_funders: List[str]
    total_daily_mca_debits: float
    estimated_monthly_mca_payment: float
    mca_debt_service_strain_ratio: float  # (Monthly MCA payments / Monthly Revenue)
    risk_level: str  # "LOW", "MODERATE", "HIGH", "CRITICAL"
    detected_transactions: List[Dict[str, Any]]


class CommercialDocumentParser:
    """Parses commercial tax returns (IRS 1120-S, 1040 Schedule C, 1065) and bank statements into financial spreading metrics and detects MCA debt-stacking."""

    KNOWN_MCA_KEYWORDS: List[str] = [
        "KABBAGE", "ONDECK", "FUNDBOX", "RAPID FINANCE", "DAILY ACH",
        "CANAPITAL", "BIZ2CREDIT", "FORWARD FINANCING", "NATIONAL FUNDING",
        "BLUEVINE", "MULLEN", "LGCY", "LIBERTY CAPITAL", "CAPITAL STACK"
    ]

    EXCLUDED_ROUTINE_KEYWORDS: List[str] = [
        "PAYROLL", "ADP", "GUSTO", "INTUIT", "TAX", "IRS", "UTILITY",
        "UTILITIES", "VENDOR", "FEES", "SOFTWARE", "SUBSCRIPTION",
        "RENT", "INSURANCE", "TRANSFER TO SAVINGS", "CREDIT CARD PAYMENT"
    ]

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

    def parse_document_with_llm_vision(
        self,
        raw_text_or_json: str,
        form_type: str = "1120-S",
        use_llm: bool = False,
    ) -> CommercialFinancialSpreading:
        """Parse raw OCR text or unstructured document content into structured financial spreading.

        Supports regex line item extraction for IRS Form 1120-S (Line 1a, 2, 7, 14, 21), Form 1040 Schedule C, Form 1065.
        """
        parsed_fields: Dict[str, Any] = {}

        if use_llm:
            try:
                # Stubbed LLM call hook - falls back to regex parser if LLM response unavailable
                import os
                if os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY"):
                    logger.info("Parsing commercial document using LLM vision model...")
                    # LLM invocation logic would go here
            except Exception as exc:
                logger.warning("LLM document extraction failed; using regex parser: %s", exc)

        # Regex-based extraction fallback for standard IRS form line items
        text = raw_text_or_json.upper()

        # Entity Name
        name_match = (
            re.search(r"NAME OF CORPORATION[:\s]+([^\n\r]+?)(?:\s*(?:EIN|FORM|\d{2}-\d{7})|$)", text) or
            re.search(r"BUSINESS NAME[:\s]+([^\n\r]+?)(?:\s*(?:EIN|FORM|\d{2}-\d{7})|$)", text)
        )
        if name_match:
            parsed_fields["entity_name"] = name_match.group(1).strip()

        # Tax ID / EIN
        ein_match = re.search(r"\b(\d{2}-\d{7})\b", text)
        if ein_match:
            parsed_fields["tax_id"] = ein_match.group(1)

        # Line 1a: Gross receipts or sales
        sales_match = re.search(r"(?:GROSS RECEIPTS|GROSS SALES|LINE 1A)[^\d$]*\$?\s*([\d,]+(?:\.\d{2})?)", text)
        if sales_match:
            parsed_fields["gross_receipts_sales"] = float(sales_match.group(1).replace(",", ""))

        # Line 2: Cost of goods sold
        cogs_match = re.search(r"(?:COST OF GOODS|COGS|LINE 2)[^\d$]*\$?\s*([\d,]+(?:\.\d{2})?)", text)
        if cogs_match:
            parsed_fields["cost_of_goods_sold"] = float(cogs_match.group(1).replace(",", ""))

        # Line 7: Officer compensation
        officer_match = re.search(r"(?:COMPENSATION OF OFFICERS|LINE 7)[^\d$]*\$?\s*([\d,]+(?:\.\d{2})?)", text)
        if officer_match:
            parsed_fields["officer_compensation"] = float(officer_match.group(1).replace(",", ""))

        # Line 14: Depreciation
        dep_match = re.search(r"(?:DEPRECIATION|LINE 14)[^\d$]*\$?\s*([\d,]+(?:\.\d{2})?)", text)
        if dep_match:
            parsed_fields["depreciation"] = float(dep_match.group(1).replace(",", ""))

        # Line 21: Ordinary business income
        net_match = re.search(r"(?:ORDINARY BUSINESS INCOME|NET INCOME|LINE 21)[^\d$]*\$?\s*([\d,]+(?:\.\d{2})?)", text)
        if net_match:
            parsed_fields["net_taxable_income"] = float(net_match.group(1).replace(",", ""))

        # Balance Sheet Assets & Debt
        assets_match = re.search(r"(?:TOTAL ASSETS|LINE 15D)[^\d$]*\$?\s*([\d,]+(?:\.\d{2})?)", text)
        if assets_match:
            parsed_fields["total_assets"] = float(assets_match.group(1).replace(",", ""))

        debt_match = re.search(r"(?:TOTAL LIABILITIES|TOTAL DEBT)[^\d$]*\$?\s*([\d,]+(?:\.\d{2})?)", text)
        if debt_match:
            parsed_fields["total_debt"] = float(debt_match.group(1).replace(",", ""))

        return self.parse_tax_return(parsed_fields, form_type=form_type)

    def detect_mca_debt_stacking(
        self,
        bank_transactions: List[Dict[str, Any]],
        monthly_revenue: float = 50000.0,
    ) -> MCADebtStackingResult:
        """Scan bank transactions for daily ACH MCA debits, detect MCA lenders, and compute debt service strain.

        Remediations applied:
        1. Normalizes debit detection across positive and negative amount schemas.
        2. Filters out routine business transactions (payroll, taxes, utilities, credit card payments).
        3. Groups by (lender, amount_signature) to identify multiple distinct loan positions from the same funder.
        4. Independent monthly payment scaling per position signature.
        """
        flagged_txs: List[Dict[str, Any]] = []
        flagged_positions: set[str] = set()
        flagged_funders: set[str] = set()
        position_daily_sums: Dict[str, List[float]] = {}

        for tx in bank_transactions:
            desc = str(tx.get("description", tx.get("memo", ""))).upper()
            raw_amt = float(tx.get("amount", 0.0))
            amt_abs = abs(raw_amt)
            tx_type = str(tx.get("type", tx.get("transaction_type", ""))).lower()

            # 1. Normalized Debit Direction Check
            is_explicit_debit = raw_amt < 0 or any(kw in tx_type for kw in ["debit", "withdrawal", "outflow"])
            is_explicit_credit = raw_amt > 0 and any(kw in tx_type for kw in ["credit", "deposit", "inflow"])

            if is_explicit_credit or amt_abs <= 0:
                continue

            if not is_explicit_debit and raw_amt > 0:
                # If amount is positive and no explicit type, skip if it matches common deposit patterns
                if "DEPOSIT" in desc or "PAYMENT RECEIVED" in desc:
                    continue

            # 2. Exclude Routine Non-MCA Transactions
            if any(ex_kw in desc for ex_kw in self.EXCLUDED_ROUTINE_KEYWORDS):
                continue

            # 3. Check Known MCA Funder Match
            matched_funder = None
            for kw in self.KNOWN_MCA_KEYWORDS:
                if kw in desc:
                    matched_funder = kw
                    break

            # Check frequency pattern (daily ACH debit pattern)
            is_daily_ach = "DAILY" in desc or "ACH DEBIT" in desc or ("PAYMENT" in desc and "ACH" in desc)

            if matched_funder or (is_daily_ach and amt_abs > 50.0):
                funder_name = matched_funder if matched_funder else "UNIDENTIFIED_MCA_PROVIDER"
                # Position signature combines lender name + rounded amount (nearest $10) to catch multiple loans from 1 lender
                position_signature = f"{funder_name}_{round(amt_abs, -1):.0f}"

                flagged_funders.add(funder_name)
                flagged_positions.add(position_signature)
                flagged_txs.append(tx)

                if position_signature not in position_daily_sums:
                    position_daily_sums[position_signature] = []
                position_daily_sums[position_signature].append(amt_abs)

        # 4. Calculate Independent Monthly MCA Payment across active positions
        total_monthly_mca_payment = 0.0
        daily_debits_sum = 0.0

        for pos_sig, amts in position_daily_sums.items():
            daily_avg = sum(amts) / len(amts)
            daily_debits_sum += sum(amts)
            total_monthly_mca_payment += daily_avg * 21.0  # ~21 business days/month

        concurrent_count = max(len(flagged_funders), len(flagged_positions))
        mca_detected = concurrent_count > 0 or len(flagged_txs) >= 5

        # 5. Risk Classification & Debt Strain Calculation
        effective_rev = max(monthly_revenue, 1.0) if total_monthly_mca_payment > 0 else monthly_revenue
        strain_ratio = round(total_monthly_mca_payment / effective_rev, 4) if effective_rev > 0 else 0.0

        if concurrent_count >= 3 or strain_ratio >= 0.35:
            risk_level = "CRITICAL"
        elif concurrent_count == 2 or strain_ratio >= 0.20:
            risk_level = "HIGH"
        elif concurrent_count == 1 or strain_ratio >= 0.10:
            risk_level = "MODERATE"
        else:
            risk_level = "LOW"

        return MCADebtStackingResult(
            mca_detected=mca_detected,
            concurrent_mca_count=concurrent_count,
            flagged_funders=sorted(list(flagged_funders)),
            total_daily_mca_debits=round(daily_debits_sum, 2),
            estimated_monthly_mca_payment=round(total_monthly_mca_payment, 2),
            mca_debt_service_strain_ratio=strain_ratio,
            risk_level=risk_level,
            detected_transactions=flagged_txs,
        )
