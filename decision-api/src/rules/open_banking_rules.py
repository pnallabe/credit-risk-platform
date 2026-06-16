from typing import Dict, Any, List

def calculate_cash_flow_score(avg_monthly_inflow: float, avg_monthly_outflow: float) -> float:
    """Calculates a rudimentary cash flow score based on inflow/outflow ratio."""
    if avg_monthly_outflow == 0:
        return 100.0 if avg_monthly_inflow > 0 else 0.0
    ratio = avg_monthly_inflow / avg_monthly_outflow
    # Simple scoring: 1.0 ratio -> 50 score, 1.5 ratio -> 75 score, >= 2.0 ratio -> 100
    score = (ratio - 0.5) * 50
    return max(0.0, min(100.0, score))

def evaluate_open_banking_rules(bank_data_summary: Dict[str, Any]) -> Dict[str, Any]:
    """
    Dedicated decision engine ruleset for the OPEN_BANKING_SBX tenant.
    """
    avg_inflow = bank_data_summary.get("plaid_avg_monthly_inflow", 0.0)
    avg_outflow = bank_data_summary.get("plaid_avg_monthly_outflow", 0.0)
    nsfv_count = bank_data_summary.get("plaid_nsfv_count_90d", 0)
    gambling_txns = bank_data_summary.get("plaid_gambling_transactions", 0)
    payday_loan = bank_data_summary.get("plaid_payday_loan_detected", 0)

    cash_flow_score = calculate_cash_flow_score(avg_inflow, avg_outflow)

    decisions: List[Dict[str, Any]] = []

    # 1. Cash Flow Underwriting
    if cash_flow_score < 40.0:
        decisions.append({"rule": "cash_flow_underwriting", "status": "REJECT", "reason": "Insufficient cash flow buffer"})
    else:
        decisions.append({"rule": "cash_flow_underwriting", "status": "PASS", "reason": "Healthy cash flow"})

    # 2. Risk Indicators
    if nsfv_count > 2:
        decisions.append({"rule": "nsf_check", "status": "REJECT", "reason": "Too many non-sufficient funds events"})
    if payday_loan:
        decisions.append({"rule": "payday_loan_check", "status": "REJECT", "reason": "Payday loan detected"})

    # Aggregate decision
    final_status = "APPROVE"
    for d in decisions:
        if d["status"] == "REJECT":
            final_status = "REJECT"
            break

    return {
        "status": final_status,
        "cash_flow_score": cash_flow_score,
        "details": decisions
    }
