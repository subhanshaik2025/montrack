"""Expense categorization engine + forecasting + budget variance — the Expenses module metrics."""
from __future__ import annotations

import re
from datetime import date

import numpy as np
import pandas as pd


def categorize(description: str, rules: pd.DataFrame, fallback: str = "Manual Review") -> str:
    """
    rules: columns [category_name, match_pattern] (match_pattern is a regex, case-insensitive).
    First matching rule wins. Every transaction gets *some* category — never silently dropped,
    which is what makes the categorization engine trustworthy enough to build a budget on top of.
    """
    for _, rule in rules.iterrows():
        pattern = rule["match_pattern"]
        if pattern and re.search(pattern, description, re.IGNORECASE):
            return rule["category_name"]
    return fallback


def _rolling_average_forecast(daily_spend: pd.Series, days_in_month: int, days_elapsed: int) -> tuple[float, float, float]:
    """
    Blends trailing 3-month daily run-rate with this month's pace-to-date, weighted toward
    recent/current data. Returns (point_forecast, lower_band, upper_band).
    """
    month_start = pd.Timestamp(date.today().replace(day=1))
    history = daily_spend[daily_spend.index < month_start]
    trailing_3mo = history[history.index >= month_start - pd.DateOffset(months=3)]
    historical_daily_avg = trailing_3mo.mean() if not trailing_3mo.empty else daily_spend.mean()

    this_month = daily_spend[daily_spend.index >= month_start]
    pace_to_date_daily_avg = this_month.mean() if not this_month.empty else historical_daily_avg

    # weight current pace more heavily as the month progresses (more signal, less noise)
    w = min(days_elapsed / days_in_month, 1.0)
    blended_daily = w * pace_to_date_daily_avg + (1 - w) * historical_daily_avg

    point_forecast = blended_daily * days_in_month
    daily_std = trailing_3mo.std() if len(trailing_3mo) > 1 else blended_daily * 0.15
    band_width = daily_std * np.sqrt(days_in_month) * 1.28  # ~80% interval
    return float(point_forecast), float(max(point_forecast - band_width, 0)), float(point_forecast + band_width)


def _arima_forecast(monthly_spend: pd.Series, days_in_month: int, days_elapsed: int) -> tuple[float, float, float] | None:
    """ARIMA on monthly totals, used once >= 12 months of history exist (needs enough data to
    capture seasonality). Returns None if statsmodels isn't available or history is too short."""
    if len(monthly_spend) < 12:
        return None
    try:
        from statsmodels.tsa.arima.model import ARIMA
    except ImportError:
        return None

    model = ARIMA(monthly_spend, order=(1, 1, 1))
    fit = model.fit()
    forecast = fit.get_forecast(steps=1)
    mean = float(forecast.predicted_mean.iloc[0])
    ci = forecast.conf_int(alpha=0.2)
    lower, upper = float(ci.iloc[0, 0]), float(ci.iloc[0, 1])

    # blend in month-to-date actuals so the forecast isn't blind to what's already happened this month
    mtd_actual = monthly_spend.iloc[-1] if monthly_spend.index[-1].month == date.today().month else 0.0
    if mtd_actual > 0 and days_elapsed > 0:
        pace_projection = mtd_actual / days_elapsed * days_in_month
        w = days_elapsed / days_in_month
        mean = w * pace_projection + (1 - w) * mean
    return mean, max(lower, 0), upper


def forecast_month_end_spend(daily_spend: pd.Series, monthly_spend: pd.Series | None = None) -> dict:
    """
    daily_spend: Series indexed by date, daily total spend (any history length).
    monthly_spend: optional Series indexed by month-start, monthly totals (for ARIMA path).

    Automatically uses ARIMA once enough history exists, otherwise falls back to the
    weighted rolling average — the caller doesn't need to know which estimator ran.
    """
    today = date.today()
    days_in_month = (pd.Timestamp(today.replace(day=1)) + pd.DateOffset(months=1) - pd.Timedelta(days=1)).day
    days_elapsed = today.day

    result = None
    method = "rolling_average"
    if monthly_spend is not None:
        arima_result = _arima_forecast(monthly_spend, days_in_month, days_elapsed)
        if arima_result:
            result = arima_result
            method = "arima"

    if result is None:
        result = _rolling_average_forecast(daily_spend, days_in_month, days_elapsed)

    point, lower, upper = result
    return {"method": method, "point_forecast": point, "lower_band": lower, "upper_band": upper}


def budget_variance(actuals: pd.DataFrame, budgets: pd.DataFrame) -> pd.DataFrame:
    """
    actuals: columns [category_name, forecast_amount]
    budgets: columns [category_name, target_amount]

    Sorted by absolute rupee overage descending — prescriptive ordering (biggest ₹ problem
    first), not % overage, since a 40% miss on a ₹500 category is noise next to a 10% miss
    on a ₹50,000 category.
    """
    df = budgets.merge(actuals, on="category_name", how="outer").fillna(0.0)
    df["variance_amount"] = df["forecast_amount"] - df["target_amount"]
    df["variance_pct"] = np.where(
        df["target_amount"] != 0, df["variance_amount"] / df["target_amount"] * 100, np.nan
    )
    df["over_budget"] = df["variance_amount"] > 0
    return df.sort_values("variance_amount", ascending=False).reset_index(drop=True)
