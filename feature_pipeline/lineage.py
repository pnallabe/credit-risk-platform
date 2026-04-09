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
import os
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
        store: "LineageStore | None" = None,
    ) -> None:
        self.transport = transport
        self.endpoint = endpoint
        self.api_key = api_key
        self.job_namespace = job_namespace
        self._store = store

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

            # Persist to lineage store if configured (opt-in, zero impact on callers)
            if self._store is not None:
                try:
                    self._store.record(
                        run_id=str(run_id),
                        job_namespace=self.job_namespace,
                        job_name=str(job_name),
                        event_type=str(event_type),
                        event_time=event["eventTime"],
                        inputs=[asdict(d) if not isinstance(d, dict) else d for d in inputs],
                        outputs=[asdict(d) if not isinstance(d, dict) else d for d in outputs],
                        run_facets=run_facets,
                    )
                except Exception as _store_exc:
                    logger.warning("LineageStore.record failed (suppressed): %s", _store_exc)

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


# ---------------------------------------------------------------------------
# LineageStore — SQLite-backed persistent store for OpenLineage events (G8-A)
# ---------------------------------------------------------------------------


class LineageStore:
    """SQLite-backed store for OpenLineage events.

    Persists every event emitted by :class:`LineageClient` so they can be
    queried by run_id, job name, or dataset namespace after the fact.

    Schema
    ------
    Table ``lineage_events``:
      id            INTEGER PRIMARY KEY AUTOINCREMENT
      run_id        TEXT NOT NULL
      job_namespace TEXT NOT NULL
      job_name      TEXT NOT NULL
      event_type    TEXT NOT NULL          -- START / COMPLETE / FAIL
      event_time    TEXT NOT NULL          -- ISO-8601 UTC
      inputs_json   TEXT NOT NULL          -- JSON array of DatasetRef dicts
      outputs_json  TEXT NOT NULL          -- JSON array of DatasetRef dicts
      run_facets_json TEXT                 -- optional JSON
      created_at    TEXT NOT NULL          -- insert time ISO-8601 UTC
    """

    _CREATE_TABLE = """
        CREATE TABLE IF NOT EXISTS lineage_events (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id           TEXT    NOT NULL,
            job_namespace    TEXT    NOT NULL,
            job_name         TEXT    NOT NULL,
            event_type       TEXT    NOT NULL,
            event_time       TEXT    NOT NULL,
            inputs_json      TEXT    NOT NULL DEFAULT '[]',
            outputs_json     TEXT    NOT NULL DEFAULT '[]',
            run_facets_json  TEXT,
            created_at       TEXT    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_lineage_run_id
            ON lineage_events (run_id);
        CREATE INDEX IF NOT EXISTS ix_lineage_job_name
            ON lineage_events (job_name);
    """

    def __init__(self, db_path: str = "./feature_pipeline/lineage.db") -> None:
        """Initialise the SQLite lineage store.

        Parameters
        ----------
        db_path:
            Filesystem path to the SQLite database file. Will be created if it
            does not already exist.
        """
        import sqlite3  # stdlib
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.executescript(self._CREATE_TABLE)
        self._conn.commit()

    def record(
        self,
        run_id: str,
        job_namespace: str,
        job_name: str,
        event_type: str,
        event_time: str,
        inputs: List[Dict[str, Any]],
        outputs: List[Dict[str, Any]],
        run_facets: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Persist one OpenLineage run event to the SQLite store.

        Parameters
        ----------
        run_id:
            OpenLineage run UUID.
        job_namespace:
            Job namespace (e.g. ``"credit-risk-platform"``).
        job_name:
            Job name (e.g. ``"feature_engineering"``).
        event_type:
            One of ``"START"``, ``"COMPLETE"``, ``"FAIL"``.
        event_time:
            ISO-8601 UTC timestamp of the event.
        inputs:
            List of input dataset dicts.
        outputs:
            List of output dataset dicts.
        run_facets:
            Optional dict of additional run facets.
        """
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """INSERT INTO lineage_events
               (run_id, job_namespace, job_name, event_type, event_time,
                inputs_json, outputs_json, run_facets_json, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                run_id, job_namespace, job_name, event_type, event_time,
                json.dumps(inputs), json.dumps(outputs),
                json.dumps(run_facets) if run_facets else None,
                now,
            ),
        )
        self._conn.commit()

    def get_by_run_id(self, run_id: str) -> List[Dict[str, Any]]:
        """Return all events for *run_id*, ordered by event_time ASC.

        Parameters
        ----------
        run_id:
            The run UUID to query.

        Returns
        -------
        list[dict]
            Each dict has keys: id, run_id, job_namespace, job_name, event_type,
            event_time, inputs, outputs, run_facets, created_at.
        """
        cur = self._conn.execute(
            "SELECT id,run_id,job_namespace,job_name,event_type,event_time,"
            "inputs_json,outputs_json,run_facets_json,created_at "
            "FROM lineage_events WHERE run_id = ? ORDER BY event_time ASC",
            (run_id,),
        )
        col_names = [d[0] for d in cur.description]
        result = []
        for row in cur.fetchall():
            rec = dict(zip(col_names, row))
            rec["inputs"]  = json.loads(rec.pop("inputs_json"))
            rec["outputs"] = json.loads(rec.pop("outputs_json"))
            rf = rec.pop("run_facets_json")
            rec["run_facets"] = json.loads(rf) if rf else {}
            result.append(rec)
        return result

    def get_by_job(self, job_name: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Return the most recent *limit* events for *job_name*.

        Parameters
        ----------
        job_name:
            The job name to filter by.
        limit:
            Maximum number of events to return (default 100).

        Returns
        -------
        list[dict]
            Same structure as :meth:`get_by_run_id`.
        """
        cur = self._conn.execute(
            "SELECT id,run_id,job_namespace,job_name,event_type,event_time,"
            "inputs_json,outputs_json,run_facets_json,created_at "
            "FROM lineage_events WHERE job_name = ? ORDER BY event_time DESC LIMIT ?",
            (job_name, limit),
        )
        col_names = [d[0] for d in cur.description]
        result = []
        for row in cur.fetchall():
            rec = dict(zip(col_names, row))
            rec["inputs"]  = json.loads(rec.pop("inputs_json"))
            rec["outputs"] = json.loads(rec.pop("outputs_json"))
            rf = rec.pop("run_facets_json")
            rec["run_facets"] = json.loads(rf) if rf else {}
            result.append(rec)
        return result

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()


# ---------------------------------------------------------------------------
# Module-level default store (opt-in via LINEAGE_STORE_PATH env var)
# ---------------------------------------------------------------------------

DEFAULT_LINEAGE_STORE: Optional[LineageStore] = (
    LineageStore(os.environ["LINEAGE_STORE_PATH"])
    if "LINEAGE_STORE_PATH" in os.environ
    else None
)


# ---------------------------------------------------------------------------
# Convenience function kept for backwards compatibility
# ---------------------------------------------------------------------------

def emit_dataset_event(
    run_id: str,
    job_name: str,
    inputs: List[DatasetRef],
    outputs: List[DatasetRef],
    event_type: Literal["START", "COMPLETE", "FAIL"] = "COMPLETE",
    run_facets: Optional[Dict[str, Any]] = None,
    *,
    client: Optional[LineageClient] = None,
) -> None:
    """Module-level convenience wrapper for :class:`LineageClient`.

    Creates a transient console-mode client if *client* is not supplied.
    """
    c = client or LineageClient(store=DEFAULT_LINEAGE_STORE)
    c.emit_dataset_event(
        run_id=run_id,
        job_name=job_name,
        inputs=inputs,
        outputs=outputs,
        event_type=event_type,
        run_facets=run_facets,
    )
