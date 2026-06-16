"""
Tests for the P1.4 MDR generator (compliance/generate_model_doc.py).
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from compliance.generate_model_doc import (
    MDRValidationError,
    ModelDocumentationConfig,
    ModelDocumentationRecord,
    generate_mdr,
    mdr_to_json,
    mdr_to_markdown,
    save_mdr,
    validate_mdr_completeness,
)


def _default_config(**kwargs) -> ModelDocumentationConfig:
    defaults = dict(
        model_name="cc_pd_model",
        version="v1",
        use_case="Credit Card Probability of Default",
        owner="Risk Analytics",
        reviewer="Model Risk Management",
        approver="Chief Risk Officer",
        intended_population="US credit card applicants, age 18+",
    )
    defaults.update(kwargs)
    return ModelDocumentationConfig(**defaults)


def _minimal_model_card() -> dict:
    return {
        "model_id": "cc_pd_model_v1",
        "algorithm": "LightGBM + Isotonic Calibration",
        "feature_count": 42,
        "cv_metrics": {"mean_auc": 0.78, "mean_gini": 0.56, "mean_ks": 0.42},
        "monotone_constraints": {
            "n_constrained_features": 18,
            "verification_passed": True,
        },
        "limitations": ["LGD is assumed constant at 0.65."],
        "assumptions": ["A001: LGD = 0.65 (fixed)."],
    }


# ---------------------------------------------------------------------------
# generate_mdr — basic contract
# ---------------------------------------------------------------------------


def test_generate_mdr_requires_run_id_or_card():
    with pytest.raises(ValueError, match="at least one"):
        generate_mdr(config=_default_config())


def test_generate_mdr_from_model_card(tmp_path):
    card_path = tmp_path / "card.json"
    card_path.write_text(json.dumps(_minimal_model_card()), encoding="utf-8")

    mdr = generate_mdr(config=_default_config(), model_card_path=card_path)

    assert mdr.model_id == "cc_pd_model_v1"
    assert mdr.algorithm == "LightGBM + Isotonic Calibration"
    assert mdr.feature_count == 42
    assert mdr.monotone_constraints_applied
    assert mdr.monotone_verification_passed is True
    assert mdr.n_constrained_features == 18


def test_generate_mdr_sets_owner_reviewer_approver(tmp_path):
    card_path = tmp_path / "card.json"
    card_path.write_text(json.dumps(_minimal_model_card()), encoding="utf-8")

    config = _default_config(owner="Alice", reviewer="Bob", approver="CEO")
    mdr = generate_mdr(config=config, model_card_path=card_path)

    assert mdr.owner == "Alice"
    assert mdr.reviewer == "Bob"
    assert mdr.approver == "CEO"


def test_generate_mdr_default_limitations_present_when_card_absent(tmp_path):
    """When model card has no limitations, defaults should be injected."""
    card = _minimal_model_card()
    del card["limitations"]
    card_path = tmp_path / "card.json"
    card_path.write_text(json.dumps(card), encoding="utf-8")

    mdr = generate_mdr(config=_default_config(), model_card_path=card_path)
    assert len(mdr.limitations) > 0
    assert any("LGD" in lim for lim in mdr.limitations)


def test_additional_limitations_merged(tmp_path):
    card_path = tmp_path / "card.json"
    card_path.write_text(json.dumps(_minimal_model_card()), encoding="utf-8")

    config = _default_config(additional_limitations=["Extra: model untested in recession."])
    mdr = generate_mdr(config=config, model_card_path=card_path)
    assert any("recession" in lim for lim in mdr.limitations)


def test_generated_at_is_set(tmp_path):
    card_path = tmp_path / "card.json"
    card_path.write_text(json.dumps(_minimal_model_card()), encoding="utf-8")
    mdr = generate_mdr(config=_default_config(), model_card_path=card_path)
    assert mdr.generated_at  # non-empty ISO timestamp


# ---------------------------------------------------------------------------
# validate_mdr_completeness
# ---------------------------------------------------------------------------


def _make_complete_mdr() -> ModelDocumentationRecord:
    from datetime import datetime, timezone
    return ModelDocumentationRecord(
        model_id="cc_pd_model_v1",
        model_name="cc_pd_model",
        version="v1",
        use_case="Credit Card PD",
        owner="Risk Analytics",
        reviewer="MRM",
        approver="CRO",
        intended_population="US CC applicants",
        algorithm="LightGBM",
        feature_count=42,
        training_data_description="5M synthetic records.",
        validation_summary={"cv_method": "5-fold", "metrics": {"auc": 0.78}},
        limitations=["LGD fixed."],
        assumptions=["A001."],
        monotone_constraints_applied=True,
        monotone_verification_passed=True,
        n_constrained_features=18,
        mlflow_run_id=None,
        mlflow_experiment_id=None,
        mlflow_run_name=None,
        monitoring_plan="Monthly PSI check.",
    )


def test_complete_mdr_passes_validation():
    mdr = _make_complete_mdr()
    validate_mdr_completeness(mdr)  # should not raise


def test_missing_owner_fails_validation():
    mdr = _make_complete_mdr()
    mdr.owner = ""
    with pytest.raises(MDRValidationError, match="owner"):
        validate_mdr_completeness(mdr)


def test_zero_feature_count_fails_validation():
    mdr = _make_complete_mdr()
    mdr.feature_count = 0
    with pytest.raises(MDRValidationError, match="feature_count"):
        validate_mdr_completeness(mdr)


def test_empty_limitations_fails_validation():
    mdr = _make_complete_mdr()
    mdr.limitations = []
    with pytest.raises(MDRValidationError, match="limitations"):
        validate_mdr_completeness(mdr)


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def test_mdr_to_json_is_valid():
    mdr = _make_complete_mdr()
    doc = json.loads(mdr_to_json(mdr))
    assert doc["model_id"] == "cc_pd_model_v1"
    assert "validation_summary" in doc


def test_mdr_to_markdown_contains_key_sections():
    mdr = _make_complete_mdr()
    md = mdr_to_markdown(mdr)
    assert "# Model Documentation Record" in md
    assert "## 1. Model Identification" in md
    assert "## 2. Training Data" in md
    assert "## 4. Validation Summary" in md
    assert "## 5. Limitations" in md
    assert "## 6. Assumptions" in md
    assert "## 7. Ongoing Monitoring Plan" in md


def test_save_mdr_markdown(tmp_path):
    mdr = _make_complete_mdr()
    out = tmp_path / "mdr.md"
    save_mdr(mdr, out, fmt="markdown")
    assert out.exists()
    assert "# Model Documentation Record" in out.read_text()


def test_save_mdr_json(tmp_path):
    mdr = _make_complete_mdr()
    out = tmp_path / "mdr.json"
    save_mdr(mdr, out, fmt="json")
    assert out.exists()
    doc = json.loads(out.read_text())
    assert doc["model_id"] == "cc_pd_model_v1"


def test_save_mdr_creates_parents(tmp_path):
    mdr = _make_complete_mdr()
    out = tmp_path / "docs" / "mdr" / "test.md"
    save_mdr(mdr, out, fmt="markdown")
    assert out.exists()
