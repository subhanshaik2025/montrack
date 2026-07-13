from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from analytics.irr import portfolio_irr
from analytics.risk import allocation_drift, annualized_volatility, beta, daily_returns, sharpe_ratio
from analytics.twr import time_weighted_return
from db.models import AssetMetadata, BenchmarkPrice, PortfolioSnapshot, Transaction
from db.session import get_session, init_db

st.set_page_config(page_title="Investments", page_icon="📈", layout="wide")
st.title("📈 Investments")

init_db()
session = get_session()

assets = pd.read_sql(session.query(AssetMetadata).statement, session.bind)
snaps = pd.read_sql(session.query(PortfolioSnapshot).statement, session.bind)
txns = pd.read_sql(session.query(Transaction).filter(Transaction.ticker.isnot(None)).statement, session.bind)
bench = pd.read_sql(session.query(BenchmarkPrice).statement, session.bind)

if snaps.empty:
    st.warning("No investment data. Run `python3 db/seed.py`.")
    st.stop()

snaps["snapshot_date"] = pd.to_datetime(snaps["snapshot_date"])
latest_date = snaps["snapshot_date"].max()
latest = snaps[snaps["snapshot_date"] == latest_date].merge(assets, on="ticker")
current_value = latest["market_value"].sum()

# ---- KPI strip ----
txns["txn_date"] = pd.to_datetime(txns["txn_date"]).dt.date
try:
    irr = portfolio_irr(txns.rename(columns={"txn_type": "txn_type"}), current_value, date.today())
except ValueError:
    irr = float("nan")

port_daily = snaps.groupby("snapshot_date")["market_value"].sum()
port_returns = daily_returns(port_daily)

bench["price_date"] = pd.to_datetime(bench["price_date"])
bench_series = bench.set_index("price_date")["close"]
bench_returns = daily_returns(bench_series)

flows = txns[txns["txn_type"] == "buy"][["txn_date", "amount"]].copy()
flows["txn_date"] = pd.to_datetime(flows["txn_date"])
snap_totals = port_daily.reset_index().rename(columns={"snapshot_date": "snapshot_date", "market_value": "market_value"})
twr = time_weighted_return(snap_totals, flows.rename(columns={"txn_date": "txn_date"}))

b = beta(port_returns, bench_returns, window=252)
vol = annualized_volatility(port_returns)
sharpe = sharpe_ratio(port_returns)

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("IRR (XIRR)", f"{irr*100:.1f}%" if irr == irr else "—")
k2.metric("TWR (cumulative)", f"{twr*100:.1f}%")
k3.metric("Beta vs NIFTY50", f"{b:.2f}" if b == b else "—")
k4.metric("Ann. Volatility", f"{vol*100:.1f}%")
k5.metric("Sharpe Ratio", f"{sharpe:.2f}")

st.divider()

# ---- Allocation drift ----
col1, col2 = st.columns(2)
with col1:
    st.subheader("Allocation — Actual")
    alloc = latest.groupby("asset_class")["market_value"].sum().reset_index()
    fig = px.pie(alloc, names="asset_class", values="market_value", hole=0.55,
                 color_discrete_sequence=px.colors.sequential.Teal)
    fig.update_layout(template="plotly_dark", height=350, margin=dict(t=10, b=10))
    st.plotly_chart(fig, use_container_width=True)

with col2:
    st.subheader("Allocation Drift vs. Target")
    targets = assets[["asset_class", "target_weight_pct"]].groupby("asset_class").first().reset_index()
    holdings_for_drift = latest[["asset_class", "market_value"]]
    drift = allocation_drift(holdings_for_drift, targets, tolerance_pp=5.0)
    colors = [("#fb7185" if b_ else "#14b8a6") for b_ in drift["breach"]]
    fig = go.Figure(go.Bar(x=drift["asset_class"], y=drift["drift_pp"], marker_color=colors))
    fig.add_hline(y=5, line_dash="dot", line_color="gray")
    fig.add_hline(y=-5, line_dash="dot", line_color="gray")
    fig.update_layout(template="plotly_dark", height=350, margin=dict(t=10, b=10), yaxis_title="Drift (pp)")
    st.plotly_chart(fig, use_container_width=True)
    breached = drift[drift["breach"]]
    if not breached.empty:
        st.warning("Rebalance suggested: " + ", ".join(breached["asset_class"]))

st.divider()

# ---- Performance heatmap: asset x trailing period ----
st.subheader("Performance Heatmap")
periods = {"1M": 30, "3M": 90, "6M": 180, "1Y": 365}
rows = []
for ticker in snaps["ticker"].unique():
    tseries = snaps[snaps["ticker"] == ticker].set_index("snapshot_date")["price"].sort_index()
    row = {"ticker": ticker}
    for label, days in periods.items():
        cutoff = latest_date - timedelta(days=days)
        past = tseries[tseries.index <= cutoff]
        if not past.empty and tseries.iloc[-1] and past.iloc[-1]:
            row[label] = (tseries.iloc[-1] / past.iloc[-1] - 1) * 100
        else:
            row[label] = None
    rows.append(row)
heat_df = pd.DataFrame(rows).set_index("ticker")
fig = px.imshow(heat_df, text_auto=".1f", color_continuous_scale="RdYlGn", aspect="auto")
fig.update_layout(template="plotly_dark", height=350, margin=dict(t=10, b=10))
st.plotly_chart(fig, use_container_width=True)

# ---- Portfolio vs benchmark, indexed ----
st.subheader("Portfolio vs. NIFTY50 (Indexed to 100)")
port_idx = (port_daily / port_daily.iloc[0]) * 100
bench_idx = (bench_series / bench_series.iloc[0]) * 100
fig = go.Figure()
fig.add_trace(go.Scatter(x=port_idx.index, y=port_idx.values, name="Portfolio", line=dict(color="#14b8a6")))
fig.add_trace(go.Scatter(x=bench_idx.index, y=bench_idx.values, name="NIFTY50", line=dict(color="#64748b")))
fig.update_layout(template="plotly_dark", height=350, margin=dict(t=10, b=10))
st.plotly_chart(fig, use_container_width=True)

session.close()
