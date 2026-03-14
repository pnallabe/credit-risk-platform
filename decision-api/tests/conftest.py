"""pytest conftest for decision-api tests.

Adds the ``decision-api/`` directory to sys.path so that
``import src.main`` resolves correctly despite the hyphenated directory name.
"""

from __future__ import annotations

import sys
from pathlib import Path

# decision-api/ directory (parent of this tests/ folder)
_DECISION_API_DIR = str(Path(__file__).parent.parent)
if _DECISION_API_DIR not in sys.path:
    sys.path.insert(0, _DECISION_API_DIR)

# project root (for sibling packages: decision_engine, feature_pipeline, etc.)
_ROOT = str(Path(__file__).parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
