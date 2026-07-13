"""
Time-Weighted Return — strips out the effect of cash-flow timing so it measures strategy/
market performance, not the investor's contribution timing (that's what IRR is for).

Method: Modified Dietz-free approach — break the period into sub-periods at every external
cash-flow date, compute each sub-period's holding-period return off snapshot market values,
then geometrically link the sub-period returns.
"""
import pandas as pd


def sub_period_returns(snapshots: pd.DataFrame, cash_flows: pd.DataFrame) -> pd.Series:
    """
    snapshots: columns [snapshot_date, market_value] — one row per day, portfolio total.
    cash_flows: columns [txn_date, amount] — external flows only (deposits/withdrawals),
                signed +in / -out. Buys/sells *within* the portfolio are NOT external flows.

    Returns a Series of sub-period returns indexed by period-end date.
    """
    snapshots = snapshots.sort_values("snapshot_date").reset_index(drop=True)
    flow_dates = set(cash_flows["txn_date"]) if not cash_flows.empty else set()

    boundaries = sorted(set(snapshots["snapshot_date"]) | flow_dates)
    flows_by_date = cash_flows.groupby("txn_date")["amount"].sum().to_dict() if not cash_flows.empty else {}
    value_by_date = snapshots.set_index("snapshot_date")["market_value"].to_dict()

    returns = {}
    begin_value = None
    begin_date = None
    for d in boundaries:
        end_value = value_by_date.get(d)
        if end_value is None:
            continue
        if begin_value is not None:
            flow = flows_by_date.get(d, 0.0)
            # holding-period return, adjusting the ending value for any flow that occurred on this date
            denom = begin_value
            if denom != 0:
                returns[d] = (end_value - flow - begin_value) / denom
        begin_value = end_value
        begin_date = d
    return pd.Series(returns, name="sub_period_return")


def time_weighted_return(snapshots: pd.DataFrame, cash_flows: pd.DataFrame) -> float:
    """Geometrically link sub-period returns into a single cumulative TWR."""
    r = sub_period_returns(snapshots, cash_flows)
    if r.empty:
        return 0.0
    cumulative = (1 + r).prod() - 1
    return float(cumulative)


def annualize(cumulative_return: float, num_days: int) -> float:
    if num_days <= 0:
        return 0.0
    return float((1 + cumulative_return) ** (365.0 / num_days) - 1)
