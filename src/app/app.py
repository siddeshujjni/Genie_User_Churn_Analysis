"""Genie User Churn Analysis — Databricks App (Streamlit)"""
import os, streamlit as st, pandas as pd, plotly.express as px, plotly.graph_objects as go
from databricks import sql as dbsql

# --- connection ---
def conn():
    return dbsql.connect(
        server_hostname=os.getenv("DATABRICKS_SERVER_HOSTNAME", os.getenv("DATABRICKS_HOST", "")).replace("https://", ""),
        http_path=f"/sql/1.0/warehouses/{os.environ['DATABRICKS_WAREHOUSE_ID']}",
        credentials_provider=lambda: None,  # uses app service principal OAuth
    )

@st.cache_data(ttl=300)
def query(sql):
    with conn() as c:
        with c.cursor() as cur:
            cur.execute(sql)
            cols = [d[0] for d in cur.description]
            return pd.DataFrame(cur.fetchall(), columns=cols)

CAT = os.environ.get("DATABRICKS_CATALOG", "main")
SCH = os.environ.get("DATABRICKS_SCHEMA", "genie_churn")
def q(table): return f"`{CAT}`.`{SCH}`.`{table}`"

# --- page config ---
st.set_page_config(page_title="Genie Churn Analysis", layout="wide", page_icon="📉")
st.title("📉 Genie User Churn Analysis")

# --- sidebar ---
st.sidebar.header("Filters")
try:
    spaces_df = query(f"SELECT DISTINCT space_name FROM {q('dim_genie_spaces')} ORDER BY 1")
    space_filter = st.sidebar.multiselect("Spaces", spaces_df["space_name"].tolist(), default=[])
except Exception:
    space_filter = []

# --- Overview KPIs ---
st.header("Overview")
try:
    health = query(f"SELECT * FROM {q('gold_monthly_user_health')} ORDER BY month_start")
    latest = health.iloc[-1]
    prev = health.iloc[-2] if len(health) > 1 else latest
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Active users", int(latest["active_users"]), int(latest["active_users"] - prev["active_users"]))
    c2.metric("New users", int(latest["new_users"]))
    c3.metric("Churned", int(latest["churned_users"]), int(latest["churned_users"] - prev["churned_users"]), delta_color="inverse")
    c4.metric("At risk", int(latest.get("at_risk_users", 0)))
    c5.metric("Churn rate", f"{latest.get('monthly_churn_rate_pct', 0) or 0:.1f}%")
except Exception as e:
    st.warning(f"Could not load monthly health: {e}")
    health = pd.DataFrame()

# --- Monthly trend ---
if not health.empty:
    st.subheader("Monthly Adoption Trend")
    fig = go.Figure()
    fig.add_bar(x=health["month_start"], y=health["new_users"], name="New", marker_color="#2ecc71")
    fig.add_bar(x=health["month_start"], y=-health["churned_users"], name="Churned", marker_color="#e74c3c")
    fig.add_scatter(x=health["month_start"], y=health["active_users"], name="Active", mode="lines+markers", yaxis="y2", line=dict(color="#3498db", width=3))
    fig.update_layout(barmode="relative", yaxis=dict(title="New / Churned"), yaxis2=dict(title="Active", overlaying="y", side="right"), height=380, legend=dict(orientation="h"))
    st.plotly_chart(fig, use_container_width=True)

# --- Cohort retention ---
try:
    coh = query(f"SELECT * FROM {q('gold_cohort_retention')} ORDER BY cohort_month, months_since_join")
    if not coh.empty:
        st.subheader("Cohort Retention")
        pivot = coh.pivot_table(index="cohort_month", columns="months_since_join", values="retention_pct").round(1)
        pivot.index = pd.to_datetime(pivot.index).strftime("%Y-%m")
        pivot.columns = [f"M{int(c)}" for c in pivot.columns]
        fig2 = px.imshow(pivot, text_auto=True, color_continuous_scale="RdYlGn", aspect="auto", zmin=0, zmax=100)
        fig2.update_layout(height=300)
        st.plotly_chart(fig2, use_container_width=True)
except Exception as e:
    st.warning(f"Cohort retention: {e}")

# --- Churn drivers ---
st.header("Why Are Users Leaving?")
col_a, col_b = st.columns(2)
try:
    drivers = query(f"SELECT * FROM {q('gold_churn_driver_summary')}")
    if not drivers.empty:
        with col_a:
            st.subheader("Churned vs Active")
            metrics = ["avg_failure_pct", "avg_rephrase_pct", "avg_slow_pct", "avg_negative_feedback_pct", "avg_problem_pct"]
            labels = ["Failure %", "Rephrase %", "Slow %", "Neg Feedback %", "Problem %"]
            avail = [m for m in metrics if m in drivers.columns]
            avail_labels = [labels[metrics.index(m)] for m in avail]
            melted = drivers.melt(id_vars="lifecycle_status", value_vars=avail, var_name="metric", value_name="pct")
            melted["metric"] = melted["metric"].map(dict(zip(avail, avail_labels)))
            fig3 = px.bar(melted, x="metric", y="pct", color="lifecycle_status", barmode="group", color_discrete_map={"Active": "#2ecc71", "At Risk": "#f39c12", "Churned": "#e74c3c"})
            fig3.update_layout(height=350)
            st.plotly_chart(fig3, use_container_width=True)
except Exception as e:
    st.warning(f"Drivers: {e}")

try:
    reasons = query(f"SELECT failure_reason, lifecycle_status, SUM(occurrences) occ FROM {q('gold_failure_reasons')} GROUP BY 1,2 ORDER BY occ DESC LIMIT 30")
    if not reasons.empty:
        with col_b:
            st.subheader("Top Failure Reasons")
            fig4 = px.bar(reasons, x="occ", y="failure_reason", color="lifecycle_status", orientation="h", color_discrete_map={"Active": "#2ecc71", "At Risk": "#f39c12", "Churned": "#e74c3c"})
            fig4.update_layout(height=350, yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig4, use_container_width=True)
except Exception as e:
    st.warning(f"Failure reasons: {e}")

# --- Space health ---
st.header("Space Health")
try:
    sp = query(f"SELECT * FROM {q('gold_space_health')} ORDER BY churned_users DESC")
    if space_filter:
        sp = sp[sp["space_name"].isin(space_filter)]
    if not sp.empty:
        display_cols = ["space_name", "users", "active_users", "at_risk_users", "churned_users", "churned_user_pct", "failure_pct", "negative_feedback_pct", "avg_response_seconds", "rephrase_pct", "top_failure_reason"]
        display_cols = [c for c in display_cols if c in sp.columns]
        st.dataframe(sp[display_cols], use_container_width=True, hide_index=True)
except Exception as e:
    st.warning(f"Space health: {e}")

# --- At-risk users ---
st.header("At-Risk & Recently Churned Users")
try:
    risk = query(f"SELECT * FROM {q('gold_user_risk')} WHERE lifecycle_status IN ('At Risk', 'Churned') ORDER BY churn_risk_score DESC LIMIT 100")
    if space_filter:
        risk = risk[risk["last_space_name"].isin(space_filter)]
    if not risk.empty:
        risk_cols = ["user_email", "lifecycle_status", "churn_risk_score", "days_since_last_question", "primary_churn_reason", "last_space_name", "total_questions", "recent_problem_pct", "recent_negative_feedback"]
        risk_cols = [c for c in risk_cols if c in risk.columns]
        st.dataframe(risk[risk_cols], use_container_width=True, hide_index=True)
    else:
        st.info("No at-risk or churned users found.")
except Exception as e:
    st.warning(f"User risk: {e}")

st.caption("Data refreshed by the Genie User Churn Analysis job. Tables live in " + f"{CAT}.{SCH}.")
