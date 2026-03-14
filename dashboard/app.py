"""
Credit Risk Platform — Streamlit Dashboard
==========================================
Interactive dashboard with 5 pages:
  1. Portfolio Overview
  2. Model Performance
  3. Drift Monitor
  4. Fair Lending
  5. Audit Lookup

Run with:
    streamlit run dashboard/app.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parents[1]))

import numpy as np
import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Page config (must be first Streamlit call)
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Credit Risk Platform",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Helpers / mock data
# ---------------------------------------------------------------------------


def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).strftime("%Y-%m-%d")


@st.cache_data(ttl=300)
def load_portfolio_data() -> pd.DataFrame:
    """Return mock portfolio decisions for the last 30 days."""
    rng = np.random.RandomState(42)
    n = 3000
    dates = pd.date_range(end=datetime.now(), periods=30, freq="D")
    decisions = rng.choice(["APPROVE", "REJECT", "MANUAL_REVIEW"], size=n,
                           p=[0.68, 0.25, 0.07])
    purposes = rng.choice(
        ["personal", "auto", "home_improvement", "medical", "education", "debt_consolidation"],
        size=n,
    )
    df = pd.DataFrame({
        "date": rng.choice(dates, size=n),
        "decision": decisions,
        "pd_score": rng.beta(2, 18, size=n),
        "fraud_probability": rng.beta(1, 20, size=n),
        "loan_purpose": purposes,
        "loan_amount": rng.uniform(1000, 100000, size=n),
        "state": rng.choice(["CA", "TX", "NY", "FL", "WA", "IL", "PA", "OH"], size=n),
    })
    df["date"] = pd.to_datetime(df["date"])
    return df


@st.cache_data(ttl=300)
def load_drift_reports() -> list:
    """Load drift reports from monitoring/reports/ or return mock data."""
    reports_dir = Path(__file__).parents[1] / "monitoring" / "reports"
    reports = []
    if reports_dir.exists():
        for f in sorted(reports_dir.glob("drift_report_*.json"), reverse=True):
            try:
                reports.append(json.loads(f.read_text()))
            except Exception:
                pass
    if not reports:
        # Mock drift data for demonstration
        reports = [
            {
                "overall_drift_status": "minor",
                "report_timestamp": _days_ago(0),
                "feature_results": [
                    {"feature_name": "credit_utilization", "psi": 0.08, "drift_status": "stable"},
                    {"feature_name": "income_stability_score", "psi": 0.14, "drift_status": "minor"},
                    {"feature_name": "repayment_capacity", "psi": 0.05, "drift_status": "stable"},
                    {"feature_name": "debt_service_coverage", "psi": 0.28, "drift_status": "major"},
                    {"feature_name": "log_loan_amount", "psi": 0.07, "drift_status": "stable"},
                ],
            }
        ]
    return reports


@st.cache_data(ttl=300)
def load_model_metrics() -> dict:
    """Load model performance metrics from MLflow or mock."""
    try:
        import mlflow
        from mlflow_config.mlflow_config import configure_mlflow
        configure_mlflow()
        runs = mlflow.search_runs(experiment_names=["credit_risk"])
        if not runs.empty:
            row = runs.iloc[0]
            return {
                "auc": row.get("metrics.auc", 0.83),
                "ks": row.get("metrics.ks", 0.41),
                "precision": row.get("metrics.precision", 0.72),
                "recall": row.get("metrics.recall", 0.65),
                "f1": row.get("metrics.f1", 0.68),
            }
    except Exception:
        pass
    return {"auc": 0.83, "ks": 0.41, "precision": 0.72, "recall": 0.65, "f1": 0.68}


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

PAGES = [
    "📈 Portfolio Overview",
    "🤖 Model Performance",
    "🔍 Drift Monitor",
    "⚖️ Fair Lending",
    "🔎 Audit Lookup",
]

st.sidebar.title("Credit Risk Platform")
st.sidebar.markdown("---")
page = st.sidebar.radio("Navigation", PAGES)
st.sidebar.markdown("---")
st.sidebar.caption(f"Last refresh: {datetime.now().strftime('%H:%M:%S')}")


# ---------------------------------------------------------------------------
# Page 1: Portfolio Overview
# ---------------------------------------------------------------------------


def page_portfolio_overview() -> None:
    st.title("📈 Portfolio Overview")
    df = load_portfolio_data()

    total = len(df)
    approved = (df["decision"] == "APPROVE").sum()
    approval_rate = approved / total
    avg_risk = df["pd_score"].mean()
    fraud_rate = (df["fraud_probability"] > 0.3).mean()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Applications", f"{total:,}")
    c2.metric("Approval Rate", f"{approval_rate:.1%}")
    c3.metric("Avg Risk Score", f"{avg_risk:.4f}")
    c4.metric("Fraud Flag Rate", f"{fraud_rate:.1%}")

    st.markdown("---")

    try:
        import plotly.express as px
        import plotly.graph_objects as go

        # Daily approval rate
        daily = (
            df.groupby(df["date"].dt.date)["decision"]
            .apply(lambda x: (x == "APPROVE").mean())
            .reset_index()
        )
        daily.columns = ["date", "approval_rate"]
        fig1 = px.line(daily, x="date", y="approval_rate",
                       title="Daily Approval Rate (Last 30 Days)",
                       labels={"approval_rate": "Approval Rate", "date": "Date"})
        fig1.add_hline(y=0.80, line_dash="dash", line_color="red", annotation_text="80% target")
        st.plotly_chart(fig1, use_container_width=True)

        col1, col2 = st.columns(2)
        with col1:
            # Decisions by loan purpose
            purpose_counts = df.groupby(["loan_purpose", "decision"]).size().reset_index(name="count")
            fig2 = px.bar(purpose_counts, x="loan_purpose", y="count", color="decision",
                          title="Decisions by Loan Purpose",
                          color_discrete_map={"APPROVE": "#28a745", "REJECT": "#dc3545",
                                              "MANUAL_REVIEW": "#ffc107"})
            st.plotly_chart(fig2, use_container_width=True)

        with col2:
            # Decision distribution pie
            decision_counts = df["decision"].value_counts().reset_index()
            decision_counts.columns = ["decision", "count"]
            fig3 = px.pie(decision_counts, names="decision", values="count",
                          title="Decision Distribution",
                          color="decision",
                          color_discrete_map={"APPROVE": "#28a745", "REJECT": "#dc3545",
                                              "MANUAL_REVIEW": "#ffc107"})
            st.plotly_chart(fig3, use_container_width=True)

    except ImportError:
        st.warning("Install plotly for interactive charts: pip install plotly")
        st.bar_chart(df["decision"].value_counts())


# ---------------------------------------------------------------------------
# Page 2: Model Performance
# ---------------------------------------------------------------------------


def page_model_performance() -> None:
    st.title("🤖 Model Performance")
    metrics = load_model_metrics()

    c1, c2, c3, c4 = st.columns(4)
    auc_ok = metrics["auc"] >= 0.75
    ks_ok = metrics["ks"] >= 0.35
    c1.metric("AUC", f"{metrics['auc']:.4f}", delta="✓ PASS" if auc_ok else "✗ FAIL")
    c2.metric("KS Statistic", f"{metrics['ks']:.4f}", delta="✓ PASS" if ks_ok else "✗ FAIL")
    c3.metric("Precision", f"{metrics['precision']:.4f}")
    c4.metric("F1 Score", f"{metrics['f1']:.4f}")

    st.markdown("---")

    try:
        import plotly.graph_objects as go
        from sklearn.datasets import make_classification
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.metrics import roc_curve, auc

        # Generate mock ROC curve
        rng = np.random.RandomState(42)
        X, y = make_classification(n_samples=1000, random_state=42)
        clf = RandomForestClassifier(n_estimators=20, random_state=42)
        clf.fit(X[:800], y[:800])
        probs = clf.predict_proba(X[800:])[:, 1]
        fpr, tpr, _ = roc_curve(y[800:], probs)
        roc_auc = auc(fpr, tpr)

        col1, col2 = st.columns(2)
        with col1:
            fig_roc = go.Figure()
            fig_roc.add_trace(go.Scatter(x=fpr, y=tpr, name=f"ROC (AUC={roc_auc:.3f})"))
            fig_roc.add_trace(go.Scatter(x=[0, 1], y=[0, 1], line=dict(dash="dash"), name="Random"))
            fig_roc.update_layout(title="ROC Curve", xaxis_title="FPR", yaxis_title="TPR")
            st.plotly_chart(fig_roc, use_container_width=True)

        with col2:
            # Feature importance (mock)
            features = [
                "credit_utilization", "income_stability", "repayment_capacity",
                "debt_service_coverage", "credit_age_score", "derogatory_penalty",
                "log_loan_amount", "log_annual_income", "dti_x_loan_amount",
                "employment_encoded",
            ]
            importances = rng.dirichlet(np.ones(len(features))) * 100
            imp_df = pd.DataFrame({"feature": features, "importance": importances}).sort_values(
                "importance", ascending=True
            )
            import plotly.express as px
            fig_imp = px.bar(imp_df, x="importance", y="feature", orientation="h",
                             title="Feature Importance (Top 10 SHAP)")
            st.plotly_chart(fig_imp, use_container_width=True)

    except ImportError:
        st.info("Install plotly and scikit-learn for charts.")


# ---------------------------------------------------------------------------
# Page 3: Drift Monitor
# ---------------------------------------------------------------------------


def page_drift_monitor() -> None:
    st.title("🔍 Drift Monitor")
    reports = load_drift_reports()

    if not reports:
        st.warning("No drift reports found in monitoring/reports/")
        return

    latest = reports[0]
    status = latest.get("overall_drift_status", "unknown")
    ts = latest.get("report_timestamp", "")

    status_color = {"stable": "🟢", "minor": "🟡", "major": "🔴"}.get(status, "⚪")
    st.markdown(f"### Overall Status: {status_color} **{status.upper()}**")
    st.caption(f"Last checked: {ts[:19]}")

    st.markdown("---")

    # Traffic-light table
    feature_results = latest.get("feature_results", [])
    if feature_results:
        rows = []
        for fr in feature_results:
            icon = {"stable": "🟢", "minor": "🟡", "major": "🔴"}.get(
                fr.get("drift_status", ""), "⚪"
            )
            rows.append({
                "Status": icon,
                "Feature": fr.get("feature_name", ""),
                "PSI": round(fr.get("psi", 0), 4),
                "KS p-value": round(fr.get("ks_p_value", 0), 4) if "ks_p_value" in fr else "N/A",
                "Drift": fr.get("drift_status", "").title(),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True)

    try:
        import plotly.express as px
        # PSI bar chart
        psi_df = pd.DataFrame([{
            "feature": fr["feature_name"], "psi": fr["psi"], "status": fr["drift_status"]
        } for fr in feature_results])
        color_map = {"stable": "#28a745", "minor": "#ffc107", "major": "#dc3545"}
        fig = px.bar(psi_df, x="feature", y="psi", color="status",
                     title="PSI by Feature", color_discrete_map=color_map)
        fig.add_hline(y=0.10, line_dash="dash", annotation_text="Minor threshold (0.10)")
        fig.add_hline(y=0.25, line_dash="dot", line_color="red",
                      annotation_text="Major threshold (0.25)")
        st.plotly_chart(fig, use_container_width=True)
    except ImportError:
        pass


# ---------------------------------------------------------------------------
# Page 4: Fair Lending
# ---------------------------------------------------------------------------


def page_fair_lending() -> None:
    st.title("⚖️ Fair Lending")

    # Try loading from file, otherwise use mock data
    reports_dir = Path(__file__).parents[1] / "monitoring" / "reports"
    report = None
    if reports_dir.exists():
        for f in sorted(reports_dir.glob("fair_lending_*.json"), reverse=True):
            try:
                report = json.loads(f.read_text())
                break
            except Exception:
                pass

    if report is None:
        report = {
            "dir_score": 0.82,
            "dir_flag": False,
            "protected_group": "group_A",
            "control_group": "group_B",
            "protected_approval_rate": 0.72,
            "control_approval_rate": 0.88,
            "approval_parity_p_value": 0.03,
            "approval_parity_flag": True,
            "geographic_flags": ["OH", "AR"],
            "state_approval_rates": {"CA": 0.80, "TX": 0.75, "NY": 0.78, "OH": 0.55},
            "n_total": 5000,
            "n_approved": 3400,
        }

    dir_score = report["dir_score"]
    dir_flag = report["dir_flag"]
    parity_flag = report["approval_parity_flag"]
    parity_p = report["approval_parity_p_value"]

    c1, c2, c3 = st.columns(3)
    c1.metric(
        "Disparate Impact Ratio (DIR)",
        f"{dir_score:.4f}",
        delta="⚠ FLAG" if dir_flag else "✓ PASS",
        delta_color="inverse",
    )
    c2.metric(
        "Approval Parity p-value",
        f"{parity_p:.4f}" if parity_p else "N/A",
        delta="⚠ FLAG (p < 0.05)" if parity_flag else "✓ PASS",
        delta_color="inverse",
    )
    c3.metric("Total Decisions", f"{report['n_total']:,}")

    st.markdown("---")

    try:
        import plotly.graph_objects as go
        import plotly.express as px

        col1, col2 = st.columns(2)

        with col1:
            # DIR gauge
            fig_gauge = go.Figure(go.Indicator(
                mode="gauge+number",
                value=dir_score,
                title={"text": f"DIR: {report['protected_group']} vs {report['control_group']}"},
                gauge={
                    "axis": {"range": [0, 1.2]},
                    "bar": {"color": "darkgreen" if not dir_flag else "red"},
                    "threshold": {
                        "line": {"color": "red", "width": 4},
                        "thickness": 0.75,
                        "value": 0.80,
                    },
                    "steps": [
                        {"range": [0, 0.80], "color": "#ffcccc"},
                        {"range": [0.80, 1.20], "color": "#ccffcc"},
                    ],
                },
                number={"suffix": "", "valueformat": ".3f"},
            ))
            st.plotly_chart(fig_gauge, use_container_width=True)

        with col2:
            # State approval rates
            state_rates = report.get("state_approval_rates", {})
            if state_rates:
                states_df = pd.DataFrame(
                    [{"state": k, "approval_rate": v} for k, v in state_rates.items()]
                )
                flagged = report.get("geographic_flags", [])
                states_df["flagged"] = states_df["state"].isin(flagged)
                fig_states = px.bar(
                    states_df, x="state", y="approval_rate", color="flagged",
                    title="Approval Rate by State",
                    color_discrete_map={True: "#dc3545", False: "#28a745"},
                )
                fig_states.add_hline(y=0.80, line_dash="dash", annotation_text="80% threshold")
                st.plotly_chart(fig_states, use_container_width=True)

    except ImportError:
        st.info("Install plotly for charts.")

    if report.get("geographic_flags"):
        st.error(f"⚠ Geographic flags: {', '.join(report['geographic_flags'])}")
    else:
        st.success("✓ No geographic bias detected")


# ---------------------------------------------------------------------------
# Page 5: Audit Lookup
# ---------------------------------------------------------------------------


def page_audit_lookup() -> None:
    st.title("🔎 Audit Lookup")
    st.markdown("Query the audit log by application ID to review full decision records.")

    application_id = st.text_input(
        "Application ID",
        placeholder="e.g. app-lr-001",
        help="Enter the UUID of the loan application",
    )

    api_url = st.text_input(
        "Decision API URL",
        value=os.getenv("DECISION_API_URL", "http://localhost:8081"),
        help="Base URL of the decision API service",
    )

    if st.button("🔍 Lookup Audit Record", type="primary"):
        if not application_id.strip():
            st.error("Please enter an application ID.")
            return

        try:
            import requests
            resp = requests.get(
                f"{api_url.rstrip('/')}/v1/decisions/{application_id}/audit",
                timeout=5,
            )
            if resp.status_code == 200:
                record = resp.json()
                st.success(f"✓ Audit record found for `{application_id}`")
                st.json(record)
            elif resp.status_code == 404:
                st.warning(f"No audit record found for application_id: `{application_id}`")
            else:
                st.error(f"API error: HTTP {resp.status_code} — {resp.text}")
        except Exception as exc:
            st.error(f"Could not reach API at {api_url}: {exc}")
            st.info("Hint: Start the decision API with `uvicorn decision-api.src.main:app --port 8081`")


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

if page == PAGES[0]:
    page_portfolio_overview()
elif page == PAGES[1]:
    page_model_performance()
elif page == PAGES[2]:
    page_drift_monitor()
elif page == PAGES[3]:
    page_fair_lending()
elif page == PAGES[4]:
    page_audit_lookup()
