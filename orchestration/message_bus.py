"""
Agent Communication Protocol & Message Bus
===========================================
Defines the typed message contract between agents and provides:
  - In-process message bus (synchronous, for single-service deployments)
  - Kafka-compatible message envelope (for distributed deployments)
  - File-based contract for batch/offline pipelines

Agents communicate exclusively through AgentMessage objects.
No agent should read another agent's internal state directly.

Message flow:
  DataIngestionAgent   → TOPIC: ingestion.validated
  FeatureAgent         → TOPIC: features.computed
  ModelingAgent        → TOPIC: models.scored
  DecisionAgent        → TOPIC: decisions.made
  ExplainabilityAgent  → TOPIC: explanations.generated
  MonitoringAgent      → TOPIC: monitoring.alerts
"""

from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Message envelope
# ---------------------------------------------------------------------------


@dataclass
class AgentMessage:
    """
    Universal message envelope passed between agents.
    Compatible with Kafka / Pub/Sub serialisation via to_json().
    """

    topic: str                        # e.g. "features.computed"
    source_agent: str                 # agent that produced this message
    run_id: str
    payload: Dict[str, Any]
    schema_version: str = "1.0"
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    correlation_id: Optional[str] = None  # tie back to original request ID

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> "AgentMessage":
        return cls(**json.loads(raw))


# ---------------------------------------------------------------------------
# Topic constants
# ---------------------------------------------------------------------------


class Topics:
    INGESTION_VALIDATED = "ingestion.validated"
    FEATURES_COMPUTED = "features.computed"
    MODELS_SCORED = "models.scored"
    DECISIONS_MADE = "decisions.made"
    EXPLANATIONS_GENERATED = "explanations.generated"
    MONITORING_ALERTS = "monitoring.alerts"
    EXPERIMENT_RESULTS = "experiment.results"


# ---------------------------------------------------------------------------
# In-process message bus (synchronous, no network needed)
# ---------------------------------------------------------------------------


class InProcessMessageBus:
    """
    Simple in-process pub/sub bus for single-service deployments.
    Suitable for online scoring where agents run in the same process.

    For distributed (microservice) deployments, replace with KafkaMessageBus.
    """

    def __init__(self):
        self._subscribers: Dict[str, List[Callable[[AgentMessage], None]]] = defaultdict(list)
        self._message_log: List[AgentMessage] = []

    def subscribe(self, topic: str, handler: Callable[[AgentMessage], None]) -> None:
        self._subscribers[topic].append(handler)
        logger.debug("Subscribed handler to topic '%s'", topic)

    def publish(self, message: AgentMessage) -> None:
        self._message_log.append(message)
        handlers = self._subscribers.get(message.topic, [])
        logger.debug(
            "Publishing to '%s': %d subscriber(s)", message.topic, len(handlers)
        )
        for handler in handlers:
            try:
                handler(message)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Handler error on topic '%s': %s", message.topic, exc
                )

    def get_messages(self, topic: Optional[str] = None) -> List[AgentMessage]:
        if topic:
            return [m for m in self._message_log if m.topic == topic]
        return list(self._message_log)

    def replay(self, topic: str) -> Optional[AgentMessage]:
        """Return the most recent message for a topic (for resume/recovery)."""
        messages = self.get_messages(topic)
        return messages[-1] if messages else None


# ---------------------------------------------------------------------------
# File-based contract (for batch / offline pipelines)
# ---------------------------------------------------------------------------


class FileContractBus:
    """
    Writes agent outputs to structured JSON files.
    Useful for batch pipelines where agents run as separate processes / jobs.
    """

    def __init__(self, base_dir: str = "/tmp/credit_risk_contracts"):
        self._base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)

    def write(self, message: AgentMessage) -> str:
        """Persist message to <base_dir>/<topic>/<run_id>.json"""
        topic_dir = os.path.join(self._base_dir, message.topic.replace(".", "/"))
        os.makedirs(topic_dir, exist_ok=True)
        path = os.path.join(topic_dir, f"{message.run_id}.json")
        with open(path, "w") as f:
            f.write(message.to_json())
        logger.info("Written contract: %s", path)
        return path

    def read(self, topic: str, run_id: str) -> Optional[AgentMessage]:
        path = os.path.join(self._base_dir, topic.replace(".", "/"), f"{run_id}.json")
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return AgentMessage.from_json(f.read())


# ---------------------------------------------------------------------------
# Kafka-compatible envelope builder (serialisation only — no KafkaProducer dep)
# ---------------------------------------------------------------------------


def build_kafka_message(
    topic: str,
    source_agent: str,
    run_id: str,
    payload: Dict[str, Any],
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Returns a Kafka-compatible dict for use with confluent-kafka or aiokafka.

    Usage:
        producer.produce(
            topic=msg["topic"],
            key=msg["key"],
            value=json.dumps(msg["value"]).encode(),
        )
    """
    msg = AgentMessage(
        topic=topic,
        source_agent=source_agent,
        run_id=run_id,
        payload=payload,
        correlation_id=correlation_id,
    )
    return {
        "topic": topic,
        "key": run_id,
        "value": asdict(msg),
        "timestamp_ms": int(datetime.utcnow().timestamp() * 1000),
    }
