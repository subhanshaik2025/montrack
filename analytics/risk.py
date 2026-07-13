"""Allocation drift, beta, volatility, Sharpe — the risk-side metrics for the Investments module."""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def allocation_drift(holdings: pd.DataFrame, targets: pd.DataFrame, tolerance_pp: float = 5.0) -> pd.DataFrame:
    """
    holdings: columns [asset_class, market_value]
    targets:  columns [asset_class, target_weight_pct]

    Returns a DataFrame with actual_weight_pct, target_weight_pct, drift_pp, and a
    breach flag — the prescriptive signal for "rebalance this asset class."
    """
    actual = holdings.groupby("asset_class")["market_value"].sum()
    actual_pct = (actual / actual.sum() * 100).rename("actual_weight_pct")
    merged = targets.set_index("asset_class").join(actual_pct, how="outer").fillna(0.0)
    merged["drift_pp"] = merged["actual_weight_pct"] - merged["target_weight_pct"]
    merged["breach"] = merged["drift_pp"].abs() > tolerance_pp
    return merged.reset_index().rename(columns={"index": "asset_class"})


def daily_returns(prices: pd.Series) -> pd.Series:
    return prices.sort_index().pct_change().dropna()


def beta(portfolio_returns: pd.Series, benchmark_returns: pd.Series, window: int | None = None) -> float:
    """Covariance(portfolio, benchmark) / Variance(benchmark). window=None uses full history;
    pass e.g. 252 for a rolling trailing-year beta."""
    df = pd.concat([portfolio_returns.rename("p"), benchmark_returns.rename("b")], axis=1).dropna()
    if window:
        df = df.tail(window)
    if len(df) < 2 or df["b"].var() == 0:
        return float("nan")
    cov = df["p"].cov(df["b"])
    return float(cov / df["b"].var())


def annualized_volatility(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    return float(returns.std(ddof=1) * np.sqrt(TRADING_DAYS))


def sharpe_ratio(returns: pd.Series, risk_free_annual: float = 0.07) -> float:
    """Default risk-free rate assumes an Indian government T-bill/FD benchmark (~7%)."""
    if returns.empty or returns.std(ddof=1) == 0:
        return 0.0
    rf_daily = (1 + risk_free_annual) ** (1 / TRADING_DAYS) - 1
    excess = returns - rf_daily
    return float(excess.mean() / returns.std(ddof=1) * np.sqrt(TRADING_DAYS))
