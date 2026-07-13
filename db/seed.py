"""Generates realistic demo data so the dashboard isn't empty on first run."""
import hashlib
import random
from datetime import date, timedelta

import numpy as np

from db.models import (
    Account, AssetMetadata, BenchmarkPrice, Budget, ExpenseCategory,
    PortfolioSnapshot, Transaction,
)
from db.session import get_session, init_db

random.seed(42)
np.random.seed(42)


def dedupe_hash(txn_date, account_id, amount, description):
    raw = f"{txn_date}|{account_id}|{amount}|{description}"
    return hashlib.sha256(raw.encode()).hexdigest()


def seed():
    init_db()
    session = get_session()

    if session.query(Account).first():
        print("DB already seeded, skipping. Delete wealth.db to reseed.")
        return

    # --- accounts ---
    brokerage = Account(name="Zerodha", account_type="brokerage", institution="Zerodha", is_liquid=False)
    savings_acct = Account(name="HDFC Savings", account_type="bank", institution="HDFC", is_liquid=True)
    fd = Account(name="SBI Fixed Deposit", account_type="fd", institution="SBI", is_liquid=False)
    credit_card = Account(name="HDFC Credit Card", account_type="credit_card", institution="HDFC", is_liquid=False)
    session.add_all([brokerage, savings_acct, fd, credit_card])
    session.flush()

    # --- asset metadata ---
    assets = [
        AssetMetadata(ticker="NIFTYBEES", name="Nifty 50 ETF", asset_class="equity", target_weight_pct=40),
        AssetMetadata(ticker="INFY", name="Infosys", asset_class="equity", sector="IT", target_weight_pct=15),
        AssetMetadata(ticker="HDFCBANK", name="HDFC Bank", asset_class="equity", sector="Financials", target_weight_pct=15),
        AssetMetadata(ticker="GOLDBEES", name="Gold ETF", asset_class="gold", target_weight_pct=10),
        AssetMetadata(ticker="LIQUIDBEES", name="Liquid Fund", asset_class="debt", target_weight_pct=20),
    ]
    session.add_all(assets)

    # --- expense categories ---
    categories = {
        "Groceries": r"BIGBASKET|ZEPTO|BLINKIT|DMART",
        "Dining": r"SWIGGY|ZOMATO|RESTAURANT|CAFE",
        "Rent": r"RENT|LANDLORD",
        "Utilities": r"ELECTRICITY|BSES|WATER|BROADBAND|AIRTEL|JIO",
        "Transport": r"UBER|OLA|PETROL|FUEL",
        "Entertainment": r"NETFLIX|SPOTIFY|BOOKMYSHOW|PRIME",
        "Shopping": r"AMAZON|FLIPKART|MYNTRA",
        "Insurance": r"LIC|INSURANCE|PREMIUM",
        "Manual Review": r"",
    }
    cat_objs = {}
    for name, pattern in categories.items():
        c = ExpenseCategory(name=name, match_pattern=pattern, is_essential=name in ("Groceries", "Rent", "Utilities", "Transport", "Insurance"))
        session.add(c)
        cat_objs[name] = c
    session.flush()

    # --- budgets for current and last 2 months ---
    budget_targets = {
        "Groceries": 12000, "Dining": 6000, "Rent": 35000, "Utilities": 4000,
        "Transport": 5000, "Entertainment": 1500, "Shopping": 8000, "Insurance": 3000,
    }
    today = date.today()
    for m_offset in range(3):
        month = (today.replace(day=1) - timedelta(days=1)).replace(day=1) if m_offset else today.replace(day=1)
        month = today.replace(day=1)
        for i in range(m_offset):
            prev = month.replace(day=1) - timedelta(days=1)
            month = prev.replace(day=1)
        for cat_name, amt in budget_targets.items():
            session.add(Budget(category_id=cat_objs[cat_name].id, month=month, target_amount=amt))

    # --- 18 months of expense transactions on the credit card / savings ---
    start = today - timedelta(days=18 * 30)
    d = start
    while d <= today:
        for cat_name, base in budget_targets.items():
            if random.random() < 0.85:  # not every category every day
                n_txns = np.random.poisson(0.15)
                for _ in range(n_txns):
                    amt = -abs(np.random.normal(base / 20, base / 60))
                    session.add(Transaction(
                        account_id=credit_card.id, txn_date=d, txn_type="expense",
                        amount=round(amt, 2), category_id=cat_objs[cat_name].id,
                        description=f"{cat_name.upper()} PURCHASE {d.isoformat()}",
                        dedupe_hash=dedupe_hash(d, credit_card.id, amt, f"{cat_name}-{d}"),
                    ))
        # monthly salary
        if d.day == 1:
            session.add(Transaction(
                account_id=savings_acct.id, txn_date=d, txn_type="income", amount=150000,
                description="SALARY CREDIT", dedupe_hash=dedupe_hash(d, savings_acct.id, 150000, "salary"),
            ))
        d += timedelta(days=1)

    # --- investment buy transactions + portfolio snapshots (daily, 18 months) ---
    holdings = {a.ticker: {"qty": 0.0, "base_price": p} for a, p in zip(
        assets, [250, 1500, 1650, 55, 1000]
    )}
    buy_dates = [start + timedelta(days=30 * i) for i in range(18)]
    for bd in buy_dates:
        if bd > today:
            continue
        for a in assets:
            if a.asset_class == "gold" and random.random() > 0.5:
                continue
            price = holdings[a.ticker]["base_price"] * (1 + np.random.normal(0, 0.02))
            invest_amt = {"equity": 8000, "gold": 3000, "debt": 5000}[a.asset_class]
            qty = round(invest_amt / price, 4)
            holdings[a.ticker]["qty"] += qty
            session.add(Transaction(
                account_id=brokerage.id, txn_date=bd, txn_type="buy", ticker=a.ticker,
                quantity=qty, price=round(price, 2), amount=round(qty * price, 2),
                description=f"BUY {a.ticker}",
                dedupe_hash=dedupe_hash(bd, brokerage.id, qty * price, f"buy-{a.ticker}-{bd}"),
            ))

    # daily price walk + snapshots + benchmark
    drift = {"equity": 0.0004, "gold": 0.0002, "debt": 0.0001}
    vol = {"equity": 0.012, "gold": 0.008, "debt": 0.001}
    prices = {a.ticker: holdings[a.ticker]["base_price"] for a in assets}
    qty_running = {a.ticker: 0.0 for a in assets}
    buy_qty_by_date = {}
    for bd in buy_dates:
        buy_qty_by_date.setdefault(bd, {})

    nifty_price = 22000.0
    d = start
    while d <= today:
        for a in assets:
            prices[a.ticker] *= (1 + np.random.normal(drift[a.asset_class], vol[a.asset_class]))
        nifty_price *= (1 + np.random.normal(0.0004, 0.011))
        session.add(BenchmarkPrice(benchmark="NIFTY50", price_date=d, close=round(nifty_price, 2)))

        # accumulate quantity as of this date
        for bd in buy_dates:
            if bd == d:
                for a in assets:
                    qty_running[a.ticker] = holdings[a.ticker]["qty"] if bd == buy_dates[-1] else qty_running[a.ticker]

        if d.weekday() < 5:  # snapshot on weekdays only
            cum_qty = {a.ticker: 0.0 for a in assets}
            for a in assets:
                total_qty = 0.0
                invest_amt = {"equity": 8000, "gold": 3000, "debt": 5000}[a.asset_class]
                for bd in buy_dates:
                    if bd <= d:
                        total_qty += invest_amt / holdings[a.ticker]["base_price"]  # approx, fine for demo
                if total_qty > 0:
                    session.add(PortfolioSnapshot(
                        snapshot_date=d, account_id=brokerage.id, ticker=a.ticker,
                        quantity=round(total_qty, 4), price=round(prices[a.ticker], 2),
                        market_value=round(total_qty * prices[a.ticker], 2),
                    ))
        d += timedelta(days=1)

    session.commit()
    session.close()
    print("Seeded wealth.db with 18 months of demo data.")


if __name__ == "__main__":
    seed()
