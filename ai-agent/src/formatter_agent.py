"""
formatter_agent.py — Prompt 20-D (GAP-20)
Final gate before AI answers are delivered.
PRD §4.6.5 Rule 6 (non-negotiable): blocks output if code_artifacts is empty.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CodeArtifactsMissingError(Exception):
    """Raised when FormatterAgent blocks delivery due to missing code artifacts."""


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

class FormattedOutput(BaseModel):
    answer_text: str
    code_artifacts: list[str]         # URIs from code_artifact_store
    code_zip_uri: Optional[str]       # ZIP URI if already assembled
    confidence: str                   # HIGH | MEDIUM | LOW
    metadata: dict                    # session_id, query_id, tenant_id, timestamp


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class FormatterAgent:
    """
    Final formatting gate. Enforces Rule 6: no delivery without code artifacts.
    """

    def format(
        self,
        validated_narrative: str,
        code_artifact_uris: list[str],
        confidence: str,
        metadata: dict,
        code_zip_uri: Optional[str] = None,
    ) -> FormattedOutput:
        """
        Format and validate output for delivery.
        Raises CodeArtifactsMissingError if code_artifact_uris is empty.
        """
        if not code_artifact_uris:
            raise CodeArtifactsMissingError(
                "Output delivery blocked: no code artifacts recorded for this query. "
                "Ensure the query pipeline produced and stored at least one SQL or "
                "Python artifact before formatting the answer."
            )

        return FormattedOutput(
            answer_text=validated_narrative,
            code_artifacts=code_artifact_uris,
            code_zip_uri=code_zip_uri,
            confidence=confidence,
            metadata=metadata,
        )
