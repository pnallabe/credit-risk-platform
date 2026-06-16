from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class LGDSegment:
    segment_id: str
    product_type: Literal["unsecured", "secured"]
    risk_grade: str
    collateral_type: Optional[str]
    mean_lgd: float
    std_lgd: float
    downturn_lgd: float
    sample_size: int
    percentile_95_lgd: float


_RISK_GRADE_ORDER: Dict[str, int] = {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "ALL": 3}


def _risk_grade_rank(risk_grade: str) -> int:
    return _RISK_GRADE_ORDER.get(str(risk_grade).upper(), 3)


def _basel_unsecured_floor(lgd: float) -> float:
    # Basel III floor for senior unsecured retail: LGD must be >= 45%.
    return float(max(float(lgd), 0.45))


def _segment(
    segment_id: str,
    product_type: Literal["unsecured", "secured"],
    risk_grade: str,
    mean: float,
    std: float,
    downturn: float,
) -> LGDSegment:
    mean = float(mean)
    downturn = float(downturn)
    if product_type == "unsecured":
        mean = _basel_unsecured_floor(mean)
        downturn = _basel_unsecured_floor(downturn)

    return LGDSegment(
        segment_id=segment_id,
        product_type=product_type,
        risk_grade=risk_grade,
        collateral_type=None,
        mean_lgd=mean,
        std_lgd=float(std),
        downturn_lgd=downturn,
        sample_size=0,
        percentile_95_lgd=float(mean),
    )


# Regulatory-defensible starting segments (benchmarks) expanded across risk grades.
DEFAULT_LGD_SEGMENTS: List[LGDSegment] = [
    # Unsecured — premium-like behavior for best grades
    _segment("unsecured_premium_A", "unsecured", "A", mean=0.68, std=0.10, downturn=0.80),
    _segment("unsecured_premium_B", "unsecured", "B", mean=0.68, std=0.10, downturn=0.80),
    # Unsecured — standard for mid/lower grades
    _segment("unsecured_standard_C", "unsecured", "C", mean=0.72, std=0.12, downturn=0.85),
    _segment("unsecured_standard_D", "unsecured", "D", mean=0.72, std=0.12, downturn=0.85),
    _segment("unsecured_standard_E", "unsecured", "E", mean=0.72, std=0.12, downturn=0.85),
    # Secured
    _segment("secured_ALL", "secured", "ALL", mean=0.42, std=0.08, downturn=0.55),
]


class LGDModel:
    def __init__(self, segments: Optional[List[LGDSegment]] = None):
        self._segments: List[LGDSegment] = list(segments) if segments is not None else list(DEFAULT_LGD_SEGMENTS)

    @property
    def segments(self) -> List[LGDSegment]:
        return list(self._segments)

    def _find_best_segment(
        self,
        product_type: str,
        risk_grade: str,
        collateral_type: Optional[str] = None,
    ) -> LGDSegment:
        product_type_norm = str(product_type).lower().strip()
        risk_grade_norm = str(risk_grade).upper().strip()
        collateral_norm = None if collateral_type is None else str(collateral_type).lower().strip()

        candidates = [s for s in self._segments if s.product_type == product_type_norm]
        if not candidates:
            candidates = list(self._segments)

        # Prefer collateral_type matches when supplied.
        if collateral_norm is not None:
            coll_matches = [s for s in candidates if (s.collateral_type or "").lower() == collateral_norm]
            if coll_matches:
                candidates = coll_matches

        # Exact risk grade match first.
        exact = [s for s in candidates if str(s.risk_grade).upper() == risk_grade_norm]
        if exact:
            return exact[0]

        # Nearest risk grade by ordinal distance.
        target_rank = _risk_grade_rank(risk_grade_norm)
        candidates_sorted = sorted(
            candidates,
            key=lambda s: abs(_risk_grade_rank(s.risk_grade) - target_rank),
        )
        return candidates_sorted[0]

    def predict(
        self,
        product_type: str,
        risk_grade: str,
        collateral_type: Optional[str] = None,
        use_downturn: bool = False,
    ) -> float:
        seg = self._find_best_segment(product_type, risk_grade, collateral_type=collateral_type)
        lgd = float(seg.downturn_lgd if use_downturn else seg.mean_lgd)

        # Enforce Basel floor on ALL unsecured outputs.
        if str(seg.product_type).lower() == "unsecured":
            lgd = _basel_unsecured_floor(lgd)

        return float(np.clip(lgd, 0.0, 1.0))

    def predict_batch(self, df: pd.DataFrame, use_downturn: bool = False) -> pd.Series:
        if "product_type" not in df.columns or "risk_grade" not in df.columns:
            raise ValueError("predict_batch requires columns: product_type, risk_grade")

        vals = [
            self.predict(
                product_type=row.product_type,
                risk_grade=row.risk_grade,
                collateral_type=getattr(row, "collateral_type", None),
                use_downturn=use_downturn,
            )
            for row in df.itertuples(index=False)
        ]
        return pd.Series(vals, index=df.index, name="lgd")

    def fit(self, recovery_df: pd.DataFrame) -> "LGDModel":
        required = {
            "defaulted_balance",
            "recovered_amount",
            "product_type",
            "risk_grade",
            "collateral_type",
            "year",
        }
        missing = required - set(recovery_df.columns)
        if missing:
            raise ValueError(f"recovery_df missing required columns: {sorted(missing)}")

        df = recovery_df.copy()
        bal = df["defaulted_balance"].astype(float).replace({0.0: np.nan})
        rec = df["recovered_amount"].astype(float)
        observed = 1.0 - (rec / bal)
        df["observed_lgd"] = observed.clip(lower=0.0, upper=1.0).fillna(1.0)

        # Portfolio annual LGD means for downturn identification
        annual = df.groupby("year", as_index=False)["observed_lgd"].mean().rename(columns={"observed_lgd": "annual_lgd"})
        p99 = float(np.quantile(annual["annual_lgd"].to_numpy(dtype=float), 0.99)) if len(annual) else 1.0
        downturn_years = set(annual.loc[annual["annual_lgd"] >= p99, "year"].tolist())

        seg_rows: List[LGDSegment] = []
        grouped = df.groupby(["product_type", "risk_grade"], sort=True)

        for (product_type, risk_grade), g in grouped:
            vals = g["observed_lgd"].to_numpy(dtype=float)
            mean = float(np.mean(vals))
            std = float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0
            p95 = float(np.quantile(vals, 0.95)) if len(vals) else mean

            if downturn_years:
                dmask = g["year"].isin(downturn_years)
                if dmask.any():
                    downturn = float(np.mean(g.loc[dmask, "observed_lgd"].to_numpy(dtype=float)))
                else:
                    downturn = mean
            else:
                downturn = mean

            seg = LGDSegment(
                segment_id=f"{product_type}_{risk_grade}",
                product_type=str(product_type).lower().strip(),  # type: ignore[assignment]
                risk_grade=str(risk_grade).upper().strip(),
                collateral_type=None,
                mean_lgd=_basel_unsecured_floor(mean) if str(product_type).lower().strip() == "unsecured" else float(mean),
                std_lgd=float(std),
                downturn_lgd=_basel_unsecured_floor(downturn) if str(product_type).lower().strip() == "unsecured" else float(downturn),
                sample_size=int(len(g)),
                percentile_95_lgd=float(p95),
            )
            seg_rows.append(seg)

        self._segments = seg_rows
        return self

    def save(self, path: Path) -> None:
        payload = {
            "model": "LGDModel",
            "segments": [asdict(s) for s in self._segments],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True))

    @classmethod
    def load(cls, path: Path) -> "LGDModel":
        payload = json.loads(path.read_text())
        segs = []
        for s in payload.get("segments", []):
            segs.append(
                LGDSegment(
                    segment_id=s["segment_id"],
                    product_type=s["product_type"],
                    risk_grade=s["risk_grade"],
                    collateral_type=s.get("collateral_type"),
                    mean_lgd=float(s["mean_lgd"]),
                    std_lgd=float(s["std_lgd"]),
                    downturn_lgd=float(s["downturn_lgd"]),
                    sample_size=int(s["sample_size"]),
                    percentile_95_lgd=float(
                        s.get("percentile_95_lgd", s.get("p95_lgd", s.get("95th_percentile_lgd", 0.0)))
                    ),
                )
            )
        return cls(segments=segs)


def generate_lgd_model_card(model: LGDModel, output_path: Path) -> None:
    """Write a lightweight MDR-aligned LGD model card JSON artifact."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    segment_table = [
        {
            "segment_id": s.segment_id,
            "product_type": s.product_type,
            "risk_grade": s.risk_grade,
            "collateral_type": s.collateral_type,
            "mean_lgd": round(float(s.mean_lgd), 4),
            "std_lgd": round(float(s.std_lgd), 4),
            "downturn_lgd": round(float(s.downturn_lgd), 4),
            "sample_size": int(s.sample_size),
            "95th_percentile_lgd": round(float(s.percentile_95_lgd), 4),
        }
        for s in model.segments
    ]

    card = {
        "model_name": "cc_lgd_segmentation",
        "model_type": "segmentation_table",
        "version": "1.0.0",
        "intended_use": "Provide LGD estimates for PD×LGD×EAD expected loss computations",
        "basel_iii_compliance": {
            "unsecured_floor_applied": True,
            "unsecured_floor_value": 0.45,
            "notes": "All unsecured LGD predictions are floored at 45% (senior unsecured retail).",
        },
        "downturn_lgd_methodology": {
            "description": "Downturn LGD computed as mean LGD in years where portfolio annual mean LGD is above the 99th percentile.",
            "idempotent_fit": True,
        },
        "segments": segment_table,
    }

    output_path.write_text(json.dumps(card, indent=2, sort_keys=True))
