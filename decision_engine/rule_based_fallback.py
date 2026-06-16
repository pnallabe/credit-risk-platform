"""
Rule-Based Fallback Scorer — S6-A
===================================
Provides a deterministic PD estimate when the ML model is unavailable.
Uses only bureau features (FICO, DTI, derogatory marks).
"""

from __future__ import annotations

from typing import Optional


def rule_based_pd_estimate(features: dict) -> tuple[float, str]:
    """Return (pd_score, rationale) using only bureau features.

    Decision tree:
      fico >= 720 AND dti < 0.36 AND num_derog_marks == 0 → PD = 0.03
      fico >= 680 AND dti < 0.43                           → PD = 0.07
      fico >= 620 AND dti < 0.50                           → PD = 0.13
      fico >= 580                                          → PD = 0.22
      else                                                 → PD = 0.40
      fico not available                                   → PD = 0.99 (force refer)
    """
    fico_raw = features.get("fico_score") or features.get("credit_score")
    if fico_raw is None:
        return 0.99, "FICO score not available; forcing manual review."

    fico = float(fico_raw)
    dti = float(features.get("dti", features.get("debt_to_income_ratio", 0.50)))
    derog = int(features.get("num_derog_marks", features.get("num_derogatory_marks", 0)))

    if fico >= 720 and dti < 0.36 and derog == 0:
        return 0.03, (
            f"FICO {fico:.0f} ≥ 720, DTI {dti:.2f} < 0.36, no derogatory marks → Low PD = 0.03"
        )
    if fico >= 680 and dti < 0.43:
        return 0.07, (
            f"FICO {fico:.0f} ≥ 680, DTI {dti:.2f} < 0.43 → Near-prime PD = 0.07"
        )
    if fico >= 620 and dti < 0.50:
        return 0.13, (
            f"FICO {fico:.0f} ≥ 620, DTI {dti:.2f} < 0.50 → Subprime PD = 0.13"
        )
    if fico >= 580:
        return 0.22, (
            f"FICO {fico:.0f} ≥ 580 → Deep-subprime PD = 0.22"
        )

    return 0.40, (
        f"FICO {fico:.0f} < 580 → High risk PD = 0.40"
    )
