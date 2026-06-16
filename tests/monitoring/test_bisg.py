"""
Tests for the P1.5 BISG proxy methodology (monitoring/bisg.py).
"""
from __future__ import annotations

import pandas as pd
import pytest

from monitoring.bisg import (
    RACE_COLS,
    add_bisg_columns,
    assign_proxy_group,
    compute_bisg_probabilities,
    load_surname_table,
    load_tract_demographics,
)


# ---------------------------------------------------------------------------
# load_surname_table
# ---------------------------------------------------------------------------


def test_load_surname_table_bundled():
    """Bundled data loads without needing a CSV."""
    table = load_surname_table()
    assert isinstance(table, pd.DataFrame)
    assert set(RACE_COLS).issubset(table.columns)
    assert len(table) > 0
    # Probabilities should be in [0, 1]
    assert (table[RACE_COLS] >= 0).all().all()
    assert (table[RACE_COLS] <= 1.0001).all().all()


def test_load_surname_table_missing_csv_falls_back(tmp_path):
    """Non-existent CSV path should fall back to bundled data gracefully."""
    table = load_surname_table(csv_path=tmp_path / "nonexistent.csv")
    assert len(table) > 0


def test_load_surname_table_from_csv(tmp_path):
    """Custom CSV with pct_xxx columns (percentage 0–100) loads correctly."""
    rows = [
        "name,pct_white,pct_black,pct_hispanic,pct_asian,pct_other",
        "TESTNAME,50.0,20.0,15.0,10.0,5.0",
    ]
    csv_path = tmp_path / "surnames.csv"
    csv_path.write_text("\n".join(rows))
    table = load_surname_table(csv_path=csv_path)
    assert "TESTNAME" in table.index
    assert abs(table.loc["TESTNAME", "white"] - 0.50) < 1e-4


# ---------------------------------------------------------------------------
# compute_bisg_probabilities — surname-only mode
# ---------------------------------------------------------------------------


def test_surnames_sum_to_one():
    probs = compute_bisg_probabilities(["Smith", "Garcia", "Lee"])
    row_sums = probs[RACE_COLS].sum(axis=1)
    assert (abs(row_sums - 1.0) < 0.01).all(), f"Row sums: {row_sums.tolist()}"


def test_garcia_has_highest_hispanic_probability():
    probs = compute_bisg_probabilities(["Garcia"])
    max_group = probs[RACE_COLS].idxmax(axis=1).iloc[0]
    assert max_group == "hispanic", f"Expected hispanic, got {max_group}"


def test_smith_has_highest_white_probability():
    probs = compute_bisg_probabilities(["Smith"])
    max_group = probs[RACE_COLS].idxmax(axis=1).iloc[0]
    assert max_group == "white", f"Expected white, got {max_group}"


def test_nguyen_has_highest_asian_probability():
    probs = compute_bisg_probabilities(["Nguyen"])
    max_group = probs[RACE_COLS].idxmax(axis=1).iloc[0]
    assert max_group == "asian", f"Expected asian, got {max_group}"


def test_unknown_surname_falls_back_to_national_priors():
    probs = compute_bisg_probabilities(["ZZZYYYXXX"])
    # National prior: white is largest group
    max_group = probs[RACE_COLS].idxmax(axis=1).iloc[0]
    assert max_group == "white"


def test_output_shape():
    n = 5
    probs = compute_bisg_probabilities(["Smith"] * n)
    assert probs.shape == (n, len(RACE_COLS))


def test_lengths_must_match():
    with pytest.raises(ValueError, match="same length"):
        compute_bisg_probabilities(["Smith", "Lee"], census_tracts=["06037101110"])


# ---------------------------------------------------------------------------
# compute_bisg_probabilities — with geographic update
# ---------------------------------------------------------------------------


def _make_tract_table() -> pd.DataFrame:
    """Minimal tract table: majority-Hispanic tract. Values already in 0-1 range."""
    return pd.DataFrame(
        {
            "census_tract": ["06037101110"],
            "white": [0.05],
            "black": [0.02],
            "hispanic": [0.90],
            "asian": [0.02],
            "other": [0.01],
        }
    ).set_index("census_tract")[RACE_COLS]


def _normalise_tract_table(df: pd.DataFrame) -> pd.DataFrame:
    """No-op — table is already normalised in _make_tract_table."""
    return df


def test_bisg_geo_update_amplifies_hispanic_for_smith():
    """Smith in a 90% Hispanic tract should shift toward hispanic."""
    tract_table = _normalise_tract_table(_make_tract_table())
    probs_no_geo = compute_bisg_probabilities(["Smith"])
    probs_with_geo = compute_bisg_probabilities(
        ["Smith"],
        census_tracts=["06037101110"],
        tract_table=tract_table,
    )
    assert probs_with_geo.loc[0, "hispanic"] > probs_no_geo.loc[0, "hispanic"]


def test_unknown_tract_leaves_probabilities_unchanged():
    tract_table = _normalise_tract_table(_make_tract_table())
    probs_no_geo = compute_bisg_probabilities(["Smith"])
    probs_unknown_tract = compute_bisg_probabilities(
        ["Smith"],
        census_tracts=["UNKNOWN_TRACT"],
        tract_table=tract_table,
    )
    # Should be identical since tract unknown
    assert abs(
        probs_no_geo.loc[0, "white"] - probs_unknown_tract.loc[0, "white"]
    ) < 1e-4


# ---------------------------------------------------------------------------
# assign_proxy_group
# ---------------------------------------------------------------------------


def test_assign_proxy_group_above_threshold():
    probs = compute_bisg_probabilities(["Garcia"])
    group = assign_proxy_group(probs, threshold=0.50)
    assert group.iloc[0] == "hispanic"


def test_assign_proxy_group_below_threshold_is_unknown():
    """Ambiguous row should return 'unknown' below threshold."""
    import pandas as pd
    equal_probs = pd.DataFrame(
        {"white": [0.20], "black": [0.20], "hispanic": [0.20], "asian": [0.20], "other": [0.20]}
    )
    group = assign_proxy_group(equal_probs, threshold=0.50, fallback="unknown")
    assert group.iloc[0] == "unknown"


def test_assign_proxy_group_threshold_zero_always_assigns():
    probs = compute_bisg_probabilities(["ZZZYYYXXX"])
    group = assign_proxy_group(probs, threshold=0.0)
    assert group.iloc[0] != "unknown"


# ---------------------------------------------------------------------------
# add_bisg_columns
# ---------------------------------------------------------------------------


def test_add_bisg_columns_adds_expected_cols():
    df = pd.DataFrame({"application_id": ["A1", "A2"], "surname": ["Garcia", "Smith"]})
    result = add_bisg_columns(df)
    for col in RACE_COLS:
        assert f"bisg_{col}" in result.columns
    assert "proxy_group" in result.columns


def test_add_bisg_columns_does_not_mutate_input():
    df = pd.DataFrame({"application_id": ["A1"], "surname": ["Garcia"]})
    original_cols = set(df.columns)
    add_bisg_columns(df)
    assert set(df.columns) == original_cols


def test_add_bisg_columns_with_census_tract():
    import pandas as pd
    tract_table = _normalise_tract_table(_make_tract_table())
    df = pd.DataFrame(
        {
            "surname": ["Smith"],
            "census_tract": ["06037101110"],
        }
    )
    result = add_bisg_columns(df, tract_table=tract_table)
    # Geographic update should increase Hispanic probability
    probs_surname_only = compute_bisg_probabilities(["Smith"])
    assert result.loc[0, "bisg_hispanic"] > probs_surname_only.loc[0, "hispanic"]


def test_add_bisg_columns_missing_tract_col_ok():
    df = pd.DataFrame({"surname": ["Garcia"], "other_col": [1]})
    result = add_bisg_columns(df, tract_col=None)
    assert "proxy_group" in result.columns
