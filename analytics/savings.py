"""Liquidity ratio, emergency-fund progress, cash-equivalent yield — the Savings module metrics."""
from datetime import date

import pandas as pd
from dateutil.relativedelta import relativedelta


def liquidity_ratio(liquid_assets: float, monthly_essential_expense: float) -> float:
    """Months of essential expenses covered by liquid assets. >1 means covered for that many months."""
    if monthly_essential_expense <= 0:
        return float("inf")
    return liquid_assets / monthly_essential_expense


def emergency_fund_progress(
    current_balance: float,
    monthly_essential_expense: float,
    target_months: float = 6.0,
    monthly_contribution: float = 0.0,
) -> dict:
    """
    Returns progress % against target and, if still contributing, a projected completion date —
    the prescriptive part (a bare % doesn't tell you when you'll be done).
    """
    target_amount = target_months * monthly_essential_expense
    progress_pct = min(current_balance / target_amount, 1.0) * 100 if target_amount > 0 else 100.0
    shortfall = max(target_amount - current_balance, 0.0)

    projected_completion = None
    if shortfall > 0 and monthly_contribution > 0:
        months_needed = shortfall / monthly_contribution
        projected_completion = date.today() + relativedelta(months=int(months_needed) + 1)

    return {
        "target_amount": target_amount,
        "current_balance": current_balance,
        "progress_pct": progress_pct,
        "shortfall": shortfall,
        "projected_completion": projected_completion,
    }


def cash_equivalent_yield(instruments: pd.DataFrame, cpi_annual: float = 5.0) -> pd.DataFrame:
    """
    instruments: columns [name, balance, annual_yield_pct]
    Adds weighted contribution and real (inflation-adjusted) yield per instrument, flags
    negative real yield — money quietly losing purchasing power despite a "positive" return.
    """
    df = instruments.copy()
    total = df["balance"].sum()
    df["weight_pct"] = df["balance"] / total * 100 if total > 0 else 0.0
    df["real_yield_pct"] = df["annual_yield_pct"] - cpi_annual
    df["erodes_value"] = df["real_yield_pct"] < 0
    weighted_avg_yield = (df["annual_yield_pct"] * df["weight_pct"] / 100).sum()
    df.attrs["portfolio_weighted_yield_pct"] = weighted_avg_yield
    df.attrs["portfolio_real_yield_pct"] = weighted_avg_yield - cpi_annual
    return df
