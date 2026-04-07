"""Data quality enforcement — no-dependency expectation suite.

Public API
----------
>>> from data_quality import run_expectations, assert_quality_gate, CC_PD_TRAINING_RULES
>>> from data_quality import DataQualityReport, save_report
"""
from data_quality.expectations import (
    DataQualityRule,
    DataQualityReport,
    DataQualityGateError,
    CC_PD_TRAINING_RULES,
    run_expectations,
    assert_quality_gate,
    save_report,
)

__all__ = [
    "DataQualityRule",
    "DataQualityReport",
    "DataQualityGateError",
    "CC_PD_TRAINING_RULES",
    "run_expectations",
    "assert_quality_gate",
    "save_report",
]
