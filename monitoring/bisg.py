"""
BISG Proxy Methodology
=======================
Implements the Bayesian Improved Surname Geocoding (BISG) method for
estimating race/ethnicity probabilities when self-reported demographic data
are unavailable.

Regulatory basis
----------------
CFPB Supervisory Guidance (2014, revised 2019) and HMDA reporting rules
require lenders to estimate protected-group membership using a proxy
methodology when collecting demographic data is not permitted (e.g., for
non-mortgage credit products).  BISG is the CFPB-endorsed proxy.

Statistical basis
-----------------
Using Bayes' theorem, the posterior probability that an applicant belongs to
racial/ethnic group *r* is:

    P(r | surname, geo) ∝ P(r | surname) × P(r | geo) / P(r)

where P(r | surname) comes from the Census Surname List and P(r | geo)
comes from Census block-group or tract demographics.

Public API
----------
    from monitoring.bisg import compute_bisg_probabilities, assign_proxy_group

    probs = compute_bisg_probabilities(
        surnames=["Smith", "Garcia", "Lee"],
        census_tracts=["06037101110", "06037210200", "36061007900"],
    )
    # probs: DataFrame with columns [white, black, hispanic, asian, other]

    primary = assign_proxy_group(probs)
    # primary: Series with the most-probable group per row

Note on bundled data
--------------------
This module ships with summary-level Census surname data derived from the
2010 Census Surname List (public domain, see
https://www.census.gov/topics/population/genealogy/data/2010_surnames.html).
For production use, download the full CSV from the Census Bureau and pass the
path to ``load_surname_table()``.  Tract-level demographics must be supplied
by the caller (e.g., from the ACS 5-year estimates API).
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Race/ethnicity categories (aligns to HMDA / CFPB proxy guidance) ──────────
RACE_COLS: List[str] = ["white", "black", "hispanic", "asian", "other"]

# ── Minimum posterior probability to assign a definitive proxy group ──────────
_DEFAULT_THRESHOLD = 0.50

# ── Bundled fallback surname priors (derived from Census 2010 top surnames) ──
#    These are illustrative; replace with full Census Surname List CSV.
_BUNDLED_SURNAME_PRIORS: Dict[str, Dict[str, float]] = {
    # surname_upper -> {white, black, hispanic, asian, other}
    "SMITH":     {"white": 0.706, "black": 0.232, "hispanic": 0.028, "asian": 0.005, "other": 0.029},
    "JOHNSON":   {"white": 0.589, "black": 0.341, "hispanic": 0.032, "asian": 0.006, "other": 0.032},
    "WILLIAMS":  {"white": 0.483, "black": 0.461, "hispanic": 0.023, "asian": 0.005, "other": 0.028},
    "JONES":     {"white": 0.574, "black": 0.368, "hispanic": 0.026, "asian": 0.004, "other": 0.028},
    "BROWN":     {"white": 0.579, "black": 0.356, "hispanic": 0.033, "asian": 0.007, "other": 0.025},
    "GARCIA":    {"white": 0.059, "black": 0.006, "hispanic": 0.920, "asian": 0.002, "other": 0.013},
    "MARTINEZ":  {"white": 0.054, "black": 0.006, "hispanic": 0.924, "asian": 0.002, "other": 0.014},
    "RODRIGUEZ": {"white": 0.033, "black": 0.006, "hispanic": 0.950, "asian": 0.002, "other": 0.009},
    "HERNANDEZ": {"white": 0.024, "black": 0.004, "hispanic": 0.962, "asian": 0.001, "other": 0.009},
    "LOPEZ":     {"white": 0.040, "black": 0.006, "hispanic": 0.942, "asian": 0.002, "other": 0.010},
    "GONZALEZ":  {"white": 0.041, "black": 0.005, "hispanic": 0.940, "asian": 0.002, "other": 0.012},
    "LEE":       {"white": 0.268, "black": 0.170, "hispanic": 0.052, "asian": 0.479, "other": 0.031},
    "NGUYEN":    {"white": 0.009, "black": 0.001, "hispanic": 0.010, "asian": 0.974, "other": 0.006},
    "KIM":       {"white": 0.025, "black": 0.008, "hispanic": 0.017, "asian": 0.940, "other": 0.010},
    "PARK":      {"white": 0.100, "black": 0.024, "hispanic": 0.053, "asian": 0.792, "other": 0.031},
    "PATEL":     {"white": 0.012, "black": 0.003, "hispanic": 0.008, "asian": 0.961, "other": 0.016},
    "CHEN":      {"white": 0.017, "black": 0.003, "hispanic": 0.011, "asian": 0.963, "other": 0.006},
    "WASHINGTON":{"white": 0.167, "black": 0.778, "hispanic": 0.020, "asian": 0.002, "other": 0.033},
    "JACKSON":   {"white": 0.397, "black": 0.550, "hispanic": 0.024, "asian": 0.003, "other": 0.026},
    "TAYLOR":    {"white": 0.676, "black": 0.264, "hispanic": 0.028, "asian": 0.004, "other": 0.028},
}

# National-level base rates (2020 Census — approximation)
_NATIONAL_PRIORS: Dict[str, float] = {
    "white":    0.597,
    "black":    0.134,
    "hispanic": 0.186,
    "asian":    0.059,
    "other":    0.024,
}


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------


def load_surname_table(csv_path: Optional[Path] = None) -> pd.DataFrame:
    """Load the Census surname probability table.

    Parameters
    ----------
    csv_path :
        Path to the Census Surname CSV.  Expected columns:
        ``name, pct_white, pct_black, pct_hispanic, pct_asian, pct_other``
        (values as percentages 0–100).  If *None*, the bundled summary data is
        returned.

    Returns
    -------
    DataFrame indexed by uppercase surname with float columns
    ``[white, black, hispanic, asian, other]`` that sum to ≈1.0.
    """
    if csv_path and Path(csv_path).exists():
        df = pd.read_csv(csv_path, dtype=str)
        # Normalise column names
        df.columns = [c.lower().strip() for c in df.columns]
        rename = {
            "pct_white": "white", "pct_black": "black",
            "pct_hispanic": "hispanic", "pct_asian": "asian",
            "pct_other": "other", "pctwhite": "white", "pctblack": "black",
            "pcthispanic": "hispanic", "pctasian": "asian", "pctother": "other",
        }
        df = df.rename(columns=rename)
        df["name"] = df["name"].str.upper().str.strip()
        for col in RACE_COLS:
            df[col] = pd.to_numeric(df.get(col, 0), errors="coerce").fillna(0.0) / 100.0
        return df.set_index("name")[RACE_COLS]
    else:
        if csv_path:
            logger.warning("Surname CSV not found at %s; using bundled data.", csv_path)
        rows = {name: {c: v for c, v in probs.items()} for name, probs in _BUNDLED_SURNAME_PRIORS.items()}
        return pd.DataFrame(rows).T[RACE_COLS]


def load_tract_demographics(
    csv_path: Optional[Path] = None,
    acs_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Load census-tract-level race/ethnicity proportions.

    Parameters
    ----------
    csv_path :
        Path to an ACS CSV with columns:
        ``census_tract, pct_white, pct_black, pct_hispanic, pct_asian, pct_other``.
    acs_df :
        Alternatively pass a pre-loaded DataFrame directly.

    Returns
    -------
    DataFrame indexed by census_tract with float columns
    ``[white, black, hispanic, asian, other]`` summing to ≈1.0.
    """
    if acs_df is not None:
        df = acs_df.copy()
    elif csv_path and Path(csv_path).exists():
        df = pd.read_csv(csv_path, dtype=str)
    else:
        logger.warning("No tract demographics provided; using national priors for geo step.")
        return pd.DataFrame()

    df.columns = [c.lower().strip() for c in df.columns]
    rename = {
        "pct_white": "white", "pct_black": "black",
        "pct_hispanic": "hispanic", "pct_asian": "asian",
        "pct_other": "other",
    }
    df = df.rename(columns=rename)
    # standardise tract identifier
    tract_col = next((c for c in df.columns if "tract" in c), None)
    if tract_col is None:
        raise ValueError("DataFrame must have a column containing 'tract' in the name.")
    df["census_tract"] = df[tract_col].astype(str).str.strip()
    for col in RACE_COLS:
        df[col] = pd.to_numeric(df.get(col, 0), errors="coerce").fillna(0.0) / 100.0
    return df.set_index("census_tract")[RACE_COLS]


# ---------------------------------------------------------------------------
# Core BISG algorithm
# ---------------------------------------------------------------------------


def _normalise_surname(name: str) -> str:
    """Uppercase, strip punctuation and whitespace for surname lookup."""
    return re.sub(r"[^A-Z ]", "", str(name).upper().strip())


def _apply_surname_prior(
    surnames: Sequence[str],
    surname_table: pd.DataFrame,
) -> pd.DataFrame:
    """Look up P(r | surname) for each surname.

    Unknown surnames are assigned the national base rates.
    """
    national = pd.Series(_NATIONAL_PRIORS, name="fallback")
    rows = []
    for raw_name in surnames:
        name = _normalise_surname(raw_name)
        if name in surname_table.index:
            rows.append(surname_table.loc[name, RACE_COLS].values)
        else:
            rows.append(national[RACE_COLS].values)
    return pd.DataFrame(rows, columns=RACE_COLS)


def _apply_geography_update(
    surname_probs: pd.DataFrame,
    census_tracts: Sequence[Optional[str]],
    tract_table: pd.DataFrame,
) -> pd.DataFrame:
    """Bayesian update: P(r | surname, geo) ∝ P(r | surname) × P(r | geo) / P(r).

    When a tract is not found in the table the surname-only posterior is kept.
    """
    national = pd.Series(_NATIONAL_PRIORS)
    result = surname_probs.copy().values.astype(float)

    for i, tract in enumerate(census_tracts):
        if tract is None:
            continue
        tract = str(tract).strip()
        if tract not in tract_table.index:
            continue

        geo_probs = tract_table.loc[tract, RACE_COLS].values.astype(float)
        prior = national[RACE_COLS].values.astype(float)

        # Zero-safe division: omit components where prior == 0
        with np.errstate(divide="ignore", invalid="ignore"):
            posterior = result[i] * geo_probs / prior
            posterior = np.where(prior > 0, posterior, 0.0)

        total = posterior.sum()
        if total > 0:
            result[i] = posterior / total
        # else keep surname-only posterior

    return pd.DataFrame(result, columns=RACE_COLS)


def compute_bisg_probabilities(
    surnames: Sequence[str],
    census_tracts: Optional[Sequence[Optional[str]]] = None,
    surname_table: Optional[pd.DataFrame] = None,
    tract_table: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Compute BISG posterior race/ethnicity probabilities.

    Parameters
    ----------
    surnames :
        Sequence of applicant surnames (same length as *census_tracts*).
    census_tracts :
        FIPS census tract codes (11-digit).  Pass ``None`` elements or omit
        to use surname-only priors.
    surname_table :
        Pre-loaded surname table from ``load_surname_table()``.  Loaded from
        bundled data if omitted.
    tract_table :
        Pre-loaded tract demographics from ``load_tract_demographics()``.
        If omitted, no geographic update is applied.

    Returns
    -------
    DataFrame of shape (n, 5) with columns ``[white, black, hispanic, asian,
    other]``.  Values are posterior probabilities that sum to 1.0 per row.
    """
    if surname_table is None:
        surname_table = load_surname_table()

    n = len(surnames)
    if census_tracts is None:
        census_tracts = [None] * n

    if len(census_tracts) != n:
        raise ValueError("'surnames' and 'census_tracts' must have the same length.")

    # Step 1: P(r | surname)
    probs = _apply_surname_prior(surnames, surname_table)

    # Step 2: Bayesian update with geography if available
    if tract_table is not None and len(tract_table) > 0:
        probs = _apply_geography_update(probs, census_tracts, tract_table)

    # Round to 4 decimal places for readability
    return probs.round(4).reset_index(drop=True)


def assign_proxy_group(
    bisg_probs: pd.DataFrame,
    threshold: float = _DEFAULT_THRESHOLD,
    fallback: str = "unknown",
) -> pd.Series:
    """Assign the most-probable racial/ethnic group per applicant.

    If the maximum probability in a row is below *threshold*, the applicant
    is assigned *fallback* (typically ``"unknown"``).

    Parameters
    ----------
    bisg_probs :
        Output of ``compute_bisg_probabilities()``.
    threshold :
        Minimum posterior probability to make a definitive assignment.
    fallback :
        Label used when no group exceeds the threshold.

    Returns
    -------
    pd.Series of group labels.
    """
    max_vals = bisg_probs[RACE_COLS].max(axis=1)
    assigned = bisg_probs[RACE_COLS].idxmax(axis=1)
    return assigned.where(max_vals >= threshold, other=fallback).rename("proxy_group")


def add_bisg_columns(
    df: pd.DataFrame,
    surname_col: str = "surname",
    tract_col: Optional[str] = "census_tract",
    surname_table: Optional[pd.DataFrame] = None,
    tract_table: Optional[pd.DataFrame] = None,
    threshold: float = _DEFAULT_THRESHOLD,
) -> pd.DataFrame:
    """Convenience wrapper: add BISG columns to an existing DataFrame.

    Adds five probability columns (``bisg_white``, ``bisg_black``, etc.) and
    one ``proxy_group`` column to *df*.  The original DataFrame is not mutated.

    Parameters
    ----------
    df :
        Input DataFrame containing at least *surname_col*.
    surname_col :
        Column name for applicant surnames.
    tract_col :
        Column name for FIPS census tract codes.  Pass ``None`` to skip the
        geographic update.
    surname_table / tract_table :
        Pre-loaded tables; loaded automatically if omitted.
    threshold :
        Probability threshold for ``assign_proxy_group()``.

    Returns
    -------
    Copy of *df* with added BISG columns.
    """
    surnames = df[surname_col].fillna("").tolist()
    tracts: Optional[List[Optional[str]]] = (
        df[tract_col].where(df[tract_col].notna(), other=None).tolist()
        if (tract_col and tract_col in df.columns)
        else None
    )

    bisg = compute_bisg_probabilities(
        surnames=surnames,
        census_tracts=tracts,
        surname_table=surname_table,
        tract_table=tract_table,
    )

    result = df.copy().reset_index(drop=True)
    for col in RACE_COLS:
        result[f"bisg_{col}"] = bisg[col].values
    result["proxy_group"] = assign_proxy_group(bisg, threshold=threshold).values
    return result
