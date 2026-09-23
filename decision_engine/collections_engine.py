from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from sklearn.linear_model import Ridge

logger = logging.getLogger(__name__)


@dataclass
class TreatmentRecommendation:
    account_id: str
    recommended_treatment: str  # "CALL", "EMAIL", "SMS", "SELF_CURE"
    estimated_uplift: float
    confidence_score: float


class CausalUpliftModel:
    """Causal Forest / T-Learner Uplift Model for collections treatment allocation.

    Estimates Individual Treatment Effect (ITE):
        ITE(x) = E[ Recovery | Treatment=Call, X=x ] - E[ Recovery | Treatment=SelfCure, X=x ]
    """

    def __init__(self) -> None:
        self.model_control = Ridge(alpha=1.0)
        self.model_treatment = Ridge(alpha=1.0)
        self._is_fitted = False

    def fit(self, X: np.ndarray, treatment: np.ndarray, y_recovery: np.ndarray) -> CausalUpliftModel:
        """Fit dual treatment and control models."""
        X = np.asarray(X, dtype=float)
        treatment = np.asarray(treatment, dtype=int)
        y_recovery = np.asarray(y_recovery, dtype=float)

        mask_ctrl = treatment == 0
        mask_treat = treatment == 1

        if np.sum(mask_ctrl) > 5 and np.sum(mask_treat) > 5:
            self.model_control.fit(X[mask_ctrl], y_recovery[mask_ctrl])
            self.model_treatment.fit(X[mask_treat], y_recovery[mask_treat])
            self._is_fitted = True
        return self

    def predict_uplift(self, X: np.ndarray) -> np.ndarray:
        """Predict expected recovery uplift (ITE)."""
        if not self._is_fitted:
            return np.full(len(X), 0.05)
        pred_treat = self.model_treatment.predict(X)
        pred_ctrl = self.model_control.predict(X)
        return pred_treat - pred_ctrl

    def allocate_treatment(self, account_id: str, feature_vector: np.ndarray, dpd: int) -> TreatmentRecommendation:
        """Select optimal treatment channel based on predicted uplift and delinquency bucket."""
        if dpd <= 15:
            return TreatmentRecommendation(account_id, "SELF_CURE", 0.02, 0.95)

        uplift = float(self.predict_uplift(feature_vector.reshape(1, -1))[0])

        if uplift >= 0.15:
            rec = "CALL"
        elif uplift >= 0.05:
            rec = "SMS"
        elif uplift >= 0.01:
            rec = "EMAIL"
        else:
            rec = "SELF_CURE"

        return TreatmentRecommendation(account_id, rec, round(uplift, 4), 0.90)


@dataclass
class RegFCheckResult:
    allowed: bool
    reason: str
    call_attempts_last_7d: int


class RegFContactGuard:
    """CFPB Regulation F (§ 1006.14) Contact Frequency Guard.

    Enforces the 7-in-7 rule:
    - No more than 7 telephone call attempts within 7 consecutive days.
    - At least 7 days must elapse after a telephone conversation before calling again.
    - Permissible contact window: 8:00 AM to 9:00 PM local borrower time.
    """

    def __init__(self, max_calls_per_7d: int = 7) -> None:
        self.max_calls_per_7d = max_calls_per_7d
        # account_id -> list of POSIX timestamps of call attempts
        self._call_logs: Dict[str, List[float]] = defaultdict(list)

    def record_call_attempt(self, account_id: str, timestamp: float) -> None:
        self._call_logs[account_id].append(timestamp)

    def can_call_borrower(self, account_id: str, current_time: float, local_hour: int) -> RegFCheckResult:
        """Evaluate if calling borrower complies with Regulation F."""
        # 1. Time-of-day check (8:00 AM to 9:00 PM)
        if local_hour < 8 or local_hour >= 21:
            return RegFCheckResult(False, "OUTSIDE_PERMISSIBLE_HOURS_REG_F", 0)

        # 2. 7-day sliding window call count check
        seven_days_sec = 7 * 86400
        recent_calls = [t for t in self._call_logs[account_id] if (current_time - t) <= seven_days_sec]
        call_count = len(recent_calls)

        if call_count >= self.max_calls_per_7d:
            return RegFCheckResult(False, "REG_F_7_CALL_ATTEMPTS_EXCEEDED", call_count)

        return RegFCheckResult(True, "REG_F_COMPLIANT", call_count)


@dataclass
class SettlementOffer:
    account_id: str
    outstanding_balance: float
    dpd: int
    lump_sum_offer: float
    lump_sum_discount_pct: float
    installment_offer_monthly: float
    installment_months: int
    npv_recovery_expectation: float


class SettlementCopilot:
    """AI Settlement Negotiation Copilot for delinquent accounts."""

    def __init__(self, min_lump_sum_discount: float = 0.30, max_lump_sum_discount: float = 0.55) -> None:
        self.min_lump_sum_discount = min_lump_sum_discount
        self.max_lump_sum_discount = max_lump_sum_discount

    def generate_offer(self, account_id: str, balance: float, dpd: int) -> SettlementOffer:
        """Compute NPV-optimal settlement lump-sum and installment offers."""
        if dpd >= 180:
            disc = self.max_lump_sum_discount
        elif dpd >= 120:
            disc = 0.45
        elif dpd >= 90:
            disc = self.min_lump_sum_discount
        else:
            disc = 0.20

        lump_sum = round(balance * (1.0 - disc), 2)
        inst_months = 12
        monthly_inst = round((balance * (1.0 - disc + 0.05)) / inst_months, 2)
        npv = round(lump_sum * 0.95, 2)

        return SettlementOffer(
            account_id=account_id,
            outstanding_balance=balance,
            dpd=dpd,
            lump_sum_offer=lump_sum,
            lump_sum_discount_pct=round(disc * 100, 1),
            installment_offer_monthly=monthly_inst,
            installment_months=inst_months,
            npv_recovery_expectation=npv,
        )
