"""Landing page: cross-module KPIs, net-worth waterfall, cash-flow Sankey."""
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from db.models import Account, ExpenseCategory, PortfolioSnapshot, Transaction
from db.session import get_session, init_db
from db.seed import seed

st.set_page_config(page_title="MonTrack", page_icon="💎", layout="wide")

PRIMARY   = "#14b8a6"
POSITIVE  = "#10b981"
NEGATIVE  = "#fb7185"
NEUTRAL   = "#64748b"

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding-top: 1.5rem !important; max-width: 1200px; }
.kpi-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 1rem;
    margin-bottom: 1.5rem;
}
.kpi-card {
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 16px;
    padding: 1.25rem 1.5rem;
    position: relative;
    overflow: hidden;
    transition: transform 0.2s, box-shadow 0.2s;
}
.kpi-card:hover { transform: translateY(-2px); box-shadow: 0 8px 32px rgba(0,0,0,0.3); }
.kpi-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 3px;
    background: var(--accent, #14b8a6);
    border-radius: 16px 16px 0 0;
}
.kpi-label { font-size: 0.72rem; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: #94a3b8; margin-bottom: 0.5rem; }
.kpi-value { font-size: 1.75rem; font-weight: 700; color: #f1f5f9; line-height: 1.1; margin-bottom: 0.35rem; }
.kpi-delta { font-size: 0.78rem; font-weight: 500; padding: 2px 8px; border-radius: 999px; display: inline-block; }
.kpi-delta.pos { background: rgba(16,185,129,0.15); color: #10b981; }
.kpi-delta.neg { background: rgba(251,113,133,0.15); color: #fb7185; }
.kpi-delta.neu { background: rgba(100,116,139,0.15); color: #94a3b8; }
.kpi-icon { position: absolute; top: 1rem; right: 1.25rem; font-size: 1.5rem; opacity: 0.25; }
.section-header {
    font-size: 0.72rem; font-weight: 600; letter-spacing: 0.1em;
    text-transform: uppercase; color: #64748b;
    margin: 1.5rem 0 0.75rem;
    display: flex; align-items: center; gap: 0.5rem;
}
.section-header::after { content: ''; flex: 1; height: 1px; background: rgba(255,255,255,0.06); }
@media (max-width: 640px) {
    .kpi-grid { grid-template-columns: 1fr 1fr; gap: 0.75rem; }
    .kpi-value { font-size: 1.35rem; }
    .block-container { padding: 0.75rem !important; }
}
</style>
""", unsafe_allow_html=True)


def inr(x: float) -> str:
    if abs(x) >= 1_00_00_000:
        return f"{'−' if x < 0 else ''}₹{abs(x)/1_00_00_000:.2f}Cr"
    if abs(x) >= 1_00_000:
        return f"{'−' if x < 0 else ''}₹{abs(x)/1_00_000:.1f}L"
    return f"{'−' if x < 0 else ''}₹{abs(x):,.0f}"

def pct(x: float) -> str:
    return f"{'▲' if x >= 0 else '▼'} {abs(x):.1f}%"


init_db()
seed()
session = get_session()

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

month_ago_snap = session.query(PortfolioSnapshot.snapshot_date).filter(
    PortfolioSnapshot.snapshot_date <= latest_snap_date - timedelta(days=30)
).order_by(PortfolioSnapshot.snapshot_date.desc()).first()

mom_change, mom_pct = None, None
if month_ago_snap:
    prev_snap = pd.read_sql(
        session.query(PortfolioSnapshot).filter(PortfolioSnapshot.snapshot_date == month_ago_snap[0]).statement,
        session.bind,
    )
    prev_val = prev_snap["market_value"].sum()
    mom_change = invest_value - prev_val
    mom_pct = (mom_change / prev_val * 100) if prev_val else None

last_90d = txn_df[(txn_df["txn_type"] == "expense") & (txn_df["txn_date"] >= pd.Timestamp(today - timedelta(days=90)))]
monthly_essential = abs(last_90d["amount"].sum()) / 3 if not last_90d.empty else 1

from analytics.savings import liquidity_ratio
liq_ratio = liquidity_ratio(cash_balance, monthly_essential)

last_30d_income  = txn_df[(txn_df["txn_type"] == "income")  & (txn_df["txn_date"] >= pd.Timestamp(today - timedelta(days=30)))]["amount"].sum()
last_30d_expense = abs(txn_df[(txn_df["txn_type"] == "expense") & (txn_df["txn_date"] >= pd.Timestamp(today - timedelta(days=30)))]["amount"].sum())
savings_rate = ((last_30d_income - last_30d_expense) / last_30d_income * 100) if last_30d_income > 0 else 0

col_title, col_date = st.columns([3, 1])
with col_title:
    st.markdown("## 💎 MonTrack")
with col_date:
    st.markdown(f"<p style='text-align:right;color:#64748b;font-size:0.85rem;padding-top:0.6rem'>{today.strftime('%d %b %Y')}</p>", unsafe_allow_html=True)

def kpi_card(label, value, delta=None, delta_type="neu", icon="", accent="#14b8a6"):
    delta_html = f'<span class="kpi-delta {delta_type}">{delta}</span>' if delta else ""
    return f"""<div class="kpi-card" style="--accent:{accent}">
        <div class="kpi-icon">{icon}</div>
        <div class="kpi-label">{label}</div>
        <div class="kpi-value">{value}</div>
        {delta_html}
    </div>"""

mom_delta_type = "pos" if (mom_change or 0) >= 0 else "neg"
liq_type = "pos" if liq_ratio >= 3 else ("neu" if liq_ratio >= 1 else "neg")
sr_type  = "pos" if savings_rate >= 20 else ("neu" if savings_rate >= 10 else "neg")

cards_html = (
    '<div class="kpi-grid">'
    + kpi_card("Net Worth", inr(net_worth), icon="🏦", accent="#14b8a6")
    + kpi_card("Investments", inr(invest_value), delta=(pct(mom_pct) + " MoM") if mom_pct is not None else None, delta_type=mom_delta_type, icon="📈", accent="#6366f1")
    + kpi_card("Cash Balance", inr(cash_balance), icon="💵", accent="#f59e0b")
    + kpi_card("Liquidity Ratio", (str(round(liq_ratio, 1)) + " mo") if liq_ratio != float("inf") else "∞ mo", delta="Healthy ✓" if liq_ratio >= 3 else ("Low ⚠" if liq_ratio < 1 else "OK"), delta_type=liq_type, icon="🛡️", accent="#10b981")
    + kpi_card("Savings Rate", str(round(savings_rate)) + "%", delta="On track ✓" if savings_rate >= 20 else "Below target", delta_type=sr_type, icon="🎯", accent="#8b5cf6")
    + "</div>"
)
st.markdown(cards_html, unsafe_allow_html=True)

st.markdown('<div class="section-header">Net Worth — Trailing 6 Months</div>', unsafe_allow_html=True)

six_mo_ago = today - timedelta(days=180)
snap_hist = pd.read_sql(
    session.query(PortfolioSnapshot).filter(PortfolioSnapshot.snapshot_date >= six_mo_ago).statement,
    session.bind,
)
monthly_invest_value = snap_hist.groupby(pd.to_datetime(snap_hist["snapshot_date"]).dt.to_period("M"))["market_value"].sum()
flows = txn_df[txn_df["txn_date"] >= pd.Timestamp(six_mo_ago)]
buys = flows[flows["txn_type"] == "buy"].groupby(flows["txn_date"].dt.to_period("M"))["amount"].sum()
periods = sorted(set(monthly_invest_value.index) | set(buys.index))

if len(periods) >= 2:
    start_val = monthly_invest_value.get(periods[0], 0)
    labels = ["Start"]
    values = [start_val]
    for p in periods[1:]:
        contrib = buys.get(p, 0)
        market_change = monthly_invest_value.get(p, 0) - monthly_invest_value.get(periods[periods.index(p) - 1], 0) - contrib
        labels += [f"{p}\nContrib", f"{p}\nMarket"]
        values += [contrib, market_change]
    labels.append("Now")
    values.append(monthly_invest_value.get(periods[-1], 0))
    measures = ["absolute"] + ["relative"] * (len(values) - 2) + ["total"]

    fig = go.Figure(go.Waterfall(
        x=labels, y=values, measure=measures,
        increasing={"marker": {"color": POSITIVE}},
        decreasing={"marker": {"color": NEGATIVE}},
        totals={"marker": {"color": PRIMARY}},
        connector={"line": {"color": "rgba(255,255,255,0.1)", "width": 1, "dash": "dot"}},
        texttemplate="%{y:,.0f}", textfont={"size": 11, "color": "#f1f5f9"},
    ))
    fig.update_layout(
        height=360, margin=dict(t=16, b=8, l=8, r=8),
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Inter", "color": "#94a3b8"},
        xaxis={"gridcolor": "rgba(255,255,255,0.04)"},
        yaxis={"gridcolor": "rgba(255,255,255,0.04)", "tickformat": ",.0f", "tickprefix": "₹"},
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Not enough history yet.")

st.markdown('<div class="section-header">Cash Flow — Last Month</div>', unsafe_allow_html=True)

last_month_start = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
last_month_end   = today.replace(day=1) - timedelta(days=1)
lm = txn_df[(txn_df["txn_date"] >= pd.Timestamp(last_month_start)) & (txn_df["txn_date"] <= pd.Timestamp(last_month_end))]

income_total   = lm[lm["txn_type"] == "income"]["amount"].sum()
invest_total   = abs(lm[lm["txn_type"] == "buy"]["amount"].sum())
expense_by_cat = lm[lm["txn_type"] == "expense"].copy()
cat_lookup     = {c.id: c.name for c in session.query(ExpenseCategory).all()}
expense_by_cat["cat_name"] = expense_by_cat["category_id"].map(cat_lookup).fillna("Other")
expense_grouped = expense_by_cat.groupby("cat_name")["amount"].sum().abs()
savings_total   = max(income_total - invest_total - expense_grouped.sum(), 0)

if income_total > 0:
    nodes = ["Income", "Investments", "Savings"] + list(expense_grouped.index)
    node_idx = {n: i for i, n in enumerate(nodes)}
    sources, targets, values = [], [], []
    if invest_total > 0:
        sources.append(node_idx["Income"]); targets.append(node_idx["Investments"]); values.append(invest_total)
    if savings_total > 0:
        sources.append(node_idx["Income"]); targets.append(node_idx["Savings"]); values.append(savings_total)
    for cat, amt in expense_grouped.items():
        sources.append(node_idx["Income"]); targets.append(node_idx[cat]); values.append(amt)

    node_colors = [PRIMARY, "#6366f1", POSITIVE] + [NEGATIVE] * len(expense_grouped)
    link_colors = (["rgba(99,102,241,0.25)"] if invest_total > 0 else []) + \
                  (["rgba(16,185,129,0.25)"] if savings_total > 0 else []) + \
                  ["rgba(251,113,133,0.2)"] * len(expense_grouped)

    fig2 = go.Figure(go.Sankey(
        node=dict(label=nodes, color=node_colors, pad=24, thickness=18, line={"color": "rgba(0,0,0,0)", "width": 0}),
        link=dict(source=sources, target=targets, value=values, color=link_colors),
    ))
    fig2.update_layout(
        height=380, template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Inter", "size": 12, "color": "#94a3b8"},
        margin=dict(t=16, b=8, l=8, r=8),
    )
    st.plotly_chart(fig2, use_container_width=True)
else:
    st.info("Not enough transaction history for a cash-flow view.")

session.close()
st.markdown("<p style='text-align:center;color:#334155;font-size:0.75rem;margin-top:2rem'>MonTrack · Personal Wealth Dashboard</p>", unsafe_allow_html=True)
