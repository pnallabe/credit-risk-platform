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
    "📋 Credit Policy Docs",
    "🏦 Plaid Tenant",
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
# Page 6: Credit Policy Docs
# ---------------------------------------------------------------------------


@st.cache_data(ttl=600)
def load_policy_artifacts_manifest():
    """Load policy manifest from artifacts/plaid_tenant/ if it exists."""
    import json
    manifest_path = Path(__file__).parents[1] / "artifacts" / "plaid_tenant" / "policy_manifest.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text())
    return None


@st.cache_data(ttl=600)
def load_product_policy_json(product_type: str):
    import json
    p = Path(__file__).parents[1] / "artifacts" / "plaid_tenant" / f"policy_{product_type.lower()}.json"
    if p.exists():
        return json.loads(p.read_text())
    return None


@st.cache_data(ttl=600)
def load_underwriting_summary_md():
    p = Path(__file__).parents[1] / "artifacts" / "plaid_tenant" / "underwriting_summary.md"
    if p.exists():
        return p.read_text()
    return None


def page_credit_policy_docs() -> None:
    st.title("📋 Credit Policy Documents")
    st.markdown(
        "Policy artifacts for all credit products — **Plaid Data Tenant** (`plaid_data`). "
        "Artifacts are generated by `compliance/plaid_policy_artifacts.py`."
    )

    # Generate button
    if st.button("🔄 Regenerate Artifacts", help="Run compliance/plaid_policy_artifacts.py"):
        with st.spinner("Generating policy artifacts…"):
            try:
                from compliance.plaid_policy_artifacts import generate_all_artifacts
                result = generate_all_artifacts(out_dir="artifacts/plaid_tenant")
                st.success(f"✓ Generated {len(result)} artifacts in `artifacts/plaid_tenant/`")
                st.cache_data.clear()
            except Exception as exc:
                st.error(f"Generation failed: {exc}")

    st.markdown("---")

    manifest = load_policy_artifacts_manifest()
    if manifest:
        c1, c2, c3 = st.columns(3)
        c1.metric("Tenant", manifest.get("tenant_id", "—"))
        c2.metric("Policy Version", manifest.get("policy_version", "—"))
        c3.metric("Products Covered", len(manifest.get("products", [])))

        st.subheader("Wave Delivery Map")
        wave_map = manifest.get("wave_map", {})
        wave_cols = st.columns(len(wave_map))
        for col, (wave, products) in zip(wave_cols, wave_map.items()):
            col.markdown(f"**{wave}**")
            for prod in products:
                col.markdown(f"- {prod}")
    else:
        st.info("No artifacts found. Click **Regenerate Artifacts** to generate them.")

    st.markdown("---")

    # Underwriting summary markdown
    summary_md = load_underwriting_summary_md()
    if summary_md:
        with st.expander("📄 Full Underwriting Policy Summary", expanded=True):
            st.markdown(summary_md)

    # Per-product policy viewer
    st.subheader("Per-Product Policy Parameters")
    try:
        from decision_engine.plaid_tenant_policies import plaid_policy_summary_rows
        rows = plaid_policy_summary_rows()
        df_policies = pd.DataFrame(rows)
        st.dataframe(df_policies, use_container_width=True, hide_index=True)
    except Exception as exc:
        st.warning(f"Could not load live policy data: {exc}")

    # Drill-down by product
    st.subheader("Product Policy Detail")
    try:
        from decision_engine.plaid_tenant_policies import ALL_PRODUCT_TYPES
        product_types = list(ALL_PRODUCT_TYPES)
    except Exception:
        product_types = ["BNPL", "PERSONAL_LOAN", "SMB_SECURED_LOAN", "CREDIT_CARD",
                         "CREDIT_BUILDER", "OVERDRAFT_CASH_ADVANCE", "AUTO_LOAN", "MORTGAGE"]

    selected = st.selectbox("Select Product", product_types)
    artifact = load_product_policy_json(selected)
    if artifact:
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Policy Parameters**")
            params = artifact.get("policy_parameters", {})
            display = {
                "Approve PD ≤": f"{params.get('pd_threshold_approve', 0):.1%}",
                "Refer PD ≤": f"{params.get('pd_threshold_refer', 0):.1%}",
                "Max DTI": f"{params.get('max_dti', 0):.0%}",
                "Loan Min (USD)": f"${params.get('min_loan_amount_usd', 0):,.0f}",
                "Loan Max (USD)": f"${params.get('max_loan_amount_usd', 0):,.0f}",
                "Base APR": f"{params.get('base_apr', 0):.2f}%",
                "Max APR": f"{params.get('max_apr', 0):.2f}%",
                "Fraud Reject ≥": f"{params.get('fraud_reject_threshold', 0):.0%}",
                "Fraud Review ≥": f"{params.get('fraud_review_threshold', 0):.0%}",
            }
            st.table(pd.DataFrame(display.items(), columns=["Parameter", "Value"]))
        with col2:
            st.markdown("**Plaid Features**")
            plaid_feats = artifact.get("plaid_features_used", [])
            if plaid_feats:
                for f in plaid_feats:
                    st.markdown(f"- `{f}`")
            else:
                st.info("No explicit Plaid features tagged")
            st.markdown("**Extra Rules**")
            extra_rules = params.get("extra_rules", [])
            for rule in extra_rules:
                st.markdown(f"- `{rule}`")

        st.markdown("**Regulatory Compliance Checklist**")
        checklist = artifact.get("regulatory_compliance_checklist", [])
        if checklist:
            df_check = pd.DataFrame(checklist)
            st.dataframe(df_check, use_container_width=True, hide_index=True)
    else:
        st.info(f"No artifact for `{selected}` yet — click **Regenerate Artifacts** above.")


# ---------------------------------------------------------------------------
# Page 7: Plaid Tenant
# ---------------------------------------------------------------------------


def page_plaid_tenant() -> None:
    st.title("🏦 Plaid Tenant Dashboard")
    st.markdown(
        "Live view of Plaid data tenant configuration, Plaid signal health, "
        "and per-product underwriting thresholds."
    )

    # Tenant config section
    st.subheader("Tenant Configuration (`plaid_data`)")
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parents[1]))
        from config_registry.plaid_tenant_seed import PLAID_CONFIG_V1
        col1, col2, col3 = st.columns(3)
        col1.metric("Bureau Provider", PLAID_CONFIG_V1.get("bureau_provider", "—").upper())
        col2.metric("Plaid Environment", PLAID_CONFIG_V1.get("plaid_env", "—").upper())
        col3.metric("Bank Lookback", f"{PLAID_CONFIG_V1.get('bank_lookback_days', 90)} days")

        ft = PLAID_CONFIG_V1.get("feature_toggles", {})
        st.markdown("**Feature Toggles**")
        toggle_df = pd.DataFrame(
            [{"Feature": k, "Enabled": "✅" if v else "❌"} for k, v in ft.items()]
        )
        st.dataframe(toggle_df, use_container_width=True, hide_index=True)

        st.markdown("**Alt-Data Signals Enabled**")
        signals = PLAID_CONFIG_V1.get("alt_data_signals", [])
        cols = st.columns(3)
        for i, sig in enumerate(signals):
            cols[i % 3].markdown(f"- `{sig}`")

    except Exception as exc:
        st.warning(f"Could not load tenant config: {exc}")

    st.markdown("---")

    # Plaid signal simulator
    st.subheader("Plaid Signal PD Adjustment Simulator")
    st.markdown(
        "Simulate how Plaid cash-flow signals adjust the PD approval threshold "
        "for a given applicant profile."
    )
    col1, col2 = st.columns(2)
    with col1:
        stability = st.slider("Cash Flow Stability Score", 0.0, 1.0, 0.65, 0.05)
        nsf_count = st.slider("NSF Events (90 days)", 0, 10, 0)
        product_sel = st.selectbox(
            "Product",
            ["BNPL", "PERSONAL_LOAN", "SMB_SECURED_LOAN", "CREDIT_CARD",
             "CREDIT_BUILDER", "OVERDRAFT_CASH_ADVANCE"],
        )
    with col2:
        try:
            from decision_engine.plaid_tenant_policies import (
                get_plaid_cash_flow_pd_adjustment,
                plaid_tenant_policy_overrides,
            )
            overrides = plaid_tenant_policy_overrides()
            base_pol = overrides.get(product_sel)
            if base_pol:
                base_thresh = base_pol.pd_threshold_approve
                multiplier = get_plaid_cash_flow_pd_adjustment(stability, nsf_count)
                adj_thresh = base_thresh * multiplier
                delta_pct = (multiplier - 1) * 100

                st.metric(
                    "Base Approval PD Threshold",
                    f"{base_thresh:.1%}",
                )
                st.metric(
                    "Adjusted Threshold",
                    f"{adj_thresh:.2%}",
                    delta=f"{delta_pct:+.0f}% {'(relaxed)' if delta_pct > 0 else '(tightened)' if delta_pct < 0 else '(unchanged)'}",
                )
                st.metric("Multiplier", f"×{multiplier:.2f}")

                if delta_pct > 0:
                    st.success("✅ Strong cash-flow signals — threshold relaxed for thin-file approval")
                elif delta_pct < 0:
                    st.warning("⚠️ Weak cash-flow signals — threshold tightened")
                else:
                    st.info("ℹ️ Neutral signals — base threshold unchanged")
        except Exception as exc:
            st.error(f"Simulator unavailable: {exc}")

    st.markdown("---")

    # Plaid feature impact table
    st.subheader("Plaid Feature → Underwriting Rule Mapping")
    impact_data = [
        {"Plaid Feature": "cash_flow_stability_score", "Gate Type": "PD Threshold Adjustment",
         "Rule": "≥0.70 + 0 NSF → relax 20%; <0.20 → tighten 20%", "Products": "All"},
        {"Plaid Feature": "nsf_count_90d", "Gate Type": "Hard Reject Gate",
         "Rule": "plaid_nsf_gate_3: reject if ≥3 (BNPL/Personal); gate_2 for SMB", "Products": "All"},
        {"Plaid Feature": "avg_monthly_inflow", "Gate Type": "Minimum Income Gate",
         "Rule": "≥$200/mo (BNPL/Credit Builder); ≥$500/mo (Overdraft)", "Products": "BNPL, Credit Builder, Overdraft"},
        {"Plaid Feature": "plaid_income_estimate", "Gate Type": "Income Consistency Check",
         "Rule": "< 30% gap vs stated income; else manual review", "Products": "Personal Loan, SMB"},
        {"Plaid Feature": "bank_account_age_months", "Gate Type": "Account Tenure Gate",
         "Rule": "≥3 months (Personal); ≥2 months (Overdraft); ≥1 month (Credit Builder)", "Products": "Personal, Overdraft, Credit Builder"},
        {"Plaid Feature": "savings_balance", "Gate Type": "Liquidity Check",
         "Rule": "≥$100 balance (Credit Card)", "Products": "Credit Card"},
        {"Plaid Feature": "overdraft_count_90d", "Gate Type": "Hard Reject Gate",
         "Rule": ">10 overdrafts in 90 days → reject (Overdraft product)", "Products": "Overdraft"},
        {"Plaid Feature": "net_monthly_cash_flow", "Gate Type": "Cash-Flow Gate",
         "Rule": "Must be positive (Personal Loan, Credit Card)", "Products": "Personal Loan, Credit Card"},
        {"Plaid Feature": "income_source_count", "Gate Type": "Income Diversification",
         "Rule": "≥1 distinct source (SMB, Personal)", "Products": "SMB, Personal Loan"},
        {"Plaid Feature": "recurring_expense_ratio", "Gate Type": "Free-Cash Check",
         "Rule": "≤90% of outflow is recurring (Credit Builder)", "Products": "Credit Builder"},
    ]
    st.dataframe(pd.DataFrame(impact_data), use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("Plaid Integration Architecture")
    st.markdown("""
**Data Flow:**
```
Applicant → Plaid Link (OAuth) → ingestion-api/plaid_connector.py
         → BankDataSummary (normalized)
         → credit_core/features.py (canonical feature matrix)
         → decision_engine/plaid_tenant_policies.py (policy thresholds)
         → compliance/engine.py (compliance gate)
         → decision-api/v1/decisions (response)
```

**Key Files:**
- `ingestion-api/src/plaid_connector.py` — Plaid/Finicity/OpenBankProject connector
- `decision_engine/plaid_tenant_policies.py` — Plaid-aware policy overrides
- `config_registry/plaid_tenant_seed.py` — Tenant config seeding
- `compliance/plaid_policy_artifacts.py` — Policy artifact generator
- `docs/PLAID_TENANT_CREDIT_POLICIES.md` — Authoritative policy documentation
""")


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
elif page == PAGES[5]:
    page_credit_policy_docs()
elif page == PAGES[6]:
    page_plaid_tenant()
