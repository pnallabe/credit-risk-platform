"""
credit_core
===========
Canonical "credit brain" package — the single source of truth for
feature engineering and policy evaluation used by ALL entry points:

  * Decision API (decision-api/src/main.py)
  * Agent orchestrator (orchestration/pipeline.py)
  * Batch scoring jobs

Importing any logic directly from ``feature_pipeline`` or
``decision_engine`` by non-core code is deprecated in favour of these
public entry points, which guarantee a consistent feature matrix and
decision outcome regardless of calling channel.

Public surface
--------------
>>> from credit_core.features import compute_feature_matrix
>>> from credit_core.policy import evaluate_policy
"""

from credit_core.features import compute_feature_matrix  # noqa: F401
from credit_core.policy import evaluate_policy  # noqa: F401

__all__ = ["compute_feature_matrix", "evaluate_policy"]
