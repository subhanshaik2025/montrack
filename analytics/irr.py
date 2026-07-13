"""
Money-weighted return (XIRR) for irregular cash flows.

Pure function, no DB/Streamlit imports — takes/returns plain Python + pandas so it can be
unit tested and reused regardless of what sits on top of it.
"""
from datetime import date

import numpy as np
from scipy.optimize import brentq


def xnpv(rate: float, cash_flows: list[tuple[date, float]]) -> float:
    """Net present value of dated cash flows at a given annual rate."""
    t0 = cash_flows[0][0]
    return sum(cf / (1 + rate) ** ((d - t0).days / 365.0) for d, cf in cash_flows)


def xirr(cash_flows: list[tuple[date, float]], low: float = -0.999, high: float = 10.0) -> float:
    """
    Solve for the annualized rate that zeroes the NPV of dated cash flows.

    cash_flows: list of (date, amount) — outflows (contributions/buys) negative,
                inflows (withdrawals/current market value) positive. Must include at least
                one negative and one positive flow, and the final "as-of" market value as a
                positive flow on the valuation date.

    Uses Brent's method (bounded, guaranteed convergence for a sign-changing continuous
    function) rather than plain Newton's method, which can diverge on cash-flow patterns
    with multiple sign changes (e.g. buy -> partial sell -> buy again).
    """
    if len(cash_flows) < 2:
        raise ValueError("xirr requires at least two cash flows")
    cash_flows = sorted(cash_flows, key=lambda cf: cf[0])

    amounts = [cf for _, cf in cash_flows]
    if not (any(a < 0 for a in amounts) and any(a > 0 for a in amounts)):
        raise ValueError("xirr requires at least one inflow and one outflow")

    try:
        return brentq(lambda r: xnpv(r, cash_flows), low, high, maxiter=1000)
    except ValueError as e:
        raise ValueError(
            "xirr did not converge in [-99.9%, 1000%] — check for a sign error "
            "or an implausible cash-flow pattern"
        ) from e


def portfolio_irr(transactions_df, as_of_value: float, as_of_date: date) -> float:
    """
    Convenience wrapper: build the cash-flow list from a transactions DataFrame
    (columns: txn_date, txn_type, amount) and the current portfolio value.

    Buys/deposits into the portfolio are outflows from the investor's pocket (negative);
    sells/withdrawals are inflows (positive); the current market value is the final inflow.
    """
    flows: list[tuple[date, float]] = []
    for _, row in transactions_df.iterrows():
        d = row["txn_date"]
        if row["txn_type"] in ("buy", "deposit"):
            flows.append((d, -abs(float(row["amount"]))))
        elif row["txn_type"] in ("sell", "withdrawal", "dividend"):
            flows.append((d, abs(float(row["amount"]))))
    flows.append((as_of_date, as_of_value))
    return xirr(flows)
