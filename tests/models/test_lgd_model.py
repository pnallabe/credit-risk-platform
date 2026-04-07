from __future__ import annotations

import numpy as np
import pandas as pd

from models.credit_risk.lgd_model import LGDModel


def test_unsecured_lgd_above_basel_floor() -> None:
    model = LGDModel()
    lgd = model.predict(product_type="unsecured", risk_grade="C")
    assert lgd >= 0.45


def test_downturn_lgd_greater_than_mean() -> None:
    model = LGDModel()
    seg = model.segments[0]
    mean = model.predict(seg.product_type, seg.risk_grade, use_downturn=False)
    downturn = model.predict(seg.product_type, seg.risk_grade, use_downturn=True)
    assert downturn >= mean


def test_fit_on_synthetic_data() -> None:
    rng = np.random.default_rng(42)
    n = 500
    df = pd.DataFrame({
        "defaulted_balance": rng.uniform(500, 5000, size=n),
        "recovered_amount": rng.uniform(0, 3000, size=n),
        "product_type": rng.choice(["unsecured", "secured"], size=n, p=[0.8, 0.2]),
        "risk_grade": rng.choice(["A", "B", "C", "D"], size=n),
        "collateral_type": [None] * n,
        "year": rng.integers(2018, 2025, size=n),
    })

    # Ensure recovered_amount <= defaulted_balance
    df["recovered_amount"] = np.minimum(df["recovered_amount"], df["defaulted_balance"])  # type: ignore[assignment]

    model = LGDModel().fit(df)
    assert len(model.segments) > 0
    assert all(s.sample_size > 0 for s in model.segments)


def test_predict_batch_shape() -> None:
    model = LGDModel()
    df = pd.DataFrame({
        "product_type": ["unsecured"] * 100,
        "risk_grade": ["C"] * 100,
    })
    out = model.predict_batch(df)
    assert len(out) == 100
