from __future__ import annotations

import json
from typing import Any

import urllib.request

from feature_pipeline.lineage import DatasetRef, LineageClient


def test_dataset_ref_has_namespace_and_name() -> None:
    ds = DatasetRef(namespace="ns", name="name")
    assert ds.namespace == "ns"
    assert ds.name == "name"


def test_console_transport_emits_json(capsys) -> None:
    client = LineageClient(transport="console")
    client.emit_dataset_event(
        run_id="run-123",
        job_name="job",
        inputs=[DatasetRef(namespace="in", name="a")],
        outputs=[DatasetRef(namespace="out", name="b")],
        event_type="COMPLETE",
        run_facets={"rowCount": 10},
    )

    out = capsys.readouterr().out.strip().splitlines()
    assert out
    payload = json.loads(out[-1])
    assert payload["eventType"] == "COMPLETE"
    assert payload["run"]["runId"] == "run-123"
    assert payload["inputs"][0]["name"] == "a"
    assert payload["outputs"][0]["name"] == "b"


def test_http_transport_posts_correct_payload(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(req: urllib.request.Request, timeout: int = 0):  # type: ignore[override]
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        body = req.data or b""
        captured["body"] = json.loads(body.decode("utf-8"))

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"ok"

        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    client = LineageClient(transport="http", endpoint="http://example.test/api")
    client.emit_dataset_event(
        run_id="run-456",
        job_name="job2",
        inputs=[DatasetRef(namespace="in", name="x")],
        outputs=[DatasetRef(namespace="out", name="y")],
        event_type="START",
    )

    assert captured["url"] == "http://example.test/api"
    assert captured["method"] == "POST"
    assert captured["body"]["eventType"] == "START"
    assert captured["body"]["inputs"][0]["name"] == "x"
    assert captured["body"]["outputs"][0]["name"] == "y"


# ---------------------------------------------------------------------------
# factory helpers
# ---------------------------------------------------------------------------

def test_raw_parquet_dataset():
    from feature_pipeline.lineage import raw_parquet_dataset
    ds = raw_parquet_dataset("raw_data.parquet")
    assert ds.namespace == "raw_parquet"
    assert "raw_data.parquet" in ds.name


def test_model_training_dataset():
    from feature_pipeline.lineage import model_training_dataset
    ds = model_training_dataset(run_id="run-1", model_name="lgd_v2")
    assert ds.namespace == "model_training"
    assert "lgd_v2" in ds.name


def test_feature_store_dataset():
    from feature_pipeline.lineage import feature_store_dataset
    ds = feature_store_dataset(version="v3", as_of_date="2024-01-01")
    assert ds.namespace == "feature_store"
    assert "v3" in ds.name
    assert "2024-01-01" in ds.name


def test_dataset_ref_with_facets():
    ds = DatasetRef(namespace="ns", name="n", facets={"schemaFields": []})
    assert ds.facets is not None


def test_unknown_transport_is_noop(capsys):
    client = LineageClient(transport="grpc")  # unknown transport
    client.emit_dataset_event(
        run_id="run-x", job_name="j",
        inputs=[], outputs=[], event_type="COMPLETE",
    )
    # Should not raise — just log a warning and return


def test_http_transport_no_endpoint_is_noop():
    client = LineageClient(transport="http", endpoint=None)
    client.emit_dataset_event(
        run_id="run-y", job_name="j",
        inputs=[], outputs=[], event_type="COMPLETE",
    )
    # No exception


def test_http_transport_with_api_key(monkeypatch):
    import urllib.request
    headers_seen = {}

    def fake_urlopen(req, timeout=0):
        headers_seen.update(dict(req.headers))
        class _R:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b""
        return _R()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    client = LineageClient(transport="http", endpoint="http://example.test/api", api_key="secret")
    client.emit_dataset_event(
        run_id="run-z", job_name="j",
        inputs=[], outputs=[], event_type="COMPLETE",
    )
    assert "Authorization" in headers_seen


def test_emit_with_lineage_store(capsys):
    from feature_pipeline.lineage import LineageStore
    import tempfile, os
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "lineage.db")
        store = LineageStore(db_path=db_path)
        client = LineageClient(transport="console", store=store)
        client.emit_dataset_event(
            run_id="run-store", job_name="job-store",
            inputs=[DatasetRef(namespace="in", name="a")],
            outputs=[DatasetRef(namespace="out", name="b")],
            event_type="COMPLETE",
        )
        # Should have written to store
        events = store.get_by_run_id("run-store")
        assert len(events) >= 1
