"""Data models for the bureau client layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class BureauProvider(str, Enum):
    EXPERIAN   = "experian"
    TRANSUNION = "transunion"
    EQUIFAX    = "equifax"
    MOCK       = "mock"


@dataclass(frozen=True)
class BureauRequest:
    application_id:   str
    first_name:       str
    last_name:        str
    date_of_birth:    str    # ISO-8601 YYYY-MM-DD
    ssn_last4:        str    # last 4 digits only — NEVER log full SSN
    address_line1:    str
    city:             str
    state:            str    # 2-letter US state code
    zip_code:         str
    requested_amount: float
    loan_purpose:     str


@dataclass(frozen=True)
class Tradeline:
    creditor_name:   str
    account_type:    str              # "revolving" | "installment" | "mortgage" | "other"
    balance:         float
    credit_limit:    Optional[float]
    payment_status:  str              # "current" | "30_dpd" | "60_dpd" | "90_dpd" | "chargeoff"
    opened_date:     Optional[str]    # ISO-8601
    months_on_file:  Optional[int]


@dataclass(frozen=True)
class BureauResponse:
    provider:                    BureauProvider
    application_id:              str
    credit_score:                int         # FICO 8 or provider equivalent
    score_model:                 str         # e.g. "FICO_8", "VantageScore_4"
    open_accounts:               int
    delinquencies_last_24m:      int
    total_debt:                  float
    utilisation_rate:            float       # 0.0–1.0
    inquiries_last_6m:           int
    months_since_oldest_account: int
    public_records:              int
    tradelines:    List[Tradeline] = field(default_factory=list)
    raw_response:  dict            = field(default_factory=dict)
    pulled_at:     str             = ""      # ISO-8601 UTC timestamp

    def to_feature_dict(self) -> dict:
        """Return a flat dict suitable for feature_pipeline ingestion."""
        return {
            "bureau_provider":              self.provider.value,
            "credit_score":                 self.credit_score,
            "open_accounts":                self.open_accounts,
            "delinquencies_last_24m":       self.delinquencies_last_24m,
            "total_debt":                   self.total_debt,
            "utilisation_rate":             self.utilisation_rate,
            "inquiries_last_6m":            self.inquiries_last_6m,
            "months_since_oldest_account":  self.months_since_oldest_account,
            "public_records":               self.public_records,
            # Derived tradeline aggregates
            "tradeline_count":              len(self.tradelines),
            "derogatory_tradeline_count":   sum(
                1 for t in self.tradelines
                if t.payment_status not in ("current",)
            ),
            "revolving_utilisation_avg":    self._revolving_util_avg(),
        }

    def _revolving_util_avg(self) -> float:
        revolving = [
            t for t in self.tradelines
            if t.account_type == "revolving" and t.credit_limit and t.credit_limit > 0
        ]
        if not revolving:
            return 0.0
        return sum(t.balance / t.credit_limit for t in revolving) / len(revolving)


class BureauPullError(Exception):
    """Raised when all bureau providers fail or are misconfigured."""

    def __init__(self, message: str, provider: Optional[BureauProvider] = None):
        super().__init__(message)
        self.provider = provider
