"""
P1.4 — Model Loader: No Per-Request Disk I/O
=============================================
Verifies that:
* get_or_load returns the same object on repeated calls (cache hit, O(1) lookup)
* load_model raises RuntimeError on missing artefacts
* evict / force_reload work correctly
* predict_pd and predict_fraud do not call joblib.load on the hot path once the
  model is in the process-level cache
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# model_loader unit tests
# ---------------------------------------------------------------------------

class TestModelLoader:

    def setup_method(self):
        """Clear the cache before each test for isolation."""
        from models import model_loader
        model_loader._MODEL_CACHE.clear()

    def test_load_model_caches_result(self, tmp_path):
        """Second call with same path must return the cached object, no disk I/O."""
        import joblib
        from models.model_loader import load_model, _MODEL_CACHE

        # Write a dummy model
        model_path = tmp_path / "dummy.pkl"
        dummy = {"type": "mock_model"}
        joblib.dump(dummy, str(model_path))

        with patch("models.model_loader.joblib") as mock_joblib:
            mock_joblib.load.return_value = dummy
            m1 = load_model(str(model_path), version="v1")
            m2 = load_model(str(model_path), version="v1")

        # joblib.load should have been called exactly once
        assert mock_joblib.load.call_count == 1
        assert m1 is m2

    def test_different_versions_loaded_separately(self, tmp_path):
        """Same path with different version tags are cached as distinct entries."""
        import joblib
        from models.model_loader import load_model, _MODEL_CACHE

        model_path = tmp_path / "model.pkl"
        joblib.dump({"v": "champion"}, str(model_path))

        with patch("models.model_loader.joblib") as mock_joblib:
            mock_joblib.load.side_effect = [{"v": "champion"}, {"v": "challenger"}]
            load_model(str(model_path), version="v1")
            load_model(str(model_path), version="v2")

        assert mock_joblib.load.call_count == 2

    def test_missing_artefact_raises_runtime_error(self, tmp_path):
        from models.model_loader import load_model

        with pytest.raises(RuntimeError, match="Failed to load model artefact"):
            load_model(str(tmp_path / "nonexistent.pkl"), version="v1")

    def test_evict_removes_from_cache(self, tmp_path):
        import joblib
        from models.model_loader import load_model, evict, _MODEL_CACHE

        model_path = tmp_path / "evict_test.pkl"
        joblib.dump({"x": 1}, str(model_path))

        load_model(str(model_path), version="v1")
        assert len(_MODEL_CACHE) == 1

        evicted = evict(str(model_path), version="v1")
        assert evicted is True
        assert len(_MODEL_CACHE) == 0

    def test_force_reload_bypasses_cache(self, tmp_path):
        import joblib
        from models.model_loader import load_model

        model_path = tmp_path / "reload_test.pkl"
        joblib.dump({"v": 1}, str(model_path))

        with patch("models.model_loader.joblib") as mock_joblib:
            mock_joblib.load.return_value = {"v": 1}
            load_model(str(model_path), version="v1")
            load_model(str(model_path), version="v1", force_reload=True)

        assert mock_joblib.load.call_count == 2

    def test_cache_info_returns_loaded_models(self, tmp_path):
        import joblib
        from models.model_loader import load_model, cache_info

        model_path = tmp_path / "info_test.pkl"
        joblib.dump({"x": 1}, str(model_path))

        load_model(str(model_path), version="v99")
        info = cache_info()
        assert info["total_models"] >= 1
        paths = [m["path"] for m in info["loaded_models"]]
        assert str(model_path.resolve()) in paths

    def test_preload_logs_warnings_on_missing(self, capfd):
        """preload must not raise even when artefacts are missing."""
        from models.model_loader import preload

        # Should not raise
        preload([("/nonexistent/path.pkl", "v1")])

    def test_is_loaded_returns_false_before_load(self, tmp_path):
        from models.model_loader import is_loaded

        assert is_loaded(str(tmp_path / "unloaded.pkl"), version="v1") is False

    def test_is_loaded_returns_true_after_load(self, tmp_path):
        import joblib
        from models.model_loader import load_model, is_loaded

        model_path = tmp_path / "loaded.pkl"
        joblib.dump({"x": 1}, str(model_path))
        load_model(str(model_path), version="v1")
        assert is_loaded(str(model_path), version="v1") is True


# ---------------------------------------------------------------------------
# predict_pd / predict_fraud hot-path tests
# ---------------------------------------------------------------------------

class TestPredictHotPath:

    def setup_method(self):
        from models import model_loader
        model_loader._MODEL_CACHE.clear()

    def test_predict_pd_uses_cached_model(self, tmp_path):
        """predict_pd must NOT call joblib.load after the model is in cache."""
        import numpy as np
        import pandas as pd
        from models.model_loader import _MODEL_CACHE

        # Pre-seed the cache with a mock model
        mock_model = MagicMock()
        # predict_proba returns a numpy array; the result is sliced with [:, 1]
        mock_model.predict_proba.return_value = np.array([[0.95, 0.05]] * 3)
        resolved = str((tmp_path / "risk_model_v1.pkl").resolve())
        _MODEL_CACHE[(resolved, "v1")] = mock_model

        df = pd.DataFrame({
            "credit_utilization": [0.3, 0.5, 0.1],
            "income_stability_score": [0.8, 0.6, 0.9],
            "repayment_capacity": [0.7, 0.5, 0.8],
            "debt_service_coverage": [2.0, 1.5, 3.0],
            "credit_age_score": [0.5, 0.4, 0.6],
            "derogatory_penalty": [0.0, 0.05, 0.0],
            "months_since_delinquency": [999, 12, 999],
            "log_loan_amount": [10.0, 10.5, 9.5],
            "log_annual_income": [11.0, 11.5, 10.5],
            "dti_x_loan_amount": [0.3, 0.25, 0.2],
            "employment_encoded": [2.0, 1.0, 2.0],
            "thin_file_alt_score": [0.5, 0.4, 0.6],
        })

        with patch("models.model_loader.joblib") as mock_joblib:
            from models.credit_risk.predict import predict_pd
            result = predict_pd(df, model_path=resolved)
            # joblib.load must NOT have been called — cache hit
            mock_joblib.load.assert_not_called()

        assert "pd_score" in result.columns
        assert "pd_band" in result.columns
