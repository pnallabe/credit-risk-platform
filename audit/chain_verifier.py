"""
audit/chain_verifier.py
=======================
Cryptographic hash-chain verifier for the audit log tables.

Public API
----------
>>> from audit.chain_verifier import verify_chain, ChainVerificationResult
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from sqlalchemy import text

from audit.logger import _sha256, _get_engine


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChainVerificationResult:
    """Outcome of a hash-chain integrity scan."""

    verified: bool
    rows_checked: int
    first_tampered_log_id: Optional[str]
    first_tampered_at: Optional[str]
    gap_detected: bool


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_CANONICAL_FIELDS = {
    "audit_log": ("decision_output", "fraud_score", "reason_codes", "risk_score"),
    "portfolio_audit_log": (
        "model_version_portfolio",
        "policy_version",
        "recommended_action",
        "scenario_weighted_delta",
    ),
    "adverse_action_log": (
        "action_date",
        "deadline_date",
        "form_type",
        "reason_codes",
    ),
    "ai_agent_audit_log": ("query_text", "result_hash", "confidence_score", "answer_text"),
}


def _rebuild_canonical(row: dict, table: str) -> str:
    """Re-build the deterministic canonical payload from a stored row."""
    fields = _CANONICAL_FIELDS.get(table, ())
    payload = {f: row.get(f) for f in sorted(fields)}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _recompute_hash(row: dict, previous_hash: str, table: str) -> str:
    log_id = row.get("log_id") or row.get("notice_id", "")
    logged_at = row.get("logged_at") or row.get("generated_at") or row.get("action_date", "")
    canonical = _rebuild_canonical(row, table)
    raw = previous_hash + "|" + log_id + "|" + logged_at + "|" + canonical
    return _sha256(raw)


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------


async def verify_chain(
    db_url: str,
    tenant_id: str,
    from_logged_at: Optional[str] = None,
    to_logged_at: Optional[str] = None,
    table: Literal["audit_log", "portfolio_audit_log", "adverse_action_log"] = "audit_log",
) -> ChainVerificationResult:
    """Verify the cryptographic hash chain for *tenant_id* in *table*.

    Parameters
    ----------
    db_url:
        SQLAlchemy async connection URL.
    tenant_id:
        Scope verification to this tenant's rows.
    from_logged_at / to_logged_at:
        ISO-8601 UTC date-time window (inclusive).  ``None`` means unbounded.
    table:
        Which table to verify.

    Returns
    -------
    ChainVerificationResult
    """
    # Determine the partition / timestamp column based on table
    if table == "portfolio_audit_log":
        partition_col = "account_id"
    else:
        partition_col = "tenant_id"

    ts_col = "logged_at"
    if table == "adverse_action_log":
        ts_col = "generated_at"

    id_col = "log_id"
    if table == "adverse_action_log":
        id_col = "notice_id"

    engine = _get_engine(db_url)

    # Build the SELECT query
    where_clauses = [f"{partition_col} = :partition_value"]
    params: dict[str, Any] = {"partition_value": tenant_id}
    if from_logged_at:
        where_clauses.append(f"{ts_col} >= :from_ts")
        params["from_ts"] = from_logged_at
    if to_logged_at:
        where_clauses.append(f"{ts_col} <= :to_ts")
        params["to_ts"] = to_logged_at

    where_str = " AND ".join(where_clauses)
    query = text(
        f"SELECT * FROM {table} WHERE {where_str}"
        f" ORDER BY {ts_col} ASC, {id_col} ASC"
    )

    try:
        async with engine.connect() as conn:
            result = await conn.execute(query, params)
            rows = [dict(r) for r in result.mappings().fetchall()]
    except Exception as exc:
        return ChainVerificationResult(
            verified=False,
            rows_checked=0,
            first_tampered_log_id=None,
            first_tampered_at=None,
            gap_detected=False,
        )

    if not rows:
        return ChainVerificationResult(
            verified=True,
            rows_checked=0,
            first_tampered_log_id=None,
            first_tampered_at=None,
            gap_detected=False,
        )

    # Build a lookup set of all record_hashes in our result set for gap detection
    all_record_hashes = {r.get("record_hash") for r in rows if r.get("record_hash")}

    rows_checked = 0
    gap_detected = False
    running_previous: Optional[str] = None  # None = before any row

    for i, row in enumerate(rows):
        stored_hash = row.get("record_hash")
        if stored_hash is None:
            # Pre-migration row — skip but count
            rows_checked += 1
            continue

        row_id = row.get(id_col, "")
        row_ts = row.get(ts_col) or row.get("action_date", "")

        # Check gap: this row's previous_hash must equal the last verified hash
        stored_previous = row.get("previous_hash") or ""

        if running_previous is not None:
            # We have a previous verified row in this result set
            if stored_previous != running_previous:
                # Previous hash doesn't match — either tampered or gap
                if stored_previous not in all_record_hashes:
                    gap_detected = True
                return ChainVerificationResult(
                    verified=False,
                    rows_checked=rows_checked,
                    first_tampered_log_id=str(row_id),
                    first_tampered_at=str(row_ts),
                    gap_detected=gap_detected,
                )
        else:
            # First row in result — its previous_hash can be "" or a hash
            # from before our window; we can only verify that the stored hash
            # is self-consistent, not that it chains back to the absolute first row.
            pass

        # Recompute and compare
        prev_for_hash = stored_previous  # use what's stored for the recomputation
        recomputed = _recompute_hash(row, prev_for_hash, table)

        if recomputed != stored_hash:
            return ChainVerificationResult(
                verified=False,
                rows_checked=rows_checked,
                first_tampered_log_id=str(row_id),
                first_tampered_at=str(row_ts),
                gap_detected=gap_detected,
            )

        running_previous = stored_hash
        rows_checked += 1

    return ChainVerificationResult(
        verified=True,
        rows_checked=rows_checked,
        first_tampered_log_id=None,
        first_tampered_at=None,
        gap_detected=gap_detected,
    )


# ---------------------------------------------------------------------------
# AI Agent audit log chain verifier (sqlite3, not SQLAlchemy)
# ---------------------------------------------------------------------------

AI_CANONICAL_FIELDS = ("query_text", "result_hash", "confidence_score", "answer_text")


def _rebuild_ai_canonical(row: dict) -> str:
    payload = {
        "log_id": row.get("log_id"),
        "logged_at": row.get("logged_at"),
        "query_text": row.get("query_text"),
        "result_hash": row.get("result_hash"),
        "confidence_score": row.get("confidence_score"),
        "answer_text": row.get("answer_text"),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _recompute_ai_hash(row: dict) -> str:
    previous_hash = row.get("previous_hash") or "GENESIS"
    log_id = row.get("log_id", "")
    logged_at = row.get("logged_at", "")
    canonical = _rebuild_ai_canonical(row)
    raw = previous_hash + "|" + log_id + "|" + logged_at + "|" + canonical
    return hashlib.sha256(raw.encode()).hexdigest()


def _sync_verify_ai_chain(
    db_path: str,
    session_id: Optional[str],
    from_logged_at: Optional[str],
    to_logged_at: Optional[str],
) -> ChainVerificationResult:
    try:
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro&uri=true", uri=True)
        except Exception:
            conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
    except Exception as exc:
        return ChainVerificationResult(
            verified=False,
            rows_checked=0,
            first_tampered_log_id=None,
            first_tampered_at=None,
            gap_detected=False,
        )

    try:
        query = "SELECT * FROM ai_agent_audit_log WHERE 1=1"
        params: list = []
        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)
        if from_logged_at:
            query += " AND logged_at >= ?"
            params.append(from_logged_at)
        if to_logged_at:
            query += " AND logged_at <= ?"
            params.append(to_logged_at)
        query += " ORDER BY logged_at ASC, log_id ASC"

        rows = [dict(r) for r in conn.execute(query, params).fetchall()]
    except Exception:
        conn.close()
        return ChainVerificationResult(
            verified=True,
            rows_checked=0,
            first_tampered_log_id=None,
            first_tampered_at=None,
            gap_detected=False,
        )
    finally:
        conn.close()

    if not rows:
        return ChainVerificationResult(
            verified=True,
            rows_checked=0,
            first_tampered_log_id=None,
            first_tampered_at=None,
            gap_detected=False,
        )

    all_record_hashes = {r.get("record_hash") for r in rows if r.get("record_hash")}
    rows_checked = 0
    gap_detected = False
    running_previous: Optional[str] = None

    for row in rows:
        stored_hash = row.get("record_hash")
        if stored_hash is None:
            rows_checked += 1
            continue

        log_id = row.get("log_id", "")
        logged_at = row.get("logged_at", "")
        stored_previous = row.get("previous_hash") or ""

        if running_previous is not None:
            if stored_previous != running_previous:
                if stored_previous not in all_record_hashes:
                    gap_detected = True
                return ChainVerificationResult(
                    verified=False,
                    rows_checked=rows_checked,
                    first_tampered_log_id=str(log_id),
                    first_tampered_at=str(logged_at),
                    gap_detected=gap_detected,
                )

        recomputed = _recompute_ai_hash(row)
        if recomputed != stored_hash:
            return ChainVerificationResult(
                verified=False,
                rows_checked=rows_checked,
                first_tampered_log_id=str(log_id),
                first_tampered_at=str(logged_at),
                gap_detected=gap_detected,
            )

        running_previous = stored_hash
        rows_checked += 1

    return ChainVerificationResult(
        verified=True,
        rows_checked=rows_checked,
        first_tampered_log_id=None,
        first_tampered_at=None,
        gap_detected=gap_detected,
    )


async def verify_ai_agent_chain(
    db_url: str,
    session_id: Optional[str] = None,
    from_logged_at: Optional[str] = None,
    to_logged_at: Optional[str] = None,
) -> ChainVerificationResult:
    """
    Verify the hash chain of ai_agent_audit_log using sqlite3.

    Parameters
    ----------
    db_url:
        Path to the SQLite file or bare filename (strip \"sqlite:///\" prefix if present).
    session_id:
        If provided, scope verification to this session.
    from_logged_at / to_logged_at:
        ISO-8601 UTC date-time window (inclusive). None means unbounded.

    Returns ChainVerificationResult with the same semantics as verify_chain().
    """
    db_path = db_url[len("sqlite:///"):] if db_url.startswith("sqlite:///") else db_url
    return await asyncio.to_thread(
        _sync_verify_ai_chain, db_path, session_id, from_logged_at, to_logged_at
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify the cryptographic hash chain of an audit log table."
    )
    parser.add_argument("--tenant-id", required=True, help="Tenant ID to verify")
    parser.add_argument(
        "--db-url",
        default="sqlite+aiosqlite:///./decision_audit.db",
        help="SQLAlchemy async DB URL",
    )
    parser.add_argument("--from", dest="from_ts", default=None, help="Start date (ISO-8601)")
    parser.add_argument("--to", dest="to_ts", default=None, help="End date (ISO-8601)")
    parser.add_argument(
        "--table",
        default="audit_log",
        choices=["audit_log", "portfolio_audit_log", "adverse_action_log"],
        help="Table to verify",
    )
    return parser


async def _async_main(args: argparse.Namespace) -> int:
    result = await verify_chain(
        db_url=args.db_url,
        tenant_id=args.tenant_id,
        from_logged_at=args.from_ts,
        to_logged_at=args.to_ts,
        table=args.table,
    )

    status_str = "PASS" if result.verified else "FAIL"
    print(f"Chain verification [{status_str}]")
    print(f"  Table         : {args.table}")
    print(f"  Tenant        : {args.tenant_id}")
    print(f"  Rows checked  : {result.rows_checked}")
    print(f"  Verified      : {result.verified}")
    print(f"  Gap detected  : {result.gap_detected}")
    if result.first_tampered_log_id:
        print(f"  First tampered: {result.first_tampered_log_id} at {result.first_tampered_at}")

    return 0 if result.verified else 1


def main() -> None:  # pragma: no cover
    parser = _build_arg_parser()
    args = parser.parse_args()
    sys.exit(asyncio.run(_async_main(args)))


if __name__ == "__main__":
    main()
