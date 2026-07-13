# MonTrack — Architecture

Personal finance portal covering three modules — **Investments**, **Savings**, **Expenses** —
built on a relational schema, a Python analytics layer, and a Streamlit visualization layer.
Designed to be prescriptive (tells you what to do next), not just descriptive (shows you numbers).

## 1. Data Architecture & Schema

Schema lives as SQLAlchemy models in [`db/models.py`](db/models.py) — this is the source of truth
and generates real DDL for either SQLite (used by default, zero setup) or PostgreSQL (swap the
`DATABASE_URL` env var; no code changes needed). Conceptually:

```
accounts            — every account you hold money/assets in (brokerage, bank, wallet, credit card)
asset_metadata       — static info per instrument: ticker, name, asset_class, sector, currency, beta_source
transactions         — the single append-only ledger: buys/sells/deposits/withdrawals/expenses/income
                        this is the ONLY place money movement is recorded — everything else derives from it
portfolio_snapshots  — daily EOD snapshot per holding (qty, price, market_value) — powers TWR/IRR/drift
                        without replaying the whole transaction history every time
budgets              — per-category monthly budget targets, versioned by month so history isn't lost
expense_categories   — hierarchical (parent_id) categorization tree + auto-categorization rules
benchmark_prices     — daily index prices (e.g. NIFTY 50) for beta calculation
ingestion_batches    — audit trail of every CSV/API import: source, row count, status, errors
```

Key design decisions:
- **Transactions are immutable and append-only.** Corrections are new offsetting transactions, never
  edits/deletes. This is what makes IRR/TWR/audit trails trustworthy.
- **`portfolio_snapshots` is a derived/materialized table**, rebuilt nightly from transactions + daily
  prices. Keeps analytics queries fast (no need to replay history on every dashboard load) while
  transactions remain the ground truth.
- **`ingestion_batches`** gives every CSV upload or API pull a batch id, so a bad import can be
  identified and rolled back (delete transactions where `batch_id = X`) without touching anything else.

### Ingestion
- **CSV upload** ([`ingestion/csv_import.py`](ingestion/csv_import.py)): validates schema, dedupes
  against existing transactions (hash of date+account+amount+description), writes an `ingestion_batches`
  row, then inserts.
- **Bank/broker API integration**: same insertion path, different adapter. In India this means Account
  Aggregator (Setu/Finvu/OneMoney) for bank data and broker APIs (Zerodha Kite, Upstox) for holdings —
  both produce the same normalized transaction/holding shape before hitting `csv_import.normalize_and_insert`.
  This is why ingestion is split into "produce a normalized DataFrame" (source-specific) → "insert"
  (source-agnostic): adding a new source never touches the DB layer.

## 2. Core Modules & Analytics

### Investments — [`analytics/twr.py`](analytics/twr.py), [`analytics/irr.py`](analytics/irr.py), [`analytics/risk.py`](analytics/risk.py)

| Metric | Method | Why this one |
|---|---|---|
| **TWR** (Time-Weighted Return) | Geometric linking of sub-period returns, sub-period boundaries at every cash flow date | Measures manager/strategy skill — strips out the effect of *when* you happened to deposit/withdraw money. Use for comparing your portfolio's performance to a benchmark. |
| **IRR / XIRR** | Newton's method on irregularly-dated cash flows (`scipy.optimize.brentq` fallback for non-convergence) | Measures *your* actual money-weighted return — the number that answers "was contributing/withdrawing on the days I did a good idea." Use for personal performance, not strategy comparison. |
| **Allocation drift** | `current_weight - target_weight` per asset class, flagged past a tolerance band (default ±5pp) | Descriptive allocation is useless without a target; drift is what triggers a rebalance action. |
| **Beta** | Covariance(portfolio returns, benchmark returns) / Variance(benchmark returns), rolling 252-day window | Tells you how much of your volatility is market-driven vs. idiosyncratic. |
| **Volatility** | Annualized stdev of daily returns (`σ_daily × √252`) | Standard risk measure, paired with beta to separate systematic/idiosyncratic risk. |

### Savings — [`analytics/savings.py`](analytics/savings.py)

- **Liquidity ratio** = liquid assets (cash + cash-equivalents) / monthly essential expenses.
- **Emergency fund progress** = current emergency-fund balance / (target_months × avg_monthly_expense),
  expressed as % complete, with a projected completion date given current contribution rate.
- **Yield on cash equivalents** = weighted average annualized yield across FDs/savings/liquid funds,
  compared against a CPI benchmark to flag real-return erosion.

### Expenses — [`analytics/expenses.py`](analytics/expenses.py)

- **Categorization engine**: rule table (`expense_categories.match_pattern`, regex on description) applied
  at ingestion time, falling back to a "Manual Review" bucket — every transaction is always categorized,
  never silently dropped.
- **Forecasting**: two interchangeable estimators behind one interface —
  1. **Weighted rolling average** (default, no extra dependency risk): blends the last 3 months' run-rate
     with the current month's pace-to-date, weighted toward recent data.
  2. **ARIMA** (`statsmodels`, used automatically once ≥ 12 months of history exist): captures seasonality
     (e.g. annual insurance premiums, festival-month spending spikes) that a rolling average can't.
- **Budget variance**: forecast vs. budget per category, sorted by $ overage (not % — a 40% overage on a
  ₹500 category matters less than a 10% overage on a ₹50,000 category), which is the prescriptive signal
  ("cut dining out by ₹4,200 to hit target" rather than "you're over budget").

## 3. Technical Blueprint

- **Visualization layer: Streamlit.** Chosen over Dash for faster iteration and native multipage support;
  chosen over a BI tool (Power BI/Tableau) because this needs custom prescriptive logic (IRR solving,
  drift alerts, forecast blending) that's Python-native — a BI tool would need a Python backend anyway,
  so cut the middleman.
- **Structure**: `app.py` is the landing page (cross-module KPIs). `pages/1_Investments.py`,
  `pages/2_Savings.py`, `pages/3_Expenses.py` are Streamlit's file-based multipage routing.
- **Data layer**: SQLAlchemy ORM (`db/models.py`) + a single `db/session.py` engine factory. SQLite file
  by default (`wealth.db`), swap to Postgres via `DATABASE_URL` env var for zero code changes when this
  needs to run on a server instead of a laptop.
- **Analytics layer is pure functions** (`analytics/*.py`) that take/return DataFrames — no Streamlit or
  DB imports inside them. This means every calculation is independently testable and reusable if the
  visualization layer ever changes.

## 4. Premium UI/UX Layout

### Landing page (`app.py`)
Top KPI row (4 cards): **Net Worth**, **MoM change** (▲/▼ with ₹ and %), **This month's IRR (blended)**,
**Liquidity ratio**. Below that: a **waterfall chart** of net worth change over the trailing 6 months
(starting balance → contributions → market gains/losses → withdrawals → ending balance) — this is the
single chart that answers "why did my net worth move" better than any line chart. Below that: a **Sankey
diagram** of last month's cash flow (income sources → spending categories → savings/investment
destinations) — makes where money actually went legible at a glance, which a table of numbers never does.

### Investments module
- Top: allocation donut (actual) next to a **drift bar chart** (actual vs. target per asset class, red/green
  bars past tolerance) — putting them side by side is what makes drift actionable instead of just visible.
- **Heatmap**: assets (rows) × trailing periods 1M/3M/6M/1Y/YTD (columns), color-scaled by return —
  scan-friendly way to spot consistent laggards vs. one-off dips.
- Line chart: portfolio TWR vs. benchmark (e.g. NIFTY 50), cumulative, indexed to 100 at start.
- KPI strip: IRR, TWR, Beta, Annualized Volatility, Sharpe ratio.

### Savings module
- Emergency fund: a **progress ring/gauge** (current / target months), with projected completion date
  as a caption underneath.
- Liquidity ratio trend line, with a shaded "healthy zone" band (e.g. 3–6 months) so the number is
  self-interpreting without needing a legend.
- Table: cash-equivalent instruments, balance, yield %, yield vs. CPI (real yield, colored red if negative).

### Expenses module
- Top: **budget variance bar chart**, categories sorted by ₹ overage descending (prescriptive ordering —
  worst offender first).
- **Forecast band chart**: daily cumulative spend this month (actual, solid line) vs. forecast range
  (shaded band, upper/lower) vs. budget (dashed horizontal line) — answers "am I on pace" visually.
- Category breakdown: treemap (size = ₹ spent, color = variance vs. budget) rather than a pie chart —
  scales to 15+ categories without becoming unreadable.
- Transaction table below, filterable, with the auto-assigned category editable inline (corrections feed
  back into the categorization rule table).

### Visual language
Dark theme by default (reduces eye strain for a dashboard checked daily), one accent color for
positive/growth (teal) and one for negative/risk (coral) used consistently across all three modules —
color meaning shouldn't have to be re-learned per page. Numbers right-aligned, ₹ formatted with Indian
digit grouping (`₹1,23,456`), deltas always signed (+/−) and colored, never color-only (accessibility).

## Setup

```bash
cd ~/wealth-portal
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 db/seed.py        # creates wealth.db and loads demo data
streamlit run app.py
```
