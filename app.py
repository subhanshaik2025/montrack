"""Landing page: cross-module KPIs, net-worth waterfall, cash-flow Sankey."""
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from db.models import Account, PortfolioSnapshot, Transaction
from db.session import get_session, init_db

st.set_page_config(page_title="MonTrack", page_icon="💎", layout="wide")

PRIMARY = "#14b8a6"   # teal — growth/positive
DANGER = "#fb7185"    # coral — risk/negative
st.markdown(f"""
<style>
[data-testid="stMetricValue"] {{ font-size: 1.8rem; }}
</style>
""", unsafe_allow_html=True)


def inr(x: float) -> str:
    s = f"{abs(x):,.0f}"
    return f"{'-' if x < 0 else ''}₹{s}"


init_db()
session = get_session()

st.title("💎 MonTrack")

# ---------------- KPI row ----------------
today = date.today()
latest_snap_date = session.query(PortfolioSnapshot.snapshot_date).order_by(PortfolioSnapshot.snapshot_date.desc()).first()

if latest_snap_date is None:
    st.warning("No data yet. Run `python3 db/seed.py` to load demo data.")
    st.stop()

latest_snap_date = latest_snap_date[0]
snap_df = pd.read_sql(
    session.query(PortfolioSnapshot).filter(PortfolioSnapshot.snapshot_date == latest_snap_date).statement,
    session.bind,
)
invest_value = snap_df["market_value"].sum()

txn_df = pd.read_sql(session.query(Transaction).statement, session.bind)
txn_df["txn_date"] = pd.to_datetime(txn_df["txn_date"])

acct_df = pd.read_sql(session.query(Account).statement, session.bind)
liquid_acct_ids = set(acct_df[acct_df["is_liquid"]]["id"])
cash_balance = txn_df[txn_df["account_id"].isin(liquid_acct_ids)]["amount"].sum()

net_worth = invest_value + cash_balance

month_ago_snap_date = session.query(PortfolioSnapshot.snapshot_date).filter(
    PortfolioSnapshot.snapshot_date <= latest_snap_date - timedelta(days=30)
).order_by(PortfolioSnapshot.snapshot_date.desc()).first()
mom_change = None
if month_ago_snap_date:
    prev_snap = pd.read_sql(
        session.query(PortfolioSnapshot).filter(PortfolioSnapshot.snapshot_date == month_ago_snap_date[0]).statement,
        session.bind,
    )
    mom_change = invest_value - prev_snap["market_value"].sum()

essential_cat_ids = txn_df[txn_df["txn_type"] == "expense"]["category_id"].unique()
last_90d_expense = txn_df[(txn_df["txn_type"] == "expense") & (txn_df["txn_date"] >= pd.Timestamp(today - timedelta(days=90)))]
monthly_essential = abs(last_90d_expense["amount"].sum()) / 3 if not last_90d_expense.empty else 0

from analytics.savings import liquidity_ratio
liq_ratio = liquidity_ratio(cash_balance, monthly_essential)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Net Worth", inr(net_worth))
c2.metric("Investments MoM", inr(mom_change) if mom_change is not None else "—",
          delta=inr(mom_change) if mom_change is not None else None)
c3.metric("Liquidity Ratio", f"{liq_ratio:.1f} mo" if liq_ratio != float("inf") else "∞")
c4.metric("Cash Balance", inr(cash_balance))

st.divider()

# ---------------- Net worth waterfall (trailing 6 months) ----------------
st.subheader("Net Worth Change — Trailing 6 Months")

six_mo_ago = today - timedelta(days=180)
snap_hist = pd.read_sql(
    session.query(PortfolioSnapshot).filter(PortfolioSnapshot.snapshot_date >= six_mo_ago).statement,
    session.bind,
)
monthly_invest_value = snap_hist.groupby(pd.to_datetime(snap_hist["snapshot_date"]).dt.to_period("M"))["market_value"].sum()

flows = txn_df[(txn_df["txn_date"] >= pd.Timestamp(six_mo_ago))]
buys = flows[flows["txn_type"] == "buy"].groupby(flows["txn_date"].dt.to_period("M"))["amount"].sum()
expenses = flows[flows["txn_type"] == "expense"].groupby(flows["txn_date"].dt.to_period("M"))["amount"].sum()
income = flows[flows["txn_type"] == "income"].groupby(flows["txn_date"].dt.to_period("M"))["amount"].sum()

periods = sorted(set(monthly_invest_value.index) | set(buys.index) | set(income.index))
if len(periods) >= 2:
    start_val = monthly_invest_value.get(periods[0], 0)
    labels = ["Start"]
    values = [start_val]
    for p in periods[1:]:
        contrib = buys.get(p, 0)
        market_change = monthly_invest_value.get(p, 0) - monthly_invest_value.get(periods[periods.index(p) - 1], 0) - contrib
        labels += [f"{p} contrib", f"{p} market"]
        values += [contrib, market_change]
    labels.append("End")
    values.append(monthly_invest_value.get(periods[-1], 0))

    measures = ["absolute"] + ["relative"] * (len(values) - 2) + ["total"]
    fig = go.Figure(go.Waterfall(
        x=labels, y=values, measure=measures,
        increasing={"marker": {"color": PRIMARY}},
        decreasing={"marker": {"color": DANGER}},
        totals={"marker": {"color": "#64748b"}},
    ))
    fig.update_layout(height=400, margin=dict(t=10, b=10), template="plotly_dark")
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Not enough history yet for a waterfall view.")

# ---------------- Cash flow Sankey (last full month) ----------------
st.subheader("Cash Flow — Last Month")

last_month_start = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
last_month_end = today.replace(day=1) - timedelta(days=1)
lm = txn_df[(txn_df["txn_date"] >= pd.Timestamp(last_month_start)) & (txn_df["txn_date"] <= pd.Timestamp(last_month_end))]

income_total = lm[lm["txn_type"] == "income"]["amount"].sum()
invest_total = abs(lm[lm["txn_type"] == "buy"]["amount"].sum())
expense_by_cat = lm[lm["txn_type"] == "expense"].copy()

from db.models import ExpenseCategory
cat_lookup = {c.id: c.name for c in session.query(ExpenseCategory).all()}
expense_by_cat["cat_name"] = expense_by_cat["category_id"].map(cat_lookup)
expense_grouped = expense_by_cat.groupby("cat_name")["amount"].sum().abs()

savings_total = max(income_total - invest_total - expense_grouped.sum(), 0)

if income_total > 0:
    nodes = ["Income", "Investments", "Savings"] + list(expense_grouped.index)
    node_idx = {n: i for i, n in enumerate(nodes)}
    sources, targets, values = [], [], []
    sources.append(node_idx["Income"]); targets.append(node_idx["Investments"]); values.append(invest_total)
    sources.append(node_idx["Income"]); targets.append(node_idx["Savings"]); values.append(savings_total)
    for cat, amt in expense_grouped.items():
        sources.append(node_idx["Income"]); targets.append(node_idx[cat]); values.append(amt)

    fig2 = go.Figure(go.Sankey(
        node=dict(label=nodes, color=PRIMARY, pad=20, thickness=15),
        link=dict(source=sources, target=targets, value=values, color="rgba(20,184,166,0.3)"),
    ))
    fig2.update_layout(height=400, template="plotly_dark", margin=dict(t=10, b=10))
    st.plotly_chart(fig2, use_container_width=True)
else:
    st.info("Not enough transaction history yet for a cash-flow view.")

session.close()
st.caption("Use the sidebar to open Investments / Savings / Expenses modules.")
