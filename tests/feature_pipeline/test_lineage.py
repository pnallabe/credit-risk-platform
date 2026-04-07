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
