"""
synonym_mapper.py — SynonymMapper

Deterministic, case-insensitive synonym resolution. Maps colloquial terms
(e.g. "bad debt rate", "FICO", "charge off") to canonical names
(e.g. "Loan.charge_off_rate", "Customer.fico_score") without an LLM call.

Matching strategy (applied in order):
  1. Exact match (lowercased)
  2. Substring match — the longest synonym that appears inside the query wins
  3. Word-level Jaccard similarity ≥ 0.5 as a fuzzy fallback
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from analytics_api.src.semantic.loader import SemanticLayerLoader, get_loader

logger = logging.getLogger(__name__)

_TOKENIZE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set:
    return set(_TOKENIZE.findall(text.lower()))


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class SynonymMapper:
    """Resolve terms to canonical semantic names.

    Example::

        mapper = SynonymMapper()
        mapper.resolve("bad debt rate")        # → "Loan.charge_off_rate"
        mapper.resolve("FICO")                 # → "Customer.fico_score"
        mapper.resolve_all("charge off rate for personal loans")
        # → {"charge off rate": "Loan.charge_off_rate"}
    """

    JACCARD_THRESHOLD = 0.50

    def __init__(self, loader: Optional[SemanticLayerLoader] = None) -> None:
        self._loader = loader or get_loader()
        self._index: Dict[str, str] = {}       # lower-term → canonical
        self._token_index: Dict[str, set] = {} # canonical → token set
        self._built = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, term: str) -> Optional[str]:
        """Resolve a single term to its canonical name, or None if no match."""
        self._ensure_built()
        key = term.lower().strip()

        # 1. Exact match
        if key in self._index:
            return self._index[key]

        # 2. Substring match: find the longest synonym contained in the term
        best_len, best_canonical = 0, None
        for syn, canonical in self._index.items():
            if syn in key and len(syn) > best_len:
                best_len = len(syn)
                best_canonical = canonical
        if best_canonical:
            return best_canonical

        # 3. Jaccard fuzzy fallback
        key_tokens = _tokens(key)
        best_score, best_fuzzy = 0.0, None
        for canonical, canon_tokens in self._token_index.items():
            score = _jaccard(key_tokens, canon_tokens)
            if score > best_score and score >= self.JACCARD_THRESHOLD:
                best_score = score
                best_fuzzy = canonical
        if best_fuzzy:
            logger.debug("SynonymMapper fuzzy: '%s' → '%s' (score=%.2f)", term, best_fuzzy, best_score)
            return best_fuzzy

        return None

    def resolve_all(self, text: str) -> Dict[str, str]:
        """Scan free text and return all matched {term → canonical} pairs found."""
        self._ensure_built()
        text_lower = text.lower()
        results: Dict[str, str] = {}
        # Check all known synonyms as substrings, pick non-overlapping longest first
        matches = []
        for syn, canonical in self._index.items():
            idx = text_lower.find(syn)
            if idx != -1:
                matches.append((len(syn), syn, canonical, idx))
        # Sort by length descending to prefer longer matches
        matches.sort(reverse=True)
        covered: set[int] = set()
        for length, syn, canonical, start in matches:
            positions = set(range(start, start + length))
            if not positions & covered:
                results[syn] = canonical
                covered.update(positions)
        return results

    def add_synonym(self, term: str, canonical: str) -> None:
        """Register a runtime synonym mapping."""
        self._ensure_built()
        self._index[term.lower().strip()] = canonical
        self._token_index[canonical] = _tokens(canonical)

    def get_synonyms(self, canonical: str) -> List[str]:
        """Return all registered synonyms for a canonical name."""
        self._ensure_built()
        return [term for term, can in self._index.items() if can == canonical]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ensure_built(self) -> None:
        if not self._built:
            raw = self._loader.get_synonyms()
            for term, canonical in raw.items():
                self._index[term] = canonical
                self._token_index[canonical] = _tokens(canonical)
            self._built = True
            logger.debug("SynonymMapper: indexed %d terms", len(self._index))
