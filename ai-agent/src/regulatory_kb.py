"""
regulatory_kb.py — Prompt 20-D (GAP-20)
RegulatoryKB retrieves relevant regulatory guidance chunks for a query.
RegulatoryInterpreterAgent formats those chunks for LLM context.
PRD §4.6.6 (RegulatoryInterpreterAgent)
"""
from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

class RegulatoryChunk(BaseModel):
    source: str
    text: str
    relevance_score: float


# ---------------------------------------------------------------------------
# Knowledge Base
# ---------------------------------------------------------------------------

class RegulatoryKB:
    """
    Regulatory guidance knowledge base.
    Production: Pinecone vector index "regulatory-kb".
    Development fallback: keyword-matching over STATIC_REGULATORY_CHUNKS.
    """

    STATIC_REGULATORY_CHUNKS: list[RegulatoryChunk] = [
        RegulatoryChunk(
            source="SR_11-7_Section_2",
            text=(
                "SR 11-7 requires banks to maintain a model risk management framework "
                "that includes robust model validation. Models must be validated by "
                "personnel independent of model development. Validation should include "
                "conceptual soundness evaluation, ongoing monitoring, and outcomes analysis."
            ),
            relevance_score=0.9,
        ),
        RegulatoryChunk(
            source="ECOA_Reg_B_202.6",
            text=(
                "Regulation B prohibits creditors from discriminating against applicants "
                "on the basis of race, color, religion, national origin, sex, marital status, "
                "age, or because the applicant receives public assistance. "
                "Disparate impact analysis must be applied to facially neutral policies. "
                "The Disparity Impact Ratio (DIR) threshold for adverse impact is 80%."
            ),
            relevance_score=0.9,
        ),
        RegulatoryChunk(
            source="CFPB_UDAAP_Exam_Procedures",
            text=(
                "UDAAP examination procedures require that credit products not be unfair, "
                "deceptive, or abusive. Unfairness is assessed based on whether an act "
                "causes substantial injury to consumers that is not reasonably avoidable. "
                "AI-generated outputs that misrepresent risk or omit material information "
                "may constitute deceptive acts."
            ),
            relevance_score=0.85,
        ),
        RegulatoryChunk(
            source="OCC_Bulletin_2021-23_Model_Risk",
            text=(
                "OCC Bulletin 2021-23 extends SR 11-7 guidance to third-party models "
                "and algorithmic decision-making systems. Banks must ensure that "
                "third-party AI/ML models used in credit decisioning are subject to "
                "the same model risk management standards as internally developed models. "
                "Explainability and fairness assessments are required before production deployment."
            ),
            relevance_score=0.85,
        ),
        RegulatoryChunk(
            source="FFIEC_IT_Examination_AI",
            text=(
                "FFIEC guidance on AI emphasizes that financial institutions must maintain "
                "human oversight of AI-driven decisions. Automated credit decisions must "
                "generate adverse action notices compliant with ECOA and FCRA. "
                "Model outputs must be auditable, and audit logs must be retained for "
                "a minimum of 5 years."
            ),
            relevance_score=0.80,
        ),
    ]

    def __init__(
        self,
        pinecone_api_key: Optional[str] = None,
        index_name: str = "regulatory-kb",
    ) -> None:
        self._backend = "local"

        if pinecone_api_key:
            try:
                import pinecone  # type: ignore[import]
                pinecone.init(api_key=pinecone_api_key)
                self._index = pinecone.Index(index_name)
                self._backend = "pinecone"
                logger.info("RegulatoryKB: using Pinecone backend (index=%s)", index_name)
            except ImportError:
                logger.info("RegulatoryKB: pinecone not installed; using local keyword backend.")
            except Exception as exc:
                logger.info("RegulatoryKB: Pinecone unavailable (%s); using local backend.", exc)
        else:
            logger.info("RegulatoryKB: no API key provided; using local keyword backend.")

    def query(self, query_text: str, top_k: int = 5) -> list[RegulatoryChunk]:
        """
        Query for relevant regulatory chunks.
        Pinecone backend: embed + vector search.
        Local backend: keyword matching with word-overlap scoring.
        Always returns sorted by relevance_score DESC.
        """
        if self._backend == "pinecone":
            return self._query_pinecone(query_text, top_k)
        return self._query_local(query_text, top_k)

    def _query_pinecone(self, query_text: str, top_k: int) -> list[RegulatoryChunk]:
        """Embed and query Pinecone. Falls back to local on any error."""
        try:
            # Attempt to use langchain_openai for embedding
            try:
                from langchain_openai import OpenAIEmbeddings  # type: ignore[import]
                import os
                embeddings = OpenAIEmbeddings(openai_api_key=os.getenv("OPENAI_API_KEY", ""))
                vector = embeddings.embed_query(query_text)
            except Exception:
                return self._query_local(query_text, top_k)

            results = self._index.query(vector=vector, top_k=top_k, include_metadata=True)
            chunks: list[RegulatoryChunk] = []
            for match in results.get("matches", []):
                meta = match.get("metadata", {})
                chunks.append(
                    RegulatoryChunk(
                        source=meta.get("source", match.get("id", "unknown")),
                        text=meta.get("text", ""),
                        relevance_score=float(match.get("score", 0.5)),
                    )
                )
            return sorted(chunks, key=lambda c: c.relevance_score, reverse=True)
        except Exception as exc:
            logger.warning("Pinecone query failed: %s; falling back to local.", exc)
            return self._query_local(query_text, top_k)

    def _query_local(self, query_text: str, top_k: int) -> list[RegulatoryChunk]:
        """Keyword overlap scoring over STATIC_REGULATORY_CHUNKS."""
        query_words = set(query_text.lower().split())

        scored: list[tuple[float, RegulatoryChunk]] = []
        for chunk in self.STATIC_REGULATORY_CHUNKS:
            chunk_words = set(chunk.text.lower().split())
            overlap = len(query_words & chunk_words)
            score = (overlap / max(len(query_words), 1)) * chunk.relevance_score
            scored.append((score, chunk))

        scored.sort(key=lambda t: t[0], reverse=True)
        return [chunk for _, chunk in scored[:top_k]]


# ---------------------------------------------------------------------------
# Interpreter Agent
# ---------------------------------------------------------------------------

class RegulatoryInterpreterAgent:
    """Formats regulatory guidance chunks as LLM context strings."""

    def __init__(self, kb: RegulatoryKB) -> None:
        self.kb = kb

    def build_context(self, query_text: str, top_k: int = 3) -> str:
        """
        Retrieve top_k regulatory chunks relevant to query_text and format
        them as a regulatory context block for LLM prompt injection.
        Returns empty string if no chunks match.
        """
        try:
            chunks = self.kb.query(query_text, top_k=top_k)
        except Exception as exc:
            logger.warning("RegulatoryKB.query failed: %s", exc)
            return ""

        if not chunks:
            return ""

        lines = [
            "",
            "--- REGULATORY CONTEXT ---",
            "Relevant regulatory guidance for this query:",
        ]
        for chunk in chunks:
            lines.append(f"\n[{chunk.source}] (relevance: {chunk.relevance_score:.2f})")
            lines.append(chunk.text)
        lines.append("--- END REGULATORY CONTEXT ---")

        return "\n".join(lines)
