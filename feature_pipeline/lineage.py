"""OpenLineage event emission helpers.

This is a lightweight integration with the OpenLineage 1.0.x event schema.

Transport options:
- console: print JSON to stdout (no external dependencies)
- http: POST JSON to a Marquez/OpenLineage endpoint using urllib.request

All emissions are best-effort: failures are logged and never raised.
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DatasetRef:
    namespace: str
    name: str
    facets: Optional[dict] = None


def feature_store_dataset(version: str, as_of_date: str) -> DatasetRef:
    return DatasetRef(namespace="feature_store", name=f"features:{version}:{as_of_date}")


def raw_parquet_dataset(filename: str) -> DatasetRef:
    return DatasetRef(namespace="raw_parquet", name=str(filename))


def model_training_dataset(run_id: str, model_name: str) -> DatasetRef:
    return DatasetRef(namespace="model_training", name=f"{model_name}:{run_id}")


class LineageClient:
    def __init__(
        self,
        transport: Literal["http", "console"] = "console",
        endpoint: str | None = None,
        api_key: str | None = None,
        job_namespace: str = "credit-risk-platform",
    ) -> None:
        self.transport = transport
        self.endpoint = endpoint
        self.api_key = api_key
        self.job_namespace = job_namespace

    @staticmethod
    def new_run_id() -> str:
        return str(uuid.uuid4())

    def emit_dataset_event(
        self,
        run_id: str,
        job_name: str,
        inputs: List[DatasetRef],
        outputs: List[DatasetRef],
        event_type: Literal["START", "COMPLETE", "FAIL"],
        run_facets: dict | None = None,
    ) -> None:
        """Emit an OpenLineage run event.

        Schema alignment (OpenLineage 1.0.x):
          eventType, eventTime, run.runId, job.namespace, job.name, inputs[], outputs[]
        """

        try:
            event: Dict[str, Any] = {
                "eventType": str(event_type),
                "eventTime": datetime.now(timezone.utc).isoformat(),
                "run": {"runId": str(run_id)},
                "job": {"namespace": str(self.job_namespace), "name": str(job_name)},
                "inputs": [self._dataset_to_ol(d) for d in inputs],
                "outputs": [self._dataset_to_ol(d) for d in outputs],
            }

            if run_facets:
                event["run"]["facets"] = dict(run_facets)

            self._send(event)
        except Exception as exc:  # noqa: BLE001
            logger.error("OpenLineage emission failed (suppressed): %s", exc)

    def _dataset_to_ol(self, ds: DatasetRef) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "namespace": ds.namespace,
            "name": ds.name,
        }
        if ds.facets:
            payload["facets"] = ds.facets
        return payload

    def _send(self, event: Dict[str, Any]) -> None:
        if self.transport == "console":
            try:
                sys.stdout.write(json.dumps(event, sort_keys=True) + "\n")
                sys.stdout.flush()
            except Exception as exc:  # noqa: BLE001
                logger.error("Console OpenLineage emission failed (suppressed): %s", exc)
            return

        if self.transport != "http":
            logger.warning("Unknown OpenLineage transport '%s'; skipping", self.transport)
            return

        if not self.endpoint:
            logger.warning("OpenLineage http transport requires endpoint; skipping")
            return

        try:
            body = json.dumps(event).encode("utf-8")
            req = urllib.request.Request(
                self.endpoint,
                data=body,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            if self.api_key:
                req.add_header("Authorization", f"Bearer {self.api_key}")

            with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
                _ = resp.read()  # consume
        except (urllib.error.URLError, TimeoutError) as exc:
            logger.error("OpenLineage HTTP emission failed (suppressed): %s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.error("OpenLineage HTTP emission failed (suppressed): %s", exc)
