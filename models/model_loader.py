"""
Centralised Model Loader
========================
Eliminates per-request disk I/O by maintaining a process-level model cache.

Motivation (P1.4)
-----------------
Before this module, ``predict_pd()`` and ``predict_fraud()`` both called
``joblib.load(path)`` on every request.  For a service handling hundreds of
real-time decisions per second that is unacceptable: disk I/O dominates
p95 latency and can stall the async event loop when the threadpool is busy.

Design
------
* ``_MODEL_CACHE`` — module-level dict keyed by ``(resolved_path, version)``
  so the same artefact under different aliases is loaded only once.
* Thread-safe via ``threading.Lock`` (safe to use from asyncio contexts because
  the heavy joblib.load is always offloaded to a thread-pool executor by
  callers that need async safety).
* ``load_model(path, version)`` — blocking load, for use at startup / agent init.
* ``get_or_load(path, version)`` — returns cached model if present, else loads.
* ``preload(paths_and_versions)`` — convenience batch loader for startup.

Usage
-----
    from models.model_loader import get_or_load

    # Called once at agent init — subsequent calls are O(1) dict lookups
    model = get_or_load("/app/models/credit_risk/risk_model_v1.pkl", version="v1")
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import joblib  # promoted to module-level so tests can patch models.model_loader.joblib

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Process-level cache
# ---------------------------------------------------------------------------
_MODEL_CACHE: Dict[Tuple[str, str], Any] = {}
_CACHE_LOCK = threading.Lock()


def _resolve_path(path: Optional[str | Path]) -> str:
    """Return a canonical absolute path string for use as the cache key."""
    if path is None:
        return ""
    return str(Path(path).resolve())


def is_loaded(path: Optional[str | Path], version: str = "unknown") -> bool:
    """Return True if the model at *path* with *version* is already cached."""
    key = (_resolve_path(path), version)
    return key in _MODEL_CACHE


def load_model(
    path: str | Path,
    version: str = "unknown",
    *,
    force_reload: bool = False,
) -> Any:
    """
    Load a joblib-serialised model from *path* and cache it.

    Parameters
    ----------
    path:
        Filesystem path to the ``.pkl`` / ``.joblib`` artefact.
    version:
        Human-readable version tag (e.g. ``"v1"``, ``"champion"``).
        Combined with the resolved path to form the cache key so that
        the same file path with a different version string is treated
        as distinct (useful during champion/challenger promotions).
    force_reload:
        If True, load from disk even if already cached.  Useful after an
        in-place model refresh without a process restart.

    Returns
    -------
    Any
        The deserialised model object (usually a scikit-learn / LightGBM estimator).

    Raises
    ------
    RuntimeError
        If the artefact cannot be loaded from disk.
    """
    resolved = _resolve_path(path)
    key = (resolved, version)

    with _CACHE_LOCK:
        if not force_reload and key in _MODEL_CACHE:
            logger.debug("Model cache hit: path=%s version=%s", resolved, version)
            return _MODEL_CACHE[key]

        logger.info("Loading model from disk: path=%s version=%s", resolved, version)
        try:
            model = joblib.load(resolved)
        except Exception as exc:
            raise RuntimeError(
                f"[model_loader] Failed to load model artefact at '{resolved}' "
                f"(version={version}): {exc}"
            ) from exc

        _MODEL_CACHE[key] = model
        logger.info(
            "Model cached: path=%s version=%s type=%s",
            resolved,
            version,
            type(model).__name__,
        )
        return model


def get_or_load(
    path: Optional[str | Path],
    version: str = "unknown",
) -> Any:
    """
    Return the cached model for *(path, version)*, loading from disk if needed.

    This is the primary entry point for scorer functions.  On the hot path
    (after init) this is an O(1) dict lookup with no disk I/O.
    """
    if not path:
        raise ValueError("[model_loader] path must be a non-empty string or Path")
    resolved = _resolve_path(path)
    key = (resolved, version)

    # Fast path — no lock needed for a read when the entry is already present
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]

    # Slow path — delegate to load_model which is thread-safe
    return load_model(resolved, version)


def preload(paths_and_versions: list[Tuple[str | Path, str]]) -> None:
    """
    Pre-load a list of ``(path, version)`` pairs at startup.

    Logs a warning for each artefact that cannot be loaded instead of
    raising so that the remaining models still load successfully.

    Parameters
    ----------
    paths_and_versions:
        e.g. ``[("/app/models/risk_v1.pkl", "v1"), ("/app/models/fraud_v1.pkl", "v1")]``
    """
    for path, version in paths_and_versions:
        try:
            load_model(path, version)
        except RuntimeError as exc:
            logger.warning("[preload] %s — this model will be unavailable: %s", path, exc)


def evict(path: Optional[str | Path], version: str = "unknown") -> bool:
    """
    Remove a model from the cache (e.g. after a hot-swap).

    Returns True if an entry was removed.
    """
    key = (_resolve_path(path), version)
    with _CACHE_LOCK:
        if key in _MODEL_CACHE:
            del _MODEL_CACHE[key]
            logger.info("Evicted model from cache: path=%s version=%s", path, version)
            return True
    return False


def cache_info() -> Dict[str, Any]:
    """Return a snapshot of the cache contents for health-check / debug endpoints."""
    with _CACHE_LOCK:
        return {
            "loaded_models": [
                {"path": k[0], "version": k[1], "type": type(v).__name__}
                for k, v in _MODEL_CACHE.items()
            ],
            "total_models": len(_MODEL_CACHE),
        }
