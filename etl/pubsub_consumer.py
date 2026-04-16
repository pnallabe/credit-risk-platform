"""
etl/pubsub_consumer.py
======================
Long-running Cloud Run service that subscribes to the Pub/Sub subscription
``PUBSUB_SUBSCRIPTION``, transforms messages through bronze/silver/gold layers,
and writes them to BigQuery.

Delivery guarantee
------------------
* Messages are acknowledged **only after** a successful BigQuery write.
* Transient BQ errors trigger exponential backoff before requeueing.
* This provides **at-least-once** delivery; idempotency is enforced by
  BigQuery's deduplication on ``(application_id, tenant_id)``.

Environment variables
---------------------
PUBSUB_SUBSCRIPTION   Full subscription path, e.g.
                      ``projects/my-project/subscriptions/ingestion-events-sub``
BQ_PROJECT            GCP project for BigQuery writes.
BQ_DATASET            BigQuery dataset ID (default: ``credit_risk``).
PULL_BATCH_SIZE       Max messages per pull (default: ``100``).
ENVIRONMENT           ``prod`` | ``dev`` (default: ``dev``).
"""

from __future__ import annotations

import json
import logging
import os
import signal
import time
from typing import Any, Dict, List

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("etl.pubsub_consumer")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PUBSUB_SUBSCRIPTION: str = os.environ.get(
    "PUBSUB_SUBSCRIPTION",
    "projects/YOUR_PROJECT/subscriptions/ingestion-events-sub",
)
BQ_PROJECT: str = os.environ.get("BQ_PROJECT", "YOUR_PROJECT")
BQ_DATASET: str = os.environ.get("BQ_DATASET", "credit_risk")
PULL_BATCH_SIZE: int = int(os.environ.get("PULL_BATCH_SIZE", "100"))

# Backoff settings for transient BQ errors
_BACKOFF_INITIAL_S: float = 1.0
_BACKOFF_MULTIPLIER: float = 2.0
_BACKOFF_MAX_S: float = 60.0

# ---------------------------------------------------------------------------
# Optional GCP imports — fail fast if missing in prod
# ---------------------------------------------------------------------------

try:
    from google.cloud import pubsub_v1
    _PUBSUB_AVAILABLE = True
except ImportError:
    pubsub_v1 = None  # type: ignore[assignment]
    _PUBSUB_AVAILABLE = False
    logger.warning(
        "google-cloud-pubsub not installed — consumer is a no-op. "
        "Install google-cloud-pubsub>=2.21 for production use."
    )

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _decode_message(msg: Any) -> Dict[str, Any]:
    """Decode a Pub/Sub received message into a transformer-compatible dict."""
    try:
        data = json.loads(msg.message.data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning("Failed to decode message data: %s", exc)
        data = {}

    attributes: Dict[str, str] = dict(msg.message.attributes)
    return {
        "data": data,
        "attributes": attributes,
        "message_id": msg.message.message_id,
    }


def _write_with_backoff(
    rows: List[Dict[str, Any]],
    table: str,
) -> int:
    """Write *rows* to *table* with exponential backoff on transient errors."""
    from etl.bq_writer import write_batch  # noqa: PLC0415

    backoff = _BACKOFF_INITIAL_S
    while True:
        try:
            n = write_batch(rows=rows, project=BQ_PROJECT, dataset=BQ_DATASET, table=table)
            return n
        except Exception as exc:
            logger.error("BQ write failed for table %s: %s — retrying in %.1fs", table, exc, backoff)
            time.sleep(backoff)
            backoff = min(backoff * _BACKOFF_MULTIPLIER, _BACKOFF_MAX_S)


# ---------------------------------------------------------------------------
# Main pull loop
# ---------------------------------------------------------------------------

_RUNNING = True


def _handle_shutdown(signum: int, frame: Any) -> None:
    global _RUNNING
    logger.info("Shutdown signal received (%d) — draining current batch...", signum)
    _RUNNING = False


def run() -> None:
    """Pull messages from Pub/Sub and write to BigQuery indefinitely.

    Registers SIGTERM and SIGINT handlers for graceful Cloud Run shutdown.
    """
    from etl.transformer import transform_batch_with_rejects  # noqa: PLC0415

    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    if not _PUBSUB_AVAILABLE:
        logger.error("google-cloud-pubsub not available — exiting.")
        return

    subscriber = pubsub_v1.SubscriberClient()
    logger.info(
        "Starting ETL consumer: subscription=%s bq=%s.%s batch_size=%d",
        PUBSUB_SUBSCRIPTION,
        BQ_PROJECT,
        BQ_DATASET,
        PULL_BATCH_SIZE,
    )

    while _RUNNING:
        try:
            response = subscriber.pull(
                request={
                    "subscription": PUBSUB_SUBSCRIPTION,
                    "max_messages": PULL_BATCH_SIZE,
                }
            )
        except Exception as exc:
            logger.error("Pub/Sub pull failed: %s — sleeping 5s", exc)
            time.sleep(5)
            continue

        received = response.received_messages
        if not received:
            logger.debug("No messages in pull response — sleeping 1s")
            time.sleep(1)
            continue

        logger.info("Pulled %d messages", len(received))
        decoded = [_decode_message(m) for m in received]
        ack_ids = [m.ack_id for m in received]

        # Transform
        bronze_rows, valid_silver, rejected_silver, _gold = transform_batch_with_rejects(decoded)

        # Write bronze
        bronze_ok = _write_with_backoff(bronze_rows, "loan_applications_bronze")
        logger.info("Wrote %d bronze rows", bronze_ok)

        # Write valid silver
        if valid_silver:
            silver_ok = _write_with_backoff(valid_silver, "loan_applications_silver")
            logger.info("Wrote %d silver rows", silver_ok)

        # Write rejected silver to side table
        if rejected_silver:
            # Add rejection_reason before writing
            rej_ok = _write_with_backoff(rejected_silver, "loan_applications_silver_rejected")
            logger.info("Wrote %d rejected silver rows", rej_ok)

        # Acknowledge only after successful BQ write
        subscriber.acknowledge(
            request={
                "subscription": PUBSUB_SUBSCRIPTION,
                "ack_ids": ack_ids,
            }
        )
        logger.info("Acknowledged %d messages", len(ack_ids))

    logger.info("ETL consumer shut down gracefully.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run()
