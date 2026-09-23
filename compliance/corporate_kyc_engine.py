from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx

logger = logging.getLogger(__name__)


@dataclass
class BeneficialOwner:
    name: str
    is_natural_person: bool
    effective_ownership_pct: float
    requires_cdd_verification: bool  # True if ownership >= 25.0%


@dataclass
class UBOTraversalResult:
    target_entity: str
    ultimate_beneficial_owners: List[BeneficialOwner]
    max_ownership_chain_depth: int
    cdd_compliance_pass: bool


class UBOGraphTraversalEngine:
    """NetworkX directed graph traversal engine for multi-tier Ultimate Beneficial Ownership (UBO) resolution.

    FinCEN CDD Rule (31 CFR 1010.230):
    Requires covered financial institutions to identify and verify the identity of the
    natural person beneficial owners who own >= 25% equity interest in a legal entity customer.
    """

    def __init__(self, ubo_threshold_pct: float = 25.0) -> None:
        self.ubo_threshold_pct = ubo_threshold_pct
        self.graph = nx.DiGraph()

    def add_ownership_stake(
        self,
        owner_name: str,
        entity_name: str,
        ownership_pct: float,
        is_natural_person: bool = False,
    ) -> None:
        """Add directed equity ownership edge: owner -> entity."""
        self.graph.add_edge(
            owner_name,
            entity_name,
            ownership_pct=float(ownership_pct),
            is_natural_person=is_natural_person,
        )

    def resolve_ubos(self, target_entity: str) -> UBOTraversalResult:
        """Traverse ownership graph upstream to compute cumulative effective ownership of natural persons."""
        if target_entity not in self.graph:
            return UBOTraversalResult(target_entity, [], 0, True)

        effective_ownership: Dict[str, float] = {}
        max_depth = 0

        # Traverse all simple paths ending at target_entity
        for node in self.graph.nodes():
            if node == target_entity:
                continue

            if self.graph.nodes[node].get("is_natural_person", False) or not list(self.graph.predecessors(node)):
                # Node is an ultimate root owner
                try:
                    paths = list(nx.all_simple_paths(self.graph, source=node, target=target_entity))
                except Exception:
                    paths = []

                for path in paths:
                    max_depth = max(max_depth, len(path) - 1)
                    # Multiply ownership fractions along the path
                    path_pct = 1.0
                    for i in range(len(path) - 1):
                        u, v = path[i], path[i + 1]
                        edge_pct = self.graph[u][v]["ownership_pct"] / 100.0
                        path_pct *= edge_pct

                    is_nat = self.graph.nodes[node].get("is_natural_person", True)
                    effective_ownership[node] = effective_ownership.get(node, 0.0) + (path_pct * 100.0)

        ubos: List[BeneficialOwner] = []
        for owner, pct in effective_ownership.items():
            is_nat = self.graph.nodes[owner].get("is_natural_person", True)
            req_cdd = pct >= self.ubo_threshold_pct and is_nat
            ubos.append(
                BeneficialOwner(
                    name=owner,
                    is_natural_person=is_nat,
                    effective_ownership_pct=round(pct, 2),
                    requires_cdd_verification=req_cdd,
                )
            )

        cdd_pass = len(ubos) > 0

        return UBOTraversalResult(
            target_entity=target_entity,
            ultimate_beneficial_owners=ubos,
            max_ownership_chain_depth=max_depth,
            cdd_compliance_pass=cdd_pass,
        )


@dataclass
class SanctionsMatchResult:
    query_name: str
    matched_sdn_name: str
    match_score: float  # 0.0 to 1.0
    match_found: bool
    list_source: str  # e.g. "OFAC_SDN", "PEP_REGISTRY"


def _jaro_winkler_similarity(s1: str, s2: str) -> float:
    """Calculate Jaro-Winkler string similarity between two names."""
    s1, s2 = s1.lower().strip(), s2.lower().strip()
    if s1 == s2:
        return 1.0
    if not s1 or not s2:
        return 0.0

    len1, len2 = len(s1), len(s2)
    match_distance = max(len1, len2) // 2 - 1
    if match_distance < 0:
        match_distance = 0

    s1_matches = [False] * len1
    s2_matches = [False] * len2

    matches = 0
    transpositions = 0

    for i in range(len1):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, len2)
        for j in range(start, end):
            if s2_matches[j]:
                continue
            if s1[i] == s2[j]:
                s1_matches[i] = True
                s2_matches[j] = True
                matches += 1
                break

    if matches == 0:
        return 0.0

    k = 0
    for i in range(len1):
        if not s1_matches[i]:
            continue
        while not s2_matches[k]:
            k += 1
        if s1[i] != s2[k]:
            transpositions += 1
        k += 1

    jaro = (matches / len1 + matches / len2 + (matches - transpositions / 2.0) / matches) / 3.0

    # Winkler prefix scale adjustment (up to 4 matching prefix characters)
    prefix = 0
    for i in range(min(4, min(len1, len2))):
        if s1[i] == s2[i]:
            prefix += 1
        else:
            break

    return jaro + prefix * 0.1 * (1.0 - jaro)


class FuzzySanctionsScreener:
    """Fuzzy sanctions and PEP screening engine using Jaro-Winkler distance algorithms."""

    def __init__(self, match_threshold: float = 0.85) -> None:
        self.match_threshold = match_threshold
        # Mock OFAC SDN / PEP reference list
        self.sdn_registry = [
            "VLADIMIR PETROV",
            "SERGEI IVANOV",
            "ALEXANDER SMIRNOV",
            "GLOBAL TRADING CORP S.A.",
            "CARIBBEAN VENTURES LTD",
        ]

    def screen_name(self, query_name: str) -> SanctionsMatchResult:
        """Screen query name against sanctions list using Jaro-Winkler similarity."""
        best_match_name = ""
        best_score = 0.0

        for sdn in self.sdn_registry:
            score = _jaro_winkler_similarity(query_name, sdn)
            if score > best_score:
                best_score = score
                best_match_name = sdn

        match_found = best_score >= self.match_threshold

        return SanctionsMatchResult(
            query_name=query_name,
            matched_sdn_name=best_match_name if match_found else "",
            match_score=round(best_score, 4),
            match_found=match_found,
            list_source="OFAC_SDN" if match_found else "NONE",
        )


@dataclass
class AdverseMediaResult:
    headline: str
    risk_category: str  # "MONEY_LAUNDERING", "FRAUD", "BRIBERY", "SANCTIONS_VIOLATION", "CLEAN"
    adverse_sentiment_score: float
    flagged: bool


class AdverseMediaNLPClassifier:
    """Adverse media NLP sentiment and financial crime risk classifier."""

    CRIME_KEYWORDS: Dict[str, List[str]] = {
        "MONEY_LAUNDERING": ["money laundering", "laundering", "shell company", "illicit funds"],
        "FRAUD": ["fraud", "embezzlement", "ponzi", "accounting scandal", "indicted"],
        "BRIBERY": ["bribery", "corrupt", "kickback", "fcpa violation"],
        "SANCTIONS_VIOLATION": ["sanction violation", "ofac fine", "evading sanctions"],
    }

    def classify_headline(self, headline: str) -> AdverseMediaResult:
        """Classify media headline for financial crime risk."""
        text_lower = headline.lower()
        detected_cat = "CLEAN"
        score = 0.0

        for cat, keywords in self.CRIME_KEYWORDS.items():
            for kw in keywords:
                if kw in text_lower:
                    detected_cat = cat
                    score = 0.85
                    break
            if detected_cat != "CLEAN":
                break

        return AdverseMediaResult(
            headline=headline,
            risk_category=detected_cat,
            adverse_sentiment_score=score,
            flagged=detected_cat != "CLEAN",
        )
