"""
Condition dataclass for conditional approval — S4-A
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional


@dataclass
class Condition:
    condition_type: Literal[
        "INCOME_VERIFICATION_REQUIRED",
        "REDUCED_LIMIT",
        "COLLATERAL_REQUIRED",
        "ADDITIONAL_DOCUMENTATION",
        "GUARANTOR_REQUIRED",
    ]
    description: str
    suggested_limit: Optional[float] = None        # for REDUCED_LIMIT
    min_coverage_ratio: Optional[float] = None     # for COLLATERAL_REQUIRED
    doc_types: Optional[List[str]] = None          # for ADDITIONAL_DOCUMENTATION
