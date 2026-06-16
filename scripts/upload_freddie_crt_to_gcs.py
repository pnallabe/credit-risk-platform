#!/usr/bin/env python3
"""
Freddie Mac CRT Data Intelligence — SFLLD → GCS Upload Pipeline
================================================================
Downloads Single-Family Loan Level Data (SFLLD) from the Freddie Mac
CRT Clarity portal and uploads it to Google Cloud Storage as
partitioned Parquet files.

Portal  : https://claritydownload.fmapps.freddiemac.com/CRT/#/sflld
Auth    : Freddie Mac SSO (PingFederate OIDC)
Output  : gs://<BUCKET>/<PREFIX>/<deal>/<file>.parquet

── Quick-start ──────────────────────────────────────────────────────────────

  # 1. List available deals/files
  make crt-list

  # 2. Upload all SFLLD files (auto-skips already uploaded)
  make crt-upload

  # 3. Upload a specific year or deal
  make crt-upload-year YEAR=2015
  make crt-upload-deal DEAL=STACR-2023

── Direct-URL fallback ───────────────────────────────────────────────────────
  If the API discovery fails, open the portal in Chrome DevTools (Network tab),
  navigate to #/sflld, right-click any download link → Copy as cURL, then pass
  the URL here:

  python scripts/upload_freddie_crt_to_gcs.py \\
      --direct-url "https://claritydownload.fmapps.freddiemac.com/CRT/api/..." \\
      --out-name my_sflld_file

── Debug / troubleshoot ─────────────────────────────────────────────────────
  python scripts/upload_freddie_crt_to_gcs.py --debug --list

── Environment variables ────────────────────────────────────────────────────
  FREDDIE_MAC_USERNAME   Registered e-mail
  FREDDIE_MAC_PASSWORD   Portal password
  GCS_BUCKET             Destination bucket
  GCP_PROJECT_ID         GCP project
  GCS_CRT_PREFIX         GCS path prefix (default: crt/sflld)
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.parse
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests
from google.cloud import storage

# ──────────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────────
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Portal constants
# ──────────────────────────────────────────────────────────────────────────────
PORTAL_BASE     = "https://claritydownload.fmapps.freddiemac.com"
CRT_BASE        = f"{PORTAL_BASE}/CRT"
PING_BASE       = "https://secure.freddiemac.com"
OIDC_CB         = f"{PORTAL_BASE}/pa/oidc/cb"

# ── PingFederate form field names (standard PF 10.x defaults) ────────────────
# If login still fails with --debug, look for <input name="..."> in the HTML.
PF_USERNAME_FIELDS  = ["username", "pf.username", "USER", "login"]
PF_PASSWORD_FIELDS  = ["password", "pf.pass",     "PASS", "pwd"]

# ── Candidate API base paths (tried in order until one returns 2xx JSON) ─────
API_CANDIDATES = [
    f"{CRT_BASE}/api/v1",
    f"{CRT_BASE}/api/v2",
    f"{CRT_BASE}/api",
    f"{PORTAL_BASE}/api/v1",
    f"{PORTAL_BASE}/api",
]

# ── Sub-paths probed for the deals/files catalogue ───────────────────────────
DEALS_PATHS  = ["/sflld/deals", "/deals", "/datasets", "/catalogue", "/catalog"]
FILES_PATHS  = ["/sflld/files", "/files", "/documents", "/downloads"]
DL_PATHS     = ["/sflld/download", "/download", "/stream", "/file"]

# Parquet / upload settings
PARQUET_COMPRESSION = "snappy"
CHUNK_ROWS   = 500_000
MAX_RETRIES  = 3
RETRY_BACKOFF = 5   # seconds

# ── Freddie Mac SFLLD column definitions (pipe-delimited, no header row) ─────
# Source: Freddie Mac Single-Family Loan-Level Dataset user guide (2023 rev.)
FREDDIE_ORIG_COLS = [
    "credit_score",
    "first_payment_date",
    "first_time_homebuyer_flag",
    "maturity_date",
    "msa",
    "mi_pct",
    "number_of_units",
    "occupancy_status",
    "ocltv",
    "odti",
    "original_upb",
    "oltv",
    "original_interest_rate",
    "channel",
    "ppm_flag",
    "product_type",
    "property_state",
    "property_type",
    "postal_code",
    "loan_sequence_number",
    "loan_purpose",
    "original_loan_term",
    "number_of_borrowers",
    "seller_name",
    "servicer_name",
    "super_conforming_flag",
    "pre_harp_loan_sequence_number",
    "program_indicator",
    "harp_indicator",
    "property_valuation_method",
    "io_indicator",
    "mi_cancellation_indicator",
]

FREDDIE_TIME_COLS = [
    "loan_sequence_number",
    "monthly_reporting_period",
    "current_actual_upb",
    "current_delinquency_status",
    "loan_age",
    "remaining_months_to_maturity",
    "defect_settlement_date",
    "modifications_flag",
    "zero_balance_code",
    "zero_balance_effective_date",
    "current_interest_rate",
    "current_non_interest_bearing_upb",
    "due_date_of_last_paid_installment",
    "mi_recoveries",
    "net_sales_proceeds",
    "non_mi_recoveries",
    "expenses",
    "legal_costs",
    "maintenance_costs",
    "taxes_and_insurance",
    "misc_expenses",
    "actual_loss",
    "modification_cost",
    "step_modification_flag",
    "deferred_payment_plan",
    "estimated_ltv",
    "zero_balance_removal_upb",
    "delinquent_accrued_interest",
    "delinquency_due_to_disaster",
    "borrower_assistance_status_code",
    "current_month_modification_cost",
    "interest_bearing_upb",
]


def _freddie_cols_for(csv_name: str) -> Optional[List[str]]:
    """Return the correct column list for a Freddie Mac SFLLD file, or None."""
    lower = csv_name.lower()
    if "_time_" in lower or "_time" in lower:
        return FREDDIE_TIME_COLS
    if "historical_data" in lower:
        return FREDDIE_ORIG_COLS
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Custom exceptions
# ──────────────────────────────────────────────────────────────────────────────
class AuthError(RuntimeError):
    pass

class APIDiscoveryError(RuntimeError):
    pass


# ──────────────────────────────────────────────────────────────────────────────
# Session / authentication
# ──────────────────────────────────────────────────────────────────────────────

def _make_base_session() -> requests.Session:
    """Return a requests.Session with browser-like headers."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    })
    return session


def build_session(
    username: str,
    password: str,
    token: str = "",
    debug: bool = False,
) -> requests.Session:
    """
    Authenticate to Freddie Mac and return an authorised requests.Session.

    Strategy
    ────────
    The CRT Clarity portal is an Angular SPA fronted by PingAccess acting as
    an API gateway.  Every API call needs an ``Authorization: Bearer <token>``
    header — cookies alone are not sufficient.  We try three approaches in order:

    1. **Explicit token** — if ``--token`` is supplied, use it immediately.
    2. **ROPC grant** (Resource Owner Password Credentials) — POST credentials
       directly to the PingFederate token endpoint.  This only works when the
       OAuth2 client is configured to allow ROPC, which is common in internal
       enterprise deployments.
    3. **Redirect-based SSO** — GET /CRT/ → 302 → PF login form → POST creds
       → 302 back to OIDC callback.  Cookie-based auth that some PF deployments
       use for the portal shell even when API calls use Bearer tokens.

    If all three fail the caller is instructed to use --token with a value
    copied from the browser DevTools Network tab.
    """
    # ── Approach 1: Explicit token supplied by caller ──────────────────────
    if token:
        log.info("── Auth: using supplied Bearer token.")
        session = _make_base_session()
        session.headers["Authorization"] = f"Bearer {token}"
        return session

    session = _make_base_session()

    # ── Approach 2: PingFederate ROPC token endpoint ───────────────────────
    # Try multiple PF token endpoint URLs common to Freddie Mac's deployment.
    pf_token_urls = [
        f"{PING_BASE}/as/token.oauth2",
        f"{PING_BASE}/ext/auth/token",
    ]
    client_ids = [
        "cx_clarity_oidc_authz_pip_pa_wam",
        "cx_clarity_oidc",
        "clarity",
    ]
    scopes = "openid profile email"

    log.info("── Auth: trying PingFederate ROPC grant …")
    access_token = None
    for pf_url in pf_token_urls:
        for cid in client_ids:
            try:
                r = session.post(
                    pf_url,
                    data={
                        "grant_type": "password",
                        "username": username,
                        "password": password,
                        "client_id": cid,
                        "scope": scopes,
                    },
                    headers={"Accept": "application/json"},
                    timeout=30,
                    allow_redirects=False,
                )
                if debug:
                    log.debug("  ROPC %s (client=%s) → HTTP %d  body=%s",
                              pf_url, cid, r.status_code, r.text[:300])
                if r.status_code == 200:
                    j = r.json()
                    access_token = j.get("access_token")
                    if access_token:
                        log.info("  ✓ ROPC succeeded (client_id=%s).", cid)
                        break
                elif r.status_code == 400:
                    body = r.json() if r.text.strip().startswith("{") else {}
                    err = body.get("error", "")
                    if err in ("invalid_client", "unauthorized_client"):
                        if debug:
                            log.debug("  ROPC not allowed for client_id=%s.", cid)
                        continue
                    # bad credentials
                    if err == "invalid_grant":
                        raise AuthError(
                            "Login rejected — check FREDDIE_MAC_USERNAME / "
                            "FREDDIE_MAC_PASSWORD."
                        )
            except AuthError:
                raise
            except requests.RequestException as exc:
                if debug:
                    log.debug("  ROPC request error: %s", exc)
        if access_token:
            break

    if access_token:
        session.headers["Authorization"] = f"Bearer {access_token}"
        return session

    log.warning("  ROPC grant unavailable — falling back to redirect-based SSO.")

    # ── Approach 3: Redirect / form-based SSO ─────────────────────────────
    log.info("── Auth: redirect-based SSO …")
    r1 = session.get(f"{CRT_BASE}/", allow_redirects=True, timeout=30)
    if debug:
        log.debug("  After redirect → %s  (HTTP %d)", r1.url, r1.status_code)
        # Avoid CookieConflictError from duplicate Cloudflare __cf_bm cookies
        log.debug("  Cookies so far: %s", [(c.name, c.value) for c in session.cookies])

    if r1.status_code in (200, 204) and "authorization.oauth2" not in r1.url:
        log.info("  ✓ Already authenticated via cookies.")
        return session

    if r1.status_code == 401:
        raise AuthError(
            "Portal returned 401 — PingAccess is protecting all endpoints with Bearer tokens.\n"
            "The ROPC grant is not enabled for this OAuth2 client, so credentials alone\n"
            "cannot obtain a token programmatically without a browser.\n\n"
            "━━  HOW TO GET YOUR TOKEN  ━━\n"
            "  1. Open https://claritydownload.fmapps.freddiemac.com/CRT/#/sflld in Chrome.\n"
            "  2. Log in with your Freddie Mac credentials.\n"
            "  3. Open DevTools (F12) → Network tab → filter by 'Fetch/XHR'.\n"
            "  4. Reload the page or click on a deal to trigger an API call.\n"
            "  5. Click any request to claritydownload.fmapps.freddiemac.com → Headers.\n"
            "  6. Copy the value of the 'Authorization' request header (it starts with 'Bearer ').\n"
            "  7. Run:\n"
            "       python scripts/upload_freddie_crt_to_gcs.py \\\n"
            "         --token 'eyJ...' --list\n"
            "     OR add to .env:\n"
            "       FREDDIE_MAC_TOKEN=eyJ...\n"
            "     then run:  make crt-list\n\n"
            "Note: tokens typically expire in 1 hour — refresh from DevTools if needed.\n"
        )

    # Portal redirected to PF login page — parse and submit the form
    if "authorization.oauth2" in r1.url or ("form" in r1.text.lower() and "password" in r1.text.lower()):
        form_action, field_map = _parse_pf_login_form(r1.text, r1.url, username, password, debug)
        log.info("── Auth: POST credentials → %s", form_action)

        r2 = session.post(form_action, data=field_map, allow_redirects=True, timeout=30)
        if debug:
            log.debug("  POST response URL: %s  (HTTP %d)", r2.url, r2.status_code)
            _log_html_snippet(r2.text, "error")

        _check_pf_error(r2)

        # Extract access_token from the OIDC callback fragment / response body
        for pattern in (r'"access_token"\s*:\s*"([^"]+)"', r'access_token=([^&"]+)'):
            m = re.search(pattern, r2.text)
            if m:
                session.headers["Authorization"] = f"Bearer {m.group(1)}"
                log.info("  ✓ Bearer token extracted from OIDC callback.")
                break

        probe = session.head(f"{CRT_BASE}/", timeout=15, allow_redirects=True)
        if probe.status_code in (401, 403):
            raise AuthError(
                f"Authenticated with SSO but portal returned HTTP {probe.status_code}. "
                "Your account may not have CRT Data Intelligence access, OR "
                "the session uses Bearer tokens not visible in cookies.\n"
                "Try --token with a token from DevTools."
            )

        log.info("  ✓ Session established. Cookies: %s", [c.name for c in session.cookies])
        return session

    # Unknown state
    if debug:
        log.debug("Unexpected auth state. URL: %s  Status: %d", r1.url, r1.status_code)
        log.debug("HTML snippet:\n%s", r1.text[:2000])
    raise AuthError(
        f"Auth flow reached an unexpected state (HTTP {r1.status_code}, url={r1.url}). "
        "Run with --debug or use --token."
    )


def _parse_pf_login_form(
    html: str,
    base_url: str,
    username: str,
    password: str,
    debug: bool,
) -> Tuple[str, Dict[str, str]]:
    """Extract form action + all input fields from a PingFederate login page."""
    form_match = re.search(r'(<form\b[^>]*>.*?</form>)', html, re.IGNORECASE | re.DOTALL)
    form_html = form_match.group(1) if form_match else html

    action_match = re.search(r'action=["\']([^"\']+)["\']', form_html, re.IGNORECASE)
    if not action_match:
        if debug:
            log.debug("HTML (first 3000 chars):\n%s", html[:3000])
        raise AuthError(
            "Could not find a <form action=...> on the login page. "
            "Run with --debug to see the raw HTML."
        )
    action_raw = action_match.group(1).strip()
    action = action_raw if action_raw.startswith("http") else urllib.parse.urljoin(base_url, action_raw)

    field_map: Dict[str, str] = {}
    for m in re.finditer(
        r'<input\b[^>]*name=["\']([^"\']+)["\'][^>]*(?:value=["\']([^"\']*)["\'])?[^>]*>',
        form_html, re.IGNORECASE,
    ):
        field_map[m.group(1)] = m.group(2) or ""
    for m in re.finditer(
        r'<input\b[^>]*value=["\']([^"\']*)["\'][^>]*name=["\']([^"\']+)["\'][^>]*>',
        form_html, re.IGNORECASE,
    ):
        if m.group(2) not in field_map:
            field_map[m.group(2)] = m.group(1)

    if debug:
        log.debug("  Raw fields from form: %s", list(field_map.keys()))

    username_set = password_set = False
    for key in list(field_map.keys()):
        if not username_set and key.lower() in [f.lower() for f in PF_USERNAME_FIELDS]:
            field_map[key] = username
            username_set = True
        if not password_set and key.lower() in [f.lower() for f in PF_PASSWORD_FIELDS]:
            field_map[key] = password
            password_set = True

    # Fallback: type="text" / type="password"
    if not username_set or not password_set:
        log.warning("Standard field names not detected (%s). Using type-based fallback.",
                    list(field_map.keys()))
        for m in re.finditer(
            r'<input\b[^>]*type=["\'](\w+)["\'][^>]*name=["\']([^"\']+)["\'][^>]*>',
            form_html, re.IGNORECASE,
        ):
            itype, iname = m.group(1).lower(), m.group(2)
            if itype == "text" and not username_set:
                field_map[iname] = username
                username_set = True
            if itype == "password" and not password_set:
                field_map[iname] = password
                password_set = True

    if not username_set:
        raise AuthError("No username field found — run with --debug to inspect the HTML.")
    if not password_set:
        raise AuthError("No password field found — run with --debug to inspect the HTML.")

    return action, field_map


def _check_pf_error(resp: requests.Response) -> None:
    body = resp.text.lower()
    if any(p in body for p in (
        "invalid username or password", "authentication failed",
        "incorrect password", "invalid credentials", "login failed",
        "your username or password",
    )):
        raise AuthError("Login rejected — check FREDDIE_MAC_USERNAME / FREDDIE_MAC_PASSWORD.")
    if "authorization.oauth2" in resp.url or (
        "form" in body and "password" in body and PORTAL_BASE not in resp.url
    ):
        raise AuthError(
            f"Login did not complete — still on login page ({resp.url}). "
            "Check your credentials or run with --debug."
        )


def _log_html_snippet(html: str, keyword: str) -> None:
    lines = html.splitlines()
    for i, line in enumerate(lines):
        if keyword.lower() in line.lower():
            log.debug("  HTML around '%s':\n    %s", keyword,
                      "\n    ".join(lines[max(0, i-3): i+4]))
            break


# ──────────────────────────────────────────────────────────────────────────────
# API discovery
# ──────────────────────────────────────────────────────────────────────────────

def discover_api(session: requests.Session, debug: bool = False) -> Tuple[str, str, str]:
    """Probe candidate API base paths to find the deals/files/download endpoints."""
    log.info("Probing API endpoints …")
    json_headers = {"Accept": "application/json, */*", "X-Requested-With": "XMLHttpRequest"}

    for base in API_CANDIDATES:
        for idx, path in enumerate(DEALS_PATHS):
            url = base + path
            try:
                r = session.get(url, headers=json_headers, timeout=15)
                if debug:
                    log.debug("  %s → HTTP %d  (%d bytes)", url, r.status_code, len(r.content))
                if r.status_code == 200 and ("json" in r.headers.get("Content-Type", "") or _looks_like_json(r.text)):
                    log.info("  ✓ Deals endpoint: %s", url)
                    return url, base + FILES_PATHS[idx % len(FILES_PATHS)], base + DL_PATHS[idx % len(DL_PATHS)]
            except requests.RequestException as e:
                if debug:
                    log.debug("  %s → %s", url, e)

    raise APIDiscoveryError(
        "Could not auto-discover the portal API.\n\n"
        "RESOLUTION:\n"
        "  1. Open https://claritydownload.fmapps.freddiemac.com/CRT/#/sflld in Chrome.\n"
        "  2. Open DevTools → Network → filter XHR/Fetch.\n"
        "  3. Note the API URLs when the file list loads.\n"
        "  4. Use --direct-url <URL> to download a specific file directly.\n"
        "  Run with --debug for detailed probe output."
    )


def _looks_like_json(text: str) -> bool:
    s = text.strip()
    return s.startswith("{") or s.startswith("[")


# ──────────────────────────────────────────────────────────────────────────────
# Catalogue helpers
# ──────────────────────────────────────────────────────────────────────────────

def list_deals(
    session: requests.Session,
    deals_url: str,
    deal_filter: Optional[str] = None,
    debug: bool = False,
) -> List[Dict]:
    resp = _api_get(session, deals_url)
    try:
        deals: List[Dict] = resp.json()
        if isinstance(deals, dict):
            deals = deals.get("data") or deals.get("deals") or deals.get("results") or []
    except Exception:
        if debug:
            log.debug("Response body: %s", resp.text[:1000])
        raise APIDiscoveryError(f"Deals endpoint returned non-JSON: {resp.text[:200]}")

    if deal_filter:
        deals = [d for d in deals if deal_filter.lower() in str(d).lower()]

    log.info("Found %d deal(s)%s.", len(deals),
             f" matching '{deal_filter}'" if deal_filter else "")
    return deals


def list_files_for_deal(
    session: requests.Session,
    files_url: str,
    deal: Dict,
    year_filter: Optional[int] = None,
) -> List[Dict]:
    deal_id = (
        deal.get("id") or deal.get("dealId") or deal.get("deal_id")
        or deal.get("name") or deal.get("dealName")
    )
    resp = _api_get(session, files_url, params={"dealId": deal_id, "id": deal_id})
    try:
        files: List[Dict] = resp.json()
        if isinstance(files, dict):
            files = files.get("data") or files.get("files") or files.get("results") or []
    except Exception:
        return []

    if year_filter:
        files = [
            f for f in files
            if str(year_filter) in f.get("name", "") + f.get("period", "") + str(f)
        ]
    return files


# ──────────────────────────────────────────────────────────────────────────────
# HTTP helpers
# ──────────────────────────────────────────────────────────────────────────────

def _api_get(
    session: requests.Session,
    url: str,
    params: Optional[Dict] = None,
    stream: bool = False,
    extra_headers: Optional[Dict] = None,
) -> requests.Response:
    headers = {"Accept": "application/json, */*", "X-Requested-With": "XMLHttpRequest"}
    if extra_headers:
        headers.update(extra_headers)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(url, params=params, headers=headers,
                            stream=stream, timeout=120)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", RETRY_BACKOFF * attempt))
                log.warning("Rate-limited — waiting %ds …", wait)
                time.sleep(wait)
                continue
            return r
        except requests.RequestException as exc:
            if attempt == MAX_RETRIES:
                raise
            log.warning("Request error (attempt %d/%d): %s", attempt, MAX_RETRIES, exc)
            time.sleep(RETRY_BACKOFF * attempt)
    raise RuntimeError("Exhausted retries")


# ──────────────────────────────────────────────────────────────────────────────
# Download
# ──────────────────────────────────────────────────────────────────────────────

def download_file(
    session: requests.Session,
    url: str,
    file_name: str,
    dest_dir: Path,
    debug: bool = False,
) -> Path:
    dest = dest_dir / file_name
    if dest.exists():
        log.info("  Cached locally: %s", dest.name)
        return dest

    log.info("  Downloading → %s", file_name)
    if debug:
        log.debug("  URL: %s", url)

    with _api_get(session, url, stream=True,
                  extra_headers={"Accept": "application/octet-stream, */*"}) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", 0))
        done = 0
        with open(dest, "wb") as fh:
            for chunk in r.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r    {done/1e6:.1f} / {total/1e6:.1f} MB "
                          f"({done/total*100:.0f}%)", end="", flush=True)
        print()

    log.info("  Saved %s (%.1f MB)", dest.name, dest.stat().st_size / 1e6)
    return dest


# ──────────────────────────────────────────────────────────────────────────────
# Convert: ZIP/CSV → Parquet
# ──────────────────────────────────────────────────────────────────────────────

def _iter_csv_files_from_zip(
    zip_path: Path,
    work_dir: Path,
    depth: int = 0,
) -> Iterator[Tuple[str, Path]]:
    """
    Generator that extracts CSV/TXT files from a (possibly nested) ZIP
    to ``work_dir`` on disk **one at a time**.

    Yields ``(original_name_inside_zip, disk_path)``.
    The caller **must** delete ``disk_path`` when done (or the generator
    will not accumulate open file handles, but the disk file stays).

    Inner ZIPs are streamed to a temp file, iterated, then deleted —
    no ZIP or CSV content is ever loaded into RAM as a whole.
    """
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            lower = name.lower()
            fname = Path(name).name
            if lower.endswith((".csv", ".txt")):
                dest = work_dir / fname
                log.info("  %sExtracting: %s", "  " * depth, fname)
                with zf.open(name) as src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst, length=1 << 20)  # 1 MB at a time
                yield name, dest
                # caller deletes dest when ready
            elif lower.endswith(".zip") and depth < 3:
                inner_path = work_dir / fname
                log.info("  %sExtracting nested ZIP: %s", "  " * depth, fname)
                with zf.open(name) as src, open(inner_path, "wb") as dst:
                    shutil.copyfileobj(src, dst, length=1 << 20)
                yield from _iter_csv_files_from_zip(inner_path, work_dir, depth + 1)
                inner_path.unlink(missing_ok=True)


def convert_to_parquet_streaming(
    csv_path: Path,
    csv_name: str,
    out_dir: Path,
) -> Iterator[Path]:
    """
    Convert a single on-disk CSV/TXT file to Parquet parts, yielding each
    part path as it is written.  The caller uploads and deletes each part
    before the next part is yielded — keeping at most one parquet file on
    disk at any time.
    """
    col_names = _freddie_cols_for(csv_name)
    if col_names:
        log.info("  Converting %s → Parquet (Freddie Mac schema, %d cols) …",
                 csv_name, len(col_names))
    else:
        log.info("  Converting %s → Parquet …", csv_name)

    stem = Path(csv_name).stem
    idx = 0
    with open(csv_path, "rb") as fh:
        for chunk in _read_csv_chunks(fh, CHUNK_ROWS, col_names=col_names):
            dest = out_dir / f"{stem}_part{idx:04d}.parquet"
            _write_parquet(chunk, dest)
            log.info("    part%04d → %s rows  (%.1f MB on disk)",
                     idx, f"{len(chunk):,}", dest.stat().st_size / 1e6)
            del chunk  # free the DataFrame memory before upload
            yield dest
            idx += 1


def convert_to_parquet(raw_path: Path, out_dir: Path) -> List[Path]:
    """Legacy wrapper used by the portal download path.
    Writes all parquet parts and returns their paths.
    For local-dir mode use the streaming variant instead.
    """
    out: List[Path] = []
    if raw_path.suffix.lower() not in (".zip", ".csv", ".txt"):
        log.warning("  Unrecognised file type %s — skipping.", raw_path.suffix)
        return out
    if raw_path.suffix.lower() == ".zip":
        work_dir = out_dir / "_extract"
        work_dir.mkdir(exist_ok=True)
        for csv_name, csv_path in _iter_csv_files_from_zip(raw_path, work_dir):
            try:
                for pq in convert_to_parquet_streaming(csv_path, csv_name, out_dir):
                    out.append(pq)
            finally:
                csv_path.unlink(missing_ok=True)
    else:
        for pq in convert_to_parquet_streaming(raw_path, raw_path.name, out_dir):
            out.append(pq)
    return out


def _read_csv_chunks(
    stream: Any,
    chunk_size: int,
    col_names: Optional[List[str]] = None,
) -> Iterator[pd.DataFrame]:
    """Try pipe delimiter first (Freddie Mac standard), then comma, then tab.

    When ``col_names`` is supplied the file is read with ``header=None``
    so that the first data row is not misinterpreted as a header.
    """
    for delim in ("|", ",", "\t"):
        try:
            read_kwargs: Dict[str, Any] = dict(
                sep=delim, low_memory=False,
                chunksize=chunk_size, encoding="utf-8", on_bad_lines="warn",
            )
            if col_names:
                read_kwargs["header"] = None
                read_kwargs["names"] = col_names
            reader = pd.read_csv(stream, **read_kwargs)
            yielded = False
            for chunk in reader:
                if chunk.empty or (chunk.shape[1] < 2 and not yielded):
                    break
                yielded = True
                yield chunk
            if yielded:
                return
        except Exception:
            if hasattr(stream, "seek"):
                stream.seek(0)
    raise ValueError("Cannot parse CSV with |, comma, or tab delimiter.")


def _write_parquet(df: pd.DataFrame, path: Path) -> None:
    for col in df.columns:
        try:
            df[col] = pd.to_numeric(df[col], errors="ignore")
        except Exception:
            pass
    pq.write_table(
        pa.Table.from_pandas(df, preserve_index=False),
        str(path),
        compression=PARQUET_COMPRESSION,
    )


# ──────────────────────────────────────────────────────────────────────────────
# GCS upload
# ──────────────────────────────────────────────────────────────────────────────

def gcs_upload(
    client: storage.Client,
    local: Path,
    bucket: str,
    blob_name: str,
    skip_existing: bool,
) -> str:
    b = client.bucket(bucket)
    blob = b.blob(blob_name)
    if skip_existing and blob.exists():
        uri = f"gs://{bucket}/{blob_name}"
        log.info("  GCS skip (exists): %s", uri)
        return uri
    log.info("  Uploading → gs://%s/%s  (%.1f MB)", bucket, blob_name,
             local.stat().st_size / 1e6)
    blob.upload_from_filename(str(local))
    return f"gs://{bucket}/{blob_name}"


def gcs_upload_json(client: storage.Client, bucket: str, blob_name: str, obj: Dict) -> str:
    b = client.bucket(bucket)
    blob = b.blob(blob_name)
    blob.upload_from_string(
        json.dumps(obj, indent=2, default=str).encode(),
        content_type="application/json",
    )
    return f"gs://{bucket}/{blob_name}"


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Freddie Mac CRT SFLLD → GCS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    auth = p.add_argument_group("Auth")
    auth.add_argument("--username", default=os.getenv("FREDDIE_MAC_USERNAME", ""))
    auth.add_argument("--password", default=os.getenv("FREDDIE_MAC_PASSWORD", ""))
    auth.add_argument(
        "--token",
        default=os.getenv("FREDDIE_MAC_TOKEN", ""),
        help=(
            "Pre-obtained Bearer access token. Skips ROPC / SSO auth completely. "
            "Obtain from Chrome DevTools → Network → any XHR request → "
            "Authorization header (strip the 'Bearer ' prefix)."
        ),
    )

    filt = p.add_argument_group("Filter")
    filt.add_argument("--deal",  default="", help="Filter deals by name substring")
    filt.add_argument("--year",  type=int,   help="Filter files by year, e.g. 2015")
    filt.add_argument("--list",  action="store_true",
                      help="List available deals/files; do not download or upload")

    gcs = p.add_argument_group("GCS")
    gcs.add_argument("--bucket",  default=os.getenv("GCS_BUCKET", ""))
    gcs.add_argument("--project", default=os.getenv("GCP_PROJECT_ID", ""))
    gcs.add_argument("--prefix",  default=os.getenv("GCS_CRT_PREFIX", "crt/sflld"))
    gcs.add_argument("--skip-existing", action="store_true",
                     help="Skip GCS upload if blob already exists")

    fb = p.add_argument_group("Direct-URL fallback")
    fb.add_argument("--direct-url", default="",
                    help="Download a specific file by URL (bypasses API discovery)")
    fb.add_argument("--out-name",   default="sflld_file",
                    help="Local filename for --direct-url download")

    misc = p.add_argument_group("Misc")
    misc.add_argument("--local-dir", default=None,
                      help="Process locally stored ZIP files instead of downloading from the "
                           "portal. Point to the directory containing historical_data_YYYY.zip "
                           "files (e.g. data/Freddiemac/). Auth credentials are NOT required "
                           "in this mode. GCS upload is optional — omit --bucket to convert "
                           "to Parquet locally only.")
    misc.add_argument("--raw-dir",   default=None,
                      help="Directory to stage raw downloads (default: temp)")
    misc.add_argument("--keep-raw",  action="store_true",
                      help="Keep raw ZIP/CSV files after Parquet conversion")
    misc.add_argument("--debug",     action="store_true",
                      help="Enable verbose debug logging (shows HTML, HTTP probes)")

    return p.parse_args()


# ──────────────────────────────────────────────────────────────────────────────
# Local-file pipeline helper
# ──────────────────────────────────────────────────────────────────────────────

def _process_one_local(
    zip_path: Path,
    raw_dir: Path,
    gcs_client: Optional[storage.Client],
    bucket: str,
    prefix: str,
    skip_existing: bool,
    keep_raw: bool,
    debug: bool,
) -> Dict[str, Any]:
    """
    Memory-efficient local pipeline for one annual ZIP:

    For each quarterly ZIP inside the annual ZIP:
      1. Stream-extract the quarterly ZIP to disk (no RAM for ZIP bytes)
      2. Stream-extract each TXT to disk (one file at a time)
      3. Convert TXT → Parquet in CHUNK_ROWS-row chunks
      4. Upload each Parquet chunk to GCS immediately
      5. Delete the Parquet chunk from disk
      6. Delete the TXT from disk
      7. Delete the quarterly ZIP from disk

    Peak disk use ≈ one inner ZIP + one TXT + one Parquet chunk.
    Peak RAM use  ≈ one Parquet chunk (CHUNK_ROWS × ~50 bytes ≈ 25 MB).
    """
    deal_name = zip_path.stem   # e.g. 'historical_data_2015'
    file_name = zip_path.name
    entry: Dict[str, Any] = {
        "deal": deal_name, "file": file_name,
        "gcs_blobs": [], "status": "pending",
    }

    work_dir = raw_dir / deal_name
    work_dir.mkdir(parents=True, exist_ok=True)
    total_parts = 0

    try:
        for csv_name, csv_path in _iter_csv_files_from_zip(zip_path, work_dir):
            try:
                stem = Path(csv_name).stem
                for pq_path in convert_to_parquet_streaming(csv_path, csv_name, work_dir):
                    try:
                        if gcs_client:
                            blob_name = f"{prefix}/{deal_name}/{stem}/{pq_path.name}"
                            uri = gcs_upload(
                                gcs_client, pq_path, bucket, blob_name, skip_existing
                            )
                            entry["gcs_blobs"].append(uri)
                        total_parts += 1
                    finally:
                        if not keep_raw:
                            pq_path.unlink(missing_ok=True)  # delete parquet immediately
            finally:
                csv_path.unlink(missing_ok=True)  # delete TXT immediately

        if total_parts == 0:
            entry["status"] = "skipped_no_parquet"
        else:
            entry["status"] = "success"
            entry["parquet_parts"] = total_parts
            log.info("  ✓ %d part(s) %s", total_parts,
                     "uploaded to GCS" if gcs_client else "converted locally")

    except Exception as exc:
        log.error("  FAILED: %s", exc, exc_info=debug)
        entry["status"] = "error"
        entry["error"] = str(exc)
    finally:
        # Always clean up the work dir (extract staging area)
        if not keep_raw and work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)

    return entry


# ──────────────────────────────────────────────────────────────────────────────
# Portal pipeline helper
# ──────────────────────────────────────────────────────────────────────────────

def _process_one(
    session: requests.Session,
    dl_url: str,
    file_name: str,
    deal_name: str,
    raw_dir: Path,
    gcs_client: Optional[storage.Client],
    bucket: str,
    prefix: str,
    skip_existing: bool,
    keep_raw: bool,
    debug: bool,
) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "deal": deal_name, "file": file_name,
        "gcs_blobs": [], "status": "pending",
    }
    try:
        deal_dir = raw_dir / deal_name
        deal_dir.mkdir(parents=True, exist_ok=True)
        raw_path = download_file(session, dl_url, file_name, deal_dir, debug)

        pq_dir = deal_dir / "parquet"
        pq_dir.mkdir(exist_ok=True)
        pq_files = convert_to_parquet(raw_path, pq_dir)

        if not pq_files:
            entry["status"] = "skipped_no_parquet"
            return entry

        if gcs_client:
            stem = Path(file_name).stem
            for pq_path in pq_files:
                blob_name = f"{prefix}/{deal_name}/{stem}/{pq_path.name}"
                uri = gcs_upload(gcs_client, pq_path, bucket, blob_name, skip_existing)
                entry["gcs_blobs"].append(uri)

        if not keep_raw:
            raw_path.unlink(missing_ok=True)
            for pq_path in pq_files:
                pq_path.unlink(missing_ok=True)

        entry["status"] = "success"
        entry["parquet_parts"] = len(pq_files)
        log.info("  ✓ %d part(s) %s", len(pq_files),
                 "uploaded to GCS" if gcs_client else "converted locally")

    except Exception as exc:
        log.error("  FAILED: %s", exc, exc_info=debug)
        entry["status"] = "error"
        entry["error"] = str(exc)
    return entry


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # ── Validate ──────────────────────────────────────────────────────────────
    if not args.local_dir:  # auth not needed for local-dir mode
        if not args.token:
            if not args.username:
                sys.exit("ERROR: --username / FREDDIE_MAC_USERNAME is required (or supply --token).")
            if not args.password:
                sys.exit("ERROR: --password / FREDDIE_MAC_PASSWORD is required (or supply --token).")
    if not args.list and not args.direct_url and not args.local_dir:
        if not args.bucket:
            sys.exit("ERROR: --bucket / GCS_BUCKET is required.")
        if not args.project:
            sys.exit("ERROR: --project / GCP_PROJECT_ID is required.")

    # ── Staging dir ───────────────────────────────────────────────────────────
    use_tmpdir = args.raw_dir is None
    raw_dir = Path(args.raw_dir) if args.raw_dir else Path(
        tempfile.mkdtemp(prefix="freddie_crt_")
    )
    raw_dir.mkdir(parents=True, exist_ok=True)

    gcs_client = storage.Client(project=args.project) if args.bucket else None

    # ── Local-dir mode: process pre-downloaded ZIP files ─────────────────────
    if args.local_dir:
        local_dir = Path(args.local_dir)
        if not local_dir.is_dir():
            sys.exit(f"ERROR: --local-dir '{local_dir}' is not a directory.")

        zip_files = sorted(local_dir.glob("*.zip"))
        if not zip_files:
            sys.exit(f"ERROR: No .zip files found in '{local_dir}'.")

        if args.year:
            zip_files = [z for z in zip_files if str(args.year) in z.name]
            if not zip_files:
                sys.exit(f"ERROR: No .zip files matching year {args.year} in '{local_dir}'.")

        log.info("═" * 65)
        log.info("Freddie Mac CRT SFLLD — Local → GCS Pipeline")
        log.info("  Source  : %s", local_dir.resolve())
        log.info("  Files   : %d ZIP file(s)", len(zip_files))
        if gcs_client:
            log.info("  Bucket  : gs://%s/%s", args.bucket, args.prefix)
        else:
            log.info("  GCS     : (disabled — no --bucket supplied, Parquet only)")
        log.info("═" * 65)

        t0 = time.perf_counter()
        manifest_entries: List[Dict] = []

        for zip_path in zip_files:
            log.info("")
            log.info("─" * 65)
            log.info("Processing: %s", zip_path.name)
            log.info("─" * 65)
            entry = _process_one_local(
                zip_path=zip_path,
                raw_dir=raw_dir,
                gcs_client=gcs_client,
                bucket=args.bucket,
                prefix=args.prefix,
                skip_existing=args.skip_existing,
                keep_raw=args.keep_raw,
                debug=args.debug,
            )
            manifest_entries.append(entry)

        elapsed = time.perf_counter() - t0
        manifest = {
            "pipeline":         "freddie_mac_crt_sflld_local_to_gcs",
            "generated_at":     pd.Timestamp.utcnow().isoformat(),
            "source_dir":       str(local_dir.resolve()),
            "gcp_project":      args.project,
            "bucket":           args.bucket,
            "gcs_prefix":       args.prefix,
            "year_filter":      args.year,
            "total_files":      len(zip_files),
            "success":          sum(1 for e in manifest_entries if e["status"] == "success"),
            "skipped":          sum(1 for e in manifest_entries if e["status"].startswith("skip")),
            "errors":           sum(1 for e in manifest_entries if e["status"] == "error"),
            "duration_seconds": round(elapsed, 2),
            "files":            manifest_entries,
        }

        if gcs_client:
            uri = gcs_upload_json(gcs_client, args.bucket, f"{args.prefix}/manifest.json", manifest)
            log.info("  Manifest: %s", uri)

        if use_tmpdir and not args.keep_raw:
            shutil.rmtree(raw_dir, ignore_errors=True)

        log.info("")
        log.info("═" * 65)
        log.info("Pipeline complete!")
        log.info("  Files   : %d  ✓%d  skip%d  ✗%d",
                 len(zip_files), manifest["success"], manifest["skipped"], manifest["errors"])
        log.info("  Time    : %.1f s", elapsed)
        if gcs_client:
            log.info("  Query   : pandas.read_parquet('gs://%s/%s/', "
                     "storage_options={'project': '%s'})",
                     args.bucket, args.prefix, args.project)
        log.info("═" * 65)

        if manifest["errors"]:
            sys.exit(1)
        return

    # ── Portal mode banner ───────────────────────────────────────────────────
    log.info("═" * 65)
    log.info("Freddie Mac CRT SFLLD → GCS Upload Pipeline")
    log.info("  Portal  : %s/#/sflld", CRT_BASE)
    log.info("  Deal    : %s", args.deal or "(all)")
    log.info("  Year    : %s", args.year or "(all)")
    if not args.list:
        log.info("  Bucket  : gs://%s/%s", args.bucket, args.prefix)
    log.info("═" * 65)

    # ── Authenticate (portal modes only) ──────────────────────────────────────
    try:
        session = build_session(
            args.username, args.password,
            token=args.token,
            debug=args.debug,
        )
    except AuthError as exc:
        sys.exit(f"ERROR: {exc}")

    # ── Direct-URL mode ───────────────────────────────────────────────────────
    if args.direct_url:
        log.info("Direct-URL mode: %s", args.direct_url)
        file_name = args.out_name if "." in args.out_name else args.out_name + ".zip"
        entry = _process_one(
            session=session, dl_url=args.direct_url, file_name=file_name,
            deal_name="direct", raw_dir=raw_dir, gcs_client=gcs_client,
            bucket=args.bucket, prefix=args.prefix,
            skip_existing=args.skip_existing, keep_raw=args.keep_raw, debug=args.debug,
        )
        log.info("Status: %s", entry["status"])
        for uri in entry.get("gcs_blobs", []):
            log.info("  %s", uri)
        return

    # ── API discovery ─────────────────────────────────────────────────────────
    try:
        deals_url, files_url, dl_base = discover_api(session, debug=args.debug)
    except APIDiscoveryError as e:
        log.error("\n%s", e)
        sys.exit(1)

    # ── List available deals ──────────────────────────────────────────────────
    deals = list_deals(session, deals_url, deal_filter=args.deal or None, debug=args.debug)
    if not deals:
        log.warning("No deals found. Check credentials and deal filter.")
        sys.exit(0)

    all_files: List[Dict] = []
    for deal in deals:
        deal_name = (
            deal.get("name") or deal.get("dealName") or deal.get("dealId", "unknown")
        )
        files = list_files_for_deal(session, files_url, deal, year_filter=args.year)
        for f in files:
            f["_deal_name"] = deal_name
            f["_dl_url"] = (
                f.get("downloadUrl") or f.get("url") or f.get("link")
                or f"{dl_base}/{f.get('id') or f.get('fileId', '')}"
            )
        all_files.extend(files)
        log.info("  %-35s → %d file(s)", deal_name, len(files))

    if args.list:
        print(f"\n{'Deal':<35} {'File':<45} {'Size':>10}")
        print("─" * 92)
        for f in all_files:
            sz = f.get("size", 0)
            sz_str = f"{sz/1e6:.1f} MB" if sz else "unknown"
            name = f.get("name") or f.get("fileName") or "(unnamed)"
            print(f"{f['_deal_name']:<35} {name:<45} {sz_str:>10}")
        print(f"\nTotal: {len(all_files)} file(s) across {len(deals)} deal(s).")
        return

    if not all_files:
        log.warning("No files found — try removing --year or --deal filters.")
        sys.exit(0)

    # ── Process each file ─────────────────────────────────────────────────────
    t0 = time.perf_counter()
    manifest_entries: List[Dict] = []

    for fm in all_files:
        file_name = fm.get("name") or fm.get("fileName") or f"{fm.get('id','?')}.zip"
        deal_name = fm["_deal_name"]
        dl_url    = fm["_dl_url"]

        log.info("")
        log.info("─" * 65)
        log.info("Processing: %s / %s", deal_name, file_name)
        log.info("─" * 65)

        entry = _process_one(
            session=session, dl_url=dl_url, file_name=file_name,
            deal_name=deal_name, raw_dir=raw_dir, gcs_client=gcs_client,
            bucket=args.bucket, prefix=args.prefix,
            skip_existing=args.skip_existing, keep_raw=args.keep_raw, debug=args.debug,
        )
        manifest_entries.append(entry)

    # ── Upload manifest ───────────────────────────────────────────────────────
    elapsed = time.perf_counter() - t0
    manifest = {
        "pipeline":        "freddie_mac_crt_sflld_to_gcs",
        "generated_at":    pd.Timestamp.utcnow().isoformat(),
        "source_portal":   f"{CRT_BASE}/#/sflld",
        "gcp_project":     args.project,
        "bucket":          args.bucket,
        "gcs_prefix":      args.prefix,
        "deal_filter":     args.deal or None,
        "year_filter":     args.year,
        "total_files":     len(all_files),
        "success":         sum(1 for e in manifest_entries if e["status"] == "success"),
        "skipped":         sum(1 for e in manifest_entries if e["status"].startswith("skip")),
        "errors":          sum(1 for e in manifest_entries if e["status"] == "error"),
        "duration_seconds": round(elapsed, 2),
        "files":           manifest_entries,
    }

    if gcs_client:
        uri = gcs_upload_json(gcs_client, args.bucket, f"{args.prefix}/manifest.json", manifest)

    if use_tmpdir and not args.keep_raw:
        shutil.rmtree(raw_dir, ignore_errors=True)

    log.info("")
    log.info("═" * 65)
    log.info("Pipeline complete!")
    log.info("  Files   : %d  ✓%d  skip%d  ✗%d",
             len(all_files), manifest["success"], manifest["skipped"], manifest["errors"])
    log.info("  Time    : %.1f s", elapsed)
    if gcs_client:
        log.info("  Manifest: %s", uri)
        log.info("  Query   : pandas.read_parquet('gs://%s/%s/', "
                 "storage_options={'project': '%s'})",
                 args.bucket, args.prefix, args.project)
    log.info("═" * 65)

    if manifest["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
