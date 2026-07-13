# 💎 MonTrack

A personal wealth management dashboard built with Streamlit — covering investments, savings, and expenses in one place. Designed to be **prescriptive** (tells you what to do next), not just descriptive (shows you numbers).

![Python](https://img.shields.io/badge/Python-3.9+-blue) ![Streamlit](https://img.shields.io/badge/Streamlit-1.32+-red) ![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0+-green) ![License](https://img.shields.io/badge/license-MIT-lightgrey)

---

## Features

**Landing Dashboard**
- Net Worth, MoM change, Liquidity Ratio, Cash Balance — at a glance
- 6-month net worth **waterfall chart** (contributions vs. market gains/losses)
- Last-month **cash flow Sankey** (income → investments / expenses / savings)

**Investments Module**
- Allocation donut vs. drift bar chart (actual vs. target per asset class)
- Return heatmap: assets × trailing periods (1M / 3M / 6M / 1Y / YTD)
- Portfolio TWR vs. benchmark line chart (indexed to 100)
- KPIs: IRR, TWR, Beta, Volatility, Sharpe ratio

**Savings Module**
- Emergency fund progress gauge with projected completion date
- Liquidity ratio trend with healthy-zone shading
- Cash equivalent yield table vs. CPI (flags real-return erosion)

**Expenses Module**
- Budget variance bar chart — sorted by ₹ overage (worst offender first)
- Daily cumulative spend vs. forecast band vs. budget line
- Category treemap (size = ₹ spent, color = budget variance)
- Filterable transaction table with inline category correction

---

## Tech Stack

| Layer | Technology |
|---|---|
| UI | Streamlit |
| Database | SQLite (default) / PostgreSQL (via `DATABASE_URL`) |
| ORM | SQLAlchemy 2.0 |
| Analytics | pandas, numpy, scipy, statsmodels |
| Charts | Plotly |

---

## Setup

```bash
git clone https://github.com/subhanshaik2025/montrack.git
cd montrack

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python3 db/seed.py        # creates wealth.db with demo data
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

---

## Project Structure

```
montrack/
├── app.py                  # Landing page (KPIs, waterfall, Sankey)
├── pages/
│   ├── 1_Investments.py    # Portfolio performance & allocation
│   ├── 2_Savings.py        # Emergency fund & liquidity
│   └── 3_Expenses.py       # Budget tracking & forecasting
├── analytics/
│   ├── twr.py              # Time-weighted return (geometric linking)
│   ├── irr.py              # XIRR via Newton's method / Brent fallback
│   ├── risk.py             # Beta, volatility, Sharpe ratio
│   ├── savings.py          # Liquidity ratio, emergency fund progress
│   └── expenses.py         # Categorization, forecasting, budget variance
├── db/
│   ├── models.py           # SQLAlchemy ORM schema (source of truth)
│   ├── session.py          # Engine factory (SQLite ↔ PostgreSQL)
│   └── seed.py             # Demo data seeder
└── ingestion/
    └── csv_import.py       # CSV import with deduplication
```

---

## Data Architecture

The schema is built around a **single append-only transactions ledger** — every money movement lives in one table, nothing else is a source of truth. Key design decisions:

- **Transactions are immutable.** Corrections are new offsetting transactions, never edits. This makes IRR/TWR/audit trails trustworthy.
- **`portfolio_snapshots`** is a derived table rebuilt nightly from transactions + prices — keeps dashboard queries fast without replaying full history every load.
- **`ingestion_batches`** gives every CSV upload a batch ID, so a bad import can be rolled back by deleting `WHERE batch_id = X` without touching anything else.
- **SQLite by default, PostgreSQL with zero code changes** — swap `DATABASE_URL` env var and nothing else changes.

---

## Analytics

| Metric | Method |
|---|---|
| TWR | Geometric linking of sub-period returns at every cash flow date |
| IRR / XIRR | Newton's method, Brent's method fallback for non-convergence |
| Allocation drift | `current_weight − target_weight`, flagged past ±5pp tolerance |
| Beta | Rolling 252-day covariance with benchmark / benchmark variance |
| Expense forecast | Weighted rolling average (< 12 months) → ARIMA (≥ 12 months) |

Analytics functions (`analytics/*.py`) are pure functions that take/return DataFrames — no Streamlit or DB imports inside them, so they're independently testable.

---

## Switching to PostgreSQL

```bash
export DATABASE_URL=postgresql://user:password@localhost:5432/montrack
streamlit run app.py
```

No code changes required.

---

## Roadmap

- [ ] Account Aggregator integration (Setu / Finvu) for automated bank data
- [ ] Zerodha Kite / Upstox API adapter for live holdings
- [ ] Mobile-responsive layout
- [ ] PDF export (monthly statement)
- [ ] Multi-currency support

---

## License

MIT
