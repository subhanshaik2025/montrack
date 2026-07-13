from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from analytics.savings import cash_equivalent_yield, emergency_fund_progress, liquidity_ratio
from db.models import Account, Transaction
from db.session import get_session, init_db

st.set_page_config(page_title="Savings", page_icon="🏦", layout="wide")
st.title("🏦 Savings")

init_db()
session = get_session()

acct_df = pd.read_sql(session.query(Account).statement, session.bind)
txn_df = pd.read_sql(session.query(Transaction).statement, session.bind)
txn_df["txn_date"] = pd.to_datetime(txn_df["txn_date"])

liquid_acct_ids = set(acct_df[acct_df["is_liquid"]]["id"])
cash_balance = txn_df[txn_df["account_id"].isin(liquid_acct_ids)]["amount"].sum()

last_90d = txn_df[(txn_df["txn_type"] == "expense") & (txn_df["txn_date"] >= txn_df["txn_date"].max() - timedelta(days=90))]
monthly_essential = abs(last_90d["amount"].sum()) / 3 if not last_90d.empty else 0

liq = liquidity_ratio(cash_balance, monthly_essential)
progress = emergency_fund_progress(cash_balance, monthly_essential, target_months=6.0, monthly_contribution=10000)

k1, k2, k3 = st.columns(3)
k1.metric("Liquidity Ratio", f"{liq:.1f} months")
k2.metric("Emergency Fund Progress", f"{progress['progress_pct']:.0f}%")
k3.metric("Shortfall", f"₹{progress['shortfall']:,.0f}")

st.divider()

col1, col2 = st.columns([1, 2])
with col1:
    st.subheader("Emergency Fund")
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=progress["progress_pct"],
        gauge={"axis": {"range": [0, 100]}, "bar": {"color": "#14b8a6"},
               "steps": [{"range": [0, 50], "color": "#3f3f46"}, {"range": [50, 100], "color": "#27272a"}]},
        number={"suffix": "%"},
    ))
    fig.update_layout(template="plotly_dark", height=300, margin=dict(t=30, b=10))
    st.plotly_chart(fig, use_container_width=True)
    if progress["projected_completion"]:
        st.caption(f"Projected completion: {progress['projected_completion'].strftime('%b %Y')} at current contribution rate")
    else:
        st.caption("Target reached." if progress["shortfall"] == 0 else "Set a monthly contribution to see a projected date.")

with col2:
    st.subheader("Liquidity Ratio Trend")
    daily_expense = txn_df[txn_df["txn_type"] == "expense"].set_index("txn_date")["amount"].abs()
    monthly_expense = daily_expense.resample("MS").sum()
    trend = []
    for m_end, exp in monthly_expense.items():
        cash_as_of = txn_df[(txn_df["account_id"].isin(liquid_acct_ids)) & (txn_df["txn_date"] <= m_end)]["amount"].sum()
        trend.append({"month": m_end, "ratio": liquidity_ratio(cash_as_of, exp) if exp else None})
    trend_df = pd.DataFrame(trend).dropna()
    fig = go.Figure()
    fig.add_hrect(y0=3, y1=6, fillcolor="#14b8a6", opacity=0.15, line_width=0)
    fig.add_trace(go.Scatter(x=trend_df["month"], y=trend_df["ratio"], line=dict(color="#14b8a6")))
    fig.update_layout(template="plotly_dark", height=300, margin=dict(t=30, b=10), yaxis_title="Months covered")
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Shaded band = healthy zone (3–6 months of essential expenses)")

st.divider()
st.subheader("Cash-Equivalent Instruments")
instruments = pd.DataFrame([
    {"name": "SBI Fixed Deposit", "balance": 400000, "annual_yield_pct": 7.1},
    {"name": "HDFC Savings", "balance": max(cash_balance, 0), "annual_yield_pct": 3.0},
    {"name": "Liquid Fund (LIQUIDBEES)", "balance": 90000, "annual_yield_pct": 6.5},
])
yield_df = cash_equivalent_yield(instruments, cpi_annual=5.0)
display_df = yield_df[["name", "balance", "annual_yield_pct", "real_yield_pct"]].copy()
display_df.columns = ["Instrument", "Balance (₹)", "Yield %", "Real Yield % (vs 5% CPI)"]
st.dataframe(
    display_df.style.format({"Balance (₹)": "₹{:,.0f}", "Yield %": "{:.1f}%", "Real Yield % (vs 5% CPI)": "{:.1f}%"})
    .applymap(lambda v: "color: #fb7185" if isinstance(v, float) and v < 0 else "", subset=["Real Yield % (vs 5% CPI)"]),
    use_container_width=True, hide_index=True,
)
st.caption(f"Portfolio-weighted yield: {yield_df.attrs['portfolio_weighted_yield_pct']:.2f}% | "
           f"Real yield: {yield_df.attrs['portfolio_real_yield_pct']:.2f}%")

session.close()
