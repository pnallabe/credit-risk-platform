from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class TransactionEvent:
    transaction_id: str
    sender_account_id: str
    recipient_account_id: str
    amount: float
    timestamp: float  # POSIX timestamp
    device_id: Optional[str] = None
    ip_address: Optional[str] = None
    channel: str = "P2P"


@dataclass
class FraudScoreResult:
    transaction_id: str
    fraud_score: float  # 0.0 to 1.0
    action: str  # "ALLOW", "REVIEW", "REJECT"
    velocity_1m_count: int
    velocity_5m_count: int
    velocity_1h_count: int
    app_scam_flag: bool
    mule_cluster_flag: bool
    reason_codes: List[str]
    latency_ms: float
    evaluated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class StreamFraudEngine:
    """Sub-50ms sliding window real-time fraud & APP (Authorized Push Payment) prevention engine."""

    def __init__(
        self,
        reject_threshold: float = 0.65,
        review_threshold: float = 0.35,
        window_1h_sec: int = 3600,
    ) -> None:
        self.reject_threshold = reject_threshold
        self.review_threshold = review_threshold
        self.window_1h_sec = window_1h_sec

        # Account sliding window state: account_id -> deque of (timestamp, amount, recipient_id, device_id)
        self._account_history: Dict[str, deque] = defaultdict(deque)

    def evaluate_transaction(self, event: TransactionEvent) -> FraudScoreResult:
        """Evaluate incoming streaming transaction event against sliding window velocity rules."""
        t_start = time.monotonic()
        sender = event.sender_account_id
        now = event.timestamp

        # Clean history older than 1 hour
        history = self._account_history[sender]
        while history and (now - history[0][0]) > self.window_1h_sec:
            history.popleft()

        # Compute sliding window velocity counts
        count_1m = sum(1 for item in history if (now - item[0]) <= 60)
        count_5m = sum(1 for item in history if (now - item[0]) <= 300)
        count_1h = len(history)

        # APP Scam heuristic: Rapid multi-recipient fan-out within 5 minutes
        recipients_5m = {item[2] for item in history if (now - item[0]) <= 300}
        recipients_5m.add(event.recipient_account_id)
        app_scam = len(recipients_5m) >= 4 or (count_1m >= 3 and event.amount >= 2000.0)

        # Calculate fraud score component weights
        base_score = 0.05
        reasons = []

        if count_1m >= 4:
            base_score += 0.35
            reasons.append("HIGH_VELOCITY_1M")
        elif count_5m >= 8:
            base_score += 0.25
            reasons.append("HIGH_VELOCITY_5M")

        if app_scam:
            base_score += 0.40
            reasons.append("APP_PUSH_PAYMENT_SCAM_PATTERN")

        if event.amount >= 10000.0:
            base_score += 0.20
            reasons.append("HIGH_VALUE_TRANSFER")

        # Record event in sender history
        history.append((event.timestamp, event.amount, event.recipient_account_id, event.device_id))

        final_score = float(np.clip(base_score, 0.0, 1.0))
        if final_score >= self.reject_threshold:
            action = "REJECT"
        elif final_score >= self.review_threshold:
            action = "REVIEW"
        else:
            action = "ALLOW"

        t_end = time.monotonic()
        latency_ms = round((t_end - t_start) * 1000.0, 3)

        return FraudScoreResult(
            transaction_id=event.transaction_id,
            fraud_score=round(final_score, 4),
            action=action,
            velocity_1m_count=count_1m + 1,
            velocity_5m_count=count_5m + 1,
            velocity_1h_count=count_1h + 1,
            app_scam_flag=app_scam,
            mule_cluster_flag=False,
            reason_codes=reasons,
            latency_ms=latency_ms,
        )


@dataclass
class MuleClusterDetectionResult:
    mule_account_ids: List[str]
    circular_loops_detected: List[List[str]]
    high_degree_hubs: List[str]
    total_suspicious_volume: float


class MuleNetworkAnalyzer:
    """NetworkX directed graph analyzer detecting mule account clusters and money laundering loops."""

    def __init__(self) -> None:
        self.graph = nx.DiGraph()

    def add_transfer(self, sender_id: str, recipient_id: str, amount: float) -> None:
        """Add transfer edge to network graph."""
        if self.graph.has_edge(sender_id, recipient_id):
            self.graph[sender_id][recipient_id]["weight"] += amount
            self.graph[sender_id][recipient_id]["count"] += 1
        else:
            self.graph.add_edge(sender_id, recipient_id, weight=amount, count=1)

    def detect_mule_clusters(self, min_in_degree: int = 3, max_hold_time_hours: float = 2.0) -> MuleClusterDetectionResult:
        """Identify high-in-degree mule hubs and circular laundering cycles."""
        mule_accounts: List[str] = []
        high_degree_hubs: List[str] = []

        for node in self.graph.nodes():
            in_deg = self.graph.in_degree(node)
            out_deg = self.graph.out_degree(node)
            if in_deg >= min_in_degree and out_deg >= 1:
                mule_accounts.append(node)
                high_degree_hubs.append(node)

        # Detect simple circular cycles (A -> B -> C -> A)
        try:
            cycles = list(nx.simple_cycles(self.graph))
            laundering_loops = [c for c in cycles if 3 <= len(c) <= 6]
        except Exception:
            laundering_loops = []

        total_vol = sum(d["weight"] for u, v, d in self.graph.edges(data=True))

        return MuleClusterDetectionResult(
            mule_account_ids=sorted(list(set(mule_accounts))),
            circular_loops_detected=laundering_loops,
            high_degree_hubs=high_degree_hubs,
            total_suspicious_volume=round(total_vol, 2),
        )
