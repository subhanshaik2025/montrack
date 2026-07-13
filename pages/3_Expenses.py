from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from analytics.expenses import budget_variance, forecast_month_end_spend
from db.models import Budget, ExpenseCategory, Transaction
from db.session import get_session, init_db

st.set_page_config(page_title="Expenses", page_icon="🧾", layout="wide")
st.title("🧾 Expenses")

init_db()
session = get_session()

txn_df = pd.read_sql(session.query(Transaction).filter(Transaction.txn_type == "expense").statement, session.bind)
cat_df = pd.read_sql(session.query(ExpenseCategory).statement, session.bind)
budget_df = pd.read_sql(session.query(Budget).statement, session.bind)

if txn_df.empty:
    st.warning("No expense data. Run `python3 db/seed.py`.")
    st.stop()

txn_df["txn_date"] = pd.to_datetime(txn_df["txn_date"])
txn_df["amount"] = txn_df["amount"].abs()
cat_lookup = cat_df.set_index("id")["name"]
txn_df["category_name"] = txn_df["category_id"].map(cat_lookup)

today = pd.Timestamp(date.today())
month_start = today.replace(day=1)

# ---- forecast ----
daily_spend = txn_df.set_index("txn_date")["amount"].resample("D").sum()
monthly_spend = txn_df.set_index("txn_date")["amount"].resample("MS").sum()
forecast = forecast_month_end_spend(daily_spend, monthly_spend)

mtd_actual = txn_df[txn_df["txn_date"] >= month_start]["amount"].sum()
current_month = month_start.date()
budget_this_month = budget_df[pd.to_datetime(budget_df["month"]).dt.date == current_month]
budget_total = budget_this_month["target_amount"].sum()

k1, k2, k3 = st.columns(3)
k1.metric("Spent Month-to-Date", f"₹{mtd_actual:,.0f}")
k2.metric(f"Forecast ({forecast['method']})", f"₹{forecast['point_forecast']:,.0f}",
          delta=f"₹{forecast['point_forecast'] - budget_total:,.0f} vs budget")
k3.metric("Monthly Budget", f"₹{budget_total:,.0f}")

st.divider()

# ---- budget variance, sorted by $ overage ----
st.subheader("Budget Variance (sorted by ₹ overage)")
actual_by_cat = txn_df[txn_df["txn_date"] >= month_start].groupby("category_name")["amount"].sum()
# scale each category's MTD actual to a full-month forecast using the same pace ratio as the total
days_elapsed = (today - month_start).days + 1
days_in_month = (month_start + pd.DateOffset(months=1) - pd.Timedelta(days=1)).day
scale = days_in_month / days_elapsed if days_elapsed else 1
forecast_by_cat = (actual_by_cat * scale).reset_index()
forecast_by_cat.columns = ["category_name", "forecast_amount"]

budget_this_month_named = budget_this_month.merge(cat_df, left_on="category_id", right_on="id")[["name", "target_amount"]]
budget_this_month_named.columns = ["category_name", "target_amount"]

variance = budget_variance(forecast_by_cat, budget_this_month_named)
colors = ["#fb7185" if v else "#14b8a6" for v in variance["over_budget"]]
fig = go.Figure(go.Bar(x=variance["variance_amount"], y=variance["category_name"], orientation="h", marker_color=colors))
fig.update_layout(template="plotly_dark", height=350, margin=dict(t=10, b=10), xaxis_title="Variance (₹, +over/-under)")
st.plotly_chart(fig, use_container_width=True)
worst = variance[variance["over_budget"]].head(1)
if not worst.empty:
    row = worst.iloc[0]
    st.warning(f"Biggest overage: **{row['category_name']}** — cut ₹{row['variance_amount']:,.0f} to hit budget.")

st.divider()

# ---- forecast band chart ----
st.subheader("Spend Pace This Month")
mtd_daily = daily_spend[daily_spend.index >= month_start].cumsum()
days = pd.date_range(month_start, month_start + pd.DateOffset(months=1) - pd.Timedelta(days=1))
fig = go.Figure()
fig.add_trace(go.Scatter(x=mtd_daily.index, y=mtd_daily.values, name="Actual (cumulative)", line=dict(color="#14b8a6")))
fig.add_hline(y=budget_total, line_dash="dash", line_color="#fb7185", annotation_text="Budget")
fig.add_hline(y=forecast["point_forecast"], line_dash="dot", line_color="#eab308", annotation_text="Forecast")
fig.update_layout(template="plotly_dark", height=350, margin=dict(t=10, b=10), yaxis_title="Cumulative spend (₹)")
st.plotly_chart(fig, use_container_width=True)

st.divider()

# ---- treemap ----
st.subheader("Category Breakdown")
merged = forecast_by_cat.merge(budget_this_month_named, on="category_name", how="left").fillna(0)
merged["variance_pct"] = (merged["forecast_amount"] - merged["target_amount"]) / merged["target_amount"].replace(0, pd.NA) * 100
fig = px.treemap(merged, path=["category_name"], values="forecast_amount", color="variance_pct",
                  color_continuous_scale="RdYlGn_r", color_continuous_midpoint=0)
fig.update_layout(template="plotly_dark", height=400, margin=dict(t=10, b=10))
st.plotly_chart(fig, use_container_width=True)

st.divider()
st.subheader("Transactions")
show_df = txn_df.sort_values("txn_date", ascending=False).head(100)[["txn_date", "description", "category_name", "amount"]]
edited = st.data_editor(show_df, use_container_width=True, hide_index=True,
                         column_config={"category_name": st.column_config.SelectboxColumn(options=list(cat_lookup))})

session.close()
